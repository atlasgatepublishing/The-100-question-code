#!/usr/bin/env python3
"""
CRYPTO-X-INDEX-ADDITIONS — v12 Wing 1 run. Spec: CONSTRUCTION-SPEC.md (frozen).
Coin analogue of re-index-additions: buy coins entering the CMC top-20
(first daily open after the snapshot that first shows them in), sell at the
close of the snapshot date on which they are first observed out.
Both rule sets (constructed native, no floor / v9 protections), costs
0.40/0.60/0.80 %/side, 20-seed random-entry-date placebos, BTC hold beside all.
Shared data READ-ONLY. Writes only inside this folder.
"""
import json, os, glob, random, statistics
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.join(HERE, "..")
V4 = os.path.join(HERE, "..", "..", "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
SNAP = os.path.join(V12, "crypto-basket-pit", "data", "weekly_snapshots.json")
HYPE = os.path.join(V12, "crypto-basket-pit", "data", "hype.json")
POT = 100.0
GRACE = 30
PEGGED = {"USDT", "USDC", "DAI", "BUSD", "TUSD", "USD1", "USDE", "UST", "USTC", "WBTC"}
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}
ROADS = {"full": ("2017-01-01", "2026-11-20"),
         "design": ("2017-01-01", "2022-12-31"),
         "validation": ("2023-01-01", "2026-11-20")}
END_ALL = "2026-11-20"

def D(s): return date.fromisoformat(s)

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
    if os.path.exists(HYPE):
        with open(HYPE) as f: rows = json.load(f)
        reg[32196] = {"symbol": "HYPE", "slug": "hyperliquid",
                      "source": "hyperliquid:HYPE", "reason": None, "rows": rows}
    return reg

class Coin:
    def __init__(self, rows):
        self.dates = [r["d"] for r in rows]
        self.bars = {r["d"]: (float(r["o"]), float(r["c"])) for r in rows}
        self.sorted_dates = sorted(self.bars)
    def first_bar_after(self, dstr):
        import bisect
        i = bisect.bisect_right(self.sorted_dates, dstr)
        return self.sorted_dates[i] if i < len(self.sorted_dates) else None
    def last_bar_on_or_before(self, dstr):
        import bisect
        i = bisect.bisect_right(self.sorted_dates, dstr) - 1
        return self.sorted_dates[i] if i >= 0 else None
    def value_close(self, dstr):
        """Close for valuation on dstr: last close <= dstr if within GRACE days, else 0 (dead)."""
        lb = self.last_bar_on_or_before(dstr)
        if lb is None: return None
        if (D(dstr) - D(lb)).days > GRACE: return 0.0
        return self.bars[lb][1]
    def open_on(self, dstr):
        return self.bars[dstr][0] if dstr in self.bars else None

def build_events(weekly, reg):
    """Returns list of raw membership events + the exit-snapshot lookup."""
    keys = sorted(weekly.keys())
    snap_top = {k: {c["cmc_id"]: c["symbol"] for c in weekly[k]["top20"]} for k in keys}
    entries = []   # (cid, symbol, snapshot_date)
    for i in range(1, len(keys)):
        prev, cur = snap_top[keys[i-1]], snap_top[keys[i]]
        for cid, sym in cur.items():
            if cid not in prev:
                entries.append((cid, sym, keys[i]))
    # exit snapshot for an entry: first later snapshot where cid absent
    def exit_snap(cid, snap_date):
        started = False
        for k in keys:
            if k <= snap_date: continue
            if cid not in snap_top[k]: return k
        return None
    return entries, exit_snap

def make_trades(entries, exit_snap, coins, road):
    """Resolve entries into trades for a road. Returns (trades, skipped dict)."""
    r0, r1 = road
    trades, skipped = [], {"pegged": 0, "no_series": [], "no_bar": 0, "cap_or_other": 0}
    for cid, sym, snap in entries:
        xs = exit_snap(cid, snap)
        # road membership: entry snapshot inside road; exit may run past road end (closed at road end)
        if not (r0 <= snap <= r1): continue
        if sym in PEGGED or coins.get(cid) and coins[cid][1] in PEGGED:
            skipped["pegged"] += 1; continue
        if cid not in coins:
            skipped["no_series"].append(sym); continue
        coin = coins[cid][0]
        ed = coin.first_bar_after(snap)
        # ADDENDUM validity rule: series must cover the event week, entry before exit
        if (ed is None or ed > r1 or (D(ed) - D(snap)).days > 7
                or (xs is not None and ed >= xs)):
            skipped["no_bar"] += 1; continue
        exit_date = xs if (xs and xs <= r1) else r1
        open_ended = not (xs and xs <= r1)
        trades.append({"cid": cid, "sym": sym, "snap": snap, "entry_date": ed,
                       "entry_open": coin.open_on(ed), "exit_date": exit_date,
                       "open_ended": open_ended})
    trades.sort(key=lambda t: t["entry_date"])
    return trades, skipped

# ------------------------------------------------------------ simulator ---
def simulate(trades, coins, cal, cost, v9):
    """Event pot: slice = equity/10 at each entry (valued at that day's opens/
    last closes), max 10 concurrent, exits at close of exit_date. Daily curve."""
    by_entry, by_exit = {}, {}
    for t in trades:
        by_entry.setdefault(t["entry_date"], []).append(t)
        by_exit.setdefault(t["exit_date"], []).append(t)
    cash, positions = POT, []   # positions: dicts with cid, shares, trade ref
    curve, costs_paid, n_fills, halts = [], 0.0, 0, []
    floor_level, episode, halt_until, dead = 0.85 * POT, 1, None, False
    skipped_cap, skipped_halt, skipped_nocash = 0, 0, 0
    traded = []
    ci = {d: i for i, d in enumerate(cal)}
    for d in cal:
        # entries at today's open
        if not dead and (halt_until is None or d > halt_until):
            for t in by_entry.get(d, []):
                if len(positions) >= 10:
                    skipped_cap += 1; continue
                eq_now = cash
                for p in positions:
                    v = coins[p["cid"]][0].value_close(d)
                    eq_now += p["shares"] * (v if v is not None else 0.0)
                slice_ = eq_now / 10.0
                if slice_ <= 0 or cash < slice_: slice_ = max(cash, 0.0)
                if slice_ <= 0: skipped_nocash += 1; continue
                spend = min(slice_, cash)
                costs_paid += spend * cost; n_fills += 1
                shares = spend * (1 - cost) / t["entry_open"]
                cash -= spend
                positions.append({"cid": t["cid"], "shares": shares, "trade": t})
                traded.append(t)
        elif dead or (halt_until is not None and d <= halt_until):
            skipped_halt += len(by_entry.get(d, []))
        # mark to close
        eq = cash
        for p in positions:
            v = coins[p["cid"]][0].value_close(d)
            eq += p["shares"] * (v if v is not None else 0.0)
        # exits at today's close
        exiting = [p for p in positions if p["trade"]["exit_date"] == d]
        for p in exiting:
            v = coins[p["cid"]][0].value_close(d)
            proceeds = p["shares"] * (v if v is not None else 0.0)
            if proceeds > 0:
                costs_paid += proceeds * cost; n_fills += 1
                proceeds *= (1 - cost)
            cash += proceeds
            p["trade"]["exit_close_used"] = v
            positions.remove(p)
        eq = cash + sum(p["shares"] * (coins[p["cid"]][0].value_close(d) or 0.0) for p in positions)
        curve.append((d, round(eq, 4)))
        # v9 floor on daily close
        if v9 and not dead and (halt_until is None or d > halt_until) and eq < floor_level:
            for p in list(positions):
                v = coins[p["cid"]][0].value_close(d)
                proceeds = p["shares"] * (v if v is not None else 0.0)
                if proceeds > 0:
                    costs_paid += proceeds * cost; n_fills += 1
                    proceeds *= (1 - cost)
                cash += proceeds; positions.remove(p)
            eq = cash
            curve[-1] = (d, round(eq, 4))
            halts.append({"date": d, "equity": round(eq, 2), "episode": episode})
            if episode == 1:
                episode = 2; floor_level = 0.85 * eq
                halt_until = (D(d) + timedelta(days=90)).isoformat()
            else:
                dead = True
    # close anything left at final close (already marked; count a sell fill)
    final = curve[-1][1] if curve else POT
    maxdd, peak = 0.0, POT
    for _, e in curve:
        peak = max(peak, e); maxdd = min(maxdd, e / peak - 1 if peak else 0.0)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs_paid, 2), "fills": n_fills, "halts": halts,
            "n_traded": len(traded), "skipped_cap": skipped_cap, "skipped_nocash": skipped_nocash,
            "skipped_halt": skipped_halt, "curve": curve, "traded": traded}

def btc_hold(btc_coin, road, cost):
    r0, r1 = road
    ed = btc_coin.first_bar_after((D(r0) - timedelta(days=1)).isoformat())
    if ed is None or ed > r1: return None
    shares = POT * (1 - cost) / btc_coin.open_on(ed)
    v = btc_coin.value_close(r1)
    return round(shares * (v if v is not None else 0.0), 2)

def standalone_event_stats(trades, coins, cost):
    out = []
    for t in trades:
        coin = coins[t["cid"]][0]
        v = coin.value_close(t["exit_date"])
        if v is None: v = 0.0
        net = (100.0 * (1 - cost) / t["entry_open"]) * v * (1 - cost) / 100.0 - 1.0 if v > 0 else -1.0
        out.append({"sym": t["sym"], "snap": t["snap"], "entry": t["entry_date"],
                    "exit": t["exit_date"], "hold_days": (D(t["exit_date"]) - D(t["entry_date"])).days,
                    "net_pct": round(net * 100, 2), "open_ended": t["open_ended"]})
    return out

def dist_stats(nets):
    if not nets: return {}
    srt = sorted(nets)
    med = statistics.median(nets)
    longest_loss, run = 0, 0
    for x in nets:
        run = run + 1 if x <= 0 else 0
        longest_loss = max(longest_loss, run)
    return {"count": len(nets), "pct_profitable": round(100 * sum(1 for x in nets if x > 0) / len(nets), 1),
            "median_pct": round(med, 2), "best_pct": round(max(nets), 2),
            "worst_pct": round(min(nets), 2), "longest_losing_run": longest_loss,
            "average_pct_secondary": round(sum(nets) / len(nets), 2)}

def curve_period_stats(curve, weekly=True):
    """Period distribution from equity curve (weekly resample) + longest stretch between new highs (days)."""
    if not curve: return {}
    peak, last_high_i, longest = curve[0][1], 0, 0
    for i, (d, e) in enumerate(curve):
        if e >= peak: peak, last_high_i = e, i
        longest = max(longest, i - last_high_i)
    pts = []
    if weekly:
        seen = {}
        for d, e in curve: ic = D(d).isocalendar(); seen[(ic[0], ic[1])] = e
        pts = list(seen.values())
    else:
        pts = [e for _, e in curve]
    rets = [pts[i] / pts[i-1] - 1 for i in range(1, len(pts)) if pts[i-1] > 0]
    st = dist_stats([r * 100 for r in rets])
    st["longest_stretch_between_new_highs_days"] = longest
    st["periods"] = len(rets)
    return st

def placebo_trades(trades, coins, road, seed):
    rng = random.Random(seed)
    r0, r1 = road
    out = []
    for t in trades:
        coin = coins[t["cid"]][0]
        hold = (D(t["exit_date"]) - D(t["entry_date"])).days
        cands = [d for d in coin.sorted_dates if r0 <= d and (D(d) + timedelta(days=hold)).isoformat() <= r1]
        if not cands: continue
        ed = rng.choice(cands)
        xd = (D(ed) + timedelta(days=hold)).isoformat()
        out.append({"cid": t["cid"], "sym": t["sym"], "snap": t["snap"], "entry_date": ed,
                    "entry_open": coin.open_on(ed), "exit_date": xd, "open_ended": False})
    out.sort(key=lambda t: t["entry_date"])
    return out

# ----------------------------------------------------------------- main ---
def main():
    reg = load_registry()
    coins = {}
    for cid, info in reg.items():
        if info["rows"]:
            coins[cid] = (Coin(info["rows"]), info["symbol"])
    with open(SNAP) as f: weekly = json.load(f)
    entries, exit_snap = build_events(weekly, reg)
    btc = coins[1][0]
    cal_all = [d for d in btc.sorted_dates if d <= END_ALL]
    results = {"spec": "CONSTRUCTION-SPEC.md (frozen)", "costs_headline": 0.006,
               "total_entry_events_all_snapshots": len(entries), "roads": {}}
    for road_name, road in ROADS.items():
        r0, r1 = road
        cal = [d for d in cal_all if r0 <= d <= r1]
        trades, skipped = make_trades(entries, exit_snap, coins, road)
        road_out = {"skipped": {"pegged": skipped["pegged"], "no_bar": skipped["no_bar"],
                                "no_series_syms": sorted(set(skipped["no_series"])),
                                "n_no_series_events": len(skipped["no_series"])},
                    "n_candidate_events": len(trades)}
        for label, v9 in (("native", False), ("v9", True)):
            sim = simulate(trades, coins, cal, 0.006, v9)
            road_out[label] = {k: sim[k] for k in ("final", "max_dd_pct", "costs", "fills",
                                 "halts", "n_traded", "skipped_cap", "skipped_halt", "skipped_nocash")}
            road_out[label + "_curve"] = sim["curve"]
            # placebos: FULL both rule sets; VALIDATION native only
            if road_name in ("full",) or (road_name == "validation" and label == "native"):
                seeds_beaten, finals = 0, []
                for seed in range(1, 21):
                    pt = placebo_trades(trades, coins, road, seed)
                    ps = simulate(pt, coins, cal, 0.006, v9)
                    finals.append(ps["final"])
                    if sim["final"] > ps["final"]: seeds_beaten += 1
                road_out[label + "_placebos"] = {"seeds_beaten_of_20": seeds_beaten,
                                                 "twin_finals": finals,
                                                 "twin_median": round(statistics.median(finals), 2)}
        # cost sensitivity, native only
        sens = {}
        for cst in (0.004, 0.008):
            s2 = simulate(trades, coins, cal, cst, False)
            sens[str(cst)] = {"final": s2["final"], "max_dd_pct": s2["max_dd_pct"], "costs": s2["costs"]}
        road_out["native_cost_sensitivity"] = sens
        road_out["btc_hold_0.60"] = btc_hold(btc, road, 0.006)
        road_out["btc_hold_0.40"] = btc_hold(btc, road, 0.004)
        road_out["btc_hold_0.80"] = btc_hold(btc, road, 0.008)
        ev = standalone_event_stats(trades, coins, 0.006)
        road_out["event_stats_native"] = dist_stats([e["net_pct"] for e in ev])
        road_out["events"] = ev
        road_out["weekly_period_stats_native"] = curve_period_stats(road_out["native_curve"])
        results["roads"][road_name] = road_out
        print(road_name, "events", len(trades),
              "native", road_out["native"]["final"], "v9", road_out["v9"]["final"],
              "btc", road_out["btc_hold_0.60"], flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("done")

if __name__ == "__main__":
    main()
