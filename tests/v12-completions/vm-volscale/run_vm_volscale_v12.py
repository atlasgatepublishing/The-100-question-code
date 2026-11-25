#!/usr/bin/env python3
"""
V12 CONSTRUCTION — vm-volscale: Barroso & Santa-Clara (2015) volatility
scaling, paper's exact formula on a tradable long-only host.
Simulation only. Spec frozen in CONSTRUCTION-SPEC.md BEFORE this run;
hunt in HUNT-LOG.md. Nothing tuned after results.

FORMULA (published, Eq. 5):  w = sigma_target / sigma_hat,  sigma_target
= 0.12 annualized; sigma_hat = realized vol of the strategy's OWN daily
returns over the prior 6 months (126 trading days, sample stdev ddof=1,
annualized sqrt(252)); weight re-set MONTHLY.

CONSTRUCTED pieces (labeled, see spec):
  - HOST: the champion value+momentum book (PIT Nov-2016 top-30 pond,
    quarterly top-5 by book-to-market + 12-1 momentum, equal weight,
    PIT EDGAR 548-day freshness gate) — the program's momentum book and
    the host of the v5 house form, so only the construction corrections
    differ from v5.
  - ESTIMATOR STAND-IN: sigma_hat is measured on a SHADOW book — the
    same host, same picks, program costs, always 100% invested, no
    floor, no scaling — run from 2009-01-02 so the estimator is warm at
    every road start. (v5 measured vol of the NEW PICKS instead.)
  - LEVERAGE CAP: w = min(1, 0.12/sigma_hat). The paper is uncapped
    (observed 0.13-2.00); the $100 cash habitat cannot borrow. Remainder
    in cash at 0. Bias: hurts (deletes the calm-period leverage half).
  - MONTHLY MECHANIC: at non-quarterly months, existing holdings are
    scaled proportionally to w x total equity (relative weights kept);
    at quarterly dates the new book forms at w, equal weight.
  - NO SHORT LEG (absent, not approximated — the crash the paper tames
    is mostly a short-leg phenomenon).
  - FLOOR: plain -15% at $85, daily close check, halt liquidates at
    next open and ends the run (habitat rule; the paper publishes none).
    Shadow books run floorless (they are estimator series, not pots).

Costs: program standard 0.10%/side + $0.01 per sell order, on every
trade including monthly scale trades. $100 pots, fractional shares.

INTEGRITY GATE (runs first, v4 caches, original v5 code paths):
  scaling OFF must reproduce champion CONT $544.47 / VAL $288.05;
  v5 rule ON (quarterly, new-picks vol) must reproduce $256.05/$205.85.

ROADS (pxfull caches): LONG 2010-01-04->2026-11-20,
DECADE 2016-11-21->2026-11-20, CONT 2019-01-02->2026-11-20,
VAL 2023-01-03->2026-11-20. Placebos: seeds 1..20 per road, each with
its own shadow book and the identical monthly scaling rule.

DATA (read-only): EDGAR facts + tickers from backtests/v4/data/;
pxfull prices from backtests/v7/long-hold/data/ (GOOGL from
backtests/long-run-2010/data/); integrity prices from backtests/v4/data/
+ backtests/v4/value-momentum-honest-data/. Writes only in this folder.
"""
import json, math, os, random, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
V4DATA = os.path.join(ROOT, "v4", "data")
V4HON = os.path.join(ROOT, "v4", "value-momentum-honest-data")
PXFULL = os.path.join(ROOT, "v7", "long-hold", "data")
LR2010 = os.path.join(ROOT, "long-run-2010", "data")

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
PLACEBO_SEEDS = list(range(1, 21))
VOL_TARGET = 0.12
VOL_LOOKBACK = 126
VOL_MIN_RETURNS = 60
SQRT252 = math.sqrt(252)
SHADOW_START = "2009-01-02"
END_ALL = "2026-11-20"

# ------------------------------------------------------------------ data
def load_json(path):
    with open(path, "rb") as f:
        blob = f.read()
    if blob[:2] == b"\x1f\x8b":
        import gzip
        blob = gzip.decompress(blob)
    return json.loads(blob)

def parse_chart(j):
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

def prices_v4(ticker):
    for base in (V4DATA, V4HON):
        p = os.path.join(base, f"px_{ticker}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            return parse_chart(load_json(p))
    raise RuntimeError(f"no v4 prices for {ticker}")

def prices_full(ticker):
    if ticker == "GOOGL":
        p = os.path.join(LR2010, "pxfull_GOOGL.json")
    else:
        p = os.path.join(PXFULL, f"pxfull_{ticker}.json")
    return parse_chart(load_json(p))

def get_ciks():
    raw = load_json(os.path.join(V4DATA, "company_tickers.json"))
    return {row["ticker"]: int(row["cik_str"]) for row in raw.values()}

def get_facts(cik):
    return load_json(os.path.join(V4DATA, f"facts_{cik:010d}.json"))

# ------------------------------------------------------------ point-in-time
def pit_series(facts, taxonomy, concept, prio=0):
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
    return best[1] if best else None

def build_fact_rows():
    ciks = get_ciks()
    overrides = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        facts = get_facts(overrides.get(t, ciks[t]))
        equity_rows[t] = (pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            pit_series(facts, "us-gaap",
                       "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                       prio=1))
        shares_rows[t] = (pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    return equity_rows, shares_rows

# ------------------------------------------------------------------ engine
class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        self.didx = {d: i for i, d in enumerate(self.dates)}
        self.bpos = {t: {b["d"]: i for i, b in enumerate(bl)}
                     for t, bl in bars_by_ticker.items()}
        self._aligned = {}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        # Mechanical speedup (v10-proven identical): forward-filled aligned
        # close at the global date index — same value as the linear scan.
        i = self.didx.get(d)
        if i is None:
            return None
        return self.aligned(t)[i]

    def aligned(self, t):
        if t not in self._aligned:
            out, last = [], None
            idx = self.idx.get(t, {})
            for d in self.dates:
                b = idx.get(d)
                if b:
                    last = b["c"]
                out.append(last)
            self._aligned[t] = out
        return self._aligned[t]

def quarter_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end:
            key = (d[:4], d[5:7])
            if d[5:7] in ("01", "04", "07", "10") and key not in seen:
                seen.add(key)
                out.append(d)
    return out

def month_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end:
            key = (d[:4], d[5:7])
            if key not in seen:
                seen.add(key)
                out.append(d)
    return out

def percentile_ranks(values):
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    return {t: i / (n - 1) for i, (t, _) in enumerate(items)}

class Engine:
    """One price book + fact rows; scores memoized per date (scores depend
    only on the date — v10 proved this generalization reproduces v5 to
    the cent)."""
    def __init__(self, pb, equity_rows, shares_rows):
        self.pb = pb
        self.er = equity_rows
        self.sr = shares_rows
        self._scores = {}

    def scores_on(self, d):
        if d in self._scores:
            return self._scores[d]
        pb = self.pb
        scores = {}
        for t in UNIVERSE:
            be = pit_value(self.er.get(t, []), d)
            so = pit_value(self.sr.get(t, []), d)
            px = pb.close_on_or_before(t, d)
            if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            bm = be[2] / mcap
            bl = pb.bars.get(t, [])
            didx = pb.bpos.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (bm, mom)
        self._scores[d] = scores
        return scores

    def picks_on(self, d, placebo_rng=None):
        scores = self.scores_on(d)
        if len(scores) < 5:
            return None
        if placebo_rng is not None:
            return placebo_rng.sample(sorted(scores), 5)
        vr = percentile_ranks({t: v[0] for t, v in scores.items()})
        mr = percentile_ranks({t: v[1] for t, v in scores.items()})
        combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
        return sorted(combined, key=lambda t: -combined[t])[:5]

    # ---- v5 estimator: trailing vol of the new picks (integrity only)
    def picks_vol(self, d, picks):
        pb = self.pb
        i = pb.didx[d]
        series = [pb.aligned(t) for t in picks]
        start = max(0, i - VOL_LOOKBACK)
        while start < i and any(s[start] is None for s in series):
            start += 1
        rets = []
        for jj in range(start + 1, i + 1):
            r, ok = 0.0, True
            for s in series:
                prev, cur = s[jj - 1], s[jj]
                if prev is None or cur is None or prev <= 0:
                    ok = False
                    break
                r += cur / prev - 1.0
            if ok:
                rets.append(r / len(series))
        if len(rets) < VOL_MIN_RETURNS:
            return None
        m = sum(rets) / len(rets)
        var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
        return math.sqrt(var) * SQRT252

    def run(self, start, end, mode="plain", placebo_seed=None,
            shadow_rets=None, floor=True):
        """mode: plain | v5vol | constructed. shadow_rets: dict
        date->daily return of the shadow book (constructed mode)."""
        pb = self.pb
        rng = random.Random(placebo_seed) if placebo_seed is not None else None
        cash = 100.0
        positions = {}
        trades = []
        total_costs = 0.0
        curve = []
        weights = []
        halted = None
        qset = set(quarter_dates(pb, start, end))
        mset = set(month_dates(pb, start, end)) if mode == "constructed" else set()
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

        for di, d in enumerate(days):
            if pending is not None:
                execute_rebalance(d, pending)
                pending = None
            is_q = d in qset
            is_m = d in mset
            if is_q or (mode == "v5vol" and is_q) or (mode == "constructed" and is_m):
                if is_q:
                    picks = self.picks_on(d, rng)
                    if picks is not None:
                        pv = portfolio_close(d)
                        w = 1.0
                        if mode == "v5vol":
                            sig = self.picks_vol(d, picks)
                            if sig is not None and sig > 0:
                                w = min(1.0, VOL_TARGET / sig)
                            weights.append((d, round(sig, 4) if sig else None, round(w, 4)))
                        elif mode == "constructed":
                            w = self._shadow_w(d, shadow_rets)
                            weights.append((d, w[1], w[0]))
                            w = w[0]
                        each = w * pv / 5.0
                        pending = {t: each for t in picks}
                elif mode == "constructed" and is_m and positions:
                    w, sig = self._shadow_w(d, shadow_rets)
                    weights.append((d, sig, w))
                    pv = portfolio_close(d)
                    invested = pv - cash
                    if invested > 0.005 and pv > 0:
                        scale = (w * pv) / invested
                        pending = {}
                        for t, sh in positions.items():
                            c = pb.close_on_or_before(t, d)
                            if c:
                                pending[t] = sh * c * scale
            v = portfolio_close(d)
            curve.append((d, v))
            if floor and v <= 85.0 and di < len(days) - 1:
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
                return {"final": cash, "costs": total_costs, "trades": trades,
                        "halted": halted, "end": nd, "curve": curve,
                        "weights": weights}
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
                "halted": None, "end": last, "curve": curve, "weights": weights}

    def _shadow_w(self, d, shadow_rets):
        """(w, sigma_ann) from the shadow book's own trailing 126 daily
        returns ending on date d (returns keyed by the date they end on)."""
        pb = self.pb
        i = pb.didx[d]
        rets = []
        for j in range(max(0, i - VOL_LOOKBACK), i + 1):
            r = shadow_rets.get(pb.dates[j])
            if r is not None:
                rets.append(r)
        rets = rets[-VOL_LOOKBACK:]
        if len(rets) < VOL_MIN_RETURNS:
            return 1.0, None
        m = sum(rets) / len(rets)
        var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
        sig = math.sqrt(var) * SQRT252
        if sig <= 0:
            return 1.0, round(sig, 4)
        return min(1.0, VOL_TARGET / sig), round(sig, 4)

def shadow_returns(eng, seed=None):
    """Run the floorless, unscaled shadow book from SHADOW_START and
    return (dict date->daily return, shadow final/curve summary)."""
    r = eng.run(SHADOW_START, END_ALL, mode="plain", placebo_seed=seed, floor=False)
    rets = {}
    curve = r["curve"]
    for k in range(1, len(curve)):
        prev, cur = curve[k - 1][1], curve[k][1]
        if prev and prev > 0:
            rets[curve[k][0]] = cur / prev - 1.0
    return rets, {"shadow_final_from_2009": round(r["final"], 2),
                  "shadow_costs": round(r["costs"], 2),
                  "shadow_orders": len(r["trades"])}

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

def diagnostics(r):
    curve = r["curve"]
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    ws = [w for _, _, w in r["weights"]]
    return {"final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted": r["halted"],
            "max_drawdown_pct": round(maxdd * 100, 2), "max_dd_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "mean_w": round(sum(ws) / len(ws), 4) if ws else None,
            "min_w": round(min(ws), 4) if ws else None,
            "scaled_months": sum(1 for w in ws if w < 0.999) if ws else 0,
            "n_weights": len(ws)}

def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

ROADS = {"LONG": ("2010-01-04", END_ALL), "DECADE": ("2016-11-21", END_ALL),
         "CONT": ("2019-01-02", END_ALL), "VAL": ("2023-01-03", END_ALL)}
CHAMPIONS = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

def main():
    equity_rows, shares_rows = build_fact_rows()
    out = {"family": "vm-volscale", "program": "v12-completions",
           "construction": "B&SC exact formula (w=min(1,0.12/sigma_hat), monthly, "
                           "sigma_hat = shadow host book's own trailing 126d returns) "
                           "on champion V+M host; CONSTRUCTED",
           "pot": 100.0, "floor": 85.0}

    # ---------- integrity gate on v4 caches
    bars4 = {t: prices_v4(t) for t in UNIVERSE + ["SPY"]}
    eng4 = Engine(PriceBook(bars4), equity_rows, shares_rows)
    integ = {}
    for name, (ws, we) in (("CONT", ROADS["CONT"]), ("VAL", ROADS["VAL"])):
        r_off = eng4.run(ws, we, mode="plain")
        r_v5 = eng4.run(ws, we, mode="v5vol")
        integ[name] = {"off_final": round(r_off["final"], 2),
                       "v5vol_final": round(r_v5["final"], 2)}
        print(f"INTEGRITY {name}: off=${r_off['final']:,.2f} v5vol=${r_v5['final']:,.2f}",
              flush=True)
    out["integrity"] = integ

    # ---------- constructed roads on pxfull
    barsF = {t: prices_full(t) for t in UNIVERSE + ["SPY"]}
    pbF = PriceBook(barsF)
    engF = Engine(pbF, equity_rows, shares_rows)

    print("shadow: ranked ...", flush=True)
    ranked_rets, ranked_shadow = shadow_returns(engF, seed=None)
    placebo_rets = {}
    for seed in PLACEBO_SEEDS:
        placebo_rets[seed], _ = shadow_returns(engF, seed=seed)
        print(f"shadow: seed {seed} done", flush=True)
    out["shadow_ranked"] = ranked_shadow

    roads_out = {}
    for name, (ws, we) in ROADS.items():
        spy = spy_net(pbF, ws, we)
        naked = engF.run(ws, we, mode="plain")
        cons = engF.run(ws, we, mode="constructed", shadow_rets=ranked_rets)
        blk = {"window": [ws, we], "spy_net": round(spy, 2),
               "champion_vm": CHAMPIONS[name],
               "naked_host": diagnostics(naked),
               "constructed": diagnostics(cons),
               "constructed_curve": [[d, round(v, 4)] for d, v in cons["curve"]],
               "naked_curve": [[d, round(v, 4)] for d, v in naked["curve"]],
               "weights": [[d, s, w] for d, s, w in cons["weights"]]}
        finals = []
        rows = []
        for seed in PLACEBO_SEEDS:
            pr = engF.run(ws, we, mode="constructed", placebo_seed=seed,
                          shadow_rets=placebo_rets[seed])
            finals.append(pr["final"])
            rows.append({"seed": seed, "final": round(pr["final"], 2),
                         "halted": pr["halted"], "costs": round(pr["costs"], 2)})
        srt = sorted(finals)
        beaten = sum(1 for f in finals if f < cons["final"])
        blk["placebo"] = {"median": round(pct(srt, 0.5), 2),
                          "best": round(srt[-1], 2), "worst": round(srt[0], 2),
                          "halted_count": sum(1 for x in rows if x["halted"]),
                          "seeds_beaten": beaten, "rows": rows}
        roads_out[name] = blk
        print(f"{name}: constructed=${cons['final']:,.2f} naked=${naked['final']:,.2f} "
              f"SPY=${spy:,.2f} champ=${CHAMPIONS[name]:,.2f} "
              f"placebo {beaten}/20 median=${blk['placebo']['median']:,.2f} "
              f"maxDD={blk['constructed']['max_drawdown_pct']}% "
              f"mean_w={blk['constructed']['mean_w']}", flush=True)
    out["roads"] = roads_out

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
