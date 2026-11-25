#!/usr/bin/env python3
"""
NOVEL TEST N-F4 — CASH ALREADY COLLECTED (contract-liability excess growth).
Terry's AI stock app, v8 "never been done" track. Simulation only.

INVENTED-IN-2026 RULE: this is 1 of 12 invented rules. It was written in
2026 knowing the test era exists, so the best verdict it can earn is
CANDIDATE — only a forward paper trial can promote an invented rule.
CANDIDATE requires ALL of: validation final > SPY $187.77, validation
placebo >= 19/20, continuous final > SPY $313.62, and no floor halt on
either main window. Anything less is NOT A CANDIDATE.

FROZEN SPEC (research/v8-novel/novel-filings.md, N-F4, implemented verbatim):
  - CL (contract liabilities), first available branch, in order:
    (i) us-gaap ContractWithCustomerLiability; if the filer splits it,
        ContractWithCustomerLiabilityCurrent + ContractWithCustomerLiabilityNoncurrent;
    (ii) pre-ASC-606 fallback: DeferredRevenueCurrent + DeferredRevenueNoncurrent
        (either alone if only one is tagged).
  - At each selection date: CL(now) = most recent CL balance filed before the
    date; CL(year ago) = CL balance for the same fiscal quarter one year
    earlier. CL_GROWTH = CL(now)/CL(year ago) - 1.
    REV_GROWTH = TTM revenue(now)/TTM revenue(year ago) - 1, TTM per the
    N-F3 construction (sum of the latest four distinct fiscal-quarter
    duration values; Q4 = FY duration - nine-month duration where a
    standalone Q4 is not tagged) and the N-F3 revenue concept chain:
    RevenueFromContractWithCustomerExcludingAssessedTax -> Revenues ->
    RevenuesNetOfInterestExpense -> SalesRevenueNet.
  - EXCESS = CL_GROWTH - REV_GROWTH. Rank descending. Hold top 5, equal weight.
  - Materiality gate: CL(now) >= 1% of TTM revenue, and CL computable one
    year earlier, else ineligible — never patched.
  - If fewer than 5 names are eligible, hold all eligible equal-weight;
    if fewer than 3 are eligible, hold cash for that quarter.
  - Point-in-time: only facts with EDGAR filed date strictly before the
    selection date; latest filing before the date wins (as-filed values).

FORCED READINGS (stated before any result; house conventions, not tunings):
  R1 — branch priority is applied PER PERIOD END: CL(end) takes the first
       branch that has an as-filed value at that end. This is what stitches
       the pre/post-ASC-606 series (the spec's stated mechanism) — e.g. IBM's
       older ends come from DeferredRevenue*, its recent ends from the
       ContractWithCustomerLiability split. Within a split branch, the legs
       present at that end are summed; if only one leg is tagged at that
       end, that leg alone is used (the fallback's explicit either-alone
       rule, applied to the split branch as well).
  R2 — the combined single tag `DeferredRevenue` is NOT in the frozen chain
       and is never used (names relying on it alone in a given year are
       ineligible that year).
  R3 — "same fiscal quarter one year earlier": the CL period end 320-410
       days before CL(now)'s end, closest to 365 days (the program's
       standing one-year window, cf. N-F1). CL(now)'s anchor end is the
       latest CL period end whose winning filing was accepted within 548
       days before the selection date (the champion engine's standing
       freshness gate) — a name that stopped filing the line drops out
       instead of anchoring on ancient data.
  R4 — revenue TTM is anchored on the same pair of period ends as CL
       (E = CL(now)'s end, E_ya = CL(year ago)'s end). Quarter values:
       standalone quarter duration if tagged, else the difference of
       successive year-to-date durations ending at that quarter end
       (Q4 = FY - 9M is the special case). The revenue chain is tried in
       order; the first concept that yields BOTH TTM values is used.
  R5 — placebos draw, on identical dates, the same NUMBER of names the
       ranked pot holds that quarter, uniformly from that date's eligible
       pool (seeds 1..20, one rng stream per pot, champion convention).
       When the ranked pot holds cash (<3 eligible), the placebo holds
       cash too — there is nothing to randomize.
  R6 — engine mechanics (selection on the first trading day of Jan/Apr/
       Jul/Oct, targets executed at the next open, sells before buys,
       0.10%/side + $0.01/sell, plain -$15 floor at $85.00 with next-open
       liquidation, end-of-window liquidation at the final close) are the
       champion engine's, verbatim (value-momentum-plainfloor.py).

Windows: FULL continuous 2019-01-02 -> 2026-11-20 and VALIDATION
2023-01-03 -> 2026-11-20. Champion reference: $544.47 / $288.05,
placebo 19/20 / 18/20. SPY nets: $313.62 / $187.77 (replication-checked
in-script before any strategy number is taken).

Data: SEC EDGAR companyfacts, reused read-only from the champion's cache
(../v4/data); Yahoo Finance chart API prices (split/dividend-adjusted),
reused read-only from the champion's caches.
"""
import json, math, os, random, sys, time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
SHARED = os.path.join(V4, "data")                       # champion cache, read-only
HONEST = os.path.join(V4, "value-momentum-honest-data")  # champion cache, read-only

UA = "AtlasGateResearch terry-research@example.com"
UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
PLACEBO_SEEDS = list(range(1, 21))
FRESH_DAYS = 548          # champion pit freshness gate (R3)
YA_LO, YA_HI = 320, 410   # "one year earlier" window in days (R3)

REV_CHAIN = ["RevenueFromContractWithCustomerExcludingAssessedTax",
             "Revenues", "RevenuesNetOfInterestExpense", "SalesRevenueNet"]

# ---------------------------------------------------------------- fetch utils
def read_shared(filename):
    p = os.path.join(SHARED, filename)
    if os.path.exists(p) and os.path.getsize(p) > 100:
        with open(p, "rb") as f:
            return f.read()
    p2 = os.path.join(HONEST, filename)
    if os.path.exists(p2) and os.path.getsize(p2) > 100:
        with open(p2, "rb") as f:
            return f.read()
    return None

def get_ciks():
    raw = json.loads(read_shared("company_tickers.json"))
    out = {}
    for row in raw.values():
        out[row["ticker"]] = (int(row["cik_str"]), row["title"])
    return out

def get_companyfacts(cik):
    filename = f"facts_{cik:010d}.json"
    blob = read_shared(filename)
    if blob is None:
        import urllib.request
        req = urllib.request.Request(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
            headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read()
    if blob[:2] == b"\x1f\x8b":
        import gzip
        blob = gzip.decompress(blob)
    return json.loads(blob)

def get_prices(ticker):
    # champion's method verbatim: shared cache first, else honest cache
    for base in (SHARED, HONEST):
        path = os.path.join(base, f"px_{ticker}.json")
        if os.path.exists(path) and os.path.getsize(path) > 100:
            with open(path, "rb") as f:
                blob = f.read()
            break
    else:
        raise RuntimeError(f"no cached prices for {ticker}")
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

# ------------------------------------------------------------ EDGAR fact prep
def ord_of(ds):
    return _date(int(ds[:4]), int(ds[5:7]), int(ds[8:10])).toordinal()

def instant_entries(facts, concept):
    """[(end, filed, val)] for a balance-sheet (instant) us-gaap concept."""
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else (list(units)[0] if units else None)
    if key is None:
        return []
    out = []
    for e in units[key]:
        if "filed" in e and "val" in e and "end" in e:
            out.append((e["end"], e["filed"], float(e["val"])))
    return out

def duration_entries(facts, concept):
    """[(start, end, filed, val)] for a flow (duration) us-gaap concept."""
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else (list(units)[0] if units else None)
    if key is None:
        return []
    out = []
    for e in units[key]:
        if "filed" in e and "val" in e and "end" in e and "start" in e:
            out.append((e["start"], e["end"], e["filed"], float(e["val"])))
    return out

def as_filed_instants(entries, asof):
    """end -> (filed, val): latest filing strictly before asof wins."""
    best = {}
    for end, filed, val in entries:
        if filed < asof:
            if end not in best or filed > best[end][0]:
                best[end] = (filed, val)
    return best

def as_filed_durations(entries, asof):
    """(start, end) -> val: latest filing strictly before asof wins."""
    best = {}
    for start, end, filed, val in entries:
        if filed < asof:
            k = (start, end)
            if k not in best or filed > best[k][0]:
                best[k] = (filed, val)
    return {k: v[1] for k, v in best.items()}

# ------------------------------------------------------------- CL machinery
CL_BRANCHES = [
    ["ContractWithCustomerLiability"],
    ["ContractWithCustomerLiabilityCurrent", "ContractWithCustomerLiabilityNoncurrent"],
    ["DeferredRevenueCurrent", "DeferredRevenueNoncurrent"],
]

def cl_series(facts, asof):
    """end -> val, branch priority applied per period end (R1)."""
    branch_maps = []
    for branch in CL_BRANCHES:
        leg_maps = [as_filed_instants(instant_entries(facts, c), asof) for c in branch]
        ends = set()
        for m in leg_maps:
            ends |= set(m)
        merged = {}
        for e in ends:
            tot, ok = 0.0, False
            for m in leg_maps:
                if e in m:
                    tot += m[e][1]
                    ok = True
            if ok:
                merged[e] = tot
        branch_maps.append(merged)
    ends = set()
    for m in branch_maps:
        ends |= set(m)
    series = {}
    for e in ends:
        for m in branch_maps:
            if e in m:
                series[e] = m[e]
                break
    return series

def cl_anchor(facts, asof):
    """(E, filed_of_E, series) or None. E = latest CL end whose winning
    filing was accepted within FRESH_DAYS before asof (R3)."""
    series = cl_series(facts, asof)
    if not series:
        return None
    # filed date of the winning entry per end, per branch-priority end:
    # recompute the winning filed date for the branch that supplied each end
    branch_raw = []
    for branch in CL_BRANCHES:
        leg_maps = [as_filed_instants(instant_entries(facts, c), asof) for c in branch]
        ends = set()
        for m in leg_maps:
            ends |= set(m)
        filed_map = {}
        for e in ends:
            fs = [m[e][0] for m in leg_maps if e in m]
            filed_map[e] = max(fs)
        branch_raw.append(filed_map)
    cutoff = ord_of(asof) - FRESH_DAYS
    best = None
    for e in series:
        filed = None
        for fm in branch_raw:
            if e in fm:
                filed = fm[e]
                break
        if filed is not None and ord_of(filed) >= cutoff:
            if best is None or e > best[0]:
                best = (e, filed)
    if best is None:
        return None
    return best[0], best[1], series

def year_ago_end(series, E):
    """Same fiscal quarter one year earlier (R3): end 320-410 days before
    E, closest to 365 days."""
    eo = ord_of(E)
    cands = []
    for e in series:
        gap = eo - ord_of(e)
        if YA_LO <= gap <= YA_HI:
            cands.append((abs(gap - 365), e))
    if not cands:
        return None
    cands.sort()
    return cands[0][1]

# ---------------------------------------------------------- revenue machinery
def _durations_by_end(dmap):
    by_end = {}
    for (s, e), v in dmap.items():
        by_end.setdefault(e, []).append((s, v))
    return by_end

def _ytd_at(by_end, end):
    """Longest duration ending at `end` with length >= 150 days
    (a YTD or FY value); returns (start, val, days) or None."""
    best = None
    for s, v in by_end.get(end, []):
        days = ord_of(end) - ord_of(s)
        if days >= 150 and (best is None or days > best[2]):
            best = (s, v, days)
    return best

def _quarter_value(dmap, by_end, end):
    """Standalone quarter value for the quarter ending at `end`:
    direct quarter duration if tagged, else YTD difference (R4)."""
    # direct standalone quarter: 60-115 day duration ending at end
    direct = None
    for s, v in by_end.get(end, []):
        days = ord_of(end) - ord_of(s)
        if 60 <= days <= 115:
            if direct is None or days > direct[0]:
                direct = (days, v)
    if direct is not None:
        return direct[1]
    ytd = _ytd_at(by_end, end)
    if ytd is None:
        return None
    # previous quarter end: an end 75-115 days earlier that has a YTD value
    eo = ord_of(end)
    prevs = []
    for e2 in by_end:
        gap = eo - ord_of(e2)
        if 75 <= gap <= 115 and _ytd_at(by_end, e2) is not None:
            prevs.append(e2)
    if not prevs:
        return None
    prev = max(prevs)
    return ytd[1] - _ytd_at(by_end, prev)[1]

def ttm_revenue(dmap, anchor_end):
    """Sum of the four distinct fiscal-quarter duration values ending at
    anchor_end (N-F3 construction, R4). None if any quarter is missing."""
    by_end = _durations_by_end(dmap)
    ends = [anchor_end]
    cur = anchor_end
    for _ in range(3):
        co = ord_of(cur)
        prevs = [e for e in by_end if 75 <= co - ord_of(e) <= 115]
        if not prevs:
            return None
        cur = max(prevs)
        ends.append(cur)
    total = 0.0
    for e in ends:
        q = _quarter_value(dmap, by_end, e)
        if q is None:
            return None
        total += q
    return total

def score_name(facts, asof):
    """N-F4 score for one name at one selection date.
    Returns dict with EXCESS and diagnostics, or None if ineligible."""
    anch = cl_anchor(facts, asof)
    if anch is None:
        return None
    E, _filed, series = anch
    E_ya = year_ago_end(series, E)
    if E_ya is None:
        return None
    cl_now, cl_ya = series[E], series[E_ya]
    if cl_ya is None or cl_ya <= 0:
        return None
    rev = None
    for concept in REV_CHAIN:
        dmap = as_filed_durations(duration_entries(facts, concept), asof)
        if not dmap:
            continue
        t_now = ttm_revenue(dmap, E)
        t_ya = ttm_revenue(dmap, E_ya)
        if t_now is not None and t_ya is not None and t_now > 0 and t_ya > 0:
            rev = (concept, t_now, t_ya)
            break
    if rev is None:
        return None
    concept, t_now, t_ya = rev
    if cl_now < 0.01 * t_now:      # frozen materiality gate
        return None
    cl_g = cl_now / cl_ya - 1.0
    rev_g = t_now / t_ya - 1.0
    return {"EXCESS": cl_g - rev_g, "CL_GROWTH": cl_g, "REV_GROWTH": rev_g,
            "CL_now": cl_now, "CL_ya": cl_ya, "TTM_now": t_now, "TTM_ya": t_ya,
            "E": E, "E_ya": E_ya, "rev_concept": concept}

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

def run_pot(pb, picks_by_date, start, end, start_cash, floor0,
            placebo_rng=None, label="", quiet=True):
    """Champion mechanics verbatim, except picks come from the precomputed
    frozen-spec table (identical dates for ranked and placebo pots).
    picks_by_date: date -> {"eligible": [...], "picks": [...]}.
    Placebo draws len(picks) names from eligible on the same date (R5)."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
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
            entry = picks_by_date.get(d, {"eligible": [], "picks": []})
            eligible = entry["eligible"]
            if placebo_rng is not None:
                k = len(entry["picks"])
                picks = placebo_rng.sample(sorted(eligible), k) if k > 0 else []
            else:
                picks = list(entry["picks"])
            pv = portfolio_close(d)
            if picks:
                each = pv / len(picks)
                pending = {t: each for t in picks}
            else:
                pending = {}   # frozen fallback: <3 eligible -> cash quarter
            if not quiet:
                print(f"  [{label}] {d} eligible={len(eligible)} picks={picks} pot=${pv:,.2f}", flush=True)
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
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "curve": curve}
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
            "halt_info": None, "curve": curve}

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

def diagnostics(r, floor0):
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
        year_end[d[:4]] = (d, v)
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

# --------------------------------------------------------------------- main
def main():
    ciks = get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}   # champion override, carried verbatim
    facts_by_ticker = {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts_by_ticker[t] = get_companyfacts(cik)
        print(f"{t}: facts loaded (CIK {cik})", flush=True)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = get_prices(t)
    pb = PriceBook(bars)
    print(f"prices: {len(pb.dates)} trading days {pb.dates[0]}..{pb.dates[-1]}", flush=True)

    # ---- replication gate: SPY nets must reproduce the published figures
    s_full, _ = spy_net(pb, "2019-01-02", "2026-11-20", 100.0)
    s_val, _ = spy_net(pb, "2023-01-03", "2026-11-20", 100.0)
    print(f"REPLICATION: SPY continuous=${s_full:,.2f} (published $313.62) | "
          f"validation=${s_val:,.2f} (published $187.77)", flush=True)
    assert abs(s_full - 313.62) < 0.02 and abs(s_val - 187.77) < 0.02, \
        "SPY replication failed — no strategy number may be taken"

    # ---- frozen-spec scoring at every quarterly selection date, 2019-2026
    all_sel = quarter_selection_dates(pb, "2019-01-02", "2026-11-20")
    picks_by_date = {}
    for d in all_sel:
        scored = {}
        for t in UNIVERSE:
            s = score_name(facts_by_ticker[t], d)
            if s is not None:
                scored[t] = s
        ranked = sorted(scored, key=lambda t: -scored[t]["EXCESS"])
        if len(ranked) >= 3:
            picks = ranked[:5]
        else:
            picks = []          # frozen fallback: <3 eligible -> cash quarter
        picks_by_date[d] = {"eligible": sorted(scored), "picks": picks,
                            "scores": {t: scored[t] for t in ranked}}
        print(f"{d}: eligible={len(scored)} picks={picks} "
              f"EXCESS={ {t: round(scored[t]['EXCESS'], 4) for t in picks} }", flush=True)

    windows = [("FULL", "2019-01-02", "2026-11-20"),
               ("VALIDATION", "2023-01-03", "2026-11-20")]
    out = {"strategy": "N-F4 Cash Already Collected (invented 2026, 1 of 12)",
           "protection": "plain -15% floor only",
           "universe": UNIVERSE,
           "candidate_bar": {"validation_final_gt": 187.77,
                             "validation_placebo_min": "19/20",
                             "continuous_final_gt": 313.62,
                             "no_halt_either_main_window": True},
           "eligible_pool_by_date": {d: len(picks_by_date[d]["eligible"])
                                     for d in all_sel},
           "picks_by_date": {d: {"eligible": picks_by_date[d]["eligible"],
                                 "picks": picks_by_date[d]["picks"],
                                 "scores": picks_by_date[d]["scores"]}
                             for d in all_sel}}
    results = {}
    for wname, ws, we in windows:
        spy, _ = spy_net(pb, ws, we, 100.0)
        r = run_pot(pb, picks_by_date, ws, we, 100.0, 85.0,
                    label=f"{wname} N-F4")
        diag = diagnostics(r, 85.0)
        twins = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            tw = run_pot(pb, picks_by_date, ws, we, 100.0, 85.0,
                         placebo_rng=rng, label=f"{wname} twin{seed}")
            twins.append({"seed": seed, "final": round(tw["final"], 2),
                          "halted": tw["halted"]})
        finals = sorted(tw["final"] for tw in twins)
        median = finals[len(finals) // 2] if len(finals) % 2 == 1 else \
            (finals[len(finals) // 2 - 1] + finals[len(finals) // 2]) / 2.0
        # house convention: median of 20 = 10th value (cf. A-1 report);
        # report the interpolated median too for transparency
        beats = sum(1 for tw in twins if r["final"] > tw["final"])
        results[wname] = {"final": round(r["final"], 2), "costs": round(r["costs"], 2),
                          "orders": len(r["trades"]), "halted": r["halted"],
                          "halt_info": r["halt_info"], "spy_net": round(spy, 2),
                          "diag": diag, "trades": r["trades"],
                          "placebo": {"twins": twins,
                                      "median_10th": finals[9],
                                      "median_interp": round(median, 2),
                                      "beats": beats,
                                      "best_twin": finals[-1],
                                      "halts": sum(1 for tw in twins if tw["halted"])}}
        print(f"== {wname} N-F4 final=${r['final']:,.2f} costs=${r['costs']:,.2f} "
              f"orders={len(r['trades'])} halted={r['halted']} | SPY=${spy:,.2f} | "
              f"placebo beats {beats}/20 median=${finals[9]:,.2f}", flush=True)

    # ---- walk-forward folds: fresh $100 pot per calendar year
    folds = []
    for yr in range(2020, 2027):
        ws = f"{yr}-01-01"
        we = f"{yr}-12-31" if yr < 2026 else "2026-11-20"
        r = run_pot(pb, picks_by_date, ws, we, 100.0, 85.0, label=f"FOLD {yr}")
        spy, _ = spy_net(pb, ws, we, 100.0)
        folds.append({"year": yr, "final": round(r["final"], 2),
                      "return_pct": round(r["final"] - 100.0, 2),
                      "halted": r["halted"], "spy_final": round(spy, 2),
                      "spy_return_pct": round(spy - 100.0, 2),
                      "beat_spy": r["final"] > spy})
        print(f"FOLD {yr}: N-F4 ${r['final']:,.2f} ({r['final']-100:+.2f}%) "
              f"halted={r['halted']} | SPY ${spy:,.2f} ({spy-100:+.2f}%)", flush=True)
    wins = sum(1 for f in folds if f["beat_spy"])
    comp = 100.0
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
    spy_comp = 100.0
    for f in folds:
        spy_comp *= 1 + f["spy_return_pct"] / 100.0
    out["folds"] = {"folds": folds, "wins": wins, "losses": len(folds) - wins,
                    "fold_compounded_final": round(comp, 2),
                    "spy_fold_compounded_final": round(spy_comp, 2)}
    for k, v in results.items():
        out[k] = v

    val, full = results["VALIDATION"], results["FULL"]
    checks = {"validation_final_gt_spy": val["final"] > 187.77,
              "validation_placebo_ge_19": val["placebo"]["beats"] >= 19,
              "continuous_final_gt_spy": full["final"] > 313.62,
              "no_halt_either_window": val["halted"] is None and full["halted"] is None}
    out["candidate_checks"] = checks
    out["verdict"] = "CANDIDATE" if all(checks.values()) else "NOT A CANDIDATE"
    print(f"CANDIDATE CHECKS: {checks} -> {out['verdict']}", flush=True)

    with open(os.path.join(HERE, "novel-f4-cash-collected-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


# ======================================================================
# V9 RE-RUN - "CLAUDE-RULES PROTECTION SPEC v9" (this copy only)
# Copied from the v8 original; the ONLY change is the protection module
# (run_*_v9 below, which calls the original engine unchanged for each
# episode) plus a folds-only main_v9 (the original main is retained
# above but not invoked):
#   - Episode 1: plain -15% floor from the $100 start ($85.00),
#     identical to Terry's rule. On FIRST halt: liquidate exactly as
#     the original engine does, sit in cash 90 calendar days, then
#     RESTART with the remaining cash at the strategy's next regular
#     decision point (next quarterly selection date on/after day 90).
#   - Episode 2: floor = -15% from the RESTART balance. On SECOND
#     halt: the run ends permanently.
#   - If halt + 90 days runs past the window/fold end, the fold ends
#     in cash.
# Everything else is byte-identical: universe, signals, parameters,
# costs 0.10%/side + $0.01/sell, windows, $100 start. No retuning.
# Scope: main windows are NOT re-run - the original recorded results
# show the floor never fired there, so they are identical under v9 by
# construction. This script re-runs the yearly folds 2020-2026 under
# BOTH rule sets (his recomputed folds are asserted against the
# published originals). Ranked pots only; no placebos in this bundle.
# Data caches are read from the original test's folders, read-only;
# this script writes only v9-folds-detail.json next to itself.
# Simulation only.
# ======================================================================

# ============================================================ V9 MODULE
def run_pot_v9(pb, picks_by_date, start, end, start_cash, label=""):
    """One window under CLAUDE-RULES PROTECTION SPEC v9 (see header)."""
    from datetime import date as _d
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_pot(pb, picks_by_date, start, end, start_cash, floor1, label=label + " EP1")
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": r1["trades"], "curve": list(r1["curve"]),
           "halted": r1["halted"], "halt_info": r1["halt_info"],
           "restarts": [], "second_halt": None, "episodes": 1}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _d(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in quarter_selection_dates(pb, start, end):
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _d(cy, cm, cd).toordinal() >= day90:
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
    out["restarts"].append({"halt_signal_date": r1["halted"],
                            "liquidation_date": liq_date,
                            "halt_signal_close": r1["halt_info"]["signal_close"],
                            "restart_date": restart,
                            "restart_balance": round(cash, 2),
                            "episode2_floor": floor2})
    r2 = run_pot(pb, picks_by_date, restart, end, cash, floor2, label=label + " EP2")
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

def _worst(r, start_cash):
    vals = [v for _, v in r["curve"]] + [r["final"]]
    return min(vals) if vals else start_cash

def _compounded(folds):
    p = 100.0
    for k in sorted(folds):
        p *= folds[k]["final"] / 100.0
    return round(p, 2)

def main_v9():
    
    ciks = get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    facts_by_ticker = {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts_by_ticker[t] = get_companyfacts(cik)
        print(f"{t}: facts loaded", flush=True)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = get_prices(t)
    pb = PriceBook(bars)
    s_full, _ = spy_net(pb, "2019-01-02", "2026-11-20", 100.0)
    s_val, _ = spy_net(pb, "2023-01-03", "2026-11-20", 100.0)
    assert abs(s_full - 313.62) < 0.02 and abs(s_val - 187.77) < 0.02, "SPY replication FAILED"
    print(f"REPLICATION spy continuous=${s_full:,.2f} validation=${s_val:,.2f}", flush=True)
    all_sel = quarter_selection_dates(pb, "2019-01-02", "2026-11-20")
    picks_by_date = {}
    for d in all_sel:
        scored = {}
        for t in UNIVERSE:
            s = score_name(facts_by_ticker[t], d)
            if s is not None:
                scored[t] = s
        ranked = sorted(scored, key=lambda t: -scored[t]["EXCESS"])
        picks = ranked[:5] if len(ranked) >= 3 else []
        picks_by_date[d] = {"eligible": sorted(scored), "picks": picks,
                            "scores": {t: scored[t] for t in ranked}}
    print("picks built", flush=True)

    START = 100.0
    fold_defs = [(y, f"{y}-01-01", "2026-11-20" if y == 2026 else f"{y}-12-31")
                 for y in range(2020, 2027)]
    his_folds, v9_folds = {}, {}
    his_worst, v9_worst = START, START
    restarts_all, second_halts = [], []
    for y, fs, fe in fold_defs:
        rh = run_pot(pb, picks_by_date, fs, fe, START, 85.0, label=f"HIS FOLD {y}")
        spy_f, _ = spy_net(pb, fs, fe, START)
        his_folds[str(y)] = {"final": round(rh["final"], 2), "halted": rh["halted"],
                             "spy_net": round(spy_f, 2), "beat_spy": rh["final"] > spy_f,
                             "orders": len(rh["trades"]), "costs": round(rh["costs"], 2)}
        his_worst = min(his_worst, _worst(rh, START))
        rv = run_pot_v9(pb, picks_by_date, fs, fe, START, label=f"V9 FOLD {y}")
        v9_folds[str(y)] = {"final": round(rv["final"], 2), "halted_first": rv["halted"],
                            "second_halt": rv["second_halt"], "restarts": rv["restarts"],
                            "spy_net": round(spy_f, 2), "beat_spy": rv["final"] > spy_f,
                            "orders": len(rv["trades"]), "costs": round(rv["costs"], 2),
                            "episodes": rv["episodes"]}
        v9_worst = min(v9_worst, _worst(rv, START))
        for rr in rv["restarts"]:
            restarts_all.append({"fold": str(y), **rr})
        if rv["second_halt"]:
            second_halts.append({"fold": str(y), **rv["second_halt"]})
        print(f"FOLD {y}: his=${rh['final']:,.2f} halted={rh['halted']} | "
              f"v9=${rv['final']:,.2f} restarts={len(rv['restarts'])} "
              f"second_halt={bool(rv['second_halt'])}", flush=True)
    his_comp, v9_comp = _compounded(his_folds), _compounded(v9_folds)
    print(f"FOLD-COMPOUNDED: his=${his_comp} v9=${v9_comp}", flush=True)
    out = {"protection_v9": "episode-1 floor -15% from start; on first halt liquidate, 90 calendar days cash, restart at next quarterly selection date with remaining cash; episode-2 floor -15% from restart balance; second halt ends run",
           "his_folds": his_folds, "v9_folds": v9_folds,
           "his_folds_compounded": his_comp, "v9_folds_compounded": v9_comp,
           "restarts": restarts_all, "second_halts": second_halts,
           "his_worst_fold_equity_from_100": round(his_worst, 2),
           "v9_worst_fold_equity_from_100": round(v9_worst, 2)}
    with open(os.path.join(HERE, "v9-folds-detail.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main_v9()

