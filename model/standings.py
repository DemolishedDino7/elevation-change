"""Conference standings for the six Western/G6 leagues on standings.html (bot/standings.json).

Built from the same games table The Bot uses (public archive + same-night NCAA.com finals),
so the page updates on every run with no hand editing.
"""
from __future__ import annotations

import pandas as pd

from index_feed import site_week

CONFS = [("Mountain West", "Mountain West"), ("Pac-12", "Pac-12"), ("MAC", "Mid-American"),
         ("American", "American Athletic"), ("Conference USA", "Conference USA"), ("Sun Belt", "Sun Belt")]

# how the site spells a few schools
DISPLAY = {"App State": "Appalachian State", "Massachusetts": "UMass", "Florida International": "FIU",
           "UL Monroe": "Louisiana-Monroe", "Miami": "Miami (FL)", "Connecticut": "UConn",
           "Southern Mississippi": "Southern Miss", "Hawaii": "Hawai'i", "San Jose State": "San José State"}


def disp(name: str) -> str:
    return DISPLAY.get(name, name)


def build(sg: pd.DataFrame, ti: pd.DataFrame) -> dict:
    """sg: this season's games; ti: this season's team_info (school, conference)."""
    g = sg.copy()
    g["sw"] = site_week(g.start, g.week)
    done = g[g.completed]
    cur = int(done[done.season_type == "regular"].sw.max()) if len(done) else 0
    conf_of = dict(zip(ti.school, ti.conference))

    out = {"week": cur, "conferences": {}}
    for label, conf in CONFS:
        rows = []
        for name in sorted(n for n, c in conf_of.items() if c == conf):
            mine = g[(g.home_team == name) | (g.away_team == name)].sort_values("start")
            fin = mine[mine.completed]
            w = l = cw = cl = 0
            for _, x in fin.iterrows():
                home = x.home_team == name
                pf, pa = (x.home_points, x.away_points) if home else (x.away_points, x.home_points)
                won = pf > pa
                w += won
                l += not won
                opp = x.away_team if home else x.home_team
                is_ccg = x.season_type != "regular" or "championship" in ("" if pd.isna(x.notes) else str(x.notes)).lower()
                if conf_of.get(opp) == conf and not is_ccg:
                    cw += won
                    cl += not won
            pend = mine[~mine.completed]
            if not len(pend):
                nxt = "Season complete"
            else:
                x = pend.iloc[0]
                if int(x.sw) > cur + 1:
                    nxt = "Bye"
                else:
                    home = x.home_team == name
                    opp = disp(x.away_team if home else x.home_team)
                    nxt = ("vs " if home or x.neutral_site else "@ ") + opp
            rows.append({"team": disp(name), "name": name, "rec": f"{w}-{l}", "conf": f"{cw}-{cl}", "next": nxt})
        out["conferences"][label] = rows
    return out
