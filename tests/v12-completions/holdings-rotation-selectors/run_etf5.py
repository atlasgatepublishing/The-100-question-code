#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — the four 5-ETF rotation selectors.
Simulation only. See SWEEP-SPEC.md (frozen before this run).

One engine, per-family config; the mechanics of each family's own v12
engine are reproduced (selection, ranking, weighting, caps, exits,
rebalance, costs) with ONLY the holdings count parameterized and a
floor on/off switch for the two rule sets:
  frozen = the protection form the family ran under in v12
           (v9 for disciplined-v2 / low-volatility-tournament;
            original ladder for disciplined-v3 / v0-disciplined)
  nofloor = identical, all floor/halt/restart removed.
INTEGRITY GATE: at native count, frozen form, the engine must reproduce
each family's v12 published road finals (checked in main, printed).
"""
import csv, json, math, os, random, statistics
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.expanduser("~/workspace/stock-app/backtests")
UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
COST_RATE = 0.001; SELL_FEE = 0.01; POT0 = 100.0
COUNTS = [1, 2, 3, 5, "ALL"]
SEEDS = list(range(1, 21))
ROADS = {"LONG": ("2010-01-04", "2026-11-20"),
         "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}

FAMILIES = {
    "disciplined-v2": {
        "native": 2, "rank": "mom", "weights": "invvol", "share_quirk": True,
        "defensive": True, "ddcap": True, "trend_exits": False,
        "rebalance": "std", "floor": "v9", "dd_peak0": "curve0",
        "data": {"cache": os.path.join(ROOT, "v2/data"),
                 "long": os.path.join(ROOT, "v12-completions/disciplined-v2/data")},
        "published": {"LONG": 304.62, "DECADE": 202.03, "CONT": 192.35, "VAL": 148.96}},
    "disciplined-v3": {
        "native": 3, "rank": "mom", "weights": "equal", "share_quirk": True,
        "defensive": True, "ddcap": False, "trend_exits": True,
        "rebalance": "std", "floor": "ladder_chain", "dd_peak0": 100.0,
        "data": {"cache": os.path.join(ROOT, "v3/data"),
                 "long": os.path.join(ROOT, "v12-completions/disciplined-v3/data_long")},
        "published": {"LONG": 333.18, "DECADE": 242.92, "CONT": 201.21, "VAL": 148.31}},
    "v0-disciplined": {
        "native": 2, "rank": "mom", "weights": "equal", "share_quirk": True,
        "defensive": False, "ddcap": False, "trend_exits": True,
        "rebalance": "std", "floor": "ladder_end", "dd_peak0": 100.0,
        "data": {"cache": os.path.join(ROOT, "v12-completions/v0-disciplined/data"),
                 "long": os.path.join(ROOT, "v12-completions/v0-disciplined/data")},
        "published": {"LONG": 369.92, "DECADE": 248.63, "CONT": 213.18, "VAL": 151.25}},
    "low-volatility-tournament": {
        "native": 2, "rank": "vol_simple", "weights": "equal", "share_quirk": False,
        "defensive": False, "ddcap": False, "trend_exits": False,
        "rebalance": "lowvol", "floor": "v9_lv", "dd_peak0": 100.0,
        "data": {"cache": os.path.join(ROOT, "v3/tournament2-data"),
                 "long": os.path.join(ROOT, "v12-completions/low-volatility-tournament/data_long")},
        "published": {"LONG": 412.18, "DECADE": 236.63, "CONT": 186.44, "VAL": 161.60}},
}


class Dataset:
    def __init__(self, data_dir):
        series = {}
        for t in UNIVERSE:
            rows = []
            with open(os.path.join(data_dir, f"{t}.csv")) as f:
                for r in csv.DictReader(f):
                    rows.append((r["date"], float(r["open"]), float(r["close"])))
            series[t] = rows
        self.dates = [d for d, _, _ in series["SPY"]]
        for t in UNIVERSE:
            assert [d for d, _, _ in series[t]] == self.dates, f"{t} calendar mismatch {data_dir}"
        self.idx = {d: i for i, d in enumerate(self.dates)}
        self.O = {t: [r[1] for r in series[t]] for t in UNIVERSE}
        self.C = {t: [r[2] for r in series[t]] for t in UNIVERSE}
        n = len(self.dates)
        self.MA = {}; self.MOM = {}; self.VLOG = {}; self.VSIM = {}
        for t in UNIVERSE:
            c = self.C[t]
            self.MA[t] = [None if i < 199 else sum(c[i - 199:i + 1]) / 200.0 for i in range(n)]
            self.MOM[t] = [None if i < 63 else c[i] / c[i - 63] - 1.0 for i in range(n)]
            vl = [None] * n; vs = [None] * n
            for i in range(20, n):
                lr = [math.log(c[j] / c[j - 1]) for j in range(i - 19, i + 1)]
                vl[i] = statistics.stdev(lr) * math.sqrt(252)
                sr = [c[j] / c[j - 1] - 1.0 for j in range(i - 19, i + 1)]
                vs[i] = statistics.stdev(sr)
            self.VLOG[t] = vl; self.VSIM[t] = vs


def monthly_sel_days(win):
    out, seen = [], set()
    for d in win:
        k = d[:7]
        if k not in seen:
            seen.add(k); out.append(d)
    return set(out)


def run_segment(ds, cfg, win, count, floor_mode, mode="ranked", seed=None):
    """One uninterrupted segment over window dates `win` (list of date strs).
    floor_mode: 'v9' | 'v9_lv' | 'ladder' | None. Ladder here = halt ends
    segment (chaining handled by caller for disciplined-v3)."""
    rng = random.Random(seed)
    sel_days = monthly_sel_days(win)
    cash = POT0; shares = {t: 0.0 for t in UNIVERSE}
    orders = 0; costs = 0.0; curve = []
    floor = 85.0 if floor_mode in ("ladder",) else (0.85 * POT0 if floor_mode else None)
    episode = 1; ep_start = POT0; peak_close = POT0
    liquidate_next = False; halt_trigger = None; halts = []
    waiting_until = None; restart_date = None; ended = False
    pending_exits = set()

    def equity(mp):
        return cash + sum(shares[t] * mp[t] for t in UNIVERSE)

    def do_sell(t, price, n=None):
        nonlocal cash, costs, orders
        n = shares[t] if n is None else min(n, shares[t])
        if n <= 1e-12 or price <= 0: return
        v = n * price; c = v * COST_RATE + SELL_FEE
        cash += v - c; costs += c; shares[t] -= n; orders += 1

    def do_buy(t, price, value):
        nonlocal cash, costs, orders
        if value <= 0.005 or price <= 0: return
        c = value * COST_RATE
        if value + c > cash + 1e-9:
            value = cash / (1 + COST_RATE); c = value * COST_RATE
        cash -= value + c; costs += c; shares[t] += value / price; orders += 1

    for pos, d in enumerate(win):
        i = ds.idx[d]
        opens = {t: ds.O[t][i] for t in UNIVERSE}
        closes = {t: ds.C[t][i] for t in UNIVERSE}

        # --- floor liquidation at open (v9 / v9_lv / ladder) ---
        if liquidate_next:
            for t in UNIVERSE:
                if shares[t] > 0: do_sell(t, opens[t])
            liquidate_next = False
            halts.append({"episode": episode, "trigger_date": halt_trigger,
                          "liquidation_date": d, "balance": round(cash, 2)})
            if floor_mode in ("v9", "v9_lv"):
                if episode == 2:
                    ended = True; curve.append((d, cash)); break
                if floor_mode == "v9":
                    waiting_until = (datetime.strptime(halt_trigger, "%Y-%m-%d")
                                     + timedelta(days=90)).strftime("%Y-%m-%d")
                else:  # v9_lv: first exec day >= liquidation + 90d
                    resume = datetime.strptime(d, "%Y-%m-%d") + timedelta(days=90)
                    cands = [x for x in win if x in sel_days
                             and datetime.strptime(x, "%Y-%m-%d") >= resume]
                    waiting_until = cands[0] if cands else "NEVER"
                curve.append((d, cash)); continue
            else:  # ladder: segment ends here
                ended = True; curve.append((d, cash)); break

        if waiting_until is not None:
            restart = (d in sel_days and d >= waiting_until) if floor_mode == "v9" \
                else (d == waiting_until)
            if restart:
                episode = 2; ep_start = cash; floor = 0.85 * cash
                peak_close = cash; restart_date = d; waiting_until = None
            else:
                curve.append((d, cash)); continue

        # --- trend exits at open (v3 / v0 chassis) ---
        if cfg["trend_exits"]:
            for t in sorted(pending_exits):
                if shares[t] > 0: do_sell(t, opens[t])
            pending_exits = set()

        # --- monthly selection ---
        if d in sel_days and i > 0:
            ref = i - 1
            elig = []
            for t in UNIVERSE:
                ma = ds.MA[t][ref]
                if ma is not None and ds.C[t][ref] > ma:
                    elig.append(t)
            if cfg["rank"] == "mom":
                ranked = sorted(elig, key=lambda t: ds.MOM[t][ref], reverse=True)
            else:
                ranked = sorted(elig, key=lambda t: ds.VSIM[t][ref])
            k = len(ranked) if count == "ALL" else min(count, len(ranked))
            if mode == "placebo":
                if count == "ALL":
                    picks = list(ranked)
                elif cfg["rank"] == "vol_simple":
                    picks = rng.sample(ranked, k) if k else []
                else:
                    picks = sorted(rng.sample(sorted(ranked), k)) if k else []
            else:
                picks = ranked[:k]
            if cfg["rebalance"] == "lowvol":
                # tournament form: sell non-targets fully first, then equal
                # targets on post-sell open equity, $0.25 minimum delta.
                # (first window day has no signal day -> no trades, as original)
                if pos > 0:
                    for t in UNIVERSE:
                        if shares[t] > 0 and t not in picks:
                            do_sell(t, opens[t])
                    if picks:
                        eq_o = equity(opens); tgt = eq_o / len(picks)
                        for t in picks:
                            delta = tgt - shares[t] * opens[t]
                            if delta > 0.25: do_buy(t, opens[t], delta)
                            elif delta < -0.25: do_sell(t, opens[t], -delta / opens[t])
            else:
                if not picks:
                    share = 0.0
                elif len(picks) == 1 and cfg["share_quirk"]:
                    share = 0.5
                else:
                    share = 1.0
                if cfg["defensive"]:
                    sma = ds.MA["SPY"][ref]
                    if sma is not None and ds.C["SPY"][ref] < sma:
                        share = min(share, 0.5)
                if cfg["ddcap"]:
                    ref_eq = curve[-1][1] if curve else ep_start
                    dd = (peak_close - ref_eq) / peak_close if peak_close > 0 else 0.0
                    if dd >= 0.07: share = min(share, 0.5)
                weights = {}
                if picks:
                    if cfg["weights"] == "invvol":
                        inv = {t: (1.0 / ds.VLOG[t][ref]) if ds.VLOG[t][ref] else None
                               for t in picks}
                        if any(v is None for v in inv.values()):
                            weights = {t: 1.0 / len(picks) for t in picks}
                        else:
                            tot = sum(inv.values())
                            weights = {t: inv[t] / tot for t in picks}
                    else:
                        weights = {t: 1.0 / len(picks) for t in picks}
                eq_o = equity(opens)
                targets = {t: share * eq_o * weights.get(t, 0.0) for t in picks}
                for t in UNIVERSE:
                    if shares[t] <= 0: continue
                    cur = shares[t] * opens[t]; tgt = targets.get(t, 0.0)
                    if cur > tgt + 0.005: do_sell(t, opens[t], (cur - tgt) / opens[t])
                wants = {}
                for t in picks:
                    cur = shares[t] * opens[t]
                    if targets[t] > cur + 0.005: wants[t] = targets[t] - cur
                twc = sum(v * (1 + COST_RATE) for v in wants.values())
                scale = max(cash, 0.0) / twc if twc > cash and twc > 0 else 1.0
                for t in picks:
                    if t in wants: do_buy(t, opens[t], wants[t] * scale)

        eq_c = equity(closes)
        curve.append((d, eq_c))

        # --- floor bookkeeping at close ---
        if floor_mode == "ladder":
            if eq_c >= 150.0: floor = max(floor, 125.0)
            elif eq_c >= 125.0: floor = max(floor, 100.0)
            if eq_c <= floor:
                if d == win[-1]:
                    for t in UNIVERSE:
                        if shares[t] > 0: do_sell(t, closes[t])
                    halts.append({"episode": episode, "trigger_date": d,
                                  "liquidation_date": d, "balance": round(cash, 2)})
                    ended = True; curve[-1] = (d, cash); break
                liquidate_next = True; halt_trigger = d
                continue  # originals skip trend-exit marking on a halt day
        elif floor_mode in ("v9", "v9_lv"):
            if waiting_until is None and eq_c > peak_close: peak_close = eq_c
            if waiting_until is None and eq_c <= floor:
                if d == win[-1]:
                    for t in UNIVERSE:
                        if shares[t] > 0: do_sell(t, closes[t])
                    halts.append({"episode": episode, "trigger_date": d,
                                  "liquidation_date": d, "balance": round(cash, 2)})
                    ended = True; curve[-1] = (d, cash); break
                liquidate_next = True; halt_trigger = d
        else:  # no floor: only peak tracking (ddcap uses it in v2 nofloor too)
            if eq_c > peak_close: peak_close = eq_c

        if cfg["trend_exits"]:
            for t in UNIVERSE:
                if shares[t] > 1e-9:
                    ma = ds.MA[t][i]
                    if ma is not None and closes[t] < ma: pending_exits.add(t)

    if not ended:
        i = ds.idx[win[-1]]
        closes = {t: ds.C[t][i] for t in UNIVERSE}
        for t in UNIVERSE:
            if shares[t] > 0: do_sell(t, closes[t])
        if curve and curve[-1][0] == win[-1]: curve[-1] = (win[-1], cash)
        else: curve.append((win[-1], cash))
    elif floor_mode in ("v9", "v9_lv"):
        # v9 originals pad the curve flat to the window end after a final halt
        last_d, last_v = curve[-1]
        for d in win:
            if d > last_d: curve.append((d, last_v))

    peak0 = curve[0][1] if cfg["dd_peak0"] == "curve0" else POT0
    peak, mdd = peak0, 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, (peak - v) / peak if peak > 0 else 0.0)
    return {"final": round(cash, 2), "max_dd_pct": round(mdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "halts": halts,
            "restart": restart_date is not None,
            "curve": [[d, round(v, 4)] for d, v in curve]}


def run_family(ds, cfg, start, end, count, form, mode="ranked", seed=None):
    win = [d for d in ds.dates if start <= d <= end]
    if form == "nofloor":
        return run_segment(ds, cfg, win, count, None, mode, seed)
    fm = cfg["floor"]
    if fm in ("v9", "v9_lv"):
        return run_segment(ds, cfg, win, count, fm, mode, seed)
    if fm == "ladder_end":
        return run_segment(ds, cfg, win, count, "ladder", mode, seed)
    # ladder_chain (disciplined-v3): halt -> fresh $100 next Jan 1, chained
    segments = []; seg_start = start; factor = 1.0; curve = []
    total_costs = 0.0; total_orders = 0; all_halts = []
    while True:
        w = [d for d in ds.dates if seg_start <= d <= end]
        seg = run_segment(ds, cfg, w, count, "ladder", mode, seed)
        segments.append(seg)
        total_costs += seg["costs"]; total_orders += seg["orders"]
        all_halts += seg["halts"]
        for d, v in seg["curve"]: curve.append([d, round(v * factor, 4)])
        factor *= seg["final"] / 100.0
        if not seg["halts"]: break
        halt_year = int(seg["curve"][-1][0][:4]); nxt = f"{halt_year + 1}-01-01"
        if nxt > end: break
        seg_start = nxt
    peak, mdd = POT0, 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, (peak - v) / peak if peak > 0 else 0.0)
    return {"final": round(100.0 * factor, 2), "max_dd_pct": round(mdd * 100, 2),
            "costs": round(total_costs, 2), "orders": total_orders,
            "halts": all_halts, "restart": len(segments) > 1,
            "n_segments": len(segments),
            "curve": curve}


def period_stats(curve, start_balance=100.0):
    """Monthly period distribution from a daily [date, equity] curve."""
    months = []
    prev_m = None; last_v = None
    for d, v in curve:
        if d[:7] != prev_m:
            if prev_m is not None: months.append(last_v)
            prev_m = d[:7]
        last_v = v
    if last_v is not None: months.append(last_v)
    rets = []; prev = start_balance
    for v in months:
        rets.append(v / prev - 1.0); prev = v
    if not rets: return None
    prof = sum(1 for r in rets if r > 0)
    run = longest = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        longest = max(longest, run)
    peak = start_balance; since = 0; longest_gap = 0
    for v in months:
        if v > peak: peak = v; since = 0
        else:
            since += 1; longest_gap = max(longest_gap, since)
    return {"periods": len(rets), "pct_profitable": round(100.0 * prof / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run": longest, "longest_between_highs_months": longest_gap,
            "average_pct_secondary": round(statistics.mean(rets) * 100, 2)}


def main():
    out = {"wing": "holdings-rotation-selectors", "families": {}}
    datasets = {}
    def get_ds(path):
        if path not in datasets: datasets[path] = Dataset(path)
        return datasets[path]
    # ---------- integrity gate ----------
    print("=== INTEGRITY GATE (native count, frozen form) ===", flush=True)
    integrity = {}
    for slug, cfg in FAMILIES.items():
        integrity[slug] = {}
        for road, (s, e) in ROADS.items():
            ds = get_ds(cfg["data"]["long" if road == "LONG" else "cache"])
            r = run_family(ds, cfg, s, e, cfg["native"], "frozen")
            pub = cfg["published"][road]
            ok = abs(r["final"] - pub) < 0.005
            integrity[slug][road] = {"mine": r["final"], "published": pub, "match": ok}
            print(slug, road, r["final"], "vs published", pub, "MATCH" if ok else "** MISMATCH **", flush=True)
    out["integrity"] = integrity
    if not all(v["match"] for f in integrity.values() for v in f.values()):
        print("INTEGRITY FAILED — sweep aborted", flush=True)
        with open(os.path.join(HERE, "results_etf5.json"), "w") as f:
            json.dump(out, f, indent=1)
        return
    # ---------- grid ----------
    for slug, cfg in FAMILIES.items():
        fam = {"native_count": cfg["native"], "forms": {}}
        for form in ("frozen", "nofloor"):
            cells = {}
            for count in COUNTS:
                key = str(count)
                cells[key] = {}
                for road, (s, e) in ROADS.items():
                    ds = get_ds(cfg["data"]["long" if road == "LONG" else "cache"])
                    r = run_family(ds, cfg, s, e, count, form)
                    cell = {"final": r["final"], "max_dd_pct": r["max_dd_pct"],
                            "costs": r["costs"], "orders": r["orders"],
                            "halts": len(r["halts"]), "restart": r["restart"]}
                    if count == "ALL":
                        cell["placebo_beaten"] = None; cell["placebo_finals"] = None
                    else:
                        twins = []
                        for seed in SEEDS:
                            pr = run_family(ds, cfg, s, e, count, form,
                                            mode="placebo", seed=seed)
                            twins.append(pr["final"])
                        cell["placebo_finals"] = twins
                        cell["placebo_beaten"] = sum(1 for x in twins if r["final"] > x)
                    if road == "DECADE":
                        cell["curve"] = r["curve"]
                    cells[key][road] = cell
                    print(slug, form, key, road, cell["final"], "DD", cell["max_dd_pct"],
                          "pl", cell["placebo_beaten"], flush=True)
            fam["forms"][form] = cells
        out["families"][slug] = fam
    with open(os.path.join(HERE, "results_etf5.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE etf5")


if __name__ == "__main__":
    main()
