"""Opponent-adjusted efficiency ratings for men's basketball.

Every game gives two observations, one per offense:
    points per 100 possessions = mu + Off[team] + Def[opponent] + home * hca_eff
(Def is points allowed above average, so lower is better; net = Off - Def.)
and one pace observation:
    possessions per 40 min = tmu + Tempo[home] + Tempo[away]

Solved by weighted least squares with every team pulled toward its preseason
prior (a ridge penalty worth `lam` games), recent games weighted more, and
blowout efficiency margins capped so running up the score doesn't pay.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from data import NON_D1


@dataclass
class Params:
    lam: float = 4.0          # prior weight, in games
    lam_t: float = 4.0        # tempo prior weight, in games
    tau: float = 75.0         # recency: weight halves every tau*ln2 days
    cap: float = 30.0         # cap on a game's efficiency margin (points per 100)
    hca_eff: float = 3.4      # home edge in points per 100 possessions (refit each run)


def team_index(g: pd.DataFrame, d1: set[int]) -> tuple[np.ndarray, dict]:
    ids = sorted(d1) + [NON_D1]
    return np.array(ids), {t: i for i, t in enumerate(ids)}


def _ix(ids, idx):
    return np.array([idx.get(int(t), idx[NON_D1]) for t in ids])


def solve(g: pd.DataFrame, ids: np.ndarray, idx: dict, prior_o: np.ndarray, prior_d: np.ndarray,
          prior_t: np.ndarray, p: Params, as_of: pd.Timestamp | None = None, fit_hca: bool = False):
    """g: completed games with possessions. Returns dict of arrays/scalars."""
    n = len(ids)
    g = g[g.poss.notna() & g.completed]
    if as_of is not None:
        g = g[g.day < as_of]
    out = {"mu": 103.0, "hca": p.hca_eff, "tmu": 68.0, "games": int(len(g))}
    if len(g) == 0:
        out.update(O=prior_o.copy(), D=prior_d.copy(), T=prior_t.copy())
        return out
    hi, ai = _ix(g.home_id, idx), _ix(g.away_id, idx)
    ref = as_of if as_of is not None else g.day.max() + pd.Timedelta(days=1)
    age = (ref - g.day).dt.days.to_numpy(float)
    w = np.exp(-age / p.tau)
    he = 100 * g.home_pts.to_numpy(float) / g.poss.to_numpy(float)
    ae = 100 * g.away_pts.to_numpy(float) / g.poss.to_numpy(float)
    # cap the efficiency margin: shrink both sides toward the game mean
    m, c = (he + ae) / 2, (he - ae) / 2
    c = np.clip(c, -p.cap / 2, p.cap / 2)
    he, ae = m + c, m - c
    h = np.where(g.neutral.to_numpy(), 0.0, 1.0)
    # unknowns: O[0:n], D[n:2n], mu, hca
    k = 2 * n + 2
    A = np.zeros((k, k))
    b = np.zeros(k)

    def add(off, dfn, y, hs):
        cols = np.stack([off, n + dfn, np.full_like(off, 2 * n), np.full_like(off, 2 * n + 1)], 1)
        vals = np.stack([np.ones_like(y), np.ones_like(y), np.ones_like(y), hs], 1)
        for a_ in range(4):
            for b_ in range(4):
                np.add.at(A, (cols[:, a_], cols[:, b_]), w * vals[:, a_] * vals[:, b_])
            np.add.at(b, cols[:, a_], w * vals[:, a_] * y)

    add(hi, ai, he, h)
    add(ai, hi, ae, -h)
    # priors (ridge toward each team's preseason value)
    lam = p.lam * np.ones(n)
    A[np.arange(n), np.arange(n)] += lam
    A[n + np.arange(n), n + np.arange(n)] += lam
    b[:n] += lam * prior_o
    b[n:2 * n] += lam * prior_d
    if not fit_hca:  # hold home court fixed at its long-run value
        A[2 * n + 1, :] = 0
        A[2 * n + 1, 2 * n + 1] = 1
        b[2 * n + 1] = p.hca_eff
    # identify: offenses and defenses each sum to zero (soft)
    A[:n, :n] += 1e-3
    A[n:2 * n, n:2 * n] += 1e-3
    x = np.linalg.solve(A + 1e-9 * np.eye(k), b)
    O, D, mu, hca = x[:n], x[n:2 * n], x[2 * n], x[2 * n + 1]
    # tempo
    pace = g.pace.to_numpy(float)
    At = np.zeros((n + 1, n + 1))
    bt = np.zeros(n + 1)
    for a_, b_ in [(hi, hi), (ai, ai), (hi, ai), (ai, hi)]:
        np.add.at(At, (a_, b_), w)
    for a_ in (hi, ai):
        np.add.at(At, (a_, np.full_like(a_, n)), w)
        np.add.at(At, (np.full_like(a_, n), a_), w)
        np.add.at(bt, a_, w * pace)
    At[n, n] += w.sum()
    bt[n] += (w * pace).sum()
    At[np.arange(n), np.arange(n)] += p.lam_t
    bt[:n] += p.lam_t * prior_t
    At[:n, :n] += 1e-3
    xt = np.linalg.solve(At + 1e-9 * np.eye(n + 1), bt)
    out.update(O=O, D=D, mu=float(mu), hca=float(hca), T=xt[:n], tmu=float(xt[n]))
    return out


def predict_raw(r: dict, idx: dict, home_ids, away_ids, neutral) -> pd.DataFrame:
    """Rating-only expectations (no situational adjustments): points each side and possessions."""
    hi, ai = _ix(home_ids, idx), _ix(away_ids, idx)
    pace = r["tmu"] + r["T"][hi] + r["T"][ai]
    he = r["mu"] + r["O"][hi] + r["D"][ai]
    ae = r["mu"] + r["O"][ai] + r["D"][hi]
    return pd.DataFrame({"r_pace": pace, "r_home_eff": he, "r_away_eff": ae,
                         "r_margin": (he - ae) * pace / 100, "r_total": (he + ae) * pace / 100})
