#!/usr/bin/env python3
"""
CRYPTO-X-LOTTERY — Wing 1 cross-application of the lottery (MAX-effect)
family as a coin cross-section on the PIT universe.
Spec: CONSTRUCTION-SPEC.md (frozen before this run).

Lines:
  L-LOT : buy 5 lowest-MAX eligible coins (published MAX long leg)
  L-V2  : buy 5 highest-MAX eligible coins (the lottery-pot direction;
          v2's volume-spike variable does not translate - no volume in
          the shared PIT cache; see spec)
  L-V3  : among eligible coins up over prior 30 days, buy 5 lowest-MAX
          (v3 headline N3 'quiet gainers' at basket tempo)

Reads v4 registry/cache and v12 crypto-basket-pit weekly snapshots
READ-ONLY. Writes only inside this folder.
"""
import json, math, os, random, bisect
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
WEEKLY = os.path.join(HERE, "..", "crypto-basket-pit", "data", "weekly_snapshots.json")
POT = 100.0
COST = 0.006            # 0.60%/side headline
GRACE_DAYS = 30
WINDOWS = {"full": ("2017-01-01", "2026-11-20"),
           "design": ("2017-01-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}
LINES = ["L-LOT", "L-V2", "L-V3"]
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}

# ---------------------------------------------------------------- data ----
def load_registry():
    with open(os.path.join(V4, "crypto-basket-pit-results.json")) as f:
        v4res = json.load(f)
    reg = {}
    for cid_s, info in v4res["registry"].items():
        cid = int(cid_s)
        if info["source"] == "excluded":
            reg[cid] = {**info, "rows": []}
            continue
        kind, name = info["source"].split(":", 1)
        fn = {"yahoo": f"y_{name}.json", "binance": f"b_{name}.json",
              "kraken": f"k_{name}.json"}[kind]
        with open(os.path.join(V4CACHE, fn)) as f:
            rows = json.load(f)
        if cid in CREDIBLE_START:
            rows = [r for r in rows if r["d"] >= CREDIBLE_START[cid]]
        reg[cid] = {**info, "rows": rows}
    return reg

class Market:
    def __init__(self, reg, weekly):
        self.reg = reg
        btc = reg[1]["rows"]
        self.cal = [r["d"] for r in btc]
        self.ci = {d: i for i, d in enumerate(self.cal)}
        self.bars, self.ff, self.lb, self.bc = {}, {}, {}, {}
        self.max30, self.ret30 = {}, {}
        for cid, info in reg.items():
            if info["source"] == "excluded" or not info["rows"]:
                continue
            bars = {r["d"]: (r["o"], r["c"]) for r in info["rows"]}
            self.bars[cid] = bars
            ff, lb, bc = [], [], []
            last, li, n = None, -1, 0
            for i, d in enumerate(self.cal):
                if d in bars:
                    last, li, n = bars[d][1], i, n + 1
                ff.append(last); lb.append(li); bc.append(n)
            self.ff[cid], self.lb[cid], self.bc[cid] = ff, lb, bc
            # MAX30 / RET30 aligned arrays, computed from actual bars only.
            # daily return on calendar day j uses ff closes j vs j-1 and
            # requires real bars on both days.
            mx, rt = [None] * len(self.cal), [None] * len(self.cal)
            rets = [None] * len(self.cal)
            for i, d in enumerate(self.cal):
                if d in bars and i > 0 and self.cal[i - 1] in bars:
                    p0 = bars[self.cal[i - 1]][1]
                    if p0 > 0:
                        rets[i] = bars[d][1] / p0 - 1.0
            for i in range(len(self.cal)):
                lo = i - 29
                if lo < 0:
                    continue
                win = [rets[j] for j in range(lo, i + 1) if rets[j] is not None]
                if len(win) >= 25:
                    mx[i] = max(win)
                if i >= 30 and ff[i] is not None and ff[i - 30] is not None and ff[i - 30] > 0 \
                        and bc[i] - bc[i - 30] >= 25:
                    rt[i] = ff[i] / ff[i - 30] - 1.0
            self.max30[cid], self.ret30[cid] = mx, rt
        self.snap_keys = sorted(weekly.keys())
        self.snap_top = {k: [c["cmc_id"] for c in weekly[k]["top20"]]
                         for k in self.snap_keys}

    def universe(self, d):
        k = bisect.bisect_right(self.snap_keys, d) - 1
        return self.snap_top[self.snap_keys[k]] if k >= 0 else []

    def trade_open(self, cid, i):
        d = self.cal[i]
        if d in self.bars[cid]:
            return self.bars[cid][d][0]
        if i > 0 and self.cal[i - 1] in self.bars[cid]:
            return self.bars[cid][self.cal[i - 1]][1]
        return None

    def value_close(self, cid, i):
        lb = self.lb[cid][i]
        if lb < 0:
            return None
        return self.ff[cid][i] if i - lb <= GRACE_DAYS else 0.0

    def eligible(self, i, universe):
        """Eligible coins at signal close index i (dict cid -> (max30, ret30))."""
        out = {}
        for cid in universe:
            if cid not in self.bars:
                continue
            if i - self.lb[cid][i] > 7:        # freshness: real bar within 7d
                continue
            if self.bc[cid][i] < 35:           # history for a full MAX window
                continue
            m = self.max30[cid][i]
            if m is None:
                continue
            out[cid] = (m, self.ret30[cid][i])
        return out

def select(line, elig, rng=None):
    items = list(elig.items())  # cid -> (max30, ret30)
    if rng is not None:
        rng.shuffle(items)
        return [cid for cid, _ in items[:5]]
    if line == "L-LOT":
        items.sort(key=lambda kv: (kv[1][0], kv[0]))
    elif line == "L-V2":
        items.sort(key=lambda kv: (-kv[1][0], kv[0]))
    elif line == "L-V3":
        items = [kv for kv in items if kv[1][1] is not None and kv[1][1] > 0]
        items.sort(key=lambda kv: (kv[1][0], kv[0]))
    return [cid for cid, _ in items[:5]]

# -------------------------------------------------------------- engine ----
def run(mkt, line, wname, ruleset, cost=COST, seed=None):
    start, end = WINDOWS[wname]
    i0 = mkt.ci[start]
    i1 = mkt.ci[end]
    rng = random.Random(seed) if seed is not None else None
    cash, pos = POT, {}          # pos: cid -> units
    curve, picks = [], []
    costs_total = 0.0
    halts = []
    episode = 1
    ep_start_equity = POT
    halted_until = None          # date index: in cash (90d sit) until this idx
    ended = False
    pending_liquidation = False

    def equity_close(i):
        v = cash
        for cid, u in pos.items():
            p = mkt.value_close(cid, i)
            if p:
                v += u * p
        return v

    def equity_open(i):
        v = cash
        for cid, u in pos.items():
            p = mkt.trade_open(cid, i)
            if p is None:
                p = mkt.value_close(cid, i - 1) or 0.0
            v += u * p
        return v

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        # pending floor liquidation at today's open
        if pending_liquidation and not ended:
            eq_o = equity_open(i)
            for cid, u in list(pos.items()):
                p = mkt.trade_open(cid, i)
                if p is None:
                    p = mkt.value_close(cid, i - 1) or 0.0
                amt = u * p
                cash += amt * (1 - cost)
                costs_total += amt * cost
            pos = {}
            pending_liquidation = False
            if episode == 1:
                halt_date = date.fromisoformat(d) + timedelta(days=90)
                halted_until = halt_date.isoformat()
                halts.append({"episode": 1, "liquidated": d,
                              "cash_after": round(cash, 2),
                              "restart_on_or_after": halted_until})
                episode = 2
                ep_start_equity = cash
            else:
                halts.append({"episode": 2, "liquidated": d,
                              "cash_after": round(cash, 2), "ended": True})
                ended = True
            curve.append([d, round(cash, 4)])
            continue
        if halted_until is not None and d >= halted_until:
            halted_until = None  # 90-day sit served; restart at next rebalance
        # monthly rebalance at open (1st calendar day), signals from prior close
        is_rebal = d.endswith("-01") or i == i0
        in_sit = halted_until is not None and d < halted_until
        if is_rebal and not ended and not in_sit:
            sig = i - 1
            if sig >= 0:
                elig = mkt.eligible(sig, mkt.universe(d))
                picks_today = select(line, elig, rng)
            else:
                picks_today = []
            if picks_today or pos:
                eq_o = equity_open(i)
                target = {cid: 0.20 * eq_o for cid in picks_today}
                # sells first
                for cid, u in list(pos.items()):
                    p = mkt.trade_open(cid, i)
                    if p is None:
                        continue
                    cur = u * p
                    tgt = target.get(cid, 0.0)
                    if cur > tgt + 1e-9:
                        sell_amt = cur - tgt
                        cash += sell_amt * (1 - cost)
                        costs_total += sell_amt * cost
                        pos[cid] = u - sell_amt / p
                        if pos[cid] * p < 1e-6:
                            del pos[cid]
                # buys
                for cid in picks_today:
                    p = mkt.trade_open(cid, i)
                    if p is None:
                        continue
                    cur = pos.get(cid, 0.0) * p
                    need = target[cid] - cur
                    if need > 1e-9:
                        spend = min(need, cash / (1 + cost) * 1.0) if cash > 0 else 0.0
                        # spend is pre-cost amount such that spend*(1+cost)<=cash approx:
                        spend = min(need, cash / (1 + cost))
                        if spend > 1e-9:
                            cash -= spend * (1 + cost)
                            costs_total += spend * cost
                            pos[cid] = pos.get(cid, 0.0) + spend / p
                picks.append({"date": d,
                              "picks": [mkt.reg[c]["symbol"] for c in picks_today]})
                if halted_until is not None and d >= halted_until:
                    halted_until = None
        eq = equity_close(i)
        curve.append([d, round(eq, 4)])
        # v9 floor check on close
        if ruleset == "v9" and not ended and not pending_liquidation \
                and halted_until is None:
            if eq <= 0.85 * ep_start_equity + 1e-9 and (pos or i > i0):
                # only breach if the run has actually traded / holds risk:
                if pos:
                    pending_liquidation = True
    final = curve[-1][1] if curve else POT
    # max drawdown
    peak, mdd = 0.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return {"line": line, "window": wname, "ruleset": ruleset,
            "cost_rate": cost, "final": round(final, 2),
            "ret_pct": round((final / POT - 1) * 100, 2),
            "max_dd_pct": round(mdd * 100, 2),
            "costs_total": round(costs_total, 2),
            "halts": halts, "n_rebalances_held": len(picks),
            "curve": curve, "picks": picks}

def btc_hold(mkt, wname, cost=COST):
    start, end = WINDOWS[wname]
    i0, i1 = mkt.ci[start], mkt.ci[end]
    p0 = mkt.trade_open(1, i0)
    units = POT * (1 - cost) / p0
    curve = []
    for i in range(i0, i1 + 1):
        v = mkt.value_close(1, i)
        curve.append([mkt.cal[i], round(units * (v or 0.0), 4)])
    final = units * (mkt.value_close(1, i1) or 0.0) * (1 - cost)
    peak, mdd = 0.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return {"final": round(final, 2), "max_dd_pct": round(mdd * 100, 2),
            "curve": curve}

def period_stats(curve):
    """Monthly period distribution from a daily equity curve."""
    months = {}
    for d, v in curve:
        months[d[:7]] = v  # last value in month wins (curve is daily-ordered)
    keys = sorted(months)
    vals = [months[k] for k in keys]
    rets = []
    for a, b in zip(vals[:-1], vals[1:]):
        rets.append(b / a - 1.0 if a > 0 else 0.0)
    if not rets:
        return {"n_periods": 0}
    srt = sorted(rets)
    n = len(rets)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    longest_loss, cur = 0, 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        longest_loss = max(longest_loss, cur)
    # longest stretch between new highs (in months, month-end equity basis)
    peak, since, longest_gap = -1.0, 0, 0
    for v in vals:
        if v > peak:
            peak, since = v, 0
        else:
            since += 1
            longest_gap = max(longest_gap, since)
    return {"n_periods": n,
            "pct_profitable": round(100.0 * sum(1 for r in rets if r > 0) / n, 1),
            "median_pct": round(median * 100, 2),
            "best_pct": round(max(rets) * 100, 2),
            "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run": longest_loss,
            "longest_months_between_new_highs": longest_gap,
            "average_pct_secondary": round(sum(rets) / n * 100, 2)}

def main():
    reg = load_registry()
    with open(WEEKLY) as f:
        weekly = json.load(f)
    mkt = Market(reg, weekly)
    out = {"family": "lottery (MAX-effect) — coin cross-section",
           "label": "Wing 1 cross-application; adaptations per CONSTRUCTION-SPEC.md",
           "cost_headline": COST, "pot": POT, "runs": {}, "btc_hold": {},
           "placebos": {}, "period_stats": {}, "sensitivity_native_full": {}}
    for w in WINDOWS:
        out["btc_hold"][w] = {k: v for k, v in btc_hold(mkt, w).items()
                              if k != "curve"}
    for line in LINES:
        for w in WINDOWS:
            for rs in ("native", "v9"):
                r = run(mkt, line, w, rs)
                key = f"{line}|{w}|{rs}"
                out["runs"][key] = {k: v for k, v in r.items() if k != "curve"}
                out["runs"][key]["curve"] = r["curve"]
                out["period_stats"][key] = period_stats(r["curve"])
                print(key, r["final"], "BTC", out["btc_hold"][w]["final"],
                      "DD", r["max_dd_pct"], "costs", r["costs_total"], flush=True)
        # cost sensitivity, native FULL
        for c in (0.004, 0.008):
            r = run(mkt, line, "full", "native", cost=c)
            out["sensitivity_native_full"][f"{line}|{c}"] = {
                "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                "costs_total": r["costs_total"]}
            print(line, "sens", c, r["final"], flush=True)
        # placebos: native, FULL + VALIDATION, 20 seeds
        for w in ("full", "validation"):
            finals = []
            for s in range(1, 21):
                r = run(mkt, line, w, "native", seed=s)
                finals.append(r["final"])
            real = out["runs"][f"{line}|{w}|native"]["final"]
            beaten = sum(1 for f_ in finals if real > f_)
            out["placebos"][f"{line}|{w}"] = {
                "seed_finals": finals, "beaten": beaten,
                "median_placebo": sorted(finals)[10]}
            print(line, w, "placebos beaten", beaten, "/20", flush=True)
    # per-coin death/hold diagnostics for FULL native L-V2 (worst-hit line):
    # count how many distinct coins were ever picked per line (FULL native)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f)
    print("done")

if __name__ == "__main__":
    main()
