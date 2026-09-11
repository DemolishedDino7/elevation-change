/* ===================================================================
   ELEVATION CHANGE TICKER

   Live mode: pulls this week's games from ESPN's public scoreboard
   for the teams listed in WATCH, shows the line before kickoff and
   the live score once a game starts. Refreshes every 60 seconds
   while any game is in progress.

   Fallback: if ESPN can't be reached, the hand-entered list in
   FALLBACK is shown instead. Keep FALLBACK updated each week so
   the ticker never goes blank.
   =================================================================== */

/* Teams to include — ESPN abbreviations. Add or remove freely. */
const WATCH = [
  "AFA","HAW","NEV","UNM","NDSU","NIU","SJSU","UNLV","UTEP","WYO",   /* Mountain West */
  "BSU","CSU","FRES","ORST","SDSU","TXST","USU","WSU",                /* Pac-12 */
  "SAC"                                                               /* Sacramento State */
];

/* Hand-entered backup. ["Away @ Home", "Day time (MT)", "Line"] */
const FALLBACK = [
  ["Washington State @ Kansas State", "Sat 10:00 AM", "KSU −17.5"],
  ["Utah State @ Washington",         "Sat 1:30 PM",  "UW −26.5"],
  ["UTSA @ Texas State",              "Sat 1:30 PM",  "TXST −1.5"],
  ["Memphis @ Boise State",           "Sat 4:00 PM",  "BSU −7.5"],
  ["Southern Utah @ Colorado State",  "Sat 5:00 PM",  "CSU −20.5"],
  ["San Diego State @ UCLA",          "Sat 5:15 PM",  "UCLA −11.5"],
  ["Texas Tech @ Oregon State",       "Sat 5:30 PM",  "TTU −26.5"],
  ["Sacramento State @ Fresno State", "Sat 8:30 PM",  ""],
  ["North Dakota State @ Air Force",  "Sat",          "NDSU −3"],
  ["UNLV @ North Texas",              "Sat",          "UNLV −3.5"],
  ["Montana State @ Nevada",          "Sat",          ""],
  ["Illinois State @ Northern Illinois", "Sat",       ""],
  ["Cal Poly @ San José State",       "Sat",          ""],
  ["Texas Southern @ UTEP",           "Sat",          ""],
  ["Mercyhurst @ New Mexico",         "Sat",          ""],
  ["Northern Colorado @ Wyoming",     "Sat",          ""],
  ["New Mexico State @ Hawai'i",      "Sat late",     "HAW −9.5"]
];

/* ---- nothing below here needs editing ---- */

(function () {
  const ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300";
  const SEP = '<span class="tk-sep">·</span>';
  const watch = new Set(WATCH);

  const bar = document.createElement('div');
  bar.className = 'ticker';
  bar.setAttribute('role', 'region');
  bar.setAttribute('aria-label', 'This weekend in the Western Group of Six');
  bar.innerHTML = '<div class="tk-label">This weekend</div><div class="tk-track"><div class="tk-scroll"></div></div>';
  document.body.appendChild(bar);
  const scroll = bar.querySelector('.tk-scroll');
  const label = bar.querySelector('.tk-label');

  function esc(s) { return String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }

  function paint(items, live) {
    const html = items.join('');
    scroll.innerHTML = html + html;
    label.textContent = live ? 'Live' : 'This weekend';
    label.classList.toggle('tk-live', live);
  }

  function fallback() {
    paint(FALLBACK.map(g =>
      '<span class="tk-item"><b>' + esc(g[0]) + '</b>' +
      (g[1] ? SEP + esc(g[1]) : '') +
      (g[2] ? SEP + '<em>' + esc(g[2]) + '</em>' : '') + '</span>'), false);
  }

  function mtTime(iso) {
    const d = new Date(iso);
    const day = d.toLocaleDateString('en-US', { weekday: 'short', timeZone: 'America/Denver' });
    const t = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Denver' });
    return day + ' ' + t;
  }

  function render(data) {
    const items = [];
    let anyLive = false;
    (data.events || []).forEach(ev => {
      const c = ev.competitions && ev.competitions[0];
      if (!c) return;
      const home = c.competitors.find(x => x.homeAway === 'home');
      const away = c.competitors.find(x => x.homeAway === 'away');
      if (!home || !away) return;
      const ha = home.team.abbreviation, aa = away.team.abbreviation;
      if (!watch.has(ha) && !watch.has(aa)) return;

      const state = ev.status && ev.status.type && ev.status.type.state;   /* pre | in | post */
      const an = esc(away.team.location || away.team.shortDisplayName);
      const hn = esc(home.team.location || home.team.shortDisplayName);
      let s;

      if (state === 'in') {
        anyLive = true;
        const clock = esc(ev.status.displayClock || '');
        const q = ev.status.period ? 'Q' + ev.status.period : '';
        s = '<span class="tk-item tk-in"><i class="tk-dot"></i><b>' + an + ' ' + esc(away.score) +
            ' – ' + hn + ' ' + esc(home.score) + '</b>' + SEP + q + (clock ? ' ' + clock : '') + '</span>';
      } else if (state === 'post') {
        s = '<span class="tk-item"><b>' + an + ' ' + esc(away.score) + ' – ' + hn + ' ' + esc(home.score) +
            '</b>' + SEP + 'Final</span>';
      } else {
        const odds = c.odds && c.odds[0] && c.odds[0].details;
        s = '<span class="tk-item"><b>' + an + ' @ ' + hn + '</b>' + SEP + esc(mtTime(ev.date)) +
            (odds ? SEP + '<em>' + esc(odds) + '</em>' : '') + '</span>';
      }
      items.push(s);
    });
    if (!items.length) { fallback(); return false; }
    paint(items, anyLive);
    return anyLive;
  }

  function load() {
    fetch(ESPN, { cache: 'no-store' })
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(data => { if (render(data)) setTimeout(load, 60000); else setTimeout(load, 15 * 60000); })
      .catch(() => { fallback(); setTimeout(load, 5 * 60000); });
  }

  fallback();   /* show something immediately */
  load();
})();
