#!/usr/bin/env python3
"""v13 BEST RULES — hunt-hy-credit-spread. Frozen spec: BEST-RULES-SPEC.md.
Credit-spread DIAL on SPY: monthly, exposure step from the spread's own
trailing-120-month-end percentile (<=70:100%, 70-85:67%, 85-95:33%, >95:0%).
Gauge: FRED BAA10Y (Moody's Baa yield minus 10Y Treasury, daily, public,
full history) because the ICE HY OAS (BAMLH0A0HYM2) is distributed keyless
only as a rolling ~3y window (v12 HUNT-LOG; FRED series note). The same
dial + v12's frozen published switch also run on the ICE series over its
available window as a cross-check. PIT: a spread value dated T is usable
from T+2 calendar days. Costs: 0.10%/side on traded fraction + $0.01 on
any exposure-reducing rebalance. No floor. $100 pots. FRED data used as
signal input only, not trained on; ICE series kept in /tmp, not in the
deliverable folder (ICE redistribution restriction). Simulation only."""
import json, os, sys, random, statistics, csv, io, urllib.request
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chassis_ref import load_bars, period_stats, buy_hold, simulate_openfill

HERE = os.path.dirname(os.path.abspath(__file__))
SPY = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
bars = load_bars(SPY)
COST = 0.001; SELLFEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

def fetch_fred(sid):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
    with urllib.request.urlopen(url, timeout=60) as r:
        txt = r.read().decode()
    out = {}
    for row in csv.reader(io.StringIO(txt)):
        if len(row) == 2 and row[0][:4].isdigit() and row[1] not in ("", "."):
            try: out[row[0]] = float(row[1])
            except ValueError: pass
    return out

def dparse(s):
    y, m, d = s.split("-"); return date(int(y), int(m), int(d))

def month_end_usable(series, lag_days=2):
    """{(y,m): (usable_value, obs_date)} — last obs whose date+lag <= the
    month's last calendar day, evaluated per SPY trading month-end later."""
    obs = sorted((dparse(d), d, v) for d, v in series.items())
    return obs

def usable_at(obs, when):
    """Last spread value usable on date `when` (obs date + 2d <= when)."""
    val = None
    for od, _, v in obs:
        if od + timedelta(days=2) <= when: val = v
        else: break
    return val

def step_for(pct):
    if pct is None: return 1.0
    if pct <= 70: return 1.0
    if pct <= 85: return 0.67
    if pct <= 95: return 0.33
    return 0.0

def monthly_targets(obs, min_hist=60, lookback=120):
    """{(y,m): (target_step, spread, percentile)} decided at that month's
    last SPY trading day, from data usable that day."""
    lastday = {}
    for b in bars: lastday[(int(b["d"][:4]), int(b["d"][5:7]))] = b["d"]
    months = sorted(lastday)
    hist = []  # month-end usable values, in order
    out = {}
    for mk in months:
        v = usable_at(obs, dparse(lastday[mk]))
        if v is None: out[mk] = (1.0, None, None); continue
        window = hist[-lookback:]
        if len(window) >= min_hist:
            pct = 100.0 * (sum(1 for h in window if h < v) + 0.5 * sum(1 for h in window if h == v)) / len(window)
        else:
            pct = None
        out[mk] = (step_for(pct), v, None if pct is None else round(pct, 1))
        hist.append(v)
    return out

def simulate_dial2(targets_by_month, start, end, permute_seed=None):
    """Cleaner implementation: stock tracked in dollars at close; on a
    rebalance day, stock first moves prev-close -> open, rebalance at open,
    then stock moves open -> close."""
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    if len(idx) < 2: return None
    all_months = sorted(targets_by_month)
    road_months = []
    for i in idx:
        mk = (int(bars[i]["d"][:4]), int(bars[i]["d"][5:7]))
        if mk not in road_months: road_months.append(mk)
    eff = {}
    for j, mk in enumerate(all_months):
        if j + 1 < len(all_months): eff[all_months[j + 1]] = targets_by_month[mk][0]
    steps = [eff.get(mk, 1.0) for mk in road_months]
    if permute_seed is not None:
        random.Random(permute_seed).shuffle(steps)
    step_of = dict(zip(road_months, steps))
    lastday = {}
    for i in idx: lastday[(int(bars[i]["d"][:4]), int(bars[i]["d"][5:7]))] = i
    cash = 100.0; stock = 0.0; curve = []; trades = 0; costs = 0.0
    peak = 100.0; maxdd = 0.0; cur = 0.0
    pm = [m for m in all_months if m < road_months[0]]
    pending = targets_by_month[pm[-1]][0] if pm else 1.0
    if permute_seed is not None: pending = steps[0]
    for k, i in enumerate(idx):
        b = bars[i]; prev = bars[idx[k - 1]] if k > 0 else None
        rebalanced = False
        if pending is not None and abs(pending - cur) > 1e-9:
            stock_open = stock * (b["o"] / prev["c"]) if (prev is not None and stock > 0) else stock
            V = cash + stock_open
            delta = pending * V - stock_open
            c = abs(delta) * COST + (SELLFEE if delta < 0 else 0.0)
            V -= c; costs += c; trades += 1
            stock = pending * V; cash = V - stock; cur = pending; rebalanced = True
            pending = None
        if stock > 0:
            stock *= (b["c"] / b["o"]) if rebalanced else (b["c"] / prev["c"] if prev is not None else 1.0)
        eq = cash + stock
        curve.append([b["d"], round(eq, 4)])
        peak = max(peak, eq); maxdd = max(maxdd, 1 - eq / peak)
        mk = (int(b["d"][:4]), int(b["d"][5:7]))
        if lastday.get(mk) == i:
            if permute_seed is not None:
                # next month's step is the permuted step of next month
                nm = road_months[road_months.index(mk) + 1] if road_months.index(mk) + 1 < len(road_months) else None
                pending = step_of[nm] if nm else None
            else:
                pending = targets_by_month[mk][0]
    return {"final": round(cash + stock, 2), "curve": curve, "trades": trades,
            "costs": round(costs, 2), "max_dd": round(maxdd, 4),
            "exposure_steps_road": steps}

def main():
    log = []
    baa = fetch_fred("BAA10Y")
    log.append(f"BAA10Y rows={len(baa)} range={min(baa)}..{max(baa)}")
    os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
    with open(os.path.join(HERE, "data", "FRED_BAA10Y.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(["date", "BAA10Y"])
        for d in sorted(baa): w.writerow([d, baa[d]])
    ice = fetch_fred("BAMLH0A0HYM2")
    log.append(f"BAMLH0A0HYM2 rows={len(ice)} range={min(ice)}..{max(ice)} (kept in memory only)")
    obs_baa = month_end_usable(baa)
    targets = monthly_targets(obs_baa)
    out = {"family": "hunt-hy-credit-spread", "program": "v13-best-rules",
           "gauge": "FRED BAA10Y (Moody's Baa - 10Y Treasury), PIT lag 2d, trailing-120m percentile dial",
           "spec": "BEST-RULES-SPEC.md", "log": log, "roads": {}}
    any_beat = False
    for road, (s, e) in ROADS.items():
        r = simulate_dial2(targets, s, e)
        ent = {k: v for k, v in r.items() if k != "curve"}
        ent["curve"] = r["curve"]
        ent["period_stats_monthly"] = period_stats(r["curve"], "M")
        ent["spy_buy_hold"] = buy_hold(bars, s, e)
        ent["spy_reference"] = SPYREF[road]; ent["champion_vm"] = CHAMP[road]
        finals = []
        for seed in range(1, 21):
            pr = simulate_dial2(targets, s, e, permute_seed=seed)
            finals.append(pr["final"])
        ent["placebo_random_timing"] = {"finals": finals,
            "median": round(statistics.median(finals), 2),
            "min": min(finals), "max": max(finals),
            "share_beating_system": round(sum(1 for x in finals if x > r["final"]) / len(finals), 3)}
        out["roads"][road] = ent
        if r["final"] > CHAMP[road]: any_beat = True
        print(road, "dial", r["final"], "dd", r["max_dd"], "trades", r["trades"],
              "bh", ent["spy_buy_hold"], "placeboMed", ent["placebo_random_timing"]["median"])
    out["monthly_targets"] = {f"{k[0]}-{k[1]:02d}": {"step": v[0], "spread": v[1], "pct": v[2]}
                              for k, v in sorted(targets.items())}
    # ICE cross-check on its available window
    WIN = ("2023-11-21", "2026-11-20")
    obs_ice = month_end_usable(ice)
    t_ice = monthly_targets(obs_ice, min_hist=24, lookback=120)
    rd = simulate_dial2(t_ice, *WIN)
    cross = {"window": list(WIN), "dial_on_ice_hy": {k: v for k, v in rd.items() if k != "curve"},
             "dial_on_ice_hy_curve": rd["curve"],
             "dial_on_baa_same_window": None, "spy_buy_hold": buy_hold(bars, *WIN)}
    rb = simulate_dial2(targets, *WIN)
    cross["dial_on_baa_same_window"] = {k: v for k, v in rb.items() if k != "curve"}
    # v12 frozen published switch on ICE, same window (construction per v12 SPEC-FROZEN)
    me = {}
    for d in sorted(ice): me[d[:7]] = ice[d]
    months = sorted(me); dec = {}; state = 1; sell_ref = None; falls = 0; prev = None
    for mk in months:
        v = me[mk]
        if state == 1:
            if v > 5.0 and prev is not None and v > prev: state = 0; sell_ref = v; falls = 0
        else:
            if v <= 5.0: state = 1; sell_ref = None
            else:
                falls = falls + 1 if (prev is not None and v < prev) else 0
                if falls >= 2 and sell_ref is not None and v < sell_ref: state = 1; sell_ref = None
        dec[mk] = state; prev = v
    st = [0] * len(bars); cur = 1; ld = {}
    for i, b in enumerate(bars): ld[b["d"][:7]] = i
    for i, b in enumerate(bars):
        mk = b["d"][:7]
        if ld.get(mk) == i and mk in dec: cur = dec[mk]
        st[i] = cur
    sw = simulate_openfill(bars, st, *WIN, "native")
    cross["published_switch_on_ice"] = {k: v for k, v in sw.items() if k != "curve"}
    out["ice_crosscheck"] = cross
    print("ICE window: dialICE", rd["final"], "dialBAA", rb["final"], "switch", sw["final"], "bh", cross["spy_buy_hold"])
    out["champion_beaten_any_road"] = any_beat
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("champion beaten:", any_beat)

if __name__ == "__main__":
    main()
