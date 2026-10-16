"""Download Bart Torvik's season player tables (one row per player-season, including
each player's recruiting rank and class) into model/hoops/torvik/players_YYYY.csv.gz.
Run from GitHub Actions (barttorvik.com isn't reachable from every network).
Used by prior.py to learn what incoming freshmen and transfers are worth."""
from __future__ import annotations

import gzip
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "torvik"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def get(year: int) -> bytes:
    req = urllib.request.Request(f"https://barttorvik.com/getadvstats.php?year={year}&csv=1", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main(first: int, last: int) -> None:
    OUT.mkdir(exist_ok=True)
    for y in range(first, last + 1):
        dest = OUT / f"players_{y}.csv.gz"
        try:
            body = get(y)
        except Exception as e:
            print(f"{y}: failed ({e})")
            continue
        head = body[:300].decode("utf-8", "replace")
        if "<html" in head.lower() or body.count(b"\n") < 500:
            print(f"{y}: not a CSV ({len(body)} bytes): {head[:120]!r}")
            continue
        with gzip.open(dest, "wb") as f:
            f.write(body)
        print(f"{y}: {body.count(b'\n')} rows")
        time.sleep(2)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(int(a[0]) if a else 2012, int(a[1]) if len(a) > 1 else 2026)
