#!/usr/bin/env python3
"""2-Year MA Multiplier (Bitcoin Investor Tool, Philip Swift 2017) — SPEC-FROZEN exact.
SMA730 and 5x SMA730 on CoinMetrics PriceUSD closes. MA2Y-ACCUM: enter on close < SMA730,
exit on close >= 5x SMA730, hold state between, start cash, 730d warmup in cash.
MA2Y-ZONE: long unless close >= 5x SMA730. Close-exec chassis, 0.60%/side.
NATIVE no floor; V9 plain -15% floor (daily close). BTC primary; ETH EXTENSION.
NOTE: as run, common.py and the CoinMetrics cache (cm_btc.json/cm_eth.json, fetched
from the CoinMetrics community API 2026-11-22) lived in the ephemeral /tmp/hunt1
(wiped after the run); common.py is saved beside this script."""
import json, os, random, sys
sys.path.insert(0, "/tmp/hunt1")
from common import *

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-2yr-ma-multiplier")

def run_asset(asset):
    bars = load_cm(asset); closes = [b["c"] for b in bars]
    sma = sma_series(closes, 730)
    def states_for(bm, sm, mode):
        st = []; pos = 0 if mode == "ACCUM" else 1
        for i in range(len(closes)):
            if sma[i] is None: st.append(0); continue
            if mode == "ACCUM":
                if closes[i] < bm * sma[i]: pos = 1
                elif closes[i] >= sm * sma[i]: pos = 0
            else:
                pos = 0 if closes[i] >= sm * sma[i] else 1
            st.append(pos)
        return st
    first = next(i for i, v in enumerate(sma) if v is not None)
    windows = {"FULL": (bars[first]["d"], "2026-11-20"), "DESIGN": (bars[first]["d"], "2022-12-31"),
               "VALIDATION": ("2023-01-01", "2026-11-20")}
    res = {}
    for mode in ["ACCUM", "ZONE"]:
        res[mode] = {}
        st_full = states_for(1.0, 5.0, mode)
        for wname, (s, e) in windows.items():
            idx = [i for i, b in enumerate(bars) if s <= b["d"] <= e]
            wb = [bars[i] for i in idx]; st = [st_full[i] for i in idx]
            nat = sim_close_exec(wb, st); hou = sim_close_exec(wb, st, house=True)
            res[mode][wname] = {"native": nat, "house_v9": hou, "buyhold": round(buyhold_close(wb), 2),
                                "periods_monthly": period_stats(nat["curve"], "monthly")}
        pls = {}
        for wname in ["FULL", "VALIDATION"]:
            s, e = windows[wname]
            idx = [i for i, b in enumerate(bars) if s <= b["d"] <= e]
            wb = [bars[i] for i in idx]
            finals = []
            for sd in range(1, 21):
                rng = random.Random(sd)
                if mode == "ACCUM":
                    pst = states_for(rng.uniform(0.8, 1.2), rng.uniform(3.5, 6.5), mode)
                else:
                    mult = 5.0 * rng.choice([0.7, 0.85, 1.15, 1.3])
                    pst = states_for(1.0, mult, mode)
                finals.append(sim_close_exec(wb, [pst[i] for i in idx])["final"])
            pls[wname] = {"finals": [round(f, 2) for f in finals],
                          "beaten": sum(1 for f in finals if res[mode][wname]["native"]["final"] > f)}
        res[mode]["placebos"] = pls
    return res

out = {"family": "hunt-2yr-ma-multiplier", "holdings_grid": "NOT-APPLICABLE — single-asset gauge timer, no selection",
       "BTC": run_asset("btc"), "ETH_EXTENSION": run_asset("eth")}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
for mode in ["ACCUM", "ZONE"]:
    print("BTC", mode, {w: (out["BTC"][mode][w]["native"]["final"], out["BTC"][mode][w]["buyhold"]) for w in ["FULL", "DESIGN", "VALIDATION"]})
