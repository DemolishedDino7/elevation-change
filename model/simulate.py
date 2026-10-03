"""Monte Carlo season simulation.

Each simulated season first draws how good every team *really* is (its
rating plus a shock sized to the model's uncertainty about it), then plays
out every remaining game with that draw, so a team that is secretly better
than we think tends to win several more games, not just one. Then it seats
the conference title games, crowns champions, and picks the highest-ranked
Group of Six champion for the CFP's automatic bid.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

G6 = {"American Athletic", "Conference USA", "Mid-American", "Mountain West", "Pac-12", "Sun Belt"}
P4 = {"SEC", "Big Ten", "ACC", "Big 12"}
SCORE_SD = 11.0  # points of noise per team-score observation (scales rating uncertainty)


def simulate(teams: pd.DataFrame, done: pd.DataFrame, remaining: pd.DataFrame, n: int = 10000, seed: int = 7):
    """
    teams:     index team_id; columns name, conf, div, net, sd
    done:      completed games (home_id, away_id, margin, conference_game)
    remaining: future games with pred_margin, sigma, conference_game, home_id, away_id
    """
    rng = np.random.default_rng(seed)
    ids = teams.index.to_numpy()
    pos = {t: i for i, t in enumerate(ids)}
    T = len(ids)
    tau = np.clip(teams.sd.to_numpy() * SCORE_SD, 1.5, 9.0)

    wins = np.zeros((n, T), np.int16)
    losses = np.zeros((n, T), np.int16)
    cwins = np.zeros((n, T), np.int16)
    closs = np.zeros((n, T), np.int16)

    # completed games are fixed
    for _, g in done.iterrows():
        h, a = pos.get(g.home_id), pos.get(g.away_id)
        hw = g.margin > 0
        for t, w in ((h, hw), (a, not hw)):
            if t is None:
                continue
            if w:
                wins[:, t] += 1
                if g.conference_game:
                    cwins[:, t] += 1
            else:
                losses[:, t] += 1
                if g.conference_game:
                    closs[:, t] += 1

    shock = rng.normal(0, 1, (n, T)) * tau
    if len(remaining):
        hi = remaining.home_id.map(pos).to_numpy()
        ai = remaining.away_id.map(pos).to_numpy()
        hv = ~pd.isna(hi)
        av = ~pd.isna(ai)
        hi = np.where(hv, hi, 0).astype(int)
        ai = np.where(av, ai, 0).astype(int)
        mu = remaining.pred_margin.to_numpy()
        sh = np.where(hv, shock[:, hi], 0) - np.where(av, shock[:, ai], 0)
        sig_g = np.sqrt(np.clip(remaining.sigma.to_numpy() ** 2 - tau[hi] ** 2 * hv - tau[ai] ** 2 * av, 64, None))
        m = mu + sh + rng.normal(0, 1, (n, len(remaining))) * sig_g
        hw = m > 0
        conf = remaining.conference_game.to_numpy()
        for j in range(len(remaining)):
            w = hw[:, j]
            if hv[j]:
                wins[:, hi[j]] += w
                losses[:, hi[j]] += ~w
                if conf[j]:
                    cwins[:, hi[j]] += w
                    closs[:, hi[j]] += ~w
            if av[j]:
                wins[:, ai[j]] += ~w
                losses[:, ai[j]] += w
                if conf[j]:
                    cwins[:, ai[j]] += ~w
                    closs[:, ai[j]] += w

    true_net = teams.net.to_numpy()[None, :] + shock
    conf_of = teams.conf.to_numpy()
    fbs = teams["div"].to_numpy() == "fbs"
    champ = np.zeros((n, T), bool)
    in_ccg = np.zeros((n, T), bool)
    sig_ccg = 15.5
    for c in sorted(set(conf_of[fbs])):
        if c in ("FBS Independents",) or c is None:
            continue
        members = np.where((conf_of == c) & fbs)[0]
        if len(members) < 4:
            continue
        cg = cwins[:, members] + closs[:, members]
        pct = np.where(cg > 0, cwins[:, members] / np.maximum(cg, 1), 0.0)
        # tiebreak: overall wins, then (simulated) team quality
        key = pct * 1000 + wins[:, members] * 10 + true_net[:, members] / 100
        order = np.argsort(-key, axis=1)
        s1 = members[order[:, 0]]
        s2 = members[order[:, 1]]
        rows = np.arange(n)
        in_ccg[rows, s1] = True
        in_ccg[rows, s2] = True
        hfa = 0.0 if c in P4 else 2.2  # G6 title games are usually hosted by the top seed
        mm = true_net[rows, s1] - true_net[rows, s2] + hfa + rng.normal(0, sig_ccg - 3, n)
        w1 = mm > 0
        win_t = np.where(w1, s1, s2)
        lose_t = np.where(w1, s2, s1)
        champ[rows, win_t] = True
        wins[rows, win_t] += 1
        losses[rows, lose_t] += 1

    # CFP auto-bid: highest-ranked G6 champion (committee proxy: fewest losses, then quality)
    g6 = np.isin(conf_of, list(G6)) & fbs
    g6champ = champ & g6[None, :]
    key = np.where(g6champ, -losses * 100 + true_net, -1e9)
    auto = np.zeros((n, T), bool)
    auto[np.arange(n), np.argmax(key, axis=1)] = True
    auto &= g6champ

    out = pd.DataFrame(index=ids)
    out["exp_wins"] = wins.mean(0)
    out["exp_losses"] = losses.mean(0)
    out["exp_conf_wins"] = cwins.mean(0)
    out["exp_conf_losses"] = closs.mean(0)
    out["bowl_elig"] = (wins >= 6).mean(0)
    out["ccg"] = in_ccg.mean(0)
    out["conf_title"] = champ.mean(0)
    out["cfp_autobid"] = auto.mean(0)
    out["undefeated"] = (losses == 0).mean(0)
    # win distribution (0..15)
    dist = np.stack([(wins == k).mean(0) for k in range(16)], axis=1)
    out["win_dist"] = list(np.round(dist, 4))
    return out
