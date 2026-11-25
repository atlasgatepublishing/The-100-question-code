#!/usr/bin/env python3
"""
GAP TEST A-8 — CAN SLIM (AAII SCREEN FORM) — Terry's AI stock app.
Simulation only. NO parameter tuning: the frozen spec below is run ONCE,
exactly as specified in research/v7-completeness/missing-families.md
(Table A, item A-8), and judged against the promoted champion's published
numbers (value + momentum: validation $288.05, continuous $544.47,
placebo 18/20 and 19/20, folds 4 of 7).

THE FAMILY: O'Neil, "How to Make Money in Stocks" (4th ed., 2009);
AAII's O'Neil CAN SLIM screens, tracked since 1998 (the No-Float variant:
+13.4%/yr since inception vs +7.3% S&P 500 per AAII — hypothetical,
gross of costs). The most widely followed named composite in practitioner
literature; never enumerated in the program's census of 85.

THE FROZEN SPEC (missing-families.md A-8, verbatim substance):
  Monthly screen on the honest top-30 pond as of Nov 2016, transcribing
  AAII's published screen criteria and freezing them:
    C — current quarterly EPS up >= +25% YoY (EDGAR point-in-time EPS).
    A — annual EPS growth per AAII (see FORCED READINGS for the exact
        published form frozen here).
    N — price within 15% of the 52-week high.
    L — top-5 of qualifiers by 12-1 momentum as the relative-strength
        proxy (SUBSTITUTION stated in the spec: IBD's relative-strength
        rank is proprietary; 12-1 momentum is the program's ruler).
    S — dropped, as in AAII's own No-Float variant (per spec).
    M — SPY above its 200-day average, the mechanical residue of
        O'Neil's market rule (per spec).
  Hold qualifiers equal-weight (cap 5). Explicitly excluded as
  non-mechanical (per spec): cup-with-handle base entries; the book's
  7-8% discretionary stop is replaced by the program floor.

HOUSE CHASSIS (identical to the champion's):
  - $100 pot; costs 0.10% of trade value per side + $0.01 per sell order.
  - PLAIN -15% floor ($85): close at/below floor -> liquidate at next
    open, run ends.
  - Windows: CONTINUOUS 2019-01-02 -> 2026-11-20 and VALIDATION
    2023-01-03 -> 2026-11-20. SPY buy-hold net on the same chassis
    ($313.62 / $187.77 published).
  - Selection on the first trading day of each month; decisions use only
    data FILED strictly before that day; rebalance executes at the next
    open (the champion engine's mechanics).
  - Placebos: 20 seeds (1..20), same dates, same market gate, same
    holding count as the ranked pot that month, names drawn at random
    from the SCREENABLE pool (names with complete point-in-time data to
    be screened that month) — the champion/piotroski placebo pattern.

FORCED READINGS (stated BEFORE results; documented, not tuned):
  R1. EPS CONCEPT. AAII screens on diluted EPS from continuing
      operations. EDGAR companyfacts carries no uniform
      continuing-operations EPS concept across all 30 pond names; the
      one concept every pond name files is us-gaap
      EarningsPerShareDiluted. It is used for all names, for both C
      and A. (JPMorgan additionally files pro-forma continuing-ops
      per-share concepts for acquisitions only — not a screen input.)
  R2. QUARTER DEFINITION (C). A "quarter" is a filed EPS period of
      60-120 days' duration. The current quarter is the quarter with
      the latest period END among values filed strictly before the
      selection date; for each period the latest filing before the
      selection date wins (restatements enter only once filed, and
      both the current and year-ago values are read on that same
      as-filed basis, so split restatements apply consistently). The
      year-ago quarter is the filed quarter ending 330-400 days before
      the current quarter's end (nearest to 365). C passes iff
      year-ago EPS > 0 and current/year-ago - 1 >= 0.25 (a percentage
      change off a non-positive base is not AAII's number; with a
      positive base and +25% growth the current EPS is positive
      automatically, which also covers AAII's positive-current-EPS
      line). House freshness gate: the current quarter must have been
      FILED within 548 days of the selection date.
  R3. ANNUAL FORM (A). AAII's published criteria carry two annual
      lines, both frozen here: (i) annual EPS "increased in each of
      the last three years" (AAII 4th-edition criteria list; the
      Stock Investor Pro screen specified EPS higher each year vs the
      previous year), and (ii) "average annual earnings growth of at
      least 25% over the last three years" (AAII's revised-screen
      requirement, verbatim). Frozen form: the four most recent fiscal
      years (filed periods of 330-400 days, consecutive year-ends
      300-430 days apart, latest filed within 548 days) must ALL have
      EPS > 0, each year strictly greater than the year before, AND
      the 3-year compound growth (FY0/FY3)^(1/3) - 1 >= 0.25.
  R4. NOT IN THE FROZEN SPEC — EXCLUDED, on the record: O'Neil's
      earnings-acceleration preference and the >=25% quarterly sales
      confirmation (both appear in AAII's fuller prose; the frozen
      spec transmitted for this test freezes C at the >=+25% YoY line
      and names no sales leg); I (institutional sponsorship — not in
      the spec's operational line and not point-in-time rebuildable
      from free EDGAR data); ROE >= 17% (a secondary characteristic
      in AAII's list, not part of the tracked screen's frozen lines
      transmitted here).
  R5. N: selection-day close >= 0.85 x the highest close of the
      trailing 252 sessions including the selection day.
  R6. L: 12-1 momentum exactly as the champion computes it (close
      21 sessions ago / close 252 sessions ago - 1). Qualifiers are
      ranked by it; top 5 held. Ties: alphabetical (deterministic;
      momentum is a float and exact ties are not expected).
  R7. FEWER THAN 5 QUALIFIERS: hold all qualifiers equal-weight,
      fully invested (AAII screens hold every passing name; the cap
      binds only above 5). ZERO qualifiers, or the market gate off:
      100% cash until the next monthly selection.
  R8. MARKET GATE (M): SPY selection-day close strictly above the
      mean of its trailing 200 closes including the selection day.
      Gate off at a selection -> liquidate everything at the next
      open and hold cash; the gate is re-evaluated only at monthly
      selections (it is a screen input, not a daily stop).
  R9. SCREENABLE POOL (placebo universe + coverage reporting): a name
      is screenable at a date iff its C pair (current + year-ago
      quarter) and its A set (four annuals) are both computable
      point-in-time AND it has >= 253 price bars up to the selection
      day (N and momentum computable). A name that is screenable but
      fails C, A or N is a non-qualifier; a name that is not
      screenable is excluded, never patched (house rule).

Data: SEC EDGAR companyfacts + Yahoo prices, reused read-only from the
champion test's caches via the imported champion module
(backtests/v4/value-momentum-plainfloor.py). The imported champion
engine must first reproduce its published figures to the cent
(replication check) before any CAN SLIM number is taken.
"""
import importlib.util
import json
import math
import os
import random
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "champion", os.path.join(HERE, "..", "..", "v4",
                             "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))
FRESH_DAYS = 548


def _ord(dstr):
    return _date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()


# ------------------------------------------------------------- EPS series
def eps_entries(facts):
    """All EarningsPerShareDiluted rows with a start date:
    (filed, start, end, val)."""
    try:
        units = facts["facts"]["us-gaap"]["EarningsPerShareDiluted"]["units"]
    except KeyError:
        return []
    key = "USD/shares" if "USD/shares" in units else list(units)[0]
    rows = []
    for e in units[key]:
        if "filed" not in e or "val" not in e or "start" not in e or "end" not in e:
            continue
        rows.append((e["filed"], e["start"], e["end"], float(e["val"])))
    return rows


def _pit_periods(rows, asof, dur_lo, dur_hi):
    """Point-in-time period map: (start,end) -> (filed, val), latest
    filing strictly before asof wins per period; only periods whose
    duration is within [dur_lo, dur_hi] days."""
    best = {}
    for filed, start, end, val in rows:
        if filed >= asof:
            continue
        dur = _ord(end) - _ord(start)
        if dur < dur_lo or dur > dur_hi:
            continue
        k = (start, end)
        if k not in best or filed > best[k][0]:
            best[k] = (filed, val)
    out = [(end, start, filed, val) for (start, end), (filed, val) in best.items()]
    out.sort(key=lambda r: r[0], reverse=True)  # by end desc
    return out


def eps_snapshot(rows, asof):
    """C and A inputs as knowable on `asof`. Returns None if the name is
    not screenable (R9); else a dict with the raw values and pass flags
    for C and A (price legs N / momentum are computed by the caller)."""
    quarters = _pit_periods(rows, asof, 60, 120)
    annuals = _pit_periods(rows, asof, 330, 400)
    if not quarters or len(annuals) < 4:
        return None
    q0_end, _q0_start, q0_filed, q0_val = quarters[0]
    if _ord(asof) - _ord(q0_filed) > FRESH_DAYS:
        return None
    # year-ago quarter: end 330-400 days before q0 end, nearest to 365
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
    # annuals: four most recent, consecutive year-ends 300-430 days apart
    fys = annuals[:4]
    for i in range(3):
        gap = _ord(fys[i][0]) - _ord(fys[i + 1][0])
        if gap < 300 or gap > 430:
            return None
    if _ord(asof) - _ord(fys[0][2]) > FRESH_DAYS:
        return None
    vals = [f[3] for f in fys]  # FY0, FY1, FY2, FY3
    a_pass = False
    a_cagr = None
    if all(v > 0 for v in vals):
        a_cagr = (vals[0] / vals[3]) ** (1.0 / 3.0) - 1.0
        a_pass = (vals[0] > vals[1] > vals[2] > vals[3]) and a_cagr >= 0.25
    return {"q_end": q0_end, "q_val": q0_val, "yoy_end": yoy[0],
            "yoy_val": yoy[1], "c_growth": c_growth, "c_pass": c_pass,
            "fy_vals": vals, "fy_ends": [f[0] for f in fys],
            "a_cagr": a_cagr, "a_pass": a_pass}


# ---------------------------------------------------------------- screen
def month_selection_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end:
            key = d[:7]
            if key not in seen:
                seen.add(key)
                out.append(d)
    return out


def build_screen_table(pb, eps_rows, start, end):
    """One screen evaluation per monthly selection date in [start, end].
    Returns {date: {gate, screenable, qualifiers, detail}} where
    qualifiers is a list of (ticker, momentum) sorted by momentum desc."""
    table = {}
    spy_bars = pb.bars["SPY"]
    spy_idx = {b["d"]: i for i, b in enumerate(spy_bars)}
    for d in month_selection_dates(pb, start, end):
        # market gate (R8)
        si = spy_idx.get(d)
        gate = None
        if si is not None and si >= 199:
            ma200 = sum(b["c"] for b in spy_bars[si - 199:si + 1]) / 200.0
            gate = spy_bars[si]["c"] > ma200
        screenable, qualifiers, detail = [], [], {}
        for t in UNIVERSE:
            snap = eps_snapshot(eps_rows.get(t, []), d)
            if snap is None:
                continue
            bl = pb.bars.get(t, [])
            didx = None
            for i, b in enumerate(bl):
                if b["d"] == d:
                    didx = i
                    break
            if didx is None or didx < 253:
                continue
            close = bl[didx]["c"]
            hi252 = max(b["c"] for b in bl[didx - 251:didx + 1])
            n_pass = close >= 0.85 * hi252
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            screenable.append(t)
            detail[t] = {"c_pass": snap["c_pass"], "a_pass": snap["a_pass"],
                         "n_pass": n_pass, "mom": mom,
                         "c_growth": snap["c_growth"], "a_cagr": snap["a_cagr"],
                         "q_end": snap["q_end"], "fy_vals": snap["fy_vals"]}
            if snap["c_pass"] and snap["a_pass"] and n_pass:
                qualifiers.append((t, mom))
        qualifiers.sort(key=lambda kv: (-kv[1], kv[0]))
        table[d] = {"gate": gate, "screenable": screenable,
                    "qualifiers": qualifiers, "detail": detail}
    return table


# ---------------------------------------------------------------- engine
def run_pot(pb, table, start, end, start_cash=100.0, floor0=85.0,
            placebo_rng=None, label="", quiet=True):
    """Champion mechanics: selection-day targets execute at the next
    open; sells first then buys; 0.10%/side + $0.01/sell; plain floor
    checked on the close; end-of-window liquidation at the final close."""
    cash = start_cash
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    picks_log = []
    sel_set = set(month_selection_dates(pb, start, end))
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


def diagnostics(r, floor0=85.0):
    curve = r["curve"]
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = (d, v)
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "floor": floor0,
            "worst_close_above_floor": round(worst_v - floor0, 2),
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "year_end_closes": {y: {"date": d, "close": round(v, 2)}
                                for y, (d, v) in sorted(year_end.items())}}


# ------------------------------------------------------------------ main
def main():
    t0 = time.time()
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    eps_rows = {}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        eps_rows[t] = eps_entries(facts)
        equity_rows[t] = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
                          E.pit_series(facts, "us-gaap",
                                       "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                                       prio=1))
        shares_rows[t] = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
                          E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
                          E.pit_series(facts, "us-gaap",
                                       "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        print(f"{t}: eps rows={len(eps_rows[t])}", flush=True)
        time.sleep(0.1)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
        print(f"{t}: {len(bars[t])} bars {bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = E.PriceBook(bars)

    # ---- (0) replication check: imported champion engine, published numbers
    rep = {}
    for wname, ws, we in [("FULL", "2019-01-02", "2026-11-20"),
                          ("VALIDATION", "2023-01-03", "2026-11-20")]:
        r = E.run_pot(pb, equity_rows, shares_rows, ws, we, 100.0, 85.0, [],
                      label=f"REPLICATION {wname}", quiet=True)
        rep[wname] = round(r["final"], 2)
        print(f"REPLICATION {wname}: champion final=${r['final']:,.2f} "
              f"(published FULL $544.47 / VALIDATION $288.05)", flush=True)
    assert abs(rep["FULL"] - 544.47) < 0.02 and abs(rep["VALIDATION"] - 288.05) < 0.02, \
        f"REPLICATION FAILED: {rep}"
    print("REPLICATION CHECK PASSED", flush=True)

    # ---- screen tables (one PIT evaluation per monthly selection date)
    table_all = build_screen_table(pb, eps_rows, "2019-01-02", "2026-11-20")
    n_sel = len(table_all)
    gate_on = sum(1 for s in table_all.values() if s["gate"])
    print(f"screen table: {n_sel} monthly selections, gate ON {gate_on}, "
          f"OFF {n_sel - gate_on}", flush=True)

    windows = [("CONTINUOUS", "2019-01-02", "2026-11-20"),
               ("VALIDATION", "2023-01-03", "2026-11-20")]
    out = {"strategy": "CAN SLIM (AAII screen form), gap test A-8",
           "replication_check": rep,
           "champion_reference": {"continuous": 544.47, "validation": 288.05},
           "windows": {}}
    for wname, ws, we in windows:
        s_net, _ = E.spy_net(pb, ws, we, 100.0)
        r = run_pot(pb, table_all, ws, we, label=f"CANSLIM {wname}")
        diag = diagnostics(r)
        twins = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            tw = run_pot(pb, table_all, ws, we, placebo_rng=rng,
                         label=f"CANSLIM {wname} PLACEBO s{seed}")
            twins.append(round(tw["final"], 2))
        twins_sorted = sorted(twins)
        median = twins_sorted[len(twins_sorted) // 2] if len(twins_sorted) % 2 == 1 else \
            (twins_sorted[len(twins_sorted) // 2 - 1] + twins_sorted[len(twins_sorted) // 2]) / 2.0
        beats = sum(1 for x in twins if r["final"] > x)
        # screen anatomy for this window
        sel_dates = [d for d in sorted(table_all) if ws <= d <= we]
        anatomy = {"selections": len(sel_dates),
                   "gate_on": sum(1 for d in sel_dates if table_all[d]["gate"]),
                   "months_with_any_qualifier": sum(1 for d in sel_dates if table_all[d]["qualifiers"]),
                   "months_ranked_invested": sum(1 for d, g, sc, q, p in r["picks_log"] if p),
                   "avg_screenable": round(sum(len(table_all[d]["screenable"]) for d in sel_dates) / max(1, len(sel_dates)), 1),
                   "avg_qualifiers": round(sum(len(table_all[d]["qualifiers"]) for d in sel_dates) / max(1, len(sel_dates)), 2),
                   "pass_counts_total": {
                       "C": sum(1 for d in sel_dates for v in table_all[d]["detail"].values() if v["c_pass"]),
                       "A": sum(1 for d in sel_dates for v in table_all[d]["detail"].values() if v["a_pass"]),
                       "N": sum(1 for d in sel_dates for v in table_all[d]["detail"].values() if v["n_pass"]),
                       "screenable_evals": sum(len(table_all[d]["detail"]) for d in sel_dates)}}
        out["windows"][wname] = {
            "final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted": r["halted"],
            "halt_info": r["halt_info"], "spy_net": round(s_net, 2),
            "diag": diag, "placebo_finals": twins,
            "placebo_median": round(median, 2), "placebo_beats": beats,
            "placebo_percentile": beats * 5,
            "anatomy": anatomy,
            "picks_log": [(d, g, sc, q, p) for d, g, sc, q, p in r["picks_log"]],
            "trades": r["trades"]}
        print(f"== CANSLIM {wname}: final=${r['final']:,.2f} costs=${r['costs']:,.2f} "
              f"orders={len(r['trades'])} halted={r['halted']} | SPY=${s_net:,.2f} | "
              f"placebo median=${median:,.2f} beats={beats}/20", flush=True)

    # ---- yearly folds (fresh $100 per calendar year, ranked only)
    folds = []
    for y in range(2020, 2027):
        ws = f"{y}-01-01"
        we = f"{y}-12-31" if y < 2026 else "2026-11-20"
        r = run_pot(pb, table_all, ws, we, label=f"CANSLIM FOLD {y}")
        s_net, _ = E.spy_net(pb, ws, we, 100.0)
        folds.append({"year": y, "final": round(r["final"], 2),
                      "return_pct": round(r["final"] - 100.0, 2),
                      "halted": r["halted"], "spy_net": round(s_net, 2),
                      "spy_return_pct": round(s_net - 100.0, 2),
                      "beat_spy": r["final"] > s_net})
        print(f"FOLD {y}: CANSLIM ${r['final']:,.2f} halted={r['halted']} "
              f"vs SPY ${s_net:,.2f}", flush=True)
    comp = 100.0
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
    out["folds"] = folds
    out["fold_record"] = f"{sum(1 for f in folds if f['beat_spy'])} wins, " \
                         f"{sum(1 for f in folds if not f['beat_spy'])} losses vs SPY"
    out["fold_compounded_final"] = round(comp, 2)

    # full selection detail for the report (qualifier history)
    out["screen_table"] = {
        d: {"gate": s["gate"], "screenable": s["screenable"],
            "qualifiers": [t for t, _m in s["qualifiers"]],
            "detail": {t: {"c_pass": v["c_pass"], "a_pass": v["a_pass"],
                           "n_pass": v["n_pass"], "mom": round(v["mom"], 4),
                           "c_growth": (None if v["c_growth"] is None else round(v["c_growth"], 4)),
                           "a_cagr": (None if v["a_cagr"] is None else round(v["a_cagr"], 4))}
                       for t, v in s["detail"].items()}}
        for d, s in sorted(table_all.items())}
    out["runtime_seconds"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "canslim-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
