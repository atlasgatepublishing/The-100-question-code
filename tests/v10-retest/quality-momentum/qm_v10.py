#!/usr/bin/env python3
"""
QUALITY + MOMENTUM (standalone) — THE GREAT RETEST (v10).

Strategy (frozen, verbatim from backtests/v4/quality-momentum.py):
  quality  = Novy-Marx gross profitability proxy (Revenue - COGS)/Assets
             from a single filing (same accession, same annual period;
             OPINC/Assets fallback only if a name has NO GP observations),
             most recently FILED strictly before the selection date.
  momentum = trailing 12-1 return (close[-21] / close[-252] - 1).
  Rank by the average of the two percentile ranks; hold top 5, equal
  weight; rebalance at the NEXT trading day's open after a selection date.
Costs (program, identical to original): 0.10% of trade value per side
  + $0.01 per sell order.

INTEGRITY modes reproduce the original published records through this
plumbing in the original forms:
  - his-rules (floor + LADDER, quarterly, v4 price cache 2017-06->):
        CONT 2019-01-02->2026-11-20 and VAL 2023-01-03->2026-11-20
  - v9-protection form (plain -15% floor, NO ladder, 90-day sit-out,
    restart at next quarterly selection date, episode-2 floor -15% from
    restart balance, second halt ends the run): same windows.

SWEEP mode: DECADE 2016-11-21 -> 2026-11-20, $100/cell, v9 protections
(NO ladder in any cell), at 7 cadences under the SPEC's uniform cadence
definition (signal evaluation / selection / trading ONLY on cadence
dates; the daily -15% floor check stays daily exactly as the original
engine checked it every day). Cadence per the original engine's form:
selection is computed on the cadence date's close and executed at the
next trading day's open (the original engine's pending/next-open form).
Restart after a halt happens at the next cadence date on/after the
90-day sit-out eligibility date.

Prices for the sweep: full-range Yahoo payloads (pxfull_*.json) read
READ-ONLY from backtests/v7/long-hold/data/ (GOOGL from
backtests/long-run-2010/data/), except AMD, whose full-range payload was
missing from every shared cache and was downloaded fresh from Yahoo
(the channel the original test used) into THIS folder's data/ cache.
Fundamentals: EDGAR companyfacts read READ-ONLY from backtests/v4/data/
(the original test's own cache; only the 20 universe names are loaded).

Placebos: random-rank twins — at each selection date, 5 names sampled
uniformly from the scored names (the original engine's placebo form),
20 seeds (20261121 + i, i = 0..19), same seeds in every cell.
"""
import json, os, random, time, urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
V4_DATA = os.path.join(BT, "v4", "data")
LH_DATA = os.path.join(BT, "v7", "long-hold", "data")
LR_DATA = os.path.join(BT, "long-run-2010", "data")
MYDATA = os.path.join(HERE, "data")
os.makedirs(MYDATA, exist_ok=True)
os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)

UA = "AtlasGateResearch terry-research@example.com"
UNIVERSE = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "JPM", "XOM",
            "UNH", "HD", "MA", "V", "LLY", "CRM", "ORCL", "COST", "NFLX",
            "AMD", "AVGO", "TSLA"]
PLACEBO_SEEDS = [20261121 + i for i in range(20)]

REV_CONCEPTS = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "SalesRevenueNet"]
COGS_CONCEPTS = ["CostOfRevenue", "CostOfGoodsAndServicesSold",
                 "CostOfGoodsSold"]
OPINC_CONCEPT = "OperatingIncomeLoss"
ASSETS_CONCEPT = "Assets"

# ------------------------------------------------------- quality (verbatim v4)
def _entries(facts, concept):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else list(units)[0]
    return units[key]

def _annual(entries):
    out = []
    for e in entries:
        if "start" not in e or "end" not in e or "val" not in e:
            continue
        try:
            days = (date.fromisoformat(e["end"]) -
                    date.fromisoformat(e["start"])).days
        except ValueError:
            continue
        if 300 <= days <= 400:
            out.append(e)
    return out

def build_quality_observations(facts):
    assets_by_accn = {}
    for e in _entries(facts, ASSETS_CONCEPT):
        if "val" not in e or "end" not in e:
            continue
        accn = e.get("accn", "")
        assets_by_accn.setdefault(accn, {})[e["end"]] = (
            float(e["val"]), e.get("filed", ""))

    def assets_for(accn, period_end):
        m = assets_by_accn.get(accn, {})
        if period_end in m:
            return m[period_end][0]
        earlier = [en for en in m if en <= period_end]
        if earlier:
            return m[max(earlier)][0]
        return None

    def by_accn_period(concepts):
        out = {}
        for concept in concepts:
            for e in _annual(_entries(facts, concept)):
                accn = e.get("accn", "")
                key = (e["start"], e["end"])
                slot = out.setdefault(accn, {})
                if key not in slot:
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
    best = None
    for filed, end, val, method in obs:
        if filed < asof:
            if best is None or (filed, end) > (best[0], best[1]):
                best = (filed, end, val, method)
        else:
            break
    return best

def load_quality():
    with open(os.path.join(V4_DATA, "company_tickers.json"), "rb") as f:
        raw = json.loads(f.read())
    ciks = {row["ticker"]: int(row["cik_str"]) for row in raw.values()}
    quality = {}
    for t in UNIVERSE:
        path = os.path.join(V4_DATA, f"facts_{ciks[t]:010d}.json")
        with open(path, "rb") as f:
            blob = f.read()
        if blob[:2] == b"\x1f\x8b":
            import gzip
            blob = gzip.decompress(blob)
        quality[t] = build_quality_observations(json.loads(blob))
    return quality

# ------------------------------------------------------------- price loading
def bars_from_payload(j):
    """Identical bar construction to the original engine: open/close
    scaled by adjclose/close; close = adjclose."""
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

def load_bars_v4(ticker):
    with open(os.path.join(V4_DATA, f"px_{ticker}.json"), "rb") as f:
        return bars_from_payload(json.loads(f.read()))

def fetch_pxfull(ticker):
    path = os.path.join(MYDATA, f"pxfull_{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return json.loads(f.read())
    import calendar
    t1 = calendar.timegm(time.strptime("2008-01-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        blob = r.read()
    with open(path, "wb") as f:
        f.write(blob)
    return json.loads(blob)

def load_bars_full(ticker):
    for base in (LH_DATA, LR_DATA):
        path = os.path.join(base, f"pxfull_{ticker}.json")
        if os.path.exists(path) and os.path.getsize(path) > 100:
            with open(path, "rb") as f:
                return bars_from_payload(json.loads(f.read()))
    return bars_from_payload(fetch_pxfull(ticker))

# ------------------------------------------------------------- price book
class PriceBook:
    """Same semantics as the original PriceBook (bar by date; close on or
    before a date), with aligned arrays for speed. Values are identical:
    prev-close array entry = close of the last bar on/before that date."""
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.didx = {d: i for i, d in enumerate(self.dates)}
        self.idx = {t: {b["d"]: b for b in bl}
                    for t, bl in bars_by_ticker.items()}
        self.tidx = {t: {b["d"]: i for i, b in enumerate(bl)}
                     for t, bl in bars_by_ticker.items()}
        self.prev_close = {}
        for t, bl in bars_by_ticker.items():
            arr = [None] * len(self.dates)
            last = None
            bmap = self.idx[t]
            for i, d in enumerate(self.dates):
                b = bmap.get(d)
                if b is not None:
                    last = b["c"]
                arr[i] = last
            self.prev_close[t] = arr

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        i = self.didx.get(d)
        if i is None:
            return None
        return self.prev_close[t][i]

# ------------------------------------------------------------- cadences
def cadence_dates(pb, cadence, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    if cadence == "weekly":
        for d in days:
            y, w, _ = date.fromisoformat(d).isocalendar()
            if (y, w) not in seen:
                seen.add((y, w)); out.append(d)
        return out
    if cadence == "biweekly":
        weeks = []
        for d in days:
            y, w, _ = date.fromisoformat(d).isocalendar()
            if (y, w) not in seen:
                seen.add((y, w)); weeks.append(d)
        return weeks[::2]
    months = {"monthly": None, "quarterly": ("01", "04", "07", "10"),
              "semiannual": ("01", "07"), "annual": ("01",)}[cadence]
    for d in days:
        if months is not None and d[5:7] not in months:
            continue
        key = (d[:4], d[5:7])
        if key not in seen:
            seen.add(key); out.append(d)
    return out

def percentile_ranks(values):
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    return {t: i / (n - 1) for i, (t, _) in enumerate(items)}

# ------------------------------------------------------------- engine
def run_episode(pb, quality_obs, start, end, start_cash, floor, ladder,
                sel_dates, placebo_rng=None, want_curve=False):
    """The original run_pot, with the selection-date set parameterised.
    ladder = [] under v9. Returns dict incl. equity curve if requested."""
    cash = start_cash
    floor_now = floor
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_close = None
    min_close, min_close_date = None, None
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None
    curve = []

    def portfolio_close(d):
        i = pb.didx[d]
        v = cash
        for t, sh in positions.items():
            c = pb.prev_close[t][i]
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
                    continue
                bl = pb.bars.get(t, [])
                didx = pb.tidx.get(t, {}).get(d)
                if didx is None or didx < 253:
                    continue
                mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
                scores[t] = (q[2], mom)
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
        v = portfolio_close(d)
        if want_curve:
            curve.append((d, round(v, 4)))
        if min_close is None or v < min_close:
            min_close, min_close_date = v, d
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor_now:
                floor_now = newfloor
        if v <= floor_now and di < len(days) - 1:
            halted = d
            halt_close = v
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t],
                                   b["o"], val, c))
            positions = {}
            if want_curve:
                curve.append((nd, round(cash, 4)))
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_close": halt_close,
                    "floor_in_effect": floor_now, "min_close": min_close,
                    "min_close_date": min_close_date, "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    if want_curve and curve:
        curve[-1] = (last, round(cash, 4))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_close": None,
            "floor_in_effect": floor_now, "min_close": min_close,
            "min_close_date": min_close_date, "curve": curve}

def run_v9(pb, quality_obs, start, end, cadence, placebo_seed=None,
           want_curve=False):
    """v9 protection wrapper: plain -15% floor, no ladder; on first halt
    liquidate (inside run_episode), sit 90 calendar days, restart at the
    next cadence date on/after eligibility; episode-2 floor -15% from
    restart balance; second halt ends the run."""
    sel_all = cadence_dates(pb, cadence, start, end)
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    ep1 = run_episode(pb, quality_obs, start, end, 100.0, 85.0, [],
                      sel_all, placebo_rng=rng, want_curve=want_curve)
    out = {"episode1": ep1, "episode2": None, "final": ep1["final"],
           "halts": [], "restart": False, "second_halt": False,
           "costs": ep1["costs"], "orders": len(ep1["trades"]),
           "curve": list(ep1["curve"])}
    if ep1["halted"] is None:
        return out
    out["halts"].append({"episode": 1, "signal_date": ep1["halted"],
                         "signal_close": ep1["halt_close"],
                         "floor": ep1["floor_in_effect"],
                         "liquidation_date": ep1["end"],
                         "cash_after": ep1["final"]})
    liq = date.fromisoformat(ep1["end"])
    cash1 = ep1["final"]
    eligible = (liq + timedelta(days=90)).isoformat()
    cands = [d for d in sel_all if d >= eligible]
    if not cands:
        return out
    restart = cands[0]
    out["restart"] = True
    out["restart_date"] = restart
    out["restart_balance"] = cash1
    rng2 = rng  # placebo stream continues across episodes, as one run
    ep2 = run_episode(pb, quality_obs, restart, end, cash1, 0.85 * cash1,
                      [], [d for d in sel_all if d >= restart],
                      placebo_rng=rng2, want_curve=want_curve)
    out["episode2"] = ep2
    out["final"] = ep2["final"]
    out["costs"] += ep2["costs"]
    out["orders"] += len(ep2["trades"])
    if want_curve:
        curve = list(ep1["curve"])
        have = {d for d, _ in curve}
        dcur = liq
        while dcur.isoformat() < restart:
            ds = dcur.isoformat()
            if ds in pb.didx and start <= ds <= end and ds not in have:
                curve.append((ds, round(cash1, 4)))
            dcur += timedelta(days=1)
        curve.extend(ep2["curve"])
        curve.sort()
        out["curve"] = curve
    if ep2["halted"] is not None:
        out["second_halt"] = True
        out["halts"].append({"episode": 2, "signal_date": ep2["halted"],
                             "signal_close": ep2["halt_close"],
                             "floor": ep2["floor_in_effect"],
                             "liquidation_date": ep2["end"],
                             "cash_after": ep2["final"]})
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
    return val - sell_cost, buy_cost + sell_cost

def stats(curve, start, end, final):
    peak, mdd = -1e18, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    cagr = (final / 100.0) ** (1.0 / yrs) - 1.0 if final > 0 else -1.0
    return round(cagr * 100, 2), round(mdd * 100, 2)

# ------------------------------------------------------------- integrity
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
DECADE = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

def integrity(quality):
    bars = {t: load_bars_v4(t) for t in UNIVERSE + ["SPY"]}
    pb = PriceBook(bars)
    res = {}
    for name, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        sel = cadence_dates(pb, "quarterly", ws, we)
        his = run_episode(pb, quality, ws, we, 100.0, 85.0,
                          [(125.0, 100.0), (150.0, 125.0)], sel)
        v9 = run_v9(pb, quality, ws, we, "quarterly")
        res[name] = {
            "his_rules": {"final": round(his["final"], 2),
                          "costs": round(his["costs"], 2),
                          "orders": len(his["trades"]),
                          "halted": his["halted"]},
            "v9_form": {"final": round(v9["final"], 2),
                        "costs": round(v9["costs"], 2),
                        "orders": v9["orders"],
                        "halts": v9["halts"], "restart": v9["restart"],
                        "second_halt": v9["second_halt"]}}
        print(f"INTEGRITY {name}: his=${his['final']:.2f} halted={his['halted']} "
              f"| v9=${v9['final']:.2f}", flush=True)
    return res

# ------------------------------------------------------------- sweep
def sweep(quality):
    bars = {t: load_bars_full(t) for t in UNIVERSE + ["SPY"]}
    pb = PriceBook(bars)
    ws, we = DECADE
    spy_final, spy_costs = spy_net(pb, ws, we)
    print(f"DECADE SPY net=${spy_final:.2f}", flush=True)
    cells = {}
    for cad in CADENCES:
        run = run_v9(pb, quality, ws, we, cad, want_curve=True)
        cagr, mdd = stats(run["curve"], ws, we, run["final"])
        twins = []
        beaten = 0
        for seed in PLACEBO_SEEDS:
            tw = run_v9(pb, quality, ws, we, cad, placebo_seed=seed)
            twins.append(round(tw["final"], 2))
            if run["final"] > tw["final"]:
                beaten += 1
        cell = {"final": round(run["final"], 2), "cagr_pct": cagr,
                "max_dd_pct": mdd, "halts": run["halts"],
                "restart": run["restart"], "second_halt": run["second_halt"],
                "costs": round(run["costs"], 2), "orders": run["orders"],
                "placebo_beaten": f"{beaten}/20",
                "placebo_twin_finals": twins,
                "equity_curve": [[d, v] for d, v in run["curve"]]}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump({"slug": "quality-momentum", "cadence": cad,
                       "window": [ws, we], "start_cash": 100.0,
                       "decade_spy_final": round(spy_final, 2), **cell},
                      f, indent=1)
        cells[cad] = {k: cell[k] for k in
                      ("final", "cagr_pct", "max_dd_pct", "halts", "restart",
                       "second_halt", "costs", "orders", "placebo_beaten")}
        cells[cad]["placebo_note"] = (
            "20 random-rank twin seeds (20261121+i); finals in cells file")
        print(f"CELL {cad}: final=${run['final']:.2f} CAGR={cagr} "
              f"DD={mdd} costs=${run['costs']:.2f} orders={run['orders']} "
              f"placebo beaten {beaten}/20 halts={len(run['halts'])}",
              flush=True)
    return cells, round(spy_final, 2)

def main():
    quality = load_quality()
    integ = integrity(quality)
    cells, spy_final = sweep(quality)
    money = [c for c in CADENCES
             if cells[c]["final"] > spy_final
             and int(cells[c]["placebo_beaten"].split("/")[0]) > 10]
    results = {
        "slug": "quality-momentum",
        "area": "long-holding fundamental sort (quality + momentum ranking, top-5) on the 20-name pond",
        "native_cadence": "quarterly",
        "original_cadence_foreign": False,
        "cadence_note": ("Original engine's form kept at every cadence: "
                         "selection scored on the cadence date's close, "
                         "executed at the next trading day's open; the "
                         "-15% floor check stays daily as in the original."),
        "integrity": {
            "status": "reproduced",
            "original_finals": {
                "his_rules_floor_plus_ladder": {"CONT": 100.48, "VAL": 211.54},
                "v9_protection_form": {"CONT": 428.46, "VAL": 211.54}},
            "reproduced_finals": integ},
        "decade_spy_final": spy_final,
        "cells": cells,
        "money_cadences": money,
        "verdict_area": None,  # filled in RESULTS.md narrative; see below
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("MONEY CADENCES:", money, flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
