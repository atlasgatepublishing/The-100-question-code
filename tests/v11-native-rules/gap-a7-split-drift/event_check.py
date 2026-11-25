"""Native-form check on the only verified exactly-2-for-1 event in the broadened
verified census (KO, announced 2012-04-25, from v10-retest/gap-a7-split-drift, read-only).
Ikenberry-Rankine-Stice measurement: buy after announcement, buy-and-hold 1yr and 3yr,
excess vs market (SPY). Prices: v10 pxlong cache (Yahoo adjusted), read-only.
Costs 0.10%/side on the pot variant."""
import json, os
from datetime import date

SRC = "/home/hatch/workspace/stock-app/backtests/v10-retest/gap-a7-split-drift/cache"
def load(t):
    d = json.load(open(os.path.join(SRC, f"pxlong_{t}.json")))["chart"]["result"][0]
    out = {}
    for i, x in enumerate(d["timestamp"]):
        a = d["indicators"]["adjclose"][0]["adjclose"][i]
        if a: out[date.fromtimestamp(x).isoformat()] = a
    return out

ko, spy = load("KO"), load("SPY")
cal = sorted(spy.keys())
ann = "2012-04-25"
entry = next(d for d in cal if d > ann)
res = {"event": {"ticker": "KO", "ratio": "2-for-1", "announced": ann, "entry": entry}}
for yrs, label in ((1, "1yr"), (3, "3yr")):
    target = cal[min(len(cal) - 1, cal.index(entry) + 252 * yrs)]
    kr = ko[target] / ko[entry] - 1; sr = spy[target] / spy[entry] - 1
    res[label] = {"exit": target, "KO_return_pct": round(kr * 100, 2),
                  "SPY_return_pct": round(sr * 100, 2), "excess_pp": round((kr - sr) * 100, 2),
                  "standalone_$100_net_of_costs": round(100 * (1 - 0.001) * (1 + kr) * (1 - 0.001), 2)}
json.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json"), "w"), indent=1)
print(res)
