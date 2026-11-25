#!/usr/bin/env python3
# V13 BEST RULES - N-F1 "THE SLOW FILER" - exclusion form.
# Spec frozen in BEST-RULES-SPEC.md before this run.
# Structural change vs v8: signal used ONLY as an exclusion (acute
# dLAG >= +6, or persistent dLAG >= +2 in two consecutive filings, or
# NT filing); hold every other eligible name equal weight; NO floor.
# Roads: DECADE 2016-11-21, CONT 2019-01-02, VAL 2023-01-03, all to
# 2026-11-20. LONG is not an honest road for this family (Nov-2016 pond).
# Costs 0.10%/side + $0.01 per sell order. $100 pots. 20-seed placebos:
# random sample of the SAME SIZE as the held book from the same pool.
import importlib.util, json, math, os, random, sys, time, urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
sys.path.insert(0, os.path.join(BT, "long-run-2010"))
import lr_common as C

_spec = importlib.util.spec_from_file_location(
    "nf1_v8", os.path.join(BT, "v8", "novel-f1-slow-filer", "novel-f1-slow-filer.py"))
nf1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nf1)

UNIVERSE = nf1.UNIVERSE
ROADS = [("DECADE", "2016-11-21", "2026-11-20"),
         ("CONT", "2019-01-02", "2026-11-20"),
         ("VAL", "2023-01-03", "2026-11-20")]
SEEDS = list(range(1, 21))
LH_DATA = os.path.join(BT, "v7", "long-hold", "data")


def payload_for(t):
    lh = os.path.join(LH_DATA, "pxfull_%s.json" % t)
    if os.path.exists(lh) and os.path.getsize(lh) > 100:
        with open(lh, "rb") as f:
            return json.loads(f.read())
    mine = os.path.join(HERE, "pxfull_%s.json" % t)
    if os.path.exists(mine) and os.path.getsize(mine) > 100:
        with open(mine, "rb") as f:
            return json.loads(f.read())
    import calendar
    t1 = calendar.timegm(time.strptime("2008-01-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
           "?period1=%d&period2=%d&interval=1d&events=div,split" % (t, t1, t2))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        blob = r.read()
    with open(mine, "wb") as f:
        f.write(blob)
    return json.loads(blob)


def dparse(s):
    return date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def lag_of(filing):
    return (dparse(filing["acc_d"]) - dparse(filing["period"])).days


def yoy_dlag(target_filing, prior_list):
    """dLAG for one filing vs its same-form 320-410-day match (v8 rule)."""
    if not target_filing["period"]:
        return None
    target = dparse(target_filing["period"]) - timedelta(days=365)
    cands = []
    for r in prior_list:
        if r["form"] != target_filing["form"] or r is target_filing or not r["period"]:
            continue
        gap = (dparse(target_filing["period"]) - dparse(r["period"])).days
        if 320 <= gap <= 410:
            cands.append(r)
    if not cands:
        return None
    cands.sort(key=lambda r: (abs((dparse(r["period"]) - target).days), r["acc"]))
    return lag_of(target_filing) - lag_of(cands[0])


def build_pools(filings_by_ticker, sel_dates):
    """pools[sd] = {eligible:[...], held:[...], excluded:{t:reason},
    detail:{t:{dlag_now,dlag_prev}}} implementing the frozen v13 spec."""
    prep = {}
    for t in UNIVERSE:
        periodic, nts = [], []
        for r in filings_by_ticker[t]:
            if not r["acceptance"]:
                continue
            if r["form"] in nf1.PERIODIC_FORMS:
                periodic.append({"form": r["form"], "acc": r["acceptance"],
                                 "acc_d": r["acceptance"][:10],
                                 "period": r["period"], "accession": r["accession"]})
            elif r["form"] in nf1.NT_FORMS:
                nts.append(r["acceptance"][:10])
        periodic.sort(key=lambda r: (r["acc"], r["accession"]))
        prep[t] = (periodic, nts)
    pools = {}
    for sd in sel_dates:
        sdate = dparse(sd)
        eligible, held, excluded, detail = [], [], {}, {}
        for t in UNIVERSE:
            periodic, nts = prep[t]
            if any(1 <= (sdate - dparse(a)).days <= 365 for a in nts):
                excluded[t] = "NT"
                continue
            prior = [r for r in periodic if r["acc_d"] < sd]
            if not prior:
                continue
            now = prior[-1]
            if (sdate - dparse(now["acc_d"])).days > 200 or not now["period"]:
                continue
            d_now = yoy_dlag(now, prior)
            if d_now is None:
                continue
            d_prev = None
            if len(prior) >= 2:
                d_prev = yoy_dlag(prior[-2], prior)
            eligible.append(t)
            detail[t] = {"dlag_now": d_now, "dlag_prev": d_prev}
            if d_now >= 6:
                excluded[t] = "acute"
            elif d_now >= 2 and d_prev is not None and d_prev >= 2:
                excluded[t] = "persistent"
            else:
                held.append(t)
        pools[sd] = {"eligible": eligible, "held": held,
                     "excluded": excluded, "detail": detail}
    return pools


def quarter_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end and d[5:7] in ("01", "04", "07", "10"):
            key = (d[:4], d[5:7])
            if key not in seen:
                seen.add(key)
                out.append(d)
    return out


def run_pot(pb, pools, start, end, rng=None):
    cash, positions, trades, total_costs, curve, pools_log = 100.0, {}, [], 0.0, [], []
    sel = quarter_dates(pb, start, end)
    sel_set = set(sel)
    days = [d for d in pb.dates if start <= d <= end]
    pending = None

    def pclose(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute(d, targets):
        nonlocal cash, total_costs
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        for t in list(positions):
            if t not in opens:
                continue
            cur = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur > tgt + 0.005:
                sv = cur - tgt
                sh = sv / opens[t]
                c = sv * 0.001 + 0.01
                cash += sv - c
                total_costs += c
                positions[t] -= sh
                trades.append((d, t, "SELL", round(sv, 2), round(c, 2)))
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur = positions.get(t, 0.0) * opens[t]
            bv = tgt - cur
            if bv > 0.005:
                bv = min(bv, cash / 1.001)
                if bv <= 0.005:
                    continue
                sh = bv / opens[t]
                c = bv * 0.001
                cash -= bv + c
                total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", round(bv, 2), round(c, 2)))

    for d in days:
        if pending is not None:
            execute(d, pending)
            pending = None
        if d in sel_set:
            p = pools.get(d)
            if p and p["eligible"]:
                if rng is not None:
                    picks = rng.sample(sorted(p["eligible"]), len(p["held"]))
                else:
                    picks = list(p["held"])
                if picks:
                    pools_log.append((d, list(p["eligible"]), list(picks),
                                      dict(p["excluded"])))
                    pv = pclose(d)
                    each = pv / len(picks)
                    pending = {t: each for t in picks}
        curve.append((d, pclose(d)))
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", round(val, 2), round(cst, 2)))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "curve": curve, "pools": pools_log}


def diagnostics(curve):
    peak, maxdd, maxdd_d, worst_d, worst_v = -1.0, 0.0, None, None, 1e18
    last_high_i, longest_gap, cur_gap = 0, 0, 0
    for i, (d, v) in enumerate(curve):
        if v > peak:
            peak = v
            last_high_i = i
            cur_gap = 0
        else:
            cur_gap = i - last_high_i
            longest_gap = max(longest_gap, cur_gap)
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
        if v < worst_v:
            worst_v, worst_d = v, d
    return {"max_dd_pct": round(maxdd * 100, 2), "max_dd_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "longest_no_new_high_days": longest_gap}


def period_distribution(curve, sel_dates):
    pts = [(d, v) for d, v in curve]
    bounds = [pts[0]] + [(d, dict(pts)[d]) for d in sel_dates if d in dict(pts) and d != pts[0][0]] + [pts[-1]]
    bounds = sorted(set(bounds))
    changes = [round(bounds[i + 1][1] - bounds[i][1], 2) for i in range(len(bounds) - 1)]
    if not changes:
        return {}
    s = sorted(changes)
    n = len(s)
    med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0
    streak = cur = 0
    for c_ in changes:
        cur = cur + 1 if c_ < 0 else 0
        streak = max(streak, cur)
    return {"periods": n, "median_change": round(med, 2),
            "pct_positive": round(100.0 * sum(1 for c_ in changes if c_ > 0) / n, 1),
            "best": max(changes), "worst": min(changes),
            "longest_losing_streak": streak,
            "avg_change_secondary": round(sum(changes) / n, 2)}


def pct(sorted_vals, q):
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    return sorted_vals[lo] if lo == hi else sorted_vals[lo] * (1 - (pos - lo)) + sorted_vals[hi] * (pos - lo)


def main():
    ciks = nf1.get_ciks()
    filings = {}
    for t in UNIVERSE:
        filings[t] = nf1.get_filing_index(nf1.CIK_OVERRIDES.get(t, ciks[t][0]))
    print("filings loaded", flush=True)

    # ---- INTEGRITY: original v8 engine reproduces its published finals
    bars0 = {t: nf1.get_prices(t) for t in UNIVERSE + ["SPY"]}
    pb0 = nf1.PriceBook(bars0)
    s_cont, _ = nf1.spy_net(pb0, "2019-01-02", "2026-11-20", 100.0)
    s_val, _ = nf1.spy_net(pb0, "2023-01-03", "2026-11-20", 100.0)
    assert abs(s_cont - 313.62) < 0.02 and abs(s_val - 187.77) < 0.02, "SPY integrity FAILED"
    sel0 = nf1.quarter_selection_dates(pb0, "2019-01-01", "2026-11-20")
    pools0, _ = nf1.build_pools(filings, sel0)
    integ = {}
    for name, ws, we, pub in (("CONT", "2019-01-02", "2026-11-20", 332.79),
                              ("VAL", "2023-01-03", "2026-11-20", 189.47)):
        r = nf1.run_pot(pb0, pools0, ws, we, 100.0, 85.0, label="INTEG " + name)
        integ[name] = round(r["final"], 2)
        print("INTEGRITY %s $%.2f (pub %.2f)" % (name, r["final"], pub), flush=True)
        assert abs(r["final"] - pub) < 0.02, "integrity FAILED " + name

    # ---- v13 prices (full-range pxfull cache, read-only)
    bars = {t: C.bars_adj(payload_for(t)) for t in UNIVERSE + ["SPY"]}
    pb = C.FastPriceBook(bars)
    all_sel = quarter_dates(pb, "2016-11-21", "2026-11-20")
    pools = build_pools(filings, all_sel)
    held_counts = [len(pools[d]["held"]) for d in all_sel]
    excl_counts = [len(pools[d]["excluded"]) for d in all_sel]
    print("held count min/max %d/%d ; excluded min/max %d/%d" %
          (min(held_counts), max(held_counts), min(excl_counts), max(excl_counts)), flush=True)

    out = {"family": "novel-f1-slow-filer", "form": "v13 exclusion (acute>=6 / persistent>=2+>=2 / NT), no floor",
           "integrity": {"spy_cont": round(s_cont, 2), "spy_val": round(s_val, 2),
                         "original_cont": integ["CONT"], "original_val": integ["VAL"]},
           "held_count_range": [min(held_counts), max(held_counts)],
           "excluded_count_range": [min(excl_counts), max(excl_counts)], "roads": {}}
    champ = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
    pub = {"DECADE": 364.80, "CONT": 332.79, "VAL": 189.47}
    for name, ws, we in ROADS:
        spy, _ = C.champ.spy_net(pb, ws, we, 100.0)
        r = run_pot(pb, pools, ws, we)
        diag = diagnostics(r["curve"])
        pdist = period_distribution(r["curve"], quarter_dates(pb, ws, we))
        pfinals = []
        for seed in SEEDS:
            pr = run_pot(pb, pools, ws, we, rng=random.Random(seed))
            pfinals.append(round(pr["final"], 2))
        beat = sum(1 for f in pfinals if f < r["final"])
        srt = sorted(pfinals)
        out["roads"][name] = {
            "window": [ws, we], "final": round(r["final"], 2),
            "spy": round(spy, 2), "champion_vm": champ[name], "published_form": pub[name],
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "diag": diag, "period_distribution": pdist,
            "placebo": {"finals": pfinals, "median": round(pct(srt, 0.5), 2),
                        "q1": round(pct(srt, 0.25), 2), "q3": round(pct(srt, 0.75), 2),
                        "best": max(pfinals), "worst": min(pfinals), "beat": beat},
            "curve": [[d, round(v, 2)] for d, v in r["curve"]],
            "pools": [(d, e, h, x) for d, e, h, x in r["pools"]],
            "trades": r["trades"]}
        print("%s final $%.2f (SPY $%.2f, champ $%.2f, pub $%.2f) maxDD %.2f%% placebo beat %d/20 median $%.2f" %
              (name, r["final"], spy, champ[name], pub[name], diag["max_dd_pct"], beat, pct(srt, 0.5)), flush=True)

    # ---- confirmation folds: fresh $100 each calendar year 2017-2026
    folds = []
    for y in range(2017, 2027):
        fs, fe = "%d-01-01" % y, ("2026-11-20" if y == 2026 else "%d-12-31" % y)
        r = run_pot(pb, pools, fs, fe)
        spy, _ = C.champ.spy_net(pb, fs, fe, 100.0)
        pf = [round(run_pot(pb, pools, fs, fe, rng=random.Random(s))["final"], 2) for s in SEEDS]
        beat = sum(1 for f in pf if f < r["final"])
        folds.append({"year": y, "final": round(r["final"], 2), "spy": round(spy, 2),
                      "beat_spy": r["final"] > spy, "placebo_beat": beat,
                      "placebo_median": round(pct(sorted(pf), 0.5), 2)})
        print("FOLD %d $%.2f vs SPY $%.2f placebo %d/20" % (y, r["final"], spy, beat), flush=True)
    out["folds"] = folds
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
