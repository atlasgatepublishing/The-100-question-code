#!/usr/bin/env python3
"""
crypto-x-reversals — V13 "Best Rules" run. Implements BEST-RULES-SPEC.md exactly
as frozen. Reads v4 caches and v12 crypto-basket-pit snapshots READ-ONLY.
Writes only in this folder.

Design (frozen): PIT top-20 universe, pegged/wrapped coins excluded, daily
event-driven entries. Candidate = formation condition (ST: 30d return <= -20%;
LT: monthly bottom-5 by 36m return). Entry only on the stabilization trigger:
fresh 10-day low within last 3 bars + first up close + close above that low.
Exits: mean-reclaim / target / time stop / per-position stop. No pot floor.
Costs 0.60%/side. $100 pots.
"""
import bisect, json, math, os, random, statistics, time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
PIT = os.path.join(HERE, "..", "..", "v12-completions", "crypto-basket-pit")
POT = 100.0
COST = 0.006
GRACE_DAYS = 30
PEGGED = {"USDT", "USDC", "DAI", "BUSD", "UST", "USD1", "USDE"}
WRAPPED = {"WBTC"}
EXCLUDED_SYMS = PEGGED | WRAPPED
WINDOWS = {"full": ("2017-01-01", "2026-11-20"),
           "design": ("2017-01-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}

LINES = {
    "st": {"form_days": 30, "form_thresh": -0.20, "watch_days": 10,
           "max_slots": 3, "sma_exit": 20, "target": 1.20, "stop": 0.90,
           "time_stop_days": 14, "cooldown_days": 14, "start_tol": 7, "min_bars": 0},
    "lt": {"form_days": 1095, "form_thresh": None, "watch_days": 30,
           "max_slots": 5, "sma_exit": 50, "target": 1.30, "stop": 0.85,
           "time_stop_days": 90, "cooldown_days": 30, "start_tol": 14, "min_bars": 900},
}

def fetch_hype():
    with open(os.path.join(PIT, "data", "hype.json")) as f: return json.load(f)

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
    reg[32196] = {"symbol": "HYPE", "slug": "hyperliquid", "source": "hyperliquid:HYPE",
                  "reason": None, "rows": fetch_hype()}
    return reg

def load_weekly():
    with open(os.path.join(PIT, "data", "weekly_snapshots.json")) as f:
        return json.load(f)

class Market:
    def __init__(self, reg, weekly):
        self.reg = reg
        btc = reg[1]["rows"]
        self.cal = [r["d"] for r in btc]
        self.bars, self.ff, self.lb = {}, {}, {}
        self.bdates, self.bcloses = {}, {}
        self.prefix = {}   # prefix sums of closes per coin (bar order)
        for cid, info in reg.items():
            if info["source"] == "excluded" or not info["rows"]: continue
            bars = {r["d"]: (r["o"], r["c"]) for r in info["rows"]}
            self.bars[cid] = bars
            self.bdates[cid] = [r["d"] for r in info["rows"]]
            self.bcloses[cid] = [r["c"] for r in info["rows"]]
            ps = [0.0]
            for c in self.bcloses[cid]: ps.append(ps[-1] + c)
            self.prefix[cid] = ps
            ff, lb, last, li = [], [], None, -1
            for i, d in enumerate(self.cal):
                if d in bars: last, li = bars[d][1], i
                ff.append(last); lb.append(li)
            self.ff[cid], self.lb[cid] = ff, lb
        self.snap_keys = sorted(weekly.keys())
        self.snap_top = {k: [c["cmc_id"] for c in weekly[k]["top20"]] for k in self.snap_keys}
        self._form = {}
    def universe(self, d):
        k = bisect.bisect_right(self.snap_keys, d) - 1
        return self.snap_top[self.snap_keys[k]] if k >= 0 else []
    def trade_open(self, cid, i):
        d = self.cal[i]
        if cid in self.bars and d in self.bars[cid]: return self.bars[cid][d][0]
        if i > 0 and cid in self.bars and self.cal[i-1] in self.bars[cid]:
            return self.bars[cid][self.cal[i-1]][1]
        return None
    def value_close(self, cid, i):
        lb = self.lb[cid][i]
        if lb < 0: return None
        return self.ff[cid][i] if i - lb <= GRACE_DAYS else 0.0
    def form_return(self, cid, j, cfg):
        key = (cid, j, cfg["form_days"])
        if key in self._form: return self._form[key]
        out = None
        if cid in self.bars and j >= 0:
            lb = self.lb[cid]
            if lb[j] >= 0 and j - lb[j] <= 7:
                k = j - cfg["form_days"]
                if k >= 0 and lb[k] >= 0 and k - lb[k] <= cfg["start_tol"]:
                    a, b = self.ff[cid][lb[k]], self.ff[cid][lb[j]]
                    if a and b and a > 0 and b > 0:
                        if cfg["min_bars"]:
                            dates = self.bdates[cid]
                            lo = bisect.bisect_left(dates, self.cal[k])
                            hi = bisect.bisect_right(dates, self.cal[j])
                            if hi - lo < cfg["min_bars"]:
                                self._form[key] = None; return None
                        out = b / a - 1.0
        self._form[key] = out
        return out
    def bar_idx(self, cid, i):
        """Index into the coin's own bar series of the last bar <= calendar i."""
        return bisect.bisect_right(self.bdates[cid], self.cal[i]) - 1
    def sma(self, cid, i, n):
        """SMA of last n bar-closes ending at the last bar <= calendar i."""
        if cid not in self.bcloses: return None
        bi = self.bar_idx(cid, i)
        if bi < n - 1: return None
        ps = self.prefix[cid]
        return (ps[bi + 1] - ps[bi + 1 - n]) / n
    def trigger(self, cid, i):
        """Stabilization trigger at close of calendar day i (bar-based):
        fresh 10-bar low within last 3 bars, first up close, close above that low."""
        if cid not in self.bcloses: return False
        bi = self.bar_idx(cid, i)
        if bi < 10: return False
        if self.bdates[cid][bi] != self.cal[i]: return False  # need a real bar today
        closes = self.bcloses[cid]
        win = closes[bi - 9: bi + 1]
        low = min(win); low_pos = len(win) - 1 - win[::-1].index(low)  # most recent low pos
        bars_since_low = 9 - low_pos
        if bars_since_low > 3: return False
        if not (closes[bi] > closes[bi - 1]): return False
        if not (closes[bi] > low): return False
        return True

def simulate(mkt, start_d, end_d, line, cfg, mode="ranked", seed=42,
             entry_schedule=None):
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    cash = float(POT)
    pos = {}          # cid -> {sh, entry_px, entry_date, entry_i}
    cooldown = {}     # cid -> date string until which re-entry blocked
    candidates = {}   # cid -> expiry date string (ranked mode)
    pending_exits = []   # cids to sell at today's open
    pending_entries = [] # (cid, form_ret) to buy at today's open, priority order
    orders, costs, traded = 0, 0.0, 0.0
    curve, trades, entries_log = [], [], []
    sched = {}
    if entry_schedule:
        for dstr in entry_schedule: sched.setdefault(dstr, 0); sched[dstr] += 1

    def equity_at(i):
        return cash + sum(p["sh"] * (mkt.value_close(cid, i) or 0.0) for cid, p in pos.items())
    def dplus(dstr, days):
        return (datetime.strptime(dstr, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")

    for i in range(i0, i1 + 1):
        d = cal[i]
        # --- executions at today's open: exits first, then entries ---
        for cid in list(pending_exits):
            if cid not in pos: continue
            px = mkt.trade_open(cid, i)
            p = pos.pop(cid)
            if px is None:
                trades.append({"coin": mkt.reg[cid]["symbol"], "entry_date": p["entry_date"],
                               "exit_date": d, "ret_pct": -100.0, "reason": "no_price_writeoff"})
                cooldown[cid] = dplus(d, cfg["cooldown_days"]); continue
            val = p["sh"] * px; fee = val * COST
            cash += val - fee; costs += fee; orders += 1; traded += val
            trades.append({"coin": mkt.reg[cid]["symbol"], "entry_date": p["entry_date"],
                           "exit_date": d, "ret_pct": round((px / p["entry_px"] - 1) * 100, 2),
                           "reason": p.get("exit_reason", "exit")})
            cooldown[cid] = dplus(d, cfg["cooldown_days"])
        pending_exits = []
        for cid, fret in pending_entries:
            if cid in pos or len(pos) >= cfg["max_slots"]: continue
            if cooldown.get(cid, "") > d: continue
            px = mkt.trade_open(cid, i)
            if px is None or px <= 0: continue
            eq = equity_at(i)
            slot = eq / cfg["max_slots"]
            bv = min(slot, cash / (1.0 + COST))
            if bv <= 0.01: continue
            fee = bv * COST; cash -= bv + fee; costs += fee; orders += 1; traded += bv
            pos[cid] = {"sh": bv / px, "entry_px": px, "entry_date": d, "entry_i": i}
            entries_log.append({"date": d, "coin": mkt.reg[cid]["symbol"],
                                "form_ret_pct": round(fret * 100, 2) if fret is not None else None})
            candidates.pop(cid, None)
        pending_entries = []
        # --- close-of-day bookkeeping ---
        eq_close = equity_at(i)
        curve.append((d, eq_close))
        if i == i1: break
        # exits evaluated at close i, executed next open
        for cid, p in list(pos.items()):
            if p["entry_i"] >= i: continue
            c = mkt.ff[cid][i] if cid in mkt.ff else None
            if c is None: continue
            reason = None
            sma = mkt.sma(cid, i, cfg["sma_exit"])
            if sma is not None and c >= sma: reason = "mean_reclaim"
            elif c >= p["entry_px"] * cfg["target"]: reason = "target"
            elif c <= p["entry_px"] * cfg["stop"]: reason = "stop"
            elif (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(p["entry_date"], "%Y-%m-%d")).days >= cfg["time_stop_days"]:
                reason = "time_stop"
            if reason:
                p["exit_reason"] = reason; pending_exits.append(cid)
        held_or_pending = set(pos) | set(pending_exits)
        if mode == "ranked":
            # candidacy
            univ = [c for c in mkt.universe(d)
                    if c in mkt.bars and mkt.reg[c]["symbol"] not in EXCLUDED_SYMS]
            if line == "st":
                for cid in univ:
                    if cid in candidates or cid in held_or_pending: continue
                    if cooldown.get(cid, "") > d: continue
                    r = mkt.form_return(cid, i, cfg)
                    if r is not None and r <= cfg["form_thresh"]:
                        candidates[cid] = dplus(d, cfg["watch_days"])
            else:  # lt: monthly candidacy on the 1st
                if datetime.strptime(d, "%Y-%m-%d").day == 1 or i == i0:
                    elig = [(cid, mkt.form_return(cid, i, cfg)) for cid in univ]
                    elig = [(c, r) for c, r in elig if r is not None]
                    elig.sort(key=lambda x: x[1])
                    for cid, r in elig[:5]:
                        if cid not in held_or_pending and cooldown.get(cid, "") <= d:
                            candidates[cid] = dplus(d, cfg["watch_days"])
            # expire candidates
            for cid in list(candidates):
                if candidates[cid] < d: del candidates[cid]
            # trigger checks -> entries at next open, most-capitulated first
            trig = []
            for cid in list(candidates):
                if cid in held_or_pending: continue
                if mkt.trigger(cid, i):
                    r = mkt.form_return(cid, i, cfg)
                    trig.append((cid, r if r is not None else 0.0))
            trig.sort(key=lambda x: x[1])
            free = cfg["max_slots"] - len(held_or_pending)
            pending_entries = trig[:max(free, 0)]
            for cid, _ in pending_entries: candidates.pop(cid, None)
        else:  # placebo: entries on the real run's entry dates, random coin
            n = sched.get(cal[i + 1], 0) if i + 1 <= i1 else 0
            if n > 0:
                univ = [c for c in mkt.universe(cal[i + 1])
                        if c in mkt.bars and mkt.reg[c]["symbol"] not in EXCLUDED_SYMS
                        and c not in held_or_pending]
                rng.shuffle(univ)
                pending_entries = [(c, None) for c in univ[:n]]
    # liquidate open positions at final close less cost
    final_cash = cash
    for cid, p in list(pos.items()):
        v = mkt.value_close(cid, i1)
        if v: final_cash += p["sh"] * v * (1 - COST); costs += p["sh"] * v * COST; orders += 1
        trades.append({"coin": mkt.reg[cid]["symbol"], "entry_date": p["entry_date"],
                       "exit_date": cal[i1], "ret_pct": round((v / p["entry_px"] - 1) * 100, 2) if v else -100.0,
                       "reason": "road_end"})
    if curve: curve[-1] = (cal[i1], final_cash)
    final = final_cash
    peak, dd = -1.0, 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0: dd = min(dd, e / peak - 1.0)
    wins = [t for t in trades if t["ret_pct"] > 0]
    return {"final": round(final, 2), "ret_pct": round((final / POT - 1) * 100, 2),
            "max_dd_pct": round(dd * 100, 2), "orders": orders, "costs": round(costs, 2),
            "traded_notional": round(traded, 2), "turnover_x_pot": round(traded / POT, 2),
            "n_trades": len(trades), "n_entries": len(entries_log),
            "win_rate_pct": round(100 * len(wins) / len(trades), 1) if trades else None,
            "avg_win_pct": round(statistics.mean([t["ret_pct"] for t in wins]), 2) if wins else None,
            "avg_loss_pct": round(statistics.mean([t["ret_pct"] for t in trades if t["ret_pct"] <= 0]), 2) if len(wins) < len(trades) else None,
            "trades": trades, "entries_log": entries_log,
            "curve": [[d, round(e, 4)] for d, e in curve]}

def btc_hold(mkt, start_d, end_d, cost=COST):
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
    pts = {}
    for d, e in curve: pts[d] = e
    dates = [d for d, _ in curve]
    bounds = [dates[0]]
    for d in dates[1:]:
        dt = datetime.strptime(d, "%Y-%m-%d")
        if dt.day <= 3 and d[:7] != bounds[-1][:7]: bounds.append(d)
    if bounds[-1] != dates[-1]: bounds.append(dates[-1])
    bounds = sorted(set(bounds))
    rets = []
    for a, b in zip(bounds, bounds[1:]):
        va, vb = pts[a], pts[b]
        if va > 0: rets.append(vb / va - 1.0)
    if not rets: return None
    n = len(rets); wins = sum(1 for r in rets if r > 0)
    run = longest = 0
    for r in rets:
        run = run + 1 if r <= 0 else 0
        longest = max(longest, run)
    eqs = [pts[b] for b in bounds]
    peak, since, max_s = -1.0, 0, 0
    for e in eqs:
        if e > peak: peak, since = e, 0
        else: since += 1; max_s = max(max_s, since)
    return {"periods": n, "pct_profitable": round(100 * wins / n, 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run_periods": longest,
            "longest_stretch_between_new_highs_periods": max_s,
            "average_pct_secondary": round(100 * sum(rets) / n, 2)}

def pct(vals, q):
    s = sorted(vals)
    if len(s) == 1: return s[0]
    p = q * (len(s) - 1); lo, hi = int(math.floor(p)), int(math.ceil(p))
    return s[lo] if lo == hi else s[lo] * (1 - (p - lo)) + s[hi] * (p - lo)

PUBLISHED_BEST = {"st": 56.79, "lt": 97.98}

def main():
    t0 = time.time()
    reg = load_registry(); weekly = load_weekly()
    mkt = Market(reg, weekly)
    print(f"registry coins={len(reg)} mapped={sum(1 for v in reg.values() if v['rows'])} "
          f"cal {mkt.cal[0]}..{mkt.cal[-1]}", flush=True)
    out = {"family": "crypto-x-reversals (v13 best rules)",
           "label": "V13 best-rules: gated capitulation reversal (ST 30d / LT 36m), CANDIDATE ceiling",
           "cost_per_side": COST, "pot": POT, "published_best": PUBLISHED_BEST,
           "runs": {}, "btc_hold": {}, "placebos": {}, "period_stats": {}}
    for w, (sd, ed) in WINDOWS.items():
        out["btc_hold"][w] = btc_hold(mkt, sd, ed)
    for line, cfg in LINES.items():
        real_entries = {}
        for w, (sd, ed) in WINDOWS.items():
            r = simulate(mkt, sd, ed, line, cfg)
            key = f"{line}|{w}"
            out["runs"][key] = r
            out["period_stats"][key] = period_stats(r["curve"])
            real_entries[w] = [e["date"] for e in r["entries_log"]]
            print(f"{key}: ${r['final']} DD {r['max_dd_pct']}% trades {r['n_trades']} "
                  f"orders {r['orders']} costs ${r['costs']} traded ${r['traded_notional']} "
                  f"BTC ${out['btc_hold'][w]['final']} ({time.time()-t0:.0f}s)", flush=True)
        for w in ("full", "validation"):
            sd, ed = WINDOWS[w]
            finals, rows = [], []
            for seed in range(1, 21):
                r = simulate(mkt, sd, ed, line, cfg, mode="placebo", seed=seed,
                             entry_schedule=real_entries[w])
                finals.append(r["final"])
                rows.append({"seed": seed, "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                             "orders": r["orders"], "costs": r["costs"]})
            rk = out["runs"][f"{line}|{w}"]["final"]
            nb = sum(1 for v in finals if rk > v)
            out["placebos"][f"{line}|{w}"] = {
                "n_seeds": 20, "median_final": round(pct(finals, .5), 2),
                "p25_final": round(pct(finals, .25), 2), "p75_final": round(pct(finals, .75), 2),
                "best_final": round(max(finals), 2), "worst_final": round(min(finals), 2),
                "ranked_final": rk, "ranked_beats_n_of_20": nb, "rows": rows}
            print(f"placebo {line}|{w}: median ${pct(finals,.5):.2f} ranked ${rk} beats {nb}/20 "
                  f"({time.time()-t0:.0f}s)", flush=True)
    # confirmation folds: any line beating BOTH bars on FULL gets yearly folds
    out["period_stats"]["btc_hold"] = {w: period_stats(out["btc_hold"][w]["curve"]) for w in WINDOWS}
    for line, cfg in LINES.items():
        if (out["runs"][f"{line}|full"]["final"] > out["btc_hold"]["full"]["final"]
                and out["runs"][f"{line}|full"]["final"] > PUBLISHED_BEST[line]):
            folds = {}
            for y in range(2018, 2027):
                sd, ed = f"{y}-01-01", min(f"{y}-12-31", "2026-11-20")
                r = simulate(mkt, sd, ed, line, cfg); b = btc_hold(mkt, sd, ed)
                folds[str(y)] = {"strategy_final": r["final"], "btc_final": b["final"]}
            out.setdefault("confirmation_year_folds", {})[line] = folds
            print(f"confirmation folds {line}:", folds, flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"saved results.json in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
