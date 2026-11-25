#!/usr/bin/env python3
"""
META-LABELING (v12 CONSTRUCTED) — Lopez de Prado's secondary veto model over
the program's proven quality-momentum WEEKLY primary, per CONSTRUCTION-SPEC.md
(frozen before this run). Primary engine functions are copied verbatim from
backtests/v10-retest/quality-momentum/qm_v10.py (marked COPY), with one added
hook: a `blocked` set of (ticker, selection_date) pairs whose picks are
removed at selection time (the meta-veto). Everything else is byte-identical
logic. Shared caches are read-only; outputs land only in this folder.
"""
import importlib.util, json, math, os, random, time
from datetime import date, timedelta

import numpy as np
from scipy.optimize import minimize

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
spec = importlib.util.spec_from_file_location(
    "qm", os.path.join(BT, "v10-retest", "quality-momentum", "qm_v10.py"))
qm = importlib.util.module_from_spec(spec); spec.loader.exec_module(qm)

UNIVERSE = qm.UNIVERSE
WIN = ("2013-01-02", "2026-11-20")
OOS = ("2022-01-01", "2026-11-20")
DECADE = ("2016-11-21", "2026-11-20")
FEATURES = ["qr", "mr", "atr_pct", "dist200", "spy_above200", "spy_rvol20"]

# ------------------------------------------------------------ OHLC bars (for
# ATR / labels / features). Same payload resolution and adjclose-ratio method
# as the primary engine's bars_from_payload, keeping high/low as well.
def load_payload(t):
    for base in (os.path.join(BT, "v7", "long-hold", "data"),
                 os.path.join(BT, "long-run-2010", "data"),
                 os.path.join(BT, "v10-retest", "quality-momentum", "data")):
        p = os.path.join(base, f"pxfull_{t}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            with open(p, "rb") as f:
                return json.loads(f.read())
    raise FileNotFoundError(t)

def ohlc_bars(t):
    j = load_payload(t)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, tt in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(tt))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        h = q["high"][i] * r if q["high"][i] else a
        l = q["low"][i] * r if q["low"][i] else a
        bars.append({"d": d, "o": (o * r if o else a), "h": h, "l": l, "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

def atr_pct_series(bars, period=14):
    """Wilder ATR as fraction of close, one value per bar index (None early)."""
    out = [None] * len(bars)
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return out
    atr = sum(trs[:period]) / period
    out[period] = atr / bars[period]["c"]
    for i in range(period + 1, len(bars)):
        atr = (atr * (period - 1) + trs[i - 1]) / period
        out[i] = atr / bars[i]["c"]
    return out

# ------------------------------------------------------------ selection stream
def selection_stream(pb, quality, start, end):
    """Replicates the engine's scoring exactly; returns per-date picks with
    percentile ranks, plus SPY feature series helpers."""
    sel = qm.cadence_dates(pb, "weekly", start, end)
    stream = []
    for d in sel:
        scores = {}
        for t in UNIVERSE:
            q = qm.quality_at(quality.get(t, []), d)
            if q is None:
                continue
            bl = pb.bars.get(t, [])
            didx = pb.tidx.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (q[2], mom)
        if len(scores) < 5:
            stream.append((d, [], {}))
            continue
        qr = qm.percentile_ranks({t: v[0] for t, v in scores.items()})
        mr = qm.percentile_ranks({t: v[1] for t, v in scores.items()})
        combined = {t: (qr[t] + mr[t]) / 2.0 for t in scores}
        picks = sorted(combined, key=lambda t: -combined[t])[:5]
        stream.append((d, picks, {t: (qr[t], mr[t]) for t in picks}))
    return stream

def build_episodes(stream):
    eps, prev = [], {}
    for d, picks, _ in stream:
        cur = {}
        for t in picks:
            if t in prev:
                cur[t] = prev[t]; cur[t]["last_sel"] = d
                cur[t]["sel_dates"].append(d)
            else:
                cur[t] = {"ticker": t, "entry_sel": d, "last_sel": d,
                          "sel_dates": [d]}
        for t, ep in prev.items():
            if t not in cur:
                eps.append(ep)
        prev = cur
    eps.extend(prev.values())
    eps.sort(key=lambda e: e["entry_sel"])
    for i, e in enumerate(eps):
        e["id"] = i
    return eps

# ------------------------------------------------------------ labels/features
def label_and_features(eps, stream, ohlc, pb):
    ranks = {}
    for d, picks, rk in stream:
        for t, (a, b) in rk.items():
            ranks[(t, d)] = (a, b)
    alldates = pb.dates
    nxt = {}
    for i, d in enumerate(alldates[:-1]):
        nxt[d] = alldates[i + 1]
    spy = ohlc["SPY"]; spy_idx = {b["d"]: i for i, b in enumerate(spy)}
    spy_close = [b["c"] for b in spy]
    for ep in eps:
        t = ep["ticker"]; bars = ohlc[t]; idx = {b["d"]: i for i, b in enumerate(bars)}
        es = ep["entry_sel"]
        ep["features"] = None; ep["label"] = None
        if es not in idx or es not in spy_idx:
            continue
        i0 = idx[es]
        atrp = atr_pct_series(bars)[i0]
        if atrp is None:
            continue
        # features at selection close
        closes = [b["c"] for b in bars]
        sma200 = sum(closes[i0 - 199:i0 + 1]) / 200.0
        si = spy_idx[es]
        spy_sma = sum(spy_close[si - 199:si + 1]) / 200.0
        rets = [spy_close[j] / spy_close[j - 1] - 1.0 for j in range(si - 19, si + 1)]
        rvol = float(np.std(rets, ddof=1))
        qr_, mr_ = ranks[(t, es)]
        ep["features"] = {"qr": qr_, "mr": mr_, "atr_pct": atrp,
                          "dist200": closes[i0] / sma200 - 1.0,
                          "spy_above200": 1.0 if spy_close[si] > spy_sma else 0.0,
                          "spy_rvol20": rvol}
        # execution days
        entry_exec = nxt.get(es)
        # exit selection = first stream date after last_sel not containing t:
        exit_sel = None
        seen_last = False
        for d, picks, _ in stream:
            if d == ep["last_sel"]:
                seen_last = True; continue
            if seen_last:
                exit_sel = d; break
        if entry_exec is None or entry_exec not in idx:
            continue
        ei = idx[entry_exec]; p0 = bars[ei]["o"]
        if exit_sel is None:  # held to window end: liquidate at final close
            path = bars[ei:]
            net = path[-1]["c"] / p0 - 1.0 - 0.0025
            ep["label"] = 1 if net > 0 else 0
            ep["label_end"] = path[-1]["d"]
            ep["exit_exec"] = path[-1]["d"]
            continue
        exit_exec = nxt.get(exit_sel)
        if exit_exec is None or exit_exec not in idx:
            continue
        xi = idx[exit_exec]
        up = p0 * (1 + 1.5 * atrp); dn = p0 * (1 - 1.5 * atrp)
        lab, lend = None, None
        for b in bars[ei:xi]:  # closes, execution day .. day before exit exec
            if b["c"] >= up:
                lab, lend = 1, b["d"]; break
            if b["c"] <= dn:
                lab, lend = 0, b["d"]; break
        if lab is None:
            net = bars[xi]["o"] / p0 - 1.0 - 0.0025
            lab, lend = (1 if net > 0 else 0), exit_exec
        ep["label"] = lab; ep["label_end"] = lend; ep["exit_exec"] = exit_exec
    return [e for e in eps if e["label"] is not None and e["features"]]

# ------------------------------------------------------------ logistic (LdP
# secondary; sklearn-convention L2, C=1.0, intercept unpenalized)
def fit_logistic(X, y, C=1.0):
    mu, sd = X.mean(axis=0), X.std(axis=0); sd[sd == 0] = 1.0
    Xs = (X - mu) / sd
    n, k = Xs.shape
    def obj(w):
        z = w[0] + Xs @ w[1:]
        ll = np.sum(y * z - np.logaddexp(0.0, z))
        pen = 0.5 * np.sum(w[1:] ** 2)
        return -(C * ll - pen) * -1.0 if False else (-ll + pen / C) / n
    def grad(w):
        z = w[0] + Xs @ w[1:]
        p = 1.0 / (1.0 + np.exp(-z))
        g = np.empty(k + 1)
        g[0] = np.sum(p - y) / n
        g[1:] = Xs.T @ (p - y) / n + (w[1:] / C) / n
        return g
    res = minimize(obj, np.zeros(k + 1), jac=grad, method="L-BFGS-B",
                   options={"maxiter": 500})
    return res.x, mu, sd

def predict(model, X):
    w, mu, sd = model
    Xs = (X - mu) / sd
    z = w[0] + Xs @ w[1:]
    return 1.0 / (1.0 + np.exp(-z))

def feats(eps_list):
    return np.array([[e["features"][f] for f in FEATURES] for e in eps_list])

# ------------------------------------------------------------ portfolio engine
# COPY of qm_v10.run_episode / run_v9, verbatim except the marked VETO HOOK.
def run_episode(pb, quality_obs, start, end, start_cash, floor, ladder,
                sel_dates, placebo_rng=None, want_curve=False, blocked=None):
    cash = start_cash
    floor_now = floor
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_close = None
    min_close, min_close_date = None, None
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None
    curve = []

    def portfolio_close(d):
        i = pb.didx[d]
        v = cash
        for t, sh in positions.items():
            c = pb.prev_close[t][i]
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
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    combined = {t: (qr[t] + mr[t]) / 2.0 for t in scores}
                    picks = sorted(combined, key=lambda t: -combined[t])[:5]
                if blocked:  # <<<< VETO HOOK (only change vs the original)
                    picks = [t for t in picks if (t, d) not in blocked]
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        if want_curve:
            curve.append((d, round(v, 4)))
        if min_close is None or v < min_close:
            min_close, min_close_date = v, d
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor_now:
                floor_now = newfloor
        if v <= floor_now and di < len(days) - 1:
            halted = d
            halt_close = v
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
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    if want_curve and curve:
        curve[-1] = (last, round(cash, 4))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_close": None,
            "floor_in_effect": floor_now, "min_close": min_close,
            "min_close_date": min_close_date, "curve": curve}

def run_v9m(pb, quality_obs, start, end, cadence, blocked=None,
            want_curve=False):
    sel_all = qm.cadence_dates(pb, cadence, start, end)
    ep1 = run_episode(pb, quality_obs, start, end, 100.0, 85.0, [],
                      sel_all, want_curve=want_curve, blocked=blocked)
    out = {"episode1": ep1, "episode2": None, "final": ep1["final"],
           "halts": [], "restart": False, "second_halt": False,
           "costs": ep1["costs"], "orders": len(ep1["trades"]),
           "curve": list(ep1["curve"])}
    if ep1["halted"] is None:
        return out
    out["halts"].append({"episode": 1, "signal_date": ep1["halted"],
                         "signal_close": ep1["halt_close"],
                         "floor": ep1["floor_in_effect"],
                         "liquidation_date": ep1["end"],
                         "cash_after": ep1["final"]})
    liq = date.fromisoformat(ep1["end"])
    cash1 = ep1["final"]
    eligible = (liq + timedelta(days=90)).isoformat()
    cands = [d for d in sel_all if d >= eligible]
    if not cands:
        return out
    restart = cands[0]
    out["restart"] = True; out["restart_date"] = restart
    out["restart_balance"] = cash1
    ep2 = run_episode(pb, quality_obs, restart, end, cash1, 0.85 * cash1,
                      [], [d for d in sel_all if d >= restart],
                      want_curve=want_curve, blocked=blocked)
    out["episode2"] = ep2
    out["final"] = ep2["final"]
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
        out["second_halt"] = True
        out["halts"].append({"episode": 2, "signal_date": ep2["halted"],
                             "signal_close": ep2["halt_close"],
                             "floor": ep2["floor_in_effect"],
                             "liquidation_date": ep2["end"],
                             "cash_after": ep2["final"]})
    return out

def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return round(mdd * 100, 2)

def blocked_set(vetoed_eps):
    s = set()
    for e in vetoed_eps:
        for d in e["sel_dates"]:
            s.add((e["ticker"], d))
    return s

# ------------------------------------------------------------ main
def main():
    t0 = time.time()
    quality = qm.load_quality()
    bars_oc = {t: qm.load_bars_full(t) for t in UNIVERSE + ["SPY"]}
    pb = qm.PriceBook(bars_oc)
    ohlc = {t: ohlc_bars(t) for t in UNIVERSE + ["SPY"]}

    # INTEGRITY: copied engine, no vetoes, v10 DECADE window must = 1164.49
    integ = run_v9m(pb, quality, DECADE[0], DECADE[1], "weekly",
                    want_curve=True)
    print(f"INTEGRITY decade weekly primary-alone: ${integ['final']:.2f} "
          f"(expected 1164.49)", flush=True)

    stream = selection_stream(pb, quality, WIN[0], WIN[1])
    eps = build_episodes(stream)
    eps = label_and_features(eps, stream, ohlc, pb)
    print(f"episodes with labels+features: {len(eps)}", flush=True)
    by_year = {}
    for e in eps:
        by_year.setdefault(e["entry_sel"][:4], []).append(e)
    print("episodes by entry year:",
          {y: len(v) for y, v in sorted(by_year.items())}, flush=True)
    base_rate = float(np.mean([e["label"] for e in eps]))
    print(f"overall label base rate (label=1 share): {base_rate:.3f}",
          flush=True)

    # ---- walk-forward: train on labels resolved <= Dec 20 of prior year
    def train_pool(year):
        cut = f"{year - 1}-12-20"
        return [e for e in eps if e["label_end"] <= cut]

    oos_eps = [e for e in eps if OOS[0] <= e["entry_sel"] <= OOS[1]]
    preds = {}          # ep id -> prob (true labels)
    train_sizes = {}
    for Y in range(2022, 2027):
        pool = train_pool(Y)
        train_sizes[Y] = len(pool)
        yr = [e for e in oos_eps if e["entry_sel"][:4] == str(Y)]
        if not yr:
            continue
        model = fit_logistic(feats(pool),
                             np.array([e["label"] for e in pool], float))
        for e, p in zip(yr, predict(model, feats(yr))):
            preds[e["id"]] = float(p)
    print("training pool sizes by OOS year:", train_sizes, flush=True)
    vetoed = [e for e in oos_eps if preds[e["id"]] < 0.5]
    kept = [e for e in oos_eps if preds[e["id"]] >= 0.5]
    print(f"OOS episodes: {len(oos_eps)}  vetoed: {len(vetoed)}  "
          f"kept: {len(kept)}", flush=True)
    print(f"kept win rate: {np.mean([e['label'] for e in kept]):.3f}  "
          f"vetoed win rate: {np.mean([e['label'] for e in vetoed]):.3f}  "
          f"OOS base rate: {np.mean([e['label'] for e in oos_eps]):.3f}",
          flush=True)
    yv = np.array([e["label"] for e in oos_eps], float)
    pv_ = np.array([preds[e["id"]] for e in oos_eps])
    acc = float(np.mean((pv_ >= 0.5) == (yv == 1)))
    # rank AUC
    order = np.argsort(pv_); ranks = np.empty(len(pv_)); ranks[order] = np.arange(1, len(pv_) + 1)
    n1 = yv.sum(); n0 = len(yv) - n1
    auc = float((ranks[yv == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)) if n1 and n0 else None
    print(f"OOS classifier: acc={acc:.3f} AUC={auc}", flush=True)

    veto_by_year = {}
    for e in vetoed:
        veto_by_year[e["entry_sel"][:4]] = veto_by_year.get(e["entry_sel"][:4], 0) + 1

    def run_arm(blocked, start, end):
        r = run_v9m(pb, quality, start, end, "weekly", blocked=blocked,
                    want_curve=True)
        return {"final": round(r["final"], 2), "costs": round(r["costs"], 2),
                "orders": r["orders"], "halts": len(r["halts"]),
                "max_dd_pct": max_dd(r["curve"]), "curve": r["curve"]}

    primary = run_arm(None, OOS[0], OOS[1])
    meta = run_arm(blocked_set(vetoed), OOS[0], OOS[1])
    print(f"PRIMARY-ALONE OOS: ${primary['final']:.2f} DD {primary['max_dd_pct']}%", flush=True)
    print(f"META-VETO OOS:     ${meta['final']:.2f} DD {meta['max_dd_pct']}%", flush=True)

    # ---- placebos: 20 random vetoes at the same per-year rate
    rand_finals = []
    for i in range(20):
        rng = random.Random(20261201 + i)
        rv = []
        for Y in range(2022, 2027):
            yr = [e for e in oos_eps if e["entry_sel"][:4] == str(Y)]
            k = veto_by_year.get(str(Y), 0)
            rv.extend(rng.sample(yr, min(k, len(yr))))
        rand_finals.append(run_arm(blocked_set(rv), OOS[0], OOS[1])["final"])
    print("random-veto finals:", rand_finals, flush=True)

    # ---- shuffled-label control: 5 seeds
    shuf_finals = []
    for s in range(5):
        rng = random.Random(777 + s)
        sv = []
        for Y in range(2022, 2027):
            pool = train_pool(Y)
            labels = [e["label"] for e in pool]
            rng.shuffle(labels)
            yr = [e for e in oos_eps if e["entry_sel"][:4] == str(Y)]
            if not yr:
                continue
            m = fit_logistic(feats(pool), np.array(labels, float))
            for e, p in zip(yr, predict(m, feats(yr))):
                if p < 0.5:
                    sv.append(e)
        shuf_finals.append(run_arm(blocked_set(sv), OOS[0], OOS[1])["final"])
    print("shuffled-label finals:", shuf_finals, flush=True)

    # ---- confirmation: two independent fresh-$100 sub-windows
    conf = {}
    for name, (cs, ce) in {"2022-2023": ("2022-01-01", "2023-12-31"),
                           "2024-2026": ("2024-01-01", "2026-11-20")}.items():
        sub_v = [e for e in vetoed if cs <= e["entry_sel"] <= ce]
        conf[name] = {"primary": run_arm(None, cs, ce),
                      "meta": run_arm(blocked_set(sub_v), cs, ce)}
        print(f"CONF {name}: primary ${conf[name]['primary']['final']:.2f} "
              f"meta ${conf[name]['meta']['final']:.2f}", flush=True)

    # ---- primary-alone over the full extended window (record)
    full_primary = run_arm(None, WIN[0], WIN[1])
    print(f"PRIMARY-ALONE full 2013-2026: ${full_primary['final']:.2f}", flush=True)

    results = {
        "family": "meta-labeling",
        "form": "CONSTRUCTED pairing: LdP meta-labeling (triple-barrier, logistic secondary, purged walk-forward, veto-only p<0.5) over quality-momentum weekly primary, window extended 2013-2026",
        "integrity_decade_primary_alone": round(integ["final"], 2),
        "integrity_expected": 1164.49,
        "episodes_total": len(eps),
        "episodes_by_entry_year": {y: len(v) for y, v in sorted(by_year.items())},
        "label_base_rate_all": round(base_rate, 4),
        "train_pool_sizes": train_sizes,
        "oos_window": list(OOS),
        "oos_episodes": len(oos_eps),
        "oos_vetoed": len(vetoed), "oos_kept": len(kept),
        "veto_by_year": veto_by_year,
        "kept_win_rate": round(float(np.mean([e['label'] for e in kept])), 4) if kept else None,
        "vetoed_win_rate": round(float(np.mean([e['label'] for e in vetoed])), 4) if vetoed else None,
        "oos_classifier": {"accuracy": round(acc, 4), "auc": round(auc, 4) if auc else None},
        "primary_alone_oos": {k: primary[k] for k in ("final", "costs", "orders", "halts", "max_dd_pct")},
        "meta_veto_oos": {k: meta[k] for k in ("final", "costs", "orders", "halts", "max_dd_pct")},
        "random_veto_finals": rand_finals,
        "shuffled_label_finals": shuf_finals,
        "confirmation": {k: {"primary_final": v["primary"]["final"],
                             "meta_final": v["meta"]["final"]} for k, v in conf.items()},
        "primary_alone_full_window": {k: full_primary[k] for k in ("final", "costs", "orders", "halts", "max_dd_pct")},
        "equity_curves": {"primary_alone_oos": primary["curve"],
                          "meta_veto_oos": meta["curve"]},
        "episodes": [{"id": e["id"], "ticker": e["ticker"],
                      "entry_sel": e["entry_sel"], "last_sel": e["last_sel"],
                      "exit_exec": e["exit_exec"], "label": e["label"],
                      "label_end": e["label_end"],
                      "features": {k: round(v, 5) for k, v in e["features"].items()},
                      "oos_prob": (round(preds[e["id"]], 4) if e["id"] in preds else None)}
                     for e in eps],
        "runtime_sec": round(time.time() - t0, 1),
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
