"""Pull The Boys vs. The Bot picks straight from the weekly articles.

Each the-boys-vs-the-bot-week-N.html has, per game, a <div class="picks"> block with
a "pk boys" row and a "pk bot" row, each holding two "Team score" pairs. Any week that
has an article but no entry in bot/boys.json is filled in from the article, so the
contest tally keeps grading every Sunday even if nobody hand-edits boys.json.
Weeks already in boys.json are never touched (hand edits win).
"""
import html
import re
from pathlib import Path

PK = re.compile(
    r'class="pk (boys|bot)".*?<span class="sc">\s*<b>(.*?)</b>\s*<i>(.*?)</i>', re.S)
PAIR = re.compile(r'^\s*(.+?)\s+(\d+)\s*$')
# article spellings -> schedule names
ALIAS = {"Cal": "California", "Hawaii": "Hawai'i", "SJSU": "San José State", "San Jose State": "San José State"}


def _pair(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace(" ", " ")
    m = PAIR.match(s)
    if not m:
        return None
    name = re.sub(r"[\u2018\u2019\u02bb`]", "'", m.group(1).strip())
    return ALIAS.get(name, name), int(m.group(2))


def parse_article(path):
    """Return [(boys {team: pts}, bot {team: pts}), ...] in article order."""
    text = Path(path).read_text(encoding="utf-8")
    out = []
    for block in re.split(r'<div class="picks">', text)[1:]:
        block = block.split("</section>")[0]
        rows = {}
        for who, a, b in PK.findall(block):
            pa, pb = _pair(a), _pair(b)
            if pa and pb:
                rows[who] = {pa[0]: pa[1], pb[0]: pb[1]}
        if "boys" in rows:
            out.append((rows["boys"], rows.get("bot")))
    return out


def merge(boys, season, site_root, games, log=print):
    """Add missing weeks to `boys` from the articles. Returns the weeks added."""
    season_picks = boys.setdefault(str(season), {})
    by_week = {}
    for g in games:
        by_week.setdefault(g["week"], []).append(g)
    added = []
    for path in sorted(Path(site_root).glob("the-boys-vs-the-bot-week-*.html")):
        m = re.search(r"week-(\d+)\.html$", path.name)
        if not m or m.group(1) in season_picks:
            continue
        wk = int(m.group(1))
        picks, missed = [], []
        for boys_row, bot_row in parse_article(path):
            names = set(boys_row)
            g = next((g for g in by_week.get(wk, []) if {g["home"], g["away"]} == names), None)
            if not g:
                missed.append(" / ".join(sorted(names)))
                continue
            pk = {"home": g["home"], "away": g["away"],
                  "home_pts": boys_row[g["home"]], "away_pts": boys_row[g["away"]]}
            if bot_row and set(bot_row) == names:
                pk["bot_home"], pk["bot_away"] = bot_row[g["home"]], bot_row[g["away"]]
            picks.append(pk)
        if missed:
            log(f"boys article week {wk}: no schedule match for {missed}")
        if picks:
            season_picks[str(wk)] = picks
            added.append(wk)
            log(f"boys article week {wk}: added {len(picks)} picks from {path.name}")
    return added
