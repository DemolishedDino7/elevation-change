"""Temporary probe (removed after use)."""
import json, sys, time, collections
sys.path.insert(0, "model/hoops")
import espn, data
out = {}
data.download(2027)
# 1) the Bot's roster download, team by team, with errors kept
ids = sorted(data.d1_teams(2027, 2027))
res, errs = {}, collections.Counter()
for t in ids:
    try:
        js = espn._get(f"/apis/site/v2/sports/basketball/mens-college-basketball/teams/{int(t)}/roster", tries=1)
        ath = js.get("athletes") or []
        if ath and isinstance(ath[0], dict) and "items" in ath[0]:
            ath = [a for g in ath for a in g.get("items", [])]
        res[str(t)] = {"ids": [int(a["id"]) for a in ath if a.get("id")], "season": (js.get("season") or {}).get("year")}
    except Exception as e:
        errs[repr(e)[:80]] += 1
    time.sleep(0.15)
out["rosters"] = {"teams": len(ids), "ok": len(res), "errors": errs.most_common(5)}
json.dump({"season": 2027, "teams": {k: v["ids"] for k, v in res.items()}}, open("model/hoops/probe/ro_live_probe.json", "w"))
json.dump(out, open("model/hoops/probe/out.json", "w"), indent=1)
print("done")
