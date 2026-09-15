/* ===================================================================
   ELEVATION INDEX — DATA
   This is the only file you edit each week.

   1. Add each game to GAMES (one line per team per game — a game
      between two tracked teams gets TWO lines, one from each side).
   2. Update NEXT with each team's next opponent.
   3. If a new non-tracked opponent appears, add it to OPPONENTS
      with a national rank estimate (AP rank if ranked, otherwise
      a reasonable power-rating position out of ~135).

   Stats fields on a game are OPTIONAL. Fill them in when you have
   the box score and the performance adjustment kicks in; leave
   them out and the engine falls back to margin-based dominance.
   =================================================================== */

const TEAMS = [
  /* id, name, conference, color, seed national rank (preseason estimate), logo (optional URL) */
  ["AFA",  "Air Force",          "Mountain West", "#003087", 82,  "https://a.espncdn.com/i/teamlogos/ncaa/500/2005.png"],
  ["HAW",  "Hawai'i",            "Mountain West", "#024731", 100, "https://a.espncdn.com/i/teamlogos/ncaa/500/62.png"],
  ["NEV",  "Nevada",             "Mountain West", "#003366", 96,  "https://a.espncdn.com/i/teamlogos/ncaa/500/2440.png"],
  ["UNM",  "New Mexico",         "Mountain West", "#BA0C2F", 70,  "https://a.espncdn.com/i/teamlogos/ncaa/500/167.png"],
  ["NDSU", "North Dakota State", "Mountain West", "#009A44", 78,  "https://a.espncdn.com/i/teamlogos/ncaa/500/2449.png"],
  ["NIU",  "Northern Illinois",  "Mountain West", "#C8102E", 98,  "https://a.espncdn.com/i/teamlogos/ncaa/500/2459.png"],
  ["SJSU", "San José State",     "Mountain West", "#0055A2", 104, "https://a.espncdn.com/i/teamlogos/ncaa/500/23.png"],
  ["UNLV", "UNLV",               "Mountain West", "#CF0A2C", 60,  "https://a.espncdn.com/i/teamlogos/ncaa/500/2439.png"],
  ["UTEP", "UTEP",               "Mountain West", "#FF8200", 118, "https://a.espncdn.com/i/teamlogos/ncaa/500/2638.png"],
  ["WYO",  "Wyoming",            "Mountain West", "#492F24", 102, "https://a.espncdn.com/i/teamlogos/ncaa/500/2751.png"],
  ["BSU",  "Boise State",        "Pac-12",        "#0033A0", 30,  "https://a.espncdn.com/i/teamlogos/ncaa/500/68.png"],
  ["CSU",  "Colorado State",     "Pac-12",        "#1E4D2B", 84,  "https://a.espncdn.com/i/teamlogos/ncaa/500/36.png"],
  ["FRES", "Fresno State",       "Pac-12",        "#DB0032", 66,  "https://a.espncdn.com/i/teamlogos/ncaa/500/278.png"],
  ["ORST", "Oregon State",       "Pac-12",        "#DC4405", 90,  "https://a.espncdn.com/i/teamlogos/ncaa/500/204.png"],
  ["SDSU", "San Diego State",    "Pac-12",        "#A6192E", 72,  "https://a.espncdn.com/i/teamlogos/ncaa/500/21.png"],
  ["TXST", "Texas State",        "Pac-12",        "#501214", 68,  "https://a.espncdn.com/i/teamlogos/ncaa/500/326.png"],
  ["USU",  "Utah State",         "Pac-12",        "#0F2439", 88,  "https://a.espncdn.com/i/teamlogos/ncaa/500/328.png"],
  ["WSU",  "Washington State",   "Pac-12",        "#981E32", 76,  "https://a.espncdn.com/i/teamlogos/ncaa/500/265.png"],
  ["NMSU", "New Mexico State",   "Independent",   "#891216", 120, "https://a.espncdn.com/i/teamlogos/ncaa/500/166.png"],
  ["SAC",  "Sacramento State",   "MAC",           "#043927", 126, "https://a.espncdn.com/i/teamlogos/ncaa/500/16.png"]
];

/* Non-tracked opponents. natRank = national rank estimate at time of game.
   fcs = true for FCS programs. strong = true for elite FCS programs. */
const OPPONENTS = {
  "Oregon":            { natRank: 21,   fcs: false },
  "Texas":             { natRank: 1,   fcs: false },
  "Oklahoma":          { natRank: 24,  fcs: false },
  "Texas Tech":        { natRank: 13,  fcs: false },
  "USC":               { natRank: 12,  fcs: false },
  "Washington":        { natRank: 26,  fcs: false },
  "Iowa":              { natRank: 18,  fcs: false },
  "Houston":           { natRank: 22,  fcs: false },
  "Kansas State":      { natRank: 36,  fcs: false },
  "Memphis":           { natRank: 46,  fcs: false },
  "Florida State":     { natRank: 50,  fcs: false },
  "UCLA":              { natRank: 40,  fcs: false },
  "North Texas":       { natRank: 55,  fcs: false },
  "UTSA":              { natRank: 62,  fcs: false },
  "Stanford":          { natRank: 85,  fcs: false },
  "Western Kentucky":  { natRank: 95,  fcs: false },
  "Jacksonville State":{ natRank: 100, fcs: false },
  "Eastern Michigan":  { natRank: 108, fcs: false },
  "Central Michigan":  { natRank: 112, fcs: false },
  "Montana State":     { fcs: true, strong: true },
  "Illinois State":    { fcs: true, strong: true },
  "Idaho State":       { fcs: true, strong: false },
  "Southern Utah":     { fcs: true, strong: false },
  "Cal Poly":          { fcs: true, strong: false },
  "Northern Colorado": { fcs: true, strong: false },
  "Portland State":    { fcs: true, strong: false },
  "Duquesne":          { fcs: true, strong: false },
  "Fordham":           { fcs: true, strong: false },
  "Mercyhurst":        { fcs: true, strong: false },
  "Texas Southern":    { fcs: true, strong: false },
  "Mississippi Valley State": { fcs: true, strong: false }
};

/* Games. Fields:
   team, week, date, opp (name, or a tracked team id), site (H/A/N), pf, pa,
   optional stats: { yds, oppYds, ypp, oppYpp, to, oppTo, firstDowns, oppFirstDowns,
                     thirdPct, oppThirdPct, explosive, oppExplosive, sacks, sacksAllowed } */
const GAMES = [
  /* ---- Week 0 ---- */
  { team:"NDSU", week:0, date:"2026-08-29", opp:"Jacksonville State", site:"H", pf:33, pa:7,
    stats:{ yds:381, oppYds:170, to:0, oppTo:1 } },
  { team:"SJSU", week:0, date:"2026-08-29", opp:"USC",               site:"A", pf:26, pa:42 },
  { team:"HAW",  week:0, date:"2026-08-29", opp:"Stanford",          site:"A", pf:27, pa:37 },
  { team:"UNLV", week:0, date:"2026-08-29", opp:"Memphis",           site:"H", pf:21, pa:27,
    stats:{ sacksAllowed:6 } },
  { team:"NMSU", week:0, date:"2026-08-29", opp:"Florida State",     site:"A", pf:17, pa:34 },
  { team:"SAC",  week:0, date:"2026-08-29", opp:"Eastern Michigan",  site:"A", pf:17, pa:28 },

  /* ---- Week 1 ---- */
  { team:"BSU",  week:1, date:"2026-09-05", opp:"Oregon",            site:"A", pf:27, pa:34 },
  { team:"TXST", week:1, date:"2026-09-05", opp:"Texas",             site:"A", pf:7,  pa:59 },
  { team:"FRES", week:1, date:"2026-09-04", opp:"USC",               site:"A", pf:0,  pa:39 },
  { team:"UTEP", week:1, date:"2026-09-04", opp:"Oklahoma",          site:"A", pf:0,  pa:51 },
  { team:"WSU",  week:1, date:"2026-09-06", opp:"Washington",        site:"A", pf:10, pa:24 },
  { team:"NIU",  week:1, date:"2026-09-05", opp:"Iowa",              site:"A", pf:0,  pa:40,
    stats:{ yds:120 } },
  { team:"ORST", week:1, date:"2026-09-05", opp:"Houston",           site:"A", pf:20, pa:33 },
  { team:"CSU",  week:1, date:"2026-09-05", opp:"WYO",               site:"H", pf:35, pa:13 },
  { team:"WYO",  week:1, date:"2026-09-05", opp:"CSU",               site:"A", pf:13, pa:35 },
  { team:"UNLV", week:1, date:"2026-09-05", opp:"HAW",               site:"A", pf:21, pa:6 },
  { team:"HAW",  week:1, date:"2026-09-05", opp:"UNLV",              site:"H", pf:6,  pa:21 },
  { team:"NEV",  week:1, date:"2026-09-05", opp:"Western Kentucky",  site:"H", pf:49, pa:14,
    stats:{ yds:486 } },
  { team:"UNM",  week:1, date:"2026-09-05", opp:"Central Michigan",  site:"H", pf:38, pa:7 },
  { team:"SJSU", week:1, date:"2026-09-04", opp:"Eastern Michigan",  site:"A", pf:27, pa:21 },
  { team:"AFA",  week:1, date:"2026-09-05", opp:"Duquesne",          site:"H", pf:34, pa:0 },
  { team:"NDSU", week:1, date:"2026-09-05", opp:"Fordham",           site:"H", pf:38, pa:0 },
  { team:"USU",  week:1, date:"2026-09-05", opp:"Idaho State",       site:"H", pf:17, pa:29 },
  { team:"SDSU", week:1, date:"2026-09-05", opp:"Portland State",    site:"H", pf:53, pa:20 },
  { team:"NMSU", week:1, date:"2026-09-05", opp:"Mercyhurst",        site:"H", pf:51, pa:14 },
  { team:"SAC",  week:1, date:"2026-09-05", opp:"Mississippi Valley State", site:"H", pf:52, pa:0 },

  /* ---- Week 2 ---- */
  { team:"BSU",  week:2, date:"2026-09-12", opp:"Memphis",           site:"H", pf:38, pa:20,
    stats:{ yds:578 } },
  { team:"ORST", week:2, date:"2026-09-12", opp:"Texas Tech",        site:"H", pf:24, pa:35,
    stats:{ yds:472, oppYds:352, thirdPct:27 } },
  { team:"SDSU", week:2, date:"2026-09-12", opp:"UCLA",              site:"A", pf:10, pa:28 },
  { team:"WSU",  week:2, date:"2026-09-12", opp:"Kansas State",      site:"A", pf:7,  pa:34 },
  { team:"USU",  week:2, date:"2026-09-12", opp:"Washington",        site:"A", pf:14, pa:16 },
  { team:"TXST", week:2, date:"2026-09-12", opp:"UTSA",              site:"H", pf:26, pa:31,
    stats:{ yds:481, oppYds:398, to:3, fourthMade:0, fourthAtt:1 } },
  { team:"NDSU", week:2, date:"2026-09-12", opp:"AFA",               site:"A", pf:38, pa:32,
    stats:{ yds:374, oppYds:386, fourthMade:3, fourthAtt:3 } },
  { team:"AFA",  week:2, date:"2026-09-12", opp:"NDSU",              site:"H", pf:32, pa:38,
    stats:{ yds:386, oppYds:374, thirdPct:43, fourthMade:2, fourthAtt:2 } },
  { team:"UNLV", week:2, date:"2026-09-12", opp:"North Texas",       site:"A", pf:6,  pa:44 },
  { team:"CSU",  week:2, date:"2026-09-12", opp:"Southern Utah",     site:"H", pf:58, pa:24,
    stats:{ yds:678, oppYds:442, ypp:9.8, thirdPct:53, oppTo:4, oppExplosive:11, explosive:9 } },
  { team:"FRES", week:2, date:"2026-09-12", opp:"SAC",               site:"H", pf:49, pa:3,
    stats:{ oppYds:180 } },
  { team:"SAC",  week:2, date:"2026-09-12", opp:"FRES",              site:"A", pf:3,  pa:49 },
  { team:"NEV",  week:2, date:"2026-09-12", opp:"Montana State",     site:"H", pf:7,  pa:20 },
  { team:"NIU",  week:2, date:"2026-09-12", opp:"Illinois State",    site:"H", pf:24, pa:28 },
  { team:"SJSU", week:2, date:"2026-09-12", opp:"Cal Poly",          site:"H", pf:30, pa:20 },
  { team:"UTEP", week:2, date:"2026-09-12", opp:"Texas Southern",    site:"H", pf:51, pa:10 },
  { team:"UNM",  week:2, date:"2026-09-12", opp:"Mercyhurst",        site:"H", pf:70, pa:7 },
  { team:"WYO",  week:2, date:"2026-09-12", opp:"Northern Colorado", site:"H", pf:21, pa:13 },
  { team:"HAW",  week:2, date:"2026-09-12", opp:"NMSU",              site:"H", pf:29, pa:19,
    stats:{ yds:420 } },
  { team:"NMSU", week:2, date:"2026-09-12", opp:"HAW",               site:"A", pf:19, pa:29 }
];

/* Next opponent for each team (used in the team cards). */
const NEXT = {
  AFA:  "Bye",
  HAW:  "Bye",
  NEV:  "at Middle Tennessee",
  UNM:  "at No. 10 Oklahoma",
  NDSU: "at Sacramento State",
  NIU:  "at Arizona",
  SJSU: "vs Fresno State",
  UNLV: "Bye",
  UTEP: "at Michigan",
  WYO:  "at Central Michigan",
  BSU:  "vs South Dakota (FCS)",
  CSU:  "vs BYU",
  FRES: "at San José State",
  ORST: "vs Montana (FCS)",
  SDSU: "vs James Madison",
  TXST: "vs North Texas",
  USU:  "at Utah",
  WSU:  "vs Duquesne (FCS)",
  NMSU: "Bye",
  SAC:  "vs North Dakota State"
};

const CURRENT_WEEK = 2;
