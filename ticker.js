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
  "SAC",                                                              /* Sacramento State */
  "NMSU"                                                               /* New Mexico State */
];

/* Hand-entered backup. ["Away @ Home", "Day time (MT)", "Line", live?]
   Put true as a 4th value to mark a game in progress (red dot + LIVE label). */
const FALLBACK = [
  ["Navy @ Air Force",                  "Sat 10:00 AM", "AFA −2.5"],
  ["California @ UNLV",                 "Sat 1:30 PM",  "UNLV −2.5"],
  ["Wyoming @ North Dakota State",      "Sat 1:30 PM",  "NDSU −20.5"],
  ["UTEP @ New Mexico",                 "Sat 2:00 PM",  "UNM −22.5"],
  ["Oregon State @ Colorado State",     "Sat 4:00 PM",  "ORST −4.5"],
  ["Utah State @ Boise State",          "Sat 5:30 PM",  "BSU −21"],
  ["Fresno State @ Washington State",   "Sat 7:30 PM",  "FRES −1.5"],
  ["Texas State @ San Diego State",     "Sat 8:30 PM",  "TXST −4"],
  ["San José State @ Hawai'i",          "Sat TBA",      ""]
];

/* ---- nothing below here needs editing ---- */

/* Basketball: our 23 teams by ESPN team id (the 20 football schools + Gonzaga, Grand Canyon, UC Davis) */
const WATCH_HOOPS = [68, 36, 278, 2250, 204, 21, 326, 328, 265, 2005, 2253, 62, 2440, 167, 23, 302, 2439, 2638, 2751, 2449, 2459, 166, 16];

(function () {
  /* Which games this page's ticker shows. Basketball pages (Basketball tab
     selected in the main nav) get basketball only, football pages get
     football only, and the home page gets both. A page can force it with
     <script src="ticker.js" data-sport="football|basketball|all">. */
  const SPORT = (function () {
    const me = document.currentScript;
    if (me && me.dataset.sport) return me.dataset.sport;
    const cur = document.querySelector('.nav a[aria-current="page"]');
    const href = cur ? cur.getAttribute('href') : '';
    return href === 'basketball.html' ? 'basketball' : href === 'football.html' ? 'football' : 'all';
  })();
  const ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300";
  const ESPN_HOOPS = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=500&dates=";
  const watchHoops = new Set(WATCH_HOOPS.map(String));
  const SEP = '<span class="tk-sep"></span>';
  const watch = new Set(WATCH);

  const bar = document.createElement('div');
  bar.className = 'ticker';
  bar.setAttribute('role', 'region');
  bar.setAttribute('aria-label', SPORT === 'basketball' ? 'Basketball games for our teams' : SPORT === 'football' ? 'Football games this weekend' : 'This weekend in the Western Group of Six');
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
    if (SPORT === 'basketball') { hoopsSchedule(); return; }
    paint(FALLBACK.map(g =>
      '<span class="tk-item' + (g[3] ? ' tk-in' : '') + '">' + (g[3] ? '<i class="tk-dot"></i>' : '') + '<b>' + esc(g[0]) + '</b>' +
      (g[1] ? SEP + '<em>' + esc(g[1]) + '</em>' : '') +
      (g[2] ? SEP + '<em>' + esc(g[2]) + '</em>' : '') + '</span>'), FALLBACK.some(g => g[3]));
  }

  function mtTime(iso) {
    const d = new Date(iso);
    const day = d.toLocaleDateString('en-US', { weekday: 'short', timeZone: 'America/Denver' });
    const t = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/Denver' });
    return day + ' ' + t;
  }

  function hoopsItems(data) {
    /* today's basketball games for our teams; "BB" marks them when football is on the ticker too */
    const items = [];
    let anyLive = false;
    (data && data.events || []).forEach(ev => {
      const c = ev.competitions && ev.competitions[0];
      if (!c) return;
      const home = c.competitors.find(x => x.homeAway === 'home');
      const away = c.competitors.find(x => x.homeAway === 'away');
      if (!home || !away || (!watchHoops.has(String(home.team.id)) && !watchHoops.has(String(away.team.id)))) return;
      const state = ev.status && ev.status.type && ev.status.type.state;
      const an = esc(away.team.location || away.team.shortDisplayName), hn = esc(home.team.location || home.team.shortDisplayName);
      const tag = SPORT === 'all' ? '<em>BB</em>' + SEP : '';
      if (state === 'in') {
        anyLive = true;
        items.push('<span class="tk-item tk-in"><i class="tk-dot"></i>' + tag + '<b>' + an + ' ' + esc(away.score) + ' – ' + hn + ' ' + esc(home.score) + '</b>' + SEP + '<em>' + esc(ev.status.type.shortDetail || '') + '</em></span>');
      } else if (state === 'post') {
        items.push('<span class="tk-item">' + tag + '<b>' + an + ' ' + esc(away.score) + ' – ' + hn + ' ' + esc(home.score) + '</b>' + SEP + '<em>Final</em></span>');
      } else {
        const odds = c.odds && c.odds[0] && c.odds[0].details;
        items.push('<span class="tk-item">' + tag + '<b>' + an + ' @ ' + hn + '</b>' + SEP + '<em>' + esc(c.timeValid === false ? 'Today' : mtTime(ev.date)) + '</em>' + (odds ? SEP + '<em>' + esc(odds) + '</em>' : '') + '</span>');
      }
    });
    return { items, anyLive };
  }

  /* Basketball pages with no games today: show the next day our teams play,
     with the Bot's pick, from the hoops Bot's schedule. */
  let schedShown = false;
  function hoopsSchedule() {
    fetch('hoops/games_west.json?v=' + Math.floor(Date.now() / 300000)).then(r => r.json()).then(games => {
      const today = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Denver' });
      const next = games.filter(g => !g.final && g.day >= today).map(g => g.day).sort()[0];
      if (!next) return;
      const day = new Date(next + 'T12:00:00Z').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' });
      const list = games.filter(g => g.day === next).sort((a, b) => (a.tba - b.tba) || String(a.start).localeCompare(String(b.start)));
      paint(list.map(g => {
        const fav = g.home_wp >= 0.5 ? g.home : g.away;
        return '<span class="tk-item"><b>' + esc(g.away) + ' @ ' + esc(g.home) + '</b>' + SEP + '<em>' + esc(g.tba ? day : mtTime(g.start)) + '</em>' +
          (g.pred_margin != null ? SEP + '<em>Bot: ' + esc(fav) + ' −' + Math.abs(g.pred_margin).toFixed(1) + '</em>' : '') + '</span>';
      }), false);
      label.textContent = next === today ? 'Today' : 'Next up · ' + day;
      schedShown = true;
    }).catch(() => {});
  }

  function render(data, hoops) {
    if (SPORT === 'basketball') data = null;
    if (SPORT === 'football') hoops = null;
    const items = [];
    let anyLive = false;
    (data && data.events || []).forEach(ev => {
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
            ' – ' + hn + ' ' + esc(home.score) + '</b>' + SEP + '<em>' + q + (clock ? ' ' + clock : '') + '</em></span>';
      } else if (state === 'post') {
        s = '<span class="tk-item"><b>' + an + ' ' + esc(away.score) + ' – ' + hn + ' ' + esc(home.score) +
            '</b>' + SEP + '<em>Final</em></span>';
      } else {
        const odds = c.odds && c.odds[0] && c.odds[0].details;
        s = '<span class="tk-item"><b>' + an + ' @ ' + hn + '</b>' + SEP + '<em>' + esc(mtTime(ev.date)) + '</em>' +
            (odds ? SEP + '<em>' + esc(odds) + '</em>' : '') + '</span>';
      }
      items.push(s);
    });
    const h = hoopsItems(hoops);
    /* football is only "this weekend" news Thursday-Saturday; hoops games are today's */
    const all = items.concat(h.items);
    if (!all.length) { if (SPORT === 'basketball') { if (!schedShown) hoopsSchedule(); } else if (data) { fallback(); } return false; }
    paint(all, anyLive || h.anyLive);
    if (h.items.length) { label.textContent = (anyLive || h.anyLive) ? 'Live' : (items.length ? 'This week' : 'Today'); }
    return anyLive || h.anyLive;
  }

  function get(url) {
    return fetch(url, { cache: 'no-store' }).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
  }

  function load() {
    const day = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Denver' }).replace(/-/g, '');
    const none = Promise.reject(new Error('not shown on this page'));
    none.catch(() => {});
    Promise.allSettled([SPORT === 'basketball' ? none : get(ESPN), SPORT === 'football' ? none : get(ESPN_HOOPS + day)]).then(([fb, bb]) => {
      if (fb.status === 'rejected' && bb.status === 'rejected') { fallback(); setTimeout(load, 5 * 60000); return; }
      const live = render(fb.status === 'fulfilled' ? fb.value : null, bb.status === 'fulfilled' ? bb.value : null);
      setTimeout(load, live ? 60000 : 15 * 60000);
    });
  }

  fallback();   /* show something immediately */
  load();
})();
