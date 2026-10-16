"""The Bot (men's basketball) — daily pipeline.

    python model/hoops/run.py            # full: download, refit, backtest, predict, write hoops/*.json
    python model/hoops/run.py --quick    # game-night refresh: reuse the morning's fitted model

Writes everything the basketball pages read into hoops/:
    meta.json        when it ran, season, backtest scorecard, model settings
    teams.json       ratings for every Division I team (ours flagged), preseason start, records
    games_west.json  every game our teams play this season: Bot pick, factors, result
    games_all.json   every Division I game this season (compact)
    record.json      the live scorecard and The Boys vs. The Bot
    standings.json   Pac-12 and Mountain West standings
Kept between runs (also in hoops/): locked.json (picks frozen at tip), lines.json
(pregame lines seen on ESPN, for grading only), history.json (rank by day),
boys.json (the analysts' weekly picks, entered by hand), model.json (fitted model).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from math import erf, sqrt
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import data  # noqa: E402
import espn  # noqa: E402
import prior as PR  # noqa: E402
import ratings as R  # noqa: E402
import walk as W  # noqa: E402
from game_model import GameModel  # noqa: E402

SITE = Path(__file__).resolve().parents[2]
OUT = SITE / "hoops"
PARAMS = R.Params(lam=4.0, lam_t=4.0, tau=1e9, hca_eff=2.0)
TRAIN_LAST = 2021  # backtest: everything fit on seasons through 2020-21, graded on 2021-22 on

# Elevation Change coverage: site id -> ESPN team id
WEST = {
    "BSU": 68, "CSU": 36, "FRES": 278, "GONZ": 2250, "ORST": 204, "SDSU": 21, "TXST": 326, "USU": 328, "WSU": 265,
    "AFA": 2005, "GCU": 2253, "HAW": 62, "NEV": 2440, "UNM": 167, "SJSU": 23, "UCD": 302, "UNLV": 2439, "UTEP": 2638,
    "WYO": 2751, "NDSU": 2449, "NIU": 2459, "NMSU": 166, "SAC": 16,
}
SITE_ID = {v: k for k, v in WEST.items()}
PAC12, MW = 21, 44
CONF = {1: "America East", 2: "ACC", 3: "A-10", 4: "Big East", 5: "Big Sky", 6: "Big South", 7: "Big Ten", 8: "Big 12",
        9: "Big West", 10: "CAA", 11: "CUSA", 12: "Ivy", 13: "MAAC", 14: "MAC", 16: "MEAC", 18: "MVC", 19: "NEC",
        20: "OVC", 21: "Pac-12", 22: "Patriot", 23: "SEC", 24: "SoCon", 25: "Southland", 26: "SWAC", 27: "Sun Belt",
        29: "WCC", 30: "UAC", 43: "Independent", 44: "Mountain West", 45: "Horizon", 46: "ASUN", 49: "Summit", 62: "American"}
NAME = {"San Jose State": "San José State", "Hawaii": "Hawai'i", "Hawai`i": "Hawai'i"}
LOCAL_LOGOS = {p.stem for p in (SITE / "logos").glob("*.png")}


def log(*a):
    print(f"[{datetime.now().strftime('%H:%M:%S')}]", *a, flush=True)


def current_season(now: datetime) -> int:
    return now.year + 1 if now.month >= 8 else now.year


def r1(x, nd=1):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd)


def whole_score(ph: float, pa: float):
    """Whole-number score, never a tie, winner preserved."""
    h, a = int(round(ph)), int(round(pa))
    if h == a:
        if ph >= pa:
            h += 1
        else:
            a += 1
    if (h > a) != (ph >= pa):
        h, a = a, h
    return max(h, 0), max(a, 0)


def load(name, default):
    f = OUT / name
    return json.load(open(f)) if f.exists() else default


def dump(name, obj, indent=None):
    def clean(o):
        if isinstance(o, dict):
            return {str(k): clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating, float)):
            return None if np.isnan(o) else float(o)
        if isinstance(o, np.bool_):
            return bool(o)
        return o
    with open(OUT / name, "w") as f:
        json.dump(clean(obj), f, indent=indent, separators=(",", ":") if indent is None else None, ensure_ascii=False)


def fit_all(g, fin, ro, mins, season):
    """Walk-forward every past season, fit the game model, grade 2022+ out of sample."""
    pri_bt = PR.Prior.fit(g, fin, ro, mins, season, range(2014, TRAIN_LAST + 1))
    parts = []
    for y in range(2014, season):
        ids, idx, P, _ = W.season_priors(y, g, fin, ro, mins, pri_bt, season)
        parts.append(W.run_season(y, g, ids, idx, P, PARAMS))
        log(f"  walk-forward {y - 1}-{str(y)[2:]}")
    e = pd.concat(parts)
    r = g.join(e, how="inner")
    r = r[r.completed & r.home_d1 & r.away_d1 & r.r_margin.notna()]
    gm_bt = GameModel.fit(r[r.season <= TRAIN_LAST])
    te = r[r.season > TRAIN_LAST].join(gm_bt.predict(r[r.season > TRAIN_LAST]))
    hw = te.margin > 0
    fav = np.maximum(te.home_wp, 1 - te.home_wp)
    won = np.where(te.home_wp >= 0.5, hw, ~hw)
    cal = []
    for lo in (0.5, 0.6, 0.7, 0.8, 0.9):
        m = (fav >= lo) & (fav < lo + 0.1 + (1e-9 if lo == 0.9 else 0))
        cal.append({"bin": f"{int(lo * 100)}–{int(lo * 100 + 10)}%", "pred": r1(100 * fav[m].mean()), "actual": r1(100 * won[m].mean()), "games": int(m.sum())})
    by = []
    for y, s in te.groupby("season"):
        by.append({"season": f"{y - 1}-{str(y)[2:]}", "games": int(len(s)), "mae": r1((s.pred_margin - s.margin).abs().mean(), 2),
                   "su": r1(100 * ((s.pred_margin > 0) == (s.margin > 0)).mean()),
                   "total_mae": r1((s.pred_total - s.total).abs().mean(), 2)})
    backtest = {"seasons": f"{TRAIN_LAST}-{str(TRAIN_LAST + 1)[2:]} to {season - 2}-{str(season - 1)[2:]}", "games": int(len(te)),
                "mae": r1((te.pred_margin - te.margin).abs().mean(), 2), "su": r1(100 * ((te.pred_margin > 0) == hw).mean()),
                "total_mae": r1((te.pred_total - te.total).abs().mean(), 2), "brier": r1(((te.home_wp - hw) ** 2).mean(), 4),
                "by_season": by, "calibration": cal}
    # live model: game model on every season, prior on every season
    gm = GameModel.fit(r)
    # injuries: what a missing regular costs, from games since 2021-22
    import injuries as INJ
    rr = r[r.season > TRAIN_LAST].join(gm.predict(r[r.season > TRAIN_LAST]))
    rr["resid"] = rr.margin - rr.pred_margin
    boxes = {y: INJ.load_box(data.CACHE / f"pb_{y}.parquet") for y in range(TRAIN_LAST + 1, season)}
    inj_k = INJ.calibrate(boxes, rr, log=log)
    backtest["inj_k"] = round(inj_k, 3)
    pri = PR.Prior.fit(g, fin, ro, mins, season, range(2014, season))
    log(f"  backtest {backtest['games']} games: miss {backtest['mae']} pts, winners {backtest['su']}%")
    return pri, gm, backtest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int)
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--no-espn", action="store_true")
    ap.add_argument("--quick", action="store_true", help="reuse model.json (game-night refresh)")
    ap.add_argument("--now", help="pretend it is this UTC time (testing)")
    ap.add_argument("--bracket", action="store_true", help="rebuild the March Madness projection now (otherwise Mondays)")
    args = ap.parse_args()
    now = pd.Timestamp(args.now, tz="UTC") if args.now else pd.Timestamp.now(tz="UTC")
    season = args.season or current_season(now.to_pydatetime())
    OUT.mkdir(exist_ok=True)
    log(f"The Bot (hoops): season {season - 1}-{str(season)[2:]}, now {now:%Y-%m-%d %H:%M} UTC")

    if not args.no_download:
        data.download(season)
    today = (now + data.MT).date()
    patch, new_lines, espn_status = (pd.DataFrame(), {}, {"ok": False, "error": "skipped"}) if args.no_espn else \
        espn.fetch(espn.window(today), season, log=log)
    if not args.no_espn and not espn_status.get("ok"):
        import ncaa_mbb
        sched = data.schedule(season)
        if not sched.empty:
            sched = sched.assign(home=sched.home.map(lambda n: NAME.get(n, n)), away=sched.away.map(lambda n: NAME.get(n, n)))
            fb, st = ncaa_mbb.finals(sched, season, [today - timedelta(days=1), today], log=log)
            espn_status["ncaa"] = st
            patch = fb
    if not args.no_espn and not args.quick:
        espn.rosters(sorted(data.d1_teams(season, season)), season, data.CACHE / "ro_live.json", log=log)
    g = data.games(season, patch=patch)
    g = g.join(W.games_played_before(g), on="game_id")
    fin = PR.final_ratings(g, season)
    ro, mins = data.rosters_and_minutes(season)

    saved = load("model.json", None)
    if saved and any(len(saved["prior"].get(k, [])) != n for k, n in PR.N_DESIGN.items()):
        saved = None   # the prior gained features since this model was saved: refit
    if args.quick and saved:
        pri, gm, backtest = PR.Prior({k: v for k, v in saved["prior"].items()}), GameModel.from_dict(saved["game"]), saved["backtest"]
        log("  quick run: reusing the morning's model")
    else:
        pri, gm, backtest = fit_all(g, fin, ro, mins, season)
        dump("model.json", {"prior": pri.coef, "game": gm.to_dict(), "backtest": backtest, "params": PARAMS.__dict__,
                            "fitted": now.isoformat(timespec="minutes")})

    # ---------------- this season ----------------
    cur = g[g.season == season].copy()
    ids, idx, P, ret = W.season_priors(season, g, fin, ro, mins, pri, season)
    pre = R.solve(cur.iloc[0:0], ids, idx, P["O"].to_numpy(), P["D"].to_numpy(), P["T"].to_numpy(), PARAMS)
    rnow = R.solve(cur, ids, idx, P["O"].to_numpy(), P["D"].to_numpy(), P["T"].to_numpy(), PARAMS)
    log(f"  {rnow['games']} games this season in the ratings")

    # predictions as of now for everything, walk-forward for finished games
    raw = R.predict_raw(rnow, idx, cur.home_id, cur.away_id, cur.neutral)
    raw.index = cur.index
    done_days = set(cur.loc[cur.completed & cur.poss.notna(), "day"]) | set(cur.loc[cur.completed, "day"])
    wf = W.run_season(season, g, ids, idx, P, PARAMS, days=done_days) if done_days else pd.DataFrame()
    now_pred = gm.predict(cur.join(raw))
    wf_pred = gm.predict(cur.join(wf, how="inner")) if len(wf) else pd.DataFrame(columns=now_pred.columns)

    # ---------------- injuries and absences ----------------
    import injuries as INJ
    from bracket import ncdf
    inj_k = float(backtest.get("inj_k", 0.21))
    box = INJ.load_box(data.CACHE / f"pb_{season}.parquet")
    box_prev = INJ.load_box(data.CACHE / f"pb_{season - 1}.parquet")
    tg_now = box.drop_duplicates(["team_id", "game_id"]).groupby("team_id").size() if len(box) else pd.Series(dtype=int)
    vals = INJ.values(box, tg_now) if len(box) else pd.DataFrame(columns=["team_id", "athlete_id", "name", "gp", "mpg", "v", "share", "regular"])
    tg_prev = box_prev.drop_duplicates(["team_id", "game_id"]).groupby("team_id").size() if len(box_prev) else pd.Series(dtype=int)
    vals_prev = INJ.values(box_prev, tg_prev) if len(box_prev) else vals.iloc[0:0]
    name_to_id = {}
    for side in ("home", "away"):
        for t, n in zip(cur[f"{side}_id"], cur[side]):
            name_to_id[str(NAME.get(n, n)).lower()] = int(t)
    hand = INJ.manual(OUT / "injuries.json")
    for h in hand:
        h["team_id"] = name_to_id.get(str(h.get("team", "")).lower(), h.get("team_id", -1))
        # before a player has games this season, use last season's numbers (wherever he played)
        have = (vals.team_id == h["team_id"]) & (vals.name.str.lower() == str(h.get("player", "")).lower()) if len(vals) else pd.Series(dtype=bool)
        if not len(vals) or not have.any():
            m = vals_prev[vals_prev.name.str.lower() == str(h.get("player", "")).lower()]
            if len(m):
                row = m.sort_values("mins", ascending=False).iloc[[0]].copy()
                row["team_id"], row["share"], row["regular"] = h["team_id"], 1.0, True
                vals = pd.concat([vals, row], ignore_index=True)
    soon = cur[~cur.completed & (cur.day >= pd.Timestamp(today)) & (cur.day <= pd.Timestamp(today) + pd.Timedelta(days=1))
               & (cur.home_id.isin(SITE_ID) | cur.away_id.isin(SITE_ID))]
    espn_inj = {} if args.no_espn or soon.empty else INJ.espn_injuries([int(x) for x in soon.game_id], log=log)
    st = INJ.status_now(vals, box if len(box) else box_prev.iloc[0:0], espn_inj, hand, str(today)) if len(vals) else pd.DataFrame()
    inj = INJ.team_adjust(st, inj_k) if len(st) else {}
    inj_games = {}
    for i, x in cur.iterrows():
        if x.completed or not len(inj):
            continue
        ahead = (x.day - pd.Timestamp(today)).days
        if ahead < 0:
            continue
        key = "near" if ahead <= 6 else "long"
        a_h, a_a = inj.get(int(x.home_id), {}), inj.get(int(x.away_id), {})
        d = a_h.get(key, 0.0) - a_a.get(key, 0.0)
        if abs(d) < 0.05:
            continue
        now_pred.at[i, "pred_margin"] += d
        now_pred.at[i, "pred_home"] += d / 2
        now_pred.at[i, "pred_away"] -= d / 2
        now_pred.at[i, "home_wp"] = float(ncdf(now_pred.at[i, "pred_margin"] / gm.sigma_late))
        pick = lambda a_: [q for q in a_.get("players", []) if (key == "near" or q["long"]) and abs(q["pts"]) >= 0.3][:3]
        inj_games[int(x.game_id)] = {"home": pick(a_h), "away": pick(a_a), "pts": round(d, 1)}
    log(f"  injuries: {int((st.p_out >= 0.3).sum()) if len(st) else 0} regulars flagged, {len(inj_games)} games adjusted")

    # lock picks until tip: a game's pick is the last one published before it started
    locked = load("locked.json", {})
    lines = load("lines.json", {})
    for gid, ln in new_lines.items():
        lines[str(gid)] = {**ln, "seen": now.isoformat(timespec="minutes")}

    def started(x) -> bool:
        if x.completed or x.get("state") in ("in", "post"):
            return True
        if bool(x.time_valid):
            return now >= x.start
        tip_guess = pd.Timestamp(x.day) + pd.Timedelta(hours=10) - data.MT  # TBA times: lock by 10am MT
        return now >= tip_guess.tz_localize("UTC")

    for i, x in cur.iterrows():
        gid = str(int(x.game_id))
        if not started(x):
            p_ = now_pred.loc[i]
            ph, pa = whole_score(p_.pred_home, p_.pred_away)
            locked[gid] = {"pred_home": ph, "pred_away": pa, "pred_margin": r1(p_.pred_margin, 2), "pred_total": r1(p_.pred_total, 2),
                           "home_wp": r1(p_.home_wp, 4), "pace": r1(raw.at[i, "r_pace"]), "made": now.isoformat(timespec="minutes")}

    # ---------------- week numbering (Monday-Sunday, Mountain time) ----------------
    first = pd.Timestamp(cur.day.min()) if len(cur) else pd.Timestamp(today)
    monday0 = first - pd.Timedelta(days=first.weekday())
    cur["week"] = ((cur.day - monday0).dt.days // 7 + 1).astype(int)

    # ---------------- team table ----------------
    names, abbr, logo_url = {}, {}, {}
    for side in ("home", "away"):
        for _, x in g[g.season >= season - 1][[f"{side}_id", side, f"{side}_abbr", f"{side}_logo"]].dropna(subset=[side]).iterrows():
            t = int(x[f"{side}_id"])
            names[t] = NAME.get(x[side], x[side])
            abbr[t] = x[f"{side}_abbr"]
            if isinstance(x[f"{side}_logo"], str) and x[f"{side}_logo"]:
                logo_url[t] = x[f"{side}_logo"]
    conf_of = pd.concat([cur[["home_id", "home_conf"]].set_axis(["t", "c"], axis=1), cur[["away_id", "away_conf"]].set_axis(["t", "c"], axis=1)]).dropna()
    conf_of = conf_of.groupby("t").c.agg(lambda s: int(s.mode().iat[0])).to_dict()
    for y in (season - 1,):
        if y in fin:
            for t, c in fin[y].conf.dropna().items():
                conf_of.setdefault(int(t), int(c))
    # 2026-27 memberships (the schedule doesn't show every league game yet)
    for sid in ("BSU", "CSU", "FRES", "GONZ", "ORST", "SDSU", "TXST", "USU", "WSU"):
        conf_of[WEST[sid]] = PAC12
    for sid in ("AFA", "GCU", "HAW", "NEV", "UNM", "SJSU", "UCD", "UNLV", "UTEP", "WYO"):
        conf_of[WEST[sid]] = MW

    O, D, T = rnow["O"], rnow["D"], rnow["T"]
    net = O - D
    d1_mask = ids != data.NON_D1
    order = np.argsort(-np.where(d1_mask, net, -1e9))
    rank = np.empty(len(ids), int)
    rank[order] = np.arange(1, len(ids) + 1)
    pnet = pre["O"] - pre["D"]
    porder = np.argsort(-np.where(d1_mask, pnet, -1e9))
    prank = np.empty(len(ids), int)
    prank[porder] = np.arange(1, len(ids) + 1)
    hist = load("history.json", {})
    key = str(today)
    hist[key] = {str(int(t)): int(rank[i]) for i, t in enumerate(ids) if t != data.NON_D1}
    hist = {k: v for k, v in sorted(hist.items())[-60:]}
    week_ago = [k for k in hist if k <= str(today - timedelta(days=7))]
    prev = hist[week_ago[-1]] if week_ago else {str(int(t)): int(prank[i]) for i, t in enumerate(ids) if t != data.NON_D1}

    fins = cur[cur.completed]
    rec = {}
    for _, x in fins.iterrows():
        hw = x.home_pts > x.away_pts
        cg = bool(x.conf_game)
        for t, w in ((int(x.home_id), hw), (int(x.away_id), not hw)):
            r_ = rec.setdefault(t, [0, 0, 0, 0])
            r_[0 if w else 1] += 1
            if cg:
                r_[2 if w else 3] += 1

    def team_logo(t):
        sid = SITE_ID.get(t)
        if sid and sid in LOCAL_LOGOS:
            return f"logos/{sid}.png"
        return logo_url.get(t)

    # incoming ranked freshmen this season, best first (shown on team pages)
    rc = PR.recruits(season)
    rc = rc[rc["class"] == season - 1].sort_values("rank")
    frosh = {int(t): [{"name": n, "rank": int(k)} for n, k in zip(d.name, d["rank"])] for t, d in rc.groupby("team_id")}
    teams = []
    off_rank = pd.Series(O[d1_mask]).rank(ascending=False).to_numpy()
    def_rank = pd.Series(D[d1_mask]).rank(ascending=True).to_numpy()
    d1_pos = {i: k for k, i in enumerate(np.where(d1_mask)[0])}
    for i, t in enumerate(ids):
        if t == data.NON_D1:
            continue
        t = int(t)
        r_ = rec.get(t, [0, 0, 0, 0])
        rt = ret.loc[t] if t in ret.index else None
        c = conf_of.get(t)
        teams.append({
            "id": t, "name": names.get(t, str(t)), "abbr": SITE_ID.get(t) or abbr.get(t), "site": SITE_ID.get(t),
            "conf": CONF.get(c, ""), "west": t in SITE_ID,
            "league": "pac" if c == PAC12 else "mw" if c == MW else "oth",
            "logo": team_logo(t), "rank": int(rank[i]), "prev_rank": int(prev.get(str(t), rank[i])),
            "net": r1(net[i]), "off": r1(O[i]), "def": r1(-D[i]),
            "off_rank": int(off_rank[d1_pos[i]]), "def_rank": int(def_rank[d1_pos[i]]),
            "tempo": r1(rnow["tmu"] + T[i]),
            "pre_rank": int(prank[i]), "pre_net": r1(pnet[i]),
            "ret": r1(float(rt.ret) * 100, 0) if rt is not None else None,
            "fr_pts": r1(float(P.at[t, "fr_pts"])) if "fr_pts" in P and t in P.index else None,
            "xf_pts": r1(float(P.at[t, "xf_pts"])) if "xf_pts" in P and t in P.index else None,
            "frosh": frosh.get(t, []),
            "w": r_[0], "l": r_[1], "cw": r_[2], "cl": r_[3],
        })
    teams.sort(key=lambda x: x["rank"])

    # ---------------- games ----------------
    out_games = []
    team_by = {x["id"]: x for x in teams}
    for i, x in cur.sort_values(["start", "game_id"]).iterrows():
        gid = str(int(x.game_id))
        lk = locked.get(gid)
        if x.completed and lk:
            pk, mode = lk, "live"
        elif x.completed and i in wf_pred.index:
            p_ = wf_pred.loc[i]
            ph, pa = whole_score(p_.pred_home, p_.pred_away)
            pk, mode = {"pred_home": ph, "pred_away": pa, "pred_margin": r1(p_.pred_margin, 2), "pred_total": r1(p_.pred_total, 2),
                        "home_wp": r1(p_.home_wp, 4), "pace": r1(wf.at[i, "r_pace"])}, "test"
        elif lk and started(x):
            pk, mode = lk, "live"
        else:
            p_ = now_pred.loc[i]
            ph, pa = whole_score(p_.pred_home, p_.pred_away)
            pk, mode = {"pred_home": ph, "pred_away": pa, "pred_margin": r1(p_.pred_margin, 2), "pred_total": r1(p_.pred_total, 2),
                        "home_wp": r1(p_.home_wp, 4), "pace": r1(raw.at[i, "r_pace"])}, "projection"
        ln = lines.get(gid) or {}
        hid, aid = int(x.home_id), int(x.away_id)
        out_games.append({
            "id": int(x.game_id), "week": int(x.week), "day": str(x.day.date()),
            "start": x.start.isoformat() if pd.notna(x.start) else None, "tba": not bool(x.time_valid),
            "neutral": bool(x.neutral), "conf_game": bool(x.conf_game),
            "venue": x.get("venue") if isinstance(x.get("venue"), str) else None,
            "city": x.get("city") if isinstance(x.get("city"), str) else None, "st": x.get("st") if isinstance(x.get("st"), str) else None,
            "note": x.get("note") if isinstance(x.get("note"), str) else None,
            "home": NAME.get(x.home, x.home), "away": NAME.get(x.away, x.away), "home_id": hid, "away_id": aid,
            "home_d1": bool(x.home_d1), "away_d1": bool(x.away_d1),
            "home_west": hid in SITE_ID, "away_west": aid in SITE_ID,
            "home_rank": team_by.get(hid, {}).get("rank"), "away_rank": team_by.get(aid, {}).get("rank"),
            **{k: pk.get(k) for k in ("pred_home", "pred_away", "pred_margin", "pred_total", "home_wp", "pace")},
            "vegas_spread": ln.get("spread"), "vegas_total": ln.get("total"),
            "inj": inj_games.get(int(x.game_id)) if not x.completed else None,
            "final": bool(x.completed), "home_pts": int(x.home_pts) if x.completed else None,
            "away_pts": int(x.away_pts) if x.completed else None, "mode": mode,
            "factors": {"altitude_ft": int(round(x.away_climb - x.home_climb)) if not x.neutral else 0,
                        "site_elev": int(x.site_elev) if pd.notna(x.site_elev) else None,
                        "travel_mi": int(round(x.away_travel - x.home_travel)),
                        "rest_diff": int(round(x.home_rest - x.away_rest))},
        })
    west_games = [x for x in out_games if x["home_west"] or x["away_west"]]
    all_games = [{k: x[k] for k in ("id", "week", "day", "start", "tba", "neutral", "home", "away", "home_id", "away_id",
                                     "home_west", "away_west", "home_rank", "away_rank", "pred_home", "pred_away",
                                     "home_wp", "final", "home_pts", "away_pts", "mode")}
                 for x in out_games if x["home_d1"] and x["away_d1"]]

    # ---------------- record ----------------
    def grade(gs):
        n = len(gs)
        su = sum((x["pred_margin"] > 0) == (x["home_pts"] > x["away_pts"]) for x in gs)
        mae = float(np.mean([abs(x["pred_margin"] - (x["home_pts"] - x["away_pts"])) for x in gs])) if n else None
        lined = [x for x in gs if x["vegas_spread"] is not None and (x["home_pts"] - x["away_pts"] + x["vegas_spread"]) != 0
                 and (x["pred_margin"] + x["vegas_spread"]) != 0]
        ats = sum(np.sign(x["home_pts"] - x["away_pts"] + x["vegas_spread"]) == np.sign(x["pred_margin"] + x["vegas_spread"]) for x in lined)
        vmae = float(np.mean([abs(-x["vegas_spread"] - (x["home_pts"] - x["away_pts"])) for x in lined])) if lined else None
        bmae = float(np.mean([abs(x["pred_margin"] - (x["home_pts"] - x["away_pts"])) for x in lined])) if lined else None
        return {"games": n, "su_w": int(su), "su_l": int(n - su), "mae": r1(mae, 2),
                "ats_w": int(ats), "ats_l": int(len(lined) - ats), "lined": len(lined), "vegas_mae": r1(vmae, 2), "bot_mae_lined": r1(bmae, 2)}

    finals = [x for x in out_games if x["final"] and x["home_d1"] and x["away_d1"] and x["pred_margin"] is not None]
    west_f = [x for x in finals if x["home_west"] or x["away_west"]]
    record = {"live": {"all": grade([x for x in finals if x["mode"] == "live"]), "west": grade([x for x in west_f if x["mode"] == "live"])},
              "weeks": [], "boys_vs_bot": {"boys": 0, "bot": 0, "weeks": []}}
    for wk in sorted({x["week"] for x in west_f}):
        gw = [x for x in west_f if x["week"] == wk]
        record["weeks"].append({"week": wk, **grade(gw)})
    boys = load("boys.json", {"_how_to": "Each week add the analysts' score picks before tip. Team names must match the schedule "
                                         "(e.g. \"Hawai'i\", \"San José State\", \"Gonzaga\"). bot_home/bot_away are optional: leave them "
                                         "out and the contest uses the Bot's locked pick."})
    by_names = {(x["home"], x["away"]): x for x in finals}
    for wk, picks in sorted(boys.get(str(season), {}).items(), key=lambda kv: int(kv[0])):
        bw = {"week": int(wk), "boys": 0, "bot": 0, "games": []}
        for pk in picks:
            gx = by_names.get((pk["home"], pk["away"])) or by_names.get((pk["away"], pk["home"]))
            if not gx:
                continue
            flip = gx["home"] != pk["home"]
            bh, ba = (pk["away_pts"], pk["home_pts"]) if flip else (pk["home_pts"], pk["away_pts"])
            th, ta = ((pk["bot_away"], pk["bot_home"]) if flip else (pk["bot_home"], pk["bot_away"])) if "bot_home" in pk else (gx["pred_home"], gx["pred_away"])
            fh, fa = gx["home_pts"], gx["away_pts"]
            mb, mt = abs(bh - fh) + abs(ba - fa), abs(th - fh) + abs(ta - fa)
            hw = fh > fa
            boys_right, bot_right = (bh > ba) == hw, (th > ta) == hw
            if boys_right != bot_right:
                winner, how = ("boys" if boys_right else "bot"), "winner"
            elif mb == mt:
                wb, wt = abs((bh if hw else ba) - (fh if hw else fa)), abs((th if hw else ta) - (fh if hw else fa))
                winner, how = ("boys" if wb < wt else "bot" if wt < wb else "push"), "tiebreak"
            else:
                winner, how = ("boys" if mb < mt else "bot"), "score"
            if winner != "push":
                bw[winner] += 1
            bw["games"].append({"home": gx["home"], "away": gx["away"], "final": [fh, fa], "boys": [bh, ba], "bot": [th, ta],
                                "boys_miss": mb, "bot_miss": mt, "point": winner, "how": how,
                                "boys_right": boys_right, "bot_right": bot_right})
        record["boys_vs_bot"]["boys"] += bw["boys"]
        record["boys_vs_bot"]["bot"] += bw["bot"]
        record["boys_vs_bot"]["weeks"].append(bw)

    # ---------------- standings ----------------
    def table(cid):
        members = [x for x in teams if conf_of.get(x["id"]) == cid]
        members.sort(key=lambda x: (-(x["cw"] - x["cl"]), -x["cw"], -(x["w"] - x["l"]), x["rank"]))
        return [{k: x[k] for k in ("id", "name", "abbr", "site", "logo", "w", "l", "cw", "cl", "rank", "net")} for x in members]
    standings = {"pac": table(PAC12), "mw": table(MW)}

    # ---------------- meta ----------------
    upcoming = [x for x in west_games if not x["final"]]
    meta = {
        "generated": now.isoformat(timespec="minutes"), "season": season, "season_label": f"{season - 1}-{str(season)[2:]}",
        "today": str(today), "week": int(((pd.Timestamp(today) - monday0).days // 7) + 1),
        "first_day": str(first.date()), "games_in_ratings": int(rnow["games"]), "teams": len(teams),
        "backtest": backtest, "espn": espn_status, "lines_seen": len(lines),
        "next_west": upcoming[0]["day"] if upcoming else None,
        "model": {"hca_pts": r1(gm.coef["home"], 2), "altitude_per_1000ft": r1(gm.coef["climb"], 2), "altitude_hi_per_1000ft": r1(gm.coef["climb"] + gm.coef["climb_hi"], 2),
                  "travel_per_1000mi": r1(gm.coef["travel"], 2), "sigma": r1(gm.sigma_late, 2),
                  "prior_weight_games": PARAMS.lam},
        "conf_schedule": {"pac": int(((cur.home_conf == PAC12) & cur.conf_game).sum()), "mw": int(((cur.home_conf == MW) & cur.conf_game).sum())},
    }
    # ---------------- players (team pages) ----------------
    players = {}
    status_by = {(int(r.team_id), int(r.athlete_id)): r for _, r in st.iterrows()} if len(st) else {}
    # this season's roster, where ESPN has updated it (an unchanged file means it hasn't been)
    roster_now = {}
    if season in ro:
        now_sets = ro[season].groupby("team_id").athlete_id.agg(set)
        old_sets = ro[season - 1].groupby("team_id").athlete_id.agg(set) if season - 1 in ro else {}
        for t, ath in now_sets.items():
            o = old_sets.get(t) if len(old_sets) else None
            if PR.trusted(ath, o):
                roster_now[int(t)] = ath
    prev_team = vals_prev.sort_values("mins").drop_duplicates("athlete_id", keep="last").set_index("athlete_id") if len(vals_prev) else None
    for t in [x["id"] for x in teams]:
        src = vals[vals.team_id == t] if len(vals) else vals
        label = "this season"
        if not len(src) or src.gp.max() < 1:
            if t in roster_now and prev_team is not None:
                src = prev_team[prev_team.index.isin(roster_now[t])].reset_index()
                label = "last season's numbers, this season's roster"
            else:
                src = vals_prev[vals_prev.team_id == t] if len(vals_prev) else vals_prev
                label = "last season (this season's roster isn't posted yet, so some of these players may be gone)"
        src = src.sort_values("mpg", ascending=False).head(10)
        rows = []
        for _, r in src.iterrows():
            stt = status_by.get((t, int(r.athlete_id)))
            frm = int(r.team_id) if int(r.team_id) != t else None
            rows.append({"name": r["name"], "from": frm, "gp": int(r.gp), "mpg": r1(r.mpg), "ppg": r1(r.get("ppg")), "rpg": r1(r.get("rpg")),
                         "apg": r1(r.get("apg")), "impact": r1(inj_k * r.v), "regular": bool(r.regular),
                         "p_out": r1(stt.p_out, 2) if stt is not None else None, "note": stt.note if stt is not None else None})
        if rows:
            players[str(t)] = {"season": label, "players": rows, "adjust": inj.get(t)}
    dump("players.json", players)
    if not (OUT / "injuries.json").exists():
        dump("injuries.json", {"_how_to": "Players our writers know are out (or back). team = school name as on the site, player = full name as "
                                          "in box scores. status: out, doubtful, questionable, available. until: last date out (optional). "
                                          "season: true if out for the year. Remove entries when they no longer apply.",
                               "players": []}, indent=2)
    meta["injuries"] = {"k": round(inj_k, 3), "flagged": int((st.p_out >= 0.3).sum()) if len(st) else 0, "games_adjusted": len(inj_games),
                        "espn_reports": len(espn_inj), "hand": len(hand)}

    # ---------------- March Madness projection (weekly: Monday morning runs) ----------------
    if args.bracket or (not args.quick and pd.Timestamp(today).weekday() == 0) or not (OUT / "bracket.json").exists():
        try:
            rb = dict(rnow)
            rb["O"] = rnow["O"].copy()
            for t, a_ in inj.items():  # long-term absences carry into the season simulation
                if t in idx and abs(a_["long"]) >= 0.05:
                    i_ = idx[t]
                    rb["O"][i_] += a_["long"] * 100 / (rnow["tmu"] + rnow["T"][i_]) / gm.coef["r_margin"]
            bracket_step(g, season, fin, ro, mins, pri, ids, idx, rb, conf_of, gm, teams, now, today, meta)
        except Exception as e:  # the rest of the site never waits on the bracket
            import traceback
            traceback.print_exc()
            log("bracket step failed:", repr(e)[:200])
    dump("meta.json", meta, indent=1)
    dump("teams.json", teams)
    dump("games_west.json", west_games)
    dump("games_all.json", all_games)
    dump("record.json", record)
    dump("standings.json", standings)
    dump("locked.json", locked, indent=0)
    dump("lines.json", lines, indent=0)
    dump("history.json", hist)
    if not (OUT / "boys.json").exists():
        dump("boys.json", {**boys, str(season): {}}, indent=2)
    log(f"done: {len(teams)} teams, {len(west_games)} games for our teams, {len(all_games)} D-I games")


def bracket_step(g, season, fin, ro, mins, pri, ids, idx, rnow, conf_of, gm, teams, now, today, meta):
    import bracket as BK
    log("  bracket: learning what it takes from past Selection Sundays")
    cache = {}

    def asof(y, day):
        if y not in cache:
            cache[y] = W.season_priors(y, g, fin, ro, mins, pri, season)
        ids_, idx_, P_, _ = cache[y]
        r = R.solve(g[g.season == y], ids_, idx_, P_["O"].to_numpy(), P_["D"].to_numpy(), P_["T"].to_numpy(), PARAMS, as_of=day)
        net = {int(t): float(r["O"][i] - r["D"][i]) for i, t in enumerate(ids_) if t != data.NON_D1}
        order = sorted(net, key=lambda t: -net[t])
        return {t: i + 1 for i, t in enumerate(order)}, net

    H = BK.history(g, asof, season)
    sel, seed = BK.fit_models(H)
    bt = BK.backtest(H)
    wit = BK.what_it_takes(H)
    auto_confs = {c for c in set(conf_of.values()) if c in CONF and c != 43}
    log(f"  bracket: {len(auto_confs)} automatic-bid conferences; simulating the season")
    Pj = BK.project(g, season, rnow, idx, ids, conf_of, gm, sel, seed, auto_confs, sims=1000, log=log)
    B = BK.build_bracket(Pj, season, auto_confs)
    or_games, rounds, champ, adv = BK.play(B, Pj, sims=10000)
    tb = {x["id"]: x for x in teams}
    hist = load("bracket_history.json", {})
    prev_key = max([k for k in hist if k < str(today)], default=None)
    prev = hist.get(prev_key, {})
    field = B["field"]
    pj = Pj.set_index("team")
    n_field, n_auto, n_al, n_or = BK.fmt(season)
    or_set = {o for gm_ in B["games"] for o in gm_}
    seeds_now = {}
    prev_seed = lambda v: (v[0] if isinstance(v, list) else v) if v is not None else None
    prev_p = lambda v: v[1] if isinstance(v, list) else None
    rows = []
    for _, x in field.iterrows():
        t = int(x.team)
        line, reg = B["seed_of"][int(x.overall)]
        tm = tb.get(t, {})
        pv = prev_seed(prev.get(str(t)))
        rows.append({"overall": int(x.overall), "id": t, "name": tm.get("name"), "abbr": tm.get("abbr"), "logo": tm.get("logo"),
                     "conf": tm.get("conf"), "west": tm.get("west", False), "seed": line, "region": reg, "auto": bool(x.auto),
                     "opening_round": int(x.overall) in or_set, "p_bid": r1(pj.at[t, "p_bid"], 3), "p_auto": r1(pj.at[t, "p_auto"], 3),
                     "rank": tm.get("rank"), "net": tm.get("net"), "w": tm.get("w"), "l": tm.get("l"),
                     "exp_w": r1(pj.at[t, "exp_w"]), "exp_l": r1(pj.at[t, "exp_l"]), "exp_q1w": r1(pj.at[t, "exp_q1w"]),
                     "prev_seed": pv, "adv": adv.get(t)})
    for _, x in field.iterrows():
        seeds_now[str(int(x.team))] = B["seed_of"][int(x.overall)][0]
    hist[str(today)] = {str(int(t)): [seeds_now.get(str(int(t))), round(float(p_), 3)] for t, p_ in zip(Pj.team, Pj.p_bid) if p_ >= 0.005 or str(int(t)) in seeds_now}
    hist = {k: v for k, v in sorted(hist.items())[-30:]}

    def brief(t):
        tm = tb.get(t, {})
        return {"id": t, "name": tm.get("name"), "abbr": tm.get("abbr"), "logo": tm.get("logo"), "conf": tm.get("conf"),
                "p_bid": r1(pj.at[t, "p_bid"], 3), "rank": tm.get("rank"), "exp_w": r1(pj.at[t, "exp_w"]), "exp_l": r1(pj.at[t, "exp_l"])}
    ours = []
    for t in WEST.values():
        if t in pj.index:
            o = brief(t)
            line = seeds_now.get(str(t))
            o.update(site=SITE_ID[t], seed=line, p_auto=r1(pj.at[t, "p_auto"], 3), west=True,
                     adv=adv.get(t), exp_q1w=r1(pj.at[t, "exp_q1w"]))
            ours.append(o)
    ours.sort(key=lambda o: -o["p_bid"])
    regions = {}
    for reg, lines in B["regions"].items():
        regions[reg] = [{"seed": ln, "slot": (["team", int(field.team[field.overall == s_[1]].iloc[0])] if s_[0] == "team" else ["or", s_[1]])}
                        for ln, s_ in sorted(lines.items())]
    conf_bids = {}
    for r_ in rows:
        conf_bids[r_["conf"]] = conf_bids.get(r_["conf"], 0) + 1
    out = {
        "generated": now.isoformat(timespec="minutes"), "season": season, "season_label": f"{season - 1}-{str(season)[2:]}",
        "week": meta.get("week"), "previous": prev_key,
        "format": {"field": n_field, "auto": n_auto, "at_large": n_al, "opening_round_games": n_or},
        "field": rows, "regions": regions,
        "opening_round": [{"a": g_["a"], "b": g_["b"], "p_a": r1(g_["p"], 3), "pick": g_["pick"],
                           "seed": B["seed_of"][B["games"][i][0]][0], "region": B["seed_of"][B["games"][i][0]][1]} for i, g_ in enumerate(or_games)],
        "rounds": rounds, "champion": champ,
        "bubble": {"last_in": [brief(t) for t in B["last_in"]], "first_out": [brief(t) for t in B["first_out"]],
                   "next_out": [brief(t) for t in B["next_out"]]},
        "ours": ours, "conf_bids": dict(sorted(conf_bids.items(), key=lambda kv: -kv[1])),
        "backtest": {"hit": bt["hit"], "at_large": bt["at_large"], "exact": bt["exact"], "within1": bt["within1"], "seeds": bt["seeds"],
                     "seasons": [{k: v for k, v in x.items() if k not in ("missed_in", "wrong_in")} for x in bt["seasons"]]},
        "what_it_takes": wit,
        "model": {"selection": dict(zip(BK.FEATS, [round(float(b), 3) for b in sel.beta[:-1]])),
                  "seed": dict(zip(BK.FEATS, [round(float(b), 3) for b in seed.beta[:-1]]))},
        "sims": 1000,
    }
    dump("bracket.json", out)
    # ---- odds for every Division I team, grouped by league (Season odds tab, team pages)
    sp = Pj.attrs.get("sched_posted", {})
    odds = []
    for t in Pj.team:
        t = int(t)
        tm = tb.get(t)
        if not tm:
            continue
        x = pj.loc[t]
        pv = prev.get(str(t))
        odds.append({"id": t, "name": tm["name"], "abbr": tm["abbr"], "logo": tm["logo"], "conf": tm["conf"], "west": tm["west"],
                     "rank": tm["rank"], "net": tm["net"], "w": tm["w"], "l": tm["l"], "cw": tm["cw"], "cl": tm["cl"],
                     "exp_w": r1(x.exp_w), "exp_l": r1(x.exp_l), "exp_cw": r1(x.exp_cw), "exp_cl": r1(x.exp_cl),
                     "p_rs_title": r1(x.p_rs_title, 3), "p_tourney": r1(x.p_auto, 3), "p_bid": r1(x.p_bid, 3), "p_atlarge": r1(x.p_atlarge, 3),
                     "seed": seeds_now.get(str(t)), "adv": adv.get(t), "exp_q1w": r1(x.exp_q1w),
                     "q1w": int(x.q1w_now), "q1l": int(x.q1l_now), "q2w": int(x.q2w_now), "q2l": int(x.q2l_now), "badl": int(x.badl_now),
                     "safe_q1w": None if np.isnan(x.safe_q1w) else int(x.safe_q1w),
                     "prev_p_bid": prev_p(pv), "prev_seed": prev_seed(pv)})
    conf_list = sorted({o["conf"] for o in odds if o["conf"]}, key=lambda c: (c not in ("Pac-12", "Mountain West"), c != "Pac-12", c))
    est = {CONF.get(c): v for c, v in sp.items() if CONF.get(c)}
    dump("odds.json", {"generated": out["generated"], "previous": prev_key, "season_label": out["season_label"], "conferences": conf_list,
                       "schedule_posted": est, "teams": sorted(odds, key=lambda o: (o["conf"] or "", -(o["p_bid"] or 0), o["rank"]))})
    dump("bracket_history.json", hist)
    meta["bracket"] = {"generated": out["generated"], "champion": champ}
    log(f"  bracket: field of {len(rows)}, champion pick {tb.get(champ, {}).get('name')}")


if __name__ == "__main__":
    main()
