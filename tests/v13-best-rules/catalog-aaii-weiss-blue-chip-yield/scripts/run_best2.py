#!/usr/bin/env python3
"""V13 BEST RULES — Weiss, RUN OF RECORD (see BEST-RULES-SPEC.md + Addendum).
Universe: full EDGAR frames dividend-paying operating filers (824 CIKs);
screen = published gates verbatim, per-share series split-adjusted to current
units (Yahoo OHLC is split-adjusted; within-tape yields consistent).
Chassis (frozen): June entries accumulate; exit on yield <= 50% of 7yr avg
high yield, DPS cut/no-pay, or tape end; cap 20 by current yield; annual
equal-weight re-equalization at June review; NO floor; tiered program costs.
Placebos: 20 seeds, random names from all cached tapes at each entry June,
same entry/exit spans. Roads/folds as frozen."""
import json, os, random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
W04 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
DRE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-aaii-dreman/data/frames")
MYFR = os.path.join(ROOT, "data", "frames")
YEARS = list(range(2009, 2026))
FORM_YEARS = list(range(2016, 2026))
CAP_N = 20

def loadj(p): return json.load(open(p)) if os.path.exists(p) else {}
def frame(name, y, kind):
    d = loadj(os.path.join(MYFR, f"{name}_{y}{kind}.json"))
    if not d: d = loadj(os.path.join(W04, "frames", f"{name}_{y}{kind}.json"))
    return {int(k): v for k, v in d.items()}

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

pre = json.load(open(os.path.join(ROOT, "data", "prescreen.json")))
cik2ticker = {int(k): v for k, v in pre["cik2ticker"].items()}
UNIV = sorted(cik2ticker)  # non-price passers in >=1 formation

# tapes by ticker: { 'YYYY-MM': (adj, close, high) }
def load_tape(t):
    p = os.path.join(ROOT, "data", f"px_{t}.json")
    if not os.path.exists(p): return None
    try: return {m: tuple(v) for m, v in json.load(open(p)).items()}
    except Exception: return None

px = {}
for cik in UNIV:
    tp = load_tape(cik2ticker[cik])
    if tp: px[cik] = tp
print("passers with tapes:", len(px), "of", len(UNIV), flush=True)

# placebo tape pool (all cached tapes, ticker-keyed)
pool_tapes = {}
import glob
for f in glob.glob(os.path.join(ROOT, "data", "px_*.json")):
    t = os.path.basename(f)[3:-5]
    if t == "SPY": continue
    tp = load_tape(t)
    if tp and len(tp) >= 24: pool_tapes[t] = tp
spy = load_tape("SPY")
if spy: spy = {m: v[0] for m, v in spy.items()}
else: spy = {r[0]: r[1] for r in loadj(os.path.join(W04, "px_SPY.json"))}

def jumps(cik):
    s = FR["Shares"]; out = {}; prev = None
    for y in YEARS:
        if cik in s[y]:
            if prev is not None and s[prev].get(cik):
                r = s[y][cik] / s[prev][cik]
                if r >= 1.6 or r <= 0.625: out[y] = r
            prev = y
    return out

JM = {c: jumps(c) for c in UNIV}
def per_share(cik, y, kind):
    """Per-share value for fiscal y in CURRENT share units."""
    sh = FR["Shares"][y].get(cik)
    if not sh: return None
    if kind == "dps":
        dv = DIV[y].get(cik)
        if not dv: return None
        v = dv / sh
    else:
        ni = FR["NetIncomeLoss"][y].get(cik)
        if ni is None: return None
        v = ni / sh
    J = 1.0
    for z, r in JM[cik].items():
        if z > y: J *= r
    return v / J if J > 0 else None

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

def avg_high_yield(cik, F):
    ahy = []
    for y in range(F - 7, F):
        d = per_share(cik, y, "dps"); h = annual_high(cik, y)
        if d is None or not h: return None
        ahy.append(d / h)
    return float(np.mean(ahy))

def screen_pass(cik, F):
    yrs = list(range(F - 7, F))
    ds = [per_share(cik, y, "dps") for y in yrs]
    if any(v is None or v <= 0 for v in ds): return None
    if sum(1 for i in range(1, 7) if ds[i] > ds[i - 1]) < 3: return None
    if any(ds[i] < ds[i - 1] for i in range(1, 7)): return None
    es = [per_share(cik, y, "eps") for y in yrs]
    if any(v is None for v in es): return None
    if sum(1 for i in range(1, 7) if es[i] > es[i - 1]) < 4: return None
    sh = FR["Shares"][F - 1].get(cik)
    if not sh or sh < 5e6: return None
    price = june_close(cik, F)
    if not price: return None
    ahy = avg_high_yield(cik, F)
    if ahy is None: return None
    cur_yield = ds[-1] / price
    if cur_yield < 0.9 * ahy: return None
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

passers = {}
for F in FORM_YEARS:
    res = {}
    for cik in px:
        cy = screen_pass(cik, F)
        if cy is not None: res[cik] = cy
    passers[F] = res
    print("formation", F, "passers", len(res), sorted(cik2ticker[c] for c in res), flush=True)

def cost_rate(cik, F):
    sh = FR["Shares"].get(F - 1, {}).get(cik) or FR["Shares"].get(F - 2, {}).get(cik)
    p = june_close(cik, F) or june_close(cik, F - 1)
    if not sh or not p: return 0.0075
    cap = sh * p * 1.0
    # shares are current-unit frames; cap approx uses raw frame shares x raw-ish price: use tier by cap
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

def build_events():
    held = {}; events = []
    for F in FORM_YEARS:
        for cik in list(held):
            d_prev = per_share(cik, F - 2, "dps"); d_cur = per_share(cik, F - 1, "dps")
            reason = None
            if d_cur is None or d_cur <= 0 or (d_prev is not None and d_cur < d_prev * (1 - 1e-9)):
                reason = "cut"
            else:
                ahy = avg_high_yield(cik, F); price = june_close(cik, F)
                if ahy and price and (d_cur / price) <= 0.5 * ahy: reason = "band"
            if reason: events.append((cik, held.pop(cik), F, reason))
        for c in passers[F]:
            if c not in held: held[c] = F
        if len(held) > CAP_N:
            ranked = sorted(held, key=lambda c: -((per_share(c, F - 1, "dps") or 0) / (june_close(c, F) or 1e18)))
            for c in ranked[CAP_N:]:
                e = held.pop(c)
                if e != F: events.append((c, e, F, "cap"))
    for cik, eF in held.items():
        events.append((cik, eF, 2026, "held_to_end"))
    return events

MONTHS = []
y, m = 2010, 1
while (y, m) <= (2026, 11):
    MONTHS.append(f"{y:04d}-{m:02d}"); m += 1
    if m == 13: y, m = y + 1, 1

def simulate(events, tape_of, rate_of):
    """events: (key, entry_F, exit_F). tape_of(key)->tape dict. rate_of(key,F)->cost rate."""
    ev_by_F = {}
    for k, eF, xF in events:
        ev_by_F.setdefault(eF, []).append(("buy", k))
        if xF <= 2025: ev_by_F.setdefault(xF, []).append(("sell", k))
    cash = 100.0; shares = {}; curve = {}; total_cost = 0.0; n_trades = 0
    for mm in MONTHS:
        y = int(mm[:4]); mo = int(mm[5:7])
        val = cash
        for k, n in shares.items():
            s = tape_of(k).get(mm)
            if s: val += n * s[0]
        curve[mm] = val
        if mo == 6 and y in ev_by_F:
            def curval(k):
                s = tape_of(k).get(mm)
                return shares.get(k, 0.0) * s[0] if s else 0.0
            for kind, k in ev_by_F[y]:
                if kind == "sell" and k in shares:
                    v = curval(k); r = rate_of(k, y)
                    total_cost += v * r; cash += v * (1 - r); del shares[k]; n_trades += 1
            total = cash + sum(curval(k) for k in shares)
            buys = [k for kd, k in ev_by_F[y] if kd == "buy"]
            book = list(shares) + [k for k in buys if k not in shares]
            if book and total > 0:
                tgt = total / len(book); rc = 0.0
                for k in book:
                    s = tape_of(k).get(mm)
                    if not s or not s[0]: continue
                    cur = curval(k); delta = tgt - cur; r = rate_of(k, y)
                    if abs(delta) > 1e-9:
                        total_cost += abs(delta) * r; rc += abs(delta) * r; n_trades += 1
                    newv = tgt - abs(delta) * r if delta != 0 else cur
                    shares[k] = max(newv, 0.0) / s[0]
                cash = total - rc - sum(curval(k) for k in shares)
        for k in list(shares):
            s = tape_of(k)
            if s and mm > max(s): del shares[k]
    return curve, round(total_cost, 2), n_trades

def period_stats(vals):
    v = np.array(vals, dtype=float)
    r = v[1:] / v[:-1] - 1; r = r[np.isfinite(r)]
    if len(r) == 0: return {}
    ls = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0; ls = max(ls, cur)
    peak = np.maximum.accumulate(v); below = v < peak - 1e-9
    lb = cur = 0
    for b in below:
        cur = cur + 1 if b else 0; lb = max(lb, cur)
    return {"n_periods": int(len(r)), "share_positive": round(float((r > 0).mean()), 3),
            "median_period": round(float(np.median(r)), 4), "mean_period_secondary": round(float(r.mean()), 4),
            "best": round(float(r.max()), 4), "worst": round(float(r.min()), 4),
            "longest_losing_streak": int(ls), "longest_below_high_months": int(lb),
            "max_dd": round(float((v / peak - 1).min()), 4)}

ROADS = {"LONG": ("2010-01", "2026-11"), "DECADE": ("2016-11", "2026-11"),
         "CONT": ("2019-01", "2026-11"), "VAL": ("2023-01", "2026-11")}
def road_slice(curve, road):
    a, b = ROADS[road]
    ms = [mm for mm in MONTHS if a <= mm <= b]
    vals = [curve[mm] for mm in ms]
    reb = [100.0 * v / vals[0] for v in vals]
    return round(reb[-1], 2), period_stats(reb), {mm: round(v, 4) for mm, v in zip(ms, reb)}

def main():
    events = build_events()
    print("events", [(cik2ticker[c], e, x, r) for c, e, x, r in events], flush=True)
    ev3 = [(c, e, x) for c, e, x, r in events]
    curve, cost, ntr = simulate(ev3, lambda c: px[c], cost_rate)
    pilot = {}
    pj = os.path.join(ROOT, "results.json")
    if os.path.exists(pj):
        try: pilot = json.load(open(pj))
        except Exception: pilot = {}
    out = {"spec": "v13 best-rules weiss RUN OF RECORD: accumulate + band/cut exit, cap20, annual re-eq, no floor",
           "pilot_w04_pond": pilot.get("roads", {}),
           "passers_by_formation": {F: sorted(cik2ticker[c] for c in passers[F]) for F in FORM_YEARS},
           "events": [{"ticker": cik2ticker[c], "entry": e, "exit": x, "exit_reason": r} for c, e, x, r in sorted(events, key=lambda z: (z[1], z[0]))],
           "total_cost": cost, "n_trades": ntr, "roads": {}, "placebos": {}, "spy_same_slice": {}, "folds": {}}
    for road in ROADS:
        f, st, cv = road_slice(curve, road)
        out["roads"][road] = {"final": f, "stats": st, "curve": cv}
        a, b = ROADS[road]
        ms = [mm for mm in MONTHS if a <= mm <= b and mm in spy]
        if len(ms) > 1: out["spy_same_slice"][road] = round(100.0 * spy[ms[-1]] / spy[ms[0]], 2)
        print(road, f, st, "spy", out["spy_same_slice"].get(road), flush=True)
    for road in ("LONG", "CONT"):
        beats = 0; finals = []
        for seed in range(20):
            rng = random.Random(seed)
            pev = []
            used = {}
            for c, e, x, r in events:
                pool = [t for t, tp in pool_tapes.items() if f"{e:04d}-06" in tp and t not in used.get(e, set())]
                if not pool: continue
                pick = rng.choice(pool); used.setdefault(e, set()).add(pick)
                pev.append((pick, e, x))
            pc, _, _ = simulate(pev, lambda t: pool_tapes[t], lambda t, F: 0.001)
            f, _, _ = road_slice(pc, road)
            finals.append(f)
            if out["roads"][road]["final"] > f: beats += 1
        out["placebos"][road] = {"beats": beats, "median_placebo": round(float(np.median(finals)), 2), "finals": finals}
        print("placebo", road, beats, out["placebos"][road]["median_placebo"], flush=True)
    for name, (a, b) in {"FOLD_2016_2020": ("2016-06", "2021-06"), "FOLD_2021_2025": ("2021-06", "2026-11"),
                         "LONG_H1": ("2010-01", "2018-06"), "LONG_H2": ("2018-06", "2026-11")}.items():
        ms = [mm for mm in MONTHS if a <= mm <= b]
        vals = [curve[mm] for mm in ms]
        reb = [100.0 * v / vals[0] for v in vals]
        out["folds"][name] = {"final": round(reb[-1], 2), "stats": period_stats(reb),
                              "spy": round(100.0 * spy[ms[-1]] / spy[ms[0]], 2) if ms[0] in spy and ms[-1] in spy else None}
    json.dump(out, open(pj, "w"), indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
