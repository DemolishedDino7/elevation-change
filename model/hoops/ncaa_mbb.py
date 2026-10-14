"""Fallback for same-night finals when ESPN's scoreboard refuses us: ncaa.com's
scoreboard (the football Bot's source), matched to our schedule by team names
with the football Bot's matcher. Best-effort; the daily mirror is the backstop."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(1, str(Path(__file__).resolve().parents[1]))  # model/ (football's ncaa.py)
import ncaa as N  # noqa: E402


def finals(sched: pd.DataFrame, season: int, days, log=print) -> tuple[pd.DataFrame, dict]:
    status = {"ok": False, "contests": 0, "matched": 0, "finals": 0, "error": None}
    try:
        cs = []
        for d in days:
            for yr in (season - 1, season):
                data = N._get(N.Q_SCOREBOARD, {"sportCode": "MBB", "division": 1, "seasonYear": yr,
                                               "contestDate": d.strftime("%m/%d/%Y"), "week": None})
                got = (data.get("data") or {}).get("contests") or []
                if got:
                    cs += got
                    break
        status["contests"] = len(cs)
        s = sched.rename(columns={"home": "home_team", "away": "away_team"})
        pairs = N.match(cs, s)
        status["matched"] = len(pairs)
        rows = []
        for idx, m in pairs:
            c = m["contest"]
            if c.get("gameState") != "F":
                continue
            hp, ap = m["home"].get("score"), m["away"].get("score")
            if hp is None or ap is None:
                continue
            rows.append({"game_id": int(s.at[idx, "game_id"]), "completed": True, "state": "post",
                         "home_pts": float(hp), "away_pts": float(ap)})
        status.update(ok=True, finals=len(rows))
        log(f"NCAA fallback: {len(cs)} contests, {len(pairs)} matched, {len(rows)} finals")
        return pd.DataFrame(rows), status
    except Exception as e:
        status["error"] = repr(e)[:300]
        log("NCAA fallback unavailable:", status["error"])
        return pd.DataFrame(), status
