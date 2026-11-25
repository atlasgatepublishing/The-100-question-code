#!/usr/bin/env python3
"""
GAP TEST A-2 — EARNINGS ANNOUNCEMENT PREMIUM (Frazzini & Lamont 2007).
Terry's AI stock app. Simulation only. No broker orders were placed.

SOURCE: Frazzini & Lamont (2007), "The Earnings Announcement Premium and
Trading Volume," NBER WP 13090; global replication: Barber, Schwarz &
Waples, "The Earnings Announcement Premium Around the Globe." The claim:
stocks earn higher returns in months they are SCHEDULED to announce
earnings than in other months — regardless of whether the news is good
or bad (~61 bp/month long-short; ~7%/yr; the paper stresses the effect
is substantial among LARGE CAPS, and the bulk accrues BEFORE the
announcement day). This is the scheduled-window premium, known in
advance, sign-independent. It is NOT PEAD (census section 2, failed
twice): PEAD is drift AFTER an announcement, conditional on the
surprise. This family was found by the missing-family hunt
(research/v7-completeness/missing-families.md, Table A, item A-2) and
is run here as ONE clean shot, exactly per that frozen spec. No tuning.

THE SPEC (verbatim from missing-families.md, Table A, item A-2):
  "Monthly rotation on the pond. A name is 'expected to announce' in
  month m if, point-in-time, its own EDGAR history (prior-year
  same-fiscal-quarter earnings release / Item 2.02 8-K dates) puts its
  announcement in m. Pot holds that month's expected announcers
  equal-weight (typically ~10 names), cash otherwise; benchmark SPY and
  the champion. Full monthly turnover is part of the trial."

HOUSE CHASSIS (identical to the champion's):
  - Universe: the honest point-in-time top-30 pond as of Nov 2016
    (the champion engine's UNIVERSE, imported).
  - Pot: $100. Costs: 0.10% of trade value per side + $0.01 per sell
    order. Fractional shares.
  - Protection: PLAIN -15% floor only ($85.00, no ladder). Close
    at/below floor -> liquidate at next open, run ends.
  - Windows: FULL continuous 2019-01-02 -> 2026-11-20 (primary) and
    VALIDATION 2023-01-03 -> 2026-11-20. End of window: liquidate at
    final close.
  - Judged vs SPY buy-hold net (champion engine's spy_net) and vs the
    promoted champion (value + momentum: validation $288.05,
    continuous $544.47), plus 20-seed placebos on the same
    dates/mechanics (seeds 1..20, the program's standard).
  - Prices: the champion engine's Yahoo cache (split/dividend-adjusted
    opens/closes), reused read-only from backtests/v4/data.

FORCED READINGS (stated here, before any result — the spec's prose
leaves these points open; each reading is the plainest one available,
chosen before the run, and none was changed after seeing results):
  R1. "Expected to announce in month m" = the name filed at least one
      Item 2.02 earnings-release 8-K (form 8-K or 8-K/A) in the SAME
      CALENDAR MONTH of the PRIOR calendar year — the prior-year
      same-fiscal-quarter announcement. Strict calendar-month match;
      the spec names no day tolerance, so none is applied. The prior-
      year filing date must also be strictly before the selection day
      (point-in-time; automatically true, enforced anyway).
  R2. Decision/execution timing follows the champion engine's
      mechanics verbatim: the selection day is the first trading day
      of month m; the expected set is computed from filings dated
      strictly before that day; equal-weight targets are set from the
      selection day's closing pot value and executed at the NEXT
      trading day's open (the champion's pending-rebalance rule).
  R3. "Cash otherwise": when a month has expected announcers, the pot
      is fully invested, equal weight across them (targets sum to the
      full pot value); a month with ZERO expected announcers puts the
      pot fully in cash for that month.
  R4. Placebo: at each selection day, the placebo holds the same COUNT
      of names as the ranked pot that month, drawn uniformly without
      replacement from the full 30-name pond (an actual expected
      announcer may be drawn by chance — that is what "random" means),
      same dates, same mechanics, same floor. Seeds 1..20.
  R5. Earnings events are Item 2.02 dates from the EDGAR submissions
      API (filing date = announcement date) — the program's
      established PEAD convention. A name whose Item 2.02 history is
      thin is simply rarely or never "expected"; it is never patched
      with another source (e.g. Berkshire files few Item 2.02 8-Ks).

INTEGRITY GATE (run first, before any strategy number is taken): the
imported champion engine must reproduce its published figures to the
cent — champion $544.47 continuous / $288.05 validation, SPY net
$313.62 / $187.77. If the gate fails, the run stops.
"""
import importlib.util
import json
import os
import random
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "edgar-cache")
os.makedirs(CACHE, exist_ok=True)
CHAMPION_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py")

spec = importlib.util.spec_from_file_location("champion", CHAMPION_PATH)
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
UA = E.UA
START_CASH = 100.0
FLOOR0 = 85.0
PLACEBO_SEEDS = list(range(1, 21))
EVENT_FROM = "2017-06-01"     # need prior-year months for Jan 2019 onward
EVENT_TO = "2026-11-21"
CIK_OVERRIDES = {"XOM": 34088}  # same override as the champion engine

WINDOWS = [
    ("FULL", "2019-01-02", "2026-11-20"),
    ("VALIDATION", "2023-01-03", "2026-11-20"),
]

# ---------------------------------------------------------------- EDGAR events
def fetch_cached(url, path, headers=None):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        blob = r.read()
    with open(path, "wb") as f:
        f.write(blob)
    time.sleep(0.15)  # EDGAR etiquette: well under 10 req/s
    return blob


def filings_from_block(block, out, ticker):
    forms = block.get("form", [])
    dates = block.get("filingDate", [])
    items = block.get("items", [])
    for i, form in enumerate(forms):
        if form not in ("8-K", "8-K/A"):
            continue
        fd = dates[i] if i < len(dates) else ""
        if not fd or fd < EVENT_FROM or fd > EVENT_TO:
            continue
        it = items[i] if i < len(items) else ""
        if "2.02" in [s.strip() for s in it.split(",")]:
            out.append(fd)


def get_earnings_dates():
    """ticker -> sorted list of Item 2.02 8-K filing dates (strings)."""
    cache_file = os.path.join(CACHE, "earnings_dates.json")
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            return json.load(f)
    ciks = E.get_ciks()
    out = {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        sub = json.loads(fetch_cached(
            f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
            os.path.join(CACHE, f"sub_{t}.json")))
        dates = []
        filings_from_block(sub["filings"]["recent"], dates, t)
        for extra in sub["filings"].get("files", []):
            if extra["filingTo"] < EVENT_FROM or extra["filingFrom"] > EVENT_TO:
                continue
            block = json.loads(fetch_cached(
                f"https://data.sec.gov/submissions/{extra['name']}",
                os.path.join(CACHE, f"sub_{t}_{extra['name']}")))
            filings_from_block(block, dates, t)
        out[t] = sorted(set(dates))
        print(f"  EDGAR {t}: {len(out[t])} Item 2.02 earnings dates "
              f"({out[t][0] if out[t] else '-'}..{out[t][-1] if out[t] else '-'})",
              flush=True)
    with open(cache_file, "w") as f:
        json.dump(out, f, indent=1)
    return out


def expected_announcers(earn_dates, sel_date):
    """R1: names with an Item 2.02 filing in the same calendar month of
    the prior year, filed strictly before sel_date."""
    y, m = int(sel_date[:4]), sel_date[5:7]
    target = f"{y - 1}-{m}"
    return sorted(t for t in UNIVERSE
                  if any(fd.startswith(target) and fd < sel_date
                         for fd in earn_dates.get(t, [])))


# ------------------------------------------------------------------- engine
def month_selection_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end:
            key = d[:7]
            if key not in seen:
                seen.add(key)
                out.append(d)
    return out


def run_monthly(pb, earn_dates, start, end, start_cash=START_CASH,
                floor0=FLOOR0, placebo_rng=None, label="", quiet=True):
    """Champion run_pot mechanics verbatim (execute_rebalance, floor,
    end-of-window liquidation), with the quarterly V+M selection
    replaced by the A-2 monthly expected-announcer set (or a same-count
    random draw when placebo_rng is given)."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    months = []          # (selection date, ranked expected set, picks held)
    sel_dates = month_selection_dates(pb, start, end)
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
            expected = expected_announcers(earn_dates, d)
            if placebo_rng is not None:
                picks = placebo_rng.sample(sorted(UNIVERSE), len(expected))
            else:
                picks = expected
            months.append((d, expected, list(picks)))
            pv = portfolio_close(d)
            if picks:
                each = pv / len(picks)
                pending = {t: each for t in picks}
            else:
                pending = {}
            if not quiet:
                print(f"  [{label}] {d} expected={len(expected)} "
                      f"picks={picks} pot=${pv:,.2f}", flush=True)
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
                    "halt_info": halt_info, "months": months, "curve": curve}
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
            "halt_info": None, "months": months, "curve": curve}


def placebo_summary(ranked_final, finals):
    srt = sorted(finals)
    beats = sum(1 for f in finals if ranked_final > f)
    return {"finals": [round(f, 2) for f in finals],
            "median": round(E._pct(srt, 0.5), 2),
            "min": round(srt[0], 2), "max": round(srt[-1], 2),
            "beats": beats, "of": len(finals),
            "percentile": round(100.0 * beats / len(finals), 1)}


# --------------------------------------------------------------------- main
def main():
    print("Fetching EDGAR Item 2.02 earnings dates...", flush=True)
    earn_dates = get_earnings_dates()

    print("Loading prices (champion cache, read-only)...", flush=True)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    pb = E.PriceBook(bars)

    # ---- (0) integrity gate: champion engine reproduces published numbers
    print("Building champion PIT rows for the replication check...", flush=True)
    ciks = E.get_ciks()
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic",
                         prio=1))
    gate = {}
    for wname, ws, we in WINDOWS:
        r = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                      FLOOR0, [], label=f"GATE {wname}", quiet=True)
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        gate[wname] = {"champion_final": round(r["final"], 2),
                       "spy_net": round(s, 2)}
        print(f"  GATE {wname}: champion=${r['final']:,.2f} SPY net=${s:,.2f}",
              flush=True)
    assert abs(gate["FULL"]["champion_final"] - 544.47) < 0.01, gate
    assert abs(gate["VALIDATION"]["champion_final"] - 288.05) < 0.01, gate
    assert abs(gate["FULL"]["spy_net"] - 313.62) < 0.01, gate
    assert abs(gate["VALIDATION"]["spy_net"] - 187.77) < 0.01, gate
    print("Replication gate PASSED (champion $544.47 / $288.05; "
          "SPY $313.62 / $187.77).", flush=True)

    # ---- ranked runs + placebos, both windows
    results = {"gate": gate, "spec": "missing-families.md Table A item A-2",
               "universe": UNIVERSE,
               "event_counts": {t: len(earn_dates.get(t, [])) for t in UNIVERSE}}
    for wname, ws, we in WINDOWS:
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        r = run_monthly(pb, earn_dates, ws, we, label=f"{wname} RANKED")
        diag = E.diagnostics(r, FLOOR0)
        finals = []
        phalts = 0
        for seed in PLACEBO_SEEDS:
            pr = run_monthly(pb, earn_dates, ws, we,
                             placebo_rng=random.Random(seed),
                             label=f"{wname} PLACEBO {seed}")
            finals.append(pr["final"])
            if pr["halted"]:
                phalts += 1
        ps = placebo_summary(r["final"], finals)
        ps["halts"] = phalts
        counts = [len(m[1]) for m in r["months"]]
        results[wname] = {
            "final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted": r["halted"],
            "halt_info": r["halt_info"], "spy_net": round(s, 2),
            "diag": diag, "placebo": ps,
            "months_count": len(counts),
            "announcers_per_month": {"min": min(counts), "max": max(counts),
                                     "mean": round(sum(counts) / len(counts), 2)},
            "months": [{"date": m[0], "expected": m[1]} for m in r["months"]],
            "trades": r["trades"]}
        print(f"== {wname} RANKED final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halted={r['halted']} | SPY net=${s:,.2f} | "
              f"placebo median=${ps['median']:,.2f} beats={ps['beats']}/20",
              flush=True)

    # ---- walk-forward folds: fresh $100 pot per calendar year, 2020-2026
    folds = []
    for y in range(2020, 2027):
        days = [d for d in pb.dates if d[:4] == str(y) and d <= "2026-11-20"]
        if not days:
            continue
        fs, fe = days[0], days[-1]
        fr = run_monthly(pb, earn_dates, fs, fe, label=f"FOLD {y}")
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        folds.append({"year": y, "start": fs, "end": fe,
                      "final": round(fr["final"], 2),
                      "return_pct": round((fr["final"] / START_CASH - 1) * 100, 2),
                      "spy_net": round(fspy, 2),
                      "spy_return_pct": round((fspy / START_CASH - 1) * 100, 2),
                      "beat_spy": fr["final"] > fspy,
                      "halted": fr["halted"], "costs": round(fr["costs"], 2),
                      "orders": len(fr["trades"])})
        print(f"  FOLD {y}: final=${fr['final']:,.2f} vs SPY ${fspy:,.2f} "
              f"beat={fr['final'] > fspy} halted={fr['halted']}", flush=True)
    comp, scomp = 100.0, 100.0
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
        scomp *= 1 + f["spy_return_pct"] / 100.0
    results["folds"] = {"folds": folds,
                        "wins": sum(1 for f in folds if f["beat_spy"]),
                        "losses": sum(1 for f in folds if not f["beat_spy"]),
                        "fold_compounded_final": round(comp, 2),
                        "spy_fold_compounded_final": round(scomp, 2)}

    # ---- diagnostic (descriptive only; never fed to the strategy):
    # how often did an "expected" announcer actually announce that month?
    hits, tot = 0, 0
    for wname, ws, we in WINDOWS[:1]:
        for d, expected, _p in run_monthly(pb, earn_dates, ws, we,
                                           label="diag")["months"]:
            ym = d[:7]
            actual = {t for t in UNIVERSE
                      if any(fd.startswith(ym) for fd in earn_dates.get(t, []))}
            hits += len(set(expected) & actual)
            tot += len(expected)
    results["inference_diagnostic"] = {
        "note": "Share of expected-announcer slots (FULL window) whose name "
                "did in fact file an Item 2.02 8-K in that month. Ex-post "
                "description of the R1 inference only; not a strategy input.",
        "hits": hits, "slots": tot,
        "hit_rate_pct": round(100.0 * hits / tot, 1) if tot else None}

    with open(os.path.join(HERE, "gap-a2-earnings-premium-results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__" and False:
    main()  # original entry disabled in v9 copy


# =====================================================================
# CLAUDE-RULES PROTECTION SPEC v9 — the ONLY change vs the original.
# Original run_monthly() above is byte-identical (signal, universe,
# costs, execution). v9 wraps it in episodes:
#   Episode 1: plain -15% floor from the $100 start ($85) — identical
#     to the original protection.
#   On FIRST halt: liquidate exactly as run_monthly does (next open,
#     same costs), sit in cash 90 calendar days from the liquidation
#     date, then RESTART with the remaining cash at the next regular
#     monthly decision point (first trading day of a month).
#   Episode 2: floor = -15% from the RESTART balance (0.85 x cash).
#   On SECOND halt: run ends permanently.
# Ranked pot only; no placebos in this re-run.
# =====================================================================
import datetime as _dt

ORIG_CACHE = os.path.expanduser(
    "~/workspace/stock-app/backtests/v7/gap-a2-earnings-premium/edgar-cache")


def run_monthly_v9(pb, earn_dates, start, end, label=""):
    sel_dates = month_selection_dates(pb, start, end)
    ep1 = run_monthly(pb, earn_dates, start, end, label=label + " EP1")
    base = {"episodes": 1, "ep1_halted": ep1["halted"],
            "ep1_final": round(ep1["final"], 2),
            "costs": ep1["costs"], "orders": len(ep1["trades"]),
            "restart": None, "ep2_halted": None,
            "curve_min": min((v for _d, v in ep1["curve"]), default=None)}
    if not ep1["halted"]:
        base.update({"final": ep1["final"], "status": "no_halt"})
        return base
    liq_date = ep1["end"]
    cash1 = ep1["final"]
    eligible = (_dt.date.fromisoformat(liq_date)
                + _dt.timedelta(days=90)).isoformat()
    restart = next((d for d in sel_dates if d >= eligible), None)
    if restart is None:
        base.update({"final": cash1,
                     "status": "halted_ep1_no_restart_in_window"})
        return base
    floor2 = round(0.85 * cash1, 2)
    ep2 = run_monthly(pb, earn_dates, restart, end, start_cash=cash1,
                      floor0=0.85 * cash1, label=label + " EP2")
    base.update({"episodes": 2, "final": ep2["final"],
                 "costs": ep1["costs"] + ep2["costs"],
                 "orders": len(ep1["trades"]) + len(ep2["trades"]),
                 "ep2_halted": ep2["halted"],
                 "status": "halted_ep2_run_ends" if ep2["halted"]
                           else "restarted_completed",
                 "restart": {"halt_signal_date": ep1["halted"],
                             "liquidation_date": liq_date,
                             "cash_at_halt": round(cash1, 2),
                             "eligible_from": eligible,
                             "restart_date": restart,
                             "restart_balance": round(cash1, 2),
                             "episode2_floor": floor2}})
    return base


def main_v9():
    global CACHE
    CACHE = ORIG_CACHE   # read the original test's EDGAR cache, read-only
    earn_dates = get_earnings_dates()
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    pb = E.PriceBook(bars)
    out = {"spec": "CLAUDE-RULES PROTECTION SPEC v9 (90-day sit-out, one "
                   "restart, ep2 floor -15% from restart balance)",
           "ranked_only": True}
    for wname, ws, we in WINDOWS:
        r = run_monthly_v9(pb, earn_dates, ws, we, label=wname + " RANKED")
        out[wname] = r
        print(f"== {wname}: v9 final=${r['final']:,.2f} status={r['status']} "
              f"ep1_halted={r['ep1_halted']} restart={r['restart']}",
              flush=True)
    folds = []
    for y in range(2020, 2027):
        days = [d for d in pb.dates if d[:4] == str(y) and d <= "2026-11-20"]
        if not days:
            continue
        fr = run_monthly_v9(pb, earn_dates, days[0], days[-1],
                            label=f"FOLD {y}")
        folds.append({"year": y, "start": days[0], "end": days[-1],
                      "final": round(fr["final"], 2),
                      "status": fr["status"], "ep1_halted": fr["ep1_halted"],
                      "restart": fr["restart"], "ep2_halted": fr["ep2_halted"]})
        print(f"  FOLD {y}: v9 final=${fr['final']:,.2f} "
              f"status={fr['status']} restart={fr['restart']}", flush=True)
    comp = 100.0
    for f in folds:
        comp *= f["final"] / 100.0
    out["folds"] = {"folds": folds,
                    "fold_compounded_final": round(comp, 2)}
    with open(os.path.join(HERE, "v9-raw-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main_v9()
