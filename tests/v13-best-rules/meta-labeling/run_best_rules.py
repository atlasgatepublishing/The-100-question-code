#!/usr/bin/env python3
"""
META-LABELING v13 BEST-RULES — per BEST-RULES-SPEC.md (frozen before run).
Confirmation run of a closed premise with three mechanical corrections vs v12:
(1) label = the episode's ACTUAL net return sign (not triple-barrier wiggles);
(2) action = LdP sizing map s = clip(2p-1,0,1) on the primary's slot
    (not hard veto); (3) model = bagged CART forest, the author's example
    model class (not logistic). Primary (quality-momentum weekly), purge
    discipline, costs, OOS window identical to v12. Shared inputs read-only.
"""
import importlib.util, json, math, os, random, time
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")

def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

qm = load_mod("qm", os.path.join(BT, "v10-retest", "quality-momentum", "qm_v10.py"))
v12 = load_mod("v12", os.path.join(BT, "v12-completions", "meta-labeling",
                                  "run_meta_labeling.py"))

UNIVERSE = qm.UNIVERSE
WIN = ("2013-01-02", "2026-11-20")
OOS = ("2022-01-01", "2026-11-20")
CONT = ("2019-01-01", "2026-11-20")
DECADE = ("2016-11-21", "2026-11-20")
FEATURES = ["qr", "mr", "atr_pct", "dist200", "spy_above200", "spy_rvol20",
            "spy_ret20", "name_ret20"]

# ------------------------------------------------------------ features/labels
def build_episode_data(stream, ohlc, pb):
    """Episodes with 8 entry features and REALIZED labels (spec correction 1).
    Label = 1 iff net episode return (exit open / entry open - 1 - 0.25%
    round-trip allowance) > 0; label_end = exit execution date."""
    eps = v12.build_episodes(stream)
    ranks = {}
    for d, picks, rk in stream:
        for t, (a, b) in rk.items():
            ranks[(t, d)] = (a, b)
    nxt = {}
    for i, d in enumerate(pb.dates[:-1]):
        nxt[d] = pb.dates[i + 1]
    spy = ohlc["SPY"]; spy_idx = {b["d"]: i for i, b in enumerate(spy)}
    spy_close = [b["c"] for b in spy]
    out = []
    for ep in eps:
        t = ep["ticker"]; bars = ohlc[t]
        idx = {b["d"]: i for i, b in enumerate(bars)}
        es = ep["entry_sel"]
        if es not in idx or es not in spy_idx:
            continue
        i0 = idx[es]
        atrp = v12.atr_pct_series(bars)[i0]
        if atrp is None or i0 < 200:
            continue
        closes = [b["c"] for b in bars]
        sma200 = sum(closes[i0 - 199:i0 + 1]) / 200.0
        si = spy_idx[es]
        spy_sma = sum(spy_close[si - 199:si + 1]) / 200.0
        rets = [spy_close[j] / spy_close[j - 1] - 1.0 for j in range(si - 19, si + 1)]
        qr_, mr_ = ranks[(t, es)]
        feats_d = {"qr": qr_, "mr": mr_, "atr_pct": atrp,
                   "dist200": closes[i0] / sma200 - 1.0,
                   "spy_above200": 1.0 if spy_close[si] > spy_sma else 0.0,
                   "spy_rvol20": float(np.std(rets, ddof=1)),
                   "spy_ret20": spy_close[si] / spy_close[si - 20] - 1.0,
                   "name_ret20": closes[i0] / closes[i0 - 20] - 1.0}
        entry_exec = nxt.get(es)
        exit_sel = None; seen = False
        for d, picks, _ in stream:
            if d == ep["last_sel"]:
                seen = True; continue
            if seen:
                exit_sel = d; break
        if entry_exec is None or entry_exec not in idx:
            continue
        ei = idx[entry_exec]; p0 = bars[ei]["o"]
        if exit_sel is None:
            net = bars[-1]["c"] / p0 - 1.0 - 0.0025
            ep.update(features=feats_d, label=1 if net > 0 else 0,
                      label_end=bars[-1]["d"], exit_exec=bars[-1]["d"],
                      net_ret=net)
            out.append(ep); continue
        exit_exec = nxt.get(exit_sel)
        if exit_exec is None or exit_exec not in idx:
            continue
        xi = idx[exit_exec]
        net = bars[xi]["o"] / p0 - 1.0 - 0.0025
        ep.update(features=feats_d, label=1 if net > 0 else 0,
                  label_end=exit_exec, exit_exec=exit_exec, net_ret=net)
        out.append(ep)
    return out

def feats(eps_list):
    return np.array([[e["features"][f] for f in FEATURES] for e in eps_list])

# ------------------------------------------------------------ bagged CART forest
def _gini(y):
    if len(y) == 0:
        return 0.0
    p = y.mean()
    return 2.0 * p * (1.0 - p)

def fit_tree(X, y, rng, depth=0, max_depth=4, min_leaf=20, mtry=3):
    n = len(y); val = float(y.mean())
    if depth >= max_depth or n < 2 * min_leaf or y.min() == y.max():
        return ("leaf", val)
    k = X.shape[1]
    cand = rng.choice(k, size=min(mtry, k), replace=False)
    base = _gini(y); best = None
    for f in cand:
        x = X[:, f]
        for thr in np.unique(np.quantile(x, [0.2, 0.35, 0.5, 0.65, 0.8])):
            left = x <= thr
            nl = int(left.sum()); nr = n - nl
            if nl < min_leaf or nr < min_leaf:
                continue
            gain = base - (nl * _gini(y[left]) + nr * _gini(y[~left])) / n
            if gain > 1e-12 and (best is None or gain > best[0]):
                best = (gain, f, float(thr))
    if best is None:
        return ("leaf", val)
    _, f, thr = best
    left = X[:, f] <= thr
    return ("node", f, thr,
            fit_tree(X[left], y[left], rng, depth + 1, max_depth, min_leaf, mtry),
            fit_tree(X[~left], y[~left], rng, depth + 1, max_depth, min_leaf, mtry))

def tree_predict(node, x):
    while node[0] == "node":
        node = node[3] if x[node[1]] <= node[2] else node[4]
    return node[1]

def fit_forest(X, y, seed, n_trees=300):
    rng = np.random.default_rng(seed)
    n = len(y); trees = []
    for _ in range(n_trees):
        idx = rng.integers(0, n, n)
        trees.append(fit_tree(X[idx], y[idx], rng))
    return trees

def forest_predict(trees, X):
    return np.array([np.mean([tree_predict(tr, x) for tr in trees]) for x in X])

# ------------------------------------------------------------ weighted engine
# COPY of v12/qm run_episode with ONE change: slot targets scaled by the
# sizing map s in [0,1] keyed by (ticker, selection_date); default 1.0.
def run_episode_w(pb, quality_obs, start, end, start_cash, floor, sel_dates,
                    size_map=None, want_curve=False):
    cash = start_cash; floor_now = floor
    positions = {}; trades = []; total_costs = 0.0
    halted = None; halt_close = None
    min_close, min_close_date = None, None
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None; curve = []

    def portfolio_close(d):
        i = pb.didx[d]; v = cash
        for t, sh in positions.items():
            c = pb.prev_close[t][i]
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0; opens = {}
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
                cash += sell_val - c; cost += c
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
                cash -= buy_val + c; cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending); pending = None
        if d in sel_set:
            scores = {}
            for t in UNIVERSE:
                q = qm.quality_at(quality_obs.get(t, []), d)
                if q is None:
                    continue
                bl = pb.bars.get(t, [])
                didx = pb.tidx.get(t, {}).get(d)
                if didx is None or didx < 253:
                    continue
                mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
                scores[t] = (q[2], mom)
            if len(scores) >= 5:
                qr = qm.percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = qm.percentile_ranks({t: v[1] for t, v in scores.items()})
                combined = {t: (qr[t] + mr[t]) / 2.0 for t in scores}
                picks = sorted(combined, key=lambda t: -combined[t])[:5]
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each * (size_map.get((t, d), 1.0) if size_map else 1.0)
                           for t in picks}
        v = portfolio_close(d)
        if want_curve:
            curve.append((d, round(v, 4)))
        if min_close is None or v < min_close:
            min_close, min_close_date = v, d
        if v <= floor_now and di < len(days) - 1:
            halted = d; halt_close = v
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c; total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            if want_curve:
                curve.append((nd, round(cash, 4)))
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_close": halt_close,
                    "floor_in_effect": floor_now, "min_close": min_close,
                    "min_close_date": min_close_date, "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst; total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    if want_curve and curve:
        curve[-1] = (last, round(cash, 4))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_close": None,
            "floor_in_effect": floor_now, "min_close": min_close,
            "min_close_date": min_close_date, "curve": curve}

def run_v9w(pb, quality_obs, start, end, size_map=None, want_curve=False):
    sel_all = qm.cadence_dates(pb, "weekly", start, end)
    ep1 = run_episode_w(pb, quality_obs, start, end, 100.0, 85.0, sel_all,
                        size_map=size_map, want_curve=want_curve)
    out = {"episode1": ep1, "episode2": None, "final": ep1["final"],
           "halts": [], "restart": False, "second_halt": False,
           "costs": ep1["costs"], "orders": len(ep1["trades"]),
           "curve": list(ep1["curve"])}
    if ep1["halted"] is None:
        return out
    out["halts"].append(ep1["halted"])
    liq = date.fromisoformat(ep1["end"]); cash1 = ep1["final"]
    eligible = (liq + timedelta(days=90)).isoformat()
    cands = [d for d in sel_all if d >= eligible]
    if not cands:
        return out
    restart = cands[0]; out["restart"] = True
    ep2 = run_episode_w(pb, quality_obs, restart, end, cash1, 0.85 * cash1,
                        [d for d in sel_all if d >= restart],
                        size_map=size_map, want_curve=want_curve)
    out["episode2"] = ep2; out["final"] = ep2["final"]
    out["costs"] += ep2["costs"]; out["orders"] += len(ep2["trades"])
    if want_curve:
        curve = list(ep1["curve"]); have = {d for d, _ in curve}
        dcur = liq
        while dcur.isoformat() < restart:
            ds = dcur.isoformat()
            if ds in pb.didx and start <= ds <= end and ds not in have:
                curve.append((ds, round(cash1, 4)))
            dcur += timedelta(days=1)
        curve.extend(ep2["curve"]); curve.sort(); out["curve"] = curve
    if ep2["halted"] is not None:
        out["second_halt"] = True; out["halts"].append(ep2["halted"])
    return out

# ------------------------------------------------------------ helpers
def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return round(mdd * 100, 2)

def auc_score(y, p):
    y = np.asarray(y, float); p = np.asarray(p, float)
    order = np.argsort(p); ranks = np.empty(len(p)); ranks[order] = np.arange(1, len(p) + 1)
    # average ranks for ties
    i = 0
    while i < len(p):
        j = i
        while j + 1 < len(p) and p[order[j + 1]] == p[order[i]]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = ranks[order[i:j + 1]].mean()
        i = j + 1
    n1 = y.sum(); n0 = len(y) - n1
    if not n1 or not n0:
        return None
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))

def size_map_from_probs(eps_list, prob_by_id):
    sm = {}
    for e in eps_list:
        if e["id"] in prob_by_id:
            s = min(1.0, max(0.0, 2.0 * prob_by_id[e["id"]] - 1.0))
            for d in e["sel_dates"]:
                sm[(e["ticker"], d)] = s
    return sm

def weekly_stats(curve):
    """Per-period (ISO-week) distribution from a daily equity curve."""
    weeks = {}
    for d, v in curve:
        y, w, _ = date.fromisoformat(d).isocalendar()
        weeks[(y, w)] = v
    vals = [weeks[k] for k in sorted(weeks)]
    rets = [vals[i] / vals[i - 1] - 1.0 for i in range(1, len(vals))]
    if not rets:
        return {}
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    peak = vals[0]; underwater = cur2 = 0
    for v in vals:
        peak = max(peak, v)
        cur2 = cur2 + 1 if v < peak else 0
        underwater = max(underwater, cur2)
    return {"periods": len(rets), "pct_positive": round(100.0 * pos / len(rets), 1),
            "median_pct": round(100.0 * float(np.median(rets)), 2),
            "mean_pct_secondary": round(100.0 * float(np.mean(rets)), 2),
            "best_pct": round(100.0 * max(rets), 2),
            "worst_pct": round(100.0 * min(rets), 2),
            "longest_losing_streak_weeks": streak,
            "longest_stretch_between_highs_weeks": underwater}

def arm(r):
    return {"final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": r["orders"], "halts": len(r["halts"]),
            "max_dd_pct": max_dd(r["curve"]), "curve": r["curve"]}

# ------------------------------------------------------------ main
def main():
    t0 = time.time()
    quality = qm.load_quality()
    bars_oc = {t: qm.load_bars_full(t) for t in UNIVERSE + ["SPY"]}
    pb = qm.PriceBook(bars_oc)
    ohlc = {t: v12.ohlc_bars(t) for t in UNIVERSE + ["SPY"]}

    integ = v12.run_v9m(pb, quality, DECADE[0], DECADE[1], "weekly", want_curve=True)
    print(f"INTEGRITY decade primary-alone: ${integ['final']:.2f} (expected 1164.49)", flush=True)
    assert round(integ["final"], 2) == 1164.49, "integrity anchor failed"

    stream = v12.selection_stream(pb, quality, WIN[0], WIN[1])
    eps = build_episode_data(stream, ohlc, pb)
    for i, e in enumerate(eps):
        e["id"] = i
    print(f"episodes with realized labels+features: {len(eps)}", flush=True)
    base = float(np.mean([e['label'] for e in eps]))
    print(f"realized label base rate: {base:.3f}", flush=True)

    def train_pool(year):
        cut = f"{year - 1}-12-20"
        return [e for e in eps if e["label_end"] <= cut]

    def walk_forward(years, shuffle_seed=None):
        preds = {}; sizes = {}
        for Y in years:
            pool = train_pool(Y)
            sizes[Y] = len(pool)
            yr = [e for e in eps if e["entry_sel"][:4] == str(Y)]
            if not yr or not pool:
                continue
            y = np.array([e["label"] for e in pool], float)
            if shuffle_seed is not None:
                rng = random.Random(shuffle_seed * 1000 + Y)
                yl = list(y); rng.shuffle(yl); y = np.array(yl)
            trees = fit_forest(feats(pool), y, seed=20261122 + Y + (shuffle_seed or 0) * 77)
            for e, p in zip(yr, forest_predict(trees, feats(yr))):
                preds[e["id"]] = float(p)
        return preds, sizes

    # ---- MAIN road walk-forward 2022-2026
    preds, pool_main = walk_forward(range(2022, 2027))
    oos_eps = [e for e in eps if OOS[0] <= e["entry_sel"] <= OOS[1] and e["id"] in preds]
    yv = np.array([e["label"] for e in oos_eps], float)
    pv = np.array([preds[e["id"]] for e in oos_eps])
    auc_main = auc_score(yv, pv)
    acc_main = float(np.mean((pv >= 0.5) == (yv == 1)))
    print(f"MAIN pools: {pool_main}  OOS eps: {len(oos_eps)}  AUC={auc_main} acc={acc_main:.3f}", flush=True)
    zeroed = [e for e in oos_eps if preds[e["id"]] <= 0.5]
    print(f"episodes sized to zero (p<=0.5): {len(zeroed)}  their win rate: "
          f"{np.mean([e['label'] for e in zeroed]) if zeroed else float('nan'):.3f}  "
          f"OOS base: {yv.mean():.3f}", flush=True)

    sm_main = size_map_from_probs(oos_eps, preds)
    primary_main = arm(run_v9w(pb, quality, OOS[0], OOS[1], want_curve=True))
    meta_main = arm(run_v9w(pb, quality, OOS[0], OOS[1], size_map=sm_main, want_curve=True))
    print(f"PRIMARY MAIN: ${primary_main['final']:.2f} DD {primary_main['max_dd_pct']}%", flush=True)
    print(f"META MAIN:    ${meta_main['final']:.2f} DD {meta_main['max_dd_pct']}%", flush=True)

    # ---- CONT-style road walk-forward 2019-2026
    preds_c, pool_cont = walk_forward(range(2019, 2027))
    cont_eps = [e for e in eps if CONT[0] <= e["entry_sel"] <= CONT[1] and e["id"] in preds_c]
    auc_cont = auc_score([e["label"] for e in cont_eps], [preds_c[e["id"]] for e in cont_eps])
    sm_cont = size_map_from_probs(cont_eps, preds_c)
    primary_cont = arm(run_v9w(pb, quality, CONT[0], CONT[1], want_curve=True))
    meta_cont = arm(run_v9w(pb, quality, CONT[0], CONT[1], size_map=sm_cont, want_curve=True))
    print(f"CONT pools: {pool_cont} AUC={auc_cont}", flush=True)
    print(f"PRIMARY CONT-window: ${primary_cont['final']:.2f} DD {primary_cont['max_dd_pct']}%", flush=True)
    print(f"META CONT-window:    ${meta_cont['final']:.2f} DD {meta_cont['max_dd_pct']}%", flush=True)

    # ---- confirmation splits on MAIN
    conf = {}
    for name, (cs, ce) in {"2022-2023": ("2022-01-01", "2023-12-31"),
                           "2024-2026": ("2024-01-01", "2026-11-20")}.items():
        sub = [e for e in oos_eps if cs <= e["entry_sel"] <= ce]
        sm = size_map_from_probs(sub, preds)
        conf[name] = {"primary": arm(run_v9w(pb, quality, cs, ce, want_curve=True)),
                      "meta": arm(run_v9w(pb, quality, cs, ce, size_map=sm, want_curve=True))}
        print(f"CONF {name}: primary ${conf[name]['primary']['final']:.2f} meta ${conf[name]['meta']['final']:.2f}", flush=True)

    # ---- placebos on MAIN: 20 random-probability
    rand_finals = []
    for i in range(20):
        rng = random.Random(20261301 + i)
        rp = {e["id"]: rng.random() for e in oos_eps}
        r = run_v9w(pb, quality, OOS[0], OOS[1], size_map=size_map_from_probs(oos_eps, rp))
        rand_finals.append(round(r["final"], 2))
    print("random-prob finals:", rand_finals, flush=True)

    # ---- placebos on MAIN: 20 shuffled-label models
    shuf_finals = []
    for s in range(20):
        sp, _ = walk_forward(range(2022, 2027), shuffle_seed=977 + s)
        sub = [e for e in eps if OOS[0] <= e["entry_sel"] <= OOS[1] and e["id"] in sp]
        r = run_v9w(pb, quality, OOS[0], OOS[1], size_map=size_map_from_probs(sub, sp))
        shuf_finals.append(round(r["final"], 2))
        print(f"shuffled seed {s}: ${shuf_finals[-1]:.2f}", flush=True)

    results = {
        "family": "meta-labeling",
        "form": "v13 BEST-RULES confirmation run: LdP meta-labeling over quality-momentum weekly primary; realized-outcome labels; sizing map s=clip(2p-1,0,1); bagged CART forest (300 trees, depth 4, min leaf 20, mtry 3); purged annual walk-forward",
        "integrity_decade_primary_alone": round(integ["final"], 2),
        "integrity_expected": 1164.49,
        "episodes_total": len(eps),
        "episodes_by_entry_year": {y: len([e for e in eps if e["entry_sel"][:4] == y])
                                   for y in sorted({e["entry_sel"][:4] for e in eps})},
        "realized_label_base_rate_all": round(base, 4),
        "main_road": {"window": list(OOS), "train_pool_sizes": pool_main,
                      "oos_episodes": len(oos_eps),
                      "auc": round(auc_main, 4) if auc_main else None,
                      "accuracy": round(acc_main, 4),
                      "oos_base_rate": round(float(yv.mean()), 4),
                      "episodes_sized_to_zero": len(zeroed),
                      "zeroed_win_rate": round(float(np.mean([e['label'] for e in zeroed])), 4) if zeroed else None,
                      "primary_alone": {k: primary_main[k] for k in ("final", "costs", "orders", "halts", "max_dd_pct")},
                      "meta_sized": {k: meta_main[k] for k in ("final", "costs", "orders", "halts", "max_dd_pct")},
                      "weekly_primary": weekly_stats(primary_main["curve"]),
                      "weekly_meta": weekly_stats(meta_main["curve"])},
        "cont_road": {"window": list(CONT), "train_pool_sizes": pool_cont,
                      "episodes": len(cont_eps),
                      "auc": round(auc_cont, 4) if auc_cont else None,
                      "primary_alone": {k: primary_cont[k] for k in ("final", "costs", "orders", "halts", "max_dd_pct")},
                      "meta_sized": {k: meta_cont[k] for k in ("final", "costs", "orders", "halts", "max_dd_pct")}},
        "confirmation": {k: {"primary_final": v["primary"]["final"], "primary_dd": v["primary"]["max_dd_pct"],
                             "meta_final": v["meta"]["final"], "meta_dd": v["meta"]["max_dd_pct"]}
                         for k, v in conf.items()},
        "random_prob_finals_main": rand_finals,
        "shuffled_label_finals_main": shuf_finals,
        "v12_reference_main": {"primary_alone": 223.37, "meta_veto": 207.71, "auc": 0.470},
        "equity_curves": {"primary_main": primary_main["curve"], "meta_main": meta_main["curve"],
                          "primary_cont": primary_cont["curve"], "meta_cont": meta_cont["curve"]},
        "episodes": [{"id": e["id"], "ticker": e["ticker"], "entry_sel": e["entry_sel"],
                      "exit_exec": e["exit_exec"], "label": e["label"],
                      "label_end": e["label_end"], "net_ret": round(e["net_ret"], 4),
                      "features": {k: round(v, 5) for k, v in e["features"].items()},
                      "prob_main": (round(preds[e["id"]], 4) if e["id"] in preds else None),
                      "prob_cont": (round(preds_c[e["id"]], 4) if e["id"] in preds_c else None)}
                     for e in eps],
        "runtime_sec": round(time.time() - t0, 1),
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
