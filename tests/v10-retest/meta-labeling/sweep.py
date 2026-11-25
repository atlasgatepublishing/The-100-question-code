#!/usr/bin/env python3
"""
META-LABELING — THE GREAT RETEST (v10) CADENCE SWEEP. Simulation only.

WHAT THIS IS
López de Prado meta-labeling over the champion (value+momentum): a
secondary logistic model, trained ONCE per its frozen published spec,
vetoes champion picks it scores p(beat SPY) < 0.5; a vetoed pick's pot
share stays in cash. Original test: backtests/v6/meta-labeling/
(meta-labeling.py) — VAL 2023-01-03..2026-11-20 final $114.64 vs the
naked champion's $288.05; vetoed 53 of 80 picks; beat 1 of 20 random-
veto placebos. Verdict then: FAILED — the one idea that ever made the
champion worse on its own validation.

SWEEP TREATMENT (stated precisely, per the task — no redesign):
  * ROAD: DECADE 2016-11-21 -> 2026-11-20, $100, program costs
    (0.10%/side + $0.01/sell), adopted v9 protections via the long-run
    test's run_v9 wrapper (plain -15% floor; first halt -> liquidate,
    90 calendar days in cash, restart at the next cadence date under an
    episode-2 floor of -15% from the restart balance; second halt ends
    the run).
  * BOOK/POND: identical to the published champion decade run in
    backtests/lazy-quarterly/run_lq.py — the Nov-2016 pond
    (gap-a5 Lazy Prices UNIVERSE, 30 names), prices from the champion's
    shared cache via gap-a5's get_prices, EDGAR chains from the
    champion engine's caches. (Book bars begin 2017-06-01 — the same
    book the $65.89 champion decade reference was computed on.)
  * CADENCE governs the PRIMARY only: the champion-form re-rank /
    rebalance rhythm (top-5 by B/M + 12-1 momentum percentile-rank
    average, equal weight pv/5 targets, next-open execution — the
    champion engine's mechanics verbatim, selection dates replaced by
    the cadence calendar of the SPEC's uniform definition).
  * THE META-MODEL IS FROZEN AS PUBLISHED: LogisticRegression(C=1.0)
    on standardized [value_rank, mom_rank, combined_rank, pick_vol63,
    spy_vol63, spy_above_200dma], threshold 0.5, trained ONCE on the
    published training set (quarterly selections 2016Q1..2022Q3 whose
    label exit < 2023-01-03; label = pick's net return over the
    quarter-to-next-quarter span beats SPY's). No retraining, no
    walk-forward redesign, no feature or threshold change. At
    non-quarterly cadences the same frozen model scores each primary
    pick at each cadence date (its features/labels stay as published).
  * POINT-IN-TIME APPLICATION: the frozen model's training data is
    only fully knowable on 2023-01-03, so the veto is applied ONLY at
    selection dates >= 2023-01-03 — exactly its published application
    era. Before that date the primary runs naked at every cadence.
    (Applying it earlier would leak its own training outcomes into
    2017-2022 decisions — the original spec's strict leakage rule.)
  * PLACEBOS per cell: 20 seeds; each vetoes every application-era
    pick independently with probability = that cell's realized meta
    veto rate (the original's random-filter control), same v9 wrapper.
    Where the primary's run ends before 2023-01-03 (two halts), the
    veto never fires: vetoes = 0 and placebos are not applicable
    (nothing was ever vetoed to randomize) — recorded, not skipped.

INTEGRITY (run before the sweep, asserted in code):
  * The frozen training set reproduces: 135 events, base rate 0.4889,
    in-sample coefficients equal to the published values.
  * Quarterly cadence, veto OFF, decade, v9 wrapper == the published
    champion decade reference $65.89 (lazy-quarterly plumbing).
  * Quarterly cadence, veto ON, VAL window, v9 wrapper == $114.64
    (the original final under BOTH rule sets — the floor never fired
    on VAL, so his-rules and v9 agree).

ENGINE NOTE: run_episode below is the original run_pot_meta (itself a
verbatim copy of the champion's run_pot + the veto hook) with exactly
two mechanical substitutions, both result-preserving: (1) selection
dates are supplied by the cadence calendar instead of
quarter_selection_dates; (2) the per-ticker bar-index scan and
pit_value use precomputed index/bisect lookups (equality with
champ.pit_value is asserted on a cross-era sample before any run).
"""
import importlib.util
import json
import math
import os
import random
import sys
from bisect import bisect_left
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
sys.path.insert(0, os.path.join(BT, "long-run-2010"))
sys.path.insert(0, os.path.expanduser(
    "~/workspace/stock-app/backtests/v6/meta-labeling/venv/lib"))

import lr_common as C  # noqa: E402

champ = C.champ  # v4 value-momentum-plainfloor, imported by lr_common


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# the original meta-labeling module (integrity copy; identical logic)
META = load_mod("meta_orig", os.path.join(HERE, "integrity",
                                          "meta-labeling.py"))
E = META.E  # champion engine instance used by the original test
lazy = C.load_module("lazy_ml", os.path.join(C.V7, "gap-a5-lazy-prices",
                                             "lazy-prices.py"))

DS, DE = "2016-11-21", "2026-11-20"
VAL = ("2023-01-03", "2026-11-20")
APPLY_FROM = "2023-01-03"
START_CASH = 100.0
FEATURES = META.FEATURES
THRESHOLD = META.THRESHOLD
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------------------ book
POND = list(lazy.UNIVERSE)
BOOK = C.FastPriceBook({t: lazy.get_prices(t) for t in POND + ["SPY"]})


def build_chains(tickers):
    ciks = champ.get_ciks()
    eq, so = {}, {}
    for t in tickers:
        cik = 34088 if t == "XOM" else ciks[t][0]
        facts = champ.get_companyfacts(cik)
        eq[t] = C.equity_chain(facts)
        so[t] = C.shares_chain(facts)
    return eq, so


EQ16, SO16 = build_chains(POND)

# ------------------------------------------------- fast PIT (exact copy)
def prep_chain(rows):
    """Group rows by filed date; per filed date keep the row pit_value
    would pick among rows sharing that filed date: max (prio, end)."""
    by_filed = {}
    for filed, end, val, prio in rows:
        cur = by_filed.get(filed)
        if cur is None or (prio, end) > (cur[0], cur[1]):
            by_filed[filed] = (prio, end, val)
    filed_sorted = sorted(by_filed)
    return filed_sorted, by_filed


def fast_pit(prepped, asof, max_age_days=548):
    filed_sorted, by_filed = prepped
    i = bisect_left(filed_sorted, asof) - 1  # last filed strictly < asof
    if i < 0:
        return None
    filed = filed_sorted[i]
    ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
    fy, fm, fd = int(filed[:4]), int(filed[5:7]), int(filed[8:10])
    if (date(ay, am, ad).toordinal() - date(fy, fm, fd).toordinal()
            > max_age_days):
        return None
    prio, end, val = by_filed[filed]
    return (filed, end, val)


EQF = {t: prep_chain(EQ16[t]) for t in POND}
SOF = {t: prep_chain(SO16[t]) for t in POND}
DIDX = {t: {b["d"]: i for i, b in enumerate(BOOK.bars[t])} for t in POND}

# assert fast_pit == champ.pit_value on a cross-era sample
for t in POND:
    for asof in ("2017-01-03", "2018-07-02", "2019-04-01", "2020-03-02",
                 "2021-10-01", "2023-01-03", "2024-07-01", "2026-01-02"):
        assert fast_pit(EQF[t], asof) == champ.pit_value(EQ16[t], asof), (t, asof, "eq")
        assert fast_pit(SOF[t], asof) == champ.pit_value(SO16[t], asof), (t, asof, "so")
print("fast_pit == champ.pit_value on 480 sampled (ticker, date) pairs", flush=True)

# ------------------------------------------------------- cadence dates
def cadence_dates(name, start, end):
    days = [d for d in BOOK.dates if start <= d <= end]
    if name == "daily":
        return days
    if name == "quarterly":
        return champ.quarter_selection_dates(BOOK, start, end)
    out, seen = [], set()
    if name == "weekly":
        for d in days:
            k = date.fromisoformat(d).isocalendar()[:2]
            if k not in seen:
                seen.add(k)
                out.append(d)
        return out
    if name == "biweekly":
        weeks = []
        for d in days:
            k = date.fromisoformat(d).isocalendar()[:2]
            if k not in seen:
                seen.add(k)
                weeks.append(d)
        return weeks[::2]
    if name == "monthly":
        for d in days:
            k = d[:7]
            if k not in seen:
                seen.add(k)
                out.append(d)
        return out
    if name == "semiannual":
        for d in days:
            k = (d[:4], "H1" if d[5:7] <= "06" else "H2")
            if k not in seen:
                seen.add(k)
                out.append(d)
        return out
    if name == "annual":
        for d in days:
            k = d[:4]
            if k not in seen:
                seen.add(k)
                out.append(d)
        return out
    raise ValueError(name)

# ------------------------------------------- episode engine (see header)
def run_episode(sel_dates, start, end, start_cash, floor0,
                veto_fn=None, label="", sel_log=None):
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    sel_set = set(sel_dates)
    days = [d for d in BOOK.dates if start <= d <= end]
    if not days:
        return None
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = BOOK.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = BOOK.bar(t, d)
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
            for t in POND:
                be = fast_pit(EQF[t], d)
                so = fast_pit(SOF[t], d)
                px = BOOK.close_on_or_before(t, d)
                if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
                    continue
                mcap = so[2] * px
                if mcap <= 0:
                    continue
                bm = be[2] / mcap
                didx = DIDX[t].get(d)
                if didx is None or didx < 253:
                    continue
                bl = BOOK.bars[t]
                mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
                scores[t] = (bm, mom)
            if len(scores) >= 5:
                vr = champ.percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = champ.percentile_ranks({t: v[1] for t, v in scores.items()})
                combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
                picks = sorted(combined, key=lambda t: -combined[t])[:5]
                if veto_fn is not None:
                    kept = veto_fn(d, list(picks), scores, vr, mr)
                else:
                    kept = list(picks)
                if sel_log is not None:
                    sel_log.append({"date": d, "pool": len(scores),
                                    "picks": list(picks), "kept": list(kept),
                                    "vetoed": [t for t in picks if t not in kept]})
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in kept}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            for t in list(positions):
                b = BOOK.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": sel_log or [],
                    "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = BOOK.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "pools": sel_log or [], "curve": curve}


def run_cell(cadence, veto_fn, start=DS, end=DE, shared_log=None):
    """One v9-wrapped run at a cadence. shared_log (optional list)
    collects the selection log across both episodes."""
    def run_one(s, e, cash, floor):
        log = [] if shared_log is not None else None
        r = run_episode(cadence_dates(cadence, s, e), s, e, cash, floor,
                        veto_fn=veto_fn, label=cadence, sel_log=log)
        if shared_log is not None and log:
            shared_log.extend(log)
        return r
    return C.run_v9(run_one, BOOK.dates, start, end, START_CASH)

# ------------------------------------------------------- frozen model
def train_frozen_model():
    """The original training pipeline, verbatim (via the original
    module): champion inputs from the champion's caches, extended
    price book from the cached pxlong files, events 2016Q1..2022Q3."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    import numpy as np
    pb, eq_rows, so_rows = META.build_inputs()
    xbars = {}
    for t in E.UNIVERSE + ["SPY"]:
        xbars[t] = META.get_prices_long(t)
    xpb = E.PriceBook(xbars)
    events, dropped = META.extract_training_events(xpb, eq_rows, so_rows)
    X = np.array([[e["features"][k] for k in FEATURES] for e in events],
                 dtype=float)
    y = np.array([e["label"] for e in events], dtype=int)
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)
    clf = LogisticRegression(C=1.0, max_iter=1000)
    clf.fit(Xs, y)
    coefs = {k: round(float(c), 4) for k, c in zip(FEATURES, clf.coef_[0])}
    return scaler, clf, events, dropped, coefs


def main():
    out = {"slug": "meta-labeling"}
    scaler, clf, events, dropped, coefs = train_frozen_model()
    published_coefs = {"value_rank": -0.1799, "mom_rank": 0.117,
                       "combined_rank": -0.0562, "pick_vol63": -0.0965,
                       "spy_vol63": 0.0182, "spy_above_200dma": -0.0397}
    base_rate = round(sum(e["label"] for e in events) / len(events), 4)
    train_ok = (len(events) == 135 and dropped == 5
                and base_rate == 0.4889 and coefs == published_coefs)
    print(f"TRAINING events={len(events)} dropped={dropped} "
          f"base_rate={base_rate} coefs_match={coefs == published_coefs}",
          flush=True)
    assert train_ok, f"frozen-model training diverges: {coefs}"

    import numpy as np

    def model_veto(d, picks, scores, vr, mr):
        if d < APPLY_FROM:
            return list(picks)  # model does not exist yet (point-in-time)
        sstate = META.spy_state(BOOK, d)
        kept = []
        for t in picks:
            feats = META.pick_features(BOOK, t, d, vr[t], mr[t], sstate)
            if feats is None:
                kept.append(t)
                continue
            x = np.array([[feats[k] for k in FEATURES]], dtype=float)
            p = float(clf.predict_proba(scaler.transform(x))[0, 1])
            if p >= THRESHOLD:
                kept.append(t)
        return kept

    # ---- integrity A: naked champion, quarterly, decade == $65.89
    champ_dec = run_cell("quarterly", None)
    champ_ok = round(champ_dec["final"], 2) == 65.89
    print(f"INTEGRITY champion decade quarterly naked: "
          f"${champ_dec['final']:,.2f} (published $65.89) match={champ_ok}",
          flush=True)

    # ---- integrity B: meta, quarterly, VAL, v9 == $114.64
    val_log = []
    meta_val = run_cell("quarterly", model_veto, start=VAL[0], end=VAL[1],
                        shared_log=val_log)
    val_vetoes = sum(len(s["vetoed"]) for s in val_log)
    val_ok = round(meta_val["final"], 2) == 114.64 and val_vetoes == 53
    print(f"INTEGRITY meta VAL quarterly v9: ${meta_val['final']:,.2f} "
          f"(published $114.64) vetoes={val_vetoes} (published 53) "
          f"match={val_ok}", flush=True)

    spy_dec, _ = champ.spy_net(BOOK, DS, DE, START_CASH)
    print(f"SPY decade in-plumbing: ${spy_dec:,.2f} (SPEC reference "
          f"$367.80 on the verified W6 plumbing; this book's bars begin "
          f"{BOOK.dates[0]})", flush=True)

    out["integrity"] = {
        "status": "reproduced" if (train_ok and champ_ok and val_ok)
                  else "FAILED",
        "training_set": {"events": len(events), "dropped": dropped,
                         "base_rate_beat_spy": base_rate,
                         "coefficients": coefs,
                         "published_coefficients": published_coefs,
                         "matches_published": train_ok},
        "champion_decade_quarterly_naked": {
            "reproduced_final": round(champ_dec["final"], 2),
            "published_final": 65.89, "matches": champ_ok,
            "halts": champ_dec["halts"]},
        "meta_val_quarterly_v9": {
            "reproduced_final": round(meta_val["final"], 2),
            "published_final": 114.64, "vetoes": val_vetoes,
            "published_vetoes": 53, "matches": val_ok,
            "note": "Original $114.64 was published under his rules "
                    "(plain floor, no restart); the floor never fired "
                    "on VAL, so the v9-wrapped run is identical — "
                    "$114.64 under BOTH rule sets. The full original-"
                    "form reproduction (his rules, original script) is "
                    "in integrity/."},
        "original_form": "see integrity/meta-labeling-results.json "
                         "(verbatim copy of the v6 script, paths only)"}
    out["decade_spy_final"] = round(spy_dec, 2)
    out["decade_spy_note"] = ("SPEC reference $367.80 (W6 verified "
                              "plumbing, full 2016-11-21 start). This "
                              "sweep runs on the champion's own decade "
                              "book — the identical book behind the "
                              "$65.89 champion reference — whose bars "
                              "begin 2017-06-01; SPY on that book is "
                              "the in-plumbing figure above.")
    out["champion_reference_decade"] = {
        "quarterly_final": 65.89,
        "note": "plain champion, decade, v9, lazy-quarterly plumbing; "
                "reproduced in this run (see integrity). Per-cadence "
                "naked-champion finals are in each cell file."}
    out["treatment"] = (
        "Cadence governs the primary (champion-form) re-rank rhythm "
        "only. The meta-model is the frozen published model (trained "
        "once on 2016Q1-2022Q3 quarterly events, threshold 0.5, six "
        "published features); it is applied point-in-time, i.e. only "
        "at selection dates >= 2023-01-03, its published application "
        "era. Vetoed pick's share stays in cash. Placebos: random "
        "vetoes at the cell's realized application-era veto rate, "
        "20 seeds, v9-wrapped.")

    cells = {}
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    for cad in CADENCES:
        log = []
        res = run_cell(cad, model_veto, shared_log=log)
        app = [s for s in log if s["date"] >= APPLY_FROM]
        pick_events = sum(len(s["picks"]) for s in app)
        vetoes = sum(len(s["vetoed"]) for s in app)
        veto_rate = vetoes / pick_events if pick_events else 0.0
        diag = C.curve_diagnostics(res["curve"])
        cagr_pct, _yrs = C.cagr(res["final"], START_CASH, DS, DE)

        # naked champion at the same cadence (the same-road reference)
        cref = run_cell(cad, None)
        cref_diag = C.curve_diagnostics(cref["curve"])

        # placebos
        twin_finals, beaten, pnote = [], None, None
        if pick_events == 0:
            pnote = ("NOT RUN — the primary's run ended before "
                     "2023-01-03 (two halts), so the frozen meta-model "
                     "never scored a single pick; there is no veto "
                     "behavior to randomize. The cell IS the naked "
                     "champion at this cadence.")
        elif veto_rate == 0.0:
            pnote = ("NOT RUN — the meta-model vetoed 0 of "
                     f"{pick_events} application-era picks at this "
                     "cadence, so every random-veto twin at rate 0 is "
                     "identical to the meta run by construction.")
        else:
            for seed in range(1, 21):
                rng = random.Random(seed)

                def rand_veto(d, picks, scores, vr, mr, rng=rng):
                    if d < APPLY_FROM:
                        return list(picks)
                    return [t for t in picks if rng.random() >= veto_rate]
                twin = run_cell(cad, rand_veto)
                twin_finals.append(round(twin["final"], 2))
            beaten = sum(1 for f in twin_finals if f < res["final"])
            pnote = (f"random vetoes at the cell's realized veto rate "
                     f"{veto_rate:.4f}, seeds 1-20, v9-wrapped")

        cell = {"cadence": cad, "window": [DS, DE],
                "final": round(res["final"], 2),
                "cagr_pct": cagr_pct,
                "max_dd_pct": diag["max_drawdown_pct"],
                "costs": round(res["costs"], 2),
                "orders": res["orders"],
                "halts": res["halts"],
                "restart": res["restart"],
                "second_halt": bool(res["restart"]
                                    and res["restart"]["second_halt"]),
                "vetoes": vetoes, "pick_events_application_era": pick_events,
                "veto_rate": round(veto_rate, 4),
                "selections_total": len(log),
                "placebo_twin_finals": twin_finals,
                "placebo_beaten": beaten,
                "placebo_note": pnote,
                "champion_ref_final": round(cref["final"], 2),
                "champion_ref": {"final": round(cref["final"], 2),
                                 "max_dd_pct": cref_diag["max_drawdown_pct"],
                                 "costs": round(cref["costs"], 2),
                                 "orders": cref["orders"],
                                 "halts": cref["halts"]},
                "spy_final_in_plumbing": round(spy_dec, 2),
                "equity_curve": [[d, round(v, 2)] for d, v in res["curve"]]}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = {"final": cell["final"], "cagr_pct": cagr_pct,
                      "max_dd_pct": diag["max_drawdown_pct"],
                      "halts": len(res["halts"]),
                      "restart": bool(res["restart"]),
                      "second_halt": cell["second_halt"],
                      "costs": cell["costs"], "orders": cell["orders"],
                      "placebo_beaten": beaten,
                      "placebo_note": pnote,
                      "vetoes": vetoes,
                      "pick_events_application_era": pick_events,
                      "champion_ref_final": cell["champion_ref_final"]}
        print(f"{cad:11s} meta=${res['final']:10,.2f} champ="
              f"${cref['final']:10,.2f} vetoes={vetoes}/{pick_events} "
              f"halts={len(res['halts'])} placebo_beaten={beaten}",
              flush=True)

    out["cells"] = cells
    money = [c for c in CADENCES
             if cells[c]["final"] > spy_dec
             and cells[c]["placebo_beaten"] is not None
             and cells[c]["placebo_beaten"] >= 11]
    out["money_cadences"] = money
    out["native_cadence"] = "quarterly"
    out["area"] = ("veto overlay on the champion — judged on the "
                   "champion's road (decade sweep; original windows "
                   "CONT + VAL)")
    out["original_cadence_foreign"] = False
    out["verdict_area"] = "NO GROUND" if not money else "REAL BUT SMALL"
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved results.json", flush=True)
    print("DONE")


if __name__ == "__main__":
    main()
