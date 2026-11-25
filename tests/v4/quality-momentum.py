#!/usr/bin/env python3
"""
QUALITY + MOMENTUM backtest for Terry's AI stock app. Simulation only.

Rule (frozen):
  Quarterly selection (first trading day of Jan/Apr/Jul/Oct), using only SEC
  facts FILED before that date (point-in-time, no look-ahead).
    quality score  = gross profitability proxy (Novy-Marx):
                     (Revenue - COGS) / Total Assets, taken from a single
                     filing (same accession number, same fiscal period,
                     annual periods only). If COGS is unavailable for a
                     name, fall back to Operating Income / Total Assets
                     from the same filing, and flag it.
    momentum score = trailing 12-month return skipping the most recent
                     month (12-1)
  Rank by the AVERAGE of the two percentile ranks; hold top 5, equal weight;
  rebalance quarterly at next open.
Costs: 0.10% of trade value per side + $0.01 per sell order.
Floor/ladder ACTIVE: $50 pot -> floor $42.50, ladder to $50 at $62.50 close,
  $62.50 at $75 close. $100 pot -> floor $85, ladder $100 at $125, $125 at $150.
  Close at/below floor -> liquidate at next open, run ends.

Data: SEC EDGAR companyfacts API (free, no key) + Yahoo Finance chart API.
Everything cached under ./data (shared with the value-momentum run).
"""
import json, os, random, time, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

UA = "AtlasGateResearch terry-research@example.com"
UNIVERSE = ["AAPL","MSFT","AMZN","NVDA","GOOGL","META","JPM","XOM","UNH","HD",
            "MA","V","LLY","CRM","ORCL","COST","NFLX","AMD","AVGO","TSLA"]
PLACEBO_SEED = 20261121

REV_CONCEPTS = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "SalesRevenueNet"]
COGS_CONCEPTS = ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"]
OPINC_CONCEPT = "OperatingIncomeLoss"
ASSETS_CONCEPT = "Assets"

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
        out[row["ticker"]] = int(row["cik_str"])
    return out

def get_companyfacts(cik):
    path = os.path.join(DATA, f"facts_{cik:010d}.json")
    blob = fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
                 path, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
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
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

# ------------------------------------------------------- quality observations
def _entries(facts, concept):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else list(units)[0]
    return units[key]

def _annual(entries):
    """Keep duration entries whose period looks like a fiscal year."""
    out = []
    for e in entries:
        if "start" not in e or "end" not in e or "val" not in e:
            continue
        try:
            days = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
        except ValueError:
            continue
        if 300 <= days <= 400:
            out.append(e)
    return out

def build_quality_observations(facts):
    """Return sorted list of (filed, end, quality, method).
    GP observations: (Revenue - COGS)/Assets within one filing (accn) and one
    annual period, Assets from the same filing at the period end.
    OPINC observations (fallback): OperatingIncomeLoss/Assets, same structure.
    """
    # assets by accession: accn -> {end: (val, filed)}
    assets_by_accn = {}
    for e in _entries(facts, ASSETS_CONCEPT):
        if "val" not in e or "end" not in e:
            continue
        accn = e.get("accn", "")
        assets_by_accn.setdefault(accn, {})[e["end"]] = (float(e["val"]), e.get("filed", ""))

    def assets_for(accn, period_end):
        m = assets_by_accn.get(accn, {})
        if period_end in m:
            return m[period_end][0]
        earlier = [en for en in m if en <= period_end]
        if earlier:
            return m[max(earlier)][0]
        return None

    def by_accn_period(concepts):
        """accn -> {(start,end): (val, filed)} using concept priority order."""
        out = {}
        for concept in concepts:
            for e in _annual(_entries(facts, concept)):
                accn = e.get("accn", "")
                key = (e["start"], e["end"])
                slot = out.setdefault(accn, {})
                if key not in slot:  # higher-priority concept wins
                    slot[key] = (float(e["val"]), e.get("filed", ""))
        return out

    rev = by_accn_period(REV_CONCEPTS)
    cogs = by_accn_period(COGS_CONCEPTS)
    obs = []
    for accn, periods in rev.items():
        for (start, end), (rval, rfiled) in periods.items():
            c = cogs.get(accn, {}).get((start, end))
            if c is None:
                continue
            a = assets_for(accn, end)
            if a is None or a <= 0:
                continue
            filed = max(rfiled, c[1])
            obs.append((filed, end, (rval - c[0]) / a, "GP"))
    if not obs:
        op = by_accn_period([OPINC_CONCEPT])
        for accn, periods in op.items():
            for (start, end), (oval, ofiled) in periods.items():
                a = assets_for(accn, end)
                if a is None or a <= 0:
                    continue
                obs.append((ofiled, end, oval / a, "OPINC"))
    obs.sort()
    return obs

def quality_at(obs, asof):
    """Most recently FILED observation strictly before asof."""
    best = None
    for filed, end, val, method in obs:
        if filed < asof:
            if best is None or (filed, end) > (best[0], best[1]):
                best = (filed, end, val, method)
        else:
            break
    return best  # (filed, end, val, method) or None

# ------------------------------------------------------------------ engine
class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        best = None
        for b in self.bars.get(t, []):
            if b["d"] <= d:
                best = b
            else:
                break
        return best["c"] if best else None

def quarter_selection_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end:
            key = (d[:4], d[5:7])
            if d[5:7] in ("01", "04", "07", "10") and key not in seen:
                seen.add(key)
                out.append(d)
    return out

def percentile_ranks(values):
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    return {t: i / (n - 1) for i, (t, _) in enumerate(items)}

def run_pot(pb, quality_obs, start, end, start_cash, floor0, ladder,
            placebo_rng=None, label="", coverage=None):
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    sel_dates = quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
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
            scores = {}
            for t in UNIVERSE:
                q = quality_at(quality_obs.get(t, []), d)
                if q is None:
                    if coverage is not None:
                        coverage[t]["unscored"] += 1
                    continue
                bl = pb.bars.get(t, [])
                didx = None
                for i, b in enumerate(bl):
                    if b["d"] == d:
                        didx = i
                        break
                if didx is None or didx < 253:
                    if coverage is not None:
                        coverage[t]["unscored"] += 1
                    continue
                mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
                scores[t] = (q[2], mom)
                if coverage is not None:
                    coverage[t][q[3]] += 1
            if len(scores) >= 5:
                qr = percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = percentile_ranks({t: v[1] for t, v in scores.items()})
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    combined = {t: (qr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:5]
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                print(f"  [{label}] {d} picks={picks} pot=${pv:,.2f}", flush=True)
        v = portfolio_close(d)
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor:
                floor = newfloor
        if v <= floor and di < len(days) - 1:
            halted = d
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
    quality_obs = {}
    for t in UNIVERSE:
        facts = get_companyfacts(ciks[t])
        obs = build_quality_observations(facts)
        quality_obs[t] = obs
        methods = {}
        for _, _, _, m in obs:
            methods[m] = methods.get(m, 0) + 1
        print(f"{t}: quality observations={len(obs)} methods={methods}", flush=True)
        time.sleep(0.15)

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
    # Coverage: evaluate the quality score at EVERY quarterly selection date
    # in the full window, independent of any pot run (runs can halt early).
    coverage = {t: {"GP": 0, "OPINC": 0, "unscored": 0} for t in UNIVERSE}
    for d in quarter_selection_dates(pb, "2019-01-02", "2026-11-20"):
        for t in UNIVERSE:
            q = quality_at(quality_obs.get(t, []), d)
            if q is None:
                coverage[t]["unscored"] += 1
            else:
                coverage[t][q[3]] += 1
    for wname, ws, we in windows:
        spy = {}
        for szname, sc, fl, lad in configs:
            s, _ = spy_net(pb, ws, we, sc)
            spy[szname] = s
            r = run_pot(pb, quality_obs, ws, we, sc, fl, lad,
                        label=f"{wname} {szname}")
            results[(wname, szname, "QM")] = r
            print(f"== {wname} {szname} QM final=${r['final']:,.2f} costs=${r['costs']:,.2f} "
                  f"orders={len(r['trades'])} halted={r['halted']} | SPY net=${s:,.2f}", flush=True)
            if wname == "VALIDATION":
                rng = random.Random(PLACEBO_SEED)
                rp = run_pot(pb, quality_obs, ws, we, sc, fl, lad,
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
    out["coverage"] = coverage
    out["quality_obs_counts"] = {t: len(quality_obs[t]) for t in UNIVERSE}
    with open(os.path.join(HERE, "quality-momentum-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("COVERAGE:", json.dumps(coverage, indent=1))
    print("DONE")

if __name__ == "__main__":
    main()
