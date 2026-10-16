"""Preseason priors: where each team starts before it plays a game.

For every team, from last season:
  * its final offense/defense/tempo ratings (and the season before, more lightly),
  * returning minutes: share of last season's minutes played by players back this year,
  * transfers in: minutes-weighted strength of the teams incoming transfers played for,
    and how productive each transfer was himself (box-score game score per 40 minutes,
    weighted by how good his old team was),
  * returning production: share of last season's box-score production that's back,
  * incoming freshmen: ranked high school recruits by tier (recruits.py, On3 Industry rank),
  * its conference's average strength.
The weights are fit on 2014-2026: last season's facts -> this season's final ratings.
For past seasons "back this year" is read from who played; for the current season,
from the posted roster.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import data
import ratings as R
import recruits as RC

FEATS = ["last", "last_x_ret", "ret", "last2", "xfer", "conf", "new"]


PROD_COLS = ["athlete_id", "team_id", "minutes", "points", "field_goals_made", "field_goals_attempted",
             "free_throws_made", "free_throws_attempted", "offensive_rebounds", "defensive_rebounds",
             "assists", "steals", "blocks", "turnovers", "fouls"]
_PROD: dict = {}
_REC: dict = {}


def production(season: int) -> pd.DataFrame | None:
    """Each player's season box-score production: athlete_id, team_id, minutes, gs (Hollinger game score total)."""
    if season not in _PROD:
        f = data.CACHE / f"pb_{season}.parquet"
        if not f.exists():
            _PROD[season] = None
        else:
            p = pd.read_parquet(f, columns=PROD_COLS).apply(pd.to_numeric, errors="coerce")
            p = p.dropna(subset=["athlete_id", "team_id"]).fillna(0)
            s = p.groupby(["athlete_id", "team_id"], as_index=False).sum()
            s["gs"] = (s.points + 0.4 * s.field_goals_made - 0.7 * s.field_goals_attempted
                       - 0.4 * (s.free_throws_attempted - s.free_throws_made) + 0.7 * s.offensive_rebounds
                       + 0.3 * s.defensive_rebounds + s.steals + 0.7 * s.assists + 0.7 * s.blocks
                       - 0.4 * s.fouls - s.turnovers)
            _PROD[season] = s[s.minutes > 0][["athlete_id", "team_id", "minutes", "gs"]].astype({"athlete_id": "int64", "team_id": "int64"})
    return _PROD[season]


def recruits(current: int) -> pd.DataFrame:
    if current not in _REC:
        _REC[current] = RC.load(current)
    return _REC[current]


def trusted(now_ids: set, last_ids: set | None) -> bool:
    """A current roster we believe: at least 8 players and at least 3 newcomers."""
    if not now_ids or len(now_ids) < 8:
        return False
    return last_ids is None or len(now_ids - last_ids) >= 3


def final_ratings(g: pd.DataFrame, current: int) -> dict:
    """Season -> DataFrame(team, O, D, T, net, conf) from each season's full results (light prior)."""
    out = {}
    for y in sorted(g.season.unique()):
        if y >= current:
            continue
        s = g[g.season == y]
        d1 = data.d1_teams(y, current)
        ids, idx = R.team_index(s, d1)
        z = np.zeros(len(ids))
        r = R.solve(s, ids, idx, z, z, z, R.Params(lam=1.0, lam_t=1.0, tau=1e9), fit_hca=True)
        conf = pd.concat([s[["home_id", "home_conf"]].set_axis(["team", "conf"], axis=1),
                          s[["away_id", "away_conf"]].set_axis(["team", "conf"], axis=1)]).dropna()
        conf = conf.groupby("team").conf.agg(lambda x: x.mode().iat[0])
        df = pd.DataFrame({"team": ids, "O": r["O"], "D": r["D"], "T": r["T"]})
        df["net"] = df.O - df.D
        df["conf"] = df.team.map(conf)
        out[y] = df[df.team != data.NON_D1].set_index("team")
    return out


def returning(season: int, ro: dict, mins: dict, fin: dict, current: int) -> pd.DataFrame:
    """team -> ret (share of last season's minutes back), xfer_o / xfer_d / xfer_net (incoming transfers)."""
    last = mins.get(season - 1)
    if last is None:
        return pd.DataFrame(columns=["ret", "xfer_o", "xfer_d"])
    tot = last.groupby("team_id").minutes.sum()
    if season >= current and season in ro:
        now = ro[season].rename(columns={"team_id": "now_team"})
        # ESPN refreshes rosters team by team, and early in the fall a "new" roster is often last
        # season's with a few players removed. Only a roster that has added newcomers says who is back;
        # every other team gets typical values instead.
        stale = set()
        if season - 1 in ro:
            old = ro[season - 1].groupby("team_id").athlete_id.agg(set)
            for t, ath in now.groupby("now_team").athlete_id.agg(set).items():
                if not trusted(ath, old.get(t)):
                    stale.add(t)
        now = now[~now.now_team.isin(stale)]
    elif season in mins:
        now = mins[season][mins[season].minutes > 0][["athlete_id", "team_id"]].rename(columns={"team_id": "now_team"})
    else:
        return pd.DataFrame(columns=["ret", "xfer_o", "xfer_d"])
    now = now.drop_duplicates("athlete_id")
    m = last.merge(now, on="athlete_id", how="inner")
    m["share"] = m.minutes / m.team_id.map(tot)
    back = m[m.team_id == m.now_team].groupby("now_team").share.sum()
    xf = m[m.team_id != m.now_team].copy()
    prev = fin.get(season - 1)
    if prev is not None:
        xf["o"] = xf.team_id.map(prev.O).fillna(-8)
        xf["d"] = xf.team_id.map(prev.D).fillna(8)
    else:
        xf["o"], xf["d"] = 0.0, 0.0
    # a transfer's share of his old team's minutes, times that team's strength (5 lineup slots)
    xo = (xf.share * xf.o).groupby(xf.now_team).sum()
    xd = (xf.share * xf.d).groupby(xf.now_team).sum()
    xs = xf.groupby("now_team").share.sum()
    out = pd.DataFrame({"ret": back}).join(pd.DataFrame({"xfer_o": xo, "xfer_d": xd, "xfer_share": xs}), how="outer").fillna(0.0)
    out["ret"] = out.ret.clip(0, 1)
    # production, not just minutes: who was actually good last season, and where he is now
    pr = production(season - 1)
    if pr is not None:
        tgs, tmin = pr.groupby("team_id").gs.sum(), pr.groupby("team_id").minutes.sum()
        pm = pr.merge(now[["athlete_id", "now_team"]], on="athlete_id", how="inner")
        bk = pm[pm.team_id == pm.now_team]
        rq = (bk.groupby("now_team").gs.sum() / tgs).dropna().clip(0, 1.2)
        tx = pm[pm.team_id != pm.now_team].copy()
        tx["share"] = tx.minutes / tx.team_id.map(tmin)
        tx["gs40"] = np.where(tx.minutes > 60, 40 * tx.gs / tx.minutes.clip(lower=1), 6.0)
        tx["lvl"] = (tx.team_id.map(prev.O - prev.D).fillna(-15) / 10) if prev is not None else 0.0
        tx["v"] = tx.share * (tx.gs40 - 10)
        q = pd.DataFrame({"ret_q": rq, "xq": tx.groupby("now_team").v.sum(), "xql": (tx.v * tx.lvl).groupby(tx.now_team).sum()})
        out = out.join(q, how="outer").fillna(0.0)
    for c in ("ret_q", "xq", "xql"):
        if c not in out:
            out[c] = 0.0
    if season >= current:
        # typical values from the last two completed seasons, for teams without an updated roster
        hist = [returning(y, ro, mins, fin, current) for y in (season - 2, season - 1) if y in mins and y - 1 in mins]
        hist = [h for h in hist if len(h)]
        if hist:
            hh = pd.concat(hist)
            out.attrs["typical"] = {k: float(hh[k].mean()) for k in ("ret", "xfer_o", "xfer_d", "ret_q", "xq", "xql")}
    return out


def features(season: int, teams: np.ndarray, fin: dict, ret: pd.DataFrame, conf_now: pd.Series) -> pd.DataFrame:
    p1, p2 = fin.get(season - 1), fin.get(season - 2)
    rows = []
    for t in teams:
        r = {"team": t}
        has1 = p1 is not None and t in p1.index
        rt = ret.loc[t] if t in ret.index else None
        for k in ["O", "D", "T"]:
            l1 = p1.at[t, k] if has1 else 0.0
            l2 = p2.at[t, k] if (p2 is not None and t in p2.index) else l1
            r[f"{k}_last"], r[f"{k}_last2"] = l1, l2
        typ = {"ret": 0.35, "xfer_o": 0.0, "xfer_d": 0.0, "ret_q": 0.35, "xq": 0.0, "xql": 0.0}
        typ.update(ret.attrs.get("typical", {}))
        for k in ("ret", "xfer_o", "xfer_d", "ret_q", "xq", "xql"):
            r[k] = float(rt[k]) if (rt is not None and k in rt) else (typ[k] if has1 else 0.0)
        r["new"] = 0.0 if has1 else 1.0
        c = conf_now.get(t)
        if p1 is not None and c is not None and not pd.isna(c):
            same = p1[(p1.conf == c) & (p1.index != t)]
            r["conf_O"], r["conf_D"] = (same.O.mean(), same.D.mean()) if len(same) else (0.0, 0.0)
        else:
            r["conf_O"], r["conf_D"] = (0.0, 0.0)
        rows.append(r)
    F = pd.DataFrame(rows).set_index("team")
    return F.join(RC.features(season, F.index, recruits(data_current())))


def data_current() -> int:
    """The newest season in the data (recruit names are matched against recent schedules)."""
    ys = [int(p.stem.split("_")[1]) for p in data.CACHE.glob("sch_*.parquet")]
    return max(ys) if ys else 0


TIER_COLS = [t[0] for t in RC.TIERS]


def design(F: pd.DataFrame, k: str) -> np.ndarray:
    last = F[f"{k}_last"].to_numpy()
    if k == "T":
        return np.stack([last, F[f"{k}_last2"], F.ret, F.new, np.ones(len(F))], 1)
    xf = F.xfer_o if k == "O" else F.xfer_d
    cf = F.conf_O if k == "O" else F.conf_D
    return np.stack([last, last * F.ret, F.ret, F[f"{k}_last2"], xf, cf, F.new, np.ones(len(F)),
                     F.ret_q, last * F.ret_q, F.xq, F.xql] + [F[c] for c in TIER_COLS], 1)


N_DESIGN = {"O": 16, "D": 16, "T": 5}   # columns per rating; a saved model with fewer is out of date


class Prior:
    def __init__(self, coef: dict):
        self.coef = coef

    @staticmethod
    def fit(g: pd.DataFrame, fin: dict, ro: dict, mins: dict, current: int, seasons) -> "Prior":
        X = {"O": [], "D": [], "T": []}
        Y = {"O": [], "D": [], "T": []}
        for y in seasons:
            if y not in fin or (y - 1) not in fin:
                continue
            tgt = fin[y]
            ret = returning(y, ro, mins, fin, current)
            F = features(y, tgt.index.to_numpy(), fin, ret, tgt.conf)
            for k in X:
                X[k].append(design(F, k))
                Y[k].append(tgt[k].to_numpy())
        coef = {}
        for k in X:
            A, yv = np.vstack(X[k]), np.concatenate(Y[k])
            coef[k] = np.linalg.lstsq(A.T @ A + 1e-3 * np.eye(A.shape[1]), A.T @ yv, rcond=None)[0].tolist()
        return Prior(coef)

    def predict(self, season, teams, fin, ret, conf_now) -> pd.DataFrame:
        F = features(season, teams, fin, ret, conf_now)
        out = pd.DataFrame(index=F.index)
        for k in ["O", "D", "T"]:
            out[k] = design(F, k) @ np.array(self.coef[k])
        out["ret"], out["xfer"] = F.ret, F.xfer_o - F.xfer_d
        # how much of the start (net points) comes from incoming freshmen and from transfers
        cO, cD = np.array(self.coef["O"]), np.array(self.coef["D"])
        if len(cO) == N_DESIGN["O"]:
            tiers = F[TIER_COLS].to_numpy()
            out["fr_pts"] = tiers @ (cO[12:16] - cD[12:16])
            out["xf_pts"] = (F.xfer_o * cO[4] - F.xfer_d * cD[4] + F.xq * (cO[10] - cD[10]) + F.xql * (cO[11] - cD[11])).to_numpy()
            out[TIER_COLS] = tiers
        return out
