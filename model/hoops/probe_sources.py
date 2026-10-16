"""Temporary: which On3 ranking pages have players for which years."""
import gzip, json, re, urllib.request
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
def get(u):
    req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf8", "replace")
def count(u):
    try:
        h = get(u)
        d = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S).group(1))
        pdd = d["props"]["pageProps"].get("playerData") or {}
        return (pdd.get("pagination") or {}).get("count"), len(pdd.get("list") or [])
    except Exception as e:
        return str(e)[:60]
pats = ["https://www.on3.com/rivals/rankings/player/basketball/{y}/",
        "https://www.on3.com/rivals/rankings/industry-player/basketball/{y}/",
        "https://www.on3.com/db/rankings/industry-player/basketball/{y}/",
        "https://www.on3.com/db/rankings/player/basketball/{y}/",
        "https://www.on3.com/rivals/rankings/consensus-player/basketball/{y}/"]
for y in (2012, 2016, 2019, 2020, 2022, 2026):
    print(y, [count(p.format(y=y)) for p in pats])
