"""Temporary: official athletics site + schedule page for every D-I team."""
import gzip, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, "model/hoops")
import espn, data
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
WUA = "ElevationChangeBot/1.0 (https://elevationchange.co; schedule lookup)"
P = Path("probe/pages"); P.mkdir(parents=True, exist_ok=True)

def jget(u, ua=WUA):
    req = urllib.request.Request(u, headers={"User-Agent": ua})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

def raw(u):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.geturl(), r.read().decode("utf8", "replace")

teams = {}
js = espn._get("/apis/site/v2/sports/basketball/mens-college-basketball/teams?groups=50&limit=500", tries=2)
for t in js["sports"][0]["leagues"][0]["teams"]:
    t = t["team"]; teams[int(t["id"])] = {"loc": t.get("location"), "name": t.get("name"), "disp": t.get("displayName")}
d1 = data.d1_teams(2027, 2027) if (data.CACHE / "sch_2027.parquet").exists() else set(teams)
print("espn teams", len(teams), "d1", len(d1))

def site_from_wiki(title):
    u = "https://en.wikipedia.org/w/api.php?action=parse&prop=wikitext|properties&format=json&redirects=1&page=" + urllib.parse.quote(title)
    d = jget(u).get("parse")
    if not d:
        return None, None
    w = d["wikitext"]["*"]
    m = re.search(r"\|\s*website\s*=\s*(?:\{\{URL\|)?\[?(https?://)?([A-Za-z0-9.\-]+\.[a-z]{2,})", w)
    if m:
        return m.group(2).lower(), "wiki"
    m = re.search(r"\{\{Official website\|(?:1=)?(https?://)?([A-Za-z0-9.\-]+\.[a-z]{2,})", w)
    if m:
        return m.group(2).lower(), "wiki"
    qid = next((p["*"] for p in d.get("properties", []) if p.get("name") == "wikibase_item"), None)
    if qid:
        c = jget(f"https://www.wikidata.org/w/api.php?action=wbgetclaims&entity={qid}&property=P856&format=json").get("claims", {}).get("P856", [])
        if c:
            v = c[0]["mainsnak"]["datavalue"]["value"]
            return re.sub(r"^https?://(www\.)?", "", v).split("/")[0].lower(), "wikidata"
    return None, None

out = {}
for tid in sorted(d1):
    t = teams.get(tid)
    if not t:
        out[tid] = {"err": "not in ESPN team list"}; continue
    dom, src = None, None
    for title in (f"{t['disp']}", f"{t['disp']} men's basketball"):
        try:
            dom, src = site_from_wiki(title)
        except Exception as e:
            dom = None
        if dom:
            break
    rec = {"disp": t["disp"], "domain": dom, "src": src}
    if dom:
        dom = dom.replace("www.", "")
        for path in ("/sports/mens-basketball/schedule", "/sports/mbball/schedule", "/sports/m-baskbl/sched", "/sports/mens-basketball/schedule/"):
            try:
                final, h = raw("https://" + dom + path)
                rec.update({"url": final, "len": len(h), "exh": h.lower().count("exhib")})
                (P / f"{tid}.html.gz").write_bytes(gzip.compress(h.encode()))
                break
            except Exception as e:
                rec["err"] = repr(e)[:90]
    out[tid] = rec
    time.sleep(0.3)
json.dump(out, open("probe/out.json", "w"), indent=1)
ok = sum(1 for r in out.values() if r.get("url"))
print("domains", sum(1 for r in out.values() if r.get("domain")), "pages", ok)
