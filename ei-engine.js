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
  function fcsEquiv(opp) { return opp.fcsRank ? 70 + 2 * opp.fcsRank : 128; }
  function effRank(opp) { return opp.fcs ? fcsEquiv(opp) : (opp.natRank || 100); }

  /* ---- schedule-strength factor (season body-of-work add-on) ----
     Opponent quality, not margin: the average effective rank of every
     opponent faced (FCS mapped through fcsEquiv) earns a bounded
     bonus or discount against a #85 baseline. */
  const SOS_BASELINE = 85, SOS_WEIGHT = 0.25, SOS_CLAMP = 10;
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
        if (fr) {
          /* ranked FCS win: scored like a win over its FBS equivalent,
             but still capped — an FCS win never carries a full FBS win */
          const t = tier(fcsEquiv(opp));
          out.base = Math.min(fr <= 10 ? 16 : 14, t.q + t.w + winMargin(am));
          out.label = fr <= 10 ? 'Ranked FCS win' : 'FCS win';
        } else if (am < 10) {
          /* scraping past an unranked FCS team is a warning sign, not a win:
             it banks almost nothing */
          out.base = 1;
          out.label = 'Narrow FCS win';
        } else {
          let v = 4 + Math.min(6, Math.floor(am / 7) * 1.5) + (opp.strong ? 2 : 0);
          out.base = Math.min(opp.strong ? 14 : 12, v);
          out.label = 'FCS win';
        }
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
    /* shutout: getting blanked is a statement about you, not the
       opponent — extra penalty on top of the loss, whoever it was */
    if (!win && g.pf === 0) { out.shutout = true; out.base -= 6; }
    /* venue: road games are harder, so a road win earns more and a road
       loss hurts less. FBS opponents only — the FCS branch returns above,
       so venue never inflates an FCS result. */
    if (g.site === 'A') { out.venue = 3; out.base += 3; }
    else if (g.site === 'N') { out.venue = 1; out.base += 1; }
    return out;
  }

  /* ---- resolve an opponent (tracked team id or OPPONENTS entry) ---- */
  function resolveOpp(name, ratings) {
    if (ratings[name]) return { natRank: ratings[name], fcs: false, tracked: true };
    const o = OPPONENTS[name];
    if (!o) return { natRank: 100, fcs: false, unknown: true };
    return o;
  }

  /* ---- compute the full index through a given week ---- */
  function compute(throughWeek) {
    const games = GAMES.filter(g => g.week <= throughWeek).sort((a, b) => a.date < b.date ? -1 : 1);
    const byTeam = {}; TEAMS.forEach(t => byTeam[t[0]] = []);
    games.forEach(g => byTeam[g.team].push(g));

    /* seed national ranks, then iterate: tracked opponents take on ranks
       derived from the previous pass's ordering (mapped onto 28–125). */
    let ratings = {}; TEAMS.forEach(t => ratings[t[0]] = t[4]);
    let result;
    for (let pass = 0; pass < 4; pass++) {
      result = TEAMS.map(t => {
        const id = t[0], tg = byTeam[id], n = tg.length;
        let score = 0, rows = [], qualityWins = 0, qualityLosses = 0, badLosses = 0, winStrength = 0, pd = 0, oppRankSum = 0;
        let rec = { w: 0, l: 0, fbsW: 0, fbsL: 0, fcsW: 0, fcsL: 0, confW: 0, confL: 0 };
        tg.forEach((g, i) => {
          const opp = resolveOpp(g.opp, ratings);
          const s = scoreGame(g, opp, ratings[id]);
          const rc = recency(n - 1 - i);
          const p = performance(g);
          const final = s.base * rc + p.perf;
          score += final; pd += s.margin; oppRankSum += effRank(opp);
          if (s.win) { rec.w++; opp.fcs ? rec.fcsW++ : rec.fbsW++; if (s.qualityWin) qualityWins++; winStrength += s.base; }
          else       { rec.l++; opp.fcs ? rec.fcsL++ : rec.fbsL++; if (s.qualityLoss) qualityLosses++; if (s.badLoss) badLosses++; }
          rows.push(Object.assign({}, g, s, { recency: rc, perf: p.perf, turnover: p.turnover, perfNote: p.note, final, oppName: displayName(g.opp) }));
        });
        const sosAdj = sosAdjust(oppRankSum, n);
        score += sosAdj;
        /* a résumé with no FBS win — whether the wins were all FCS or
           there are no wins at all — hasn't proven it can beat anyone
           in its own division: small discount */
        const fcsOnlyWins = n > 0 && rec.fbsW === 0;
        if (fcsOnlyWins) score -= 3;
        return { id, name: t[1], conf: t[2], color: t[3], logo: t[5], seed: t[4], games: rows, score,
                 rec, qualityWins, qualityLosses, badLosses, winStrength, pd,
                 sos: n ? oppRankSum / n : null, sosAdj, fcsOnlyWins,
                 last: rows.length ? rows[rows.length - 1] : null };
      });
      sortTeams(result);
      /* re-derive national ranks for tracked teams from this ordering */
      const next = {};
      result.forEach((t, i) => next[t.id] = t.games.length ? Math.round(28 + i * (97 / 19)) : t.seed);
      ratings = next;
    }
    result.forEach((t, i) => { t.rank = i + 1; t.natRank = ratings[t.id]; });
    return result;
  }

  /* head-to-head: did x beat y in every meeting so far? */
  function beat(x, y) {
    const ms = x.games.filter(g => g.opp === y.id);
    return ms.length > 0 && ms.every(g => g.win);
  }

  function sortTeams(arr) {
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
    /* head-to-head override: two teams essentially tied (within 4 pts)
       who met on the field never rank with the loser ahead */
    for (let pass = 0; pass < 2; pass++)
      for (let i = 0; i + 1 < arr.length; i++) {
        const a = arr[i], b = arr[i + 1];
        if (Math.abs(a.score - b.score) <= 4 && beat(b, a)) { arr[i] = b; arr[i + 1] = a; }
      }
  }

  function displayName(opp) { const t = TEAMS.find(x => x[0] === opp); return t ? t[1] : opp; }

  /* ---- snapshots for every week, with movement + auto-generated reasons ---- */
  function history(throughWeek) {
    const weeks = [];
    for (let w = 0; w <= throughWeek; w++) weeks.push(compute(w));
    const latest = weeks[weeks.length - 1], prev = weeks.length > 1 ? weeks[weeks.length - 2] : null;
    latest.forEach(t => {
      const p = prev ? prev.find(x => x.id === t.id) : null;
      t.prevRank = p ? p.rank : null;
      t.prevScore = p ? p.score : 0;
      t.move = p ? p.rank - t.rank : 0;
      t.reason = reason(t);
      t.bestWin = best(t.games.filter(g => g.win));
      t.worstLoss = worst(t.games.filter(g => !g.win));
      t.ranks = weeks.map(wk => wk.find(x => x.id === t.id).rank);
    });
    return { weeks, latest };
  }
  function best(list) { return list.length ? list.reduce((a, b) => b.base > a.base ? b : a) : null; }
  function worst(list) { return list.length ? list.reduce((a, b) => b.base < a.base ? b : a) : null; }

  function oppLabel(g) {
    if (g.fcs) return g.oppFcsRank ? 'No. ' + g.oppFcsRank + ' (FCS) ' + g.oppName : g.oppName + ' (FCS)';
    return g.oppNatRank <= 25 ? 'No. ' + g.oppNatRank + ' ' + g.oppName : g.oppName;
  }
  function scoreLine(g) { return g.pf + '–' + g.pa; }

  function reason(t) {
    const g = t.last; if (!g) return 'No games played yet.';
    const dir = t.move > 0 ? 'Moved up ' + t.move : t.move < 0 ? 'Dropped ' + (-t.move) : 'Held';
    const fcsLoss = t.games.find(x => x.label === 'FCS loss');
    if (g.label === 'FCS loss') return dir + ' after losing ' + scoreLine(g) + ' to ' + (g.oppFcsRank ? oppLabel(g) + ' — a ranked FCS team softens the blow, but an FCS loss still stings in the Elevation Index.' : g.oppName + ', an FCS opponent — the largest single penalty in the Elevation Index.');
    if (!g.win && g.fcs && g.label === 'Respectable loss') return dir + '. Losing ' + scoreLine(g) + ' to ' + oppLabel(g) + ' is judged like losing to the FBS team they play like — the top of the FCS is better than the bottom of the FBS.';
    if (g.win && g.label === 'Ranked FCS win') return dir + ' after beating ' + oppLabel(g) + ' ' + scoreLine(g) + ' — a top-10 FCS scalp counts for more than a routine FCS win, though it is still capped.';
    if (g.win && g.label === 'Narrow FCS win') return dir + '. Beating ' + g.oppName + ' ' + scoreLine(g) + ' avoided disaster, but a one-score game against an unranked FCS team banks almost nothing in the Index.';
    if (g.win && g.label === 'Elite win') return dir + ' after beating ' + oppLabel(g) + ' ' + scoreLine(g) + ', the best win on any résumé in the West.';
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

  function improve(t) {
    const g = t.last; if (!g) return '';
    const nxt = NEXT[t.id] || 'TBD';
    if (nxt === 'Bye') return t.name + ' is off this week. ' + (g.win ? 'The bye comes after a win, which is the easier kind.' : 'The bye is a chance to fix ' + (g.perfNote || 'what went wrong against ' + g.oppName) + ' before the next one.');
    let issue;
    if (g.stats && g.stats.to >= 3) issue = 'ball security — ' + g.stats.to + ' turnovers against ' + g.oppName + ' turned a winnable game';
    else if (g.stats && g.stats.sacksAllowed >= 5) issue = 'pass protection — ' + g.stats.sacksAllowed + ' sacks allowed against ' + g.oppName;
    else if (!g.win && g.pf <= 10) issue = 'scoring — ' + g.pf + ' points against ' + g.oppName + ' is not enough to win a game';
    else if (!g.win && g.pa >= 35) issue = 'run and pass defense — ' + g.pa + ' points allowed to ' + g.oppName;
    else if (g.win && g.margin <= 7 && g.fcs) issue = 'finishing — an FCS opponent stayed within ' + g.margin + ' points';
    else if (g.win) issue = 'consistency — the win over ' + g.oppName + ' was the right result, and the next opponent is a step up';
    else issue = 'closing — the ' + Math.abs(g.margin) + '-point loss to ' + g.oppName + ' was competitive but not enough';
    return 'The priority against ' + nxt.replace(/^(vs|at) /, '') + ' is ' + issue + '. Enter box-score stats for this game in ei-data.js and this section sharpens automatically.';
  }

  return { compute, history, whyRanked, improve, oppLabel, scoreLine };
})();
