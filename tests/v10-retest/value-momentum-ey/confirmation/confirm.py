#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — CONFIRMATION RUN — value-momentum-ey.
Simulation only.

Terry's confirmation rule (SPEC.md, 2026-11-21 ~22:19): the cadence
sweep crowned WEEKLY — a faster-than-native tempo — as this variant's
best money cadence on the DECADE road ($554.19, 20/20 placebos). A new
money cadence is not crowned until it is re-run on the OTHER roads.
This script re-runs the variant, with plumbing IDENTICAL to the sweep
(it imports ../sweep.py and reuses its PriceBook / PitChain / Scorer /
cadence_dates / run_one / spy_net verbatim), at WEEKLY and MONTHLY on:

  CONT  2019-01-02 -> 2026-11-20   (SPY reference $313.62)
  VAL   2023-01-03 -> 2026-11-20   (SPY reference $187.77)
  LONG  2010-01-04 -> 2026-11-20   (SPY reference $822.94) — WEEKLY only

plus a quarterly plumbing proof on CONT/VAL (must land on the original
published $302.28 / $227.25), fresh yearly folds 2017-2026 at weekly,
and 20-seed random-rank placebos per cadence per road (the sweep's twin
design: rng.sample(sorted(scored pool), 5) at each selection date).

LONG constructibility (judged before running, documented in
CONFIRMATION.md): the pxfull book carries bars from 2008-01-02 for
28/30 names (V from 2008-03-19; META from its 2012-05-18 IPO — the
scorer excludes any name until it has 253 bars and PIT facts, so late
entry is exclusion, never backfill), and the PIT EDGAR chains carry
facts genuinely filed from mid-2009. The scored pool is 3 names on
2010-01-04 (below the 5-name minimum — the pot sits in cash, the honest
consequence) and 25 names by 2010-04-01. Universe construction is
therefore point-in-time honest back to 2010 and LONG runs.

$100 start per run, program costs (0.10%/side + $0.01/sell order),
point-in-time facts, adopted v9 protections (plain -15% floor checked
on every close; 90-calendar-day cash sit-out after a first halt;
restart at the next regular cadence decision point under an episode-2
floor of -15% from the restart balance; second halt ends the run) —
all inherited unchanged from the sweep's run_one.
"""
import json
import os
import random
import sys
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(HERE)
sys.path.insert(0, PARENT)
import sweep as S  # noqa: E402  (the sweep engine, read-only import)

START_CASH = 100.0
PLACEBO_SEEDS = list(range(1, 21))
ROADS = {
    "CONT": ("2019-01-02", "2026-11-20", 313.62),
    "VAL": ("2023-01-03", "2026-11-20", 187.77),
    "LONG": ("2010-01-04", "2026-11-20", 822.94),
}


def run_v9w(pb, scorer, cadence, start, end, placebo_seed=None):
    """The sweep's run_v9 wrapper with the window parameterized (the
    sweep hardcodes its DECADE globals; semantics copied exactly):
    episode 1 plain -15% floor; on first halt, cash 90 calendar days,
    restart at the next regular cadence decision point on/after
    eligibility under an episode-2 floor of -15% from the restart
    balance; second halt ends the run."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    episodes = []
    ep1 = S.run_one(pb, scorer, start, end, START_CASH, 0.85 * START_CASH,
                    cadence, placebo_rng=rng)
    episodes.append(ep1)
    restart = None
    if ep1 is not None and ep1["halted"]:
        halt_d = date.fromisoformat(ep1["halted"])
        elig = (halt_d + timedelta(days=90)).isoformat()
        if elig <= end:
            ep2 = S.run_one(pb, scorer, elig, end, ep1["final"],
                            0.85 * ep1["final"], cadence, placebo_rng=rng)
            if ep2 is not None:
                episodes.append(ep2)
                first_sel = ep2["pools"][0][0] if ep2["pools"] else None
                restart = {"halt_date": ep1["halted"],
                           "eligibility": elig,
                           "restart_balance": round(ep1["final"], 2),
                           "episode2_floor": round(0.85 * ep1["final"], 2),
                           "episode2_first_selection": first_sel}
    last = episodes[-1]
    curve = list(episodes[0]["curve"])
    if len(episodes) > 1:
        trading_days = [d for d in pb.dates if start <= d <= end]
        gap = [d for d in trading_days
               if episodes[0]["end"] < d < episodes[1]["curve"][0][0]]
        curve += [(d, episodes[0]["final"]) for d in gap]
        curve += list(episodes[1]["curve"])
    halts = []
    for i, ep in enumerate(episodes):
        if ep["halted"]:
            halts.append({"episode": i + 1,
                          "signal_date": ep["halted"],
                          "signal_close": ep["halt_info"]["signal_close"]
                          if ep.get("halt_info") else None,
                          "floor_in_effect":
                              ep["halt_info"]["floor_in_effect"]
                              if ep.get("halt_info") else None,
                          "liquidation_date": ep["end"],
                          "proceeds": round(ep["final"], 2)})
    return {"final": last["final"],
            "costs": sum(ep["costs"] for ep in episodes),
            "orders": sum(len(ep["trades"]) for ep in episodes),
            "trades": [tr for ep in episodes for tr in ep["trades"]],
            "halts": halts, "restart": restart,
            "second_halt": bool(len(episodes) > 1 and
                                episodes[1]["halted"]),
            "curve": curve}


def cagr_pct(final, start, end):
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    return round(((final / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2)


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 == 1 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def run_cell(pb, scorer, road, cadence, start, end, with_placebos=True):
    ranked = run_v9w(pb, scorer, cadence, start, end)
    placebo_finals = []
    if with_placebos:
        for seed in PLACEBO_SEEDS:
            twin = run_v9w(pb, scorer, cadence, start, end,
                           placebo_seed=seed)
            placebo_finals.append(round(twin["final"], 2))
    n_beat = sum(1 for v in placebo_finals if ranked["final"] > v) \
        if placebo_finals else None
    spy_final, spy_costs = S.spy_net(pb, start, end, START_CASH)
    cell = {
        "slug": "value-momentum-ey",
        "run_kind": "confirmation",
        "road": road,
        "cadence": cadence,
        "window": {"start": start, "end": end},
        "final": round(ranked["final"], 2),
        "cagr_pct": cagr_pct(ranked["final"], start, end),
        "max_dd_pct": S.curve_stats(ranked["curve"]),
        "halts": ranked["halts"],
        "restart": ranked["restart"],
        "second_halt": ranked["second_halt"],
        "costs": round(ranked["costs"], 2),
        "orders": ranked["orders"],
        "spy_final": round(spy_final, 2),
        "spy_costs": round(spy_costs, 2),
        "beats_spy": ranked["final"] > spy_final,
        "placebo_beaten": n_beat,
        "placebo_median": round(median(placebo_finals), 2)
        if placebo_finals else None,
        "placebo_finals": placebo_finals,
        "trades": [[d, t, side, round(sh, 6), round(px, 4),
                    round(val, 2), round(c, 4)]
                   for (d, t, side, sh, px, val, c) in ranked["trades"]],
        "equity_curve": [[d, round(v, 4)] for d, v in ranked["curve"]],
    }
    path = os.path.join(HERE, f"{road.lower()}-{cadence}.json")
    with open(path, "w") as f:
        json.dump(cell, f, indent=1)
    print(f"== {road} {cadence}: final=${cell['final']:,.2f} "
          f"spy=${cell['spy_final']:,.2f} cagr={cell['cagr_pct']}% "
          f"maxdd={cell['max_dd_pct']}% costs=${cell['costs']:,.2f} "
          f"orders={cell['orders']} halts={len(ranked['halts'])} "
          f"placebo beaten {n_beat}/20 "
          f"(median ${cell['placebo_median']})", flush=True)
    return cell


def main():
    t0 = time.time()
    ciks = S.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    income_chains, shares_chains = {}, {}
    raw_income, raw_shares = {}, {}
    for t in S.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t])
        facts = S.load_facts(cik)
        inc = S.pit_series_income(facts)
        so = (S.pit_series(facts, "dei",
                         "EntityCommonStockSharesOutstanding", prio=3) +
              S.pit_series(facts, "us-gaap",
                         "CommonStockSharesOutstanding", prio=2) +
              S.pit_series(facts, "us-gaap",
                         "WeightedAverageNumberOfSharesOutstandingBasic",
                         prio=1))
        raw_income[t], raw_shares[t] = inc, so
        income_chains[t] = S.PitChain(inc)
        shares_chains[t] = S.PitChain(so)
    bars = {}
    for t in S.UNIVERSE + ["SPY"]:
        bars[t] = S.bars_adj(S.yahoo_payload(t))
    pb = S.PriceBook(bars)
    print(f"price book: {len(pb.dates)} union dates "
          f"{pb.dates[0]}..{pb.dates[-1]}", flush=True)

    # fast-path equivalence check vs the original pit_value, sampled
    # across the FULL range incl. the 2010s (the sweep sampled the
    # decade only; the confirmation extends the sample to LONG).
    sample_days = [d for d in pb.dates if "2010-01-04" <= d <= "2026-11-20"][::37]
    for t in S.UNIVERSE:
        for d in sample_days:
            assert income_chains[t].value(d) == \
                S.pit_value_slow(raw_income[t], d), (t, d, "income")
            assert shares_chains[t].value(d) == \
                S.pit_value_slow(raw_shares[t], d), (t, d, "shares")
    print(f"pit fast path == original pit_value on {len(sample_days)} "
          f"sampled dates x {len(S.UNIVERSE)} names x 2 chains",
          flush=True)

    # SPY reference verification in this plumbing
    for road, (s, e, ref) in ROADS.items():
        got, _ = S.spy_net(pb, s, e, START_CASH)
        print(f"SPY {road}: computed ${got:,.2f} vs SPEC reference "
              f"${ref:,.2f} -> {'MATCH' if round(got, 2) == ref else 'DIFF'}",
              flush=True)

    scorer = S.Scorer(pb, income_chains, shares_chains)
    summary = {"roads": {}, "folds": []}

    # (proof) quarterly plumbing check on CONT/VAL vs the originals
    for road in ("CONT", "VAL"):
        s, e, _ = ROADS[road]
        proof = run_cell(pb, scorer, f"{road}-proof", "quarterly", s, e,
                         with_placebos=False)
        summary["roads"][f"{road}-quarterly-proof"] = {
            "final": proof["final"], "spy_final": proof["spy_final"]}
        os.replace(os.path.join(HERE, f"{road.lower()}-proof-quarterly.json"),
                   os.path.join(HERE, f"{road.lower()}-quarterly-proof.json"))

    # (1) CONT + VAL at weekly and monthly, with placebos
    for road in ("CONT", "VAL"):
        s, e, _ = ROADS[road]
        for cadence in ("weekly", "monthly"):
            cell = run_cell(pb, scorer, road, cadence, s, e)
            summary["roads"][f"{road}-{cadence}"] = {
                "final": cell["final"], "spy_final": cell["spy_final"],
                "cagr_pct": cell["cagr_pct"],
                "max_dd_pct": cell["max_dd_pct"], "costs": cell["costs"],
                "orders": cell["orders"], "halts": len(cell["halts"]),
                "placebo_beaten": cell["placebo_beaten"],
                "placebo_median": cell["placebo_median"]}

    # (2) LONG at weekly only (constructibility judged honest — see
    # CONFIRMATION.md), with placebos
    s, e, _ = ROADS["LONG"]
    cell = run_cell(pb, scorer, "LONG", "weekly", s, e)
    summary["roads"]["LONG-weekly"] = {
        "final": cell["final"], "spy_final": cell["spy_final"],
        "cagr_pct": cell["cagr_pct"], "max_dd_pct": cell["max_dd_pct"],
        "costs": cell["costs"], "orders": cell["orders"],
        "halts": len(cell["halts"]),
        "placebo_beaten": cell["placebo_beaten"],
        "placebo_median": cell["placebo_median"]}

    # (3) fresh yearly folds at weekly, 2017-2026, fresh $100 each
    folds = []
    for yr in range(2017, 2027):
        days = [d for d in pb.dates if d[:4] == str(yr) and d <= "2026-11-20"]
        fs, fe = days[0], days[-1]
        r = run_v9w(pb, scorer, "weekly", fs, fe)
        spy_final, spy_costs = S.spy_net(pb, fs, fe, START_CASH)
        fold = {
            "year": yr, "window": {"start": fs, "end": fe},
            "final": round(r["final"], 2),
            "cagr_pct": cagr_pct(r["final"], fs, fe),
            "max_dd_pct": S.curve_stats(r["curve"]),
            "costs": round(r["costs"], 2), "orders": r["orders"],
            "halts": r["halts"], "restart": r["restart"],
            "second_halt": r["second_halt"],
            "spy_final": round(spy_final, 2),
            "spy_costs": round(spy_costs, 2),
            "beats_spy": r["final"] > spy_final,
            "beats_100": r["final"] > START_CASH,
            "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
            "trades": [[d, t, side, round(sh, 6), round(px, 4),
                        round(val, 2), round(c, 4)]
                       for (d, t, side, sh, px, val, c) in r["trades"]],
        }
        folds.append(fold)
        print(f"== fold {yr} ({fs}..{fe}): final=${fold['final']:,.2f} "
              f"spy=${fold['spy_final']:,.2f} "
              f"beat_spy={fold['beats_spy']} beat_100={fold['beats_100']} "
              f"halts={len(r['halts'])}", flush=True)
    with open(os.path.join(HERE, "folds.json"), "w") as f:
        json.dump({"slug": "value-momentum-ey", "cadence": "weekly",
                   "start_cash": START_CASH, "folds": folds}, f, indent=1)
    summary["folds"] = [{"year": fo["year"], "final": fo["final"],
                         "spy_final": fo["spy_final"],
                         "beats_spy": fo["beats_spy"],
                         "beats_100": fo["beats_100"],
                         "halts": len(fo["halts"])} for fo in folds]
    with open(os.path.join(HERE, "confirmation_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print(f"DONE in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
