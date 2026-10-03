"""Stage two: turn rating matchups into margin, total and win probability.

The rating engine knows who is better. This layer learns *how much the
situation matters* — home field, the thin air at altitude, cross-country
travel, time zones, short weeks and byes, FCS opponents, early-season
uncertainty — from 15 seasons of walk-forward, out-of-sample predictions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
import pandas as pd
from math import erf, sqrt


def _ncdf(x):
    return 0.5 * (1 + np.vectorize(erf)(np.asarray(x, float) / sqrt(2)))


def features(r: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=r.index)
    home = (~r.neutral_site).astype(float)
    early = np.exp(-r.n_played_team / 3.0)  # 1 at week 1, ~0 by mid-season
    X["rat"] = r.rat_margin
    X["rat_early"] = r.rat_margin * early
    X["eff"] = r.eff_margin - r.rat_margin
    X["eff_early"] = (r.eff_margin - r.rat_margin) * early
    X["home"] = home
    X["home_fcs_game"] = home * ((r.home_division == "fcs") | (r.away_division == "fcs")).astype(float)
    # altitude: the visitor's climb (km) at a true home game, with diminishing curve
    climb = (r.away_climb - r.home_climb) / 1000.0
    X["climb"] = climb
    X["climb_hi"] = np.clip(climb - 1.2, 0, None)  # Laramie, Air Force, Boulder, Albuquerque, Logan...
    X["travel"] = np.log1p(r.away_travel) - np.log1p(r.home_travel)
    X["tz"] = r.away_tz - r.home_tz
    X["rest"] = np.clip(r.home_rest, 4, 15) - np.clip(r.away_rest, 4, 15)
    X["post"] = (r.season_type == "postseason").astype(float)
    X["post_rat"] = X.post * r.rat_margin
    X["conf"] = r.conference_game.astype(float)
    X["conf_rat"] = X.conf * r.rat_margin
    return X


def total_features(r: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=r.index)
    X["level"] = 2 * r.mu                               # league scoring environment right now
    X["dev"] = r.rat_total - 2 * r.mu                    # this matchup vs an average one
    X["late"] = np.clip(r.wk - 8, 0, 12) / 4.0          # November weather
    X["post"] = (r.season_type == "postseason").astype(float)
    X["alt"] = np.clip(r.v_elev.fillna(0) / 1000.0, 0, 2.5)
    X["spread_abs"] = np.abs(r.rat_margin) / 10.0      # lopsided games run clock late
    if "home_pace" in r:
        X["pace"] = (r.home_pace + r.away_pace).fillna(0) / 10.0
        X["passr"] = (r.home_passr + r.away_passr).fillna(0) * 10
    return X


@dataclass
class GameModel:
    coef: dict
    intercept: float
    tcoef: dict
    tintercept: float
    sigma_early: float
    sigma_late: float
    tsigma: float

    @staticmethod
    def fit(r: pd.DataFrame, ridge: float = 1.0) -> "GameModel":
        r = r[r.completed]
        X = features(r)
        y = r.margin.to_numpy(float)
        # robust-ish fit: Huber via IRLS so one 63-0 game doesn't swing coefficients
        Xm = X.to_numpy()  # no intercept: home/away labels at neutral sites are arbitrary
        w = np.ones(len(y))
        for _ in range(8):
            A = Xm.T * w
            beta = np.linalg.solve(A @ Xm + ridge * np.eye(Xm.shape[1]), A @ y)
            res = y - Xm @ beta
            c = 1.345 * np.median(np.abs(res)) / 0.6745
            w = np.where(np.abs(res) <= c, 1.0, c / np.abs(res))
        res = y - Xm @ beta
        early = r.n_played_team.to_numpy() < 3
        T = total_features(r)
        lvl = T.pop("level").to_numpy()   # scoring environment passes through 1:1
        Tm = np.column_stack([np.ones(len(T)), T.to_numpy()])
        ty = r.total.to_numpy(float) - lvl
        tb = np.linalg.solve(Tm.T @ Tm + ridge * np.eye(Tm.shape[1]) * np.r_[0, np.ones(Tm.shape[1] - 1)], Tm.T @ ty)
        tres = ty - Tm @ tb
        return GameModel(dict(zip(X.columns, beta)), 0.0,
                         dict(zip(T.columns, tb[1:])), float(tb[0]),
                         float(np.std(res[early])), float(np.std(res[~early])), float(np.std(tres)))

    def predict(self, r: pd.DataFrame) -> pd.DataFrame:
        X = features(r)
        m = self.intercept + sum(X[k] * v for k, v in self.coef.items())
        T = total_features(r)
        t = T.pop("level") + self.tintercept + sum(T[k] * v for k, v in self.tcoef.items())
        early = np.exp(-r.n_played_team / 3.0)
        sig = self.sigma_late + (self.sigma_early - self.sigma_late) * early
        out = pd.DataFrame({"pred_margin": m, "pred_total": t, "sigma": sig}, index=r.index)
        out["home_wp"] = _ncdf(m / sig)
        out["pred_home"] = (t + m) / 2
        out["pred_away"] = (t - m) / 2
        return out

    def to_json(self, path):
        json.dump(self.__dict__, open(path, "w"), indent=1)

    @staticmethod
    def load(path):
        return GameModel(**json.load(open(path)))


def add_games_played(r: pd.DataFrame, games: pd.DataFrame) -> pd.DataFrame:
    """Fewest completed games by either team before this game (uncertainty proxy)."""
    long = pd.concat([
        games[["game_id", "season", "start", "home_id"]].rename(columns={"home_id": "tid"}),
        games[["game_id", "season", "start", "away_id"]].rename(columns={"away_id": "tid"}),
    ]).sort_values(["tid", "season", "start"])
    long["n"] = long.groupby(["tid", "season"]).cumcount()
    n = long.groupby("game_id").n.min()
    r = r.copy()
    r["n_played_team"] = r.game_id.map(n).fillna(0)
    return r
