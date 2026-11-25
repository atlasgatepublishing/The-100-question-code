#!/usr/bin/env python3
"""Growth-Trend Timing, Unemployment-Trend input (Philosophical
Economics, 2016) — frozen SPEC-FROZEN.md implementation.
Monthly: decide at close of last trading day of month M using UNRATE
for month M-1 (latest released by then; CONSTRUCTED 1-print lag,
HURTS). If UNRATE(M-1) <= its trailing 12MMA -> 100% long SPY (price
component OFF). Else defer to price trend: SPY month-end total-return
close vs its 10-month MA -> long if above, cash if below. Fill next
trading day open (simulate_openfill). Cash 0%. Costs 0.10%/side +
$0.01 sell fee. NATIVE no floor; HOUSE v9 -15% floor chassis.
UNRATE = FRED current vintage (ALFRED vintage retrieval needs a
registered API key; current-vintage caveat FLATTERS slightly, printed).
Placebos: 20 seeds, circular month-shift of the decision-state series.
Crypto: same monthly gate applied to BTC (external US-macro gate, not
coin-native), crypto costs 0.60%/side, BTC buy-hold is the bar.
Simulation only."""
import json, os, sys, random, statistics, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chassis import load_bars, simulate_openfill, buy_hold, period_stats, ROADS, CHAMP, SPYREF

HERE = os.path.dirname(os.path.abspath(__file__))
SPY = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
bars = load_bars(SPY)

# UNRATE monthly: {"YYYY-MM": value}
unrate = {}
with open(os.path.join(HERE, "data", "FRED_UNRATE.csv")) as f:
    for row in csv.reader(f):
        if len(row) == 2 and row[0][0].isdigit() and row[1] not in ("", "."):
            unrate[row[0][:7]] = float(row[1])
months = sorted(unrate)
def ue_trend_down(m_idx):
    """m_idx = index into months of the M-1 print month."""
    if m_idx < 11: return None
    cur = unrate[months[m_idx]]
    ma = sum(unrate[months[m_idx - k]] for k in range(12)) / 12
    return cur <= ma

# month-end SPY closes
me = {}
for b in bars: me[b["d"][:7]] = b["c"]
me_months = sorted(me)
def price_long(mkey):
    i = me_months.index(mkey)
    if i < 9: return None
    ma = sum(me[me_months[i - k]] for k in range(10)) / 10
    return me[mkey] > ma

def build_state(shift=0):
    """Daily desired-state array aligned to bars. Decision at last
    trading day of month M uses UNRATE print for month M-1."""
    # monthly decisions: monthkey -> state
    dec = {}
    for mi, mk in enumerate(me_months):
        y, m = int(mk[:4]), int(mk[5:7])
        pm = f"{y-1:04d}-12" if m == 1 else f"{y:04d}-{m-1:02d}"
        if pm not in unrate: continue
        pidx = months.index(pm)
        down = ue_trend_down(pidx)
        if down is None: continue
        if down: dec[mk] = 1
        else:
            pl = price_long(mk)
            if pl is None: continue
            dec[mk] = 1 if pl else 0
    if shift:
        keys = sorted(dec); vals = [dec[k] for k in keys]
        vals = vals[shift:] + vals[:shift]
        dec = dict(zip(keys, vals))
    st = [0] * len(bars); cur = 0
    lastday = {}
    for i, b in enumerate(bars): lastday[b["d"][:7]] = i
    for i, b in enumerate(bars):
        mk = b["d"][:7]
        if lastday.get(mk) == i and mk in dec: cur = dec[mk]
        st[i] = cur
    return st

def main():
    out = {"family": "hunt-gtt-unemployment", "vehicle": "SPY",
           "signal": "UNRATE (FRED current vintage) vs 12MMA; else SPY vs 10MMA",
           "roads": {}}
    st = build_state()
    for road, (s, e) in ROADS.items():
        ent = {}
        for form in ("native", "house"):
            r = simulate_openfill(bars, st, s, e, form)
            ent[form] = {k: v for k, v in r.items() if k != "curve"}
            ent[form]["period_stats_monthly"] = period_stats(r["curve"], "M")
            if form == "native": ent["curve_native"] = r["curve"]
        ent["spy_buy_hold"] = buy_hold(bars, s, e)
        ent["spy_reference_program"] = SPYREF[road]; ent["champion_vm"] = CHAMP[road]
        out["roads"][road] = ent
        print(road, "native", ent["native"]["final"], "house", ent["house"]["final"], "bh", ent["spy_buy_hold"])
    # placebos: circular month shifts
    out["placebos"] = {}
    for road in ("LONG", "VAL"):
        s, e = ROADS[road]; finals = []
        for seed in range(1, 21):
            rng = random.Random(seed); sh = rng.randint(1, 60)
            pst = build_state(shift=sh)
            finals.append(simulate_openfill(bars, pst, s, e, "native")["final"])
        sysf = out["roads"][road]["native"]["final"]
        out["placebos"][road] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                 "system_native_final": sysf,
                                 "beats": sum(1 for f in finals if sysf > f)}
        print("placebo", road, out["placebos"][road])
    # crypto gate on BTC
    sys.path.insert(0, HERE)
    from crypto_chassis import simulate as csim, buy_hold as cbh, period_stats as cps
    raw = json.load(open(os.path.expanduser(
        "~/workspace/stock-app/backtests/v12-completions/crypto-onchain/data/cm_btc.json")))
    btc = [{"d": r["time"][:10], "c": float(r["PriceUSD"])} for r in raw if r.get("PriceUSD")]
    btc.sort(key=lambda x: x["d"])
    # monthly gate state mapped to btc days: use SPY decision months
    dec_state = {}
    cur = 0
    # rebuild decisions dict quickly from st on SPY bars
    lastday = {}
    for i, b in enumerate(bars): lastday[b["d"][:7]] = i
    for i, b in enumerate(bars):
        if lastday[b["d"][:7]] == i: dec_state[b["d"][:7]] = st[i]
    bst = []
    cur = 0
    for d in btc:
        mk = d["d"][:7]
        # gate decided at end of month mk applies from next month; approximate:
        # use decision of previous month once known
        y, m = int(mk[:4]), int(mk[5:7])
        pm = f"{y-1:04d}-12" if m == 1 else f"{y:04d}-{m-1:02d}"
        if pm in dec_state: cur = dec_state[pm]
        bst.append(cur)
    out["crypto_btc_gate"] = {}
    for road, (s, e) in ROADS.items():
        ent = {}
        for form in ("native", "house"):
            r = csim(btc, bst, s, e, form)
            if r is None: continue
            ent[form] = {k: v for k, v in r.items() if k != "curve"}
            ent[form]["period_stats_monthly"] = cps(r["curve"], "M")
            if form == "native": ent["curve_native"] = r["curve"]
        ent["btc_buy_hold_bar"] = cbh(btc, s, e)
        out["crypto_btc_gate"][road] = ent
        print("BTC gate", road, ent.get("native", {}).get("final"), "bar", ent["btc_buy_hold_bar"])
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
