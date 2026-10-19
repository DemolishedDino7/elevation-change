"""Preseason exhibition results for every Division I team, from each school's official schedule page.

ESPN and the public data mirrors don't carry exhibitions, so the Bot reads the
schools' own athletics sites (almost all run on Sidearm). Any game dated before
the season's first official day is an exhibition. Results go to
model/hoops/exhibitions.csv (one row per game per team, by ESPN team id); rows marked
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
WEST = {"BSU": 68, "CSU": 36, "FRES": 278, "GONZ": 2250, "ORST": 204, "SDSU": 21, "TXST": 326, "USU": 328, "WSU": 265,
        "AFA": 2005, "GCU": 2253, "HAW": 62, "NEV": 2440, "UNM": 167, "SJSU": 23, "UCD": 302, "UNLV": 2439, "UTEP": 2638,
        "WYO": 2751, "NDSU": 2449, "NIU": 2459, "NMSU": 166, "SAC": 16}
SITES_FILE = ROOT / "school_sites.json"   # ESPN team id -> {"name", "url"}: every D-I school's schedule page
PATHS = ["/sports/mens-basketball/schedule", "/sports/mbball/schedule"]
COLS = ["season", "team", "date", "opponent", "site", "result", "team_pts", "opp_pts", "source"]
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def fetch(dom: str, url: str | None = None) -> str | None:
    for p in ([url] if url else []) + ["https://" + dom + q for q in PATHS]:
        try:
            req = urllib.request.Request(p, headers={"User-Agent": UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf8", "replace")
        except Exception:
            continue
    return None


EXH_RE = re.compile(r"\s*[\(\[](?:exhibition|exh|exb|exhib|ex|exhibition game|scrimmage|closed scrimmage|charity exhibition)\.?[\)\]]\s*", re.I)


WD = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WD_RE = re.compile(r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b", re.I)


def weekday_ok(L: list[str], k: int, d: date) -> bool:
    """A page still showing last season gives the right month and day but the wrong weekday
    ("Oct 28 (Tue)" was 2025). If a weekday is printed next to the date, it has to match."""
    for j in (k, k + 1, k - 1):
        if 0 <= j < len(L) and len(L[j]) <= 24:
            m = WD_RE.search(L[j])
            if m:
                return WD[d.weekday()] == m.group(1)[:3].lower()
    return True


RANK_RE = re.compile(r"^\s*(No\.?\s*|#)\d+(/\d+)?\s*$")


def clean_opp(s: str) -> str:
    s = H.unescape(re.sub(r"\s+", " ", s)).strip()
    s = EXH_RE.sub("", s)
    s = re.sub(r"^\s*(Preseason|Exhibition|Exh)\s*[-:]\s*", "", s, flags=re.I)
    s = re.sub(r"^\s*(No\.?\s*|#)\d+(/\d+)?\s*", "", s)
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
        try:
            a_, b_ = int(re.sub(r"\D", "", str(r["team_score"]))), int(re.sub(r"\D", "", str(r["opponent_score"])))
        except ValueError:
            continue
        if "basketball" not in json.dumps(o).lower() and "mbb" not in json.dumps(o).lower():
            continue
        if not plausible(a_, b_) or (r["status"] == "W") != (a_ > b_):
            continue   # another sport's score from a site-wide scoreboard
        out.append({"date": str(d), "opponent": clean_opp((o.get("opponent") or {}).get("title", "")),
                    "site": {"H": "home", "A": "away"}.get(o.get("location_indicator"), "neutral"),
                    "result": r["status"], "team_pts": int(re.sub(r"\D", "", str(r["team_score"]))), "opp_pts": int(re.sub(r"\D", "", str(r["opponent_score"])))})
    return out


def plausible(a: int, b: int) -> bool:
    """A men's basketball score (keeps other sports' results out)."""
    return 35 <= a <= 160 and 35 <= b <= 160 and a != b


def lines_of(h: str) -> list[str]:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S)
    t = H.unescape(re.sub(r"<[^>]+>", "\n", t))
    return [l.strip() for l in t.split("\n") if l.strip()]


DATE_RE = re.compile(r"^(?:[A-Z][a-z]{2},? )?(Oct|Nov|Sep)[a-z]*\.? ?(\d{1,2})\b|^(\d{1,2})\.(\d{1,2})\.(\d{2})$")
SCORE_RE = re.compile(r"^(\d{2,3})\s*-\s*(\d{2,3})$")


TEAMS: set[str] = set()   # known school names (normalized), filled by main() from the schedule data
ALIAS = {"texas christian": "tcu", "southern california": "usc", "brigham young": "byu", "louisiana state": "lsu",
         "southern methodist": "smu", "central florida": "ucf", "nevada las vegas": "unlv", "texas el paso": "utep"}


def _n(s: str) -> str:
    s = re.sub(r"[^a-z0-9& ]", "", clean_opp(s).lower().replace("é", "e")).strip()
    return ALIAS.get(s, s)


def from_text(h: str, opener: date, season: int) -> list[dict]:
    """Every other layout: walk the page text. Each result (W/L plus a score) anchors one game; its
    date, opponent and home/away are the nearest ones between the previous and next result, so a
    score can never attach to a game that hasn't been played."""
    L, out = lines_of(h), []
    year = season - 1

    def as_date(l):
        m = DATE_RE.match(l)
        if not m:
            return None
        if m.group(1):
            return date(year, MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
        return date(2000 + int(m.group(5)), int(m.group(3)), int(m.group(4)))

    anchors = []
    for i, l in enumerate(L):
        r = l.rstrip(",").strip()
        if r in ("W", "L", "Win", "Loss"):
            for k in (1, 2):
                if i + k < len(L) and SCORE_RE.match(L[i + k]):
                    anchors.append((i, "W" if r in ("W", "Win") else "L", SCORE_RE.match(L[i + k])))
                    break
    seen = set()
    for n, (i, res, sc) in enumerate(anchors):
        lo = anchors[n - 1][0] + 3 if n else max(0, i - 40)
        hi = anchors[n + 1][0] if n + 1 < len(anchors) else min(len(L), i + 40)
        if any(x[1] == res and x[2].group(0) == sc.group(0) for x in anchors[:n]):
            continue   # the same result shown twice on the page
        before = [(i - k, k) for k in range(lo, i) if as_date(L[k])]
        after = [(k - i, k) for k in range(i, hi) if as_date(L[k])]
        dk = (min(before) if before else min(after) if after else (0, None))[1]
        d = as_date(L[dk]) if dk is not None else None
        if d is not None and not weekday_ok(L, dk, d):
            continue
        if not plausible(int(sc.group(1)), int(sc.group(2))):
            continue
        # opponent: a known school name closest before the result, else a line marked as an exhibition
        ok_line = lambda k: not RANK_RE.match(L[k]) and "hide/show" not in L[k].lower() and "information for" not in L[k].lower() and len(L[k]) < 60
        opps = [k for k in range(lo, i) if _n(L[k]) in TEAMS and ok_line(k)]
        if not opps:
            opps = [k for k in range(lo, i) if EXH_RE.search(L[k]) and ok_line(k)]
        if d is None or not opps:
            continue
        ok = opps[-1]
        if d >= opener:
            continue
        a, b = int(sc.group(1)), int(sc.group(2))
        tp, op = (max(a, b), min(a, b)) if res == "W" else (min(a, b), max(a, b))
        marks = [L[k].lower() for k in range(max(lo, ok - 4), ok)]
        after_opp = [L[k].lower() for k in range(ok + 1, i)]
        if "neutral" in after_opp or "home" in after_opp or "away" in after_opp:
            site = "neutral" if "neutral" in after_opp else "home" if "home" in after_opp else "away"
        else:
            site = "away" if any(m in ("at", "away") for m in marks) else "home" if any(m in ("vs", "vs.", "home") for m in marks) else "neutral"
        key = (str(d), clean_opp(L[ok]))
        if key in seen:
            continue
        seen.add(key)
        out.append({"date": str(d), "opponent": key[1], "site": site, "result": res, "team_pts": tp, "opp_pts": op})
    return out


CARD = re.compile(r'data-test-id="s-game-card-standard__root"|<li[^>]+class="sidearm-schedule-game[ "]|<tr[^>]+class="[^"]*sidearm-schedule-game')


def from_cards(h: str, opener: date, season: int) -> list[dict]:
    """Sidearm layouts where each game is its own card (nextgen "s-game-card", classic "sidearm-schedule-game"):
    everything about a game sits inside its card, so date, opponent and result can't come from another game."""
    starts = [m.start() for m in CARD.finditer(h)]
    out, seen = [], set()
    for a, b in zip(starts, starts[1:] + [len(h)]):
        L = lines_of(h[a:b])
        d = None
        for dk, l in enumerate(L):
            m = DATE_RE.match(l)
            if m:
                if m.group(1):
                    mo = MONTHS[m.group(1)[:3].lower()]
                    d = date(season - 1 if mo >= 7 else season, mo, int(m.group(2)))
                else:
                    d = date(2000 + int(m.group(5)), int(m.group(3)), int(m.group(4)))
                if not weekday_ok(L, dk, d):
                    d = None
                break
        if d is None or d >= opener:
            continue
        res = sc = None
        for n, l in enumerate(L):
            r = l.rstrip(",").strip()
            if r in ("W", "L", "Win", "Loss"):
                for k in (1, 2):
                    if n + k < len(L) and SCORE_RE.match(L[n + k]):
                        res, sc = ("W" if r in ("W", "Win") else "L"), SCORE_RE.match(L[n + k])
                        break
            if res:
                break
        if not res or not plausible(int(sc.group(1)), int(sc.group(2))):
            continue
        opp, site = None, "neutral"
        for n, l in enumerate(L[:-1]):
            if l.lower() in ("vs", "vs.", "at", "@"):
                nxt = [x for x in L[n + 1:n + 4] if not RANK_RE.match(x)]
                opp, site = (nxt[0] if nxt else None), ("away" if l.lower() in ("at", "@") else "home")
                break
        low = [l.lower() for l in L]
        if "neutral" in low or "neutral site" in low:
            site = "neutral"
        if opp is None:
            opp = next((l for l in L if EXH_RE.search(l)), None)
        if not opp:
            continue
        x, y = int(sc.group(1)), int(sc.group(2))
        tp, op = (max(x, y), min(x, y)) if res == "W" else (min(x, y), max(x, y))
        key = (str(d), clean_opp(opp))
        if key in seen:
            continue
        seen.add(key)
        out.append({"date": str(d), "opponent": key[1], "site": site, "result": res, "team_pts": tp, "opp_pts": op})
    return out


def parse(h: str, opener: date, season: int) -> list[dict]:
    """Best reader for this page's layout: embedded game data, then game cards, then plain text."""
    if CARD.search(h):
        got = from_cards(h, opener, season)
        if got:
            return got
    return from_json(h, opener) or from_text(h, opener, season)


def collect(season: int, opener: date, save_raw: bool = False) -> list[dict]:
    rows = []
    RAW.mkdir(exist_ok=True)
    sites = {str(WEST[k]): {"name": k, "url": "https://" + d + "/sports/mens-basketball/schedule"} for k, d in SITES.items()}
    if SITES_FILE.exists():
        for k, v in json.load(open(SITES_FILE)).items():
            sites.setdefault(k, v)
    for sid, info in sites.items():
        h = fetch(re.sub(r"^https?://([^/]+).*$", r"\1", info["url"]), info["url"])
        if h is None:
            print(f"{sid}: page not reachable")
            continue
        if save_raw:
            (RAW / f"{sid}.html.gz").write_bytes(gzip.compress(h.encode()))
        got = [g for g in parse(h, opener, season) if g["date"] <= str(date.today())]   # never a game not yet played
        uniq = {(g["date"], g["opponent"]): g for g in got}
        for g in uniq.values():
            rows.append({"season": season, "team": sid, **g, "source": "auto"})
        print(f"{sid}: {len(uniq)} exhibition results")
    return rows


def load_names() -> None:
    import pandas as pd
    for f in sorted(Path(ROOT / "cache").glob("sch_*.parquet"))[-2:]:
        sch = pd.read_parquet(f)
        for c in ("home_location", "away_location", "home_display_name", "away_display_name"):
            TEAMS.update(_n(x) for x in sch[c].dropna().unique())
    TEAMS.update(ALIAS.values())


def main(season: int, opener: str) -> None:
    op = date.fromisoformat(opener)
    load_names()
    have = list(csv.DictReader(open(OUT))) if OUT.exists() else []
    manual = [r for r in have if r["source"] == "manual" or int(r["season"]) != season]
    keys = {(r["season"], r["team"], r["date"]) for r in manual}
    auto = [r for r in collect(season, op) if (str(r["season"]), r["team"], r["date"]) not in keys]
    rows = sorted(manual + auto, key=lambda r: (int(r["season"]), r["date"], r["team"]))
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)


def season_and_opener(today: date) -> tuple[int, date]:
    """Season (2027 = 2026-27) and its first regular-season day: from the cached schedule if there,
    otherwise the first Monday of November."""
    season = today.year + 1 if today.month >= 7 else today.year
    f = ROOT / "cache" / f"sch_{season}.parquet"
    if f.exists():
        import pandas as pd
        s = pd.read_parquet(f, columns=["date", "season_type"])
        reg = pd.to_datetime(s[s.season_type == 2].date, utc=True)
        if len(reg):
            return season, reg.min().date()
    d = date(season - 1, 11, 1)
    return season, date(d.year, 11, 1 + (0 - d.weekday()) % 7)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a:
        main(int(a[0]), a[1])
    else:
        today = date.today()
        season, opener = season_and_opener(today)
        if today > date.fromordinal(opener.toordinal() + 7):
            print(f"exhibition season is over (opener {opener})")
        else:
            main(season, str(opener))
