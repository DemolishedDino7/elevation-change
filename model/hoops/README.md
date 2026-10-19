# The Bot (men's basketball)

Elevation Change's independent basketball model. It never reads betting lines,
KenPom, the NET or anyone's rankings to make a pick; lines are used only to grade it.

```
pip install -r model/requirements.txt
python model/hoops/run.py            # downloads data, refits, backtests, writes hoops/*.json
python model/hoops/run.py --quick    # game-night refresh: reuses the morning's fitted model
```

The GitHub Action in `.github/workflows/hoops-bot.yml` runs a full refresh every
morning (6:10am MT, October-April) and quick refreshes at 4:40pm, 8:40pm,
10:40pm, 12:40am and 2:40am MT on game nights, then commits `hoops/`.
The basketball pages (`basketball.html`, `hoops-bot.html`, `hoops-index.html`,
`hoops-standings.html`) read those files.

| File | What it does |
|---|---|
| `data.py` | Schedules, box scores, rosters, player minutes from the public hoopR mirror (ESPN data); possessions, travel, altitude, rest |
| `geo.json` | Every team's home arena location and elevation |
| `espn.py` | ESPN scoreboard: same-night finals, schedule changes, pregame lines (grading only) |
| `ratings.py` | Opponent-adjusted offense/defense per 100 possessions and tempo, pulled toward preseason priors |
| `prior.py` | Preseason start: last season's ratings + returning minutes and production + transfers (old team's strength and each player's own production) + ranked recruits + conference |
| `recruits.py` / `recruits.csv` | High school recruits (On3 Industry ranking, classes 2011 on) matched to ESPN teams; `fetch_recruits.py` refreshes the CSV weekly via `.github/workflows/fetch-recruits.yml` |
| `exhibitions.py` / `fetch_exhibitions.py` / `exhibitions.csv` / `school_sites.json` | Preseason exhibitions for every D-I team, read from each school's official schedule page (362 of 366 schools; `school_sites.json`) in the morning run until a week after the opener (ESPN doesn't carry them). Each D-I exhibition counts as a full game in the starting ratings, fading to zero a quarter of the way through the regular season. A D-I vs D-I game is on both schools' pages, so a school we can't read is still covered by its opponent's; when the two pages disagree on the site the game counts as neutral. D-I opponents only, half a game each, in the starting ratings; never in the résumé. Rows marked `source=manual` in the CSV are kept as entered, to fix a misread |
| `resume_index.py` | The Elevation Index: preseason start until 90% of D-I teams have 2 D-I games, then half résumé (Wins Above Bubble) and half stats (this season's adjusted efficiency, no prior), plus "our field" |
| `walk.py` | Walk-forward predictions (each day predicted from games before it) |
| `game_model.py` | Margin, total and win chance from ratings + home court, altitude, travel, rest |
| `bracket.py` | March Madness: Selection Sunday résumés 2013-2026, selection + seed models, season simulation, 76-team bracket, tournament picks |
| `ncaa_fields.json` | Every NCAA Tournament field and seed since 2013 (from ESPN game files) |
| `run.py` | Daily pipeline: picks, pick locking, scorecard, Boys vs. Bot, standings; bracket every Monday |

## Weekly chores
* **The Boys vs. The Bot:** add the analysts' picks to `hoops/boys.json` before tip,
  under the season (`"2027"` = 2026-27) and week number (Week 1 = Mon Nov 2 - Sun Nov 8):
  ```json
  "2027": { "1": [ {"home": "San Diego State", "away": "Gonzaga", "home_pts": 72, "away_pts": 75} ] }
  ```
  Team names must match the schedule ("Hawai'i", "San José State"). Leave out
  `bot_home`/`bot_away` and the contest uses the Bot's locked pick.
* Our 23 teams are listed in `WEST` at the top of `run.py`.

## March Madness projection
Rebuilt in the Monday morning run (or `python model/hoops/run.py --bracket` any time) and written to
`hoops/bracket.json`; `hoops-bracket.html` shows it. Each week's seeds are kept in
`hoops/bracket_history.json` for the movement column. Tested leave-one-season-out on 13
tournaments: 94% of at-large teams picked, 86% of seeds within one line. Format: 76 teams from
2027 (32 automatic, 44 at-large, 12 Opening Round games). After each tournament, add that year's
field to `ncaa_fields.json` so the model keeps learning.

## Not yet
* **Season odds tab** (conference titles) switches on once both league schedules are
  in the data. NCAA bid odds already live on the bracket page.

## Backtest (D-I vs D-I, 2021-22 to 2025-26, walk-forward)
Fit on seasons through 2020-21. 28,479 games: winners 72.0%, average margin miss
9.08 points, well calibrated. No historical betting lines in the data, so live
picks are graded against Vegas as ESPN's pregame lines come in.

## Elevation Index (résumé + stats)
Checked on every Selection Sunday 2014-2026: the résumé half picked 87% of the committee's at-large teams
(about 92% in the last four seasons), and the stats half tracked NCAA Tournament wins better than résumé
(rank correlation 0.56 vs 0.53). Preseason prior with recruits/transfers, leave-one-season-out 2014-2026:
miss 4.24 -> 4.01 points per 100 possessions (high-major 4.32 -> 3.97).
