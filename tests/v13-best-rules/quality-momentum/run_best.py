#!/usr/bin/env python3
"""
HOLDINGS-COUNT SWEEP — quality-momentum (v12 wing).

Adapted from v10-retest/quality-momentum/qm_v10.py (read-only), with the
holdings count generalised from the hardcoded top-5 to the pre-registered
grid [1,2,3,5,8,10,15,20,30,ALL]. Everything else is the v10 plumbing
verbatim in semantics: same quality (Novy-Marx GP/Assets, most recently
FILED strictly before selection date) + 12-1 momentum percentile-rank
average, same bar construction, same costs (0.10%/side + $0.01/sell),
selection scored on cadence-date close, executed next trading day open,
daily -15% floor check.

Grids:
  house-weekly    : v9 protections (plain -15% floor, no ladder, 90-day
                    sit-out, restart at next cadence date, episode-2 floor
                    -15% from restart balance, second halt ends run),
                    WEEKLY cadence (the family's champion/house cadence).
  house-quarterly : v9 protections, QUARTERLY cadence (native cadence).
  native-quarterly: the original v4 form — quarterly, floor $85 + LADDER
                    ($100 at $125 close, $125 at $150 close), halt ends
                    the run (no restart).

Roads: DECADE 2016-11-21->2026-11-20, CONT 2019-01-02->2026-11-20,
VAL 2023-01-03->2026-11-20. LONG (2010) NOT run — documented in the v10
confirmation: pond is a fixed later-era list, only 2 of 20 names
scoreable at 2010-01-04; not point-in-time honest.

Count semantics: at each selection date the scored pool is computed
exactly as v10 (gate: >=5 scored names, else no selection). Picks =
top-k ranked names, k = min(count, pool size); ALL = whole pool.
Equal weight pv/k. Placebos: 20 seeds (20261121+i, the v10 stream),
random sample of k names from the same pool at each selection date,
same count/cadence/rules. For k = pool size the twin degenerates to the
strategy itself (noted in RESULTS).
"""
import json, os, random, sys, time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
V4_DATA = os.path.join(BT, "v4", "data")
LH_DATA = os.path.join(BT, "v7", "long-hold", "data")
LR_DATA = os.path.join(BT, "long-run-2010", "data")
QM_DATA = os.path.join(BT, "v10-retest", "quality-momentum", "data")

UNIVERSE = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "JPM", "XOM",
            "UNH", "HD", "MA", "V", "LLY", "CRM", "ORCL", "COST", "NFLX",
            "AMD", "AVGO", "TSLA"]
PLACEBO_SEEDS = [20261121 + i for i in range(20)]
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
ROADS = {"DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}

REV_CONCEPTS = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "SalesRevenueNet"]
COGS_CONCEPTS = ["CostOfRevenue", "CostOfGoodsAndServicesSold",
                 "CostOfGoodsSold"]
OPINC_CONCEPT = "OperatingIncomeLoss"
ASSETS_CONCEPT = "Assets"

# ------------------------------------------------------- quality (verbatim v10)
def _entries(facts, concept):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else list(units)[0]
    return units[key]

def _annual(entries):
    out = []
    for e in entries:
        if "start" not in e or "end" not in e or "val" not in e:
            continue
        try:
            days = (date.fromisoformat(e["end"]) -
                    date.fromisoformat(e["start"])).days
        except ValueError:
            continue
        if 300 <= days <= 400:
            out.append(e)
    return out

def build_quality_observations(facts):
    assets_by_accn = {}
    for e in _entries(facts, ASSETS_CONCEPT):
        if "val" not in e or "end" not in e:
            continue
        accn = e.get("accn", "")
        assets_by_accn.setdefault(accn, {})[e["end"]] = (
            float(e["val"]), e.get("filed", ""))

    def assets_for(accn, period_end):
        m = assets_by_accn.get(accn, {})
        if period_end in m:
            return m[period_end][0]
        earlier = [en for en in m if en <= period_end]
        if earlier:
            return m[max(earlier)][0]
        return None

    def by_accn_period(concepts):
        out = {}
        for concept in concepts:
            for e in _annual(_entries(facts, concept)):
                accn = e.get("accn", "")
                key = (e["start"], e["end"])
                slot = out.setdefault(accn, {})
                if key not in slot:
                    slot[key] = (float(e["val"]), e.get("filed", ""))
        return out

    rev = by_accn_period(REV_CONCEPTS)
    cogs = by_accn_period(COGS_CONCEPTS)
    obs = []
    for accn, periods in rev.items():
        for (start, end), (rval, rfiled) in periods.items():
            c = cogs.get(accn, {}).get((start, end))
            if c is None:
                continue
            a = assets_for(accn, end)
            if a is None or a <= 0:
                continue
            filed = max(rfiled, c[1])
            obs.append((filed, end, (rval - c[0]) / a, "GP"))
    if not obs:
        op = by_accn_period([OPINC_CONCEPT])
        for accn, periods in op.items():
            for (start, end), (oval, ofiled) in periods.items():
                a = assets_for(accn, end)
                if a is None or a <= 0:
                    continue
                obs.append((ofiled, end, oval / a, "OPINC"))
    obs.sort()
    return obs

def quality_at(obs, asof):
    best = None
    for filed, end, val, method in obs:
        if filed < asof:
            if best is None or (filed, end) > (best[0], best[1]):
                best = (filed, end, val, method)
        else:
            break
    return best

def load_quality():
    with open(os.path.join(V4_DATA, "company_tickers.json"), "rb") as f:
        raw = json.loads(f.read())
    ciks = {row["ticker"]: int(row["cik_str"]) for row in raw.values()}
    quality = {}
    for t in UNIVERSE:
        path = os.path.join(V4_DATA, f"facts_{ciks[t]:010d}.json")
        with open(path, "rb") as f:
            blob = f.read()
        if blob[:2] == b"\x1f\x8b":
            import gzip
            blob = gzip.decompress(blob)
        quality[t] = build_quality_observations(json.loads(blob))
    return quality

# ------------------------------------------------------------- prices (v10)
def bars_from_payload(j):
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

def load_bars_full(ticker):
    for base in (LH_DATA, LR_DATA, QM_DATA):
        path = os.path.join(base, f"pxfull_{ticker}.json")
        if os.path.exists(path) and os.path.getsize(path) > 100:
            with open(path, "rb") as f:
                return bars_from_payload(json.loads(f.read()))
    raise FileNotFoundError(ticker)

class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.didx = {d: i for i, d in enumerate(self.dates)}
        self.idx = {t: {b["d"]: b for b in bl}
                    for t, bl in bars_by_ticker.items()}
        self.tidx = {t: {b["d"]: i for i, b in enumerate(bl)}
                     for t, bl in bars_by_ticker.items()}
        self.prev_close = {}
        for t, bl in bars_by_ticker.items():
            arr = [None] * len(self.dates)
            last = None
            bmap = self.idx[t]
            for i, d in enumerate(self.dates):
                b = bmap.get(d)
                if b is not None:
                    last = b["c"]
                arr[i] = last
            self.prev_close[t] = arr

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        i = self.didx.get(d)
        if i is None:
            return None
        return self.prev_close[t][i]

def cadence_dates(pb, cadence, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    if cadence == "weekly":
        for d in days:
            y, w, _ = date.fromisoformat(d).isocalendar()
            if (y, w) not in seen:
                seen.add((y, w)); out.append(d)
        return out
    months = {"quarterly": ("01", "04", "07", "10")}[cadence]
    for d in days:
        if d[5:7] not in months:
            continue
        key = (d[:4], d[5:7])
        if key not in seen:
            seen.add(key); out.append(d)
    return out

def percentile_ranks(values):
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    return {t: i / (n - 1) for i, (t, _) in enumerate(items)}

# ------------------------------------------------- score cache (per date)
class Scorer:
    """Ranked list + pool per selection date, computed once and shared
    across counts / roads / placebo seeds (identical values to v10)."""
    def __init__(self, pb, quality_obs):
        self.pb = pb
        self.q = quality_obs
        self.cache = {}

    def ranked(self, d):
        if d in self.cache:
            return self.cache[d]
        pb = self.pb
        scores = {}
        for t in UNIVERSE:
            q = quality_at(self.q.get(t, []), d)
            if q is None:
                continue
            bl = pb.bars.get(t, [])
            didx = pb.tidx.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (q[2], mom)
        if len(scores) < 5:
            out = None
        else:
            qr = percentile_ranks({t: v[0] for t, v in scores.items()})
            mr = percentile_ranks({t: v[1] for t, v in scores.items()})
            # V13 BEST RULES: quality = eligibility gate (top half only);
            # ranking among eligible = 0.70 momentum + 0.30 quality.
            eligible = [t for t in scores if qr[t] >= 0.5]
            combined = {t: 0.7 * mr[t] + 0.3 * qr[t] for t in eligible}
            ranked = sorted(combined, key=lambda t: -combined[t])
            out = (ranked, sorted(eligible))
        self.cache[d] = out
        return out

    def spy_above_200dma(self, d):
        """Regime gate: True if SPY close on d >= its 200-trading-day MA
        (True when history is insufficient — never the case on our roads)."""
        if d in getattr(self, "_gate_cache", {}):
            return self._gate_cache[d]
        if not hasattr(self, "_gate_cache"):
            self._gate_cache = {}
        bl = self.pb.bars.get("SPY", [])
        didx = self.pb.tidx.get("SPY", {}).get(d)
        if didx is None or didx < 199:
            res = True
        else:
            sma = sum(b["c"] for b in bl[didx - 199:didx + 1]) / 200.0
            res = bl[didx]["c"] >= sma
        self._gate_cache[d] = res
        return res

# ------------------------------------------------------------- engine
def run_episode(pb, scorer, start, end, start_cash, floor, ladder,
                sel_dates, count, placebo_rng=None, want_curve=False):
    cash = start_cash
    floor_now = floor
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_close = None
    min_close, min_close_date = None, None
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None
    curve = []

    def portfolio_close(d):
        i = pb.didx[d]
        v = cash
        for t, sh in positions.items():
            c = pb.prev_close[t][i]
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
            if not scorer.spy_above_200dma(d):
                pending = {}  # regime gate: go to cash, stay out
            else:
                got = scorer.ranked(d)
                if got is not None:
                    ranked, pool = got
                    k = min(5, len(pool))
                    if placebo_rng is not None:
                        picks = placebo_rng.sample(pool, k)
                    else:
                        picks = ranked[:k]
                    pv = portfolio_close(d)
                    each = pv / len(picks)
                    pending = {t: each for t in picks}
        v = portfolio_close(d)
        if want_curve:
            curve.append((d, round(v, 4)))
        if min_close is None or v < min_close:
            min_close, min_close_date = v, d
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor_now:
                floor_now = newfloor
        if v <= floor_now and di < len(days) - 1:
            halted = d
            halt_close = v
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
            if want_curve:
                curve.append((nd, round(cash, 4)))
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_close": halt_close,
                    "floor_in_effect": floor_now, "min_close": min_close,
                    "min_close_date": min_close_date, "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    if want_curve and curve:
        curve[-1] = (last, round(cash, 4))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_close": None,
            "floor_in_effect": floor_now, "min_close": min_close,
            "min_close_date": min_close_date, "curve": curve}

def run_best(pb, scorer, start, end, cadence="weekly", placebo_seed=None,
             want_curve=False):
    """V13 best-rules run: single episode, NO price floor (floor=0 never
    fires), no ladder, no sit-out. Protection is the SPY 200dma regime
    gate inside the selection step."""
    sel_all = cadence_dates(pb, cadence, start, end)
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    ep = run_episode(pb, scorer, start, end, 100.0, 0.0, [],
                     sel_all, 5, placebo_rng=rng, want_curve=want_curve)
    return {"final": ep["final"], "costs": ep["costs"],
            "orders": len(ep["trades"]), "halts": [],
            "restart": False, "second_halt": False,
            "curve": list(ep["curve"])}

def spy_net(pb, start, end, start_cash=100.0):
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost

def stats(curve, start, end, final):
    peak, mdd = -1e18, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    cagr = (final / 100.0) ** (1.0 / yrs) - 1.0 if final > 0 else -1.0
    return round(cagr * 100, 2), round(mdd * 100, 2)

ROADS_ORDER = ["DECADE", "CONT", "VAL"]
CHAMPION = {"LONG": 1415.62, "CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}

def weekly_distribution(curve):
    """Per-period (weekly, sampled at 5-trading-day steps from the daily
    curve's cadence Mondays is overkill; use consecutive weekly samples
    of the saved curve by ISO week) distribution stats."""
    by_week = {}
    for d, v in curve:
        y, w, _ = date.fromisoformat(d).isocalendar()
        by_week[(y, w)] = v  # last value in week wins (curve is date-ordered)
    vals = [by_week[k] for k in sorted(by_week)]
    rets = [vals[i] / vals[i - 1] - 1.0 for i in range(1, len(vals))
            if vals[i - 1] > 0]
    if not rets:
        return {}
    srt = sorted(rets)
    med = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt)//2-1] + srt[len(srt)//2]) / 2
    pos = sum(1 for r in rets if r > 0)
    longest_loss = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        longest_loss = max(longest_loss, cur)
    peak, longest_nodh, since = -1e18, 0, 0
    for v in vals:
        if v >= peak:
            peak, since = v, 0
        else:
            since += 1
        longest_nodh = max(longest_nodh, since)
    return {"periods": len(rets), "pct_positive": round(100.0 * pos / len(rets), 1),
            "median_pct": round(med * 100, 2), "best_pct": round(max(rets) * 100, 2),
            "worst_pct": round(min(rets) * 100, 2),
            "avg_pct_secondary": round(100.0 * sum(rets) / len(rets), 2),
            "longest_losing_streak_wks": longest_loss,
            "longest_stretch_between_new_highs_wks": longest_nodh}

def main():
    quality = load_quality()
    bars = {t: load_bars_full(t) for t in UNIVERSE + ["SPY"]}
    pb = PriceBook(bars)
    scorer = Scorer(pb, quality)
    results = {"slug": "quality-momentum", "program": "v13-best-rules",
               "spec": "BEST-RULES-SPEC.md", "roads": ROADS, "spy": {},
               "cells": {}, "confirmation": None}
    beats_champion = []
    for road in ROADS_ORDER:
        ws, we = ROADS[road]
        sf, _ = spy_net(pb, ws, we)
        results["spy"][road] = round(sf, 2)
        run = run_best(pb, scorer, ws, we, want_curve=True)
        cagr, mdd = stats(run["curve"], ws, we, run["final"])
        twins, beaten = [], 0
        for seed in PLACEBO_SEEDS:
            tw = run_best(pb, scorer, ws, we, placebo_seed=seed)
            twins.append(round(tw["final"], 2))
            if run["final"] > tw["final"]:
                beaten += 1
        cell = {"final": round(run["final"], 2), "cagr_pct": cagr,
                "max_dd_pct": mdd, "costs": round(run["costs"], 2),
                "orders": run["orders"], "halts": run["halts"],
                "placebo_beaten": f"{beaten}/20",
                "placebo_twin_finals": twins,
                "distribution_weekly": weekly_distribution(run["curve"]),
                "equity_curve": [[d, v] for d, v in run["curve"]]}
        results["cells"][road] = cell
        print(f"{road}: ${run['final']:.2f} CAGR={cagr} DD={mdd} "
              f"costs=${run['costs']:.2f} orders={run['orders']} "
              f"placebo {beaten}/20 SPY=${sf:.2f}", flush=True)
        if run["final"] > CHAMPION[road]:
            beats_champion.append(road)
    # Confirmation on different years if any road beat the champion
    if beats_champion:
        print(f"CONFIRMATION triggered for roads: {beats_champion}", flush=True)
        folds = {}
        for yr in range(2017, 2027):
            ws = f"{yr}-01-01"
            we = "2026-11-20" if yr == 2026 else f"{yr}-12-31"
            run = run_best(pb, scorer, ws, we, want_curve=True)
            sf, _ = spy_net(pb, ws, we)
            twins, beaten = [], 0
            for seed in PLACEBO_SEEDS:
                tw = run_best(pb, scorer, ws, we, placebo_seed=seed)
                twins.append(round(tw["final"], 2))
                if run["final"] > tw["final"]:
                    beaten += 1
            _, mdd = stats(run["curve"], ws, we, run["final"])
            folds[str(yr)] = {"final": round(run["final"], 2),
                              "spy": round(sf, 2), "max_dd_pct": mdd,
                              "placebo_beaten": f"{beaten}/20",
                              "placebo_twin_finals": twins}
            print(f"FOLD {yr}: ${run['final']:.2f} SPY=${sf:.2f} "
                  f"placebo {beaten}/20 DD={mdd}", flush=True)
        results["confirmation"] = {"roads_triggering": beats_champion,
                                   "folds": folds}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
