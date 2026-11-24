import json, sys, re, html, subprocess, urllib.request, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone

# De namen moeten exact overeenkomen met de lijst KRANTEN in index.html.
#
# Mediahuis (De Standaard, Het Nieuwsblad, Gazet van Antwerpen, Het Belang
# van Limburg) zet titel, korte tekst, foto en link in de openbare feed
# https://www.<krant>/rss/. De oude adressen /rss/section/<uuid> sturen door
# naar een loginmuur of antwoorden 403. De artikelpagina zelf zit achter
# Cloudflare; de feed niet. We halen dus alleen die feed op, nooit de
# volledige tekst.
#
# De Tijd is Mediafin, geen Mediahuis. /rss/top_stories.xml bestaat niet meer
# (404). /rss/nieuws.xml geeft titel, tekst en link, maar geen foto per artikel,
# en de artikelpagina is vanaf een server geblokkeerd. Geen aggregator.
FEEDS = [
 ("VRT NWS", "https://www.vrt.be/vrtnws/nl.rss.articles.xml"),
 ("Het Laatste Nieuws", "https://www.hln.be/home/rss.xml"),
 ("De Standaard", "https://www.standaard.be/rss/"),
 ("Het Nieuwsblad", "https://www.nieuwsblad.be/rss/"),
 ("De Morgen", "https://www.demorgen.be/in-het-nieuws/rss.xml"),
 ("De Tijd", "https://www.tijd.be/rss/nieuws.xml"),
 ("Gazet van Antwerpen", "https://www.gva.be/rss/"),
 ("Het Belang van Limburg", "https://www.hbvl.be/rss/"),
 ("Knack", "https://www.knack.be/feed/"),
 ("Bruzz", "https://www.bruzz.be/rss.xml"),
 ("Newsmonkey", "https://newsmonkey.be/feed/"),
 ("Apache", "https://apache.be/feed/artikels/nieuws"),
 ("Sporza (sport)", "https://sporza.be/nl.rss.xml"),
 ("HLN Sport", "https://www.hln.be/sport/rss.xml"),
 # Geen RSS. De nieuwspagina laadt een openbare lijst (titel, intro, foto, link).
 ("Gemeente Brecht", "https://www.brecht.be/nieuws"),
]

# Gemeentenieuws verschijnt een paar keer per week. Langer dan een dag bewaren,
# anders is de lijst bijna altijd leeg. Drie maanden is nog actueel (werken, oproepen).
BRECHT_DAGEN = 90

# Eerlijke feedlezer. Lukt dat niet (Cloudflare-muur), dan een gewone browser.
UA_FEED = "Mozilla/5.0 (compatible; Nieuwslezer/1.0; +https://verbeeckorama.github.io/nieuws/)"
UA_BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, application/json;q=0.8, text/xml;q=0.8, */*;q=0.7"

def is_feed(data):
    head = (data or b"").lstrip()
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:].lstrip()
    low = head[:400].lower()
    return low.startswith((b"<?xml", b"<rss", b"<feed", b"<rdf")) or low.startswith(b"{")

def haal_python(url, timeout, ua):
    req = urllib.request.Request(url, headers={
        "User-Agent": ua,
        "Accept": ACCEPT,
        "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.6",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def haal_curl(url, timeout, ua):
    # curl heeft een TLS-vingerafdruk die Cloudflare wel doorlaat,
    # in tegenstelling tot urllib op sommige Mediahuis-paden.
    p = subprocess.run(
        ["curl", "-fsSL", "--compressed", "--max-redirs", "5",
         "--max-time", str(timeout),
         "-A", ua,
         "-H", "Accept: " + ACCEPT,
         "-H", "Accept-Language: nl-BE,nl;q=0.9,en;q=0.6",
         "-H", "Cache-Control: no-cache",
         url],
        capture_output=True, timeout=timeout + 5,
    )
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(err[-1][:180] if err else f"curl exit {p.returncode}")
    return p.stdout

def haal_ruw(url, timeout=20):
    """Bytes, ook als het gewone HTML is (de nieuwspagina van Brecht)."""
    laatste = None
    for naam, fn, ua in (
        ("python", haal_python, UA_FEED),
        ("curl", haal_curl, UA_BROWSER),
    ):
        try:
            return fn(url, timeout, ua)
        except Exception as e:
            laatste = RuntimeError(f"{naam}: {type(e).__name__}: {e}")
    raise laatste or RuntimeError("leeg")

def haal(url, timeout=20):
    """Bytes van een feed of van headlines.json. HTML-muur telt als mislukking."""
    laatste = None
    for naam, fn, ua in (
        ("python", haal_python, UA_FEED),
        ("curl", haal_curl, UA_BROWSER),
    ):
        try:
            data = fn(url, timeout, ua)
        except Exception as e:
            laatste = RuntimeError(f"{naam}: {type(e).__name__}: {e}")
            continue
        if is_feed(data):
            return data
        laatste = RuntimeError(f"{naam}: geen feed")
    raise laatste or RuntimeError("leeg")

def brecht(pagina_url):
    """Titel, korte intro, foto en link. Nooit de volledige artikeltekst."""
    pagina = haal_ruw(pagina_url).decode("utf-8", "replace")
    bid = re.search(r'blueprintId\s*=\s*"([^"]+)"', pagina)
    blk = re.search(r'data-block-id="([^"]+)"[^>]*data-block-type="news-tiles"', pagina)
    if not (bid and blk):
        raise RuntimeError("nieuwspagina zonder lijst")
    basis = "https://www.brecht.be/ajax-id/block/%s/%s" % (bid.group(1), blk.group(1))
    grens = datetime.now(timezone.utc) - timedelta(days=BRECHT_DAGEN)
    out, gezien = [], set()
    for page in range(1, 5):
        url = basis if page == 1 else basis + "?page=%d" % page
        data = json.loads(haal(url))
        pubs = data.get("publications") or []
        if not pubs:
            break
        te_oud = False
        for p in pubs:
            if not p.get("published"):
                continue
            titel = re.sub(r"\s+", " ", p.get("title") or "").strip()
            link = (p.get("href") or "").strip()
            if not titel or not link.startswith("http") or link in gezien:
                continue
            d = parse_date(p.get("createdAt") or "")
            dt = datetime.fromisoformat(d) if d else None
            if dt is not None and dt < grens:
                te_oud = True
                continue
            gezien.add(link)
            # intro is de korte tekst op de lijst; body is het hele artikel en blijft weg
            out.append({"t": titel, "l": link, "d": d, "x": kort(p.get("intro") or ""), "i": https(p.get("img") or "")})
        if te_oud or page >= len((data.get("pager") or {}).get("pages") or []):
            break
    out.sort(key=lambda x: x["d"] or "", reverse=True)
    return out

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
        bijschrift = ""
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
                if not bijschrift and n == "content":
                    bijschrift = "".join(c.itertext())
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
        # Sommige Mediahuis-items hebben geen description, wel een fotobijschrift.
        # Trefwoordlijsten ("themabeeld, thema, ...") laten we liggen.
        if not kort(ruw) and bijschrift:
            cap = " ".join(bijschrift.split())
            laag = cap.lower()
            if (len(cap) >= 40 and laag.count(",") < 4
                    and "themabeeld" not in laag and "themafoto" not in laag):
                ruw = cap
        if not beeld:
            for v in [ruw] + list(tekst.values()):
                m = re.search(r'<img[^>]+src="([^"]+)"', v or "")
                if m: beeld = https(html.unescape(m.group(1))); break
        if t and l and l.startswith("http"):
            out.append({"t": t, "l": l, "d": d, "x": kort(ruw), "i": beeld})
    # Dezelfde kop kan twee keer in een feed staan (liveblog).
    gezien, uniek = set(), []
    for i in out:
        if i["l"] in gezien: continue
        gezien.add(i["l"])
        uniek.append(i)
    uniek.sort(key=lambda x: x["d"] or "", reverse=True)
    return uniek[:80]

# Vangnet: de koppen van de vorige keer, voor het geval een feed tijdelijk faalt.
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
    try:
        if n == "Gemeente Brecht":
            it, via = brecht(url), "nieuwspagina"
        else:
            it, via = items(haal(url)), "eigen feed"
        if not it:
            fouten.append("leeg")
    except Exception as e:
        fouten.append(f"{e}")
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
        nt = sum(1 for i in it if i.get("x"))
        nb = sum(1 for i in it if i.get("i"))
        extra = f"  [{'; '.join(fouten)}]" if fouten else ""
        print(f"OK   {n}: {len(it)} koppen via {via} ({nt} met tekst, {nb} met beeld){extra}")
    else:
        result.append({"n": n, "err": ("; ".join(fouten) or "leeg")[:160]})
        print(f"FOUT {n}: {'; '.join(fouten) or 'geen koppen'}")

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump({"updated": datetime.now(timezone.utc).isoformat(), "feeds": result}, f, ensure_ascii=False)
