#!/usr/bin/env python3
"""
NOVEL N-F1 — "THE SLOW FILER" (filing-lag rank) — THE GREAT RETEST (v10).
Simulation only.

Strategy (frozen, verbatim from backtests/v8/novel-f1-slow-filer/ and its
v9 copy in backtests/v9-muse-rules/novel-f1-slow-filer/): rank the honest
top-30 pond (as of Nov 2016) by dLAG = LAG_now - LAG_ref, where LAG is the
acceptance-date minus period-of-report-date (days) of a firm's most recent
original 10-K/10-Q, and LAG_ref is the same form's filing whose period
date falls 320-410 days earlier (closest to 365). Rank ascending (largest
shortening first), hold top 5 equal weight. Hard exclusion: any NT 10-K /
NT 10-Q accepted in the trailing 365 days. Eligibility: both lags
computable and LAG_now accepted within 200 days before the selection
date. Costs 0.10%/side + $0.01 per sell order. INVENTED rule (2026):
candidate ceiling language applies — an invention can at best be a
CANDIDATE, and only a forward paper trial can promote it.

INTEGRITY (run first, in ORIGINAL form): the original v8/v9 engine
(imported verbatim from the v9 folder) on its original caches reproduces
CONT 2019-01-02->2026-11-20 = $332.79 and VAL 2023-01-03->2026-11-20 =
$189.47, SPY $313.62 / $187.77, and the original placebos (CONT median
$283.72, beat 13/20; VAL median $204.08, beat 8/20 — the eligible pool
did the work on VAL, not the rank).

CADENCE SWEEP (SPEC v10): DECADE 2016-11-21 -> 2026-11-20, $100/cell,
v9 protections (plain -15% floor; first halt -> liquidate, 90 calendar
days cash, restart at the next regular decision point under an episode-2
floor of -15% from the restart balance; second halt ends the run),
20-seed random-rank placebos per cell (same eligible pools, dates and
mechanics; median twin reported per cell).

SIGNAL TREATMENT UNDER CADENCE (stated per task): the filing-lag signal
is recomputed at EVERY cadence date from the freshest filings accepted
strictly before that date — i.e. the eligible pool and dLAG ranks update
as filings land, and faster cadences simply re-evaluate (re-rank and
rebalance) on that freshest filed data more often. Nothing else changes:
same dLAG definition, same NT exclusion, same 200-day staleness gate,
same top-5 equal-weight mechanics, execution at the next open.
NATIVE CADENCE = quarterly (first trading day of Jan/Apr/Jul/Oct).

Data (read-only shared caches; nothing written outside this folder):
  - Filings: EDGAR submissions history cached in
    backtests/v8/novel-f1-slow-filer/data/ (the original engine's own
    loader, read-only).
  - Sweep prices: full-range Yahoo payloads from
    backtests/v7/long-hold/data/pxfull_*.json (read-only, the program's
    verified cache); any ticker missing there is downloaded once into
    THIS folder's data/ and used from there.
  - Integrity prices: the original engine's v4 caches, via the original
    engine itself.
"""
import importlib.util
import json
import math
import os
import random
import sys
import time
import urllib.request
from bisect import bisect_right
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
sys.path.insert(0, os.path.join(BT, "long-run-2010"))
import lr_common as C  # noqa: E402  (FastPriceBook, bars_adj, champ.spy_net, run_v9, diagnostics)

# ------------------------------------------------ original engine, verbatim
_spec = importlib.util.spec_from_file_location(
    "nf1_v9", os.path.join(BT, "v9-muse-rules", "novel-f1-slow-filer",
                           "novel-f1-slow-filer-v9.py"))
nf1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nf1)

UNIVERSE = nf1.UNIVERSE
DEC = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
PLACEBO_SEEDS = list(range(1, 21))
MYDATA = os.path.join(HERE, "data")
LH_DATA = os.path.join(BT, "v7", "long-hold", "data")


# ------------------------------------------------------------ sweep prices
def payload_for(t):
    """Full-range Yahoo payload: v7 long-hold cache (read-only) first,
    else this folder's data/, else one fresh download into this folder."""
    lh = os.path.join(LH_DATA, f"pxfull_{t}.json")
    if os.path.exists(lh) and os.path.getsize(lh) > 100:
        with open(lh, "rb") as f:
            return json.loads(f.read())
    mine = os.path.join(MYDATA, f"pxfull_{t}.json")
    if os.path.exists(mine) and os.path.getsize(mine) > 100:
        with open(mine, "rb") as f:
            return json.loads(f.read())
    import calendar
    t1 = calendar.timegm(time.strptime("2008-01-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        blob = r.read()
    with open(mine, "wb") as f:
        f.write(blob)
    return json.loads(blob)


# ------------------------------------------------------- cadence calendar
def cadence_dates(pb, start, end, cad):
    """Uniform SPEC cadence: first trading day of each cadence period.
    Biweekly anchored on absolute week parity (Monday ordinal // 7),
    the W4 harness convention."""
    days = [d for d in pb.dates if start <= d <= end]
    if cad == "daily":
        return days
    out, seen = [], set()
    for d in days:
        dt = date.fromisoformat(d)
        if cad == "weekly":
            key = ("W", dt.isocalendar()[0], dt.isocalendar()[1])
        elif cad == "biweekly":
            monday = dt.toordinal() - dt.weekday()
            if (monday // 7) % 2 != 0:
                continue
            key = ("B", monday)
        elif cad == "monthly":
            key = ("M", d[:4], d[5:7])
        elif cad == "quarterly":
            if d[5:7] not in ("01", "04", "07", "10"):
                continue
            key = ("Q", d[:4], d[5:7])
        elif cad == "semiannual":
            if d[5:7] not in ("01", "07"):
                continue
            key = ("S", d[:4], d[5:7])
        elif cad == "annual":
            key = ("A", d[:4])
        else:
            raise ValueError(cad)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


# ------------------------------------------- engine: original mechanics,
# selection calendar parameterised (body copied from nf1.run_pot with
# only the sel_dates source changed; everything else identical).
def run_pot_cad(pb, pools, start, end, start_cash, floor0, sel_dates,
                placebo_rng=None, label="", record_pools=False):
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools_log = []
    sel_dates = [d for d in sel_dates if start <= d <= end]
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            pool = pools.get(d, {})
            if len(pool) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(pool), 5)
                else:
                    picks = sorted(pool, key=lambda t: (pool[t], t))[:5]
                if record_pools:
                    pools_log.append((d, dict(pool), list(picks)))
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t],
                                   b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": pools_log,
                    "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "pools": pools_log, "curve": curve}


def median(vals):
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


# ------------------------------------------------------------------ main
def main():
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    os.makedirs(MYDATA, exist_ok=True)

    # ---------- load filings once (original loader, read-only caches)
    ciks = nf1.get_ciks()
    filings_by_ticker = {}
    for t in UNIVERSE:
        cik = nf1.CIK_OVERRIDES.get(t, ciks[t][0])
        filings_by_ticker[t] = nf1.get_filing_index(cik)
    print("filings loaded", flush=True)

    # ================= INTEGRITY — original engine, original form =====
    bars0 = {}
    for t in UNIVERSE + ["SPY"]:
        bars0[t] = nf1.get_prices(t)
    pb0 = nf1.PriceBook(bars0)
    s_cont, _ = nf1.spy_net(pb0, CONT[0], CONT[1], 100.0)
    s_val, _ = nf1.spy_net(pb0, VAL[0], VAL[1], 100.0)
    print(f"INTEGRITY spy CONT=${s_cont:,.2f} (pub 313.62) "
          f"VAL=${s_val:,.2f} (pub 187.77)", flush=True)
    assert abs(s_cont - 313.62) < 0.02 and abs(s_val - 187.77) < 0.02, \
        "SPY integrity gate FAILED"
    all_sel_q = nf1.quarter_selection_dates(pb0, "2019-01-01", "2026-11-20")
    pools0, _detail0 = nf1.build_pools(filings_by_ticker, all_sel_q)
    integrity = {"status": "reproduced",
                 "original_finals": {"CONT": 332.79, "VAL": 189.47,
                                     "spy_CONT": 313.62, "spy_VAL": 187.77,
                                     "placebo_median_CONT": 283.72,
                                     "placebo_beaten_CONT": "13/20",
                                     "placebo_median_VAL": 204.08,
                                     "placebo_beaten_VAL": "8/20"},
                 "reproduced_finals": {}}
    for wname, (ws, we), pub in (("CONT", CONT, 332.79),
                                 ("VAL", VAL, 189.47)):
        r = nf1.run_pot(pb0, pools0, ws, we, 100.0, 85.0,
                        label=f"INTEGRITY {wname}", record_pools=True)
        pfinals = []
        for seed in PLACEBO_SEEDS:
            pr = nf1.run_pot(pb0, pools0, ws, we, 100.0, 85.0,
                             placebo_rng=random.Random(seed),
                             label=f"INTEGRITY {wname} placebo {seed}")
            pfinals.append(pr["final"])
        psum = nf1.placebo_summary(pfinals, r["final"])
        integrity["reproduced_finals"][wname] = {
            "final": round(r["final"], 2), "published": pub,
            "match": abs(r["final"] - pub) < 0.02,
            "placebo_median": psum["median"],
            "placebo_beaten": f"{psum['beat']}/20",
            "placebo_finals": psum["finals"]}
        print(f"INTEGRITY {wname}: final=${r['final']:,.2f} (pub {pub}) "
              f"placebo median=${psum['median']:,.2f} beat={psum['beat']}/20",
              flush=True)
        assert abs(r["final"] - pub) < 0.02, f"INTEGRITY FAILED on {wname}"
    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump(integrity, f, indent=1, default=str)

    # ================= SWEEP — decade, 7 cadences =====================
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = C.bars_adj(payload_for(t))
    pb = C.FastPriceBook(bars)
    spy_dec, _ = C.champ.spy_net(pb, DEC[0], DEC[1], 100.0)
    spy_dec = round(spy_dec, 2)
    print(f"DECADE SPY (sweep plumbing) = ${spy_dec:,.2f} "
          f"(SPEC reference $367.80)", flush=True)

    cad_dates = {cad: cadence_dates(pb, DEC[0], DEC[1], cad)
                 for cad in CADENCES}
    union_dates = sorted({d for ds in cad_dates.values() for d in ds})
    print({c: len(ds) for c, ds in cad_dates.items()},
          f"union={len(union_dates)}", flush=True)
    pools, detail = nf1.build_pools(filings_by_ticker, union_dates)
    pool_sizes = {d: len(pools[d]) for d in union_dates}
    print("pool sizes min/max:", min(pool_sizes.values()),
          max(pool_sizes.values()), flush=True)
    dlags = [v["dlag"] for v in detail.values() if v["status"] == "scored"]
    print(f"dLAG scored name-dates: {len(dlags)} min={min(dlags)} "
          f"max={max(dlags)} mean={sum(dlags)/len(dlags):.2f}", flush=True)

    trading_days = [d for d in pb.dates if DEC[0] <= d <= DEC[1]]
    cells = {}
    for cad in CADENCES:
        sdates = cad_dates[cad]

        def run_one(s, e, cash, floor, _sd=sdates, _rng=None):
            return run_pot_cad(pb, pools, s, e, cash, floor, _sd,
                               placebo_rng=_rng, record_pools=True)

        out = C.run_v9(run_one, trading_days, DEC[0], DEC[1], 100.0)
        cg, _yrs = C.cagr(out["final"], 100.0, DEC[0], DEC[1])
        diag = C.curve_diagnostics(out["curve"])
        # placebos: 20 seeds through the identical v9-wrapped chassis
        pfinals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)

            def run_p(s, e, cash, floor, _sd=sdates, _rng=rng):
                return run_pot_cad(pb, pools, s, e, cash, floor, _sd,
                                   placebo_rng=_rng, record_pools=True)

            po = C.run_v9(run_p, trading_days, DEC[0], DEC[1], 100.0)
            pfinals.append(round(po["final"], 2))
        beat = sum(1 for f in pfinals if f < out["final"])
        med = round(median(pfinals), 2)
        cell = {"final": round(out["final"], 2), "cagr_pct": cg,
                "max_dd_pct": diag["max_drawdown_pct"],
                "halts": len(out["halts"]),
                "restart": bool(out["restart"]),
                "second_halt": bool(out["restart"] and
                                    out["restart"].get("second_halt")),
                "costs": round(out["costs"], 2), "orders": out["orders"],
                "placebo_beaten": f"{beat}/20",
                "placebo_note": (f"20 seeds, same pools/dates/mechanics; "
                                 f"median twin ${med:,.2f}")}
        cells[cad] = cell
        cell_doc = dict(cell)
        cell_doc.update({
            "slug": "novel-f1-slow-filer", "cadence": cad,
            "window": {"start": DEC[0], "end": DEC[1]},
            "start_cash": 100.0, "spy_final": spy_dec,
            "selection_dates_count": len(sdates),
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "max_dd_date": diag["max_drawdown_date"],
            "halts_detail": out["halts"], "restart_detail": out["restart"],
            "placebo_twin_finals": pfinals,
            "placebo_median": med,
            "equity_curve": [[d, round(v, 2)] for d, v in out["curve"]]})
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1, default=str)
        print(f"CELL {cad}: final=${cell['final']:,.2f} CAGR={cg} "
              f"maxDD={cell['max_dd_pct']} halts={cell['halts']} "
              f"restart={cell['restart']} 2nd={cell['second_halt']} "
              f"costs=${cell['costs']:,.2f} orders={cell['orders']} "
              f"placebo beat={beat}/20 median=${med:,.2f}", flush=True)

    money = [cad for cad, c in cells.items()
             if c["final"] > spy_dec and
             int(c["placebo_beaten"].split("/")[0]) >= 11]
    results = {
        "slug": "novel-f1-slow-filer",
        "area": ("W4 filings pond ranking — long road (quarterly filing-lag "
                 "rank on the honest top-30 pond); sweep road = DECADE"),
        "area_source": "SPEC W4 assignment + CADENCE GRID (W4: quarterly as designed)",
        "cadence": "quarterly",
        "native_cadence": "quarterly",
        "original_cadence_foreign": False,
        "original_cadence_note": ("Original v8/v9 test ran quarterly — the "
                                  "native cadence. No foreign-cadence flag."),
        "signal_treatment": ("Filing-lag signal recomputed at every cadence "
                             "date from filings accepted strictly before "
                             "that date; faster cadences re-evaluate on "
                             "the freshest filed data. Definition, NT "
                             "exclusion, staleness gate and top-5 "
                             "mechanics unchanged."),
        "integrity": integrity,
        "decade_spy_final": spy_dec,
        "decade_window": {"start": DEC[0], "end": DEC[1]},
        "champion_decade_reference": 65.89,
        "champion_decade_caveat": ("Champion DECADE $65.89 after two halts "
                                   "(lazy-quarterly test); its crown rests "
                                   "on the 2010 and 2019 roads."),
        "cells": cells,
        "money_cadences": money,
        "pool_size_range_decade_union": [min(pool_sizes.values()),
                                         max(pool_sizes.values())],
        "data_note": ("Filings: v8 EDGAR submissions cache (read-only). "
                      "Sweep prices: v7 long-hold pxfull Yahoo cache "
                      "(read-only) plus any missing tickers downloaded "
                      "into this folder's data/. Integrity: original v4 "
                      "caches via the original engine. The 1.7GB long-run "
                      "cache was NOT bulk-loaded; only lr_common plumbing "
                      "was imported."),
        "verdict_area": None,  # filled below
        "verdict_change": None,
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    print("MONEY CADENCES:", money, flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
