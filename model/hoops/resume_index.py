"""The basketball Elevation Index: résumé plus stats, this season only.

Preseason, the Index is where the Bot starts every team (last season, returning
production, transfers, recruits). Once nearly every Division I team has played
two games against D-I opponents, it flips and preseason counts for nothing:

  * Résumé (who has earned a March Madness bid): Wins Above Bubble. For every
    game, the chance a bubble team would have won it, at that site, against that
    opponent. Beat a team a bubble team usually loses to and you bank most of a
    win; lose to a team a bubble team almost always beats and it costs nearly a
    full win. Opponents are judged by the Bot's current ratings.
  * Stats (who is actually good, so who goes furthest in March): offense and
    defense per 100 possessions, adjusted for every opponent and home court,
    from this season's games only. Early on each team is pulled lightly toward
    an average D-I team, never toward its preseason rating.

The Index score is half each, on the stats scale (points per 100 possessions
better than an average D-I team).
"""
from __future__ import annotations

from math import erf, sqrt

import numpy as np
import pandas as pd

import bracket as BR
import ratings as R

FLIP_GAMES = 2          # D-I games each team needs before the résumé Index takes over
FLIP_SHARE = 0.9        # ...for this share of D-I teams
BUBBLE_RANK = 45        # a bubble team: about the last at-large in a 76-team field
PACE = 68.0             # possessions per game, to turn per-100 ratings into points
SIGMA = 11.0            # spread of a single game's margin (points)
W_RESUME = 0.5          # Index weight on résumé (the rest is stats)


def _phi(x):
    x = np.asarray(x, dtype=float)
    return 0.5 * (1 + np.array([erf(v / sqrt(2)) for v in x.ravel()]).reshape(x.shape))


def d1_games_played(g: pd.DataFrame) -> pd.Series:
    L = BR.long_games(g[g.completed])
    return L.groupby("team").size()


def flipped(g: pd.DataFrame, d1: set) -> bool:
    n = d1_games_played(g).reindex(sorted(d1)).fillna(0)
    return bool(len(n)) and (n >= FLIP_GAMES).mean() >= FLIP_SHARE


def power(s: pd.DataFrame, ids, idx) -> pd.DataFrame:
    """This season's opponent-adjusted offense/defense, no preseason prior."""
    z = np.zeros(len(ids))
    r = R.solve(s[s.completed], ids, idx, z, z, z, R.Params(lam=1.0, lam_t=1.0, tau=1e9), fit_hca=True)
    return pd.DataFrame({"pO": r["O"], "pD": r["D"], "pow": r["O"] - r["D"]}, index=pd.Index(ids, name="team"))


def wab(s: pd.DataFrame, opp_net: dict, hca: float, teams) -> pd.DataFrame:
    """Wins Above Bubble and its pieces for each team, from completed D-I games."""
    nets = np.sort(np.array([v for v in opp_net.values() if v is not None]))[::-1]
    bubble = float(nets[min(BUBBLE_RANK, len(nets)) - 1]) if len(nets) else 0.0
    L = BR.long_games(s[s.completed])
    L = L[L.team.isin(teams)].copy()
    on = L.opp.map(opp_net).fillna(-20.0).to_numpy()
    site = np.where(L["loc"] == "home", hca, np.where(L["loc"] == "away", -hca, 0.0))
    L["p_bub"] = _phi((bubble - on + site) * PACE / 100 / SIGMA)
    L["win"] = (L.pts > L.opts).astype(float)
    L["wab"] = L.win - L.p_bub
    out = L.groupby("team").agg(gp=("win", "size"), wab=("wab", "sum"))
    out = out.reindex(pd.Index(list(teams), name="team")).fillna({"gp": 0, "wab": 0.0})
    out.attrs["bubble_net"] = bubble
    return out


def build(s: pd.DataFrame, ids, idx, d1: set, opp_net: dict, opp_rank: dict, hca: float, conf_of: dict,
          n_field: int = 76, n_auto: int = 32) -> pd.DataFrame:
    """Index for every D-I team from this season's games s."""
    teams = sorted(d1)
    P = power(s, ids, idx).reindex(teams)
    W = wab(s, opp_net, hca, teams)
    Q = BR.resume(s, opp_rank, opp_net, teams)[["w", "l", "q1w", "q1l", "q2w", "q2l", "q3l", "q4l"]]
    X = P.join(W).join(Q)
    # résumé onto the stats scale, then blend
    z = lambda v: (v - v.mean()) / (v.std() or 1)
    X["res"] = X["pow"].mean() + X["pow"].std() * z(X.wab)
    X["score"] = W_RESUME * X.res + (1 - W_RESUME) * X["pow"]
    X["idx_rank"] = X.score.rank(ascending=False, method="first").astype(int)
    X["res_rank"] = X.wab.rank(ascending=False, method="first").astype(int)
    X["pow_rank"] = X["pow"].rank(ascending=False, method="first").astype(int)
    X["conf"] = X.index.map(conf_of)
    X["field"] = our_field(X, n_field, n_auto)
    return X


def our_field(X: pd.DataFrame, n_field: int = 76, n_auto: int = 32) -> pd.Series:
    """Our take on the bracket today, by résumé: each league's best résumé takes its
    automatic bid, the best remaining résumés take the at-large spots."""
    lab = pd.Series("", index=X.index)
    by = X.sort_values("wab", ascending=False)
    auto = by[by.conf.notna()].groupby("conf").head(1).index
    lab[auto] = "auto"
    rest = by[~by.index.isin(auto)]
    n_at = n_field - len(auto)
    lab[rest.index[:n_at]] = "in"
    lab[rest.index[max(0, n_at - 4):n_at]] = "last4in"
    lab[rest.index[n_at:n_at + 4]] = "first4out"
    lab[rest.index[n_at + 4:n_at + 8]] = "next4out"
    return lab
