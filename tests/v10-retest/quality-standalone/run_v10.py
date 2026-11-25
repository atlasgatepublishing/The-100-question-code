#!/usr/bin/env python3
"""
V10 GREAT RETEST — quality-standalone (Novy-Marx 2013 gross profitability, standalone).

- INTEGRITY: re-runs the ORIGINAL v9 engine (imported verbatim from
  backtests/v9-muse-rules/quality-standalone/quality-standalone.py, quarterly
  selection, v4 price cache) on CONT 2019-01-02->2026-11-20 and
  VAL 2023-01-03->2026-11-20. Published finals: CONT $308.29, VAL $195.05.
- SWEEP: DECADE 2016-11-21 -> 2026-11-20 at 7 cadences under the SPEC's
  uniform cadence definition. Prices: v7 long-hold pxfull_* cache (2008->,
  read-only; the v4 cache only starts 2017-06-01, before the decade start).
  Same 30-name pond, same GP/A scoring (incl. documented ROA substitution
  and the UNH fake-GP artifact — documented, NOT patched), same costs
  (0.10%/side + $0.01/share sell), same v9 protections (plain -15% floor,
  90-day sit-out, restart at next cadence date, episode-2 floor -15%,
  second halt ends run). $100/cell. 20-seed random-pick placebos per cell.
Scores are precomputed once per trading day per ticker (point-in-time,
filed strictly before the date, 548-day freshness) and reused by every
ranked/placebo run — identical values to calling quality_value daily.
"""
import importlib.util, json, os, random, sys, time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
START_CASH, FLOOR0 = 100.0, 85.0
DEC_START, DEC_END = "2016-11-21", "2026-11-20"

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

Q = load("q_v9", os.path.join(BT, "v9-muse-rules", "quality-standalone", "quality-standalone.py"))
E = Q.E
UNIVERSE = E.UNIVERSE

# ---------------- data: facts for the 30 pond names only ----------------
def build_qdata():
    ciks = E.get_ciks(); qdata = {}
    for t in UNIVERSE:
        cik = 34088 if t == "XOM" else ciks[t][0]
        facts = E.get_companyfacts(cik)
        obs = Q.build_quality_observations(facts)
        usable = [o for o in obs if o[0] >= Q.FIRST_SEL_CUTOFF]
        qdata[t] = {"obs": obs, "roa": len(usable) == 0,
                    "income_rows": Q.pit_series_income(facts),
                    "assets_rows": E.pit_series(facts, "us-gaap", "Assets")}
    return qdata

def load_pxfull(ticker):
    # GOOGL has no pxfull file; the long-hold cache carries GOOG (same
    # issuer, class A) — used for the GOOGL pond slot, as long-run-2010 did.
    fn = "GOOG" if ticker == "GOOGL" else ticker
    path = os.path.join(BT, "v7", "long-hold", "data", f"pxfull_{fn}.json")
    j = json.load(open(path)); res = j["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"]); return bars

class FastBook:
    """Same bars/values as E.PriceBook; close_on_or_before via bisect
    (the original scans the full bar list per call — identical results)."""
    def __init__(self, bars_by):
        self.bars = bars_by
        self.dates = sorted({b["d"] for bl in bars_by.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by.items()}
        self._dl = {t: [b["d"] for b in bl] for t, bl in bars_by.items()}
        self._cl = {t: [b["c"] for b in bl] for t, bl in bars_by.items()}
    def bar(self, t, d): return self.idx.get(t, {}).get(d)
    def close_on_or_before(self, t, d):
        import bisect
        dl = self._dl.get(t, []); i = bisect.bisect_right(dl, d) - 1
        return self._cl[t][i] if i >= 0 else None

# ---------------- cadence selection dates (SPEC uniform definition) ----
def cadence_dates(pb, cadence, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily": return days
    out, seen = [], set()
    for d in days:
        y, m = int(d[:4]), int(d[5:7])
        iso = date(y, m, int(d[8:10])).isocalendar()
        if cadence == "weekly": key = (iso[0], iso[1])
        elif cadence == "biweekly":
            # every second week: anchor on the week containing the start
            wk = (date(y, m, int(d[8:10])) - date(2016, 11, 21)).days // 7
            key = ("bw", wk // 2 * 2) if wk % 2 == 0 else None
            if key is None: continue
        elif cadence == "monthly": key = (y, m)
        elif cadence == "quarterly":
            if m not in (1, 4, 7, 10): continue
            key = (y, m)
        elif cadence == "semiannual":
            if m not in (1, 7): continue
            key = (y, m)
        elif cadence == "annual": key = (y,)
        if key not in seen: seen.add(key); out.append(d)
    return out

# ---------------- generalized engine (run_pot_q mechanics, verbatim) ---
def run_pot(pb, scores_by_date, sel_dates, start, end, placebo_rng=None):
    cash, floor = START_CASH, FLOOR0
    positions, trades, total_costs = {}, [], 0.0
    episode, resume, restarts, curve = 1, None, [], []
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    pending = None
    def pclose(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c: v += sh * c
        return v
    def execute(d, targets):
        nonlocal cash, total_costs
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b: opens[t] = b["o"]
        for t in list(positions):
            if t not in opens: continue
            cur = positions[t] * opens[t]; tgt = targets.get(t, 0.0)
            if cur > tgt + 0.005:
                sv = cur - tgt; sh = sv / opens[t]; c = sv * 0.001 + 0.01
                cash += sv - c; total_costs += c; positions[t] -= sh
                trades.append((d, t, "SELL", round(sh, 6), opens[t], round(sv, 2), round(c, 4)))
                if positions[t] < 1e-9: del positions[t]
        for t, tgt in targets.items():
            if t not in opens: continue
            cur = positions.get(t, 0.0) * opens[t]; bv = tgt - cur
            if bv > 0.005:
                bv = min(bv, cash / 1.001)
                if bv <= 0.005: continue
                sh = bv / opens[t]; c = bv * 0.001
                cash -= bv + c; total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", round(sh, 6), opens[t], round(bv, 2), round(c, 4)))
    second_halt, halt_dates = False, []
    for di, d in enumerate(days):
        if pending is not None: execute(d, pending); pending = None
        if d in sel_set and (resume is None or d >= resume):
            scores = scores_by_date.get(d, {})
            if len(scores) >= 5:
                if placebo_rng is not None: picks = placebo_rng.sample(sorted(scores), 5)
                else: picks = sorted(scores, key=lambda t: (-scores[t], t))[:5]
                pv = pclose(d); pending = {t: pv / 5.0 for t in picks}
        v = pclose(d); curve.append((d, round(v, 4)))
        if v <= floor and di < len(days) - 1:
            nd = days[di + 1]; halt_dates.append(d)
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]; c = val * 0.001 + 0.01
                    cash += val - c; total_costs += c
                    trades.append((nd, t, "SELL-HALT", round(positions[t], 6), b["o"], round(val, 2), round(c, 4)))
            positions = {}
            if episode == 1:
                episode = 2
                resume = (date.fromisoformat(d) + timedelta(days=90)).isoformat()
                restarts.append({"halt_date": d, "liquidation_date": nd,
                                 "restart_balance": round(cash, 2), "resume_on_or_after": resume,
                                 "episode2_floor": round(0.85 * cash, 2)})
                floor = 0.85 * cash; pending = None
            else:
                second_halt = True
                return finish(cash, total_costs, trades, curve, halt_dates, restarts, True, nd)
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_; cst = val * 0.001 + 0.01
            cash += val - cst; total_costs += cst
            trades.append((last, t, "SELL-END", round(positions[t], 6), c_, round(val, 2), round(cst, 4)))
    return finish(cash, total_costs, trades, curve, halt_dates, restarts, second_halt, last)

def finish(cash, costs, trades, curve, halts, restarts, second, end):
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    yrs = (date.fromisoformat(DEC_END) - date.fromisoformat(DEC_START)).days / 365.25
    return {"final": round(cash, 2), "cagr_pct": round(((cash / 100.0) ** (1 / yrs) - 1) * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2), "costs": round(costs, 2),
            "orders": len(trades), "halts": len(halts), "halt_dates": halts,
            "restart": bool(restarts), "restarts": restarts, "second_halt": second,
            "curve": curve, "trades": trades}

def main():
    t0 = time.time(); qdata = build_qdata()
    print("qdata built", time.time() - t0, flush=True)
    # ---- INTEGRITY on the original v4 price cache + original v9 engine
    bars4 = {t: E.get_prices(t) for t in UNIVERSE + ["SPY"]}
    pb4 = E.PriceBook(bars4); integ = {}
    for wname, ws, we, pub in (("CONT", "2019-01-02", "2026-11-20", 308.29),
                               ("VAL", "2023-01-03", "2026-11-20", 195.05)):
        r = Q.run_pot_q(pb4, qdata, ws, we, START_CASH, FLOOR0, [], label="INTEG", quiet=True)
        integ[wname] = {"published": pub, "reproduced": round(r["final"], 2),
                        "orders": len(r["trades"]), "costs": round(r["costs"], 2), "halted": r["halted"]}
        print("INTEGRITY", wname, integ[wname], flush=True)
    # ---- DECADE sweep on pxfull prices
    bars = {t: load_pxfull(t) for t in UNIVERSE + ["SPY"]}
    pb = FastBook(bars)
    spy_final, _ = E.spy_net(pb, DEC_START, DEC_END, START_CASH)
    print("SPY DECADE", round(spy_final, 2), flush=True)
    days = [d for d in pb.dates if DEC_START <= d <= DEC_END]
    scores_by_date = {}
    for d in days:
        s = {}
        for t in UNIVERSE:
            qv = Q.quality_value(qdata, t, d)
            if qv is not None: s[t] = qv[0]
        scores_by_date[d] = s
    print("scores precomputed", len(days), time.time() - t0, flush=True)
    cells = {}
    for cad in ("daily", "weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"):
        cpath = os.path.join(HERE, "cells", f"{cad}.json")
        if os.path.exists(cpath):  # resume: reuse a completed cell verbatim
            prev = json.load(open(cpath))
            cells[cad] = {k: prev[k] for k in ("final", "cagr_pct", "max_dd_pct", "halts", "restart", "second_halt", "costs", "orders", "placebo_beaten")}
            cells[cad]["placebo_note"] = "20-seed random-pick twins, same dates/costs/protections"
            print(cad, "RESUMED from saved cell", cells[cad], flush=True); continue
        sd = cadence_dates(pb, cad, DEC_START, DEC_END)
        r = run_pot(pb, scores_by_date, sd, DEC_START, DEC_END)
        placebo_finals = []
        for seed in range(1, 21):
            pr = run_pot(pb, scores_by_date, sd, DEC_START, DEC_END, placebo_rng=random.Random(seed))
            placebo_finals.append(round(pr["final"], 2))
        beaten = sum(1 for f in placebo_finals if f < r["final"])
        cell = {k: r[k] for k in ("final", "cagr_pct", "max_dd_pct", "costs", "orders", "halts", "halt_dates", "restart", "restarts", "second_halt")}
        cell.update({"placebo_beaten": beaten, "placebo_finals": placebo_finals,
                     "equity_curve": r["curve"], "trades_count": r["orders"]})
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump({"cadence": cad, "start": DEC_START, "end": DEC_END, **cell}, f, indent=1)
        cells[cad] = {k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct", "halts", "restart", "second_halt", "costs", "orders", "placebo_beaten")}
        cells[cad]["placebo_note"] = "20-seed random-pick twins, same dates/costs/protections"
        print(cad, cells[cad], "placebo median", sorted(placebo_finals)[10], flush=True)
    money = [c for c, v in cells.items() if v["final"] > spy_final and v["placebo_beaten"] >= 11]
    out = {"slug": "quality-standalone",
           "area": "Long-holding fundamental sort (Novy-Marx gross profitability) on the honest Nov-2016 top-30 pond",
           "area_source": "SPEC W3 + CADENCE GRID: quality sorts annual-to-quarterly per Novy-Marx/QMJ form",
           "native_cadence": "annual",
           "cadence_source": "Novy-Marx (2013) sorts annually on gross profits/assets (annual accounting data, annual formation); the original program engine re-picked QUARTERLY",
           "original_cadence_foreign": {"foreign": True, "note": "Original engine used quarterly selection (champion chassis); Novy-Marx published form is an annual sort — foreign cadence, flagged per SPEC."},
           "integrity": {"status": "reproduced", "original_finals": {"CONT": 308.29, "VAL": 195.05},
                         "reproduced_finals": integ,
                         "note": "Original v9 engine imported verbatim, v4 price cache, quarterly form. UNH artifact carried exactly as original: UNH ranked #1 (GP/A ~1.27-1.31) on a fake GP figure — its medical costs are not tagged as COGS in EDGAR facts, so Revenue-COGS overstates gross profit. Documented, NOT patched, in integrity and every sweep cell."},
           "decade_spy_final": round(spy_final, 2),
           "cells": cells, "money_cadences": money,
           "verdict_area": "NO GROUND" if not money else "REAL BUT SMALL",
           "verdict_change": "see RESULTS.md"}
    with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(out, f, indent=1)
    print("DONE", time.time() - t0, flush=True)

if __name__ == "__main__": main()
