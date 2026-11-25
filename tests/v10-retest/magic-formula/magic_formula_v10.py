#!/usr/bin/env python3
"""
MAGIC FORMULA (Greenblatt) — v10 GREAT RETEST, cadence sweep.
Simulation only. One clean shot, no tuning.

Strategy: rank the pond by earnings yield (EBIT / enterprise value) and
return on capital (EBIT / (net working capital + net PPE)); buy top-5 by
average percentile rank, equal weight. Scoring construction copied verbatim
from backtests/v9-muse-rules/magic-formula/magic-formula.py (which itself
imports the v4 baseline machinery). Pool caveat (documented, NOT fixed):
only 12-21 of the 30 pond names are scorable on any selection date; banks
(JPM, BAC, WFC) and BRK-B drop out because they file unclassified balance
sheets (no AssetsCurrent/LiabilitiesCurrent), which coincides with
Greenblatt's own exclusion of financials.

What this script does:
  (1) INTEGRITY: the copied v9 engine in its ORIGINAL form (quarterly
      selection, original v4 cached prices) on CONT 2019-01-02->2026-11-20
      and VAL 2023-01-03->2026-11-20 must reproduce $271.66 / $149.01.
  (2) SWEEP: DECADE 2016-11-21 -> 2026-11-20 at 7 cadences under the SPEC's
      uniform cadence definition (selection/rebalance ONLY on cadence
      dates), $100/cell, program costs (0.10%/side + $0.01/sell), v9
      protections (plain -15% floor; first halt -> liquidate next open,
      90 calendar days cash, restart at next cadence date with episode-2
      floor -15% of restart balance; second halt ends the run).
      Native cadence = ANNUAL (Greenblatt: select, hold a year). The
      original program test re-picked QUARTERLY -> original_cadence_foreign.
  (3) PLACEBOS: 20 seeds (1..20) per cell, random 5 from the scored pool
      at each selection, same cadence + v9 protections.

Data: EDGAR companyfacts + Yahoo prices reused READ-ONLY from the v4
caches (via the imported v4 baseline). The v4 price cache starts
2017-06-01, before the decade start, so decade prices are downloaded
fresh from Yahoo (same chart API + adjclose method as the original) with
period1=2016-01-01 and cached in THIS folder's data/. An overlap check
against the original cached bars is recorded in results.json.
"""
import bisect
import importlib.util
import json
import os
import random
import time
import urllib.request
from datetime import date as _date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
DATA = os.path.join(HERE, "data")
CELLS = os.path.join(HERE, "cells")
os.makedirs(DATA, exist_ok=True)
os.makedirs(CELLS, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
FLOOR0 = 85.0
DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------- MF fact builders (copied v9)
def annual_series(facts, concept, prio=0):
    rows = []
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return rows
    key = "USD" if "USD" in units else list(units)[0]
    for e in units[key]:
        if "filed" not in e or "val" not in e or "start" not in e or "end" not in e:
            continue
        sy, sm, sd = int(e["start"][:4]), int(e["start"][5:7]), int(e["start"][8:10])
        ey_, em, ed = int(e["end"][:4]), int(e["end"][5:7]), int(e["end"][8:10])
        dur = _date(ey_, em, ed).toordinal() - _date(sy, sm, sd).toordinal()
        if 300 <= dur <= 400:
            rows.append((e["filed"], e["end"], float(e["val"]), prio))
    return rows

def merged_annual(facts, concept_prios):
    rows = []
    for concept, prio in concept_prios:
        rows += annual_series(facts, concept, prio)
    return rows

def merged_instant(facts, concept_prios):
    rows = []
    for concept, prio in concept_prios:
        rows += E.pit_series(facts, "us-gaap", concept, prio=prio)
    return rows

def build_mf_rows(facts):
    opinc = annual_series(facts, "OperatingIncomeLoss")
    pretax = merged_annual(facts, [
        ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", 3),
        ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments", 2),
        ("IncomeLossFromContinuingOperationsBeforeIncomeTaxes", 1)])
    interest = merged_annual(facts, [
        ("InterestExpense", 3),
        ("InterestExpenseDebt", 2),
        ("InterestAndDebtExpense", 1)])
    cash = merged_instant(facts, [
        ("CashAndCashEquivalentsAtCarryingValue", 2),
        ("Cash", 1)])
    debt_cur = merged_instant(facts, [
        ("LongTermDebtCurrent", 3),
        ("DebtCurrent", 2),
        ("ShortTermBorrowings", 1)])
    debt_non = merged_instant(facts, [
        ("LongTermDebtNoncurrent", 3),
        ("LongTermDebt", 2)])
    assets_cur = E.pit_series(facts, "us-gaap", "AssetsCurrent")
    liab_cur = E.pit_series(facts, "us-gaap", "LiabilitiesCurrent")
    ppe = E.pit_series(facts, "us-gaap", "PropertyPlantAndEquipmentNet")
    return {"opinc": opinc, "pretax": pretax, "interest": interest,
            "cash": cash, "debt_cur": debt_cur, "debt_non": debt_non,
            "assets_cur": assets_cur, "liab_cur": liab_cur, "ppe": ppe}

def mf_ebit(mfr, asof):
    oi = E.pit_value(mfr["opinc"], asof)
    if oi is not None:
        return oi[2]
    pt = E.pit_value(mfr["pretax"], asof)
    if pt is None:
        return None
    intr = E.pit_value(mfr["interest"], asof)
    return pt[2] + (intr[2] if intr is not None else 0.0)

def mf_score_slow(mfr, so_rows, px, asof):
    """Original v9 mf_score (route counter dropped)."""
    ebit = mf_ebit(mfr, asof)
    so = E.pit_value(so_rows, asof)
    cash_r = E.pit_value(mfr["cash"], asof)
    ac = E.pit_value(mfr["assets_cur"], asof)
    lc = E.pit_value(mfr["liab_cur"], asof)
    ppe = E.pit_value(mfr["ppe"], asof)
    if (ebit is None or so is None or px is None or so[2] <= 0
            or cash_r is None or ac is None or lc is None or ppe is None):
        return None
    mcap = so[2] * px
    if mcap <= 0:
        return None
    dc = E.pit_value(mfr["debt_cur"], asof)
    dn = E.pit_value(mfr["debt_non"], asof)
    debt_cur = dc[2] if dc is not None else 0.0
    total_debt = debt_cur + (dn[2] if dn is not None else 0.0)
    cash = cash_r[2]
    ev = mcap + total_debt - cash
    if ev <= 0:
        return None
    nwc = (ac[2] - cash) - (lc[2] - debt_cur)
    capital = nwc + ppe[2]
    if capital <= 0:
        return None
    return (ebit / ev, ebit / capital)

# ------------------------------------------------ fast point-in-time lookup
# E.pit_value picks, among rows filed strictly before asof and filed within
# 548 days of asof, the max key (filed, prio, end). Since filed is the
# primary key, that is exactly the best entry of the LATEST filed-date
# group before asof (provided that filed date passes the freshness gate;
# if it fails, every older group fails too). FastPit precomputes that.
class FastPit:
    def __init__(self, rows):
        groups = {}
        for filed, end, val, prio in rows:
            cur = groups.get(filed)
            if cur is None or (prio, end) > (cur[0], cur[1]):
                groups[filed] = (prio, end, val)
        self.fileds = sorted(groups)
        self.vals = [groups[f][2] for f in self.fileds]
        self.ords = [_date(int(f[:4]), int(f[5:7]), int(f[8:10])).toordinal()
                     for f in self.fileds]

    def value(self, asof):
        i = bisect.bisect_left(self.fileds, asof) - 1
        if i < 0:
            return None
        ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
        if self.ords[i] < _date(ay, am, ad).toordinal() - 548:
            return None
        return self.vals[i]

def fast_series(mfr, so_rows):
    return {"ebit_opinc": FastPit(mfr["opinc"]),
            "ebit_pretax": FastPit(mfr["pretax"]),
            "ebit_int": FastPit(mfr["interest"]),
            "cash": FastPit(mfr["cash"]), "debt_cur": FastPit(mfr["debt_cur"]),
            "debt_non": FastPit(mfr["debt_non"]),
            "assets_cur": FastPit(mfr["assets_cur"]),
            "liab_cur": FastPit(mfr["liab_cur"]), "ppe": FastPit(mfr["ppe"]),
            "shares": FastPit(so_rows)}

def mf_score_fast(fs, px, asof):
    oi = fs["ebit_opinc"].value(asof)
    if oi is not None:
        ebit = oi
    else:
        pt = fs["ebit_pretax"].value(asof)
        if pt is None:
            return None
        intr = fs["ebit_int"].value(asof)
        ebit = pt + (intr if intr is not None else 0.0)
    so = fs["shares"].value(asof)
    cash = fs["cash"].value(asof)
    ac = fs["assets_cur"].value(asof)
    lc = fs["liab_cur"].value(asof)
    ppe = fs["ppe"].value(asof)
    if (so is None or px is None or so <= 0 or cash is None or ac is None
            or lc is None or ppe is None):
        return None
    mcap = so * px
    if mcap <= 0:
        return None
    dc = fs["debt_cur"].value(asof)
    dn = fs["debt_non"].value(asof)
    debt_cur = dc if dc is not None else 0.0
    total_debt = debt_cur + (dn if dn is not None else 0.0)
    ev = mcap + total_debt - cash
    if ev <= 0:
        return None
    capital = (ac - cash) - (lc - debt_cur) + ppe
    if capital <= 0:
        return None
    return (ebit / ev, ebit / capital)

# ------------------------------------------------------------- fast price book
class FastBook:
    """Same semantics as E.PriceBook, bisect-based lookups."""
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        self._dl = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t, [])
        i = bisect.bisect_right(dl, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None

# ------------------------------------------------------------- cadence dates
def cadence_dates(days, cadence):
    """SPEC uniform definition, on the window's trading days (ascending)."""
    out, seen = [], set()
    if cadence == "daily":
        return list(days)
    week_idx = -1
    last_week = None
    for d in days:
        dt = _date(int(d[:4]), int(d[5:7]), int(d[8:10]))
        if cadence == "weekly":
            key = dt.isocalendar()[:2]
            if key not in seen:
                seen.add(key); out.append(d)
        elif cadence == "biweekly":
            key = dt.isocalendar()[:2]
            if key != last_week:
                last_week = key; week_idx += 1
                if week_idx % 2 == 0:
                    out.append(d)
        elif cadence == "monthly":
            key = (d[:4], d[5:7])
            if key not in seen:
                seen.add(key); out.append(d)
        elif cadence == "quarterly":
            if d[5:7] in ("01", "04", "07", "10"):
                key = (d[:4], d[5:7])
                if key not in seen:
                    seen.add(key); out.append(d)
        elif cadence == "semiannual":
            if d[5:7] in ("01", "07"):
                key = (d[:4], d[5:7])
                if key not in seen:
                    seen.add(key); out.append(d)
        elif cadence == "annual":
            key = d[:4]
            if key not in seen:
                seen.add(key); out.append(d)
    return out

# ------------------------------------------------------------------- engine
def run_pot_gen(pb, scores_by_date, sel_dates, start, end, placebo_rng=None):
    """v9 run_pot_mf mechanics copied verbatim, except: selection dates and
    precomputed scores are passed in (cadence-general), and halt events are
    recorded for reporting (instrumentation only, no trading effect)."""
    cash = START_CASH
    floor = FLOOR0
    positions, trades = {}, []
    total_costs = 0.0
    halted, halt_info = None, None
    v9_episode, v9_resume = 1, None
    restarts, halt_events, curve, pools = [], [], [], []
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
        if d in sel_set and (v9_resume is None or d >= v9_resume):
            scores = scores_by_date.get(d, {})
            if len(scores) >= 5:
                er = E.percentile_ranks({t: v[0] for t, v in scores.items()})
                rr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    combined = {t: (er[t] + rr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:5]
                pools.append((d, sorted(scores), list(picks)))
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
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            if v9_episode == 1:
                v9_episode = 2
                v9_resume = (_date.fromisoformat(d) + timedelta(days=90)).isoformat()
                restarts.append({"halt_date": d, "liquidation_date": nd,
                                 "restart_balance": round(cash, 2),
                                 "resume_on_or_after": v9_resume,
                                 "episode2_floor": round(0.85 * cash, 2)})
                halt_events.append({"halt_date": d, "liquidation_date": nd,
                                    "signal_close": round(v, 2),
                                    "restart_balance": round(cash, 2),
                                    "resume_on_or_after": v9_resume,
                                    "episode2_floor": round(0.85 * cash, 2)})
                floor = 0.85 * cash
                pending = None
                halted = None
            else:
                halt_events.append({"halt_date": d, "liquidation_date": nd,
                                    "signal_close": round(v, 2),
                                    "restart_balance": round(cash, 2),
                                    "second_halt": True})
                return {"final": cash, "costs": total_costs, "trades": trades,
                        "halted": halted, "end": nd, "halt_info": halt_info,
                        "restarts": restarts, "halt_events": halt_events,
                        "pools": pools, "curve": curve}
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
            "restarts": restarts, "halt_events": halt_events,
            "pools": pools, "curve": curve}

def stats(r, start, end):
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in r["curve"]:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    yrs = (_date.fromisoformat(end) - _date.fromisoformat(start)).days / 365.25
    cagr = (r["final"] / START_CASH) ** (1.0 / yrs) - 1.0
    return {"final": round(r["final"], 2), "cagr_pct": round(cagr * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2), "max_dd_date": maxdd_d,
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halts": len(r["halt_events"]),
            "restart": len(r["restarts"]) > 0,
            "second_halt": r["halted"] is not None,
            "halt_events": r["halt_events"]}

# ------------------------------------------------------- extended price pull
def get_prices_ext(ticker, p1="2016-01-01", p2="2026-11-21"):
    path = os.path.join(DATA, f"pxext_{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            blob = f.read()
    else:
        import calendar
        t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
        t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read()
        with open(path, "wb") as f:
            f.write(blob)
        time.sleep(0.3)
    j = json.loads(blob)
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

# --------------------------------------------------------------------- main
def main():
    t0 = time.time()
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    mf_rows, shares_rows, fast = {}, {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        so = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
              E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
              E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        mfr = build_mf_rows(facts)
        mf_rows[t], shares_rows[t] = mfr, so
        fast[t] = fast_series(mfr, so)
        del facts
        print(f"facts {t} ok", flush=True)

    # ---------- (1) INTEGRITY: original form, original cached prices
    print("loading original cached prices...", flush=True)
    bars0 = {t: E.get_prices(t) for t in UNIVERSE + ["SPY"]}
    print("original prices loaded", flush=True)
    pb0 = E.PriceBook(bars0)
    integrity = {}
    for tag, (ws, we), published in (("CONT", CONT, 271.66), ("VAL", VAL, 149.01)):
        sel = E.quarter_selection_dates(pb0, ws, we)
        days = [d for d in pb0.dates if ws <= d <= we]
        scores = {}
        for d in sel:
            sc = {}
            for t in UNIVERSE:
                px = pb0.close_on_or_before(t, d)
                s = mf_score_slow(mf_rows[t], shares_rows[t], px, d)
                if s is not None:
                    sc[t] = s
            scores[d] = sc
        r = run_pot_gen(pb0, scores, sel, ws, we)
        st = stats(r, ws, we)
        integrity[tag] = {"published": published, "reproduced": st["final"],
                          "match": st["final"] == published,
                          "costs": st["costs"], "orders": st["orders"],
                          "halts": st["halts"]}
        print(f"INTEGRITY {tag}: reproduced=${st['final']} published=${published} "
              f"match={st['final'] == published}", flush=True)
    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump(integrity, f, indent=1)
    del bars0, pb0
    import gc; gc.collect()

    # ---------- (2) decade book on extended prices
    barsX = {t: get_prices_ext(t) for t in UNIVERSE + ["SPY"]}
    pbX = FastBook(barsX)
    # overlap check vs original cache (closes, overlapping dates)
    worst_rel = 0.0
    for t in UNIVERSE + ["SPY"]:
        old = {b["d"]: b["c"] for b in E.get_prices(t)}
        for b in barsX[t]:
            if b["d"] in old and old[b["d"]]:
                rel = abs(b["c"] - old[b["d"]]) / old[b["d"]]
                worst_rel = max(worst_rel, rel)
    print(f"price overlap worst rel diff = {worst_rel:.2e}", flush=True)

    ws, we = DECADE
    days = [d for d in pbX.dates if ws <= d <= we]
    # precompute fast scores for every trading day in the window
    scores_all = {}
    for d in days:
        sc = {}
        for t in UNIVERSE:
            px = pbX.close_on_or_before(t, d)
            s = mf_score_fast(fast[t], px, d)
            if s is not None:
                sc[t] = s
        scores_all[d] = sc
    pool_sizes = sorted({len(v) for v in scores_all.values()})
    print(f"decade days={len(days)} pool sizes={pool_sizes}", flush=True)

    # cross-check fast vs slow scoring on the quarterly dates
    qdates = cadence_dates(days, "quarterly")
    mism = 0
    for d in qdates:
        for t in UNIVERSE:
            px = pbX.close_on_or_before(t, d)
            a = mf_score_fast(fast[t], px, d)
            b = mf_score_slow(mf_rows[t], shares_rows[t], px, d)
            if (a is None) != (b is None) or (a and abs(a[0]-b[0]) > 1e-12) or (a and abs(a[1]-b[1]) > 1e-9):
                mism += 1
    print(f"fast-vs-slow score mismatches on quarterly dates: {mism}", flush=True)

    spy_final, spy_costs = E.spy_net(pbX, ws, we, START_CASH)
    print(f"SPY decade (this plumbing) = ${spy_final:.2f}", flush=True)

    cells, cell_summ = {}, {}
    for cad in CADENCES:
        sel = cadence_dates(days, cad)
        r = run_pot_gen(pbX, scores_all, sel, ws, we)
        st = stats(r, ws, we)
        twins = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            rp = run_pot_gen(pbX, scores_all, sel, ws, we, placebo_rng=rng)
            sp = stats(rp, ws, we)
            twins.append({"seed": seed, "final": sp["final"],
                          "costs": sp["costs"], "orders": sp["orders"],
                          "halts": sp["halts"], "halt_events": sp["halt_events"]})
        beaten = sum(1 for tw in twins if st["final"] > tw["final"])
        cell = {"slug": "magic-formula", "cadence": cad,
                "window": [ws, we], "start_cash": START_CASH,
                "final": st["final"], "cagr_pct": st["cagr_pct"],
                "max_dd_pct": st["max_dd_pct"], "max_dd_date": st["max_dd_date"],
                "costs": st["costs"], "orders": st["orders"],
                "halts": st["halt_events"], "restart": st["restart"],
                "second_halt": st["second_halt"],
                "n_selections": len(r["pools"]),
                "pool_sizes_seen": pool_sizes,
                "spy_final_plumbing": round(spy_final, 2),
                "spy_final_spec_dividend_adjusted": 367.80,
                "placebo": {"beaten": beaten, "of": 20,
                            "finals": [tw["final"] for tw in twins],
                            "twins": twins},
                "equity_curve": [[d, round(v, 2)] for d, v in r["curve"]]}
        with open(os.path.join(CELLS, f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cell_summ[cad] = {"final": st["final"], "cagr_pct": st["cagr_pct"],
                          "max_dd_pct": st["max_dd_pct"], "halts": st["halts"],
                          "restart": st["restart"], "second_halt": st["second_halt"],
                          "costs": st["costs"], "orders": st["orders"],
                          "placebo_beaten": beaten,
                          "placebo_note": "20 random-rank twins (seeds 1..20), same cadence, v9 protections; full twin finals in cells/<cadence>.json"}
        cells[cad] = cell_summ[cad]
        print(f"CELL {cad}: final=${st['final']} CAGR={st['cagr_pct']}% "
              f"maxDD={st['max_dd_pct']}% costs=${st['costs']} orders={st['orders']} "
              f"halts={st['halts']} placebo beaten {beaten}/20 "
              f"({time.time()-t0:.0f}s)", flush=True)

    money = [c for c in CADENCES
             if cells[c]["final"] > 367.80 and cells[c]["placebo_beaten"] is not None
             and cells[c]["placebo_beaten"] >= 11]
    out = {"slug": "magic-formula",
           "area": "long-holding fundamental sort (Greenblatt Magic Formula) — judged in this sweep on the DECADE road at every cadence",
           "area_source": "SPEC THE CADENCE SWEEP (Terry 2026-11-21 ~22:09); strategy per Greenblatt, The Little Book That Beats the Market (2005)",
           "native_cadence": "annual",
           "cadence": "annual",
           "original_cadence_foreign": True,
           "original_cadence_note": "FOREIGN: the original program test (v6/v9) re-picked QUARTERLY (first trading day of Jan/Apr/Jul/Oct, top-5). Greenblatt's published form selects and holds for a year — the annual cell is this strategy's home cadence.",
           "integrity": {"status": "reproduced" if all(v["match"] for v in integrity.values()) else "FAILED",
                         "original_finals": {"CONT": 271.66, "VAL": 149.01},
                         "reproduced_finals": {k: v["reproduced"] for k, v in integrity.items()},
                         "detail": integrity},
           "decade_spy_final": 367.80,
           "decade_spy_note": f"SPEC dividend-adjusted figure used as the money hurdle. This plumbing's own SPY net on the extended-price book is ${spy_final:.2f}.",
           "price_overlap_worst_rel_diff_vs_original_cache": worst_rel,
           "fast_slow_score_mismatches_quarterly_dates": mism,
           "pool_caveat": "Original pool scored only 12-21 of the 30 pond names per selection (banks JPM/BAC/WFC and BRK-B excluded — unclassified balance sheets give no AssetsCurrent/LiabilitiesCurrent, so the ROC denominator cannot be built; coincides with Greenblatt's exclusion of financials). Documented, not fixed.",
           "champion_decade": {"final": 65.89,
                               "note": "Value+Momentum on this decade road: two halts on this road; its crown rests on the 2010 road ($1,415.62) and the 2019 road (CONT $544.47 / VAL $288.05)."},
           "champion_reference": {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 65.89},
           "cells": cells,
           "money_cadences": money,
           "verdict_area": None,  # filled in RESULTS.md narrative; set below by rule
           "runtime_sec": round(time.time() - t0, 1)}
    # verdict by SPEC scale on its own ground (native annual cell + sweep):
    ann = cells["annual"]
    if ann["final"] > 367.80 and ann["placebo_beaten"] >= 11:
        out["verdict_area"] = "OWNS ITS GROUND"
    elif any(cells[c]["final"] > 367.80 for c in CADENCES):
        out["verdict_area"] = "REAL BUT SMALL"
    else:
        out["verdict_area"] = "NO GROUND"
    out["verdict_change"] = "see RESULTS.md"
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE", json.dumps({"money_cadences": money, "verdict": out["verdict_area"]}))

if __name__ == "__main__":
    main()
