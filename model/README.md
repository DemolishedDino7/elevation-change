# The Bot

Elevation Change's independent prediction model. It never reads betting lines,
FPI or anyone's rankings to make a pick; lines are used only to grade it.

```
pip install -r model/requirements.txt
python model/run.py          # downloads data, refits everything, writes bot/*.json
```

The GitHub Action in `.github/workflows/the-bot.yml` runs this Sun/Mon/Wed/Fri
and commits the results; `the-bot.html` reads them.

| File | What it does |
|---|---|
| `data.py` | Games, venues, altitude, travel, rest, historical closing lines |
| `plays.py` | Play-level efficiency (success rate, YPP, explosiveness, tempo), garbage time removed |
| `returning.py` | Returning production + transfer-portal production from rosters |
| `ratings.py` | Opponent-adjusted offense/defense ratings with preseason priors |
| `game_model.py` | Margin, total, win probability from ratings + situation |
| `simulate.py` | 10,000-season Monte Carlo: bowls, conference titles, CFP auto-bid |
| `run.py` | Weekly pipeline + backtest scorecard + pick locking + contest grading |

## Weekly chores
* **The Boys vs. The Bot:** add the analysts' picks to `bot/boys.json` before kickoff.
* `LAUNCH` in `run.py` marks the first live week each season (earlier weeks are graded as walk-forward tests).

## Optional
Add a free CollegeFootballData.com key as the repo secret `CFBD_API_KEY` and the
scorecard will also grade live picks against the Vegas spread.

## Backtest (FBS vs FBS, 2022–2025, walk-forward)
Average miss 12.3 pts vs Vegas closing line 12.0 · winners 72.0% vs 72.6% · well calibrated.
