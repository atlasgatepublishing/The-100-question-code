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
    """Read the champion study's cached Yahoo chart blobs (same files,
    read-only) and build (a) split-adjusted, dividend-UNadjusted bars,
    (b) dividend events {ticker: {ex_date: amount/share}}, (c) split
    events {ticker: [(ex_date, factor)]}."""
    bars, divs, splits = {}, {}, {}
    for t in UNIVERSE + ["SPY"]:
        blob = None
        for d in (os.path.join(V4, "data"),
                  os.path.join(V4, "value-momentum-honest-data")):
            p = os.path.join(d, f"px_{t}.json")
            if os.path.exists(p) and os.path.getsize(p) > 100:
                with open(p, "rb") as f:
                    blob = f.read()
                break
        if blob is None:
            raise RuntimeError(f"no cached prices for {t}")
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
                quiet=True):
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

# --------------------------------------------------------------------- main
def main():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    facts_by_t = {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts_by_t[t] = E.get_companyfacts(cik)
    print("EDGAR facts loaded for", len(facts_by_t), "tickers", flush=True)

    raw_bars, divs, splits = load_raw_market()
    raw_pb = E.PriceBook(raw_bars)
    adj_bars = {t: E.get_prices(t) for t in UNIVERSE + ["SPY"]}
    adj_pb = E.PriceBook(adj_bars)
    print("price books built", flush=True)

    # ---- sanity checks -------------------------------------------------
    spy_full_adj, _ = E.spy_net(adj_pb, "2019-01-02", "2026-11-20", 100.0)
    spy_val_adj, _ = E.spy_net(adj_pb, "2023-01-03", "2026-11-20", 100.0)
    print(f"SANITY spy_net adjusted: FULL=${spy_full_adj:,.2f} "
          f"(published 313.62) VALIDATION=${spy_val_adj:,.2f} "
          f"(published 187.77)", flush=True)
    po_f, wd_f, dv_f = spy_raw_variants(raw_pb, divs,
                                        "2019-01-02", "2026-11-20")
    po_v, wd_v, dv_v = spy_raw_variants(raw_pb, divs,
                                        "2023-01-03", "2026-11-20")
    print(f"SANITY SPY raw price-only: FULL=${po_f:,.2f} VAL=${po_v:,.2f} | "
          f"raw + cash dividends: FULL=${wd_f:,.2f} (divs ${dv_f:,.2f}) "
          f"VAL=${wd_v:,.2f} (divs ${dv_v:,.2f})", flush=True)

    # ---- precompute eligibility pools for every quarterly selection ---
    all_sel = E.quarter_selection_dates(raw_pb, "2019-01-02", "2026-11-20")
    pools = {}
    fallback_years = 0
    total_years = 0
    for d in all_sel:
        ranked = []
        for t in UNIVERSE:
            res = eligibility(facts_by_t[t], d, splits.get(t, []))
            if res is not None:
                ranked.append((t, res[0]))
        ranked.sort(key=lambda kv: (-kv[1], kv[0]))
        pools[d] = ranked
        print(f"POOL {d}: eligible={len(ranked)} "
              f"{[(t, round(g, 3)) for t, g in ranked]}", flush=True)
    # count Declared-vs-CashPaid year usage at the final selection date
    d_last = all_sel[-1]
    for t in UNIVERSE:
        s = annual_dps_series(facts_by_t[t], d_last, splits.get(t, []))
        for _, src in s.values():
            total_years += 1
            if "CashPaid" in src:
                fallback_years += 1
    print(f"annual-DPS year cells at {d_last}: {total_years}, of which "
          f"CashPaid fallback: {fallback_years}", flush=True)

    out = {"rule": "dividend growth screen: >=6 consecutive fiscal years of "
                   "annual DPS with no cut (tol -0.5%), currently pays; "
                   "rank by 5y DPS growth; top-5 equal weight (slot = "
                   "pot/5, unfilled slots stay cash); quarterly",
           "universe": UNIVERSE,
           "sanity": {"spy_net_adjusted_full": round(spy_full_adj, 2),
                      "spy_net_adjusted_validation": round(spy_val_adj, 2),
                      "spy_raw_price_only_full": round(po_f, 2),
                      "spy_raw_price_only_validation": round(po_v, 2),
                      "spy_raw_plus_cash_divs_full": round(wd_f, 2),
                      "spy_raw_plus_cash_divs_validation": round(wd_v, 2),
                      "spy_raw_divs_credited_full": round(dv_f, 2),
                      "spy_raw_divs_credited_validation": round(dv_v, 2)},
           "pools": {d: [(t, round(g, 4)) for t, g in pools[d]]
                     for d in all_sel}}

    windows = [("FULL", "2019-01-02", "2026-11-20", 313.62),
               ("VALIDATION", "2023-01-03", "2026-11-20", 187.77)]
    for wname, ws, we, spy_pub in windows:
        r = run_pot_div(raw_pb, divs, pools, ws, we, label=f"{wname} RANKED")
        diag = diagnostics(r)
        print(f"== {wname} RANKED final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halted={r['halted']} dividends=${r['div_total']:,.2f} | "
              f"SPY net=${spy_pub:,.2f}", flush=True)
        print(f"   worst close ${diag['worst_close']:,.2f} on "
              f"{diag['worst_close_date']} (margin "
              f"${diag['worst_close_above_floor']:,.2f}) | maxDD "
              f"{diag['max_drawdown_pct']}% on {diag['max_drawdown_date']}",
              flush=True)
        finals, rows = [], []  # V9 RUN RULE: ranked pots only, no placebos
        dist = {"median": None, "best": None, "worst": None, "halted_count": 0, "skipped": "v9 ranked-only"}
        print("   PLACEBO: skipped (v9 ranked-only)", flush=True)
        out[wname] = {"final": round(r["final"], 2),
                      "costs": round(r["costs"], 2),
                      "orders": len(r["trades"]),
                      "halted": r["halted"], "halt_info": r["halt_info"], "restarts": r.get("restarts", []),
                      "dividends_credited": round(r["div_total"], 2),
                      "diag": diag, "picks_log": r["picks_log"],
                      "placebo": dist, "placebo_rows": rows,
                      "spy_net_published": spy_pub}

    # ---- walk-forward folds --------------------------------------------
    champ_folds = {2020: (83.62, 117.47), 2021: (118.43, 127.97),
                   2022: (108.91, 81.42), 2023: (118.47, 125.28),
                   2024: (144.32, 125.46), 2025: (124.57, 116.81),
                   2026: (136.26, 101.17)}
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot_div(raw_pb, divs, pools, fs, fe, label=f"FOLD {y}")
        fspy, _ = E.spy_net(adj_pb, fs, fe, 100.0)
        row = {"year": y, "final": round(fr["final"], 2),
               "return_pct": round(fr["final"] - 100.0, 2),
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy - 100.0, 2),
               "beat_spy": fr["final"] > fspy,
               "halted": fr["halted"], "restarts": fr.get("restarts", []),
               "costs": round(fr["costs"], 2),
               "dividends_credited": round(fr["div_total"], 2),
               "champion_final": champ_folds[y][0],
               "champion_spy_final": champ_folds[y][1]}
        folds.append(row)
        print(f"FOLD {y}: DIVGROWTH ${fr['final']:,.2f} "
              f"({row['return_pct']:+.2f}%) vs SPY ${fspy:,.2f} "
              f"({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"halted={fr['halted']} div=${fr['div_total']:,.2f}",
              flush=True)
    wins = sum(1 for f in folds if f["beat_spy"])
    out["folds"] = folds
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    print("FOLD RECORD:", out["fold_record"], flush=True)

    with open(os.path.join(HERE, "dividend-growth-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
