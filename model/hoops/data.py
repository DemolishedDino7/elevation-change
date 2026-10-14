"""Data layer for The Bot (men's basketball).

Pulls schedules, team box scores, rosters and player minutes from the public
sportsdataverse/hoopR-mbb-data mirror on GitHub (no API key needed; it is
built from ESPN's data and refreshed daily), caches them under
model/hoops/cache/, and builds one tidy games table with possessions and
every situational feature the model uses.

Season numbers follow the source: 2027 = the 2026-27 season.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
RAW = "https://raw.githubusercontent.com/sportsdataverse/hoopR-mbb-data/main/mbb"
FIRST_SEASON = 2012
GEO = {int(k): v for k, v in json.load(open(ROOT / "geo.json")).items()}
NON_D1 = -1  # every non-Division I opponent shares one rating
MT = pd.Timedelta(hours=-7)  # Mountain Standard Time (Nov-Mar): game "days" and weeks are in MT


def _fetch(rel: str, dest: Path, refresh: bool) -> Path | None:
    if dest.exists() and not refresh:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    try:
        urllib.request.urlretrieve(f"{RAW}/{rel}", tmp)
    except Exception:
        if dest.exists():
            return dest
        return None
    os.replace(tmp, dest)
    return dest


def download(current: int, refresh_current: bool = True) -> None:
    for y in range(FIRST_SEASON, current + 1):
        live = y >= current - 1 and refresh_current
        _fetch(f"schedules/parquet/mbb_schedule_{y}.parquet", CACHE / f"sch_{y}.parquet", live)
        _fetch(f"team_box/parquet/team_box_{y}.parquet", CACHE / f"tb_{y}.parquet", live)
        _fetch(f"rosters/parquet/rosters_{y}.parquet", CACHE / f"ro_{y}.parquet", live)
        # player box scores: past seasons once, the current season every run (who's playing, injuries)
        _fetch(f"player_box/parquet/player_box_{y}.parquet", CACHE / f"pb_{y}.parquet", y >= current - 1 and refresh_current)


def haversine_mi(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * np.arcsin(np.sqrt(a))


def _poss(tb: pd.DataFrame) -> pd.DataFrame:
    """Possessions per game (average of both teams' estimates)."""
    t = tb.copy()
    for c in ["field_goals_attempted", "offensive_rebounds", "total_turnovers", "turnovers", "free_throws_attempted"]:
        if c in t:
            t[c] = pd.to_numeric(t[c], errors="coerce")
    to = t["total_turnovers"].where(t["total_turnovers"].notna(), t.get("turnovers"))
    t["poss"] = t.field_goals_attempted - t.offensive_rebounds + to + 0.475 * t.free_throws_attempted
    g = t.groupby("game_id").agg(poss=("poss", "mean"), n=("poss", "size"))
    g = g[(g.n == 2) & g.poss.between(40, 110)]
    return g[["poss"]]


def schedule(season: int) -> pd.DataFrame:
    f = CACHE / f"sch_{season}.parquet"
    if not f.exists():
        return pd.DataFrame()
    s = pd.read_parquet(f)
    keep = {
        "game_id": "game_id", "season": "season", "season_type": "season_type", "date": "start", "time_valid": "time_valid",
        "neutral_site": "neutral", "conference_competition": "conf_game", "status_type_completed": "completed",
        "status_type_state": "state", "status_period": "periods", "venue_full_name": "venue", "venue_address_city": "city",
        "venue_address_state": "st", "notes_headline": "note", "tournament_id": "tournament_id",
        "home_id": "home_id", "home_location": "home", "home_abbreviation": "home_abbr", "home_conference_id": "home_conf",
        "home_score": "home_pts", "home_logo": "home_logo",
        "away_id": "away_id", "away_location": "away", "away_abbreviation": "away_abbr", "away_conference_id": "away_conf",
        "away_score": "away_pts", "away_logo": "away_logo",
    }
    s = s[[c for c in keep if c in s.columns]].rename(columns=keep)
    s["game_id"] = pd.to_numeric(s.game_id, errors="coerce")
    s = s.dropna(subset=["game_id", "home_id", "away_id"]).copy()
    for c in ["game_id", "home_id", "away_id"]:
        s[c] = s[c].astype("int64")
    s["start"] = pd.to_datetime(s.start, utc=True, errors="coerce")
    for c in ["home_pts", "away_pts", "periods", "home_conf", "away_conf"]:
        s[c] = pd.to_numeric(s.get(c), errors="coerce")
    for c in ["neutral", "conf_game", "completed", "time_valid"]:
        s[c] = s[c].fillna(False).astype(bool)
    s["season"] = season
    s["completed"] = s.completed & s.home_pts.notna() & s.away_pts.notna() & ((s.home_pts + s.away_pts) > 0)
    return s.drop_duplicates("game_id")


def d1_teams(season: int, current: int) -> set[int]:
    """Division I teams: 12+ box-score games that season (for the current season: last season's
    D-I teams plus everyone with a roster posted)."""
    if season < current and (CACHE / f"tb_{season}.parquet").exists():
        tb = pd.read_parquet(CACHE / f"tb_{season}.parquet", columns=["team_id"])
        c = pd.to_numeric(tb.team_id, errors="coerce").value_counts()
        return set(c[c >= 12].index.astype(int))
    out = d1_teams(season - 1, current) if season - 1 >= FIRST_SEASON else set()
    # plus newcomers: any team this season's schedule places in a Division I conference
    s = schedule(season)
    if not s.empty:
        conf = pd.concat([s[["home_id", "home_conf"]].set_axis(["t", "c"], axis=1),
                          s[["away_id", "away_conf"]].set_axis(["t", "c"], axis=1)]).dropna()
        d1_confs = set(conf[conf.t.isin(out)].c.value_counts().loc[lambda x: x >= 20].index)
        out |= set(conf[conf.c.isin(d1_confs)].t.astype(int))
    return out


def merge_patch(s: pd.DataFrame, patch: pd.DataFrame) -> pd.DataFrame:
    """Overlay ESPN scoreboard rows on the mirror's schedule: newer times, finals, added games.
    A final the mirror already has is never undone."""
    if patch is None or patch.empty:
        return s
    patch = patch.copy()
    patch["start"] = pd.to_datetime(patch.start, utc=True)
    base = s.set_index("game_id")
    for _, r in patch.iterrows():
        gid = int(r.game_id)
        if gid in base.index and bool(base.at[gid, "completed"]) and not r.completed:
            continue
        rec = {c: r[c] for c in patch.columns if c != "game_id" and pd.notna(r[c])}
        if gid in base.index:
            for c, v in rec.items():
                if c in base.columns:
                    base.at[gid, c] = v
        else:
            new = pd.DataFrame([rec], index=pd.Index([gid], name="game_id"))
            base = pd.concat([base, new])
    out = base.reset_index()
    for c in ["neutral", "conf_game", "completed", "time_valid"]:
        out[c] = out[c].fillna(False).astype(bool)
    return out


def games(current: int, patch: pd.DataFrame | None = None) -> pd.DataFrame:
    """Every game 2012-current, one row each, with possessions and situational features."""
    rows = []
    for y in range(FIRST_SEASON, current + 1):
        s = schedule(y)
        if y == current:
            s = merge_patch(s if not s.empty else pd.DataFrame(columns=["game_id", "completed"]), patch)
        if s.empty:
            continue
        tbf = CACHE / f"tb_{y}.parquet"
        if tbf.exists():
            s = s.merge(_poss(pd.read_parquet(tbf)), left_on="game_id", right_index=True, how="left")
        else:
            s["poss"] = np.nan
        d1 = d1_teams(y, current)
        s["home_d1"], s["away_d1"] = s.home_id.isin(d1), s.away_id.isin(d1)
        rows.append(s)
    g = pd.concat(rows, ignore_index=True)
    g = g[g.home_d1 | g.away_d1].copy()
    # game day in Mountain time; TBA games carry a midnight-Eastern placeholder for their date
    et = (g.start - pd.Timedelta(hours=5)).dt.normalize().dt.tz_localize(None)
    g["day"] = (g.start + MT).dt.normalize().dt.tz_localize(None).where(g.time_valid, et)
    # regulation-equivalent pace: possessions per 40 minutes
    ot = (g.periods.fillna(2) - 2).clip(lower=0)
    g["pace"] = g.poss * 40 / (40 + 5 * ot)
    g["margin"] = g.home_pts - g.away_pts
    g["total"] = g.home_pts + g.away_pts
    # where the game was played: home arena, or the neutral venue's city (best effort: a team in that city)
    lat = lambda t: GEO.get(int(t), [np.nan, np.nan, np.nan])
    hl = np.array([lat(t) for t in g.home_id], dtype=float)
    al = np.array([lat(t) for t in g.away_id], dtype=float)
    site = hl.copy()
    neu = g.neutral.to_numpy()
    city_site = _city_sites(g)
    for i in np.where(neu)[0]:
        site[i] = city_site.get((g.city.iat[i], g.st.iat[i]), [np.nan, np.nan, np.nan])
    g["site_elev"] = site[:, 2]
    g["home_elev"], g["away_elev"] = hl[:, 2], al[:, 2]
    g["home_travel"] = np.where(neu, haversine_mi(hl[:, 0], hl[:, 1], site[:, 0], site[:, 1]), 0.0)
    g["away_travel"] = haversine_mi(al[:, 0], al[:, 1], site[:, 0], site[:, 1])
    # altitude the visitor climbs to play here (feet), and the same for the "home" team at a neutral site
    g["away_climb"] = np.clip(g.site_elev - g.away_elev, 0, None)
    g["home_climb"] = np.clip(g.site_elev - g.home_elev, 0, None)
    for c in ["home_travel", "away_travel", "away_climb", "home_climb"]:
        g[c] = g[c].fillna(0.0)
    g = _rest(g)
    return g.sort_values(["start", "game_id"]).reset_index(drop=True)


def _city_sites(g: pd.DataFrame) -> dict:
    """(city, state) -> [lat, lon, elev] using a team whose home arena is in that city."""
    h = g[~g.neutral].dropna(subset=["city"])
    out = {}
    for (c, st), tid in h.groupby(["city", "st"]).home_id.agg(lambda x: x.mode().iat[0]).items():
        if int(tid) in GEO:
            out[(c, st)] = GEO[int(tid)]
    return out


def _rest(g: pd.DataFrame) -> pd.DataFrame:
    """Days since each team's previous game (capped at 7; 7 for a season opener)."""
    long = pd.concat([g[["game_id", "season", "day", "home_id"]].rename(columns={"home_id": "team"}).assign(side="h"),
                      g[["game_id", "season", "day", "away_id"]].rename(columns={"away_id": "team"}).assign(side="a")])
    long = long.sort_values(["team", "season", "day"])
    long["rest"] = long.groupby(["team", "season"]).day.diff().dt.days.clip(upper=7).fillna(7)
    r = long.pivot_table(index="game_id", columns="side", values="rest", aggfunc="first")
    g = g.merge(r.rename(columns={"h": "home_rest", "a": "away_rest"}), left_on="game_id", right_index=True, how="left")
    g[["home_rest", "away_rest"]] = g[["home_rest", "away_rest"]].fillna(7)
    return g


def rosters_and_minutes(current: int):
    """(rosters by season: team -> set(athlete ids), player minutes by season: athlete -> (team, minutes))."""
    ro, mins = {}, {}
    for y in range(FIRST_SEASON, current + 1):
        f = CACHE / f"ro_{y}.parquet"
        if f.exists():
            r = pd.read_parquet(f, columns=["team_id", "athlete_id"])
            r = r.apply(pd.to_numeric, errors="coerce").dropna().astype("int64")
            ro[y] = r
    # ESPN's live rosters (fetched each morning) replace the mirror's for the teams ESPN has
    live = CACHE / "ro_live.json"
    if live.exists():
        try:
            lv = json.load(open(live))
            if lv.get("season") == current and lv.get("teams"):
                rows = [(int(t), int(a)) for t, ath in lv["teams"].items() for a in ath]
                L = pd.DataFrame(rows, columns=["team_id", "athlete_id"])
                base = ro.get(current, L.iloc[0:0])
                ro[current] = pd.concat([base[~base.team_id.isin(L.team_id)], L], ignore_index=True)
        except Exception:
            pass
    for y in range(FIRST_SEASON, current + 1):
        f = CACHE / f"pb_{y}.parquet"
        if f.exists():
            p = pd.read_parquet(f, columns=["athlete_id", "team_id", "minutes"])
            p = p.apply(pd.to_numeric, errors="coerce").dropna()
            p = p.groupby(["athlete_id", "team_id"], as_index=False).minutes.sum()
            mins[y] = p.astype({"athlete_id": "int64", "team_id": "int64"})
    return ro, mins
