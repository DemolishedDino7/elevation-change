"""Play-level efficiency.

Turns the play-by-play stat feed into per-team, per-game efficiency:
success rate, yards per play, explosive-play rate and turnovers, with
garbage time removed. These numbers say how well a team actually played,
which is more stable week to week than the final score (a 4-turnover game
or a fluky fourth quarter shouldn't move a rating as much as the score says).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from data import CACHE, RAW, _fetch

COLS = ["game_id", "season", "week", "team", "opponent", "team_score", "opponent_score", "play_id", "period",
        "down", "distance", "yards_to_goal",
        "rush_player_id", "rush_yds", "completion_player_id", "completion_yds", "incompletion_player_id",
        "sack_taken_player_id", "interception_thrown_player_id", "fumble_player_id", "fumble_recovered_player_id",
        "touchdown_player_id", "reception_player_id", "reception_yds", "rush_player", "completion_player"]


def download(first: int, current: int, refresh_current: bool = True):
    for y in range(first, current + 1):
        live = y >= current - 1 and refresh_current
        _fetch(f"player_stats/parquet/player_stats_{y}.parquet", CACHE / f"ps_{y}.parquet", live)
        _fetch(f"rosters/parquet/cfb_rosters_{y}.parquet", CACHE / f"ro_{y}.parquet", live)


def load_plays(season: int) -> pd.DataFrame:
    """One row per offensive scrimmage play."""
    p = pd.read_parquet(CACHE / f"ps_{season}.parquet")
    p = p[[c for c in COLS if c in p.columns]].copy()
    p = p.dropna(subset=["play_id"])
    # rows belonging to the offense on this play
    off = (p.rush_player_id.notna() | p.completion_player_id.notna() | p.incompletion_player_id.notna()
           | p.sack_taken_player_id.notna() | p.interception_thrown_player_id.notna())
    o = p[off].copy()
    o["kind"] = np.select(
        [o.rush_player_id.notna(), o.completion_player_id.notna(), o.sack_taken_player_id.notna(),
         o.interception_thrown_player_id.notna(), o.incompletion_player_id.notna()],
        ["rush", "pass", "sack", "int", "inc"], "other")
    o["yds"] = np.select([o.kind == "rush", o.kind == "pass", o.kind == "sack"],
                         [o.rush_yds, o.completion_yds, -7.0], 0.0)
    o["yds"] = o.yds.fillna(0.0)
    order = {"rush": 0, "pass": 1, "sack": 2, "int": 3, "inc": 4, "other": 5}
    o["_o"] = o.kind.map(order)
    o = o.sort_values(["play_id", "_o"]).drop_duplicates("play_id")
    # turnovers: interceptions, and fumbles recovered by the defense
    fum = p[p.fumble_recovered_player_id.notna()][["play_id", "team"]].rename(columns={"team": "rec_team"})
    fum = fum.drop_duplicates("play_id")
    o = o.merge(fum, on="play_id", how="left")
    o["to"] = ((o.kind == "int") | (o.rec_team.notna() & (o.rec_team != o.team))).astype(int)
    tds = p[p.touchdown_player_id.notna()][["play_id", "team"]].drop_duplicates("play_id").rename(columns={"team": "td_team"})
    o = o.merge(tds, on="play_id", how="left")
    o["td"] = (o.td_team == o.team).astype(int)
    d = o.down.fillna(1).astype(int)
    need = np.select([d == 1, d == 2], [0.5, 0.7], 1.0) * o.distance.fillna(10).clip(lower=1)
    o["success"] = ((o.yds >= need) | (o.td == 1)).astype(int) * (o.to == 0)
    o["explosive"] = (o.yds >= np.where(o.kind == "rush", 12, 16)).astype(int)
    # garbage time (Connelly thresholds)
    diff = (o.team_score - o.opponent_score).abs()
    per = o.period.fillna(1).astype(int)
    o["garbage"] = ((per == 2) & (diff > 38)) | ((per == 3) & (diff > 28)) | ((per >= 4) & (diff > 22))
    return o[["game_id", "season", "week", "team", "opponent", "kind", "yds", "success", "explosive", "to",
              "td", "garbage", "down", "distance", "yards_to_goal", "period", "play_id",
              "rush_player_id", "completion_player_id", "rush_player", "completion_player"]]


def team_games(season: int) -> pd.DataFrame:
    o = load_plays(season)
    allp = o.groupby(["game_id", "team"]).agg(to=("to", "sum"), plays_all=("success", "size"))
    ng = o[~o.garbage]
    agg = ng.groupby(["game_id", "team"]).agg(
        opponent=("opponent", "first"), plays=("success", "size"), sr=("success", "mean"),
        ypp=("yds", "mean"), xpl=("explosive", "mean"),
        pass_rate=("kind", lambda k: (k != "rush").mean()))
    agg = agg.join(allp)
    agg["season"] = season
    return agg.reset_index()


def efficiency_table(first: int, current: int) -> pd.DataFrame:
    out = []
    for y in range(first, current + 1):
        f = CACHE / f"eff_{y}.parquet"
        live = y >= current
        if f.exists() and not live:
            out.append(pd.read_parquet(f))
            continue
        t = team_games(y)
        t.to_parquet(f)
        out.append(t)
    return pd.concat(out, ignore_index=True)


DESERVED_FEATS = ["sr", "ypp", "xpl", "plays"]


def fit_deserved(eff: pd.DataFrame, games: pd.DataFrame, seasons) -> dict:
    """Linear map from a team's non-garbage efficiency to the points it 'should' have scored."""
    m = attach_points(eff, games)
    m = m[m.season.isin(list(seasons)) & m.pf.notna() & (m.plays >= 25)]
    X = np.column_stack([np.ones(len(m))] + [m[f].to_numpy(float) for f in DESERVED_FEATS])
    beta = np.linalg.lstsq(X, m.pf.to_numpy(float), rcond=None)[0]
    return {"intercept": float(beta[0]), **{f: float(b) for f, b in zip(DESERVED_FEATS, beta[1:])}}


def attach_points(eff: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    h = games[["game_id", "home_team", "away_team", "home_points", "away_points"]]
    m = eff.merge(h, on="game_id", how="inner")
    m["side"] = np.where(m.team == m.home_team, "home", np.where(m.team == m.away_team, "away", None))
    m["pf"] = np.where(m.side == "home", m.home_points, np.where(m.side == "away", m.away_points, np.nan))
    return m


def deserved_points(eff: pd.DataFrame, games: pd.DataFrame, coef: dict) -> pd.DataFrame:
    """Per game: home_dpts / away_dpts (NaN where play data is missing or thin)."""
    m = attach_points(eff, games)
    dp = coef["intercept"] + sum(m[f] * coef[f] for f in DESERVED_FEATS)
    m["dpts"] = np.where(m.plays >= 25, dp.clip(lower=0), np.nan)
    w = m.pivot_table(index="game_id", columns="side", values="dpts")
    return w.rename(columns={"home": "home_dpts", "away": "away_dpts"})


def pace_features(eff: pd.DataFrame, games: pd.DataFrame, k: float = 3.0) -> pd.DataFrame:
    """Pre-game tempo/style estimate per team: plays per game and pass rate, relative to the
    season average, from games played *before* this one, shrunk toward last season's value."""
    m = attach_points(eff, games)[["game_id", "team", "plays_all", "pass_rate", "season", "side"]]
    m = m.merge(games[["game_id", "start", "home_id", "away_id"]], on="game_id")
    m["tid"] = np.where(m.side == "home", m.home_id, m.away_id)
    m["plays_rel"] = m.plays_all - m.groupby("season").plays_all.transform("mean")
    m["pass_rel"] = m.pass_rate - m.groupby("season").pass_rate.transform("mean")
    m = m.sort_values(["tid", "start"])
    out = []
    last = {}
    for (tid, season), d in m.groupby(["tid", "season"], sort=True):
        prior = last.get((tid, season - 1), (0.0, 0.0))
        cs_p = d.plays_rel.cumsum().shift().fillna(0).to_numpy()
        cs_r = d.pass_rel.cumsum().shift().fillna(0).to_numpy()
        n = np.arange(len(d))
        pp = (cs_p + k * 0.6 * prior[0]) / (n + k)
        pr = (cs_r + k * 0.6 * prior[1]) / (n + k)
        out.append(pd.DataFrame({"game_id": d.game_id.to_numpy(), "tid": tid, "pace": pp, "passr": pr}))
        last[(tid, season)] = (d.plays_rel.mean(), d.pass_rel.mean())
    o = pd.concat(out)
    # also expose each team's latest (for future games)
    latest = {}
    for (tid, season), d in m.groupby(["tid", "season"]):
        prior = last.get((tid, season - 1), (0.0, 0.0))
        n = len(d)
        latest[(tid, season)] = ((d.plays_rel.sum() + k * 0.6 * prior[0]) / (n + k),
                                 (d.pass_rel.sum() + k * 0.6 * prior[1]) / (n + k))
    return o, latest, last


def attach_pace(games: pd.DataFrame, eff: pd.DataFrame) -> pd.DataFrame:
    o, latest, last = pace_features(eff, games)
    g = games.copy()
    key = o.set_index(["game_id", "tid"])
    for side in ("home", "away"):
        ix = pd.MultiIndex.from_arrays([g.game_id, g[f"{side}_id"]])
        for c in ("pace", "passr"):
            v = key[c].reindex(ix).to_numpy()
            # games without play data yet (future): use the team's latest estimate
            fb = np.array([(last.get((t, s - 1), (0.0, 0.0)) if done else latest.get((t, s), last.get((t, s - 1), (0.0, 0.0))))[0 if c == "pace" else 1]
                           for t, s, done in zip(g[f"{side}_id"], g.season, g.completed)])
            g[f"{side}_{c}"] = np.where(np.isnan(v), fb, v)
    return g
