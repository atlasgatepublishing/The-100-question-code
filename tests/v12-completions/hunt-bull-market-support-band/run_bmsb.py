#!/usr/bin/env python3
"""Bull Market Support Band (Cowen) — SPEC-FROZEN exact (CONSTRUCTED position rule).
Band = between 20-week SMA and 21-week EMA of weekly closes (UTC weeks ending Sunday).
BMSB-REGIME: long while weekly close >= band lower edge; exit on first weekly close below;
re-enter on first weekly close back >= lower edge. Position change applied from the Monday
daily close (named execution convention in spec). CoinMetrics PriceUSD. 0.60%/side.
NATIVE no floor; V9 -15% plain floor on daily closes. BTC + ETH only.
Placebos: 20-seed exposure-matched random weekly timing + SMA20-only and EMA21-only controls.
NOTE: as run, common.py and the CoinMetrics cache lived in the ephemeral /tmp/hunt1
(wiped after the run); common.py is saved beside this script."""
import json, os, random, sys
sys.path.insert(0, "/tmp/hunt1")
from common import *

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-bull-market-support-band")

def weekly_sundays(bars):
    sun = {}
    for b in bars:
        if date.fromisoformat(b["d"]).weekday() == 6: sun[b["d"]] = b["c"]
    return sorted(sun.items())

def run_asset(asset):
    bars = load_cm(asset)
    wk = weekly_sundays(bars); wdates = [d for d, _ in wk]; wcloses = [c for _, c in wk]
    sma20 = sma_series(wcloses, 20); ema21 = ema_series(wcloses, 21)
    def regime_states(kind):
        st = []
        for i in range(len(wk)):
            if sma20[i] is None: st.append(0); continue
            lo = min(sma20[i], ema21[i])
            if kind == "band": st.append(1 if wcloses[i] >= lo else 0)
            elif kind == "sma": st.append(1 if wcloses[i] >= sma20[i] else 0)
            elif kind == "ema": st.append(1 if wcloses[i] >= ema21[i] else 0)
        return st
    def daily_states(wstates):
        st = []; wi = -1
        for b in bars:
            while wi + 1 < len(wdates) and wdates[wi+1] < b["d"]: wi += 1
            st.append(wstates[wi] if wi >= 0 else 0)
        return st
    windows = {"FULL": (None, "2026-11-20"), "DESIGN": (None, "2022-12-31"), "VALIDATION": ("2023-01-01", "2026-11-20")}
    res = {}
    for kind in ["band", "sma", "ema"]:
        dst = daily_states(regime_states(kind))
        res[kind] = {}
        for wname, (s, e) in windows.items():
            idx = [i for i, b in enumerate(bars) if (s is None or b["d"] >= s) and b["d"] <= e]
            wb = [bars[i] for i in idx]; st = [dst[i] for i in idx]
            nat = sim_close_exec(wb, st); hou = sim_close_exec(wb, st, house=True)
            res[kind][wname] = {"native": nat, "house_v9": hou, "buyhold": round(buyhold_close(wb), 2),
                                "periods_monthly": period_stats(nat["curve"], "monthly"),
                                "periods_weekly": period_stats(nat["curve"], "daily")}
    wst = regime_states("band")
    pls = {}
    for wname in ["FULL", "VALIDATION"]:
        s, e = windows[wname]
        idxw = [i for i, d in enumerate(wdates) if (s is None or d >= s) and d <= e]
        expo = sum(wst[i] for i in idxw) / max(1, len(idxw))
        finals = []
        for sd in range(1, 21):
            rng = random.Random(sd)
            pw = [1 if rng.random() < expo else 0 for _ in range(len(wk))]
            dst = daily_states(pw)
            idx = [i for i, b in enumerate(bars) if (s is None or b["d"] >= s) and b["d"] <= e]
            finals.append(sim_close_exec([bars[i] for i in idx], [dst[i] for i in idx])["final"])
        pls[wname] = {"finals": [round(f, 2) for f in finals], "exposure": round(expo, 3),
                      "beaten": sum(1 for f in finals if res["band"][wname]["native"]["final"] > f)}
    res["placebos"] = pls
    return res

out = {"family": "hunt-bull-market-support-band", "holdings_grid": "NOT-APPLICABLE — single-asset regime gauge, no selection",
       "BTC": run_asset("btc"), "ETH": run_asset("eth")}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
for a in ["BTC", "ETH"]:
    print(a, {w: (out[a]["band"][w]["native"]["final"], out[a]["band"][w]["buyhold"]) for w in ["FULL", "DESIGN", "VALIDATION"]})
