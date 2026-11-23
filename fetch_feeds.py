import json, sys, re, html, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

# De namen moeten exact overeenkomen met de lijst KRANTEN in index.html
FEEDS = [
 ("VRT NWS", "https://www.vrt.be/vrtnws/nl.rss.articles.xml"),
 ("Het Laatste Nieuws", "https://www.hln.be/home/rss.xml"),
 ("De Standaard", "https://www.standaard.be/rss/section/1f2838d4-99ea-49f0-9102-138784c7ea7c"),
 ("Het Nieuwsblad", "https://www.nieuwsblad.be/rss/section/55178e67-15a8-4ddd-a3d8-bfe5708f8932"),
 ("De Morgen", "https://www.demorgen.be/in-het-nieuws/rss.xml"),
 ("De Tijd", "https://www.tijd.be/rss/top_stories.xml"),
 ("Gazet van Antwerpen", "https://www.gva.be/rss/section/ca750cdf-3d1e-4621-90ef-a3260118e21c"),
 ("Het Belang van Limburg", "https://www.hbvl.be/rss/section/D1618839-F921-43CC-AF6A-A2B200A962DC"),
 ("Knack", "https://www.knack.be/feed/"),
 ("Bruzz", "https://www.bruzz.be/rss.xml"),
 ("Newsmonkey", "https://newsmonkey.be/feed/"),
 ("Apache", "https://apache.be/feed/artikels/nieuws"),
 ("Sporza (sport)", "https://sporza.be/nl.rss.xml"),
 ("HLN Sport", "https://www.hln.be/sport/rss.xml"),
]

# Kranten van Mediahuis (De Standaard, Nieuwsblad, GVA, HBVL, De Tijd) blokkeren
# servers zoals die van GitHub. Lukt hun eigen feed niet, dan halen we hun koppen
# van de voorbije 24 uur via Google Nieuws (alleen titel, tijd en link).
RESERVE = {
 "De Standaard": "standaard.be",
 "Het Nieuwsblad": "nieuwsblad.be",
 "De Tijd": "tijd.be",
 "Gazet van Antwerpen": "gva.be",
 "Het Belang van Limburg": "hbvl.be",
}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"

def haal(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.7",
        "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.6",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def name(tag): return tag.rsplit("}", 1)[-1]

def parse_date(s):
    if not s: return None
    try: d = parsedate_to_datetime(s)
    except Exception:
        try: d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception: return None
    if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
    return d.isoformat()

def pick_link(links):
    # Kies de link naar het gewone artikel (webpagina), niet naar de feed zelf
    best = None
    for c in links:
        href = (c.get("href") or c.text or "").strip()
        if href.startswith("//"): href = "https:" + href
        if not href.startswith("http"): continue
        rel = c.get("rel", "alternate")
        typ = c.get("type", "")
        if rel == "alternate" and (not typ or "html" in typ) and not href.endswith(".xml"):
            return href
        if best is None and rel != "self" and not href.endswith(".xml"):
            best = href
    return best

MAX_TEKST = 350  # enkel een kort voorproefje, nooit het volledige artikel

def kort(raw):
    t = html.unescape(re.sub(r"<[^>]+>", " ", raw or ""))
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > MAX_TEKST:
        cut = t[:MAX_TEKST]
        punt = cut.rfind(". ")
        t = cut[:punt + 1] if punt > 150 else cut[:cut.rfind(" ")] + "..."
    return t

def https(u):
    u = (u or "").strip()
    if u.startswith("//"): u = "https:" + u
    return u if u.startswith("https://") or u.startswith("http://") else ""

def items(xml):
    out = []
    for el in ET.fromstring(xml).iter():
        if name(el.tag) not in ("item", "entry"): continue
        t = d = None
        links = []
        tekst = {}
        beeld = ""
        for c in el:
            n = name(c.tag)
            if n == "title": t = "".join(c.itertext()).strip()
            elif n == "link": links.append(c)
            elif "mrss" in c.tag and n in ("content", "thumbnail", "group"):
                if not beeld:
                    kand = [c] + list(c)
                    for g in kand:
                        if name(g.tag) in ("content", "thumbnail") and g.get("url") and (g.get("medium", "image") == "image" or "image" in g.get("type", "")):
                            beeld = https(g.get("url")); break
            elif n in ("description", "summary", "content", "encoded"):
                tekst.setdefault(n, "".join(c.itertext()))
            elif n == "enclosure" and not beeld:
                u = c.get("url") or ""
                typ = c.get("type", "") + c.get("medium", "")
                if u and (n == "thumbnail" or "image" in typ or re.search(r"\.(jpe?g|png|webp)(\?|$)", u, re.I)):
                    beeld = https(u)
            elif n == "group" and not beeld:
                for g in c:
                    if name(g.tag) in ("content", "thumbnail") and g.get("url"):
                        beeld = https(g.get("url")); break
            elif n in ("pubDate", "published", "updated", "date") and not d:
                d = parse_date((c.text or "").strip())
        l = pick_link(links)
        if not beeld:
            for c in links:
                if c.get("rel") == "enclosure" and "image" in c.get("type", "image"):
                    beeld = https(c.get("href")); break
        ruw = tekst.get("description") or tekst.get("summary") or tekst.get("content") or tekst.get("encoded") or ""
        if not beeld:
            for v in [ruw] + list(tekst.values()):
                m = re.search(r'<img[^>]+src="([^"]+)"', v or "")
                if m: beeld = https(html.unescape(m.group(1))); break
        if t and l and l.startswith("http"):
            out.append({"t": t, "l": l, "d": d, "x": kort(ruw), "i": beeld})
    out.sort(key=lambda x: x["d"] or "", reverse=True)
    return out[:80]

def google(site):
    url = f"https://news.google.com/rss/search?q=site:{site}+when:1d&hl=nl&gl=BE&ceid=BE:nl"
    it = items(haal(url))
    for i in it:
        # Google zet " - GVA" of " - De Standaard" achter elke titel
        i["t"] = re.sub(r"\s+-\s+[^-]{2,40}$", "", i["t"]).strip()
        i["x"] = ""
    return it

# Laatste redmiddel voor Mediahuis: de voorpagina van dekrantenkoppen.be lezen.
# We nemen enkel titel, korte samenvatting en de link naar de krant zelf.
DKK_URL = "https://www.dekrantenkoppen.be/"
_dkk = None
def dkk_pagina():
    global _dkk
    if _dkk is None:
        try:
            _dkk = haal(DKK_URL).decode("utf-8", "replace")
            print(f"dekrantenkoppen.be gelezen ({len(_dkk)} tekens)")
        except Exception as e:
            _dkk = ""
            print(f"dekrantenkoppen.be niet bereikbaar: {type(e).__name__}: {e}")
    return _dkk

def attr(tag, naam):
    m = re.search(naam + r'\s*=\s*"([^"]*)"', tag) or re.search(naam + r"\s*=\s*'([^']*)'", tag)
    return html.unescape(m.group(1)) if m else ""

def dkk(n, site):
    pagina = dkk_pagina()
    out, gezien, laatste = [], set(), None
    for m in re.finditer(r"(<a\s[^>]*>)(.*?)</a>", pagina, re.S | re.I):
        tag, tekst = m.group(1), m.group(2)
        titel = attr(tag, "title")
        if titel.startswith("Meer details over:"):
            if laatste is not None and not laatste["x"]:
                laatste["x"] = kort(titel.split(":", 1)[1].strip())
            continue
        laatste = None
        if titel.strip() != f"Lees het artikel op {n}":
            continue
        href = attr(tag, "href")
        if "dekrantenkoppen" in urllib.parse.urlparse(href).netloc:
            q = re.search(r"[?&](?:url|u|link|to)=([^&]+)", href)
            href = urllib.parse.unquote(q.group(1)) if q else ""
        # Alleen links die rechtstreeks naar de krant gaan, nooit via hun site
        if site not in urllib.parse.urlparse(href).netloc:
            continue
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", tekst))).strip()
        if not t or not href.startswith("http") or href in gezien:
            continue
        gezien.add(href)
        laatste = {"t": t, "l": href, "d": "", "x": "", "i": ""}
        out.append(laatste)
    return out

def sleutel(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())[:60]

# Doorgeefluiken: publieke diensten die een feed voor ons ophalen vanaf een ander netwerk.
RELAIS = [
    lambda u: "https://api.allorigins.win/raw?url=" + urllib.parse.quote(u, safe=""),
    lambda u: "https://corsproxy.io/?url=" + urllib.parse.quote(u, safe=""),
    lambda u: "https://api.codetabs.com/v1/proxy?quest=" + u,
]

def mediahuis(n, url, site):
    """Probeer alle wegen na elkaar; geef (items, via, fouten) terug."""
    fouten = []
    try:
        it = items(haal(url))
        if it: return it, "eigen feed", fouten
        fouten.append("eigen feed: leeg")
    except Exception as e:
        fouten.append(f"eigen feed: {type(e).__name__}")
    for r in RELAIS:
        naam = r("x").split("/")[2]
        try:
            it = items(haal(r(url), timeout=15))
            if it: return it, f"eigen feed via {naam}", fouten
            fouten.append(f"{naam}: leeg")
        except Exception as e:
            fouten.append(f"{naam}: {type(e).__name__}")
    # Eerst Google Nieuws; dekrantenkoppen.be vult enkel aan met koppen die nog ontbreken.
    it, via = [], []
    try:
        it = google(site)
        if it: via.append(f"Google Nieuws ({len(it)})")
        else: fouten.append("Google Nieuws: leeg")
    except Exception as e:
        fouten.append(f"Google Nieuws: {type(e).__name__}")
    try:
        bekend = {sleutel(i["t"]) for i in it}
        extra = [i for i in dkk(n, site) if sleutel(i["t"]) not in bekend]
        if extra:
            via.append(f"aangevuld met dekrantenkoppen.be ({len(extra)})")
            it = it + extra
    except Exception as e:
        fouten.append(f"dekrantenkoppen.be: {type(e).__name__}")
    return it, " + ".join(via), fouten

# Vangnet: de koppen van de vorige keer, voor het geval alles tijdelijk faalt.
VORIGE = {}
try:
    oud = json.loads(haal("https://verbeeckorama.github.io/nieuws/headlines.json"))
    for f in oud.get("feeds", []):
        if f.get("items"): VORIGE[f["n"]] = f["items"]
    print(f"Vorige koppen geladen voor {len(VORIGE)} kranten")
except Exception as e:
    print(f"Geen vorige koppen: {type(e).__name__}")

result = []
for n, url in FEEDS:
    it, via, fouten = [], "", []
    if n in RESERVE:
        it, via, fouten = mediahuis(n, url, RESERVE[n])
    else:
        try:
            it = items(haal(url)); via = "eigen feed"
        except Exception as e:
            fouten.append(f"{type(e).__name__}: {e}")
    if it:
        # Koppen zonder tijd: neem de tijd van de vorige keer, anders "nu"
        oud_d = {i["l"]: i.get("d") for i in VORIGE.get(n, [])}
        nu = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for i in it:
            if not i.get("d"): i["d"] = oud_d.get(i["l"]) or nu
        it.sort(key=lambda x: x["d"] or "", reverse=True)
    if not it and VORIGE.get(n):
        it, via = VORIGE[n], "vorige keer (bewaard)"
    if it:
        result.append({"n": n, "via": via, "items": it})
        print(f"OK   {n}: {len(it)} koppen via {via}" + (f"  [{'; '.join(fouten)}]" if fouten else ""))
    else:
        result.append({"n": n, "err": ("; ".join(fouten) or "leeg")[:160]})
        print(f"FOUT {n}: {'; '.join(fouten) or 'geen koppen'}")

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump({"updated": datetime.now(timezone.utc).isoformat(), "feeds": result}, f, ensure_ascii=False)
