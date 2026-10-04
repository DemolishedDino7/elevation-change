"""Data audit: cross-checks this season's results against NCAA.com.

Written to bot/audit.json on every run so problems are visible, not silent.
Checks
  * every final score (both teams, right side) matches NCAA.com
  * every NCAA.com final is in our data, and every one of our finals is on NCAA.com
  * home / away / neutral site agrees
  * FBS vs FCS classification of every team agrees with NCAA.com's division
  * games-played count per FBS team agrees
"""
from __future__ import annotations

import pandas as pd

import ncaa


def run(g: pd.DataFrame, season: int, last_week: int, log=print) -> dict:
    sg = g[(g.season == season) & (g.season_type == "regular")].copy()
    out = {"ok": False, "weeks": list(range(1, last_week + 1)), "score_mismatch": [], "missing_in_ours": [],
           "missing_on_ncaa": [], "home_away": [], "division": [], "games_played": [], "checked": 0}
    try:
        contests, div_of = [], {}
        for w in range(1, last_week + 1):
            for d in ncaa.DIVISIONS:
                data = ncaa._get(ncaa.Q_SCOREBOARD, {"sportCode": "MFB", "division": d, "seasonYear": season,
                                                     "contestDate": None, "week": w})
                for c in (data.get("data") or {}).get("contests") or []:
                    contests.append(c)
                    # a team's division: FCS-vs-FCS games only appear on the FCS board
                    if d == 12 and all(t.get("conferenceSeo") for t in c["teams"]):
                        for t in c["teams"]:
                            div_of.setdefault(t["seoname"], set()).add(12)
                    if d == 11:
                        for t in c["teams"]:
                            div_of.setdefault(t["seoname"], set()).add(11)
        uniq = {c["contestId"]: c for c in contests}
        finals = [c for c in uniq.values() if c.get("gameState") == "F" and len(c.get("teams", [])) == 2]
        pairs = ncaa.match(finals, sg)
        matched_rows = set()
        for idx, m in pairs:
            matched_rows.add(idx)
            r = sg.loc[idx]
            h, a = m["home"], m["away"]
            label = f"Wk {int(r.week)}: {r.away_team} at {r.home_team}"
            out["checked"] += 1
            if not r.completed:
                out["missing_in_ours"].append(f"{label} — NCAA final {a.get('score')}-{h.get('score')}, not final in our data")
                continue
            if int(r.home_points) != int(h.get("score")) or int(r.away_points) != int(a.get("score")):
                out["score_mismatch"].append(f"{label}: ours {int(r.away_points)}-{int(r.home_points)}, NCAA {a.get('score')}-{h.get('score')}")
            if m["flip"] and not r.neutral_site:
                out["home_away"].append(f"{label}: NCAA lists {r.home_team} as the visitor")
        matched_ids = {m["contest"]["contestId"] for _, m in pairs}
        for c in finals:
            if c["contestId"] in matched_ids:
                continue
            names = [t["nameShort"] for t in c["teams"]]
            # only care about games involving an FBS team
            if any(11 in div_of.get(t["seoname"], set()) and 12 not in div_of.get(t["seoname"], set()) for t in c["teams"]):
                out["missing_in_ours"].append(f"NCAA final not in our data: {' vs '.join(names)} ({c.get('startDate')})")
        done = sg[sg.completed & (sg.week <= last_week)]
        for idx, r in done.iterrows():
            if idx not in matched_rows and ("fbs" in (r.home_division, r.away_division)):
                out["missing_on_ncaa"].append(f"Wk {int(r.week)}: {r.away_team} {int(r.away_points)} at {r.home_team} {int(r.home_points)}")
        # division check, via the matched pairs
        for idx, m in pairs:
            r = sg.loc[idx]
            for side in ("home", "away"):
                seo = m[side]["seoname"]
                ncaa_div = "fcs" if div_of.get(seo) == {12} else ("fbs" if div_of.get(seo) == {11} else None)
                ours = r[f"{side}_division"]
                if ncaa_div and ours != ncaa_div:
                    out["division"].append(f"{r[f'{side}_team']}: ours {ours.upper()}, NCAA {ncaa_div.upper()}")
        out["division"] = sorted(set(out["division"]))
        # games played per FBS team
        ours_n, ncaa_n = {}, {}
        for _, r in done.iterrows():
            for side in ("home", "away"):
                if r[f"{side}_division"] == "fbs":
                    ours_n[r[f"{side}_team"]] = ours_n.get(r[f"{side}_team"], 0) + 1
        for idx, m in pairs:
            r = sg.loc[idx]
            for side in ("home", "away"):
                if r[f"{side}_division"] == "fbs":
                    ncaa_n[r[f"{side}_team"]] = ncaa_n.get(r[f"{side}_team"], 0) + 1
        for t in sorted(set(ours_n) | set(ncaa_n)):
            if ours_n.get(t, 0) != ncaa_n.get(t, 0):
                out["games_played"].append(f"{t}: ours {ours_n.get(t, 0)}, matched to NCAA {ncaa_n.get(t, 0)}")
        out["ok"] = True
        issues = sum(len(out[k]) for k in ("score_mismatch", "missing_in_ours", "missing_on_ncaa", "home_away", "division", "games_played"))
        log(f"audit: {out['checked']} games checked against NCAA.com, {issues} issue(s)")
    except Exception as e:
        out["error"] = repr(e)[:300]
        log("audit unavailable:", out["error"])
    return out
