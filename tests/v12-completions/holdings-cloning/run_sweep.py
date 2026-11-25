#!/usr/bin/env python3
"""Holdings-count sweep: 13F cloning (v12 wing, pre-registered grid).
Chassis: v10 cloning engine mechanics (next-open rebalance, equal weight
across distinct tickers, costs 0.10%/side + $0.01/sell). Forms:
  native: no floor.  house: v9 protections (plain -15% floor, liquidate
  next open, 90-day cash sit, one restart, second halt ends run).
Count ladder per SPEC.md. Roads: CONT 2019-2026, VAL 2023-2026,
PRE 2019-2022 (confirmation). 20-seed placebos per cell."""
import importlib.util, json, os, random, statistics, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
V10 = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/cloning-13f")
spec = importlib.util.spec_from_file_location("clone_engine", os.path.join(V10, "engine.py"))
ENG = importlib.util.module_from_spec(spec); spec.loader.exec_module(ENG)
E = ENG.E

COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
ROADS = {"CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20"),
         "PRE": ("2019-01-02", "2022-12-30")}

# ---------------------------------------------------------------- ladder
books = json.load(open(os.path.join(HERE, "books.json")))
cmap = json.load(open(os.path.join(HERE, "cusip_map_ext.json")))["map"]
QALL = books["dates"]

def ladder_for(D):
    """Returns (ranked candidate tickers, native rank-1 distinct tickers)."""
    agg = {}   # ticker -> [best_rank, weight_sum]
    native = []
    for cik, v in books["books"][D].items():
        if not v: continue
        for i, row in enumerate(v["rows"]):
            t = cmap.get(row["cusip"])
            if not t: continue
            r = i + 1
            if r == 1: native.append(t)
            cur = agg.get(t)
            if cur is None: agg[t] = [r, row["pct"] or 0.0]
            else:
                cur[0] = min(cur[0], r); cur[1] += row["pct"] or 0.0
    ranked = sorted(agg.items(), key=lambda kv: (kv[1][0], -kv[1][1], kv[0]))
    return [t for t, _ in ranked], sorted(set(native))

LADDERS = {D: ladder_for(D) for D in QALL}

# ---------------------------------------------------------------- prices
def parse_yahoo_raw(raw):
    try:
        res = raw["chart"]["result"][0]; ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
        bars = []
        for i, t in enumerate(ts):
            c = q["close"][i]
            if c is None: continue
            a = adj[i] if adj and adj[i] else c
            ratio = a / c if c else 1.0
            o = q["open"][i]
            bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                         "o": (o * ratio if o else a), "c": a})
        bars.sort(key=lambda b: b["d"])
        return bars
    except Exception:
        return None

PRICE_DIRS = [HERE, os.path.join(V10, "data"),
              os.path.expanduser("~/workspace/stock-app/backtests/v4/data"),
              os.path.expanduser("~/workspace/stock-app/backtests/v4/value-momentum-honest-data"),
              os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/cloning-13f"),
              os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/bars")]

def load_bars(t):
    for d in PRICE_DIRS:
        for pat in (f"px_{t}.json", f"yh_{t}.json", f"{t}.json"):
            p = os.path.join(d, pat)
            if os.path.exists(p) and os.path.getsize(p) > 100:
                try:
                    raw = json.load(open(p))
                    if "chart" in raw: return parse_yahoo_raw(raw)
                    if isinstance(raw, list): return raw
                except Exception: pass
    # fetch into HERE
    import calendar
    t1 = calendar.timegm(time.strptime("2018-06-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-21", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(t)}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r: raw = json.loads(r.read())
        json.dump(raw, open(os.path.join(HERE, f"px_{t}.json"), "w"))
        return parse_yahoo_raw(raw)
    except Exception:
        return None

all_tickers = sorted({t for D in QALL for t in LADDERS[D][0]})
print(f"candidate tickers total: {len(all_tickers)}", flush=True)
bars, fails = {}, []
spy_bars = E.get_prices("SPY"); bars["SPY"] = spy_bars
_PKL = os.path.join(HERE, "prices_cache.json")
if os.path.exists(_PKL):
    bars = json.load(open(_PKL))["bars"]
    print(f"prices from cache: {len(bars)}", flush=True)
else:
    for i, t in enumerate(all_tickers):
        b = load_bars(t)
        if b: bars[t] = b
        else: fails.append(t)
        if i % 100 == 0: print(f"prices {i}/{len(all_tickers)} fails={len(fails)}", flush=True)
    print(f"priced {len(bars)-1}/{len(all_tickers)}; fails={fails}", flush=True)
pb = E.PriceBook(bars)
PRICED = set(bars)
# memoized price lookups (identical across the 21 runs per cell)
_cob, _bar = {}, {}
_orig_cob, _orig_bar = pb.close_on_or_before, pb.bar
def cob(t, d):
    k = (t, d)
    if k not in _cob: _cob[k] = _orig_cob(t, d)
    return _cob[k]
def barf(t, d):
    k = (t, d)
    if k not in _bar: _bar[k] = _orig_bar(t, d)
    return _bar[k]
pb.close_on_or_before, pb.bar = cob, barf

# tradable ladders (priced only)
TLAD = {}
for D in QALL:
    ranked, native = LADDERS[D]
    TLAD[D] = ([t for t in ranked if t in PRICED], [t for t in native if t in PRICED])

def picks_for(count, D):
    ranked, native = TLAD[D]
    if count == "NATIVE": return list(dict.fromkeys(native))
    if count == "ALL": return list(ranked)
    return list(ranked[:count])

# ---------------------------------------------------------------- engine
def run_pot(picks_map, start, end, form, start_cash=100.0):
    cash = start_cash; floor = 0.85 * start_cash if form == "house" else None
    positions = {}; trades = []; total_costs = 0.0
    episode = 1; resume = None; restarts = []; halted = None; curve = []
    sel_dates = E.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates); days = [d for d in pb.dates if start <= d <= end]
    pending = None
    def pclose(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c: v += sh * c
        return v
    def rebalance(d, targets):
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
                trades.append((d, t, "SELL", round(sv, 2), round(c, 2)))
                if positions[t] < 1e-9: del positions[t]
        for t, tgt in targets.items():
            if t not in opens: continue
            cur = positions.get(t, 0.0) * opens[t]; bv = tgt - cur
            if bv > 0.005:
                bv = min(bv, cash / 1.001)
                if bv <= 0.005: continue
                c = bv * 0.001; cash -= bv + c; total_costs += c
                positions[t] = positions.get(t, 0.0) + bv / opens[t]
                trades.append((d, t, "BUY", round(bv, 2), round(c, 2)))
    for di, d in enumerate(days):
        if pending is not None:
            rebalance(d, pending); pending = None
        if d in sel_set and (resume is None or d >= resume):
            picks = picks_map.get(d) or []
            if picks:
                pv = pclose(d); each = pv / len(picks)
                pending = {t: each for t in picks}
        v = pclose(d); curve.append((d, round(v, 4)))
        if floor is not None and v <= floor and di < len(days) - 1:
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]; c = val * 0.001 + 0.01
                    cash += val - c; total_costs += c
                    trades.append((nd, t, "SELL-HALT", round(val, 2), round(c, 2)))
            positions = {}; pending = None
            if episode == 1:
                import datetime as _dt
                episode = 2
                resume = (_dt.date.fromisoformat(d) + _dt.timedelta(days=90)).isoformat()
                restarts.append({"halt_date": d, "restart_balance": round(cash, 2)})
                floor = 0.85 * cash; halted = None
            else:
                halted = d
                return {"final": round(cash, 2), "costs": round(total_costs, 2),
                        "orders": len(trades), "curve": curve, "halted": halted,
                        "restarts": restarts, "trades": trades}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_; cst = val * 0.001 + 0.01
            cash += val - cst; total_costs += cst
            trades.append((last, t, "SELL-END", round(val, 2), round(cst, 2)))
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "orders": len(trades), "curve": curve, "halted": halted,
            "restarts": restarts, "trades": trades}

def maxdd(curve):
    peak = -1.0; m = 0.0
    for _, v in curve:
        peak = max(peak, v); m = max(m, (peak - v) / peak if peak > 0 else 0)
    return round(m * 100, 2)

def period_dist(curve, sel_dates):
    marks = []
    cd = dict(curve)
    for d in sel_dates:
        if d in cd: marks.append((d, cd[d]))
    if curve and (not marks or marks[-1][0] != curve[-1][0]): marks.append(curve[-1])
    rets = [marks[i + 1][1] / marks[i][1] - 1 for i in range(len(marks) - 1)]
    if not rets: return None
    los = 0; worst_run = 0
    for r in rets:
        los = los + 1 if r < 0 else 0; worst_run = max(worst_run, los)
    # longest stretch between new highs, from daily curve (calendar days)
    import datetime as _dt
    peak = -1; last_high = None; longest = 0
    for d, v in curve:
        if v > peak:
            if last_high: longest = max(longest, (_dt.date.fromisoformat(d) - _dt.date.fromisoformat(last_high)).days)
            peak = v; last_high = d
    return {"periods": len(rets), "pct_profitable": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "avg_pct_secondary": round(statistics.mean(rets) * 100, 2),
            "longest_losing_run": worst_run, "longest_between_highs_days": longest}

def spy_final(start, end):
    s = [b for b in spy_bars if start <= b["d"] <= end]
    return round(100 * s[-1]["c"] / s[0]["c"], 2)

# ---------------------------------------------------------------- prep mode
if "--prep" in sys.argv:
    try:
        json.dump({"bars": bars, "TLAD": TLAD}, open(os.path.join(HERE, "prices_cache.json"), "w"))
        print("prepped", len(bars), "tickers")
    except Exception as e:
        print("prep write failed:", e)
    sys.exit(0)

# ---------------------------------------------------------------- curve mode
_cv = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--curve=")), None)
if _cv:
    _road, _form, _cnt = _cv.split("|")
    _cnt = "NATIVE" if _cnt == "NATIVE" else ("ALL" if _cnt == "ALL" else int(_cnt))
    _s, _e = ROADS[_road]
    _sel = E.quarter_selection_dates(pb, _s, _e)
    _r = run_pot({d: picks_for(_cnt, d) for d in _sel}, _s, _e, _form)
    print("CURVECSV " + _cv + " final=" + str(_r["final"]) + " first=" + _r["curve"][0][0]
          + " last=" + _r["curve"][-1][0], flush=True)
    _cd = dict(_r["curve"])
    _marks = [[d, _cd[d]] for d in _sel if d in _cd]
    _marks.append([_r["curve"][-1][0], _r["curve"][-1][1]])
    print("MARKSJSON " + json.dumps({"key": _cv, "marks": _marks}), flush=True)
    sys.exit(0)

# ---------------------------------------------------------------- sweep
_RP = os.path.join(HERE, "results.json")
out = None
if os.path.exists(_RP) and os.path.getsize(_RP) > 10:
    try:
        out = json.load(open(_RP)); out.setdefault("cells", {})
    except Exception:
        out = None
if out is None:
    out = {"family": "holdings-cloning", "cells": {}, "spy": {}, "ladder_sizes": {},
           "native_counts": {}, "price_fails": fails}
for D in QALL:
    out["ladder_sizes"][D] = len(TLAD[D][0]); out["native_counts"][D] = len(set(TLAD[D][1]))
_only_road = next((a.split("=")[1] for a in sys.argv if a.startswith("--road=")), None)
_only_form = next((a.split("=")[1] for a in sys.argv if a.startswith("--form=")), None)
for road, (start, end) in ROADS.items():
    if _only_road and road != _only_road: continue
    out["spy"][road] = spy_final(start, end)
    sel = [d for d in E.quarter_selection_dates(pb, start, end)]
    for form in ("native", "house"):
        if _only_form and form != _only_form: continue
        _only_counts = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--counts=")), None)
        _clist = COUNTS + ["NATIVE"]
        if _only_counts:
            _want = _only_counts.split(",")
            _clist = [c for c in _clist if str(c) in _want or (c == "NATIVE" and "NATIVE" in _want)]
        for count in _clist:
            key = f"{road}|{form}|{count}"
            pmap = {d: picks_for(count, d) for d in sel}
            r = run_pot(pmap, start, end, form)
            twins = []
            for seed in range(20):
                rng = random.Random(10_000 * seed + hash(key) % 1000)
                tmap = {}
                for d in sel:
                    ranked, _n = TLAD[d]
                    n = len(pmap[d])
                    tmap[d] = rng.sample(ranked, min(n, len(ranked))) if ranked else []
                tr = run_pot(tmap, start, end, form)
                twins.append(tr["final"])
            beaten = sum(1 for x in twins if r["final"] > x)
            cell = {"final": r["final"], "max_dd_pct": maxdd(r["curve"]), "costs": r["costs"],
                    "orders": r["orders"], "halted": r["halted"], "restarts": r["restarts"],
                    "placebos_beaten": beaten, "placebo_median": round(statistics.median(twins), 2),
                    "twin_finals": [round(x, 2) for x in twins]}
            if road == "CONT":
                cell["curve"] = r["curve"]
                cell["period_dist"] = period_dist(r["curve"], sel)
                cell["picks_by_date"] = {d: pmap[d] for d in sel}
            out["cells"][key] = cell
            print(f"{key}: final={r['final']} dd={cell['max_dd_pct']} beaten={beaten}/20", flush=True)
            _slim = {k: v for k, v in cell.items() if k not in ("curve", "picks_by_date")}
            print("CELLJSON " + json.dumps({"key": key, **_slim}), flush=True)
    try:
        json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    except Exception as e:
        print("results.json write skipped:", e, flush=True)
print("DONE")
