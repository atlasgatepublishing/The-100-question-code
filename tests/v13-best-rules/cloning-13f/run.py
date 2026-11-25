#!/usr/bin/env python3
"""V13 BEST-RULES run — cloning-13f. Simulation only.
Spec: BEST-RULES-SPEC.md (frozen before this run).
Top-3 per manager, slot-weighted, quarterly, next-open rebalance,
SPY 200DMA trend gate (50% invested when SPY < 200DMA at selection),
NO pot floor. Costs 0.10%/side + $0.01/sell order. $100 pots.
Shared inputs (v10 engine/data) are READ-ONLY: all caches written here.
"""
import bisect, calendar, datetime as _dt, importlib.util, json, os, random, time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)
V10 = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/cloning-13f")
DATA10 = os.path.join(V10, "data")

spec = importlib.util.spec_from_file_location("clone_engine", os.path.join(V10, "engine.py"))
ENG = importlib.util.module_from_spec(spec); spec.loader.exec_module(ENG)
E = ENG.E

START_CASH = 100.0
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")

# ---------------- prices (own loader; caches only in this folder) --------
def parse_yahoo(blob):
    j = json.loads(blob); res = j["chart"]["result"][0]
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
    bars.sort(key=lambda b: b["d"])
    return bars

def get_prices(ticker):
    for cand in (os.path.join(CACHE, f"px_{ticker}.json"),
                 os.path.join(DATA10, f"px_{ticker}.json")):
        if os.path.exists(cand) and os.path.getsize(cand) > 100:
            try: return parse_yahoo(open(cand, "rb").read())
            except Exception: pass
    t1 = calendar.timegm(time.strptime("2017-01-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-21", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        blob = r.read()
    with open(os.path.join(CACHE, f"px_{ticker}.json"), "wb") as f:
        f.write(blob)
    return parse_yahoo(blob)

class PriceBook:
    def __init__(self, bars_by_t):
        self.b = bars_by_t
        self.idx = {t: [x["d"] for x in bs] for t, bs in bars_by_t.items()}
        self.dates = sorted({x["d"] for bs in bars_by_t.values() for x in bs})
    def bar(self, t, d):
        i = bisect.bisect_right(self.idx[t], d) - 1
        if i < 0: return None
        x = self.b[t][i]
        return x if x["d"] == d else None
    def close_on_or_before(self, t, d):
        i = bisect.bisect_right(self.idx[t], d) - 1
        return self.b[t][i]["c"] if i >= 0 else None
    def open_on(self, t, d):
        x = self.bar(t, d)
        return x["o"] if x else None

def quarter_selection_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if not (start <= d <= end): continue
        dt = _dt.date.fromisoformat(d)
        key = (dt.year, (dt.month - 1) // 3)
        if key not in seen:
            seen.add(key); out.append(d)
    return out

# ---------------- CUSIP mapping (own figi stage; cache here only) --------
def my_figi(cusips, base_cmap):
    cache_path = os.path.join(CACHE, "cusip_map_extra.json")
    extra = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    todo = [c for c in cusips if c not in base_cmap and c not in extra]
    for i in range(0, len(todo), 5):
        batch = todo[i:i + 5]
        jobs = [{"idType": "ID_CUSIP", "idValue": c} for c in batch]
        req = urllib.request.Request("https://api.openfigi.com/v3/mapping",
            data=json.dumps(jobs).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read())
        except Exception as e:
            print(f"figi batch failed {batch}: {e}", flush=True); continue
        for c, res in zip(batch, resp):
            data = res.get("data") or []
            us = [x for x in data if x.get("exchCode") == "US" and x.get("marketSector") == "Equity"]
            pick = None
            if us:
                cs = [x for x in us if x.get("securityType") == "Common Stock"]
                pick = cs[0] if cs else us[0]
            extra[c] = {"ticker": (pick["ticker"].replace("/", "-") if pick else None)}
        json.dump(extra, open(cache_path, "w"), indent=1)
        time.sleep(3)
    out = {}
    for c in cusips:
        if c in base_cmap: out[c] = base_cmap[c]
        elif extra.get(c, {}).get("ticker"): out[c] = (extra[c]["ticker"], "FIGI")
    return out

# ---------------- build point-in-time states (top-3 + rank10) ------------
spy_bars = get_prices("SPY")
pb_cal = PriceBook({"SPY": spy_bars})
Q_DATES = quarter_selection_dates(pb_cal, CONT[0], CONT[1])
print(f"selection dates: {len(Q_DATES)} {Q_DATES[0]}..{Q_DATES[-1]}", flush=True)

# cusip census over quarterly books (names for mapping)
cusip_names = {}
for D in Q_DATES:
    for cik in ENG.PANEL:
        book, period, _f = ENG.effective_book(cik, D)
        if book is None: continue
        ranked = ENG.rank_positions(book)
        for r in ranked[:3] + ([ranked[9]] if len(ranked) >= 10 else [ranked[-1]] if ranked else []):
            cusip_names.setdefault(r["cusip"], (r["name"], r["title"]))
all_cusips = sorted(cusip_names)
base_raw = json.load(open(os.path.join(DATA10, "cusip_map.json")))
base_cmap = {c: (v["ticker"], v.get("figi_name")) for c, v in base_raw.items() if v.get("ticker")}
cmap = my_figi(all_cusips, base_cmap)
unmapped_in = {c: cusip_names[c] for c in all_cusips if c not in cmap}
if unmapped_in:
    fb, fb_log = ENG.name_map(unmapped_in)   # reads cached SEC tickers file only
    for c, t in fb.items(): cmap[c] = (t, "SEC-NAME-MATCH")
    print(f"name_map fallback: +{len(fb)}", flush=True)
print(f"CUSIP mapping: {len(cmap)}/{len(all_cusips)} mapped; unmapped {len(all_cusips)-len(cmap)}", flush=True)

tickers = sorted({t for t, _ in cmap.values()})
bars, price_fail = {}, {}
for t in tickers + ["SPY"]:
    try:
        b = get_prices(t)
        if not b: raise RuntimeError("empty")
        bars[t] = b
    except Exception as e:
        price_fail[t] = str(e)
print(f"prices: {len(bars)-1}/{len(tickers)} priced; fails={sorted(price_fail)}", flush=True)
pb = PriceBook(bars)
priced = set(bars)

def build_states(cik):
    by_period, groups = {}, {}
    for f in ENG.FILINGS[cik]:
        groups.setdefault(f["filed"], []).append(f)
    bounds = []
    for fdate in sorted(groups):
        for f in sorted(groups[fdate], key=lambda x: (x["period"], x["acc"])):
            p = f["period"]
            if f["form"] == "13F-HR":
                by_period[p] = list(f["holdings"])
            else:
                typ = ENG.AMEND.get((f["label"], f["period"], f["filed"]), "?")
                if typ == "RESTATEMENT" or p not in by_period:
                    by_period[p] = list(f["holdings"])
                else:
                    merged = {h["cusip"]: h for h in by_period[p]}
                    for h in f["holdings"]: merged[h["cusip"]] = h
                    by_period[p] = list(merged.values())
        if by_period:
            ranked = ENG.rank_positions(by_period[max(by_period)])
            if ranked:
                top3 = [r["cusip"] for r in ranked[:3]]
                r10 = (ranked[9] if len(ranked) >= 10 else ranked[-1])["cusip"]
                pool = [r["cusip"] for r in ranked[:10]]
                bounds.append((fdate, top3, r10, pool))
    return bounds

STATES = {}
for cik in ENG.PANEL:
    b = build_states(cik)
    dates, picks = [], []
    for fdate, top3c, r10c, poolc in b:
        def res(c):
            if c not in cmap: return None
            t = cmap[c][0]
            return t if t in priced else None
        dates.append(fdate)
        picks.append(([res(c) for c in top3c], res(r10c), sorted({x for x in (res(c) for c in poolc) if x})))
    STATES[cik] = (dates, picks)

def picks_at(D):
    """(slot list with duplicates, distinct count, placebo pool) from filings filed < D."""
    slots, pool = [], set()
    for cik in ENG.PANEL:
        dates, picks = STATES[cik]
        k = bisect.bisect_left(dates, D) - 1
        if k < 0: continue
        top3, r10, pl = picks[k]
        for t in top3:
            if t: slots.append(t)
        pool.update(pl)
    return slots, len(set(slots)), sorted(pool)

# ---------------- SPY 200DMA gate ---------------------------------------
spy_close = {x["d"]: x["c"] for x in spy_bars}
spy_days = sorted(spy_close)
def gate_fraction(D):
    i = bisect.bisect_right(spy_days, D) - 1
    if i < 199: return 1.0
    ma = sum(spy_close[spy_days[j]] for j in range(i - 199, i + 1)) / 200.0
    return 1.0 if spy_close[spy_days[i]] >= ma else 0.5

# ---------------- pot engine (no floor) ----------------------------------
def run_pot(sel_dates, start, end, picks_fn):
    cash = START_CASH; positions = {}; trades = []; curve = []
    total_costs = 0.0; pending = None
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    def pv_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c: v += sh * c
        return v
    def execute(d, targets):
        nonlocal cash, total_costs
        opens = {}
        for t in set(list(positions) + list(targets)):
            o = pb.open_on(t, d)
            if o: opens[t] = o
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
                sh = bv / opens[t]; c = bv * 0.001
                cash -= bv + c; total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", round(bv, 2), round(c, 2)))
    for d in days:
        if pending is not None:
            execute(d, pending); pending = None
        if d in sel_set:
            targets = picks_fn(d)
            if targets is not None:
                pv = pv_close(d); gf = gate_fraction(d)
                tot = sum(targets.values())
                if tot > 0:
                    pending = {t: pv * gf * w / tot for t, w in targets.items()}
        curve.append((d, round(pv_close(d), 4)))
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_; cst = val * 0.001 + 0.01
            cash += val - cst; total_costs += cst
            trades.append((last, t, "SELL-END", round(val, 2), round(cst, 2)))
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "orders": len(trades), "trades": trades, "curve": curve}

def real_targets(D):
    slots, _n, _pool = picks_at(D)
    if not slots: return None
    w = {}
    for t in slots: w[t] = w.get(t, 0) + 1
    return w

def stats(r):
    peak, maxdd = -1.0, 0.0
    for _d, v in r["curve"]:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": r["final"], "max_dd_pct": round(maxdd * 100, 2),
            "costs": r["costs"], "orders": r["orders"]}

def distribution(curve):
    # monthly periods
    months = {}
    for d, v in curve: months.setdefault(d[:7], []).append((d, v))
    keys = sorted(months)
    rets = []
    prev = None
    for k in keys:
        v = months[k][-1][1]
        if prev is not None: rets.append(v / prev - 1)
        prev = v
    rets_s = sorted(rets)
    med = rets_s[len(rets_s) // 2] if len(rets_s) % 2 else (rets_s[len(rets_s)//2 - 1] + rets_s[len(rets_s)//2]) / 2
    pos = sum(1 for x in rets if x > 0)
    streak = cur = 0
    for x in rets:
        cur = cur + 1 if x <= 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (trading days)
    peak = -1; last_high = 0; longest = 0
    for i, (_d, v) in enumerate(curve):
        if v >= peak: peak = v; last_high = i
        longest = max(longest, i - last_high)
    # yearly fresh-pot style: calendar-year returns of continuous curve
    yrs = {}
    for d, v in curve: yrs.setdefault(d[:4], []).append(v)
    yrets = []
    ykeys = sorted(yrs)
    for i, y in enumerate(ykeys):
        if i == 0: yrets.append((y, yrs[y][-1] / 100.0 - 1))
        else: yrets.append((y, yrs[y][-1] / yrs[ykeys[i-1]][-1] - 1))
    return {"monthly": {"n": len(rets), "median_pct": round(med * 100, 2),
                        "share_positive_pct": round(100 * pos / len(rets), 1) if rets else None,
                        "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
                        "longest_losing_streak_months": streak},
            "longest_days_between_new_highs": longest,
            "yearly_returns": [(y, round(x * 100, 2)) for y, x in yrets]}

def spy_final(start, end):
    s = [x for x in spy_bars if start <= x["d"] <= end]
    return round(100.0 * s[-1]["c"] / s[0]["c"], 2)

def main():
    out = {"family": "cloning-13f", "spec": "v13 best-rules: top-3/manager slot-weighted, quarterly, SPY200DMA gate 50%, no floor, costs 0.10%/side+$0.01/sell"}
    for name, (start, end) in (("CONT", CONT), ("VAL", VAL)):
        sel = [d for d in Q_DATES if start <= d <= end]
        if not sel or sel[0] != start:
            # first selection on/after start: use quarter dates within window; if start not a sel date, prepend start using filings filed < start
            sel = [start] + [d for d in sel if d > start] if name == "VAL" else sel
        r = run_pot(sel, start, end, real_targets)
        st = stats(r); st["distribution"] = distribution(r["curve"])
        st["spy_final"] = spy_final(start, end)
        st["curve"] = r["curve"]
        out[name] = st
        print(name, json.dumps({k: v for k, v in st.items() if k not in ("curve", "distribution")}), flush=True)
        # placebos: 20 seeds
        finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            def placebo_targets(D, rng=rng):
                slots, n_distinct, pool = picks_at(D)
                if not pool or n_distinct == 0: return None
                draw = rng.sample(pool, min(n_distinct, len(pool)))
                return {t: 1 for t in draw}
            pr = run_pot(sel, start, end, placebo_targets)
            finals.append(round(pr["final"], 2))
        beaten = sum(1 for f in finals if st["final"] > f)
        out[name]["placebo_finals"] = sorted(finals)
        out[name]["placebo_beaten"] = f"{beaten}/20"
        out[name]["placebo_median"] = sorted(finals)[10]
        print(name, "placebos beaten", beaten, "/20 median", sorted(finals)[10], flush=True)
    out["closures"] = {"LONG": "no 13F harvest before report period 2018-09-30; no filing available for 2010-2018 selection dates",
                       "DECADE": "honest sub-window is exactly CONT 2019-2026; not double-counted"}
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("done", flush=True)

if __name__ == "__main__":
    main()
