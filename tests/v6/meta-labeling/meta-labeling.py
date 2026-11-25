#!/usr/bin/env python3
"""
META-LABELING ON VALUE+MOMENTUM — Terry's AI stock app. Simulation only.

Per the program's ML feasibility study (~/workspace/stock-app/research/
ml-feasibility.md, section 4): meta-labeling is the ONE ML build judged
feasible — a secondary classifier that never picks direction; it only
learns "when the proven primary fires, did taking the pick pay?" and
vetoes picks it scores as likely losers. This test follows the study's
constraints and Terry's standing rules (frozen spec, run once, honest
placebo, no tuning after seeing results).

PRIMARY (champion, verbatim): value+momentum from
~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py —
quarterly top-5, book-to-market + 12-1 momentum percentile-rank average,
honest point-in-time top-30 universe, EDGAR facts filed strictly before
each selection date, costs 0.10%/side + $0.01/sell, $100 pot, plain -15%
floor ($85), no ladder. The champion engine module is IMPORTED and its
run_pot used for the baseline; the meta run uses a copy of run_pot with
exactly one added hook (a veto function consulted at each selection).
Integrity gate: the copy with the hook disabled must reproduce the
champion's validation final to the cent before any meta number is taken.

META-MODEL (frozen spec, written before any results):
  Model: scikit-learn LogisticRegression(C=1.0, L2, lbfgs, max_iter=1000)
         on StandardScaler-standardized features. Threshold 0.5, fixed.
  FEATURES (all knowable at the selection date d, per pick) — FINAL LIST:
    1. value_rank      pick's B/M percentile rank in the scored pool
    2. mom_rank        pick's 12-1 momentum percentile rank in the pool
    3. combined_rank   (value_rank + mom_rank) / 2  (the champion's score)
    4. pick_vol63      pick's trailing 63-trading-day realized vol
                       (std of daily log returns x sqrt(252)), ending at d
    5. spy_vol63       SPY's trailing 63-day realized vol, ending at d
    6. spy_above_200dma  1 if SPY close at d > its trailing 200-day mean
                       close (incl. d), else 0
  LABEL: 1 if the pick's net return over its holding period beats SPY's
         net return over the identical span, else 0. Holding period =
         buy at the open of the first bar after selection date d, exit at
         the open of the first bar after the NEXT quarterly selection
         date (exactly when the champion's rebalance would sell it).
         Net = gross x (1 - 0.0015) / (1 + 0.001): 0.10% buy cost, 0.10%
         sell cost + $0.01 per $20 notional (0.05%), applied symmetrically
         to the pick and to SPY.
  TRAINING SET: primary picks at quarterly selections in 2016-2022 whose
         label exit date is < 2023-01-03 — i.e. selections 2016Q1..2022Q3.
         STRICT LEAKAGE RULE: no validation-era (2023+) price, feature, or
         label is used in training, and the 0.5 threshold is pre-set, not
         chosen on any era. Design-era (2016-2022) selections need price
         history from 2014; those bars are fetched fresh (same Yahoo
         adjusted method as the champion) into THIS folder's cache and
         used ONLY for training-event extraction — every portfolio run
         (baseline, meta, placebo) uses the champion's own caches.
  APPLICATION: at each validation-era selection (2023-01-03..2026-11-20),
         picks scored p < 0.5 are VETOED: their share of the pot stays in
         cash (NOT redistributed to other stocks). A held name that is
         vetoed is sold by the engine's normal rebalance mechanics.
  PLACEBO (per task spec): 20 seeds; each placebo run vetoes every pick
         independently with probability = the meta run's realized veto
         rate (same fraction of trades skipped, chosen at random) — the
         feasibility study's "random filter" control: if random skipping
         captures the gain, the model learned "trade less," not "which."
  DIAGNOSTIC (extra, labeled as such): shuffled-label model — identical
         pipeline trained on permuted training labels (seed 42); if it
         also "improves" validation, the pipeline leaks.

Judged against: champion validation final $288.05 and the champion's
placebo standing (18/20 on validation in the v4 walk-forward study).
"""
import importlib.util
import json
import math
import os
import random
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
OWN_DATA = os.path.join(HERE, "data")
os.makedirs(OWN_DATA, exist_ok=True)

sys.path.insert(0, os.path.join(HERE, "venv", "lib"))

# ------------------------------------------------------------ champion import
spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
VAL = ("2023-01-03", "2026-11-20")
FULL = ("2019-01-02", "2026-11-20")
FEATURES = ["value_rank", "mom_rank", "combined_rank",
            "pick_vol63", "spy_vol63", "spy_above_200dma"]
THRESHOLD = 0.5

# ------------------------------------------------------------ champion inputs
def build_inputs():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in E.UNIVERSE:
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
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        time.sleep(0.05)
    bars = {}
    for t in E.UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return E.PriceBook(bars), equity_rows, shares_rows

# --------------------------------------- extended prices (training era only)
def fetch_long(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            with open(path, "wb") as f:
                f.write(blob)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")

def get_prices_long(ticker, p1="2014-06-01", p2="2026-11-21"):
    """Champion's get_prices method verbatim, longer window, own cache."""
    import calendar
    path = os.path.join(OWN_DATA, f"pxlong_{ticker}.json")
    t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    blob = fetch_long(url, path)
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

# ------------------------------------------------------------ feature helpers
def _idx_on_or_before(bars, d):
    lo, hi, ans = 0, len(bars) - 1, -1
    while lo <= hi:
        mid = (lo + hi) // 2
        if bars[mid]["d"] <= d:
            ans = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return ans

def realized_vol(bars, d, n=63):
    i = _idx_on_or_before(bars, d)
    if i < n:
        return None
    rets = []
    for k in range(i - n + 1, i + 1):
        c0, c1 = bars[k - 1]["c"], bars[k]["c"]
        if c0 and c1 and c0 > 0 and c1 > 0:
            rets.append(math.log(c1 / c0))
    if len(rets) < n - 2:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)

def spy_state(pb, d):
    bars = pb.bars.get("SPY", [])
    i = _idx_on_or_before(bars, d)
    if i < 200:
        return None
    vol = realized_vol(bars, d)
    if vol is None:
        return None
    ma200 = sum(b["c"] for b in bars[i - 199:i + 1]) / 200.0
    above = 1 if bars[i]["c"] > ma200 else 0
    return vol, above

def pick_features(pb, t, d, vr_t, mr_t, sstate):
    bars = pb.bars.get(t, [])
    vol = realized_vol(bars, d)
    if vol is None or sstate is None:
        return None
    spy_vol, spy_above = sstate
    return {"value_rank": vr_t, "mom_rank": mr_t,
            "combined_rank": (vr_t + mr_t) / 2.0,
            "pick_vol63": vol, "spy_vol63": spy_vol,
            "spy_above_200dma": float(spy_above)}

# --------------------------------------------- champion scoring (verbatim logic)
def score_pool(pb, equity_rows, shares_rows, d):
    """Replicates the champion run_pot selection block exactly.
    Returns (scores, vr, mr) or (None, None, None) if pool < 5."""
    scores = {}
    for t in E.UNIVERSE:
        be = E.pit_value(equity_rows.get(t, []), d)
        so = E.pit_value(shares_rows.get(t, []), d)
        px = pb.close_on_or_before(t, d)
        if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
            continue
        mcap = so[2] * px
        if mcap <= 0:
            continue
        bm = be[2] / mcap
        bl = pb.bars.get(t, [])
        didx = None
        for i, b in enumerate(bl):
            if b["d"] == d:
                didx = i
                break
        if didx is None or didx < 253:
            continue
        mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
        scores[t] = (bm, mom)
    if len(scores) < 5:
        return None, None, None
    vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
    mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
    return scores, vr, mr

def net_ret(buy_px, sell_px):
    return (sell_px / buy_px) * (1 - 0.0015) / (1 + 0.001) - 1.0

# ------------------------------------------------------- training extraction
def extract_training_events(xpb, equity_rows, shares_rows):
    """Design-era events: selections 2016Q1..2022Q4 on the extended book;
    an event is kept only if its label exit date is < 2023-01-03."""
    sel_all = E.quarter_selection_dates(xpb, "2016-01-01", "2026-11-20")
    events, dropped = [], 0
    for si, d in enumerate(sel_all):
        if d > "2022-12-31":
            break
        if si + 1 >= len(sel_all):
            dropped += 5
            continue
        d2 = sel_all[si + 1]
        scores, vr, mr = score_pool(xpb, equity_rows, shares_rows, d)
        if scores is None:
            dropped += 5
            continue
        combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
        picks = sorted(combined, key=lambda t: -combined[t])[:5]
        sstate = spy_state(xpb, d)
        for t in picks:
            bd, bo = xpb.next_open(t, d)
            sd, sp = xpb.next_open(t, d2)
            if bd is None or sd is None or sd >= "2023-01-03":
                dropped += 1
                continue
            sb = xpb.bar("SPY", bd)
            ss = xpb.bar("SPY", sd)
            if not sb or not ss:
                dropped += 1
                continue
            feats = pick_features(xpb, t, d, vr[t], mr[t], sstate)
            if feats is None:
                dropped += 1
                continue
            r_pick = net_ret(bo, sp)
            r_spy = net_ret(sb["o"], ss["o"])
            events.append({"sel_date": d, "exit_date": sd, "ticker": t,
                           "features": feats,
                           "pick_net_ret": round(r_pick, 6),
                           "spy_net_ret": round(r_spy, 6),
                           "label": 1 if r_pick > r_spy else 0})
    return events, dropped

# ------------------------------- champion run_pot copy + ONE hook (the veto)
def run_pot_meta(pb, equity_rows, shares_rows, start, end, start_cash,
                 floor0, ladder, veto_fn=None, label="", sel_log=None):
    """Byte-for-byte the champion's run_pot mechanics with a single added
    hook: after picks are computed at a selection, veto_fn(d, picks,
    scores, vr, mr) may return a reduced pick list. Vetoed picks are
    simply absent from targets — their cash share is never redistributed.
    With veto_fn=None this must reproduce the champion exactly."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    sel_dates = E.quarter_selection_dates(pb, start, end)
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
            scores = {}
            for t in E.UNIVERSE:
                be = E.pit_value(equity_rows.get(t, []), d)
                so = E.pit_value(shares_rows.get(t, []), d)
                px = pb.close_on_or_before(t, d)
                if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
                    continue
                mcap = so[2] * px
                if mcap <= 0:
                    continue
                bm = be[2] / mcap
                bl = pb.bars.get(t, [])
                didx = None
                for i, b in enumerate(bl):
                    if b["d"] == d:
                        didx = i
                        break
                if didx is None or didx < 253:
                    continue
                mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
                scores[t] = (bm, mom)
            if len(scores) >= 5:
                vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
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
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor:
                floor = newfloor
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
                    "halt_info": halt_info, "pools": [], "curve": curve}
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
            "halt_info": None, "pools": [], "curve": curve}

def curve_stats(r):
    curve = r["curve"]
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd = dd
    return {"final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted": r["halted"],
            "max_drawdown_pct": round(maxdd * 100, 2),
            "worst_close": round(min(v for _, v in curve), 2)}

# --------------------------------------------------------------------- main
def main():
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import roc_auc_score

    out = {"test": "meta-labeling on value+momentum (champion, plain floor)",
           "spec": {"features": FEATURES, "threshold": THRESHOLD,
                    "model": "LogisticRegression(C=1.0, L2, lbfgs) on standardized features",
                    "training_rule": "selections 2016Q1..2022Q3 with label exit < 2023-01-03",
                    "veto_action": "vetoed pick's pot share stays in cash"}}

    pb, equity_rows, shares_rows = build_inputs()
    print("champion inputs built", flush=True)

    # ---- integrity 1: champion engine verbatim
    base_val = E.run_pot(pb, equity_rows, shares_rows, VAL[0], VAL[1],
                         START_CASH, FLOOR0, LADDER, label="BASE-VAL", quiet=True)
    base_full = E.run_pot(pb, equity_rows, shares_rows, FULL[0], FULL[1],
                          START_CASH, FLOOR0, LADDER, label="BASE-FULL", quiet=True)
    spy_val, _ = E.spy_net(pb, VAL[0], VAL[1], START_CASH)
    out["champion_baseline"] = {
        "validation": curve_stats(base_val), "full": curve_stats(base_full),
        "spy_validation_final": round(spy_val, 2),
        "published_validation": 288.05, "published_full": 544.47}
    print(f"CHAMPION validation=${base_val['final']:,.2f} (published $288.05) "
          f"full=${base_full['final']:,.2f} (published $544.47) "
          f"SPY val=${spy_val:,.2f}", flush=True)

    # ---- integrity 2: copied engine, hook disabled
    copy_val = run_pot_meta(pb, equity_rows, shares_rows, VAL[0], VAL[1],
                            START_CASH, FLOOR0, LADDER, veto_fn=None,
                            label="COPY-NOHOOK")
    out["copy_integrity"] = {"validation_final": round(copy_val["final"], 2),
                             "matches_champion": round(copy_val["final"], 2) == round(base_val["final"], 2)}
    print(f"COPY no-hook validation=${copy_val['final']:,.2f} "
          f"match={out['copy_integrity']['matches_champion']}", flush=True)
    assert out["copy_integrity"]["matches_champion"], "copied engine diverges!"

    # ---- training events (extended book, design era only)
    xbars = {}
    for t in E.UNIVERSE + ["SPY"]:
        xbars[t] = get_prices_long(t)
        time.sleep(0.1)
    xpb = E.PriceBook(xbars)
    events, dropped = extract_training_events(xpb, equity_rows, shares_rows)
    n = len(events)
    base_rate = sum(e["label"] for e in events) / n if n else None
    out["training_set"] = {"events": n, "dropped": dropped,
                           "base_rate_beat_spy": round(base_rate, 4) if base_rate is not None else None,
                           "sel_dates": sorted({e["sel_date"] for e in events}),
                           "events_csv": "meta-labeling-events.csv"}
    with open(os.path.join(HERE, "meta-labeling-events.csv"), "w") as f:
        f.write("sel_date,exit_date,ticker," + ",".join(FEATURES) + ",pick_net_ret,spy_net_ret,label\n")
        for e in events:
            f.write(",".join([e["sel_date"], e["exit_date"], e["ticker"]] +
                             [f"{e['features'][k]:.6f}" for k in FEATURES] +
                             [f"{e['pick_net_ret']:.6f}", f"{e['spy_net_ret']:.6f}",
                              str(e["label"])]) + "\n")
    print(f"TRAINING events={n} dropped={dropped} base_rate={base_rate:.3f} "
          f"selections={len(out['training_set']['sel_dates'])}", flush=True)

    import numpy as np
    X = np.array([[e["features"][k] for k in FEATURES] for e in events], dtype=float)
    y = np.array([e["label"] for e in events], dtype=int)

    def train(Xtr, ytr):
        scaler = StandardScaler()
        Xs = scaler.fit_transform(Xtr)
        clf = LogisticRegression(C=1.0, max_iter=1000)
        clf.fit(Xs, ytr)
        return scaler, clf

    scaler, clf = train(X, y)
    p_in = clf.predict_proba(scaler.transform(X))[:, 1]
    pred_in = (p_in >= THRESHOLD).astype(int)
    acc_in = float((pred_in == y).mean())
    auc_in = float(roc_auc_score(y, p_in)) if len(set(y.tolist())) > 1 else None
    out["design_era_fit_IN_SAMPLE"] = {
        "note": "IN-SAMPLE fit on the training events themselves — NOT evidence of edge",
        "accuracy": round(acc_in, 4), "auc": round(auc_in, 4) if auc_in else None,
        "coefficients": {k: round(float(c), 4) for k, c in zip(FEATURES, clf.coef_[0])},
        "intercept": round(float(clf.intercept_[0]), 4),
        "in_sample_veto_rate": round(float((p_in < THRESHOLD).mean()), 4)}
    print(f"IN-SAMPLE fit: acc={acc_in:.3f} auc={auc_in:.3f} "
          f"coefs={out['design_era_fit_IN_SAMPLE']['coefficients']}", flush=True)

    # ---- veto functions (features from the CHAMPION book at run time)
    def make_model_veto(scaler_, clf_):
        def veto(d, picks, scores, vr, mr):
            sstate = spy_state(pb, d)
            kept = []
            for t in picks:
                feats = pick_features(pb, t, d, vr[t], mr[t], sstate)
                if feats is None:
                    kept.append(t)  # cannot score -> do not veto
                    continue
                x = np.array([[feats[k] for k in FEATURES]], dtype=float)
                p = float(clf_.predict_proba(scaler_.transform(x))[0, 1])
                veto.probs.append({"date": d, "ticker": t, "p_beat_spy": round(p, 4),
                                   "vetoed": bool(p < THRESHOLD)})
                if p >= THRESHOLD:
                    kept.append(t)
            return kept
        veto.probs = []
        return veto

    # ---- meta run (the judgment run)
    meta_log = []
    model_veto = make_model_veto(scaler, clf)
    meta = run_pot_meta(pb, equity_rows, shares_rows, VAL[0], VAL[1],
                        START_CASH, FLOOR0, LADDER, veto_fn=model_veto,
                        label="META", sel_log=meta_log)
    n_pick_events = sum(len(s["picks"]) for s in meta_log)
    n_vetoes = sum(len(s["vetoed"]) for s in meta_log)
    veto_rate = n_vetoes / n_pick_events if n_pick_events else 0.0
    out["meta_run"] = {"stats": curve_stats(meta),
                       "selections": len(meta_log),
                       "pick_events": n_pick_events, "vetoes": n_vetoes,
                       "veto_rate": round(veto_rate, 4),
                       "pick_scores": model_veto.probs,
                       "selection_log": meta_log}
    print(f"META validation=${meta['final']:,.2f} vetoes={n_vetoes}/{n_pick_events} "
          f"rate={veto_rate:.3f} halted={meta['halted']}", flush=True)

    # ---- autopsy: what did the vetoed picks actually do?
    sel_dates_val = E.quarter_selection_dates(pb, VAL[0], VAL[1])
    autopsy = []
    for s in meta_log:
        d = s["date"]
        si = sel_dates_val.index(d) if d in sel_dates_val else -1
        for t in s["vetoed"]:
            bd, bo = pb.next_open(t, d)
            if si >= 0 and si + 1 < len(sel_dates_val):
                sd, sp = pb.next_open(t, sel_dates_val[si + 1])
                exit_kind = "next-selection open"
            else:
                sd = VAL[1]
                sp = pb.close_on_or_before(t, VAL[1])
                exit_kind = "window-end close"
            if bd is None or sp is None:
                continue
            sb = pb.bar("SPY", bd)
            ss = pb.bar("SPY", sd) if exit_kind == "next-selection open" else None
            spy_exit = ss["o"] if ss else pb.close_on_or_before("SPY", VAL[1])
            if not sb or spy_exit is None:
                continue
            r_pick = net_ret(bo, sp)
            r_spy = net_ret(sb["o"], spy_exit)
            autopsy.append({"date": d, "ticker": t,
                            "pick_net_ret": round(r_pick, 4),
                            "spy_net_ret": round(r_spy, 4),
                            "veto_correct": bool(r_pick <= r_spy)})
    out["veto_autopsy"] = autopsy
    if autopsy:
        print(f"AUTOPSY vetoed picks: {sum(a['veto_correct'] for a in autopsy)}/"
              f"{len(autopsy)} actually trailed SPY", flush=True)

    # ---- placebo: random vetoes at the same rate, 20 seeds
    placebo_finals = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        def rand_veto(d, picks, scores, vr, mr, rng=rng):
            return [t for t in picks if rng.random() >= veto_rate]
        pr = run_pot_meta(pb, equity_rows, shares_rows, VAL[0], VAL[1],
                          START_CASH, FLOOR0, LADDER, veto_fn=rand_veto,
                          label=f"PLACEBO {seed}")
        placebo_finals.append(round(pr["final"], 2))
        print(f"PLACEBO seed {seed:2d}: final=${pr['final']:,.2f} halted={pr['halted']}", flush=True)
    srt = sorted(placebo_finals)
    meta_final = round(meta["final"], 2)
    beaten = sum(1 for f in placebo_finals if f < meta_final)
    out["placebo_random_veto"] = {
        "seeds": list(range(1, 21)), "finals": placebo_finals,
        "median": round(E._pct(srt, 0.50), 2), "q1": round(E._pct(srt, 0.25), 2),
        "q3": round(E._pct(srt, 0.75), 2), "best": srt[-1], "worst": srt[0],
        "meta_final": meta_final, "meta_beats_seeds": beaten,
        "veto_rate_used": round(veto_rate, 4)}
    print(f"PLACEBO median=${out['placebo_random_veto']['median']:,.2f} | "
          f"META ${meta_final:,.2f} beats {beaten}/20 seeds", flush=True)

    # ---- diagnostic: shuffled-label model (pipeline leak check)
    rng_shuf = random.Random(42)
    y_shuf = y.copy()
    rng_shuf.shuffle(y_shuf)
    scaler_s, clf_s = train(X, y_shuf)
    shuf_veto = make_model_veto(scaler_s, clf_s)
    shuf_log = []
    shuf = run_pot_meta(pb, equity_rows, shares_rows, VAL[0], VAL[1],
                        START_CASH, FLOOR0, LADDER, veto_fn=shuf_veto,
                        label="SHUFFLED", sel_log=shuf_log)
    out["shuffled_label_diagnostic"] = {
        "note": "DIAGNOSTIC ONLY — model trained on permuted labels; any 'improvement' here indicates pipeline leakage, not edge",
        "stats": curve_stats(shuf),
        "vetoes": sum(len(s["vetoed"]) for s in shuf_log)}
    print(f"SHUFFLED-LABEL diagnostic validation=${shuf['final']:,.2f}", flush=True)

    with open(os.path.join(HERE, "meta-labeling-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
