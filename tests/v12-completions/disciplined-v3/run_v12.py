#!/usr/bin/env python3
"""
disciplined-v3 v12 re-run. Simulation only.
Engine mechanics copied from backtests/v3/disciplined-v3.py (original engine),
generalized only to (a) accept a Market built from either the v3 cache or a
freshly fetched long Yahoo series, and (b) report chained daily curves.
No rule changes. Frozen spec: CONSTRUCTION-SPEC.md in this folder.
  FROZEN v3 cfg = BASE with vol_scaling=False (D1), dd_cap=False (D3), top_k=3 (D6),
  defensive=True, mom_lookback=63, monthly, universe SPY/QQQ/IWM/GLD/TLT.
Costs 0.10%/side + $0.01/sell. Floor ladder $85 -> $100 @125 close -> $125 @150 close;
halt liquidates next open; restart fresh $100 first trading day on/after next Jan 1, chained.
"""
import csv, json, math, os, random, statistics, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.expanduser("~/workspace/stock-app/backtests/v3/data")
LONG_DIR = os.path.join(HERE, "data_long")
os.makedirs(LONG_DIR, exist_ok=True)
UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
COST_RATE = 0.001
SELL_FEE = 0.01
ET = ZoneInfo("America/New_York")

BASE_CFG = {"vol_scaling": True, "defensive": True, "dd_cap": True,
            "mom_lookback": 63, "top_k": 2, "rebalance": "monthly",
            "abs_gate": False, "universe": list(UNIVERSE)}
FROZEN_CFG = dict(BASE_CFG, vol_scaling=False, dd_cap=False, top_k=3)
COMBO_CFG = dict(BASE_CFG, dd_cap=False, top_k=3)  # original D3+D6, vol scaling ON

def load_cache_bars():
    bars = {}
    for t in UNIVERSE:
        rows = []
        with open(os.path.join(CACHE_DIR, f"{t}.csv")) as f:
            for r in csv.DictReader(f):
                rows.append({k: (r[k] if k == "date" else float(r[k])) for k in r})
        bars[t] = rows
    return bars

def fetch_long_bars():
    frm = int(datetime(2008, 1, 1, tzinfo=timezone.utc).timestamp())
    to = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
    bars = {}
    for t in UNIVERSE:
        cache = os.path.join(LONG_DIR, f"{t}.csv")
        if os.path.exists(cache):
            rows = []
            with open(cache) as f:
                for r in csv.DictReader(f):
                    rows.append({k: (r[k] if k == "date" else float(r[k])) for k in r})
            bars[t] = rows; continue
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
               f"?period1={frm}&period2={to}&interval=1d&events=history")
        payload = None
        for host in ("query1", "query2"):
            req = urllib.request.Request(url.replace("query1", host), headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    payload = json.loads(resp.read().decode())
                break
            except Exception:
                continue
        if payload is None:
            raise RuntimeError(f"could not fetch {t}")
        result = payload["chart"]["result"][0]
        ts = result["timestamp"]; q = result["indicators"]["quote"][0]
        rows = []
        for i, tt in enumerate(ts):
            vals = [q[k][i] for k in ("open", "high", "low", "close")]
            if any(v is None for v in vals):
                continue
            d = datetime.fromtimestamp(tt, tz=ET).strftime("%Y-%m-%d")
            rows.append({"date": d, "open": vals[0], "high": vals[1],
                         "low": vals[2], "close": vals[3],
                         "volume": q["volume"][i] or 0})
        rows.sort(key=lambda r: r["date"])
        # dedupe (DST edge duplicates, as original engine implicitly had unique dates via dict)
        seen = {}
        for r in rows: seen[r["date"]] = r
        rows = [seen[d] for d in sorted(seen)]
        with open(cache, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["date","open","high","low","close","volume"])
            w.writeheader(); w.writerows(rows)
        bars[t] = rows
        time.sleep(0.3)
    return bars

class Market:
    def __init__(self, bars):
        self.bars = bars
        self.by_date = {t: {r["date"]: r for r in rows} for t, rows in bars.items()}
        self.closes = {t: [r["close"] for r in rows] for t, rows in bars.items()}
        self.dates_all = [r["date"] for r in bars["SPY"]]
        self.idx_of = {t: {r["date"]: i for i, r in enumerate(rows)} for t, rows in bars.items()}
    def ma200(self, t, date):
        i = self.idx_of[t][date]
        return None if i < 199 else sum(self.closes[t][i-199:i+1]) / 200.0
    def mom(self, t, date, lookback):
        i = self.idx_of[t][date]
        return None if i < lookback else self.closes[t][i] / self.closes[t][i-lookback] - 1.0
    def vol20(self, t, date):
        i = self.idx_of[t][date]
        if i < 20: return None
        c = self.closes[t]
        rets = [math.log(c[j]/c[j-1]) for j in range(i-19, i+1)]
        return statistics.stdev(rets) * math.sqrt(252)

def run_segment(mkt, cfg, start, end, mode="momentum", seed=42):
    universe = cfg["universe"]; dates_all = mkt.dates_all
    period = [d for d in dates_all if start <= d <= end]
    if not period: return None
    first_day, last_day = period[0], period[-1]
    prior_day = {d: dates_all[dates_all.index(d)-1] for d in period}
    selection_days = set(); seen_keys = set()
    for d in period:
        key = d[:7] if cfg["rebalance"] == "monthly" else d[:4] + "Q" + str((int(d[5:7])-1)//3)
        if d == first_day or key not in seen_keys: selection_days.add(d)
        seen_keys.add(key)
    rng = random.Random(seed)
    cash = 100.0; shares = {t: 0.0 for t in universe}; trades = []
    total_costs = 0.0; floor = 85.0; peak_close = 100.0
    pending_exits = set(); liquidate_next_open = False
    halt_trigger_date = None; halted = False; final_balance = None; daily = []
    def equity(pm): return cash + sum(shares[t]*pm[t] for t in universe)
    def do_sell(t, date, price, reason, n=None):
        nonlocal cash, total_costs
        n = shares[t] if n is None else min(n, shares[t])
        if n <= 1e-12 or price <= 0: return
        value = n*price; cost = value*COST_RATE + SELL_FEE
        cash += value - cost; total_costs += cost; shares[t] -= n
        trades.append({"date": date, "ticker": t, "side": "sell", "price": round(price,4),
                       "shares": round(n,6), "value": round(value,2), "reason": reason})
    def do_buy(t, date, price, value, reason):
        nonlocal cash, total_costs
        if value <= 0.005 or price <= 0: return
        cost = value*COST_RATE
        if value + cost > cash + 1e-9:
            value = cash/(1+COST_RATE); cost = value*COST_RATE
        n = value/price; cash -= value + cost; total_costs += cost; shares[t] += n
        trades.append({"date": date, "ticker": t, "side": "buy", "price": round(price,4),
                       "shares": round(n,6), "value": round(value,2), "reason": reason})
    for d in period:
        opens = {t: mkt.by_date[t][d]["open"] for t in universe}
        closes_today = {t: mkt.by_date[t][d]["close"] for t in universe}
        if liquidate_next_open:
            for t in universe:
                if shares[t] > 0: do_sell(t, d, opens[t], "floor-liquidation")
            halted = True; final_balance = cash; daily.append((d, cash)); break
        for t in sorted(pending_exits):
            if shares[t] > 0: do_sell(t, d, opens[t], "trend-exit")
        pending_exits = set()
        if d in selection_days:
            ref = prior_day[d]; info = {}
            for t in universe:
                ma = mkt.ma200(t, ref); c = mkt.by_date[t][ref]["close"]
                elig = (ma is not None and c > ma)
                if elig and cfg["abs_gate"]:
                    r252 = mkt.mom(t, ref, 252); elig = (r252 is not None and r252 > 0)
                info[t] = {"close": c, "ma200": ma, "eligible": elig,
                           "mom": mkt.mom(t, ref, cfg["mom_lookback"]), "vol20": mkt.vol20(t, ref)}
            eligible = [t for t in universe if info[t]["eligible"]]
            if mode == "placebo":
                k = min(cfg["top_k"], len(eligible))
                picks = sorted(rng.sample(sorted(eligible), k)) if k else []
            else:
                ranked = sorted(eligible, key=lambda t: info[t]["mom"], reverse=True)
                picks = ranked[:cfg["top_k"]]
            if len(picks) == 0: share = 0.0
            elif len(picks) == 1: share = 0.5
            else: share = 1.0
            if cfg["defensive"]:
                spy_ma = info["SPY"]["ma200"]
                if spy_ma is not None and info["SPY"]["close"] < spy_ma: share = min(share, 0.5)
            if cfg["dd_cap"]:
                ref_equity = daily[-1][1] if daily else 100.0
                dd = (peak_close - ref_equity)/peak_close if peak_close > 0 else 0.0
                if dd >= 0.07: share = min(share, 0.5)
            weights = {}
            if picks:
                if cfg["vol_scaling"]:
                    inv = {t: (1.0/info[t]["vol20"]) if info[t]["vol20"] else None for t in picks}
                    if any(v is None for v in inv.values()):
                        weights = {t: 1.0/len(picks) for t in picks}
                    else:
                        tot = sum(inv.values()); weights = {t: inv[t]/tot for t in picks}
                else:
                    weights = {t: 1.0/len(picks) for t in picks}
            eq_open = equity(opens)
            targets = {t: share*eq_open*weights.get(t, 0.0) for t in picks}
            for t in universe:
                if shares[t] <= 0: continue
                cur = shares[t]*opens[t]; tgt = targets.get(t, 0.0)
                if cur > tgt + 0.005:
                    do_sell(t, d, opens[t], "monthly-sell-dropout" if t not in targets else "monthly-rebalance-trim", (cur-tgt)/opens[t])
            wants = {}
            for t in picks:
                cur = shares[t]*opens[t]
                if targets[t] > cur + 0.005: wants[t] = targets[t] - cur
            twc = sum(v*(1+COST_RATE) for v in wants.values())
            scale = max(cash, 0.0)/twc if twc > cash and twc > 0 else 1.0
            for t in picks:
                if t in wants: do_buy(t, d, opens[t], wants[t]*scale, "monthly-buy" if shares[t] == 0 else "monthly-rebalance-add")
        eq_close = equity(closes_today); daily.append((d, eq_close))
        if eq_close > peak_close: peak_close = eq_close
        if eq_close >= 150.0: floor = max(floor, 125.0)
        elif eq_close >= 125.0: floor = max(floor, 100.0)
        if eq_close <= floor:
            if d == last_day:
                for t in universe:
                    if shares[t] > 0: do_sell(t, d, closes_today[t], "floor-liquidation")
                halted = True; halt_trigger_date = d; final_balance = cash
            else:
                liquidate_next_open = True; halt_trigger_date = d
            if halted: break
            continue
        for t in universe:
            if shares[t] > 1e-9:
                ma = mkt.ma200(t, d)
                if ma is not None and closes_today[t] < ma: pending_exits.add(t)
    if not halted:
        closes_last = {t: mkt.by_date[t][last_day]["close"] for t in universe}
        for t in universe:
            if shares[t] > 0: do_sell(t, last_day, closes_last[t], "final-liquidation")
        final_balance = cash
    return {"first_day": first_day, "last_day": last_day, "halted": halted,
            "halt_trigger_date": halt_trigger_date, "final_balance": final_balance,
            "total_trades": len(trades), "total_costs": total_costs, "daily": daily, "trades": trades}

def run_window(mkt, cfg, start, end, mode="momentum", seed=42):
    segments = []; seg_start = start
    while True:
        seg = run_segment(mkt, cfg, seg_start, end, mode=mode, seed=seed)
        if seg is None: break
        segments.append(seg)
        if not seg["halted"]: break
        halt_year = int(seg["daily"][-1][0][:4]); nxt = f"{halt_year+1}-01-01"
        if nxt > end: break
        seg_start = nxt
    chained = []; factor = 1.0
    for seg in segments:
        for dte, eq in seg["daily"]: chained.append((dte, eq*factor))
        factor *= seg["final_balance"]/100.0
    chained_final = 100.0*factor
    peak, max_dd = 100.0, 0.0
    for _, eq in chained:
        peak = max(peak, eq); max_dd = max(max_dd, (peak-eq)/peak if peak > 0 else 0.0)
    d0 = datetime.strptime(chained[0][0], "%Y-%m-%d"); d1 = datetime.strptime(chained[-1][0], "%Y-%m-%d")
    years = (d1-d0).days/365.25
    cagr = (chained_final/100.0)**(1.0/years)-1.0 if years > 0 else 0.0
    return {"final_balance": round(chained_final,2), "return_pct": round((chained_final/100.0-1)*100,2),
            "cagr_pct": round(cagr*100,2), "total_trades": sum(s["total_trades"] for s in segments),
            "total_costs": round(sum(s["total_costs"] for s in segments),2),
            "max_drawdown_pct": round(max_dd*100,2), "n_segments": len(segments),
            "halts": [s["halt_trigger_date"] for s in segments if s["halted"]],
            "first_day": chained[0][0], "last_day": chained[-1][0],
            "daily": [[d, round(e,4)] for d, e in chained]}

def benchmark(mkt, start, end):
    period = [d for d in mkt.dates_all if start <= d <= end]
    first_day, last_day = period[0], period[-1]
    spy_open = mkt.by_date["SPY"][first_day]["open"]; spy_close = mkt.by_date["SPY"][last_day]["close"]
    gross = 100.0/spy_open*spy_close
    sh = 100.0/(spy_open*(1+COST_RATE)); net = sh*spy_close*(1-COST_RATE) - SELL_FEE
    peak, max_dd = None, 0.0
    for d in period:
        c = mkt.by_date["SPY"][d]["close"]
        peak = c if peak is None or c > peak else peak
        max_dd = max(max_dd, (peak-c)/peak)
    return {"first_day": first_day, "last_day": last_day, "gross": round(gross,2),
            "net": round(net,2), "max_drawdown_pct": round(max_dd*100,2)}

def brief(r):
    return {k: r[k] for k in ("final_balance","return_pct","cagr_pct","total_trades",
            "total_costs","max_drawdown_pct","n_segments","halts","first_day","last_day")}

def main():
    out = {"family": "disciplined-v3", "frozen_cfg": FROZEN_CFG, "base_cfg": BASE_CFG,
           "combo_cfg_original": COMBO_CFG}
    cache_mkt = Market(load_cache_bars())
    # ---- INTEGRITY: original published finals, original configs, original cache ----
    DESIGN = ("2016-11-21", "2022-12-31"); VALID = ("2023-01-01", "2026-11-20"); FULL = ("2016-11-21", "2026-11-20")
    integ = {}
    integ["BASE_design"] = brief(run_window(cache_mkt, dict(BASE_CFG), *DESIGN))
    integ["BASE_validation"] = brief(run_window(cache_mkt, dict(BASE_CFG), *VALID))
    integ["BASE_full"] = brief(run_window(cache_mkt, dict(BASE_CFG), *FULL))
    integ["COMBO_design"] = brief(run_window(cache_mkt, dict(COMBO_CFG), *DESIGN))
    integ["COMBO_validation"] = brief(run_window(cache_mkt, dict(COMBO_CFG), *VALID))
    integ["COMBO_full"] = brief(run_window(cache_mkt, dict(COMBO_CFG), *FULL))
    integ["PLACEBO_combo_validation_seed42"] = brief(run_window(cache_mkt, dict(COMBO_CFG), *VALID, mode="placebo", seed=42))
    d1_cfg = dict(BASE_CFG, vol_scaling=False)
    integ["D1_design"] = brief(run_window(cache_mkt, d1_cfg, *DESIGN))
    out["integrity"] = integ
    for k, v in integ.items(): print("INTEGRITY", k, json.dumps(v), flush=True)
    # ---- V12 ROADS: frozen spec ----
    roads_cache = {"DECADE": FULL, "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    roads = {}
    for name, (s, e) in roads_cache.items():
        r = run_window(cache_mkt, dict(FROZEN_CFG), s, e)
        twins = []
        for seed in range(1, 21):
            pr = run_window(cache_mkt, dict(FROZEN_CFG), s, e, mode="placebo", seed=seed)
            twins.append({"seed": seed, "final": pr["final_balance"], "max_dd_pct": pr["max_drawdown_pct"]})
        beaten = sum(1 for t in twins if r["final_balance"] > t["final"])
        roads[name] = {"window": [s, e], "data": "v3 cache (2015-2026, split-adj, not div-adj)",
                       **brief(r), "equity_curve": r["daily"],
                       "spy_benchmark": benchmark(cache_mkt, s, e),
                       "placebo_beaten": beaten, "placebo_finals": twins}
        print("ROAD", name, json.dumps(brief(r)), "spy", json.dumps(roads[name]["spy_benchmark"]), "placebos beaten", beaten, flush=True)
    # ---- LONG on fetched long series + DECADE cross-check on same series ----
    try:
        long_mkt = Market(fetch_long_bars())
        s, e = "2010-01-04", "2026-11-20"
        r = run_window(long_mkt, dict(FROZEN_CFG), s, e)
        twins = []
        for seed in range(1, 21):
            pr = run_window(long_mkt, dict(FROZEN_CFG), s, e, mode="placebo", seed=seed)
            twins.append({"seed": seed, "final": pr["final_balance"], "max_dd_pct": pr["max_drawdown_pct"]})
        beaten = sum(1 for t in twins if r["final_balance"] > t["final"])
        roads["LONG"] = {"window": [s, e], "data": "fresh Yahoo fetch 2008-2026 into data_long/ (split-adj, not div-adj)",
                         **brief(r), "equity_curve": r["daily"],
                         "spy_benchmark": benchmark(long_mkt, s, e),
                         "placebo_beaten": beaten, "placebo_finals": twins}
        print("ROAD LONG", json.dumps(brief(r)), "spy", json.dumps(roads["LONG"]["spy_benchmark"]), "placebos beaten", beaten, flush=True)
        xchk = run_window(long_mkt, dict(FROZEN_CFG), *FULL)
        roads["DECADE_crosscheck_fetched"] = {"window": list(FULL), "data": "fresh Yahoo fetch",
                                              **brief(xchk), "equity_curve": xchk["daily"]}
        print("XCHECK DECADE fetched", json.dumps(brief(xchk)), flush=True)
    except Exception as ex:
        out["long_error"] = repr(ex)
        print("LONG FETCH/RUN FAILED:", repr(ex), flush=True)
    out["roads"] = roads
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
