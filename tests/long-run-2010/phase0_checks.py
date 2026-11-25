#!/usr/bin/env python3
"""
PHASE 0 — integrity gates for the long-run test. Every engine must
reproduce its published finals through the plumbing used here BEFORE
any long-run number is taken. Any failure stops the test.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lr_common as C  # noqa: E402
import lr_basket as B  # noqa: E402

END = C.END
out = {}
fails = []


def check(name, got, expect):
    ok = round(got, 2) == expect
    out[name] = {"got": round(got, 2), "expected": expect, "match": ok}
    print(f"{name}: ${got:,.2f} expected ${expect:,.2f} MATCH={ok}",
          flush=True)
    if not ok:
        fails.append(name)


# ---------------------------------------------------------- 1. champion
print("=== champion (original caches) ===", flush=True)
champ = C.champ
ciks = champ.get_ciks()
eq, so, bars = {}, {}, {}
for t in champ.UNIVERSE:
    cik = 34088 if t == "XOM" else ciks[t][0]
    facts = champ.get_companyfacts(cik)
    eq[t], so[t] = C.equity_chain(facts), C.shares_chain(facts)
for t in champ.UNIVERSE + ["SPY"]:
    bars[t] = champ.get_prices(t)
pb = champ.PriceBook(bars)
r = champ.run_pot(pb, eq, so, "2019-01-02", END, 100.0, 85.0, [],
                  label="P0 FULL", quiet=True)
check("champion_full", r["final"], 544.47)
r = champ.run_pot(pb, eq, so, "2023-01-03", END, 100.0, 85.0, [],
                  label="P0 VAL", quiet=True)
check("champion_validation", r["final"], 288.05)
fpb = C.FastPriceBook(bars)
r2 = champ.run_pot(fpb, eq, so, "2019-01-02", END, 100.0, 85.0, [],
                   label="P0 FULL FAST", quiet=True)
out["fastbook_equivalence"] = {"final": round(r2["final"], 2),
                               "identical": abs(r2["final"] - 544.47) < 0.005}
print(f"fastbook FULL: ${r2['final']:,.2f} identical="
      f"{out['fastbook_equivalence']['identical']}", flush=True)
if not out["fastbook_equivalence"]["identical"]:
    fails.append("fastbook")

# ---------------------------------------------------------- 2. basket
print("=== momentum basket (v9 simulate on long-hold price pulls) ===",
      flush=True)
POND2016 = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
B.UNIVERSE = POND2016
bbars = {t: C.bars_raw(C.yahoo_payload(t)) for t in POND2016 + ["SPY"]}
mkt = B.Market(bbars)
res = B.simulate(mkt, "2016-11-21", END, 100, "ranked")
check("basket_full", res.final, 439.45)
out["basket_full_halts"] = res.halts
res = B.simulate(mkt, "2023-01-01", END, 100, "ranked")
check("basket_validation", res.final, 208.27)
out["basket_validation_halts"] = res.halts

# ---------------------------------------------------------- 3. lazy prices
print("=== lazy prices (original module + cached similarities) ===",
      flush=True)
lazy = C.load_module("lazy_lr", os.path.join(
    C.V7, "gap-a5-lazy-prices", "lazy-prices.py"))
with open(os.path.join(C.V7, "gap-a5-lazy-prices", "data",
                       "similarities.json")) as f:
    sims = json.load(f)["signals"]
lbars = {t: lazy.get_prices(t) for t in lazy.UNIVERSE + ["SPY"]}
lpb = lazy.PriceBook(lbars)
r = lazy.run_pot(lpb, sims, "2019-01-02", END, label="P0 FULL")
check("lazy_full", r["final"], 504.34)
r = lazy.run_pot(lpb, sims, "2023-01-03", END, label="P0 VAL")
check("lazy_validation", r["final"], 324.12)

# ---------------------------------------------------------- 4. N-F3
print("=== N-F3 (original module, champion caches) ===", flush=True)
nf3 = C.load_module("nf3_lr", os.path.join(
    C.V8, "novel-f3-paying-in-stock", "novel-f3-paying-in-stock.py"))
nchamp = nf3.champ
nciks = nchamp.get_ciks()
nfacts = {}
for t in nf3.UNIVERSE:
    cik = 34088 if t == "XOM" else nciks[t][0]
    nfacts[t] = nchamp.get_companyfacts(cik)
nbars = {t: nchamp.get_prices(t) for t in nf3.UNIVERSE + ["SPY"]}
npb = nchamp.PriceBook(nbars)
stats = {"direct": 0, "derived": 0}
r = nf3.run_pot(npb, nfacts, "2019-01-02", END, 100.0, 85.0,
                label="P0 FULL", stats=stats)
check("nf3_full", r["final"], 505.43)
r = nf3.run_pot(npb, nfacts, "2023-01-03", END, 100.0, 85.0,
                label="P0 VAL", stats={"direct": 0, "derived": 0})
check("nf3_validation", r["final"], 289.53)

# ---------------------------------------------------------- 5. switch B
print("=== switch B (original module, champion caches) ===", flush=True)
sw = C.load_module("switch_lr", os.path.join(
    C.V8, "switch-champion-to-blend", "switch-champion-to-blend.py"))
schamp = sw.champ
snf3 = sw.nf3
sciks = schamp.get_ciks()
sfacts, seq, sso = {}, {}, {}
for t in sw.UNIVERSE:
    cik = 34088 if t == "XOM" else sciks[t][0]
    facts = schamp.get_companyfacts(cik)
    sfacts[t] = facts
    seq[t] = C.equity_chain(facts)
    sso[t] = C.shares_chain(facts)
sbars = {t: schamp.get_prices(t) for t in sw.UNIVERSE + ["SPY"]}
spb = schamp.PriceBook(sbars)
scorer = sw.Scorer(spb, seq, sso, sfacts)
r = sw.run_combo(spb, scorer, "2019-01-02", END, 100.0, 85.0,
                 label="P0 BLEND")
check("switch_blend_full", r["final"], 532.39)
r = sw.run_switch(spb, scorer, "2019-01-02", END, "2023-01-01",
                  label="P0 SWITCH")
check("switch_full", r["final"], 549.43)

out["fails"] = fails
with open(os.path.join(HERE, "phase0_results.json"), "w") as f:
    json.dump(out, f, indent=1, default=str)
print("PHASE 0:", "ALL PASS" if not fails else f"FAILURES: {fails}",
      flush=True)
sys.exit(1 if fails else 0)
