#!/usr/bin/env python3
"""V10 CONFIRMATION RUN — N-PV3 at ANNUAL cadence (Terry's CONFIRMATION RULE).

Re-runs PV3 at ANNUAL cadence on LONG / CONT / VAL plus fresh yearly folds
2017-2026. Treatment IDENTICAL to sweep.py (copied in as sweep_base.py for
reference): only the rotation rhythm changes vs the native monthly form —
signal from prior close, VR-5/63d, sign gate >= 0, top-5, full rotation at
20% of pre-trade equity per name at the cadence date's open, program costs
(0.10%/side + $0.01/sell order), daily-close -15% v9 floor, halt -> liquidate
next open, 90 calendar days cash, restart at next cadence date under an
episode-2 -15% floor; second halt ends the run. Placebos: 20 seeds, random
names from the same sign-gated eligible set on the same cadence dates.
Writes ONLY inside this confirmation/ folder.
"""
import importlib.util, json, os, random, statistics, sys
from datetime import date, timedelta, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)  # slug folder (read-only sources)
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
spec = importlib.util.spec_from_file_location(
    "pv3", os.path.join(BASE, "integrity", "novel-pv3-metaorder.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

def load_bars(ticker):
    if ticker == "GOOGL":
        j = json.load(open(os.path.join(BASE, "pxfull_GOOGL.json")))
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
print(f"CAL {CAL[0]} .. {CAL[-1]} ({len(CAL)} sessions)", flush=True)

_ELIG = {}
def eligible(signal_date):
    if signal_date not in _ELIG:
        _ELIG[signal_date] = MKT.eligible(signal_date)
    return _ELIG[signal_date]

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
    s.add(days[0])
    return s

def simulate_cad(start_d, end_d, mode, cdates, seed=42, start_cash=None,
                 floor=None):
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
                picks = [t for t, _, _ in elig_s[:5]]
            else:
                names = sorted(t for t, _, _ in elig)
                picks = rng.sample(names, min(5, len(names))) if names else []
            eq_open = equity_at(i, use_open=True)
            for t in list(pos):
                px = MKT.open_px(t, i)
                if px is None: px = MKT.close_px(t, i)
                val = pos[t] * px; fee = val * COST_RATE + SELL_FEE
                cash += val - fee; costs += fee; orders += 1; del pos[t]
            for t in picks:
                px = MKT.open_px(t, i)
                if px is None: continue
                target = 0.20 * eq_open
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

def run_v9(start, end, cadence, mode, seed=42):
    cdates = cadence_dates(cadence, start, end)
    r1 = simulate_cad(start, end, mode, cdates, seed=seed)
    eps = [r1]; restart = None
    if r1["halt_date"] is not None:
        elig_d = (date.fromisoformat(r1["halt_date"]) + timedelta(days=90)).isoformat()
        cands = sorted(d for d in cdates if d >= elig_d)
        if cands and cands[0] <= end:
            rot = cands[0]
            r2 = simulate_cad(rot, end, mode, cdates, seed=seed,
                              start_cash=r1["final"], floor=0.85 * r1["final"])
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

def cagr(final, start, end):
    yrs = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days / 365.25
    return round(((final / POT) ** (1.0 / yrs) - 1.0) * 100, 2) if yrs > 0 else None

CAD = "annual"
ROADS = {
    "LONG": ("2010-01-04", "2026-11-20", 822.94),
    "CONT": ("2019-01-02", "2026-11-20", 313.62),
    "VAL":  ("2023-01-03", "2026-11-20", 187.77),
}

summary = {}
for road, (start, end, spy_ref) in ROADS.items():
    spy = round(M.spy_net(MKT, start, end), 2)
    r = run_v9(start, end, CAD, "ranked")
    curve = r.pop("curve")
    finals = []
    for seed in range(1, 21):
        pr = run_v9(start, end, CAD, "placebo", seed=seed)
        finals.append(pr["final"])
        print(f"  {road} placebo seed {seed}: {pr['final']}", flush=True)
    beaten = sum(1 for f in finals if f < r["final"])
    med = round(statistics.median(finals), 2)
    out = {"road": road, "cadence": CAD, "start": start, "end": end,
           "final": r["final"], "cagr_pct": cagr(r["final"], start, end),
           "max_dd_pct": diag(curve), "costs": r["costs"],
           "orders": r["orders"], "halts": r["halts"],
           "restart": r["restart"], "restart_info": r["restart_info"],
           "second_halt": r["second_halt"],
           "spy_final": spy, "spy_reference": spy_ref,
           "beats_spy": r["final"] > spy,
           "placebo_beaten": beaten, "placebo_median": med,
           "placebo_best": max(finals), "placebo_worst": min(finals),
           "placebo_twin_finals": finals,
           "equity_curve": [[d, round(v, 4)] for d, v in curve]}
    json.dump(out, open(os.path.join(HERE, f"{road.lower()}-annual.json"), "w"), indent=1)
    summary[road] = out
    print(f"{road}: final={r['final']} SPY={spy} (ref {spy_ref}) CAGR={out['cagr_pct']} "
          f"DD={out['max_dd_pct']} costs={r['costs']} orders={r['orders']} "
          f"halts={r['halts']} restart={r['restart']} placebo {beaten}/20 median={med}",
          flush=True)

# --- fresh yearly folds, annual cadence, fresh $100 each year -----------
folds = {}
for yr in range(2017, 2027):
    days = [d for d in CAL if d[:4] == str(yr) and d <= "2026-11-20"]
    start, end = days[0], days[-1]
    spy = round(M.spy_net(MKT, start, end), 2)
    r = run_v9(start, end, CAD, "ranked")
    curve = r.pop("curve")
    folds[str(yr)] = {"year": yr, "start": start, "end": end,
                      "final": r["final"], "spy_final": spy,
                      "beat_spy": r["final"] > spy,
                      "beat_100": r["final"] > 100.0,
                      "max_dd_pct": diag(curve), "costs": r["costs"],
                      "orders": r["orders"], "halts": r["halts"],
                      "restart": r["restart"],
                      "restart_info": r["restart_info"],
                      "second_halt": r["second_halt"],
                      "equity_curve": [[d, round(v, 4)] for d, v in curve]}
    print(f"fold {yr}: final={r['final']} SPY={spy} beat_spy={r['final']>spy} "
          f"beat100={r['final']>100.0} halts={r['halts']}", flush=True)
json.dump({"cadence": CAD, "folds": folds},
          open(os.path.join(HERE, "folds.json"), "w"), indent=1)
print("CONFIRMATION RUNS DONE", flush=True)
