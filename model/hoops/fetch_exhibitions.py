"""Preseason exhibition results for our 23 teams, from each school's official schedule page.

ESPN and the public data mirrors don't carry exhibitions, so the Bot reads the
schools' own athletics sites (almost all run on Sidearm). Any game dated before
the season's first official day is an exhibition. Results go to
model/hoops/exhibitions.csv (one row per game per our team); rows marked
source=manual are never overwritten, so a wrong or missing result can be fixed
by hand.

Run from GitHub Actions (.github/workflows/hoops-bot.yml, morning run).
"""
from __future__ import annotations

import csv
import gzip
import html as H
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "exhibitions.csv"
RAW = ROOT / "exh_pages"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
SITES = {"BSU": "broncosports.com", "CSU": "csurams.com", "FRES": "gobulldogs.com", "GONZ": "gozags.com", "ORST": "osubeavers.com",
         "SDSU": "goaztecs.com", "TXST": "txst.com", "USU": "utahstateaggies.com", "WSU": "wsucougars.com", "AFA": "goairforcefalcons.com",
         "GCU": "gculopes.com", "HAW": "hawaiiathletics.com", "NEV": "nevadawolfpack.com", "UNM": "golobos.com", "SJSU": "sjsuspartans.com",
         "UCD": "ucdavisaggies.com", "UNLV": "unlvrebels.com", "UTEP": "utepminers.com", "WYO": "gowyo.com", "NDSU": "gobison.com",
         "NIU": "niuhuskies.com", "NMSU": "nmstatesports.com", "SAC": "hornetsports.com"}
PATHS = ["/sports/mens-basketball/schedule", "/sports/mbball/schedule"]
COLS = ["season", "team", "date", "opponent", "site", "result", "team_pts", "opp_pts", "source"]
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def fetch(dom: str) -> str | None:
    for p in PATHS:
        try:
            req = urllib.request.Request("https://" + dom + p, headers={"User-Agent": UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf8", "replace")
        except Exception:
            continue
    return None


def clean_opp(s: str) -> str:
    s = H.unescape(re.sub(r"\s+", " ", s)).strip()
    s = re.sub(r"\s*\((Exhibition|Exh\.?|exhibition)\)\s*", "", s)
    s = re.sub(r"^(University of |The )", "", s)
    return s.replace(" University", "").strip(" -|")


def from_json(h: str, opener: date) -> list[dict]:
    """Sidearm pages that embed each game as JSON ({"id":..,"date":..,"opponent":..,"result":..})."""
    dec, out, seen = json.JSONDecoder(), [], set()
    for m in re.finditer(r'\{"id":\d+,"date":"(20\d\d-\d\d-\d\d)', h):
        try:
            o, _ = dec.raw_decode(h, m.start())
        except Exception:
            continue
        if "result" not in o or "opponent" not in o or o["id"] in seen:
            continue
        seen.add(o["id"])
        d = date.fromisoformat(o["date"][:10])
        r = o.get("result") or {}
        if d >= opener or r.get("status") not in ("W", "L") or not r.get("team_score"):
            continue
        out.append({"date": str(d), "opponent": clean_opp((o.get("opponent") or {}).get("title", "")),
                    "site": {"H": "home", "A": "away"}.get(o.get("location_indicator"), "neutral"),
                    "result": r["status"], "team_pts": int(re.sub(r"\D", "", str(r["team_score"]))), "opp_pts": int(re.sub(r"\D", "", str(r["opponent_score"])))})
    return out


def lines_of(h: str) -> list[str]:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S)
    t = H.unescape(re.sub(r"<[^>]+>", "\n", t))
    return [l.strip() for l in t.split("\n") if l.strip()]


DATE_RE = re.compile(r"^(?:[A-Z][a-z]{2},? )?(Oct|Nov|Sep)[a-z]*\.? ?(\d{1,2})\b|^(\d{1,2})\.(\d{1,2})\.(\d{2})$")
SCORE_RE = re.compile(r"^(\d{2,3})\s*-\s*(\d{2,3})$")


def from_text(h: str, opener: date, season: int) -> list[dict]:
    """Every other layout: walk the page text. A game block starts at a date line; within the block
    we need an opponent marked as exhibition (or any game before the opener), W/L and a score."""
    L, out = lines_of(h), []
    year = season - 1
    starts = []
    for i, l in enumerate(L):
        m = DATE_RE.match(l)
        if m:
            if m.group(1):
                d = date(year, MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
            else:
                d = date(2000 + int(m.group(5)), int(m.group(3)), int(m.group(4)))
            starts.append((i, d))
    for k, (i, d) in enumerate(starts):
        if d >= opener:
            continue
        j = starts[k + 1][0] if k + 1 < len(starts) else min(len(L), i + 40)
        # some layouts put the date after the result: look a little before the date too
        blk = L[max(0, i - 14): j]
        res = next((x.rstrip(",").strip() for x in blk if x.rstrip(",").strip() in ("W", "L", "Win", "Loss")), None)
        sc = next((SCORE_RE.match(x) for x in blk if SCORE_RE.match(x)), None)
        opp = next((x for x in blk if re.search(r"\((Exhibition|Exh\.?|exhibition)\)", x)), None)
        if not opp:
            vs = next((n for n, x in enumerate(blk) if x.lower() in ("vs", "vs.", "at")), None)
            opp = blk[vs + 1] if vs is not None and vs + 1 < len(blk) else None
        if not (res and sc and opp):
            continue
        a, b = int(sc.group(1)), int(sc.group(2))
        win = res in ("W", "Win")
        tp, op = (max(a, b), min(a, b)) if win else (min(a, b), max(a, b))
        at = any(x.lower() == "at" for x in blk) or any(x.lower() == "away" for x in blk)
        out.append({"date": str(d), "opponent": clean_opp(opp), "site": "away" if at else "home",
                    "result": "W" if win else "L", "team_pts": tp, "opp_pts": op})
    return out


def collect(season: int, opener: date, save_raw: bool = True) -> list[dict]:
    rows = []
    RAW.mkdir(exist_ok=True)
    for sid, dom in SITES.items():
        h = fetch(dom)
        if h is None:
            print(f"{sid}: page not reachable")
            continue
        if save_raw:
            (RAW / f"{sid}.html.gz").write_bytes(gzip.compress(h.encode()))
        got = from_json(h, opener) or from_text(h, opener, season)
        uniq = {(g["date"], g["opponent"]): g for g in got}
        for g in uniq.values():
            rows.append({"season": season, "team": sid, **g, "source": "auto"})
        print(f"{sid}: {len(uniq)} exhibition results")
    return rows


def main(season: int, opener: str) -> None:
    op = date.fromisoformat(opener)
    have = list(csv.DictReader(open(OUT))) if OUT.exists() else []
    manual = [r for r in have if r["source"] == "manual" or int(r["season"]) != season]
    keys = {(r["season"], r["team"], r["date"]) for r in manual}
    auto = [r for r in collect(season, op) if (str(r["season"]), r["team"], r["date"]) not in keys]
    rows = sorted(manual + auto, key=lambda r: (int(r["season"]), r["date"], r["team"]))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2])
