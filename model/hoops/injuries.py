"""Injuries and absences: what a missing player costs, and who's missing.

Player value. Each player's production per game from the box score (Game Score:
points, shooting, rebounds, assists, steals, blocks, turnovers, fouls), measured
against what a bench replacement produces in the same minutes. One number per
player, in "production per game above replacement".

What it costs. Calibrated on five seasons: in every game where a regular sat out,
how far the team fell short of the Bot's pregame expectation (which was built on
games he mostly played). Points of margin per unit of missing value.

Who's missing, best source first:
  1. hoops/injuries.json  — entered by hand (writers know our 23 best)
  2. ESPN's injury report for the game (status Out / Doubtful / Questionable)
  3. the box scores: a regular who missed the team's last games
The Bot's ratings already include games a player missed, so the adjustment is the
difference between how often he's been out so far and his chance of playing tonight
(a player returning from injury moves a team up, not just a player going down).
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
COLS = ["game_id", "athlete_id", "athlete_display_name", "team_id", "minutes", "points", "field_goals_made",
        "field_goals_attempted", "free_throws_made", "free_throws_attempted", "offensive_rebounds",
        "defensive_rebounds", "assists", "steals", "blocks", "turnovers", "fouls", "did_not_play", "game_date"]
REG_MPG = 18.0        # a "regular": at least this many minutes per game when he plays...
REG_SHARE = 0.6       # ...and in at least this share of his team's games so far
REP_PER40 = 4.0       # Game Score per 40 minutes of a bench replacement
P_STATUS = {"out": 0.97, "doubtful": 0.8, "questionable": 0.5, "day-to-day": 0.35, "probable": 0.15, "available": 0.0}


def load_box(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLS)
    p = pd.read_parquet(path, columns=[c for c in COLS if c != "game_date"] + ["game_date"])
    for c in COLS[4:17]:
        p[c] = pd.to_numeric(p[c], errors="coerce").fillna(0.0)
    p["game_date"] = pd.to_datetime(p.game_date, errors="coerce")
    p["athlete_id"] = pd.to_numeric(p.athlete_id, errors="coerce")
    p = p.dropna(subset=["athlete_id"])
    p["athlete_id"] = p.athlete_id.astype("int64")
    p["team_id"] = pd.to_numeric(p.team_id, errors="coerce").astype("int64")
    p["game_id"] = pd.to_numeric(p.game_id, errors="coerce").astype("int64")
    p["played"] = (~p.did_not_play.fillna(False).astype(bool)) & (p.minutes > 0)
    p["gs"] = (p.points + 0.4 * p.field_goals_made - 0.7 * p.field_goals_attempted
               - 0.4 * (p.free_throws_attempted - p.free_throws_made) + 0.7 * p.offensive_rebounds
               + 0.3 * p.defensive_rebounds + p.steals + 0.7 * p.assists + 0.7 * p.blocks - 0.4 * p.fouls - p.turnovers)
    return p


def values(p: pd.DataFrame, team_games: pd.DataFrame) -> pd.DataFrame:
    """Season-to-date value of every player on every team (from the games in p).
    team_games: team_id -> games played (n)."""
    pl = p[p.played]
    a = pl.groupby(["team_id", "athlete_id"]).agg(name=("athlete_display_name", "last"), gp=("game_id", "nunique"),
                                                  mins=("minutes", "sum"), gs=("gs", "sum"), pts=("points", "sum"),
                                                  reb=("defensive_rebounds", "sum"), oreb=("offensive_rebounds", "sum"), ast=("assists", "sum"))
    a["ppg"], a["rpg"], a["apg"] = a.pts / a.gp, (a.reb + a.oreb) / a.gp, a.ast / a.gp
    a = a.join(team_games.rename("tg"), on="team_id")
    a["mpg"] = a.mins / a.gp
    a["v"] = (a.gs - REP_PER40 * a.mins / 40) / a.gp  # production per game he plays, above a replacement
    a["share"] = a.gp / a.tg
    a["regular"] = (a.mpg >= REG_MPG) & (a.share >= REG_SHARE) & (a.gp >= 3)
    return a.reset_index()


def calibrate(seasons: dict, wf: pd.DataFrame, log=print) -> float:
    """Points of margin per unit of missing value, from games where regulars sat out.
    seasons: season -> box DataFrame; wf: walk-forward games with residual (margin - pred_margin)."""
    xs, ys = [], []
    for y, p in seasons.items():
        if p.empty:
            continue
        gd = p[["game_id", "game_date"]].drop_duplicates("game_id").sort_values("game_date")
        order = {g: i for i, g in enumerate(gd.game_id)}
        pp = p[p.played].assign(o=p.game_id.map(order))
        rows = {k_: list(zip(x.athlete_id, x.minutes, x.gs)) for k_, x in pp.groupby(["team_id", "game_id"])}
        tgames = p.assign(o=p.game_id.map(order)).drop_duplicates(["team_id", "game_id"]).sort_values("o")
        miss_val = {}  # (game, team) -> value missing (weighted by how often the ratings had him)
        for team, games in tgames.groupby("team_id"):
            stats, n = {}, 0  # athlete -> [gp, mins, gs]
            for gid in games.game_id:
                here = rows.get((team, gid), [])
                ids = {a_ for a_, _, _ in here}
                if n >= 5:
                    lost = 0.0
                    for a_, (gp_, mins_, gs_) in stats.items():
                        if a_ in ids:
                            continue
                        if mins_ / gp_ >= REG_MPG and gp_ / n >= REG_SHARE:
                            lost += (gs_ - REP_PER40 * mins_ / 40) / gp_ * (gp_ / n)
                    miss_val[(gid, team)] = lost
                for a_, mi, g_ in here:
                    st_ = stats.setdefault(a_, [0, 0.0, 0.0])
                    st_[0] += 1; st_[1] += mi; st_[2] += g_
                n += 1
        w = wf[wf.season == y]
        for _, r in w.iterrows():
            h, a = miss_val.get((r.game_id, r.home_id)), miss_val.get((r.game_id, r.away_id))
            if h is None or a is None:
                continue
            xs.append(a - h)  # positive = the away team is missing more
            ys.append(r.resid)
    x, y = np.array(xs), np.array(ys)
    k = float((x * y).sum() / (x * x).sum()) if len(x) else 0.6
    se = float(np.sqrt(((y - k * x) ** 2).sum() / max(len(x) - 1, 1) / (x * x).sum())) if len(x) else 0
    log(f"  injuries: {len(x)} games, {int((x != 0).sum())} with a regular out; {k:.2f} pts per unit (±{se:.2f})")
    return k


# ---------------------------------------------------------------- who's out
def espn_injuries(game_ids, log=print) -> dict:
    """{athlete_id: (status, detail)} from ESPN game summaries (best effort)."""
    from espn import HEADERS
    out, ok, err = {}, 0, None
    for gid in game_ids:
        for host in ("https://site.api.espn.com", "https://site.web.api.espn.com"):
            try:
                url = f"{host}/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={gid}"
                js = json.load(urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=20))
                for tm in js.get("injuries") or []:
                    for inj in tm.get("injuries") or []:
                        ath = inj.get("athlete") or {}
                        if ath.get("id"):
                            out[int(ath["id"])] = (str(inj.get("status") or "").lower(),
                                                   (inj.get("details") or {}).get("type") or inj.get("type") or "")
                ok += 1
                break
            except Exception as e:
                err = repr(e)[:120]
        time.sleep(0.2)
    log(f"  injuries: ESPN reports for {ok}/{len(game_ids)} games, {len(out)} players listed" + (f" (last error {err})" if err and not ok else ""))
    return out


def manual(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.load(open(path)).get("players", [])
    except Exception:
        return []


def status_now(vals: pd.DataFrame, p: pd.DataFrame, espn: dict, hand: list, today: str) -> pd.DataFrame:
    """Every regular's chance of sitting out his team's next game, and why."""
    v = vals[vals.regular].copy()
    if v.empty:
        return v.assign(p_out=[], source=[], note=[])
    last = p.sort_values("game_date").groupby("team_id").game_id.agg(lambda s: list(dict.fromkeys(s))[-2:])
    played = p[p.played].groupby("game_id").athlete_id.agg(set)
    po, src, note = [], [], []
    for _, r in v.iterrows():
        prob, s, n = 0.0, "", ""
        lg = last.get(r.team_id, [])
        missed = [g for g in lg if r.athlete_id not in played.get(g, set())]
        if len(lg) >= 1 and len(missed) == len(lg) == 2:
            prob, s, n = 0.85, "box", "Missed the last two games"
        elif lg and lg[-1] in missed:
            prob, s, n = 0.5, "box", "Missed the last game"
        if int(r.athlete_id) in espn:
            st, det = espn[int(r.athlete_id)]
            prob, s, n = P_STATUS.get(st, prob), "espn", ("ESPN: " + st.title() + (f" ({det})" if det else ""))
        po.append(prob); src.append(s); note.append(n)
    v["p_out"], v["source"], v["note"] = po, src, note
    v["long"] = False
    # hand-entered statuses win; matched by team and name
    for h in hand:
        until = h.get("until")
        if until and str(until) < today:
            continue
        m = (v.team_id == int(h.get("team_id", -1))) & (v.name.str.lower() == str(h.get("player", "")).lower())
        if m.any():
            st = str(h.get("status", "out")).lower()
            v.loc[m, "p_out"] = P_STATUS.get(st, 0.97)
            v.loc[m, "source"] = "hand"
            v.loc[m, "note"] = (h.get("note") or st.title()) + (f" (through {until})" if until else "")
            v.loc[m, "long"] = bool(h.get("season", False)) or bool(until and str(until) > (pd.Timestamp(today) + pd.Timedelta(days=7)).strftime("%Y-%m-%d"))
    return v


def team_adjust(st: pd.DataFrame, k: float) -> dict:
    """team -> {"near": points for games this week, "long": points for every game after, "players": [...]}.
    The ratings assumed each regular was out for the share of games he's missed; the adjustment is the
    gap between that and his chance of sitting out now (positive = a player back from injury)."""
    out = {}
    if st.empty:
        return out
    for t, x in st.groupby("team_id"):
        near = long = 0.0
        ppl = []
        for _, r in x.iterrows():
            missed = 1 - min(1.0, float(r.share))
            p_long = float(r.p_out) if bool(r.get("long", False)) else 0.0
            d_near = k * r.v * (missed - r.p_out)
            d_long = k * r.v * (missed - p_long)
            near += d_near
            long += d_long
            if abs(d_near) >= 0.3 or r.p_out >= 0.3:
                ppl.append({"id": int(r.athlete_id), "name": r["name"], "mpg": round(float(r.mpg), 1), "value": round(float(r.v), 1),
                            "p_out": round(float(r.p_out), 2), "pts": round(float(d_near), 1), "note": r.note, "source": r.source,
                            "long": bool(r.get("long", False))})
        out[int(t)] = {"near": round(near, 2), "long": round(long, 2), "players": sorted(ppl, key=lambda q: q["pts"])}
    return out
