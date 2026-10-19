"""Preseason exhibitions (every D-I team) in the Bot's starting ratings (exhibitions.csv, from fetch_exhibitions.py).

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
    s = str(s).lower().replace("é", "e").replace("&", " and ")
    s = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", s)           # (Exh.), [Exh], (Ariz.)
    s = re.sub(r"^\s*(preseason|exhibition|exh)\s*[-:]\s*", "", s)    # "Preseason - Charlotte"
    s = re.sub(r"^\s*(no\.?\s*|#)\d+(/\d+)?\s*", "", s)              # "No. 2/2 Florida", "#14 Kansas"
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(university|univ|college|of|the|at)\b", " ", s)
    s = re.sub(r"\bst\b", "state", s) if not re.match(r"^\s*st\b", s) else re.sub(r"^\s*st\b", "saint", s)
    s = re.sub(r"\s+", " ", s).strip()
    return ALIAS.get(s, s)


ALIAS = {"texas christian": "tcu", "southern california": "usc", "brigham young": "byu", "louisiana state": "lsu",
         "southern methodist": "smu", "central florida": "ucf", "nevada las vegas": "unlv", "texas el paso": "utep",
         "north carolina state": "nc state", "virginia commonwealth": "vcu", "connecticut": "uconn", "mississippi": "ole miss",
         "miami fl": "miami", "miami florida": "miami", "miami ohio": "miami oh", "pennsylvania": "penn", "saint marys california": "saint marys",
         "massachusetts": "umass", "alabama birmingham": "uab", "texas san antonio": "utsa", "citadel": "the citadel",
         "california baptist": "california baptist", "loyola chicago": "loyola chicago", "texas arlington": "ut arlington",
         "tennessee martin": "ut martin", "wisconsin green bay": "green bay", "wisconsin milwaukee": "milwaukee",
         "illinois chicago": "uic", "maryland baltimore county": "umbc", "missouri kansas city": "kansas city",
         "texas rio grande valley": "ut rio grande valley", "utrgv": "ut rio grande valley", "fiu": "florida international",
         "fau": "florida atlantic", "csu bakersfield": "cal state bakersfield", "csu fullerton": "cal state fullerton",
         "csun": "cal state northridge", "csu northridge": "cal state northridge", "lmu": "loyola marymount", "uc santa barbara": "uc santa barbara", "unc": "north carolina"}


def names(current: int) -> dict:
    """Normalized school name -> ESPN team id, from recent schedules (location, full and short names, abbreviation)."""
    import data
    out = {}
    for y in (current, current - 1):
        f = data.CACHE / f"sch_{y}.parquet"
        if not f.exists():
            continue
        s = pd.read_parquet(f)
        for side in ("home", "away"):
            ids = pd.to_numeric(s[f"{side}_id"], errors="coerce")
            for col in (f"{side}_location", f"{side}_display_name", f"{side}_short_display_name", f"{side}_abbreviation", f"{side}_name"):
                if col not in s or col.endswith("_name") and not col.endswith("display_name"):
                    continue
                for n, i in zip(s[col], ids):
                    if pd.notna(i) and isinstance(n, str):
                        out.setdefault(_n(n), int(i))
            # location without trailing state abbreviation, e.g. "Miami (OH)" -> "miami oh"
            for n, i in zip(s[f"{side}_location"], ids):
                if pd.notna(i) and isinstance(n, str):
                    out.setdefault(_n(n.replace("(", " ").replace(")", " ")), int(i))
    return out


def load(season: int, our_ids: dict, cur: pd.DataFrame = None) -> list[dict]:
    """Exhibitions this season with ESPN ids for both sides (opp None when the opponent isn't Division I).
    The team column is an ESPN team id (older rows may use our site ids, e.g. "BSU", mapped by our_ids)."""
    if not FILE.exists():
        return []
    name_id = names(season)
    rows = [r for r in csv.DictReader(open(FILE)) if int(r["season"]) == season]
    for r in rows:
        r["_t"] = int(our_ids[r["team"]]) if r["team"] in our_ids else int(r["team"])
        r["_o"] = name_id.get(_n(r["opponent"]))
    # a page that lists the result before the opponent can pin a score on the wrong opponent (Nebraska's
    # loss to BYU read as a second Saint Louis game). When two games on one day share a team and the
    # same score, keep the one the schools' own pages back up: a school whose page we read but that
    # shows no game that day counts against it.
    readable = set()
    sf = FILE.parent / "school_sites.json"
    if sf.exists():
        import json
        readable = {int(k) for k in json.load(open(sf))}
    on_day = {(r["_t"], r["date"]) for r in rows}
    def support(t, o, d):
        rep = sum(1 for r in rows if r["date"] == d and {r["_t"], r["_o"]} == {t, o})
        against = sum(1 for x in (t, o) if x in readable and (x, d) not in on_day)
        return rep - against
    groups = {}
    for r in rows:
        if r["_o"] is None:
            continue
        sc = tuple(sorted((int(r["team_pts"]), int(r["opp_pts"]))))
        for shared in (r["_t"], r["_o"]):
            other = r["_o"] if shared == r["_t"] else r["_t"]
            groups.setdefault((shared, r["date"], sc), {}).setdefault(other, []).append(r)
    drop = set()
    for (shared, d, sc), opps in groups.items():
        if len(opps) > 1:
            best = max(opps, key=lambda o: support(shared, o, d))
            for o, rs in opps.items():
                if o != best:
                    drop |= {id(x) for x in rs}
    rows = [r for r in rows if id(r) not in drop]
    games = {}
    flip = {"home": "away", "away": "home", "neutral": "neutral"}
    for r in rows:
        t, o = r["_t"], r["_o"]
        if o == t:
            continue
        g = {"date": r["date"], "team": t, "opp": o, "opp_name": r["opponent"], "site": r["site"],
             "result": r["result"], "pts": int(r["team_pts"]), "opp_pts": int(r["opp_pts"])}
        key = (r["date"], frozenset((t, o if o is not None else _n(r["opponent"]))))
        # one school's layout can misplace the date: same matchup and score within two weeks is one game
        for k2, h2 in games.items():
            if k2[1] == key[1] and k2[0] != key[0] and abs((pd.Timestamp(k2[0]) - pd.Timestamp(key[0])).days) <= 14 \
                    and sorted((h2["pts"], h2["opp_pts"])) == sorted((g["pts"], g["opp_pts"])):
                key = k2
                break
        if key not in games:
            games[key] = g
            continue
        # the same game from both schools' pages: if they disagree on where it was, call it neutral
        h = games[key]
        other_site = h["site"] if h["team"] == t else flip[h["site"]]
        if other_site != g["site"]:
            h["site"] = "neutral"
    out = list(games.values())
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
