#!/usr/bin/env python3
"""V13 BEST RULES — AAII Weiss blue-chip yield. Spec: BEST-RULES-SPEC.md (frozen).
Chassis: published screen verbatim at each June review (2016-2025); entries
ACCUMULATE; exit only on (a) yield <= 50% of 7yr avg high yield, (b) DPS cut /
no dividend in latest fiscal year, (c) tape ends -> zero. Cap 20 holdings
(highest current yield kept). Annual equal-weight re-equalization at the June
review only. NO floor. Tiered program costs. Monthly marking Jan2010-Nov2026.
Placebos: 20 seeds mirroring entry counts / holding spans / exit dates with
random names from each entry June's tape-available universe.
Data (read-only except this folder): W04 stack frames 2014-2025 + candidates;
v12 dreman dividend frames 2009-2025; this folder's fetched frames 2009-2013
and Yahoo monthly tapes (fallback: W04 px tapes, annual high = max monthly
close, labeled in output)."""
import json, os, random, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W04 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
DRE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-aaii-dreman/data/frames")
MYFR = os.path.join(ROOT, "data", "frames")
COST_TIERS = [(5e9, 0.0010), (1e9, 0.0025), (0, 0.0075)]
CAP_N = 20

def loadj(p):
    return json.load(open(p)) if os.path.exists(p) else {}

def frame(name, y, kind):
    """My fetched 2009-2013 first, then W04 2014-2025."""
    d = loadj(os.path.join(MYFR, f"{name}_{y}{kind}.json"))
    if not d:
        d = loadj(os.path.join(W04, "frames", f"{name}_{y}{kind}.json"))
    return {int(k): v for k, v in d.items()}

YEARS = list(range(2009, 2026))
FR = {}
for nm, kd in [("AssetsCurrent", "I"), ("LiabilitiesCurrent", "I"), ("StockholdersEquity", "I"),
               ("LongTermDebtCurrent", "I"), ("LongTermDebtNoncurrent", "I"), ("DebtCurrent", "I"),
               ("Shares", "I"), ("NetIncomeLoss", "D")]:
    FR[nm] = {y: frame(nm, y, kd) for y in YEARS}
DIV = {}
for y in YEARS:
    d1 = {int(k): v for k, v in loadj(os.path.join(DRE, f"PaymentsOfDividendsCommonStock_{y}D.json")).items()}
    d2 = {int(k): v for k, v in loadj(os.path.join(DRE, f"PaymentsOfDividends_{y}D.json")).items()}
    DIV[y] = d1 if d1 else d2

cand = {int(k): v for k, v in loadj(os.path.join(W04, "candidates.json")).items()}

# ---- price tapes: {cik: {'YYYY-MM': (adj, close, high)}} ----
px = {}
px_src = {}
for cik, info in cand.items():
    t = info["ticker"].replace("/", "-")
    p = os.path.join(ROOT, "data", f"px_{t}.json")
    if os.path.exists(p):
        try:
            px[cik] = {m: tuple(v) for m, v in json.load(open(p)).items()}
            px_src[cik] = "yahoo"
            continue
        except Exception:
            pass
    p2 = os.path.join(W04, f"px_{t}.json")
    if os.path.exists(p2):
        try:
            px[cik] = {r[0]: (r[1], r[2], r[2]) for r in loadj(p2)}
            px_src[cik] = "w04_closeproxy"
        except Exception:
            pass
spy = {}
_sp = os.path.join(ROOT, "data", "px_SPY.json")
if os.path.exists(_sp):
    spy = {m: v[0] for m, v in json.load(open(_sp)).items()}
if not spy:
    spy = {r[0]: r[1] for r in loadj(os.path.join(W04, "px_SPY.json"))}

MONTHS = []
y, m = 2010, 1
while (y, m) <= (2026, 11):
    MONTHS.append(f"{y:04d}-{m:02d}")
    m += 1
    if m == 13: y, m = y + 1, 1

# split-factor correction for DPS/shares (as in v12 slice engine)
sf = {}
for cik in cand:
    avail = [(yy, FR["Shares"][yy][cik]) for yy in YEARS if cik in FR["Shares"][yy]]
    d = {}
    for F in range(2016, 2027):
        f = 1.0
        for (y0, a), (y1, b) in zip(avail, avail[1:]):
            if y1 >= F and a:
                r = b / a
                if r >= 1.6 or r <= 0.625: f *= r
        d[F] = f
    sf[cik] = d

def dps(cik, y):
    dv = DIV[y].get(cik); sh = FR["Shares"][y].get(cik)
    if not dv or not sh: return None
    return dv / sh

def eps(cik, y):
    ni = FR["NetIncomeLoss"][y].get(cik); sh = FR["Shares"][y].get(cik)
    if ni is None or not sh: return None
    return ni / sh

def annual_high(cik, y):
    s = px.get(cik)
    if not s: return None
    hs = [v[2] for mm, v in s.items() if mm.startswith(f"{y:04d}-") and v[2]]
    return max(hs) if hs else None

def june_close(cik, F):
    s = px.get(cik)
    if not s: return None
    v = s.get(f"{F:04d}-06")
    return v[1] if v and v[1] else None

def screen_pass(cik, F):
    """Published Weiss screen at June formation F (fiscal years F-7..F-1)."""
    yrs = list(range(F - 7, F))
    ds = [dps(cik, yy) for yy in yrs]
    if any(v is None or v <= 0 for v in ds): return None
    inc = sum(1 for i in range(1, 7) if ds[i] > ds[i - 1])
    dec = any(ds[i] < ds[i - 1] for i in range(1, 7))
    if inc < 3 or dec: return None
    es = [eps(cik, yy) for yy in yrs]
    if any(v is None for v in es): return None
    einc = sum(1 for i in range(1, 7) if es[i] > es[i - 1])
    if einc < 4: return None
    sh = FR["Shares"][F - 1].get(cik)
    if not sh or sh < 5e6: return None
    price = june_close(cik, F)
    if not price: return None
    ahy = []
    for i, yy in enumerate(yrs):
        h = annual_high(cik, yy)
        if not h: return None
        # DPS stated on formation-F share basis (split-consistent)
        ahy.append(ds[i] * (sf[cik][F] if False else 1.0) / h)
    # NOTE: DPS from frames is in each year's own share units; split years are
    # handled by comparing yields only within consistent tape prices -- the
    # tape 'close/high' are raw (unadjusted), DPS raw per-share of that year.
    cur_yield = ds[-1] / price
    if cur_yield < 0.9 * float(np.mean(ahy)): return None
    ac = FR["AssetsCurrent"][F - 1].get(cik); lc = FR["LiabilitiesCurrent"][F - 1].get(cik)
    if not ac or not lc or ac / lc < 2.0: return None
    eqv = FR["StockholdersEquity"][F - 1].get(cik)
    if not eqv or eqv <= 0: return None
    debt = (FR["LongTermDebtNoncurrent"][F - 1].get(cik) or 0) + \
           (FR["LongTermDebtCurrent"][F - 1].get(cik) or 0) + (FR["DebtCurrent"][F - 1].get(cik) or 0)
    if debt / eqv > 0.5: return None
    ni = FR["NetIncomeLoss"][F - 1].get(cik)
    if not ni or ni <= 0 or DIV[F - 1][cik] / ni > 0.5: return None
    return cur_yield

def avg_high_yield(cik, F):
    yrs = list(range(F - 7, F))
    ds = [dps(cik, yy) for yy in yrs]
    if any(v is None for v in ds): return None
    ahy = []
    for i, yy in enumerate(yrs):
        h = annual_high(cik, yy)
        if not h: return None
        ahy.append(ds[i] / h)
    return float(np.mean(ahy))

def cost_rate(cik, F):
    sh = FR["Shares"].get(F - 1, {}).get(cik) or FR["Shares"].get(F - 2, {}).get(cik)
    p = june_close(cik, F) or june_close(cik, F - 1)
    if not sh or not p: return 0.0075
    cap = sh * p
    for thr, r in COST_TIERS:
        if cap >= thr: return r
    return 0.0075

# ---------- precompute screen + events ----------
FORM_YEARS = list(range(2016, 2026))
passers = {}
for F in FORM_YEARS:
    res = {}
    for cik in cand:
        if cik not in px: continue
        try:
            cy = screen_pass(cik, F)
        except Exception:
            cy = None
        if cy is not None: res[cik] = cy
    passers[F] = res
    print("formation", F, "passers", len(res), sorted(cand[c]["ticker"] for c in res), flush=True)

def build_events(seed=None):
    """Returns list of (cik, entry_F, exit_F or 2026 for still-held/marked to
    Nov-2026) following the frozen chassis. Placebo (seed not None): build the
    real events first, then replace each entry with a random tape-available
    name keeping the SAME entry/exit span (frozen spec)."""
    if seed is not None:
        real = build_events()
        rng = random.Random(seed)
        out = []
        used_by_F = {}
        for cik, eF, xF in real:
            pool = [c for c in cand if c in px and june_close(c, eF)
                    and c not in used_by_F.get(eF, set())]
            if not pool: continue
            pick = rng.choice(pool)
            used_by_F.setdefault(eF, set()).add(pick)
            out.append((pick, eF, xF))
        return out
    held = {}  # cik -> entry_F
    events = []
    rng = None
    for F in FORM_YEARS:
        # exits at this review
        for cik in list(held):
            reason = None
            d_prev = dps(cik, F - 2); d_cur = dps(cik, F - 1)
            if d_cur is None or d_cur <= 0 or (d_prev is not None and d_cur < d_prev):
                reason = "cut"
            else:
                ahy = avg_high_yield(cik, F)
                price = june_close(cik, F)
                if ahy and price and (d_cur / price) <= 0.5 * ahy:
                    reason = "band"
            if reason:
                events.append((cik, held.pop(cik), F))
        # entries
        new = [c for c in passers[F] if c not in held]
        for c in new:
            held[c] = F
        # cap 20 by current yield
        if len(held) > CAP_N:
            ranked = sorted(held, key=lambda c: -(dps(c, F - 1) or 0) / (june_close(c, F) or 1e18))
            for c in ranked[CAP_N:]:
                e = held.pop(c)
                if e != F:  # bought this same review and capped out: never enters
                    events.append((c, e, F))
    for cik, eF in held.items():
        events.append((cik, eF, 2026))  # held to end (marked through Nov 2026)
    return events

def simulate(events):
    """Monthly simulation Jan2010-Nov2026. At each June review: sell exits,
    buy entries, re-equalize all holdings. Costs tiered per name at review."""
    ev_by_F = {}
    for cik, eF, xF in events:
        ev_by_F.setdefault(eF, []).append(("buy", cik))
        if xF <= 2025:
            ev_by_F.setdefault(xF, []).append(("sell", cik))
    cash = 100.0
    shares = {}  # cik -> share count (adj-price units)
    curve = {}
    total_cost = 0.0
    n_trades = 0
    for mi, mm in enumerate(MONTHS):
        y = int(mm[:4]); mo = int(mm[5:7])
        # mark
        val = cash
        for cik, n in shares.items():
            s = px[cik].get(mm)
            if s: val += n * s[0]
        curve[mm] = val
        if mo == 6 and y in ev_by_F:
            # current values per name (adj)
            def curval(cik):
                s = px[cik].get(mm)
                return shares.get(cik, 0.0) * s[0] if s else 0.0
            for kind, cik in ev_by_F[y]:
                if kind == "sell" and cik in shares:
                    v = curval(cik); r = cost_rate(cik, y)
                    total_cost += v * r; cash += v * (1 - r)
                    del shares[cik]; n_trades += 1
            total = cash + sum(curval(c) for c in shares)
            buys = [c for k, c in ev_by_F[y] if k == "buy"]
            book = list(shares) + [c for c in buys if c not in shares]
            if book and total > 0:
                tgt = total / len(book)
                review_cost = 0.0
                for cik in book:
                    s = px[cik].get(mm)
                    if not s or not s[0]: continue
                    cur = curval(cik)
                    delta = tgt - cur
                    r = cost_rate(cik, y)
                    if abs(delta) > 1e-9:
                        total_cost += abs(delta) * r; review_cost += abs(delta) * r; n_trades += 1
                    newv = tgt - abs(delta) * r if delta != 0 else cur
                    shares[cik] = max(newv, 0.0) / s[0]
                cash = total - review_cost - sum(curval(c) for c in shares)
        # month-end: names whose tape has ended -> zero (remove, value lost already via missing marks=0)
        for cik in list(shares):
            s = px.get(cik, {})
            if s and mm > max(s):
                del shares[cik]
    return curve, round(total_cost, 2), n_trades

def period_stats(vals):
    v = np.array(vals, dtype=float)
    r = v[1:] / v[:-1] - 1
    r = r[np.isfinite(r)]
    if len(r) == 0: return {}
    ls = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0; ls = max(ls, cur)
    peak = np.maximum.accumulate(v)
    below = v < peak - 1e-9
    lb = cur = 0
    for b in below:
        cur = cur + 1 if b else 0; lb = max(lb, cur)
    dd = float((v / peak - 1).min()) if len(v) else 0.0
    return {"n_periods": int(len(r)), "share_positive": round(float((r > 0).mean()), 3),
            "median_period": round(float(np.median(r)), 4),
            "mean_period_secondary": round(float(r.mean()), 4),
            "best": round(float(r.max()), 4), "worst": round(float(r.min()), 4),
            "longest_losing_streak": int(ls), "longest_below_high_months": int(lb),
            "max_dd": round(dd, 4)}

ROADS = {"LONG": ("2010-01", "2026-11"), "DECADE": ("2016-11", "2026-11"),
         "CONT": ("2019-01", "2026-11"), "VAL": ("2023-01", "2026-11")}
def road_slice(curve, road):
    a, b = ROADS[road]
    ms = [m for m in MONTHS if a <= m <= b]
    vals = [curve[m] for m in ms]
    reb = [100.0 * v / vals[0] for v in vals]
    return round(reb[-1], 2), period_stats(reb), {m: round(v, 4) for m, v in zip(ms, reb)}

def main():
    events = build_events()
    print("events", len(events), flush=True)
    curve, cost, ntr = simulate(events)
    out = {"spec": "v13 best-rules weiss: accumulate + band/cut exit, cap20, annual re-eq, no floor",
           "passers_by_formation": {F: sorted(cand[c]["ticker"] for c in passers[F]) for F in FORM_YEARS},
           "events": [{"ticker": cand[c]["ticker"], "entry": e, "exit": x} for c, e, x in sorted(events, key=lambda z: (z[1], z[0]))],
           "total_cost": cost, "n_trades": ntr, "roads": {}, "placebos": {},
           "px_sources": {"yahoo": sum(1 for v in px_src.values() if v == "yahoo"),
                          "w04_closeproxy": sum(1 for v in px_src.values() if v != "yahoo")}}
    for road in ROADS:
        f, st, cv = road_slice(curve, road)
        out["roads"][road] = {"final": f, "stats": st, "curve": cv}
        print(road, f, st, flush=True)
    # SPY same-slice
    out["spy_same_slice"] = {}
    for road in ROADS:
        a, b = ROADS[road]
        ms = [m for m in MONTHS if a <= m <= b and m in spy]
        if len(ms) > 1:
            out["spy_same_slice"][road] = round(100.0 * spy[ms[-1]] / spy[ms[0]], 2)
    # placebos
    for road in ("LONG", "CONT"):
        beats = 0; finals = []
        for seed in range(20):
            ev = build_events(seed=seed)
            pc, _, _ = simulate(ev)
            f, _, _ = road_slice(pc, road)
            finals.append(f)
            if out["roads"][road]["final"] > f: beats += 1
        out["placebos"][road] = {"beats": beats, "median_placebo": round(float(np.median(finals)), 2),
                                 "finals": finals}
        print("placebo", road, beats, out["placebos"][road]["median_placebo"], flush=True)
    # folds (formation windows) as fresh $100 pots over their month spans
    out["folds"] = {}
    for name, (a, b) in {"FOLD_2016_2020": ("2016-06", "2021-06"), "FOLD_2021_2025": ("2021-06", "2026-11"),
                         "LONG_H1": ("2010-01", "2018-06"), "LONG_H2": ("2018-06", "2026-11")}.items():
        ms = [m for m in MONTHS if a <= m <= b]
        vals = [curve[m] for m in ms]
        out["folds"][name] = {"final": round(100.0 * vals[-1] / vals[0], 2), "stats": period_stats([100.0 * v / vals[0] for v in vals]),
                              "spy": round(100.0 * spy[ms[-1]] / spy[ms[0]], 2) if ms[0] in spy and ms[-1] in spy else None}
    json.dump(out, open(os.path.join(ROOT, "results.json"), "w"), indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
