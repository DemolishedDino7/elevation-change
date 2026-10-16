"""High school recruits for the preseason prior (recruits.csv, from fetch_recruits.py).

Each season's incoming freshmen are the previous class's ranked recruits who
signed with that school. On3 names schools its own way ("Gonzaga University
Bulldogs"), so they're matched to ESPN team ids by mascot plus location words.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

import data

FILE = Path(__file__).resolve().parent / "recruits.csv"
# rank tiers the prior learns a value for (On3 Industry national rank)
TIERS = [("r10", 1, 10), ("r25", 11, 25), ("r50", 26, 50), ("r100", 51, 100)]
ALIAS = {"connecticut": "uconn", "usf": "south florida", "loyola chi": "loyola chicago", "missourikansas city": "kansas city",
         "illinoischicago": "uic", "new jersey institute of technology": "njit", "arkansaslittle rock": "little rock",
         "wisconsingreen bay": "green bay", "wisconsinmilwaukee": "milwaukee", "middle tennessee state": "middle tennessee",
         "texas a  m universitycorpus christi": "texas aandmcorpus christi", "the university of texas at arlington": "ut arlington",
         "california state universityfullerton": "cal state fullerton", "california state universitylong beach": "long beach state",
         "university of californiairvine": "uc irvine", "university of californiasanta barbara": "uc santa barbara",
         "saint marys college of california": "saint marys", "college of charleston": "charleston"}
# a few On3 names whose mascot or place ESPN spells differently
EXPLICIT = {"Appalachian State Mountaineers": "App State Mountaineers", "California State University-Long Beach 49ers": "Long Beach State Beach",
            "Missouri-Kansas City Kangaroos": "Kansas City Roos", "Texas A & M University-Corpus Christi Islanders": "Texas A&M-Corpus Christi Islanders"}
DROP = re.compile(r"\b(university|college|of|the)\b")


def _norm(x: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", str(x).lower().replace("&", "and").replace("é", "e"))).strip()


def team_names(current: int) -> pd.DataFrame:
    rows = []
    for y in range(current - 6, current + 1):
        f = data.CACHE / f"sch_{y}.parquet"
        if not f.exists():
            continue
        s = pd.read_parquet(f)
        for side in ("home", "away"):
            c = [f"{side}_id", f"{side}_location", f"{side}_name", f"{side}_display_name"]
            if all(k in s for k in c):
                rows.append(s[c].set_axis(["id", "loc", "mascot", "disp"], axis=1))
    t = pd.concat(rows).dropna().drop_duplicates("id", keep="last")
    t["id"] = pd.to_numeric(t["id"], errors="coerce")
    return t.dropna(subset=["id"]).astype({"id": "int64"})


def match(schools, current: int) -> dict:
    """On3 school name -> ESPN team id (None if not D-I or not found)."""
    T = team_names(current)
    disp = {_norm(d): i for d, i in zip(T.disp, T.id)}
    out = {}
    for s in schools:
        n = _norm(EXPLICIT.get(s, s))
        if n in disp:
            out[s] = disp[n]
            continue
        best, score = None, 0
        for i, loc, mas in zip(T.id, T["loc"], T.mascot):
            m = _norm(mas)
            if not m or not n.endswith(m):
                continue
            place = n[: -len(m)].strip()
            place = ALIAS.get(place, place)
            a, b = set(DROP.sub(" ", place).split()), set(_norm(loc).split())
            sc = len(a & b) / max(1, len(a | b))
            if place == _norm(loc):
                sc = 2
            if sc > score:
                best, score = i, sc
        out[s] = best if score >= 0.5 else None
    return out


def load(current: int) -> pd.DataFrame:
    """Ranked recruits with an ESPN team id: class, rank, team_id."""
    if not FILE.exists():
        return pd.DataFrame(columns=["class", "rank", "team_id"])
    r = pd.read_csv(FILE)
    r = r[r.school.notna() & r["rank"].notna()]
    ids = match(sorted(set(r.school)), current)
    r = r.assign(team_id=r.school.map(ids)).dropna(subset=["team_id"])
    return r.astype({"team_id": "int64", "rank": "int64", "class": "int64"})


def features(season: int, teams, rec: pd.DataFrame) -> pd.DataFrame:
    """Incoming freshmen by rank tier (counts) for each team."""
    r = rec[rec["class"] == season - 1]
    out = pd.DataFrame(index=pd.Index(teams, name="team"))
    for name, lo, hi in TIERS:
        out[name] = r[(r["rank"] >= lo) & (r["rank"] <= hi)].groupby("team_id").size().reindex(out.index).fillna(0.0)
    return out
