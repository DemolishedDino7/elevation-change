"""Temporary: which recruiting sources answer from GitHub Actions."""
import urllib.request
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
URLS = [
  "https://247sports.com/season/2025-basketball/compositerecruitrankings/",
  "https://247sports.com/season/2015-basketball/compositerecruitrankings/?InstitutionGroup=HighSchool",
  "https://www.on3.com/rivals/rankings/player/basketball/2025/",
  "https://www.espn.com/college-sports/basketball/recruiting/rankings/_/class/2025",
  "https://en.wikipedia.org/w/api.php?action=parse&page=2025_McDonald%27s_All-American_Boys_Game&prop=wikitext&format=json",
  "https://en.wikipedia.org/w/api.php?action=parse&page=Recruiting_Services_Consensus_Index&prop=wikitext&format=json",
  "https://www.rscihoops.com/2025-rsci-final",
  "https://barttorvik.com/trank.php",
  "https://www.sports-reference.com/cbb/seasons/men/2025-school-stats.html",
]
for u in URLS:
    try:
        req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "text/html,application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            b = r.read()
        print("OK ", len(b), u, b[:80])
    except Exception as e:
        print("ERR", e, u)
