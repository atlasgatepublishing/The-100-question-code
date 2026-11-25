#!/usr/bin/env python3
"""
DISCIPLINED pot v3 — one-variable-at-a-time ablation study. Simulation only.

Base = v2 exactly (see ../v2/disciplined-v2.py): monthly selection from
SPY/QQQ/IWM/GLD/TLT; eligible = close above 200-day MA (signals from the
prior trading day's close); rank by trailing 63-day momentum, hold top 2;
inverse-20-day-volatility weights; defensive mode (SPY below its 200-day MA
at a selection -> invested share capped at 50%); drawdown ladder (pot 7%+
below peak close at a selection -> share capped at 50%); trend exit on a
close below the 200-day MA (sell next open); costs 0.10%/side + $0.01/sell;
Terry's floor ladder ($85; $100 at a $125 close; $125 at a $150 close; close
at/below floor -> liquidate next open, run ends; a halted pot restarts fresh
at $100 on the first trading day on/after the next Jan 1, chained).

Each ablation flips exactly ONE config flag off the base:
  D1  vol_scaling=False        (equal weights instead of inverse-vol)
  D2  defensive=False
  D3  dd_cap=False
  D4  mom_lookback=126
  D5  mom_lookback=252
  D6  top_k=3
  D7  top_k=1
  D8  rebalance='quarterly'    (trend exits still daily)
  D9  abs_gate=True            (eligible also needs trailing 252d return > 0)
  D10 universe += XLK, XLF, XLV, XLE

Protocol: base + D1..D10 on DESIGN 2016-11-21 -> 2022-12-31. Best two
singles (by design final balance) combined -> one more design run. Then
base, best single, best combo run ONCE on VALIDATION 2023-01-01 ->
2026-11-20, plus a random-pick placebo (seed 42) of the best combo there.

Data: free Yahoo Finance chart API, daily bars, split-adjusted, NOT
dividend-adjusted, fetched 2015-01-01 -> 2026-11-20 (cache in data/).
"""
import csv, json, math, os, random, statistics, time, urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
os.makedirs(DATA_DIR, exist_ok=True)

BASE_UNIVERSE = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
SECTORS = ["XLK", "XLF", "XLV", "XLE"]
ALL_TICKERS = BASE_UNIVERSE + SECTORS
FETCH_FROM = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp())
FETCH_TO = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
COST_RATE = 0.001
SELL_FEE = 0.01
ET = ZoneInfo("America/New_York")
PLACEBO_SEED = 42

BASE_CFG = {
    "vol_scaling": True,
    "defensive": True,
    "dd_cap": True,
    "mom_lookback": 63,
    "top_k": 2,
    "rebalance": "monthly",
    "abs_gate": False,
    "universe": list(BASE_UNIVERSE),
}

ABLATIONS = [
    ("D1", "volatility scaling REMOVED (equal weights)", {"vol_scaling": False}),
    ("D2", "defensive mode REMOVED", {"defensive": False}),
    ("D3", "drawdown cap REMOVED", {"dd_cap": False}),
    ("D4", "momentum lookback 126d (was 63d)", {"mom_lookback": 126}),
    ("D5", "momentum lookback 252d (was 63d)", {"mom_lookback": 252}),
    ("D6", "hold top 3 eligible (was top 2)", {"top_k": 3}),
    ("D7", "hold only top 1 (was top 2)", {"top_k": 1}),
    ("D8", "quarterly rebalance (was monthly)", {"rebalance": "quarterly"}),
    ("D9", "absolute-momentum gate added (252d return > 0)", {"abs_gate": True}),
    ("D10", "universe + XLK/XLF/XLV/XLE", {"universe": BASE_UNIVERSE + SECTORS}),
]


def fetch(ticker):
    cache = os.path.join(DATA_DIR, f"{ticker}.csv")
    if os.path.exists(cache):
        rows = []
        with open(cache) as f:
            for r in csv.DictReader(f):
                rows.append({k: (r[k] if k == "date" else float(r[k]))
                             for k in r})
        return rows
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={FETCH_FROM}&period2={FETCH_TO}&interval=1d"
           f"&events=history")
    payload = None
    for host in ("query1", "query2"):
        req = urllib.request.Request(url.replace("query1", host), headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                          "AppleWebKit/537.36"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
            break
        except Exception:
            continue
    if payload is None:
        raise RuntimeError(f"could not fetch {ticker}")
    result = payload["chart"]["result"][0]
    ts = result["timestamp"]
    q = result["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        vals = [q[k][i] for k in ("open", "high", "low", "close")]
        if any(v is None for v in vals):
            continue
        d = datetime.fromtimestamp(t, tz=ET).strftime("%Y-%m-%d")
        rows.append({"date": d, "open": vals[0], "high": vals[1],
                     "low": vals[2], "close": vals[3],
                     "volume": q["volume"][i] or 0})
    rows.sort(key=lambda r: r["date"])
    with open(cache, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "open", "high", "low",
                                          "close", "volume"])
        w.writeheader()
        w.writerows(rows)
    time.sleep(0.3)
    return rows


class Market:
    def __init__(self):
        self.bars = {t: fetch(t) for t in ALL_TICKERS}
        self.by_date = {t: {r["date"]: r for r in rows}
                        for t, rows in self.bars.items()}
        self.closes = {t: [r["close"] for r in rows]
                       for t, rows in self.bars.items()}
        self.dates_all = [r["date"] for r in self.bars["SPY"]]
        self.idx_of = {t: {r["date"]: i for i, r in enumerate(rows)}
                       for t, rows in self.bars.items()}

    def ma200(self, t, date):
        i = self.idx_of[t][date]
        if i < 199:
            return None
        return sum(self.closes[t][i - 199:i + 1]) / 200.0

    def mom(self, t, date, lookback):
        i = self.idx_of[t][date]
        if i < lookback:
            return None
        return self.closes[t][i] / self.closes[t][i - lookback] - 1.0

    def vol20(self, t, date):
        i = self.idx_of[t][date]
        if i < 20:
            return None
        c = self.closes[t]
        rets = [math.log(c[j] / c[j - 1]) for j in range(i - 19, i + 1)]
        return statistics.stdev(rets) * math.sqrt(252)


def run_segment(mkt, cfg, start, end, mode="momentum", seed=PLACEBO_SEED):
    """One fresh $100 pot, first trading day on/after `start` through `end`.
    Mechanics copied from disciplined-v2.run_sim; cfg flips one variable."""
    universe = cfg["universe"]
    dates_all = mkt.dates_all
    period = [d for d in dates_all if start <= d <= end]
    if not period:
        return None
    first_day, last_day = period[0], period[-1]
    prior_day = {d: dates_all[dates_all.index(d) - 1] for d in period}

    selection_days = set()
    seen_keys = set()
    for d in period:
        if cfg["rebalance"] == "monthly":
            key = d[:7]
        else:  # quarterly
            key = d[:4] + "Q" + str((int(d[5:7]) - 1) // 3)
        if d == first_day or key not in seen_keys:
            selection_days.add(d)
        seen_keys.add(key)

    rng = random.Random(seed)
    cash = 100.0
    shares = {t: 0.0 for t in universe}
    trades = []
    total_costs = 0.0
    floor = 85.0
    peak_close = 100.0
    pending_exits = set()
    liquidate_next_open = False
    halt_trigger_date = None
    halted = False
    final_balance = None
    daily = []

    def equity(price_map):
        return cash + sum(shares[t] * price_map[t] for t in universe)

    def do_sell(t, date, price, reason, n=None):
        nonlocal cash, total_costs
        n = shares[t] if n is None else min(n, shares[t])
        if n <= 1e-12 or price <= 0:
            return
        value = n * price
        cost = value * COST_RATE + SELL_FEE
        cash += value - cost
        total_costs += cost
        shares[t] -= n
        trades.append({"date": date, "ticker": t, "side": "sell",
                       "price": round(price, 4), "shares": round(n, 6),
                       "value": round(value, 2), "reason": reason})

    def do_buy(t, date, price, value, reason):
        nonlocal cash, total_costs
        if value <= 0.005 or price <= 0:
            return
        cost = value * COST_RATE
        if value + cost > cash + 1e-9:
            value = cash / (1 + COST_RATE)
            cost = value * COST_RATE
        n = value / price
        cash -= value + cost
        total_costs += cost
        shares[t] += n
        trades.append({"date": date, "ticker": t, "side": "buy",
                       "price": round(price, 4), "shares": round(n, 6),
                       "value": round(value, 2), "reason": reason})

    for d in period:
        opens = {t: mkt.by_date[t][d]["open"] for t in universe}
        closes_today = {t: mkt.by_date[t][d]["close"] for t in universe}

        if liquidate_next_open:
            for t in universe:
                if shares[t] > 0:
                    do_sell(t, d, opens[t], "floor-liquidation")
            halted = True
            final_balance = cash
            daily.append((d, cash))
            break

        for t in sorted(pending_exits):
            if shares[t] > 0:
                do_sell(t, d, opens[t], "trend-exit")
        pending_exits = set()

        if d in selection_days:
            ref = prior_day[d]
            info = {}
            for t in universe:
                ma = mkt.ma200(t, ref)
                c = mkt.by_date[t][ref]["close"]
                elig = (ma is not None and c > ma)
                if elig and cfg["abs_gate"]:
                    r252 = mkt.mom(t, ref, 252)
                    elig = (r252 is not None and r252 > 0)
                info[t] = {"close": c, "ma200": ma, "eligible": elig,
                           "mom": mkt.mom(t, ref, cfg["mom_lookback"]),
                           "vol20": mkt.vol20(t, ref)}
            eligible = [t for t in universe if info[t]["eligible"]]
            if mode == "placebo":
                k = min(cfg["top_k"], len(eligible))
                picks = sorted(rng.sample(sorted(eligible), k)) if k else []
            else:
                ranked = sorted(eligible,
                                key=lambda t: info[t]["mom"], reverse=True)
                picks = ranked[:cfg["top_k"]]

            if len(picks) == 0:
                share = 0.0
            elif len(picks) == 1:
                share = 0.5
            else:
                share = 1.0
            if cfg["defensive"]:
                spy_ma = info["SPY"]["ma200"]
                if spy_ma is not None and info["SPY"]["close"] < spy_ma:
                    share = min(share, 0.5)
            if cfg["dd_cap"]:
                ref_equity = daily[-1][1] if daily else 100.0
                dd_from_peak = ((peak_close - ref_equity) / peak_close
                                if peak_close > 0 else 0.0)
                if dd_from_peak >= 0.07:
                    share = min(share, 0.5)

            weights = {}
            if picks:
                if cfg["vol_scaling"]:
                    inv = {}
                    for t in picks:
                        v = info[t]["vol20"]
                        inv[t] = (1.0 / v) if (v and v > 1e-9) else None
                    if any(v is None for v in inv.values()):
                        weights = {t: 1.0 / len(picks) for t in picks}
                    else:
                        tot = sum(inv.values())
                        weights = {t: inv[t] / tot for t in picks}
                else:
                    weights = {t: 1.0 / len(picks) for t in picks}

            eq_open = equity(opens)
            targets = {t: share * eq_open * weights.get(t, 0.0)
                       for t in picks}
            for t in universe:
                if shares[t] <= 0:
                    continue
                cur = shares[t] * opens[t]
                tgt = targets.get(t, 0.0)
                if cur > tgt + 0.005:
                    reason = ("monthly-sell-dropout" if t not in targets
                              else "monthly-rebalance-trim")
                    do_sell(t, d, opens[t], reason, (cur - tgt) / opens[t])
            wants = {}
            for t in picks:
                cur = shares[t] * opens[t]
                if targets[t] > cur + 0.005:
                    wants[t] = targets[t] - cur
            total_want_cost = sum(v * (1 + COST_RATE) for v in wants.values())
            scale = 1.0
            if total_want_cost > cash and total_want_cost > 0:
                scale = max(cash, 0.0) / total_want_cost
            for t in picks:
                if t in wants:
                    reason = ("monthly-buy" if shares[t] == 0
                              else "monthly-rebalance-add")
                    do_buy(t, d, opens[t], wants[t] * scale, reason)

        eq_close = equity(closes_today)
        daily.append((d, eq_close))
        if eq_close > peak_close:
            peak_close = eq_close

        if eq_close >= 150.0:
            floor = max(floor, 125.0)
        elif eq_close >= 125.0:
            floor = max(floor, 100.0)
        if eq_close <= floor:
            if d == last_day:
                for t in universe:
                    if shares[t] > 0:
                        do_sell(t, d, closes_today[t], "floor-liquidation")
                halted = True
                halt_trigger_date = d
                final_balance = cash
            else:
                liquidate_next_open = True
                halt_trigger_date = d
            if halted:
                break
            continue

        for t in universe:
            if shares[t] > 1e-9:
                ma = mkt.ma200(t, d)
                if ma is not None and closes_today[t] < ma:
                    pending_exits.add(t)

    if not halted:
        closes_last = {t: mkt.by_date[t][last_day]["close"] for t in universe}
        for t in universe:
            if shares[t] > 0:
                do_sell(t, last_day, closes_last[t], "final-liquidation")
        final_balance = cash

    return {"first_day": first_day, "last_day": last_day, "halted": halted,
            "halt_trigger_date": halt_trigger_date,
            "final_balance": final_balance, "total_trades": len(trades),
            "total_costs": total_costs, "daily": daily, "trades": trades}


def run_window(mkt, cfg, start, end, mode="momentum", seed=PLACEBO_SEED):
    """Full window with v2's restart convention; returns chained stats."""
    segments = []
    seg_start = start
    while True:
        seg = run_segment(mkt, cfg, seg_start, end, mode=mode, seed=seed)
        if seg is None:
            break
        segments.append(seg)
        if not seg["halted"]:
            break
        halt_year = int(seg["daily"][-1][0][:4])
        nxt = f"{halt_year + 1}-01-01"
        if nxt > end:
            break
        seg_start = nxt

    chained_daily = []
    factor = 1.0
    for seg in segments:
        for dte, eq in seg["daily"]:
            chained_daily.append((dte, eq * factor))
        factor *= seg["final_balance"] / 100.0
    chained_final = 100.0 * factor

    peak, max_dd = 100.0, 0.0
    for _, eq in chained_daily:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    d0 = datetime.strptime(chained_daily[0][0], "%Y-%m-%d")
    d1 = datetime.strptime(chained_daily[-1][0], "%Y-%m-%d")
    years = (d1 - d0).days / 365.25
    cagr = (chained_final / 100.0) ** (1.0 / years) - 1.0 if years > 0 else 0.0

    return {
        "final_balance": round(chained_final, 2),
        "return_pct": round((chained_final / 100.0 - 1.0) * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "total_trades": sum(s["total_trades"] for s in segments),
        "total_costs": round(sum(s["total_costs"] for s in segments), 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "n_segments": len(segments),
        "halts": [s["halt_trigger_date"] for s in segments if s["halted"]],
        "first_day": chained_daily[0][0], "last_day": chained_daily[-1][0],
        "daily": [(d, round(e, 4)) for d, e in chained_daily],
        "segments": [{k: s[k] for k in ("first_day", "last_day", "halted",
                                        "halt_trigger_date", "total_trades",
                                        "total_costs")}
                     for s in segments] +
                    [{"final_balance": round(s["final_balance"], 2)}
                     for s in segments],
    }


def benchmark(mkt, start, end):
    period = [d for d in mkt.dates_all if start <= d <= end]
    first_day, last_day = period[0], period[-1]
    spy_open = mkt.by_date["SPY"][first_day]["open"]
    spy_close = mkt.by_date["SPY"][last_day]["close"]
    gross = 100.0 / spy_open * spy_close
    sh = 100.0 / (spy_open * (1 + COST_RATE))
    net = sh * spy_close * (1 - COST_RATE) - SELL_FEE
    # SPY max drawdown on closes over the window
    peak, max_dd = None, 0.0
    for d in period:
        c = mkt.by_date["SPY"][d]["close"]
        if peak is None or c > peak:
            peak = c
        if peak:
            max_dd = max(max_dd, (peak - c) / peak)
    return {"first_day": first_day, "last_day": last_day,
            "gross": round(gross, 2), "net": round(net, 2),
            "net_pct": round((net / 100 - 1) * 100, 2),
            "max_drawdown_pct": round(max_dd * 100, 2)}


def year_table(mkt, result):
    """Per-calendar-year returns from a chained daily series + SPY."""
    daily = result["daily"]
    years = {}
    for dte, eq in daily:
        years.setdefault(int(dte[:4]), []).append((dte, eq))
    spy_close = {r["date"]: r["close"] for r in mkt.bars["SPY"]}
    rows = []
    prev_eq = 100.0
    idx = mkt.dates_all.index(daily[0][0])
    prev_spy = spy_close[mkt.dates_all[idx - 1]]
    for y in sorted(years):
        rows_y = years[y]
        end_eq = rows_y[-1][1]
        spy_end = spy_close[rows_y[-1][0]]
        rows.append({
            "year": y,
            "pot_return_pct": round((end_eq / prev_eq - 1) * 100, 2),
            "spy_return_pct": round((spy_end / prev_spy - 1) * 100, 2),
            "pot_end": round(end_eq, 2)})
        prev_eq = end_eq
        prev_spy = spy_end
    return rows


def brief(name, r):
    return {"name": name, "final": r["final_balance"],
            "return_pct": r["return_pct"], "cagr_pct": r["cagr_pct"],
            "trades": r["total_trades"], "costs": r["total_costs"],
            "max_dd_pct": r["max_drawdown_pct"], "halts": r["halts"],
            "segments": r["n_segments"]}


def main():
    mkt = Market()
    out = {"trial_log": []}
    trial_no = [0]

    def log(kind, name, window, note=""):
        trial_no[0] += 1
        out["trial_log"].append({"n": trial_no[0], "kind": kind,
                                 "name": name, "window": window,
                                 "note": note})

    # --- replication check: base config on v2's Window A must give $100.45 ---
    chk = run_window(mkt, dict(BASE_CFG), "2025-11-21", "2026-11-20")
    out["replication_check_windowA"] = brief("base on v2 Window A", chk)
    print("REPLICATION (expect final 100.45, trades 35, costs 1.29):",
          json.dumps(out["replication_check_windowA"]))

    DESIGN = ("2016-11-21", "2022-12-31")
    VALID = ("2023-01-01", "2026-11-20")
    out["benchmarks"] = {
        "design": benchmark(mkt, *DESIGN),
        "validation": benchmark(mkt, *VALID)}

    # --- design phase: base + 10 singles ---
    design = {}
    base = run_window(mkt, dict(BASE_CFG), *DESIGN)
    design["BASE"] = base
    log("design", "BASE (v2)", "design")
    print("DESIGN BASE:", json.dumps(brief("BASE", base)))

    singles = {}
    for tag, desc, delta in ABLATIONS:
        cfg = dict(BASE_CFG)
        cfg.update(delta)
        if "universe" in delta:
            cfg["universe"] = list(delta["universe"])
        r = run_window(mkt, cfg, *DESIGN)
        singles[tag] = (desc, delta, r)
        design[tag] = r
        log("design", tag, "design", desc)
        print(f"DESIGN {tag}:", json.dumps(brief(tag, r)))

    # --- best two singles -> combo on design ---
    ranked = sorted(singles.items(),
                    key=lambda kv: (-kv[1][2]["final_balance"],
                                    kv[1][2]["max_drawdown_pct"]))
    top2 = ranked[:2]
    combo_delta = {}
    for tag, (desc, delta, r) in top2:
        combo_delta.update(delta)
    combo_cfg = dict(BASE_CFG)
    combo_cfg.update(combo_delta)
    if "universe" in combo_delta:
        combo_cfg["universe"] = list(combo_delta["universe"])
    combo_name = "+".join(t for t, _ in top2) + " combo"
    combo_design = run_window(mkt, combo_cfg, *DESIGN)
    design["COMBO"] = combo_design
    log("design", combo_name, "design",
        "combined best two singles: " + ", ".join(
            f"{t} ({d})" for t, (d, _dl, _r) in top2))
    print("DESIGN COMBO:", json.dumps(brief(combo_name, combo_design)))
    out["design"] = {k: brief(k, v) for k, v in design.items()}
    out["design_ranking"] = [t for t, _ in
                             sorted(design.items(),
                                    key=lambda kv: -kv[1]["final_balance"])]
    out["best_singles"] = [t for t, _ in top2]

    best_single_tag = top2[0][0]
    best_single_delta = top2[0][1][1]
    best_single_cfg = dict(BASE_CFG)
    best_single_cfg.update(best_single_delta)
    if "universe" in best_single_delta:
        best_single_cfg["universe"] = list(best_single_delta["universe"])

    # --- validation phase: frozen configs, run once ---
    val = {}
    val["BASE"] = run_window(mkt, dict(BASE_CFG), *VALID)
    log("validation", "BASE (v2)", "validation")
    val[best_single_tag] = run_window(mkt, best_single_cfg, *VALID)
    log("validation", best_single_tag, "validation", "best single, frozen")
    val["COMBO"] = run_window(mkt, combo_cfg, *VALID)
    log("validation", combo_name, "validation", "best combo, frozen")
    val["PLACEBO"] = run_window(mkt, combo_cfg, *VALID, mode="placebo",
                                seed=PLACEBO_SEED)
    log("validation", "PLACEBO of " + combo_name, "validation",
        f"random picks from eligible set, seed {PLACEBO_SEED}, "
        "same machinery as combo")
    out["validation"] = {k: brief(k, v) for k, v in val.items()}
    out["validation_years"] = {
        k: year_table(mkt, v) for k, v in val.items()
        if k in ("BASE", best_single_tag, "COMBO")}
    out["best_single_tag"] = best_single_tag
    out["combo_name"] = combo_name
    out["combo_delta"] = {k: (v if not isinstance(v, list) else v)
                          for k, v in combo_delta.items()}
    for k, v in val.items():
        print(f"VALIDATION {k}:", json.dumps(brief(k, v)))
    print("BENCH design:", json.dumps(out["benchmarks"]["design"]))
    print("BENCH valid: ", json.dumps(out["benchmarks"]["validation"]))
    print("YEARS:", json.dumps(out["validation_years"]))

    # --- full-period picture: one continuous $100 run, 2016 -> 2026 ---
    # Same restart convention as v2 Window B (a halt restarts fresh $100 the
    # next Jan 1, chained). This is the picture, NOT the judge: the design /
    # validation split above is the judge.
    FULL = ("2016-11-21", "2026-11-20")
    full = {}
    full["BASE"] = run_window(mkt, dict(BASE_CFG), *FULL)
    log("full-period", "BASE (v2)", "full-period",
        "continuous run, picture only")
    full["COMBO"] = run_window(mkt, combo_cfg, *FULL)
    log("full-period", combo_name, "full-period",
        "continuous run, picture only")
    out["full_period"] = {k: brief(k, v) for k, v in full.items()}
    out["full_period_years"] = {k: year_table(mkt, v)
                                for k, v in full.items()}
    out["benchmarks"]["full_period"] = benchmark(mkt, *FULL)
    for k, v in full.items():
        print(f"FULL {k}:", json.dumps(brief(k, v)))
    print("BENCH full:  ", json.dumps(out["benchmarks"]["full_period"]))
    print("FULL YEARS:", json.dumps(out["full_period_years"]))

    with open(os.path.join(HERE, "disciplined-v3-results.json"), "w") as f:
        json.dump(out, f, indent=2)
    print("TOTAL LOGGED RUNS:", trial_no[0])


if __name__ == "__main__":
    main()
