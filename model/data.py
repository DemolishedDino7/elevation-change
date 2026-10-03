"""Data layer for The Bot.

Pulls game results, venues and betting lines from the public
sportsdataverse/cfbfastR-data mirror on GitHub (no API key needed),
caches them under model/cache/, and builds one tidy games table with
every situational feature the model uses.
"""
from __future__ import annotations

import math
import os
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
RAW = "https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/main"
FIRST_SEASON = 2010
DIVS = {"fbs", "fcs"}


def _fetch(rel: str, dest: Path, refresh: bool) -> Path:
    if dest.exists() and not refresh:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    urllib.request.urlretrieve(f"{RAW}/{rel}", tmp)
    os.replace(tmp, dest)
    return dest


def download(current: int, refresh_current: bool = True) -> None:
    for y in range(FIRST_SEASON, current + 1):
        live = y >= current - 1 and refresh_current
        _fetch(f"schedules/parquet/cfb_schedules_{y}.parquet", CACHE / f"sch_{y}.parquet", live)
        _fetch(f"team_info/parquet/cfb_team_info_{y}.parquet", CACHE / f"ti_{y}.parquet", live)
    _fetch("betting/parquet/cfb_line_odds.parquet", CACHE / "lines.parquet", refresh_current)


def haversine_mi(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * np.arcsin(np.sqrt(a))


def team_info(current: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(team-season locations, venue locations)."""
    rows = []
    for y in range(FIRST_SEASON, current + 1):
        t = pd.read_parquet(CACHE / f"ti_{y}.parquet")
        t["season"] = y
        rows.append(t)
    t = pd.concat(rows, ignore_index=True)
    keep = ["season", "team_id", "school", "abbreviation", "conference", "classification", "color",
            "alt_color", "logo", "venue_id", "latitude", "longitude", "elevation", "timezone"]
    t = t[keep].copy()
    for c in ["team_id", "venue_id", "latitude", "longitude", "elevation"]:
        t[c] = pd.to_numeric(t[c], errors="coerce")
    t = t.dropna(subset=["team_id"])
    t["team_id"] = t.team_id.astype("int64")
    # carry locations across seasons when a year is missing them
    t = t.sort_values(["team_id", "season"])
    for c in ["latitude", "longitude", "elevation"]:
        t[c] = t.groupby("team_id")[c].transform(lambda s: s.ffill().bfill())
    venues = (t.dropna(subset=["venue_id", "latitude"])
               .sort_values("season").drop_duplicates("venue_id", keep="last")
               [["venue_id", "latitude", "longitude", "elevation"]])
    return t, venues


def _norm(s) -> str:
    return "".join(ch for ch in str(s).lower().replace("&", "and").replace("state", "st") if ch.isalnum())


def closing_lines(g: pd.DataFrame, current: int) -> pd.DataFrame:
    """Consensus (median across books) closing home spread, opening spread and total per game.

    Older seasons in the source use sportsbook abbreviations and sometimes lack a
    game_id, so we (1) recover missing ids by matching 'Away@Home' + date against
    the schedule using every known alias of each school, and (2) learn which
    abbreviation belongs to which team from how often they co-occur.
    """
    l = pd.read_parquet(CACHE / "lines.parquet",
                        columns=["game_id", "game_desc", "date_time", "market_type", "abbr", "lines", "opening_lines", "book"])
    ti = pd.concat([pd.read_parquet(CACHE / f"ti_{y}.parquet") for y in range(FIRST_SEASON, current + 1)])
    alias = {}
    for c in ["school", "alt_name1", "alt_name2", "alt_name3", "abbreviation"]:
        for k, v in zip(ti[c], ti.school):
            if pd.notna(k):
                alias.setdefault(_norm(k), v)
    for k in list(ti.school.dropna().unique()):
        alias[_norm(k)] = k

    miss = l.game_id.isna() & l.game_desc.str.contains("@", na=False)
    if miss.any():
        m = l[miss].copy()
        parts = m.game_desc.str.split("@", n=1, expand=True)
        m["a"] = parts[0].map(lambda x: alias.get(_norm(x)))
        m["h"] = parts[1].map(lambda x: alias.get(_norm(x)))
        m["d"] = pd.to_datetime(m.date_time, errors="coerce").dt.tz_localize(None).dt.normalize()
        key = g[["game_id", "home_team", "away_team", "start"]].copy()
        key["d"] = key.start.dt.tz_convert(None).dt.normalize()
        hits = []
        for shift in (0, 1, -1):
            k2 = key.assign(d=key.d + pd.Timedelta(days=shift))
            hits.append(m.reset_index().merge(k2, left_on=["h", "a", "d"], right_on=["home_team", "away_team", "d"]).set_index("index").game_id_y)
        found = pd.concat(hits)
        found = found[~found.index.duplicated()]
        l.loc[found.index, "game_id"] = found.values

    l = l.dropna(subset=["game_id"]).copy()
    l["game_id"] = l.game_id.astype("int64")
    sp = l[l.market_type == "spread"].merge(g[["game_id", "home_team", "away_team"]], on="game_id")
    # learn abbreviation -> team
    co = pd.concat([sp[["abbr", "home_team"]].rename(columns={"home_team": "t"}),
                    sp[["abbr", "away_team"]].rename(columns={"away_team": "t"})])
    cnt = co.groupby(["abbr", "t"]).size().rename("n").reset_index().sort_values("n")
    amap = cnt.drop_duplicates("abbr", keep="last").set_index("abbr").t
    sp["side_team"] = sp.abbr.map(amap)
    sp.loc[sp.abbr == sp.home_team, "side_team"] = sp.home_team
    sp.loc[sp.abbr == sp.away_team, "side_team"] = sp.away_team
    home = sp[sp.side_team == sp.home_team]
    away = sp[sp.side_team == sp.away_team].copy()
    away["lines"] = -away["lines"]
    away["opening_lines"] = -away["opening_lines"]
    both = pd.concat([home, away])
    both = both[both.lines.abs() < 70]
    cons = both.groupby("game_id").agg(close=("lines", "median"), open=("opening_lines", "median"))
    tot = l[(l.market_type == "total") & (l.abbr == "over") & l.lines.between(20, 110)].groupby("game_id").lines.median()
    cons["total"] = tot
    return cons


def build_games(current: int) -> pd.DataFrame:
    frames = []
    for y in range(FIRST_SEASON, current + 1):
        s = pd.read_parquet(CACHE / f"sch_{y}.parquet")
        frames.append(s)
    g = pd.concat(frames, ignore_index=True)
    g = g[g.home_division.isin(DIVS) & g.away_division.isin(DIVS)].copy()
    g = g[g.season_type.isin(["regular", "postseason"])]
    g["start"] = pd.to_datetime(g.start_date, utc=True, errors="coerce")
    g["completed"] = g.completed.fillna(False).astype(bool) & g.home_points.notna() & g.away_points.notna()
    g["neutral_site"] = g.neutral_site.fillna(False).astype(bool)
    g["conference_game"] = g.conference_game.fillna(False).astype(bool)
    g = g.drop_duplicates("game_id").sort_values(["season", "start", "game_id"]).reset_index(drop=True)
    # week index that is monotone across regular + postseason
    g["wk"] = np.where(g.season_type == "postseason", 20, g.week).astype(int)

    ti, venues = team_info(current)
    loc = ti[["season", "team_id", "latitude", "longitude", "elevation", "conference", "classification"]]
    for side in ("home", "away"):
        m = loc.rename(columns={c: f"{side}_{c}" for c in loc.columns if c not in ("season",)})
        m = m.rename(columns={f"{side}_team_id": f"{side}_id"})
        g = g.merge(m[["season", f"{side}_id", f"{side}_latitude", f"{side}_longitude", f"{side}_elevation"]],
                    on=["season", f"{side}_id"], how="left")
    # fill missing team locations from any season
    anyloc = ti.dropna(subset=["latitude"]).drop_duplicates("team_id", keep="last").set_index("team_id")
    for side in ("home", "away"):
        for c in ("latitude", "longitude", "elevation"):
            col = f"{side}_{c}"
            g[col] = g[col].fillna(g[f"{side}_id"].map(anyloc[c]))

    v = venues.set_index("venue_id")
    g["v_lat"] = g.venue_id.map(v.latitude)
    g["v_lon"] = g.venue_id.map(v.longitude)
    g["v_elev"] = g.venue_id.map(v.elevation)
    # a home game with an unknown venue is at the home team's stadium
    home_game = ~g.neutral_site
    for a, b in (("v_lat", "home_latitude"), ("v_lon", "home_longitude"), ("v_elev", "home_elevation")):
        g.loc[home_game & g[a].isna(), a] = g.loc[home_game & g[a].isna(), b]

    for side in ("home", "away"):
        d = haversine_mi(g[f"{side}_latitude"], g[f"{side}_longitude"], g.v_lat, g.v_lon)
        g[f"{side}_travel"] = d.fillna(0.0 if side == "home" else 600.0)
        g.loc[(side == "home") & home_game, f"{side}_travel"] = 0.0
        # meters of elevation gained by coming to this venue (only uphill hurts)
        g[f"{side}_climb"] = (g.v_elev - g[f"{side}_elevation"]).clip(lower=0).fillna(0.0)
        g[f"{side}_tz"] = ((g[f"{side}_longitude"] - g.v_lon).abs() / 15.0).fillna(0.0)

    # rest days
    long = pd.concat([
        g[["game_id", "season", "start", "home_id"]].rename(columns={"home_id": "tid"}).assign(side="home"),
        g[["game_id", "season", "start", "away_id"]].rename(columns={"away_id": "tid"}).assign(side="away"),
    ]).sort_values(["tid", "start"])
    long["prev"] = long.groupby(["tid", "season"]).start.shift()
    long["rest"] = ((long.start - long.prev).dt.total_seconds() / 86400).clip(upper=21).fillna(21)
    r = long.pivot_table(index="game_id", columns="side", values="rest")
    g["home_rest"] = g.game_id.map(r["home"]).fillna(21)
    g["away_rest"] = g.game_id.map(r["away"]).fillna(21)

    # closing lines
    cons = closing_lines(g, current)
    g["vegas_spread"] = g.game_id.map(cons["close"])  # negative = home favored
    g["vegas_open"] = g.game_id.map(cons["open"])
    g["vegas_total"] = g.game_id.map(cons["total"])

    g["margin"] = g.home_points - g.away_points
    g["total"] = g.home_points + g.away_points
    keep = ["game_id", "season", "week", "wk", "season_type", "start", "completed", "neutral_site", "conference_game",
            "venue_id", "venue", "home_id", "home_team", "home_division", "home_conference", "home_points",
            "away_id", "away_team", "away_division", "away_conference", "away_points", "v_elev",
            "home_travel", "away_travel", "home_climb", "away_climb", "home_tz", "away_tz", "home_rest", "away_rest",
            "home_elevation", "away_elevation", "vegas_spread", "vegas_open", "vegas_total", "margin", "total", "notes"]
    g = g[keep].copy()
    g["notes"] = g.notes.astype("string")
    return g


def teams_table(current: int) -> pd.DataFrame:
    ti, _ = team_info(current)
    return ti[ti.season == current].set_index("team_id")
