"""Opponent-adjusted offense/defense power ratings.

Every team gets an offensive rating O and a defensive rating D, both in
points per game relative to an average team. A game is modelled as

    home points = mu + O_home - D_away + hfa/2
    away points = mu + O_away - D_home - hfa/2

and the ratings are a weighted ridge regression over the season's games,
pulled toward each team's preseason prior. The prior's pull fades as real
games pile up, recent games count more than old ones, and blowouts are
compressed so running up the score in garbage time isn't rewarded.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Params:
    hfa: float = 2.2            # home-field points used inside the rating fit
    cap: float = 45.0           # margin above which blowouts are compressed
    cap_slope: float = 0.8     # how much of the margin beyond the cap still counts
    decay: float = 0.94         # per-week recency weight
    post_w: float = 0.7         # postseason games (opt-outs) count a bit less
    lam_o: float = 2.0          # prior strength (in game-equivalents) for offense
    lam_d: float = 3.0          # prior strength for defense
    lam_final: float = 1.5      # light prior when fitting full-season final ratings
    keep1: float = 0.62         # weight on last year's rating in the preseason prior
    keep2: float = 0.08         # weight on two years ago
    keep3: float = 0.22         # weight on the program's longer-run level (3-5 years ago)
    fcs_mean: float = -26.0     # where an unknown FCS team's net rating starts
    newfbs_mean: float = -9.0   # unknown FBS team
    eff_w: float = 0.25          # weight on efficiency-based 'deserved' points vs the actual score


def compress(hp, ap, cap, slope):
    m = hp - ap
    am = np.abs(m)
    newm = np.where(am > cap, np.sign(m) * (cap + (am - cap) * slope), m)
    mid = (hp + ap) / 2
    return mid + newm / 2, mid - newm / 2


def solve(games: pd.DataFrame, teams: np.ndarray, prior_o: np.ndarray, prior_d: np.ndarray,
          lam_o: float | np.ndarray, lam_d: float | np.ndarray, p: Params, weights: np.ndarray,
          want_cov: bool = False, mu0: float = 27.5):
    """Weighted ridge solve. Returns O, D, mu (+ per-team net-rating sd if want_cov)."""
    n = len(teams)
    idx = {t: i for i, t in enumerate(teams)}
    k = 2 * n + 1
    if len(games):
        hi = games.home_id.map(idx).to_numpy()
        ai = games.away_id.map(idx).to_numpy()
        neutral = games.neutral_site.to_numpy()
        hp = games.home_points.to_numpy(float)
        ap = games.away_points.to_numpy(float)
        if p.eff_w > 0 and "home_dpts" in games:
            hd = games.home_dpts.to_numpy(float)
            ad = games.away_dpts.to_numpy(float)
            ok = ~(np.isnan(hd) | np.isnan(ad))
            hp = np.where(ok, (1 - p.eff_w) * hp + p.eff_w * np.nan_to_num(hd), hp)
            ap = np.where(ok, (1 - p.eff_w) * ap + p.eff_w * np.nan_to_num(ad), ap)
        hp, ap = compress(hp, ap, p.cap, p.cap_slope)
        h = np.where(neutral, 0.0, p.hfa / 2)
        m = len(games)
        rows = np.arange(2 * m)
        A = np.zeros((2 * m, k))
        # home points row
        A[rows[:m], hi] = 1
        A[rows[:m], n + ai] = -1
        # away points row
        A[rows[m:], ai] = 1
        A[rows[m:], n + hi] = -1
        A[:, 2 * n] = 1
        y = np.concatenate([hp - h, ap + h])
        w = np.concatenate([weights, weights])
        AtW = A.T * w
        M = AtW @ A
        b = AtW @ y
    else:
        M = np.zeros((k, k))
        b = np.zeros(k)
    lo = np.broadcast_to(lam_o, (n,))
    ld = np.broadcast_to(lam_d, (n,))
    reg = np.concatenate([lo, ld, [4.0]])  # league scoring level: ~4 games' worth of pull toward last year
    M = M + np.diag(reg)
    b = b + np.concatenate([lo * prior_o, ld * prior_d, [4.0 * mu0]])
    x = np.linalg.solve(M, b)
    O, D, mu = x[:n], x[n:2 * n], x[2 * n]
    # keep the scale anchored: average FBS-ish team is 0 (mu absorbs the shift)
    if want_cov:
        Minv = np.linalg.inv(M)
        var_net = np.diag(Minv)[:n] + np.diag(Minv)[n:2 * n] - 2 * np.diag(Minv[:n, n:2 * n])
        return O, D, mu, Minv, var_net
    return O, D, mu


def game_weights(games: pd.DataFrame, as_of_wk: int, p: Params) -> np.ndarray:
    age = np.clip(as_of_wk - games.wk.to_numpy(), 0, None)
    w = p.decay ** age
    w = np.where(games.season_type.to_numpy() == "postseason", w * p.post_w, w)
    return w


class SeasonPriors:
    """Builds preseason priors from previous seasons' final ratings."""

    RET = ["qb_ret", "skill_ret", "def_ret", "qb_in", "skill_in", "def_in"]

    def __init__(self, p: Params, ret: pd.DataFrame | None = None, ret_coef: dict | None = None):
        self.p = p
        self.final: dict[int, pd.DataFrame] = {}
        self.final_mu: dict[int, float] = {}
        self.priors: dict[int, pd.DataFrame] = {}
        # returning production, indexed by (season, team_id), centered within season
        self.ret = None
        if ret is not None:
            r = ret.copy()
            for c in self.RET:
                r[c] = r[c] - r.groupby("season")[c].transform("mean")
            self.ret = r.set_index(["season", "team_id"])[self.RET].fillna(0.0)
        self.ret_coef = ret_coef or {}

    def prior(self, season: int, teams: np.ndarray, div: pd.Series, conf: pd.Series):
        p = self.p
        f1 = self.final.get(season - 1)
        f2 = self.final.get(season - 2)
        O = np.zeros(len(teams))
        D = np.zeros(len(teams))
        have = np.zeros(len(teams), bool)
        for i, t in enumerate(teams):
            o1 = d1 = None
            if f1 is not None and t in f1.index:
                o1, d1 = f1.at[t, "O"], f1.at[t, "D"]
            if o1 is None:
                continue
            o2, d2 = (f2.at[t, "O"], f2.at[t, "D"]) if (f2 is not None and t in f2.index) else (o1, d1)
            lr = [self.final[y].loc[t] for y in range(season - 5, season - 2) if y in self.final and t in self.final[y].index]
            o3, d3 = (np.mean([x.O for x in lr]), np.mean([x.D for x in lr])) if lr else (o2, d2)
            O[i] = p.keep1 * o1 + p.keep2 * o2 + p.keep3 * o3
            D[i] = p.keep1 * d1 + p.keep2 * d2 + p.keep3 * d3
            have[i] = True
        # mean-reversion target: the team's current conference average (keeps realignment honest)
        df = pd.DataFrame({"t": teams, "O": O, "D": D, "have": have,
                           "conf": conf.reindex(teams).to_numpy(), "div": div.reindex(teams).to_numpy()})
        base_o = np.zeros(len(teams))
        base_d = np.zeros(len(teams))
        if f1 is not None:
            last = f1.copy()
            last["conf"] = conf.reindex(last.index)
            cm = last.dropna(subset=["conf"]).groupby("conf")[["O", "D"]].mean()
            for i, c in enumerate(df.conf):
                if c in cm.index:
                    base_o[i], base_d[i] = cm.at[c, "O"], cm.at[c, "D"]
                else:
                    tgt = p.fcs_mean if df["div"].iat[i] == "fcs" else p.newfbs_mean
                    base_o[i], base_d[i] = tgt / 2, tgt / 2
        else:
            for i in range(len(teams)):
                tgt = p.fcs_mean if df["div"].iat[i] == "fcs" else 0.0
                base_o[i], base_d[i] = tgt / 2, tgt / 2
        rest = 1 - p.keep1 - p.keep2 - p.keep3
        O = np.where(have, O + rest * base_o, base_o)
        D = np.where(have, D + rest * base_d, base_d)
        # teams with no history get a weaker (less confident) prior
        conf_w = np.where(have, 1.0, 0.5)
        if self.ret is not None and self.ret_coef:
            for i, t in enumerate(teams):
                if (season, t) in self.ret.index:
                    rr = self.ret.loc[(season, t)]
                    O[i] += sum(self.ret_coef.get("o_" + c, 0.0) * rr[c] for c in self.RET)
                    D[i] += sum(self.ret_coef.get("d_" + c, 0.0) * rr[c] for c in self.RET)
        self.priors[season] = pd.DataFrame({"O": O, "D": D, "have": have}, index=teams)
        return O, D, conf_w

    def store_final(self, season: int, teams, O, D):
        self.final[season] = pd.DataFrame({"O": O, "D": D}, index=teams)


def season_meta(season_games: pd.DataFrame):
    """Division and conference of every team in a season."""
    h = season_games[["home_id", "home_division", "home_conference"]].set_axis(["id", "div", "conf"], axis=1)
    a = season_games[["away_id", "away_division", "away_conference"]].set_axis(["id", "div", "conf"], axis=1)
    m = pd.concat([h, a]).drop_duplicates("id", keep="last").set_index("id")
    return m["div"], m["conf"]


def run_season(sg: pd.DataFrame, priors: SeasonPriors, p: Params, keep_snapshots: bool = False):
    """Walk forward through one season.

    Returns a DataFrame of pre-game rating predictions for every game (fit only
    on games from earlier weeks) and, optionally, the rating snapshot taken
    before each week.
    """
    season = int(sg.season.iloc[0])
    div, conf = season_meta(sg)
    teams = np.array(sorted(div.index))
    pO, pD, cw = priors.prior(season, teams, div, conf)
    idx = {t: i for i, t in enumerate(teams)}
    out = []
    snaps = {}
    for wk in sorted(sg.wk.unique()):
        played = sg[(sg.wk < wk) & sg.completed]
        w = game_weights(played, wk, p)
        mu0 = priors.final_mu.get(season - 1, 27.5)
        O, D, mu, Minv, var_net = solve(played, teams, pO, pD, p.lam_o * cw, p.lam_d * cw, p, w, want_cov=True, mu0=mu0)
        # a second, pure-efficiency view (what the box score says, ignoring the scoreboard)
        pe = Params(**{**p.__dict__, "eff_w": 1.0, "cap": 99.0})
        EO, ED, _ = solve(played, teams, pO, pD, p.lam_o * cw, p.lam_d * cw, pe, w, mu0=mu0)
        this = sg[sg.wk == wk]
        hi = this.home_id.map(idx).to_numpy()
        ai = this.away_id.map(idx).to_numpy()
        r = pd.DataFrame({
            "game_id": this.game_id.to_numpy(),
            "h_off": O[hi], "h_def": D[hi], "a_off": O[ai], "a_def": D[ai], "mu": mu,
            "h_sd": np.sqrt(var_net[hi]), "a_sd": np.sqrt(var_net[ai]),
            "n_played": len(played),
        })
        r["rat_margin"] = (O[hi] - D[ai]) - (O[ai] - D[hi])
        r["eff_margin"] = (EO[hi] - ED[ai]) - (EO[ai] - ED[hi])
        r["prior_margin"] = (pO[hi] - pD[ai]) - (pO[ai] - pD[hi])
        r["rat_total"] = 2 * mu + O[hi] - D[ai] + O[ai] - D[hi]
        out.append(r)
        if keep_snapshots:
            snaps[wk] = pd.DataFrame({"O": O, "D": D, "net": O + D, "sd": np.sqrt(var_net), "mu": mu,
                                      "EO": EO, "ED": ED, "pO": pO, "pD": pD}, index=teams)
    # final ratings for next year's prior
    done = sg[sg.completed]
    w = np.where(done.season_type.to_numpy() == "postseason", p.post_w, 1.0)
    O, D, mu = solve(done, teams, pO, pD, p.lam_final * cw, p.lam_final * cw, p, w,
                     mu0=priors.final_mu.get(season - 1, 27.5))
    if len(done) > 0.6 * len(sg):
        priors.store_final(season, teams, O, D)
        priors.final_mu[season] = float(mu)
    res = pd.concat(out, ignore_index=True)
    return (res, snaps, (teams, O, D, mu)) if keep_snapshots else res


def walk_forward(games: pd.DataFrame, p: Params, seasons=None, ret=None, ret_coef=None):
    priors = SeasonPriors(p, ret, ret_coef)
    seasons = seasons or sorted(games.season.unique())
    outs = []
    for s in seasons:
        sg = games[games.season == s]
        outs.append(run_season(sg, priors, p))
    return pd.concat(outs, ignore_index=True).merge(games, on="game_id"), priors
