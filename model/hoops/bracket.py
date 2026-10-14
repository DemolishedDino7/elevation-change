"""March Madness predictor: who gets in, where they're seeded, and who wins.

1. What it takes. For every season since 2013, each team's Selection Sunday résumé
   is rebuilt with what was known that morning: the Bot's rating and rank, record,
   Quadrant 1-4 wins and losses (the committee's NET quadrants, using the Bot's
   rankings), strength of schedule and road/neutral wins. A selection model learns
   which non-champions got at-large bids, and a seed model learns where the field
   was seeded (13 tournaments, 2013-2026).
2. This season. The rest of the regular season (including league games not yet
   posted) and every conference tournament are simulated; each simulated résumé
   goes through the two models. The projected field is the most likely 32
   champions plus the 44 at-large teams most often selected (76-team format from
   2027), seeded on an S-curve and bracketed; the Bot then picks every game and
   simulates the tournament for advancement odds.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import data
import ratings as R

ROOT = Path(__file__).resolve().parent
FIELDS = {int(k): v for k, v in json.load(open(ROOT / "ncaa_fields.json")).items()}
FEATS = ["net", "lrank", "wpct", "q1w", "q1l", "q2w", "q2l", "badl", "sos", "ncsos", "roadw"]
REGIONS = ["East", "South", "Midwest", "West"]
R64 = [(1, 16), (8, 9), (5, 12), (4, 13), (6, 11), (3, 14), (7, 10), (2, 15)]
QCUT = {"home": (30, 75, 160), "neutral": (50, 100, 200), "away": (75, 135, 240)}


def fmt(season):
    """(field size, automatic bids, at-large bids, opening-round games)."""
    return (76, 32, 44, 12) if season >= 2027 else (68, 32, 36, 4)


# ---------------------------------------------------------------- résumés
def _quad(rank: np.ndarray, loc: np.ndarray) -> np.ndarray:
    q = np.full(len(rank), 4)
    for where, cuts in QCUT.items():
        m = loc == where
        q[m] = np.where(rank[m] <= cuts[0], 1, np.where(rank[m] <= cuts[1], 2, np.where(rank[m] <= cuts[2], 3, 4)))
    return q


def long_games(g: pd.DataFrame) -> pd.DataFrame:
    """One row per team per game (both D-I teams only)."""
    g = g[g.home_d1 & g.away_d1]
    h = pd.DataFrame({"game_id": g.game_id.values, "team": g.home_id.values, "opp": g.away_id.values,
                      "loc": np.where(g.neutral, "neutral", "home"), "conf": g.conf_game.values,
                      "pts": g.home_pts.values, "opts": g.away_pts.values, "day": g.day.values})
    a = pd.DataFrame({"game_id": g.game_id.values, "team": g.away_id.values, "opp": g.home_id.values,
                      "loc": np.where(g.neutral, "neutral", "away"), "conf": g.conf_game.values,
                      "pts": g.away_pts.values, "opts": g.home_pts.values, "day": g.day.values})
    return pd.concat([h, a], ignore_index=True)


def resume(g: pd.DataFrame, rank: dict, net: dict, teams) -> pd.DataFrame:
    """Selection Sunday résumé for each team from completed games in g."""
    L = long_games(g[g.completed])
    L = L[L.team.isin(teams)]
    L["orank"] = L.opp.map(rank).fillna(400).to_numpy()
    L["onet"] = L.opp.map(net).fillna(-20).to_numpy()
    L["win"] = (L.pts > L.opts).astype(int)
    L["q"] = _quad(L.orank.to_numpy(), L["loc"].to_numpy())
    agg = L.groupby("team").agg(w=("win", "sum"), n=("win", "size"), sos=("onet", "mean"))
    out = pd.DataFrame(index=pd.Index(list(teams), name="team"))
    out = out.join(agg)
    out["l"] = out.n - out.w
    for q in (1, 2, 3, 4):
        s = L[L.q == q].groupby("team").win
        out[f"q{q}w"], out[f"q{q}l"] = s.sum(), s.count() - s.sum()
    out["ncsos"] = L[~L.conf].groupby("team").onet.mean()
    out["roadw"] = L[(L["loc"] != "home") & (L.win == 1)].groupby("team").size()
    out = out.fillna({"w": 0, "n": 0, "l": 0, "q1w": 0, "q1l": 0, "q2w": 0, "q2l": 0, "q3w": 0, "q3l": 0,
                      "q4w": 0, "q4l": 0, "roadw": 0})
    out["sos"] = out.sos.fillna(0.0)
    out["ncsos"] = out.ncsos.fillna(out.sos)
    out["wpct"] = np.where(out.n > 0, out.w / out.n.clip(lower=1), 0.5)
    out["badl"] = out.q3l + out.q4l
    out["rank"] = pd.Series(rank).reindex(out.index).fillna(400).to_numpy()
    out["net"] = pd.Series(net).reindex(out.index).fillna(-20).to_numpy()
    out["lrank"] = np.log(out["rank"].clip(lower=1))
    return out


def conf_champions(g: pd.DataFrame, before) -> dict:
    """conference id -> champion, from the last game of each conference tournament before `before`."""
    t = g[g.tournament_id.notna() & g.completed & g.conf_game & (g.home_conf == g.away_conf) & (g.day < before)]
    out = {}
    for tid, x in t.sort_values("start").groupby("tournament_id"):
        last = x.iloc[-1]
        out[int(last.home_conf)] = int(last.home_id if last.home_pts > last.away_pts else last.away_id)
    return out


def team_conf(g: pd.DataFrame) -> dict:
    c = pd.concat([g[["home_id", "home_conf"]].set_axis(["t", "c"], axis=1), g[["away_id", "away_conf"]].set_axis(["t", "c"], axis=1)]).dropna()
    return c.groupby("t").c.agg(lambda s: int(s.mode().iat[0])).to_dict()


# ---------------------------------------------------------------- models
class Logit:
    def __init__(self, mu, sd, beta):
        self.mu, self.sd, self.beta = np.array(mu), np.array(sd), np.array(beta)

    @staticmethod
    def fit(X: np.ndarray, y: np.ndarray, l2=1.0) -> "Logit":
        mu, sd = X.mean(0), X.std(0) + 1e-9
        Z = np.column_stack([(X - mu) / sd, np.ones(len(X))])
        b = np.zeros(Z.shape[1])
        P = l2 * np.eye(Z.shape[1]); P[-1, -1] = 0
        for _ in range(50):
            p = 1 / (1 + np.exp(-Z @ b))
            W = p * (1 - p)
            H = Z.T @ (Z * W[:, None]) + P
            step = np.linalg.solve(H, Z.T @ (y - p) - P @ b)
            b += step
            if np.abs(step).max() < 1e-8:
                break
        return Logit(mu, sd, b)

    def score(self, X):
        Z = np.column_stack([(X - self.mu) / self.sd, np.ones(len(X))])
        return Z @ self.beta

    def prob(self, X):
        return 1 / (1 + np.exp(-self.score(X)))


class Linear:
    def __init__(self, mu, sd, beta):
        self.mu, self.sd, self.beta = np.array(mu), np.array(sd), np.array(beta)

    @staticmethod
    def fit(X, y, l2=1.0) -> "Linear":
        mu, sd = X.mean(0), X.std(0) + 1e-9
        Z = np.column_stack([(X - mu) / sd, np.ones(len(X))])
        P = l2 * np.eye(Z.shape[1]); P[-1, -1] = 0
        return Linear(mu, sd, np.linalg.solve(Z.T @ Z + P, Z.T @ y))

    def predict(self, X):
        return np.column_stack([(X - self.mu) / self.sd, np.ones(len(X))]) @ self.beta


def history(g: pd.DataFrame, ratings_asof, current: int) -> pd.DataFrame:
    """Selection Sunday résumé for every D-I team, every season with a tournament.
    ratings_asof(season, day) -> (rank dict, net dict)."""
    rows = []
    for y, f in sorted(FIELDS.items()):
        if y >= current:
            continue
        s = g[g.season == y]
        first = (pd.Timestamp(f["first_game"]) + data.MT).normalize().tz_localize(None)
        sel_day = first - pd.Timedelta(days=1)  # games through Selection Sunday count
        rank, net = ratings_asof(y, sel_day)
        d1 = data.d1_teams(y, current)
        res = resume(s[s.day <= sel_day - pd.Timedelta(days=1)], rank, net, d1)
        champs = conf_champions(s, first)
        conf = team_conf(s[s.conf_game])
        field = {int(k): v["seed"] for k, v in f["teams"].items()}
        # leagues whose final isn't in the data (or old Ivy, no tournament): the conference's
        # lowest-seeded team in the field took the automatic bid (always right for one-bid leagues)
        for c in set(conf.values()):
            ins = [t for t in field if conf.get(t) == c]
            if ins and (c not in champs or champs[c] not in field):
                champs[c] = max(ins, key=lambda t: (field[t] or 0))
        auto = set(champs.values())
        res["season"] = y
        res["conf"] = res.index.map(conf)
        res["in_field"] = res.index.isin(field)
        res["auto"] = res.index.isin(auto) & res.in_field
        res["seed"] = res.index.map(field)
        rows.append(res.reset_index())
    return pd.concat(rows, ignore_index=True)


def fit_models(H: pd.DataFrame):
    al = H[~H.auto]
    sel = Logit.fit(al[FEATS].to_numpy(float), al.in_field.to_numpy(float), l2=1.0)
    fl = H[H.in_field & H.seed.notna()]
    seed = Linear.fit(fl[FEATS].to_numpy(float), fl.seed.to_numpy(float), l2=1.0)
    return sel, seed


def seed_lines(n_field: int, season: int) -> list[int]:
    """Seed line for each S-curve position of the main bracket (64 slots)."""
    return [i // 4 + 1 for i in range(64)]


def backtest(H: pd.DataFrame) -> dict:
    """Leave one season out: fit on the others, pick that year's at-large field and seeds."""
    out, hits, tot, ex, w1, nseed = [], 0, 0, 0, 0, 0
    for y in sorted(H.season.unique()):
        tr, te = H[H.season != y], H[H.season == y].copy()
        sel, seed = fit_models(tr)
        n_al = int(te.in_field.sum() - te.auto.sum())
        cand = te[~te.auto].copy()
        cand["p"] = sel.prob(cand[FEATS].to_numpy(float))
        picked = set(cand.nlargest(n_al, "p").team)
        actual = set(cand[cand.in_field].team)
        h = len(picked & actual)
        # seeds for the actual field, S-curve from the seed model, lines from positions
        fl = te[te.in_field].copy()
        fl["s"] = seed.predict(fl[FEATS].to_numpy(float))
        fl = fl.sort_values("s")
        n = len(fl)
        # 68-team fields: lines 11 and 16 hold six teams (First Four); map positions to lines that way
        caps = [4] * 10 + [6] + [4] * 4 + [6] if n >= 68 else [4] * 16
        lines = sum(([i + 1] * c for i, c in enumerate(caps)), [])[:n]
        lines += [16] * (n - len(lines))
        fl["pl"] = lines
        e = int((fl.pl == fl.seed).sum()); w = int(((fl.pl - fl.seed).abs() <= 1).sum())
        last_in = cand[cand.in_field].sort_values("p").head(1)
        first_out = cand[~cand.in_field].sort_values("p", ascending=False).head(1)
        out.append({"season": f"{y - 1}-{str(y)[2:]}", "at_large": n_al, "hit": h, "seeds": n, "exact": e, "within1": w,
                    "missed_in": [int(t) for t in actual - picked], "wrong_in": [int(t) for t in picked - actual]})
        hits += h; tot += n_al; ex += e; w1 += w; nseed += n
    return {"seasons": out, "hit": hits, "at_large": tot, "exact": ex, "within1": w1, "seeds": nseed}


def what_it_takes(H: pd.DataFrame) -> dict:
    """Plain-numbers history of at-large selection, for the page."""
    al = H[~H.auto]
    rows = []
    for lo, hi in [(1, 25), (26, 40), (41, 50), (51, 60), (61, 75), (76, 100), (101, 400)]:
        m = al[(al["rank"] >= lo) & (al["rank"] <= hi)]
        rows.append({"bucket": f"{lo}-{hi}" if hi < 400 else f"{lo}+", "teams": int(len(m)), "in": int(m.in_field.sum())})
    q1 = []
    for k, lab in [(0, "0"), (1, "1-2"), (3, "3-4"), (5, "5-6"), (7, "7+")]:
        hi = {0: 0, 1: 2, 3: 4, 5: 6, 7: 99}[k]
        m = al[(al.q1w >= k) & (al.q1w <= hi) & (al["rank"] <= 75)]
        q1.append({"q1w": lab, "teams": int(len(m)), "in": int(m.in_field.sum())})
    ins = al[al.in_field]
    per = []
    for y, s in H.groupby("season"):
        a = s[~s.auto]
        i = a[a.in_field]
        per.append({"season": f"{y - 1}-{str(y)[2:]}", "worst_rank_in": int(i["rank"].max()), "best_rank_out": int(a[~a.in_field]["rank"].min()),
                    "avg_q1w": round(float(i.q1w.mean()), 1), "min_wins": int(i.w.min())})
    return {"by_rank": rows, "by_q1": q1, "seasons": per,
            "typical": {"q1w": round(float(ins.q1w.median()), 1), "rank": int(ins["rank"].median()), "badl": round(float(ins.badl.mean()), 1),
                        "worst_rank_ever": int(ins["rank"].max()), "q1w_min": int(ins.q1w.min())}}


# ---------------------------------------------------------------- this season
_erf = np.vectorize(__import__("math").erf, otypes=[float])


def ncdf(x):
    return 0.5 * (1 + _erf(np.asarray(x, float) / np.sqrt(2)))


def project(g, season, cur_rating, idx, ids, conf_of, gm, sel, seed, auto_confs, sims=1000, rng_seed=11, log=print):
    """Simulate the rest of the season + conference tournaments; return per-team bid/seed odds."""
    rng = np.random.default_rng(rng_seed)
    s = g[g.season == season].copy()
    d1 = [int(t) for t in ids if t != data.NON_D1]
    T = len(d1)
    tix = {t: i for i, t in enumerate(d1)}
    O, D, Tm = cur_rating["O"], cur_rating["D"], cur_rating["T"]
    net_all = {int(t): float(O[i] - D[i]) for i, t in enumerate(ids) if t != data.NON_D1}
    order = sorted(net_all, key=lambda t: -net_all[t])
    rank = {t: i + 1 for i, t in enumerate(order)}
    netv = np.array([net_all[t] for t in d1])
    pace_t = np.array([cur_rating["tmu"] + Tm[idx[t]] for t in d1])

    # ---- remaining games (posted) between D-I teams
    rem = s[~s.completed & s.home_d1 & s.away_d1].copy()
    rem = rem[rem.home_id.isin(tix) & rem.away_id.isin(tix)]
    # ---- league games not posted yet: fill each conference up to its usual count
    last = g[(g.season == season - 1) & g.conf_game]
    lastc = pd.concat([last[["home_id", "home_conf"]].set_axis(["t", "c"], axis=1), last[["away_id", "away_conf"]].set_axis(["t", "c"], axis=1)])
    usual = lastc.groupby(["c", "t"]).size().groupby("c").median().to_dict()
    posted = s[s.conf_game & s.home_d1 & s.away_d1]
    syn = []
    sched_posted = {}
    members = {}
    for t, c in conf_of.items():
        if t in tix and c in auto_confs:
            members.setdefault(c, []).append(t)
    for c, mem in members.items():
        n = len(mem)
        target = min(usual.get(c, 2 * (n - 1)), 2 * (n - 1)) if c in usual else 2 * (n - 1)
        pc = posted[(posted.home_id.isin(mem)) & (posted.away_id.isin(mem))]
        have = set(zip(pc.home_id, pc.away_id))
        need_total = target * n / 2 - len(pc)
        pairs = [(h, a) for h in mem for a in mem if h != a and (h, a) not in have]
        if need_total <= 0 or not pairs:
            continue
        sched_posted[c] = round(float(len(pc) / max(target * n / 2, 1)), 2)
        p_incl = min(1.0, need_total / len(pairs))
        for h, a in pairs:
            syn.append((h, a, p_incl))
    # ---- non-conference games not posted yet: each team gets last season's count against
    # opponents as strong as last season's, at home (where most of them are played)
    prev = g[(g.season == season - 1) & g.home_d1 & g.away_d1 & ~g.conf_game & (g.season_type == 2)]
    prev = prev[prev.tournament_id.isna() | ~prev.tournament_id.isin(prev[prev.conf_game].tournament_id.dropna().unique())]
    Lp = long_games(prev)
    Lp["onet"] = Lp.opp.map(lambda t: net_all.get(int(t), np.nan))
    usual_nc = Lp.groupby("team").agg(n=("opp", "size"), onet=("onet", "mean"))
    posted_nc = long_games(s[~s.conf_game & s.home_d1 & s.away_d1]).groupby("team").size()
    xn, xp, xq = np.zeros(T), np.zeros(T), np.full(T, 4)
    sorted_net = np.sort(netv)[::-1]
    for t, i in tix.items():
        u = usual_nc.loc[t] if t in usual_nc.index else None
        target = float(u.n) if u is not None else 11.0
        onet = float(u.onet) if u is not None and not np.isnan(u.onet) else float(np.median(netv))
        miss = max(0.0, target - float(posted_nc.get(t, 0)))
        if miss <= 0:
            continue
        orank = int(np.searchsorted(-sorted_net, -onet)) + 1
        mm = gm.coef["r_margin"] * (netv[i] - onet) * pace_t[i] / 100 + gm.coef["home"]
        xn[i], xp[i], xq[i] = round(miss), float(ncdf(mm / gm.sigma_late)), _quad(np.array([orank]), np.array(["home"]))[0]
    log(f"  bracket: {int(xn.sum())} non-conference games not posted yet, filled from last season's schedules")
    hi = np.array([tix[int(t)] for t in rem.home_id] + [tix[h] for h, a, p in syn], dtype=int)
    ai = np.array([tix[int(t)] for t in rem.away_id] + [tix[a] for h, a, p in syn], dtype=int)
    neu = np.array(list(rem.neutral.astype(bool)) + [False] * len(syn))
    cg = np.array(list(rem.conf_game.astype(bool)) + [True] * len(syn))
    incl_p = np.array([1.0] * len(rem) + [p for _, _, p in syn])
    pace = pace_t[hi] + pace_t[ai] - cur_rating["tmu"]
    m = gm.coef["r_margin"] * (netv[hi] - netv[ai]) * pace / 100 + np.where(neu, 0.0, gm.coef["home"])
    p_home = ncdf(m / gm.sigma_late)
    G = len(hi)
    log(f"  bracket: {len(rem)} posted games left, {len(syn)} league games to be scheduled (weighted)")

    # quadrant of each game for each side (opponent's current rank)
    rk = np.array([rank[t] for t in d1])
    qh = _quad(rk[ai], np.where(neu, "neutral", "home"))
    qa = _quad(rk[hi], np.where(neu, "neutral", "away"))
    # current résumé (completed games)
    base = resume(s[s.day <= s.day.max()], rank, net_all, d1).reindex(d1)
    # schedule strength over the full season (expected)
    sos_full = base.sos.to_numpy()

    feats = {k: np.zeros((sims, T)) for k in ["w", "l", "q1w", "q1l", "q2w", "q2l", "badl", "roadw", "cw", "cl"]}
    for k in ["w", "l", "q1w", "q1l", "q2w", "q2l", "roadw"]:
        feats[k] += base[k].to_numpy()
    feats["badl"] += base.badl.to_numpy()
    cwl = s[s.completed & s.conf_game & s.home_d1 & s.away_d1]
    for _, x in cwl.iterrows():
        if int(x.home_id) in tix and int(x.away_id) in tix:
            hw = x.home_pts > x.away_pts
            feats["cw"][:, tix[int(x.home_id)]] += hw; feats["cl"][:, tix[int(x.home_id)]] += not hw
            feats["cw"][:, tix[int(x.away_id)]] += not hw; feats["cl"][:, tix[int(x.away_id)]] += hw

    U = rng.random((sims, G))
    inc = rng.random((sims, G)) < incl_p
    hw = (U < p_home) & inc
    aw = (~(U < p_home)) & inc

    def add(side_idx, won, lost, q, road):
        for k_w, k_l, qq in (("q1w", "q1l", 1), ("q2w", "q2l", 2)):
            mq = q == qq
            np.add.at(feats[k_w].T, side_idx[mq], won[:, mq].T)
            np.add.at(feats[k_l].T, side_idx[mq], lost[:, mq].T)
        mb = q >= 3
        np.add.at(feats["badl"].T, side_idx[mb], lost[:, mb].T)
        np.add.at(feats["w"].T, side_idx, won.T)
        np.add.at(feats["l"].T, side_idx, lost.T)
        np.add.at(feats["roadw"].T, side_idx[road], won[:, road].T)
    add(hi, hw.astype(float), aw.astype(float), qh, neu)
    add(ai, aw.astype(float), hw.astype(float), qa, np.ones(G, bool))
    xw = rng.binomial(xn.astype(int)[None, :].repeat(sims, 0), xp[None, :].repeat(sims, 0)).astype(float)
    xl = xn[None, :] - xw
    feats["w"] += xw; feats["l"] += xl
    for qq, kw, kl in ((1, "q1w", "q1l"), (2, "q2w", "q2l")):
        m_ = xq == qq
        feats[kw][:, m_] += xw[:, m_]; feats[kl][:, m_] += xl[:, m_]
    feats["badl"][:, xq >= 3] += xl[:, xq >= 3]
    np.add.at(feats["cw"].T, hi[cg], hw[:, cg].T.astype(float)); np.add.at(feats["cl"].T, hi[cg], aw[:, cg].T.astype(float))
    np.add.at(feats["cw"].T, ai[cg], aw[:, cg].T.astype(float)); np.add.at(feats["cl"].T, ai[cg], hw[:, cg].T.astype(float))

    # pairwise neutral win chance for tournaments
    PW = ncdf(gm.coef["r_margin"] * (netv[:, None] - netv[None, :]) * (pace_t[:, None] + pace_t[None, :] - cur_rating["tmu"]) / 100 / gm.sigma_late)

    qn = _quad(rk, np.array(["neutral"] * T))  # quadrant of a neutral-site game against each team
    # regular-season league titles (ties shared) and projected league records, before the tournaments
    rs_title = np.zeros((sims, T))
    for c, mem in members.items():
        mi = np.array([tix[t] for t in mem])
        pct = feats["cw"][:, mi] / np.maximum(feats["cw"][:, mi] + feats["cl"][:, mi], 1)
        best = pct >= pct.max(1, keepdims=True) - 1e-9
        rs_title[:, mi] = best / best.sum(1, keepdims=True)
    exp_cw, exp_cl = feats["cw"].mean(0), feats["cl"].mean(0)
    auto = np.zeros((sims, T), bool)
    cw, cl = feats["cw"], feats["cl"]
    for c, mem in members.items():
        mi = np.array([tix[t] for t in mem])
        n = len(mi)
        size = 4 if c == 12 else n  # Ivy League takes four
        for k in range(sims):
            pct = (cw[k, mi] + 1e-3 * netv[mi]) / np.maximum(cw[k, mi] + cl[k, mi], 1)
            seeded = mi[np.argsort(-pct)][:size]
            alive = list(seeded)
            # single elimination; top seeds get byes up to the next power of two
            while len(alive) > 1:
                p2 = 1 << (len(alive) - 1).bit_length()
                byes = p2 - len(alive)
                top, rest = alive[:byes], alive[byes:]
                nxt = []
                for j in range(len(rest) // 2):
                    a_, b_ = rest[j], rest[-1 - j]
                    wa = rng.random() < PW[a_, b_]
                    win, lose = (a_, b_) if wa else (b_, a_)
                    nxt.append(win)
                    feats["w"][k, win] += 1; feats["l"][k, lose] += 1; feats["roadw"][k, win] += 1
                    qw, ql = qn[lose], qn[win]
                    if qw == 1: feats["q1w"][k, win] += 1
                    elif qw == 2: feats["q2w"][k, win] += 1
                    if ql == 1: feats["q1l"][k, lose] += 1
                    elif ql == 2: feats["q2l"][k, lose] += 1
                    else: feats["badl"][k, lose] += 1
                alive = top + sorted(nxt, key=lambda t: list(seeded).index(t))
            auto[k, alive[0]] = True

    n = feats["w"] + feats["l"]
    X = np.stack([
        np.broadcast_to(netv, (sims, T)), np.broadcast_to(np.log(rk), (sims, T)),
        np.where(n > 0, feats["w"] / np.maximum(n, 1), 0.5), feats["q1w"], feats["q1l"], feats["q2w"], feats["q2l"], feats["badl"],
        np.broadcast_to(sos_full, (sims, T)), np.broadcast_to(base.ncsos.to_numpy(), (sims, T)), feats["roadw"]], -1)
    _, _, n_al, _ = fmt(season)
    selp = sel.score(X.reshape(-1, X.shape[-1])).reshape(sims, T)
    seedp = seed.predict(X.reshape(-1, X.shape[-1])).reshape(sims, T)
    in_al = np.zeros((sims, T), bool)
    sc = np.where(auto, -np.inf, selp)
    top = np.argpartition(-sc, n_al, axis=1)[:, :n_al]
    np.put_along_axis(in_al, top, True, axis=1)
    in_f = in_al | auto
    seed_mean = np.where(in_f, seedp, np.nan)
    import warnings
    with warnings.catch_warnings(), np.errstate(invalid="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        avg_seed = np.nanmean(seed_mean, 0)
    out = pd.DataFrame({"team": d1, "p_bid": in_f.mean(0), "p_auto": auto.mean(0), "p_atlarge": in_al.mean(0),
                        "seed_score": avg_seed, "sel_score": selp.mean(0),
                        "exp_w": feats["w"].mean(0), "exp_l": feats["l"].mean(0), "exp_q1w": feats["q1w"].mean(0),
                        "exp_q1l": feats["q1l"].mean(0), "rank": rk, "net": netv, "conf": [conf_of.get(t) for t in d1]})
    out["p_rs_title"], out["exp_cw"], out["exp_cl"] = rs_title.mean(0), exp_cw, exp_cl
    for k in ("q1w", "q1l", "q2w", "q2l", "badl", "w", "l"):
        out[k + "_now"] = base[k].to_numpy()
    out.attrs["sched_posted"] = {c: sched_posted.get(c, 1.0) for c in members}
    # "to be safe": Quad 1 wins an at-large résumé like this one needs for a 90% chance
    Xm = X.mean(0)
    qi = FEATS.index("q1w")
    safe = np.full(T, np.nan)
    for q in range(0, 16):
        Xq = Xm.copy()
        Xq[:, qi] = q
        ok = (sel.prob(Xq) >= 0.9) & np.isnan(safe)
        safe[ok] = q
    out["safe_q1w"] = safe
    out.attrs["PW"] = PW
    out.attrs["tix"] = tix
    return out


def build_bracket(P: pd.DataFrame, season: int, auto_confs: set) -> dict:
    """Most likely field -> S-curve -> opening round -> regions."""
    n_field, n_auto, n_al, n_or = fmt(season)
    P = P.copy()
    champs = []
    for c in sorted(auto_confs):
        m = P[P.conf == c]
        if len(m):
            champs.append(int(m.sort_values(["p_auto", "net"], ascending=False).team.iloc[0]))
    rest = P[~P.team.isin(champs)].sort_values(["p_bid", "sel_score"], ascending=False)
    at_large = [int(t) for t in rest.team.head(n_al)]
    bubble_in = [int(t) for t in rest.team.iloc[n_al - 4:n_al]][::-1]
    out_ = [int(t) for t in rest.team.iloc[n_al:n_al + 8]]
    field = P[P.team.isin(champs + at_large)].copy()
    field["auto"] = field.team.isin(champs)
    field["seed_score"] = field.seed_score.fillna(17.0)
    field = field.sort_values(["seed_score", "net"], ascending=[True, False]).reset_index(drop=True)
    field["overall"] = np.arange(1, len(field) + 1)
    # opening round: the lowest automatic qualifiers and the lowest at-large teams, paired with the closest on the list
    k = n_or  # games
    low_auto = field[field.auto].tail(k).overall.tolist()
    low_al = field[~field.auto].tail(k).overall.tolist()
    games = []
    for grp in (low_auto, low_al):
        for j in range(0, len(grp), 2):
            games.append(sorted(grp[j:j + 2]))
    # slots: every team not in the opening round, plus one slot per opening-round game
    in_or = {o for gm in games for o in gm}
    slots = [("team", o) for o in field.overall if o not in in_or] + [("or", i) for i in range(len(games))]
    slot_pos = {s_: (s_[1] if s_[0] == "team" else games[s_[1]][0]) for s_ in slots}
    slots.sort(key=lambda s_: slot_pos[s_])
    slots = slots[:64]
    # seed lines and regions (S-curve: line 1 left to right, line 2 right to left, ...)
    import itertools
    regions = {r: {} for r in REGIONS}
    seed_of = {}
    t_of = dict(zip(field.overall, field.team))
    c_of = dict(zip(field.overall, field.conf))
    placed = {r: [] for r in REGIONS}  # (conf, line) already in each region

    def confs(s_):
        return [c_of[s_[1]]] if s_[0] == "team" else [c_of[o] for o in games[s_[1]]]
    assign = {}
    for line in range(1, 17):
        group = slots[(line - 1) * 4: line * 4]
        snake = REGIONS if line % 2 == 1 else REGIONS[::-1]
        best, best_cost = None, None
        for perm in itertools.permutations(range(len(group))):
            cost = 0.0
            for j, s_ in enumerate(group):
                reg = snake[perm[j]]
                for c in confs(s_):
                    for c2, l2 in placed[reg]:
                        if c2 == c:
                            cost += 100 if (line <= 4 and l2 <= 4) else (3 if line + l2 == 17 or abs(line - l2) <= 1 else 1)
                cost += 0.05 * abs(perm[j] - j)  # stay close to the S-curve
            if best_cost is None or cost < best_cost:
                best, best_cost = perm, cost
        for j, s_ in enumerate(group):
            reg = snake[best[j]]
            assign[s_] = (line, reg)
            placed[reg] += [(c, line) for c in confs(s_)]
    for i, s_ in enumerate(slots):
        line, reg = assign[s_]
        regions[reg][line] = s_
        if s_[0] == "team":
            seed_of[s_[1]] = (line, reg)
        else:
            for o in games[s_[1]]:
                seed_of[o] = (line, reg)
    team_of = dict(zip(field.overall, field.team))
    return {"field": field, "games": games, "regions": regions, "seed_of": seed_of, "team_of": team_of,
            "champs": champs, "at_large": at_large, "last_in": bubble_in, "first_out": out_[:4], "next_out": out_[4:8]}


def play(B: dict, P: pd.DataFrame, sims=20000, rng_seed=5):
    """Bot picks every game (higher win chance) and simulates the tournament for advancement odds."""
    PW, tix = P.attrs["PW"], P.attrs["tix"]
    team_of, games = B["team_of"], B["games"]
    rng = np.random.default_rng(rng_seed)

    def p(a, b):
        return PW[tix[a], tix[b]]

    or_games = []
    for i, (o1, o2) in enumerate(games):
        a, b = team_of[o1], team_of[o2]
        or_games.append({"a": a, "b": b, "p": p(a, b), "pick": a if p(a, b) >= 0.5 else b})
    # bracket order of the 64 slots: per region, R64 pairs
    entries = []  # (region, seed, slot)
    for reg in REGIONS:
        for s1, s2 in R64:
            entries.append((reg, s1, B["regions"][reg][s1]))
            entries.append((reg, s2, B["regions"][reg][s2]))

    def slot_team(slot, pick_mode, k=None, or_res=None):
        if slot[0] == "team":
            return team_of[slot[1]]
        gmi = or_games[slot[1]]
        return gmi["pick"] if pick_mode else or_res[slot[1]]

    # Bot's picks (deterministic)
    rounds = []
    cur = [slot_team(e[2], True) for e in entries]
    seeds = [e[1] for e in entries]
    regs = [e[0] for e in entries]
    names_r = ["Round of 64", "Round of 32", "Sweet 16", "Elite 8", "Final Four", "Championship"]
    alive = list(zip(cur, seeds, regs))
    for rn in names_r:
        nxt, gl = [], []
        for j in range(0, len(alive), 2):
            (a, sa, ra), (b, sb, rb) = alive[j], alive[j + 1]
            pa = p(a, b)
            w = (a, sa, ra) if pa >= 0.5 else (b, sb, rb)
            gl.append({"a": a, "sa": sa, "b": b, "sb": sb, "region": ra if ra == rb else None, "pa": round(float(pa), 3), "pick": w[0]})
            nxt.append(w)
        rounds.append({"round": rn, "games": gl})
        alive = nxt
    champion = alive[0][0]

    # simulations
    teams = sorted({team_of[o] for o in team_of})
    adv = {t: np.zeros(7) for t in teams}  # made R64, R32, S16, E8, F4, title game, champion
    S = sims
    or_res = np.array([[g_["a"] if r < g_["p"] else g_["b"] for r in rng.random(S)] for g_ in or_games]).T if or_games else None
    for k in range(S):
        al_ = [team_of[e[2][1]] if e[2][0] == "team" else or_res[k, e[2][1]] for e in entries]
        for t in al_:
            adv[t][0] += 1
        r = 1
        while len(al_) > 1:
            u = rng.random(len(al_) // 2)
            al_ = [al_[2 * j] if u[j] < p(al_[2 * j], al_[2 * j + 1]) else al_[2 * j + 1] for j in range(len(al_) // 2)]
            for t in al_:
                adv[t][r] += 1
            r += 1
    adv = {t: (v / S).round(4).tolist() for t, v in adv.items()}
    return or_games, rounds, champion, adv
