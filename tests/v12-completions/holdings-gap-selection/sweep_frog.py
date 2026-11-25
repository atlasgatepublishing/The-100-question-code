#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — gap-a9-frog-pan (STOCK count sweep).
Frozen mapping (written before runs):
- POND forms (the program's only pre-v12 frog form): v10 engine mechanics
  verbatim (monthly, positive 12-1 momentum eligible, rank by ID asc then
  momentum desc, equal weight, program costs 0.10%/side + $0.01 sell fee),
  with the ONLY change: picks = top-N and target weight = equity/N.
  Forms: house = v9 protections (plain -15% floor, liquidate next open,
  90-day sit-out, one restart, ep2 floor -15% from restart balance, 2nd
  halt ends); original = plain -15% floor, no restart (the v10 integrity
  form). Native published form (broad long-short) is UNBUILDABLE (v11) —
  the pond adaptation's published count is 5. ALL-ELIGIBLE = all
  positive-momentum names that month.
- CONSTRUCTED form (v12 gap-a9 folder, CONSTRUCTION-SPEC): PIT S&P 500
  universe, monthly, lowest-ID names, plain -15% floor no restart,
  vanished->zero conventions — engine semantics copied from that folder's
  run.py run_window with NHOLD replaced by the sweep count (validated:
  this sim at count 30 must reproduce run_window's own output on DECADE).
  Its published constructed count is 30. ALL-ELIGIBLE = all eligible.
Grid: 1,2,3,5,8,10,15,20,30,ALL. Placebos: 20 seeds, random same-count
picks from the same eligible set, primary road only (DECADE pond /
DECADE constructed). Confirmation windows for non-native winners:
CONF_A 2020-2023, CONF_B 2024-2026.
"""
import importlib.util, json, os, random, statistics, sys, time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, None]
ROADS = {"DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}
CONF = {"CONF_A": ("2020-01-01", "2023-12-31"), "CONF_B": ("2024-01-01", "2026-11-20")}

def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

F = load_mod("frog_v10", os.path.join(BT, "v10-retest/gap-a9-frog-pan/run_v10.py"))

# ---------------- pond sim (v10 simulate, count-parameterized) --------------
def simulate_n(mkt, start_d, end_d, n_count, mode="frog", seed=42, v9=True):
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    dec = F.cadence_dates(mkt, "monthly", i0, i1)
    cash = 100.0; pos = {}; res = F.Res()
    episode = 1; floor = 85.0; ep_start_balance = 100.0
    pending_liq = False; ended = False; restart_after = None
    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None: px = mkt.close_px(t, i)
            if px is not None: tot += sh * px
        return tot
    def liquidate(i, use_open):
        nonlocal cash
        for t in list(pos):
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None: px = mkt.close_px(t, i)
            val = pos[t] * px; fee = val * F.COST_RATE + F.SELL_FEE
            cash += val - fee; res.costs += fee; res.orders += 1
            del pos[t]
    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        if ended:
            res.curve.append((d, cash)); continue
        if pending_liq:
            liquidate(i, use_open=True)
            res.halts[-1]["liquidation_date"] = d
            res.halts[-1]["balance_after"] = round(cash, 2)
            pending_liq = False
            if episode == 1 and v9:
                episode = 2
                restart_after = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
            else:
                ended = True; res.second_halt = (len(res.halts) >= 2)
                res.curve.append((d, cash)); continue
        can_trade = (restart_after is None or d >= restart_after)
        if i in dec and can_trade and i > 0:
            if restart_after is not None and not res.restart:
                res.restart = True; ep_start_balance = cash
                floor = 0.85 * cash; restart_after = None
                res.halts[-1]["restart_date"] = d
                res.halts[-1]["restart_balance"] = round(cash, 2)
            j = i - 1
            elig = []
            for t in F.UNIVERSE:
                m = mkt.mom[t][j]
                if m is None or m <= 0: continue
                v = mkt.idv[t][j]
                if v is None: continue
                elig.append((t, m, v))
            if mode == "frog":
                elig.sort(key=lambda x: (x[2], -x[1], x[0]))
                picks = [t for t, _, _ in elig] if n_count is None else [t for t, _, _ in elig[:n_count]]
            else:
                names = sorted(t for t, _, _ in elig)
                k = len(names) if n_count is None else min(n_count, len(names))
                picks = rng.sample(names, k) if names else []
            if picks:
                eq_open = equity_at(i, use_open=True)
                target = {t: eq_open / len(picks) for t in picks}
                for t in list(pos):
                    px = mkt.open_px(t, i)
                    if px is None: continue
                    cur = pos[t] * px; want = target.get(t, 0.0)
                    if cur > want + 0.01:
                        sv = cur - want; sh = sv / px; fee = sv * F.COST_RATE + F.SELL_FEE
                        cash += sv - fee; res.costs += fee; res.orders += 1
                        pos[t] -= sh
                        if want <= 0.0 or pos[t] * px < 0.01: del pos[t]
                for t in picks:
                    px = mkt.open_px(t, i)
                    if px is None: continue
                    cur = pos.get(t, 0.0) * px; deficit = target[t] - cur
                    if deficit <= 0.01: continue
                    bv = min(deficit, cash / (1.0 + F.COST_RATE))
                    if bv <= 0.01: continue
                    fee = bv * F.COST_RATE; cash -= bv + fee; res.costs += fee; res.orders += 1
                    pos[t] = pos.get(t, 0.0) + bv / px
        eq_close = equity_at(i, use_open=False)
        res.curve.append((d, round(eq_close, 4)))
        if pos and eq_close <= floor:
            res.halts.append({"episode": episode, "trigger_date": d,
                              "floor": round(floor, 2),
                              "episode_start_balance": round(ep_start_balance, 2)})
            if i == i1:
                liquidate(i, use_open=False)
                res.halts[-1]["liquidation_date"] = d
                res.halts[-1]["balance_after"] = round(cash, 2)
                if episode == 2 or not v9: res.second_halt = (episode == 2)
                ended = True
            else:
                pending_liq = True
    res.final = cash if ended else (res.curve[-1][1] if res.curve else 100.0)
    if ended: res.final = cash
    peak = -1.0
    for d, eq in res.curve:
        peak = max(peak, eq)
        if peak > 0: res.max_dd = min(res.max_dd, eq / peak - 1.0)
    return res

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

def cell_stats(res):
    return {"final": round(res.final, 2), "max_dd_pct": round(res.max_dd * 100, 2),
            "costs": round(res.costs, 2), "orders": res.orders, "halts": len(res.halts)}

def main():
    t0 = time.time()
    out = {"family": "gap-a9-frog-pan", "native_count_published": None,
           "pond_native_count": 5, "constructed_count": 30,
           "counts_grid": ["ALL" if c is None else c for c in COUNTS], "forms": {}}
    mkt = F.Market(F.UNIVERSE)
    print("pond market loaded", round(time.time() - t0), "s", flush=True)
    # integrity: count 5 original form must reproduce v10 CONT $199.91 / VAL $118.59
    chk = {}
    for nm, (a, b), pub in (("CONT", ROADS["CONT"], 199.91), ("VAL", ROADS["VAL"], 118.59)):
        r = simulate_n(mkt, a, b, 5, v9=False)
        chk[nm] = {"final": round(r.final, 2), "published": pub, "match": round(r.final, 2) == pub}
    out["integrity_pond_count5_original"] = chk
    print("integrity pond:", chk, flush=True)
    for form, v9 in (("house_v9", True), ("original_plain_floor", False)):
        cells = {}
        for n in COUNTS:
            key = "ALL" if n is None else str(n)
            cell = {}
            for w, (a, b) in {**ROADS, **CONF}.items():
                r = simulate_n(mkt, a, b, n, v9=v9)
                cell[w] = cell_stats(r)
                if w == "DECADE":
                    cell[w]["curve"] = [[d, round(v, 2)] for d, v in r.curve]
            a, b = ROADS["DECADE"]
            pls = []
            for s in range(1, 21):
                rp = simulate_n(mkt, a, b, n, mode="placebo", seed=s, v9=v9)
                pls.append(round(rp.final, 2))
            cell["placebos_DECADE"] = {"finals": pls,
                "beaten": sum(1 for x in pls if cell["DECADE"]["final"] > x),
                "median": round(statistics.median(pls), 2)}
            cells[key] = cell
            print(f"pond {form} n={key}: DECADE {cell['DECADE']['final']} CONT {cell['CONT']['final']} VAL {cell['VAL']['final']} placebo {cell['placebos_DECADE']['beaten']}/20 ({round(time.time()-t0)}s)", flush=True)
        out["forms"][form] = cells
    # period stats: native 5 + best-on-DECADE per pond form
    for form, cells in list(out["forms"].items()):
        finals = {k: c["DECADE"]["final"] for k, c in cells.items()}
        best = max(finals, key=finals.get)
        for k in {best, "5"}:
            cells[k]["DECADE"]["period_stats_monthly"] = period_stats(cells[k]["DECADE"]["curve"])
        for c in cells.values():
            c["DECADE"].pop("curve", None)
        out["forms"][form + "_best_DECADE"] = best
    out["spy"] = {w: F.spy_net_canon(a, b) for w, (a, b) in ROADS.items()}
    json.dump(out, open(os.path.join(HERE, "results_frog_pond.json"), "w"), indent=1)
    print("pond done", round(time.time() - t0), "s", flush=True)

if __name__ == "__main__":
    main()
