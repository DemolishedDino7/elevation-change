"""Walk-forward predictions: each day of a season predicted using only games before it."""
from __future__ import annotations

import numpy as np
import pandas as pd

import data
import prior as PR
import ratings as R


def season_priors(y: int, g: pd.DataFrame, fin: dict, ro: dict, mins: dict, pri: PR.Prior, current: int):
    s = g[g.season == y]
    d1 = data.d1_teams(y, current)
    ids, idx = R.team_index(s, d1)
    conf_now = pd.concat([s[["home_id", "home_conf"]].set_axis(["team", "conf"], axis=1),
                          s[["away_id", "away_conf"]].set_axis(["team", "conf"], axis=1)]).dropna()
    conf_now = conf_now.groupby("team").conf.agg(lambda x: x.mode().iat[0])
    ret = PR.returning(y, ro, mins, fin, current)
    P = pri.predict(y, ids, fin, ret, conf_now)
    # the shared non-D-I rating starts where it usually ends
    P.loc[data.NON_D1, ["O", "D", "T"]] = [-12.0, 14.0, 0.0]
    return ids, idx, P.loc[ids], ret


def run_season(y, g, ids, idx, P, p: R.Params, days=None):
    """Predictions for every game in season y (rating-only expectations, as of that morning)."""
    s = g[g.season == y]
    po, pd_, pt = P["O"].to_numpy(), P["D"].to_numpy(), P["T"].to_numpy()
    out = []
    for day, gd in s.groupby("day"):
        if days is not None and day not in days:
            continue
        r = R.solve(s, ids, idx, po, pd_, pt, p, as_of=day)
        e = R.predict_raw(r, idx, gd.home_id, gd.away_id, gd.neutral)
        e.index = gd.index
        e["n_before"] = r["games"]
        out.append(e)
    return pd.concat(out) if out else pd.DataFrame()


def games_played_before(g: pd.DataFrame) -> pd.DataFrame:
    """Each team's games already played this season (for early-season uncertainty)."""
    long = pd.concat([g[["game_id", "season", "start", "home_id"]].rename(columns={"home_id": "t"}).assign(side="h"),
                      g[["game_id", "season", "start", "away_id"]].rename(columns={"away_id": "t"}).assign(side="a")])
    long = long.sort_values(["t", "season", "start"])
    long["gp"] = long.groupby(["t", "season"]).cumcount()
    pv = long.pivot_table(index="game_id", columns="side", values="gp", aggfunc="first")
    return pv.rename(columns={"h": "home_gp", "a": "away_gp"})
