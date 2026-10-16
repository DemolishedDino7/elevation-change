"""High school recruiting rankings for the basketball Bot's preseason prior.

Pulls On3's Industry ranking (a composite of the major services, like 247's
composite) for every class from 2011 on and writes model/hoops/recruits.csv:
one row per ranked recruit with his class, national rank, rating, stars and
the school he signed with. Class Y plays its first college season in Y-Y+1,
which the model calls season Y+1.

Runs from GitHub Actions (.github/workflows/fetch-recruits.yml). Past classes
never change; the current and next class are refreshed weekly in the fall.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "recruits.csv"
URL = "https://www.on3.com/rivals/rankings/industry-player/basketball/{y}/?page={p}"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
COLS = ["class", "rank", "rating", "stars", "name", "school", "school_abbr", "position", "state", "enrolled", "signed"]


def page(y: int, p: int) -> tuple[list, int]:
    req = urllib.request.Request(URL.format(y=y, p=p), headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=60) as r:
        h = r.read().decode("utf8", "replace")
    d = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S).group(1))
    pdd = d["props"]["pageProps"].get("playerData") or {}
    return pdd.get("list") or [], (pdd.get("pagination") or {}).get("pageCount") or 0


def row(y: int, x: dict) -> dict:
    per = x.get("person") or {}
    st = per.get("status") or {}
    ind = next((r for r in x.get("ratings") or [] if r.get("type") == "Industry"), {}) or {}
    team = x.get("collegeTeam") or {}
    return {"class": y, "rank": x.get("overallRank") or ind.get("overallRank"),
            "rating": round(ind.get("rating") or 0, 2) or "", "stars": ind.get("stars") or "",
            "name": per.get("name") or "", "school": team.get("fullName") or "", "school_abbr": team.get("abbreviation") or "",
            "position": x.get("positionAbbreviation") or "", "state": x.get("stateAbbreviation") or "",
            "enrolled": int(bool(st.get("isEnrolled"))), "signed": int(bool(st.get("isSigned")))}


def fetch(y: int) -> list[dict]:
    rows, p, pages = [], 1, 1
    while p <= pages:
        lst, pages = page(y, p)
        rows += [row(y, x) for x in lst]
        p += 1
        time.sleep(1.5)
    return rows


def main(first: int, last: int) -> None:
    keep = []
    if OUT.exists():
        keep = [r for r in csv.DictReader(open(OUT)) if not (first <= int(r["class"]) <= last)]
    new = []
    for y in range(first, last + 1):
        try:
            rs = fetch(y)
            print(f"class {y}: {len(rs)} recruits, {sum(1 for r in rs if r['school'])} with a school")
            new += rs
        except Exception as e:
            print(f"class {y}: failed ({e}); keeping what we had")
            keep += [r for r in csv.DictReader(open(OUT)) if int(r["class"]) == y] if OUT.exists() else []
    allr = sorted(keep + new, key=lambda r: (int(r["class"]), int(r["rank"] or 9999)))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(allr)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]) if a else 2011, int(a[1]) if len(a) > 1 else 2026)
