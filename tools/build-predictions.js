/* ===================================================================
   BUILD A PREDICTION SLATE PAGE
   node tools/build-predictions.js
   Runs the prediction model in ei-engine.js over SLATE in ei-data.js
   and writes week-<N>-predictions.html. The page is frozen on
   purpose: picks are made before kickoff and never revised.
   =================================================================== */
const fs = require('fs'), path = require('path');
const root = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(root, 'ei-data.js'), 'utf8') + '\n' +
            fs.readFileSync(path.join(root, 'ei-engine.js'), 'utf8') +
            '\n;module.exports = { EI, SLATE, TEAMS, OPPONENTS };';
const m = { exports: {} };
new Function('module', src)(m);
const { EI, SLATE, TEAMS } = m.exports;

const DATE = process.argv[2] || 'Sep 28, 2026';
const picks = EI.predictSlate(SLATE);
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/'/g, '&rsquo;');
const pts = x => (x >= 0 ? '+' : '−') + Math.abs(x).toFixed(1);
const pct = x => Math.round(x * 100) + '%';
const slug = s => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

/* market line "NMSU −1.5" → spread from the home side's view (+ = home favored) */
function marketSpread(g, p) {
  const mt = (g.line || '').match(/^(\S+)\s*[−-]\s*([\d.]+)/);
  if (!mt) return null;
  const n = parseFloat(mt[2]);
  const isHome = mt[1] === g.home || mt[1] === p.home.name;
  return isHome ? n : -n;
}

function logo(side) {
  return side.tracked ? '<img class="team-logo" alt="" data-logo="' + side.key + '">' : '';
}

function note(p, g, ms) {
  const fav = p.spread >= 0 ? p.home : p.away, dog = p.spread >= 0 ? p.away : p.home;
  let s = 'Power ratings: ' + esc(p.home.name) + ' ' + pts(p.home.rating) + ', ' + esc(p.away.name) + ' ' + pts(p.away.rating) +
          ' (points better or worse than an average FBS team), plus 2.5 for home field.';
  if (ms != null) {
    const diff = p.spread - ms;                   /* + = model likes home more than the market */
    const mktFavHome = ms >= 0, modelFavHome = p.spread >= 0;
    if (ms !== 0 && mktFavHome !== modelFavHome)
      s += ' <b>Upset pick:</b> the market has ' + esc(mktFavHome ? p.home.name : p.away.name) + ' favored; the model takes ' + esc(fav.name) + ' straight up.';
    else if (Math.abs(diff) >= 3)
      s += ' The model is ' + Math.abs(diff).toFixed(1) + ' points ' + (Math.abs(p.spread) > Math.abs(ms) ? 'higher' : 'lower') + ' on ' + esc(fav.name) + ' than the market.';
    else
      s += ' Within ' + Math.max(0.5, Math.abs(diff)).toFixed(1) + ' of the market — no argument here.';
  }
  return s;
}

const board = picks.map(p => {
  const w = p.score.home > p.score.away ? p.home : p.away, l = w === p.home ? p.away : p.home;
  const ws = Math.max(p.score.home, p.score.away), ls = Math.min(p.score.home, p.score.away);
  return '<li><a href="#' + slug(p.away.name + '-' + p.home.name) + '">' + esc(w.name) + ' ' + ws + ', ' + esc(l.name) + ' ' + ls + '</a><span class="conf">' + p.confidence + '</span></li>';
}).join('\n            ');

const upsets = picks.filter(p => { const ms = marketSpread(p.meta, p); return ms && (ms >= 0) !== (p.spread >= 0); });

const games = picks.map(p => {
  const g = p.meta, ms = marketSpread(g, p);
  const hw = p.score.home > p.score.away;
  const bar = '<div class="pbar" role="img" aria-label="Win probability: ' + esc(p.away.name) + ' ' + pct(p.pAway) + ', ' + esc(p.home.name) + ' ' + pct(p.pHome) + '">' +
    '<span class="' + (hw ? 'dog' : 'fav') + '" style="width:' + (p.pAway * 100).toFixed(1) + '%"></span>' +
    '<span class="' + (hw ? 'fav' : 'dog') + '" style="width:' + (p.pHome * 100).toFixed(1) + '%"></span></div>' +
    '<div class="plabels"><span>' + esc(p.away.name) + ' ' + pct(p.pAway) + '</span><span>' + esc(p.home.name) + ' ' + pct(p.pHome) + '</span></div>';
  return `
        <section class="pick" id="${slug(p.away.name + '-' + p.home.name)}">
          <p class="pick-meta"><span>${esc(g.day)}</span><span>${p.site === 'N' ? 'Neutral site' : 'at ' + esc(p.home.name)}</span><span class="conf">${p.confidence}</span></p>
          <h2>${logo(p.away)}${esc(p.away.name)} <span class="at">at</span> ${logo(p.home)}${esc(p.home.name)}</h2>
          <dl class="score">
            <dt class="${hw ? 'loser' : ''}">${esc(p.away.name)}</dt><dd class="${hw ? 'loser' : ''}">${p.score.away}</dd>
            <dt class="${hw ? '' : 'loser'}">${esc(p.home.name)}</dt><dd class="${hw ? '' : 'loser'}">${p.score.home}</dd>
          </dl>
          ${bar}
          <p class="lines"><span>Model <b>${esc(p.line)}</b></span><span>Market <b>${g.line ? esc(g.line.replace(/^(\S+)/, t => (TEAMS.find(x => x[0] === t) || [0, t])[1])) : 'Off the board'}</b></span><span>Total <b>${p.total}</b></span></p>
          <p class="why">${note(p, g, ms)}</p>
        </section>`;
}).join('\n');

const locks = picks.filter(p => p.confidence === 'Lock').length, flips = picks.filter(p => p.confidence === 'Coin flip').length;
const title = 'Week ' + SLATE.week + ' Predictions';
const dek = 'Every Western Group of Six game this week, run through the Elevation Change model: a score, a win probability and a line for all ' + picks.length + '.';

const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title} — Elevation Change</title>
<meta name="description" content="${esc(dek)}">
<meta name="theme-color" content="#08080E">
<meta property="og:site_name" content="Elevation Change">
<meta property="og:type" content="article">
<meta property="og:title" content="${title}: the model picks every game">
<meta property="og:description" content="${esc(dek)}">
<meta property="og:url" content="https://elevationchange.co/week-${SLATE.week}-predictions.html">
<meta name="twitter:card" content="summary">
<link rel="icon" href="https://elevationchange.co/logo.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:ital,wdth,wght@0,100,400;0,100,500;0,100,600;0,100,700;0,100,800;0,104,800;0,108,700;0,112,900;1,100,700;1,104,700;1,104,800;1,108,700;1,112,900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="styles.css">
<style>
.pick { border-top: 1px solid var(--line); padding: 2rem 0 0.5rem; margin: 0 0 1.5rem; scroll-margin-top: 1.5rem; }
.pick-meta, .lines { display: flex; flex-wrap: wrap; gap: 0.5rem 0; font-size: 0.8125rem; color: var(--purple); letter-spacing: 0.04em; margin: 0 0 0.75rem; }
.pick-meta span, .lines span { padding-right: 1rem; margin-right: 1rem; border-right: 1px solid var(--rule); }
.pick-meta span:last-child, .lines span:last-child { border-right: 0; margin-right: 0; padding-right: 0; }
.lines { color: var(--muted); margin: 1rem 0 0.75rem; }
.lines b { color: var(--paper); font-weight: 700; }
.pick h2 { margin: 0 0 1.25rem !important; font-size: clamp(1.4rem, 4.5vw, 1.9rem) !important; }
.pick h2 .at { color: var(--muted); font-size: 0.7em; }
.pick .team-logo { width: 1.3em; height: 1.3em; object-fit: contain; vertical-align: -0.3em; margin-right: 0.4rem; }
.conf { color: var(--paper); font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.75rem; }
.score { margin: 0 0 1.25rem; display: grid; grid-template-columns: 1fr auto; gap: 0.3rem 1.5rem; }
.score dt, .score dd { font-family: var(--display); font-style: italic; font-weight: 900; font-stretch: 112%; text-transform: uppercase; font-size: clamp(1.3rem, 5vw, 1.9rem); line-height: 1.05; margin: 0; }
.score dd { text-align: right; color: var(--purple); }
.score .loser { color: var(--muted); }
.pbar { display: flex; height: 10px; gap: 3px; }
.pbar span { display: block; height: 100%; }
.pbar .fav { background: var(--purple); }
.pbar .dog { background: var(--rule); }
.plabels { display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--muted); margin-top: 0.4rem; }
.why { font-size: 0.9375rem; color: var(--muted); }
.why b { color: var(--paper); }
.jump li a { flex: 1; }
.jump li .conf { flex: none; }
.jump .conf { font-size: 0.6875rem; color: var(--muted); }
</style>
</head>
<body>

<header class="masthead">
  <div class="wrap">
    <a class="brand" href="index.html">
      <svg class="mark" viewBox="0 0 100 100" role="img" aria-label="Elevation Change"><circle cx="50" cy="50" r="45" fill="none" stroke="#8B6BB8" stroke-width="4"/><path d="M16 64 L32 40 L41 50 L54 26 L66 48 L74 40 L86 64 Z" fill="#F2F1EE"/><path d="M47 66 Q60 74 45 80 Q33 85 52 90" fill="none" stroke="#8B6BB8" stroke-width="5" stroke-linecap="round"/></svg>
      <span>Elevation Change</span>
    </a>
    <nav class="nav" aria-label="Main">
      <a href="index.html">Home</a>
      <a href="elevation-index.html">Index</a>
      <a href="standings.html">Standings</a>
      <a href="index.html#about">About</a>
    </nav>
  </div>
</header>

<main>
  <article class="article">
    <div class="wrap">
      <div class="article-head">
        <p class="eyebrow">Predictions | Week ${SLATE.week}</p>
        <h1>The model picks every game in the West</h1>
        <p class="dek">${esc(dek)}</p>
        <p class="byline">By Preston Thompson | ${DATE} | Model through Week ${SLATE.throughWeek}</p>
      </div>

      <div class="article-body">

        <p>The Elevation Index tells you who has earned what. This is the other half: who wins next. The model reads the same games the Index does, adjusts every margin for the opponent and the venue, and turns that into a power rating for all 20 teams. ${locks} of this week&rsquo;s ${picks.length} games grade out as locks, ${flips} are coin flips${upsets.length ? ', and the model is picking ' + upsets.length + ' market underdog' + (upsets.length > 1 ? 's' : '') + ' to win outright: ' + upsets.map(p => esc(p.winner)).join(' and ') : ''}.</p>

        <nav class="jump" aria-label="The board">
          <h2>The board</h2>
          <ol>
            ${board}
          </ol>
        </nav>
${games}

        <div class="aside-note">
          <p><b>How the model works.</b> Every game becomes a rating: the margin, adjusted for how good the opponent is right now and whether it was home or away. Margins past 21 count at 40%, 30% of the margin comes from yardage when we have the box score, and half of the turnover swing is treated as luck. Recent games count more, and each team&rsquo;s preseason estimate still carries a game and a half of weight so one result can&rsquo;t swing everything.</p>
          <p>The spread is the gap between two ratings plus 2.5 points for home field. Win probability assumes about 13.5 points of game-to-game noise. The market line is shown for comparison only &mdash; the model never sees it. None of this is betting advice.</p>
        </div>

      </div>
    </div>
  </article>
</main>

<footer class="foot">
  <div class="wrap" style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:1rem;width:min(68rem,100% - 2.5rem);">
    <span>Elevation Change | 2026</span>
    <span><a href="index.html">Home</a></span>
  </div>
</footer>

<script data-goatcounter="https://elevationchange.goatcounter.com/count"
        async src="//gc.zgo.at/count.js"></script>
<script src="ei-data.js"></script>
<script>
(function () {
  document.querySelectorAll('img[data-logo]').forEach(img => {
    const t = TEAMS.find(x => x[0] === img.dataset.logo); if (!t) { img.remove(); return; }
    const cands = (t[5] || '').split('|').map(s => s.trim()).filter(Boolean);
    (function tryNext(i) {
      if (i >= cands.length) { img.remove(); return; }
      const probe = new Image();
      probe.onload = () => { img.src = cands[i]; };
      probe.onerror = () => tryNext(i + 1);
      probe.src = cands[i];
    })(0);
  });
})();
</script>
<script src="ticker.js"></script>
</body>
</html>
`;
const out = path.join(root, 'week-' + SLATE.week + '-predictions.html');
fs.writeFileSync(out, html);
console.log('wrote ' + path.basename(out));
picks.forEach(p => console.log(p.away.name + ' ' + p.score.away + ' @ ' + p.home.name + ' ' + p.score.home + ' | ' + p.line + ' | ' + p.confidence));
