#!/usr/bin/env python3
"""V12 crypto cross-run slice X3: pv1, pv2, pv3, pv4, x2, wyckoff.
Shared data READ-ONLY: CMC PIT snapshots, crypto-x-constructed OHLC cache,
crypto-x-slow-illiquidity volume cache. Costs 0.60%/side. $100 pots."""
import json, os, math, random, statistics, sys
from datetime import date, timedelta

BASE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
OUTROOT = BASE
COST = 0.006
END = "2026-11-20"

snap = json.load(open(f"{BASE}/crypto-basket-pit/data/weekly_snapshots.json"))
snap_dates = sorted(snap.keys())
SYM = {}
for d in snap_dates:
    for e in snap[d]["top20"]:
        SYM[e["cmc_id"]] = e["symbol"]

def membership(dstr):
    # latest snapshot <= dstr
    import bisect
    i = bisect.bisect_right(snap_dates, dstr) - 1
    if i < 0: return set()
    return {e["cmc_id"] for e in snap[snap_dates[i]]["top20"]}

def load_series():
    S = {}
    ohlc_dir = f"{BASE}/crypto-x-constructed/data_ohlc"
    vol_dir = f"{BASE}/crypto-x-slow-illiquidity/data"
    for cid in SYM:
        p = f"{ohlc_dir}/{cid}.json"
        if not os.path.exists(p): continue
        bars = json.load(open(p))
        vols = {}
        vp = f"{vol_dir}/vol_{cid}.json"
        if os.path.exists(vp):
            for b in json.load(open(vp)): vols[b["d"]] = b.get("v")
        rows = []
        for b in bars:
            rows.append({"d": b["d"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"],
                         "v": vols.get(b["d"])})
        rows.sort(key=lambda r: r["d"])
        S[cid] = rows
    return S

S = load_series()
BTC = 1
cal = [r["d"] for r in S[BTC] if r["d"] <= END]
cal_idx = {d: i for i, d in enumerate(cal)}
# per-coin date->bar index
IDX = {cid: {r["d"]: i for i, r in enumerate(rows)} for cid, rows in S.items()}

def bar_on(cid, dstr):
    i = IDX[cid].get(dstr)
    return S[cid][i] if i is not None else None

def last_close(cid, dstr):
    rows = S[cid]; idx = IDX[cid]
    if dstr in idx: return rows[idx[dstr]]["c"]
    # binary search last bar <= dstr
    import bisect
    ds = [r["d"] for r in rows]
    i = bisect.bisect_right(ds, dstr) - 1
    if i < 0: return None
    if (date.fromisoformat(dstr) - date.fromisoformat(ds[i])).days > 30: return 0.0
    return rows[i]["c"]

def btc_hold(start, end):
    rows = [r for r in S[BTC] if start <= r["d"] <= end]
    if not rows: return None
    sh = 100 * (1 - COST) / rows[0]["o"]
    return round(sh * rows[-1]["c"], 2)

def monthly_dist(curve):
    # curve: list of [date, equity] daily (calendar of BTC)
    months = {}
    for d, e in curve: months[d[:7]] = e  # last value in month
    keys = sorted(months)
    rets = []
    for a, b in zip(keys, keys[1:]):
        if months[a] > 0: rets.append(months[b] / months[a] - 1)
    if not rets: return {}
    prof = sum(1 for r in rets if r > 0)
    longest_loss = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        longest_loss = max(longest_loss, cur)
    # longest stretch between new highs (months)
    peak = -1; since = 0; longest = 0
    for k in keys:
        if months[k] >= peak: peak = months[k]; since = 0
        else: since += 1; longest = max(longest, since)
    return {"n_periods": len(rets), "pct_profitable": round(100 * prof / len(rets), 1),
            "median_pct": round(100 * statistics.median(rets), 2),
            "best_pct": round(100 * max(rets), 2), "worst_pct": round(100 * min(rets), 2),
            "longest_losing_run": longest_loss, "longest_stretch_between_highs_months": longest,
            "mean_pct_secondary": round(100 * statistics.mean(rets), 2)}

class Floor:
    """v9: -15% episode floor, 90d sit-out, one restart, second halt ends."""
    def __init__(self, active):
        self.active = active; self.ep_start = 100.0; self.halts = 0
        self.sit_until = None; self.ended = False
    def check(self, equity, dstr):
        if not self.active or self.ended: return False
        if self.sit_until and dstr <= self.sit_until: return False
        if equity <= 0.85 * self.ep_start:
            self.halts += 1
            if self.halts >= 2: self.ended = True
            else:
                self.sit_until = (date.fromisoformat(dstr) + timedelta(days=90)).isoformat()
                self.ep_start = equity
            return True
        return False
    def blocked(self, dstr):
        if not self.active: return False
        if self.ended: return True
        if self.sit_until and dstr <= self.sit_until: return True
        return False

_XCACHE = {}
WINDOWS = {"FULL": ("2017-01-01", END), "DESIGN": ("2017-01-01", "2022-12-31"),
           "VALIDATION": ("2023-01-01", END)}

# ---------- generic rotation engine (pv1, pv3, x2-basket handled separately) ----------
def run_rotation(score_fn, start, end, floor_active, rng=None, placebo=False):
    cash = 100.0; pos = {}  # cid -> shares
    fl = Floor(floor_active)
    curve = []
    days = [d for d in cal if start <= d <= end]
    # month-end signal dates within window (use BTC calendar)
    sig_dates = []
    seen = set()
    for d in days:
        seen.add(d[:7])
    for m in sorted(seen):
        mdays = [d for d in days if d[:7] == m]
        if mdays: sig_dates.append(mdays[-1])
    pending = None  # list of cids to buy at next day open
    trades = 0
    for di, d in enumerate(days):
        # execute pending at open
        if pending is not None and not fl.blocked(d):
            # sell all at open
            for cid in list(pos):
                b = bar_on(cid, d)
                px = b["o"] if b else (last_close(cid, d) or 0)
                cash += pos[cid] * px * (1 - COST); trades += 1
            pos = {}
            eq = cash
            for cid in pending:
                b = bar_on(cid, d)
                if not b: continue
                amt = eq / len(pending)
                sh = amt * (1 - COST) / b["o"]
                if sh > 0: pos[cid] = sh; cash -= amt; trades += 1
            pending = None
        elif pending is not None:
            pending = None
        # mark
        eq = cash + sum(sh * (last_close(cid, d) or 0) for cid, sh in pos.items())
        curve.append([d, round(eq, 4)])
        # floor check at close
        if fl.check(eq, d):
            # liquidate at next open: emulate by selling at next day open in next iter via pending sell
            pending_sell = True
            # do immediate: mark positions to be sold tomorrow
            # implement by setting a flag handled below
            fl._sell_tomorrow = True
        if getattr(fl, "_sell_tomorrow", False) and di + 1 < len(days):
            pass  # handled next iteration start below
        # sell-tomorrow execution
        if getattr(fl, "_sell_tomorrow", False):
            nd = days[di + 1] if di + 1 < len(days) else None
            if nd:
                for cid in list(pos):
                    b = bar_on(cid, nd)
                    px = b["o"] if b else (last_close(cid, nd) or 0)
                    cash += pos[cid] * px * (1 - COST); trades += 1
                pos = {}
            fl._sell_tomorrow = False
            pending = None
        # signal at month-end close
        if d in sig_dates and not fl.blocked(d):
            picks = score_fn(d, rng, placebo)
            if picks is not None: pending = picks
    final = curve[-1][1] if curve else 100.0
    dd = max_dd(curve)
    return {"final": round(final, 2), "max_dd_pct": round(100 * dd, 2), "trades": trades,
            "halts": fl.halts, "curve": curve, "monthly": monthly_dist(curve)}

def max_dd(curve):
    peak = -1; mdd = 0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0: mdd = min(mdd, e / peak - 1)
    return mdd

def trailing_bars(cid, dstr, n):
    if cid not in IDX: return None
    idx = IDX[cid].get(dstr)
    if idx is None: return None
    if idx + 1 < n: return None
    return S[cid][idx - n + 1: idx + 1]

# ---------- PV1 ----------
def pv1_score(d, rng=None, placebo=False):
    mem = membership(d); elig = []
    for cid in mem:
        bars = trailing_bars(cid, d, 20)
        if not bars: continue
        ls = []; us = []
        for b in bars:
            R = b["h"] - b["l"]
            if R > 0:
                ls.append((min(b["o"], b["c"]) - b["l"]) / R)
                us.append((b["h"] - max(b["o"], b["c"])) / R)
        if len(ls) < 15: continue
        elig.append((cid, statistics.mean(ls) - statistics.mean(us)))
    if len(elig) < 5: return None
    if placebo:
        return [c for c, _ in rng.sample(elig, 5)]
    elig.sort(key=lambda x: -x[1])
    return [c for c, _ in elig[:5]]

# ---------- PV3 ----------
def pv3_score(d, rng=None, placebo=False):
    mem = membership(d); elig = []
    for cid in mem:
        bars = trailing_bars(cid, d, 64)
        if not bars: continue
        closes = [b["c"] for b in bars]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        if len(rets) < 63: continue
        tot = closes[-1] / closes[0] - 1
        if tot < 0: continue
        r = rets[-63:]
        s5 = [sum(r[j:j + 5]) for j in range(59)]
        vr = statistics.pvariance(s5) / (5 * statistics.pvariance(r)) if statistics.pvariance(r) > 0 else 0
        elig.append((cid, vr))
    if len(elig) < 5: return None
    if placebo:
        return [c for c, _ in rng.sample(elig, 5)]
    elig.sort(key=lambda x: -x[1])
    return [c for c, _ in elig[:5]]

# ---------- event engine (pv2, pv4) ----------
def run_events(kind, start, end, floor_active, rng=None, placebo=False):
    cash = 100.0; positions = []  # dicts: cid, shares, entry_idx (coin bar idx), entry_date
    fl = Floor(floor_active); curve = []; trades = 0; n_events = 0
    days = [d for d in cal if start <= d <= end]
    for di, d in enumerate(days):
        mem = membership(d)
        # exits at open: positions whose exit bar is today
        still = []
        for p in positions:
            idx = IDX[p["cid"]].get(d)
            if idx is not None and idx >= p["exit_idx"]:
                b = S[p["cid"]][idx]
                cash += p["shares"] * b["o"] * (1 - COST); trades += 1
            else:
                still.append(p)
        positions = still
        # triggers at close of d, entry next bar
        if not fl.blocked(d):
            trig = []
            for cid in mem:
                if cid not in IDX: continue
                if any(p["cid"] == cid for p in positions): continue
                idx = IDX[cid].get(d)
                if idx is None: continue
                rows = S[cid]; b = rows[idx]
                if kind == "pv2":
                    if b["v"] is None or idx < 126: continue
                    prev = [rows[j]["v"] for j in range(idx - 126, idx)]
                    if any(v is None for v in prev): continue
                    if not (b["v"] > max(prev)): continue
                    if rows[idx - 1]["c"] == 0 or b["c"] / rows[idx - 1]["c"] - 1 > -0.015: continue
                    med = statistics.median([rows[j]["v"] for j in range(idx - 20, idx) if rows[j]["v"]])
                    trig.append((cid, b["v"] / med if med else 0))
                else:  # pv4
                    if idx < 1: continue
                    pc = rows[idx - 1]["c"]
                    if pc == 0: continue
                    g = b["o"] / pc - 1
                    if g <= -0.02 and b["c"] >= pc:
                        trig.append((cid, -g))
            trig.sort(key=lambda x: -x[1])
            free = 5 - len(positions)
            if placebo and trig:
                pool = [c for c in mem if c in IDX and d in IDX[c] and not any(p["cid"] == c for p in positions)]
                trig = [(c, 0) for c in rng.sample(pool, min(len(trig), len(pool)))] if pool else []
            for cid, _ in trig[:max(free, 0)]:
                idx = IDX[cid][d]
                rows = S[cid]
                if idx + 1 >= len(rows): continue
                nb = rows[idx + 1]
                eq_now = cash + sum(p["shares"] * (last_close(p["cid"], d) or 0) for p in positions)
                amt = 0.20 * eq_now
                if amt > cash: amt = cash
                if amt <= 0: continue
                sh = amt * (1 - COST) / nb["o"]
                hold = 20 if kind == "pv2" else 10
                positions.append({"cid": cid, "shares": sh, "exit_idx": idx + 1 + hold})
                cash -= amt; trades += 1; n_events += 1
        eq = cash + sum(p["shares"] * (last_close(p["cid"], d) or 0) for p in positions)
        curve.append([d, round(eq, 4)])
        if fl.check(eq, d):
            # liquidate all at next day open
            if di + 1 < len(days):
                nd = days[di + 1]
                for p in positions:
                    b = bar_on(p["cid"], nd)
                    px = b["o"] if b else (last_close(p["cid"], nd) or 0)
                    cash += p["shares"] * px * (1 - COST); trades += 1
                positions = []
    final = curve[-1][1] if curve else 100.0
    return {"final": round(final, 2), "max_dd_pct": round(100 * max_dd(curve), 2),
            "trades": trades, "events": n_events, "halts": fl.halts,
            "curve": curve, "monthly": monthly_dist(curve)}

# ---------- X2 correlation switch ----------
def run_x2(start, end, floor_active, rng=None, placebo=False):
    cash = 100.0; pos = {}; mode = None  # 'basket' or 'btc'
    fl = Floor(floor_active); curve = []; trades = 0
    days = [d for d in cal if start <= d <= end]
    readings = []
    # pre-window readings from 2016-06 onward for expanding median
    eval_dates = []
    seen = set()
    alldays = [d for d in cal if "2016-06-01" <= d <= end]
    for d in alldays: seen.add(d[:7])
    for m in sorted(seen):
        md = [d for d in alldays if d[:7] == m]
        if md: eval_dates.append(md[0])
    def corr_reading(d):
        if d in _XCACHE: return _XCACHE[d]
        mem = [c for c in membership(d) if c in S]
        series = {}
        import bisect
        for cid in mem:
            rows = S[cid]
            ds = [r["d"] for r in rows]
            i = bisect.bisect_right(ds, d) - 1
            if i < 60: continue
            closes = [rows[j]["c"] for j in range(i - 60, i + 1)]
            rets = [closes[k] / closes[k - 1] - 1 for k in range(1, 61) if closes[k - 1] > 0]
            if len(rets) == 60: series[cid] = rets
        if len(series) < 5: return None
        cs = []
        cids = list(series)
        for a in range(len(cids)):
            for b in range(a + 1, len(cids)):
                x, y = series[cids[a]], series[cids[b]]
                mx, my = statistics.mean(x), statistics.mean(y)
                num = sum((x[k] - mx) * (y[k] - my) for k in range(60))
                den = math.sqrt(sum((v - mx) ** 2 for v in x) * sum((v - my) ** 2 for v in y))
                if den > 0: cs.append(num / den)
        v = statistics.mean(cs) if cs else None
        _XCACHE[d] = v
        return v
    pending_mode = None
    for di, d in enumerate(days):
        if pending_mode is not None and not fl.blocked(d):
            if pending_mode != mode:
                for cid in list(pos):
                    b = bar_on(cid, d)
                    px = b["o"] if b else (last_close(cid, d) or 0)
                    cash += pos[cid] * px * (1 - COST); trades += 1
                pos = {}
                eq = cash
                targets = [c for c in membership(d) if c in S] if pending_mode == "basket" else [BTC]
                bought = 0
                for cid in targets:
                    b = bar_on(cid, d)
                    if not b: continue
                    amt = eq / len(targets)
                    sh = amt * (1 - COST) / b["o"]
                    if sh > 0: pos[cid] = sh; cash -= amt; bought += 1; trades += 1
                mode = pending_mode
            pending_mode = None
        eq = cash + sum(sh * (last_close(cid, d) or 0) for cid, sh in pos.items())
        curve.append([d, round(eq, 4)])
        if fl.check(eq, d) and di + 1 < len(days):
            nd = days[di + 1]
            for cid in list(pos):
                b = bar_on(cid, nd)
                px = b["o"] if b else (last_close(cid, nd) or 0)
                cash += pos[cid] * px * (1 - COST); trades += 1
            pos = {}; mode = None; pending_mode = None
        if d in eval_dates and not fl.blocked(d):
            r = corr_reading(d)
            if r is not None:
                if len(readings) >= 3:
                    med = statistics.median(readings)
                    want = "basket" if r <= med else "btc"
                    if placebo:
                        want = rng.choice(["basket", "btc"]) if rng.random() < 0.5 else want
                    pending_mode = want
                readings.append(r)
    final = curve[-1][1] if curve else 100.0
    return {"final": round(final, 2), "max_dd_pct": round(100 * max_dd(curve), 2),
            "trades": trades, "halts": fl.halts, "curve": curve, "monthly": monthly_dist(curve)}

# ---------- Wyckoff ----------
def pf_columns(closes, box):
    # simple P&F on closes: returns number of columns
    if not closes: return 0
    cols = 1; direction = 0; anchor = closes[0]
    hi = lo = closes[0]
    for px in closes[1:]:
        if direction >= 0:
            if px >= hi: hi = px
            elif px <= hi - 3 * box:
                cols += 1; direction = -1; lo = px; anchor = px
        if direction <= 0:
            if px <= lo: lo = px
            elif px >= lo + 3 * box:
                cols += 1; direction = 1; hi = px
    return cols

_WCACHE = {}
def wyckoff_candidates(d):
    """Return list of (cid, fill, stop, target, t7margin) for test day d."""
    if d in _WCACHE: return _WCACHE[d]
    out = []
    bi = IDX[BTC].get(d)
    if bi is None or bi < 221: return out
    brows = S[BTC]
    bcloses = [r["c"] for r in brows]
    sma200 = statistics.mean(bcloses[bi - 199:bi + 1])
    sma200_prev = statistics.mean(bcloses[bi - 220:bi - 20])
    if not (bcloses[bi] > sma200 and sma200 > sma200_prev): return out  # B0 gate (BTC as market)
    for cid in membership(d):
        if cid not in S: continue
        rows = S[cid]; idx = IDX[cid].get(d)
        if idx is None or idx < 400: continue
        if any(rows[j]["v"] is None for j in range(idx - 90, idx + 1)): continue
        rng_bars = rows[idx - 90: idx - 30]
        rh = max(b["h"] for b in rng_bars); rl = min(b["l"] for b in rng_bars)
        if rl <= 0 or (rh - rl) / rl > 0.35: continue
        # B1
        pre = rows[idx - 90 - 252: idx - 90]
        if len(pre) < 200: continue
        if max(b["h"] for b in pre) < rl * 1.25: continue
        # B2 climax + ST in range
        climax = None
        for j in range(idx - 90, idx - 90 + 25):
            b = rows[j]
            pv = [rows[k]["v"] for k in range(j - 50, j)]
            spans = [(rows[k]["h"] - rows[k]["l"]) / rows[k]["c"] for k in range(j - 50, j) if rows[k]["c"] > 0]
            if len(pv) < 50 or b["v"] is None: continue
            span = (b["h"] - b["l"]) / b["c"] if b["c"] > 0 else 0
            if (b["v"] >= 1.8 * statistics.mean(pv) and span >= 2 * statistics.median(spans)
                    and b["h"] > b["l"] and (b["c"] - b["l"]) / (b["h"] - b["l"]) >= 0.5):
                climax = (j, b["v"]); break
        if not climax: continue
        st_low = None
        for j in range(climax[0] + 1, idx - 30):
            b = rows[j]
            if abs(b["l"] - rl) / rl <= 0.03 and b["v"] is not None and b["v"] < climax[1]:
                st_low = b["l"]
        if st_low is None: continue
        # B3 spring in [idx-30, idx)
        spring = None
        for j in range(idx - 30, idx):
            b = rows[j]
            if rl * 0.95 <= b["l"] < rl:
                for k in range(j, min(j + 3, idx)):
                    if rows[k]["c"] > rl:
                        spring = (j, b["l"], b["v"]); break
            if spring: break
        if not spring: continue
        # B4 test day = today
        t = rows[idx]
        if not (t["l"] >= spring[1] and t["l"] <= 1.02 * rl and t["v"] is not None
                and spring[2] is not None and t["v"] < spring[2] and t["c"] > spring[1]): continue
        # T3
        ups = [rows[j]["v"] for j in range(idx - 30, idx) if rows[j]["c"] > rows[j - 1]["c"] and rows[j]["v"] is not None]
        dns = [rows[j]["v"] for j in range(idx - 30, idx) if rows[j]["c"] < rows[j - 1]["c"] and rows[j]["v"] is not None]
        t3 = bool(ups and dns and statistics.mean(ups) > statistics.mean(dns))
        t5 = t["l"] >= st_low
        # T7 vs BTC over range
        bidx0 = IDX[BTC].get(rows[idx - 90]["d"]); bidx1 = bi
        t7 = False; margin = -9
        if bidx0 is not None and brows[bidx0]["c"] > 0:
            margin = (t["c"] / rows[idx - 90]["c"] - 1) - (brows[bidx1]["c"] / brows[bidx0]["c"] - 1)
            t7 = margin > 0
        # T9
        closes = [b["c"] for b in rng_bars]
        cols = pf_columns(closes, 0.01 * rl)
        target = rl + cols * (0.01 * rl) * 3
        fill = t["c"]; stop = spring[1]
        if fill <= stop: continue
        t9 = (target - fill) / (fill - stop) >= 3.0
        if not t9: continue
        if sum([t3, t5, t7]) < 2: continue
        out.append((cid, fill, stop, target, rl, margin))
    out.sort(key=lambda x: -x[5])
    _WCACHE[d] = out
    return out

def run_wyckoff(start, end, floor_active, rng=None, placebo=False):
    cash = 100.0; positions = []  # cid, shares, stop, target, rl
    fl = Floor(floor_active); curve = []; trades = 0; n_trades = 0
    days = [d for d in cal if start <= d <= end]
    for di, d in enumerate(days):
        # exits (intraday stop, target close, SOW close)
        still = []
        for p in positions:
            b = bar_on(p["cid"], d)
            sold = False
            if b:
                if b["l"] <= p["stop"]:
                    px = b["o"] if b["o"] < p["stop"] else p["stop"]
                    cash += p["shares"] * px * (1 - COST); trades += 1; sold = True
                elif b["c"] >= p["target"]:
                    cash += p["shares"] * b["c"] * (1 - COST); trades += 1; sold = True
                else:
                    idx = IDX[p["cid"]][d]
                    rows = S[p["cid"]]
                    pv = [rows[k]["v"] for k in range(idx - 50, idx) if rows[k]["v"] is not None]
                    if pv and b["c"] < p["rl"] and b["v"] is not None and b["v"] >= 1.5 * statistics.mean(pv):
                        cash += p["shares"] * b["c"] * (1 - COST); trades += 1; sold = True
            if not sold: still.append(p)
        positions = still
        # entries at close
        if not fl.blocked(d) and len(positions) < 5:
            cands = wyckoff_candidates(d)
            if placebo and cands:
                mem = [c for c in membership(d) if c in S and IDX[c].get(d, 0) > 252]
                nc = []
                for (cid, fill, stop, target, rl, mg) in cands:
                    rc = rng.choice(mem)
                    rb = bar_on(rc, d)
                    if not rb: continue
                    sf = (fill - stop) / fill; tf = (target - fill) / fill
                    nc.append((rc, rb["c"], rb["c"] * (1 - sf), rb["c"] * (1 + tf), rb["c"], 0))
                cands = nc
            for (cid, fill, stop, target, rl, mg) in cands:
                if len(positions) >= 5: break
                if any(p["cid"] == cid for p in positions): continue
                eq = cash + sum(p["shares"] * (last_close(p["cid"], d) or 0) for p in positions)
                amt = min(0.20 * eq, cash)
                if amt <= 0: continue
                sh = amt * (1 - COST) / fill
                positions.append({"cid": cid, "shares": sh, "stop": stop, "target": target, "rl": rl})
                cash -= amt; trades += 1; n_trades += 1
        eq = cash + sum(p["shares"] * (last_close(p["cid"], d) or 0) for p in positions)
        curve.append([d, round(eq, 4)])
        if fl.check(eq, d) and di + 1 < len(days):
            nd = days[di + 1]
            for p in positions:
                b = bar_on(p["cid"], nd)
                px = b["o"] if b else (last_close(p["cid"], nd) or 0)
                cash += p["shares"] * px * (1 - COST); trades += 1
            positions = []
    final = curve[-1][1] if curve else 100.0
    return {"final": round(final, 2), "max_dd_pct": round(100 * max_dd(curve), 2),
            "trades": trades, "entries": n_trades, "halts": fl.halts,
            "curve": curve, "monthly": monthly_dist(curve)}

def assemble(family, runner, slug, extra_note=""):
    res = {"family": family, "cost_per_side": COST, "windows": {}, "btc_hold": {},
           "placebos": {}, "note": extra_note}
    for w, (st, en) in WINDOWS.items():
        res["btc_hold"][w] = btc_hold(st, en)
        nat = runner(st, en, False)
        v9 = runner(st, en, True)
        res["windows"][w] = {"native": {k: v for k, v in nat.items()},
                             "v9": {k: v for k, v in v9.items()}}
        print(f"{family} {w} native={nat['final']} v9={v9['final']} btc={res['btc_hold'][w]}", flush=True)
    # placebos on FULL, native
    st, en = WINDOWS["FULL"]
    finals = []
    for seed in range(20):
        rng = random.Random(20261122 + seed)
        r = runner(st, en, False, rng=rng, placebo=True)
        finals.append(r["final"])
    real = res["windows"]["FULL"]["native"]["final"]
    res["placebos"]["FULL"] = {"seed_finals": finals, "median": round(statistics.median(finals), 2),
                               "seeds_beaten": sum(1 for f in finals if real > f)}
    print(f"{family} placebos beaten {res['placebos']['FULL']['seeds_beaten']}/20 median {res['placebos']['FULL']['median']}", flush=True)
    outdir = f"{OUTROOT}/crypto-x-{slug}"
    os.makedirs(outdir, exist_ok=True)
    json.dump(res, open(f"{outdir}/results.json", "w"), indent=1)
    return res

if __name__ == "__main__":
    which = sys.argv[1]
    if which == "pv1":
        assemble("novel-pv1-standing-bid", lambda st, en, fl, rng=None, placebo=False: run_rotation(pv1_score, st, en, fl, rng, placebo), "novel-pv1-standing-bid")
    elif which == "pv3":
        assemble("novel-pv3-metaorder", lambda st, en, fl, rng=None, placebo=False: run_rotation(pv3_score, st, en, fl, rng, placebo), "novel-pv3-metaorder")
    elif which == "pv2":
        assemble("novel-pv2-last-seller", lambda st, en, fl, rng=None, placebo=False: run_events("pv2", st, en, fl, rng, placebo), "novel-pv2-last-seller")
    elif which == "pv4":
        assemble("novel-pv4-overnight-confession", lambda st, en, fl, rng=None, placebo=False: run_events("pv4", st, en, fl, rng, placebo), "novel-pv4-overnight-confession")
    elif which == "x2":
        assemble("novel-x2-correlation-switch", run_x2, "novel-x2-correlation-switch")
    elif which == "wyckoff":
        assemble("judgment-wyckoff", run_wyckoff, "judgment-wyckoff")
