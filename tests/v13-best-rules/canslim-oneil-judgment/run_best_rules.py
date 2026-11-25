#!/usr/bin/env python3
"""
V13 BEST-RULES CAN SLIM — JUDGMENT-CONSTRUCTED. Frozen per BEST-RULES-SPEC.md
in this folder (B1-B5): single trend market gate, no profit-take (winners exit
on 50-day break after +20%), -7.5% stop unchanged, max 5 positions at 20%,
NO portfolio floor. Engine adapted from the v12 judgment run; fundamentals,
bases, RS, costs, pond inherited unchanged. Simulation only. Reads ONLY
cached data (read-only). Writes only here.
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
FLOOR = -1.0  # B5: NO portfolio floor — check `eq <= FLOOR` can never fire
BUY_COST = 0.001
SELL_COST = 0.001
SELL_FEE = 0.01
MAX_POS = 5  # B4
POS_FRAC = 0.20
PILOT_FRAC = 0.20  # B1: single tier — pilot tier deleted
STOP = 0.075  # B3: unchanged
ARM_GAIN = 0.20  # B2: winner arms at +20% close, exits on 50-day break

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
        # J1: EPS up EACH of last 3 years, latest >= +25%, ROE >= 17%
        ends = sorted(e for e in self.a_eps if any(f < d for f, _ in self.a_eps[e]))
        if len(ends) < 4:
            return False
        last4 = ends[-4:]
        vals = [asof(self.a_eps, e, d) for e in last4]
        if any(v is None or v <= 0 for v in vals):
            return False
        for i in range(1, 4):
            if vals[i] <= vals[i - 1]:
                return False
        if vals[3] / vals[2] - 1 < 0.25:
            return False
        fy = last4[-1]
        ni = asof(self.a_ni, fy, d)
        eq = asof(self.a_eq, fy, d)
        if ni is None or eq is None or eq <= 0:
            return False
        return ni / eq >= 0.17

    def a_near(self, d):
        ends = sorted(e for e in self.a_eps if any(f < d for f, _ in self.a_eps[e]))
        if len(ends) < 4:
            return False
        last4 = ends[-4:]
        vals = [asof(self.a_eps, e, d) for e in last4]
        if any(v is None or v <= 0 for v in vals):
            return False
        ups = sum(1 for i in range(1, 4) if vals[i] > vals[i - 1])
        if ups < 2 or vals[3] <= vals[2]:
            return False
        ni = asof(self.a_ni, last4[-1], d)
        eq = asof(self.a_eq, last4[-1], d)
        if ni is None or eq is None or eq <= 0:
            return False
        return ni / eq >= 0.12

    def _eps_yoy(self, end, d):
        r = self._yoy(self.q_eps, end, d)
        if not r:
            return None
        cur, prev = r
        if prev <= 0 or cur <= 0:
            return None
        return cur / prev - 1

    def _rev_yoy(self, end, d):
        r = self._yoy(self.q_rev, end, d)
        if not r:
            return None
        cur, prev = r
        if prev <= 0:
            return None
        return cur / prev - 1

    def c_pass_j(self, d):
        # J2: constructed C OR (>=18% AND accelerating AND sales >= +20%)
        if self.c_pass(d):
            return True
        end = latest_end(self.q_eps, d)
        if end is None:
            return False
        g = self._eps_yoy(end, d)
        if g is None or g < 0.18:
            return False
        pq = find_end_near(self.q_eps, (date.fromisoformat(end) -
                             __import__("datetime").timedelta(days=92)).isoformat(), 30)
        if pq is None:
            return False
        pg = self._eps_yoy(pq, d)
        if pg is None or g <= pg:
            return False
        rend = latest_end(self.q_rev, d)
        if rend is None:
            return False
        rg = self._rev_yoy(rend, d)
        return rg is not None and rg >= 0.20

    def c_near(self, d):
        end = latest_end(self.q_eps, d)
        if end is not None:
            g = self._eps_yoy(end, d)
            if g is not None and g >= 0.10:
                return True
        rend = latest_end(self.q_rev, d)
        if rend is not None:
            rg = self._rev_yoy(rend, d)
            if rg is not None and rg >= 0.20:
                return True
        return False

    def fund_ok(self, d):
        # J3: both pass, or exactly one passes and the other is NEAR;
        # a leg actively negative blocks (checked via near/pass definitions
        # plus explicit down checks below)
        cp, ap = self.c_pass_j(d), self.a_pass(d)
        if cp and ap:
            return True
        if cp and self.a_near(d):
            return True
        if ap and self.c_near(d):
            return True
        return False

# ------------------------------------------------------------------- prices
class Series:
    def __init__(self, bars):
        self.bars = bars
        self.dates = [b["d"] for b in bars]
        self.idx = {b["d"]: i for i, b in enumerate(bars)}
        self.c = [b["c"] for b in bars]
        self.v = [b["v"] for b in bars]
        self.h = [b["h"] for b in bars]
        self.l = [b["l"] for b in bars]
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
    """B1: date -> tier: 2 (buys allowed, full size) if SPY close is above
    BOTH its 50-day and 200-day averages, else 0. The FTD/distribution-day
    state machine and the PILOT tier are deleted."""
    states = {}
    closes = spy.c
    for i, b in enumerate(spy.bars):
        d = b["d"]
        tier = 0
        if i >= 200:
            ma50 = sum(closes[i - 49:i + 1]) / 50
            ma200 = sum(closes[i - 199:i + 1]) / 200
            if closes[i] > ma50 and closes[i] > ma200:
                tier = 2
        states[d] = tier
    return states

# ------------------------------------------------------------ base detection
def find_base(s, i):
    """Breakout day index i (signal at close of i). Returns pivot or None.
    Speed note: slice min/max/index are C-speed; tie-breaking (first index
    of the max/min) matches the original range-based code exactly."""
    H, L, C, V = s.h, s.l, s.c, s.v
    if i < 290:
        return None
    for hl in range(5, 31):
        hs = i - hl
        if hs < 40:
            continue
        hhigh = max(H[hs:i])
        hlow = min(L[hs:i])
        if hhigh <= 0 or (hhigh - hlow) / hhigh > 0.15:
            continue
        lo_i = max(0, hs - 325)
        rim_high = max(H[lo_i:hs - 4])
        rim_i = H.index(rim_high, lo_i, hs - 4)
        cup_len = hs - rim_i
        if cup_len < 35:
            continue
        cup_low = min(L[rim_i:hs])
        cup_low_i = L.index(cup_low, rim_i, hs)
        if rim_high <= 0:
            continue
        depth = (rim_high - cup_low) / rim_high
        if not (0.12 <= depth <= 0.40):
            continue
        if hhigh < rim_high * 0.95:
            continue
        if hlow < (rim_high + cup_low) / 2:
            continue
        frac = (cup_low_i - rim_i) / max(cup_len, 1)
        if not (0.2 <= frac <= 0.8):
            continue
        rim_close = C[rim_i]
        pre = C[max(0, rim_i - 126):rim_i]
        if not pre or min(pre) > rim_close / 1.30:
            continue
        hv = sum(V[hs:i]) / hl
        cv = sum(V[hs - 10:hs]) / 10
        if cv > 0 and hv >= cv:
            continue
        return hhigh + 0.10
    # J5 cup without handle
    for cl in range(35, 326):
        cs = i - cl
        if cs < 130:
            continue
        lo_w = max(0, cs - 5)
        rim_high = max(H[lo_w:cs + 6])
        rim_i = H.index(rim_high, lo_w, cs + 6)
        if rim_high <= 0:
            continue
        cup_low = min(L[rim_i:i])
        depth = (rim_high - cup_low) / rim_high
        if not (0.12 <= depth <= 0.40):
            continue
        if H[i - 1] < rim_high * 0.95:
            continue
        rim_close = C[rim_i]
        pre = C[max(0, rim_i - 126):rim_i]
        if not pre or min(pre) > rim_close / 1.30:
            continue
        return rim_high + 0.10
    # J5 double bottom (W)
    for span in range(50, 201):
        bs = i - span
        if bs < 130:
            continue
        half = span // 2
        l1 = min(L[bs:bs + half]); l2 = min(L[bs + half:i])
        lo = min(l1, l2)
        if lo <= 0 or abs(l1 - l2) / lo > 0.03 or l2 < l1 * 0.98:
            continue
        mid = max(H[bs:i])
        if (mid - lo) / mid < 0.12 or (mid - lo) / mid > 0.40:
            continue
        if (mid - lo) / lo < 0.08:
            continue
        start_close = C[bs]
        pre = C[max(0, bs - 126):bs]
        if not pre or min(pre) > start_close / 1.30:
            continue
        return mid + 0.10
    # flat base
    for bl in range(25, 51):
        bs = i - bl
        if bs < 130:
            continue
        bh = max(H[bs:i])
        blo = min(L[bs:i])
        if bh <= 0 or (bh - blo) / bh > 0.15:
            continue
        start_close = C[bs]
        pre = C[max(0, bs - 126):bs]
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
        if avg50 <= 0 or b["v"] < 1.40 * avg50:
            continue
        if b["c"] < 0.97 * max(s.c[i - 252:i]):
            continue  # J5: within 3% of 252-bar high (near-new-high)
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
        for (d, _t, _f) in real_entries:
            entry_plan.setdefault(d, []).append(_f)

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
            p["hi"] = max(p.get("hi", p["fill"]), bar["c"])
            # B2: arm the winner exit once a close reaches +20% over fill
            if bar["c"] >= p["fill"] * (1 + ARM_GAIN):
                p["armed"] = True
            sell_px, why = None, None
            stop_px = p["fill"] * (1 - STOP)  # B3: from blended fill, always
            ma50 = sum(s.c[i - 49:i + 1]) / 50 if i >= 49 else None
            if bar["l"] <= stop_px:
                sell_px = bar["o"] if bar["o"] < stop_px else stop_px
                why = "stop7.5"
            elif p.get("armed") and ma50 and bar["c"] < ma50:
                sell_px, why = bar["c"], "winner-ma50-break"
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
        # ---- J7 pyramiding: one add per position on strength
        for t in list(pos):
            pp = pos[t]
            if pp.get("added"):
                continue
            ss = series_by[t]
            ii = ss.idx.get(d)
            if ii is None or d <= pp["entry_date"]:
                continue
            ei = ss.idx[pp["entry_date"]]
            if ss.c[ii] >= pp["fill"] * 1.05 and ss.c[ii] >= max(ss.c[ei:ii + 1]):
                px = ss.c[ii]
                budget = min(0.10 * equity(d), cash / (1 + BUY_COST))
                if budget >= 1.0:
                    sh = budget / px
                    cst = budget * BUY_COST
                    cash -= budget + cst
                    total_costs += cst
                    newsh = pp["shares"] + sh
                    pp["fill"] = (pp["shares"] * pp["fill"] + sh * px) / newsh
                    pp["shares"] = newsh
                    pp["hi"] = max(pp.get("hi", px), px)
                    pp["added"] = True
                    trades.append((d, t, "BUY", px, budget, "pyramid-add"))
        # ---- entries
        if rng is None:
            tier = mstates.get(d, 0)
            if tier and len(pos) < MAX_POS:
                frac = POS_FRAC if tier == 2 else PILOT_FRAC
                day_cands = []
                for t, cd in cands.items():
                    if d in cd and t not in pos:
                        r = rs.get(d, {}).get(t)
                        if r is not None and r >= 80 and funds[t].fund_ok(d):
                            day_cands.append((r, t))
                day_cands.sort(reverse=True)
                for r, t in day_cands:
                    if len(pos) >= MAX_POS:
                        break
                    s = series_by[t]
                    px = s.bars[s.idx[d]]["c"]
                    budget = min(frac * equity(d), cash / (1 + BUY_COST))
                    if budget < 1.0:
                        break
                    sh = budget / px
                    cst = budget * BUY_COST
                    cash -= budget + cst
                    total_costs += cst
                    pos[t] = {"shares": sh, "fill": px, "entry_date": d,
                              "days": 0, "added": False,
                              "armed": False, "hi": px}
                    trades.append((d, t, "BUY", px, budget, f"rs{r}t{tier}"))
                    entries_made.append((d, t, frac))
        else:
            for frac in entry_plan.get(d, []):
                if len(pos) >= MAX_POS:
                    break
                pool = [t for t, s in series_by.items()
                        if d in s.idx and s.idx[d] >= 252 and t not in pos]
                if not pool:
                    break
                t = rng.choice(pool)
                s = series_by[t]
                px = s.bars[s.idx[d]]["c"]
                budget = min(frac * equity(d), cash / (1 + BUY_COST))
                if budget < 1.0:
                    break
                sh = budget / px
                cst = budget * BUY_COST
                cash -= budget + cst
                total_costs += cst
                pos[t] = {"shares": sh, "fill": px, "entry_date": d,
                          "days": 0, "added": False,
                          "armed": False, "hi": px}
                trades.append((d, t, "BUY", px, budget, "placebo"))
                entries_made.append((d, t, frac))
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

def monthly_stats(curve):
    """curve: [[date, equity], ...] daily. Returns monthly distribution."""
    months = []
    cur_key, prev_last = None, None
    last_val = None
    for d, v in curve:
        k = d[:7]
        if k != cur_key:
            if cur_key is not None:
                months.append((cur_key, last_val))
            cur_key = k
        last_val = v
    if cur_key is not None:
        months.append((cur_key, last_val))
    rets = []
    base = 100.0
    for k, v in months:
        rets.append(v / base - 1)
        base = v
    if not rets:
        return {}
    srt = sorted(rets)
    n = len(rets)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    pos_share = sum(1 for r in rets if r > 0) / n
    worst_run = run = 0
    for r in rets:
        run = run + 1 if r <= 0 else 0
        worst_run = max(worst_run, run)
    peak, since_high, longest = -1.0, 0, 0
    run_val = 100.0
    vals = [v for _, v in months]
    peak = vals[0]
    for v in vals:
        if v >= peak:
            peak, since_high = v, 0
        else:
            since_high += 1
            longest = max(longest, since_high)
    return {"periods": n, "median_pct": round(med * 100, 2),
            "share_positive_pct": round(pos_share * 100, 1),
            "best_pct": round(max(rets) * 100, 2),
            "worst_pct": round(min(rets) * 100, 2),
            "avg_pct_secondary": round(sum(rets) / n * 100, 2),
            "longest_losing_streak_months": worst_run,
            "longest_between_highs_months": longest}

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
    results = {"label": "JUDGMENT-CONSTRUCTED (V13 BEST RULES B1-B5): our frozen reconstruction of O'Neil's documented decision-making under rules chosen per BEST-RULES-SPEC.md; not O'Neil's own trading.",
               "universe_size": len(series_by) - 1, "failures": failures,
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
            "monthly": monthly_stats(r["curve"]),
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
