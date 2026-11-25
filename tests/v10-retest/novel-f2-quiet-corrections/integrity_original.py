#!/usr/bin/env python3
"""
NOVEL TEST N-F2 — "QUIET CORRECTIONS" (amendment-cadence sort) — Terry's
AI stock app, v8 novel ("never been done") track. Simulation only.

Implements Rule N-F2 from research/v8-novel/novel-filings.md VERBATIM.
The spec is frozen: no parameter was improved, re-cut, or reinterpreted.
Forced readings are declared in the report BEFORE results and summarized
in the header notes of the results JSON.

Spec N-F2 as written:
  - Data: EDGAR submissions history per pond CIK (form type, acceptance
    date). Filing-behavior metadata ONLY — the rule never reads a filing's
    content, a financial number, or any 8-K.
  - Signal: at each selection date, over the trailing 1,095 days:
        AMEND_RATE = (count of 10-K/A + 10-Q/A filings)
                     / (count of 10-K + 10-Q filings)
    Rank the pond ASCENDING (cleanest reporting record first). Hold the
    top 5, equal weight.
  - Tie-breaks (frozen): lower absolute amendment count first; then
    fewer denominator filings; then ticker, A->Z.
  - Eligibility: denominator >= 10 over the trailing 1,095 days (an
    established quarterly filer). Otherwise unscorable and excluded —
    never patched.

House chassis (shared, frozen for the whole v8 filings batch):
  - Universe: the honest top-30 pond as of Nov 2016 (champion engine's
    UNIVERSE). $100 pot, long-only, fractional shares, entire pot
    reinvested at every rebalance.
  - Selection: quarterly, first trading day of Jan/Apr/Jul/Oct; trades
    execute at the next open (champion-engine mechanics: sell dropouts
    in full, keep survivors, equal-weight the new top-5).
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Protection: plain -15% floor — a close at or below $85.00 liquidates
    the pot at the next open and ends the run. No ladder, ever.
  - Point-in-time: only filings with an EDGAR acceptance date STRICTLY
    BEFORE the selection date are counted.
  - Windows: continuous 2019-01-02 -> 2026-11-20 and validation
    2023-01-03 -> 2026-11-20; benchmarks SPY buy-hold net of the same
    costs (the champion engine's spy_net, imported) and a 20-seed random
    placebo (random 5 names drawn from the same selection date's
    ELIGIBLE set, identical dates and mechanics).

INVENTED-RULE BAR (harsher than for published families; this rule was
invented in 2026 and is reported as "1 of 12 invented rules"): the best
possible verdict is CANDIDATE — only a forward paper trial can promote
an invented rule. CANDIDATE requires ALL of: (1) validation final >
SPY $187.77, (2) validation placebo >= 19/20, (3) continuous final >
SPY $313.62, (4) no floor halt on either main window. Anything less is
NOT A CANDIDATE.

FORCED READINGS (declared here and in the report, before results):
  R1. Trailing window: acceptance calendar date in [selection - 1095
      days, selection) — the 1,095 calendar days ending the day before
      the selection date. The strictly-before end is the chassis PIT
      rule; the start is inclusive.
  R2. Acceptance date = the calendar date of EDGAR's acceptanceDateTime
      field in the submissions history. (If acceptanceDateTime were ever
      absent in range, filingDate would be used and counted; the run
      reports how many fallbacks occurred — expected zero for 2015+.)
  R3. Pond CIK = the program's own mapping (company_tickers.json, with
      the champion engine's XOM override to parent CIK 34088). Disney's
      pond CIK (1744489, the post-Fox successor registrant) has a
      submissions history beginning only in 2018-2019, so DIS fails the
      denominator >= 10 gate at early selection dates and enters only
      once ten periodic filings have accumulated under that CIK. That
      is the spec's mechanical outcome — documented, NOT patched (no
      predecessor-CIK merge), exactly as the frozen eligibility rule
      prescribes.
  R4. If fewer than 5 names are eligible at a selection date, champion
      mechanics apply unchanged: no rebalance that quarter (the
      existing book rides). Expected never to bind (the pond files ~12
      periodic reports per 1,095 days); the run reports the eligible
      count at every selection date.

Integrity: before any variant number is taken, the imported champion
engine must reproduce its published figures to the cent ($544.47
continuous, $288.05 validation, SPY nets $313.62 / $187.77).
"""
import importlib.util
import json
import os
import random
import time
import urllib.request
from bisect import bisect_left
from datetime import date as _date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

ENGINE_PATH = os.path.join(HERE, "..", "..", "v4",
                           "value-momentum-plainfloor.py")
spec = importlib.util.spec_from_file_location("champion_engine",
                                              ENGINE_PATH)
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
UA = "AtlasGateResearch terry-research@example.com"
START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
PLACEBO_SEEDS = list(range(1, 21))
ORIG_FORMS = ("10-K", "10-Q")
AMEND_FORMS = ("10-K/A", "10-Q/A")
TRAILING_DAYS = 1095
MIN_DENOM = 10

WINDOWS = [
    ("FULL", "2019-01-02", "2026-11-20"),
    ("VALIDATION", "2023-01-03", "2026-11-20"),
]
CHAMPION_REF = {"FULL": 544.47, "VALIDATION": 288.05}
SPY_REF = {"FULL": 313.62, "VALIDATION": 187.77}

# ---------------------------------------------------------------- EDGAR
def fetch(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url,
                                         headers=headers or
                                         {"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            with open(path, "wb") as f:
                f.write(blob)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")


def get_submissions(cik):
    """Merged EDGAR submissions history for one CIK: the main
    submissions JSON plus every archive file it lists. Returns a list
    of {form, acc_date, accession} for ALL forms (filtering happens in
    the signal), deduped by accession number. Cached compactly."""
    cache = os.path.join(DATA, f"sub_{cik:010d}.json")
    if os.path.exists(cache) and os.path.getsize(cache) > 100:
        with open(cache) as f:
            return json.load(f)
    main = json.loads(fetch(
        f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
        os.path.join(DATA, f"submissions_{cik:010d}.json"),
        headers={"User-Agent": UA}))
    chunks = [main.get("filings", {}).get("recent", {})]
    for finfo in main.get("filings", {}).get("files", []):
        name = finfo["name"]
        sub = json.loads(fetch(
            f"https://data.sec.gov/submissions/{name}",
            os.path.join(DATA, name), headers={"User-Agent": UA}))
        chunks.append(sub)
        time.sleep(0.12)
    seen = {}
    n_fallback = 0
    for ch in chunks:
        forms = ch.get("form", [])
        accs = ch.get("accessionNumber", [])
        adts = ch.get("acceptanceDateTime", [])
        fds = ch.get("filingDate", [])
        for i, form in enumerate(forms):
            acc = accs[i] if i < len(accs) else ""
            if acc in seen:
                continue
            adt = adts[i] if i < len(adts) else ""
            if adt:
                acc_date = adt[:10]
            else:
                acc_date = fds[i] if i < len(fds) else ""
                n_fallback += 1
            seen[acc] = {"form": form, "acc_date": acc_date,
                         "accession": acc}
    rows = sorted(seen.values(), key=lambda r: r["acc_date"])
    with open(cache, "w") as f:
        json.dump({"rows": rows, "n_acceptance_fallbacks": n_fallback}, f)
    return {"rows": rows, "n_acceptance_fallbacks": n_fallback}


def build_signal_data(ciks):
    """Per ticker: two sorted lists of acceptance dates — originals
    (10-K + 10-Q) and amendments (10-K/A + 10-Q/A)."""
    orig, amend, coverage = {}, {}, {}
    for t in UNIVERSE:
        sub = get_submissions(ciks[t])
        rows = sub["rows"]
        o = sorted(r["acc_date"] for r in rows if r["form"] in ORIG_FORMS)
        a = sorted(r["acc_date"] for r in rows if r["form"] in AMEND_FORMS)
        orig[t], amend[t] = o, a
        coverage[t] = {
            "cik": ciks[t],
            "n_originals_all": len(o),
            "n_amendments_all": len(a),
            "first_original": o[0] if o else None,
            "last_original": o[-1] if o else None,
            "n_acceptance_fallbacks": sub["n_acceptance_fallbacks"],
        }
        print(f"{t}: CIK {ciks[t]} originals={len(o)} amendments={len(a)} "
              f"first={coverage[t]['first_original']} "
              f"last={coverage[t]['last_original']}", flush=True)
        time.sleep(0.12)
    return orig, amend, coverage


def amend_counts(orig_dates, amend_dates, sel_date):
    """(n_amend, n_denom) with acceptance date in
    [sel_date - 1095 days, sel_date)."""
    y, m, dd = int(sel_date[:4]), int(sel_date[5:7]), int(sel_date[8:10])
    lo = (_date(y, m, dd) - timedelta(days=TRAILING_DAYS)).isoformat()
    n_o = (bisect_left(orig_dates, sel_date) -
           bisect_left(orig_dates, lo))
    n_a = (bisect_left(amend_dates, sel_date) -
           bisect_left(amend_dates, lo))
    return n_a, n_o


# ---------------------------------------------------------------- engine
# Champion run_pot (value-momentum-plainfloor.py) copied verbatim EXCEPT
# the scoring block, which is replaced by the N-F2 amendment-rate signal.
# All trade mechanics, cost math, floor semantics and end-of-window
# liquidation are byte-identical to the champion's.
def run_pot_nf2(pb, orig, amend, start, end, start_cash,
                floor0, ladder, placebo_rng=None, label="", quiet=False):
    """Simulate one pot under the N-F2 signal. Returns the champion's
    result dict plus 'selections': per-selection-date detail (eligible
    count, ranked table, picks)."""
    cash = start_cash
    floor = floor0
    positions = {}  # ticker -> shares
    trades = []     # (date, ticker, side, shares, price, value, cost)
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []      # (date, close equity) — instrumentation only
    selections = []  # (date, eligible, ranked rows, picks)
    sel_dates = E.quarter_selection_dates(pb, start, end)
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
        # selection day: compute targets from filings accepted before today
        if d in sel_set:
            scores = {}  # ticker -> (amend_rate, n_amend, n_denom)
            for t in UNIVERSE:
                n_a, n_o = amend_counts(orig[t], amend[t], d)
                if n_o >= MIN_DENOM:
                    scores[t] = (n_a / n_o, n_a, n_o)
            if len(scores) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    # frozen rank: AMEND_RATE asc; ties -> fewer
                    # amendments; then fewer denominator filings; then
                    # ticker A->Z.
                    ranked = sorted(
                        scores.items(),
                        key=lambda kv: (kv[1][0], kv[1][1], kv[1][2],
                                        kv[0]))
                    picks = [t for t, _ in ranked[:5]]
                    selections.append({
                        "date": d,
                        "eligible": len(scores),
                        "ranked": [[t, round(v[0], 4), v[1], v[2]]
                                   for t, v in ranked],
                        "picks": list(picks),
                    })
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} eligible={len(scores)} "
                          f"picks={picks} pot=${pv:,.2f}", flush=True)
        # end of day: ladder then floor check
        v = portfolio_close(d)
        curve.append((d, v))
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor:
                floor = newfloor
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            # liquidate at next open
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
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "curve": curve,
                    "selections": selections}
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
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "curve": curve, "selections": selections}


def _pct(sorted_vals, q):
    return E._pct(sorted_vals, q)


def summarize(r, diag):
    return {
        "final": round(r["final"], 2),
        "return_pct": round((r["final"] / START_CASH - 1) * 100, 2),
        "costs": round(r["costs"], 2),
        "n_trades": len(r["trades"]),
        "halted": r["halted"],
        "halt_info": r["halt_info"],
        "max_drawdown_pct": diag["max_drawdown_pct"],
        "max_drawdown_date": diag["max_drawdown_date"],
        "worst_close": diag["worst_close"],
        "worst_close_date": diag["worst_close_date"],
        "worst_close_above_floor": diag["worst_close_above_floor"],
        "covid_worst_close": diag["covid_worst_close"],
        "covid_worst_date": diag["covid_worst_date"],
        "year_end_closes": {y: v["close"]
                            for y, v in diag["year_end_closes"].items()},
        "trades": r["trades"],
    }


# ------------------------------------------------------------------ main
def main():
    ciks_map = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    ciks = {t: CIK_OVERRIDES.get(t, ciks_map[t][0]) for t in UNIVERSE}

    # ---- champion replication data (EDGAR facts, engine's own chains)
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        facts = E.get_companyfacts(ciks[t])
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributable"
                         "ToNoncontrollingInterest", prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei",
                         "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap",
                         "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "WeightedAverageNumberOfSharesOutstandingBasic",
                         prio=1))
        print(f"{t}: equity facts={len(equity_rows[t])} "
              f"shares facts={len(shares_rows[t])}", flush=True)
        time.sleep(0.15)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
        print(f"{t}: {len(bars[t])} bars "
              f"{bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = E.PriceBook(bars)

    # ---- (0) replication check: imported champion engine, published
    # numbers to the cent, BEFORE any N-F2 number is taken.
    for wname, ws, we in WINDOWS:
        rb = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, label=f"REPL {wname}", quiet=True)
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        print(f"REPLICATION {wname}: champion=${rb['final']:,.2f} "
              f"(published ${CHAMPION_REF[wname]:,.2f}) "
              f"SPY=${s:,.2f} (published ${SPY_REF[wname]:,.2f}) "
              f"halted={rb['halted']}", flush=True)
        assert round(rb["final"], 2) == CHAMPION_REF[wname], \
            f"champion replication failed on {wname}"
        assert round(s, 2) == SPY_REF[wname], \
            f"SPY replication failed on {wname}"
    print("REPLICATION CHECK PASSED", flush=True)

    # ---- N-F2 signal data: EDGAR submissions history
    orig, amend, coverage = build_signal_data(ciks)

    out = {
        "strategy": "NOVEL N-F2 QUIET CORRECTIONS (amendment-cadence "
                    "quarterly top-5 sort), $100, plain -15% floor",
        "spec_source": "research/v8-novel/novel-filings.md, Rule N-F2",
        "invented_rule_context": "1 of 12 invented rules (v8 novel "
                                 "track); best possible verdict is "
                                 "CANDIDATE — only a forward paper trial "
                                 "can promote an invented rule",
        "candidate_bar": {
            "validation_final_gt_spy": SPY_REF["VALIDATION"],
            "validation_placebo_min": "19/20",
            "continuous_final_gt_spy": SPY_REF["FULL"],
            "no_floor_halt_either_main_window": True,
        },
        "forced_readings": [
            "R1 trailing window = acceptance date in [selection-1095d, "
            "selection)",
            "R2 acceptance date = date part of EDGAR acceptanceDateTime",
            "R3 pond CIK = program mapping (DIS under successor CIK "
            "1744489; early ineligibility is the spec's mechanical "
            "outcome, not patched)",
            "R4 fewer than 5 eligible -> champion mechanics (no "
            "rebalance that quarter)",
        ],
        "pot": START_CASH,
        "floor": FLOOR0,
        "signal_coverage": coverage,
    }

    verdict_checks = {}
    for wname, ws, we in WINDOWS:
        key = "full" if wname == "FULL" else "validation"
        s, s_costs = E.spy_net(pb, ws, we, START_CASH)
        r = run_pot_nf2(pb, orig, amend, ws, we, START_CASH, FLOOR0,
                        LADDER, label=f"{wname} N-F2")
        diag = E.diagnostics(r, FLOOR0)
        block = summarize(r, diag)
        block["start"], block["end"] = ws, we
        block["spy_net_final"] = round(s, 2)
        block["spy_costs"] = round(s_costs, 2)
        block["champion_final"] = CHAMPION_REF[wname]
        block["selections"] = r["selections"]

        # ---- 20-seed placebo: random 5 from the same eligible set,
        # identical dates/mechanics.
        rows = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            rp = run_pot_nf2(pb, orig, amend, ws, we, START_CASH, FLOOR0,
                             LADDER, placebo_rng=rng,
                             label=f"{wname} P{seed}", quiet=True)
            rows.append({"seed": seed, "final": round(rp["final"], 2),
                         "halted": rp["halted"]})
            print(f"  [{wname}] placebo seed {seed}: "
                  f"${rp['final']:,.2f} halted={rp['halted']}",
                  flush=True)
        finals = sorted(x["final"] for x in rows)
        beaten = sum(1 for x in rows if r["final"] > x["final"])
        block["placebo"] = {
            "median": round(_pct(finals, 0.5), 2),
            "q1": round(_pct(finals, 0.25), 2),
            "q3": round(_pct(finals, 0.75), 2),
            "best": finals[-1],
            "worst": finals[0],
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for x in rows if x["halted"]),
            "ranked_final": round(r["final"], 2),
            "ranked_minus_median": round(r["final"] - _pct(finals, 0.5),
                                         2),
            "seeds_beaten": beaten,
            "ranked_percentile": round(beaten / len(rows) * 100, 1),
            "rows": rows,
        }
        out[key] = block
        print(f"== {wname} N-F2 final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halted={r['halted']} | SPY=${s:,.2f} | "
              f"placebo median=${block['placebo']['median']:,.2f} "
              f"beats {beaten}/20", flush=True)

    v, f = out["validation"], out["full"]
    verdict_checks = {
        "validation_final_gt_spy_187.77":
            v["final"] > SPY_REF["VALIDATION"],
        "validation_placebo_ge_19_of_20":
            v["placebo"]["seeds_beaten"] >= 19,
        "continuous_final_gt_spy_313.62":
            f["final"] > SPY_REF["FULL"],
        "no_floor_halt_either_window":
            v["halted"] is None and f["halted"] is None,
    }
    out["candidate_checks"] = verdict_checks
    out["verdict"] = ("CANDIDATE" if all(verdict_checks.values())
                      else "NOT A CANDIDATE")
    print(f"CANDIDATE CHECKS: {verdict_checks}", flush=True)
    print(f"VERDICT: {out['verdict']}", flush=True)

    with open(os.path.join(
            HERE, "novel-f2-quiet-corrections-results.json"), "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
