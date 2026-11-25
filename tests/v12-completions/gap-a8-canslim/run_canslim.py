#!/usr/bin/env python3
"""
V12 CONSTRUCTED CAN SLIM (gap-a8) — frozen construction per CONSTRUCTION-SPEC.md.
Simulation only. Reads ONLY cached data (read-only): v7/long-hold pxfull_*.json
daily Yahoo payloads + EDGAR companyfacts in the same folder. Writes only here.
"""
import json, os, sys, math, random, gzip
from bisect import bisect_right
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
sys.path.insert(0, os.path.join(BT, "long-run-2010"))
import lr_common as lr  # POOL + CIK_ERA only; no network calls used

START_CASH = 100.0
FLOOR = 85.0
BUY_COST = 0.001
SELL_COST = 0.001
SELL_FEE = 0.01
MAX_POS = 5
POS_FRAC = 0.20
STOP = 0.075
PROFIT = 0.225

# ---------------------------------------------------------------- data load
def load_bars(ticker):
    path = os.path.join(LH, f"pxfull_{ticker}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        payload = json.load(f)
    try:
        res = payload["chart"]["result"][0]
    except Exception:
        return None
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        o, h, l = q["open"][i], q["high"][i], q["low"][i]
        v = q["volume"][i] or 0
        d = __import__("time").strftime("%Y-%m-%d", __import__("time").gmtime(t))
        bars.append({"d": d, "o": (o * r if o else a), "h": (h * r if h else a),
                     "l": (l * r if l else a), "c": a, "v": float(v)})
    bars.sort(key=lambda b: b["d"])
    # de-dup
    out, seen = [], set()
    for b in bars:
        if b["d"] in seen:
            continue
        seen.add(b["d"])
        out.append(b)
    return out

FACTS_DIRS = [os.path.join(BT, "v5", "vm-broad", "data"),
              os.path.join(BT, "long-run-2010", "data"),
              LH,
              os.path.join(BT, "v4", "data"),
              os.path.join(BT, "v9-muse-rules", "quality-momentum", "data"),
              os.path.join(BT, "v4", "basket-issuance-veto-data"),
              os.path.join(BT, "v4", "value-momentum-honest-data")]

def load_facts_for(ticker):
    try:
        cik = lr.cik_for(ticker)
    except Exception:
        return None
    cik = int(cik[0]) if isinstance(cik, (list, tuple)) else int(cik)
    path = None
    for dd in FACTS_DIRS:
        p = os.path.join(dd, f"facts_{cik:010d}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            path = p
            break
    if path is None:
        return None
    with open(path, "rb") as f:
        blob = f.read()
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    return json.loads(blob)

# ------------------------------------------------------- fundamentals (PIT)
def concept_rows(facts, concept, dur_lo=None, dur_hi=None):
    """end -> sorted list of (filed, val). Duration filter in days if given."""
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return {}
    key = "USD" if "USD" in units else ("USD/shares" if "USD/shares" in units
                                        else list(units)[0])
    by_end = {}
    for e in units[key]:
        if "filed" not in e or "val" not in e or "end" not in e:
            continue
        if dur_lo is not None:
            if "start" not in e:
                continue
            dur = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
            if not (dur_lo <= dur <= dur_hi):
                continue
        by_end.setdefault(e["end"], []).append((e["filed"], float(e["val"])))
    for k in by_end:
        by_end[k].sort()
    return by_end

def asof(by_end, end, d):
    rows = by_end.get(end)
    if not rows:
        return None
    vals = [v for f, v in rows if f < d]
    return vals[-1] if vals else None

def latest_end(by_end, d, max_end=None):
    best = None
    for end, rows in by_end.items():
        if max_end and end > max_end:
            continue
        if any(f < d for f, _ in rows):
            if best is None or end > best:
                best = end
    return best

def shift_year(end, years=-1):
    y, m, dd = int(end[:4]) + years, end[5:7], end[8:10]
    # Feb 29 guard
    if m == "02" and dd == "29":
        dd = "28"
    return f"{y:04d}-{m}-{dd}"

def find_end_near(by_end, target, tol_days=25):
    t = date.fromisoformat(target).toordinal()
    best, bd = None, tol_days + 1
    for end in by_end:
        diff = abs(date.fromisoformat(end).toordinal() - t)
        if diff < bd:
            bd, best = diff, end
    return best

class Fund:
    def __init__(self, facts):
        self.q_eps = concept_rows(facts, "EarningsPerShareDiluted", 80, 100)
        self.q_rev = {}
        for c in ("RevenueFromContractWithCustomerExcludingAssessedTax",
                  "Revenues", "SalesRevenueNet"):
            r = concept_rows(facts, c, 80, 100)
            for k, v in r.items():
                self.q_rev.setdefault(k, v)
        self.a_eps = concept_rows(facts, "EarningsPerShareDiluted", 330, 400)
        self.a_ni = concept_rows(facts, "NetIncomeLoss", 330, 400)
        self.a_eq = concept_rows(facts, "StockholdersEquity")

    def _yoy(self, by_end, end, d):
        cur = asof(by_end, end, d)
        if cur is None:
            return None
        pe = find_end_near(by_end, shift_year(end))
        if pe is None:
            return None
        prev = asof(by_end, pe, d)
        if prev is None:
            return None
        return cur, prev

    def c_pass(self, d):
        end = latest_end(self.q_eps, d)
        if end is None:
            return False
        r = self._yoy(self.q_eps, end, d)
        if not r:
            return False
        cur, prev = r
        if prev <= 0 or cur <= 0 or (cur / prev - 1) < 0.25:
            return False
        # revenue: >=25% YoY OR accelerating
        rend = latest_end(self.q_rev, d)
        if rend is None:
            return False
        rr = self._yoy(self.q_rev, rend, d)
        if not rr:
            return False
        rcur, rprev = rr
        if rprev <= 0:
            return False
        g = rcur / rprev - 1
        if g >= 0.25:
            return True
        # prior quarter YoY
        pq = find_end_near(self.q_rev, (date.fromisoformat(rend) -
                                        __import__("datetime").timedelta(days=92)).isoformat(), 30)
        if pq is None:
            return False
        rr2 = self._yoy(self.q_rev, pq, d)
        if not rr2:
            return False
        pcur, pprev = rr2
        if pprev <= 0:
            return False
        return g > (pcur / pprev - 1)

    def a_pass(self, d):
        ends = sorted(e for e in self.a_eps if any(f < d for f, _ in self.a_eps[e]))
        if len(ends) < 4:
            return False
        last4 = ends[-4:]
        vals = [asof(self.a_eps, e, d) for e in last4]
        if any(v is None or v <= 0 for v in vals):
            return False
        for i in range(1, 4):
            if vals[i] / vals[i - 1] - 1 < 0.25:
                return False
        # ROE >= 17% on latest FY
        fy = last4[-1]
        ni = asof(self.a_ni, fy, d)
        eq = asof(self.a_eq, fy, d)
        if ni is None or eq is None or eq <= 0:
            return False
        return ni / eq >= 0.17

# ------------------------------------------------------------------- prices
class Series:
    def __init__(self, bars):
        self.bars = bars
        self.dates = [b["d"] for b in bars]
        self.idx = {b["d"]: i for i, b in enumerate(bars)}
        self.c = [b["c"] for b in bars]
        self.v = [b["v"] for b in bars]
        # IBD strength factor per index
        self.sf = [None] * len(bars)
        for i in range(252, len(bars)):
            c = self.c
            sf = (0.4 * (c[i] / c[i - 63] - 1) + 0.2 * (c[i] / c[i - 126] - 1)
                  + 0.2 * (c[i] / c[i - 189] - 1) + 0.2 * (c[i] / c[i - 252] - 1))
            self.sf[i] = sf

def compute_rs(series_by, master_dates):
    """date -> {ticker: rs 1..99}"""
    rs = {}
    for d in master_dates:
        vals = []
        for t, s in series_by.items():
            i = s.idx.get(d)
            if i is not None and s.sf[i] is not None:
                vals.append((s.sf[i], t))
        if len(vals) < 20:
            continue
        vals.sort()
        n = len(vals)
        day = {}
        for rank, (sf, t) in enumerate(vals):
            day[t] = 1 + int(98 * rank / max(n - 1, 1))
        rs[d] = day
    return rs

def market_states(spy):
    """date -> True if CONFIRMED UPTREND (constructed M mechanization)."""
    states = {}
    confirmed = False
    dist = set()
    closes = spy.c
    low_i = 0  # index of most recent 20-day closing low
    dist_epoch = -1  # distribution counts only after the last follow-through
    for i, b in enumerate(spy.bars):
        d = b["d"]
        if i == 0:
            states[d] = False
            continue
        prev = closes[i - 1]
        chg = closes[i] / prev - 1 if prev else 0
        if chg <= -0.002 and b["v"] > spy.bars[i - 1]["v"]:
            dist.add(d)
        if i >= 19 and closes[i] <= min(closes[i - 19:i + 1]):
            low_i = i
        if confirmed:
            cnt = sum(1 for j in range(max(dist_epoch + 1, i - 24), i + 1)
                      if spy.bars[j]["d"] in dist)
            if cnt >= 5:
                confirmed = False
        if not confirmed:
            # rally attempt anchored to the most recent 20-day closing low;
            # follow-through on day >=4 after that low
            if (i - low_i) >= 4 and closes[i] > closes[low_i] and \
                    chg >= 0.0125 and b["v"] > spy.bars[i - 1]["v"]:
                confirmed = True
                dist_epoch = i
        states[d] = confirmed
    return states

# ------------------------------------------------------------ base detection
def find_base(s, i):
    """Breakout day index i (signal at close of i). Look at bars < i.
    Returns pivot or None."""
    bars = s.bars
    if i < 290:
        return None
    # cup-with-handle: handle lengths 5..30
    for hl in range(5, 31):
        hs = i - hl  # handle start index
        if hs < 40:
            continue
        handle = bars[hs:i]
        hhigh = max(b["h"] for b in handle)
        hlow = min(b["l"] for b in handle)
        if hhigh <= 0 or (hhigh - hlow) / hhigh > 0.12:
            continue
        # cup: left rim = highest high in [hs-325, hs-5]
        lo_i = max(0, hs - 325)
        rim_i = max(range(lo_i, hs - 4), key=lambda j: bars[j]["h"])
        cup_len = hs - rim_i
        if cup_len < 35:
            continue
        rim_high = bars[rim_i]["h"]
        cup_low, cup_low_i = min(((bars[j]["l"], j) for j in range(rim_i, hs)))
        if rim_high <= 0:
            continue
        depth = (rim_high - cup_low) / rim_high
        if not (0.12 <= depth <= 0.33):
            continue
        # right rim near left rim
        if hhigh < rim_high * 0.95:
            continue
        # handle in upper half
        if hlow < (rim_high + cup_low) / 2:
            continue
        # roundedness residue: low in middle 60%
        frac = (cup_low_i - rim_i) / max(cup_len, 1)
        if not (0.2 <= frac <= 0.8):
            continue
        # prior uptrend >=30%: some close in 126 bars before rim <= rim_close/1.30
        rim_close = bars[rim_i]["c"]
        pre = s.c[max(0, rim_i - 126):rim_i]
        if not pre or min(pre) > rim_close / 1.30:
            continue
        # handle volume dry-up vs last 10 bars of cup
        hv = sum(b["v"] for b in handle) / len(handle)
        cv = sum(b["v"] for b in bars[hs - 10:hs]) / 10
        if cv > 0 and hv >= cv:
            continue
        return hhigh + 0.10
    # flat base: lengths 25..50
    for bl in range(25, 51):
        bs = i - bl
        if bs < 130:
            continue
        base = bars[bs:i]
        bh = max(b["h"] for b in base)
        blo = min(b["l"] for b in base)
        if bh <= 0 or (bh - blo) / bh > 0.15:
            continue
        start_close = bars[bs]["c"]
        pre = s.c[max(0, bs - 126):bs]
        if not pre or min(pre) > start_close / 1.30:
            continue
        return bh + 0.10
    return None

def breakout_candidates(s):
    """dict date -> pivot for days passing price/volume/new-high/base tests."""
    out = {}
    bars = s.bars
    for i in range(290, len(bars)):
        b = bars[i]
        if b["v"] <= 0:
            continue
        avg50 = sum(s.v[i - 50:i]) / 50
        if avg50 <= 0 or b["v"] < 1.5 * avg50:
            continue
        if b["c"] <= max(s.c[i - 252:i]):
            continue  # must be a new 252-bar closing high (N proxy)
        piv = find_base(s, i)
        if piv is None:
            continue
        if b["c"] > piv and b["c"] <= piv * 1.05:
            out[b["d"]] = piv
    return out

# ------------------------------------------------------------------- engine
def simulate(days, series_by, rs, mstates, cands, funds, start, end,
             placebo_seed=None, real_entries=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cash = START_CASH
    pos = {}  # t -> dict(shares, fill, entry_i_date, days_held, eight_week)
    curve = []
    trades = []
    total_costs = 0.0
    halted = None
    entries_made = []  # (date, ticker)
    entry_plan = None
    if rng is not None:
        entry_plan = {}
        for (d, _t) in real_entries:
            entry_plan.setdefault(d, 0)
            entry_plan[d] += 1

    def equity(d):
        v = cash
        for t, p in pos.items():
            s = series_by[t]
            i = s.idx.get(d)
            if i is None:
                j = bisect_right(s.dates, d) - 1
                px = s.c[j] if j >= 0 else 0.0
            else:
                px = s.c[i]
            v += p["shares"] * px
        return v

    for d in days:
        if not (start <= d <= end):
            continue
        # ---- exits
        for t in list(pos):
            s = series_by[t]
            i = s.idx.get(d)
            if i is None:
                continue
            p = pos[t]
            if d <= p["entry_date"]:
                continue
            p["days"] += 1
            bar = s.bars[i]
            if not p["eight"] and p["days"] <= 15 and bar["c"] >= p["fill"] * 1.20:
                p["eight"] = True
            sell_px, why = None, None
            stop_px = p["fill"] * (1 - STOP)
            if bar["l"] <= stop_px:
                sell_px = bar["o"] if bar["o"] < stop_px else stop_px
                why = "stop7.5"
            elif p["eight"] and p["days"] >= 40:
                ma50 = sum(s.c[i - 49:i + 1]) / 50 if i >= 49 else None
                if ma50 and bar["c"] < ma50:
                    sell_px, why = bar["c"], "eightwk-ma50"
            elif not p["eight"] and bar["c"] >= p["fill"] * (1 + PROFIT):
                sell_px, why = bar["c"], "profit22.5"
            if sell_px is not None:
                val = p["shares"] * sell_px
                cst = val * SELL_COST + SELL_FEE
                cash += val - cst
                total_costs += cst
                trades.append((d, t, "SELL", sell_px, val, why))
                del pos[t]
        # ---- floor
        eq = equity(d)
        if eq <= FLOOR:
            for t in list(pos):
                s = series_by[t]
                j = bisect_right(s.dates, d) - 1
                px = s.c[j] if j >= 0 else 0.0
                val = pos[t]["shares"] * px
                cst = val * SELL_COST + SELL_FEE if val > 0 else 0.0
                cash += val - cst
                total_costs += cst
                trades.append((d, t, "SELL", px, val, "floor"))
                del pos[t]
            halted = d
            curve.append((d, cash))
            break
        # ---- entries
        if rng is None:
            if mstates.get(d) and len(pos) < MAX_POS:
                day_cands = []
                for t, cd in cands.items():
                    if d in cd and t not in pos:
                        r = rs.get(d, {}).get(t)
                        if r is not None and r >= 80 and funds[t].c_pass(d) and funds[t].a_pass(d):
                            day_cands.append((r, t))
                day_cands.sort(reverse=True)
                for r, t in day_cands:
                    if len(pos) >= MAX_POS:
                        break
                    s = series_by[t]
                    px = s.bars[s.idx[d]]["c"]
                    budget = min(POS_FRAC * equity(d), cash / (1 + BUY_COST))
                    if budget < 1.0:
                        break
                    sh = budget / px
                    cst = budget * BUY_COST
                    cash -= budget + cst
                    total_costs += cst
                    pos[t] = {"shares": sh, "fill": px, "entry_date": d,
                              "days": 0, "eight": False}
                    trades.append((d, t, "BUY", px, budget, f"rs{r}"))
                    entries_made.append((d, t))
        else:
            n_want = entry_plan.get(d, 0)
            for _ in range(n_want):
                if len(pos) >= MAX_POS:
                    break
                pool = [t for t, s in series_by.items()
                        if d in s.idx and s.idx[d] >= 252 and t not in pos]
                if not pool:
                    break
                t = rng.choice(pool)
                s = series_by[t]
                px = s.bars[s.idx[d]]["c"]
                budget = min(POS_FRAC * equity(d), cash / (1 + BUY_COST))
                if budget < 1.0:
                    break
                sh = budget / px
                cst = budget * BUY_COST
                cash -= budget + cst
                total_costs += cst
                pos[t] = {"shares": sh, "fill": px, "entry_date": d,
                          "days": 0, "eight": False}
                trades.append((d, t, "BUY", px, budget, "placebo"))
                entries_made.append((d, t))
        curve.append((d, equity(d)))
    # ---- end of road: liquidate (vanished name -> ZERO per PROGRAM)
    if halted is None:
        last_d = days[-1] if days else end
        for t in list(pos):
            s = series_by[t]
            if s.dates and s.dates[-1] >= end:
                px = s.c[s.idx[end]] if end in s.idx else s.c[-1]
                val = pos[t]["shares"] * px
                cst = val * SELL_COST + SELL_FEE
                cash += val - cst
                total_costs += cst
                trades.append((end, t, "SELL", px, val, "end"))
            else:
                trades.append((end, t, "SELL", 0.0, 0.0, "vanished-zero"))
            del pos[t]
        if curve:
            curve[-1] = (curve[-1][0], cash)
    # max drawdown on curve
    peak, mdd = -1, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    wins = sum(1 for tr in trades if tr[2] == "SELL")
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "orders": len(trades), "halted": halted,
            "max_dd_pct": round(mdd * 100, 2),
            "curve": [[d, round(v, 2)] for d, v in curve],
            "trades": trades, "entries": entries_made}

ROADS = {"LONG": ("2010-01-04", "2026-11-20"),
         "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}

def main():
    series_by, funds, failures = {}, {}, []
    for t in lr.POOL:
        bars = load_bars(t)
        if not bars or len(bars) < 300:
            failures.append((t, "no/short price cache"))
            continue
        facts = load_facts_for(t)
        if facts is None:
            failures.append((t, "no facts cache"))
            continue
        series_by[t] = Series(bars)
        funds[t] = Fund(facts)
    spy = series_by.get("SPY")
    if spy is None:
        spy = Series(load_bars("SPY"))
        series_by["SPY"] = spy
    master = spy.dates
    print(f"universe: {len(series_by)} names; failures: {len(failures)}", flush=True)
    rs = compute_rs({t: s for t, s in series_by.items() if t != "SPY"}, master)
    mstates = market_states(spy)
    cands = {}
    for t, s in series_by.items():
        if t == "SPY":
            continue
        cands[t] = breakout_candidates(s)
    print("candidate breakout days total:", sum(len(v) for v in cands.values()), flush=True)
    results = {"universe_size": len(series_by) - 1, "failures": failures,
               "roads": {}}
    for name, (start, end) in ROADS.items():
        days = [d for d in master if d <= end]
        r = simulate(days, series_by, rs, mstates, cands, funds, start, end)
        spy_days = [d for d in master if start <= d <= end]
        s0 = spy.c[spy.idx[spy_days[0]]]
        s1 = spy.c[spy.idx[spy_days[-1]]]
        spy_final = round(100 * (s1 / s0) * (1 - 0.001) - 0.01 * (s1 / s0), 2)
        beaten = 0
        pfin = []
        for seed in range(20):
            pr = simulate(days, series_by, rs, mstates, cands, funds, start, end,
                          placebo_seed=seed, real_entries=r["entries"])
            pfin.append(pr["final"])
            if r["final"] > pr["final"]:
                beaten += 1
        results["roads"][name] = {
            "start": start, "end": end, "final": r["final"],
            "costs": r["costs"], "orders": r["orders"], "halted": r["halted"],
            "max_dd_pct": r["max_dd_pct"], "n_entries": len(r["entries"]),
            "spy_final_same_chassis": spy_final,
            "placebo_beaten": beaten, "placebo_finals": pfin,
            "curve": r["curve"],
            "trades": [[d, t, sd, round(px, 4), round(v, 2), w]
                       for d, t, sd, px, v, w in r["trades"]]}
        print(f"{name}: final ${r['final']} entries {len(r['entries'])} "
              f"halted {r['halted']} DD {r['max_dd_pct']}% placebo {beaten}/20 "
              f"SPY {spy_final}", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("done")

if __name__ == "__main__":
    main()
