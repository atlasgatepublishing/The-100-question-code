#!/usr/bin/env python3
"""CADENCE GRID — crypto-funding-basis (PAPER RECORD — not a tradable pot).
Second-Chance Protocol slice. Window: the funding archive's honest start
2020-01-01 -> 2026-10-31 (the primary record's FULL window; Binance funding
does not exist before 2020, so a 2016 DECADE start is impossible — stated,
not backfilled). BTCUSDT book, Form B funding-sign gate (CONSTRUCTED:
7-day / 21-event trailing-mean funding > 0), $100 fully-collateralized 1x
book, costs spot 0.50%/side + perp 0.20%/side — all exactly as frozen in
the family's CONSTRUCTION-SPEC / run_carry.py, whose machinery is reused
here (read-only import).
Cadence = gate-evaluation frequency: the gate is re-evaluated only on
cadence dates (first funding event of the period) and held constant
between them. The native form evaluates every 8h settlement — finer than
the grid's daily cell; the native 8h result is credited from the primary
record ($152.99) and the daily cell is the closest grid cell, labeled as
such. Form A (always-on) has no gate and is cadence-invariant by
construction: credited once ($352.05), not re-printed per cell.
Placebos: 20 seeds per cell — the primary record's own design (shuffled
funding series drives the gate, real funding pays), cadence-resampled the
same way.
"""
import importlib.util, json, os, random
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/crypto-funding-basis/scripts/run_carry.py")

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

M = load("carry_engine", BASE)
CADENCES = ["daily","weekly","biweekly","monthly","quarterly","semiannual","annual"]
FREQ = {"daily": "D", "weekly": "W", "biweekly": "2W", "monthly": "M",
        "quarterly": "Q", "semiannual": "2Q", "annual": "A"}
PERIOD = {"daily": "D", "weekly": "W", "biweekly": "2W", "monthly": "M",
          "quarterly": "Q", "semiannual": "2Q", "annual": "Y"}

def cadence_gate(f, gate, cad):
    if cad == "native8h":
        return gate
    periods = f["t"].dt.tz_localize(None).dt.to_period(PERIOD[cad])
    out = np.empty(len(f), dtype=bool)
    cur = gate[0]
    seen = set()
    for i, p in enumerate(periods):
        if p not in seen:
            seen.add(p); cur = gate[i]
        out[i] = cur
    return out

def period_stats_cadence(s, cad):
    m = s.resample(FREQ[cad]).last().dropna()
    vals = np.concatenate([[M.POT], m.values])
    rets = np.diff(vals) / vals[:-1]
    if len(rets) == 0: return {"n_periods": 0}
    win = rets > 0
    longest_loss = cur = 0
    for w in win:
        cur = 0 if w else cur + 1; longest_loss = max(longest_loss, cur)
    peak, since, gap = vals[0], 0, 0
    for v in vals[1:]:
        if v >= peak: peak, since = v, 0
        else: since += 1; gap = max(gap, since)
    return {"n_periods": int(len(rets)), "pct_profitable": round(100*float(win.mean()),1),
            "median_period_pct": round(100*float(np.median(rets)),3),
            "mean_period_pct_secondary": round(100*float(rets.mean()),3),
            "best_period_pct": round(100*float(rets.max()),2),
            "worst_period_pct": round(100*float(rets.min()),2),
            "longest_losing_streak": int(longest_loss),
            "longest_between_new_highs_periods": int(gap)}

def main():
    f = M.load("BTCUSDT")
    start = f["t"].iloc[0]
    trail = f["last_funding_rate"].rolling(21).mean().shift(1)
    gate_native = (trail > 0).fillna(True).values
    rates = f["last_funding_rate"].values.copy()
    pgates = []
    for seed in range(20):
        rng = random.Random(1000 + seed)
        sh = rates.copy(); rng.shuffle(sh)
        tg = pd.Series(sh).rolling(21).mean().shift(1)
        pgates.append((tg > 0).fillna(True).values)
    bh = M.btc_hold(f, start)
    out = {"family": "crypto-funding-basis", "label": "PAPER RECORD — not a tradable pot",
           "window": [str(start.date()), "2026-10-31"],
           "window_note": "Funding archive starts 2020-01-01; DECADE's 2016 start does not exist for this family. This is the primary record's FULL window.",
           "asset": "BTCUSDT", "form": "Form B funding-sign gate (CONSTRUCTED)",
           "native_cadence": "8-hourly (finer than the grid)",
           "native_cadence_credited": {"final": 152.99, "source": "primary results.json BTCUSDT FULL formB_funding_sign_gate_constructed"},
           "formA_always_on_credited": {"final": 352.05, "note": "cadence-invariant (no gate); primary results.json BTCUSDT FULL formA"},
           "btc_buyhold_bar": {"final": bh["final"], "max_dd_pct": bh["max_dd"]},
           "cells": {}, "confirmation": {}}
    for cad in CADENCES:
        g = cadence_gate(f, gate_native, cad)
        r = M.run_book(f, start, gate=g)
        pfin = []
        for pg in pgates:
            pr = M.run_book(f, start, gate=cadence_gate(f, pg, cad))
            pfin.append(round(pr["final"], 2))
        beaten = sum(1 for v in pfin if r["final"] > v)
        curve = [[str(t.date()), round(float(v), 2)] for t, v in r["equity"].resample("D").last().dropna().items()]
        out["cells"][cad] = {"final": round(r["final"], 2),
            "max_dd_pct": round(100 * M.max_dd(r["equity"]), 2),
            "fees": round(r["fees"], 2), "funding_net": round(r["funding_net"], 2),
            "switches": r["switches"], "placebo_beaten": beaten, "placebo_finals": pfin,
            "placebo_median": round(float(np.median(pfin)), 2),
            "curve_daily": curve,
            "period_stats_at_this_cadence": period_stats_cadence(r["equity"], cad)}
        print(f"{cad}: ${r['final']:.2f} DD {out['cells'][cad]['max_dd_pct']}% switches {r['switches']} placebo {beaten}/20", flush=True)
    nat = out["cells"]["daily"]["final"]
    vstart = pd.Timestamp("2023-01-01", tz="UTC")
    for cad in CADENCES:
        if cad != "daily" and out["cells"][cad]["final"] > nat:
            conf = {}
            for cc in (cad, "daily"):
                rr = M.run_book(f, vstart, gate=cadence_gate(f, gate_native, cc))
                conf[cc] = {"final": round(rr["final"], 2), "max_dd_pct": round(100*M.max_dd(rr["equity"]), 2)}
            out["confirmation"][cad] = {"window": ["2023-01-01", "2026-10-31"], "cells": conf,
                "beats_daily_on_second_window": conf[cad]["final"] > conf["daily"]["final"]}
            print(f"CONFIRM {cad} on 2023 window: {conf[cad]['final']} vs daily {conf['daily']['final']}", flush=True)
    with open(os.path.join(HERE, "cadence_results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("saved cadence_results.json")

if __name__ == "__main__":
    main()
