"""ESPN's public scoreboard: same-night finals, schedule changes and pregame lines.

The data mirror refreshes once a day, so this fills the gap: final scores the
night they happen, games added or moved since the mirror's last refresh, and the
betting line ESPN shows before tip (saved so live picks can be graded against
Vegas; the Bot never uses lines to make a pick).

Game ids are ESPN's, the same ids the mirror uses, so nothing has to be matched
by name. Everything here is best-effort: if the feed fails, the run continues on
the mirror alone.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import date, timedelta

import pandas as pd

URL = ("https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
       "?dates={d}&groups=50&limit=500")


def _get(url: str, tries: int = 3) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ElevationChange TheBot)"})
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    return {}


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _home_spread(odds: dict, h_abbr: str, a_abbr: str):
    """Home team's spread from ESPN's odds block (negative = home favored)."""
    if not odds:
        return None
    det = (odds.get("details") or "").strip()
    if det.upper() in ("EVEN", "PK", "PICK"):
        return 0.0
    m = re.match(r"^([A-Za-z&.'\- ]+?)\s*([-+]?\d+(?:\.\d+)?)$", det)
    if m:
        who, val = m.group(1).strip().upper(), float(m.group(2))
        if who == (h_abbr or "").upper():
            return val
        if who == (a_abbr or "").upper():
            return -val
    ht = odds.get("homeTeamOdds") or {}
    sp = _num(odds.get("spread"))
    if sp is not None:
        if ht.get("favorite") is True:
            return -abs(sp)
        if ht.get("favorite") is False:
            return abs(sp)
    return None


def parse(ev: dict, season: int) -> tuple[dict, dict | None] | None:
    comp = (ev.get("competitions") or [{}])[0]
    cs = comp.get("competitors") or []
    if len(cs) != 2:
        return None
    home = next((c for c in cs if c.get("homeAway") == "home"), cs[0])
    away = next(c for c in cs if c is not home)
    st = ((comp.get("status") or ev.get("status") or {}).get("type") or {})
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    ht, at = home.get("team") or {}, away.get("team") or {}
    done = bool(st.get("completed"))
    row = {
        "game_id": int(ev["id"]), "season": season, "season_type": int((ev.get("season") or {}).get("type") or 2),
        "start": pd.Timestamp(ev.get("date")), "time_valid": bool(comp.get("timeValid", True)),
        "neutral": bool(comp.get("neutralSite")), "conf_game": bool(comp.get("conferenceCompetition")),
        "completed": done, "state": st.get("state"), "periods": _num((comp.get("status") or {}).get("period")),
        "venue": venue.get("fullName"), "city": addr.get("city"), "st": addr.get("state"),
        "note": ((comp.get("notes") or [{}])[0] or {}).get("headline"),
        "home_id": int(ht.get("id")), "home": ht.get("location"), "home_abbr": ht.get("abbreviation"),
        "home_conf": _num(ht.get("conferenceId")), "home_pts": _num(home.get("score")) if done else None,
        "home_logo": ht.get("logo"),
        "away_id": int(at.get("id")), "away": at.get("location"), "away_abbr": at.get("abbreviation"),
        "away_conf": _num(at.get("conferenceId")), "away_pts": _num(away.get("score")) if done else None,
        "away_logo": at.get("logo"),
    }
    line = None
    odds = (comp.get("odds") or [None])[0]
    if odds and st.get("state") == "pre":
        sp = _home_spread(odds, row["home_abbr"], row["away_abbr"])
        ou = _num(odds.get("overUnder"))
        if sp is not None or ou is not None:
            line = {"spread": sp, "total": ou, "provider": (odds.get("provider") or {}).get("name")}
    return row, line


def fetch(days: list[date], season: int, log=print) -> tuple[pd.DataFrame, dict, dict]:
    """(schedule-shaped rows, {game_id: line}, status)."""
    status = {"ok": False, "days": 0, "events": 0, "finals": 0, "lines": 0, "error": None}
    rows, lines = [], {}
    try:
        for d in days:
            data = _get(URL.format(d=d.strftime("%Y%m%d")))
            status["days"] += 1
            for ev in data.get("events") or []:
                try:
                    p = parse(ev, season)
                except Exception:
                    continue
                if not p:
                    continue
                row, line = p
                rows.append(row)
                if line:
                    lines[row["game_id"]] = line
        df = pd.DataFrame(rows).drop_duplicates("game_id", keep="last") if rows else pd.DataFrame()
        status.update(ok=True, events=len(df), finals=int(df.completed.sum()) if len(df) else 0, lines=len(lines))
        log(f"ESPN: {status['events']} games over {status['days']} days, {status['finals']} final, {status['lines']} lines")
        return df, lines, status
    except Exception as e:  # never let this break the run
        status["error"] = repr(e)[:300]
        log("ESPN scoreboard unavailable:", status["error"])
        return pd.DataFrame(), {}, status


def window(today: date, back: int = 2, ahead: int = 7) -> list[date]:
    return [today + timedelta(days=i) for i in range(-back, ahead + 1)]
