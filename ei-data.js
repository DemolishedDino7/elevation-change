/* ===================================================================
   ELEVATION INDEX — DATA
   Team list and the weekly "To improve" notes. Everything else
   (games, stats, opponent strength) is built automatically into
   ei-auto.js by The Bot.
   =================================================================== */

const TEAMS = [
  /* id, name, conference, color, seed national rank (preseason estimate), logo (hosted in logos/) */
  ["AFA",  "Air Force",          "Mountain West", "#003087", 82,  "logos/AFA.png"],
  ["HAW",  "Hawai'i",            "Mountain West", "#024731", 100, "logos/HAW.png"],
  ["NEV",  "Nevada",             "Mountain West", "#003366", 96,  "logos/NEV.png"],
  ["UNM",  "New Mexico",         "Mountain West", "#BA0C2F", 70,  "logos/UNM.png"],
  ["NDSU", "North Dakota State", "Mountain West", "#009A44", 78,  "logos/NDSU.png"],
  ["NIU",  "Northern Illinois",  "Mountain West", "#C8102E", 98,  "logos/NIU.png"],
  ["SJSU", "San José State",     "Mountain West", "#0055A2", 104, "logos/SJSU.png"],
  ["UNLV", "UNLV",               "Mountain West", "#CF0A2C", 60,  "logos/UNLV.png"],
  ["UTEP", "UTEP",               "Mountain West", "#FF8200", 118, "logos/UTEP.png"],
  ["WYO",  "Wyoming",            "Mountain West", "#492F24", 102, "logos/WYO.png"],
  ["BSU",  "Boise State",        "Pac-12",        "#0033A0", 30,  "logos/BSU.png"],
  ["CSU",  "Colorado State",     "Pac-12",        "#1E4D2B", 84,  "logos/CSU.png"],
  ["FRES", "Fresno State",       "Pac-12",        "#DB0032", 66,  "logos/FRES.png"],
  ["ORST", "Oregon State",       "Pac-12",        "#DC4405", 90,  "logos/ORST.png"],
  ["SDSU", "San Diego State",    "Pac-12",        "#A6192E", 72,  "logos/SDSU.png"],
  ["TXST", "Texas State",        "Pac-12",        "#501214", 68,  "logos/TXST.png"],
  ["USU",  "Utah State",         "Pac-12",        "#0F2439", 88,  "logos/USU.png"],
  ["WSU",  "Washington State",   "Pac-12",        "#981E32", 76,  "logos/WSU.png"],
  ["NMSU", "New Mexico State",   "Independent",   "#891216", 120, "logos/NMSU.png"],
  ["SAC",  "Sacramento State",   "MAC",           "#043927", 126, "logos/SAC.png"]
];

/* Opponents, games, box-score stats, next games and the current week are
   generated automatically into ei-auto.js by The Bot (model/run.py).
   Nothing below needs a weekly update except IMPROVE. */

/* The weekly "To improve" notes now live in ei-west.js. */

