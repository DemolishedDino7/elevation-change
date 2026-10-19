"""Temporary: second pass for teams whose schedule page wasn't found."""
import gzip, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path
import pandas as pd
sys.path.insert(0, "model/hoops")
import data
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
WUA = "ElevationChangeBot/1.0 (https://elevationchange.co; schedule lookup)"
P = Path("probe/pages")
out = json.load(open("probe/out.json"))
names = {}
for y in (2026, 2027):
    s = pd.read_parquet(data.CACHE / f"sch_{y}.parquet")
    for side in ("home", "away"):
        for i, d in zip(s[f"{side}_id"], s[f"{side}_display_name"]):
            names[str(int(i))] = d

def jget(u):
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": WUA}), timeout=30).read())

def raw(u):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.geturl(), r.read().decode("utf8", "replace")

def dom_of(s):
    m = re.search(r"(?:https?://)?(?:www\.)?([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)", s or "")
    return m.group(1).lower() if m else None

def candidates(title):
    out_ = []
    try:
        d = jget("https://en.wikipedia.org/w/api.php?action=parse&prop=wikitext|properties&format=json&redirects=1&page=" + urllib.parse.quote(title)).get("parse")
    except Exception:
        d = None
    if not d:
        return out_
    w = d["wikitext"]["*"]
    for m in re.finditer(r"^\s*\|\s*(?:website|url)\s*=\s*(.+)$", w, re.M):
        dd = dom_of(re.sub(r"\{\{URL\|", "", m.group(1)))
        if dd: out_.append(dd)
    for m in re.finditer(r"\{\{Official website\|(?:1=)?([^}|]+)", w):
        dd = dom_of(m.group(1))
        if dd: out_.append(dd)
    qid = next((p["*"] for p in d.get("properties", []) if p.get("name") == "wikibase_item"), None)
    if qid:
        try:
            for c in jget(f"https://www.wikidata.org/w/api.php?action=wbgetclaims&entity={qid}&property=P856&format=json").get("claims", {}).get("P856", []):
                dd = dom_of(c["mainsnak"]["datavalue"]["value"])
                if dd: out_.append(dd)
        except Exception:
            pass
    return out_

PATHS = ["/sports/mens-basketball/schedule", "/sports/mens-basketball/schedule/", "/sports/mbball/schedule/", "/sports/mbball/schedule", "/sports/mens-basketball/schedule/2026-27",
         "/sports/m-baskbl/sched/", "/sports/mbasketball/schedule", "/sports/mbb/schedule", "/schedule.aspx?path=mbball"]

def good(final, h):
    return ("basketball" in final.lower() or "mbball" in final.lower() or "mbb" in final.lower() or "baskbl" in final.lower()) and "chedule" in h and len(h) > 20000

def try_domain(dom):
    for p in PATHS:
        try:
            final, h = raw("https://" + dom + p)
            if good(final, h):
                return final, h
        except Exception:
            pass
    try:   # homepage: follow a men's basketball schedule link
        final, h = raw("https://" + dom + "/")
        for m in re.finditer(r'href="([^"]+)"', h):
            u = m.group(1)
            if re.search(r"(mens-basketball|mbball|m-baskbl|mbb)", u, re.I) and "sched" in u.lower():
                u = urllib.parse.urljoin(final, u)
                f2, h2 = raw(u)
                if good(f2, h2):
                    return f2, h2
    except Exception:
        pass
    return None, None

HAND = {"UCLA Bruins": "uclabruins.com", "UC Riverside Highlanders": "gohighlanders.com", "Jacksonville State Gamecocks": "jaxstatesports.com",
 "Georgia Tech Yellow Jackets": "ramblinwreck.com", "Bradley Braves": "bradleybraves.com", "Notre Dame Fighting Irish": "fightingirish.com",
 "Louisville Cardinals": "gocards.com", "LSU Tigers": "lsusports.net", "Michigan State Spartans": "msuspartans.com", "Wake Forest Demon Deacons": "godeacs.com",
 "Fairleigh Dickinson Knights": "fduknights.com", "St. Bonaventure Bonnies": "gobonnies.sbu.edu", "Miami (OH) RedHawks": "miamiredhawks.com",
 "Oklahoma State Cowboys": "okstate.com", "Penn State Nittany Lions": "gopsusports.com", "Baylor Bears": "baylorbears.com", "Richmond Spiders": "richmondspiders.com",
 "Marshall Thundering Herd": "herdzone.com", "West Virginia Mountaineers": "wvusports.com", "Indiana State Sycamores": "gosycamores.com",
 "UT Rio Grande Valley Vaqueros": "goutrgv.com", "Jacksonville Dolphins": "judolphins.com", "UC Irvine Anteaters": "ucirvinesports.com",
 "Evansville Purple Aces": "gopurpleaces.com", "Army Black Knights": "goarmywestpoint.com", "UAlbany Great Danes": "ualbanysports.com",
 "App State Mountaineers": "appstatesports.com", "Central Arkansas Bears": "ucasports.com", "Central Connecticut Blue Devils": "ccsubluedevils.com",
 "Dayton Flyers": "daytonflyers.com", "Drake Bulldogs": "godrakebulldogs.com", "Grand Canyon Lopes": "gculopes.com", "High Point Panthers": "highpointpanthers.com",
 "Houston Christian Huskies": "hcuhuskies.com", "Miami Hurricanes": "miamihurricanes.com", "Northern Arizona Lumberjacks": "nauathletics.com",
 "Purdue Boilermakers": "purduesports.com", "San Francisco Dons": "usfdons.com", "SE Louisiana Lions": "lionsports.net", "Seattle U Redhawks": "goseattleu.com",
 "South Carolina Gamecocks": "gamecocksonline.com", "Tennessee Tech Golden Eagles": "ttusports.com", "St. Thomas Tommies": "tommiesports.com",
 "Long Island University Sharks": "liuathletics.com"}
todo = json.load(open("probe/retry.json"))
print("retrying", len(todo))
for k in todo:
    disp = out[k].get("disp") or names.get(k) or k
    cands = [HAND[disp]] if disp in HAND else []
    for title in ([] if disp in HAND else (disp, disp + " men's basketball", re.sub(r"\s+\S+$", "", disp) + " athletics")):
        cands += [c for c in candidates(title) if c not in cands]
        if cands:
            break
    if disp in HAND:
        cands = [HAND[disp]] + [c for c in cands if c != HAND[disp]]
    rec = {"disp": disp, "cands": cands}
    for c in cands:
        final, h = try_domain(c)
        if final:
            rec.update({"domain": c, "url": final, "len": len(h), "exh": h.lower().count("exhib")})
            (P / f"{k}.html.gz").write_bytes(gzip.compress(h.encode()))
            break
    out[k] = rec
    time.sleep(0.2)
json.dump(out, open("probe/out.json", "w"), indent=1)
print("pages now", sum(1 for r in out.values() if r.get("url")))
