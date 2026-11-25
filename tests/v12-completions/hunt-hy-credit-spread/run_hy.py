#!/usr/bin/env python3
"""HY Credit-Spread Timing (Stockopedia, Edmund, Mar 2025) — frozen
SPEC-FROZEN.md implementation. Monthly: month-end ICE BofA US HY OAS
(FRED BAMLH0A0HYM2). Invested whenever OAS <= 5%. SELL (CONSTRUCTED
'rising': month-end OAS strictly above prior month-end) when OAS >
5.00% AND rising, fill next open. RE-ENTER (CONSTRUCTED 'reliably
falling'): first month-end with two consecutive month-end falls AND
latest below the sell-decision reading; OR immediately when OAS falls
to <= 5.00% (published rule dominates). Vehicle SPY, cash 0%, program
costs. NATIVE no floor; HOUSE v9 floor chassis.
DATA FENCE: the keyless FRED endpoints serve only the trailing ~3
years of this ICE-licensed series (verified 2026-11-22, see
HUNT-LOG.md) -> the only honest road is the available window
2023-11-21 -> 2026-11-20 (inside VAL). LONG/DECADE/CONT are named
GRID GAPS with the blocker in RESULTS.md. Placebos: 20 seeds,
threshold ~ U[3.5, 6.5] with the same constructed rising/falling
definitions. Crypto: same gate on BTC over the same window.
Simulation only."""
import json, os, sys, random, statistics, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chassis import load_bars, simulate_openfill, buy_hold, period_stats

HERE = os.path.dirname(os.path.abspath(__file__))
SPY = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
bars = load_bars(SPY)

oas = {}
with open(os.path.join(HERE, "data", "FRED_BAMLH0A0HYM2.csv")) as f:
    for row in csv.reader(f):
        if len(row) == 2 and row[0][0].isdigit() and row[1] not in ("", "."):
            oas[row[0]] = float(row[1])
# month-end OAS (last print of month)
me_oas = {}
for d in sorted(oas): me_oas[d[:7]] = oas[d]
WIN = ("2023-11-21", "2026-11-20")

def build_state(threshold=5.0):
    months = sorted(me_oas)
    dec = {}; state = 1; sell_ref = None; falls = 0; prev = None
    for mk in months:
        v = me_oas[mk]
        if state == 1:
            if v > threshold and prev is not None and v > prev:
                state = 0; sell_ref = v; falls = 0
        else:
            if v <= threshold:
                state = 1; sell_ref = None
            else:
                falls = falls + 1 if (prev is not None and v < prev) else 0
                if falls >= 2 and sell_ref is not None and v < sell_ref:
                    state = 1; sell_ref = None
        dec[mk] = state; prev = v
    st = [0] * len(bars); cur = 1
    lastday = {}
    for i, b in enumerate(bars): lastday[b["d"][:7]] = i
    for i, b in enumerate(bars):
        mk = b["d"][:7]
        if lastday.get(mk) == i and mk in dec: cur = dec[mk]
        st[i] = cur
    return st, dec

def main():
    out = {"family": "hunt-hy-credit-spread", "vehicle": "SPY",
           "data_window": ["2023-11-21", "2026-11-20"],
           "data_fence": "keyless FRED serves only trailing ~3y of ICE BofA OAS; see HUNT-LOG.md",
           "grid_gaps": ["LONG", "DECADE", "CONT roads: pre-2023-11 OAS history requires a registered FRED API key or paid ICE license"]}
    st, dec = build_state()
    out["monthly_decisions"] = dec
    out["oas_range_in_window"] = [min(me_oas.values()), max(me_oas.values())]
    ent = {}
    for form in ("native", "house"):
        r = simulate_openfill(bars, st, *WIN, form)
        ent[form] = {k: v for k, v in r.items() if k != "curve"}
        ent[form]["period_stats_monthly"] = period_stats(r["curve"], "M")
        if form == "native": ent["curve_native"] = r["curve"]
    ent["spy_buy_hold_same_window"] = buy_hold(bars, *WIN)
    out["window_run"] = ent
    print("HY window native", ent["native"]["final"], "house", ent["house"]["final"],
          "bh", ent["spy_buy_hold_same_window"], "oas range", out["oas_range_in_window"])
    finals = []
    for seed in range(1, 21):
        rng = random.Random(seed); th = rng.uniform(3.5, 6.5)
        pst, _ = build_state(th)
        finals.append(simulate_openfill(bars, pst, *WIN, "native")["final"])
    out["placebos_threshold"] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                 "system_native_final": ent["native"]["final"]}
    print("placebos", out["placebos_threshold"])
    # BTC gate, same window
    from crypto_chassis import simulate as csim, buy_hold as cbh, period_stats as cps
    raw = json.load(open(os.path.join(HERE, "data", "cm_btc_hash.json")))
    btc = [{"d": r["time"][:10], "c": float(r["PriceUSD"])} for r in raw if r.get("PriceUSD")]
    btc.sort(key=lambda x: x["d"])
    bst = []; cur = 1
    for d in btc:
        y, m = int(d["d"][:4]), int(d["d"][5:7])
        pm = f"{y-1:04d}-12" if m == 1 else f"{y:04d}-{m-1:02d}"
        if pm in dec: cur = dec[pm]
        bst.append(cur)
    cent = {}
    for form in ("native", "house"):
        r = csim(btc, bst, *WIN, form)
        cent[form] = {k: v for k, v in r.items() if k != "curve"}
        cent[form]["period_stats_monthly"] = cps(r["curve"], "M")
        if form == "native": cent["curve_native"] = r["curve"]
    cent["btc_buy_hold_bar"] = cbh(btc, *WIN)
    out["crypto_btc_gate"] = cent
    print("BTC gate native", cent["native"]["final"], "bar", cent["btc_buy_hold_bar"])
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
