#!/usr/bin/env python3
"""
V10 GREAT RETEST — vm-volscale
VALUE + MOMENTUM + BARROSO & SANTA-CLARA VOLATILITY SCALING
(scale-down-only, 12% target) — Terry's AI stock app. Simulation only.

Original: backtests/v5/vm-volscale/vm-volscale.py (published finals:
CONT 2019-01-02->2026-11-20 $256.05; VAL 2023-01-03->2026-11-20 $205.85).
v9 form: backtests/v9-muse-rules/vm-volscale/vm-volscale-v9.py (main
windows identical under v9 — floor never fired there).

THIS SCRIPT does, in order:
  (1) INTEGRITY — the strategy engine below is the v5 engine copied
      with only mechanical generalizations (see below). Run in its
      ORIGINAL form (quarterly cadence, plain -15% floor, no restart,
      original v4 price/facts caches) on CONT and VAL; finals must
      reproduce $256.05 / $205.85.
  (2) SWEEP — DECADE 2016-11-21 -> 2026-11-20 at 7 cadences
      (daily/weekly/biweekly/monthly/quarterly/semiannual/annual),
      $100/cell, program costs, v9 protections (plain -15% floor;
      first halt -> liquidate, 90 calendar days cash, restart at the
      next cadence date under an episode-2 -15% floor; second halt
      ends the run). 20-seed random-pick placebos per cell, same v9
      wrapper, same cadence.

UNIFORM CADENCE RULE (binding, stated per the task): cadence governs
BOTH the re-pick (selection/rebalance) AND the vol-scaling evaluation.
The B&SC weight w = min(1, 0.12/sigma_ann) is re-evaluated ONLY on
cadence dates, from the trailing 126 trading days of the picks made on
that date, exactly as in the original engine — just at the cadence's
tempo instead of always quarterly. Between cadence dates the weight
and holdings are untouched (the daily -15% floor check still runs
every trading day, as it did in the original).

CADENCE DATES (SPEC definition): first trading day of each period over
the full price calendar, filtered to the window — daily = every
trading day; weekly = first trading day of each ISO week; biweekly =
first trading day of every second ISO week (parity anchored on the
first week of the price book, week of 2008-01-02 — a construction
anchor, not a tuned choice); monthly = first trading day of each
month; quarterly = first trading day of each calendar quarter;
semiannual = first trading day of each half-year; annual = first
trading day of each year. A period that began before the window start
contributes no date at the window start (e.g. the first quarterly date
in the decade window is 2017-01-03, exactly as the original engine's
Jan/Apr/Jul/Oct rule behaves).

MECHANICAL GENERALIZATIONS vs the v5 engine (no strategy change):
  - selection dates are a parameter (cadence) instead of hard-coded
    quarterly;
  - per-date scores are memoized and shared by the ranked pot and all
    placebo pots in a cell (scores depend only on the date);
  - point-in-time fact lookup uses a pre-sorted index that returns
    exactly the original pit_value result (max by (filed, prio, end),
    first-in-list on exact ties, filed < asof, filed within 548 days);
  - closes are read from forward-filled aligned arrays (identical to
    close_on_or_before) and momentum from a date->bar-index map
    (identical to the original linear scan);
  - the v9 episode wrapper is the v9 script's run_pot_v9 generalized
    from quarterly restart dates to cadence restart dates.
Everything else — universe (the fixed honest top-30), scoring
(book-to-market + 12-1 momentum percentile-rank average, top-5, equal
weight), the vol-scaling rule and its 5 documented adaptations, costs
(0.10%/side + $0.01/share on sells), execution at next open after the
selection close, end-of-window liquidation at final close — is the
original code's logic unchanged.

DATA (all read-only shared caches; nothing written outside this folder):
  - Integrity: original v4 caches — prices backtests/v4/data/px_*.json
    with fallback backtests/v4/value-momentum-honest-data/px_*.json;
    EDGAR companyfacts + company_tickers in backtests/v4/data/.
  - Sweep: prices backtests/v7/long-hold/data/pxfull_*.json (Yahoo
    chart pulls 2008-01-02 -> 2026-11-20, the long-run-2010 plumbing's
    price source), except GOOGL which the long-run cache keeps at
    backtests/long-run-2010/data/pxfull_GOOGL.json; EDGAR facts from
    backtests/v4/data/ (full-history companyfacts files).
  Price parsing is the original get_prices parsing (adjclose-scaled
  open, adjclose close) in both modes.
"""
import json, math, os, random, sys, time
from bisect import bisect_left, bisect_right
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.join(HERE, "..", "..")
V4 = os.path.join(BT, "v4")
V4DATA = os.path.join(V4, "data")
V4HONEST = os.path.join(V4, "value-momentum-honest-data")
PXFULL_DIRS = [os.path.join(BT, "v7", "long-hold", "data"),
               os.path.join(BT, "long-run-2010", "data")]

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
PLACEBO_SEEDS = list(range(1, 21))
VOL_TARGET = 0.12
VOL_LOOKBACK = 126
VOL_MIN_RETURNS = 60
SQRT252 = math.sqrt(252)
DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------------ price loading
def parse_chart(blob):
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

def get_prices_v4(ticker):
    """Original v5 get_prices source order: v4/data shared cache first,
    then the v4 honest cache. Read-only; no fetching."""
    for path in (os.path.join(V4DATA, f"px_{ticker}.json"),
                 os.path.join(V4HONEST, f"px_{ticker}.json")):
        if os.path.exists(path) and os.path.getsize(path) > 100:
            with open(path, "rb") as f:
                return parse_chart(f.read())
    raise RuntimeError(f"no v4 price cache for {ticker}")

def get_prices_full(ticker):
    for d in PXFULL_DIRS:
        path = os.path.join(d, f"pxfull_{ticker}.json")
        if os.path.exists(path) and os.path.getsize(path) > 100:
            with open(path, "rb") as f:
                return parse_chart(f.read())
    raise RuntimeError(f"no pxfull cache for {ticker}")

# ------------------------------------------------------------ point-in-time
def pit_series(facts, taxonomy, concept, prio=0):
    """Verbatim from the original engine."""
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

def _ord(ds):
    return date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).toordinal()

class PitIndex:
    """Index over one pit_series row list returning EXACTLY the original
    pit_value(rows, asof) result: among rows with filed < asof and
    filed_ord >= asof_ord - 548, the max by key (filed, prio, end);
    exact key ties keep the earliest row in the original list order."""
    def __init__(self, rows):
        self.items = sorted(
            ((_ord(f), f, p, e, v, i) for i, (f, e, v, p) in enumerate(rows)),
            key=lambda x: x[0])
        self.ords = [x[0] for x in self.items]

    def value(self, asof):
        ao = _ord(asof)
        lo = bisect_left(self.ords, ao - 548)
        hi = bisect_left(self.ords, ao)          # filed < asof (strict)
        best = None
        for k in range(lo, hi):
            fo, f, p, e, v, i = self.items[k]
            key = (f, p, e, -i)
            if best is None or key > best[0]:
                best = (key, (f, e, v))
        return best[1] if best else None

def pit_value_orig(rows, asof, max_age_days=548):
    """The original function, kept for a self-check against PitIndex."""
    ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
    cutoff_ord = date(ay, am, ad).toordinal() - max_age_days
    best = None
    for filed, end, val, prio in rows:
        if filed < asof:
            fy, fm, fd = int(filed[:4]), int(filed[5:7]), int(filed[8:10])
            if date(fy, fm, fd).toordinal() < cutoff_ord:
                continue
            key = (filed, prio, end)
            if best is None or key > best[0]:
                best = (key, (filed, end, val))
    return best[1] if best else None

def load_facts():
    with open(os.path.join(V4DATA, "company_tickers.json"), "rb") as f:
        raw = json.loads(f.read())
    ciks = {}
    for row in raw.values():
        ciks[row["ticker"]] = int(row["cik_str"])
    ciks["XOM"] = 34088  # original CIK override
    equity_idx, shares_idx = {}, {}
    for t in UNIVERSE:
        cik = ciks[t]
        path = os.path.join(V4DATA, f"facts_{cik:010d}.json")
        with open(path, "rb") as f:
            blob = f.read()
        if blob[:2] == b"\x1f\x8b":
            import gzip
            blob = gzip.decompress(blob)
        facts = json.loads(blob)
        er = (pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
              pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        sr = (pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
              pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
              pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        equity_idx[t] = PitIndex(er)
        shares_idx[t] = PitIndex(sr)
    return equity_idx, shares_idx

# ------------------------------------------------------------------ engine
class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.didx = {d: i for i, d in enumerate(self.dates)}
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        self.tidx = {t: {b["d"]: i for i, b in enumerate(bl)}
                     for t, bl in bars_by_ticker.items()}
        # forward-filled closes aligned to the global calendar
        self.aligned = {}
        for t, bl in bars_by_ticker.items():
            arr, last = [], None
            m = self.idx[t]
            for d in self.dates:
                b = m.get(d)
                if b:
                    last = b["c"]
                arr.append(last)
            self.aligned[t] = arr

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        i = self.didx.get(d)
        if i is None:
            return None
        return self.aligned[t][i]

def cadence_dates(pb, cadence, start, end):
    """First trading day of each period over the FULL price calendar,
    filtered to [start, end]. See module docstring."""
    def key(d, i):
        y, m = int(d[:4]), int(d[5:7])
        if cadence == "daily":
            return (d,)
        if cadence == "weekly":
            return date(y, m, int(d[8:10])).isocalendar()[:2]
        if cadence == "biweekly":
            return date(y, m, int(d[8:10])).isocalendar()[:2]
        if cadence == "monthly":
            return (y, m)
        if cadence == "quarterly":
            return (y, (m - 1) // 3)
        if cadence == "semiannual":
            return (y, (m - 1) // 6)
        if cadence == "annual":
            return (y,)
        raise ValueError(cadence)
    firsts, seen = [], set()
    for d in pb.dates:
        k = key(d, 0)
        if k not in seen:
            seen.add(k)
            firsts.append(d)
    if cadence == "biweekly":
        firsts = firsts[::2]
    return [d for d in firsts if start <= d <= end]

def percentile_ranks(values):
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    return {t: i / (n - 1) for i, (t, _) in enumerate(items)}

class Scorer:
    """Memoized per-date pool scores, shared by every pot in a run."""
    def __init__(self, pb, equity_idx, shares_idx):
        self.pb, self.eq, self.sh = pb, equity_idx, shares_idx
        self.cache = {}

    def scores_on(self, d):
        if d in self.cache:
            return self.cache[d]
        pb = self.pb
        gi = pb.didx[d]
        scores = {}
        for t in UNIVERSE:
            be = self.eq[t].value(d)
            so = self.sh[t].value(d)
            px = pb.aligned[t][gi]
            if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            bm = be[2] / mcap
            bl = pb.bars.get(t, [])
            didx = pb.tidx.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (bm, mom)
        self.cache[d] = scores
        return scores

def trailing_portfolio_vol(pb, date_index, picks):
    """Original B&SC measurement on the aligned closes (identical math)."""
    i = date_index
    series = [pb.aligned[t] for t in picks]
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

def run_pot(pb, scorer, sel_dates, start, end, start_cash, floor0,
            placebo_rng=None, volscale=True):
    """The original run_pot, generalized only as documented above.
    ladder is always [] in this program (plain floor)."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    weights = []
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None

    def portfolio_close(d):
        v = cash
        gi = pb.didx[d]
        for t, sh in positions.items():
            c = pb.aligned[t][gi]
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
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
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            scores = scorer.scores_on(d)
            if len(scores) >= 5:
                vr = percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = percentile_ranks({t: v[1] for t, v in scores.items()})
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:5]
                pv = portfolio_close(d)
                w = 1.0
                if volscale:
                    sig, _n = trailing_portfolio_vol(pb, pb.didx[d], picks)
                    if sig is not None and sig > 0:
                        w = min(1.0, VOL_TARGET / sig)
                    weights.append((d, round(sig, 4) if sig is not None else None,
                                    round(w, 4)))
                each = w * pv / 5.0
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
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
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "curve": curve, "weights": weights}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_info": None,
            "curve": curve, "weights": weights}

def run_v9(pb, scorer, all_sel_dates, start, end, start_cash=100.0,
           placebo_rng=None):
    """The v9 script's run_pot_v9, generalized to cadence restart dates.
    Episode 1: floor 85% of start. First halt -> liquidate (engine),
    cash 90 calendar days from the liquidation date, restart at the
    first cadence date on/after day 90. Episode 2: floor 85% of the
    restart balance; second halt ends the run."""
    floor1 = round(0.85 * start_cash, 2)
    sel1 = [d for d in all_sel_dates if start <= d <= end]
    r1 = run_pot(pb, scorer, sel1, start, end, start_cash, floor1,
                 placebo_rng=placebo_rng, volscale=True)
    out = {"final": r1["final"], "costs": r1["costs"],
           "orders": len(r1["trades"]), "curve": list(r1["curve"]),
           "trades": list(r1["trades"]), "weights": list(r1["weights"]),
           "halted": r1["halted"], "halt_info": r1["halt_info"],
           "restarts": [], "second_halt": None, "episodes": 1,
           "ep1_final": r1["final"], "ep1_end": r1["end"]}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    day90 = _ord(liq_date) + 90
    restart = None
    for cand in all_sel_dates:
        if cand >= start and _ord(cand) >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": r1["halted"],
        "liquidation_date": liq_date,
        "halt_signal_close": r1["halt_info"]["signal_close"],
        "restart_date": restart,
        "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    sel2 = [d for d in all_sel_dates if restart <= d <= end]
    r2 = run_pot(pb, scorer, sel2, restart, end, cash, floor2,
                 placebo_rng=placebo_rng, volscale=True)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["orders"] += len(r2["trades"])
    out["trades"] += list(r2["trades"])
    out["weights"] += list(r2["weights"])
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out

def spy_net(pb, start, end, start_cash=100.0):
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost

def curve_stats(curve):
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    worst_v, worst_d = None, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
        if worst_v is None or v < worst_v:
            worst_v, worst_d = v, d
    return {"max_dd_pct": round(maxdd * 100, 2), "max_dd_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d}

def cagr(final, start, end, start_cash=100.0):
    yrs = (_ord(end) - _ord(start)) / 365.25
    return round(((final / start_cash) ** (1.0 / yrs) - 1.0) * 100, 2)

def halts_list(r):
    out = []
    if r["halted"] is not None:
        out.append({"episode": 1, "signal_date": r["halted"],
                    "signal_close": r["halt_info"]["signal_close"],
                    "floor_in_effect": r["halt_info"]["floor_in_effect"],
                    "liquidation_date": r["ep1_end"]})
    if r.get("second_halt"):
        sh = r["second_halt"]
        out.append({"episode": 2, "signal_date": sh["signal_date"],
                    "signal_close": sh["signal_close"],
                    "floor_in_effect": sh["floor_in_effect"],
                    "liquidation_date": sh["liquidation_date"]})
    return out

# --------------------------------------------------------------------- main
def main():
    t0 = time.time()
    equity_idx, shares_idx = load_facts()
    print("facts loaded", flush=True)

    # PitIndex self-check against the original pit_value on sample dates
    # (rebuild one raw row list and compare) — guards the generalization.
    import glob as _g
    # (raw rows are inside PitIndex build; re-derive for one ticker)
    with open(os.path.join(V4DATA, "company_tickers.json"), "rb") as f:
        raw = json.loads(f.read())
    ciks = {r["ticker"]: int(r["cik_str"]) for r in raw.values()}
    with open(os.path.join(V4DATA, f"facts_{ciks['AAPL']:010d}.json"), "rb") as f:
        blob = f.read()
    if blob[:2] == b"\x1f\x8b":
        import gzip
        blob = gzip.decompress(blob)
    facts = json.loads(blob)
    er = (pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
          pit_series(facts, "us-gaap",
                     "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                     prio=1))
    idx = PitIndex(er)
    for d in ("2016-11-21", "2019-01-02", "2020-03-23", "2023-01-03", "2026-10-01"):
        a, b = pit_value_orig(er, d), idx.value(d)
        assert a == b, f"PitIndex mismatch AAPL equity {d}: {a} vs {b}"
    print("PitIndex self-check passed", flush=True)

    report = {"integrity": {}, "cells": {}}

    # ---------------- (1) INTEGRITY: original form, original v4 caches
    bars4 = {t: get_prices_v4(t) for t in UNIVERSE + ["SPY"]}
    pb4 = PriceBook(bars4)
    sc4 = Scorer(pb4, equity_idx, shares_idx)
    integ = {}
    for name, (ws, we), pub in (("CONT", CONT, 256.05), ("VAL", VAL, 205.85)):
        sel = cadence_dates(pb4, "quarterly", ws, we)
        r = run_pot(pb4, sc4, sel, ws, we, 100.0, 85.0, volscale=True)
        integ[name] = {"window": [ws, we], "published_final": pub,
                       "reproduced_final": round(r["final"], 2),
                       "match": abs(r["final"] - pub) < 0.005,
                       "costs": round(r["costs"], 2),
                       "orders": len(r["trades"]), "halted": r["halted"]}
        print(f"INTEGRITY {name}: published=${pub} reproduced=${r['final']:.2f} "
              f"match={integ[name]['match']}", flush=True)
    report["integrity"] = integ

    # ---------------- (2) SWEEP: decade, pxfull prices, v9 protections
    barsF = {t: get_prices_full(t) for t in UNIVERSE + ["SPY"]}
    pbF = PriceBook(barsF)
    scF = Scorer(pbF, equity_idx, shares_idx)
    spy_dec = spy_net(pbF, DECADE[0], DECADE[1])
    print(f"SPY decade (this plumbing, adjclose): ${spy_dec:.2f}", flush=True)
    report["decade_spy_plumbing"] = round(spy_dec, 2)

    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    for cad in CADENCES:
        sel = cadence_dates(pbF, cad, DECADE[0], DECADE[1])
        r = run_v9(pbF, scF, sel, DECADE[0], DECADE[1])
        st = curve_stats(r["curve"])
        twins, finals = [], []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = run_v9(pbF, scF, sel, DECADE[0], DECADE[1], placebo_rng=rng)
            finals.append(pr["final"])
            twins.append({"seed": seed, "final": round(pr["final"], 2),
                          "costs": round(pr["costs"], 2),
                          "orders": pr["orders"],
                          "halts": len(halts_list(pr)),
                          "restart": bool(pr["restarts"]),
                          "second_halt": bool(pr["second_halt"])})
        beaten = sum(1 for f in finals if f < r["final"])
        cell = {
            "slug": "vm-volscale", "cadence": cad,
            "window": [DECADE[0], DECADE[1]], "start_cash": 100.0,
            "final": round(r["final"], 2),
            "cagr_pct": cagr(r["final"], DECADE[0], DECADE[1]),
            "max_dd_pct": st["max_dd_pct"], "max_dd_date": st["max_dd_date"],
            "worst_close": st["worst_close"],
            "worst_close_date": st["worst_close_date"],
            "costs": round(r["costs"], 2), "orders": r["orders"],
            "halts": halts_list(r),
            "restart": (r["restarts"][0] if r["restarts"] else None),
            "second_halt": r["second_halt"], "episodes": r["episodes"],
            "selection_dates": sel,
            "weights": r["weights"],
            "spy_final_plumbing": round(spy_dec, 2),
            "spy_final_spec_dividend_adjusted": 367.80,
            "champion_decade_final": 65.89,
            "placebo": {
                "beaten": beaten, "of": 20,
                "median": round(sorted(finals)[9] * 0.5 + sorted(finals)[10] * 0.5, 2),
                "best": round(max(finals), 2), "worst": round(min(finals), 2),
                "finals_sorted": [round(f, 2) for f in sorted(finals)],
                "twins": twins,
                "note": "20 random-pick twins (seeds 1..20), same cadence, "
                        "same vol-scaling rule on their own picks, same v9 "
                        "wrapper; rng stream continues across episodes."},
            "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
            "source": "vm_volscale_v10.py sweep: pxfull prices (v7/long-hold "
                      "cache; GOOGL from long-run-2010 cache), EDGAR facts "
                      "from v4/data, v9 protections.",
        }
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        report["cells"][cad] = {
            "final": cell["final"], "cagr_pct": cell["cagr_pct"],
            "max_dd_pct": cell["max_dd_pct"], "costs": cell["costs"],
            "orders": cell["orders"], "halts": len(cell["halts"]),
            "restart": bool(cell["restart"]),
            "second_halt": bool(cell["second_halt"]),
            "placebo_beaten": beaten}
        print(f"CELL {cad}: final=${r['final']:.2f} CAGR={cell['cagr_pct']}% "
              f"maxDD={cell['max_dd_pct']}% costs=${r['costs']:.2f} "
              f"orders={r['orders']} halts={len(cell['halts'])} "
              f"placebo beaten {beaten}/20 "
              f"({time.time()-t0:.0f}s)", flush=True)

    with open(os.path.join(HERE, "sweep_raw.json"), "w") as f:
        json.dump(report, f, indent=1)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
