#!/usr/bin/env python3
"""crypto-x-category: Faber category ROTATION + Moskowitz-Grinblatt category
MOMENTUM on the PIT CMC universe. Spec frozen in CONSTRUCTION-SPEC.md.
Reads v4 caches + v12 crypto-basket-pit weekly snapshots READ-ONLY."""
import json, math, os, random, bisect, statistics
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
WEEKLY = os.path.join(HERE, "..", "crypto-basket-pit", "data", "weekly_snapshots.json")
POT = 100.0
WINDOWS = {"full": ("2017-01-01", "2026-11-20"), "design": ("2017-01-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}

CAT = {}
for c, syms in {
 "PAYMENT": "BTC LTC BCH BSV BTG XRP XLM DASH DCR BCN XVG PIVX WBTC NANO",
 "PLATFORM": "ETH ADA SOL AVAX DOT NEAR EOS NEO TRX ETC XTZ ALGO HBAR ICP SUI TON KLAY WAVES LSK ONT XEM QTUM VET STRAT VEN",
 "PRIVACY": "XMR ZEC",
 "EXCHANGE": "BNB LEO HT CRO BGB HYPE",
 "STABLE": "USDT USDC DAI BUSD UST USD1 USDe",
 "DEFI_INFRA": "LINK ATOM FIL THETA SC MAID GNO REP MKR AAVE UNI OMG ICX ARDR PPT VERI GNT SNGLS FCT DGD ICN PAY MIN TAGZ5 BCC CC M",
 "MEME_SOCIAL": "DOGE SHIB PEPE STEEM HEX GAME",
}.items():
    for s in syms.split(): CAT[s] = c
CATS = sorted(set(CAT.values()))

def load_registry():
    with open(os.path.join(V4, "crypto-basket-pit-results.json")) as f: v4 = json.load(f)
    reg = {}
    for cid_s, info in v4["registry"].items():
        cid = int(cid_s)
        if info["source"] == "excluded": reg[cid] = {**info, "rows": []}; continue
        kind, name = info["source"].split(":", 1)
        fn = {"yahoo": f"y_{name}.json", "binance": f"b_{name}.json", "kraken": f"k_{name}.json"}[kind]
        with open(os.path.join(V4CACHE, fn)) as f: rows = json.load(f)
        reg[cid] = {**info, "rows": rows}
    return reg

class Market:
    def __init__(self, reg, weekly):
        self.reg = reg
        btc = reg[1]["rows"]; self.cal = [r["d"] for r in btc]
        self.ci = {d: i for i, d in enumerate(self.cal)}
        self.bars, self.ff, self.lb, self.lastdate = {}, {}, {}, {}
        for cid, info in reg.items():
            if not info["rows"]: continue
            bars = {r["d"]: r["c"] for r in info["rows"] if r["c"] > 0}
            self.bars[cid] = bars; self.lastdate[cid] = max(bars) if bars else None
            ff, lb, last, li = [], [], None, -1
            for i, d in enumerate(self.cal):
                if d in bars: last, li = bars[d], i
                ff.append(last); lb.append(li)
            self.ff[cid], self.lb[cid] = ff, lb
        self.snap_keys = sorted(weekly.keys())
        self.snap_top = {k: [c["cmc_id"] for c in weekly[k]["top20"]] for k in self.snap_keys}
        # month-end signal dates: last BTC bar of each month
        self.month_ends = []
        for i, d in enumerate(self.cal):
            if i + 1 == len(self.cal) or self.cal[i+1][5:7] != d[5:7]: self.month_ends.append(d)
        self.me_idx = {d: i for i, d in enumerate(self.month_ends)}
    def universe(self, d):
        k = bisect.bisect_right(self.snap_keys, d) - 1
        return self.snap_top[self.snap_keys[k]] if k >= 0 else []
    def close_fresh(self, cid, i):
        """close at index i if a real bar within 7 days, else None"""
        if cid not in self.lb: return None
        lb = self.lb[cid][i]
        if lb < 0 or i - lb > 7: return None
        return self.ff[cid][i]
    def coin_month_ret(self, cid, i0, i1):
        """return over month ending at cal idx i1, starting i0; -1 if dead for good"""
        if cid not in self.bars: return None
        a = self.close_fresh(cid, i0)
        if a is None or a <= 0: return None
        b = self.close_fresh(cid, i1)
        if b is not None: return b / a - 1.0
        # no fresh close at end: dead for good (no bar after i1 at all) -> -100%
        if self.lastdate[cid] <= self.cal[i1]: return -1.0
        return None

def build_category_monthly(mkt):
    """cat_ret[(me_date, cat)] = monthly return; cat_level cumulative; coin membership per month-start"""
    mes = mkt.month_ends
    cat_ret, cat_level, levels = {}, {}, {c: 1.0 for c in CATS}
    hist = {c: [] for c in CATS}  # list of (me_date, level)
    for k in range(1, len(mes)):
        d0, d1 = mes[k-1], mes[k]
        i0, i1 = mkt.ci[d0], mkt.ci[d1]
        uni = mkt.universe(d0)
        bycat = {}
        for cid in uni:
            if cid not in mkt.reg: continue
            sym = mkt.reg[cid]["symbol"]; cat = CAT.get(sym)
            if cat is None: continue
            r = mkt.coin_month_ret(cid, i0, i1)
            if r is not None: bycat.setdefault(cat, []).append(r)
        for c in CATS:
            if c in bycat:
                r = sum(bycat[c]) / len(bycat[c])
                cat_ret[(d1, c)] = r; levels[c] *= (1 + r)
            cat_level[(d1, c)] = levels[c]
            hist[c].append((d1, levels[c]))
    return cat_ret, cat_level, hist

def cat_score(mkt, hist, d, line):
    """scores at month-end date d (d in month_ends)"""
    out = {}
    for c in CATS:
        h = hist[c]; dates = [x[0] for x in h]
        j = bisect.bisect_right(dates, d) - 1
        if j < 0: continue
        lev = {x[0]: x[1] for x in h}
        def ret(months_back):
            # level at d vs level `months_back` month-ends earlier
            if j - months_back < 0: return None
            prev = h[j - months_back][1]
            return h[j][1] / prev - 1.0 if prev > 0 else None
        if line == "rotation":
            rs = [ret(m) for m in (1, 3, 6, 9, 12)]
            if any(r is None for r in rs): continue
            out[c] = sum(rs) / len(rs)
        else:  # momentum: 6-month only
            r = ret(6)
            if r is None: continue
            out[c] = r
    return out

def holdings_for(mkt, d, cats):
    """equal weight across cats, EW coins within cat; returns {cid: weight}"""
    uni = mkt.universe(d); i = mkt.ci[d]; w = {}
    for c in cats:
        members = [cid for cid in uni if cid in mkt.reg and CAT.get(mkt.reg[cid]["symbol"]) == c
                   and mkt.close_fresh(cid, i) is not None]
        if not members: continue
        share = (1.0 / len(cats)) / len(members)
        for cid in members: w[cid] = w.get(cid, 0.0) + share
    tot = sum(w.values())
    if tot > 0: w = {k: v / tot for k, v in w.items()}
    return w

def run_window(mkt, cat_ret, hist, line, wname, ruleset, cost, seed=None):
    start, end = WINDOWS[wname]
    mes = [d for d in mkt.month_ends if start <= d <= end]
    eq, curve, weights, halted = POT, [], {}, False
    floor_ref, episodes, cash_until = POT, 0, None
    rng = random.Random(seed) if seed is not None else None
    prev_me = None
    for d in mkt.month_ends:
        if d > end: break
        i = mkt.ci[d]
        # earn month return on current weights (month ending at d)
        if weights and prev_me is not None:
            i0 = mkt.ci[prev_me]; r = 0.0
            for cid, wt in weights.items():
                cr = mkt.coin_month_ret(cid, i0, i)
                if cr is not None: r += wt * cr
            eq *= (1 + r)
        prev_me = d
        if d < start: continue
        curve.append({"d": d, "eq": round(eq, 4)})
        if ruleset == "v9" and eq <= 0.85 * floor_ref:
            episodes += 1
            if episodes >= 2: halted = True; weights = {}; break
            cash_until = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
            floor_ref = eq; weights = {}
            curve[-1]["halt"] = episodes
            continue
        if cash_until and d < cash_until: weights = {}; continue
        cash_until = None
        scores = cat_score(mkt, hist, d, line)
        if len(scores) < 3: weights = {}; continue
        if rng is not None:
            cats = rng.sample(sorted(scores), 3)
        else:
            cats = [c for c, _ in sorted(scores.items(), key=lambda x: -x[1])[:3]]
        new_w = holdings_for(mkt, d, cats)
        turnover = sum(abs(new_w.get(k, 0) - weights.get(k, 0)) for k in set(new_w) | set(weights))
        eq *= max(0.0, 1 - cost * turnover)
        weights = new_w
        if curve: curve[-1]["eq"] = round(eq, 4)
    if not curve or curve[-1]["d"] != mes[-1] if mes else True:
        pass
    return {"final": round(eq, 2), "curve": curve, "halted": halted, "episodes": episodes}

def btc_hold(mkt, wname, cost=0.006):
    start, end = WINDOWS[wname]
    mes = [d for d in mkt.month_ends if start <= d <= end]
    i0 = mkt.ci[mes[0]]; p0 = mkt.ff[1][i0]
    curve, eq = [], POT * (1 - cost)
    shares = eq / p0
    for d in mes:
        v = shares * mkt.ff[1][mkt.ci[d]]
        curve.append({"d": d, "eq": round(v, 4)})
    return {"final": round(curve[-1]["eq"], 2), "curve": curve}

def period_stats(curve):
    if len(curve) < 2: return None
    rets = []
    for a, b in zip(curve, curve[1:]):
        rets.append(b["eq"] / a["eq"] - 1 if a["eq"] > 0 else 0.0)
    # include first period vs $100 start implicitly via curve[0] vs 100? curve starts at first month-end after entry; use rets as defined plus initial
    prof = sum(1 for r in rets if r > 0)
    losestreak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; losestreak = max(losestreak, cur)
    peak, since, longest = -1, 0, 0
    for pt in curve:
        if pt["eq"] >= peak: peak, since = pt["eq"], 0
        else: since += 1
        longest = max(longest, since)
    return {"n_periods": len(rets), "pct_profitable": round(100 * prof / len(rets), 1) if rets else 0,
            "median_pct": round(100 * statistics.median(rets), 2) if rets else 0,
            "best_pct": round(100 * max(rets), 2) if rets else 0, "worst_pct": round(100 * min(rets), 2) if rets else 0,
            "avg_pct_secondary": round(100 * statistics.mean(rets), 2) if rets else 0,
            "longest_losing_run": losestreak, "longest_stretch_between_highs_months": longest}

def maxdd(curve):
    peak, dd = 0, 0
    for pt in curve:
        peak = max(peak, pt["eq"]); dd = min(dd, pt["eq"] / peak - 1 if peak else 0)
    return round(100 * dd, 1)

def main():
    reg = load_registry()
    with open(WEEKLY) as f: weekly = json.load(f)
    mkt = Market(reg, weekly)
    cat_ret, cat_level, hist = build_category_monthly(mkt)
    out = {"spec": "CONSTRUCTION-SPEC.md frozen 2026-11-22", "cats": CATS,
           "cat_map": CAT, "btc": {}, "lines": {}}
    for w in WINDOWS: out["btc"][w] = btc_hold(mkt, w)
    for line in ("rotation", "momentum"):
        out["lines"][line] = {}
        for ruleset in ("native", "v9"):
            for w in WINDOWS:
                r = run_window(mkt, cat_ret, hist, line, w, ruleset, 0.006)
                r["maxdd_pct"] = maxdd(r["curve"]); r["period_stats"] = period_stats(r["curve"])
                out["lines"][line][f"{ruleset}_{w}"] = r
        for cost in (0.004, 0.008):
            r = run_window(mkt, cat_ret, hist, line, "full", "native", cost)
            out["lines"][line][f"native_full_cost{cost}"] = {"final": r["final"], "maxdd_pct": maxdd(r["curve"])}
        pls = {}
        for w in ("full", "validation"):
            finals = []
            for s in range(1, 21):
                r = run_window(mkt, cat_ret, hist, line, w, "native", 0.006, seed=s)
                finals.append(r["final"])
            real = out["lines"][line][f"native_{w}"]["final"]
            pls[w] = {"placebo_finals": finals, "beaten": sum(1 for x in finals if real > x)}
        out["lines"][line]["placebos"] = pls
    with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(out, f, indent=1)
    for line in ("rotation", "momentum"):
        for k, v in out["lines"][line].items():
            if isinstance(v, dict) and "final" in v: print(line, k, v["final"], "DD", v.get("maxdd_pct"), "btc", out["btc"][k.split("_",1)[1]]["final"] if k.split("_",1)[1] in out["btc"] else "")
        print(line, "placebos", {w: p["beaten"] for w, p in out["lines"][line]["placebos"].items()})
    print("BTC", {w: v["final"] for w, v in out["btc"].items()})

if __name__ == "__main__": main()
