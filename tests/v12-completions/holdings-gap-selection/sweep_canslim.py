#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — gap-a8-canslim, two run forms.
(1) AAII SCREEN form (the program's house form, v10 engine imported
    read-only): monthly screen on the 30-name pond, qualifiers ranked by
    12-1 momentum, M gate = SPY > 200-day. ONLY change: picks = top-N
    qualifiers, target = portfolio value / number of picks; placebo =
    random N from the same month's screenable pool (original design).
    Forms: house = v9 wrapper (floor/90-day sit-out/one restart/ep2
    floor); no_floor = single episode, floor disabled. Native count 5.
    Roads: DECADE/CONT/VAL (extended prices start 2015-06; no honest
    LONG). VALIDATION: house n=5 DECADE must reproduce v10 monthly cell
    $76.41.
(2) CONSTRUCTED form (v12 gap-a8 folder): breakout entries ranked by
    RS, taken first-come by day until slots fill — a ranked queue
    competing for slots, so per the PEAD precedent count = MAX SLOTS,
    slice = equity/N (module globals MAX_POS / POS_FRAC set per run;
    every other rule — 7.5% stop, +22.5% profit, 8-week rule, program
    $85 floor, entry-matched placebos — exactly as frozen). Constructed
    count = 5. Roads: LONG/DECADE/CONT/VAL. Placebos: 20 seeds per cell
    on every road (entries are rare; the original design is entry-matched
    per road).
True O'Neil native form: UNBUILDABLE (v11) — not faked here.
"""
import importlib.util, json, os, random, statistics, time
from datetime import date as _date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, None]

def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

C = load_mod("canslim_v10", os.path.join(BT, "v10-retest/gap-a8-canslim/scripts/canslim_v10.py"))
E = C.E

def period_stats(curve):
    bym = {}
    for d, v in curve: bym[d[:7]] = v
    keys = sorted(bym); rets = []; prev = 100.0
    for k in keys:
        rets.append(bym[k] / prev - 1); prev = bym[k]
    if not rets: return None
    prof = sum(1 for r in rets if r > 0)
    worst_run = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; worst_run = max(worst_run, cur)
    peak, since, longest = 100.0, 0, 0
    for k in keys:
        if bym[k] >= peak: peak = bym[k]; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {"period": "calendar month", "n_periods": len(rets),
            "pct_profitable": round(100 * prof / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "mean_pct_secondary_average": round(statistics.mean(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run_periods": worst_run,
            "longest_stretch_between_new_highs_periods": longest}

# ---------------- AAII form (run_pot_cad copied, count-parameterized) ------
def run_pot_n(pb, table, eval_dates, start, end, n_count, start_cash=100.0,
              floor0=85.0, placebo_rng=None):
    cash = start_cash; positions = {}; trades = []; total_costs = 0.0
    halted = None; curve = []; sel_set = set(eval_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days: return None
    pending = None
    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c: v += sh * c
        return v
    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b: opens[t] = b["o"]
        for t in list(positions):
            if t not in opens: continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c; total_costs += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9: del positions[t]
        for t, tgt in targets.items():
            if t not in opens: continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005: continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c; total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending); pending = None
        if d in sel_set:
            scr = table.get(d)
            picks = []
            if scr is not None and scr["gate"]:
                quals = [t for t, _m in scr["qualifiers"]]
                if placebo_rng is not None:
                    k = len(quals) if n_count is None else min(len(quals), n_count)
                    if k > 0:
                        picks = placebo_rng.sample(sorted(scr["screenable"]), k)
                else:
                    picks = quals if n_count is None else quals[:n_count]
            pv = portfolio_close(d)
            if picks:
                each = pv / len(picks)
                pending = {t: each for t in picks}
            else:
                pending = {}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor0 and di < len(days) - 1:
            halted = d
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c; total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst; total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "curve": curve}

def run_house_n(pb, table, eval_dates, start, end, n_count, placebo_rng=None):
    ep1 = run_pot_n(pb, table, eval_dates, start, end, n_count, placebo_rng=placebo_rng)
    out = {"episodes": 1, "final": ep1["final"], "costs": ep1["costs"],
           "orders": len(ep1["trades"]), "halts": 0, "curve": list(ep1["curve"])}
    if not ep1["halted"]: return out
    out["halts"] = 1
    liq = ep1["end"]; cash1 = ep1["final"]
    eligible = (_date.fromisoformat(liq) + timedelta(days=90)).isoformat()
    restart = next((d for d in eval_dates if d >= eligible), None)
    if restart is None: return out
    ep2 = run_pot_n(pb, table, eval_dates, restart, end, n_count,
                    start_cash=cash1, floor0=0.85 * cash1, placebo_rng=placebo_rng)
    out.update({"episodes": 2, "final": ep2["final"],
                "costs": ep1["costs"] + ep2["costs"],
                "orders": len(ep1["trades"]) + len(ep2["trades"]),
                "curve": list(ep1["curve"]) + list(ep2["curve"])})
    if ep2["halted"]: out["halts"] = 2
    return out

def stats_of(r):
    peak, mdd = 100.0, 0.0
    for _, v in r["curve"]:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    return {"final": round(r["final"], 2), "max_dd_pct": round(mdd * 100, 2),
            "costs": round(r["costs"], 2), "orders": r["orders"], "halts": r["halts"]}

def merge_aaii():
    import glob as _glob
    out = {"family": "gap-a8-canslim", "form": "AAII_screen_pond", "native_count": 5,
           "counts_grid": ["ALL" if c is None else c for c in COUNTS], "forms": {}}
    qual = {}
    for p in sorted(_glob.glob(os.path.join(HERE, "partial_aaii_*.json"))):
        part = json.load(open(p))
        qual.update(part.get("qualifier_anatomy") or {})
        if part.get("validation_house_n5_DECADE"):
            out["validation_house_n5_DECADE"] = part["validation_house_n5_DECADE"]
        for form, cells in part["acc"].items():
            tgt = out["forms"].setdefault(form, {})
            for key, cell in cells.items():
                tgt.setdefault(key, {}).update(cell)
    out["qualifier_anatomy"] = qual
    barsX = C.fetch_extended_prices()
    pbX = E.PriceBook(barsX)
    spy = {}
    for w, (a, b) in {"DECADE": ("2016-11-21", "2026-11-20"), "CONT": ("2019-01-02", "2026-11-20"),
                      "VAL": ("2023-01-03", "2026-11-20")}.items():
        f, _ = E.spy_net(pbX, a, b, 100.0)
        spy[w] = round(f, 2)
    out["spy"] = spy
    for form in ("house_v9", "no_floor"):
        cells = out["forms"][form]
        finals = {k: c["DECADE"]["final"] for k, c in cells.items()}
        best = max(finals, key=finals.get)
        out["forms"][form + "_best_DECADE"] = best
        for k in {best, "5"}:
            cells[k]["DECADE"]["period_stats_monthly"] = period_stats(cells[k]["DECADE"]["curve"])
        for c in cells.values():
            c["DECADE"].pop("curve", None)
    json.dump(out, open(os.path.join(HERE, "results_canslim_aaii.json"), "w"), indent=1)
    print("MERGED", {f: {k: c["DECADE"]["final"] for k, c in out["forms"][f].items()}
                     for f in ("house_v9", "no_floor")}, "spy", spy)

def main_aaii():
    # CHUNK MODE (2026-11-22, environment note): background/detached
    # processes are reaped after ~40s in this environment, so the sweep
    # runs one (window, form) per foreground invocation:
    #   python3 sweep_canslim.py WINDOW FORM   -> partial_aaii_WINDOW_FORM.json
    #   python3 sweep_canslim.py merge         -> results_canslim_aaii.json
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "merge":
        return merge_aaii()
    want_w = sys.argv[1] if len(sys.argv) > 1 else None
    want_f = sys.argv[2] if len(sys.argv) > 2 else None
    want_counts = None
    if len(sys.argv) > 3:
        want_counts = set()
        for tok in sys.argv[3].split(","):
            want_counts.add(None if tok == "ALL" else int(tok))
    t0 = time.time()
    out = {"family": "gap-a8-canslim", "form": "AAII_screen_pond", "native_count": 5,
           "counts_grid": ["ALL" if c is None else c for c in COUNTS], "forms": {}}
    eps_rows = C.load_eps_rows()
    barsX = C.fetch_extended_prices()
    pbX = E.PriceBook(barsX)
    C.pb_pos = {t: {b["d"]: i for i, b in enumerate(bl)} for t, bl in barsX.items()}
    spy_bars = barsX["SPY"]
    spy_closes = [b["c"] for b in spy_bars]
    spy_pos = C.pb_pos["SPY"]
    spy_dates = [b["d"] for b in spy_bars]
    fast = C.FastScreen(eps_rows)
    ROADS = {"DECADE": ("2016-11-21", "2026-11-20"), "CONT": ("2019-01-02", "2026-11-20"),
             "VAL": ("2023-01-03", "2026-11-20")}
    CONF = {"CONF_A": ("2020-01-01", "2023-12-31"), "CONF_B": ("2024-01-01", "2026-11-20")}
    # WINDOW-MAJOR (memory-lean): one screen table alive at a time.
    import gc
    acc = {form: {("ALL" if n is None else str(n)): {} for n in COUNTS}
           for form in ("house_v9", "no_floor")}
    qual_counts = {}
    for w, (a, b) in {**ROADS, **CONF}.items():
        if want_w and w != want_w:
            continue
        ev = C.cadence_dates(spy_dates, "monthly", a, b)
        tb = C.build_table_fast(pbX, fast, ev, spy_closes, spy_pos)
        qual_counts[w] = {"months": len(ev),
                          "months_with_any_qualifier": sum(1 for d in ev if tb[d]["qualifiers"]),
                          "max_qualifiers_one_month": max((len(tb[d]["qualifiers"]) for d in ev), default=0),
                          "total_qualifiers": sum(len(tb[d]["qualifiers"]) for d in ev)}
        print(f"table {w} built", qual_counts[w], round(time.time() - t0), "s", flush=True)
        if w == "DECADE":
            r = run_house_n(pbX, tb, ev, a, b, 5)
            out["validation_house_n5_DECADE"] = {"final": round(r["final"], 2), "published_v10": 76.41,
                                                 "match": round(r["final"], 2) == 76.41}
            print("VALIDATION AAII house n5 DECADE:", out["validation_house_n5_DECADE"], flush=True)
        for form in ("house_v9", "no_floor"):
            if want_f and form != want_f:
                continue
            for n in COUNTS:
                if want_counts is not None and n not in want_counts:
                    continue
                key = "ALL" if n is None else str(n)
                if form == "house_v9":
                    rr = run_house_n(pbX, tb, ev, a, b, n)
                else:
                    r1 = run_pot_n(pbX, tb, ev, a, b, n, floor0=0.0)
                    rr = {"final": r1["final"], "costs": r1["costs"], "orders": len(r1["trades"]),
                          "halts": 0, "curve": r1["curve"]}
                cell = acc[form][key]
                cell[w] = stats_of(rr)
                if w == "DECADE":
                    cell[w]["curve"] = [[d, round(v, 2)] for d, v in rr["curve"]]
                    pls = []
                    for s in range(1, 21):
                        rng = random.Random(s)
                        if form == "house_v9":
                            rp = run_house_n(pbX, tb, ev, a, b, n, placebo_rng=rng)
                        else:
                            r1 = run_pot_n(pbX, tb, ev, a, b, n, floor0=0.0, placebo_rng=rng)
                            rp = {"final": r1["final"]}
                        pls.append(round(rp["final"], 2))
                    cell["placebos_DECADE"] = {"finals": pls,
                        "beaten": sum(1 for x in pls if cell[w]["final"] > x),
                        "median": round(statistics.median(pls), 2)}
            print(f"window {w} form {form} done ({round(time.time()-t0)}s)", flush=True)
        del tb
        gc.collect()
    out["qualifier_anatomy"] = qual_counts
    if want_w:
        part = {"window": want_w, "acc": acc,
                "validation_house_n5_DECADE": out.get("validation_house_n5_DECADE"),
                "qualifier_anatomy": qual_counts}
        tag = f"{want_w}_{want_f}" if want_f else want_w
        if len(sys.argv) > 3:
            tag += "_" + sys.argv[3].replace(",", "-")
        json.dump(part, open(os.path.join(HERE, f"partial_aaii_{tag}.json"), "w"), indent=1)
        print("PARTIAL SAVED", tag, flush=True)
        return
    for form in ("house_v9", "no_floor"):
        cells = acc[form]
        finals = {k: c["DECADE"]["final"] for k, c in cells.items()}
        best = max(finals, key=finals.get)
        out["forms"][form + "_best_DECADE"] = best
        for k in {best, "5"}:
            cells[k]["DECADE"]["period_stats_monthly"] = period_stats(cells[k]["DECADE"]["curve"])
        for c in cells.values(): c["DECADE"].pop("curve", None)
        out["forms"][form] = cells
        print(f"canslim AAII {form}: " + "; ".join(
            f"n={k} " + " ".join(f"{w} {c[w]['final']}" for w in ROADS) +
            f" pl{c['placebos_DECADE']['beaten']}" for k, c in cells.items()), flush=True)
    spy = {}
    for w, (a, b) in ROADS.items():
        f, _ = E.spy_net(pbX, a, b, 100.0)
        spy[w] = round(f, 2)
    out["spy"] = spy
    json.dump(out, open(os.path.join(HERE, "results_canslim_aaii.json"), "w"), indent=1)
    print("canslim AAII done", round(time.time() - t0), "s", flush=True)

if __name__ == "__main__":
    main_aaii()
