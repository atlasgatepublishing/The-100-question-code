#!/usr/bin/env python3
"""
CRYPTO-BASKET — v10 CONFIRMATION RUN for the PROVISIONAL annual-cadence flip.
Simulation only. Terry's CONFIRMATION RULE (SPEC.md): a new money cadence is
not crowned until re-run on the other roads. The sweep's honest road for this
basket is 2020-06-01 -> 2026-11-20 (cache + lookback limits; there is no 2010
or 2016 crypto road), so the "other roads" here are the program's other
windows inside the data: the original DESIGN window and the original
VALIDATION window (dates from the original v4 engine / the sweep folder's
integrity record), plus fresh yearly folds.

  DESIGN     2020-06-01 -> 2022-12-31   (original published monthly $356.20)
  VALIDATION 2023-01-01 -> 2026-11-20   (anchors: $82.49 plain halt 2023-06-15;
                                          $80.39 under v9)

Runs: annual AND monthly (native, comparison) on both windows through the
sweep engine UNCHANGED (copied verbatim as crypto_basket_engine.py, only its
cache path depth adjusted); 20-seed hat-draw placebos at BOTH cadences on
both windows (same design as the sweep: random 5 eligible per decision, same
v9 machinery, seeds 1..20); yearly folds at ANNUAL cadence, fresh $100 each
(2020 partial 2020-06-01->2020-12-31; 2026 ends 2026-11-20).

Benchmarks per window, computed in-plumbing:
  BTC buy-and-hold — the engine's own btc_hold() (0.25%/side, engine bars).
  SPY buy-and-hold — dividend-adjusted bars from the read-only long-hold
  cache pxfull_SPY.json (bars_adj construction, lr_common.py), bought at the
  first open on/after window start, sold at the last close on/before window
  end, program stock cost 0.10%/side. Verified against SPEC references:
  DECADE $367.81 (SPEC $367.80), CONT $313.63 ($313.62), VAL $187.78
  ($187.77), LONG $822.95 ($822.94) — 1c rounding vs the published plumbing.

$100 start, crypto costs 0.25%/side, v9 protections — identical to the sweep.
One clean shot, no tuning. Universe caveat: the 20-coin list is a 2026-built
SURVIVOR list, NOT point-in-time — every number here is survivorship-
flattered and capped at REAL BUT SMALL even if confirmed.
"""
import json, os, sys, time as _time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crypto_basket_engine as E

SPY_CACHE = os.path.abspath(os.path.join(
    HERE, "..", "..", "..", "v7", "long-hold", "data", "pxfull_SPY.json"))
SPY_COST = 0.0010  # program stock convention, 0.10%/side

def spy_bars():
    p = json.load(open(SPY_CACHE))
    res = p["chart"]["result"][0]; ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = _time.strftime("%Y-%m-%d", _time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append((d, (o * ratio if o else a), a))
    bars.sort()
    return bars

SPY_BARS = spy_bars()

def spy_hold(start, end):
    w = [b for b in SPY_BARS if start <= b[0] <= end]
    sh = (E.POT * (1 - SPY_COST)) / w[0][1]
    return round(sh * w[-1][2] * (1 - SPY_COST), 2)

def run_cell(window_name, start, end, cad, with_placebos=True):
    r = E.run_v9(start, end, cad, "ranked")
    placebo_finals = []
    if with_placebos:
        for s in range(1, 21):
            placebo_finals.append(E.run_v9(start, end, cad, "placebo", seed=s)["final"])
    beaten = sum(1 for v in placebo_finals if r["final"] > v) if placebo_finals else None
    out = {"window": window_name, "start": start, "end": end, "cadence": cad,
           "final": r["final"], "cagr_pct": r["cagr_pct"], "max_dd_pct": r["max_dd_pct"],
           "costs": r["costs"], "orders": r["orders"],
           "halts": r["halts"], "halt_dates": r["halt_dates"],
           "restart": r["restart"], "second_halt": r["second_halt"],
           "restart_info": r["restart_info"],
           "placebo_beaten": beaten, "placebo_finals": placebo_finals,
           "placebo_note": "20 seeds (1..20), random 5 eligible per decision, same v9 machinery, fresh RNG per episode — identical design to the sweep",
           "btc_hold_same_window": E.btc_hold(start, end),
           "spy_hold_same_window": spy_hold(start, end),
           "equity_curve": [[d, v] for d, v in r["curve"]]}
    fn = os.path.join(HERE, f"{window_name}-{cad}.json")
    with open(fn, "w") as f: json.dump(out, f, indent=1)
    print(f"{window_name} {cad}: final={r['final']} CAGR={r['cagr_pct']} DD={r['max_dd_pct']} "
          f"halts={r['halts']} {r['halt_dates']} restart={r['restart']} costs={r['costs']} "
          f"orders={r['orders']} placebo={beaten}/20 BTC={out['btc_hold_same_window']} "
          f"SPY={out['spy_hold_same_window']}", flush=True)
    return out

def main():
    # SPY plumbing self-check against SPEC reference points
    chk = {n: spy_hold(s, e) for n, s, e in
           [("DECADE", "2016-11-21", "2026-11-20"), ("CONT", "2019-01-02", "2026-11-20"),
            ("VAL", "2023-01-03", "2026-11-20"), ("LONG", "2010-01-04", "2026-11-20")]}
    print("SPY plumbing check (SPEC: DECADE 367.80, CONT 313.62, VAL 187.77, LONG 822.94):",
          chk, flush=True)

    windows = [("design", "2020-06-01", "2022-12-31"),
               ("validation", "2023-01-01", "2026-11-20")]
    res = {}
    for wname, s, e in windows:
        for cad in ("annual", "monthly"):
            res[(wname, cad)] = run_cell(wname, s, e, cad)

    # Integrity cross-checks printed for the record
    dm = res[("design", "monthly")]["final"]
    vm = res[("validation", "monthly")]["final"]
    print(f"INTEGRITY monthly DESIGN = {dm} (original published 356.20); "
          f"monthly VALIDATION v9 = {vm} (anchor 80.39)", flush=True)

    # ---- yearly folds, ANNUAL cadence, fresh $100 ----
    folds = []
    fold_defs = [("2020-partial", "2020-06-01", "2020-12-31", True)]
    for y in range(2021, 2026):
        fold_defs.append((str(y), f"{y}-01-01", f"{y}-12-31", False))
    fold_defs.append(("2026", "2026-01-01", "2026-11-20", False))
    for label, s, e, partial in fold_defs:
        r = E.run_v9(s, e, "annual", "ranked")
        btc = E.btc_hold(s, e); spy = spy_hold(s, e)
        note = None
        if r["orders"] == 0:
            note = ("No annual decision date (Jan 1) falls inside this window after the "
                    "road start, so the pot was never invested and stayed at $100 cash.")
        fold = {"fold": label, "start": s, "end": e, "partial_year": partial,
                "cadence": "annual", "final": r["final"], "cagr_pct": r["cagr_pct"],
                "max_dd_pct": r["max_dd_pct"], "costs": r["costs"], "orders": r["orders"],
                "halts": r["halts"], "halt_dates": r["halt_dates"],
                "restart": r["restart"], "second_halt": r["second_halt"],
                "restart_info": r["restart_info"],
                "btc_hold_same_year": btc, "spy_hold_same_year": spy,
                "beat_btc": r["final"] > btc, "beat_spy": r["final"] > spy,
                "note": note, "equity_curve": [[d, v] for d, v in r["curve"]]}
        folds.append(fold)
        print(f"fold {label}: final={r['final']} BTC={btc} SPY={spy} orders={r['orders']} "
              f"halts={r['halts']} {r['halt_dates']}", flush=True)
    with open(os.path.join(HERE, "folds.json"), "w") as f:
        json.dump({"folds": folds,
                   "note": "Fresh $100 pot per fold, annual cadence, v9 protections, 0.25%/side. 2020 is a partial year (road starts 2020-06-01). 2026 ends 2026-11-20."},
                  f, indent=1)
    print("saved folds.json", flush=True)

if __name__ == "__main__":
    main()
