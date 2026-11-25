#!/usr/bin/env python3
"""TEST A - Options-income index scorecard (CBOE PUT & BXM).

No strategy simulation: the published CBOE index levels ARE the strategy.
Index daily returns are replayed onto $50 and $100 pots (a returns-replay,
not a trade simulation) and scored on Terry's standard scorecard, including
the FLOOR TEST with Terry's ladder:
  floor starts at 85% of start; rises to 100% of start once the pot closes
  at >=125% of start; rises to 125% of start once the pot closes at >=150%.
  A close at/below the floor = the pot would have been liquidated.

Data: CBOE free CDN daily index histories (PUT_History.csv, BXM_History.csv).
Benchmark: SPY from Yahoo chart API - price-only net of program costs
(0.10% buy + $0.01 sell, the program's "SPY buy-hold net") and total return
(adjclose, gross).
"""
import csv, io, json, math, urllib.request
from datetime import datetime

WIN_START = "2016-11-21"
WIN_END = "2026-11-20"

def load_cboe(path, col):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            d = datetime.strptime(r["DATE"], "%m/%d/%Y").strftime("%Y-%m-%d")
            rows.append((d, float(r[col])))
    rows.sort()
    return rows

def load_spy():
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/SPY"
           "?period1=0&period2=1800000000&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    data = json.load(urllib.request.urlopen(req, timeout=30))
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    close = res["indicators"]["quote"][0]["close"]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    px, tr = [], []
    for t, c, a in zip(ts, close, adj):
        if c is None:
            continue
        d = datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        px.append((d, c)); tr.append((d, a))
    return px, tr

def stats(series, start, end):
    """series: full [(date, level)] sorted. Window stats on closes within window."""
    win = [(d, v) for d, v in series if start <= d <= end]
    if len(win) < 2:
        return None
    v0, v1 = win[0][1], win[-1][1]
    years = (datetime.strptime(win[-1][0], "%Y-%m-%d") - datetime.strptime(win[0][0], "%Y-%m-%d")).days / 365.25
    total = v1 / v0 - 1
    cagr = (v1 / v0) ** (1 / years) - 1
    peak, maxdd = v0, 0.0
    for _, v in win:
        peak = max(peak, v)
        maxdd = min(maxdd, v / peak - 1)
    # calendar-year returns
    by_year = {}
    for d, v in win:
        by_year.setdefault(d[:4], []).append(v)
    # need prior Dec close for first year return: approximate with first close of window for year 1
    yr = {}
    prev_last = None
    all_years = {}
    for d, v in series:
        all_years[d[:4]] = v  # last close of year wins (sorted)
    yrs_sorted = sorted(all_years)
    for y in yrs_sorted:
        if y in by_year:
            base = all_years[str(int(y) - 1)] if str(int(y) - 1) in all_years else win[0][1]
            yr[y] = all_years[y] / base - 1
    best_y = max(yr.items(), key=lambda kv: kv[1])
    worst_y = min(yr.items(), key=lambda kv: kv[1])
    return dict(start_date=win[0][0], end_date=win[-1][0], total=total, cagr=cagr,
                maxdd=maxdd, best_year=best_y, worst_year=worst_y, years=yr)

def floor_test(series, start, end, pot0):
    """Replay index returns onto a pot; apply Terry's floor+ladder on closes."""
    win = [(d, v) for d, v in series if start <= d <= end]
    base = win[0][1]
    floor = 0.85 * pot0
    rung = 0
    breaches = 0
    first = None
    final = pot0
    for d, v in win:
        pot = pot0 * v / base
        final = pot
        # ladder upgrades on closes (checked before breach, rung only rises)
        if rung < 1 and pot >= 1.25 * pot0:
            floor = 1.00 * pot0; rung = 1
        if rung < 2 and pot >= 1.50 * pot0:
            floor = 1.25 * pot0; rung = 2
        if pot <= floor:
            breaches += 1
            if first is None:
                first = (d, round(pot, 2), round(floor, 2))
    return dict(final=final, breaches=breaches, first_breach=first, final_floor=floor)

def report(name, series, spy_px, spy_tr):
    out = [f"\n===== {name} ====="]
    out.append(f"Data range in file: {series[0][0]} -> {series[-1][0]} ({len(series)} rows)")
    for label, (s, e) in [("WINDOW 2016-11-21..2026-11-20", (WIN_START, WIN_END)),
                          ("FULL HISTORY", (series[0][0], series[-1][0]))]:
        st = stats(series, s, e)
        out.append(f"\n-- {label} ({st['start_date']} -> {st['end_date']})")
        out.append(f"  Total return {st['total']*100:+.1f}% | CAGR {st['cagr']*100:+.2f}% | MaxDD {st['maxdd']*100:.1f}%")
        out.append(f"  Best year {st['best_year'][0]} {st['best_year'][1]*100:+.1f}% | Worst year {st['worst_year'][0]} {st['worst_year'][1]*100:+.1f}%")
        for pot0 in (50, 100):
            ft = floor_test(series, s, e, pot0)
            out.append(f"  Pot ${pot0}: final ${ft['final']:.2f} | floor breaches (closes) = {ft['breaches']} | first = {ft['first_breach']} | end floor ${ft['final_floor']:.2f}")
    return "\n".join(out), st

put_raw = load_cboe("/tmp/PUT_hist.csv", "PUT")
# PUT CDN file has only a handful of stray pre-2007 rows (1991-2004); the daily
# series begins Jan 2007 (the index's live era). Use the daily-era series only.
put = [(d, v) for d, v in put_raw if d >= "2007-01-01"]
print(f"PUT stray pre-2007 rows dropped: {len(put_raw) - len(put)}")
bxm = load_cboe("/tmp/BXM_hist.csv", "BXM")
spy_px, spy_tr = load_spy()

print("SPY price rows:", spy_px[0][0], "->", spy_px[-1][0])
for name, series in [("PUT (CBOE PutWrite)", put), ("BXM (CBOE BuyWrite)", bxm)]:
    txt, _ = report(name, series, spy_px, spy_tr)
    print(txt)

for name, series in [("SPY price-only (gross)", spy_px), ("SPY total return (adjclose, gross)", spy_tr)]:
    st = stats(series, WIN_START, WIN_END)
    print(f"\n===== BENCH {name} window =====")
    print(f"  Total {st['total']*100:+.1f}% | CAGR {st['cagr']*100:+.2f}% | MaxDD {st['maxdd']*100:.1f}% | best {st['best_year']} | worst {st['worst_year']}")
    for pot0 in (50, 100):
        # net: buy cost 0.10% of pot + $0.01 sell at end
        net_final = pot0 * (1 + st['total']) * 0.999 - 0.01
        print(f"  Pot ${pot0}: gross final ${pot0*(1+st['total']):.2f} | net-of-program-costs ${net_final:.2f}")
    stf = stats(series, series[0][0], series[-1][0])
    print(f"  Full history in file ({series[0][0]}->): total {stf['total']*100:+.0f}% CAGR {stf['cagr']*100:+.2f}% MaxDD {stf['maxdd']*100:.1f}%")

# window per-year table for the two indexes
for name, series in [("PUT", put), ("BXM", bxm), ("SPY_px", spy_px), ("SPY_tr", spy_tr)]:
    st = stats(series, WIN_START, WIN_END)
    print(f"\n{name} window year returns:", {y: f"{r*100:+.1f}%" for y, r in sorted(st['years'].items())})
