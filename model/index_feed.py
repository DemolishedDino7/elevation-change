"""Feeds the Elevation Index from our own data.

Writes ei-auto.js: every tracked team's games and box-score stats (computed
from the play-by-play), the strength of every opponent (from The Bot's
ratings, FCS included), each team's next game and the current week.
Nothing in it is typed in by hand or taken from ESPN, the AP poll or any
other ranking.
"""
from __future__ import annotations

import json
from datetime import timedelta

import numpy as np
import pandas as pd

import ncaa
import plays


def site_week(start: pd.Series, week: pd.Series) -> pd.Series:
    """Elevation Change numbers the late-August opener weekend Week 0."""
    local = start - pd.Timedelta(hours=6)
    wk1 = local[week == 1]
    if not len(wk1):
        return week
    cutoff = wk1.max() - pd.Timedelta(days=4)
    return np.where((week == 1) & (local < cutoff), 0, week)


def build(season: int, sg: pd.DataFrame, T: pd.DataFrame, west: dict, out_path, ncaa_ids: dict | None = None,
          teams_js: str = "", scope_js: str = "", pregame: dict | None = None,
          rank_by_week: dict | None = None, scale: dict | None = None) -> dict:
    """
    sg:   this season's games (from data.build_games)
    T:    team ratings (team_id, name, div, net, rank) for every team in the season
    west: site id -> data name for the tracked teams
    """
    by_name = {v: k for k, v in west.items()}
    T = T.copy()
    fbs = T[T["div"] == "fbs"].sort_values("net", ascending=False)
    fbs_nets = fbs.net.to_numpy()
    natrank = dict(zip(fbs.name, range(1, len(fbs) + 1)))
    fcs = T[T["div"] != "fbs"].sort_values("net", ascending=False)
    fcs_rank = dict(zip(fcs.name, range(1, len(fcs) + 1)))

    def equiv(net):  # where a team with this rating would rank in FBS
        return int(1 + (fbs_nets > net).sum())

    g = sg.copy()
    g["sw"] = site_week(g.start, g.week)
    tracked = g[g.home_team.isin(by_name) | g.away_team.isin(by_name)]
    done = tracked[tracked.completed]

    box = plays.box_scores(season).set_index(["game_id", "team"])

    ncaa_ids = ncaa_ids or {}
    src = {"ncaa": 0, "pbp": 0}

    def official(gid, team_is_home):
        """Official NCAA team box score, if we have it."""
        m = ncaa_ids.get(gid)
        if not m:
            return None
        try:
            ts = ncaa.team_stats(m["contest"])
        except Exception:
            return None
        if not ts:
            return None
        mine, theirs = (m["home_seo"], m["away_seo"]) if team_is_home else (m["away_seo"], m["home_seo"])
        if mine not in ts or theirs not in ts:
            return None
        return ts[mine], ts[theirs]

    def stats(gid, team, opp, is_home):
        off = official(gid, is_home)
        if off:
            a, b = off
            s = {"yds": int(a["yds"]), "oppYds": int(b["yds"]),
                 "to": int(a["fum_lost"] + a["ints"]), "oppTo": int(b["fum_lost"] + b["ints"]),
                 "sacks": int(a["sacks"]), "sacksAllowed": int(b["sacks"])}
            if a["plays"] and b["plays"]:
                s["ypp"], s["oppYpp"] = round(a["yds"] / a["plays"], 1), round(b["yds"] / b["plays"], 1)
            if a["third_att"]:
                s["thirdPct"] = int(round(100 * a["third_conv"] / a["third_att"]))
            if b["third_att"]:
                s["oppThirdPct"] = int(round(100 * b["third_conv"] / b["third_att"]))
            if (gid, team) in box.index and (gid, opp) in box.index:  # explosive plays only exist in play-by-play
                s["explosive"], s["oppExplosive"] = int(box.loc[(gid, team)].explosive), int(box.loc[(gid, opp)].explosive)
            src["ncaa"] += 1
            return s
        if (gid, team) not in box.index or (gid, opp) not in box.index:
            return None
        src["pbp"] += 1
        a, b = box.loc[(gid, team)], box.loc[(gid, opp)]
        s = {"yds": int(a.yds), "oppYds": int(b.yds), "ypp": round(float(a.ypp), 1), "oppYpp": round(float(b.ypp), 1),
             "explosive": int(a.explosive), "oppExplosive": int(b.explosive),
             "to": int(a.to), "oppTo": int(b.to), "sacks": int(b.sacked), "sacksAllowed": int(a.sacked)}
        if a.third_att:
            s["thirdPct"] = int(round(100 * a.third_conv / a.third_att))
        if b.third_att:
            s["oppThirdPct"] = int(round(100 * b.third_conv / b.third_att))
        return s

    games, opps = [], {}
    for _, x in done.sort_values("start").iterrows():
        for side, other in (("home", "away"), ("away", "home")):
            name = x[f"{side}_team"]
            if name not in by_name:
                continue
            oname = x[f"{other}_team"]
            opp = by_name.get(oname, oname)
            if oname not in by_name and oname not in opps and scale is not None:
                # one ranking scale for everyone (e.g. the FCS Index: FBS teams sit where they'd rank among FCS)
                opps[oname] = {"natRank": int(scale.get(oname, len(scale) + 1)), "fcs": False}
            if oname not in by_name and oname not in opps:
                row = T[T.name == oname]
                if len(row) and row["div"].iat[0] == "fbs":
                    opps[oname] = {"natRank": natrank.get(oname, 100), "fcs": False}
                else:
                    net = float(row.net.iat[0]) if len(row) else -25.0
                    eq = equiv(net)
                    fr = fcs_rank.get(oname)
                    o = {"fcs": True, "equivRank": eq, "strong": eq <= 110}
                    if fr and fr <= 25 and eq <= 128:
                        o["fcsRank"] = fr
                    opps[oname] = o
            rec = {"team": by_name[name], "week": int(x.sw),
                   "date": (x.start - timedelta(hours=6)).strftime("%Y-%m-%d"), "opp": opp,
                   "site": "N" if x.neutral_site else ("H" if side == "home" else "A"),
                   "pf": int(x[f"{side}_points"]), "pa": int(x[f"{other}_points"])}
            pm = (pregame or {}).get(int(x.game_id))
            if pm is not None:  # the Bot's pre-game margin, from this team's side
                rec["exp"] = round(pm if side == "home" else -pm, 1)
            st = stats(int(x.game_id), name, oname, side == "home")
            if st:
                rec["stats"] = st
            games.append(rec)

    # next game for each tracked team
    nxt = {}
    pending = tracked[~tracked.completed].sort_values("start")
    cur_week = int(done.sw.max()) if len(done) else 0
    for sid, name in west.items():
        pg = pending[(pending.home_team == name) | (pending.away_team == name)]
        if not len(pg):
            nxt[sid] = "Season complete"
            continue
        x = pg.iloc[0]
        if int(x.sw) > cur_week + 1:
            nxt[sid] = "Bye"
            continue
        home = x.home_team == name
        oname = x.away_team if home else x.home_team
        nxt[sid] = ("vs " if home or x.neutral_site else "at ") + oname

    rank_src = scale if scale is not None else natrank
    bot_rank = {sid: rank_src.get(name) for sid, name in west.items() if rank_src.get(name)}
    js = ("/* ===================================================================\n"
          "   ELEVATION INDEX — AUTOMATIC DATA (generated by model/run.py)\n"
          "   Do not edit by hand: it is rebuilt after every run of The Bot.\n"
          "   Games and scores come from the public results archive and NCAA.com;\n"
          "   box-score stats are NCAA official team stats (explosive plays from\n"
          "   play-by-play); opponent strength is The\n"
          "   Bot's current national rank (FCS teams are placed where their\n"
          "   rating would rank among FBS teams).\n"
          "   =================================================================== */\n"
          + teams_js + scope_js +
          f"const BOT_NATRANK = {json.dumps(bot_rank)};\n"
          + (f"const RANK_BY_WEEK = {json.dumps(rank_by_week, ensure_ascii=False, separators=(',', ':'))};\n" if rank_by_week else "") +
          f"const OPPONENTS = {json.dumps(opps, ensure_ascii=False, indent=1)};\n"
          f"const GAMES = {json.dumps(games, ensure_ascii=False, separators=(',', ':')).replace('},{', '},\n{')};\n"
          f"const NEXT = {json.dumps(nxt, ensure_ascii=False, indent=1)};\n"
          f"const CURRENT_WEEK = {cur_week};\n")
    with open(out_path, "w") as f:
        f.write(js)
    return {"games": len(games), "with_stats": sum("stats" in g_ for g_ in games), "stats_source": src, "opponents": len(opps), "week": cur_week}


def build_national(season: int, sg: pd.DataFrame, T: pd.DataFrame, tinfo: pd.DataFrame, west: dict, out_path,
                   ncaa_ids: dict | None = None, pregame: dict | None = None, rank_by_week: dict | None = None) -> dict:
    """The Elevation Index résumé rules applied to every FBS team (ei-national.js)."""
    west_by_name = {v: k for k, v in west.items()}
    fbs = T[T["div"] == "fbs"].sort_values("net", ascending=False).reset_index(drop=True)
    ids, rows, used = {}, [], set()
    for i, r in fbs.iterrows():
        name = r["name"]
        tid = int(r.team_id)
        sid = west_by_name.get(name)
        if not sid:
            ab = str(tinfo.abbreviation.get(tid) or "").upper().replace(" ", "")
            sid = ab if ab and ab not in used and ab not in west else f"T{tid}"
        used.add(sid)
        ids[sid] = name
        logo = f"logos/{sid}.png" if name in west_by_name else str(tinfo.logo.get(tid) or "")
        color = str(tinfo.color.get(tid) or "#8B6BB8")
        if not color.startswith("#") or len(color) not in (4, 7):
            color = "#8B6BB8"
        rows.append([sid, name, r.conf or "", color, i + 1, logo])
    teams_js = "const TEAMS = " + json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("],[", "],\n[") + ";\n"
    scope_js = 'const EI_SCOPE = "nationally";\nvar IMPROVE = (typeof IMPROVE !== "undefined") ? IMPROVE : {};\n'
    return build(season, sg, T, ids, out_path, ncaa_ids, teams_js=teams_js, scope_js=scope_js, pregame=pregame,
                 rank_by_week=rank_by_week)


def build_fcs(season: int, sg: pd.DataFrame, T: pd.DataFrame, tinfo: pd.DataFrame, out_path,
              ncaa_ids: dict | None = None, pregame: dict | None = None, rank_by_week: dict | None = None) -> dict:
    """The Elevation Index résumé rules applied to every FCS team (ei-fcs.js).
    Everything is on an FCS scale: FCS teams 1..N by rating, FBS opponents placed where they'd rank among FCS."""
    fcs = T[T["div"] == "fcs"].sort_values("net", ascending=False).reset_index(drop=True)
    nets = fcs.net.to_numpy()
    scale = {r["name"]: i + 1 for i, r in fcs.iterrows()}
    for _, r in T[T["div"] == "fbs"].iterrows():
        scale[r["name"]] = int(1 + (nets > r.net).sum())
    ids, rows, used = {}, [], set()
    for i, r in fcs.iterrows():
        tid = int(r.team_id)
        ab = str(tinfo.abbreviation.get(tid) or "").upper().replace(" ", "")
        sid = ab if ab and ab not in used else f"T{tid}"
        used.add(sid)
        ids[sid] = r["name"]
        color = str(tinfo.color.get(tid) or "#8B6BB8")
        if not color.startswith("#") or len(color) not in (4, 7):
            color = "#8B6BB8"
        rows.append([sid, r["name"], r.conf or "", color, i + 1, str(tinfo.logo.get(tid) or "")])
    teams_js = "const TEAMS = " + json.dumps(rows, ensure_ascii=False, separators=(",", ":")).replace("],[", "],\n[") + ";\n"
    scope_js = 'const EI_SCOPE = "in the FCS";\nvar IMPROVE = (typeof IMPROVE !== "undefined") ? IMPROVE : {};\n'
    return build(season, sg, T, ids, out_path, ncaa_ids, teams_js=teams_js, scope_js=scope_js, pregame=pregame,
                 rank_by_week=rank_by_week, scale=scale)
