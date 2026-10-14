"""Game model: turns rating expectations + situation into a margin, total and win chance.

margin = a * rating margin (neutral court)
       + home court
       + altitude the visitor climbs (per 1,000 ft, and extra above 4,000 ft)
       + travel difference (per 1,000 miles) + rest difference (days)
total  = b * rating total + altitude + constant
Win chance from a normal error whose spread is wider early in the season.
"""
from __future__ import annotations

import json
from math import erf, sqrt

import numpy as np
import pandas as pd

MARGIN_F = ["r_margin", "home", "climb", "climb_hi", "travel", "rest", "early_margin"]
TOTAL_F = ["r_total", "site_k", "early_total", "const"]


def _early(r: pd.DataFrame) -> np.ndarray:
    gp = np.minimum(r.home_gp.fillna(0), r.away_gp.fillna(0)).to_numpy(float)
    return np.exp(-gp / 5.0)


def features(r: pd.DataFrame) -> pd.DataFrame:
    h = np.where(r.neutral.to_numpy(), 0.0, 1.0)
    climb = (r.away_climb - r.home_climb).to_numpy(float) / 1000
    hi = np.where(r.site_elev.fillna(0).to_numpy() > 4000, climb, 0.0)
    e = _early(r)
    return pd.DataFrame({
        "r_margin": r.r_margin.to_numpy(float), "home": h, "climb": climb, "climb_hi": hi,
        "travel": (r.away_travel - r.home_travel).to_numpy(float) / 1000,
        "rest": np.clip(r.home_rest - r.away_rest, -4, 4).to_numpy(float),
        "early_margin": e * r.r_margin.to_numpy(float),
    }, index=r.index)


def total_features(r: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({"r_total": r.r_total.to_numpy(float), "site_k": r.site_elev.fillna(0).to_numpy(float) / 1000,
                         "early_total": _early(r) * r.r_total.to_numpy(float), "const": 1.0}, index=r.index)


class GameModel:
    def __init__(self, coef, tcoef, sigma_early, sigma_late, sigma_total):
        self.coef, self.tcoef = coef, tcoef
        self.sigma_early, self.sigma_late, self.sigma_total = sigma_early, sigma_late, sigma_total

    @staticmethod
    def fit(r: pd.DataFrame, ridge: float = 1.0) -> "GameModel":
        X, y = features(r), r.margin.to_numpy(float)
        A = X.to_numpy()
        b = np.linalg.solve(A.T @ A + ridge * np.eye(A.shape[1]), A.T @ y)
        T, yt = total_features(r), r.total.to_numpy(float)
        At = T.to_numpy()
        bt = np.linalg.solve(At.T @ At + ridge * np.eye(At.shape[1]), At.T @ yt)
        res = y - A @ b
        e = _early(r)
        se = float(np.sqrt(np.average(res ** 2, weights=e + 1e-9)))
        sl = float(np.sqrt(np.average(res ** 2, weights=(1 - e) + 1e-9)))
        st = float(np.std(yt - At @ bt))
        return GameModel(dict(zip(X.columns, b.tolist())), dict(zip(T.columns, bt.tolist())), se, sl, st)

    def predict(self, r: pd.DataFrame) -> pd.DataFrame:
        m = features(r).to_numpy() @ np.array([self.coef[k] for k in MARGIN_F])
        t = total_features(r).to_numpy() @ np.array([self.tcoef[k] for k in TOTAL_F])
        e = _early(r)
        sig = e * self.sigma_early + (1 - e) * self.sigma_late
        wp = 0.5 * (1 + np.vectorize(erf)(m / sig / sqrt(2)))
        return pd.DataFrame({"pred_margin": m, "pred_total": t, "home_wp": wp,
                             "pred_home": (t + m) / 2, "pred_away": (t - m) / 2}, index=r.index)

    def to_dict(self):
        return {"coef": self.coef, "tcoef": self.tcoef, "sigma_early": self.sigma_early,
                "sigma_late": self.sigma_late, "sigma_total": self.sigma_total}

    @staticmethod
    def from_dict(d):
        return GameModel(d["coef"], d["tcoef"], d["sigma_early"], d["sigma_late"], d["sigma_total"])
