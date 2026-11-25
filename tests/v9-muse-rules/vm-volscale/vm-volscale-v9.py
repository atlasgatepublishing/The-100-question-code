#!/usr/bin/env python3
"""
VALUE + MOMENTUM (HONEST) + BARROSO & SANTA-CLARA VOLATILITY SCALING
(scale-down-only) — Terry's AI stock app. Simulation only.

ONE pre-published variant of the promoted value+momentum spec, run once,
no tuning. The engine below is value-momentum-plainfloor.py copied
verbatim (honest point-in-time top-30 universe as of Nov 2016, quarterly
top-5 by book-to-market + 12-1 momentum percentile-rank average, equal
weight, $100 pot, costs 0.10%/side + $0.01/sell, plain -15% floor at
$85, point-in-time EDGAR with the ~18-month filed-freshness gate, XOM
CIK override 34088). The ONLY strategy change:

  At each quarterly selection, after the top-5 picks are made (ranked
  or placebo — the rule is identical for both), the invested fraction
  of the pot is scaled by

      w = min(1, 0.12 / sigma_ann)

  where sigma_ann is the trailing realized volatility of an equal-weight
  portfolio of the five picks, estimated from their daily adjusted
  closes over the prior 126 trading days (~6 months) ending on the
  selection date, annualized by sqrt(252). Targets become w * pot/5
  per pick; the uninvested fraction (1 - w) of the pot stays in cash
  until the next quarterly selection. The -15% floor check is unchanged
  (it applies to total equity, cash included).

Published source: Barroso & Santa-Clara, "Momentum Has Its Moments,"
Journal of Financial Economics 116(1), 2015 — target vol 12%/yr,
realized vol of the momentum portfolio over the prior 6 months,
weights 0.13-2.00 in their long-short decile implementation.
Surveyed in ~/workspace/stock-app/research/v5/crash-protection.md
(candidate 1), including the Cederburg et al. (2020) rebuttal and the
warning that this program's two prior long-only vol-scaling trials
(Disciplined v3; vol-scaled crypto trend) both disappointed.

ADAPTATIONS FROM THE PUBLISHED METHOD (all documented, none tuned):
  1. SCALE-DOWN ONLY: B&SC lever up to 2.00x in calm periods. Terry's
     pot is long-only cash with no leverage, so w is capped at 1.0.
     This keeps the crash-protection half of the method and forfeits
     the calm-period boost, exactly as the survey prescribes.
  2. QUARTERLY, NOT MONTHLY: B&SC re-scale monthly. Terry's engine
     rebalances quarterly, so the weight is set at the quarterly
     selection and held for the quarter. A March-2020-style crash
     inside a quarter is only met at the next selection date.
  3. VOL OF THE NEW PICKS, NOT OF THE STRATEGY'S OWN RETURN SERIES:
     B&SC estimate realized vol from the momentum strategy's realized
     returns over the prior 6 months. With quarterly top-5
     re-formation, the direct point-in-time substitute used here is
     the trailing 126-trading-day volatility of an equal-weight
     portfolio of the five stocks about to be held (daily-rebalanced
     measurement, sample stdev, ddof=1). This also avoids the
     feedback loop in which last quarter's cash holding would damp
     the measured vol and push the weight back up. It uses only
     closes on or before the selection date (no lookahead).
  4. LONG-ONLY 5-STOCK BOOK, NOT A LONG-SHORT DECILE BOOK: the crash
     B&SC tame lives mostly in the short leg; a concentrated 5-stock
     book also has a much higher baseline vol than a diversified
     decile portfolio, so a 12% target binds far more often here
     (the book sits partially in cash in ordinary times, not just
     in crises). That is the published target applied as-is, not
     re-calibrated — re-calibrating it would be tuning.
  5. FALLBACK: if fewer than 60 usable daily returns exist in the
     trailing window (not expected — momentum scoring already
     requires 253 bars of history), w = 1.0 for that quarter.

RUN MATRIX ($100 pots only — the promoted spec's judged size):
  - Replication: volscale OFF, ranked, continuous + validation
    (must reproduce the baseline $544.47 / $288.05 exactly).
  - Ranked, volscale ON: continuous 2019-01-02 -> 2026-11-20 and
    validation 2023-01-03 -> 2026-11-20.
  - Placebo, volscale ON: 20 seeds (1..20, same PLACEBO_SEEDS and
    the same rng.sample draw as the baseline engine), both windows;
    placebo pots receive the identical scaling rule applied to their
    own random picks.
  - Walk-forward folds, volscale ON: fresh $100 pot each calendar
    year 2020-2026 (2026 ends 2026-11-20), scored vs SPY net, same
    fold construction as vm-walkforward.py.

Data: the baseline test's caches, reused READ-ONLY from the v4 folder
(SEC EDGAR companyfacts in ../v4/data, Yahoo prices in
../v4/value-momentum-honest-data). Nothing is fetched or written
outside this folder.
"""
import json, math, os, random, sys, time, urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
SHARED = os.path.join(V4, "data")                    # v4 cache, read-only
DATA = os.path.join(V4, "value-momentum-honest-data")  # v4 honest cache, read-only
os.makedirs(DATA, exist_ok=True)

UA = "AtlasGateResearch terry-research@example.com"
UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
PLACEBO_SEEDS = list(range(1, 21))                     # twenty seeds: 1..20

# ---------------------------------------------------------------- fetch utils
def fetch(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            with open(path, "wb") as f:
                f.write(blob)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")

def fetch_shared(url, filename, headers=None):
    """Read from the shared original cache if present; else fetch into the
    honest cache dir (shared dir is never written)."""
    shared_path = os.path.join(SHARED, filename)
    if os.path.exists(shared_path) and os.path.getsize(shared_path) > 100:
        with open(shared_path, "rb") as f:
            return f.read()
    return fetch(url, os.path.join(DATA, filename), headers=headers)

def get_ciks():
    blob = fetch_shared("https://www.sec.gov/files/company_tickers.json",
                        "company_tickers.json")
    raw = json.loads(blob)
    out = {}
    for row in raw.values():
        out[row["ticker"]] = (int(row["cik_str"]), row["title"])
    return out

def get_companyfacts(cik):
    filename = f"facts_{cik:010d}.json"
    blob = fetch_shared(
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
        filename, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    if blob[:2] == b"\x1f\x8b":
        import gzip
        blob = gzip.decompress(blob)
    return json.loads(blob)

def get_prices(ticker, p1="2017-06-01", p2="2026-11-21"):
    path = os.path.join(DATA, f"px_{ticker}.json")
    shared_path = os.path.join(SHARED, f"px_{ticker}.json")
    if os.path.exists(shared_path) and os.path.getsize(shared_path) > 100:
        # reuse the original test's cached prices verbatim (same fetch method)
        with open(shared_path, "rb") as f:
            blob = f.read()
    else:
        import calendar
        t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
        t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
        blob = fetch(url, path, headers={"User-Agent": "Mozilla/5.0"})
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

# ------------------------------------------------------------ point-in-time
def pit_series(facts, taxonomy, concept, prio=0):
    """Return list of (filed_date, end_date, val, prio) for a concept."""
    try:
        units = facts["facts"][taxonomy][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else ("shares" if "shares" in units else list(units)[0])
    rows = []
    for e in units[key]:
        if "filed" not in e or "val" not in e:
            continue
        rows.append((e["filed"], e.get("end", ""), float(e["val"]), prio))
    return rows

def pit_value(rows, asof, max_age_days=548):
    """Most recently FILED value strictly before asof.
    Tie-break: higher source priority, then latest period end.
    Freshness gate: the fact must have been filed within ~18 months of asof.
    (Visa's only EDGAR share facts were filed in 2009/2010 — a decade stale;
    using them would fabricate its market cap, so stale facts are rejected.)"""
    from datetime import date as _date
    ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
    cutoff_ord = _date(ay, am, ad).toordinal() - max_age_days
    best = None
    for filed, end, val, prio in rows:
        if filed < asof:
            fy, fm, fd = int(filed[:4]), int(filed[5:7]), int(filed[8:10])
            if _date(fy, fm, fd).toordinal() < cutoff_ord:
                continue
            key = (filed, prio, end)
            if best is None or key > best[0]:
                best = (key, (filed, end, val))
    return best[1] if best else None  # (filed, end, val) or None


# ------------------------------------------------------- vol scaling (B&SC)
VOL_TARGET = 0.12        # Barroso & Santa-Clara (2015) annual vol target
VOL_LOOKBACK = 126       # prior ~6 months of trading days (B&SC: 6 months)
VOL_MIN_RETURNS = 60     # documented fallback threshold (see docstring #5)
SQRT252 = math.sqrt(252)

def _aligned_closes(pb, ticker):
    """Closes for ticker aligned to pb.dates, forward-filled (last close
    on or before each global date); None before the ticker's first bar."""
    out = []
    last = None
    idx = pb.idx.get(ticker, {})
    for d in pb.dates:
        b = idx.get(d)
        if b:
            last = b["c"]
        out.append(last)
    return out

def trailing_portfolio_vol(pb, aligned, date_index, picks):
    """Annualized realized vol of an equal-weight, daily-rebalanced
    portfolio of `picks` over the trailing VOL_LOOKBACK trading days
    ending at pb.dates[date_index] (the selection date). Point-in-time:
    only closes on or before the selection date. Returns
    (sigma_ann, n_returns); sigma_ann is None if history is too short."""
    i = date_index
    series = [aligned[t] for t in picks]
    start = i - VOL_LOOKBACK
    if start < 0:
        start = 0
    while start < i and any(s[start] is None for s in series):
        start += 1
    rets = []
    for jj in range(start + 1, i + 1):
        r = 0.0
        ok = True
        for s in series:
            prev, cur = s[jj - 1], s[jj]
            if prev is None or cur is None or prev <= 0:
                ok = False
                break
            r += cur / prev - 1.0
        if ok:
            rets.append(r / len(series))
    if len(rets) < VOL_MIN_RETURNS:
        return None, len(rets)
    m = sum(rets) / len(rets)
    var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
    return math.sqrt(var) * SQRT252, len(rets)

# ------------------------------------------------------------------ engine
class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        bl = self.bars.get(t, [])
        best = None
        for b in bl:
            if b["d"] <= d:
                best = b
            else:
                break
        return best["c"] if best else None

    def next_open(self, t, d):
        """(date, open) of first bar strictly after d."""
        for b in self.bars.get(t, []):
            if b["d"] > d:
                return b["d"], b["o"]
        return None, None

def quarter_selection_dates(pb, start, end):
    out = []
    seen = set()
    for d in pb.dates:
        if start <= d <= end:
            key = (d[:4], d[5:7])
            if d[5:7] in ("01", "04", "07", "10") and key not in seen:
                seen.add(key)
                out.append(d)
    return out

def percentile_ranks(values):
    """values: dict ticker->score. Returns dict ticker->percentile in [0,1]."""
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    return {t: i / (n - 1) for i, (t, _) in enumerate(items)}

def run_pot(pb, equity_rows, shares_rows, start, end, start_cash,
            floor0, ladder, placebo_rng=None, label="", quiet=False,
            record_pools=False, volscale=False):
    """Simulate one pot. Identical mechanics to value-momentum.py; adds
    halt diagnostics (signal date, signal close, floor in effect) and an
    optional record of the scored pool at each selection date."""
    cash = start_cash
    floor = floor0
    positions = {}  # ticker -> shares
    trades = []     # (date, ticker, side, shares, price, value, cost)
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []      # (date, close equity) — instrumentation only
    pools = []      # (date, sorted list of scored tickers, picks)
    weights = []    # (date, sigma_ann, w) — volscale instrumentation
    sel_dates = quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None  # list of (ticker, target_value) to execute at next open

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        """Execute at open of day d toward target dollar values (dict t->value).
        Sells first, then buys. Returns total cost."""
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        # sells / trims
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        # buys
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    _aligned = {}
    _didx = {dd: ii for ii, dd in enumerate(pb.dates)}
    def picks_vol(d, picks):
        for t in picks:
            if t not in _aligned:
                _aligned[t] = _aligned_closes(pb, t)
        return trailing_portfolio_vol(pb, _aligned, _didx[d], picks)

    for di, d in enumerate(days):
        # execute pending rebalance at today's open
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        # selection day: compute targets from data filed before today
        if d in sel_set:
            scores = {}
            detail = {}
            for t in UNIVERSE:
                be = pit_value(equity_rows.get(t, []), d)
                so = pit_value(shares_rows.get(t, []), d)
                px = pb.close_on_or_before(t, d)
                if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
                    continue
                mcap = so[2] * px
                if mcap <= 0:
                    continue
                bm = be[2] / mcap
                # momentum 12-1: close ~252 trading days ago vs ~21 days ago
                bl = pb.bars.get(t, [])
                didx = None
                for i, b in enumerate(bl):
                    if b["d"] == d:
                        didx = i
                        break
                if didx is None or didx < 253:
                    continue
                mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
                scores[t] = (bm, mom)
                detail[t] = (be, so, mcap)
            if len(scores) >= 5:
                vr = percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = percentile_ranks({t: v[1] for t, v in scores.items()})
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:5]
                if record_pools:
                    pools.append((d, sorted(scores), list(picks)))
                pv = portfolio_close(d)
                w = 1.0
                if volscale:
                    sig, _nret = picks_vol(d, picks)
                    if sig is not None and sig > 0:
                        w = min(1.0, VOL_TARGET / sig)
                    weights.append((d, round(sig, 4) if sig is not None else None,
                                    round(w, 4)))
                each = w * pv / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} pool={len(scores)} picks={picks} pot=${pv:,.2f}", flush=True)
        # end of day: ladder then floor check
        v = portfolio_close(d)
        curve.append((d, v))
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor:
                floor = newfloor
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            # liquidate at next open
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": pools, "curve": curve, "weights": weights}
    # end of window: liquidate at final close
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "pools": pools, "curve": curve, "weights": weights}

def spy_net(pb, start, end, start_cash):
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost

def _pct(sorted_vals, q):
    """Percentile with linear interpolation (numpy 'linear' method)."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

# --------------------------------------------------------------------- main
def diagnostics(r, floor0):
    """Worst close vs floor, max drawdown, per-year closes, COVID window."""
    curve = r["curve"]
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = (d, v)   # last close of each calendar year wins
    covid = [(d, v) for d, v in curve if "2020-02-01" <= d <= "2020-04-30"]
    covid_worst = min(covid, key=lambda kv: kv[1]) if covid else None
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "floor": floor0,
            "worst_close_above_floor": round(worst_v - floor0, 2),
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "covid_worst_close": round(covid_worst[1], 2) if covid_worst else None,
            "covid_worst_date": covid_worst[0] if covid_worst else None,
            "year_end_closes": {y: {"date": d, "close": round(v, 2)}
                                for y, (d, v) in sorted(year_end.items())}}

def _wstats(weights):
    if not weights:
        return {}
    ws = [w for _, _, w in weights]
    return {"selections": len(ws), "mean_w": round(sum(ws) / len(ws), 4),
            "min_w": round(min(ws), 4),
            "scaled_selections": sum(1 for w in ws if w < 0.999),
            "mean_invested_pct": round(100.0 * sum(ws) / len(ws), 1)}

def _placebo_block(pb, equity_rows, shares_rows, ws, we, ranked_final):
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_pot(pb, equity_rows, shares_rows, ws, we, 100.0, 85.0, [],
                     placebo_rng=rng, label=f"PLACEBO VS seed {seed}",
                     quiet=True, volscale=True)
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2),
                     "wstats": _wstats(pr["weights"])})
        print(f"  PLACEBO VS seed {seed:2d}: final=${pr['final']:,.2f} "
              f"halted={pr['halted']} mean_w={rows[-1]['wstats'].get('mean_invested_pct')}%",
              flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    return {"seeds": PLACEBO_SEEDS,
            "median": round(_pct(srt, 0.50), 2), "q1": round(_pct(srt, 0.25), 2),
            "q3": round(_pct(srt, 0.75), 2), "best": round(srt[-1], 2),
            "worst": round(srt[0], 2), "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for p in rows if p["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_percentile": round(100.0 * (below + 0.5 * ties) / len(finals), 1),
            "seeds_beaten": below, "rows": rows}

# ============================================================ V9 MODULE
# "CLAUDE-RULES PROTECTION SPEC v9" - this copy only. The ONLY change vs
# the original v5 script is the protection module (the *_v9 wrapper
# below, which calls the original engine unchanged for each episode):
#   - Episode 1: plain -15% floor from the $100 start ($85.00), identical
#     to Terry's rule. On FIRST halt: liquidate exactly as the original
#     engine does, sit in cash 90 calendar days (counted from the
#     liquidation date), then RESTART with the remaining cash at the
#     strategy's next regular decision point after day 90.
#   - Episode 2: floor = -15% from the RESTART balance. On SECOND halt:
#     the run ends permanently.
#   - If halt + 90 days runs past the window/fold end (no regular
#     decision point remains in-window), the run ends in cash.
# Everything else is byte-identical: universe, signals, parameters
# (vol-scaling / trend-gate parameters are SIGNAL, not protection -
# untouched), costs 0.10%/side + $0.01/sell, windows, $100 start.
# Scope (per spec): ranked pots only, no placebos. Windows/folds where
# the original recorded run never fired the floor are NOT re-run - they
# are identical under v9 by construction and are logged from the
# original results JSON. This script writes ONLY v9-results.json next
# to itself. Simulation only.
# ============================================================

def run_pot_v9(pb, equity_rows, shares_rows, start, end, start_cash=100.0,
               label=""):
    """One window under v9. Episode 1 = original run_pot (volscale ON)
    with floor 85% of start_cash; on first halt, cash 90 calendar days
    from the liquidation date, restart at the next quarterly selection
    date on/after liquidation+90d; episode-2 floor = 85% of restart
    cash; second halt ends the run."""
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_pot(pb, equity_rows, shares_rows, start, end, start_cash,
                 floor1, [], label=label + " EP1", quiet=True, volscale=True)
    out = {"final": r1["final"], "costs": r1["costs"],
           "orders": len(r1["trades"]), "curve": list(r1["curve"]),
           "halted": r1["halted"], "halt_info": r1["halt_info"],
           "restarts": [], "second_halt": None, "episodes": 1,
           "ep1_final": r1["final"], "ep1_end": r1["end"]}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = date(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in quarter_selection_dates(pb, start, end):
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if date(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": r1["halted"],
        "liquidation_date": liq_date,
        "halt_signal_close": r1["halt_info"]["signal_close"],
        "restart_date": restart,
        "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    r2 = run_pot(pb, equity_rows, shares_rows, restart, end, cash,
                 floor2, [], label=label + " EP2", quiet=True, volscale=True)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["orders"] += len(r2["trades"])
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


HIS_FOLDS = [
    {"year": 2020, "final": 84.66, "spy_net": 117.47, "halted": "2020-03-12"},
    {"year": 2021, "final": 109.24, "spy_net": 127.97, "halted": None},
    {"year": 2022, "final": 103.08, "spy_net": 81.42, "halted": None},
    {"year": 2023, "final": 113.32, "spy_net": 125.28, "halted": None},
    {"year": 2024, "final": 132.54, "spy_net": 125.46, "halted": None},
    {"year": 2025, "final": 114.21, "spy_net": 116.81, "halted": None},
    {"year": 2026, "final": 120.65, "spy_net": 101.17, "halted": None},
]


def main():
    ciks = get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = get_companyfacts(cik)
        equity_rows[t] = (pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
              pit_series(facts, "us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", prio=1))
        shares_rows[t] = (pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
              pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
              pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        time.sleep(0.05)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = get_prices(t)
    pb = PriceBook(bars)
    print("inputs built", flush=True)

    # Main windows: floor never fired under his rules (continuous worst
    # close $91.94 on 2020-03-23; validation worst close $96.68 on
    # 2023-03-17; both halted=None) -> identical under v9, NOT re-run.
    # Only the 2020 fold fired (halted 2020-03-12) -> re-run that fold.
    r = run_pot_v9(pb, equity_rows, shares_rows, "2020-01-01", "2020-12-31",
                   100.0, label="V9 FOLD 2020")
    print(f"EP1 final=${r['ep1_final']:.2f} halted={r['halted']} "
          f"liq={r['ep1_end']} (recorded his: $84.66, halt 2020-03-12)",
          flush=True)
    assert abs(r["ep1_final"] - 84.66) < 0.02 and r["halted"] == "2020-03-12", \
        "episode-1 reproduction failed"
    print(f"V9 FOLD 2020 final=${r['final']:.2f} restarts={r['restarts']} "
          f"second_halt={r['second_halt']}", flush=True)

    v9_folds = []
    for f in HIS_FOLDS:
        if f["year"] == 2020:
            v9_folds.append({"year": 2020, "final": round(r["final"], 2),
                             "spy_net": f["spy_net"],
                             "beat_spy": r["final"] > f["spy_net"],
                             "halted_ep1": r["halted"],
                             "second_halt": r["second_halt"]})
        else:
            v9_folds.append({"year": f["year"], "final": f["final"],
                             "spy_net": f["spy_net"],
                             "beat_spy": f["final"] > f["spy_net"],
                             "halted_ep1": f["halted"], "second_halt": None})
    his_wins = sum(1 for f in HIS_FOLDS if f["final"] > f["spy_net"])
    v9_wins = sum(1 for f in v9_folds if f["beat_spy"])
    def comp(folds):
        c = 100.0
        for f in folds:
            c *= f["final"] / 100.0
        return round(c, 2)
    v9_min = min([v for _, v in r["curve"]] + [r["final"], r["ep1_final"]])
    out = {
        "slug": "vm-volscale",
        "name": "Value+Momentum + Barroso & Santa-Clara volatility scaling (scale-down-only)",
        "status": "partial-rerun",
        "his": {"continuous_final": 256.05, "validation_final": 205.85},
        "v9": {
            "continuous_final": 256.05, "validation_final": 205.85,
            "continuous_status": "identical - floor never fired (worst close $91.94 on 2020-03-23 vs $85 floor; halted=None in v5 results)",
            "validation_status": "identical - floor never fired (worst close $96.68 on 2023-03-17 vs $85 floor; halted=None in v5 results)",
            "restarts": [{"window": "fold-2020", **r["restarts"][0]}] if r["restarts"] else [],
            "folds_note": (f"His folds 3/7 vs SPY (fold-compounded ${comp(HIS_FOLDS)}); "
                           f"v9 folds {v9_wins}/7 vs SPY (fold-compounded ${comp(v9_folds)}). "
                           f"Only the 2020 fold fired under his rules (halt 2020-03-12, final $84.66); "
                           f"it was re-run under v9: final ${round(r['final'],2)} "
                           f"(episode 2 second_halt={r['second_halt']}). Folds 2021-2026 never fired and are unchanged."),
            "worst_total_loss_pct": round(v9_min / 100.0 * 100 - 100, 2),
        },
        "notes": ("Simulation only. Main windows NOT re-run: floor never fired there under his rules, "
                  "so v9 is identical by construction. 2020 fold episode 1 reproduced the recorded "
                  "his-rules result ($84.66, halt 2020-03-12) before the v9 restart was applied. "
                  "His worst total loss from $100: -18.93% (2020 fold signal close $81.07). "
                  f"V9 fold detail: {v9_folds}"),
        "detail": {"fold_2020_v9": {"ep1_final": round(r["ep1_final"], 2),
                                    "final": round(r["final"], 2),
                                    "costs": round(r["costs"], 2),
                                    "orders": r["orders"],
                                    "restarts": r["restarts"],
                                    "second_halt": r["second_halt"],
                                    "min_close_v9": round(v9_min, 2)},
                   "his_fold_compounded": comp(HIS_FOLDS),
                   "v9_fold_compounded": comp(v9_folds),
                   "his_fold_record": f"{his_wins} wins, {7-his_wins} losses vs SPY",
                   "v9_fold_record": f"{v9_wins} wins, {7-v9_wins} losses vs SPY"},
    }
    with open(os.path.join(HERE, "v9-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
