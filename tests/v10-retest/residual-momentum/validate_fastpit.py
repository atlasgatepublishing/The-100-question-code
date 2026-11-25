#!/usr/bin/env python3
"""Prove fastpit.fast_pit_value == engine E.pit_value on both data sets
the v10 run touches: (a) the sweep book's lr_common EDGAR chains for all
30 UNIVERSE names, (b) the integrity book's engine-native chains.
Dates: every trading day of 2016-11-21..2026-11-20 for a 6-name sample,
plus the first trading day of every month for all names, plus every
quarterly selection date. Any mismatch fails the run."""
import importlib.util
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
sys.path.insert(0, os.path.join(BT, "long-run-2010"))
import lr_common as C  # noqa: E402
from fastpit import fast_pit_value  # noqa: E402


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


M = load_mod("engine_v10", os.path.join(HERE, "engine_v10.py"))
E = M.E
orig = E.pit_value

# ---- sweep-book chains (lr_common) ----
bars = {t: C.bars_adj(C.yahoo_payload(t)) for t in M.UNIVERSE + ["SPY"]}
pb = M.FastBook(bars)
all_days = [d for d in pb.dates if "2016-11-21" <= d <= "2026-11-20"]
monthly, seen = [], set()
for d in all_days:
    if d[:7] not in seen:
        seen.add(d[:7])
        monthly.append(d)
rng = random.Random(7)
sample_days = sorted(rng.sample(all_days, 300))
test_dates_all = sorted(set(monthly) | set(sample_days))

chains = {}
for t in M.UNIVERSE:
    facts = C.load_facts(C.cik_for(t))
    chains[(t, "eq")] = C.equity_chain(facts)
    chains[(t, "so")] = C.shares_chain(facts)

bad = 0
n = 0
for (t, kind), rows in chains.items():
    dates = all_days if t in ("AAPL", "XOM", "GE", "META", "V", "BRK-B") \
        else test_dates_all
    for d in dates:
        a = orig(rows, d)
        b = fast_pit_value(rows, d)
        n += 1
        if a != b:
            bad += 1
            print("MISMATCH sweep", t, kind, d, a, b, flush=True)
print(f"sweep chains: {n} comparisons, {bad} mismatches", flush=True)

# ---- integrity-book chains (engine-native build_inputs) ----
pb2, eq2, so2 = M.build_inputs()
bad2 = 0
n2 = 0
for t in M.UNIVERSE:
    for rows in (eq2[t], so2[t]):
        for d in test_dates_all:
            a = orig(rows, d)
            b = fast_pit_value(rows, d)
            n2 += 1
            if a != b:
                bad2 += 1
                print("MISMATCH integ", t, d, a, b, flush=True)
print(f"integrity chains: {n2} comparisons, {bad2} mismatches", flush=True)
print("FASTPIT", "PASS" if (bad == 0 and bad2 == 0) else "FAIL", flush=True)
