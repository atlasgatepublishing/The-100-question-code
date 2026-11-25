#!/usr/bin/env python3
"""
WINNERS' BLEND — v10 GREAT RETEST, cadence sweep. Simulation only.

Strategy: one $100 pot split 50/50 between the honest momentum basket
(monthly top-5 by 12-1 momentum above 200-day SMA, Nov-2016 top-30 pond)
and honest value+momentum (quarterly top-5 by average percentile rank of
book-to-market and 12-1 momentum, EDGAR point-in-time), blended at the
equity-curve level exactly as backtests/v4/winners-blend.py did.

CADENCE TREATMENT (binding, per task): the sweep cadence governs BOTH
parents' re-pick rhythms AND the 50/50 split rebalance, uniformly. At the
quarterly cell BOTH legs re-pick quarterly and the split rebalances
quarterly; the original mixed tempos (basket monthly, VM quarterly,
split rebalanced each January) appear ONLY in the integrity run, which
reproduces the original form. There is no cell where one leg keeps its
native tempo while the other takes the cell cadence.

Sweep rules: DECADE 2016-11-21 -> 2026-11-20, $100/cell, program costs
(0.10%/side + $0.01/sell inside each engine; split transfers charged
0.10% sell + 0.10% buy + $0.01 x 5 as in the original), v9 protections at
pot level (plain -15% floor from episode start; first halt -> liquidate
at next day's close less 0.10% + $0.10, sit in cash 90 calendar days,
restart at the next cadence date under an episode-2 floor of -15% from
the restart balance; second halt ends the run). Finals are mark-to-market
at the last close, as in the original blend (costs exclude a terminal
liquidation, as in the original).

Data (read-only shared caches):
  - Basket leg: v4 momentum-basket-honest Yahoo cache (2015->2026,
    split-adjusted), SPY calendar.
  - VM leg, integrity: v4 caches via the original engine (prices from
    2017-06-01, EDGAR facts from v4/data).
  - VM leg, decade sweep: the SAME Yahoo dividend-adjusted price method
    over the long-history pxfull_* pulls cached for the long-run-2010
    test (v7/long-hold/data, 2008->2026) so the VM leg can score on the
    full decade road; GOOGL (absent there) was pulled the same way into
    ./cache/pxfull_GOOGL.json. EDGAR rows are the original engine's.
Engines: the sleeve simulators below are line-level copies of the
parents' logic (basket: momentum-basket-honest.simulate with floor/
ladder removed and the monthly trigger replaced by a cadence-date set;
VM: value-momentum-plainfloor.run_pot with floor/ladder/halt removed
and quarter_selection_dates replaced by a cadence-date set, plus
bisect-based lookups that return identical values). Both copies are
validated against the original engines before the sweep runs (see
integrity section in main()).
"""
import importlib.util
import json
import math
import os
import random
import time
from bisect import bisect_left, bisect_right
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
V4 = os.path.join(BT, "v4")
LH_DATA = os.path.join(BT, "v7", "long-hold", "data")

START, END = "2016-11-21", "2026-11-20"
POT = 100.0
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mb = _load("mb_v10", os.path.join(V4, "momentum-basket-honest.py"))
vm = _load("vm_v10", os.path.join(V4, "value-momentum-plainfloor.py"))
UNIVERSE = list(mb.UNIVERSE)

# --------------------------------------------------------------------------
# Cadence date sets (SPEC definition: first trading day of each period)
# --------------------------------------------------------------------------
def period_key(d, cadence):
    y, m = int(d[:4]), int(d[5:7])
    if cadence == "daily":
        return d
    if cadence in ("weekly", "biweekly"):
        dt = date(y, m, int(d[8:10]))
        monday = dt - timedelta(days=dt.weekday())
        if cadence == "weekly":
            return ("W", monday.isoformat())
        return ("B", monday.toordinal() // 14)
    if cadence == "monthly":
        return (y, m)
    if cadence == "quarterly":
        return (y, (m - 1) // 3)
    if cadence == "semiannual":
        return (y, (m - 1) // 6)
    if cadence == "annual":
        return (y,)
    raise ValueError(cadence)


def cadence_dates(cal, cadence, start, end):
    out, seen = [], set()
    for d in cal:
        if start <= d <= end:
            k = period_key(d, cadence)
            if k not in seen:
                seen.add(k)
                out.append(d)
    return out


# --------------------------------------------------------------------------
# Basket sleeve — copy of mb.simulate, floor/ladder removed, cadence trigger
# --------------------------------------------------------------------------
def basket_sim(mkt, start_d, end_d, pot0, sel_set, mode, seed=42,
               first_day_trade=True):
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    cash = float(pot0)
    pos = {}
    curve, order_log = [], []          # order_log: (date, fee)

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        if i > 0 and (d in sel_set or (first_day_trade and i == i0)):
            j = i - 1
            elig = []
            for t in UNIVERSE:
                sma200 = mkt.sma(t, j, 200)
                c = mkt.close_px(t, j)
                if sma200 is None or c is None or c <= sma200:
                    continue
                mom = mkt.momentum_12_1(t, j)
                if mom is None:
                    continue
                elig.append((t, mom))
            if mode == "ranked":
                elig.sort(key=lambda x: -x[1])
                picks = [t for t, _ in elig[:5]]
            else:
                names = sorted(t for t, _ in elig)
                picks = rng.sample(names, min(5, len(names))) if names else []
            eq_open = equity_at(i, use_open=True)
            target_val = {t: 0.20 * eq_open for t in picks}
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos[t] * px
                want = target_val.get(t, 0.0)
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * mb.COST_RATE + mb.SELL_FEE
                    cash += sell_val - fee
                    order_log.append((d, fee))
                    pos[t] -= sh
                    if want <= 0.0 or pos[t] * px < 0.01:
                        del pos[t]
            for t in picks:
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos.get(t, 0.0) * px
                deficit = target_val[t] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + mb.COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * mb.COST_RATE
                cash -= buy_val + fee
                order_log.append((d, fee))
                pos[t] = pos.get(t, 0.0) + buy_val / px
        curve.append((d, equity_at(i, use_open=False)))
    return {"curve": curve, "order_log": order_log,
            "final": curve[-1][1] if curve else pot0}


# --------------------------------------------------------------------------
# VM sleeve — copy of vm.run_pot, floor/ladder/halt removed, cadence
# selection dates, bisect lookups with identical values.
# --------------------------------------------------------------------------
class FastBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.didx = {}
        self.closes = {}
        self.opens = {}
        self.dates_by_t = {}
        for t, bl in bars_by_ticker.items():
            self.didx[t] = {b["d"]: i for i, b in enumerate(bl)}
            self.closes[t] = [b["c"] for b in bl]
            self.opens[t] = [b["o"] for b in bl]
            self.dates_by_t[t] = [b["d"] for b in bl]

    def close_on_or_before(self, t, d):
        dl = self.dates_by_t.get(t, [])
        if not dl:
            return None
        k = bisect_right(dl, d) - 1
        return self.closes[t][k] if k >= 0 else None


def make_pit_struct(rows):
    """rows: list of (filed, end, val, prio). pit_value picks the max
    (filed, prio, end) among filed<asof and filed >= asof-548d, so the
    best entry at the maximum filed date in the window decides."""
    best_by_filed = {}
    for filed, end, val, prio in rows:
        cur = best_by_filed.get(filed)
        if cur is None or (prio, end) > (cur[0], cur[1]):
            best_by_filed[filed] = (prio, end, val)
    fileds = sorted(best_by_filed)
    return (fileds, best_by_filed)


def pit_fast(struct, asof):
    fileds, best_by_filed = struct
    k = bisect_left(fileds, asof) - 1
    if k < 0:
        return None
    filed = fileds[k]
    ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
    cutoff = date(ay, am, ad).toordinal() - 548
    fy, fm, fd = int(filed[:4]), int(filed[5:7]), int(filed[8:10])
    if date(fy, fm, fd).toordinal() < cutoff:
        return None
    prio, end, val = best_by_filed[filed]
    return (filed, end, val)


def vm_sim(fb, eq_struct, sh_struct, start, end, start_cash, sel_set,
           placebo_rng=None, first_day_trade=True):
    cash = start_cash
    positions = {}
    trades = []                        # (date, cost)
    total_costs = 0.0
    curve = []
    days = [d for d in fb.dates if start <= d <= end]
    if not days:
        return {"curve": [], "trades": [], "costs": 0.0, "final": start_cash}
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = fb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        opens = {}
        for t in set(list(positions) + list(targets)):
            i = fb.didx.get(t, {}).get(d)
            if i is not None:
                opens[t] = fb.opens[t][i]
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
                trades.append((d, c))
                positions[t] -= sh
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
                trades.append((d, c))
                positions[t] = positions.get(t, 0.0) + sh

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set or (first_day_trade and di == 0):
            scores = {}
            for t in UNIVERSE:
                be = pit_fast(eq_struct[t], d)
                so = pit_fast(sh_struct[t], d)
                px = fb.close_on_or_before(t, d)
                if be is None or so is None or px is None or so[2] <= 0 \
                        or be[2] is None:
                    continue
                mcap = so[2] * px
                if mcap <= 0:
                    continue
                bm = be[2] / mcap
                didx = fb.didx.get(t, {}).get(d)
                if didx is None or didx < 253:
                    continue
                mom = fb.closes[t][didx - 21] / fb.closes[t][didx - 252] - 1.0
                scores[t] = (bm, mom)
            if len(scores) >= 5:
                vr = vm.percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = vm.percentile_ranks({t: v[1] for t, v in scores.items()})
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:5]
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
        curve.append((d, portfolio_close(d)))
    return {"curve": curve, "trades": trades, "costs": total_costs,
            "final": curve[-1][1] if curve else start_cash}


# --------------------------------------------------------------------------
# Blend machinery (sweep form): pot curve from two sleeve curves,
# split rebalanced at the close of every cadence date, pot floor check.
# --------------------------------------------------------------------------
def blend_episode(cal_days, bcurve, vcurve, pot0, rebal_set, floor):
    """Returns dict(curve, halt_date, halt_idx, transfer_costs, rebalances).
    cal_days: trading days of this episode (basket calendar). vcurve
    values are carried forward; before the VM curve starts the VM half
    is pot0/2 cash (it holds cash until its first selection can score)."""
    B = dict(bcurve)
    V = dict(vcurve)
    scaleA = scaleB = 1.0
    lastA = lastB = None
    lastV = pot0 / 2.0
    curve, rebalances = [], []
    transfer_costs = 0.0
    halt_date = None
    for idx, d in enumerate(cal_days):
        if d in B:
            lastA = B[d]
        if d in V:
            lastV = V[d]
        va = scaleA * lastA if lastA is not None else pot0 / 2.0
        vb = scaleB * lastV
        tot = va + vb
        if d in rebal_set and idx > 0:
            transfer = abs(va - vb) / 2.0
            cost = transfer * 0.002 + 0.05
            tot -= cost
            transfer_costs += cost
            if lastA:
                scaleA = (tot / 2.0) / lastA
            if lastV:
                scaleB = (tot / 2.0) / lastV
            rebalances.append({"date": d, "transfer": round(transfer, 2),
                               "cost": round(cost, 2)})
            va = vb = tot / 2.0
        curve.append((d, tot))
        if tot <= floor:
            halt_date = d
            break
    return {"curve": curve, "halt_date": halt_date,
            "transfer_costs": transfer_costs, "rebalances": rebalances,
            "scaleA": scaleA, "scaleB": scaleB}


def max_dd(curve):
    peak, worst = -1.0, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            worst = min(worst, eq / peak - 1.0)
    return worst * 100.0


def cagr_pct(final, start, sd, ed):
    yrs = (date(int(ed[:4]), int(ed[5:7]), int(ed[8:10])) -
           date(int(sd[:4]), int(sd[5:7]), int(sd[8:10]))).days / 365.25
    if final <= 0:
        return -100.0
    return ((final / start) ** (1.0 / yrs) - 1.0) * 100.0


# --------------------------------------------------------------------------
# Data assembly
# --------------------------------------------------------------------------
def build_vm_rows():
    ciks = vm.get_ciks()
    overrides = {"XOM": 34088}
    eq_rows, sh_rows = {}, {}
    for t in UNIVERSE:
        cik = overrides.get(t, ciks[t][0])
        facts = vm.get_companyfacts(cik)
        eq_rows[t] = (
            vm.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            vm.pit_series(facts, "us-gaap",
                          "StockholdersEquityIncludingPortionAttributable"
                          "ToNoncontrollingInterest", prio=1))
        sh_rows[t] = (
            vm.pit_series(facts, "dei",
                          "EntityCommonStockSharesOutstanding", prio=3) +
            vm.pit_series(facts, "us-gaap",
                          "CommonStockSharesOutstanding", prio=2) +
            vm.pit_series(facts, "us-gaap",
                          "WeightedAverageNumberOfSharesOutstandingBasic",
                          prio=1))
        time.sleep(0.02)
    return eq_rows, sh_rows


def parse_pxfull(path):
    with open(path, "rb") as f:
        j = json.loads(f.read())
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


def build_decade_book():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        if t == "GOOGL":
            path = os.path.join(HERE, "cache", "pxfull_GOOGL.json")
        else:
            path = os.path.join(LH_DATA, f"pxfull_{t}.json")
        bars[t] = parse_pxfull(path)
    return FastBook(bars)


# --------------------------------------------------------------------------
# One sweep cell (ranked or one placebo seed), with v9 episode logic
# --------------------------------------------------------------------------
def run_cell(ctx, cadence, seed=None):
    mkt, fb = ctx["mkt"], ctx["fb_decade"]
    eqs, shs = ctx["eq_struct"], ctx["sh_struct"]
    cal = mkt.cal
    sel_cal = cadence_dates(cal, cadence, START, END)
    sel_set = set(sel_cal)
    sel_vm = set(cadence_dates(fb.dates, cadence, START, END))
    mode = "ranked" if seed is None else "placebo"

    full_curve = []
    halts = []
    total_costs = 0.0
    total_orders = 0
    ep_start, ep_pot = START, POT
    restart = False
    second_halt = False
    final = None

    for episode in (1, 2):
        floor = 0.85 * ep_pot
        bres = basket_sim(mkt, ep_start, END, ep_pot / 2.0, sel_set, mode,
                          seed=seed if seed is not None else 42)
        vrng = random.Random(seed) if seed is not None else None
        vres = vm_sim(fb, eqs, shs, ep_start, END, ep_pot / 2.0, sel_vm,
                      placebo_rng=vrng)
        cal_days = [d for d in cal if ep_start <= d <= END]
        bl = blend_episode(cal_days, bres["curve"], vres["curve"], ep_pot,
                           sel_set, floor)
        curve = bl["curve"]
        if bl["halt_date"] is None:
            total_costs += (sum(f for _, f in bres["order_log"]) +
                            vres["costs"] + bl["transfer_costs"])
            total_orders += (len(bres["order_log"]) + len(vres["trades"]) +
                             2 * len(bl["rebalances"]))
            full_curve.extend(curve if episode == 1 else
                              [(d, v) for d, v in curve])
            final = curve[-1][1]
            break
        # --- halt: liquidate at next trading day's close ----------------
        hd = bl["halt_date"]
        hi = cal_days.index(hd)
        if hi < len(cal_days) - 1:
            nd = cal_days[hi + 1]
            Bd = dict(bres["curve"])
            vdates = sorted(dict(vres["curve"]))
            Vd = dict(vres["curve"])
            k = bisect_right(vdates, nd) - 1
            v_next = Vd[vdates[k]] if k >= 0 else ep_pot / 2.0
            nxt = bl["scaleA"] * Bd[nd] + bl["scaleB"] * v_next
            liq = nxt * (1 - 0.001) - 0.10
            liq_fee = nxt * 0.001 + 0.10
            liq_date = nd
        else:
            liq = curve[-1][1] * (1 - 0.001) - 0.10
            liq_fee = curve[-1][1] * 0.001 + 0.10
            liq_date = hd
        ep_costs = (sum(f for dd, f in bres["order_log"] if dd <= liq_date) +
                    sum(c for dd, c in vres["trades"] if dd <= liq_date) +
                    sum(r["cost"] for r in bl["rebalances"]) + liq_fee)
        ep_orders = (sum(1 for dd, _ in bres["order_log"] if dd <= liq_date) +
                     sum(1 for dd, _ in vres["trades"] if dd <= liq_date) +
                     2 * len(bl["rebalances"]))
        total_costs += ep_costs
        total_orders += ep_orders
        halts.append({"episode": episode, "signal_date": hd,
                      "floor": round(floor, 2),
                      "liquidation_date": liq_date,
                      "liquidation_value": round(liq, 2)})
        full_curve.extend(curve)
        full_curve.append((liq_date, liq))
        if episode == 2:
            second_halt = True
            final = liq
            break
        # sit in cash 90 calendar days; restart at next cadence date
        ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
        ready = date(ly, lm, ld) + timedelta(days=90)
        restart_date = next((d for d in sel_cal if d >= ready.isoformat()),
                            None)
        if restart_date is None or restart_date >= END:
            final = liq
            break
        restart = True
        for d in cal:
            if liq_date < d < restart_date:
                full_curve.append((d, liq))
        ep_start, ep_pot = restart_date, liq

    full_curve = sorted(dict(full_curve).items())
    return {"final": round(final, 2),
            "cagr_pct": round(cagr_pct(final, POT, START, END), 2),
            "max_dd_pct": round(max_dd(full_curve), 2),
            "costs": round(total_costs, 2),
            "orders": total_orders,
            "halts": len(halts), "halt_records": halts,
            "restart": restart, "second_halt": second_halt,
            "equity_curve": [[d, round(v, 4)] for d, v in full_curve]}


def parent_single(ctx, which, cadence):
    """One parent alone at $100 on the decade, v9 episodes, in-plumbing.
    Liquidation approximated at next day's close less 0.10% + $0.01x5
    (documented approximation, as in the original blend's halt note)."""
    mkt, fb = ctx["mkt"], ctx["fb_decade"]
    eqs, shs = ctx["eq_struct"], ctx["sh_struct"]
    cal = mkt.cal if which == "basket" else fb.dates
    sel_cal = cadence_dates(cal, cadence, START, END)
    sel_set = set(sel_cal)
    ep_start, ep_pot, final = START, POT, None
    halts = 0
    restart = False
    second = False
    for episode in (1, 2):
        floor = 0.85 * ep_pot
        if which == "basket":
            r = basket_sim(mkt, ep_start, END, ep_pot, sel_set, "ranked")
            curve = r["curve"]
        else:
            r = vm_sim(fb, eqs, shs, ep_start, END, ep_pot, sel_set)
            curve = r["curve"]
        halt_i = next((i for i, (_, v) in enumerate(curve) if v <= floor),
                      None)
        if halt_i is None:
            final = curve[-1][1]
            break
        halts += 1
        hd, hv = curve[halt_i]
        if halt_i < len(curve) - 1:
            liq = curve[halt_i + 1][1] * (1 - 0.001) - 0.05
            liq_date = curve[halt_i + 1][0]
        else:
            liq = hv * (1 - 0.001) - 0.05
            liq_date = hd
        if episode == 2:
            second = True
            final = liq
            break
        ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
        ready = (date(ly, lm, ld) + timedelta(days=90)).isoformat()
        rd = next((d for d in sel_cal if d >= ready), None)
        if rd is None or rd >= END:
            final = liq
            break
        restart = True
        ep_start, ep_pot = rd, liq
    return {"final": round(final, 2), "halts": halts, "restart": restart,
            "second_halt": second}


# --------------------------------------------------------------------------
# Integrity: original blend form (copied blend_curves from v4 script)
# --------------------------------------------------------------------------
def blend_curves_orig(curveA, curveB, pot0=100.0, floor=85.0):
    A, B = dict(curveA), dict(curveB)
    first = max(min(A), min(B))
    last = min(max(A), max(B))
    dates = sorted(d for d in (set(A) | set(B)) if first <= d <= last)
    start_year = dates[0][:4]
    jan_dates, seen_jan = set(), set()
    for d in dates:
        if d[5:7] == "01" and d[:4] != start_year and d[:4] not in seen_jan:
            seen_jan.add(d[:4])
            jan_dates.add(d)
    scaleA = scaleB = 1.0
    lastA = lastB = None
    pot_curve, transfer_costs, halt, final = [], 0.0, None, None
    for idx, d in enumerate(dates):
        if d in A:
            lastA = A[d]
        if d in B:
            lastB = B[d]
        va, vb = scaleA * lastA, scaleB * lastB
        tot = va + vb
        if d in jan_dates:
            transfer = abs(va - vb) / 2.0
            cost = transfer * 0.002 + 0.05
            tot -= cost
            transfer_costs += cost
            scaleA = (tot / 2.0) / lastA
            scaleB = (tot / 2.0) / lastB
            va = vb = tot / 2.0
        pot_curve.append((d, tot))
        if tot <= floor:
            halt = d
            if idx < len(dates) - 1:
                nd = dates[idx + 1]
                nxt = scaleA * A.get(nd, lastA) + scaleB * B.get(nd, lastB)
                final = nxt * (1 - 0.001) - 0.10
            else:
                final = tot * (1 - 0.001) - 0.10
            break
    if final is None:
        final = pot_curve[-1][1]
    return pot_curve, {"halt": halt, "final": final,
                       "transfer_costs": transfer_costs}


def build_vm_book_orig():
    ciks = vm.get_ciks()
    overrides = {"XOM": 34088}
    eq_rows, sh_rows = {}, {}
    for t in UNIVERSE:
        cik = overrides.get(t, ciks[t][0])
        facts = vm.get_companyfacts(cik)
        eq_rows[t] = (
            vm.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            vm.pit_series(facts, "us-gaap",
                          "StockholdersEquityIncludingPortionAttributable"
                          "ToNoncontrollingInterest", prio=1))
        sh_rows[t] = (
            vm.pit_series(facts, "dei",
                          "EntityCommonStockSharesOutstanding", prio=3) +
            vm.pit_series(facts, "us-gaap",
                          "CommonStockSharesOutstanding", prio=2) +
            vm.pit_series(facts, "us-gaap",
                          "WeightedAverageNumberOfSharesOutstandingBasic",
                          prio=1))
        time.sleep(0.02)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = vm.get_prices(t)
    return vm.PriceBook(bars), eq_rows, sh_rows


def cells_only(_saved):
    return {}


def _sweep_and_write(ctx, _preload, say, log, t0, repro, parents,
                     spy_final):
    cells = {}
    for cadence in CADENCES:
        cpath = os.path.join(HERE, "cells", f"{cadence}.json")
        if os.path.exists(cpath):
            with open(cpath) as f:
                cf = json.load(f)
            cells[cadence] = {k: cf[k] for k in
                              ("final", "cagr_pct", "max_dd_pct", "halts",
                               "restart", "second_halt", "costs", "orders",
                               "placebo_beaten", "placebo_note",
                               "placebo_twin_finals")}
            say(f"=== cell {cadence}: already on disk, loaded "
                f"(final ${cf['final']}) ===")
            continue
        say(f"=== cell {cadence}: ranked ===")
        res = run_cell(ctx, cadence)
        say(f"    ranked final ${res['final']} halts={res['halts']} "
            f"costs=${res['costs']} orders={res['orders']}")
        say(f"=== cell {cadence}: 20 placebos ===")
        twins = []
        for s in range(1, 21):
            pr = run_cell(ctx, cadence, seed=s)
            twins.append(round(pr["final"], 2))
            say(f"    seed {s}: ${pr['final']}")
        beaten = sum(1 for v in twins if res["final"] > v)
        say(f"    placebos beaten {beaten}/20 "
            f"(median ${sorted(twins)[10]:.2f})")
        cell = {"final": res["final"], "cagr_pct": res["cagr_pct"],
                "max_dd_pct": res["max_dd_pct"], "halts": res["halts"],
                "restart": res["restart"],
                "second_halt": res["second_halt"],
                "costs": res["costs"], "orders": res["orders"],
                "placebo_beaten": f"{beaten}/20",
                "placebo_note": "Random-rank twins: both legs pick random "
                                "eligible/scored names at the same cadence, "
                                "same blend + v9 machinery, seeds 1-20.",
                "placebo_twin_finals": twins}
        cells[cadence] = cell
        cf = dict(cell)
        cf.update({"cadence": cadence, "window": [START, END],
                   "start_pot": POT, "halt_records": res["halt_records"],
                   "equity_curve": res["equity_curve"]})
        with open(cpath, "w") as f:
            json.dump(cf, f, indent=1)

    money = [c for c in CADENCES
             if cells[c]["final"] > spy_final and
             int(cells[c]["placebo_beaten"].split("/")[0]) > 10]
    out = {
        "slug": "winners-blend",
        "area": "Long-horizon quarterly value/momentum holding on the pond "
                "(W1 variant family — variants of the champion, judged on "
                "the champion's road); v10 form: DECADE cadence sweep, "
                "cadence applied uniformly to both legs and the split "
                "rebalance.",
        "area_source": "SPEC.md W1 batch + THE CADENCE SWEEP "
                       "(2026-11-21 ~22:09) + task cadence-treatment note",
        "native_cadence": "quarterly",
        "cadence": "quarterly",
        "original_cadence_foreign": False,
        "original_cadence_foreign_note": "Per CADENCE GRID W1 the blend is "
            "classified quarterly/native, none foreign. The original test "
            "in fact ran mixed native tempos (basket leg monthly, VM leg "
            "quarterly, split rebalanced each January); the sweep replaces "
            "that mix with one uniform cadence per cell (see RESULTS.md).",
        "integrity": {
            "status": "reproduced",
            "original_finals": {"CONT": 400.84, "VAL": 245.18},
            "reproduced_finals": {"CONT": repro["continuous"],
                                  "VAL": repro["validation"]},
            "parent_checks": {"basket_ladder_full2016": 439.45,
                              "vm_plainfloor_CONT": 544.47,
                              "vm_plainfloor_VAL": 288.05},
            "note": "Original engines imported verbatim from "
                    "backtests/v4 (momentum-basket-honest.py, "
                    "value-momentum-plainfloor.py); blend combined with "
                    "the original script's own blend_curves logic "
                    "(January split rebalance, plain $85 pot floor, $50 "
                    "sleeves with no sleeve floor). Both finals reproduced "
                    "to the cent. Cadence copies of both sleeve engines "
                    "were separately validated against the originals "
                    "(VM quarterly CONT curve-last $545.06; basket monthly "
                    "CONT $100 matched the original engine)."},
        "decade_spy_final": round(spy_final, 2),
        "spy": {"DECADE": round(spy_final, 2)},
        "parents_decade": {
            "momentum_basket_monthly_inplumbing_v9": parents["basket_monthly"],
            "value_momentum_quarterly_inplumbing_v9": parents["vm_quarterly"],
            "value_momentum_quarterly_reference": {
                "final": 65.89,
                "note": "Champion decade from the lazy-quarterly test: "
                        "two halts; its crown rests on the 2010 and 2019 "
                        "roads, the decade caveat applies."}},
        "cells": cells,
        "money_cadences": money,
        "verdict_area": None,
        "verdict_change": None,
        "run_log": log,
        "runtime_sec": round(time.time() - t0, 1),
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    say(f"DONE; money cadences: {money}")


def main():
    t0 = time.time()
    log = []
    def say(s):
        print(s, flush=True)
        log.append(s)

    ctx_path = os.path.join(HERE, "context.json")
    saved_ctx = None
    if os.path.exists(ctx_path):
        with open(ctx_path) as f:
            saved_ctx = json.load(f)
        say("context.json found — integrity/parents already done, "
            "skipping to sweep (context rebuilt from caches)")

    say("loading basket market (v4 cache, read-only)...")
    mkt = mb.Market(mb.UNIVERSE)
    if saved_ctx is not None:
        # rebuild data context only; integrity numbers come from context
        pb, eq_rows, sh_rows = build_vm_book_orig()
        eq_struct = {t: make_pit_struct(eq_rows[t]) for t in UNIVERSE}
        sh_struct = {t: make_pit_struct(sh_rows[t]) for t in UNIVERSE}
        fb_decade = build_decade_book()
        ctx = {"mkt": mkt, "fb_decade": fb_decade,
               "eq_struct": eq_struct, "sh_struct": sh_struct}
        repro = saved_ctx["repro"]
        parents = saved_ctx["parents"]
        spy_final = saved_ctx["spy_final"]
        _sweep_and_write(ctx, cells_only(saved_ctx), say, log, t0,
                         repro, parents, spy_final)
        return

    # ---------------- integrity: parent engine checks -------------------
    r = mb.simulate(mkt, "2016-11-21", "2026-11-20", 100, "ranked")
    say(f"CHECK basket original ladder full-2016 $100: ${r.final:.2f} "
        f"(published $439.45)")
    assert abs(r.final - 439.45) < 0.05

    say("loading VM original book (v4 caches, read-only)...")
    pb, eq_rows, sh_rows = build_vm_book_orig()
    r = vm.run_pot(pb, eq_rows, sh_rows, "2019-01-02", "2026-11-20",
                   100.0, 85.0, [], quiet=True)
    say(f"CHECK vm plainfloor CONT $100: ${r['final']:.2f} "
        f"(published $544.47)")
    assert abs(r["final"] - 544.47) < 0.05
    r = vm.run_pot(pb, eq_rows, sh_rows, "2023-01-03", "2026-11-20",
                   100.0, 85.0, [], quiet=True)
    say(f"CHECK vm plainfloor VAL $100: ${r['final']:.2f} "
        f"(published $288.05)")
    assert abs(r["final"] - 288.05) < 0.05

    # ---------------- integrity: the blend in original form -------------
    orig_floors = mb.FLOORS
    mb.FLOORS = {100: (85.0, []), 50: (0.0, [])}
    repro = {}
    for wname, (sd, ed) in {"continuous": ("2019-01-01", "2026-11-20"),
                            "validation": ("2023-01-01", "2026-11-20")}.items():
        mbs = mb.simulate(mkt, sd, ed, 50, "ranked")
        vms = vm.run_pot(pb, eq_rows, sh_rows, sd, ed, 50.0, 0.0, [],
                         quiet=True)
        _, info = blend_curves_orig(mbs.equity_curve, vms["curve"])
        repro[wname] = round(info["final"], 2)
        say(f"CHECK blend original form {wname}: ${info['final']:.2f}")
    mb.FLOORS = orig_floors
    assert abs(repro["continuous"] - 400.84) < 0.05, repro
    assert abs(repro["validation"] - 245.18) < 0.05, repro
    say("INTEGRITY: reproduced (CONT $400.84, VAL $245.18)")

    # ---------------- validate my cadence copies vs originals -----------
    fb_orig = FastBook({t: vm.get_prices(t) for t in UNIVERSE + ["SPY"]})
    eq_struct = {t: make_pit_struct(eq_rows[t]) for t in UNIVERSE}
    sh_struct = {t: make_pit_struct(sh_rows[t]) for t in UNIVERSE}
    qtr = set(cadence_dates(fb_orig.dates, "quarterly",
                            "2019-01-02", "2026-11-20"))
    mine = vm_sim(fb_orig, eq_struct, sh_struct, "2019-01-02", "2026-11-20",
                  100.0, qtr)
    say(f"CHECK my VM copy quarterly CONT curve-last: ${mine['final']:.2f} "
        f"(original engine curve-last $545.06)")
    assert abs(mine["final"] - 545.06) < 0.05, mine["final"]
    mb.FLOORS = {100: (85.0, []), 50: (0.0, [])}
    mbp = mb.simulate(mkt, "2019-01-01", "2026-11-20", 100, "ranked")
    mb.FLOORS = orig_floors
    mset = set(cadence_dates(mkt.cal, "monthly", "2019-01-01", "2026-11-20"))
    mine_b = basket_sim(mkt, "2019-01-01", "2026-11-20", 100.0, mset,
                        "ranked")
    say(f"CHECK my basket copy monthly CONT $100: ${mine_b['final']:.2f} "
        f"(original engine ${mbp.final:.2f})")
    assert abs(mine_b["final"] - mbp.final) < 0.05

    # ---------------- decade context ------------------------------------
    say("building decade VM book (pxfull long-history caches)...")
    fb_decade = build_decade_book()
    ctx = {"mkt": mkt, "fb_decade": fb_decade,
           "eq_struct": eq_struct, "sh_struct": sh_struct}
    spy_final = decade_spy(fb_decade)
    say(f"SPY decade (dividend-adjusted, in-plumbing): ${spy_final:.2f}")

    parents = {"basket_monthly": parent_single(ctx, "basket", "monthly"),
               "vm_quarterly": parent_single(ctx, "vm", "quarterly")}
    say(f"parents decade in-plumbing: basket monthly "
        f"${parents['basket_monthly']['final']}, VM quarterly "
        f"${parents['vm_quarterly']['final']}")

    # ---------------- save context, then sweep -----------------------
    with open(ctx_path, "w") as f:
        json.dump({"repro": repro, "parents": parents,
                   "spy_final": spy_final}, f, indent=1)
    _sweep_and_write(ctx, {}, say, log, t0, repro, parents, spy_final)


def fb_decade_as_pb(fb):
    return None


def decade_spy(fb):
    """SPY buy-and-hold, dividend-adjusted, vm.spy_net convention,
    computed on the FastBook bars."""
    days = [d for d in fb.dates if START <= d <= END]
    first, last = days[0], days[-1]
    i0 = fb.didx["SPY"][first]
    o = fb.opens["SPY"][i0]
    sh = (100.0 / 1.001) / o
    c = fb.close_on_or_before("SPY", last)
    val = sh * c
    return val - (val * 0.001 + 0.01)


if __name__ == "__main__":
    main()
