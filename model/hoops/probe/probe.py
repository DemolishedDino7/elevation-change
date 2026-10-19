"""Temporary probe (removed after use)."""
import json, sys, time, collections
sys.path.insert(0, "model/hoops")
import espn, data
out = {}
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
# 2) past exhibitions on ESPN's scoreboard
ex = []
for day in ("20251025", "20251101", "20251104", "20241026", "20241102", "20231104"):
    for q in ("&groups=50", "", "&seasontype=1", "&groups=50&seasontype=1"):
        try:
            js = espn._get(f"/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates={day}&limit=500{q}", tries=1)
            evs = js.get("events", [])
            st = collections.Counter(((e.get("season") or {}).get("type"), (e.get("season") or {}).get("slug")) for e in evs)
            exh = [e.get("name") + " | " + "; ".join(n.get("headline", "") for n in e["competitions"][0].get("notes", [])) for e in evs
                   if (e.get("season") or {}).get("type") == 1 or any("xhib" in (n.get("headline") or "") for n in e["competitions"][0].get("notes", []))]
            ex.append({"day": day, "q": q, "n": len(evs), "types": {str(k): v for k, v in st.items()}, "exh": exh[:6], "n_exh": len(exh)})
        except Exception as e:
            ex.append({"day": day, "q": q, "err": repr(e)[:120]})
out["exhibitions"] = ex
json.dump(out, open("model/hoops/probe/out.json", "w"), indent=1)
print("done")
