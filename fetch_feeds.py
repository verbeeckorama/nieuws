import json, sys, urllib.request, xml.etree.ElementTree as ET
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

def items(xml):
    out = []
    for el in ET.fromstring(xml).iter():
        if name(el.tag) not in ("item", "entry"): continue
        t = l = d = None
        for c in el:
            n = name(c.tag)
            if n == "title": t = "".join(c.itertext()).strip()
            elif n == "link" and not l: l = (c.get("href") or c.text or "").strip()
            elif n in ("pubDate", "published", "updated", "date") and not d:
                d = parse_date((c.text or "").strip())
        if t and l and l.startswith("http"):
            out.append({"t": t, "l": l, "d": d})
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
