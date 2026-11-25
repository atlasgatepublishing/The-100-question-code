#!/usr/bin/env python3
"""
VALUE + MOMENTUM (HONEST) — PLAIN-FLOOR DIAGNOSTIC — Terry's AI stock app.
Simulation only.

IDENTICAL engine to value-momentum-honest.py (same universe, same EDGAR
rules, same scoring, same costs). The ONLY change is the protection rule:
  - The profit LADDER is removed (ladder=[] — no rungs, ever).
  - The floor stays at Terry's plain -15% from the starting balance for
    the whole run: $42.50 on the $50 pot, $85.00 on the $100 pot.
Instrumentation added (does not affect any trade): a daily close-equity
curve is recorded so the report can state the worst close vs the floor,
the max drawdown, and per-year balances.
Why: the honest ladder run's continuous pot died on 2020-03-20 because
the ladder had ratcheted its floor to $100.00 ($50.00 at $50) while the
signal close was $97.32 ($48.60) — under the plain floor ($85 / $42.50)
that close would NOT have fired. This diagnostic prices the ladder.
Windows run: FULL continuous 2019-01-02 -> 2026-11-20 (primary) and
VALIDATION 2023-01-03 -> 2026-11-20 (control: the ladder never fired
there, so the finals must match the ladder run's $288.05 / $143.58).
Everything else is unchanged from value-momentum-honest.py, including:
  - Value score = book equity (StockholdersEquity, merged with the
    incl.-noncontrolling-interest variant) / market cap (shares outstanding
    x selection-day close). NOTE: this is the original engine's definition
    (book-to-market). It is preserved verbatim so this re-test isolates the
    universe/placebo changes; it is NOT earnings yield.
  - Momentum score = trailing 12-month return skipping the most recent
    month (12-1). Rank by the average of the two percentile ranks; hold
    top 5, equal weight; quarterly selection (first trading day of
    Jan/Apr/Jul/Oct), rebalance at next open.
  - Point-in-time EDGAR only: facts FILED strictly before the selection
    date, with the ~18-month filed-freshness gate (pit_value max_age_days
    =548). Names that cannot be scored are excluded, never patched.
  - EDGAR fixes carried over: XOM hard-corrected to parent CIK 34088;
    shares-outstanding fallback chain dei cover-page (prio 3) >
    us-gaap CommonStockSharesOutstanding (prio 2) >
    WeightedAverageNumberOfSharesOutstandingBasic (prio 1).
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Protection (THIS run): plain -15% floor only, no ladder. Close
    at/below floor -> liquidate at next open, run ends.
  - Windows: FULL continuous 2019-01-02 -> 2026-11-20 and VALIDATION
    2023-01-03 -> 2026-11-20 (2019 start: EDGAR companyfacts coverage +
    13 months of prices for 12-1 momentum).

Data: SEC EDGAR companyfacts (cached facts reused read-only from ./data,
the original test's cache) + Yahoo Finance chart API prices
(split/dividend-adjusted, same method as the original), reused read-only
from the honest re-test's cache ./value-momentum-honest-data.

========================================================================
V9 RE-RUN — "CLAUDE-RULES PROTECTION SPEC v9" (this copy only)
Copied verbatim from value-momentum-plainfloor.py; the ONLY change is
the protection module (run_pot_v9 below, which calls the original
run_pot unchanged for each episode):
  - Episode 1: plain -15% floor from the $100 start ($85.00), identical
    to Terry's rule. On FIRST halt: liquidate exactly as the original
    engine does, sit in cash 90 calendar days, then RESTART with the
    remaining cash at the strategy's next regular decision point (next
    quarterly selection date after day 90).
  - Episode 2: floor = -15% from the RESTART balance. On SECOND halt:
    the run ends permanently.
  - If halt + 90 days runs past the window/fold end (no quarterly
    selection date remains in-window), the run ends in cash.
Everything else is byte-identical: universe, signals, parameters,
costs 0.10%/side + $0.01/sell, windows, $100 start. No signal parameter
was retuned.
Scope of this re-run (per spec): the main windows are NOT re-run — the
original recorded curves show the floor never fired there (FULL worst
close $93.13 vs $85 floor; VALIDATION worst close $94.08 vs $85 floor),
so they are identical under v9 by construction. This script re-runs
the yearly folds 2020-2026 (fold windows as in vm-walkforward.py) and
the 20-seed placebos for the folds under both rule sets.
Data paths: SHARED/DATA point at the original v4 caches, read-only;
this script writes only its own results JSON next to itself.
Simulation only.
========================================================================
"""
import json, math, os, random, sys, time, urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ORIG = os.path.abspath(os.path.join(HERE, "..", "..", "v4"))  # original folder, read-only
SHARED = os.path.join(ORIG, "data")                    # original cache, read-only
DATA = os.path.join(ORIG, "value-momentum-honest-data")  # reuse honest cache
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
            record_pools=False):
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
                each = pv / 5.0
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
                    "halt_info": halt_info, "pools": pools, "curve": curve}
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
            "halt_info": None, "pools": pools, "curve": curve}

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

# ============================================================ V9 MODULE
# The ONLY change vs the original script: run_pot_v9 wraps the original
# run_pot (unchanged above) with the v9 two-episode protection rule.
def run_pot_v9(pb, equity_rows, shares_rows, start, end, start_cash,
               placebo_rng=None, label="", quiet=True):
    """One window under CLAUDE-RULES PROTECTION SPEC v9.
    Episode 1: original run_pot with floor = 85% of start_cash.
    On first halt: cash sits 90 calendar days after the liquidation
    date; episode 2 starts at the next quarterly selection date on or
    after liquidation+90d, with floor = 85% of the restart cash.
    On second halt (or no in-window selection date left): run ends."""
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_pot(pb, equity_rows, shares_rows, start, end, start_cash,
                 floor1, [], placebo_rng=placebo_rng,
                 label=label + " EP1", quiet=quiet)
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": r1["trades"], "curve": list(r1["curve"]),
           "halted": r1["halted"], "halt_info": r1["halt_info"],
           "restarts": [], "second_halt": None, "episodes": 1}
    if r1["halted"] is None:
        return out
    # first halt: r1["end"] is the liquidation (next-open) date
    liq_date = r1["end"]
    cash = r1["final"]
    from datetime import date as _d
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _d(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in quarter_selection_dates(pb, start, end):
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _d(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
    # cash-flat curve segment between liquidation and restart/end
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({"halt_signal_date": r1["halted"],
                            "liquidation_date": liq_date,
                            "halt_signal_close": r1["halt_info"]["signal_close"],
                            "restart_date": restart,
                            "restart_balance": round(cash, 2),
                            "episode2_floor": floor2})
    r2 = run_pot(pb, equity_rows, shares_rows, restart, end, cash,
                 floor2, [], placebo_rng=placebo_rng,
                 label=label + " EP2", quiet=quiet)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += r2["trades"]
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out

def worst_from_start(r, start_cash):
    """Lowest equity point (daily closes + final cash) vs the start."""
    vals = [v for _, v in r["curve"]] + [r["final"]]
    return min(vals) if vals else start_cash

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

    START = 100.0
    FLOOR_HIS = 85.0
    fold_defs = [(y, f"{y}-01-01", "2026-11-20" if y == 2026 else f"{y}-12-31")
                 for y in range(2020, 2027)]

    # ---- ranked folds under BOTH rule sets (his = original run_pot)
    his_folds, v9_folds = {}, {}
    his_worst, v9_worst = START, START
    restarts_all, second_halts = [], []
    for y, fs, fe in fold_defs:
        rh = run_pot(pb, equity_rows, shares_rows, fs, fe, START,
                     FLOOR_HIS, [], label=f"HIS FOLD {y}", quiet=True)
        spy_f, _ = spy_net(pb, fs, fe, START)
        his_folds[str(y)] = {"final": round(rh["final"], 2),
                             "halted": rh["halted"], "spy_net": round(spy_f, 2),
                             "beat_spy": rh["final"] > spy_f,
                             "orders": len(rh["trades"]), "costs": round(rh["costs"], 2)}
        his_worst = min(his_worst, worst_from_start(rh, START))
        rv = run_pot_v9(pb, equity_rows, shares_rows, fs, fe, START,
                        label=f"V9 FOLD {y}")
        v9_folds[str(y)] = {"final": round(rv["final"], 2),
                            "halted_first": rv["halted"],
                            "second_halt": rv["second_halt"],
                            "restarts": rv["restarts"],
                            "spy_net": round(spy_f, 2),
                            "beat_spy": rv["final"] > spy_f,
                            "orders": len(rv["trades"]), "costs": round(rv["costs"], 2),
                            "episodes": rv["episodes"]}
        v9_worst = min(v9_worst, worst_from_start(rv, START))
        for rr in rv["restarts"]:
            restarts_all.append({"fold": str(y), **rr})
        if rv["second_halt"]:
            second_halts.append({"fold": str(y), **rv["second_halt"]})
        print(f"FOLD {y}: his=${rh['final']:,.2f} halted={rh['halted']} | "
              f"v9=${rv['final']:,.2f} restarts={len(rv['restarts'])} "
              f"second_halt={bool(rv['second_halt'])}", flush=True)

    def compounded(folds):
        p = START
        for k in sorted(folds):
            p *= folds[k]["final"] / START
        return round(p, 2)
    his_comp = compounded(his_folds)
    v9_comp = compounded(v9_folds)
    print(f"FOLD-COMPOUNDED: his=${his_comp} v9=${v9_comp}", flush=True)

    # ---- placebos for the folds: 20 seeds, fresh Random(seed) per fold
    # (mirrors the original per-window construction); the same rng object
    # is carried across a v9 restart (no reseed). Score = ranked
    # fold-compounded final vs each seed's fold-compounded final.
    def placebo_compounded(v9):
        rows = []
        for seed in PLACEBO_SEEDS:
            p = START
            for y, fs, fe in fold_defs:
                rng = random.Random(seed)
                if v9:
                    pr = run_pot_v9(pb, equity_rows, shares_rows, fs, fe,
                                    START, placebo_rng=rng,
                                    label=f"PLB v9 s{seed} {y}")
                else:
                    pr = run_pot(pb, equity_rows, shares_rows, fs, fe,
                                 START, FLOOR_HIS, [], placebo_rng=rng,
                                 label=f"PLB his s{seed} {y}", quiet=True)
                p *= pr["final"] / START
            rows.append({"seed": seed, "fold_compounded": round(p, 2)})
            print(f"PLACEBO {'v9' if v9 else 'his'} seed {seed:2d}: "
                  f"fold-compounded=${p:,.2f}", flush=True)
        return rows
    plb_his = placebo_compounded(v9=False)
    plb_v9 = placebo_compounded(v9=True)
    his_beaten = sum(1 for r in plb_his if r["fold_compounded"] < his_comp)
    v9_beaten = sum(1 for r in plb_v9 if r["fold_compounded"] < v9_comp)
    print(f"PLACEBO FOLDS: his ranked ${his_comp} beat {his_beaten}/20 | "
          f"v9 ranked ${v9_comp} beat {v9_beaten}/20", flush=True)

    out = {"protection_v9": "episode-1 floor -15% from start; on first halt liquidate, 90 calendar days cash, restart at next quarterly selection date with remaining cash; episode-2 floor -15% from restart balance; second halt ends run",
           "his_folds": his_folds, "v9_folds": v9_folds,
           "his_folds_compounded": his_comp, "v9_folds_compounded": v9_comp,
           "restarts": restarts_all, "second_halts": second_halts,
           "placebo_folds_his": {"ranked": his_comp, "seeds_beaten": his_beaten, "rows": plb_his},
           "placebo_folds_v9": {"ranked": v9_comp, "seeds_beaten": v9_beaten, "rows": plb_v9},
           "his_worst_equity_from_100": round(his_worst, 2),
           "v9_worst_equity_from_100": round(v9_worst, 2)}
    with open(os.path.join(HERE, "v9-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
