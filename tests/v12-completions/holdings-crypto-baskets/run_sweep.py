#!/usr/bin/env python3
"""
HOLDINGS-COUNT SWEEP — crypto selection baskets (v12 wing, Terry 2026-11-22).

Families:
  A) crypto-basket      (LTW CONSTRUCTED long leg; native = top QUINTILE,
                         weekly, sorts mom 7/14/21/28d + truncated size,
                         cost 0.60%/side, death-to-zero @7d)
  B) crypto-basket-pit  (program CONSTRUCTED form; native = top-5, monthly,
                         12-1 momentum + 200d filter, cost 0.60%/side,
                         death-to-zero after 30d grace)
  C) crypto-dominance-rotation (CONSTRUCTED; the swept leg is the ALT
                         BASKET breadth inside LARGE/ALT states: native =
                         ALL eligible alts, monthly, cost 0.60%/side)

GRID (fixed, program-wide): counts 1,2,3,5,8,10,15,20,30,ALL-ELIGIBLE,
capped by the PIT universe at each date. Both rule sets each family runs
(native no-floor + v9 house protections as frozen in its own v12 spec).
Windows (each family's own roads): FULL 2017-01-01->2026-11-20,
DESIGN 2017-01-01->2022-12-31, VALIDATION 2023-01-01->2026-11-20.
Fresh $100 pots. BTC buy-and-hold (net of the same 0.60%/side) beside
every number. Dead coins to ZERO per each family's own death rule.
20-seed placebos per cell where the family's chassis supports them.

Engines are faithful copies of the families' own v12 run scripts with
ONE change: the holdings count is a parameter. Integrity cells reproduce
each family's published v12 headline numbers before any sweep cell is
trusted (asserted in main()).
"""
import bisect, json, math, os, random, sys, time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from sweep_common import period_stats, pct

COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
WINDOWS = {"full": ("2017-01-01", "2026-11-20"),
           "design": ("2017-01-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}
POT = 100.0
SEEDS = list(range(1, 21))

def nkey(n):
    return "ALL" if n == "ALL" else str(n)

# =====================================================================
# A) crypto-basket (LTW constructed) — engine copied from its v12 folder
# =====================================================================
import importlib.util
def _load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

CB = _load_mod("cb_engine", os.path.join(HERE, "..", "crypto-basket", "run_crypto_basket.py"))
CB_COST = CB.COST  # 0.006

def cb_simulate(mkt, snaps_by_date, start_d, end_d, sort_key, horizon=None,
                cadence="weekly", ruleset="native", mode="ranked", seed=42,
                n_hold="QUINTILE"):
    """n_hold: 'QUINTILE' = native ceil(N/5); int = fixed top-N; 'ALL' = all rankable."""
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    floor = 85.0 if ruleset == "v9" else None
    cash = float(POT)
    pos, entry_avg, dead_flag = {}, {}, {}
    res = CB.Result()
    pending_liq = False

    def equity_at(i, price_fn):
        return cash + sum(sh * price_fn(cid, i) for cid, sh in pos.items())

    def note_collapse(cid, exit_px, when):
        if cid in entry_avg and entry_avg[cid] > 0 and exit_px <= 0.10 * entry_avg[cid]:
            res.events.append({"type": "collapse_exit", "coin": mkt.reg[cid]["symbol"],
                               "cmc_id": cid, "date": when, "entry_px": entry_avg[cid],
                               "exit_px": exit_px,
                               "loss_pct": round((exit_px / entry_avg[cid] - 1) * 100, 2)})

    for i in range(i0, i1 + 1):
        d = cal[i]
        dt = datetime.strptime(d, "%Y-%m-%d")
        for cid in list(pos):
            dead = mkt.is_dead(cid, i)
            if dead and not dead_flag.get(cid):
                lb = mkt.last_bar[cid][i]
                res.events.append({"type": "write_off_zero", "coin": mkt.reg[cid]["symbol"],
                                   "cmc_id": cid, "date": d,
                                   "last_bar_date": cal[lb] if lb >= 0 else None,
                                   "last_px": mkt.closes_ff[cid][lb] if lb >= 0 else None,
                                   "shares": pos[cid],
                                   "written_off_value": round(pos[cid] * (mkt.closes_ff[cid][lb] or 0.0), 2) if lb >= 0 else 0.0})
                dead_flag[cid] = True
            elif not dead and dead_flag.get(cid):
                dead_flag[cid] = False
                res.resurrections += 1
        if pending_liq:
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    note_collapse(cid, 0.0, d); del pos[cid]; entry_avg.pop(cid, None); continue
                val = pos[cid] * px; fee = val * CB_COST
                cash += val - fee; res.costs += fee; res.orders += 1
                note_collapse(cid, px, d); del pos[cid]; entry_avg.pop(cid, None)
            res.halt_date = d; res.final = cash; res.curve.append((d, cash)); break
        is_rebal = (dt.weekday() == 0 and i > i0) if cadence == "weekly" \
            else (dt.weekday() == 0 and dt.day <= 7 and i > i0)
        if is_rebal and i > 0:
            res.rebalances += 1
            j = i - 1
            universe, ranks = CB.snapshot_universe(snaps_by_date, cal[j])
            scored = []
            for cid in universe:
                if sort_key == "momentum":
                    s = mkt.momentum(cid, j, horizon)
                else:
                    s = float(ranks[cid]) if mkt.fresh(cid, j) else None
                if s is not None:
                    scored.append((cid, s))
            res._rank_sum += len(scored)
            if scored:
                if n_hold == "QUINTILE":
                    k = max(1, math.ceil(len(scored) / 5))
                elif n_hold == "ALL":
                    k = len(scored)
                else:
                    k = min(n_hold, len(scored))
                if mode == "ranked":
                    scored.sort(key=lambda x: -x[1])
                    picks = [cid for cid, _ in scored[:k]]
                else:
                    names = sorted(cid for cid, _ in scored)
                    picks = rng.sample(names, min(k, len(names)))
                res.picks_log.append({"date": d, "picks": [mkt.reg[c]["symbol"] for c in picks],
                                      "n_rankable": len(scored)})
                eq_open = equity_at(i, lambda c, ii: (mkt.trade_open(c, ii) or mkt.value_close(c, ii)))
                target = {cid: eq_open / len(picks) for cid in picks}
                for cid in list(pos):
                    if mkt.is_dead(cid, i):
                        note_collapse(cid, 0.0, d); del pos[cid]; entry_avg.pop(cid, None); continue
                    px = mkt.trade_open(cid, i)
                    if px is None: continue
                    cur_val = pos[cid] * px; want = target.get(cid, 0.0)
                    if cur_val > want + 0.01:
                        sell_val = cur_val - want; fee = sell_val * CB_COST
                        cash += sell_val - fee; res.costs += fee; res.orders += 1
                        pos[cid] -= sell_val / px
                        if want <= 0.0 or pos[cid] * px < 0.01:
                            note_collapse(cid, px, d); del pos[cid]; entry_avg.pop(cid, None)
                for cid in picks:
                    px = mkt.trade_open(cid, i)
                    if px is None: continue
                    cur_val = pos.get(cid, 0.0) * px
                    deficit = target[cid] - cur_val
                    if deficit <= 0.01: continue
                    buy_val = min(deficit, cash / (1.0 + CB_COST))
                    if buy_val <= 0.01: continue
                    fee = buy_val * CB_COST
                    cash -= buy_val + fee; res.costs += fee; res.orders += 1
                    sh_new = buy_val / px; old_sh = pos.get(cid, 0.0)
                    if old_sh > 0 and cid in entry_avg:
                        entry_avg[cid] = (entry_avg[cid] * old_sh + px * sh_new) / (old_sh + sh_new)
                    else:
                        entry_avg[cid] = px
                    pos[cid] = old_sh + sh_new
        eq_close = cash + sum(sh * mkt.value_close(cid, i) for cid, sh in pos.items())
        res.curve.append((d, eq_close))
        if floor is not None and eq_close <= floor:
            pending_liq = True
            if i == i1:
                tot = cash
                for cid, sh in list(pos.items()):
                    v = mkt.value_close(cid, i)
                    if v > 0:
                        tot += sh * v * (1 - CB_COST); res.costs += sh * v * CB_COST; res.orders += 1
                res.final = tot; res.halt_date = d; pos.clear(); break
    if res.final is None:
        res.final = res.curve[-1][1]
    peak = -1.0
    for d, eq in res.curve:
        peak = max(peak, eq)
        if peak > 0: res.max_dd = min(res.max_dd, eq / peak - 1.0)
    if res.rebalances:
        res.avg_n_rankable = round(res._rank_sum / res.rebalances, 2)
    return res

def cb_summ(r, keep_curve=True):
    out = {"final": round(r.final, 2), "max_dd_pct": round(r.max_dd * 100, 2),
           "orders": r.orders, "costs": round(r.costs, 2), "halt_date": r.halt_date,
           "avg_n_rankable": r.avg_n_rankable}
    if keep_curve:
        out["curve"] = [[d, round(e, 4)] for d, e in r.curve]
    return out

# =====================================================================
# B) crypto-basket-pit — engine copied from its v12 folder, N parameterized
# =====================================================================
PIT = _load_mod("pit_engine", os.path.join(HERE, "..", "crypto-basket-pit", "run_basket_pit_v12.py"))
PIT_COST = 0.006

def pit_simulate(mkt, start_d, end_d, cadence, ruleset, cost, mode="ranked",
                 seed=42, n_hold=5):
    """n_hold int: each pick gets (1/n_hold) of equity; fewer eligible than
    n_hold -> hold what's eligible at 1/n_hold each, rest cash (the family's
    own convention at n=5, generalized). n_hold 'ALL': all eligible, equal
    weight 1/len(eligible), fully invested."""
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    cash, pos, entry = float(POT), {}, {}
    wo = {}
    orders, costs = 0, 0.0
    curve, events, halts = [], [], []
    picks_log, elig_sum, elig_n, inv_sum = [], 0, 0, 0.0
    episode, floor_abs = 1, 85.0
    pending_liq, sit_until, ended = False, None, False

    def equity_at(i):
        return cash + sum(sh * (mkt.value_close(cid, i) or 0.0) for cid, sh in pos.items())
    def note_exit(cid, px, when):
        if cid in entry and entry[cid] > 0 and px <= 0.10 * entry[cid]:
            events.append({"type": "collapse_exit", "coin": mkt.reg[cid]["symbol"],
                           "cmc_id": cid, "date": when, "entry_px": entry[cid],
                           "exit_px": px, "loss_pct": round((px / entry[cid] - 1) * 100, 2)})

    for i in range(i0, i1 + 1):
        d = cal[i]
        for cid in list(pos):
            lb = mkt.lb[cid][i]
            if lb >= 0 and i - lb == PIT.GRACE_DAYS + 1 and not wo.get(cid):
                events.append({"type": "write_off", "coin": mkt.reg[cid]["symbol"],
                               "cmc_id": cid, "date": d, "last_bar_date": cal[lb],
                               "last_px": mkt.ff[cid][lb],
                               "written_off_value": round(pos[cid] * mkt.ff[cid][lb], 2)})
                wo[cid] = True
            if lb >= 0 and i - lb <= PIT.GRACE_DAYS and wo.get(cid): wo[cid] = False
        if pending_liq:
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    note_exit(cid, 0.0, d); del pos[cid]; entry.pop(cid, None); continue
                val = pos[cid] * px; fee = val * cost; cash += val - fee
                costs += fee; orders += 1; note_exit(cid, px, d)
                del pos[cid]; entry.pop(cid, None)
            pending_liq = False
            halts.append({"episode": episode, "halt_date": d, "liquidated_at": round(cash, 2)})
            if episode == 1:
                episode = 2
                sit_until = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
            else:
                ended = True
            curve.append((d, cash))
            if ended:
                for k in range(i + 1, i1 + 1): curve.append((cal[k], cash))
                break
            continue
        sitting = sit_until is not None and d < sit_until
        if not sitting and PIT.is_rebalance(cadence, d, i == i0):
            if sit_until is not None and d >= sit_until:
                floor_abs = 0.85 * cash; sit_until = None
                halts[-1]["restart_date"] = d; halts[-1]["restart_balance"] = round(cash, 2)
            universe = mkt.universe(d)
            j = i - 1
            elig = [(cid, mkt.eligible(cid, j)) for cid in universe]
            elig = [(c, m) for c, m in elig if m is not None]
            elig_sum += len(elig); elig_n += 1
            if n_hold == "ALL":
                k = len(elig); w = (1.0 / k) if k else 0.0
            else:
                k = min(n_hold, len(elig)); w = 1.0 / n_hold
            if mode == "ranked":
                elig.sort(key=lambda x: -x[1]); picks = [c for c, _ in elig[:k]]
            else:
                names = sorted(c for c, _ in elig)
                picks = rng.sample(names, min(k, len(names))) if names else []
            inv_sum += w * len(picks)
            if mode == "ranked":
                picks_log.append({"date": d, "picks": [mkt.reg[c]["symbol"] for c in picks],
                                  "n_eligible": len(elig)})
            eq = equity_at(i)
            target = {cid: w * eq for cid in picks}
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    lb = mkt.lb[cid][i]
                    if lb >= 0 and i - lb > PIT.GRACE_DAYS:
                        note_exit(cid, 0.0, d); del pos[cid]; entry.pop(cid, None)
                    continue
                cur = pos[cid] * px; want = target.get(cid, 0.0)
                if want <= 0.0 and cur <= 0.01:
                    note_exit(cid, px, d); del pos[cid]; entry.pop(cid, None); continue
                if cur > want + 0.01:
                    sv = cur - want; fee = sv * cost; cash += sv - fee
                    costs += fee; orders += 1; pos[cid] -= sv / px
                    if want <= 0.0 or pos[cid] * px < 0.01:
                        note_exit(cid, px, d); del pos[cid]; entry.pop(cid, None)
            for cid in picks:
                px = mkt.trade_open(cid, i)
                if px is None: continue
                deficit = target[cid] - pos.get(cid, 0.0) * px
                if deficit <= 0.01: continue
                bv = min(deficit, cash / (1.0 + cost))
                if bv <= 0.01: continue
                fee = bv * cost; cash -= bv + fee; costs += fee; orders += 1
                sh = bv / px; old = pos.get(cid, 0.0)
                entry[cid] = (entry[cid] * old + px * sh) / (old + sh) if old > 0 and cid in entry else px
                pos[cid] = old + sh
        eq_close = equity_at(i)
        curve.append((d, eq_close))
        if ruleset == "v9" and not sitting and sit_until is None and eq_close <= floor_abs:
            if i == i1:
                tot = cash
                for cid, sh in list(pos.items()):
                    v = mkt.value_close(cid, i)
                    if v: tot += sh * v - sh * v * cost; costs += sh * v * cost; orders += 1
                halts.append({"episode": episode, "halt_date": d, "liquidated_at": round(tot, 2)})
                curve[-1] = (d, tot); cash = tot; pos.clear(); ended = True
            else:
                pending_liq = True
    final = curve[-1][1]
    peak, dd = -1.0, 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0: dd = min(dd, e / peak - 1.0)
    return {"final": round(final, 2), "max_dd_pct": round(dd * 100, 2),
            "orders": orders, "costs": round(costs, 2),
            "avg_eligible": round(elig_sum / elig_n, 2) if elig_n else None,
            "avg_invested_pct": round(100 * inv_sum / elig_n, 1) if elig_n else None,
            "events": events, "halts": halts, "ended_by_second_halt": ended,
            "curve": [[d, round(e, 4)] for d, e in curve], "picks_log": picks_log}

# =====================================================================
# C) crypto-dominance-rotation — engine copied, alt-basket cap added
# =====================================================================
DOM = _load_mod("dom_engine", os.path.join(HERE, "..", "crypto-dominance-rotation", "run_dominance_rotation.py"))
DOM_COST = DOM.COST  # 0.006

def dom_target_weights(state, universe, mkt, n_cap="ALL"):
    if state == "BTC": return {1: 1.0}, 0
    basket = [c for c in universe if c not in (1, 1027) and c not in DOM.STABLES and c in mkt.bars]
    full_basket = len(basket)
    if n_cap != "ALL":
        basket = basket[:n_cap]  # universe list is in CMC rank order (best ranks first)
    w = {}
    if state == "LARGE":
        w[1027] = 0.50; alt_w = 0.50
    else:
        w[1027] = 0.25; alt_w = 0.75
    if basket:
        for c in basket: w[c] = alt_w / len(basket)
    else:
        w[1] = w.get(1, 0.0) + alt_w
    return w, full_basket

def dom_simulate(mkt, dom_keys, dom, start_d, end_d, ruleset="nofloor",
                 mode="ranked", seed=42, state_freq=None, n_cap="ALL"):
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    cash, pos, entry = float(POT), {}, {}
    orders, costs = 0, 0.0
    curve, events, halts, states_log = [], [], [], []
    basket_sizes = []
    episode, floor_abs = 1, 85.0
    pending_liq, sit_until, ended = False, None, False

    def equity_at(i):
        return cash + sum(sh * (mkt.value_close(cid, i) or 0.0) for cid, sh in pos.items())
    def note_exit(cid, px, when):
        if cid in entry and entry[cid] > 0 and px <= 0.10 * entry[cid]:
            events.append({"type": "collapse_exit", "coin": mkt.reg[cid]["symbol"],
                           "cmc_id": cid, "date": when, "entry_px": entry[cid],
                           "exit_px": px, "loss_pct": round((px / entry[cid] - 1) * 100, 2)})

    for i in range(i0, i1 + 1):
        d = cal[i]
        if pending_liq:
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    note_exit(cid, 0.0, d); del pos[cid]; entry.pop(cid, None); continue
                val = pos[cid] * px; fee = val * DOM_COST; cash += val - fee
                costs += fee; orders += 1; note_exit(cid, px, d)
                del pos[cid]; entry.pop(cid, None)
            pending_liq = False
            halts.append({"episode": episode, "halt_date": d, "liquidated_at": round(cash, 2)})
            if episode == 1:
                episode = 2
                sit_until = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
            else:
                ended = True
            curve.append((d, cash))
            if ended:
                for k in range(i + 1, i1 + 1): curve.append((cal[k], cash))
                break
            continue
        sitting = sit_until is not None and d < sit_until
        dt = datetime.strptime(d, "%Y-%m-%d")
        if not sitting and (i == i0 or dt.day == 1):
            if sit_until is not None and d >= sit_until:
                floor_abs = 0.85 * cash; sit_until = None
                halts[-1]["restart_date"] = d; halts[-1]["restart_balance"] = round(cash, 2)
            prev = cal[i - 1] if i > 0 else d
            universe = mkt.universe(prev)
            st, D = DOM.state_at(dom_keys, dom, prev)
            if mode == "placebo":
                r = rng.random(); acc = 0.0; st = "ALT"
                for sname in ("BTC", "LARGE", "ALT"):
                    acc += state_freq[sname]
                    if r <= acc: st = sname; break
            target, fb = dom_target_weights(st, universe, mkt, n_cap)
            if st in ("LARGE", "ALT"): basket_sizes.append(fb)
            states_log.append({"date": d, "state": st})
            eq = equity_at(i)
            tw = {cid: w * eq for cid, w in target.items()}
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    lb = mkt.lb[cid][i]
                    if lb >= 0 and i - lb > DOM.GRACE_DAYS:
                        note_exit(cid, 0.0, d); del pos[cid]; entry.pop(cid, None)
                    continue
                cur = pos[cid] * px; want = tw.get(cid, 0.0)
                if cur > want + 0.01:
                    sv = cur - want; fee = sv * DOM_COST; cash += sv - fee
                    costs += fee; orders += 1; pos[cid] -= sv / px
                    if want <= 0.0 or pos[cid] * px < 0.01:
                        note_exit(cid, px, d); del pos[cid]; entry.pop(cid, None)
            for cid, want_val in tw.items():
                px = mkt.trade_open(cid, i)
                if px is None: continue
                deficit = want_val - pos.get(cid, 0.0) * px
                if deficit <= 0.01: continue
                bv = min(deficit, cash / (1.0 + DOM_COST))
                if bv <= 0.01: continue
                fee = bv * DOM_COST; cash -= bv + fee; costs += fee; orders += 1
                sh = bv / px; old = pos.get(cid, 0.0)
                entry[cid] = (entry[cid] * old + px * sh) / (old + sh) if old > 0 and cid in entry else px
                pos[cid] = old + sh
        eq_close = equity_at(i)
        curve.append((d, eq_close))
        if ruleset == "v9" and not sitting and sit_until is None and eq_close <= floor_abs:
            if i == i1:
                tot = cash
                for cid, sh in list(pos.items()):
                    v = mkt.value_close(cid, i)
                    if v: tot += sh * v - sh * v * DOM_COST; costs += sh * v * DOM_COST; orders += 1
                halts.append({"episode": episode, "halt_date": d, "liquidated_at": round(tot, 2)})
                curve[-1] = (d, tot); cash = tot; pos.clear(); ended = True
            else:
                pending_liq = True
    final = curve[-1][1]
    peak, dd = -1.0, 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0: dd = min(dd, e / peak - 1.0)
    return {"final": round(final, 2), "max_dd_pct": round(dd * 100, 2),
            "orders": orders, "costs": round(costs, 2), "events": events,
            "halts": halts, "ended_by_second_halt": ended, "states_log": states_log,
            "avg_full_alt_basket": round(sum(basket_sizes) / len(basket_sizes), 2) if basket_sizes else None,
            "curve": [[d, round(e, 4)] for d, e in curve]}

# =====================================================================
# main — checkpointed: results.json saved after every block; blocks
# listed in "blocks_done" are skipped on restart. Curves are kept only
# where period distributions may be needed (native cadence cells for A,
# monthly/quarterly for B, all for C); other cells store summaries only.
def placebo_block(ranked_final, finals):
    sf = sorted(finals)
    return {"n_seeds": len(finals), "median_final": round(pct(sf, .5), 2),
            "p25_final": round(pct(sf, .25), 2), "p75_final": round(pct(sf, .75), 2),
            "best_final": round(sf[-1], 2), "worst_final": round(sf[0], 2),
            "ranked_final": ranked_final,
            "ranked_beats_n_of_20": sum(1 for v in finals if ranked_final > v),
            "finals": [round(v, 2) for v in finals]}

def main():
    t0 = time.time()
    rp = os.path.join(HERE, "results.json")
    if os.path.exists(rp):
        with open(rp) as f: out = json.load(f)
        print(f"resume: {len(out.get('blocks_done', []))} blocks done", flush=True)
    else:
        out = {"wing": "holdings-count sweep — crypto baskets",
               "grid_counts": [str(c) for c in COUNTS], "pot": POT,
               "windows": WINDOWS, "families": {}, "blocks_done": []}
    done = set(out.setdefault("blocks_done", []))

    def save():
        tmp = rp + ".tmp"
        with open(tmp, "w") as f: json.dump(out, f, indent=1)
        os.replace(tmp, rp)

    # ---------------- A) crypto-basket ----------------
    print("=== A crypto-basket ===", flush=True)
    with open(os.path.join(CB.V4DATA, "snapshots.json")) as f:
        snaps = json.load(f)
    sbd = []
    for month in sorted(snaps):
        info = snaps[month]; sd = info["snapshot_date"]
        sd = f"{sd[:4]}-{sd[4:6]}-{sd[6:8]}"
        ids = [c["cmc_id"] for c in info["top20"]]
        rk = {c["cmc_id"]: c["rank"] for c in info["top20"]}
        sbd.append((sd, ids, rk))
    sbd.sort()
    reg = CB.build_registry(snaps); mktA = CB.Market(reg)
    r = cb_simulate(mktA, sbd, *WINDOWS["full"], "momentum", horizon=21, n_hold="QUINTILE")
    assert abs(r.final - 2677.25) < 0.02, f"A integrity mom21 full {r.final}"
    del r
    famA = out["families"].setdefault("crypto-basket",
        {"family": "crypto-basket (LTW CONSTRUCTED long leg)", "cost_per_side": CB_COST,
         "native_form": "top QUINTILE (k=ceil(rankable/5), ~4), weekly",
         "sorts": ["mom7d", "mom14d", "mom21d", "mom28d", "size-truncated"],
         "runs": {}, "quintile_native": {}, "placebos": {}, "btc_hold": {}})
    for w, (sd, ed) in WINDOWS.items():
        b, bdd = CB.btc_hold(mktA, sd, ed)
        famA["btc_hold"][w] = {"final": round(b, 2), "max_dd_pct": round(bdd * 100, 2)}
    sorts = [("momentum", 7, "mom7d"), ("momentum", 14, "mom14d"),
             ("momentum", 21, "mom21d"), ("momentum", 28, "mom28d"),
             ("size", None, "size-truncated")]
    for sk, h, stag in sorts:
        blk = f"A-grid-{stag}"
        if blk not in done:
            for cad in ("weekly", "monthly"):
                keep = (cad == "weekly")
                for ruleset in ("native", "v9"):
                    for w, (sd, ed) in WINDOWS.items():
                        rq = cb_simulate(mktA, sbd, sd, ed, sk, horizon=h, cadence=cad,
                                         ruleset=ruleset, n_hold="QUINTILE")
                        famA["quintile_native"][f"{stag}|{cad}|{ruleset}|{w}"] = cb_summ(rq, keep)
                        del rq
                        for n in COUNTS:
                            rr = cb_simulate(mktA, sbd, sd, ed, sk, horizon=h, cadence=cad,
                                             ruleset=ruleset, n_hold=n)
                            famA["runs"][f"{stag}|{cad}|{ruleset}|{w}|n={nkey(n)}"] = cb_summ(rr, keep)
                            del rr
            done.add(blk); out["blocks_done"] = sorted(done); save()
            print(f"A grid {stag} done ({time.time()-t0:.0f}s)", flush=True)
        blk = f"A-plc-{stag}"
        if blk not in done:
            for w in ("full", "validation"):
                sd, ed = WINDOWS[w]
                for n in COUNTS:
                    finals = []
                    for seed in SEEDS:
                        rr = cb_simulate(mktA, sbd, sd, ed, sk, horizon=h, cadence="weekly",
                                         ruleset="native", mode="placebo", seed=seed, n_hold=n)
                        finals.append(rr.final); del rr
                    rk = famA["runs"][f"{stag}|weekly|native|{w}|n={nkey(n)}"]["final"]
                    famA["placebos"][f"{stag}|weekly|native|{w}|n={nkey(n)}"] = placebo_block(rk, finals)
            done.add(blk); out["blocks_done"] = sorted(done); save()
            print(f"A placebos {stag} done ({time.time()-t0:.0f}s)", flush=True)
    del mktA, reg

    # ---------------- B) crypto-basket-pit ----------------
    print("=== B crypto-basket-pit ===", flush=True)
    regB = PIT.load_registry(); weeklyB = PIT.load_weekly(); mktB = PIT.Market(regB, weeklyB)
    rb = pit_simulate(mktB, *WINDOWS["full"], "monthly", "nofloor", PIT_COST, n_hold=5)
    assert abs(rb["final"] - 1235.94) < 0.02, f"B integrity full {rb['final']}"
    del rb
    famB = out["families"].setdefault("crypto-basket-pit",
        {"family": "crypto-basket-pit (program CONSTRUCTED form)", "cost_per_side": PIT_COST,
         "native_form": "top-5, monthly, 12-1 momentum + above-200d filter",
         "runs": {}, "placebos": {}, "btc_hold": {}})
    famB["btc_hold"] = {w: {k: PIT.btc_hold(mktB, sd, ed, 0.006)[k]
                            for k in ("final", "max_dd_pct")}
                        for w, (sd, ed) in WINDOWS.items()}
    for cad in PIT.CADENCES:
        blk = f"B-grid-{cad}"
        if blk not in done:
            keep = cad in ("monthly", "quarterly")
            for ruleset in ("nofloor", "v9"):
                rs_name = "native" if ruleset == "nofloor" else "v9"
                for w, (sd, ed) in WINDOWS.items():
                    for n in COUNTS:
                        rr = pit_simulate(mktB, sd, ed, cad, ruleset, PIT_COST, n_hold=n)
                        if not keep:
                            rr = {k: v for k, v in rr.items() if k not in ("curve", "picks_log")}
                        famB["runs"][f"{cad}|{rs_name}|{w}|n={nkey(n)}"] = rr
                        del rr
            done.add(blk); out["blocks_done"] = sorted(done); save()
            print(f"B grid {cad} done ({time.time()-t0:.0f}s)", flush=True)
        blk = f"B-plc-{cad}"
        if cad in ("monthly", "quarterly", "weekly") and blk not in done:
            for w in ("full", "validation"):
                sd, ed = WINDOWS[w]
                for n in COUNTS:
                    finals = []
                    for seed in SEEDS:
                        rr = pit_simulate(mktB, sd, ed, cad, "nofloor", PIT_COST,
                                          mode="placebo", seed=seed, n_hold=n)
                        finals.append(rr["final"]); del rr
                    rk = famB["runs"][f"{cad}|native|{w}|n={nkey(n)}"]["final"]
                    famB["placebos"][f"{cad}|native|{w}|n={nkey(n)}"] = placebo_block(rk, finals)
            done.add(blk); out["blocks_done"] = sorted(done); save()
            print(f"B placebos {cad} done ({time.time()-t0:.0f}s)", flush=True)
    del mktB, regB

    # ---------------- C) crypto-dominance-rotation ----------------
    print("=== C crypto-dominance-rotation ===", flush=True)
    regC = DOM.load_registry()
    with open(os.path.join(HERE, "..", "crypto-basket-pit", "data", "weekly_snapshots.json")) as f:
        weeklyC = json.load(f)
    dk, dom = DOM.load_dominance()
    mktC = DOM.Market(regC, weeklyC)
    rc = dom_simulate(mktC, dk, dom, *WINDOWS["full"], n_cap="ALL")
    assert abs(rc["final"] - 1306.49) < 0.02, f"C integrity full {rc['final']}"
    famC = out["families"].setdefault("crypto-dominance-rotation",
        {"family": "crypto-dominance-rotation (CONSTRUCTED) — swept leg: ALT-basket breadth",
         "cost_per_side": DOM_COST,
         "native_form": "ALL eligible alts in basket leg (uncapped), monthly",
         "avg_full_alt_basket_size": rc["avg_full_alt_basket"],
         "runs": {}, "placebos": {}, "btc_hold": {}, "ew_hold": {}})
    del rc
    for w, (sd, ed) in WINDOWS.items():
        bh = DOM.btc_hold(mktC, sd, ed)
        famC["btc_hold"][w] = {k: bh[k] for k in ("final", "max_dd_pct")}
        ew = DOM.simulate(mktC, dk, dom, sd, ed, mode="ew")
        famC["ew_hold"][w] = {k: ew[k] for k in ("final", "max_dd_pct")}
        del ew
    if "C-grid" not in done:
        for ruleset, rs_name in (("nofloor", "native"), ("v9", "v9")):
            for w, (sd, ed) in WINDOWS.items():
                for n in COUNTS:
                    rr = dom_simulate(mktC, dk, dom, sd, ed, ruleset=ruleset, n_cap=n)
                    famC["runs"][f"{rs_name}|{w}|n={nkey(n)}"] = rr
                    del rr
        done.add("C-grid"); out["blocks_done"] = sorted(done); save()
        print(f"C grid done ({time.time()-t0:.0f}s)", flush=True)
    if "C-plc" not in done:
        for w in ("full", "validation"):
            sd, ed = WINDOWS[w]
            log = famC["runs"][f"native|{w}|n=ALL"]["states_log"]
            freq = {s: sum(1 for x in log if x["state"] == s) / len(log) for s in ("BTC", "LARGE", "ALT")}
            for n in COUNTS:
                finals = []
                for seed in SEEDS:
                    rr = dom_simulate(mktC, dk, dom, sd, ed, mode="placebo", seed=seed,
                                      state_freq=freq, n_cap=n)
                    finals.append(rr["final"]); del rr
                rk = famC["runs"][f"native|{w}|n={nkey(n)}"]["final"]
                blk2 = placebo_block(rk, finals); blk2["state_freq"] = {k: round(v, 3) for k, v in freq.items()}
                famC["placebos"][f"native|{w}|n={nkey(n)}"] = blk2
        done.add("C-plc"); out["blocks_done"] = sorted(done); save()
        print(f"C placebos done ({time.time()-t0:.0f}s)", flush=True)
    save()
    print(f"ALL saved in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
