#!/usr/bin/env python3
"""
DIVIDEND GROWTH SCREEN (Dividend-Aristocrats family) — Terry's AI stock app.
Simulation only.

THE RULE (run once, exactly as specified, no tuning):
  Universe / engine / costs / protection are Terry's program standard, taken
  from the champion study value-momentum-plainfloor.py: the honest
  point-in-time top-30 universe as of Nov 2016, $100 pot, costs 0.10% of
  trade value per side + $0.01 per sell order, plain -15% floor ($85) with
  liquidation at the next open, quarterly selection (first trading day of
  Jan/Apr/Jul/Oct), rebalance at the next open, end-of-window liquidation
  at the final close.
  Selection: a name is ELIGIBLE at a selection date if, from SEC EDGAR
  companyfacts filed strictly before that date,
    (a) its declared annual dividend per share has a chain of at least SIX
        consecutive fiscal years (five year-over-year steps),
    (b) no step in that chain is a cut (relative change >= -0.5%; the
        half-percent tolerance absorbs cent-level restatement noise only),
    (c) the latest annual DPS is > 0, its fiscal year ended within 550
        days of the selection date, and a per-share declaration with a
        period end within 400 days exists (the name currently pays).
  Eligible names are ranked by 5-year dividend growth (latest annual DPS /
  annual DPS five years earlier - 1), descending; ties break
  alphabetically. Top 5, equal weight (each pick targets pot/5). If fewer
  than 5 names are eligible, the pot holds what is eligible and the
  unfilled slots stay in CASH. If none are eligible, the pot goes to cash.

DIVIDEND DATA (EDGAR): annual DPS is the full-year (duration >= 300 days)
value of us-gaap CommonStockDividendsPerShareDeclared (USD/shares) for
each fiscal year end, taking the most recently filed value for that year
end (the baseline engine's pit convention). Where a fiscal year has no
full-year Declared figure, the same construction from
CommonStockDividendsPerShareCashPaid is used for that year (flagged in
the output; Declared and CashPaid annual per-share amounts differ only
by declaration-vs-payment timing). Per-share values are converted into
selection-date share units: a value filed before a stock split is divided
by the split factor(s) whose ex-dates fall after its filing date (Yahoo
split events), so a pre-split $3.08 and its post-split restatement $0.77
cannot fake a "cut" or a "raise" in the chain. XOM CIK override 34088,
as in the baseline engine.

DIVIDEND CASH CREDITING (the method, stated in full because the
dogs-dividend study it was to mirror has not been written yet):
  Prices here are SPLIT-ADJUSTED BUT NOT DIVIDEND-ADJUSTED (Yahoo chart
  quote open/close), unlike the champion engine's dividend-adjusted
  closes. Dividends are therefore NOT inside the price series; they are
  credited as CASH. Yahoo chart dividend events (verified split-adjusted,
  in the same share units as the prices) give amount per share and
  ex-date. On each ex-date, before any rebalance executes, the pot is
  credited shares-held-at-the-prior-close x amount — the market's actual
  entitlement rule (buying on the ex-date earns nothing; selling on the
  ex-date keeps the dividend). Credited cash sits in the pot: it counts
  toward portfolio value, the floor check, and the next rebalance's
  targets (targets are set on total portfolio value). No cost and no tax
  is charged on a dividend credit (the champion's adjusted-price
  convention likewise embeds dividends untaxed). Sanity check below:
  SPY on raw prices + cash-credited dividends must land near the
  program's dividend-adjusted SPY net figure.

PLACEBO: 20 seeds; at each selection the placebo draws randomly from the
ELIGIBLE pool only (min(5, pool size) names), with identical mechanics
including dividend crediting. Note what this isolates: ranked-vs-placebo
measures the growth RANKING inside the screened pool; the screen itself
is judged against SPY and the champion.

BENCHMARK ASYMMETRY (stated, not hidden): the champion V+M finals
($288.05 validation / $544.47 continuous) and the program SPY net finals
($187.77 / $313.62) were computed on dividend-ADJUSTED prices — dividends
embedded in the price series, effectively reinvested in the same stock
daily, with no cash pile. This study's pot instead holds raw prices plus
a cash dividend pile that is only redeployed at the next quarterly
rebalance (a small cash drag vs the champion's convention). A raw
price-only SPY (no dividends at all) is also computed and reported so
the size of the dividend term is visible.

Windows: FULL continuous 2019-01-02 -> 2026-11-20 and VALIDATION
2023-01-03 -> 2026-11-20, plus walk-forward folds (fresh $100 pot each
calendar year 2020-2026 vs the champion study's SPY fold figures).
"""
import importlib.util, json, math, os, random, time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
FLOOR0 = 85.0
CUT_TOL = -0.005          # a step >= -0.5% counts as "not a cut"
CHAIN_MIN = 6             # six annual values = five year-over-year steps
FRESH_END_DAYS = 550      # latest fiscal year end must be this recent
PAYS_DAYS = 400           # a declaration period end must be this recent

# ------------------------------------------------------------- raw prices
def load_raw_market():
    """v10 sweep variant: read the decade Yahoo chart blobs downloaded
    into this folder's data/ (2016-11-01 -> 2026-11-20, same Yahoo chart
    channel and events=div,split as the original test). Builds (a)
    split-adjusted, dividend-UNadjusted bars, (b) dividend events,
    (c) split events."""
    bars, divs, splits = {}, {}, {}
    for t in UNIVERSE + ["SPY"]:
        p = os.path.join(HERE, "data", f"px_{t}.json")
        with open(p, "rb") as f:
            blob = f.read()
        j = json.loads(blob)
        res = j["chart"]["result"][0]
        ts = res["timestamp"]
        q = res["indicators"]["quote"][0]
        bl = []
        for i, tt in enumerate(ts):
            d = time.strftime("%Y-%m-%d", time.gmtime(tt))
            c = q["close"][i]
            if c is None:
                continue
            o = q["open"][i] if q["open"][i] else c
            bl.append({"d": d, "o": o, "c": c})
        bl.sort(key=lambda b: b["d"])
        bars[t] = bl
        dv = {}
        for k, v in res.get("events", {}).get("dividends", {}).items():
            d = time.strftime("%Y-%m-%d", time.gmtime(int(k)))
            dv[d] = dv.get(d, 0.0) + float(v["amount"])
        divs[t] = dv
        sp = []
        for k, v in res.get("events", {}).get("splits", {}).items():
            d = time.strftime("%Y-%m-%d", time.gmtime(int(k)))
            sp.append((d, float(v["numerator"]) / float(v["denominator"])))
        splits[t] = sorted(sp)
    return bars, divs, splits

# ------------------------------------------------------- EDGAR DPS series
def dps_entries(facts, concept):
    """All (start, end, filed, val) for a per-share concept, USD/shares."""
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    out = []
    for e in units.get("USD/shares", []):
        if "val" not in e or "filed" not in e or "start" not in e:
            continue
        out.append((e["start"], e["end"], e["filed"], float(e["val"])))
    return out

def _ord(dstr):
    return _date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()

def split_adjust(val, filed, asof, split_list):
    """Convert a per-share value filed on `filed` into asof share units:
    divide by every split factor whose ex-date is in (filed, asof]."""
    adj = val
    for exd, fac in split_list:
        if filed < exd <= asof and fac > 0:
            adj /= fac
    return adj

def annual_dps_series(facts, asof, split_list):
    """{fy_end: (annual_dps_in_asof_units, source_concept)} built from
    facts filed strictly before asof. Full-year entries only
    (duration >= 300 days); most recently filed value per year end;
    Declared preferred, CashPaid as the per-year fallback."""
    series = {}
    for concept in ("CommonStockDividendsPerShareDeclared",
                    "CommonStockDividendsPerShareCashPaid"):
        by_end = {}
        for start, end, filed, val in dps_entries(facts, concept):
            if filed >= asof:
                continue
            if _ord(end) - _ord(start) < 300:
                continue
            if end not in by_end or filed > by_end[end][0]:
                by_end[end] = (filed, val)
        for end, (filed, val) in by_end.items():
            if end not in series:  # Declared (first pass) wins the year
                series[end] = (split_adjust(val, filed, asof, split_list),
                               concept)
    return series

def currently_pays(facts, asof):
    for concept in ("CommonStockDividendsPerShareDeclared",
                    "CommonStockDividendsPerShareCashPaid"):
        for start, end, filed, val in dps_entries(facts, concept):
            if filed < asof and val > 0 and \
                    _ord(asof) - _ord(end) <= PAYS_DAYS and \
                    _ord(end) - _ord(start) >= 60:
                return True
    return False

def eligibility(facts, asof, split_list):
    """Return (growth_5y, chain_values) if eligible at asof, else None."""
    series = annual_dps_series(facts, asof, split_list)
    if not series:
        return None
    ends = sorted(series)
    # trailing chain of consecutive fiscal years (gaps of 300-430 days)
    chain = [ends[-1]]
    for e in reversed(ends[:-1]):
        gap = _ord(chain[0]) - _ord(e)
        if 300 <= gap <= 430:
            chain.insert(0, e)
        else:
            break
    if len(chain) < CHAIN_MIN:
        return None
    if _ord(asof) - _ord(chain[-1]) > FRESH_END_DAYS:
        return None
    vals = [series[e][0] for e in chain[-CHAIN_MIN:]]
    if vals[-1] <= 0:
        return None
    for a, b in zip(vals, vals[1:]):
        if a <= 0 or (b / a - 1.0) < CUT_TOL:
            return None
    if not currently_pays(facts, asof):
        return None
    return (vals[-1] / vals[0] - 1.0), vals

# ------------------------------------------------------------------ engine
def run_pot_div(pb, divs, pools, start, end, placebo_rng=None, label="",
                quiet=True, sel_dates=None):
    """Daily loop mirroring value-momentum-plainfloor.run_pot mechanics,
    with dividend cash crediting and precomputed eligibility pools
    {selection_date: [(ticker, growth), ...] ranked best-first}."""
    cash = START_CASH
    floor = FLOOR0
    positions = {}
    trades = []
    total_costs = 0.0
    div_total = 0.0
    div_log = []
    halted = None
    halt_info = None
    # --- V9 PROTECTION MODULE (CLAUDE-RULES v9, the ONLY change): ---
    # episode 1 floor = floor0 (-15% of start). On FIRST halt: liquidate
    # exactly as below, sit in cash 90 calendar days, restart at the next
    # regular selection date with episode-2 floor = -15% of the restart
    # balance. On SECOND halt: original return (run ends permanently).
    v9_episode = 1
    v9_resume = None
    restarts = []
    curve = []
    picks_log = []
    if sel_dates is None:
        sel_dates = E.quarter_selection_dates(pb, start, end)
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

    def credit_dividends(d):
        nonlocal cash, div_total
        for t, sh in list(positions.items()):
            amt = divs.get(t, {}).get(d)
            if amt:
                pay = sh * amt
                cash += pay
                div_total += pay
                div_log.append((d, t, round(sh, 6), amt, round(pay, 4)))

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
        # (1) dividends: entitlement = shares held at prior close
        credit_dividends(d)
        # (2) execute pending rebalance at today's open
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        # (3) selection day
        if d in sel_set and (v9_resume is None or d >= v9_resume):
            pool = pools.get(d, [])
            names = [t for t, _ in pool]
            if placebo_rng is not None:
                picks = placebo_rng.sample(sorted(names),
                                           min(5, len(names)))
            else:
                picks = names[:5]
            picks_log.append((d, len(names), list(picks)))
            pv = portfolio_close(d)
            each = pv / 5.0
            pending = {t: each for t in picks}
            if not quiet:
                print(f"  [{label}] {d} eligible={len(names)} picks={picks} "
                      f"pot=${pv:,.2f}", flush=True)
        # (4) floor check at close
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            # shares are still held at the signal close: an ex-date on
            # the liquidation day is still the pot's dividend
            credit_dividends(nd)
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
            if v9_episode == 1:
                import datetime as _dt
                v9_episode = 2
                v9_resume = (_dt.date.fromisoformat(d)
                             + _dt.timedelta(days=90)).isoformat()
                restarts.append({"halt_date": d, "liquidation_date": nd,
                                 "restart_balance": round(cash, 2),
                                 "resume_on_or_after": v9_resume,
                                 "episode2_floor": round(0.85 * cash, 2)})
                floor = 0.85 * cash
                pending = None
                halted = None
            else:
                return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "restarts": restarts, "curve": curve,
                    "div_total": div_total, "div_log": div_log,
                    "picks_log": picks_log}
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
            "halt_info": None, "restarts": restarts, "curve": curve,
            "div_total": div_total, "div_log": div_log,
            "picks_log": picks_log}

def spy_raw_variants(pb, divs, start, end):
    """SPY on raw (dividend-unadjusted) prices: (a) price-only, no
    dividends; (b) dividends credited as cash, same entitlement rule."""
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (START_CASH / 1.001) / o
    buy_cost = START_CASH - sh * o
    cash = 0.0
    spy_divs = divs.get("SPY", {})
    for d in days[1:]:
        if d in spy_divs:
            cash += sh * spy_divs[d]
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    # sh*o + buy_cost == START_CASH exactly, so no residual cash
    price_only = val - sell_cost
    with_divs = price_only + cash
    return price_only, with_divs, cash

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
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = (d, v)
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "worst_close_above_floor": round(worst_v - FLOOR0, 2),
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "year_end_closes": {y: {"date": d, "close": round(v, 2)}
                                for y, (d, v) in sorted(year_end.items())}}

def placebo_block(pb, divs, pools, ws, we):
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_pot_div(pb, divs, pools, ws, we, placebo_rng=rng,
                         label=f"PLACEBO {seed}")
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2),
                     "div_total": round(pr["div_total"], 2)})
        print(f"  PLACEBO seed {seed:2d}: final=${pr['final']:,.2f} "
              f"halted={pr['halted']} div=${pr['div_total']:,.2f}",
              flush=True)
    return finals, rows

def dist_stats(finals, ranked):
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked)
    ties = sum(1 for f in finals if f == ranked)
    return {"median": round(E._pct(srt, 0.50), 2),
            "q1": round(E._pct(srt, 0.25), 2),
            "q3": round(E._pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": None,
            "ranked_final": round(ranked, 2),
            "ranked_percentile": round(100.0 * (below + 0.5 * ties) / len(finals), 1),
            "seeds_beaten": below}


# =====================================================================
# v10 GREAT RETEST SWEEP MAIN (appended for v10; engine above is the
# v9-adapted original engine, mechanics unchanged).
# DECADE 2016-11-21 -> 2026-11-20, $100/cell, program costs, v9
# protections, uniform SPEC cadence definition. Native cadence = ANNUAL
# (SCHD reconstitution form); the original program test ran QUARTERLY
# (foreign cadence, flagged).
# =====================================================================
import bisect
from datetime import date as _d2

DEC_START, DEC_END = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

def cadence_dates(dates, cadence, start, end):
    days = [d for d in dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    if cadence in ("weekly", "biweekly"):
        wk_idx = -1
        cur_wk = None
        for d in days:
            iso = _d2.fromisoformat(d).isocalendar()
            wk = (iso[0], iso[1])
            if wk != cur_wk:
                cur_wk = wk
                wk_idx += 1
                if cadence == "weekly" or wk_idx % 2 == 0:
                    out.append(d)
        return out
    for d in days:
        if cadence == "monthly":
            key = d[:7]
        elif cadence == "quarterly":
            key = (d[:4], (int(d[5:7]) - 1) // 3)
        elif cadence == "semiannual":
            key = (d[:4], (int(d[5:7]) - 1) // 6)
        elif cadence == "annual":
            key = d[:4]
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out

def adj_bars_from_blob(t):
    """Dividend-adjusted bars from this folder's downloaded blob, using
    the champion engine's convention (adjclose ratio applied to OHLC)."""
    with open(os.path.join(HERE, "data", f"px_{t}.json"), "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, tt in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(tt))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

def cell_stats(r, start, end):
    curve = r["curve"]
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (_d2.fromisoformat(end) - _d2.fromisoformat(start)).days / 365.25
    cagr = (r["final"] / START_CASH) ** (1.0 / yrs) - 1.0 if r["final"] > 0 else -1.0
    halts = []
    for rs in r.get("restarts", []):
        halts.append({"halt_date": rs["halt_date"],
                      "liquidation_date": rs["liquidation_date"],
                      "restart_balance": rs["restart_balance"],
                      "resume_on_or_after": rs["resume_on_or_after"],
                      "episode2_floor": rs["episode2_floor"]})
    second = None
    if r["halted"]:
        second = {"halt_date": r["halted"],
                  "signal_close": r["halt_info"]["signal_close"] if r["halt_info"] else None}
    return {"final": round(r["final"], 2), "cagr_pct": round(cagr * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halts": halts,
            "second_halt": second,
            "restart": bool(r.get("restarts")),
            "dividends_credited": round(r["div_total"], 2),
            "curve": [[d, round(v, 4)] for d, v in curve]}

def sweep_main():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    facts_by_t, filed_idx = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts_by_t[t] = E.get_companyfacts(cik)
        fds = sorted({e[2] for c in ("CommonStockDividendsPerShareDeclared",
                                     "CommonStockDividendsPerShareCashPaid")
                      for e in dps_entries(facts_by_t[t], c)})
        filed_idx[t] = fds
    print("EDGAR facts loaded", flush=True)
    raw_bars, divs, splits = load_raw_market()
    raw_pb = E.PriceBook(raw_bars)
    adj_pb = E.PriceBook({t: adj_bars_from_blob(t) for t in ["SPY"]})
    spy_dec, _ = E.spy_net(adj_pb, DEC_START, DEC_END, 100.0)
    po, wd, dv = spy_raw_variants(raw_pb, divs, DEC_START, DEC_END)
    print(f"DECADE SPY adjusted=${spy_dec:,.2f} (SPEC ref 367.80) | "
          f"raw price-only=${po:,.2f} raw+cashdivs=${wd:,.2f}", flush=True)

    elig_cache = {}
    def pool_at(d):
        ranked = []
        for t in UNIVERSE:
            key = (t, bisect.bisect_left(filed_idx[t], d))
            if key not in elig_cache:
                elig_cache[key] = eligibility(facts_by_t[t], d,
                                              splits.get(t, []))
            res = elig_cache[key]
            if res is not None:
                ranked.append((t, res[0]))
        ranked.sort(key=lambda kv: (-kv[1], kv[0]))
        return ranked

    summary = {"window": [DEC_START, DEC_END],
               "spy_decade_adjusted": round(spy_dec, 2),
               "spy_decade_raw_price_only": round(po, 2),
               "spy_decade_raw_plus_cash_divs": round(wd, 2),
               "cells": {}}
    for cad in CADENCES:
        cellpath = os.path.join(HERE, "cells", f"{cad}.json")
        if os.path.exists(cellpath):
            cell = json.load(open(cellpath))
            summary["cells"][cad] = {k: cell[k] for k in
                ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
                 "dividends_credited", "placebo_beaten", "restart")}
            summary["cells"][cad]["halts_n"] = len(cell["halts"]) + (1 if cell["second_halt"] else 0)
            summary["cells"][cad]["second_halt"] = bool(cell["second_halt"])
            print(f"== {cad}: SKIPPED (cell already saved)", flush=True)
            continue
        sels = cadence_dates(raw_pb.dates, cad, DEC_START, DEC_END)
        pools = {d: pool_at(d) for d in sels}
        print(f"== {cad}: {len(sels)} selection dates; pool sizes "
              f"min={min(len(p) for p in pools.values())} "
              f"max={max(len(p) for p in pools.values())}", flush=True)
        r = run_pot_div(raw_pb, divs, pools, DEC_START, DEC_END,
                        label=f"DEC {cad}", sel_dates=sels)
        st = cell_stats(r, DEC_START, DEC_END)
        placebo_finals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = run_pot_div(raw_pb, divs, pools, DEC_START, DEC_END,
                             placebo_rng=rng, label=f"PLB {cad} {seed}",
                             sel_dates=sels)
            placebo_finals.append(round(pr["final"], 2))
        beaten = sum(1 for f in placebo_finals if f < r["final"])
        cell = dict(st)
        cell["placebo_finals"] = placebo_finals
        cell["placebo_beaten"] = beaten
        cell["n_selection_dates"] = len(sels)
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        summary["cells"][cad] = {k: cell[k] for k in
            ("final", "cagr_pct", "max_dd_pct", "costs", "orders",
             "dividends_credited", "placebo_beaten", "restart")}
        summary["cells"][cad]["halts_n"] = len(cell["halts"]) + (1 if cell["second_halt"] else 0)
        summary["cells"][cad]["second_halt"] = bool(cell["second_halt"])
        print(f"   {cad}: final=${st['final']:,.2f} CAGR={st['cagr_pct']}% "
              f"maxDD={st['max_dd_pct']}% costs=${st['costs']:,.2f} "
              f"orders={st['orders']} divs=${st['dividends_credited']:,.2f} "
              f"placebo beaten {beaten}/20 halts={summary['cells'][cad]['halts_n']}",
              flush=True)
    with open(os.path.join(HERE, "sweep_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print("SWEEP DONE", flush=True)

if __name__ == "__main__":
    sweep_main()
