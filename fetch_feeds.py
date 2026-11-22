import json, sys, re, html, urllib.request, xml.etree.ElementTree as ET
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
 ("Apache", "https://www.apache.be/feed"),
 ("Sporza (sport)", "https://sporza.be/nl.rss.xml"),
 ("HLN Sport", "https://www.hln.be/sport/rss.xml"),
]

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
    return out[:30]

result = []
for n, url in FEEDS:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (nieuws-voor-papa)"})
        with urllib.request.urlopen(req, timeout=20) as r:
            result.append({"n": n, "items": items(r.read())})
        print(f"OK   {n}: {len(result[-1]['items'])} koppen")
    except Exception as e:
        result.append({"n": n, "err": type(e).__name__})
        print(f"FOUT {n}: {e}")

with open(sys.argv[1], "w", encoding="utf-8") as f:
    json.dump({"updated": datetime.now(timezone.utc).isoformat(), "feeds": result}, f, ensure_ascii=False)
