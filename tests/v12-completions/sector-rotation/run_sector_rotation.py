#!/usr/bin/env python3
"""V12 sector-rotation — Faber (2010) Relative Strength Strategies for Investing,
frozen forms A (core Top-3 combination) and B (+ dynamic hedge), per
CONSTRUCTION-SPEC.md (frozen before this run). Monthly, 9 original Select
Sector SPDRs (Dec 1998 inception), Stooq adjusted daily closes, program costs
0.10%/side, cash 0%. $100 start per window. 20-seed placebos."""
import csv, io, json, math, pathlib, random, urllib.request
from datetime import date

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"; DATA.mkdir(exist_ok=True)
V2CACHE = pathlib.Path.home() / "workspace/stock-app/backtests/v2/tournament-data"
TICKERS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]
ALL = TICKERS + ["SPY"]
COST = 0.0010  # program standard, per side on traded value

def fetch_yahoo(sym):
    """Daily adjusted closes from Yahoo chart API (same source/convention as the
    program's v2/v3 caches). Stooq was tried first on 2026-11-22 and returned a
    bot-check page for every symbol; logged in HUNT-LOG/RESULTS."""
    p = DATA / f"{sym}.csv"
    if p.exists():
        return p.read_text()
    import datetime as _dt
    p1 = int(_dt.datetime(1998, 12, 1, tzinfo=_dt.timezone.utc).timestamp())
    p2 = int(_dt.datetime(2026, 11, 22, tzinfo=_dt.timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div,splits")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    payload = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    res = payload["chart"]["result"][0]
    ts = res["timestamp"]; adj = res["indicators"]["adjclose"][0]["adjclose"]
    lines = ["Date,Close"]
    for t, a in zip(ts, adj):
        if a is None:
            continue
        d = _dt.datetime.fromtimestamp(t, _dt.timezone.utc).date().isoformat()
        lines.append(f"{d},{a}")
    txt = "\n".join(lines) + "\n"
    p.write_text(txt)
    return txt

def month_ends(txt):
    """Return dict 'YYYY-MM' -> (last_date_str, close) from daily CSV text."""
    rows = list(csv.DictReader(io.StringIO(txt)))
    out = {}
    for r in rows:
        r = {k.lower(): v for k, v in r.items()}
        d = r["date"]; c = r["close"]
        if c in ("", "N/D", None):
            continue
        out[d[:7]] = (d, float(c))  # rows are chronological; last write wins
    return out

def load_all():
    me = {}
    for s in ALL:
        me[s] = month_ends(fetch_yahoo(s))
    months = sorted(set.intersection(*[set(me[s]) for s in ALL]))
    px = {s: [me[s][m][1] for m in months] for s in ALL}
    dates = [me["SPY"][m][0] for m in months]
    return months, dates, px

def data_audit(px, months):
    """Cross-check Stooq monthly returns vs read-only v2 Yahoo cache (2015+)."""
    out = {}
    for s in ["SPY", "XLK", "XLE"]:
        f = V2CACHE / f"{s}.csv"
        if not f.exists():
            continue
        yme = month_ends(f.read_text())
        diffs = []
        prev_s = prev_y = None
        for m in months:
            if m in yme and m >= "2015-02":
                sv = px[s][months.index(m)]; yv = yme[m][1]
                if prev_s:
                    diffs.append(abs(sv / prev_s - yv / prev_y))
                prev_s, prev_y = sv, yv
        if diffs:
            out[s] = {"n_months_compared": len(diffs),
                      "mean_abs_monthly_return_diff": round(sum(diffs) / len(diffs), 5),
                      "max_abs_monthly_return_diff": round(max(diffs), 5)}
    return out

def score(px_s, i):
    """Average of trailing 1,3,6,9,12-month returns at month index i."""
    if i < 12:
        return None
    return sum(px_s[i] / px_s[i - k] - 1.0 for k in (1, 3, 6, 9, 12)) / 5.0

def run_window(months, dates, px, start, end, form, rng=None):
    """Simulate months whose month-end date is in [start, end]. Signal set at
    each month-end, earns the following month. Returns dict with curve etc."""
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    if not idx:
        return None
    eq = 100.0; weights = {}; curve = []; costs = 0.0; trades = 0
    spy_i0 = idx[0]
    for pos, i in enumerate(idx):
        # signal at month-end i (needs 12 months history and SPY 10mo SMA)
        if form == "B":
            sma10 = sum(px["SPY"][i - 9:i + 1]) / 10.0
            hedged = px["SPY"][i] < sma10
        else:
            hedged = False
        if rng is not None:  # placebo: random 3, same hedge state
            picks = rng.sample(TICKERS, 3)
            target = {} if hedged else {t: 1 / 3 for t in picks}
        elif hedged:
            target = {}
        else:
            sc = {t: score(px[t], i) for t in TICKERS}
            top3 = sorted(TICKERS, key=lambda t: -sc[t])[:3]
            target = {t: 1 / 3 for t in top3}
        # trade at close i
        keys = set(weights) | set(target)
        traded = sum(abs(target.get(k, 0.0) - weights.get(k, 0.0)) for k in keys)
        if traded > 1e-9:
            ch = eq * COST * traded; eq -= ch; costs += ch; trades += 1
        weights = target
        # earn next month (i -> i+1) if within data
        if i + 1 < len(months):
            r = sum(w * (px[t][i + 1] / px[t][i] - 1.0) for t, w in weights.items())
            eq *= (1.0 + r)
            curve.append([dates[i + 1], round(eq, 4)])
    # SPY buy-hold over same span: from close at idx[0] to last curve date close
    last_i = months.index(curve[-1][0][:7]) if curve else idx[0]
    spy_final = 100.0 * px["SPY"][last_i] / px["SPY"][spy_i0] * (1 - COST)  # one entry cost
    # max drawdown on curve (incl. starting 100)
    peak = 100.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1.0)
    yrs = (date.fromisoformat(curve[-1][0]) - date.fromisoformat(dates[spy_i0])).days / 365.25 if curve else 0
    return {"start": dates[spy_i0], "end": curve[-1][0] if curve else dates[spy_i0],
            "final": round(eq, 2), "spy_buyhold": round(spy_final, 2),
            "cagr_pct": round(((eq / 100.0) ** (1 / yrs) - 1) * 100, 2) if yrs > 0 else None,
            "max_dd_pct": round(mdd * 100, 2), "rebalance_months": trades,
            "costs": round(costs, 2), "curve": curve}

WINDOWS = {
    "FULL":   ("1999-12-31", "2026-11-20"),
    "LONG":   ("2010-01-01", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-01", "2026-11-20"),
    "VAL":    ("2023-01-01", "2026-11-20"),
    "PRE2010": ("1999-12-31", "2009-12-31"),
}
CHAMPIONS = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_PROG = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

def main():
    months, dates, px = load_all()
    audit = data_audit(px, months)
    out = {"strategy": "Faber (2010) Relative Strength Strategies for Investing — SPDR implementation (CONSTRUCTED vehicle mapping)",
           "forms": {"A": "Top-3, score=avg of 1/3/6/9/12m total returns, monthly, always invested",
                     "B": "Form A + dynamic hedge: 100% cash (0%) while SPY month-end < 10mo SMA"},
           "universe": TICKERS, "cost_per_side": COST, "cash_return": 0.0,
           "data": "Yahoo chart API daily adjusted closes (adjclose), month-end — same source as program v2/v3 caches; Stooq bot-blocked 2026-11-22; SPDR inception Dec 1998 respected (XLRE 2015 / XLC 2018 excluded)",
           "data_audit_vs_v2_yahoo_cache": audit,
           "first_month": months[0], "last_month": months[-1],
           "champions_vm": CHAMPIONS, "spy_program_refs": SPY_PROG, "forms_results": {}}
    for form in ("A", "B"):
        fr = {}
        for wname, (s, e) in WINDOWS.items():
            r = run_window(months, dates, px, s, e, form)
            pls = []
            for seed in range(20):
                rng = random.Random(1000 + seed)
                pr = run_window(months, dates, px, s, e, form, rng=rng)
                pls.append(pr["final"])
            r["placebo_finals"] = pls
            r["placebo_beaten"] = sum(1 for p in pls if r["final"] > p)
            fr[wname] = r
            print(form, wname, r["final"], "SPY", r["spy_buyhold"], "DD", r["max_dd_pct"],
                  "placebo", r["placebo_beaten"], "/20")
        # per-year folds (confirmation material)
        folds = {}
        for y in range(2000, 2027):
            r = run_window(months, dates, px, f"{y}-01-01", f"{y}-12-31", form)
            if r:
                folds[str(y)] = {"final": r["final"], "spy_buyhold": r["spy_buyhold"]}
        fr["year_folds"] = folds
        out["forms_results"][form] = fr
    (HERE / "results.json").write_text(json.dumps(out, indent=1))
    print("audit:", audit)
    print("wrote results.json")

if __name__ == "__main__":
    main()
