#!/usr/bin/env python3
"""V13 BEST RULES — Aggressive-V2. Spec: BEST-RULES-SPEC.md (frozen).
Weekly: Friday-close signal (20d breakout + close>50dMA, rank by 20d return,
top-2 @50% each), SPY<200dMA = full cash, no profit target, weekly 50d/rank
exit, daily -20% catastrophic per-name stop, NO pot floor.
Costs 0.10%/side + $0.01/sell. Data: read-only v2 Yahoo cache (OHLCV)."""
import json, os, random, statistics
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v2/data")
UNIVERSE = ["SPY","QQQ","NVDA","TSLA","AAPL","MSFT","AMZN","META","AMD","AVGO"]
COST = 0.001; FEE = 0.01; N = 2; STOP = 0.80
ROADS = {"DECADE": ("2016-11-21","2026-11-20"), "CONT": ("2019-01-02","2026-11-20"), "VAL": ("2023-01-03","2026-11-20")}
CHAMP = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

def load_bars(sym):
    with open(os.path.join(DATA, f"{sym}.json")) as f:
        raw = json.load(f)
    res = raw["chart"]["result"][0]; q = res["indicators"]["quote"][0]
    rows = {}
    for i, t in enumerate(res["timestamp"]):
        if q["close"][i] is None or q["open"][i] is None: continue
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        rows[d] = {"o": q["open"][i], "h": q["high"][i], "l": q["low"][i], "c": q["close"][i], "v": q["volume"][i] or 0}
    return rows

class Mkt:
    def __init__(self):
        self.raw = {t: load_bars(t) for t in UNIVERSE}
        self.cal = sorted(self.raw["SPY"].keys())
        self.idx = {d: i for i, d in enumerate(self.cal)}
        self.closes = {}
        for t in UNIVERSE:
            arr = []; last = None
            for d in self.cal:
                if d in self.raw[t]: last = self.raw[t][d]["c"]
                arr.append(last)
            self.closes[t] = arr
    def op(self, t, i):
        d = self.cal[i]
        return self.raw[t][d]["o"] if d in self.raw[t] else None
    def cp(self, t, i): return self.closes[t][i]
    def sma(self, t, i, n):
        if i + 1 < n: return None
        seg = self.closes[t][i-n+1:i+1]
        return None if any(v is None for v in seg) else sum(seg)/n
    def eligible(self, j):
        """signal-day j: breakout (close >= max close of prior 20d) + close>50dMA; rank by 20d return"""
        out = []
        for t in UNIVERSE:
            c = self.cp(t, j)
            if c is None or j < 51: continue
            s50 = self.sma(t, j, 50)
            if s50 is None or c <= s50: continue
            prior = self.closes[t][j-20:j]
            if any(v is None for v in prior): continue
            if c < max(prior): continue
            base = self.closes[t][j-20]
            if base is None or base <= 0: continue
            out.append((t, c/base - 1.0))
        out.sort(key=lambda x: -x[1])
        return out

def simulate(mkt, sd, ed, mode="ranked", seed=42, pot0=100.0):
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= sd)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= ed)
    cash = float(pot0); pos = {}  # t -> [shares, avg_entry]
    curve = []; orders = 0; costs = 0.0; trades = 0; wins = 0; proceeds_log = []
    # weekly signal days: last trading day of each ISO week within range; rebalance next trading day
    sig_days = {}
    for i in range(i0, i1):
        d = datetime.strptime(mkt.cal[i], "%Y-%m-%d")
        key = (d.isocalendar()[0], d.isocalendar()[1])
        sig_days[key] = i  # last one wins as we iterate forward
    rebal = {}  # trade-day index -> signal index
    for key, j in sig_days.items():
        if j + 1 <= i1: rebal[j+1] = j
    def equity(i, use_open):
        tot = cash
        for t, (sh, _) in pos.items():
            px = mkt.op(t, i) if use_open else mkt.cp(t, i)
            if px is None: px = mkt.cp(t, i)
            if px is not None: tot += sh*px
        return tot
    def sell(t, i, shares):
        nonlocal cash, orders, costs, trades, wins
        px = mkt.op(t, i)
        if px is None or shares <= 0: return
        val = shares*px; fee = val*COST + FEE
        cash += val - fee; costs += fee; orders += 1; trades += 1
        if px >= pos[t][1]: wins += 1
        pos[t][0] -= shares
        if pos[t][0] <= 1e-9: del pos[t]
    def buy(t, i, dollars):
        nonlocal cash, orders, costs
        px = mkt.op(t, i)
        if px is None or dollars <= 0.01: return
        bv = min(dollars, cash/(1+COST))
        if bv <= 0.01: return
        fee = bv*COST; cash -= bv + fee; costs += fee; orders += 1
        sh = bv/px
        if t in pos:
            old_sh, old_px = pos[t]; pos[t] = [old_sh+sh, (old_sh*old_px + sh*px)/(old_sh+sh)]
        else: pos[t] = [sh, px]
    pending_stop = []  # names to sell at today's open (stop triggered at prior close)
    for i in range(i0, i1+1):
        # 1) catastrophic stops triggered yesterday -> sell at open
        for t in list(pending_stop):
            if t in pos: sell(t, i, pos[t][0])
        pending_stop = []
        # 2) weekly rebalance at open
        if i in rebal:
            j = rebal[i]
            spy_c = mkt.cp("SPY", j); spy_s = mkt.sma("SPY", j, 200)
            if spy_s is None or spy_c <= spy_s:
                picks = []
            else:
                elig = mkt.eligible(j)
                if mode == "ranked": picks = [t for t, _ in elig[:N]]
                else:
                    names = sorted(t for t, _ in elig)
                    picks = rng.sample(names, min(N, len(names))) if names else []
            eqo = equity(i, True)
            tgt = {t: 0.5*eqo for t in picks}
            for t in list(pos):
                if t not in tgt: sell(t, i, pos[t][0])
            for t in list(pos):
                px = mkt.op(t, i)
                if px is None: continue
                cur_val = pos[t][0]*px
                if cur_val > tgt[t] + 1.0: sell(t, i, (cur_val - tgt[t])/px)
            for t in picks:
                px = mkt.op(t, i)
                if px is None: continue
                cur_val = pos.get(t, [0, 0])[0]*px
                if tgt[t] - cur_val > 1.0: buy(t, i, tgt[t] - cur_val)
        curve.append((mkt.cal[i], equity(i, False)))
        # 3) catastrophic stop check at close (sell tomorrow open; if last day, valued at close in curve)
        if i < i1:
            for t, (sh, avg) in list(pos.items()):
                c = mkt.cp(t, i)
                if c is not None and avg > 0 and c <= STOP*avg: pending_stop.append(t)
    final = curve[-1][1]
    peak = -1; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e); mdd = min(mdd, e/peak - 1.0 if peak > 0 else 0.0)
    return {"final": round(final, 2), "max_dd_pct": round(mdd*100, 2), "orders": orders,
            "costs": round(costs, 2), "round_trips": trades,
            "win_rate_pct": round(100*wins/trades, 1) if trades else None, "equity_curve": curve}

def spy_net(mkt, sd, ed, pot0=100.0):
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= sd); i1 = max(i for i, d in enumerate(mkt.cal) if d <= ed)
    sh = (pot0*(1-COST))/mkt.op("SPY", i0)
    return round(sh*mkt.cp("SPY", i1)*(1-COST) - FEE, 2)

def dist(curve):
    me = {}
    for d, e in curve: me[d[:7]] = e
    ks = sorted(me); rets = [me[b]/me[a]-1 for a, b in zip(ks, ks[1:])]
    if not rets: return {}
    s = sorted(rets); n = len(s)
    med = s[n//2] if n % 2 else (s[n//2-1]+s[n//2])/2
    streak = cur_s = 0
    for r in rets:
        cur_s = cur_s+1 if r <= 0 else 0; streak = max(streak, cur_s)
    peak = -1; since = longest = 0
    for _, e in curve:
        if e >= peak: peak = e; since = 0
        else: since += 1
        longest = max(longest, since)
    return {"periods": n, "median_pct": round(med*100, 2), "pct_positive": round(100*sum(1 for r in rets if r > 0)/n, 1),
            "best_pct": round(max(rets)*100, 2), "worst_pct": round(min(rets)*100, 2),
            "longest_losing_streak_mo": streak, "longest_days_between_highs": longest,
            "avg_pct_secondary": round(sum(rets)/n*100, 2), "monthly_rets": [round(r*100, 2) for r in rets]}

def main():
    mkt = Mkt()
    out = {"family": "aggressive-v2", "spec": "weekly top2 20d-breakout rank20d 50/50, SPY200 full-cash regime, 50d/rank exit, -20% name stop, no target, NO floor",
           "roads": {}, "placebos": {}}
    ranked = {}
    for road, (sd, ed) in ROADS.items():
        r = simulate(mkt, sd, ed, "ranked"); ranked[road] = r
        out["roads"][road] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"], "orders": r["orders"],
                              "costs": r["costs"], "round_trips": r["round_trips"], "win_rate_pct": r["win_rate_pct"],
                              "spy_net_price_only": spy_net(mkt, sd, ed), "equity_curve": r["equity_curve"]}
        print(road, r["final"], r["max_dd_pct"], "orders", r["orders"], "costs", r["costs"], flush=True)
        finals = []
        for seed in range(1, 21):
            p = simulate(mkt, sd, ed, "placebo", seed=seed); finals.append(p["final"])
        beaten = sum(1 for v in finals if r["final"] > v); sf = sorted(finals)
        out["placebos"][road] = {"finals": finals, "median": sf[10], "best": sf[-1], "worst": sf[0], "ranked_beats_n_of_20": beaten}
        print(road, "placebo median", sf[10], "beats", beaten, "/20", flush=True)
    out["distribution_decade_monthly"] = dist(ranked["DECADE"]["equity_curve"])
    # Confirmation rule: only if a champion is beaten on any road
    beaten_roads = [r for r in ROADS if ranked[r]["final"] > CHAMP[r]]
    out["confirmation"] = {"champion_beaten_on_roads": beaten_roads, "triggered": bool(beaten_roads)}
    if beaten_roads:
        folds = {}
        for y in range(2017, 2027):
            sd = f"{y}-01-01"; ed = "2026-11-20" if y == 2026 else f"{y}-12-31"
            a = simulate(mkt, sd, ed, "ranked")
            folds[str(y)] = {"final": a["final"], "max_dd_pct": a["max_dd_pct"]}
        out["confirmation"]["calendar_year_folds_fresh_100"] = folds
    with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(out, f, indent=1)
    print("saved results.json")

if __name__ == "__main__": main()
