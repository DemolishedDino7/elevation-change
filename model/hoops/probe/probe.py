"""Temporary probe (removed after use): rosters and exhibition results reachable from GitHub Actions."""
import json, sys, urllib.request, gzip
sys.path.insert(0, "model/hoops")
import espn
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
out = {}
def raw(u):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf8", "replace")
# 1) ESPN rosters for a few of our teams
for t in (167, 2253, 2440, 2439, 2751, 2006):
    try:
        js = espn._get(f"/apis/site/v2/sports/basketball/mens-college-basketball/teams/{t}/roster", tries=1)
        ath = js.get("athletes") or []
        if ath and isinstance(ath[0], dict) and "items" in ath[0]:
            ath = [a for g in ath for a in g.get("items", [])]
        out[f"espn_roster_{t}"] = {"season": (js.get("season") or {}).get("year"), "n": len(ath),
                                   "names": [a.get("displayName") for a in ath][:20],
                                   "exp": [((a.get("experience") or {}).get("displayValue")) for a in ath][:20]}
    except Exception as e:
        out[f"espn_roster_{t}"] = repr(e)[:200]
# 2) school sites (Sidearm)
for name, u in [("unm", "https://golobos.com/sports/mens-basketball/roster"), ("unlv", "https://unlvrebels.com/sports/mens-basketball/roster"),
                ("afa", "https://goairforcefalcons.com/sports/mens-basketball/roster"), ("nevada", "https://nevadawolfpack.com/sports/mens-basketball/roster")]:
    try:
        h = raw(u); out["site_" + name] = {"len": len(h), "has_roster": "sidearm-roster-player" in h or "s-person-card" in h, "head": h[:200]}
        open(f"model/hoops/probe/{name}.html.gz", "wb").write(gzip.compress(h.encode()))
    except Exception as e:
        out["site_" + name] = repr(e)[:200]
# 3) exhibitions: ESPN scoreboard Oct 1-19, all of D-I and without group filter
ex = []
for d in range(1, 20):
    day = f"202610{d:02d}"
    for grp in ("&groups=50", ""):
        try:
            js = espn._get(f"/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates={day}&limit=500{grp}", tries=1)
            for ev in js.get("events", []):
                c = ev["competitions"][0]
                ex.append({"day": day, "grp": grp, "id": ev["id"], "name": ev.get("name"), "stype": (ev.get("season") or {}).get("type"),
                           "slug": (ev.get("season") or {}).get("slug"), "state": ev["status"]["type"]["state"],
                           "teams": [(x["team"].get("id"), x["team"].get("location"), x.get("score")) for x in c["competitors"]],
                           "notes": [n.get("headline") for n in c.get("notes", [])]})
        except Exception as e:
            ex.append({"day": day, "grp": grp, "err": repr(e)[:120]})
out["scoreboard"] = ex
json.dump(out, open("model/hoops/probe/out.json", "w"), indent=1)
print("done", len(ex))
