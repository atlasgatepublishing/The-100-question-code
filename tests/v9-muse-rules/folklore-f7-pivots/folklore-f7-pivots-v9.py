#!/usr/bin/env python3
"""
FOLKLORE TEST F-7 — MONTHLY PIVOT-POINT TREND (SPY) — Terry's AI stock app.
Simulation only.

SPEC FROZEN VERBATIM from ~/workspace/stock-app/research/v7-completeness/
folklore-audit.md, Spec F-7:

  "Universe/data: SPY daily OHLC. Classic floor-trader pivot from the prior
   month's high H, low L, close C: P = (H + L + C)/3 (R1/S1 etc. are computed
   by the system but the frozen trade rule uses P only — the pivot-as-trend-
   line is the most common mechanical form).
   Rule (frozen): on the first trading day of each month, if SPY's prior
   month closed above that month's pivot P -> hold SPY for the coming month;
   if below -> hold cash. Execute at the first open of the month."

SHARED CHASSIS (audit preamble, all folklore specs): $100 starting pot;
execution at the next session's open after a signal computed on closes;
costs 0.10% of trade value per side plus $0.01 per sell order; plain -15%
floor at the pot level (a close at or below $85 liquidates everything to
cash at the next open and ends the run, exactly as in the champion engine);
judging windows continuous 2019-01-01->2026-11-20 and validation
2023-01-01->2026-11-20; benchmarks SPY buy-hold net of the same costs and
the 20-seed random placebo distribution on the same universe and cadence;
promotion requires beating SPY AND the placebo median on validation.

FORCED READINGS (stated here, before any result):
  1. PIVOT BASIS. The program's price basis is split/dividend-adjusted (the
     champion engine scales opens by adjclose/close and values on adjclose).
     H and L are therefore scaled by the same adjclose/close ratio the
     engine applies to opens, and C is the adjclose: P and the close-vs-
     pivot comparison live on the adjusted basis throughout.
  2. "THAT MONTH'S PIVOT" = the pivot computed FROM the prior month's
     H, L, C (the pivot in force for the coming month, per floor-trader
     practice), compared against the prior month's close C — the same C
     that enters P. The decision is made on the first trading day of the
     new month and executed at that day's open.
  3. TIE. A prior-month close exactly equal to P counts as NOT above ->
     cash. (Measure-zero with real prices; stated for completeness.)
  4. PLACEBO. The audit requires a "20-seed random placebo distribution on
     the same universe and cadence" without pinning the random rule. For a
     single-asset monthly timer the reading used here: for each of the
     program's seeds 1..20, every month's hold/cash state is an independent
     coin flip (p = 0.5, random.Random(seed)), executed identically (first
     open of the month, same costs, same floor, same end-of-window
     liquidation at the final close).
  5. START STATE / FLOOR / END. The pot starts in cash; each window's
     first month is positioned per its signal (prior-month bars exist in
     the cache from 2017-06). The floor is checked on daily closes exactly
     as in the champion engine. End of window: liquidate at the final
     close, as the engine does. Day cadence = SPY's own trading days (the
     only sensible reading for a single-asset test).
  6. FOLDS (instrumentation only, house format for single-asset tests —
     cf. CAPE timing v6): fresh $100 pots per calendar year 2020-2026,
     each positioned from its first month per the signal, are reported
     alongside; they do not alter the spec or the verdict bar.

Data: Yahoo Finance chart API payload for SPY, reused read-only from the
champion program's cache (~/workspace/stock-app/backtests/v4/data/).
Integrity: this script first replicates the program's published SPY net
figures ($313.62 continuous / $187.77 validation) with the engine's own
spy_net formula on the same bars; the run aborts if they do not match.
"""
import json, math, os, random, time

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.expanduser("~/workspace/stock-app/backtests/v4/data")

START_CASH = 100.0
FLOOR0 = 85.0
FULL = ("2019-01-01", "2026-11-20")
VALIDATION = ("2023-01-01", "2026-11-20")
PLACEBO_SEEDS = list(range(1, 21))          # program seeds: 1..20


# ------------------------------------------------------------------ prices
def load_spy_bars():
    """SPY bars on the champion engine's basis: o/h/l scaled by the
    adjclose/close ratio (the engine scales opens exactly this way),
    c = adjclose."""
    with open(os.path.join(SHARED, "px_SPY.json"), "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d,
                     "o": (o * ratio if o else a),
                     "h": (h * ratio if h else a),
                     "l": (l * ratio if l else a),
                     "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


def spy_net(bars, start, end, start_cash):
    """The champion engine's spy_net formula, verbatim in substance:
    buy at the first day's open (0.10% buy cost), value at the last close,
    sell cost 0.10% + $0.01."""
    days = [b for b in bars if start <= b["d"] <= end]
    first, last = days[0], days[-1]
    o = first["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    val = sh * last["c"]
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost


# ------------------------------------------------------------------ signals
def monthly_pivots(bars):
    """For every calendar month present in the bars, the pivot in force for
    that month: P from the PRIOR calendar month's bars, and the prior
    month's close C. Returns {(y, m): {"H":..,"L":..,"C":..,"P":..}}."""
    by_month = {}
    for b in bars:
        by_month.setdefault((int(b["d"][:4]), int(b["d"][5:7])), []).append(b)
    out = {}
    months = sorted(by_month)
    for i in range(1, len(months)):
        prev = by_month[months[i - 1]]
        H = max(b["h"] for b in prev)
        L = min(b["l"] for b in prev)
        C = prev[-1]["c"]
        out[months[i]] = {"H": H, "L": L, "C": C, "P": (H + L + C) / 3.0,
                          "prev_month": "%04d-%02d" % months[i - 1]}
    return out


# ------------------------------------------------------------------ engine
def run_pot(bars, pivots, start, end, start_cash=START_CASH, floor=FLOOR0,
            placebo_rng=None, label=""):
    """Monthly pivot trend on SPY. If placebo_rng is given, each month's
    hold/cash state is a coin flip instead of the pivot signal."""
    days = [b for b in bars if start <= b["d"] <= end]
    if not days:
        return None
    cash = start_cash
    shares = 0.0
    trades = []
    total_costs = 0.0
    curve = []
    decisions = []
    months_invested = 0
    months_total = 0
    switches = 0
    cur_month = None
    target_invested = False

    def value_at_close(b):
        return cash + shares * b["c"]

    for di, b in enumerate(days):
        mk = (int(b["d"][:4]), int(b["d"][5:7]))
        if mk != cur_month:
            # first trading day of a new month: decide, execute at the open
            cur_month = mk
            months_total += 1
            if placebo_rng is not None:
                target_invested = placebo_rng.random() < 0.5
                decisions.append((b["d"], "coin", target_invested))
            else:
                pv = pivots[mk]
                target_invested = pv["C"] > pv["P"]
                decisions.append((b["d"], "pivot", target_invested,
                                  round(pv["H"], 2), round(pv["L"], 2),
                                  round(pv["C"], 2), round(pv["P"], 2),
                                  pv["prev_month"]))
            if target_invested:
                months_invested += 1
            if target_invested and shares == 0.0:
                buy_val = cash / 1.001
                if buy_val > 0.005:
                    sh = buy_val / b["o"]
                    c = buy_val * 0.001
                    cash -= buy_val + c
                    total_costs += c
                    shares = sh
                    switches += 1
                    trades.append((b["d"], "BUY", sh, b["o"], buy_val, c))
            elif not target_invested and shares > 0.0:
                val = shares * b["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((b["d"], "SELL", shares, b["o"], val, c))
                shares = 0.0
                switches += 1
        v = value_at_close(b)
        curve.append((b["d"], v))
        if v <= floor and di < len(days) - 1:
            nd = days[di + 1]
            halt_info = {"signal_date": b["d"], "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            if shares > 0.0:
                val = shares * nd["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nd["d"], "SELL-HALT", shares, nd["o"], val, c))
                shares = 0.0
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": b["d"], "end": nd["d"],
                    "halt_info": halt_info, "curve": curve,
                    "decisions": decisions, "months_invested": months_invested,
                    "months_total": months_total, "switches": switches}
    last = days[-1]
    if shares > 0.0:
        val = shares * last["c"]
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((last["d"], "SELL-END", shares, last["c"], val, c))
        shares = 0.0
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last["d"],
            "halt_info": None, "curve": curve, "decisions": decisions,
            "months_invested": months_invested, "months_total": months_total,
            "switches": switches}


def curve_stats(r):
    curve = r["curve"]
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = round(v, 2)
    return {"final": round(r["final"], 2),
            "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
            "orders": len(r["trades"]), "costs": round(r["costs"], 2),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "worst_close_above_floor": round(worst_v - FLOOR0, 2),
            "months_invested": r["months_invested"],
            "months_total": r["months_total"],
            "pct_months_invested": round(100.0 * r["months_invested"]
                                         / r["months_total"], 1)
            if r["months_total"] else None,
            "switches": r["switches"],
            "year_end_closes": year_end}


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def placebo_block(bars, pivots, start, end, ranked_final, tag):
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_pot(bars, pivots, start, end, START_CASH, FLOOR0,
                     placebo_rng=rng, label=f"{tag} PLACEBO {seed}")
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2),
                     "months_invested": pr["months_invested"]})
        print(f"  {tag} PLACEBO seed {seed:2d}: final=${pr['final']:,.2f} "
              f"halted={pr['halted']} months_in={pr['months_invested']}",
              flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    pctile = 100.0 * (below + 0.5 * ties) / len(finals)
    return {"median": round(_pct(srt, 0.50), 2),
            "q1": round(_pct(srt, 0.25), 2), "q3": round(_pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for p in rows if p["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_percentile": round(pctile, 1),
            "seeds_beaten": below, "rows": rows}


def main():
    bars = load_spy_bars()
    pivots = monthly_pivots(bars)
    out = {"strategy": "FOLKLORE F-7 MONTHLY PIVOT TREND: SPY only; on the "
                       "first trading day of each month hold SPY if the "
                       "prior month's close C > prior-month pivot "
                       "P=(H+L+C)/3, else cash; $100, plain -15% floor",
           "pot": START_CASH, "floor": FLOOR0,
           "forced_readings": "see script header (pivot basis, 'that "
                              "month's pivot', tie->cash, placebo=monthly "
                              "coin flip seeds 1..20)"}

    # ---- integrity: replicate the program's published SPY nets
    for tag, (ws, we), expect in (("FULL", FULL, 313.62),
                                  ("VALIDATION", VALIDATION, 187.77)):
        spy, _ = spy_net(bars, ws, we, START_CASH)
        ok = abs(spy - expect) < 0.005
        print(f"REPLICATION {tag}: SPY net=${spy:,.2f} expected=${expect:,.2f} "
              f"match={ok}", flush=True)
        out[f"replication_{tag.lower()}"] = {"spy_net": round(spy, 2),
                                             "expected": expect, "match": ok}
        if not ok:
            raise SystemExit("REPLICATION FAILED — variant numbers untrusted")

    # ---- ranked runs + SPY + placebo, both windows
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VALIDATION)):
        spy, spy_costs = spy_net(bars, ws, we, START_CASH)
        r = run_pot(bars, pivots, ws, we, START_CASH, FLOOR0,
                    label=f"{tag} F7-PIVOT")
        st = curve_stats(r)
        st.update({"start": ws, "end": we, "spy_net_final": round(spy, 2),
                   "spy_return_pct": round(spy / START_CASH * 100 - 100, 2),
                   "spy_costs": round(spy_costs, 2),
                   "decisions": r["decisions"]})
        print(f"{tag} F7-PIVOT: final=${r['final']:,.2f} "
              f"({st['return_pct']:+.2f}%) maxDD={st['max_drawdown_pct']}% "
              f"orders={st['orders']} costs=${st['costs']} "
              f"halted={r['halted']} months_in={r['months_invested']}/"
              f"{r['months_total']} | SPY=${spy:,.2f}", flush=True)
        print(f"   worst close ${st['worst_close']} on {st['worst_close_date']} "
              f"(floor margin ${st['worst_close_above_floor']})", flush=True)
        st["placebo"] = placebo_block(bars, pivots, ws, we, r["final"], tag)
        pl = st["placebo"]
        print(f"{tag} PLACEBO: median=${pl['median']:,.2f} "
              f"best=${pl['best']:,.2f} worst=${pl['worst']:,.2f} "
              f"halted={pl['halted_count']}/20 | RANKED "
              f"${pl['ranked_final']:,.2f} = {pl['ranked_percentile']}th "
              f"pctile (beat {pl['seeds_beaten']}/20)", flush=True)
        out[tag.lower()] = st

    # ---- walk-forward folds, fresh $100 per calendar year
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot(bars, pivots, fs, fe, START_CASH, FLOOR0,
                     label=f"FOLD {y}")
        fspy, _ = spy_net(bars, fs, fe, START_CASH)
        fst = curve_stats(fr)
        row = {"year": y, "start": fs, "end": fe, "final": fst["final"],
               "return_pct": fst["return_pct"],
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"],
               "months_invested": fst["months_invested"],
               "months_total": fst["months_total"]}
        folds.append(row)
        print(f"FOLD {y}: F7 ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) "
              f"vs SPY ${fspy:,.2f} ({row['spy_return_pct']:+.2f}%) "
              f"beat={row['beat_spy']} maxDD={row['max_drawdown_pct']}% "
              f"halted={row['halted']} months_in={row['months_invested']}/"
              f"{row['months_total']}", flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    comp = 100.0
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
    out["fold_compounded_final"] = round(comp, 2)

    with open(os.path.join(HERE, "folklore-f7-pivots-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")



# =====================================================================
# V9 PROTECTION MODULE — CLAUDE-RULES PROTECTION SPEC v9 (ONLY CHANGE)
# Episode 1: floor -15% from $100 start (identical to original).
# On FIRST halt: liquidate exactly as run_pot does, sit in cash 90
# calendar days from the liquidation date, then RESTART with the
# remaining cash at the strategy's next regular decision point (this
# engine decides on the first trading day of each month, so the first
# such day on/after day 90).
# Episode 2: floor = -15% from the RESTART balance. On SECOND halt the
# run ends permanently. Ranked pot only; no placebos under v9.
# =====================================================================
import datetime as _dt

def _v9_episodes(bars, pivots, ws, we, window_label):
    ep1 = run_pot(bars, pivots, ws, we, START_CASH, FLOOR0,
                  label=window_label)
    min_close = min((v for _, v in ep1["curve"]), default=100.0)
    base = {"episodes": 1, "ep1_halted": ep1["halted"], "restart": None,
            "ep2_halted": None, "min_close": round(min_close, 2),
            "final": round(ep1["final"], 2), "status": "no_halt"}
    if not ep1["halted"]:
        return base
    liq = next((t[0] for t in reversed(ep1["trades"]) if t[1] == "SELL-HALT"),
               ep1["halted"])
    cash1 = ep1["final"]
    eligible = (_dt.date.fromisoformat(liq) + _dt.timedelta(days=90)).isoformat()
    days = [b["d"] for b in bars if ws <= b["d"] <= we]
    firsts = []
    seen = set()
    for d in days:
        if d[:7] not in seen:
            seen.add(d[:7])
            firsts.append(d)
    rest = [d for d in firsts if d >= eligible]
    restart_info = {"window": window_label, "halt_signal_date": ep1["halted"],
                    "liquidation_date": liq, "cash_at_halt": round(cash1, 2),
                    "eligible_date": eligible, "restart_date": None,
                    "restart_balance": round(cash1, 2),
                    "episode2_floor": round(0.85 * cash1, 2),
                    "second_halt": None}
    base["restart"] = restart_info
    if not rest:
        base["status"] = "halted_ep1_no_restart_in_window"
        return base
    restart_info["restart_date"] = rest[0]
    ep2 = run_pot(bars, pivots, rest[0], we, cash1, 0.85 * cash1,
                  label=window_label + " EP2")
    min2 = min((v for _, v in ep2["curve"]), default=cash1)
    base["min_close"] = round(min(base["min_close"], min2), 2)
    restart_info["second_halt"] = ep2["halted"]
    base.update({"episodes": 2, "final": round(ep2["final"], 2),
                 "ep2_halted": ep2["halted"],
                 "status": "halted_ep2_run_ends" if ep2["halted"]
                           else "restarted_completed"})
    return base

def v9_main():
    bars = load_spy_bars()
    pivots = monthly_pivots(bars)
    for tag, (ws, we), expect in (("FULL", FULL, 313.62),
                                  ("VALIDATION", VALIDATION, 187.77)):
        spy, _ = spy_net(bars, ws, we, START_CASH)
        assert abs(spy - expect) < 0.005, f"REPLICATION FAILED {tag}"
        print(f"REPLICATION {tag}: SPY net=${spy:,.2f} match=True", flush=True)
    cont = _v9_episodes(bars, pivots, FULL[0], FULL[1], "continuous")
    val = _v9_episodes(bars, pivots, VALIDATION[0], VALIDATION[1],
                       "validation")
    for tag, r in (("CONTINUOUS", cont), ("VALIDATION", val)):
        print(f"V9 {tag}: final=${r['final']} status={r['status']} "
              f"ep1_halted={r['ep1_halted']} restart={r['restart']} "
              f"ep2_halted={r['ep2_halted']}", flush=True)
    his_folds = {2020: 114.56, 2021: 108.05, 2022: 81.74, 2023: 106.72,
                 2024: 110.38, 2025: 122.96, 2026: 104.31}
    folds, fold_restarts = [], []
    for y in range(2020, 2027):
        fs, fe = f"{y}-01-01", ("2026-11-20" if y == 2026 else f"{y}-12-31")
        r = _v9_episodes(bars, pivots, fs, fe, f"fold {y}")
        if r["restart"]:
            fold_restarts.append(r["restart"])
        folds.append({"year": y, "his_final": his_folds[y],
                      "v9_final": r["final"], "status": r["status"],
                      "ep1_halted": r["ep1_halted"],
                      "ep2_halted": r["ep2_halted"],
                      "restart": r["restart"]})
        print(f"V9 FOLD {y}: his=${his_folds[y]} v9=${r['final']} "
              f"status={r['status']} restart={r['restart']}", flush=True)
    worst_loss = round(max(100.0 - cont["min_close"],
                           100.0 - val["min_close"],
                           100.0 - cont["final"], 100.0 - val["final"]), 2)
    out = {"slug": "folklore-f7-pivots",
           "name": "F-7 Monthly pivot trend",
           "status": "partial-rerun",
           "his": {"continuous_final": 168.05, "validation_final": 152.42},
           "v9": {"continuous_final": cont["final"],
                  "validation_final": val["final"],
                  "continuous_status": cont["status"],
                  "validation_status": val["status"],
                  "restarts": fold_restarts,
                  "folds_note": "Folds 2020-2026 re-run under v9; see "
                                "folds_detail. The only his-rules fold halt "
                                "is 2022 (2022-06-10); it gets one 90-day "
                                "sit-out and a restart at the next "
                                "first-trading-day-of-month inside the fold "
                                "year. Main windows never halted under "
                                "either rule set, so main finals are "
                                "identical by construction and were verified "
                                "through the same wrapper.",
                  "worst_total_loss_pct": worst_loss},
           "folds_detail": folds,
           "notes": "Main windows: identical — floor never fired (worst "
                    "closes $99.87 continuous, $96.21 validation). Only "
                    "the halted 2022 yearly fold changes under v9. Ranked "
                    "pot only; no placebos under v9."}
    with open(os.path.join(HERE, "v9-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    v9_main()
