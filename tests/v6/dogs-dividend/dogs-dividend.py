#!/usr/bin/env python3
"""
DIVIDEND YIELD ("DOGS OF THE DOW" FAMILY) — Terry's AI stock app.
Simulation only. NO parameter tuning: the spec below is run ONCE, exactly
as described, and judged against the promoted champion's published numbers.

THE RULE (published, decades-old family — Dogs of the Dow / high-yield
Dow investing, in Terry's program format):
  - Universe: the honest point-in-time top-30 as of Nov 2016 (the champion
    engine's UNIVERSE, imported verbatim from
    ~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py).
  - At each quarterly selection (first trading day of Jan/Apr/Jul/Oct),
    rank the scoreable names by TRAILING DIVIDEND YIELD and hold the
    top 5, equal weight; rebalance at the next open.
  - $100 pot, costs 0.10% of trade value per side + $0.01 per sell order,
    PLAIN -15% floor only ($85; close at/below floor -> liquidate at next
    open, run ends). Identical mechanics to the champion engine.

DIVIDEND YIELD — POINT-IN-TIME, EDGAR ONLY:
  - Source: SEC EDGAR companyfacts, units 'USD/shares', concepts
    CommonStockDividendsPerShareDeclared (preferred) and
    CommonStockDividendsPerShareCashPaid (fallback), applied uniformly:
    Declared is tried first for every name at every selection; CashPaid
    only if Declared yields no qualifying row.
  - Trailing DPS at selection date d = the sum of the FOUR most recent
    distinct quarterly-duration rows (period length 60-100 days,
    deduped by period end, latest-filed value wins) filed strictly
    before d, requiring the latest period end to be within 200 days
    of d and the four ends to span at most 400 days. If a name has no
    qualifying quarterly set in either concept, the fallback is the
    ANNUAL-duration row (300-400 days) with the latest period end
    among rows filed strictly before d whose end is within 548 days
    of d (the champion engine's ~18-month freshness gate).
  - Amounts are converted to final share units using only GENUINE
    split events from the cached Yahoo data. Yahoo also records
    spinoffs as 'splits' with thousandths ratios (T/WarnerMedia
    1324:1000, GE/GEHC 1281:1000, GE/GEV 1253:1000, MMM/Solventum
    1196:1000, PFE/Viatris 1054:1000, IBM/Kyndryl 1046:1000,
    GE/Wabtec 104:100); a spinoff does not change the share unit a
    past dividend was declared in, so those events never rescale
    per-share amounts. Mechanical rule: a split event is genuine iff
    numerator and denominator are both <= 25 (AAPL 4:1, WMT 3:1,
    GE 1:8 reverse, GOOGL/AMZN 20:1, NFLX 10:1 qualify; every
    spinoff pseudo-split is xxxx:1000 or 104:100 and does not).
  - Yield = trailing DPS / the name's contemporaneous quoted price on
    the selection day — what a buyer actually faced. Yahoo's quote
    closes are already split-adjusted (final share units, matching
    the converted DPS), but they are ALSO restated for later
    spinoffs; the denominator therefore undoes only the post-date
    spinoff restatements (the pseudo-split events above), restoring
    the price as quoted on the day.
  - Known data limitation, stated once here: DIS's CashPaid quarterly
    rows repeat its semiannual rate in every quarter, so DIS's
    trailing sum overstates its true yield roughly twofold in
    2018-2020 (its annual Declared rows are filed too late to guard
    those quarters point-in-time). DIS's overstated yield (~3%)
    still ranks mid-pool; the run's pool log verifies it is never
    selected into the top 5, so the artifact is inert for the result.
  - A name with no qualifying row in either concept is EXCLUDED from
    that quarter's pool and the exclusion is logged (AMZN, BRK-B and
    NFLX have no per-share dividend facts at all — true non-payers;
    GOOGL and META enter the pool only after their 2024 dividend
    initiations are filed; DIS drops out while its annual record is
    stale, which covers its 2020-2023 suspension).

PRICE BASIS — WHY THIS TEST HAS TWO PRICE BOOKS:
  The champion engine's cached prices are Yahoo ADJCLOSE (total-return:
  dividends and splits are already folded into the price path). Judging
  a dividend strategy on that basis while ALSO crediting cash dividends
  would pay every dividend TWICE. So the judged runs use basis B:
  prices adjusted for splits and spinoffs/distributions but NOT for
  dividends, reconstructed from the same cached Yahoo files as
      priceB(t) = adjclose(t) / D(t),
      D(t) = product over dividend events with ex-date after t of
             (1 - amount / quote close on the last trading day before
             the ex-date; Yahoo's quote closes and event amounts are
             both split-adjusted, so the factors are consistent)
  (exactly Yahoo's own dividend adjustment, divided back out; splits
  and spinoffs such as T/WarnerMedia and GE/GEHC stay adjusted, so
  there are no fake crashes at those events, while genuine ex-dividend
  price drops remain in the series). Opens are scaled by the same
  close ratio the champion engine uses.
  ASYMMETRY, STATED AS INSTRUCTED: the SPY comparison is computed with
  the champion engine's own spy_net on the ORIGINAL adjusted prices —
  the identical basis that produced the published $313.62 / $187.77 —
  so SPY's dividends are embedded in its price path while this
  strategy's dividends arrive as explicit cash credits (below). Both
  sides are total-return economically; the difference is mechanical,
  and the SPY figures replicate the published ones to the cent.
  A cross-check run of the ranked strategy on the original adjusted
  basis (dividends embedded, NO cash credits) is reported as a
  secondary line so the two accountings can be compared.

DIVIDEND CASH CREDITS (the judged runs):
  - Credits are estimated from EDGAR declared/paid per-share amounts
    (the task's instruction), NOT from Yahoo's event list (Yahoo events
    are used only as plumbing to strip dividend adjustments out of the
    price basis above).
  - Per name, distinct quarterly-duration periods (60-100 days) are
    collected from both concepts (Declared preferred per period end,
    dedupe by period end, latest-filed value wins). Each distinct
    period end is ONE credit of that period's per-share amount
    (split-adjusted to final units), credited on the first trading
    day on or after the period end, to the shares held entering that
    day. Crediting at period end is an estimate — actual pay dates
    fall inside the quarter or just after it; totals over any full
    year are exact.
  - Consistency guard: where an annual row covers a span, if the
    quarterly credits inside that span sum to a total differing from
    the annual total by more than 25% (the DIS repeated-rate case),
    or if there are no quarterly credits in the span at all, the
    span's credits are replaced by four equal quarterly credits of
    annual/4 at the span's quarter-end dates.

WINDOWS / JUDGING (program standard):
  - FULL continuous 2019-01-02 -> 2026-11-20; VALIDATION
    2023-01-03 -> 2026-11-20; 20-seed placebo on BOTH windows (random
    5 from the strategy's own scored pool each quarter, identical
    crediting mechanics); walk-forward folds = fresh $100 pots per
    calendar year 2020-2026 vs SPY net.
  - Champion (V+M, plain floor): validation $288.05, continuous
    $544.47, placebo beats 18/20 validation (median $201.15) and
    19/20 continuous (median $308.81), folds 4 wins / 7.
  - SPY net: validation $187.77, continuous $313.62.

Data: SEC EDGAR companyfacts + Yahoo chart files, reused read-only
from the v4 caches (./data and ./value-momentum-honest-data in the v4
folder). No new fetches.
"""
import importlib.util, json, math, os, random, time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")

spec = importlib.util.spec_from_file_location(
    "pf", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
FLOOR0 = 85.0
FULL = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
DECLARED = "CommonStockDividendsPerShareDeclared"
CASHPAID = "CommonStockDividendsPerShareCashPaid"

# ------------------------------------------------------------ price basis B
def raw_cache_path(ticker):
    for base in (os.path.join(V4, "data"),
                 os.path.join(V4, "value-momentum-honest-data")):
        p = os.path.join(base, f"px_{ticker}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            return p
    raise FileNotFoundError(f"no cached prices for {ticker}")

def load_raw(ticker):
    """Quote bars + adjclose + dividend/split events from the same
    cached Yahoo file the champion engine reads. NOTE: Yahoo quote
    open/close are adjusted for splits and spinoffs but NOT for
    dividends (verified in the data: AAPL 'close' on 2019-01-02 is
    the post-split $39.48; T's is its spinoff-restated $22.31)."""
    with open(raw_cache_path(ticker), "rb") as f:
        j = json.loads(f.read())
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
        bars.append({"d": d, "o_raw": o, "c_raw": c, "c_adj": a})
    bars.sort(key=lambda b: b["d"])
    ev = res.get("events") or {}
    divs = []
    for _, dv in (ev.get("dividends") or {}).items():
        divs.append({"d": time.strftime("%Y-%m-%d", time.gmtime(dv["date"])),
                     "amount": float(dv["amount"])})
    divs.sort(key=lambda x: x["d"])
    splits = []
    for _, sv in (ev.get("splits") or {}).items():
        splits.append({"d": time.strftime("%Y-%m-%d", time.gmtime(sv["date"])),
                       "num": float(sv["numerator"]),
                       "den": float(sv["denominator"])})
    splits.sort(key=lambda x: x["d"])
    return bars, divs, splits

def build_basis_b(ticker):
    """Split/spinoff-adjusted, dividend-UNADJUSTED bars ({d, o, c}) plus
    the split list (reused for DPS unit conversion)."""
    bars, divs, splits = load_raw(ticker)
    return basis_b_from_loaded(bars, divs, splits), splits

def split_factor_after(splits, when):
    """Multiply a per-share amount stated in the share units of date
    `when` by this to express it in final (post-all-splits) units.
    Pass GENUINE splits only (see true_splits)."""
    f = 1.0
    for s in splits:
        if s["d"] > when:
            f *= s["den"] / s["num"]
    return f

def true_splits(splits):
    """Genuine share splits only — mechanical rule: numerator and
    denominator both <= 25. Spinoff pseudo-splits (xxxx:1000, 104:100)
    are excluded; see the header for the full list."""
    return [s for s in splits if s["num"] <= 25 and s["den"] <= 25]

def basis_b_from_loaded(bars, divs, splits):
    """Basis-B bars from an already-loaded raw chart (load_raw output)."""
    div_factor = {}
    dates = [b["d"] for b in bars]
    raw_by_date = {b["d"]: b["c_raw"] for b in bars}
    for dv in divs:
        prev = None
        for d in dates:
            if d < dv["d"]:
                prev = d
            else:
                break
        if prev is None:
            continue
        pc = raw_by_date[prev]
        if pc and pc > 0:
            div_factor[dv["d"]] = 1.0 - dv["amount"] / pc
    out = []
    cum = 1.0
    ev_dates = sorted(div_factor)
    ei = len(ev_dates) - 1
    for b in reversed(bars):
        while ei >= 0 and ev_dates[ei] > b["d"]:
            cum *= div_factor[ev_dates[ei]]
            ei -= 1
        c_b = b["c_adj"] / cum if cum else b["c_adj"]
        ratio = c_b / b["c_raw"] if b["c_raw"] else 1.0
        o_b = b["o_raw"] * ratio if b["o_raw"] else c_b
        out.append({"d": b["d"], "o": o_b, "c": c_b})
    out.reverse()
    return out

# ------------------------------------------------------------ EDGAR DPS
def dps_rows(facts, concept):
    """All (start, end, filed, val) rows for a per-share dividend concept,
    units 'USD/shares' only (other unit keys — 'pure', 'shares' — are
    different quantities and are never mixed in)."""
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    if "USD/shares" not in units:
        return []
    rows = []
    for e in units["USD/shares"]:
        if "filed" not in e or "val" not in e or "end" not in e:
            continue
        rows.append((e.get("start", ""), e["end"], e["filed"],
                     float(e["val"])))
    return rows

def _dur_days(start, end):
    if not start:
        return -1
    return (date.fromisoformat(end) - date.fromisoformat(start)).days

def annual_dps_at(rows, asof, splits):
    """Latest annual-duration (300-400d) per-share total among rows filed
    strictly before asof with period end within 548 days of asof.
    Returns (dps_in_final_units, end, filed) or None."""
    cutoff = (date.fromisoformat(asof) - timedelta(days=548)).isoformat()
    best = None
    for start, end, filed, val in rows:
        if filed >= asof or end < cutoff or end > asof:
            continue
        if not (300 <= _dur_days(start, end) <= 400):
            continue
        key = (end, filed)
        if best is None or key > best[0]:
            best = (key, (val, end, filed))
    if best is None:
        return None
    val, end, filed = best[1]
    return (val * split_factor_after(splits, end), end, filed)

def quarterly_dps_at(rows, asof, splits):
    """Sum of the four most recent distinct quarterly-duration periods
    (60-100d, dedupe by period end, latest-filed value wins) filed
    strictly before asof. Requires the latest end within 200 days of
    asof and the four ends spanning at most 400 days. Amounts are
    converted per-period to final share units. Returns
    (dps, latest_end, filed) or None."""
    per_end = {}
    for start, end, filed, val in rows:
        if filed >= asof:
            continue
        if not (60 <= _dur_days(start, end) <= 100):
            continue
        cur = per_end.get(end)
        if cur is None or filed > cur[0]:
            per_end[end] = (filed, val)
    if len(per_end) < 4:
        return None
    ends = sorted(per_end)[-4:]
    latest = ends[-1]
    if latest < (date.fromisoformat(asof) - timedelta(days=200)
                 ).isoformat():
        return None
    if (date.fromisoformat(ends[-1]) - date.fromisoformat(ends[0])
            ).days > 400:
        return None
    total = sum(per_end[e][1] * split_factor_after(splits, e)
                for e in ends)
    return (total, latest, per_end[latest][0])

def trailing_dps(facts, asof, splits):
    """(trailing DPS in final units, source, period end) or None.
    Quarterly sets first (Declared, then CashPaid), then the annual
    fallback (Declared, then CashPaid)."""
    for concept in (DECLARED, CASHPAID):
        got = quarterly_dps_at(dps_rows(facts, concept), asof, splits)
        if got is not None:
            return (got[0], concept + "-Q", got[1])
    for concept in (DECLARED, CASHPAID):
        got = annual_dps_at(dps_rows(facts, concept), asof, splits)
        if got is not None:
            return (got[0], concept + "-A", got[1])
    return None

def build_yield_table(facts_by_t, splits_by_t, raw_bars_by_t, sel_dates):
    """For every selection date: (yields, excluded, detail) where
    yields = {ticker: trailing DPS / contemporaneous quoted price}.
    The cached Yahoo quote closes are split-adjusted (final units)
    but restated for later spinoffs; price_at undoes only the
    post-date spinoff restatements (pseudo-split events), leaving
    the price as quoted on the day, in final share units."""
    raw_close = {}
    for t, bars in raw_bars_by_t.items():
        raw_close[t] = {b["d"]: b["c_raw"] for b in bars}
    raw_dates = {t: sorted(raw_close[t]) for t in raw_bars_by_t}

    def price_at(t, d):
        best = None
        for bd in raw_dates[t]:
            if bd <= d:
                best = bd
            else:
                break
        if best is None:
            return None
        f = 1.0
        for s in splits_by_t[t]:
            if (s["num"] > 25 or s["den"] > 25) and s["d"] > best:
                f *= s["num"] / s["den"]
        return raw_close[t][best] * f

    table = {}
    for d in sel_dates:
        yields, excluded, detail = {}, [], {}
        for t in UNIVERSE:
            got = trailing_dps(facts_by_t[t], d,
                               true_splits(splits_by_t[t]))
            if got is None:
                excluded.append(t)
                continue
            px = price_at(t, d)
            if px is None or px <= 0:
                excluded.append(t)
                continue
            yields[t] = got[0] / px
            detail[t] = {"dps": round(got[0], 4), "source": got[1],
                         "period_end": got[2], "price": round(px, 2),
                         "yield": round(got[0] / px, 4)}
        table[d] = (yields, excluded, detail)
    return table

def build_credits(facts, splits, trading_dates):
    """Estimated dividend cash credits for one name: sorted list of
    (credit_date, amount_per_share_in_final_units). See the header for
    the rule and the annual-total consistency guard."""
    # distinct quarterly periods, Declared preferred per period end
    per_end = {}   # end -> (val, filed, start)
    for concept in (CASHPAID, DECLARED):   # Declared applied last = wins
        for start, end, filed, val in dps_rows(facts, concept):
            if not (60 <= _dur_days(start, end) <= 100):
                continue
            cur = per_end.get(end)
            if cur is None or filed > cur[1]:
                per_end[end] = (val, filed, start)
    credits = {}   # period end -> amount (final units)
    for end, (val, filed, start) in per_end.items():
        credits[end] = val * split_factor_after(splits, end)
    # annual spans: guard / fill
    annuals = {}
    for concept in (CASHPAID, DECLARED):
        for start, end, filed, val in dps_rows(facts, concept):
            if 300 <= _dur_days(start, end) <= 400:
                cur = annuals.get(end)
                if cur is None or filed > cur[1]:
                    annuals[end] = (val, filed, start)
    for end, (aval_raw, afiled, astart) in annuals.items():
        aval = aval_raw * split_factor_after(splits, end)
        inside = [e for e in credits if astart < e <= end]
        s = sum(credits[e] for e in inside)
        if s == 0.0 or abs(s - aval) > 0.25 * aval:
            for e in inside:
                del credits[e]
            # four equal quarterly credits at the span's quarter ends
            base = date.fromisoformat(astart)
            for k in (1, 2, 3, 4):
                qend = (base + timedelta(days=round(365.25 * k / 4))
                        ).isoformat()
                # snap to the last actual period boundary <= span end:
                # use proportional dates; final one is the span end.
                if k == 4:
                    qend = end
                credits[qend] = credits.get(qend, 0.0) + aval / 4.0
    # map each credit's period-end date to the first trading day >= it
    out = []
    td = trading_dates
    for end, amt in credits.items():
        cd = None
        for d in td:
            if d >= end:
                cd = d
                break
        if cd is not None and amt > 0:
            out.append((cd, amt))
    out.sort()
    return out

# ------------------------------------------------------------------ engine
def run_pot_dogs(pb, yield_table, credits_by_t, start, end, start_cash,
                 floor0, placebo_rng=None, label="", quiet=False,
                 apply_credits=True):
    """Champion mechanics (quarterly selection, next-open execution,
    0.10%/side + $0.01/sell costs, plain floor, halt/end liquidation)
    with yield ranking and EDGAR-estimated dividend cash credits."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    total_divs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools = []
    sel_dates = E.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None
    credit_idx = {t: 0 for t in credits_by_t}
    credits_sorted = {t: sorted(credits_by_t.get(t, []))
                      for t in credits_by_t}

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
        # dividend credits on shares held entering today
        if apply_credits:
            for t in list(positions):
                cl = credits_sorted.get(t, [])
                i = credit_idx[t]
                while i < len(cl) and cl[i][0] <= d:
                    if cl[i][0] == d:
                        amt = positions[t] * cl[i][1]
                        cash += amt
                        total_divs += amt
                        trades.append((d, t, "DIV", positions[t], None,
                                       amt, 0.0))
                    i += 1
                credit_idx[t] = i
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            yields, excluded, detail = yield_table.get(d, ({}, [], {}))
            if len(yields) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(yields), 5)
                else:
                    picks = sorted(yields,
                                   key=lambda t: (-yields[t], t))[:5]
                pools.append((d, sorted(yields),
                              {t: round(yields[t], 4) for t in picks},
                              list(picks), excluded))
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} pool={len(yields)} "
                          f"picks={[(t, round(yields[t], 4)) for t in picks]} "
                          f"pot=${pv:,.2f}", flush=True)
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
                    trades.append((nd, t, "SELL-HALT", positions[t],
                                   b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "dividends": total_divs, "trades": trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "pools": pools, "curve": curve}
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
            "dividends": total_divs, "trades": trades, "halted": None,
            "end": last, "halt_info": None, "pools": pools,
            "curve": curve}

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
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "floor": floor0,
            "worst_close_above_floor": round(worst_v - floor0, 2),
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "year_end_closes": {y: {"date": d, "close": round(v, 2)}
                                for y, (d, v) in sorted(year_end.items())}}

def placebo_block(pb, yield_table, credits_by_t, ws, we, ranked_final, tag):
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        rp = run_pot_dogs(pb, yield_table, credits_by_t, ws, we,
                          START_CASH, FLOOR0, placebo_rng=rng,
                          label=f"{tag} PLACEBO s{seed}", quiet=True)
        finals.append(rp["final"])
        rows.append({"seed": seed, "final": round(rp["final"], 2),
                     "halted": rp["halted"],
                     "dividends": round(rp["dividends"], 2)})
        print(f"  [{tag}] placebo seed {seed:2d}: final=${rp['final']:,.2f} "
              f"halted={rp['halted']} divs=${rp['dividends']:,.2f}",
              flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    dist = {"median": round(E._pct(srt, 0.50), 2),
            "q1": round(E._pct(srt, 0.25), 2),
            "q3": round(E._pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "halted_count": sum(1 for p in rows if p["halted"]),
            "ranked_final": round(ranked_final, 2),
            "seeds_beaten": below, "rows": rows}
    print(f"== {tag} PLACEBO_DIST median=${dist['median']:,.2f} "
          f"Q1=${dist['q1']:,.2f} Q3=${dist['q3']:,.2f} "
          f"best=${dist['best']:,.2f} worst=${dist['worst']:,.2f} "
          f"halted={dist['halted_count']}/20 | RANKED "
          f"${ranked_final:,.2f} beat {below}/20 seeds", flush=True)
    return dist

# --------------------------------------------------------------------- main
def main():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    facts_by_t = {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts_by_t[t] = E.get_companyfacts(cik)
        print(f"{t}: facts loaded (CIK {cik})", flush=True)

    # --- basis A (original adjusted) for SPY + cross-check
    bars_a = {}
    for t in UNIVERSE + ["SPY"]:
        bars_a[t] = E.get_prices(t)
    pbA = E.PriceBook(bars_a)
    spy_full, _ = E.spy_net(pbA, FULL[0], FULL[1], START_CASH)
    spy_val, _ = E.spy_net(pbA, VAL[0], VAL[1], START_CASH)
    print(f"SPY replication: FULL=${spy_full:,.2f} (published $313.62) | "
          f"VAL=${spy_val:,.2f} (published $187.77)", flush=True)
    assert abs(spy_full - 313.62) < 0.02 and abs(spy_val - 187.77) < 0.02, \
        "SPY replication failed — price basis mismatch, stop."

    # --- basis B (split/spinoff-adjusted, dividend-unadjusted)
    bars_b, splits_by_t, tsplits_by_t, raw_bars_by_t = {}, {}, {}, {}
    for t in UNIVERSE:
        rbars, divs, splits = load_raw(t)
        raw_bars_by_t[t] = rbars
        splits_by_t[t] = splits
        tsplits_by_t[t] = true_splits(splits)
        bars_b[t] = basis_b_from_loaded(rbars, divs, splits)
    pbB = E.PriceBook(bars_b)
    # sanity: a non-payer's basis B must equal basis A tick for tick
    diffs = [abs(x["c"] - y["c"]) for x, y in zip(bars_b["AMZN"],
                                                  bars_a["AMZN"])]
    print(f"sanity AMZN (non-payer) |B-A| max close diff = "
          f"${max(diffs):,.4f} (must be ~0)", flush=True)
    assert max(diffs) < 0.01

    # --- yield table + credit calendars
    sel_all = E.quarter_selection_dates(pbB, FULL[0], FULL[1])
    yield_table = build_yield_table(facts_by_t, splits_by_t,
                                    raw_bars_by_t, sel_all)
    credits_by_t = {t: build_credits(facts_by_t[t], tsplits_by_t[t],
                                     pbB.dates) for t in UNIVERSE}
    for t in UNIVERSE:
        print(f"{t}: {len(credits_by_t[t])} credit events "
              f"2017-2026", flush=True)
    excl_count = {}
    for d in sel_all:
        _, excluded, _ = yield_table[d]
        for t in excluded:
            excl_count[t] = excl_count.get(t, 0) + 1
    print(f"exclusions by name (of {len(sel_all)} selections): "
          f"{dict(sorted(excl_count.items(), key=lambda kv: -kv[1]))}",
          flush=True)

    out = {"strategy": "dividend yield top-5 (Dogs family), EDGAR "
                       "point-in-time annual DPS, quarterly rebalance",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "spy_replication": {"full": round(spy_full, 2),
                               "validation": round(spy_val, 2)},
           "exclusion_counts": excl_count}

    # --- ranked runs, basis B (judged)
    ranked = {}
    for wname, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        r = run_pot_dogs(pbB, yield_table, credits_by_t, ws, we,
                         START_CASH, FLOOR0, label=f"{wname} DOGS-B")
        diag = diagnostics(r, FLOOR0)
        spy = spy_full if wname == "FULL" else spy_val
        ranked[wname] = r
        out[f"ranked_{wname}"] = {
            "final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "dividends_credited": round(r["dividends"], 2),
            "orders": len([x for x in r["trades"] if x[2] != "DIV"]),
            "div_events": len([x for x in r["trades"] if x[2] == "DIV"]),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "spy_net": round(spy, 2), "diag": diag, "pools": r["pools"],
            "trades": r["trades"]}
        print(f"== {wname} DOGS (basis B) final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} dividends=${r['dividends']:,.2f} "
              f"halted={r['halted']} | SPY net=${spy:,.2f}", flush=True)
        print(f"   worst close ${diag['worst_close']:,.2f} on "
              f"{diag['worst_close_date']} (margin "
              f"${diag['worst_close_above_floor']:,.2f}) | maxDD "
              f"{diag['max_drawdown_pct']}% on {diag['max_drawdown_date']}",
              flush=True)

    # --- cross-check: ranked on basis A (dividends embedded, no credits)
    for wname, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        r = run_pot_dogs(pbA, yield_table, credits_by_t, ws, we,
                         START_CASH, FLOOR0, label=f"{wname} DOGS-A",
                         quiet=True, apply_credits=False)
        out[f"crosscheck_basisA_{wname}"] = {
            "final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "halted": r["halted"]}
        print(f"== {wname} DOGS (basis A cross-check, no cash credits) "
              f"final=${r['final']:,.2f} halted={r['halted']}", flush=True)

    # --- placebo, basis B, both windows
    out["placebo_FULL"] = placebo_block(
        pbB, yield_table, credits_by_t, FULL[0], FULL[1],
        ranked["FULL"]["final"], "FULL")
    out["placebo_VALIDATION"] = placebo_block(
        pbB, yield_table, credits_by_t, VAL[0], VAL[1],
        ranked["VALIDATION"]["final"], "VALIDATION")

    # --- walk-forward folds, basis B, fresh $100 per calendar year
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot_dogs(pbB, yield_table, credits_by_t, fs, fe,
                          START_CASH, FLOOR0, label=f"FOLD {y}",
                          quiet=True)
        fspy, _ = E.spy_net(pbA, fs, fe, START_CASH)
        row = {"year": y, "final": round(fr["final"], 2),
               "return_pct": round(fr["final"] / START_CASH * 100 - 100, 2),
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "dividends": round(fr["dividends"], 2),
               "halted": fr["halted"]}
        folds.append(row)
        print(f"FOLD {y}: DOGS ${fr['final']:,.2f} "
              f"({row['return_pct']:+.2f}%) vs SPY ${fspy:,.2f} "
              f"({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"divs=${fr['dividends']:,.2f} halted={fr['halted']}",
              flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    print(f"FOLD RECORD: {out['fold_record']} (champion: 4 wins, 3 losses)",
          flush=True)

    with open(os.path.join(HERE, "dogs-dividend-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
