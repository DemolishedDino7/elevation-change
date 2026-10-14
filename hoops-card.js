/* ===================================================================
   ELEVATION CHANGE — HOME BASKETBALL CARD

   Shows our teams' next basketball game (or one in progress) with the
   Bot's pick. Schedule and picks come from hoops/games_west.json;
   live scores come from ESPN's public scoreboard on game days.
   Priority: a game in progress -> tonight's next tip -> the next
   game day -> the latest final.
   =================================================================== */
(function () {
  const card = document.getElementById('hoops-card');
  if (!card) return;
  const TZ = 'America/Denver';
  const V = Math.floor(Date.now() / 300000);
  const ESPN = 'https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=500&dates=';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const today = () => new Date().toLocaleDateString('en-CA', { timeZone: TZ });
  const day = d => new Date(d + 'T12:00:00Z').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }).replace(',', '');
  const time = (iso, tba) => tba ? 'Time TBA' : new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: TZ, timeZoneName: 'short' });

  function live(ids) {
    /* ESPN scoreboard for today: {gameId: {state, home, away, detail}} — best effort */
    const d = today().replace(/-/g, '');
    return fetch(ESPN + d, { cache: 'no-store' }).then(r => r.ok ? r.json() : {}).then(j => {
      const out = {};
      (j.events || []).forEach(ev => {
        if (!ids.has(Number(ev.id))) return;
        const c = ev.competitions && ev.competitions[0]; if (!c) return;
        const h = c.competitors.find(x => x.homeAway === 'home'), a = c.competitors.find(x => x.homeAway === 'away');
        out[ev.id] = { state: ev.status.type.state, home: h && h.score, away: a && a.score, detail: ev.status.type.shortDetail };
      });
      return out;
    }).catch(() => ({}));
  }

  function render(games, T, L) {
    const t = today();
    const ids = new Set(games.map(g => g.id));
    const isLive = g => L[g.id] && L[g.id].state === 'in';
    const todays = games.filter(g => g.day === t);
    let g = todays.find(isLive), head;
    const nToday = todays.length;
    if (g) head = '<i class="tk-dot"></i>Basketball · Live now';
    if (!g) { g = todays.find(x => !x.final && !(L[x.id] && L[x.id].state === 'post')); if (g) head = 'Basketball · Tonight'; }
    if (!g) {
      const up = games.filter(x => x.day > t && !x.final);
      if (up.length) {
        const first = !games.some(x => x.final);
        g = up[0]; head = 'Basketball · ' + (first ? 'Tip-off' : 'Next tip');
      }
    }
    if (!g) { const done = games.filter(x => x.final); g = done[done.length - 1]; head = 'Basketball · Final'; }
    if (!g) { card.hidden = true; return false; }
    const sameDay = games.filter(x => x.day === g.day).length;
    const th = T[g.home_id] || {}, ta = T[g.away_id] || {};
    const lv = L[g.id];
    let score = '';
    if ((lv && lv.state !== 'pre') || g.final) {
      const hs = g.final ? g.home_pts : Number(lv.home), as = g.final ? g.away_pts : Number(lv.away);
      const post = g.final || lv.state === 'post';
      const row = (name, pts, lose) => '<span class="ls-row' + (lose ? ' ls-lose' : '') + '"><span>' + esc(name) + '</span><b>' + pts + '</b></span>';
      score = '<p class="live-score">' + row(g.away, as, post && as < hs) + row(g.home, hs, post && hs < as) +
              '<span class="ls-status">' + esc(post ? 'Final' : (lv.detail || 'Live')) + '</span></p>';
    }
    const fav = g.home_wp >= 0.5 ? th : ta, favName = g.home_wp >= 0.5 ? g.home : g.away;
    const wp = Math.round(Math.max(g.home_wp, 1 - g.home_wp) * 100);
    const meta = [];
    meta.push('<span>' + esc(day(g.day)) + ' | <b>' + esc(time(g.start, g.tba)) + '</b></span>');
    if (g.venue) meta.push('<span>' + esc(g.venue) + (g.city ? ', ' + esc(g.city) : '') + '</span>');
    const elev = g.factors && g.factors.site_elev;
    if (!g.neutral && elev >= 3000) meta.push('<span>Elevation <b>' + Number(elev).toLocaleString('en-US') + ' ft</b></span>');
    if (g.pred_home != null) meta.push('<span>Bot <b>' + esc(fav.abbr || favName) + ' ' + Math.max(g.pred_home, g.pred_away) + '–' + Math.min(g.pred_home, g.pred_away) + '</b> · ' + wp + '%</span>');
    card.innerHTML = '<h2><span class="sport">' + head + '</span>' + (sameDay > 1 ? ' · ' + sameDay + ' games' : '') + '</h2>' +
      '<p class="matchup">' + esc(g.away) + '<br>' + (g.neutral ? 'vs. ' : 'at ') + esc(g.home) + '</p>' + score +
      '<div class="meta-row">' + meta.join('') + '</div>' +
      '<p style="margin:0;font-size:0.8125rem"><a href="basketball.html" style="text-decoration:none">All of our games &rarr;</a></p>';
    card.classList.toggle('is-live', !!(lv && lv.state === 'in'));
    card.hidden = false;
    return !!(lv && lv.state === 'in');
  }

  function load() {
    Promise.all([
      fetch('hoops/games_west.json?v=' + V).then(r => r.json()),
      fetch('hoops/teams.json?v=' + V).then(r => r.json())
    ]).then(([games, teams]) => {
      const T = {}; teams.forEach(t => T[t.id] = t);
      games.sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : (a.tba - b.tba) || String(a.start).localeCompare(String(b.start))));
      const t = today();
      const need = games.some(g => g.day === t);
      return (need ? live(new Set(games.map(g => g.id))) : Promise.resolve({})).then(L => {
        const isLive = render(games, T, L);
        setTimeout(load, isLive ? 60000 : 10 * 60000);
      });
    }).catch(() => { card.hidden = true; });
  }
  load();
})();
