#!/usr/bin/env python3
"""
V12 JUDGMENT-CONSTRUCTED MINERVINI SEPA/VCP — frozen per JUDGMENT-SPEC.md.
JUDGMENT-CONSTRUCTED: our frozen reconstruction of Minervini's documented
decision-making; not Minervini's own trading.
Simulation only. Reads ONLY cached data (read-only). Writes only here.
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
MAX_POS = 4
POS_FRAC = 0.25
STOP = 0.08

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
        self.q_ni = concept_rows(facts, "NetIncomeLoss", 80, 100)
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


    def _q_growth_series(self, by_end, d):
        """[(end, yoy_growth)] for filed quarters, chronological."""
        out = []
        for end in sorted(by_end):
            if not any(f < d for f, _ in by_end[end]):
                continue
            r = self._yoy(by_end, end, d)
            if r:
                cur, prev = r
                if prev > 0:
                    out.append((end, cur / prev - 1, cur))
        return out

    def sepa(self, d):
        """Returns (pass, eps_growth, code33_flag). JUDGMENT-SPEC B2/B3."""
        eg = self._q_growth_series(self.q_eps, d)
        if not eg:
            return (False, None, False)
        end, g, cur = eg[-1]
        if cur <= 0 or g < 0.25:
            return (False, g, False)
        rg = self._q_growth_series(self.q_rev, d)
        sales_ok = False
        if rg:
            if rg[-1][1] >= 0.15:
                sales_ok = True
            elif len(rg) >= 2 and rg[-1][1] > rg[-2][1]:
                sales_ok = True
        if not sales_ok and len(eg) >= 2 and eg[-1][1] > eg[-2][1]:
            sales_ok = True
        if not sales_ok:
            return (False, g, False)
        # Code 33: 3 quarters accelerating EPS, sales, margins
        c33 = False
        if len(eg) >= 3 and len(rg) >= 3:
            eps_acc = eg[-3][1] < eg[-2][1] < eg[-1][1]
            rev_acc = rg[-3][1] < rg[-2][1] < rg[-1][1]
            # margins: net income / revenue per quarter YoY growth accelerating
            ng = self._q_growth_series(self.q_ni, d) if hasattr(self, "q_ni") else []
            if eps_acc and rev_acc and len(ng) >= 3 and len(rg) >= 3:
                m = []
                ok = True
                for k in (-3, -2, -1):
                    # margin level for quarter rg[k] end: NI/rev as filed
                    e = rg[k][0]
                    ni = asof(self.q_ni, e, d) if hasattr(self, "q_ni") else None
                    rv = asof(self.q_rev, e, d)
                    if ni is None or rv in (None, 0):
                        ok = False; break
                    m.append(ni / rv)
                if ok and m[0] < m[1] < m[2]:
                    c33 = True
        return (True, g, c33)

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

# ------------------------------------------------------- VCP + template
def swing_points(s, lo, hi):
    """5-bar fractal swings in bars[lo:hi]; swing at j confirmed at j+2."""
    pts = []
    bars = s.bars
    for j in range(max(lo, 2), min(hi, len(bars) - 2)):
        h, l = bars[j]["h"], bars[j]["l"]
        if h >= max(bars[k]["h"] for k in range(j - 2, j + 3)):
            pts.append(("H", j, h))
        if l <= min(bars[k]["l"] for k in range(j - 2, j + 3)):
            pts.append(("L", j, l))
    pts.sort(key=lambda p: p[1])
    return pts

def find_vcp(s, i):
    """JUDGMENT-SPEC B1. Returns (pivot, final_low) or None."""
    pts = swing_points(s, i - 100, i - 2)
    # pullbacks: swing high followed by a later swing low
    pulls = []
    k = 0
    while k < len(pts):
        if pts[k][0] == "H":
            for m in range(k + 1, len(pts)):
                if pts[m][0] == "L":
                    pulls.append((pts[k], pts[m]))
                    k = m
                    break
            else:
                break
        k += 1
    if len(pulls) < 2:
        return None
    use = pulls[-3:]
    depths = [(h[2] - l[2]) / h[2] for h, l in use]
    if depths[0] > 0.35 or depths[-1] > 0.10:
        return None
    for a in range(1, len(depths)):
        if depths[a] > 0.85 * depths[a - 1]:
            return None
    if use[-1][1][2] < use[0][1][2]:
        return None  # lows collapsing
    # volume dry-up: final pullback mean vol < first pullback mean vol
    def seg_vol(p):
        h, l = p
        seg = s.v[h[1]:l[1] + 1]
        return sum(seg) / len(seg) if seg else 0
    if seg_vol(use[-1]) >= seg_vol(use[0]):
        return None
    pivot = use[-1][0][2]
    final_low = use[-1][1][2]
    return (pivot, final_low)

def template_pass(s, i, rs_val):
    """PUBLISHED-MECHANICAL trend template (spec A1) at bar i."""
    if i < 252 or rs_val is None or rs_val < 70:
        return False
    c = s.c
    px = c[i]
    ma50 = sum(c[i - 49:i + 1]) / 50
    ma150 = sum(c[i - 149:i + 1]) / 150
    ma200 = sum(c[i - 199:i + 1]) / 200
    ma200_m = sum(c[i - 220:i - 20]) / 200
    if not (px > ma150 and px > ma200):
        return False
    if not ma150 > ma200:
        return False
    if not ma200 > ma200_m:
        return False
    if not (ma50 > ma150 and ma50 > ma200):
        return False
    if not px > ma50:
        return False
    if px < 1.30 * min(c[i - 251:i + 1]):
        return False
    if px < 0.75 * max(c[i - 251:i + 1]):
        return False
    return True

def breakout_candidates(s):
    """dict date -> (pivot, final_low). rs: date->{ticker:val} handled by caller via s name."""
    out = {}
    bars = s.bars
    for i in range(290, len(bars)):
        b = bars[i]
        if b["v"] <= 0:
            continue
        avg50 = sum(s.v[i - 50:i]) / 50
        if avg50 <= 0 or b["v"] < 1.4 * avg50:
            continue
        v = find_vcp(s, i)
        if v is None:
            continue
        piv, flow = v
        if b["c"] > piv and b["c"] <= piv * 1.05:
            out[b["d"]] = (piv, flow)
    return out

# ------------------------------------------------------------------- engine
def simulate(days, series_by, rs, cands, funds, start, end,
             placebo_seed=None, real_entries=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cash = START_CASH
    pos = {}
    curve, trades, entries_made = [], [], []
    total_costs = 0.0
    halted = None
    entry_plan = None
    if rng is not None:
        entry_plan = {}
        for (d, _t) in real_entries:
            entry_plan[d] = entry_plan.get(d, 0) + 1

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

    def buy(t, d, px, pivot, stop_dist, why, flow=None):
        nonlocal cash, total_costs
        budget = min(POS_FRAC * equity(d), cash / (1 + BUY_COST))
        if budget < 1.0:
            return False
        sh = budget / px
        cst = budget * BUY_COST
        cash -= budget + cst
        total_costs += cst
        stop_px = px * (1 - stop_dist)
        if flow:
            # tighter of structural low and 8% wall (spec B4)
            stop_px = max(px * (1 - STOP), min(px - 0.001, flow))
        pos[t] = {"shares": sh, "fill": px, "entry_date": d, "days": 0,
                  "pivot": pivot or 0.0, "stop_dist": stop_dist,
                  "stop_px": stop_px, "be": False}
        trades.append((d, t, "BUY", px, budget, why))
        entries_made.append((d, t))
        return True

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
            if not p["be"] and bar["c"] >= p["fill"] * (1 + p["stop_dist"]):
                p["be"] = True
                p["stop_px"] = max(p["stop_px"], p["fill"])
            sell_px, why = None, None
            if bar["l"] <= p["stop_px"]:
                sell_px = bar["o"] if bar["o"] < p["stop_px"] else p["stop_px"]
                why = "be-stop" if p["be"] else "stop"
            elif p["pivot"] and p["days"] <= 5 and bar["c"] < p["pivot"]:
                sell_px, why = bar["c"], "failed-breakout"
            elif p["days"] >= 10 and i >= 49:
                ma50 = sum(s.c[i - 49:i + 1]) / 50
                if bar["c"] < ma50:
                    sell_px, why = bar["c"], "ma50-exit"
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
            if len(pos) < MAX_POS:
                day_cands = []
                for t, cd in cands.items():
                    if d in cd and t not in pos:
                        ok, g, c33 = funds[t].sepa(d)
                        if ok:
                            r = rs.get(d, {}).get(t)
                            piv, flow = cd[d]
                            day_cands.append((c33, g, r or 0, t, piv, flow))
                # template check uses prior close: rs at d is close-of-d;
                # template evaluated on breakout day close (documented
                # simplification: template is a qualifier on the stock's
                # state, breakout day included) + raw stop distance gate
                filt = []
                for c33, g, r, t, piv, flow in day_cands:
                    s = series_by[t]
                    i = s.idx[d]
                    prev_d = s.dates[i - 1] if i >= 1 else d
                    r_prev = rs.get(prev_d, {}).get(t)
                    if not template_pass(s, i - 1, r_prev):
                        continue
                    px = s.bars[i]["c"]
                    raw = (px - flow) / px if px > 0 else 1.0
                    if raw > 0.10:
                        continue
                    filt.append((c33, g, r, t, piv, flow, raw))
                filt.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
                for c33, g, r, t, piv, flow, raw in filt:
                    if len(pos) >= MAX_POS:
                        break
                    s = series_by[t]
                    px = s.bars[s.idx[d]]["c"]
                    sd = min(STOP, max(0.02, raw))
                    buy(t, d, px, piv, sd, f"rs{r} eps{round(g*100)} c33={int(c33)}", flow=flow)
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
                buy(t, d, px, 0.0, STOP, "placebo")
        curve.append((d, equity(d)))
    if halted is None:
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
    peak, mdd = -1, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
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
        r = simulate(days, series_by, rs, cands, funds, start, end)
        spy_days = [d for d in master if start <= d <= end]
        s0 = spy.c[spy.idx[spy_days[0]]]
        s1 = spy.c[spy.idx[spy_days[-1]]]
        spy_final = round(100 * (s1 / s0) * (1 - 0.001) - 0.01 * (s1 / s0), 2)
        beaten = 0
        pfin = []
        for seed in range(20):
            pr = simulate(days, series_by, rs, cands, funds, start, end,
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
    # ---- emit payload on stdout (sandbox blocks python file writes;
    # harness-captured stdout is the reliable channel). Weekly-sampled
    # curve (every 5th point + final) in the payload; daily period stats
    # computed here from the full daily curve.
    import period_stats as ps
    print("PAYLOAD_BEGIN")
    print("META " + json.dumps({"universe_size": results["universe_size"],
                                "failures": results["failures"]}))
    for name, rd in results["roads"].items():
        wk = rd["curve"][::5]
        if wk[-1] != rd["curve"][-1]:
            wk = wk + [rd["curve"][-1]]
        compact = {k: v for k, v in rd.items() if k != "curve"}
        compact["curve_weekly"] = wk
        compact["period_stats_daily"] = ps.stats(rd["curve"])
        print(f"ROAD {name} " + json.dumps(compact))
    print("PAYLOAD_END")
    try:
        tmp = os.path.join(HERE, "results.json.tmp")
        with open(tmp, "w") as f:
            json.dump(results, f, indent=1)
        os.replace(tmp, os.path.join(HERE, "results.json"))
    except Exception as e:
        print("file write failed (expected in sandbox):", e)
    print("done")

if __name__ == "__main__":
    main()
