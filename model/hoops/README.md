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
| `prior.py` | Preseason start: last season's ratings + returning minutes + transfers + conference |
| `walk.py` | Walk-forward predictions (each day predicted from games before it) |
| `game_model.py` | Margin, total and win chance from ratings + home court, altitude, travel, rest |
| `run.py` | Daily pipeline: picks, pick locking, scorecard, Boys vs. Bot, standings |

## Weekly chores
* **The Boys vs. The Bot:** add the analysts' picks to `hoops/boys.json` before tip,
  under the season (`"2027"` = 2026-27) and week number (Week 1 = Mon Nov 2 - Sun Nov 8):
  ```json
  "2027": { "1": [ {"home": "San Diego State", "away": "Gonzaga", "home_pts": 72, "away_pts": 75} ] }
  ```
  Team names must match the schedule ("Hawai'i", "San José State"). Leave out
  `bot_home`/`bot_away` and the contest uses the Bot's locked pick.
* Our 23 teams are listed in `WEST` at the top of `run.py`.

## Not yet
* **Season odds** (conference titles, NCAA bids) switch on once both league
  schedules are in the data. Pac-12 league games weren't posted as of mid-October.
* **Résumé Elevation Index** like football's, once teams have a few games in.

## Backtest (D-I vs D-I, 2021-22 to 2025-26, walk-forward)
Fit on seasons through 2020-21. 28,479 games: winners 72.0%, average margin miss
9.08 points, well calibrated. No historical betting lines in the data, so live
picks are graded against Vegas as ESPN's pregame lines come in.
