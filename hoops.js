/* ===================================================================
   ELEVATION CHANGE — BASKETBALL SHARED HELPERS
   Loads the Bot's files from hoops/ and draws the pieces the
   basketball pages share (game cards, logos, Mountain-time dates).
   =================================================================== */
const HB = (function () {
  const V = Math.floor(Date.now() / 300000);   /* refetch at most every 5 minutes */
  const TZ = 'America/Denver';
  const cache = {};
  const get = n => cache[n] || (cache[n] = fetch('hoops/' + n + '?v=' + V).then(r => { if (!r.ok) throw new Error(n); return r.json(); }));
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const LIGHT = { 'logos/USU.png': 'logos/USU-light.png', 'logos/UTEP.png': 'logos/UTEP-light.png' };  /* colored versions read better on the light circle */
  const img = (src, cls) => src
    ? '<img' + (cls ? ' class="' + cls + '"' : '') + ' src="' + esc(LIGHT[src] || src) + '" alt="" loading="lazy" onerror="this.style.visibility=\'hidden\'">'
    : '<img' + (cls ? ' class="' + cls + '"' : '') + ' alt="" style="visibility:hidden">';
  const short = n => String(n || '').replace('San José State', 'San José St.').replace('North Dakota State', 'North Dakota St.');
  const today = () => new Date().toLocaleDateString('en-CA', { timeZone: TZ });
  const time = (iso, tba) => tba || !iso ? 'Time TBA'
    : new Date(iso).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: TZ, timeZoneName: 'short' });
  const dayLong = d => new Date(d + 'T12:00:00Z').toLocaleDateString('en-US', { weekday: 'long', month: 'short', day: 'numeric', timeZone: 'UTC' });
  const dayShort = d => new Date(d + 'T12:00:00Z').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' }).replace(',', '');
  const addDays = (d, n) => { const x = new Date(d + 'T12:00:00Z'); x.setUTCDate(x.getUTCDate() + n); return x.toISOString().slice(0, 10); };
  const sgn = (v, d) => v == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d == null ? 1 : d);
  const LEAGUE = { pac: 'Pac-12', mw: 'Mountain West', oth: 'Other leagues' };

  /* one game card. T: team id -> team row (from teams.json) */
  function card(g, T, opts) {
    opts = opts || {};
    const th = T[g.home_id] || {}, ta = T[g.away_id] || {};
    const hwp = g.home_wp == null ? 0.5 : g.home_wp;
    const homeFav = hwp >= 0.5;
    const nm = (t, name) => {
      const rec = t.w != null && (t.w + t.l) > 0 ? t.w + '-' + t.l : '';
      const rk = t.rank ? 'No. ' + t.rank : '';
      return '<span class="nm">' + esc(short(name)) + '<small>' + [rec, rk ? 'Bot ' + rk : ''].filter(Boolean).join(' · ') + '</small></span>';
    };
    const row = (side) => {
      const home = side === 'home', t = home ? th : ta, name = home ? g.home : g.away;
      const wp = home ? hwp : 1 - hwp;
      let cls = 'row', sc, pc;
      if (g.final) {
        const mine = home ? g.home_pts : g.away_pts, theirs = home ? g.away_pts : g.home_pts;
        sc = mine; cls += mine < theirs ? ' lose' : '';
        pc = '';
      } else {
        sc = home ? g.pred_home : g.pred_away;
        cls += (home === homeFav) ? ' fav' : '';
        pc = Math.round(wp * 100) + '%';
      }
      return '<div class="' + cls + '">' + img(t.logo) + nm(t, name) + '<span class="sc">' + (sc == null ? '' : sc) + '</span><span class="pct">' + pc + '</span></div>';
    };
    const tag = g.note ? esc(g.note) : g.conf_game ? esc((th.conf || '') + (th.conf ? ' · ' : '') + 'League game') : g.neutral ? 'Neutral site' : 'Non-conference';
    const head = '<div class="top"><span class="lbl">' + esc(g.final ? 'Final' : time(g.start, g.tba)) + '</span><span class="lbl" style="color:var(--purple)">' + tag + '</span></div>';
    const fav = homeFav ? g.home : g.away;
    const favAb = (homeFav ? th.abbr : ta.abbr) || short(fav);
    const spread = g.pred_margin == null ? null : Math.abs(g.pred_margin);
    const chips = [];
    if (spread != null) chips.push('<span class="chip">Bot line <b>' + esc(favAb) + ' −' + spread.toFixed(1) + '</b></span>');
    if (g.pred_total != null) chips.push('<span class="chip">Total ' + Math.round(g.pred_total) + '</span>');
    if (g.pace != null) chips.push('<span class="chip">Pace ' + Math.round(g.pace) + '</span>');
    const f = g.factors || {};
    if (!g.neutral && f.altitude_ft >= 1500) chips.push('<span class="chip alt">Altitude +' + f.altitude_ft.toLocaleString('en-US') + ' ft</span>');
    if (Math.abs(f.travel_mi || 0) >= 1000) chips.push('<span class="chip">Travel ' + Math.abs(f.travel_mi).toLocaleString('en-US') + ' mi</span>');
    if (g.vegas_spread != null) chips.push('<span class="chip">Vegas ' + esc(g.vegas_spread === 0 ? 'pick’em' : (g.vegas_spread < 0 ? (th.abbr || g.home) : (ta.abbr || g.away)) + ' −' + Math.abs(g.vegas_spread)) + '</span>');
    let res = '';
    if (g.final && g.pred_home != null) {
      const right = (g.pred_home > g.pred_away) === (g.home_pts > g.away_pts);
      const miss = Math.abs(g.pred_home - g.home_pts) + Math.abs(g.pred_away - g.away_pts);
      res = '<div class="res"><span>Bot: <b>' + esc(short(g.away)) + ' ' + g.pred_away + ', ' + esc(short(g.home)) + ' ' + g.pred_home + '</b></span>' +
            '<span class="' + (right ? 'hit' : 'miss') + '">' + (right ? '✓ Winner' : '✗ Winner') + '</span></div>' +
            '<div class="res2">Off by ' + miss + ' combined points' + (g.mode === 'test' ? ' · test pick (not locked before tip)' : '') + '</div>';
    }
    const bar = g.final ? '' : '<div class="bar" aria-hidden="true"><i style="width:' + Math.round((1 - hwp) * 100) + '%"></i></div>';
    return '<article class="g">' + head + row('away') + row('home') + bar + (chips.length && !g.final ? '<div class="chips">' + chips.join('') + '</div>' : '') + res + '</article>';
  }

  /* Week of a date: Monday-Sunday */
  function monday(d) { const x = new Date(d + 'T12:00:00Z'); const w = (x.getUTCDay() + 6) % 7; return addDays(d, -w); }

  return { get, esc, img, short, today, time, dayLong, dayShort, addDays, sgn, LEAGUE, card, monday, TZ };
})();
