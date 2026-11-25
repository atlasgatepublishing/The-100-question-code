#!/usr/bin/env python3
"""
GAP-A9 FROG-IN-THE-PAN — V12 CONSTRUCTED RUN. Simulation only.
Rules frozen in CONSTRUCTION-SPEC.md. Memory-light data layer: each
ticker is streamed once into compact aligned arrays (array('d')) on the
SPY master calendar, raw bars discarded.
Output: per-window JSON printed on stdout as RESULTJSON_<WINDOW>:...
(captured by the driver via shell redirection), plus human log lines.
"""
import csv, gzip, json, os, random, sys
from array import array
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SHARED = os.path.expanduser("~/workspace/stock-app/backtests/v4/data")
POT = 100.0
COST = 0.001
SELL_FEE = 0.01
FLOOR = 85.0
NHOLD = 30
NAN = float("nan")

# ---------------- membership ----------------
def load_pit():
    rows = []
    with open(os.path.join(DATA, "sp500_pit.csv")) as f:
        for r in csv.DictReader(f):
            rows.append((r["date"], set(t.strip() for t in r["tickers"].split(",") if t.strip())))
    rows.sort()
    return rows

PIT = load_pit()
def members_on(date):
    lo, hi, ans = 0, len(PIT) - 1, PIT[0][1]
    while lo <= hi:
        mid = (lo + hi) // 2
        if PIT[mid][0] <= date:
            ans = PIT[mid][1]; lo = mid + 1
        else:
            hi = mid - 1
    return ans

# ---------------- calendar ----------------
_spy_rows = json.load(open(os.path.join(DATA, "yahoo", "SPY.json")))
CAL = [r["d"] for r in _spy_rows]
CIDX = {d: i for i, d in enumerate(CAL)}
N = len(CAL)
del _spy_rows

# ---------------- aligned arrays ----------------
# AL[t] = (close_ff array('d') with NAN before first bar, open_ff array('d'),
#          last_traded_idx array('i') per calendar idx, first_idx, last_idx)
AL = {}
def build(t, bars):
    """bars: {date: (open, close)} raw (not adjusted beyond source basis)."""
    close = array("d", [NAN]) * 1
    close = array("d", [NAN for _ in range(N)])
    opn = array("d", [NAN for _ in range(N)])
    lt = array("i", [-1]) * 1
    lt = array("i", [-1 for _ in range(N)])
    last = -1; lastc = NAN; lasto = NAN; first = None
    for i, d in enumerate(CAL):
        b = bars.get(d)
        if b is not None:
            lasto, lastc = b[0], b[1]; last = i
            if first is None: first = i
        close[i] = lastc; opn[i] = lasto; lt[i] = last
    if first is None:
        return
    AL[t] = (close, opn, lt, first, last)

def load_all():
    # Layer 2: Yahoo, one file at a time
    ydir = os.path.join(DATA, "yahoo")
    for fn in sorted(os.listdir(ydir)):
        if not fn.endswith(".json"):
            continue
        t = fn[:-5]
        if t == "SPY":
            continue
        rows = json.load(open(os.path.join(ydir, fn)))
        build(t, {r["d"]: (r["o"], r["c"]) for r in rows})
        del rows
    # Layer 1: Tiingo panel (parquet) + tier1 gz — takes precedence
    sys.path.insert(0, os.path.expanduser("~/workspace/.pylibs"))
    import pyarrow.parquet as pq
    df = pq.read_table(os.path.join(DATA, "bars_panel.parquet")).to_pandas()
    recs = {}
    for t, d, o, c, sf in zip(df["ticker"], df["date"], df["open"], df["close"], df["splitFactor"]):
        recs.setdefault(t, []).append((d.strftime("%Y-%m-%d"), float(o), float(c), float(sf or 1.0)))
    del df
    with gzip.open(os.path.join(DATA, "tiingo_tier1.csv.gz"), "rt") as f:
        for r in csv.DictReader(f):
            t = r["ticker"]
            if t in recs:
                continue
            recs.setdefault(t, []).append((r["date"][:10], float(r["open"]), float(r["close"]), float(r["splitFactor"] or 1.0)))
    panel_tickers = set(recs)
    for t, rows in recs.items():
        rows.sort()
        adj = {}
        cum = 1.0
        for d, o, c, sf in reversed(rows):
            adj[d] = (o / cum, c / cum)
            cum *= sf
        build(t, adj)
        del adj
    del recs
    return panel_tickers

PANEL_TICKERS = load_all()
print(f"aligned tickers: {len(AL)} (panel layer: {len(PANEL_TICKERS)})", flush=True)

# ---------------- signals ----------------
_elig_cache = {}
def eligible(j, members):
    out = []
    for t in members:
        a = AL.get(t)
        if a is None:
            continue
        close, _, lt, first, _ = a
        if first > j - 252:
            continue
        if j - lt[j] > 5:
            continue
        c0, c1 = close[j - 252], close[j - 21]
        if c0 != c0 or c1 != c1 or c0 <= 0:
            continue
        mom = c1 / c0 - 1.0
        if mom <= 0:
            continue
        up = dn = 0
        prev = c0
        for k in range(j - 251, j - 20):
            cur = close[k]
            if cur == cur and prev == prev:
                if cur > prev: up += 1
                elif cur < prev: dn += 1
            if cur == cur:
                prev = cur
        out.append((t, (dn - up) / 231.0, mom))
    return out

def eligible_cached(j):
    if j not in _elig_cache:
        _elig_cache[j] = eligible(j, members_on(CAL[j]))
    return _elig_cache[j]

# ---------------- engine ----------------
def run_window(start_d, end_d, mode="strategy", seed=0):
    i0 = next(i for i, d in enumerate(CAL) if d >= start_d)
    i1 = max(i for i, d in enumerate(CAL) if d <= end_d)
    cash = POT; pos = {}
    curve = []; costs = 0.0; orders = 0; writeoffs = []
    rng = random.Random(seed)
    rebal = set(); seen = set()
    for i in range(i0, i1 + 1):
        m = CAL[i][:7]
        if m not in seen:
            seen.add(m); rebal.add(i)
    def px_open(t, i):
        _, opn, lt, _, _ = AL[t]
        l = lt[i]
        if l < 0 or i - l > 10:
            return None
        return opn[l] if l == i else AL[t][0][l]
    def equity(i):
        v = cash
        for t, sh in pos.items():
            close, _, lt, _, _ = AL[t]
            if i - lt[i] > 20:
                continue
            v += sh * close[i]
        return v
    halted = False
    for i in range(i0, i1 + 1):
        if i in rebal:
            j = i - 1
            if j >= 252:
                elig = eligible_cached(j)
                if mode == "strategy":
                    elig_s = sorted(elig, key=lambda x: (x[1], -x[2], x[0]))
                    picks = [e[0] for e in elig_s[:NHOLD]]
                else:
                    pool = sorted(e[0] for e in elig)  # sorted: deterministic across processes
                    picks = rng.sample(pool, min(NHOLD, len(pool))) if pool else []
                eq = equity(i)
                target_val = eq / NHOLD
                for t, sh in list(pos.items()):
                    if t not in picks:
                        p = px_open(t, i)
                        if p is None:
                            lt_i = AL[t][2][i]
                            ref = AL[t][0][lt_i] if lt_i >= 0 else 0.0
                            writeoffs.append((CAL[i], t, round(sh * ref, 2)))
                        else:
                            amt = sh * p; cst = amt * COST + SELL_FEE
                            cash += amt - cst; costs += cst; orders += 1
                        del pos[t]
                for t in picks:
                    p = px_open(t, i)
                    if p is None or p <= 0:
                        continue
                    cur = pos.get(t, 0.0) * p
                    diff = target_val - cur
                    if abs(diff) < 0.01:
                        continue
                    if diff > 0:
                        buy = min(diff, cash - diff * COST)
                        if buy <= 0: continue
                        pos[t] = pos.get(t, 0.0) + buy / p
                        cash -= buy + buy * COST; costs += buy * COST; orders += 1
                    else:
                        amt = -diff; cst = amt * COST + SELL_FEE
                        pos[t] = pos.get(t, 0.0) - amt / p
                        cash += amt - cst; costs += cst; orders += 1
                        if pos[t] <= 1e-9: del pos[t]
        eq = equity(i)
        curve.append((CAL[i], round(eq, 2)))
        if eq <= FLOOR and i < i1:
            ni = i + 1
            for t, sh in list(pos.items()):
                p = px_open(t, ni)
                if p is None:
                    lt_i = AL[t][2][ni]
                    ref = AL[t][0][lt_i] if lt_i >= 0 else 0.0
                    writeoffs.append((CAL[ni], t, round(sh * ref, 2)))
                else:
                    amt = sh * p; cst = amt * COST + SELL_FEE
                    cash += amt - cst; costs += cst; orders += 1
                del pos[t]
            curve.append((CAL[ni], round(cash, 2)))
            halted = True
            break
    final = curve[-1][1]
    peak = POT; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1.0)
    yrs = (datetime.strptime(curve[-1][0], "%Y-%m-%d") - datetime.strptime(curve[0][0], "%Y-%m-%d")).days / 365.25
    return dict(final=round(final, 2),
                cagr_pct=round(((final / POT) ** (1 / yrs) - 1) * 100, 2) if yrs > 0 and final > 0 else None,
                max_dd_pct=round(mdd * 100, 2), costs=round(costs, 2), orders=orders,
                halted=halted, end=curve[-1][0], writeoffs=writeoffs, curve=curve)

# ---------------- SPY canonical ----------------
def load_spy_canonical():
    with open(os.path.join(SHARED, "px_SPY.json"), "rb") as f:
        jj = json.loads(f.read())
    res = jj["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = {}
    for i, t in enumerate(ts):
        d = datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        o, c = q["open"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars[d] = ((o * ratio) if o else a, a)
    return bars
SPY_CANON = load_spy_canonical()
def spy_net(start_d, end_d):
    days = sorted(d for d in SPY_CANON if start_d <= d <= end_d)
    first, last = days[0], days[-1]
    sh = (POT / 1.001) / SPY_CANON[first][0]
    val = sh * SPY_CANON[last][1]
    return round(val - (val * COST + SELL_FEE), 2)

def monthly_stats(curve):
    by_month = {}
    for d, v in curve:
        by_month[d[:7]] = v
    months = sorted(by_month)
    rets = []; prev = POT
    for m in months:
        v = by_month[m]
        rets.append((m, v / prev - 1.0)); prev = v
    if not rets:
        return {}
    vals = sorted(r for _, r in rets)
    n = len(vals)
    med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    win = sum(1 for r in vals if r > 0)
    streak = mx = 0
    for _, r in rets:
        streak = streak + 1 if r <= 0 else 0
        mx = max(mx, streak)
    peak = POT; since = 0; longest = 0
    for m in months:
        v = by_month[m]
        if v > peak:
            peak = v; longest = max(longest, since); since = 0
        else:
            since += 1
    longest = max(longest, since)
    return dict(periods=n, winning=win, win_share_pct=round(100 * win / n, 1),
                median_pct=round(med * 100, 2),
                best_pct=round(max(vals) * 100, 2), worst_pct=round(min(vals) * 100, 2),
                longest_losing_streak=mx, longest_months_between_highs=longest,
                average_pct_secondary=round(sum(vals) / n * 100, 2),
                monthly_returns=[[m, round(r * 100, 2)] for m, r in rets])

WINDOWS = {
    "LONG": ("2010-01-01", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT": ("2019-01-01", "2026-11-20"),
    "VAL": ("2023-01-01", "2026-11-20"),
}

def main():
    j0 = next(i for i, d in enumerate(CAL) if d >= "2010-01-01") - 1
    mem0 = members_on(CAL[j0])
    have = sum(1 for t in mem0 if t in AL and AL[t][3] <= j0 - 252)
    withb = sum(1 for t in mem0 if t in AL)
    coverage = dict(pit_members_at_long_start=len(mem0), with_any_bars=withb,
                    with_computable_window=have, share_pct=round(100 * have / len(mem0), 1),
                    aligned_tickers=len(AL), panel_tickers=len(PANEL_TICKERS))
    print("COVERAGEJSON:" + json.dumps(coverage), flush=True)
    run_long = have / len(mem0) >= 0.70
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for wname, (sd, ed) in WINDOWS.items():
        if only and wname != only:
            continue
        if wname == "LONG" and not run_long:
            r = {"status": "NOT RUN — coverage below frozen 70% threshold",
                 "coverage_share_pct": coverage["share_pct"]}
            print(f"RESULTJSON_{wname}:" + json.dumps(r), flush=True)
            continue
        print(f"== {wname} strategy", flush=True)
        r = run_window(sd, ed, "strategy")
        curve = r.pop("curve")
        r["monthly_stats"] = monthly_stats(curve)
        r["spy_net"] = spy_net(sd, r["end"])
        print(f"   final {r['final']} spy {r['spy_net']} dd {r['max_dd_pct']} halted {r['halted']} writeoffs {len(r['writeoffs'])}", flush=True)
        pfin = []
        for s in range(1, 21):
            pfin.append(run_window(sd, ed, "placebo", seed=s)["final"])
        r["placebo_finals"] = pfin
        r["placebo_beaten"] = sum(1 for x in pfin if r["final"] > x)
        r["equity_curve_weekly_sample"] = curve[::5] + [curve[-1]]
        js = json.dumps(r)
        if os.environ.get("FROG_CHUNKS"):
            for k in range(0, len(js), 5000):
                print(f"CHUNK_{wname}_{k // 5000}:{js[k:k + 5000]}", flush=True)
        else:
            print(f"RESULTJSON_{wname}:" + js, flush=True)
        print(f"== {wname} done", flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
