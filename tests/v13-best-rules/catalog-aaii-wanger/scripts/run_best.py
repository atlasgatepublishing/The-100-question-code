#!/usr/bin/env python3
"""V13 best-rules run for catalog-aaii-wanger. Chassis per BEST-RULES-SPEC.md:
published screen verbatim at annual June formations 2015-2025; ALL passers
equal-weight at formation; weights DRIFT for the full hold year (no monthly
re-equalization); NO floor; tiered costs on formation trades only."""
import json, os, random, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W04 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
MYFR = os.path.join(ROOT, "data", "frames")
DATA = os.path.join(ROOT, "data")
YEARS = list(range(2009, 2026))

def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
def frame(name, y, kind):
    d = loadj(os.path.join(MYFR, f"{name}_{y}{kind}.json"))
    if not d: d = loadj(os.path.join(W04, "frames", f"{name}_{y}{kind}.json"))
    return {int(k): v for k, v in d.items()}
FR = {nm: {y: frame(nm, y, kd) for y in YEARS} for nm, kd in
      [("Shares", "I"), ("NetIncomeLoss", "D")]}
def cum_split(cik, y_from):
    f = 1.0; prev = None
    for y in YEARS:
        s = FR["Shares"][y].get(cik)
        if s is None or s <= 0: continue
        if prev is not None:
            py, ps = prev; r = s / ps if ps else 1.0
            if (r >= 1.6 or r <= 0.625) and py >= y_from: f *= r
        prev = (y, s)
    return f
def eps_adj(cik, y):
    ni = FR["NetIncomeLoss"][y].get(cik); sh = FR["Shares"][y].get(cik)
    if ni is None or not sh: return None
    cs = cum_split(cik, y)
    return ni / (sh * cs) if cs > 0 else None

tk = json.load(open(os.path.join(DATA, "company_tickers_exchange.json")))
cik2ticker = {}
for row in tk["data"]:
    if row[2]: cik2ticker.setdefault(int(row[0]), row[2].replace("/", "-"))
pre = json.load(open(os.path.join(DATA, "prescreen.json")))
prescreen = {int(k): v for k, v in pre["prescreen"].items()}

def tape(t):
    d = loadj(os.path.join(DATA, f"px_{t}.json"))
    return d if isinstance(d, dict) else {}
TAPES = {}
for c in pre["cand_ciks"]:
    t = cik2ticker.get(c)
    if t:
        tp = tape(t)
        if tp: TAPES[c] = tp
SPY = tape("SPY")

def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

# ---- final members per formation (cap + PE gates with June prices) ----
def members(F):
    out = []
    for c in prescreen.get(F, []):
        tp = TAPES.get(c)
        if not tp: continue
        june = tp.get(f"{F}-06")
        if not june: continue
        raw = june[1]
        sh = FR["Shares"][F-1].get(c)
        if not sh or not raw: continue
        cap = sh * raw * cum_split(c, F-1)
        if not (100e6 <= cap <= 2e9): continue
        e1, e6 = eps_adj(c, F-1), eps_adj(c, F-6)
        if e1 is None or e6 is None or e1 <= 0 or e6 <= 0: continue
        g5 = (e1 / e6) ** (1 / 5) - 1
        if g5 <= 0: continue
        pe = raw / e1
        if pe / (g5 * 100) > 1.0: continue
        out.append((c, cap))
    return out
MEM = {F: members(F) for F in range(2015, 2026)}
print({F: [cik2ticker[c] for c, _ in MEM[F]] for F in MEM}, flush=True)

# ---- placebo pool: W04 tapes (ticker -> {ym: adj}) ----
cand = {int(k): v for k, v in json.load(open(os.path.join(W04, "candidates.json"))).items()}
POOL = {}
for cik, info in cand.items():
    t = info["ticker"].replace("/", "-")
    p = os.path.join(W04, f"px_{t}.json")
    if os.path.exists(p):
        POOL[t] = {r[0]: r[1] for r in json.load(open(p))}

def simulate2(book_by_form, price_fn, cost_fn):
    cash = 100.0; holdings = {}
    curve = {}; total_cost = 0.0; trades = 0
    for i, m in enumerate(MONTHS):
        y, mo = int(m[:4]), int(m[5:7])
        if mo == 6 and y in book_by_form:
            for k, v in list(holdings.items()):
                cst = v * cost_fn(k, None); total_cost += cst; cash += v - cst; trades += 1
            holdings = {}
            mem = book_by_form[y]
            if mem and cash > 0:
                each = cash / len(mem)
                for k, cap in mem:
                    cst = each * cost_fn(k, cap); total_cost += cst; trades += 1
                    holdings[k] = each - cst
                cash = 0.0
        curve[m] = cash + sum(holdings.values())
        if i == len(MONTHS) - 1: break
        nxt = MONTHS[i + 1]
        newh = {}
        for k, v in holdings.items():
            r = price_fn(k, m, nxt)
            if r is None: continue  # written to zero
            newh[k] = v * (1 + r)
        holdings = newh
    return curve, total_cost, trades

def ret_real(c, m, nxt):
    tp = TAPES.get(c)
    if not tp or m not in tp or nxt not in tp: return None
    return tp[nxt][0] / tp[m][0] - 1
def ret_pool(t, m, nxt):
    s = POOL.get(t)
    if not s or m not in s or nxt not in s: return None
    return s[nxt] / s[m] - 1

book = {F: [(c, cap) for c, cap in MEM[F]] for F in MEM}
curve, cost, trades = simulate2(book, ret_real, lambda k, cap: cost_rate(cap))
print("MY final:", curve[MONTHS[-1]], "cost:", round(cost, 2), "trades:", trades, flush=True)

def period_stats(months, vals):
    rets = [vals[i] / vals[i-1] - 1 for i in range(1, len(vals)) if vals[i-1] > 0]
    if not rets: return {}
    ls = cur = 0
    for x in rets: cur = cur + 1 if x <= 0 else 0; ls = max(ls, cur)
    peak = -1; lb = cur = 0; dd = 0.0; runmax = vals[0]
    for v in vals:
        runmax = max(runmax, v); dd = min(dd, v / runmax - 1)
        if v < runmax - 1e-9: cur += 1; lb = max(lb, cur)
        else: cur = 0
    return {"n_periods": len(rets), "share_positive": round(sum(1 for x in rets if x > 0) / len(rets), 3),
            "median_period": round(statistics.median(rets), 4), "mean_period_secondary": round(statistics.mean(rets), 4),
            "best": round(max(rets), 4), "worst": round(min(rets), 4), "longest_losing_streak": ls,
            "longest_below_high_months": lb, "max_dd": round(dd, 4)}

ROADS = {"LONG": "2010-01", "DECADE": "2016-11", "CONT": "2019-01", "VAL": "2023-01"}
def road(curve_map, start):
    ms = [m for m in MONTHS if m >= start]
    vals = [curve_map[m] for m in ms]
    reb = [100 * v / vals[0] for v in vals]
    return round(reb[-1], 2), period_stats(ms, reb), {m: round(v, 4) for m, v in zip(ms, reb)}
def spy_road(start):
    ms = [m for m in MONTHS if m >= start and m in SPY]
    vals = [SPY[m][0] for m in ms]
    reb = [100 * v / vals[0] for v in vals]
    return round(reb[-1], 2)

out = {"counts": {str(F): len(MEM[F]) for F in MEM},
       "members": {str(F): [cik2ticker[c] for c, _ in MEM[F]] for F in MEM},
       "roads": {}, "cost_total": round(cost, 2), "trades": trades, "curve": {m: round(v, 4) for m, v in curve.items()}}
for r, s in ROADS.items():
    f, st, rc = road(curve, s)
    out["roads"][r] = {"final": f, "stats": st, "spy_same_window": spy_road(s), "curve": rc}
    print(r, f, st, "SPY", spy_road(s), flush=True)

# placebos: same counts, random names from W04 pool tape-available at June F, drift chassis, 0.75% flat
out["placebos"] = {}
for r in ("LONG", "CONT"):
    beats = 0; finals = []
    for seed in range(20):
        rng = random.Random(1000 + seed)
        pb = {}
        for F in range(2015, 2026):
            n = len(MEM[F])
            elig = [t for t in POOL if f"{F}-06" in POOL[t]]
            pb[F] = [(t, None) for t in rng.sample(elig, min(n, len(elig)))] if n else []
        pc, _, _ = simulate2(pb, ret_pool, lambda k, cap: 0.0075)
        f, _, _ = road(pc, ROADS[r])
        finals.append(f)
        if out["roads"][r]["final"] > f: beats += 1
    out["placebos"][r] = {"beats": beats, "median_placebo": round(statistics.median(finals), 2), "finals": finals}
    print("placebo", r, beats, out["placebos"][r]["median_placebo"], flush=True)
json.dump(out, open(os.path.join(ROOT, "results.json"), "w"), indent=1)
print("saved", flush=True)
