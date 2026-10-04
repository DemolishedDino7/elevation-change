"""Official NCAA game data (ncaa.com's stats service).

Used for two things:
  * same-night results: final scores the public archive hasn't picked up yet
    (it refreshes only around midnight MT Saturday and Sunday), so late West
    Coast and Hawai'i games make the Sunday-morning update;
  * official team box scores for the Elevation Index (yards, plays, third
    downs, turnovers including lost fumbles, sacks).

Everything here is best-effort: if ncaa.com changes its feed, the pipeline
falls back to the archive alone and nothing breaks.
"""
from __future__ import annotations

import json
import time
import unicodedata
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

import numpy as np
import pandas as pd

from data import CACHE

BASE = "https://sdataprod.ncaa.com/"
Q_SCOREBOARD = ("GetContests_web", "7287cda610a9326931931080cb3a604828febe6fe3c9016a7e4a36db99efdb7c")
Q_TEAMSTATS = ("GetGamecenterTeamStatsFootball_web", "b41348ee662d9236483167395b16bb6ab36b12e2908ef6cd767685ea8a2f59bd")
DIVISIONS = (11, 12)  # FBS, FCS


def _get(query, variables, tries=3):
    meta, sha = query
    ext = json.dumps({"persistedQuery": {"version": 1, "sha256Hash": sha}}, separators=(",", ":"))
    var = json.dumps(variables, separators=(",", ":"))
    url = f"{BASE}?meta={meta}&extensions={urllib.parse.quote(ext)}&variables={urllib.parse.quote(var)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ElevationChange TheBot)"})
    for i in range(tries):
        try:
            return json.load(urllib.request.urlopen(req, timeout=30))
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def scoreboard(season: int, week: int) -> list[dict]:
    out = []
    for d in DIVISIONS:
        data = _get(Q_SCOREBOARD, {"sportCode": "MFB", "division": d, "seasonYear": season, "contestDate": None, "week": week})
        out += data.get("data", {}).get("contests", []) or []
    seen, uniq = set(), []
    for c in out:
        if c["contestId"] not in seen:
            seen.add(c["contestId"])
            uniq.append(c)
    return uniq


def team_stats(contest_id: int) -> dict | None:
    """{ncaa seoname: stats} for a final game. Cached forever once final."""
    f = CACHE / "ncaa" / f"ts_{contest_id}.json"
    if f.exists():
        return json.load(open(f))
    data = _get(Q_TEAMSTATS, {"contestId": str(contest_id), "staticTestEnv": None})
    bx = (data.get("data") or {}).get("boxscore")
    if not bx or bx.get("status") != "F":
        return None
    seo = {str(t["teamId"]): t["seoname"] for t in bx["teams"]}
    res = {}
    for tb in bx.get("teamBoxscore", []):
        s = tb.get("teamStats") or {}
        n = lambda k, d=s: float(d.get(k) or 0)
        res[seo[str(tb["teamId"])]] = {
            "yds": n("teamYards"), "plays": n("teamPlays"),
            "third_conv": n("thirdDowns"), "third_att": n("thirdDownAttempts"),
            "fum_lost": n("fumblesLost"), "ints": n("passingInterceptions", s.get("TeamPassingStats") or {}),
            "sacks": n("sacks", s.get("TeamDefenseStats") or {}),
        }
    if len(res) == 2:
        f.parent.mkdir(exist_ok=True)
        json.dump(res, open(f, "w"))
        return res
    return None


# ---------- matching NCAA names to ours ----------
SUBS = [("st.", "state"), ("st ", "state "), ("ky.", "kentucky"), ("mich.", "michigan"), ("fla.", "florida"),
        ("ga.", "georgia"), ("ill.", "illinois"), ("ala.", "alabama"), ("miss.", "mississippi"), ("tenn.", "tennessee"),
        ("la.", "louisiana"), ("ark.", "arkansas"), ("ariz.", "arizona"), ("calif.", "california"), ("colo.", "colorado"),
        ("n.c.", "north carolina"), ("s.c.", "south carolina"), ("ind.", "indiana"), ("conn.", "connecticut"),
        ("wash.", "washington"), ("okla.", "oklahoma"), ("ore.", "oregon"), ("mo.", "missouri"), ("va.", "virginia"),
        ("tex.", "texas"), ("so.", "southern"), ("int'l", "international"), ("u.", "university"), ("&", "and")]


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower() + " "
    for a, b in SUBS:
        s = s.replace(a, b)
    s = s.replace("-", " ")
    return " ".join("".join(ch if ch.isalnum() or ch == " " else " " for ch in s).split())


# our name -> how ncaa.com writes it, where the two differ beyond abbreviations
ALIAS = {"USC": "southern california", "Florida International": "fiu", "Long Island University": "long island",
         "UL Monroe": "ulm", "Louisiana": "louisiana", "Miami": "miami fl", "Miami (OH)": "miami oh",
         "Northern Illinois": "niu", "Massachusetts": "umass", "Sam Houston": "sam houston state",
         "App State": "appalachian state", "Southern Miss": "southern mississippi",
         "UT Rio Grande Valley": "utrgv", "Alcorn State": "alcorn", "SE Louisiana": "southeastern louisiana",
         "Northern Iowa": "uni", "Incarnate Word": "uiw", "Stephen F. Austin": "sfa", "East Texas A&M": "east texas a and m",
         "Texas A&M-Commerce": "east texas a and m", "Mississippi Valley State": "mississippi val",
         "Arkansas-Pine Bluff": "arkansas pine bluff", "Prairie View A&M": "prairie view", "Houston Christian": "houston christian",
         "Florida Atlantic": "florida atlantic", "Middle Tennessee": "middle tennessee", "UMass": "umass",
         "Southern Illinois": "southern illinois", "Northern Arizona": "northern arizona", "North Alabama": "north alabama"}


def _sim(a: str, b: str) -> float:
    """a: an ncaa.com name, b: our name."""
    a = norm(a)
    best = 0.0
    for cand in {norm(b), norm(ALIAS.get(b, b))}:
        if a == cand:
            return 1.0
        best = max(best, SequenceMatcher(None, a, cand).ratio())
    return best


def _names(team: dict) -> list[str]:
    return [team.get("nameShort") or "", (team.get("seoname") or "").replace("-", " "), team.get("nameFull") or ""]


def match(contests: list[dict], games: pd.DataFrame) -> list[tuple[int, dict]]:
    """Pair NCAA contests with schedule rows: same day (±1), both team names must match well,
    and every contest and every game is used at most once (best pairs first)."""
    g = games.copy()
    g["day"] = (g.start - pd.Timedelta(hours=6)).dt.date
    cands = []
    for c in contests:
        if len(c.get("teams", [])) != 2:
            continue
        home = next((t for t in c["teams"] if t.get("isHome")), c["teams"][0])
        away = next(t for t in c["teams"] if t is not home)
        day = pd.Timestamp(int(c["startTimeEpoch"]), unit="s", tz="UTC") - pd.Timedelta(hours=6)
        near = g[(g.day >= (day - pd.Timedelta(days=1)).date()) & (g.day <= (day + pd.Timedelta(days=1)).date())]
        for i, r in near.iterrows():
            sh = max(_sim(n, r.home_team) for n in _names(home))
            sa = max(_sim(n, r.away_team) for n in _names(away))
            fh = max(_sim(n, r.away_team) for n in _names(home))
            fa = max(_sim(n, r.home_team) for n in _names(away))
            s1, s2 = min(sh, sa), min(fh, fa)
            sc, flip = (s2, True) if s2 > s1 else (s1, False)
            if sc >= 0.82:
                cands.append((sc, i, c["contestId"], flip, c, home, away))
    cands.sort(key=lambda x: -x[0])
    used_rows, used_contests, out = set(), set(), []
    for sc, i, cid, flip, c, home, away in cands:
        if i in used_rows or cid in used_contests:
            continue
        used_rows.add(i)
        used_contests.add(cid)
        out.append((i, {"contest": c, "flip": flip, "home": away if flip else home, "away": home if flip else away,
                        "score": round(sc, 3)}))
    return out


def patch(g: pd.DataFrame, season: int, weeks: list[int], log=print) -> tuple[pd.DataFrame, dict, dict]:
    """Fill final scores the archive is missing. Returns (games, ncaa ids by game_id, status)."""
    status = {"ok": False, "contests": 0, "matched": 0, "filled": [], "error": None}
    ids = {}
    try:
        cs = []
        for w in weeks:
            cs += scoreboard(season, w)
        status["contests"] = len(cs)
        sg = g[g.season == season]
        pairs = match(cs, sg)
        status["matched"] = len(pairs)
        g = g.copy()
        for idx, m in pairs:
            c = m["contest"]
            gid = int(g.at[idx, "game_id"])
            ids[gid] = {"contest": int(c["contestId"]), "home_seo": m["home"]["seoname"], "away_seo": m["away"]["seoname"]}
            if c.get("gameState") != "F" or g.at[idx, "completed"]:
                continue
            hp, ap = m["home"].get("score"), m["away"].get("score")
            if hp is None or ap is None:
                continue
            g.at[idx, "home_points"], g.at[idx, "away_points"] = float(hp), float(ap)
            g.at[idx, "completed"] = True
            g.at[idx, "margin"], g.at[idx, "total"] = float(hp) - float(ap), float(hp) + float(ap)
            status["filled"].append(f"{g.at[idx, 'away_team']} {int(ap)} at {g.at[idx, 'home_team']} {int(hp)}")
        status["ok"] = True
        log(f"NCAA: {len(cs)} contests, {len(pairs)} matched, {len(status['filled'])} new finals")
    except Exception as e:  # never let this break the run
        status["error"] = repr(e)[:300]
        log("NCAA feed unavailable:", status["error"])
    return g, ids, status
