#!/usr/bin/env python3
"""
CRYPTO-X-V0-LOTTERY — v0 lottery pot as a COIN CROSS-SECTION (CONSTRUCTED).

Frozen form: see CONSTRUCTION-SPEC.md in this folder. Core = the program's
frozen v0 lottery pot (monthly PIT screen of sub-$5 names, rank each evening
by the day's % gain, buy next open <=20%/name <=5 positions, -10% stop /
+25% take-profit, floor ladder, zero-cost twin). Coin adaptations frozen in
the spec: PIT CMC weekly top-20 membership, volume legs dropped (shared
data has open/close only), close-based exits executed next open, dead coins
to ZERO after a 30-day grace, stablecoins excluded by frozen name list,
costs 0.60%/side (zero-cost twin at 0).

Reads v4 caches + crypto-basket-pit weekly snapshots READ-ONLY.
Writes only inside this folder.
"""
import json, math, os, random, statistics, time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
WEEKLY = os.path.join(HERE, "..", "crypto-basket-pit", "data", "weekly_snapshots.json")
POT = 100.0
COST = 0.006
GRACE_DAYS = 30
STABLE_IDS = {825, 3408, 4943, 7083, 3717, 3890, 2791, 3280}  # USDT USDC DAI BUSD TUSD USDP GUSD UST (frozen list, spec #7)
WINDOWS = {"full": ("2017-01-01", "2026-11-20"),
           "design": ("2017-01-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}

# ---------------------------------------------------------------- data ----
def load_registry():
    with open(os.path.join(V4, "crypto-basket-pit-results.json")) as f:
        v4res = json.load(f)
    reg = {}
    for cid_s, info in v4res["registry"].items():
        cid = int(cid_s)
        if info["source"] == "excluded":
            reg[cid] = {**info, "rows": []}; continue
        kind, name = info["source"].split(":", 1)
        fn = {"yahoo": f"y_{name}.json", "binance": f"b_{name}.json",
              "kraken": f"k_{name}.json"}[kind]
        with open(os.path.join(V4CACHE, fn)) as f: rows = json.load(f)
        if cid in CREDIBLE_START:
            rows = [r for r in rows if r["d"] >= CREDIBLE_START[cid]]
        reg[cid] = {**info, "rows": rows}
    return reg

class Market:
    def __init__(self, reg, weekly):
        self.reg = reg
        btc = reg[1]["rows"]
        self.cal = [r["d"] for r in btc]
        self.bars, self.ff, self.lb = {}, {}, {}
        for cid, info in reg.items():
            if info["source"] == "excluded" or not info["rows"]: continue
            bars = {r["d"]: (r["o"], r["c"]) for r in info["rows"]}
            self.bars[cid] = bars
            ff, lb = [], []
            last, li = None, -1
            for i, d in enumerate(self.cal):
                if d in bars: last, li = bars[d][1], i
                ff.append(last); lb.append(li)
            self.ff[cid], self.lb[cid] = ff, lb
        self.snap_keys = sorted(weekly.keys())
        self.snap_top = {k: [c["cmc_id"] for c in weekly[k]["top20"]] for k in self.snap_keys}
    def universe(self, d):
        import bisect
        k = bisect.bisect_right(self.snap_keys, d) - 1
        return self.snap_top[self.snap_keys[k]] if k >= 0 else []
    def trade_open(self, cid, i):
        d = self.cal[i]
        if cid in self.bars and d in self.bars[cid]: return self.bars[cid][d][0]
        return self.value_close(cid, i)
    def value_close(self, cid, i):
        if cid not in self.lb: return None
        lb = self.lb[cid][i]
        if lb < 0: return None
        return self.ff[cid][i] if i - lb <= GRACE_DAYS else 0.0

# ------------------------------------------------------------- simulate ---
def simulate(mkt, start_d, end_d, ruleset, cost, mode="ranked", seed=42):
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    cash, pos, entry = float(POT), {}, {}
    orders, round_trips, wins = 0, 0, 0
    costs = 0.0
    curve, events, halts = [], [], []
    pending_exits, pending_buys, pending_liq = [], [], False
    screen_set, screen_month = set(), None
    # ladder state
    floor_abs = 85.0
    # v9 state
    episode, sit_until, ended = 1, None, False
    wo = set()

    def equity_close(i):
        return cash + sum(sh * (mkt.value_close(cid, i) or 0.0) for cid, sh in pos.items())
    def equity_open(i):
        tot = cash
        for cid, sh in pos.items():
            px = mkt.trade_open(cid, i)
            tot += sh * (px or 0.0)
        return tot
    def sell(cid, px, d, why):
        nonlocal cash, costs, orders, round_trips, wins
        if cid not in pos: return
        val = pos[cid] * px
        fee = val * cost
        cash += val - fee; costs += fee; orders += 1
        round_trips += 1
        if px > entry.get(cid, px): wins += 1
        if entry.get(cid) and px <= 0.10 * entry[cid]:
            events.append({"type": "collapse_exit", "coin": mkt.reg[cid]["symbol"],
                           "date": d, "why": why, "entry_px": entry[cid], "exit_px": px})
        del pos[cid]; entry.pop(cid, None)

    for i in range(i0, i1 + 1):
        d = cal[i]
        if ended:
            curve.append((d, cash)); continue
        # --- open: floor liquidation first ---
        if pending_liq:
            for cid in list(pos):
                sell(cid, mkt.trade_open(cid, i) or 0.0, d, "floor")
            pending_liq = False; pending_exits, pending_buys = [], []
            halts.append({"episode": episode if ruleset == "v9" else 1,
                          "halt_date": d, "liquidated_at": round(cash, 2)})
            if ruleset == "ladder":
                ended = True; curve.append((d, cash)); continue
            if episode == 1:
                episode = 2
                sit_until = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
            else:
                ended = True; curve.append((d, cash)); continue
        sitting = sit_until is not None and d < sit_until
        if sit_until is not None and d >= sit_until:
            floor_abs = 0.85 * cash
            halts[-1]["restart_date"] = d; halts[-1]["restart_balance"] = round(cash, 2)
            sit_until = None; sitting = False
        # --- open: queued exits ---
        for cid in pending_exits:
            if cid in pos: sell(cid, mkt.trade_open(cid, i) or 0.0, d, "exit")
        pending_exits = []
        # --- open: queued buys (rank order) ---
        if not sitting and pending_buys:
            eq_o = equity_open(i)
            for cid in pending_buys:
                if cid in pos or len(pos) >= 5: continue
                px = mkt.trade_open(cid, i)
                if px is None or px <= 0: continue
                bv = min(0.20 * eq_o, cash / (1.0 + cost))
                if bv < 1.00: continue
                fee = bv * cost; cash -= bv + fee; costs += fee; orders += 1
                pos[cid] = bv / px; entry[cid] = px
        pending_buys = []
        # --- monthly screen (for this month, from prior month-end) ---
        if d[:7] != screen_month:
            screen_month = d[:7]
            j = i - 1
            screen_set = set()
            if j >= i0 or i == i0:
                jj = max(j, 0)
                for cid in mkt.universe(cal[jj]):
                    if cid in STABLE_IDS or cid not in mkt.bars: continue
                    lb = mkt.lb[cid][jj]
                    if lb < 0 or jj - lb > 7: continue
                    c = mkt.ff[cid][jj]
                    if c is not None and c < 5.00: screen_set.add(cid)
        # --- death write-offs ---
        for cid in list(pos):
            lb = mkt.lb[cid][i]
            if lb >= 0 and i - lb == GRACE_DAYS + 1 and cid not in wo:
                events.append({"type": "write_off", "coin": mkt.reg[cid]["symbol"],
                               "date": d, "last_bar_date": cal[lb], "last_px": mkt.ff[cid][lb],
                               "written_off_value": round(pos[cid] * mkt.ff[cid][lb], 2)})
                wo.add(cid); del pos[cid]; entry.pop(cid, None)
        eq_c = equity_close(i)
        # --- close: exits, floor, rankings (all execute tomorrow) ---
        if i < i1 and not sitting:
            for cid in list(pos):
                c = mkt.value_close(cid, i)
                if c is None or cid not in entry: continue
                if c <= 0.90 * entry[cid] or c >= 1.25 * entry[cid]:
                    pending_exits.append(cid)
            # floor check on the close
            if eq_c <= floor_abs:
                pending_liq = True; pending_exits, pending_buys = [], []
            else:
                if ruleset == "ladder":
                    if floor_abs < 100.0 and eq_c >= 125.0: floor_abs = 100.0
                    elif floor_abs < 125.0 and eq_c >= 150.0: floor_abs = 125.0
                # rankings: eligible, not held, not already exiting, positive day gain
                scored = []
                for cid in screen_set:
                    if cid in pos or cid in pending_exits: continue
                    if cid not in mkt.bars or cal[i] not in mkt.bars[cid]: continue
                    lb = mkt.lb[cid][i]
                    if lb != i or i == 0: continue
                    prev = mkt.ff[cid][i - 1]
                    cur = mkt.ff[cid][i]
                    if prev is None or prev <= 0 or cur is None: continue
                    g = cur / prev - 1.0
                    if g > 0: scored.append((cid, g))
                if mode == "ranked":
                    scored.sort(key=lambda x: -x[1])
                else:
                    rng.shuffle(scored)
                slots = 5 - len(pos) + len(pending_exits)
                pending_buys = [cid for cid, _ in scored[:max(slots, 0)]]
        curve.append((d, eq_c))
    # end of window: liquidate at final close
    if not ended and pos:
        tot = cash
        for cid, sh in list(pos.items()):
            v = mkt.value_close(cid, i1) or 0.0
            tot += sh * v * (1.0 - cost); costs += sh * v * cost; orders += 1
        cash = tot; pos.clear()
        curve[-1] = (cal[i1], cash)
    final = curve[-1][1]
    peak, dd = -1.0, 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0: dd = min(dd, e / peak - 1.0)
    return {"final": round(final, 2), "ret_pct": round((final / POT - 1) * 100, 2),
            "max_dd_pct": round(dd * 100, 2), "orders": orders,
            "round_trips": round_trips, "win_rate_pct": round(100 * wins / round_trips, 1) if round_trips else None,
            "costs": round(costs, 2), "events": events, "halts": halts,
            "ended_early": ended,
            "curve": [[d, round(e, 4)] for d, e in curve]}

def btc_hold(mkt, start_d, end_d, cost):
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    sh = (POT * (1 - cost)) / mkt.trade_open(1, i0)
    peak, dd, curve = -1.0, 0.0, []
    for i in range(i0, i1 + 1):
        v = sh * mkt.ff[1][i]; curve.append([cal[i], round(v, 4)])
        peak = max(peak, v)
        if peak > 0: dd = min(dd, v / peak - 1.0)
    final = sh * mkt.ff[1][i1] * (1 - cost)
    return {"final": round(final, 2), "ret_pct": round((final / POT - 1) * 100, 2),
            "max_dd_pct": round(dd * 100, 2), "curve": curve}

def period_stats(curve):
    """Daily periods (native tempo) from a saved equity curve."""
    eq = [e for _, e in curve]
    pnl = [eq[i + 1] - eq[i] for i in range(len(eq) - 1)]
    if not pnl: return None
    pos_n = sum(1 for x in pnl if x > 0)
    run = best_run = 0
    for x in pnl:
        run = run + 1 if x < 0 else 0
        best_run = max(best_run, run)
    peak, since, worst_stretch = -1.0, 0, 0
    for e in eq:
        if e > peak: peak, since = e, 0
        else:
            since += 1; worst_stretch = max(worst_stretch, since)
    return {"periods": len(pnl), "pct_profitable": round(100 * pos_n / len(pnl), 1),
            "median_period_usd": round(statistics.median(pnl), 4),
            "best_period_usd": round(max(pnl), 2), "worst_period_usd": round(min(pnl), 2),
            "longest_losing_run_periods": best_run,
            "longest_stretch_between_new_highs_periods": worst_stretch,
            "average_period_usd_SECONDARY_LABELED_AVERAGE": round(statistics.mean(pnl), 4)}

def pct(vals, q):
    s = sorted(vals)
    if len(s) == 1: return s[0]
    p = q * (len(s) - 1); lo, hi = int(math.floor(p)), int(math.ceil(p))
    return s[lo] if lo == hi else s[lo] * (1 - (p - lo)) + s[hi] * (p - lo)

def main():
    t0 = time.time()
    reg = load_registry()
    with open(WEEKLY) as f: weekly = json.load(f)
    mkt = Market(reg, weekly)
    print(f"registry coins={len(reg)} mapped={sum(1 for v in reg.values() if v['rows'])} "
          f"cal {mkt.cal[0]}..{mkt.cal[-1]}", flush=True)
    out = {"family": "crypto-x-v0-lottery", "label": "CONSTRUCTED (program construction, coin cross-section)",
           "cost_headline": COST, "pot": POT, "runs": {}, "btc_hold": {}, "placebos": {}}
    out["btc_hold"]["c060"] = {w: btc_hold(mkt, sd, ed, COST) for w, (sd, ed) in WINDOWS.items()}
    for ruleset in ("ladder", "v9"):
        for w, (sd, ed) in WINDOWS.items():
            for cost, tag in ((COST, "costed"), (0.0, "zerocost")):
                r = simulate(mkt, sd, ed, ruleset, cost)
                key = f"{ruleset}|{w}|{tag}"
                out["runs"][key] = r
                twin = out["runs"].get(f"{ruleset}|{w}|costed")
                gap = ""
                if tag == "zerocost" and twin: gap = f" friction gap ${r['final'] - twin['final']:+.2f}"
                print(f"{key}: ${r['final']} DD {r['max_dd_pct']}% orders {r['orders']} "
                      f"halts {len(r['halts'])} BTC ${out['btc_hold']['c060'][w]['final']}{gap} "
                      f"({time.time()-t0:.0f}s)", flush=True)
    for ruleset in ("ladder", "v9"):
        for w in ("full", "validation"):
            sd, ed = WINDOWS[w]
            finals, rows = [], []
            for seed in range(1, 21):
                r = simulate(mkt, sd, ed, ruleset, COST, mode="placebo", seed=seed)
                finals.append(r["final"])
                rows.append({"seed": seed, "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                             "orders": r["orders"]})
            rk = out["runs"][f"{ruleset}|{w}|costed"]["final"]
            nb = sum(1 for v in finals if rk > v)
            distinct = len(set(finals))
            out["placebos"][f"{ruleset}|{w}"] = {
                "n_seeds": 20, "median_final": round(pct(finals, .5), 2),
                "best_final": round(max(finals), 2), "worst_final": round(min(finals), 2),
                "distinct_finals": distinct,
                "ranked_final": rk, "ranked_beats_n_of_20": nb, "rows": rows}
            print(f"placebo {ruleset}|{w}: median ${pct(finals,.5):.2f} ranked ${rk} beats {nb}/20 "
                  f"distinct {distinct} ({time.time()-t0:.0f}s)", flush=True)
    out["period_stats"] = {}
    for key in ("ladder|full|costed", "ladder|full|zerocost", "v9|full|costed",
                "ladder|validation|costed", "v9|validation|costed"):
        out["period_stats"][key] = period_stats(out["runs"][key]["curve"])
    for w in ("full", "validation"):
        out["period_stats"][f"btc_hold|{w}"] = period_stats(out["btc_hold"]["c060"][w]["curve"])
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"saved results.json in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
