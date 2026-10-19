"""Temporary probe (removed after use): our 23 teams' official schedule pages."""
import gzip, json, urllib.request
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
SITES = {"BSU": "broncosports.com", "CSU": "csurams.com", "FRES": "gobulldogs.com", "GONZ": "gozags.com", "ORST": "osubeavers.com",
         "SDSU": "goaztecs.com", "TXST": "txst.com", "USU": "utahstateaggies.com", "WSU": "wsucougars.com", "AFA": "goairforcefalcons.com",
         "GCU": "gculopes.com", "HAW": "hawaiiathletics.com", "NEV": "nevadawolfpack.com", "UNM": "golobos.com", "SJSU": "sjsuspartans.com",
         "UCD": "ucdavisaggies.com", "UNLV": "unlvrebels.com", "UTEP": "utepminers.com", "WYO": "gowyo.com", "NDSU": "gobison.com",
         "NIU": "niuhuskies.com", "NMSU": "nmstatesports.com", "SAC": "hornetsports.com"}
PATHS = ["/sports/mens-basketball/schedule", "/sports/mens-basketball/schedule/2026-27", "/sports/mbball/schedule", "/sports/m-baskbl/sched/"]
out = {}
for sid, dom in SITES.items():
    out[sid] = []
    for p in PATHS:
        u = "https://" + dom + p
        try:
            req = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "text/html"})
            with urllib.request.urlopen(req, timeout=40) as r:
                h = r.read().decode("utf8", "replace")
            out[sid].append({"url": u, "len": len(h), "exh": h.lower().count("exhibition")})
            open(f"model/hoops/probe/sch_{sid}.html.gz", "wb").write(gzip.compress(h.encode()))
            break
        except Exception as e:
            out[sid].append({"url": u, "err": repr(e)[:100]})
json.dump(out, open("model/hoops/probe/out.json", "w"), indent=1)
