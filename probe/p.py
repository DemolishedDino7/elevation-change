import json, sys, urllib.request, urllib.parse
sys.path.insert(0, "model/hoops")
import espn
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
out = {}
for t in (167, 2250, 2439, 57, 2534):
    try:
        js = espn._get(f"/apis/site/v2/sports/basketball/mens-college-basketball/teams/{t}", tries=1)
        tm = js.get("team", {})
        out[str(t)] = {"links": [(l.get("text"), l.get("href")) for l in tm.get("links", [])], "keys": list(tm.keys())}
    except Exception as e:
        out[str(t)] = repr(e)[:200]
    try:
        js = espn._get(f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball/teams/{t}", tries=1)
        out[str(t) + "_core"] = {"links": [(l.get("text"), l.get("href")) for l in js.get("links", [])]}
    except Exception as e:
        out[str(t) + "_core"] = repr(e)[:200]
q = "https://en.wikipedia.org/w/api.php?action=parse&prop=wikitext&format=json&redirects=1&page=" + urllib.parse.quote("New Mexico Lobos men's basketball")
req = urllib.request.Request(q, headers={"User-Agent": "ElevationChangeBot/1.0 (elevationchange.co)"})
w = json.loads(urllib.request.urlopen(req, timeout=30).read())["parse"]["wikitext"]["*"]
out["wiki"] = [l for l in w.split("\n") if "website" in l.lower()][:5]
json.dump(out, open("probe/out.json", "w"), indent=1)
