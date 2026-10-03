/* ===================================================================
   ELEVATION CHANGE — HOME GAME CARD

   Fully automatic. Pulls this week's games from ESPN for the teams
   in WATCH (ticker.js) and shows, in order of priority:
     1. a game in progress  -> "Live now" with the score
     2. the next kickoff    -> time, TV, stadium, spread
     3. the latest final    -> once nothing is left to play this week
   Refreshes every minute while a game is live, every 5 minutes otherwise.

   Optional hand-entered extras live in EXTRAS below.
   =================================================================== */

/* Home stadium elevation (ft, approximate). Shown when a watched team hosts. */
const HOME_ELEVATION = {
  WYO: 7220, AFA: 6621, UNM: 5100, CSU: 5000, USU: 4700, NEV: 4610,
  NMSU: 3900, UTEP: 3800, BSU: 2700, WSU: 2550, UNLV: 2030, NDSU: 900,
  NIU: 880, TXST: 600, FRES: 330, ORST: 230, SJSU: 100, SDSU: 50,
  HAW: 30, SAC: 30
};

/* Per-game extras ESPN doesn't have. Key = "AWAY@HOME" (ESPN abbreviations).
   Example: "NAVY@AFA": { winProb: "AFA 55% / Navy 45%" }
   Any field set here overrides the automatic value: winProb, elevation, tv, venue. */
const EXTRAS = {
};

(function () {
  const card = document.querySelector('.next-game');
  if (!card) return;
  const ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300";
  const watch = new Set(typeof WATCH !== 'undefined' ? WATCH :
    ["AFA","HAW","NEV","UNM","NDSU","NIU","SJSU","UNLV","UTEP","WYO","BSU","CSU","FRES","ORST","SDSU","TXST","USU","WSU","SAC","NMSU"]);

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
  function name(t) { return t.team.location || t.team.shortDisplayName || t.team.abbreviation; }

  function when(iso) {
    const d = new Date(iso), tz = 'America/Denver';
    const day = d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: tz }).replace(',', '');
    const t = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: tz, timeZoneName: 'short' });
    return [day, t];
  }

  function parse(ev) {
    const c = ev.competitions && ev.competitions[0];
    if (!c) return null;
    const home = c.competitors.find(x => x.homeAway === 'home');
    const away = c.competitors.find(x => x.homeAway === 'away');
    if (!home || !away) return null;
    if (!watch.has(home.team.abbreviation) && !watch.has(away.team.abbreviation)) return null;
    return { ev, c, home, away, state: ev.status.type.state, start: new Date(ev.date).getTime() };
  }

  function pick(games) {
    const live = games.filter(g => g.state === 'in').sort((a, b) => a.start - b.start);
    if (live.length) return { g: live[0], more: live.length - 1 };
    const next = games.filter(g => g.state === 'pre').sort((a, b) => a.start - b.start);
    if (next.length) return { g: next[0], more: 0 };
    const done = games.filter(g => g.state === 'post').sort((a, b) => b.start - a.start);
    return done.length ? { g: done[0], more: 0 } : null;
  }

  function render(p) {
    const { g, more } = p;
    const { c, home, away, state, ev } = g;
    const key = away.team.abbreviation + '@' + home.team.abbreviation;
    const x = EXTRAS[key] || {};
    const [day, time] = when(ev.date);

    const tv = x.tv || (c.broadcasts && c.broadcasts[0] && c.broadcasts[0].names && c.broadcasts[0].names[0]) ||
               (c.geoBroadcasts && c.geoBroadcasts[0] && c.geoBroadcasts[0].media && c.geoBroadcasts[0].media.shortName) || '';
    const v = c.venue || {};
    const place = v.address ? [v.address.city, v.address.state].filter(Boolean).join(' ') : '';
    const venue = x.venue || [v.fullName, place].filter(Boolean).join(', ');
    const elev = x.elevation || (!c.neutralSite && HOME_ELEVATION[home.team.abbreviation]);
    const odds = c.odds && c.odds[0];
    const spread = odds && odds.details && odds.details !== 'EVEN' ? odds.details : (odds && odds.details === 'EVEN' ? 'Pick ’em' : '');
    const ou = odds && odds.overUnder;

    let head, score = '';
    card.classList.toggle('is-live', state === 'in');
    if (state === 'in') {
      head = '<i class="tk-dot"></i>Live now';
    } else if (state === 'post') {
      head = 'Final';
    } else {
      head = 'Next kickoff';
    }

    if (state !== 'pre') {
      const win = state === 'post' ? (Number(away.score) > Number(home.score) ? 'away' : 'home') : '';
      const row = t => '<span class="ls-row' + (win && t.homeAway !== win ? ' ls-lose' : '') + '"><span>' +
                       esc(name(t)) + '</span><b>' + esc(t.score) + '</b></span>';
      const status = state === 'post' ? 'Final' + (ev.status.period > 4 ? ' / OT' : '') :
                     (ev.status.type.shortDetail || ('Q' + ev.status.period + ' ' + (ev.status.displayClock || '')));
      score = '<p class="live-score">' + row(away) + row(home) + '<span class="ls-status">' + esc(status) +
              (more > 0 ? ' | +' + more + ' more live on the ticker' : '') + '</span></p>';
    }

    const meta = [];
    meta.push('<span>' + esc(day) + ' | <b>' + esc(time) + '</b>' + (tv ? ' | ' + esc(tv) : '') + '</span>');
    if (venue) meta.push('<span>' + esc(venue) + '</span>');
    if (elev) meta.push('<span>Elevation <b>' + Number(elev).toLocaleString('en-US') + ' ft</b></span>');
    if (spread || ou) meta.push('<span>' + (spread ? 'Spread <b>' + esc(spread.replace('-', '−')) + '</b>' : '') +
                                (spread && ou ? ' | ' : '') + (ou ? 'O/U ' + esc(ou) : '') + '</span>');
    if (x.winProb) meta.push('<span>Win prob. <b>' + esc(x.winProb) + '</b></span>');

    card.innerHTML = '<h2>' + head + '</h2>' +
      '<p class="matchup">' + esc(name(away)) + '<br>' + (c.neutralSite ? 'vs. ' : 'at ') + esc(name(home)) + '</p>' +
      score + '<div class="meta-row">' + meta.join('') + '</div>';
    return state === 'in';
  }

  function load() {
    fetch(ESPN, { cache: 'no-store' })
      .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(d => {
        const p = pick((d.events || []).map(parse).filter(Boolean));
        const live = p ? render(p) : false;
        setTimeout(load, live ? 60000 : 5 * 60000);
      })
      .catch(() => setTimeout(load, 2 * 60000));   /* keep whatever is showing */
  }
  load();
})();
