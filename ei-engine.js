/* ===================================================================
   ELEVATION INDEX — ENGINE
   Computes every ranking from the games in ei-data.js.
   Nothing in here is a ranking; it is all rules.
   =================================================================== */

const EI = (function () {

  /* ---- tier tables (from the Elevation Index spec) ---- */
  const TIERS = [
    /* maxRank, oppQuality, winBonus */
    [5,   30, 35], [10,  27, 31], [15,  24, 27], [20,  21, 23], [30, 18, 19],
    [40,  15, 15], [60,  11, 11], [80,  8,  8],  [100, 5,  5],  [999, 2, 3]
  ];
  function tier(natRank) {
    for (const t of TIERS) if (natRank <= t[0]) return { q: t[1], w: t[2] };
    return { q: 2, w: 3 };
  }
  function marginBand(m) { return m <= 7 ? 0 : m <= 14 ? 1 : m <= 21 ? 2 : 3; }
  const WIN_MARGIN = [2, 4, 6, 8, 10, 12];             /* 1-7, 8-14, 15-21, 22-28, 29-35, 36+ */
  function winMargin(m) { return WIN_MARGIN[Math.min(5, Math.floor((m - 1) / 7))]; }

  /* loss tables by opponent tier band: top5, 6-15, 16-30, 31-60, 61+ ; by margin band */
  const LOSS = {
    top5:   [10,  4,  -3, -10],
    t6_15:  [6,   1,  -5, -12],
    t16_30: [2,  -4, -10, -16],
    t31_60: [-3, -8, -14, -20],
    t61:    [-7, -13, -19, -25]
  };
  function lossBand(r) { return r <= 5 ? 'top5' : r <= 15 ? 't6_15' : r <= 30 ? 't16_30' : r <= 60 ? 't31_60' : 't61'; }

  /* loss starting values when the game is judged against expectations */
  const LOSS_EXP = { top5: -10, t6_15: -13, t16_30: -16, t31_60: -20, t61: -25 };
  const WIN_Q = 0.6;            /* scale on the opponent-quality value of a win */
  const UPSET = { base: 2, slope: 0.3, cap: 6 };
  const H2H_WINDOW = 20;
  const H2H_DECAY = 0.75;      /* the head-to-head window shrinks 25% for every week since the game */      /* a head-to-head winner within this many points always ranks ahead */
  const OPP_BLEND = 0.7;       /* share of an opponent's strength taken from its résumé rank (vs power rank) */

  const FCS_PERF_CAP = 1;
  const FCS_LOSS_BASE = -35;
  const FCS_LOSS_MARGIN = [3, 7, 11, 15];

  function recency(k) {                 /* k = games ago, 0 = most recent */
    const r = [1.0, 0.82, 0.70, 0.62, 0.56];
    return k < r.length ? r[k] : Math.max(0.50, 0.56 - 0.02 * (k - 4));
  }

  /* ---- FCS strength: FCS Top 25 rank → FBS-equivalent rank ----
     The best FCS teams beat mid-tier FBS teams every year, so a
     ranked FCS opponent is treated like the FBS team it plays like:
     No. 1 FCS ≈ FBS #72, No. 10 ≈ #90, No. 25 ≈ #120, unranked #128. */
  /* FBS-equivalent rank of an FCS team: The Bot places it where its rating
     would rank among FBS teams (equivRank). Old hand-entered poll ranks
     fall back to the original 70 + 2 x poll-rank mapping. */
  function fcsEquiv(opp) { return opp.equivRank || (opp.fcsRank ? 70 + 2 * opp.fcsRank : 128); }
  function effRank(opp) { return opp.fcs ? fcsEquiv(opp) : (opp.natRank || 100); }

  /* ---- schedule-strength factor (season body-of-work add-on) ----
     Opponent quality, not margin: the average effective rank of every
     opponent faced (FCS mapped through fcsEquiv) earns a bounded
     bonus or discount against a #85 baseline. */
  const SOS_BASELINE = 85, SOS_WEIGHT = 0.5, SOS_CLAMP = 20;
  function sosAdjust(oppRankSum, n) {
    if (!n) return 0;
    const a = (SOS_BASELINE - oppRankSum / n) * SOS_WEIGHT;
    return Math.max(-SOS_CLAMP, Math.min(SOS_CLAMP, a));
  }

  /* ---- performance adjustment (±10) from optional stats ---- */
  function performance(g) {
    const s = g.stats; if (!s) return { perf: 0, turnover: 0, note: '' };
    let perf = 0, notes = [];
    if (s.ypp != null && s.oppYpp != null) { const d = s.ypp - s.oppYpp; perf += Math.max(-4, Math.min(4, d * 1.5)); notes.push(d >= 0 ? 'won yards-per-play' : 'lost yards-per-play'); }
    else if (s.yds != null && s.oppYds != null) { const d = (s.yds - s.oppYds) / 100; perf += Math.max(-3, Math.min(3, d)); }
    if (s.thirdPct != null && s.oppThirdPct != null) perf += Math.max(-2, Math.min(2, (s.thirdPct - s.oppThirdPct) / 10));
    if (s.explosive != null && s.oppExplosive != null) perf += Math.max(-2, Math.min(2, (s.explosive - s.oppExplosive) / 3));
    let turnover = 0;
    if (s.to != null || s.oppTo != null) { turnover = 2 * ((s.oppTo || 0) - (s.to || 0)); turnover = Math.max(-8, Math.min(8, turnover)); }
    if (s.to >= 3) notes.push(s.to + ' turnovers');
    if (s.sacksAllowed >= 5) notes.push('allowed ' + s.sacksAllowed + ' sacks');
    perf = Math.max(-10, Math.min(10, perf + turnover));
    return { perf, turnover, note: notes.join(', ') };
  }

  /* ---- score one game given the opponent's national rank / FCS status ---- */
  function scoreGame(g, opp, ownNatRank) {
    const margin = g.pf - g.pa, win = margin > 0, am = Math.abs(margin);
    const out = { win, margin, fcs: !!opp.fcs, oppNatRank: opp.natRank || null,
                  base: 0, qualityLoss: 0, badLoss: false, fcsPenalty: 0, label: '' };

    if (opp.fcs) {
      const fr = opp.fcsRank || null;
      out.oppFcsRank = fr;
      if (win) {
        /* FCS wins are worth less than any FBS win: a top-10 FCS team at most 5,
           other ranked FCS teams 3.5, everyone else 2 (and barely anything if it was close) */
        const cap = fr && fr <= 10 ? 5 : fr ? 3.5 : 2;
        if (!fr && am < 10) { out.base = 0.5; out.label = 'Narrow FCS win'; }
        else { out.base = Math.min(cap, cap * 0.4 + am / 20); out.label = fr && fr <= 10 ? 'Ranked FCS win' : 'FCS win'; }
      } else {
        if (fr) {
          /* loss to a RANKED FCS team: judged like a loss to its FBS
             equivalent plus a scaled FCS surcharge — losing to No. 1
             Montana State is nothing like losing to an unranked FCS team */
          out.base = LOSS[lossBand(fcsEquiv(opp))][marginBand(am)] - (4 + 0.6 * fr);
          out.fcsPenalty = out.base;
          out.badLoss = !(fr <= 10 && am <= 14);
          out.label = (fr <= 10 && am <= 14) ? 'Respectable loss' : 'FCS loss';
        } else {
          /* loss to an UNRANKED FCS team: still the largest penalty in the system */
          out.fcsPenalty = FCS_LOSS_BASE - FCS_LOSS_MARGIN[marginBand(am)];
          out.base = out.fcsPenalty;
          out.badLoss = true;
          out.label = 'FCS loss';
        }
      }
      return out;
    }

    const r = opp.natRank, t = tier(r);
    /* legacy grading: who you played and by how much (no expectations) */
    const legacy = (out => {
      if (win) {
      out.base = t.q + t.w + winMargin(am);
      if (am >= 21 && r <= 100) out.base += 2;                       /* dominance */
      out.label = r <= 25 ? 'Elite win' : r <= 60 ? 'Quality win' : r <= 90 ? 'Solid win' : 'Expected win';
      out.qualityWin = r <= 60;
    } else {
      out.base = LOSS[lossBand(r)][marginBand(am)];
      /* quality-loss bonus: opponent clearly better, and it was close —
         a one-score loss (≤8) to a top-30 team earns real credit */
      const gap = (ownNatRank || 90) - r;
      if (r <= 30 && gap >= 25 && am <= 10) { out.qualityLoss = am <= 3 ? 16 : am <= 8 ? 10 : 5; out.base += out.qualityLoss; }
      /* bad-loss detection */
      if (r >= 61 && am >= 15) out.badLoss = true;
      if (r > 30 && am >= 28) { out.base -= 10; out.badLoss = true; }   /* blowout by a non-elite team */
      if (ownNatRank && r - ownNatRank >= 40) out.badLoss = true;
      out.label = out.base > 0 ? 'Quality loss' : out.badLoss ? 'Bad loss' : r <= 30 ? 'Respectable loss' : 'Loss';
    }
      /* venue: road games are harder, so a road win earns more and a road loss hurts less */
      if (g.site === 'A') { out.venue = 3; out.base += 3; }
      else if (g.site === 'N') { out.venue = 1; out.base += 1; }
      return out;
    })(Object.assign({}, out));
    if (g.exp == null) { Object.assign(out, legacy); }
    else {
      /* graded against the Bot's pre-game expectation (home field is already inside it) */
      const E = (out => {
      /* ---- judged against expectations ----
         exp = the Bot's pre-game margin for this team (positive = favored),
         made using only what was known before kickoff. diff = how much
         better (+) or worse (-) the team did than expected. */
      const exp = g.exp, diff = margin - exp;
      out.exp = exp; out.diff = diff;
      if (win) {
        /* beating expectations counts more against good teams: the bonus for winning by
           more than expected scales with opponent strength (falling short always counts fully) */
        const beat = Math.max(-8, Math.min(8, 0.4 * diff));
        const oq = r <= 40 ? 1 : r <= 80 ? 0.7 : r <= 110 ? 0.4 : 0.2;
        out.base = WIN_Q * (t.q + t.w) + (beat > 0 ? beat * oq : beat);
        if (exp <= -3) {
          /* upset: won as a real underdog (3+ points) — the bigger the underdog, the bigger the reward */
          out.upset = Math.min(UPSET.cap, UPSET.base + UPSET.slope * -exp);
          out.base += out.upset;
          out.label = 'Upset win';
          out.qualityWin = true;
        } else {
          /* a quality win has to be over a good team you weren't expected to roll */
          out.qualityWin = r <= 60 && exp <= 10;
          out.base = Math.max(1, out.base);  /* a win never costs a team points */
          out.label = (exp >= 10 && diff <= -10) ? 'Unconvincing win'
            : r <= 25 && exp <= 10 ? 'Elite win'
            : out.qualityWin ? 'Quality win'
            : r <= 90 ? 'Solid win' : 'Expected win';
        }
      } else {
        /* a loss never adds points on its own; losing to a great team just costs less */
        out.base = LOSS_EXP[lossBand(r)];
        if (exp > 0) {
          /* lost as the favorite */
          out.base += Math.max(-15, 0.6 * diff) - Math.min(12, 4 + 0.5 * exp);
          out.badLoss = true;
          out.label = 'Upset loss';
        } else if (diff >= 3) {
          /* underdog that made it closer than expected: credit for the fight */
          out.qualityLoss = Math.min(12, 2 + 0.6 * diff);
          out.base += out.qualityLoss;
          out.label = 'Quality loss';
        } else {
          /* underdog that lost by about as much as expected, or worse */
          out.base += Math.max(-15, 0.6 * Math.min(0, diff));
          out.badLoss = diff <= -14;
          out.label = out.badLoss ? 'Blowout loss' : 'Expected loss';
        }
        /* getting blown out costs extra no matter who it was against or what was expected */
        if (am >= 21) {
          out.blowout = Math.min(15, 0.5 * (am - 20));
          out.base -= out.blowout;
          if (am >= 28 && out.label !== 'Upset loss') { out.label = 'Blowout loss'; out.badLoss = true; }
        }
      }
        return out;
      })(Object.assign({}, out));
      /* early-season expectations are mostly preseason guesswork, so they phase in:
         Weeks 0-1 count 25%, Week 2 60%, Week 3 on 100% */
      /* (losses always count in full: losing to a weak team is bad no matter the week) */
      const c = !win ? 1 : g.week <= 1 ? 0.25 : g.week === 2 ? 0.6 : 1;
      const lead = c >= 0.5 ? E : legacy;
      Object.assign(out, lead);
      out.base = c * E.base + (1 - c) * legacy.base;
      out.expWeight = c;
      out.exp = E.exp; out.diff = E.diff;
      if (c < 1 && E.upset) out.upset = E.upset * c;
    }
    /* shutout: getting blanked is a statement about you, not the
       opponent — extra penalty on top of the loss, whoever it was */
    if (!win && g.pf === 0) { out.shutout = true; out.base -= 10; }
    /* venue: road games are harder, so a road win earns more and a road
       loss hurts less. FBS opponents only — the FCS branch returns above,
       so venue never inflates an FCS result. */

    return out;
  }

  /* ---- resolve an opponent (tracked team id or OPPONENTS entry) ---- */
  function resolveOpp(name, ratings, RW) {
    if (ratings[name]) return { natRank: ratings[name], fcs: false, tracked: true };
    let o = OPPONENTS[name];
    if (!o) return { natRank: (RW && RW[name]) || 100, fcs: false, unknown: true };
    /* opponent strength as it stood that week (RANK_BY_WEEK), when available */
    if (RW && RW[name] != null) { o = Object.assign({}, o); if (o.fcs) o.equivRank = RW[name]; else o.natRank = RW[name]; }
    return o;
  }
  /* The Bot's national ranks as they stood after a given week (null if not provided) */
  function ranksAt(w) {
    if (typeof RANK_BY_WEEK === 'undefined') return null;
    if (RANK_BY_WEEK[w]) return RANK_BY_WEEK[w];
    const ks = Object.keys(RANK_BY_WEEK).map(Number).filter(k => k <= w);
    return ks.length ? RANK_BY_WEEK[Math.max(...ks)] : null;
  }

  /* ---- compute the full index through a given week ---- */
  function compute(throughWeek) {
    const games = GAMES.filter(g => g.week <= throughWeek).sort((a, b) => a.date < b.date ? -1 : 1);
    const byTeam = {}; TEAMS.forEach(t => byTeam[t[0]] = []);
    games.forEach(g => byTeam[g.team] && byTeam[g.team].push(g));
    /* bye-week credit: each actual bye (a week from Week 1 on with no game)
       is worth the team's own average game, so an idle weekend never costs
       a team ground. The optional Week 0 opener is not counted as a bye. */
    const byesOf = tg => { let b = 0; for (let w = 1; w <= throughWeek; w++) if (!tg.some(g => g.week === w)) b++; return b; };

    /* seed national ranks, then iterate: tracked opponents take on ranks
       derived from the previous pass's ordering (mapped onto 28–125). */
    /* national ranks for tracked teams: The Bot's current rank when the
       automatic feed is loaded; otherwise the old seed-and-iterate method */
    const botRanks = (typeof BOT_NATRANK !== 'undefined') ? BOT_NATRANK : null;
    const RW = ranksAt(throughWeek);
    let ratings = {}; TEAMS.forEach(t => ratings[t[0]] = (RW && RW[t[1]]) || (botRanks && botRanks[t[0]]) || t[4]);
    const base0 = Object.assign({}, ratings);
    let result;
    for (let pass = 0; pass < 4; pass++) {
      result = TEAMS.map(t => {
        const id = t[0], tg = byTeam[id], n = tg.length;
        let sosN = 0, score = 0, rows = [], qualityWins = 0, qualityLosses = 0, badLosses = 0, winStrength = 0, pd = 0, oppRankSum = 0;
        let rec = { w: 0, l: 0, fbsW: 0, fbsL: 0, fcsW: 0, fcsL: 0, confW: 0, confL: 0 };
        tg.forEach((g, i) => {
          const opp = resolveOpp(g.opp, ratings, RW);
          const s = scoreGame(g, opp, ratings[id]);
          const rc = recency(n - 1 - i);
          const p = performance(g);
          /* box-score bonus against FCS teams is capped at +2: outgaining an FCS
             team proves little. Struggling against one still costs the full amount. */
          if (opp.fcs && p.perf > FCS_PERF_CAP) p.perf = FCS_PERF_CAP;
          /* outgaining a bad FBS team proves less than outgaining a good one: the
             box-score bonus scales with opponent strength (a poor box score still costs fully) */
          else if (!opp.fcs && p.perf > 0) { const r = opp.natRank || 100; p.perf *= r <= 40 ? 1 : r <= 80 ? 0.7 : r <= 110 ? 0.4 : 0.2; }
          const final = s.base * rc + p.perf;
          score += final; pd += s.margin;
          /* getting blown out doesn't earn schedule credit */
          if (!(s.win === false && Math.abs(s.margin) >= 21)) { oppRankSum += effRank(opp); sosN++; }
          if (s.win) { rec.w++; opp.fcs ? rec.fcsW++ : rec.fbsW++; if (s.qualityWin) qualityWins++; winStrength += s.base; }
          else       { rec.l++; opp.fcs ? rec.fcsL++ : rec.fbsL++; if (s.qualityLoss) qualityLosses++; if (s.badLoss) badLosses++; }
          rows.push(Object.assign({}, g, s, { recency: rc, perf: p.perf, turnover: p.turnover, perfNote: p.note, final, oppName: displayName(g.opp) }));
        });
        const byes = n ? byesOf(tg) : 0;
        const byeCredit = n ? byes * (score / n) : 0;
        score += byeCredit;
        const sosAdj = sosAdjust(oppRankSum, sosN);
        score += sosAdj;
        /* a résumé with no FBS win — whether the wins were all FCS or
           there are no wins at all — hasn't proven it can beat anyone
           in its own division: small discount */
        const fcsOnlyWins = n > 0 && rec.fbsW === 0;
        if (fcsOnlyWins) score -= 3;
        return { id, name: t[1], conf: t[2], color: t[3], logo: t[5], seed: t[4], games: rows, score,
                 rec, qualityWins, qualityLosses, badLosses, winStrength, pd,
                 sos: sosN ? oppRankSum / sosN : null, sosAdj, fcsOnlyWins, byeCredit, byes, gamesPlayed: n,
                 last: rows.length ? rows[rows.length - 1] : null };
      });
      sortTeams(result, throughWeek);
      /* re-derive national ranks for tracked teams from this ordering */
      const next = {};
      result.forEach((t, i) => next[t.id] = t.games.length ? Math.round(28 + i * (97 / 19)) : t.seed);
      if (!botRanks && !RW) ratings = next;
      else if (OPP_BLEND > 0 && TEAMS.length >= 60) {
        /* judge opponents partly by what they've done (résumé rank), not only by
           the power rating, which still carries some preseason weight early on */
        const nr = {};
        result.forEach((t, i) => nr[t.id] = Math.round((1 - OPP_BLEND) * base0[t.id] + OPP_BLEND * (i + 1)));
        ratings = nr;
      }
    }
    result.forEach((t, i) => { t.rank = i + 1; t.natRank = ratings[t.id]; });
    return result;
  }

  /* head-to-head: did x beat y in every meeting so far? */
  function beat(x, y) {
    const ms = x.games.filter(g => g.opp === y.id);
    return ms.length > 0 && ms.every(g => g.win);
  }

  function sortTeams(arr, wk) {
    arr.sort((a, b) => {
      if (Math.abs(a.score - b.score) > 0.5) return b.score - a.score;
      if (a.qualityWins !== b.qualityWins) return b.qualityWins - a.qualityWins;
      if (a.winStrength !== b.winStrength) return b.winStrength - a.winStrength;
      if (a.qualityLosses !== b.qualityLosses) return b.qualityLosses - a.qualityLosses;
      if (a.badLosses !== b.badLosses) return a.badLosses - b.badLosses;
      if (a.pd !== b.pd) return b.pd - a.pd;
      const la = a.last ? a.last.final : 0, lb = b.last ? b.last.final : 0;
      if (la !== lb) return lb - la;
      return a.seed - b.seed;
    });
    /* head-to-head: a team that beat another (and didn't also lose to it) ranks
       just above it when the loser's score is within H2H_WINDOW of the winner's.
       Lifts are measured on the original scores, so they can't chain a team past
       anyone more than H2H_WINDOW better than it. */
    const adj = new Map(arr.map(t => [t.id, t.score]));
    for (const b of arr)
        for (const a of arr) {
          if (a === b || a.score <= b.score || a.score - b.score > H2H_WINDOW) continue;
          if (!beat(b, a) || beat(a, b)) continue;
          /* the head-to-head pull is strongest right after the game and fades each week */
          const last = Math.max(...b.games.filter(g => g.opp === a.id).map(g => g.week));
          const window = H2H_WINDOW * Math.pow(H2H_DECAY, Math.max(0, (wk == null ? last : wk) - last));
          if (a.score - b.score <= window) adj.set(b.id, Math.max(adj.get(b.id), a.score + 0.01));
        }
    const pos = new Map(arr.map((t, i) => [t.id, i]));
    arr.sort((a, b) => (adj.get(b.id) - adj.get(a.id)) || (pos.get(a.id) - pos.get(b.id)));
  }

  function displayName(opp) { const t = TEAMS.find(x => x[0] === opp); return t ? t[1] : opp; }

  /* ---- snapshots for every week, with movement + auto-generated reasons ---- */
  function history(throughWeek) {
    const weeks = [];
    for (let w = 0; w <= throughWeek; w++) {
      const cur = compute(w);
      if (w >= 1 && weeks.length) limitByeMoves(cur, weeks[weeks.length - 1], w);
      weeks.push(cur);
    }
    const latest = weeks[weeks.length - 1], prev = weeks.length > 1 ? weeks[weeks.length - 2] : null;
    latest.forEach(t => {
      const p = prev ? prev.find(x => x.id === t.id) : null;
      t.prevRank = p ? p.rank : null;
      t.prevScore = p ? p.score : 0;
      t.move = p ? p.rank - t.rank : 0;
      t.reason = reason(t, throughWeek);
      t.bestWin = best(t.games.filter(g => g.win));
      t.worstLoss = worst(t.games.filter(g => !g.win));
      t.ranks = weeks.map(wk => wk.find(x => x.id === t.id).rank);
    });
    return { weeks, latest };
  }
  /* A team on a bye holds its ground: it can move at most BYE_MAX spots,
     unless its own score fell because the teams it beat have since been
     re-rated weaker (its schedule weakened), which can drop it further. */
  const BYE_MAX = 5;
  function limitByeMoves(cur, prev, w) {
    const prevById = {}; prev.forEach(t => prevById[t.id] = t);
    const key = new Map();
    cur.forEach((t, i) => {
      const p = prevById[t.id];
      const onBye = p && t.games.length > 0 && !t.games.some(g => g.week === w);
      let k = i + 1;
      if (onBye) {
        /* schedule got weaker: its own games are worth less than last week (bye credit aside) */
        const weakened = (t.score - (t.byeCredit || 0)) < (p.score - (p.byeCredit || 0)) - 3;
        const lo = p.rank - BYE_MAX, hi = weakened ? cur.length : p.rank + BYE_MAX;
        k = Math.max(lo, Math.min(hi, k)) - 0.5;                /* held teams win ties */
        t.byeHeld = k + 0.5 !== i + 1;
        t.byeWeakened = weakened;
      }
      key.set(t.id, k);
    });
    cur.sort((a, b) => key.get(a.id) - key.get(b.id));
    cur.forEach((t, i) => t.rank = i + 1);
  }
  function best(list) { return list.length ? list.reduce((a, b) => b.base > a.base ? b : a) : null; }
  function worst(list) { return list.length ? list.reduce((a, b) => b.base < a.base ? b : a) : null; }

  function oppLabel(g) {
    if (g.fcs) return g.oppFcsRank ? 'No. ' + g.oppFcsRank + ' (FCS) ' + g.oppName : g.oppName + ' (FCS)';
    return g.oppNatRank <= 25 ? 'No. ' + g.oppNatRank + ' ' + g.oppName : g.oppName;
  }
  function scoreLine(g) { return g.pf + '–' + g.pa; }

  function reason(t, wk) {
    const g = t.last; if (!g) return 'No games played yet.';
    const dir = t.move > 0 ? 'Moved up ' + t.move : t.move < 0 ? 'Dropped ' + (-t.move) : 'Held';
    if (wk != null && g.week < wk) {
      const lead = t.move > 0 ? 'Moved up ' + t.move + ' on' : t.move < 0 ? 'Slipped ' + (-t.move) + ' on' : 'Held steady through';
      if (t.byeWeakened && t.move < 0) return lead + ' a bye week. Teams it beat earlier were re-rated weaker, so its résumé lost value.';
      return lead + ' a bye week. A team on a bye moves at most ' + BYE_MAX + ' spots unless its schedule weakens.';
    }
    const fcsLoss = t.games.find(x => x.label === 'FCS loss');
    if (g.label === 'FCS loss') return dir + ' after losing ' + scoreLine(g) + ' to ' + (g.oppFcsRank ? oppLabel(g) + ' — a ranked FCS team softens the blow, but an FCS loss still stings in the Elevation Index.' : g.oppName + ', an FCS opponent — the largest single penalty in the Elevation Index.');
    if (!g.win && g.fcs && g.label === 'Respectable loss') return dir + '. Losing ' + scoreLine(g) + ' to ' + oppLabel(g) + ' is judged like losing to the FBS team they play like — the top of the FCS is better than the bottom of the FBS.';
    if (g.win && g.label === 'Ranked FCS win') return dir + ' after beating ' + oppLabel(g) + ' ' + scoreLine(g) + ' — a top-10 FCS scalp counts for more than a routine FCS win, though it is still capped.';
    if (g.win && g.label === 'Narrow FCS win') return dir + '. Beating ' + g.oppName + ' ' + scoreLine(g) + ' avoided disaster, but a one-score game against an unranked FCS team banks almost nothing in the Index.';
    const fav = x => x.exp > 0 ? ' as a ' + Math.round(x.exp) + '-point favorite' : x.exp < 0 ? ' as a ' + Math.round(-x.exp) + '-point underdog' : '';
    if (g.win && g.label === 'Upset win') return dir + ' after an upset of ' + oppLabel(g) + ' ' + scoreLine(g) + fav(g) + '.';
    if (g.win && g.label === 'Unconvincing win') return dir + '. Beat ' + g.oppName + ' ' + scoreLine(g) + fav(g) + ', well short of expectations, so the win counted for less.';
    if (!g.win && g.label === 'Upset loss') return dir + ' after losing ' + scoreLine(g) + ' to ' + oppLabel(g) + fav(g) + ', a penalty for losing a game it was expected to win.';
    if (!g.win && g.label === 'Blowout loss') return dir + ' after a ' + Math.abs(g.margin) + '-point loss to ' + oppLabel(g) + fav(g) + ', much worse than expected.';
    if (!g.win && g.label === 'Expected loss') return dir + ' after losing ' + scoreLine(g) + ' to ' + oppLabel(g) + fav(g) + ', about as expected.';
    if (!g.win && g.label === 'Quality loss' && g.exp != null) return dir + '. Lost ' + scoreLine(g) + ' to ' + oppLabel(g) + fav(g) + ' but played them closer than expected, which earns credit.' + (fcsLoss ? ' The FCS loss to ' + fcsLoss.oppName + ' still dominates the résumé.' : '');
    if (g.win && g.label === 'Elite win') return dir + ' after beating ' + oppLabel(g) + ' ' + scoreLine(g) + ', the best win on any résumé ' + (typeof EI_SCOPE_OVERRIDE !== 'undefined' ? EI_SCOPE_OVERRIDE : typeof EI_SCOPE !== 'undefined' ? EI_SCOPE : 'in the West') + '.';
    if (g.win && g.label === 'Quality win') return dir + ' after a quality win over ' + oppLabel(g) + ' ' + scoreLine(g) + '.';
    if (g.win && g.fcs) return dir + (fcsLoss ? ' — the FCS win over ' + g.oppName + ' counts, but the earlier FCS loss to ' + fcsLoss.oppName + ' still dominates the résumé.' : '. An FCS win over ' + g.oppName + ' carries limited value, so the ranking barely moved.');
    if (g.win) return dir + ' after beating ' + g.oppName + ' ' + scoreLine(g) + (g.margin >= 21 ? ' — a dominant margin, though the opponent limits how much it counts.' : '.');
    if (g.label === 'Quality loss') return dir + '. Losing ' + scoreLine(g) + ' to ' + oppLabel(g) + ' is a quality loss and earned credit rather than a penalty' + (fcsLoss ? ', but the FCS loss to ' + fcsLoss.oppName + ' remains the biggest item on the résumé.' : '.');
    if (g.badLoss) return dir + ' after a ' + Math.abs(g.margin) + '-point loss to ' + g.oppName + ', flagged as a bad loss.';
    return dir + ' after losing ' + scoreLine(g) + ' to ' + oppLabel(g) + '.';
  }

  /* ---- article helpers ---- */
  function whyRanked(t) {
    const parts = [];
    if (t.qualityWins) parts.push(t.qualityWins + ' quality win' + (t.qualityWins > 1 ? 's' : '') + (t.bestWin ? ' (best: ' + oppLabel(t.bestWin) + ' ' + scoreLine(t.bestWin) + ')' : ''));
    if (t.qualityLosses) parts.push(t.qualityLosses + ' quality loss' + (t.qualityLosses > 1 ? 'es' : ''));
    if (t.badLosses) parts.push(t.badLosses + ' bad loss' + (t.badLosses > 1 ? 'es' : '') + (t.worstLoss ? ' (' + oppLabel(t.worstLoss) + ' ' + scoreLine(t.worstLoss) + ')' : ''));
    const fcsL = t.games.filter(g => g.label === 'FCS loss').length;
    if (fcsL) parts.push('an FCS loss, the largest penalty in the system');
    else if (t.games.length) parts.push('no FCS loss');
    if (Math.abs(t.sosAdj) >= 3) parts.push(t.sosAdj > 0 ? 'a schedule-strength bonus (average opponent ≈ #' + Math.round(t.sos) + ' nationally)' : 'a soft-schedule discount (average opponent ≈ #' + Math.round(t.sos) + ' nationally)');
    if (t.fcsOnlyWins) parts.push('no FBS win yet, which carries a discount');
    const so = t.games.filter(g => !g.win && g.shutout).length;
    if (so) parts.push(so > 1 ? so + ' shutout losses, each an extra penalty' : 'a shutout loss, an extra penalty on its own');
    return parts.length ? 'Because ' + t.name + ' has ' + parts.join(', ') + '.' : 'No résumé yet.';
  }

  /* "To improve" comes from the latest Index article (IMPROVE in ei-data.js) */
  function improve(t) {
    return (typeof IMPROVE !== 'undefined' && IMPROVE[t.id]) || '';
  }

  /* a ranking of a subset of teams (e.g. the Western 20 from the National Index):
     same scores and order, renumbered 1..n, with movement and reasons recomputed */
  function subset(H, ids) {
    const set = new Set(ids);
    const weeks = H.weeks.map(wk => wk.filter(t => set.has(t.id)).map((t, i) => Object.assign({}, t, { natRank: t.natRank, nationalRank: t.rank, rank: i + 1 })));
    const latest = weeks[weeks.length - 1], prev = weeks.length > 1 ? weeks[weeks.length - 2] : null, wk = weeks.length - 1;
    latest.forEach(t => {
      const p = prev ? prev.find(x => x.id === t.id) : null;
      t.prevRank = p ? p.rank : null;
      t.prevScore = p ? p.score : 0;
      t.move = p ? p.rank - t.rank : 0;
      t.reason = reason(t, wk);
      t.ranks = weeks.map(w => { const x = w.find(y => y.id === t.id); return x ? x.rank : null; });
    });
    return { weeks, latest };
  }

  return { compute, history, subset, whyRanked, improve, oppLabel, scoreLine };
})();
