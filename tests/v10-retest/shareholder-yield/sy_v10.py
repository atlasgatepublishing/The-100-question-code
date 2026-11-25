#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — SHAREHOLDER YIELD (Faber total payout yield sort).

Driver. Engine: sy_engine.py in this folder = verbatim copy of
backtests/v9-muse-rules/shareholder-yield/shareholder-yield-v9.py
(itself the v6 engine + the v9 protection module). All scoring,
dividend-cash crediting, costs (0.10%/side + $0.01 per sell order),
execution and floor mechanics are the engine's own, unchanged.

What this driver adds:
  1. INTEGRITY: his-rules (plain -15% floor, no restart) and v9-rules
     runs on CONT (2019-01-02->2026-11-20) and VAL (2023-01-03->
     2026-11-20), quarterly cadence, prices/dividends from the
     ORIGINAL v4 cached Yahoo payloads (engine's own loader).
  2. CADENCE SWEEP on the DECADE road 2016-11-21 -> 2026-11-20:
     cadence = how often the strategy re-scores, re-ranks and
     rebalances (SPEC uniform definition). Implemented by replacing
     the baseline engine's quarter_selection_dates with a cadence
     dispatcher for the duration of each run; quarterly dispatches to
     the original function untouched. Restart after a halt (v9 rules)
     is at the next cadence date >= halt + 90 calendar days.
     Decade prices/dividends: v7 long-hold pxfull_* Yahoo payloads
     (2008-01-02 -> 2026-11-20, read-only) because the v4 payloads
     only start 2017-06-01 and cannot cover the decade start.
     Fundamentals: EDGAR companyfacts via the baseline engine's
     shared cache (full history), same series construction as v9.
  3. PLACEBOS: 20 seeds per cell, random 5 from the strategy's own
     scored pool at each selection, same v9 protections, same
     dividend crediting (engine's placebo path).
  4. SPY decade benchmark: dividend-adjusted buy-and-hold via the
     baseline engine's spy_net on adjclose-ratio bars built from the
     pxfull SPY payload (the program's standard method).

Native cadence: ANNUAL (Faber's published form). The original
program test ran QUARTERLY — a foreign cadence, flagged.
"""
import importlib.util
import json
import math
import os
import random
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
PXFULL = os.path.join(BT, "v7", "long-hold", "data")

spec = importlib.util.spec_from_file_location("sy_engine", os.path.join(HERE, "sy_engine.py"))
SY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SY)
E = SY.E
UNIVERSE = SY.UNIVERSE

START_CASH = 100.0
DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"]

# ------------------------------------------------------------ cadence dates
_ORIG_QSD = E.quarter_selection_dates
STATE = {"cadence": "quarterly"}


def _first_per(pb, start, end, keyfn):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end:
            k = keyfn(d)
            if k not in seen:
                seen.add(k)
                out.append(d)
    return out


def cadence_dates(pb, start, end):
    c = STATE["cadence"]
    if c == "quarterly":
        return _ORIG_QSD(pb, start, end)
    if c == "daily":
        return [d for d in pb.dates if start <= d <= end]
    if c == "weekly":
        return _first_per(pb, start, end,
                          lambda d: _date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()[:2])
    if c == "biweekly":
        wk = _first_per(pb, start, end,
                        lambda d: _date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()[:2])
        return wk[::2]
    if c == "monthly":
        return _first_per(pb, start, end, lambda d: (d[:4], d[5:7]))
    if c == "semiannual":
        return _first_per(pb, start, end,
                          lambda d: (d[:4], "H1" if d[5:7] in ("01", "02", "03", "04", "05", "06") else "H2"))
    if c == "annual":
        return _first_per(pb, start, end, lambda d: d[:4])
    raise ValueError(c)


E.quarter_selection_dates = cadence_dates  # dispatcher; engine calls this

# ------------------------------------------- verified-identical speedups
# (a) pit_value is a pure function of (rows, asof): memoize it. The 21
# runs of a cell (ranked + 20 placebos) re-ask the same questions.
_PIT_ORIG = E.pit_value
_PIT_CACHE = {}


def _pit_cached(rows, asof, max_age_days=548):
    k = (id(rows), asof, max_age_days)
    v = _PIT_CACHE.get(k, False)
    if v is False:
        v = _PIT_ORIG(rows, asof, max_age_days)
        _PIT_CACHE[k] = v
    return v


E.pit_value = _pit_cached

# (b) PriceBook.close_on_or_before is a linear scan in the baseline;
# a bisect on the same sorted bars returns the identical bar.


class FastPriceBook(E.PriceBook):
    def __init__(self, bars_by_ticker):
        super().__init__(bars_by_ticker)
        from bisect import bisect_right
        self._bisect = bisect_right
        self._dl = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None
        i = self._bisect(dl, d)
        if i == 0:
            return None
        return self.bars[t][i - 1]["c"]

# ------------------------------------------------------------ data builders
def build_rows():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    shares_rows, div_rows, cash_rows, debt_rows = {}, {}, {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        shares_rows[t] = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
                          E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
                          E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        div_rows[t] = SY.annual_series(facts, SY.DIV_CONCEPTS)
        cash_rows[t] = SY.instant_series(facts, SY.CASH_CONCEPTS)
        debt_rows[t] = {"cur": SY.instant_series(facts, SY.CUR_CONCEPTS),
                        "non": SY.instant_series(facts, SY.NON_CONCEPTS),
                        "tot": SY.instant_series(facts, SY.TOT_CONCEPTS)}
        time.sleep(0.05)
    return (shares_rows, div_rows, debt_rows, cash_rows)


def load_payload_full(ticker):
    mine = os.path.join(HERE, "data_cache", f"pxfull_{ticker}.json")
    if os.path.exists(mine):  # GOOGL only: fresh Yahoo pull cached in-folder
        p = mine          # (the shared pxfull cache has GOOG, not GOOGL)
    else:
        p = os.path.join(PXFULL, f"pxfull_{ticker}.json")
    with open(p, "rb") as f:
        return json.loads(f.read())


def raw_bars_divs_from_payload(j):
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        bars.append({"d": d, "o": (o if o else c), "c": c})
    bars.sort(key=lambda b: b["d"])
    divs = {}
    for v in res.get("events", {}).get("dividends", {}).values():
        d = time.strftime("%Y-%m-%d", time.gmtime(v["date"]))
        divs[d] = float(v["amount"])
    return bars, divs


def adj_bars_from_payload(j):
    """Baseline get_prices method (adjclose ratio) on the pxfull payload."""
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

# ------------------------------------------------------------ v9 wrapper
def _ord(dstr):
    return _date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()


def run_v9g(pb, div_events, rows, start, end, start_cash=100.0, placebo_rng=None):
    """v9 protections, generalized from sy_engine.run_v9: episode 1
    plain -15% floor; on first halt liquidate as the engine does, sit
    in cash 90 calendar days, restart at the next cadence selection
    date with an episode-2 floor of -15% from the restart balance;
    second halt ends the run."""
    floor1 = round(0.85 * start_cash, 2)
    r1 = SY.run_pot_sy(pb, div_events, *rows, start, end, start_cash, floor1,
                       [], placebo_rng=placebo_rng, label="EP1", quiet=True)
    out = {"final": r1["final"], "costs": r1["costs"], "orders": len(r1["trades"]),
           "curve": list(r1["curve"]), "halted": r1["halted"],
           "ep1_final": r1["final"], "ep1_halt": None, "restarts": [],
           "second_halt": None, "dividends_total": r1["dividends_total"]}
    if r1["halted"] is None:
        return out
    out["ep1_halt"] = {"signal_date": r1["halted"],
                       "signal_close": r1["halt_info"]["signal_close"],
                       "floor_in_effect": r1["halt_info"]["floor_in_effect"],
                       "liquidation_date": r1["end"],
                       "liquidation_final": round(r1["final"], 2)}
    liq = r1["end"]
    cash = r1["final"]
    day90 = _ord(r1["halted"]) + 90
    restart = None
    for cand in cadence_dates(pb, start, end):
        if _ord(cand) >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({"halt_signal_date": r1["halted"],
                            "liquidation_date": liq,
                            "halt_signal_close": r1["halt_info"]["signal_close"],
                            "restart_date": restart,
                            "restart_balance": round(cash, 2),
                            "episode2_floor": floor2})
    r2 = SY.run_pot_sy(pb, div_events, *rows, restart, end, cash, floor2,
                       [], placebo_rng=placebo_rng, label="EP2", quiet=True)
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["orders"] += len(r2["trades"])
    out["dividends_total"] += r2["dividends_total"]
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
        out["curve"].append((r2["end"], r2["final"]))
    out["curve"].sort(key=lambda kv: kv[0])
    return out


def stats(curve, start, end):
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (_ord(end) - _ord(start)) / 365.25
    return maxdd * 100.0, yrs


def cell_record(res, start, end):
    maxdd, yrs = stats(res["curve"], start, end)
    final = res["final"]
    halts = (1 if res["ep1_halt"] else 0) + (1 if res["second_halt"] else 0)
    return {"final": round(final, 2),
            "cagr_pct": round(((final / START_CASH) ** (1.0 / yrs) - 1) * 100, 2) if final > 0 else -100.0,
            "max_dd_pct": round(maxdd, 2),
            "halts": halts,
            "restart": bool(res["restarts"]),
            "restart_dates": [r["restart_date"] for r in res["restarts"]],
            "second_halt": bool(res["second_halt"]),
            "costs": round(res["costs"], 2),
            "orders": res["orders"],
            "dividends_total": round(res["dividends_total"], 2),
            "ep1_halt": res["ep1_halt"],
            "second_halt_detail": res["second_halt"]}


def save_cell(cadence, rec, res, placebo_finals):
    doc = dict(rec)
    doc["cadence"] = cadence
    doc["window"] = {"start": DECADE[0], "end": DECADE[1]}
    doc["equity_curve"] = [[d, round(v, 4)] for d, v in res["curve"]]
    doc["placebo_twin_finals"] = placebo_finals
    with open(os.path.join(HERE, "cells", f"{cadence}.json"), "w") as f:
        json.dump(doc, f, indent=1)
    return doc

# ------------------------------------------------------------ main phases
def phase_integrity(rows, pb_v4, divs_v4):
    STATE["cadence"] = "quarterly"
    out = {}
    for tag, (ws, we), his_pub, v9_pub in (
            ("CONT", CONT, 88.56, 211.34), ("VAL", VAL, 84.56, 118.57)):
        rh = SY.run_pot_sy(pb_v4, divs_v4, *rows, ws, we, START_CASH, 85.0,
                           [], label=f"INTEGRITY HIS {tag}", quiet=True)
        rv = run_v9g(pb_v4, divs_v4, rows, ws, we)
        out[tag] = {"his_original_final": his_pub, "his_reproduced_final": round(rh["final"], 2),
                    "his_halted": rh["halted"],
                    "v9_original_final": v9_pub, "v9_reproduced_final": round(rv["final"], 2),
                    "v9_restarts": rv["restarts"], "v9_second_halt": rv["second_halt"]}
        print(f"INTEGRITY {tag}: his {rh['final']:.2f} (pub {his_pub}) halted={rh['halted']} | "
              f"v9 {rv['final']:.2f} (pub {v9_pub}) restarts={rv['restarts']}", flush=True)
    return out


def phase_cell(cadence, rows, pb, divs, do_placebos=True):
    STATE["cadence"] = cadence
    t0 = time.time()
    res = run_v9g(pb, divs, rows, DECADE[0], DECADE[1])
    rec = cell_record(res, DECADE[0], DECADE[1])
    print(f"CELL {cadence}: final=${rec['final']} cagr={rec['cagr_pct']}% maxDD={rec['max_dd_pct']}% "
          f"halts={rec['halts']} restart={rec['restart']} costs=${rec['costs']} orders={rec['orders']} "
          f"divs=${rec['dividends_total']} ({time.time()-t0:.0f}s)", flush=True)
    placebo_finals = []
    beaten = None
    if do_placebos:
        for seed in range(1, 21):
            rng = random.Random(seed)
            rp = run_v9g(pb, divs, rows, DECADE[0], DECADE[1], placebo_rng=rng)
            placebo_finals.append(round(rp["final"], 2))
        beaten = sum(1 for v in placebo_finals if rec["final"] > v)
        print(f"CELL {cadence} PLACEBOS: ranked beats {beaten}/20 "
              f"median=${sorted(placebo_finals)[10]:.2f} best=${max(placebo_finals):.2f} "
              f"worst=${min(placebo_finals):.2f} ({time.time()-t0:.0f}s total)", flush=True)
    rec["placebo_beaten"] = (f"{beaten}/20" if beaten is not None else None)
    rec["placebo_note"] = ("20 seeds, random 5 from the strategy's own scored pool at each "
                           "selection, same v9 protections and dividend crediting"
                           if beaten is not None else "not run")
    save_cell(cadence, rec, res, placebo_finals)
    return rec


def main():
    import sys
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    print("building EDGAR rows...", flush=True)
    rows = build_rows()
    # integrity plumbing: original v4 payloads via the engine's own loader
    bars_v4, divs_v4 = {}, {}
    for t in UNIVERSE + ["SPY"]:
        b, dv = SY.get_raw_bars_and_divs(t)
        bars_v4[t] = b
        divs_v4[t] = dv
    pb_v4 = E.PriceBook(bars_v4)
    # decade plumbing: pxfull payloads
    bars_full, divs_full = {}, {}
    for t in UNIVERSE:
        b, dv = raw_bars_divs_from_payload(load_payload_full(t))
        bars_full[t] = b
        divs_full[t] = dv
    pb_full = FastPriceBook(bars_full)
    spy_adj = E.PriceBook({"SPY": adj_bars_from_payload(load_payload_full("SPY"))})
    spy_dec, _ = E.spy_net(spy_adj, DECADE[0], DECADE[1], START_CASH)
    print(f"SPY DECADE (dividend-adjusted, pxfull): ${spy_dec:.2f} (SPEC reference $367.80)", flush=True)

    state_path = os.path.join(HERE, "_sweep_state.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {}
    state["decade_spy_final"] = round(spy_dec, 2)

    if which in ("all", "integrity"):
        state["integrity"] = phase_integrity(rows, pb_v4, divs_v4)
        json.dump(state, open(state_path, "w"), indent=1)

    if which in ("all", "cells"):
        todo = CADENCES if len(sys.argv) < 3 else sys.argv[2].split(",")
        state.setdefault("cells", {})
        for cad in todo:
            state["cells"][cad] = phase_cell(cad, rows, pb_full, divs_full)
            json.dump(state, open(state_path, "w"), indent=1)
    print("PHASE DONE", which, flush=True)


if __name__ == "__main__":
    main()
