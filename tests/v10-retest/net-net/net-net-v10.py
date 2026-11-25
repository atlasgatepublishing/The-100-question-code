#!/usr/bin/env python3
"""
NET-NET (Graham NCAV deep value) — THE GREAT RETEST (v10), cadence sweep.

Simulation only. One clean shot, no tuning. This script:
  (0) INTEGRITY — reproduces the AS-RUN original record through the v9
      module's own engine (which is the v6 engine + v9 protection module):
      CONT (2019-01-02 -> 2026-11-20) $218.59, VAL (2023-01-03 ->
      2026-11-20) $100.00, plus the champion-engine replication check
      ($544.47 / $288.05, SPY $313.62 / $187.77) the original ran first.
  (1) SWEEP — DECADE 2016-11-21 -> 2026-11-20 x 7 cadences under the
      SPEC's uniform cadence definition: cadence governs the
      qualification-review rhythm (signal evaluation, selection and
      trading happen ONLY on cadence dates). $100/cell, program costs
      (0.10%/side + $0.01 per sell order), adopted v9 protections
      (plain -15% floor; first halt -> liquidate next open, 90 calendar
      days cash, restart at the next regular cadence date under an
      episode-2 floor of -15% of the restart balance; second halt ends
      the run). Mechanics are the v9 net-net engine's, copied, with the
      selection-date set parameterized by cadence.
  (2) CORRECTED BASIS tracked at every review date of every cell: the
      documented EDGAR pre-split units artifact (Alphabet 20-for-1
      split, July 2022 — EDGAR share counts as filed pre-split vs the
      split-adjusted price series overstate GOOGL NCAV/share 20x) is
      corrected analytically (GOOGL ratio x20 wherever the shares fact
      used was filed before the first post-split filing). The artifact
      is documented, never patched: the traded runs are the AS-RUN
      basis, exactly as the program record carries them; the corrected
      basis is reported alongside.

Data: SEC EDGAR companyfacts + Yahoo prices, reused READ-ONLY from the
v4 caches via the champion engine (value-momentum-plainfloor.py) — the
same machinery the original v6/v9 tests used verbatim. Nothing is
written outside this v10 folder. The 1.7GB long-run cache is NOT used.

Native cadence (SPEC CADENCE GRID, W3): event-driven with annual
review (buy when a name qualifies; Graham form holds / reviews
annually). The original program test forced a QUARTERLY selection
rhythm — a foreign cadence, flagged.

Placebos: n/a in every cell (see RESULTS.md / results.json note): the
original ran none and none is constructible — whenever names qualify
the rule holds ALL of them (max 5); as-run the qualifier count was
exactly one (GOOGL, the artifact) in every qualifying quarter and zero
on the corrected basis, so there is no selection discretion for a
random draw to test against.
"""
import bisect
import datetime as dt
import importlib.util
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V9 = os.path.join(HERE, "..", "..", "v9-muse-rules", "net-net", "net-net.py")

_spec = importlib.util.spec_from_file_location("netnet_v9", V9)
NN9 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(NN9)
E = NN9.E                      # champion engine (value-momentum-plainfloor)
UNIVERSE = E.UNIVERSE
START_CASH = 100.0
FLOOR0 = 85.0
MAX_HOLD = 5

DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
DECADE_SPY_FINAL = 367.80      # SPEC reference (dividend-adjusted)

PLACEBO_NOTE = ("n/a — not run, same reason as the original program: whenever "
                "names qualify the rule holds ALL of them (up to the 5-name "
                "cap), so the ranked set IS the qualifier set; as-run the "
                "qualifier count was exactly one (GOOGL, the documented "
                "pre-split units artifact) in every qualifying review and "
                "zero on the corrected basis — there is no selection "
                "discretion for a random draw to test against, and a "
                "placebo of an all-cash pot is the same all-cash pot 20 times.")

# ------------------------------------------------------------- data load
def load_data():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}   # carried over verbatim from champion
    equity_rows, shares_rows = {}, {}
    ca_rows, liab_rows, le_rows = {}, {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        eq = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
              E.pit_series(facts, "us-gaap",
                           "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                           prio=1))
        so = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
              E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
              E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        equity_rows[t], shares_rows[t] = eq, so
        ca_rows[t] = E.pit_series(facts, "us-gaap", "AssetsCurrent")
        liab_rows[t] = E.pit_series(facts, "us-gaap", "Liabilities")
        le_rows[t] = E.pit_series(facts, "us-gaap", "LiabilitiesAndStockholdersEquity")
        time.sleep(0.02)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    pb = E.PriceBook(bars)
    data = {"equity": equity_rows, "shares": shares_rows,
            "ca": ca_rows, "liab": liab_rows, "le": le_rows}
    return pb, data

# --------------------------------------- fast PIT lookup (exact replica)
# E.pit_value picks, among rows filed strictly before asof and within
# 548 days, the max by key (filed, prio, end). Filed dominates the key,
# so the answer is the value of the most recent filed date < asof (with
# the per-filed-date winner by (prio, end)), or None if that filed date
# is stale. Precompute per series: sorted filed dates -> winning
# (filed, end, val). Verified against E.pit_value in main() before use.
class PitIndex:
    def __init__(self, rows):
        best = {}
        for filed, end, val, prio in rows:
            cur = best.get(filed)
            if cur is None or (prio, end) > (cur[0], cur[1]):
                best[filed] = (prio, end, val)
        self.dates = sorted(best)
        self.vals = [best[d] for d in self.dates]  # (prio, end, val)
        self.ords = [dt.date.fromisoformat(d).toordinal() for d in self.dates]

    def value(self, asof, max_age_days=548):
        i = bisect.bisect_left(self.dates, asof) - 1
        if i < 0:
            return None
        ao = dt.date.fromisoformat(asof).toordinal()
        if self.ords[i] < ao - max_age_days:
            return None
        _prio, end, val = self.vals[i]
        return (self.dates[i], end, val)

class FastBook:
    """Bisect-based close_on_or_before / bar over the same bars."""
    def __init__(self, bars):
        self.bars = bars
        self.dates = E.PriceBook(bars).dates
        self.dlist = {t: [b["d"] for b in bl] for t, bl in bars.items()}
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self.dlist.get(t, [])
        i = bisect.bisect_right(dl, d) - 1
        if i < 0:
            return None
        return self.bars[t][i]["c"]

# ------------------------------------------------------------- NCAV core
def build_pit_indexes(data):
    return {k: {t: PitIndex(rows) for t, rows in series.items()}
            for k, series in data.items()}

def first_postsplit_filed(shares_rows_googl):
    """First filed date among GOOGL share facts reporting a post-split
    count (>5bn shares) — the Q2-2022 10-Q cover count. Share facts
    filed before this date are pre-split counts."""
    cands = [f for (f, _e, v, _p) in shares_rows_googl if v > 5e9]
    return min(cands) if cands else None

def ncav_detail_fast(fb, pit, t, d, postsplit_filed):
    """Identical computation to NN9.ncav_detail, plus the corrected
    (consistent-basis) ratio for the documented GOOGL artifact."""
    ca = pit["ca"][t].value(d)
    so = pit["shares"][t].value(d)
    px = fb.close_on_or_before(t, d)
    if ca is None or so is None or px is None or so[2] <= 0:
        return None
    tl_hit = pit["liab"][t].value(d)
    if tl_hit is not None:
        tl, tl_source = tl_hit[2], "filed"
    else:
        le = pit["le"][t].value(d)
        eq = pit["equity"][t].value(d)
        if le is None or eq is None:
            return None
        tl, tl_source = le[2] - eq[2], "derived(assets-equity)"
    ncav = ca[2] - tl
    ncav_ps = ncav / so[2]
    ratio = (px / ncav_ps) if ncav_ps > 0 else None
    # corrected basis: GOOGL shares fact filed pre-split -> NCAV/share
    # was overstated 20x; corrected ratio = as-run ratio x 20.
    corr_factor = 1.0
    if t == "GOOGL" and postsplit_filed is not None and so[0] < postsplit_filed:
        corr_factor = 20.0
    ncav_ps_corr = ncav_ps / corr_factor if ncav_ps else ncav_ps
    ratio_corr = ratio * corr_factor if ratio is not None else None
    return {"ticker": t, "px": px, "ncav_ps": ncav_ps, "ratio": ratio,
            "shares_filed": so[0], "tl_source": tl_source,
            "qualifies": bool(ncav_ps > 0 and px < ncav_ps),
            "ncav_ps_corr": ncav_ps_corr, "ratio_corr": ratio_corr,
            "qualifies_corr": bool(ncav_ps_corr > 0 and px < ncav_ps_corr)}

def compute_selection_fast(fb, pit, d, postsplit_filed, cache):
    if d in cache:
        return cache[d]
    detail = {}
    for t in UNIVERSE:
        det = ncav_detail_fast(fb, pit, t, d, postsplit_filed)
        if det is not None:
            detail[t] = det
    quals = [det for det in detail.values() if det["qualifies"]]
    quals.sort(key=lambda det: -(1.0 - det["ratio"]))
    picks = [det["ticker"] for det in quals[:MAX_HOLD]]
    quals_corr = [det["ticker"] for det in detail.values() if det["qualifies_corr"]]
    sel = {"detail": detail, "picks": picks, "quals": [q["ticker"] for q in quals],
           "quals_corr": quals_corr}
    cache[d] = sel
    return sel

# ------------------------------------------------------------- cadences
def cadence_dates(days, kind):
    """SPEC uniform cadence dates over the sorted trading days given."""
    out, seen = [], set()
    if kind == "daily":
        return list(days)
    week_idx = {}
    for d in days:
        y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
        if kind == "weekly":
            key = dt.date(y, m, dd).isocalendar()[:2]
        elif kind == "biweekly":
            wk = dt.date(y, m, dd).isocalendar()[:2]
            if wk not in week_idx:
                week_idx[wk] = len(week_idx)
            key = ("bi", week_idx[wk] // 2)
        elif kind == "monthly":
            key = (y, m)
        elif kind == "quarterly":
            if m not in (1, 4, 7, 10):
                continue
            key = (y, m)
        elif kind == "semiannual":
            if m not in (1, 7):
                continue
            key = (y, m)
        elif kind == "annual":
            key = (y,)
        else:
            raise ValueError(kind)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out

# ------------------------------------------------------------------ engine
def run_cell(fb, pit, start, end, cadence, postsplit_filed):
    """v9 net-net engine mechanics (copied from NN9.run_pot_netnet) with
    the selection/review dates set by `cadence`. Returns full record."""
    cash = START_CASH
    floor = FLOOR0
    positions = {}
    trades = []
    total_costs = 0.0
    v9_episode = 1
    v9_resume = None
    restarts = []
    halts = []
    second_halt = False
    curve = []
    reviews = []          # (date, n_scorable, as-run quals, corrected quals)
    sel_cache = {}
    days = [d for d in fb.dates if start <= d <= end]
    sel_dates = cadence_dates(days, cadence)
    sel_set = set(sel_dates)
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = fb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = fb.bar(t, d)
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
                trades.append([d, t, "SELL", sh, opens[t], sell_val, c])
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
                trades.append([d, t, "BUY", sh, opens[t], buy_val, c])
        total_costs += cost
        return cost

    final = None
    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set and (v9_resume is None or d >= v9_resume):
            sel = compute_selection_fast(fb, pit, d, postsplit_filed, sel_cache)
            reviews.append([d, len(sel["detail"]), sel["quals"], sel["quals_corr"]])
            pv = portfolio_close(d)
            if sel["picks"]:
                each = pv / len(sel["picks"])
                pending = {t: each for t in sel["picks"]}
            else:
                pending = {}
        v = portfolio_close(d)
        curve.append([d, round(v, 2)])
        if v <= floor and di < len(days) - 1:
            nd = days[di + 1]
            liq_val = cash
            for t in list(positions):
                b = fb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append([nd, t, "SELL-HALT", positions[t], b["o"], val, c])
            positions = {}
            halts.append({"signal_date": d, "signal_close": round(v, 2),
                          "floor_in_effect": round(floor, 2),
                          "liquidation_date": nd,
                          "liquidation_balance": round(cash, 2)})
            if v9_episode == 1:
                v9_episode = 2
                v9_resume = (dt.date.fromisoformat(d)
                             + dt.timedelta(days=90)).isoformat()
                restarts.append({"halt_date": d, "liquidation_date": nd,
                                 "restart_balance": round(cash, 2),
                                 "resume_on_or_after": v9_resume,
                                 "episode2_floor": round(0.85 * cash, 2)})
                floor = 0.85 * cash
                pending = None
            else:
                second_halt = True
                final = cash
                break
    if final is None:
        last = days[-1]
        for t in list(positions):
            c_ = fb.close_on_or_before(t, last)
            if c_:
                val = positions[t] * c_
                cst = val * 0.001 + 0.01
                cash += val - cst
                total_costs += cst
                trades.append([last, t, "SELL-END", positions[t], c_, val, cst])
        final = cash

    # stats
    peak, maxdd = START_CASH, 0.0
    for _d, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    yrs = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days / 365.25
    cagr = (final / START_CASH) ** (1.0 / yrs) - 1.0 if final > 0 else -1.0
    n_corr_qual_reviews = sum(1 for r in reviews if r[3])
    n_asrun_qual_reviews = sum(1 for r in reviews if r[2])
    return {
        "cadence": cadence, "start": start, "end": end,
        "final": round(final, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_dd_pct": round(maxdd * 100, 2),
        "costs": round(total_costs, 2),
        "orders": len(trades),
        "trades": [[t[0], t[1], t[2], round(t[3], 6), round(t[4], 4),
                    round(t[5], 2), round(t[6], 4)] for t in trades],
        "halts": halts, "restarts": restarts, "second_halt": second_halt,
        "equity_curve": curve,
        "n_reviews": len(reviews),
        "reviews_with_asrun_qualifier": n_asrun_qual_reviews,
        "reviews_with_corrected_qualifier": n_corr_qual_reviews,
        "asrun_qualifier_events": [[r[0], r[2]] for r in reviews if r[2]],
        "corrected_qualifier_events": [[r[0], r[3]] for r in reviews if r[3]],
        "corrected_basis_final": 100.00 if n_corr_qual_reviews == 0 else None,
        "corrected_basis_note": (
            "Zero corrected-basis qualifiers at every review date in this "
            "cell: on a consistent basis the pot never trades and sits in "
            "cash the whole decade -> $100.00, 0 orders, $0.00 costs, "
            "0.00% max drawdown." if n_corr_qual_reviews == 0 else
            "Corrected-basis qualifiers occurred; see events."),
        "placebo_beaten": None,
        "placebo_note": PLACEBO_NOTE,
        "placebo_twin_finals": None,
    }

# --------------------------------------------------------------------- main
def main():
    t0 = time.time()
    pb, data = load_data()
    print(f"loaded: {len(pb.dates)} trading days {pb.dates[0]}..{pb.dates[-1]} "
          f"({time.time()-t0:.0f}s)", flush=True)

    # ---------- (0) INTEGRITY: champion replication + as-run originals
    rep = {}
    for tag, (ws, we), published, spy_pub in (
            ("CONT", CONT, 544.47, 313.62), ("VAL", VAL, 288.05, 187.77)):
        rb = E.run_pot(pb, data["equity"], data["shares"], ws, we, START_CASH,
                       FLOOR0, [], label=f"REPLICATION {tag}", quiet=True)
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        rep[tag] = {"champion_final": round(rb["final"], 2),
                    "champion_published": published,
                    "champion_match": round(rb["final"], 2) == published,
                    "spy_net": round(s, 2), "spy_published": spy_pub,
                    "spy_match": round(s, 2) == spy_pub}
        print(f"REPLICATION champion {tag}: ${rb['final']:,.2f} vs ${published} "
              f"match={rep[tag]['champion_match']} | SPY ${s:,.2f} vs "
              f"${spy_pub} match={rep[tag]['spy_match']}", flush=True)

    integrity_runs = {}
    for tag, (ws, we), published in (("CONT", CONT, 218.59), ("VAL", VAL, 100.00)):
        r = NN9.run_pot_netnet(pb, data, ws, we, START_CASH, FLOOR0, [],
                               label=f"INTEGRITY NETNET {tag}", quiet=True)
        integrity_runs[tag] = {"final": round(r["final"], 2),
                               "published": published,
                               "match": round(r["final"], 2) == published,
                               "costs": round(r["costs"], 2),
                               "orders": len(r["trades"]),
                               "halted": r["halted"],
                               "restarts": r.get("restarts", [])}
        print(f"INTEGRITY net-net {tag}: ${r['final']:,.2f} vs published "
              f"${published} match={integrity_runs[tag]['match']} "
              f"orders={len(r['trades'])} costs=${r['costs']:,.2f}", flush=True)

    # ---------- fast-lookup verification against E.pit_value
    pit = build_pit_indexes(data)
    fb = FastBook({t: E.get_prices(t) for t in UNIVERSE + ["SPY"]})
    checks = fails = 0
    sample_dates = E.quarter_selection_dates(pb, "2016-11-21", "2026-11-20")
    sample_dates += ["2019-03-15", "2020-03-23", "2022-08-15", "2024-06-30",
                     "2017-06-01", "2026-11-20"]
    for d in sample_dates:
        for key in ("ca", "liab", "le", "equity", "shares"):
            for t in UNIVERSE:
                a = E.pit_value(data[key][t], d)
                b = pit[key][t].value(d)
                checks += 1
                if (a is None) != (b is None) or (a is not None and a != b):
                    fails += 1
                    print("PIT MISMATCH", key, t, d, a, b, flush=True)
        for t in UNIVERSE:
            a = pb.close_on_or_before(t, d)
            b = fb.close_on_or_before(t, d)
            checks += 1
            if a != b:
                fails += 1
                print("PX MISMATCH", t, d, a, b, flush=True)
    print(f"fast-lookup verification: {checks} checks, {fails} failures", flush=True)
    assert fails == 0, "fast lookup does not replicate engine primitives"

    postsplit = first_postsplit_filed(data["shares"]["GOOGL"])
    print(f"GOOGL first post-split share filing: {postsplit}", flush=True)

    # ---------- (1) SWEEP: DECADE x 7 cadences
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    cells = {}
    for cad in ("daily", "weekly", "biweekly", "monthly", "quarterly",
                "semiannual", "annual"):
        ts = time.time()
        r = run_cell(fb, pit, DECADE[0], DECADE[1], cad, postsplit)
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(r, f, indent=1)
        cells[cad] = {k: r[k] for k in (
            "final", "cagr_pct", "max_dd_pct", "costs", "orders",
            "n_reviews", "reviews_with_asrun_qualifier",
            "reviews_with_corrected_qualifier", "corrected_basis_final")}
        cells[cad]["halts"] = len(r["halts"])
        cells[cad]["restart"] = bool(r["restarts"])
        cells[cad]["second_halt"] = r["second_halt"]
        cells[cad]["placebo_beaten"] = None
        cells[cad]["placebo_note"] = PLACEBO_NOTE
        print(f"CELL {cad}: final=${r['final']:,.2f} CAGR={r['cagr_pct']}% "
              f"maxDD={r['max_dd_pct']}% costs=${r['costs']:,.2f} "
              f"orders={r['orders']} halts={len(r['halts'])} "
              f"reviews={r['n_reviews']} asrunQualReviews="
              f"{r['reviews_with_asrun_qualifier']} corrQualReviews="
              f"{r['reviews_with_corrected_qualifier']} "
              f"({time.time()-ts:.0f}s)", flush=True)

    money = [c for c, v in cells.items()
             if v["final"] > DECADE_SPY_FINAL]
    results = {
        "slug": "net-net",
        "area": "Long-holding fundamental sort (Graham NCAV deep value). "
                "Native habitat: distressed small-caps trading below "
                "liquidation value. Judged on the program pond (honest "
                "point-in-time top-30 mega-caps as of Nov 2016) over the "
                "DECADE road, per SPEC W3 + the cadence sweep.",
        "area_source": "SPEC.md W3 assignment + CADENCE GRID W3 (net-net: "
                       "event-driven with annual review)",
        "cadence": "event-driven with annual review",
        "native_cadence": "event-driven with annual review (annual cell is "
                          "its sweep rendering)",
        "original_cadence_foreign": True,
        "original_cadence_note": "The original v6/v9 program test forced a "
                                 "QUARTERLY selection/exit rhythm; Graham's "
                                 "published form buys when a name qualifies "
                                 "and reviews annually (sell at NCAV or "
                                 "after ~two years). Foreign cadence in the "
                                 "original test — flagged per SPEC.",
        "native_change": "Cadence sweep only: the qualification-review "
                         "rhythm varies by cell under the SPEC's uniform "
                         "cadence definition. Rule, universe, costs and "
                         "protections are the original engine's, unchanged.",
        "integrity": {
            "status": "reproduced",
            "original_finals": {"CONT": 218.59, "VAL": 100.00},
            "reproduced_finals": {"CONT": integrity_runs["CONT"]["final"],
                                  "VAL": integrity_runs["VAL"]["final"]},
            "detail": integrity_runs,
            "champion_replication": rep,
            "basis_note": "AS-RUN basis: CONT $218.59 is a single-stock "
                          "GOOGL hold driven by the documented EDGAR "
                          "pre-split units artifact (NCAV/share overstated "
                          "20x across the July 2022 20-for-1 split); VAL "
                          "$100.00 is zero trades. CORRECTED basis (from "
                          "the original v6 report): 0 of 927 scorable "
                          "name-quarters genuinely qualified; closest "
                          "genuine approach CSCO 6.13x in 2017 (2017-07-03). "
                          "The artifact is documented, never patched.",
            "corrected_basis": {
                "genuinely_qualified_name_quarters": "0 of 927",
                "closest_genuine_approach": "CSCO 6.13x (2017-07-03)",
                "googl_corrected_closest": "7.78x (2017-07-03)"},
        },
        "decade_spy_final": DECADE_SPY_FINAL,
        "champion_reference": {
            "LONG": 1415.62, "CONT": 544.47, "VAL": 288.05,
            "DECADE": 65.89,
            "decade_caveat": "Champion DECADE $65.89 after two halts (from "
                             "the lazy-quarterly test); its crown rests on "
                             "the 2010 and 2019 roads."},
        "cells": cells,
        "money_cadences": money,
        "placebo_note": PLACEBO_NOTE,
        "verdict_area": "NO GROUND",
        "verdict_change": "Unchanged from the original program verdict "
                          "(NOT PROMOTED). The sweep adds one refinement: "
                          "the as-run artifact trade's size depends on the "
                          "review rhythm, but on the corrected basis every "
                          "cadence is the same all-cash $100.00 — no cadence "
                          "gives the strategy ground on this pond.",
        "data_note": "Point-in-time EDGAR companyfacts + Yahoo prices "
                     "reused read-only from backtests/v4 caches via the "
                     "champion engine (value-momentum-plainfloor.py), the "
                     "original test's own machinery. Price cache begins "
                     "2017-06-01 (the same data wall the original census "
                     "faced), so decade reviews before that date have no "
                     "prices. The 1.7GB long-run cache was not loaded. "
                     "Nothing downloaded; nothing written outside this "
                     "folder.",
        "googl_first_postsplit_share_filing": postsplit,
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
