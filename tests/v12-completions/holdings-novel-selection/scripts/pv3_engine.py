#!/usr/bin/env python3
"""V10 CADENCE SWEEP — N-PV3 RIDING THE METAORDER (invented rule PV3).
Simulation only. DECADE 2016-11-21 -> 2026-11-20, $100/cell.

TREATMENT FOR THIS RULE'S MECHANICS (uniform SPEC cadence definition):
PV3's native form is a MONTHLY full rotation: on the signal day compute
VR-5 (variance ratio of overlapping 5-day sums over trailing 63 daily
returns) for every pond name, keep names with trailing 63-day total
return >= 0 (sign gate), rank by VR descending, sell ALL holdings and
buy the top 5 at 20% of pre-trade equity each (full rotation, no
netting). Under the sweep, the ONLY change is the rotation rhythm:
signal evaluation, ranking and the full rotation happen ONLY on
cadence dates (signal = prior trading day's close, trade at the
cadence date's open, exactly as the original). The VR window (63
returns), the sign gate, top-5, equal 20% weights, full rotation and
costs (0.10%/side + $0.01/sell order) are unchanged at every cadence.
Daily-close -15% v9 floor check stays daily (it is a protection, not
the strategy's decision rhythm). On a halt: liquidate at the next
open as the engine does, sit in cash 90 calendar days, restart at the
next CADENCE date on/after halt+90d under an episode-2 floor of -15%
from the restart balance; a second halt ends the run.
Cadence dates: daily = every trading day; weekly = first trading day
of each ISO week; biweekly = first trading day of every second ISO
week, counting from the first week of the window; monthly = first
trading day of each month; quarterly = first trading day of each
calendar quarter; semiannual = first trading day of each half-year;
annual = first trading day of each year. The window's first session
is always an entry date (as in the original engine).
Placebos: 20 seeds per cell — on the same cadence dates, 5 RANDOM
names from the same sign-gated eligible set, identical engine/floor/
v9 wrapper (the original placebo design).
Data: read-only long-run pxfull payloads via the v9 engine's
load_bars slot (same construction as driver.py / area runs); GOOGL
from the slug-local pxfull_GOOGL.json. Eligible sets are cached per
signal date (identical across modes/seeds/cadences).
"""
import importlib.util, json, os, random, sys
from datetime import date, timedelta, datetime

HERE = "/home/hatch/workspace/stock-app/backtests/v10-retest/novel-pv3-metaorder"
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "pv3", os.path.join(HERE, "integrity", "novel-pv3-metaorder.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

def load_bars(ticker):
    if ticker == "GOOGL":
        j = json.load(open(os.path.join(HERE, "pxfull_GOOGL.json")))
    else:
        j = json.load(open(os.path.join(LH, f"pxfull_{ticker}.json")))
    res = j["chart"]["result"][0]; ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    import datetime as _dt
    for i, t in enumerate(ts):
        d = _dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        o, c = q["open"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": (o * r if o else a), "c": a})
    bars.sort(key=lambda b: b["d"]); return bars
M.load_bars = load_bars

print("loading market...", flush=True)
MKT = M.Market(M.UNIVERSE)
CAL = MKT.cal
COST_RATE, SELL_FEE, POT = M.COST_RATE, M.SELL_FEE, M.POT

# --- eligible-set cache (signal date -> eligible list) -----------------
_ELIG = {}
def eligible(signal_date):
    if signal_date not in _ELIG:
        _ELIG[signal_date] = MKT.eligible(signal_date)
    return _ELIG[signal_date]

# --- cadence date sets --------------------------------------------------
def cadence_dates(cadence, start, end):
    days = [d for d in CAL if start <= d <= end]
    if cadence == "daily":
        s = set(days)
    elif cadence in ("weekly", "biweekly"):
        seen, wk = set(), []
        for d in days:
            key = date.fromisoformat(d).isocalendar()[:2]
            if key not in seen:
                seen.add(key); wk.append(d)
        s = set(wk if cadence == "weekly" else wk[::2])
    elif cadence == "monthly":
        s, seen = set(), set()
        for d in days:
            if d[:7] not in seen: seen.add(d[:7]); s.add(d)
    elif cadence == "quarterly":
        s, seen = set(), set()
        for d in days:
            q = (d[:4], (int(d[5:7]) - 1) // 3)
            if q not in seen: seen.add(q); s.add(d)
    elif cadence == "semiannual":
        s, seen = set(), set()
        for d in days:
            q = (d[:4], (int(d[5:7]) - 1) // 6)
            if q not in seen: seen.add(q); s.add(d)
    elif cadence == "annual":
        s, seen = set(), set()
        for d in days:
            if d[:4] not in seen: seen.add(d[:4]); s.add(d)
    else:
        raise ValueError(cadence)
    s.add(days[0])  # initial entry, as in the original engine
    return s

# --- cadence-aware simulate (engine mechanics, rotation on cadence) ----
def simulate_cad(start_d, end_d, mode, cdates, seed=42, start_cash=None,
                 floor=None, n_hold=5):
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(CAL) if d >= start_d)
    i1 = max(i for i, d in enumerate(CAL) if d <= end_d)
    cash = float(POT) if start_cash is None else float(start_cash)
    if floor is None: floor = 0.85 * cash
    pos = {}
    orders = 0; costs = 0.0; halt_date = None; final = None
    curve = []
    pending = False

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = MKT.open_px(t, i) if use_open else MKT.close_px(t, i)
            if px is None: px = MKT.close_px(t, i)
            tot += sh * px
        return tot

    for i in range(i0, i1 + 1):
        d = CAL[i]
        if pending:
            for t in list(pos):
                px = MKT.open_px(t, i)
                if px is None: px = MKT.close_px(t, i)
                val = pos[t] * px; fee = val * COST_RATE + SELL_FEE
                cash += val - fee; costs += fee; orders += 1; del pos[t]
            halt_date = d; final = cash; curve.append((d, cash)); break
        if d in cdates:
            signal_date = CAL[i - 1]
            elig = eligible(signal_date)
            if mode == "ranked":
                elig_s = sorted(elig, key=lambda x: (-x[1], x[0]))
                picks = [t for t, _, _ in (elig_s if n_hold is None else elig_s[:n_hold])]
            else:
                names = sorted(t for t, _, _ in elig)
                picks = rng.sample(names, min(n_hold, len(names))) if (names and n_hold) else (list(names) if names else [])
            eq_open = equity_at(i, use_open=True)
            for t in list(pos):
                px = MKT.open_px(t, i)
                if px is None: px = MKT.close_px(t, i)
                val = pos[t] * px; fee = val * COST_RATE + SELL_FEE
                cash += val - fee; costs += fee; orders += 1; del pos[t]
            for t in picks:
                px = MKT.open_px(t, i)
                if px is None: continue
                target = (eq_open / n_hold) if n_hold else (eq_open / max(len(picks),1) if picks else 0.0)
                buy_val = min(target, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01: continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee; costs += fee; orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px
        eq_close = equity_at(i, use_open=False)
        curve.append((d, eq_close))
        if eq_close <= floor:
            pending = True
            if i == i1:
                tot = cash
                for t, sh in list(pos.items()):
                    val = sh * MKT.close_px(t, i)
                    fee = val * COST_RATE + SELL_FEE
                    tot += val - fee; costs += fee; orders += 1
                final = tot; halt_date = d; pos.clear(); break
    if final is None: final = curve[-1][1]
    return {"final": final, "costs": costs, "orders": orders,
            "halt_date": halt_date, "curve": curve}

def run_v9(start, end, cadence, mode, seed=42, n_hold=5):
    cdates = cadence_dates(cadence, start, end)
    r1 = simulate_cad(start, end, mode, cdates, seed=seed, n_hold=n_hold)
    eps = [r1]; restart = None
    if r1["halt_date"] is not None:
        elig_d = (date.fromisoformat(r1["halt_date"]) + timedelta(days=90)).isoformat()
        cands = sorted(d for d in cdates if d >= elig_d)
        if cands and cands[0] <= end:
            rot = cands[0]
            r2 = simulate_cad(rot, end, mode, cdates, seed=seed,
                              start_cash=r1["final"], floor=0.85 * r1["final"], n_hold=n_hold)
            eps.append(r2)
            restart = {"halt_date": r1["halt_date"],
                       "liquidation": round(r1["final"], 2),
                       "eligibility": elig_d, "restart_date": rot,
                       "episode2_floor": round(0.85 * r1["final"], 2),
                       "second_halt": r2["halt_date"]}
    curve = {}
    for ep in eps:
        for d, v in ep["curve"]: curve[d] = v
    if len(eps) > 1:
        for d in CAL:
            if eps[0]["curve"][-1][0] < d < eps[1]["curve"][0][0]:
                curve[d] = eps[0]["final"]
    curve = sorted(curve.items())
    halts = [e["halt_date"] for e in eps if e["halt_date"]]
    return {"final": round(eps[-1]["final"], 2),
            "costs": round(sum(e["costs"] for e in eps), 2),
            "orders": sum(e["orders"] for e in eps),
            "halts": halts, "restart": restart is not None,
            "restart_info": restart,
            "second_halt": bool(restart and restart["second_halt"]),
            "curve": curve}

def diag(curve):
    peak, maxdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return round(maxdd * 100, 2)

