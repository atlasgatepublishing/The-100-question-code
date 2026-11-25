#!/usr/bin/env python3
"""
VALUE + MOMENTUM backtest for Terry's AI stock app. Simulation only.

Rule (frozen):
  Quarterly selection (first trading day of Jan/Apr/Jul/Oct), using only SEC
  facts FILED before that date (point-in-time, no look-ahead).
    value score    = book equity (StockholdersEquity) / market cap
                     (market cap = shares outstanding x close on selection day)
    momentum score = trailing 12-month return skipping the most recent month (12-1)
  Rank by the AVERAGE of the two percentile ranks; hold top 5, equal weight;
  rebalance quarterly at next open.
Costs: 0.10% of trade value per side + $0.01 per sell order.
Floor/ladder ACTIVE: $50 pot -> floor $42.50, ladder to $50 at $62.50 close,
  $62.50 at $75 close. $100 pot -> floor $85, ladder $100 at $125, $125 at $150.
  Close at/below floor -> liquidate at next open, run ends.

Data: SEC EDGAR companyfacts API (free, no key) + Yahoo Finance chart API.
Everything cached under ./data.
"""
import json, math, os, random, sys, time, urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

UA = "AtlasGateResearch terry-research@example.com"
UNIVERSE = ["AAPL","MSFT","AMZN","NVDA","GOOGL","META","JPM","XOM","UNH","HD",
            "MA","V","LLY","CRM","ORCL","COST","NFLX","AMD","AVGO","TSLA"]
PLACEBO_SEED = 20261121

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

def get_ciks():
    blob = fetch("https://www.sec.gov/files/company_tickers.json",
                 os.path.join(DATA, "company_tickers.json"))
    raw = json.loads(blob)
    out = {}
    for row in raw.values():
        out[row["ticker"]] = (int(row["cik_str"]), row["title"])
    return out

def get_companyfacts(cik):
    path = os.path.join(DATA, f"facts_{cik:010d}.json")
    blob = fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
                 path, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    # server may return gzip only if requested; urllib doesn't decompress by default
    if blob[:2] == b"\x1f\x8b":
        import gzip
        blob = gzip.decompress(blob)
        with open(path, "wb") as f:
            f.write(blob)
    return json.loads(blob)

def get_prices(ticker, p1="2017-06-01", p2="2026-11-21"):
    path = os.path.join(DATA, f"px_{ticker}.json")
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
        # scale open to adjusted basis so returns are total-ish (split+div adj)
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
            floor0, ladder, placebo_rng=None, label=""):
    """Simulate one pot. Returns result dict."""
    cash = start_cash
    floor = floor0
    positions = {}  # ticker -> shares
    trades = []     # (date, ticker, side, shares, price, value, cost)
    total_costs = 0.0
    halted = None
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
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                print(f"  [{label}] {d} picks={picks} pot=${pv:,.2f}", flush=True)
        # end of day: ladder then floor check
        v = portfolio_close(d)
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor:
                floor = newfloor
        if v <= floor and di < len(days) - 1:
            halted = d
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
                    "trades": trades, "halted": halted, "end": nd}
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
            "trades": trades, "halted": None, "end": last}

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

# --------------------------------------------------------------------- main
def main():
    ciks = get_ciks()
    # company_tickers.json maps XOM to a subsidiary (ExxonMobil Holdings,
    # CIK 2115436); the listed parent is CIK 34088. Hard override.
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    missing = []
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = get_companyfacts(cik)
        # Book equity: merge the two EDGAR total-equity concepts (some filers
        # report mainly the incl.-noncontrolling-interest variant).
        eq = (pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
              pit_series(facts, "us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", prio=1))
        # Shares outstanding fallback chain (multi-class filers like GOOGL /
        # META / MA don't populate the dei cover-page concept in companyfacts):
        #   dei cover-page count > us-gaap CommonStockSharesOutstanding >
        #   WeightedAverageNumberOfSharesOutstandingBasic (documented proxy).
        so = (pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
              pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
              pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        equity_rows[t] = eq
        shares_rows[t] = so
        if not eq or not so:
            missing.append((t, len(eq), len(so)))
        print(f"{t}: equity facts={len(eq)} shares facts={len(so)}", flush=True)
        time.sleep(0.15)
    if missing:
        print("MISSING/THIN DATA:", missing, flush=True)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = get_prices(t)
        print(f"{t}: {len(bars[t])} bars {bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = PriceBook(bars)

    configs = [
        ("$50", 50.0, 42.50, [(62.50, 50.0), (75.0, 62.50)]),
        ("$100", 100.0, 85.0, [(125.0, 100.0), (150.0, 125.0)]),
    ]
    windows = [
        ("DESIGN", "2019-01-02", "2022-12-30"),
        ("VALIDATION", "2023-01-03", "2026-11-20"),
        ("FULL", "2019-01-02", "2026-11-20"),
    ]
    results = {}
    for wname, ws, we in windows:
        spy = {}
        for szname, sc, fl, lad in configs:
            s, _ = spy_net(pb, ws, we, sc)
            spy[szname] = s
            r = run_pot(pb, equity_rows, shares_rows, ws, we, sc, fl, lad,
                        label=f"{wname} {szname}")
            results[(wname, szname, "VM")] = r
            print(f"== {wname} {szname} VM final=${r['final']:,.2f} costs=${r['costs']:,.2f} "
                  f"orders={len(r['trades'])} halted={r['halted']} | SPY net=${s:,.2f}", flush=True)
            if wname == "VALIDATION":
                rng = random.Random(PLACEBO_SEED)
                rp = run_pot(pb, equity_rows, shares_rows, ws, we, sc, fl, lad,
                             placebo_rng=rng, label=f"{wname} {szname} PLACEBO")
                results[(wname, szname, "PLACEBO")] = rp
                print(f"== {wname} {szname} PLACEBO final=${rp['final']:,.2f} costs=${rp['costs']:,.2f} "
                      f"orders={len(rp['trades'])} halted={rp['halted']}", flush=True)
        results[(wname, "spy")] = spy

    out = {}
    for k, v in results.items():
        if isinstance(v, dict) and "final" in v:
            out[str(k)] = {"final": v["final"], "costs": v["costs"],
                           "orders": len(v["trades"]), "halted": v["halted"],
                           "trades": v["trades"]}
        else:
            out[str(k)] = v
    with open(os.path.join(HERE, "value-momentum-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
