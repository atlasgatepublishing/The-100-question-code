#!/usr/bin/env python3
"""
SLOW ILLIQUIDITY — COIN CROSS-SECTION (v12 Crypto Wing 1).
Implements CONSTRUCTION-SPEC.md as frozen: Amihud ILLIQ (trailing 90d mean
|ret|/dollar-volume), top-1% trim, vol terciles x most-illiquid quintile
(ceil(n/5) per tercile, min 1), equal weight, formation at month-end m,
skip m+1/m+2, hold month m+3 (buy open day 1, sell close last day),
30-day grace then ZERO for dead coins, PIT weekly CMC top-20 membership.
Rule sets: native (no floor) + v9 protections. Costs: 0.60%/side base,
1.50%/side if trailing median daily $vol < $10M, 3.00%/side if < $1M.
Zero-cost diagnostic twin. 20-seed placebos (FULL + VALIDATION, native).
BTC buy-hold beside every number.

WASH-TRADING FENCE: the ranking variable rests on reported volume, which
the program record (Cong et al. 2023) shows is >70% fabricated on
unregulated exchanges. No wash adjustment exists; the fence travels with
every number. See CONSTRUCTION-SPEC.md.
"""
import json, math, os, random, statistics
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
V4 = os.path.join(HERE, "..", "..", "v4")
SNAP = os.path.join(HERE, "..", "crypto-basket-pit", "data", "weekly_snapshots.json")
POT = 100.0
GRACE = 30
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}
WINDOWS = {"full": ("2017-01-01", "2026-11-20"),
           "design": ("2017-01-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}

def tier(med_dvol):
    if med_dvol is None: return 0.03
    if med_dvol < 1_000_000: return 0.03
    if med_dvol < 10_000_000: return 0.015
    return 0.006

# ------------------------------------------------------------------ data ----
def load_market():
    with open(os.path.join(V4, "crypto-basket-pit-results.json")) as f:
        reg = json.load(f)["registry"]
    coins = {}
    for cid_s, info in reg.items():
        cid = int(cid_s)
        path = os.path.join(DATA, f"vol_{cid}.json")
        if info["source"] == "excluded" or not os.path.exists(path):
            coins[cid] = {**info, "bars": {}}
            continue
        with open(path) as f: rows = json.load(f)
        if cid in CREDIBLE_START:
            rows = [r for r in rows if r["d"] >= CREDIBLE_START[cid]]
        bars = {}
        for r in rows:
            dv = r.get("qv")
            if dv is None: dv = r["c"] * (r.get("v") or 0.0)
            bars[r["d"]] = (r["o"], r["c"], dv)
        coins[cid] = {**info, "bars": bars}
    btc = coins[1]["bars"]
    cal = sorted(btc.keys())
    return coins, cal

class Mkt:
    def __init__(self, coins, cal, weekly):
        self.coins, self.cal = coins, cal
        self.ci = {d: i for i, d in enumerate(cal)}
        self.ff, self.lb, self.lastd = {}, {}, {}
        for cid, info in coins.items():
            bars = info["bars"]
            ff, lb, last = [], [], None
            for i, d in enumerate(cal):
                if d in bars: last = bars[d][1]; li = i
                ff.append(last); lb.append(li if last is not None else -1)
            self.ff[cid], self.lb[cid] = ff, lb
            self.lastd[cid] = max(bars) if bars else None
        self.snap_keys = sorted(weekly.keys())
        self.snap_top = {k: [c["cmc_id"] for c in weekly[k]["top20"]] for k in self.snap_keys}
    def universe(self, d):
        import bisect
        k = bisect.bisect_right(self.snap_keys, d) - 1
        return self.snap_top[self.snap_keys[k]] if k >= 0 else []
    def idx(self, d):  # last calendar index <= d
        import bisect
        return bisect.bisect_right(self.cal, d) - 1
    def value_close(self, cid, i):
        lb = self.lb[cid][i]
        if lb < 0: return None
        return self.ff[cid][i] if i - lb <= GRACE else 0.0
    def trade_open(self, cid, i):
        d = self.cal[i]
        bars = self.coins[cid]["bars"]
        if d in bars: return bars[d][0]
        vc = self.value_close(cid, i)
        return vc

# ------------------------------------------------------------- formation ----
_FORM_CACHE = {}
def formation(mkt, fdate):
    if fdate in _FORM_CACHE: return _FORM_CACHE[fdate]
    out = _formation(mkt, fdate)
    _FORM_CACHE[fdate] = out
    return out

def _formation(mkt, fdate):
    """Eligible pool + strategy picks at formation date fdate (a date string)."""
    fi = mkt.idx(fdate)
    if fi < 0: return [], []
    f = date.fromisoformat(mkt.cal[fi])
    start = (f - timedelta(days=90)).isoformat()
    pool = []
    for cid in mkt.universe(mkt.cal[fi]):
        if cid not in mkt.coins: continue  # weekly-only top-20, no mapped source (basket-pit convention)
        bars = mkt.coins[cid]["bars"]
        if not bars: continue
        days = sorted(d for d in bars if start < d <= mkt.cal[fi])
        valid = [d for d in days if bars[d][2] > 0 and bars[d][1] > 0]
        if len(valid) < 40: continue
        if (f - date.fromisoformat(valid[-1])).days > 7: continue
        rets, illiqs, dvols = [], [], []
        prev = None
        all_days = sorted(d for d in bars if d <= mkt.cal[fi])
        for d in all_days:
            c, dv = bars[d][1], bars[d][2]
            if prev is not None and prev > 0:
                r = c / prev - 1.0
                if d > start:
                    rets.append(r)
                    if dv > 0: illiqs.append(abs(r) / dv)
            prev = c
        if len(rets) < 40 or not illiqs: continue
        pool.append({"cid": cid, "illiq": statistics.mean(illiqs),
                     "vol": statistics.pstdev(rets) if len(rets) > 1 else 0.0,
                     "med_dvol": statistics.median([bars[d][2] for d in valid]),
                     "sym": mkt.coins[cid]["symbol"]})
    if len(pool) < 3: return pool, []
    # top-1% trim by formula (99th percentile)
    xs = sorted(p["illiq"] for p in pool)
    k = 0.99 * (len(xs) - 1); lo, hi = int(math.floor(k)), int(math.ceil(k))
    p99 = xs[lo] if lo == hi else xs[lo] + (xs[hi] - xs[lo]) * (k - lo)
    pool = [p for p in pool if p["illiq"] <= p99] or pool
    # vol terciles
    byv = sorted(pool, key=lambda p: p["vol"])
    n = len(byv)
    picks = []
    for t in range(3):
        grp = [p for j, p in enumerate(byv) if min(2, (j * 3) // n) == t]
        if not grp: continue
        take = max(1, math.ceil(len(grp) / 5))
        picks.extend(sorted(grp, key=lambda p: -p["illiq"])[:take])
    return pool, picks

def month_end(y, m):
    return date(y + (m == 12), (m % 12) + 1, 1) - timedelta(days=1)

def hold_months(w0, w1):
    """Yield (buy_date_str, sell_date_str, formation_date_str) within window."""
    y, m = int(w0[:4]), int(w0[5:7])
    out = []
    while True:
        fe = month_end(y, m)  # formation month-end
        hy, hm = y, m
        for _ in range(3):
            hm += 1
            if hm == 13: hm, hy = 1, hy + 1
        buy = date(hy, hm, 1)
        sell = min(month_end(hy, hm), date.fromisoformat(w1))
        if buy.isoformat() > w1: break
        if sell.isoformat() >= w0 and buy.isoformat() >= w0:
            out.append((buy.isoformat(), sell.isoformat(), fe.isoformat()))
        m += 1
        if m == 13: m, y = 1, y + 1
        if date(y, m, 1) > date.fromisoformat(w1) + timedelta(days=120): break
    return out

# ------------------------------------------------------------------- run ----
def run(mkt, wname, ruleset, cost_scale=1.0, placebo_seed=None):
    w0, w1 = WINDOWS[wname]
    i0, i1 = mkt.idx(w0), mkt.idx(w1)
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    sched = hold_months(w0, w1)
    equity = POT
    curve_d, curve_m = [], {}
    holdings = {}  # cid -> units
    picks_log = []
    floor_state = {"ep": 1, "base": POT, "halted_until": None, "dead": False,
                   "halts": 0, "restart_base": None}
    sched_by_buy = {b: (b, s, f) for b, s, f in sched}
    si = 0
    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        # buy at open on hold-month first day
        if d in sched_by_buy and not floor_state["dead"]:
            b, s, f = sched_by_buy[d]
            if floor_state["halted_until"] is None or d >= floor_state["halted_until"]:
                if floor_state["halted_until"] is not None:
                    floor_state["base"] = equity; floor_state["halted_until"] = None
                pool, picks = formation(mkt, f)
                if rng is not None:
                    picks = rng.sample(pool, min(len(picks), len(pool))) if pool else []
                if picks:
                    w = equity / len(picks)
                    newh = {}
                    spent = 0.0
                    for p in picks:
                        op = mkt.trade_open(p["cid"], i)
                        if op is None or op <= 0:
                            newh[p["cid"]] = 0.0; continue
                        ct = tier(p["med_dvol"]) * cost_scale
                        units = w * (1 - ct) / op
                        newh[p["cid"]] = units; spent += w
                        picks_log.append({"buy": b, "sell": s, "formation": f,
                                          "cid": p["cid"], "sym": p["sym"],
                                          "illiq": p["illiq"], "med_dvol": p["med_dvol"],
                                          "cost_tier": ct, "open": op})
                    holdings = newh
                    equity = equity - spent + sum(
                        (mkt.value_close(cid, i) or 0.0) * u for cid, u in holdings.items())
        # sell at close on hold-month last day
        is_sell = any(s == d for _, s, _ in sched)
        val = sum((mkt.value_close(cid, i) or 0.0) * u for cid, u in holdings.items()) \
            if holdings else equity
        if is_sell and holdings:
            net = 0.0
            for cid, u in holdings.items():
                vc = mkt.value_close(cid, i) or 0.0
                med = next((pl["med_dvol"] for pl in reversed(picks_log)
                            if pl["cid"] == cid), None)
                ct = 0.0 if vc == 0.0 else tier(med) * cost_scale
                net += vc * u * (1 - ct)
            equity = net; holdings = {}
            val = equity
        elif holdings:
            equity = val
        # v9 floor at close
        if ruleset == "v9" and not floor_state["dead"] and floor_state["halted_until"] is None:
            if equity <= floor_state["base"] * 0.85:
                # liquidate at next open (approximated: next day value_close net of sell costs)
                j = min(i + 1, i1)
                liq = 0.0
                if holdings:
                    for cid, u in holdings.items():
                        vc = mkt.value_close(cid, j) or 0.0
                        med = next((pl["med_dvol"] for pl in reversed(picks_log)
                                    if pl["cid"] == cid), None)
                        ct = 0.0 if vc == 0.0 else tier(med) * cost_scale
                        liq += vc * u * (1 - ct)
                else:
                    liq = equity
                equity = liq; holdings = {}
                floor_state["halts"] += 1
                if floor_state["ep"] == 1:
                    floor_state["ep"] = 2
                    floor_state["halted_until"] = (date.fromisoformat(d) + timedelta(days=90)).isoformat()
                else:
                    floor_state["dead"] = True
        curve_d.append([d, round(equity, 4)])
        curve_m[d[:7]] = round(equity, 4)
    return {"final": round(equity, 2), "curve_daily": curve_d,
            "curve_monthly": curve_m, "picks": picks_log if placebo_seed is None else [],
            "halts": floor_state["halts"]}

def btc_hold(mkt, wname):
    w0, w1 = WINDOWS[wname]
    i0, i1 = mkt.idx(w0), mkt.idx(w1)
    op = mkt.trade_open(1, i0); cl = mkt.ff[1][i1]
    units = POT * (1 - 0.006) / op
    final = units * cl * (1 - 0.006)
    curve = [[mkt.cal[i], round(units * (mkt.ff[1][i] or 0), 4)] for i in range(i0, i1 + 1)]
    return {"final": round(final, 2), "curve_daily": curve}

def maxdd(curve):
    peak, dd = -1, 0.0
    for _, v in curve:
        peak = max(peak, v); dd = min(dd, v / peak - 1 if peak > 0 else 0.0)
    return round(dd * 100, 1)

def period_stats(curve_m, w0):
    months = sorted(curve_m.keys())
    vals = [POT] + [curve_m[m] for m in months]
    rets = [vals[k + 1] / vals[k] - 1 for k in range(len(vals) - 1) if vals[k] > 0]
    if not rets: return {}
    prof = sum(1 for r in rets if r > 0)
    lose_run = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; lose_run = max(lose_run, cur)
    peak, since, stretch = -1, 0, 0
    for v in vals:
        if v >= peak: peak, since = v, 0
        else: since += 1; stretch = max(stretch, since)
    return {"periods": len(rets), "pct_profitable": round(100 * prof / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run": lose_run, "longest_stretch_between_highs_months": stretch,
            "average_pct_secondary": round(statistics.mean(rets) * 100, 2)}

def main():
    coins, cal = load_market()
    with open(SNAP) as f: weekly = json.load(f)
    mkt = Mkt(coins, cal, weekly)
    out = {"fences": "WASH-TRADING: ranking variable rests on reported volume; "
                     "Cong et al. 2023: >70% of volume on unregulated exchanges fabricated. "
                     "BTC drawdown history -77% to -94%. Floors in a 24/7 market gap through.",
           "windows": {}, "btc": {}, "placebos": {}, "per_coin": {}}
    for wname in WINDOWS:
        out["btc"][wname] = btc_hold(mkt, wname)
        for rs in ("native", "v9"):
            r = run(mkt, wname, rs)
            r["maxdd_pct"] = maxdd(r["curve_daily"])
            r["period_stats"] = period_stats(r["curve_monthly"], WINDOWS[wname][0])
            out["windows"][f"{wname}|{rs}"] = r
        twin = run(mkt, wname, "native", cost_scale=0.0)
        out["windows"][f"{wname}|native_zerocost"] = {
            "final": twin["final"], "maxdd_pct": maxdd(twin["curve_daily"])}
    for wname in ("full", "validation"):
        finals = []
        for seed in range(1, 21):
            r = run(mkt, wname, "native", placebo_seed=seed)
            finals.append(r["final"])
        strat = out["windows"][f"{wname}|native"]["final"]
        out["placebos"][wname] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                  "seeds_beaten": sum(1 for x in finals if strat > x),
                                  "strategy_final": strat}
    # per-coin: weeks in top20, standalone buy-hold over full window
    from collections import Counter
    wk = Counter()
    for k in mkt.snap_keys:
        for cid in mkt.snap_top[k]: wk[cid] += 1
    picks_c = Counter(pl["cid"] for pl in out["windows"]["full|native"]["picks"])
    bh = btc_hold(mkt, "full")
    for cid, info in sorted(coins.items()):
        bars = info["bars"]
        row = {"symbol": info["symbol"], "source": info["source"],
               "weeks_top20": wk.get(cid, 0), "times_picked_full_native": picks_c.get(cid, 0),
               "bars": len(bars)}
        if bars:
            ds = sorted(bars)
            row["first"], row["last"] = ds[0], ds[-1]
            i0 = mkt.idx(max(ds[0], WINDOWS["full"][0])); i1 = mkt.idx(WINDOWS["full"][1])
            op = mkt.trade_open(cid, i0)
            vc = mkt.value_close(cid, i1)
            if op and vc is not None:
                row["buyhold_full_final"] = round(POT * (1 - 0.006) / op * vc * (1 - 0.006), 2)
        out["per_coin"][str(cid)] = row
    out["btc"]["full_maxdd_pct"] = maxdd(bh["curve_daily"])
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f)
    for k, v in out["windows"].items():
        print(k, "final", v["final"], "maxDD", v["maxdd_pct"])
    for wname in WINDOWS: print("BTC", wname, out["btc"][wname]["final"])
    for wname, p in out["placebos"].items():
        print("placebo", wname, "median", p["median"], "seeds_beaten", p["seeds_beaten"], "/20")

if __name__ == "__main__":
    main()
