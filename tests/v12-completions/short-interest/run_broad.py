#!/usr/bin/env python3
"""
Short Interest Form A-broad (v12 CONSTRUCTED-broad) + Form B diagnostic.
Implements CONSTRUCTION-SPEC.md exactly as frozen. Simulation only.

Universe: S&P 500 PIT membership (program sp500_pit.csv).
Signal: FINRA mid-month settlement short shares / EDGAR frames prior
year-end shares outstanding, formation at month-end close (settlement
published 7th business day after settlement, i.e. before month-end).
Picks: 30 least-shorted, equal weight, monthly full rebalance at the
adjusted close. Costs 0.10%/side + $0.01/sell order. Plain -15% floor
checked at monthly marks only. Held name with a vanished price = ZERO.
"""
import csv, json, os, random, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); os.makedirs(DATA, exist_ok=True)
PIT = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/gap-a9-frog-pan/data/sp500_pit.csv")
FINRA_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v6/short-interest/finra-cache")
FRAMES = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/frames")
TICKERS_JSON = os.path.expanduser("~/workspace/stock-app/backtests/v4/data/company_tickers.json")

START_CASH = 100.0; FLOOR = 85.0; N_PICKS = 30
COST_RATE = 0.001; SELL_FEE = 0.01

def ym_add(ym, n):
    y, m = int(ym[:4]), int(ym[5:7]); m += n
    while m > 12: m -= 12; y += 1
    while m < 1: m += 12; y -= 1
    return f"{y:04d}-{m:02d}"

FORMATIONS = []
ym = "2018-12"
while ym <= "2026-09":
    FORMATIONS.append(ym); ym = ym_add(ym, 1)
FINAL_MONTH = "2026-10"

# ---------- PIT membership ----------
pit_rows = []
with open(PIT) as f:
    for r in csv.DictReader(f):
        pit_rows.append((r["date"], r["tickers"].split(",")))
pit_rows.sort()
def membership(ym):
    target = ym + "-31"
    best = None
    for d, tk in pit_rows:
        if d <= target: best = tk
        else: break
    return list(best) if best else []

ALL_TICKERS = sorted({t for fm in FORMATIONS for t in membership(fm)})
print(f"formations {FORMATIONS[0]}..{FORMATIONS[-1]} n={len(FORMATIONS)} distinct tickers={len(ALL_TICKERS)}", flush=True)

# ---------- prices (Yahoo monthly adjclose) ----------
def fetch_px(ticker):
    path = os.path.join(DATA, f"px_{ticker.replace('/','-')}.json")
    if os.path.exists(path):
        return ticker, json.load(open(path))
    ysym = ticker.replace(".", "-")
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}"
           f"?period1=1543622400&period2=1798761600&interval=1mo&events=div,split")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            d = json.load(urllib.request.urlopen(req, timeout=30))
            res = d["chart"]["result"][0]
            ts = res["timestamp"]; adj = res["indicators"]["adjclose"][0]["adjclose"]
            out = {}
            for t_, a in zip(ts, adj):
                if a is None: continue
                k = datetime.fromtimestamp(t_, tz=timezone.utc).strftime("%Y-%m")
                out[k] = a
            json.dump(out, open(path, "w"))
            return ticker, out
        except Exception as e:
            if attempt == 2:
                json.dump({}, open(path, "w")); return ticker, {}
            time.sleep(2 * (attempt + 1))

PX = {}
with ThreadPoolExecutor(max_workers=16) as ex:
    for t, px in ex.map(fetch_px, ALL_TICKERS + ["SPY"]):
        PX[t] = px
n_px = sum(1 for t in ALL_TICKERS if PX.get(t))
print(f"price series obtained: {n_px}/{len(ALL_TICKERS)}; SPY months={len(PX.get('SPY',{}))}", flush=True)

# ---------- CIK + shares frames ----------
ct = json.load(open(TICKERS_JSON))
T2CIK = {v["ticker"]: v["cik_str"] for v in ct.values()}
T2CIK["FB"] = 1326801  # Meta filed as FB until Jun 2022 (v6 record)
shares_cache = {}
def shares_frame(year):
    if year not in shares_cache:
        p = os.path.join(FRAMES, f"Shares_{year}I.json")
        shares_cache[year] = {int(k): v for k, v in json.load(open(p)).items()} if os.path.exists(p) else {}
    return shares_cache[year]

# ---------- FINRA mid-month settlements ----------
finra_files = {}
for fn in os.listdir(FINRA_DIR):
    if fn.startswith("shrt") and fn.endswith(".csv"):
        d = fn[4:12]; key = f"{d[:4]}-{d[4:6]}"
        day = int(d[6:8])
        if day <= 16:  # mid-month settlement (the other file is month-end)
            finra_files[key] = (f"{d[:4]}-{d[4:6]}-{d[6:8]}", os.path.join(FINRA_DIR, fn))
def finra_symbol(t, settlement):
    if t == "META" and settlement < "2022-06-10": return "FB"
    return t.replace(".", "")
def finra_rows(ym):
    settlement, path = finra_files[ym]
    wanted = {}
    for t in ALL_TICKERS:
        wanted.setdefault(finra_symbol(t, settlement), []).append(t)
    out = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f, delimiter="|"):
            sym = row["symbolCode"]
            if sym in wanted:
                for t in wanted[sym]:
                    out[t] = float(row["currentShortPositionQuantity"])
    return settlement, out

# ---------- scored pool per formation ----------
def scored_pool(ym):
    settlement, rows = finra_rows(ym)
    sh = shares_frame(int(settlement[:4]) - 1)
    pool = {}
    counts = {"members": 0, "no_finra": 0, "no_shares": 0, "no_price": 0}
    for t in membership(ym):
        counts["members"] += 1
        if t not in rows: counts["no_finra"] += 1; continue
        cik = T2CIK.get(t); so = sh.get(cik) if cik else None
        if not so or so <= 0: counts["no_shares"] += 1; continue
        if ym not in PX.get(t, {}): counts["no_price"] += 1; continue
        pool[t] = rows[t] / so
    return pool, settlement, counts

POOLS = {}
for fm in FORMATIONS:
    POOLS[fm] = scored_pool(fm)
    p, s, c = POOLS[fm]
    print(f"pool {fm} settle={s} scored={len(p)} {c}", flush=True)

# ---------- engine ----------
def run_pot(formations, seed=None):
    cash = START_CASH; positions = {}; curve = []; total_costs = 0.0; orders = 0
    halted = None; picks_log = []
    months = formations + [FINAL_MONTH]
    for i, fm in enumerate(formations):
        pool, settlement, _ = POOLS[fm]
        if seed is None:
            picks = sorted(pool, key=lambda t: (pool[t], t))[:N_PICKS]
        else:
            rng = random.Random(seed * 10000 + i)
            picks = rng.sample(sorted(pool), N_PICKS)
        picks_log.append({"formation": fm, "settlement": settlement,
                          "n_scored": len(pool), "picks": picks,
                          "pick_ratios_pct": [round(pool[t] * 100, 3) for t in picks]})
        # liquidate current at close fm
        for t, sh in list(positions.items()):
            p = PX.get(t, {}).get(fm)
            val = 0.0 if p is None else sh * p
            c = val * COST_RATE + SELL_FEE if val > 0 else 0.0
            cash += val - c; total_costs += c; orders += 1
        positions = {}
        # buy picks equal weight at close fm
        each = cash / len(picks)
        for t in picks:
            p = PX[t][fm]; c = each * COST_RATE; total_costs += c; orders += 1
            positions[t] = (each - c) / p
        cash = 0.0
        # mark at next month close
        nxt = months[i + 1]
        val = sum(sh * (PX.get(t, {}).get(nxt) or 0.0) for t, sh in positions.items())
        curve.append([nxt, round(val, 2)])
        if val <= FLOOR and nxt != FINAL_MONTH:
            halted = nxt
            tc = 0.0
            for t, sh in list(positions.items()):
                p = PX.get(t, {}).get(nxt); v = 0.0 if p is None else sh * p
                cc = v * COST_RATE + SELL_FEE if v > 0 else 0.0
                tc += cc; orders += 1
            total_costs += tc; cash = val - tc; positions = {}
            curve[-1] = [nxt, round(cash, 2)]
            break
    if positions:
        val = sum(sh * (PX.get(t, {}).get(FINAL_MONTH) or 0.0) for t, sh in positions.items())
        tc = 0.0
        for t, sh in positions.items():
            p = PX.get(t, {}).get(FINAL_MONTH); v = 0.0 if p is None else sh * p
            tc += (v * COST_RATE + SELL_FEE) if v > 0 else 0.0
        total_costs += tc; cash = val - tc
    peak = START_CASH; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak > 0 else 0.0
    return {"final": round(cash, 2), "costs": round(total_costs, 2), "orders": orders,
            "max_dd_pct": round(maxdd * 100, 2), "halted": halted,
            "worst_close": min((v for _, v in curve), default=None),
            "curve": curve, "picks_log": picks_log}

def spy_buyhold(start_ym, end_ym):
    a = PX["SPY"].get(start_ym); b = PX["SPY"].get(end_ym)
    return round(100.0 * b / a, 2) if a and b else None

# ---------- Form B diagnostic ----------
def diagnostic(formations):
    rows = []
    for fm in formations:
        pool, settlement, _ = POOLS[fm]
        nxt = ym_add(fm, 1)
        by = sorted(pool, key=lambda t: (pool[t], t))
        least, most = by[:N_PICKS], by[-N_PICKS:]
        tail = [t for t in by if pool[t] >= 0.025]
        def gret(names):
            rs = []
            for t in names:
                p0 = PX.get(t, {}).get(fm); p1 = PX.get(t, {}).get(nxt)
                if p0 and p1: rs.append(p1 / p0 - 1.0)
            return (sum(rs) / len(rs) * 100) if rs else None, len(rs)
        lr, _ = gret(least); mr, _ = gret(most); tr, tn = gret(tail); ar, _ = gret(by)
        s0, s1 = PX["SPY"].get(fm), PX["SPY"].get(nxt)
        sr = (s1 / s0 - 1.0) * 100 if s0 and s1 else None
        rows.append({"formation": fm, "settlement": settlement, "n_scored": len(pool),
                     "least_ret_pct": round(lr, 2) if lr is not None else None,
                     "most_ret_pct": round(mr, 2) if mr is not None else None,
                     "spread_pct": round(lr - mr, 2) if (lr is not None and mr is not None) else None,
                     "tail_ge2p5_n": tn, "tail_ret_pct": round(tr, 2) if tr is not None else None,
                     "all_ret_pct": round(ar, 2) if ar is not None else None,
                     "spy_ret_pct": round(sr, 2) if sr is not None else None})
    ok = [r for r in rows if r["spread_pct"] is not None]
    sp = sorted(r["spread_pct"] for r in ok)
    agg = {"n_months": len(ok),
           "mean_spread_pct": round(sum(sp) / len(sp), 3) if sp else None,
           "median_spread_pct": round(sp[len(sp) // 2], 3) if sp else None,
           "pct_months_spread_positive": round(100.0 * sum(1 for s in sp if s > 0) / len(sp), 1) if sp else None,
           "mean_least_ret_pct": round(sum(r["least_ret_pct"] for r in ok) / len(ok), 3),
           "mean_most_ret_pct": round(sum(r["most_ret_pct"] for r in ok) / len(ok), 3),
           "mean_tail_ge2p5_ret_pct": round(sum(r["tail_ret_pct"] for r in ok if r["tail_ret_pct"] is not None) / max(1, sum(1 for r in ok if r["tail_ret_pct"] is not None)), 3),
           "mean_tail_n": round(sum(r["tail_ge2p5_n"] for r in ok) / len(ok), 1),
           "mean_all_ret_pct": round(sum(r["all_ret_pct"] for r in ok) / len(ok), 3),
           "mean_spy_ret_pct": round(sum(r["spy_ret_pct"] for r in ok) / len(ok), 3)}
    return {"rows": rows, "aggregate": agg}

# ---------- roads ----------
def road(formations, tag):
    r = run_pot(formations)
    finals = []
    for seed in range(1, 21):
        rp = run_pot(formations, seed=seed)
        finals.append(rp["final"])
        print(f"  [{tag}] placebo {seed}: ${rp['final']:,.2f}", flush=True)
    beats = sum(1 for v in finals if r["final"] > v)
    sf = sorted(finals)
    return {"formations": [formations[0], formations[-1]], "ranked": r,
            "spy_buyhold": spy_buyhold(formations[0], FINAL_MONTH),
            "placebo_finals": finals, "placebo_median": round(sf[len(sf)//2], 2),
            "placebo_beaten": beats}

FULL = FORMATIONS
VAL = [f for f in FORMATIONS if f >= "2022-12"]
out = {"family": "short-interest", "form": "Form A-broad CONSTRUCTED-broad (30 least-shorted, S&P500 PIT, monthly)",
       "universe_distinct_tickers": len(ALL_TICKERS),
       "price_series_obtained": n_px,
       "pool_sizes": {fm: len(POOLS[fm][0]) for fm in FORMATIONS},
       "roads": {}, "diagnostic_FULL": diagnostic(FULL), "diagnostic_VAL": diagnostic(VAL)}
for tag, fs in (("FULL", FULL), ("VAL", VAL)):
    print(f"== ROAD {tag} ==", flush=True)
    out["roads"][tag] = road(fs, tag)
    rr = out["roads"][tag]
    print(f"== {tag}: ranked ${rr['ranked']['final']:,.2f} SPY ${rr['spy_buyhold']:,.2f} "
          f"placebo {rr['placebo_beaten']}/20 median ${rr['placebo_median']:,.2f} "
          f"maxDD {rr['ranked']['max_dd_pct']}% halted={rr['ranked']['halted']}", flush=True)
print("DIAG FULL:", out["diagnostic_FULL"]["aggregate"], flush=True)
print("DIAG VAL:", out["diagnostic_VAL"]["aggregate"], flush=True)
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("DONE", flush=True)
