"""Preseason exhibitions in the Bot's starting ratings (exhibitions.csv, from fetch_exhibitions.py).

Only games between two Division I teams count: a non-D-I opponent has no
rating to judge the result against. Each one is graded against what the
starting ratings expected (site included, in points per 100 possessions,
capped like real games) and counts as half a game next to a preseason start
worth four, so one big exhibition moves a team about 1-3 points per 100.
The opponent moves the other way. Exhibitions never count in the résumé.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import numpy as np
import pandas as pd

FILE = Path(__file__).resolve().parent / "exhibitions.csv"
WEIGHT = 0.5      # games' worth of each D-I exhibition
CAP = 30.0        # cap on a result's miss, per 100 possessions (same as real games)


def _n(s: str) -> str:
    s = re.sub(r"[^a-z0-9& ]", "", str(s).lower().replace("é", "e")).strip()
    return {"texas christian": "tcu", "southern california": "usc", "brigham young": "byu"}.get(s, s)


def load(season: int, our_ids: dict, cur: pd.DataFrame) -> list[dict]:
    """Exhibitions this season with ESPN ids for both sides (opp_id None when not D-I/unknown).
    our_ids: site id (e.g. "BSU") -> ESPN id; cur: this season's schedule (for names)."""
    if not FILE.exists():
        return []
    name_id = {}
    for side in ("home", "away"):
        for col in (side, f"{side}_display"):
            if col in cur:
                for n, i in zip(cur[col], cur[f"{side}_id"]):
                    name_id.setdefault(_n(n), int(i))
    out, seen = [], set()
    for r in csv.DictReader(open(FILE)):
        if int(r["season"]) != season or r["team"] not in our_ids:
            continue
        t = int(our_ids[r["team"]])
        o = name_id.get(_n(r["opponent"]))
        key = (r["date"], frozenset((t, o if o is not None else r["opponent"])))
        if key in seen:      # the same game from both teams' pages
            continue
        seen.add(key)
        out.append({"date": r["date"], "team": t, "opp": o, "opp_name": r["opponent"], "site": r["site"],
                    "result": r["result"], "pts": int(r["team_pts"]), "opp_pts": int(r["opp_pts"])})
    return out


def adjust(P: pd.DataFrame, games: list[dict], hca: float, tmu: float, lam: float) -> pd.Series:
    """Net shift (points per 100 possessions) for every team in P from its D-I exhibitions."""
    num = pd.Series(0.0, index=P.index)
    cnt = pd.Series(0.0, index=P.index)
    for g in games:
        t, o = g["team"], g["opp"]
        if o is None or t not in P.index or o not in P.index:
            continue
        exp = (P.at[t, "O"] - P.at[t, "D"]) - (P.at[o, "O"] - P.at[o, "D"])
        exp += {"home": hca, "away": -hca}.get(g["site"], 0.0)
        poss = max(55.0, tmu + P.at[t, "T"] + P.at[o, "T"])
        obs = 100.0 * (g["pts"] - g["opp_pts"]) / poss
        miss = float(np.clip(obs - exp, -CAP, CAP))
        g["exp"], g["miss"] = round(exp * poss / 100, 1), round(miss * poss / 100, 1)
        for team, sgn in ((t, 1.0), (o, -1.0)):
            num[team] += sgn * miss * WEIGHT
            cnt[team] += WEIGHT
    return (num / (lam + cnt)).where(cnt > 0, 0.0)
