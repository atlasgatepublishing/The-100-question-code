#!/usr/bin/env python3
"""Transit driver: exec file-writes are blocked in this environment, so this
prints compact per-coin JSON lines to stdout for assembly via file tools."""
import json, sys
import run_all as R

lo, hi = int(sys.argv[1]), int(sys.argv[2])
reg = R.load_registry_oc()
cal = [r["d"] for r in reg[1]["rows"]]
keys = sorted(reg.keys())
sel = [k for k in keys[lo:hi] if k != 1 or lo == 0]
sub = {1: reg[1]}
for k in sel: sub[k] = reg[k]
out = R.run_candle(sub, cal)
for cid in sel:
    c = out["coins"][str(cid)]
    w = {}
    for wn, r in c["windows"].items():
        if "native" not in r:
            w[wn] = {"status": r["status"], "bars": r["bars_in_window"]}; continue
        w[wn] = {"bh": r["coin_buyhold"],
                 "nat": [r["native"]["final"], r["native"]["max_dd_pct"], r["native"]["costs"],
                         r["native"]["buys"], r["native"]["win_rate_pct"]],
                 "v9": [r["v9"]["final"], r["v9"]["max_dd_pct"], r["v9"]["halts"]],
                 "plac": r["placebo_beaten"], "plac_n": len(r["placebo_finals"]),
                 "ps": r["period_stats_monthly_native"]}
        if wn == "FULL" and cid == 1:
            w[wn]["curve"] = [v for _, v in r["monthly_curve_native"]]
    print("COIN " + json.dumps({"cid": cid, "sym": c["symbol"], "src": c.get("source"), "w": w}))
print("BTCBH " + json.dumps(out["btc_buyhold"]))
