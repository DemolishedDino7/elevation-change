"""Temporary: save sample recruiting pages from GitHub Actions for inspection."""
import gzip, urllib.request
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
def get(u, accept="*/*"):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()
for name, u in [("on3_2025", "https://www.on3.com/rivals/rankings/player/basketball/2025/"),
                ("on3_2025_p2", "https://www.on3.com/rivals/rankings/player/basketball/2025/?page=2"),
                ("on3_2014", "https://www.on3.com/rivals/rankings/player/basketball/2014/"),
                ("247_2025", "https://247sports.com/season/2025-basketball/compositerecruitrankings/")]:
    try:
        b = get(u)
        open(f"model/hoops/torvik/{name}.html.gz", "wb").write(gzip.compress(b))
        print("OK", name, len(b))
    except Exception as e:
        print("ERR", name, e)
