#!/usr/bin/env python3
"""
ONE-VARIABLE ABLATION — MOMENTUM BASKET + QUALITY GATE.
Terry's AI stock app, simulation only. No broker orders.

Base strategy: the survivorship-honest MOMENTUM BASKET
(momentum-basket-honest.py — engine, universe, costs, floor and windows are
reused unchanged; the ungated runs below must reproduce its published
numbers exactly, and they do — see the verification lines in the output).

THE ONE CHANGE: a QUALITY GATE at each monthly selection.
  For each of the honest 30 names, gross profitability
      GP = (Revenue - COGS) / Total Assets
  is computed point-in-time from SEC EDGAR companyfacts, reusing the
  quality-momentum.py machinery verbatim (build_quality_observations /
  quality_at): GP from a single filing (same accession, same annual
  period); names that never report COGS fall back to
  Operating Income / Assets from the same filing structure (flagged
  "OPINC"); names with neither produce no observations.
  GATE RULE (frozen): at each monthly selection, a name is selectable
  only if its most recently FILED GP (filed strictly before the signal
  day — the quality-momentum convention) is POSITIVE. No observation at
  all also fails the gate (reason "no-data"). Momentum ranking then
  proceeds exactly as usual among the names that pass.
Everything else — 200-day eligibility, 12-1 ranking, top 5 at 20%,
0.10%/side + $0.01/sell costs, Terry's floor/ladder, $50 and $100 pots,
full + validation windows — is identical to the honest basket.

Diagnostics: every selection month logs the eligible set, the names the
gate excluded (with reason and the GP value that failed), the ungated
top-5 vs the gated top-5, and whether the picks changed.

Data: Yahoo prices from the honest basket's cache
(momentum-basket-honest-data/); EDGAR companyfacts via the shared
quality-momentum cache (data/), fetched for the names not already there.
"""

import importlib.util
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, fname))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mbh = _load("mbh", "momentum-basket-honest.py")   # engine / universe / floor
qm = _load("qm", "quality-momentum.py")           # EDGAR quality machinery

UNIVERSE = mbh.UNIVERSE
WINDOWS = {k: mbh.WINDOWS[k] for k in ("full", "validation")}


# --------------------------------------------------------------------------
# Simulation — a copy of mbh.simulate (ranked mode only) with the gate and
# diagnostics added. Everything else is line-for-line the honest engine.
# --------------------------------------------------------------------------
class Result(mbh.Result):
    def __init__(self):
        super().__init__()
        self.diag = []          # one entry per selection month


def simulate(mkt, start_d, end_d, pot0, gate_obs=None):
    """gate_obs: None (ungated base) or {ticker: quality observations}."""
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    floor0, ladder = mbh.FLOORS[pot0]
    floor = floor0
    cash = float(pot0)
    pos = {}
    res = Result()
    pending_liquidation = False
    mark_px = {}
    cur_month = None

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        month_key = d[:7]

        if pending_liquidation:
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    px = mkt.close_px(t, i)
                val = pos[t] * px
                fee = val * mbh.COST_RATE + mbh.SELL_FEE
                cash += val - fee
                res.costs += fee
                res.orders += 1
                if t in mark_px:
                    res.sel_total += 1
                    if px > mark_px[t]:
                        res.sel_wins += 1
                del pos[t]
            mark_px.clear()
            res.halt_date = d
            res.final = cash
            res.equity_curve.append((d, cash))
            break

        if month_key != cur_month and i > 0:
            cur_month = month_key
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is not None and t in mark_px:
                    res.sel_total += 1
                    if px > mark_px[t]:
                        res.sel_wins += 1
            j = i - 1                       # signal day = prior trading day
            elig = []
            for t in UNIVERSE:
                sma200 = mkt.sma(t, j, 200)
                c = mkt.close_px(t, j)
                if sma200 is None or c is None or c <= sma200:
                    continue
                mom = mkt.momentum_12_1(t, j)
                if mom is None:
                    continue
                elig.append((t, mom))
            elig.sort(key=lambda x: -x[1])
            ungated_picks = [t for t, _ in elig[:5]]

            picks = ungated_picks
            if gate_obs is not None:
                kept, excluded = [], []
                for t, mom in elig:
                    q = qm.quality_at(gate_obs.get(t, []), mkt.cal[j])
                    if q is None:
                        excluded.append({"t": t, "reason": "no-data",
                                         "gp": None, "method": None,
                                         "filed": None})
                    elif q[2] <= 0:
                        excluded.append({"t": t, "reason": "gp<=0",
                                         "gp": round(q[2], 4),
                                         "method": q[3], "filed": q[0]})
                    else:
                        kept.append((t, mom))
                picks = [t for t, _ in kept[:5]]
                res.diag.append({
                    "date": d,
                    "signal_date": mkt.cal[j],
                    "n_elig": len(elig),
                    "excluded": excluded,
                    "ungated_picks": ungated_picks,
                    "gated_picks": picks,
                    "changed": picks != ungated_picks,
                })

            eq_open = equity_at(i, use_open=True)
            target_val = {t: 0.20 * eq_open for t in picks}

            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos[t] * px
                want = target_val.get(t, 0.0)
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * mbh.COST_RATE + mbh.SELL_FEE
                    cash += sell_val - fee
                    res.costs += fee
                    res.orders += 1
                    pos[t] -= sh
                    if want <= 0.0 or pos[t] * px < 0.01:
                        del pos[t]
            for t in picks:
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos.get(t, 0.0) * px
                deficit = target_val[t] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + mbh.COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * mbh.COST_RATE
                cash -= buy_val + fee
                res.costs += fee
                res.orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px
            mark_px = {}
            for t in pos:
                px = mkt.open_px(t, i)
                if px is not None:
                    mark_px[t] = px

        eq_close = equity_at(i, use_open=False)
        res.equity_curve.append((d, eq_close))
        for thresh, new_floor in ladder:
            if eq_close >= thresh:
                floor = max(floor, new_floor)
        if eq_close <= floor:
            pending_liquidation = True
            if i == i1:
                tot = cash
                for t, sh in list(pos.items()):
                    val = sh * mkt.close_px(t, i)
                    fee = val * mbh.COST_RATE + mbh.SELL_FEE
                    tot += val - fee
                    res.costs += fee
                    res.orders += 1
                res.final = tot
                res.halt_date = d
                pos.clear()
                break

    if res.final is None:
        res.final = res.equity_curve[-1][1]
    peak = -1.0
    for d, eq in res.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
    month_end = {}
    for d, eq in res.equity_curve:
        month_end[d[:7]] = eq
    keys = sorted(month_end)
    for a, b in zip(keys, keys[1:]):
        r = month_end[b] / month_end[a] - 1.0
        res.months += 1
        res.month_rets.append(r)
        if r > 0:
            res.month_wins += 1
    return res


# --------------------------------------------------------------------------
def summ(r, pot, yrs, bench):
    return {
        "final": round(r.final, 2),
        "ret_pct": round((r.final / pot - 1) * 100, 2),
        "cagr_pct": round(mbh.cagr(r.final, pot, yrs) * 100, 2),
        "orders": r.orders,
        "costs": round(r.costs, 2),
        "max_dd_pct": round(r.max_dd * 100, 2),
        "halt": r.halt_date,
        "bench_final": round(bench, 2),
        "bench_ret_pct": round((bench / pot - 1) * 100, 2),
    }


def diag_summary(res):
    months = len(res.diag)
    changed = sum(1 for e in res.diag if e["changed"])
    excl = {}
    for e in res.diag:
        for x in e["excluded"]:
            slot = excl.setdefault(x["t"], {"months_excluded": 0,
                                            "reasons": {}, "gp_values": []})
            slot["months_excluded"] += 1
            slot["reasons"][x["reason"]] = slot["reasons"].get(x["reason"], 0) + 1
            if x["gp"] is not None:
                slot["gp_values"].append(x["gp"])
    months_picks_dropped = sum(
        1 for e in res.diag
        if any(t in e["ungated_picks"] for t in
               [x["t"] for x in e["excluded"]]))
    return {
        "selection_months": months,
        "months_picks_changed": changed,
        "months_an_ungated_pick_was_excluded": months_picks_dropped,
        "exclusions_by_name": excl,
    }


def main():
    # ---- quality observations for the honest 30 -------------------------
    ciks = qm.get_ciks()
    quality_obs = {}
    obs_info = {}
    for t in UNIVERSE:
        facts = qm.get_companyfacts(ciks[t])
        obs = qm.build_quality_observations(facts)
        quality_obs[t] = obs
        methods = {}
        for _, _, _, m in obs:
            methods[m] = methods.get(m, 0) + 1
        obs_info[t] = {"n_obs": len(obs), "methods": methods,
                       "first_filed": obs[0][0] if obs else None,
                       "last_filed": obs[-1][0] if obs else None}
        print(f"{t}: quality obs={len(obs)} methods={methods}", flush=True)
        time.sleep(0.15)

    mkt = mbh.Market(UNIVERSE)
    out = {"quality_obs_info": obs_info, "runs": {}}
    published = {("full", 100): 439.45, ("full", 50): 215.61,
                 ("validation", 100): 208.27, ("validation", 50): 103.18}

    for wname, (sd, ed) in WINDOWS.items():
        yrs = mbh.years_between(sd, ed)
        for pot in (100, 50):
            bench = mbh.spy_net(mkt, sd, ed, pot)
            base = simulate(mkt, sd, ed, pot, gate_obs=None)
            got = round(base.final, 2)
            want = published[(wname, pot)]
            status = "MATCH" if abs(got - want) < 0.02 else "MISMATCH!"
            print(f"VERIFY ungated {wname} ${pot}: got {got} published "
                  f"{want} -> {status}", flush=True)
            gated = simulate(mkt, sd, ed, pot, gate_obs=quality_obs)
            key = f"{wname}|{pot}"
            out["runs"][key] = {
                "ungated": summ(base, pot, yrs, bench),
                "gated": summ(gated, pot, yrs, bench),
                "delta_final": round(gated.final - base.final, 2),
                "diag": diag_summary(gated),
                "diag_full": gated.diag,
            }
            g = out["runs"][key]["gated"]
            print(f"{key} GATED: final={g['final']} ret={g['ret_pct']:+.2f}% "
                  f"maxDD={g['max_dd_pct']:.2f}% orders={g['orders']} "
                  f"costs=${g['costs']} halt={g['halt']} | ungated "
                  f"{out['runs'][key]['ungated']['final']} | SPY {g['bench_final']}",
                  flush=True)
            ds = out["runs"][key]["diag"]
            print(f"   gate: {ds['selection_months']} selection months, picks "
                  f"changed in {ds['months_picks_changed']}, an ungated pick "
                  f"was excluded in {ds['months_an_ungated_pick_was_excluded']}",
                  flush=True)

    with open(os.path.join(HERE, "basket-quality-gate-results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved basket-quality-gate-results.json")


if __name__ == "__main__":
    main()
