#!/usr/bin/env python3
"""
V10 GREAT RETEST — vm-trendgate (value+momentum + Faber SPY-vs-200-day gate).

WHAT THIS RUNS
1) INTEGRITY: the ORIGINAL published finals reproduced through the original
   plumbing (the v9 module's run_pot_gated, his-rules form: quarterly,
   plain -$15 floor, NO restart):
     CONT 2019-01-02 -> 2026-11-20 : $79.36, halted 2020-03-20
     VAL  2023-01-03 -> 2026-11-20 : $163.79, no halt
   Plus the v9 sweep reference: CONT under v9 protections = $183.09.

2) THE CADENCE SWEEP on the DECADE road 2016-11-21 -> 2026-11-20, $100/cell,
   program costs (0.10%/side + $0.01/sell), adopted v9 protections
   (plain -15% floor per episode; first halt -> liquidate, 90 calendar days
   cash, restart at the next regular CADENCE decision point under an
   episode-2 floor of -15% from the restart balance; second halt ends run).

UNIFORM CADENCE RULE (stated per task): cadence governs BOTH the re-pick
(selection/scoring/rebalance) AND the gate evaluation. Signal evaluation,
selection and trading happen ONLY on cadence dates: daily = every trading
day; weekly = first trading day of each ISO week; biweekly = first trading
day of every second ISO week (anchored on the first week of the window);
monthly = first trading day of each month; quarterly = first trading day
of Jan/Apr/Jul/Oct; semi-annual = first trading day of Jan/Jul; annual =
first trading day of each year. At each cadence date the gate is evaluated
exactly as in the original: on the last SPY bar strictly before the
selection date, gate ON iff SPY close >= its trailing 200-trading-day MA
(adjusted closes). Gate OFF -> target is empty (liquidate at next open,
cash until the next cadence date). Rebalances execute at the next open,
as in the original engine. The -15% floor is checked on every close
(protection is not a signal; identical to the original engine).

DATA (read-only shared caches; nothing written outside this folder):
- Integrity: the v4 module's own caches exactly as the v9 script uses them
  (prices from 2017-06-01, backtests/v4/data + value-momentum-honest-data;
  EDGAR companyfacts from backtests/v4/data).
- Sweep: the DECADE starts 2016-11-21 and 12-1 momentum needs 253 trading
  days of history, so sweep prices come from the full-history Yahoo
  payloads cached read-only in backtests/v7/long-hold/data/pxfull_*.json
  (GOOGL from backtests/long-run-2010/data/), parsed with the IDENTICAL
  bar construction as the v4 engine (open/close scaled by adjclose/close,
  close = adjclose). EDGAR facts are the same v4 cache. Universe, PIT
  rules (filed strictly before selection date, 548-day freshness gate),
  scoring (book-to-market + 12-1 momentum, average of percentile ranks,
  top-5 equal weight), and costs are byte-identical to the original.

PLUMBING NOTE (no signal change): per cadence, the scored pool, ranked
picks and gate state are precomputed once per cadence date (they depend
only on the date, not on the pot), then the ranked pot and the 20 placebo
pots (seeds 1..20, random.sample of the scored pool at each cadence date,
same RNG usage order as the original engine) are simulated against those
decisions. Trade execution, floor, halt and restart mechanics replicate
run_pot_gated / run_pot_v9 line for line.

Simulation only. Writes ONLY inside this folder.
"""
import bisect
import importlib.util
import json
import os
import random
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
BASE_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py")
V9_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v9-muse-rules/vm-trendgate/vm-trendgate-v9.py")
LH_DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
LR_DATA = os.path.expanduser("~/workspace/stock-app/backtests/long-run-2010/data")

spec = importlib.util.spec_from_file_location("vm_plainfloor", BASE_PATH)
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

spec9 = importlib.util.spec_from_file_location("vm_trendgate_v9", V9_PATH)
V9 = importlib.util.module_from_spec(spec9)
spec9.loader.exec_module(V9)

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
DECADE = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
PLACEBO_SEEDS = list(range(1, 21))


# ------------------------------------------------------------- full prices
def bars_from_payload(payload):
    """Identical to E.get_prices' bar construction."""
    res = payload["chart"]["result"][0]
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


def build_inputs_full():
    """EDGAR inputs identical to the v9 build_inputs; prices full-history."""
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        time.sleep(0.05)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        payload = None
        for folder in (LH_DATA, LR_DATA):
            p = os.path.join(folder, f"pxfull_{t}.json")
            if os.path.exists(p) and os.path.getsize(p) > 100:
                with open(p, "rb") as f:
                    payload = json.loads(f.read())
                break
        assert payload is not None, f"no pxfull cache for {t}"
        bars[t] = bars_from_payload(payload)
    return E.PriceBook(bars), equity_rows, shares_rows


# ------------------------------------------------------------ cadence dates
def cadence_dates(pb, cadence, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    if cadence == "weekly":
        for d in days:
            iso = _date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "biweekly":
        weeks, wseen = [], set()
        for d in days:
            iso = _date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()
            key = (iso[0], iso[1])
            if key not in wseen:
                wseen.add(key)
                weeks.append((key, d))
        return [d for i, (k, d) in enumerate(weeks) if i % 2 == 0]
    if cadence == "monthly":
        for d in days:
            key = d[:7]
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "quarterly":
        return E.quarter_selection_dates(pb, start, end)
    if cadence == "semiannual":
        for d in days:
            if d[5:7] in ("01", "07"):
                key = (d[:4], d[5:7])
                if key not in seen:
                    seen.add(key)
                    out.append(d)
        return out
    if cadence == "annual":
        for d in days:
            key = d[:4]
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    raise ValueError(cadence)


# ------------------------------------------------- precomputed decisions
class FastBook:
    """Bisect helpers over a PriceBook (same values, faster lookup)."""

    def __init__(self, pb):
        self.pb = pb
        self.dates_list = {t: [b["d"] for b in bl]
                           for t, bl in pb.bars.items()}

    def close_on_or_before(self, t, d):
        bl = self.pb.bars.get(t, [])
        dl = self.dates_list.get(t, [])
        i = bisect.bisect_right(dl, d) - 1
        return bl[i]["c"] if i >= 0 else None

    def bar_index_on(self, t, d):
        dl = self.dates_list.get(t, [])
        i = bisect.bisect_left(dl, d)
        return i if i < len(dl) and dl[i] == d else None


def gate_state(fb, sel_date):
    """Original spy_trend_gate semantics via bisect: last SPY bar strictly
    before sel_date; ON iff close >= trailing 200-bar mean of closes."""
    bars = fb.pb.bars["SPY"]
    dl = fb.dates_list["SPY"]
    idx = bisect.bisect_left(dl, sel_date) - 1
    if idx is None or idx < 199:
        return None
    window = bars[idx - 199: idx + 1]
    ma = sum(b["c"] for b in window) / 200.0
    close = bars[idx]["c"]
    return {"quarter_end": bars[idx]["d"], "spy_close": round(close, 2),
            "ma200": round(ma, 2), "gate_on": bool(close >= ma)}


def precompute_decisions(fb, equity_rows, shares_rows, sel_dates):
    """date -> {scores:{t:(bm,mom)}, picks:[ranked top5], gate:{...}|None}
    Replicates the selection-day block of run_pot_gated exactly."""
    dec = {}
    for d in sel_dates:
        scores = {}
        for t in UNIVERSE:
            be = E.pit_value(equity_rows.get(t, []), d)
            so = E.pit_value(shares_rows.get(t, []), d)
            px = fb.close_on_or_before(t, d)
            if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            bm = be[2] / mcap
            bl = fb.pb.bars.get(t, [])
            didx = fb.bar_index_on(t, d)
            if didx is None or didx < 253:
                continue
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (bm, mom)
        picks = None
        if len(scores) >= 5:
            vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
            mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
            combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
            picks = sorted(combined, key=lambda t: -combined[t])[:5]
        dec[d] = {"scores": scores, "picks": picks, "gate": gate_state(fb, d)}
    return dec


# ------------------------------------------------------------ pot engine
def run_pot_cadence(pb, decisions, sel_dates, start, end, start_cash,
                    floor0, placebo_rng=None):
    """run_pot_gated with precomputed decisions; mechanics identical."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    gate_log = []
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
            dec = decisions[d]
            scores = dec["scores"]
            if len(scores) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    picks = list(dec["picks"])
                pv = portfolio_close(d)
                g = dec["gate"]
                gate_log.append({"selection_date": d,
                                 "quarter_end": g["quarter_end"] if g else None,
                                 "spy_close": g["spy_close"] if g else None,
                                 "ma200": g["ma200"] if g else None,
                                 "gate_on": g["gate_on"] if g else None,
                                 "picks": list(picks),
                                 "pot_at_selection": round(pv, 2)})
                if g is not None and not g["gate_on"]:
                    pending = {}
                else:
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
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "curve": curve, "gate_log": gate_log}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_info": None,
            "curve": curve, "gate_log": gate_log}


def run_pot_v9_cadence(pb, decisions, sel_dates, start, end, start_cash=100.0):
    """run_pot_v9 generalized: restart at the next CADENCE date >= liq+90d."""
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_pot_cadence(pb, decisions, sel_dates, start, end, start_cash,
                         floor1)
    out = {"final": r1["final"], "costs": r1["costs"],
           "orders": len(r1["trades"]), "curve": list(r1["curve"]),
           "halted": r1["halted"], "halt_info": r1["halt_info"],
           "gate_log": list(r1["gate_log"]),
           "restarts": [], "second_halt": None, "episodes": 1,
           "ep1_final": r1["final"], "ep1_end": r1["end"]}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _date(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in sel_dates:
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _date(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": r1["halted"],
        "liquidation_date": liq_date,
        "halt_signal_close": r1["halt_info"]["signal_close"],
        "restart_date": restart,
        "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    r2 = run_pot_cadence(pb, decisions, sel_dates, restart, end, cash, floor2)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["orders"] += len(r2["trades"])
    out["curve"] += list(r2["curve"])
    out["gate_log"] += list(r2["gate_log"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


# ------------------------------------------------------------------ stats
def max_dd(curve):
    peak, mdd, mdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > mdd:
            mdd, mdd_d = dd, d
    return round(mdd * 100, 2), mdd_d


def cagr_pct(final, start, end):
    days = (_date(int(end[:4]), int(end[5:7]), int(end[8:10])) -
            _date(int(start[:4]), int(start[5:7]), int(start[8:10]))).days
    years = days / 365.25
    return round(((final / 100.0) ** (1.0 / years) - 1.0) * 100, 2)


def spy_curve_stats(pb, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (100.0 / 1.001) / o
    curve = []
    for d in days:
        c = pb.close_on_or_before("SPY", d)
        curve.append((d, sh * c))
    net, _ = E.spy_net(pb, start, end, 100.0)
    mdd, mdd_d = max_dd(curve)
    return {"final": round(net, 2), "max_dd_pct": mdd, "max_dd_date": mdd_d}


# ------------------------------------------------------------------- main
def main():
    t0 = time.time()
    report = {"slug": "vm-trendgate"}

    # ---------------- INTEGRITY (original plumbing, original form) -------
    pb_o, eq_o, so_o = V9.build_inputs()
    print("integrity inputs built", flush=True)
    rc_his = V9.run_pot_gated(pb_o, eq_o, so_o, CONT[0], CONT[1], 100.0,
                              85.0, [], label="INTEGRITY CONT HIS", quiet=True)
    rv_his = V9.run_pot_gated(pb_o, eq_o, so_o, VAL[0], VAL[1], 100.0,
                              85.0, [], label="INTEGRITY VAL HIS", quiet=True)
    print(f"INTEGRITY CONT his-rules: final=${rc_his['final']:.2f} "
          f"halted={rc_his['halted']} (target $79.36, 2020-03-20)", flush=True)
    print(f"INTEGRITY VAL  his-rules: final=${rv_his['final']:.2f} "
          f"halted={rv_his['halted']} (target $163.79, None)", flush=True)
    rc_v9 = V9.run_pot_v9(pb_o, eq_o, so_o, CONT[0], CONT[1], 100.0,
                          label="INTEGRITY CONT V9")
    print(f"INTEGRITY CONT v9: final=${rc_v9['final']:.2f} "
          f"(v9 sweep reference $183.09)", flush=True)
    ok_cont = abs(rc_his["final"] - 79.36) < 0.02 and rc_his["halted"] == "2020-03-20"
    ok_val = abs(rv_his["final"] - 163.79) < 0.02 and rv_his["halted"] is None
    ok_v9 = abs(rc_v9["final"] - 183.09) < 0.02
    report["integrity_check"] = {
        "cont_his_final": round(rc_his["final"], 2),
        "cont_his_halted": rc_his["halted"],
        "val_his_final": round(rv_his["final"], 2),
        "val_his_halted": rv_his["halted"],
        "cont_v9_final": round(rc_v9["final"], 2),
        "cont_ok": ok_cont, "val_ok": ok_val, "v9_ok": ok_v9}
    assert ok_cont and ok_val, "INTEGRITY GATE FAILED - see integrity_check"

    # cross-check: my cadence engine at quarterly on the ORIGINAL book must
    # reproduce the v9 CONT number through the generalized wrapper too.
    fb_o = FastBook(pb_o)
    q_dates_o = cadence_dates(pb_o, "quarterly", CONT[0], CONT[1])
    dec_o = precompute_decisions(fb_o, eq_o, so_o, q_dates_o)
    chk = run_pot_v9_cadence(pb_o, dec_o, q_dates_o, CONT[0], CONT[1], 100.0)
    print(f"ENGINE CROSS-CHECK quarterly/CONT/v9 on original book: "
          f"${chk['final']:.2f} (expect $183.09)", flush=True)
    report["integrity_check"]["engine_crosscheck_quarterly_cont_v9"] = \
        round(chk["final"], 2)

    # ---------------- SWEEP (full-history book, DECADE) ------------------
    pb, eq, so = build_inputs_full()
    fb = FastBook(pb)
    print(f"sweep inputs built ({time.time()-t0:.0f}s); SPY bars "
          f"{pb.bars['SPY'][0]['d']} -> {pb.bars['SPY'][-1]['d']}", flush=True)
    spy = spy_curve_stats(pb, DECADE[0], DECADE[1])
    print(f"SPY DECADE: final=${spy['final']} maxDD={spy['max_dd_pct']}% "
          f"on {spy['max_dd_date']}", flush=True)
    report["decade_spy"] = spy

    cells = {}
    for cad in CADENCES:
        tc = time.time()
        sel = cadence_dates(pb, cad, DECADE[0], DECADE[1])
        dec = precompute_decisions(fb, eq, so, sel)
        r = run_pot_v9_cadence(pb, dec, sel, DECADE[0], DECADE[1], 100.0)
        mdd, mdd_d = max_dd(r["curve"])
        halts = (1 if r["halted"] else 0) + (1 if r["second_halt"] else 0)
        # placebos (same v9 protections, seeds 1..20)
        twins = []
        for seed in PLACEBO_SEEDS:
            pr = run_placebo(pb, dec, sel, DECADE[0], DECADE[1], seed)
            twins.append(pr)
        twin_finals = [round(x["final"], 2) for x in twins]
        beaten = sum(1 for f in twin_finals if f < r["final"])
        cell = {
            "cadence": cad, "start": DECADE[0], "end": DECADE[1],
            "final": round(r["final"], 2),
            "cagr_pct": cagr_pct(r["final"], DECADE[0], DECADE[1]),
            "max_dd_pct": mdd, "max_dd_date": mdd_d,
            "costs": round(r["costs"], 2), "orders": r["orders"],
            "halts": halts,
            "halt_ep1": ({"signal_date": r["halted"],
                          "signal_close": r["halt_info"]["signal_close"],
                          "floor_in_effect": r["halt_info"]["floor_in_effect"],
                          "liquidation_date": r["ep1_end"]}
                         if r["halted"] else None),
            "restarts": r["restarts"],
            "second_halt": r["second_halt"],
            "episodes": r["episodes"],
            "n_selection_dates": len(sel),
            "quarters_off_total": sum(1 for g in r["gate_log"]
                                      if g["gate_on"] is False),
            "placebo_beaten": beaten,
            "placebo_twin_finals": twin_finals,
            "placebo_twins": twins,
            "equity_curve": [[d, round(v, 2)] for d, v in r["curve"]],
            "gate_log": r["gate_log"],
        }
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1, default=str)
        cells[cad] = {k: cell[k] for k in
                      ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
                       "halts", "placebo_beaten")}
        cells[cad]["restart"] = bool(r["restarts"])
        cells[cad]["second_halt"] = bool(r["second_halt"])
        print(f"[{cad}] final=${r['final']:.2f} CAGR={cell['cagr_pct']}% "
              f"maxDD={mdd}% costs=${r['costs']:.2f} orders={r['orders']} "
              f"halts={halts} placebo beaten {beaten}/20 "
              f"({time.time()-tc:.0f}s)", flush=True)

    report["cells_summary"] = cells
    report["spy"] = spy
    with open(os.path.join(HERE, "sweep-raw.json"), "w") as f:
        json.dump(report, f, indent=1, default=str)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)


def run_placebo(pb, decisions, sel_dates, start, end, seed):
    """One placebo pot under v9 protections (wrapper mirror with rng)."""
    rng = random.Random(seed)
    floor1 = 85.0
    r1 = run_pot_cadence(pb, decisions, sel_dates, start, end, 100.0,
                         floor1, placebo_rng=rng)
    out = {"seed": seed, "final": r1["final"], "costs": r1["costs"],
           "orders": len(r1["trades"]), "halted": r1["halted"],
           "restarts": [], "second_halt": None}
    if r1["halted"] is None:
        out["final"] = round(r1["final"], 2)
        out["costs"] = round(r1["costs"], 2)
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _date(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in sel_dates:
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _date(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
    if restart is None:
        out["final"] = round(cash, 2)
        out["costs"] = round(r1["costs"], 2)
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({"halt_signal_date": r1["halted"],
                            "liquidation_date": liq_date,
                            "restart_date": restart,
                            "restart_balance": round(cash, 2)})
    r2 = run_pot_cadence(pb, decisions, sel_dates, restart, end, cash,
                         floor2, placebo_rng=rng)
    out["final"] = round(r2["final"], 2)
    out["costs"] = round(r1["costs"] + r2["costs"], 2)
    out["orders"] = len(r1["trades"]) + len(r2["trades"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "liquidation_date": r2["end"]}
    return out


if __name__ == "__main__":
    main()
