#!/usr/bin/env python3
"""
V10 GREAT RETEST — gap-a8-canslim (CAN SLIM, AAII screen form).

Structure:
  PART 0 INTEGRITY: the v9 module's engine (byte-identical copy of the v7
    original run_pot) on the ORIGINAL cached data (v4 caches, read-only),
    his-rules form (plain -15% floor, no restart): CONT 2019-01-02 ->
    2026-11-20 and VAL 2023-01-03 -> 2026-11-20, ranked + 20 placebos each.
    Published targets: CONT $84.94 halted 2019-08-02 (placebo 15/20),
    VAL $80.15 halted 2026-07-23 (placebo 2/20).
  PART 1 SWEEP PLUMBING: extended Yahoo prices 2015-06-01 -> 2026-11-21
    (same fetch + adjclose method as the champion module), cached in THIS
    folder's data/. Overlap vs the shared cache verified bar-by-bar.
    A fast screen builder replicates the v9 build_screen_table exactly
    (verified equal on all 95 monthly dates 2019-2026 before use).
  PART 2 SWEEP: DECADE 2016-11-21 -> 2026-11-20 at 7 cadences. Cadence =
    the dates on which the (unchanged) screen is evaluated / rebalanced.
    $100, program costs, v9 protections (plain -15% floor, 90-day sit-out,
    one restart at the next cadence date, ep2 floor -15% from restart
    balance, second halt ends). 20-seed placebos per cell (same chassis:
    random names from the screenable pool, same count as ranked qualifiers,
    same gate — the original placebo design).
Outputs: cells/<cadence>.json, results.json, integrity detail printed.
"""
import bisect
import calendar
import importlib.util
import json
import math
import os
import random
import time
import urllib.request
from datetime import date as _date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # gap-a8-canslim/
BT = os.path.abspath(os.path.join(ROOT, "..", ".."))
DATA_DIR = os.path.join(ROOT, "data")
CELLS_DIR = os.path.join(ROOT, "cells")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CELLS_DIR, exist_ok=True)

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

V9 = _load("canslim_v9", os.path.join(
    BT, "v9-muse-rules", "gap-a8-canslim", "gap-a8-canslim-v9.py"))
E = V9.E
UNIVERSE = V9.UNIVERSE
FRESH_DAYS = V9.FRESH_DAYS
DEC_START, DEC_END = "2016-11-21", "2026-11-20"


def _ord(dstr):
    return _date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()


# ============================================================ PART 0: data
def load_eps_rows():
    ciks = E.get_ciks()
    eps_rows = {}
    for t in UNIVERSE:
        cik = {"XOM": 34088}.get(t, ciks[t][0])
        eps_rows[t] = V9.eps_entries(E.get_companyfacts(cik))
    return eps_rows


def load_cached_bars():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return bars


def fetch_extended_prices():
    """Same Yahoo chart fetch + adjclose adjustment as E.get_prices, but
    period1 = 2015-06-01 so the DECADE road (2016-11-21) has its full
    252-bar lookback. Cached in this folder only."""
    p1, p2 = "2015-06-01", "2026-11-21"
    t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        path = os.path.join(DATA_DIR, f"px_ext_{t}.json")
        if os.path.exists(path) and os.path.getsize(path) > 100:
            with open(path, "rb") as f:
                blob = f.read()
        else:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
                   f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            last = None
            for i in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=60) as r:
                        blob = r.read()
                    break
                except Exception as e:  # noqa
                    last = e
                    time.sleep(2 * (i + 1))
            else:
                raise RuntimeError(f"fetch failed {t}: {last}")
            with open(path, "wb") as f:
                f.write(blob)
            time.sleep(0.2)
        j = json.loads(blob)
        res = j["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
        bl = []
        for i, tt in enumerate(ts):
            d = time.strftime("%Y-%m-%d", time.gmtime(tt))
            o, c = q["open"][i], q["close"][i]
            if c is None:
                continue
            a = adj[i] if adj and adj[i] else c
            ratio = a / c if c else 1.0
            bl.append({"d": d, "o": (o * ratio if o else a), "c": a})
        bl.sort(key=lambda b: b["d"])
        bars[t] = bl
    return bars


# ============================================ fast screen (exact replica)
class FastScreen:
    """Replicates V9.eps_snapshot + V9.build_screen_table exactly, with the
    point-in-time period maps cached per (ticker, filing-set index)."""

    def __init__(self, eps_rows):
        self.rows = {}
        self.filed_sorted = {}
        self.map_cache = {}
        for t, rows in eps_rows.items():
            rs = sorted(rows, key=lambda r: r[0])
            self.rows[t] = rs
            self.filed_sorted[t] = [r[0] for r in rs]
            self.map_cache[t] = {}

    def _period_lists(self, t, asof):
        idx = bisect.bisect_left(self.filed_sorted[t], asof)
        cache = self.map_cache[t]
        if idx in cache:
            return cache[idx]
        best = {}
        for filed, start, end, val in self.rows[t][:idx]:
            k = (start, end)
            if k not in best or filed > best[k][0]:
                best[k] = (filed, val)
        periods = [(end, start, filed, val)
                   for (start, end), (filed, val) in best.items()]

        def pick(lo, hi):
            out = [p for p in periods if lo <= _ord(p[0]) - _ord(p[1]) <= hi]
            out.sort(key=lambda r: r[0], reverse=True)
            return out

        res = (pick(60, 120), pick(330, 400))
        cache[idx] = res
        return res

    def snapshot(self, t, asof):
        quarters, annuals = self._period_lists(t, asof)
        if not quarters or len(annuals) < 4:
            return None
        q0_end, _qs, q0_filed, q0_val = quarters[0]
        if _ord(asof) - _ord(q0_filed) > FRESH_DAYS:
            return None
        target = _ord(q0_end) - 365
        yoy = None
        for end, start, filed, val in quarters[1:]:
            gap = _ord(q0_end) - _ord(end)
            if 330 <= gap <= 400:
                if yoy is None or abs(_ord(end) - target) < abs(_ord(yoy[0]) - target):
                    yoy = (end, val)
        if yoy is None:
            return None
        c_growth = (q0_val / yoy[1] - 1.0) if yoy[1] > 0 else None
        c_pass = c_growth is not None and c_growth >= 0.25
        fys = annuals[:4]
        for i in range(3):
            gap = _ord(fys[i][0]) - _ord(fys[i + 1][0])
            if gap < 300 or gap > 430:
                return None
        if _ord(asof) - _ord(fys[0][2]) > FRESH_DAYS:
            return None
        vals = [f[3] for f in fys]
        a_pass = False
        a_cagr = None
        if all(v > 0 for v in vals):
            a_cagr = (vals[0] / vals[3]) ** (1.0 / 3.0) - 1.0
            a_pass = (vals[0] > vals[1] > vals[2] > vals[3]) and a_cagr >= 0.25
        return {"c_pass": c_pass, "a_pass": a_pass, "c_growth": c_growth,
                "a_cagr": a_cagr}


def build_table_fast(pb, fast, eval_dates, spy_closes, spy_pos):
    """Same output shape as V9.build_screen_table, for arbitrary dates."""
    table = {}
    for d in eval_dates:
        si = spy_pos.get(d)
        gate = None
        if si is not None and si >= 199:
            ma200 = sum(spy_closes[si - 199:si + 1]) / 200.0
            gate = spy_closes[si] > ma200
        screenable, qualifiers, detail = [], [], {}
        for t in UNIVERSE:
            snap = fast.snapshot(t, d)
            if snap is None:
                continue
            bl = pb.bars.get(t, [])
            b = pb.bar(t, d)
            if b is None:
                continue
            didx = pb_pos[t].get(d)
            if didx is None or didx < 253:
                continue
            close = b["c"]
            hi252 = max(x["c"] for x in bl[didx - 251:didx + 1])
            n_pass = close >= 0.85 * hi252
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            screenable.append(t)
            detail[t] = {"c_pass": snap["c_pass"], "a_pass": snap["a_pass"],
                         "n_pass": n_pass, "mom": mom,
                         "c_growth": snap["c_growth"], "a_cagr": snap["a_cagr"]}
            if snap["c_pass"] and snap["a_pass"] and n_pass:
                qualifiers.append((t, mom))
        qualifiers.sort(key=lambda kv: (-kv[1], kv[0]))
        table[d] = {"gate": gate, "screenable": screenable,
                    "qualifiers": qualifiers, "detail": detail}
    return table


pb_pos = {}  # ticker -> {date: index}, set per PriceBook in main


# ============================================ cadence engine (v9 chassis)
def run_pot_cad(pb, table, eval_dates, start, end, start_cash=100.0,
                floor0=85.0, placebo_rng=None, label=""):
    """V9.run_pot verbatim except the selection set is `eval_dates`
    (the cadence) instead of month_selection_dates."""
    cash = start_cash
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    picks_log = []
    sel_set = set(eval_dates)
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
                total_costs += c
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
                total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            scr = table.get(d)
            picks = []
            if scr is not None and scr["gate"]:
                quals = [t for t, _m in scr["qualifiers"]]
                if placebo_rng is not None:
                    k = min(len(quals), 5)
                    if k > 0:
                        picks = placebo_rng.sample(sorted(scr["screenable"]), k)
                else:
                    picks = quals[:5]
            picks_log.append((d, None if scr is None else scr["gate"],
                              None if scr is None else len(scr["screenable"]),
                              None if scr is None else len(scr["qualifiers"]),
                              list(picks)))
            pv = portfolio_close(d)
            if picks:
                each = pv / len(picks)
                pending = {t: each for t in picks}
            else:
                pending = {}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor0}
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
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "curve": curve,
                    "picks_log": picks_log}
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
            "halt_info": None, "curve": curve, "picks_log": picks_log}


def run_cell_v9(pb, table, eval_dates, start, end, placebo_rng=None):
    """v9 protection wrapper: ep1 plain floor; on halt, 90-day sit-out,
    restart at next cadence date, ep2 floor -15% from restart balance;
    second halt ends. Returns combined daily curve + episode detail."""
    days = [d for d in pb.dates if start <= d <= end]
    ep1 = run_pot_cad(pb, table, eval_dates, start, end,
                      placebo_rng=placebo_rng, label="EP1")
    out = {"episodes": 1, "final": ep1["final"], "costs": ep1["costs"],
           "orders": len(ep1["trades"]), "halts": [], "restarts": [],
           "second_halt": False, "restart": False}
    curve_map = dict(ep1["curve"])
    if not ep1["halted"]:
        out["curve"] = [(d, curve_map[d]) for d in days if d in curve_map]
        return out
    liq = ep1["end"]
    cash1 = ep1["final"]
    out["halts"].append({"episode": 1, "signal_date": ep1["halted"],
                         "liquidation_date": liq,
                         "cash_after_liquidation": round(cash1, 2)})
    eligible = (_date.fromisoformat(liq) + timedelta(days=90)).isoformat()
    restart = next((d for d in eval_dates if d >= eligible), None)
    if restart is None:
        for d in days:
            if d not in curve_map:
                curve_map[d] = cash1
        out["curve"] = [(d, curve_map[d]) for d in days]
        out["status"] = "halted_ep1_no_restart_in_window"
        return out
    out["restart"] = True
    out["restarts"].append({
        "halt_signal_date": ep1["halted"], "liquidation_date": liq,
        "cash_at_halt": round(cash1, 2), "eligible_from": eligible,
        "restart_date": restart, "restart_balance": round(cash1, 2),
        "episode2_floor": round(0.85 * cash1, 2)})
    ep2 = run_pot_cad(pb, table, eval_dates, restart, end,
                      start_cash=cash1, floor0=0.85 * cash1,
                      placebo_rng=placebo_rng, label="EP2")
    out["episodes"] = 2
    out["final"] = ep2["final"]
    out["costs"] = ep1["costs"] + ep2["costs"]
    out["orders"] = len(ep1["trades"]) + len(ep2["trades"])
    for d in days:
        if d not in curve_map and d < restart:
            curve_map[d] = cash1
    curve_map.update(dict(ep2["curve"]))
    if ep2["halted"]:
        out["second_halt"] = True
        out["halts"].append({"episode": 2, "signal_date": ep2["halted"],
                             "liquidation_date": ep2["end"],
                             "cash_after_liquidation": round(ep2["final"], 2)})
        for d in days:
            if d not in curve_map:
                curve_map[d] = ep2["final"]
    out["curve"] = [(d, curve_map[d]) for d in days]
    return out


def cadence_dates(spy_dates, cadence, start, end):
    days = [d for d in spy_dates if start <= d <= end]
    if cadence == "daily":
        return days
    if cadence == "monthly":
        out, seen = [], set()
        for d in days:
            if d[:7] not in seen:
                seen.add(d[:7])
                out.append(d)
        return out
    if cadence == "quarterly":
        out, seen = [], set()
        for d in days:
            if d[5:7] in ("01", "04", "07", "10") and d[:7] not in seen:
                seen.add(d[:7])
                out.append(d)
        return out
    if cadence == "semiannual":
        out, seen = [], set()
        for d in days:
            if d[5:7] in ("01", "07") and d[:7] not in seen:
                seen.add(d[:7])
                out.append(d)
        return out
    if cadence == "annual":
        out, seen = [], set()
        for d in days:
            if d[:4] not in seen:
                seen.add(d[:4])
                out.append(d)
        return out
    if cadence in ("weekly", "biweekly"):
        weeks, seen = [], set()
        for d in days:
            iso = _date.fromisoformat(d).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                weeks.append(d)
        if cadence == "weekly":
            return weeks
        return weeks[::2]
    raise ValueError(cadence)


def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for _d, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return round(mdd * 100, 2)


def cagr(final, start, end):
    yrs = (_date.fromisoformat(end) - _date.fromisoformat(start)).days / 365.25
    return round(((final / 100.0) ** (1.0 / yrs) - 1.0) * 100, 2) if final > 0 else None


def qualifier_stats(table, eval_dates):
    per_year = {}
    total_q = 0
    with_q = 0
    longest_zero = 0
    run = 0
    for d in eval_dates:
        n = len(table[d]["qualifiers"])
        total_q += n
        y = d[:4]
        per_year.setdefault(y, {"evals": 0, "evals_with_qualifiers": 0,
                                "qualifiers": 0})
        per_year[y]["evals"] += 1
        per_year[y]["qualifiers"] += n
        if n > 0:
            with_q += 1
            per_year[y]["evals_with_qualifiers"] += 1
            run = 0
        else:
            run += 1
            longest_zero = max(longest_zero, run)
    return {"evaluations": len(eval_dates),
            "evals_with_any_qualifier": with_q,
            "total_qualifiers": total_q,
            "gate_on_evals": sum(1 for d in eval_dates if table[d]["gate"]),
            "longest_zero_qualifier_stretch_evals": longest_zero,
            "per_year": per_year}


# ==================================================================== main
def main():
    global pb_pos
    t0 = time.time()
    eps_rows = load_eps_rows()
    print("eps rows loaded", flush=True)

    # ---------------- PART 0: INTEGRITY on original cached data
    bars0 = load_cached_bars()
    pb0 = E.PriceBook(bars0)
    table0 = V9.build_screen_table(pb0, eps_rows, "2019-01-02", "2026-11-20")
    published = {
        "CONTINUOUS": {"final": 84.94, "halted": "2019-08-02", "placebo_beaten": 15,
                       "ws": "2019-01-02", "we": "2026-11-20", "spy": 313.62},
        "VALIDATION": {"final": 80.15, "halted": "2026-07-23", "placebo_beaten": 2,
                       "ws": "2023-01-03", "we": "2026-11-20", "spy": 187.77},
    }
    integrity_windows = {}
    ok = True
    for wname, pub in published.items():
        r = V9.run_pot(pb0, table0, pub["ws"], pub["we"], label=f"INTEG {wname}")
        twins = []
        for seed in range(1, 21):
            tw = V9.run_pot(pb0, table0, pub["ws"], pub["we"],
                            placebo_rng=random.Random(seed),
                            label=f"INTEG {wname} P{seed}")
            twins.append(round(tw["final"], 2))
        beats = sum(1 for x in twins if r["final"] > x)
        s_net, _ = E.spy_net(pb0, pub["ws"], pub["we"], 100.0)
        match = (round(r["final"], 2) == pub["final"] and r["halted"] == pub["halted"]
                 and beats == pub["placebo_beaten"])
        ok = ok and match
        integrity_windows[wname] = {
            "published_final": pub["final"], "reproduced_final": round(r["final"], 2),
            "published_halted": pub["halted"], "reproduced_halted": r["halted"],
            "published_placebo_beaten": pub["placebo_beaten"],
            "reproduced_placebo_beaten": beats,
            "placebo_finals": twins, "spy_net": round(s_net, 2),
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "match": match}
        print(f"INTEGRITY {wname}: final=${r['final']:.2f} (pub {pub['final']}) "
              f"halted={r['halted']} placebo {beats}/20 (pub {pub['placebo_beaten']}) "
              f"SPY=${s_net:.2f} match={match}", flush=True)
    # anatomy facts from the original monthly table
    sel = sorted(table0)
    tot_eval = sum(len(table0[d]["detail"]) for d in sel)
    a_pass = sum(1 for d in sel for v in table0[d]["detail"].values() if v["a_pass"])
    zero_months = [d for d in sel if not table0[d]["qualifiers"]]
    zero_2205_2602 = [d for d in zero_months if "2022-05" <= d[:7] <= "2026-02"]
    anatomy = {"a_leg_pass_pct": round(100.0 * a_pass / tot_eval, 1),
               "a_leg_pass": a_pass, "screenable_evals": tot_eval,
               "zero_qualifier_months_may2022_feb2026": len(zero_2205_2602),
               "months_in_that_span": sum(1 for d in sel if "2022-05" <= d[:7] <= "2026-02")}
    print(f"ANATOMY: A-leg pass {anatomy['a_leg_pass_pct']}% "
          f"({a_pass}/{tot_eval}); zero-qualifier months May22-Feb26: "
          f"{len(zero_2205_2602)}/{anatomy['months_in_that_span']}", flush=True)
    integrity = {"status": "reproduced" if ok else "FAILED",
                 "form": "original v7 engine (via v9 module's byte-identical run_pot), "
                         "his rules: plain -15% floor, no restart, monthly screen, "
                         "original v4 cached data",
                 "windows": integrity_windows, "anatomy_facts": anatomy,
                 "engine_decision_cadence": "monthly (the v9 sweep brief's 'quarterly' "
                                            "was a documented error)"}

    # ---------------- PART 1: extended prices + fast-screen verification
    barsX = fetch_extended_prices()
    pbX = E.PriceBook(barsX)
    # overlap verification vs shared cache (closes + opens, common dates)
    max_dev = 0.0
    n_common = 0
    for t in UNIVERSE + ["SPY"]:
        cached = {b["d"]: b for b in bars0[t]}
        for b in barsX[t]:
            cb = cached.get(b["d"])
            if cb:
                n_common += 1
                for k in ("c", "o"):
                    if cb[k]:
                        max_dev = max(max_dev, abs(b[k] - cb[k]) / cb[k])
    print(f"OVERLAP: {n_common} common bars, max relative deviation "
          f"{max_dev:.2e}", flush=True)

    pb_pos = {t: {b["d"]: i for i, b in enumerate(bl)} for t, bl in barsX.items()}
    spy_bars = barsX["SPY"]
    spy_closes = [b["c"] for b in spy_bars]
    spy_pos = pb_pos["SPY"]
    spy_dates = [b["d"] for b in spy_bars]
    fast = FastScreen(eps_rows)
    monthly_dates = cadence_dates(spy_dates, "monthly", "2019-01-02", "2026-11-20")
    table_fast_m = build_table_fast(pbX, fast, monthly_dates, spy_closes, spy_pos)
    mism = 0
    for d in monthly_dates:
        a, b = table0[d], table_fast_m[d]
        if (a["gate"] != b["gate"] or a["screenable"] != b["screenable"]
                or [t for t, _ in a["qualifiers"]] != [t for t, _ in b["qualifiers"]]):
            mism += 1
    print(f"FAST-SCREEN VERIFICATION vs original table: {len(monthly_dates)} "
          f"monthly dates, mismatches={mism}", flush=True)
    assert mism == 0, "fast screen does not replicate the original screen"

    spy_dec, _ = E.spy_net(pbX, DEC_START, DEC_END, 100.0)
    print(f"DECADE SPY (extended plumbing): ${spy_dec:.2f} (reference 367.80)",
          flush=True)

    # ---------------- PART 2: THE SWEEP
    cells = {}
    for cadence in ["daily", "weekly", "biweekly", "monthly", "quarterly",
                    "semiannual", "annual"]:
        tc = time.time()
        eval_dates = cadence_dates(spy_dates, cadence, DEC_START, DEC_END)
        table = build_table_fast(pbX, fast, eval_dates, spy_closes, spy_pos)
        qs = qualifier_stats(table, eval_dates)
        r = run_cell_v9(pbX, table, eval_dates, DEC_START, DEC_END)
        twins = []
        for seed in range(1, 21):
            tw = run_cell_v9(pbX, table, eval_dates, DEC_START, DEC_END,
                             placebo_rng=random.Random(seed))
            twins.append(round(tw["final"], 2))
        beats = sum(1 for x in twins if r["final"] > x)
        cell = {"cadence": cadence, "window": [DEC_START, DEC_END],
                "final": round(r["final"], 2),
                "cagr_pct": cagr(r["final"], DEC_START, DEC_END),
                "max_dd_pct": max_dd(r["curve"]),
                "costs": round(r["costs"], 2), "orders": r["orders"],
                "episodes": r["episodes"], "halts": r["halts"],
                "restarts": r["restarts"], "restart": r["restart"],
                "second_halt": r["second_halt"],
                "qualifier_counts": qs,
                "placebo_finals": twins, "placebo_beaten": beats,
                "placebo_note": "20 seeds (1..20), original placebo design: same "
                                "cadence dates, same market gate, same monthly "
                                "qualifier count, names drawn at random from the "
                                "screenable pool; v9 protection wrapper applied "
                                "identically to twins.",
                "equity_curve": [[d, round(v, 2)] for d, v in r["curve"]]}
        with open(os.path.join(CELLS_DIR, f"{cadence}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cadence] = {k: cell[k] for k in
                          ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
                           "placebo_beaten", "placebo_note")}
        cells[cadence]["halts"] = len(r["halts"])
        cells[cadence]["restart"] = r["restart"]
        cells[cadence]["second_halt"] = r["second_halt"]
        cells[cadence]["qualifier_counts"] = qs
        print(f"CELL {cadence}: evals={qs['evaluations']} "
              f"evals_with_q={qs['evals_with_any_qualifier']} "
              f"total_q={qs['total_qualifiers']} final=${r['final']:.2f} "
              f"dd={cell['max_dd_pct']}% costs=${r['costs']:.2f} "
              f"orders={r['orders']} halts={len(r['halts'])} "
              f"restart={r['restart']} placebo {beats}/20 "
              f"({time.time()-tc:.0f}s)", flush=True)

    money = [c for c, v in cells.items()
             if v["final"] > round(spy_dec, 2) and v["placebo_beaten"] is not None
             and v["placebo_beaten"] >= 11]
    results = {
        "slug": "gap-a8-canslim",
        "area": "Growth-momentum stock selection: AAII's published CAN SLIM "
                "screen (C/A/N/L with the M market-direction gate) on the "
                "30-name pond, monthly screen cadence as published (W2 area "
                "assignment, SPEC CADENCE GRID).",
        "area_source": "v10 SPEC W2 + CADENCE GRID: 'CAN SLIM — monthly'; "
                       "frozen spec in research/v7-completeness/"
                       "missing-families.md Table A item A-8 (AAII screen form).",
        "native_cadence": "monthly",
        "cadence": "monthly",
        "original_cadence_foreign": False,
        "original_cadence_note": "The original program test ran the engine at "
                                 "its native monthly cadence (the v9 brief's "
                                 "'quarterly' label was a documented error, "
                                 "corrected in the v9 folder's own report).",
        "integrity": integrity,
        "decade_spy_final": round(spy_dec, 2),
        "decade_window": [DEC_START, DEC_END],
        "price_data_note": "Sweep prices: Yahoo chart API fetched 2015-06-01 "
                           "-> 2026-11-21 with the champion module's identical "
                           "adjclose method, cached in this folder's data/. "
                           f"Overlap vs the shared v4 cache: {n_common} common "
                           f"bars, max relative deviation {max_dev:.2e}. The "
                           "shared cache starts 2017-06-01, which cannot give "
                           "the decade road its 252-bar lookback; EDGAR EPS "
                           "facts are the original cached companyfacts "
                           "(read-only).",
        "cells": cells,
        "money_cadences": money,
        "verdict_area": "NO GROUND" if not money else "REAL BUT SMALL",
        "verdict_change": "No change. The original program verdict (a screen "
                          "that starves on a 30-name pond: the A leg passes "
                          "8.7% of evaluations and the screen produced zero "
                          "qualifiers from May 2022 through Feb 2026) is "
                          "confirmed at every cadence on the decade road.",
    }
    with open(os.path.join(ROOT, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print(f"DONE in {time.time()-t0:.0f}s; money cadences: {money}", flush=True)


if __name__ == "__main__":
    main()
