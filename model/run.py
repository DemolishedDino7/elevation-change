"""The Bot — weekly pipeline.

    python model/run.py            # full refresh: download, refit, predict, simulate, write bot/*.json

Writes everything the site reads into bot/:
    meta.json         when it ran, season/week, backtest scorecard
    predictions.json  every game this season (pre-game prediction + result where final)
    ratings.json      power ratings + season simulations (wins, bowl, conf title, CFP auto-bid)
                      for every FBS team and every team Elevation Change covers
    record.json       live scorecard: straight-up, vs Vegas (when lines exist), vs The Boys
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data  # noqa: E402
import plays  # noqa: E402
import returning  # noqa: E402
from game_model import GameModel, add_games_played  # noqa: E402
from ratings import Params, SeasonPriors, game_weights, run_season, season_meta, solve, walk_forward  # noqa: E402
from simulate import simulate  # noqa: E402
import index_feed  # noqa: E402
import ncaa  # noqa: E402

SITE = Path(__file__).resolve().parent.parent
OUT = SITE / "bot"
LAUNCH = {2026: 6}
# Elevation Index switches from the hand-entered Week 4 data to the automatic feed (Sun Oct 4, 5am MT),
# and only once every game our teams played before then is final in the data
INDEX_SWITCH = datetime(2026, 10, 4, 11, 0, tzinfo=timezone.utc)  # Sun Oct 4, 5am MT

# Elevation Change coverage: site id -> data name
WEST = {
    "AFA": "Air Force", "HAW": "Hawai'i", "NEV": "Nevada", "UNM": "New Mexico", "NDSU": "North Dakota State",
    "NIU": "Northern Illinois", "SJSU": "San José State", "UNLV": "UNLV", "UTEP": "UTEP", "WYO": "Wyoming",
    "BSU": "Boise State", "CSU": "Colorado State", "FRES": "Fresno State", "ORST": "Oregon State",
    "SDSU": "San Diego State", "TXST": "Texas State", "USU": "Utah State", "WSU": "Washington State",
    "NMSU": "New Mexico State", "SAC": "Sacramento State",
}
WEST_BY_NAME = {v: k for k, v in WEST.items()}


def log(*a):
    print(f"[{datetime.now().strftime('%H:%M:%S')}]", *a, flush=True)


def current_season(now: datetime) -> int:
    return now.year if now.month >= 7 else now.year - 1


def cfbd_lines(season: int) -> pd.DataFrame | None:
    """Optional: live Vegas consensus from CollegeFootballData.com when CFBD_API_KEY is set."""
    key = os.environ.get("CFBD_API_KEY")
    if not key:
        return None
    try:
        req = urllib.request.Request(f"https://api.collegefootballdata.com/lines?year={season}",
                                     headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
        rows = []
        for gm in json.load(urllib.request.urlopen(req, timeout=60)):
            sp = [l.get("spread") for l in gm.get("lines", []) if l.get("spread") is not None]
            ou = [l.get("overUnder") for l in gm.get("lines", []) if l.get("overUnder") is not None]
            if sp:
                rows.append({"game_id": int(gm["id"]), "vegas_spread": float(np.median(sp)),
                             "vegas_total": float(np.median(ou)) if ou else np.nan})
        log(f"CFBD lines: {len(rows)} games")
        return pd.DataFrame(rows).set_index("game_id") if rows else None
    except Exception as e:  # never let the optional feed break the run
        log("CFBD lines unavailable:", e)
        return None


def r1(x, nd=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def bot_score(ph: float, pa: float):
    """Whole-number score for The Boys vs. The Bot, never a tie, winner preserved."""
    h, a = int(round(ph)), int(round(pa))
    if h == a:
        if ph >= pa:
            h += 1
        else:
            a += 1
    if (h > a) != (ph >= pa):
        h, a = a, h
    return max(h, 0), max(a, 0)


def contest_points(pick_h, pick_a, act_h, act_a):
    return abs(pick_h - act_h) + abs(pick_a - act_a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--sims", type=int, default=10000)
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    season = args.season or current_season(now)
    OUT.mkdir(exist_ok=True)

    if not args.no_download:
        log("downloading data")
        data.download(season)
        plays.download(2014, season)

    log("building games")
    g = data.build_games(season)
    # same-night finals and official box scores from NCAA.com (the archive lags a day)
    sg0 = g[(g.season == season) & (g.season_type == "regular")]
    pend = sg0[~sg0.completed]
    wk_now = int(pend.week.min()) if len(pend) else int(sg0.week.max())
    g, ncaa_ids, ncaa_status = ncaa.patch(g, season, sorted({max(1, wk_now - 1), wk_now}), log=log)
    if season in g.season.values:
        # ids for every earlier week too, so the Index can use official box scores all season
        try:
            more = []
            for w in range(1, max(1, wk_now - 1)):
                more += ncaa.scoreboard(season, w)
            for idx, m in ncaa.match(more, g[g.season == season]):
                ncaa_ids.setdefault(int(g.at[idx, "game_id"]), {"contest": int(m["contest"]["contestId"]),
                                                               "home_seo": m["home"]["seoname"], "away_seo": m["away"]["seoname"]})
        except Exception as e:
            log("NCAA history unavailable:", repr(e)[:200])
    eff = plays.efficiency_table(2014, season)
    dcoef = plays.fit_deserved(eff, g, range(2014, 2020))
    g = g.join(plays.deserved_points(eff, g, dcoef), on="game_id")
    g = plays.attach_pace(g, eff)
    ti, _ = data.team_info(season)
    ret = returning.table(2015, season)
    ret = ret.merge(ti[["season", "school", "team_id"]].drop_duplicates(["season", "school"]), on=["season", "school"])
    p = Params()
    hist_seasons = list(range(data.FIRST_SEASON, season))

    # Pass A: learn how much returning / transfer production moves a team (from history only)
    log("fitting returning-production effects")
    _, priA = walk_forward(g[g.season < season], p, hist_seasons, ret=ret, ret_coef={})
    rows = []
    for s in range(2015, season):
        if s == 2020 or s not in priA.final or s not in priA.priors:
            continue
        f, pr = priA.final[s], priA.priors[s]
        rr = priA.ret.xs(s, level=0) if s in priA.ret.index.get_level_values(0) else None
        if rr is None:
            continue
        d = (f - pr[["O", "D"]]).join(rr, how="inner")
        rows.append(d[pr.loc[d.index, "have"]])
    D = pd.concat(rows)
    X = np.column_stack([np.ones(len(D)), D[SeasonPriors.RET].to_numpy()])
    ret_coef = {}
    for side in ("O", "D"):
        b = np.linalg.lstsq(X, D[side].to_numpy(), rcond=None)[0]
        ret_coef.update({f"{side.lower()}_{c}": float(v) for c, v in zip(SeasonPriors.RET, b[1:])})

    # Pass B: walk-forward history with the full prior -> stage-two training data
    log("walk-forward history")
    oos, pri = walk_forward(g[g.season < season], p, hist_seasons, ret=ret, ret_coef=ret_coef)
    oos = add_games_played(oos, g)
    train = oos[oos.completed & (oos.season >= 2013) & (oos.season != 2020)]
    gm = GameModel.fit(train)

    # honest scorecard: stage two fit only on seasons before the test window
    gm_bt = GameModel.fit(train[train.season <= 2021])
    te = oos[oos.completed & (oos.season >= 2022)].copy()
    te = te.join(gm_bt.predict(te))
    fb = te[(te.home_division == "fbs") & (te.away_division == "fbs") & te.vegas_spread.notna()]
    tot = fb.dropna(subset=["vegas_total"])
    d = fb.pred_margin + fb.vegas_spread
    ats = fb[(d != 0) & ((fb.margin + fb.vegas_spread) != 0)]
    backtest = {
        "seasons": f"2022–{season - 1}", "games": int(len(fb)),
        "model_mae": r1((fb.pred_margin - fb.margin).abs().mean(), 2),
        "vegas_mae": r1((fb.margin + fb.vegas_spread).abs().mean(), 2),
        "model_su": r1(((fb.pred_margin > 0) == (fb.margin > 0)).mean() * 100, 1),
        "vegas_su": r1(((fb.vegas_spread < 0) == (fb.margin > 0)).mean() * 100, 1),
        "model_total_mae": r1((tot.pred_total - tot.total).abs().mean(), 2),
        "vegas_total_mae": r1((tot.vegas_total - tot.total).abs().mean(), 2),
        "ats": r1((np.sign(ats.margin + ats.vegas_spread) == np.sign(ats.pred_margin + ats.vegas_spread)).mean() * 100, 1),
        "brier": r1(((fb.margin > 0) - fb.home_wp).pow(2).mean(), 3),
        "by_season": [
            {"season": int(s), "games": int(len(x)),
             "model_mae": r1((x.pred_margin - x.margin).abs().mean(), 2),
             "vegas_mae": r1((x.margin + x.vegas_spread).abs().mean(), 2),
             "model_su": r1(((x.pred_margin > 0) == (x.margin > 0)).mean() * 100, 1)}
            for s, x in fb.groupby("season")],
    }
    # calibration table for the record page
    bins = np.linspace(0, 1, 11)
    fav = np.maximum(fb.home_wp, 1 - fb.home_wp)
    fav_won = np.where(fb.home_wp >= 0.5, fb.margin > 0, fb.margin < 0)
    cal = []
    for lo, hi in zip(bins[5:-1], bins[6:]):
        m = (fav >= lo) & (fav < hi if hi < 1 else fav <= hi)
        if m.sum() >= 20:
            cal.append({"bin": f"{int(lo*100)}–{int(hi*100)}%", "pred": r1(fav[m].mean() * 100), "actual": r1(fav_won[m].mean() * 100), "games": int(m.sum())})
    backtest["calibration"] = cal
    log("backtest", {k: v for k, v in backtest.items() if k not in ("by_season", "calibration")})

    # Current season: walk-forward (backfill) + live ratings
    log("current season")
    sg = g[g.season == season].copy()
    cur_oos, snaps, _ = run_season(sg, pri, p, keep_snapshots=True)
    cur_oos = add_games_played(cur_oos.merge(sg, on="game_id"), g)
    cur_oos = cur_oos.join(gm.predict(cur_oos))
    pending = sg[~sg.completed]
    cur_wk = int(pending.wk.min()) if len(pending) else int(sg.wk.max()) + 1
    div, conf = season_meta(sg)
    teams = np.array(sorted(div.index))
    pr = pri.priors[season].reindex(teams)
    cw = np.where(pr.have.fillna(False).to_numpy(bool), 1.0, 0.5)
    played = sg[sg.completed]
    w = game_weights(played, cur_wk, p)
    mu0 = pri.final_mu.get(season - 1, 27.5)
    O, D, mu, Minv, var_net = solve(played, teams, pr.O.to_numpy(), pr.D.to_numpy(), p.lam_o * cw, p.lam_d * cw, p, w, want_cov=True, mu0=mu0)
    pe = Params(**{**p.__dict__, "eff_w": 1.0, "cap": 99.0})
    EO, ED, _ = solve(played, teams, pr.O.to_numpy(), pr.D.to_numpy(), p.lam_o * cw, p.lam_d * cw, pe, w, mu0=mu0)
    idx = {t: i for i, t in enumerate(teams)}

    # live predictions for every unplayed game
    fut = pending.copy()
    hi, ai = fut.home_id.map(idx).to_numpy(), fut.away_id.map(idx).to_numpy()
    fut["h_off"], fut["h_def"], fut["a_off"], fut["a_def"], fut["mu"] = O[hi], D[hi], O[ai], D[ai], mu
    fut["rat_margin"] = (O[hi] - D[ai]) - (O[ai] - D[hi])
    fut["eff_margin"] = (EO[hi] - ED[ai]) - (EO[ai] - ED[hi])
    fut["rat_total"] = 2 * mu + O[hi] - D[ai] + O[ai] - D[hi]
    fut = add_games_played(fut, g)
    fut = fut.join(gm.predict(fut))

    lines = cfbd_lines(season)
    if lines is not None:
        for c in ("vegas_spread", "vegas_total"):
            sg[c] = sg.game_id.map(lines[c])
            fut[c] = fut.game_id.map(lines[c])
            cur_oos[c] = cur_oos.game_id.map(lines[c])

    # lock pre-kickoff predictions so the record can't be rewritten after the fact
    lock_path = OUT / "locked.json"
    locked = json.load(open(lock_path)) if lock_path.exists() else {}
    for _, x in fut.iterrows():
        if pd.notna(x.start) and x.start > now:
            bh, ba = bot_score(x.pred_home, x.pred_away)
            locked[str(int(x.game_id))] = {
                "pred_margin": r1(x.pred_margin, 2), "pred_total": r1(x.pred_total, 2), "home_wp": r1(x.home_wp, 4),
                "pred_home": bh, "pred_away": ba, "made": now.isoformat(timespec="minutes"),
                "vegas_spread": r1(x.get("vegas_spread"), 1), "vegas_total": r1(x.get("vegas_total"), 1)}
    json.dump(locked, open(lock_path, "w"), indent=0, sort_keys=True)

    # ---------------- ratings.json ----------------
    tinfo = ti[ti.season == season].drop_duplicates("team_id").set_index("team_id")
    rec = {t: [0, 0, 0, 0] for t in teams}
    for _, x in played.iterrows():
        hw = x.margin > 0
        for t, won in ((x.home_id, hw), (x.away_id, not hw)):
            if t in rec:
                rec[t][0 if won else 1] += 1
                if x.conference_game:
                    rec[t][2 if won else 3] += 1
    prev_wk = max([k for k in snaps if k < cur_wk], default=None)
    prev = snaps.get(prev_wk) if prev_wk is not None else None
    T = pd.DataFrame({"team_id": teams, "O": O, "D": D, "net": O + D, "sd": np.sqrt(var_net)})
    T["name"] = T.team_id.map(tinfo.school).fillna(T.team_id.map(dict(zip(sg.home_id, sg.home_team)))).fillna(T.team_id.map(dict(zip(sg.away_id, sg.away_team))))
    T["conf"] = T.team_id.map(conf)
    T["div"] = T.team_id.map(div)
    fbs = T[T["div"] == "fbs"].sort_values("net", ascending=False).copy()
    fbs["rank"] = np.arange(1, len(fbs) + 1)
    if prev is not None:
        pn = prev.net.reindex(fbs.team_id)
        prank = pn.rank(ascending=False, method="first").to_numpy()
        fbs["prev_rank"] = prank
    T = T.merge(fbs[["team_id", "rank"] + (["prev_rank"] if prev is not None else [])], on="team_id", how="left")
    T["off_rank"] = T.O.where(T["div"] == "fbs").rank(ascending=False, method="min")
    T["def_rank"] = T.D.where(T["div"] == "fbs").rank(ascending=False, method="min")

    # ---------------- simulations ----------------
    log(f"simulating {args.sims} seasons")
    sim_teams = T.set_index("team_id")[["name", "conf", "div", "net", "sd"]]
    reg_left = fut[fut.season_type == "regular"]
    odds = simulate(sim_teams, played[played.season_type == "regular"], reg_left, n=args.sims)
    T = T.join(odds, on="team_id")

    def team_obj(r):
        t = int(r.team_id)
        site = WEST_BY_NAME.get(r["name"])
        return {
            "id": t, "name": r["name"], "abbr": site or (tinfo.abbreviation.get(t) if t in tinfo.index else None),
            "conf": r.conf, "div": r["div"], "west": bool(site),
            "logo": f"logos/{site}.png" if site else (tinfo.logo.get(t) if t in tinfo.index else None),
            "color": tinfo.color.get(t) if t in tinfo.index else None,
            "rank": None if pd.isna(r["rank"]) else int(r["rank"]),
            "prev_rank": None if "prev_rank" not in r or pd.isna(r.get("prev_rank")) else int(r["prev_rank"]),
            "net": r1(r.net), "off": r1(r.O), "def": r1(r.D), "sd": r1(r.sd * 11.0),
            "off_rank": None if pd.isna(r.off_rank) else int(r.off_rank),
            "def_rank": None if pd.isna(r.def_rank) else int(r.def_rank),
            "w": rec[t][0], "l": rec[t][1], "cw": rec[t][2], "cl": rec[t][3],
            "exp_w": r1(r.exp_wins), "exp_l": r1(r.exp_losses), "exp_cw": r1(r.exp_conf_wins), "exp_cl": r1(r.exp_conf_losses),
            "bowl": r1(r.bowl_elig, 4), "ccg": r1(r.ccg, 4), "title": r1(r.conf_title, 4), "cfp": r1(r.cfp_autobid, 4),
            "unbeaten": r1(r.undefeated, 4),
            "win_dist": [r1(v, 4) for v in r.win_dist] if isinstance(r.win_dist, (list, np.ndarray)) else None,
        }

    team_list = [team_obj(r) for _, r in T.iterrows() if r["div"] == "fbs" or r["name"] in WEST_BY_NAME]
    team_list.sort(key=lambda x: (x["rank"] is None, x["rank"] or 999, -(x["net"] or -99)))

    # ---------------- predictions.json ----------------
    games_out = []
    oos_by = cur_oos.set_index("game_id")
    fut_by = fut.set_index("game_id")
    for _, x in sg.sort_values(["wk", "start"]).iterrows():
        gid = int(x.game_id)
        src = fut_by.loc[gid] if gid in fut_by.index else oos_by.loc[gid]
        lk = locked.get(str(gid))
        launch = LAUNCH.get(season, 99)
        live = x.wk >= launch and lk is not None
        if x.completed and live:
            ph, pa, pm, pt, wp = lk["pred_home"], lk["pred_away"], lk["pred_margin"], lk["pred_total"], lk["home_wp"]
            vs, vt = lk.get("vegas_spread"), lk.get("vegas_total")
        else:
            ph, pa = bot_score(src.pred_home, src.pred_away)
            pm, pt, wp = r1(src.pred_margin, 2), r1(src.pred_total, 2), r1(src.home_wp, 4)
            vs, vt = r1(x.get("vegas_spread")), r1(x.get("vegas_total"))
        games_out.append({
            "id": gid, "week": int(x.week), "type": x.season_type, "start": x.start.isoformat() if pd.notna(x.start) else None,
            "neutral": bool(x.neutral_site), "conf_game": bool(x.conference_game), "venue": x.venue,
            "home": x.home_team, "away": x.away_team, "home_id": int(x.home_id), "away_id": int(x.away_id),
            "home_west": x.home_team in WEST_BY_NAME, "away_west": x.away_team in WEST_BY_NAME,
            "pred_home": ph, "pred_away": pa, "pred_margin": pm, "pred_total": pt, "home_wp": wp,
            "vegas_spread": vs, "vegas_total": vt,
            "final": bool(x.completed), "home_pts": None if not x.completed else int(x.home_points),
            "away_pts": None if not x.completed else int(x.away_points),
            "mode": "live" if live else ("backfill" if x.completed else "projection"),
            "factors": {
                "altitude_ft": int(round((x.away_climb - x.home_climb) * 3.281)) if not x.neutral_site else 0,
                "travel_mi": int(round(x.away_travel)), "rest_diff": int(round(x.home_rest - x.away_rest)),
            },
        })

    # ---------------- record.json ----------------
    boys_path = OUT / "boys.json"
    boys = json.load(open(boys_path)) if boys_path.exists() else {}
    def grade(gs):
        n = len(gs)
        su = sum((g_["pred_margin"] > 0) == (g_["home_pts"] > g_["away_pts"]) for g_ in gs)
        mae = np.mean([abs(g_["pred_margin"] - (g_["home_pts"] - g_["away_pts"])) for g_ in gs]) if n else None
        lined = [g_ for g_ in gs if g_["vegas_spread"] is not None and (g_["home_pts"] - g_["away_pts"] + g_["vegas_spread"]) != 0
                 and (g_["pred_margin"] + g_["vegas_spread"]) != 0]
        ats = sum(np.sign(g_["home_pts"] - g_["away_pts"] + g_["vegas_spread"]) == np.sign(g_["pred_margin"] + g_["vegas_spread"]) for g_ in lined)
        return {"games": n, "su_w": int(su), "su_l": int(n - su), "mae": r1(mae, 2),
                "ats_w": int(ats), "ats_l": int(len(lined) - ats)}
    finals = [x for x in games_out if x["final"]]
    west_f = [x for x in finals if x["home_west"] or x["away_west"]]
    record = {
        "live": {"all": grade([x for x in finals if x["mode"] == "live"]),
                 "west": grade([x for x in west_f if x["mode"] == "live"])},
        "backfill": {"all": grade([x for x in finals if x["mode"] == "backfill"]),
                     "west": grade([x for x in west_f if x["mode"] == "backfill"])},
        "weeks": [],
        "boys_vs_bot": {"boys": 0, "bot": 0, "weeks": []},
    }
    for wk in sorted({x["week"] for x in west_f}):
        gw = [x for x in west_f if x["week"] == wk]
        record["weeks"].append({"week": wk, "mode": gw[0]["mode"], **grade(gw)})
    # The Boys vs. The Bot (contest rules: lower combined point miss wins the game)
    by_names = {(x["home"], x["away"]): x for x in finals}
    for wk, picks in sorted(boys.get(str(season), {}).items(), key=lambda kv: int(kv[0])):
        bw = {"week": int(wk), "boys": 0, "bot": 0, "games": []}
        for pk in picks:
            gx = by_names.get((pk["home"], pk["away"])) or by_names.get((pk["away"], pk["home"]))
            if not gx:
                continue
            flip = gx["home"] != pk["home"]
            bh, ba = (pk["away_pts"], pk["home_pts"]) if flip else (pk["home_pts"], pk["away_pts"])
            # bot pick for the contest is whatever was published for that week (if recorded), else ours
            th, ta = (pk["bot_away"], pk["bot_home"]) if flip and "bot_home" in pk else (pk.get("bot_home"), pk.get("bot_away"))
            if th is None:
                th, ta = gx["pred_home"], gx["pred_away"]
            mb = contest_points(bh, ba, gx["home_pts"], gx["away_pts"])
            mt = contest_points(th, ta, gx["home_pts"], gx["away_pts"])
            if mb == mt:  # tiebreak: closer on the winner's points
                wh = gx["home_pts"] > gx["away_pts"]
                mb2 = abs((bh if wh else ba) - (gx["home_pts"] if wh else gx["away_pts"]))
                mt2 = abs((th if wh else ta) - (gx["home_pts"] if wh else gx["away_pts"]))
                winner = "boys" if mb2 < mt2 else ("bot" if mt2 < mb2 else "push")
            else:
                winner = "boys" if mb < mt else "bot"
            if winner != "push":
                bw[winner] += 1
            bw["games"].append({"home": gx["home"], "away": gx["away"], "final": [gx["home_pts"], gx["away_pts"]],
                                "boys": [bh, ba], "bot": [th, ta], "boys_miss": mb, "bot_miss": mt, "point": winner})
        record["boys_vs_bot"]["boys"] += bw["boys"]
        record["boys_vs_bot"]["bot"] += bw["bot"]
        record["boys_vs_bot"]["weeks"].append(bw)

    meta = {
        "generated": now.isoformat(timespec="minutes"), "season": season, "week": int(min(cur_wk, sg.week.max())),
        "launch_week": LAUNCH.get(season), "sims": args.sims, "backtest": backtest,
        "games_in_ratings": int(len(played)), "lines_live": lines is not None, "ncaa": ncaa_status,
        "model": {"rating_params": p.__dict__, "situational": {k: round(v, 3) for k, v in gm.coef.items()},
                  "sigma_early": round(gm.sigma_early, 2), "sigma_late": round(gm.sigma_late, 2),
                  "returning": {k: round(v, 2) for k, v in ret_coef.items()}},
    }

    if os.environ.get("INDEX_PREVIEW"):
        pv = index_feed.build(season, sg, T[["team_id", "name", "div", "net"]], WEST, OUT / "ei-auto-preview.js", ncaa_ids)
        json.dump({"feed": pv, "ncaa": ncaa_status}, open(OUT / "ei-preview-status.json", "w"))
        log("elevation index preview", pv)
    ours = sg[(sg.home_team.isin(WEST_BY_NAME) | sg.away_team.isin(WEST_BY_NAME)) & (sg.start < now - pd.Timedelta(hours=6))]
    missing = int((~ours.completed).sum())
    if now < INDEX_SWITCH or missing:
        # hold the published hand-entered Index until the automatic feed goes live
        shutil.copyfile(Path(__file__).resolve().parent / "ei-manual.js", SITE / "ei-auto.js")
        log("elevation index: holding hand-entered data until", INDEX_SWITCH.isoformat(), f"({missing} of our games not final yet)")
    else:
        feed = index_feed.build(season, sg, T[["team_id", "name", "div", "net"]], WEST, SITE / "ei-auto.js", ncaa_ids)
        log("elevation index feed", feed)

    def dump(name, obj):
        with open(OUT / name, "w") as f:
            json.dump(obj, f, separators=(",", ":"), default=lambda o: None if o is pd.NA else (o.item() if hasattr(o, "item") else str(o)))
    dump("meta.json", meta)
    dump("ratings.json", team_list)
    dump("predictions.json", games_out)
    dump("record.json", record)
    log("done: week", meta["week"], "|", len(team_list), "teams |", len(games_out), "games")


if __name__ == "__main__":
    main()
