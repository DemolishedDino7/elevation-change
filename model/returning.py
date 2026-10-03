"""Returning production and transfer-portal production.

For each team-season, how much of last year's production is back:
  qb_ret     share of last season's passing yards thrown by players still on the roster
  skill_ret  share of rushing + receiving yards
  def_ret    share of defensive havoc plays (sacks, INTs, breakups, forced fumbles)
  qb_in / skill_in  production arriving from players who were on *other* teams last
                    year (the transfer portal), relative to this team's own total
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data import CACHE


def _prod(season: int) -> pd.DataFrame:
    p = pd.read_parquet(CACHE / f"ps_{season}.parquet")
    rows = []
    for idc, ycol, kind in [("completion_player_id", "completion_yds", "pass"),
                            ("rush_player_id", "rush_yds", "skill"),
                            ("reception_player_id", "reception_yds", "skill")]:
        d = p[p[idc].notna()][[idc, "team", ycol]].rename(columns={idc: "pid", ycol: "v"})
        d["kind"] = kind
        rows.append(d)
    for idc in ["sack_player_id", "interception_player_id", "pass_breakup_player_id", "fumble_forced_player_id"]:
        if idc in p:
            d = p[p[idc].notna()][[idc, "team"]].rename(columns={idc: "pid"})
            d["v"] = 1.0
            d["kind"] = "def"
            rows.append(d)
    d = pd.concat(rows)
    d["pid"] = pd.to_numeric(d.pid, errors="coerce")
    d = d.dropna(subset=["pid"])
    d["pid"] = d.pid.astype("int64")
    d["v"] = d.v.fillna(0).clip(lower=0)
    return d.groupby(["pid", "team", "kind"]).v.sum().reset_index()


def _roster(season: int) -> pd.DataFrame:
    r = pd.read_parquet(CACHE / f"ro_{season}.parquet", columns=["athlete_id", "team"])
    r["pid"] = pd.to_numeric(r.athlete_id, errors="coerce")
    r = r.dropna(subset=["pid"])
    r["pid"] = r.pid.astype("int64")
    return r[["pid", "team"]].drop_duplicates("pid", keep="last").rename(columns={"team": "now"})


def returning(season: int) -> pd.DataFrame:
    prev = _prod(season - 1)
    ro = _roster(season)
    m = prev.merge(ro, on="pid", how="left")
    tot = prev.groupby(["team", "kind"]).v.sum().unstack(fill_value=0)
    back = m[m.now == m.team].groupby(["team", "kind"]).v.sum().unstack(fill_value=0).reindex(tot.index, fill_value=0)
    inc = m[m.now.notna() & (m.now != m.team)].groupby(["now", "kind"]).v.sum().unstack(fill_value=0)
    inc = inc.reindex(tot.index, fill_value=0)
    out = pd.DataFrame(index=tot.index)
    for k, name in [("pass", "qb"), ("skill", "skill"), ("def", "def")]:
        if k not in tot:
            out[f"{name}_ret"] = np.nan
            continue
        denom = tot[k].replace(0, np.nan)
        out[f"{name}_ret"] = (back.get(k, 0) / denom).clip(0, 1)
        out[f"{name}_in"] = (inc.get(k, 0) / denom).clip(0, 1.5)
    out["season"] = season
    return out.reset_index().rename(columns={"team": "school"})


def table(first: int, current: int) -> pd.DataFrame:
    return pd.concat([returning(y) for y in range(first, current + 1)], ignore_index=True)
