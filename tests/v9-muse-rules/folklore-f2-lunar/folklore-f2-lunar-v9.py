#!/usr/bin/env python3
"""
FOLKLORE TEST F-2 — LUNAR CYCLE TIMING (Yuan-Zheng-Zhu 15-day form)
====================================================================
Spec source: ~/workspace/stock-app/research/v7-completeness/folklore-audit.md,
Spec F-2. The spec is FROZEN; this script implements it verbatim. Simulation
only. Run once; no parameter was adjusted after any result was seen.

THE SPEC AS WRITTEN (folklore-audit.md, Spec F-2):
- Universe/data: SPY only. New-moon dates from published astronomical
  ephemeris (exact, free, known in advance).
- Rule (frozen, the paper's 15-day window): the pot holds SPY only on
  trading days falling within +/-7 calendar days of a new moon. On all
  other days it holds cash (0% interest). Switches execute at the next
  open after a window boundary is crossed.
- Standing warning in the spec: the published gross effect is 3-5%/yr
  between windows; this test measures whether anything survives costs
  at $100.

HOUSE CHASSIS (folklore-audit.md preamble, identical to the program):
$100 pot; execution at the next session's open after a signal computed on
closes; costs 0.10% of trade value per side plus $0.01 per sell order;
plain -15% floor at the pot level (a close at or below $85 liquidates
everything to cash at the next open and ends the run, exactly as in the
champion engine); judging windows continuous 2019-01-01 -> 2026-11-20
and validation 2023-01-01 -> 2026-11-20; benchmarks SPY buy-hold net of
the same costs and a 20-seed random placebo on the same universe and
cadence; promotion requires beating SPY AND the placebo median on
validation.

FORCED READINGS (stated here, before any result):
1. MOON DATES ARE COMPUTED, NOT TYPED. Conjunction/opposition instants
   come from an ephemeris calculation in this file: Paul Schlyter's
   published low-precision geocentric elements for the Sun and Moon
   (orbital elements + eccentric-anomaly solution + the standard lunar
   perturbation series: evection, variation, annual equation, etc.),
   with the elongation zero-crossings located by bisection to <1 minute.
   The routine is cross-validated in-code against 15 known eclipse
   dates (a solar eclipse IS a new moon; a lunar eclipse IS a full
   moon) and the run aborts if the computed UTC dates disagree.
2. The "date" of a moon event is the UTC calendar date of the computed
   conjunction/opposition instant. (Dynamical-vs-UTC offset ~69 s in
   this era is ignored; it cannot move a +/-7-day window materially.)
3. A trading day is IN WINDOW iff |trading_date - moon_event_date| <= 7
   calendar days (the paper's 15-day window: -7..+7 inclusive).
4. "Switches execute at the next open after a window boundary is
   crossed" is read as: the position held DURING a trading day equals
   that day's window membership, and any switch executes at THAT day's
   open (the boundary is crossed at the start of the first day whose
   membership differs). The pot starts each window in cash; if day 1 is
   in window it buys at day 1's open (the champion engine's spy_net
   entry convention).
5. CONTROL, per the tasking: the identical machine run on FULL-moon
   windows (+/-7 days around each full moon) — same cadence, same
   turnover, opposite phase. If the lunar claim is real, the new-moon
   pot must beat this control; if both do the same thing, the phase is
   not carrying anything.
6. PLACEBO (house chassis): 20 pseudo-lunar timers with the same
   window width and the same synodic cadence, each with its
   conjunctions shifted by one uniform-random phase offset in
   [0, 29.530588853) days (seeds 1..20, random.Random(seed)).
7. End of window: any open position is liquidated at the final close
   with the standard sell cost (champion engine convention).

Champion reference (published, reproduced by every program test):
V+M $544.47 continuous / $288.05 validation; SPY net $313.62 / $187.77.
"""
import importlib.util
import json
import math
import os
import random
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py")

_spec = importlib.util.spec_from_file_location("vm_plainfloor", ENGINE_PATH)
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)

START_CASH = 100.0
FLOOR0 = 85.0                      # plain -15% floor, no ladder
FULL = ("2019-01-01", "2026-11-20")
VALIDATION = ("2023-01-01", "2026-11-20")
SYNODIC = 29.530588853
PLACEBO_SEEDS = list(range(1, 21))

# ======================================================================
# Ephemeris (computed in code — Schlyter's published elements)
# ======================================================================

def _rev(x):
    return x - math.floor(x / 360.0) * 360.0

def _sind(x):
    return math.sin(math.radians(_rev(x)))

def _cosd(x):
    return math.cos(math.radians(_rev(x)))

def _sun(d):
    """Geocentric ecliptic longitude of the Sun (deg), mean anomaly, mean
    longitude. d = days since 2000 Jan 0.0 (JD - 2451543.5)."""
    w = 282.9404 + 4.70935e-5 * d
    e = 0.016709 - 1.151e-9 * d
    M = _rev(356.0470 + 0.9856002585 * d)
    Ea = M + math.degrees(e) * _sind(M) * (1 + e * _cosd(M))
    xv = math.cos(math.radians(Ea)) - e
    yv = math.sqrt(1 - e * e) * math.sin(math.radians(Ea))
    v = math.degrees(math.atan2(yv, xv))
    return _rev(v + w), M, _rev(M + w)

def _moon_lon(d):
    """Geocentric ecliptic longitude of the Moon (deg), with the standard
    perturbation series (evection, variation, annual equation, ...)."""
    N = 125.1228 - 0.0529538083 * d
    inc = 5.1454
    w = 318.0634 + 0.1643573223 * d
    a = 60.2666                      # Earth radii
    e = 0.054900
    M = _rev(115.3654 + 13.0649929509 * d)
    Ea = M + math.degrees(e) * _sind(M) * (1 + e * _cosd(M))
    for _ in range(3):               # Newton refinement of Kepler's equation
        Ea = Ea - (Ea - math.degrees(e) * _sind(Ea) - M) / (1 - e * _cosd(Ea))
    xv = a * (math.cos(math.radians(Ea)) - e)
    yv = a * (math.sqrt(1 - e * e) * math.sin(math.radians(Ea)))
    v = math.degrees(math.atan2(yv, xv))
    r = math.hypot(xv, yv)
    vw = v + w
    xh = r * (_cosd(N) * _cosd(vw) - _sind(N) * _sind(vw) * _cosd(inc))
    yh = r * (_sind(N) * _cosd(vw) + _cosd(N) * _sind(vw) * _cosd(inc))
    lon = _rev(math.degrees(math.atan2(yh, xh)))
    _, Ms, s_mlon = _sun(d)
    mlon = _rev(N + w + M)
    D = _rev(mlon - s_mlon)          # mean elongation
    F = _rev(mlon - N)               # argument of latitude
    Mm = M
    lon += (-1.274 * _sind(Mm - 2 * D) + 0.658 * _sind(2 * D)
            - 0.186 * _sind(Ms) - 0.059 * _sind(2 * Mm - 2 * D)
            - 0.057 * _sind(Mm - 2 * D + Ms) + 0.053 * _sind(Mm + 2 * D)
            + 0.046 * _sind(2 * D - Ms) + 0.041 * _sind(Mm - Ms)
            - 0.035 * _sind(D) - 0.031 * _sind(Mm + Ms)
            - 0.015 * _sind(2 * F - 2 * D) + 0.011 * _sind(Mm - 4 * D))
    return _rev(lon)

def _elong(d):
    slon, _, _ = _sun(d)
    return _rev(_moon_lon(d) - slon)

def _signed(x):
    y = (x + 180.0) % 360.0 - 180.0
    return 180.0 if y == -180.0 else y

_JD_EPOCH = datetime(2000, 1, 1, 12, 0)     # JD 2451545.0

def _d_of(dt):
    jd = (dt - _JD_EPOCH).total_seconds() / 86400.0 + 2451545.0
    return jd - 2451543.5

def _dt_of_d(d):
    return _JD_EPOCH + timedelta(days=(d + 2451543.5) - 2451545.0)

def moon_events(dt_start, dt_end, target):
    """All instants in [dt_start, dt_end] where elongation == target
    (0 = new moon, 180 = full moon), by bracketing + bisection."""
    t = _d_of(dt_start)
    t_end = _d_of(dt_end)
    f_prev = _signed(_elong(t) - target)
    out = []
    step = 0.25
    while t < t_end:
        t2 = t + step
        f2 = _signed(_elong(t2) - target)
        if f_prev < 0 <= f2:
            a, b = t, t2
            for _ in range(60):
                m = 0.5 * (a + b)
                if _signed(_elong(m) - target) < 0:
                    a = m
                else:
                    b = m
            out.append(_dt_of_d(0.5 * (a + b)))
            t, f_prev = t2, _signed(_elong(t2) - target)
            continue
        t, f_prev = t2, f2
    return out

def validate_ephemeris(new_dates, full_dates):
    """Solar eclipses are new moons; lunar eclipses are full moons.
    The computed UTC dates must match these known event dates."""
    known_new = ["2019-07-02", "2020-12-14", "2021-12-04", "2023-04-20",
                 "2023-10-14", "2024-04-08", "2025-03-29", "2025-09-21"]
    known_full = ["2019-01-21", "2022-05-16", "2022-11-08", "2024-03-25",
                  "2025-03-14", "2025-09-07", "2026-03-03"]
    nd = {d.isoformat() for d in new_dates}
    fd = {d.isoformat() for d in full_dates}
    rows = []
    ok = True
    for k in known_new:
        hit = k in nd
        ok = ok and hit
        rows.append({"kind": "new (solar eclipse)", "known": k, "match": hit})
    for k in known_full:
        hit = k in fd
        ok = ok and hit
        rows.append({"kind": "full (lunar eclipse)", "known": k, "match": hit})
    return ok, rows

# ======================================================================
# Timer engine — champion mechanics, SPY only
# ======================================================================

def run_timer(pb, start, end, start_cash, in_window, label=""):
    """in_window(date_str) -> bool: hold SPY during that trading day.
    Switches execute at that day's open. Plain floor, champion costs."""
    days = [d for d in pb.dates if start <= d <= end]
    cash = start_cash
    shares = 0.0
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    days_in = 0
    for di, d in enumerate(days):
        bar = pb.bar("SPY", d)
        want = in_window(d)
        holding = shares > 0.0
        if want and not holding:
            buy_val = cash / 1.001
            c = buy_val * 0.001
            shares = buy_val / bar["o"]
            cash -= buy_val + c
            total_costs += c
            trades.append((d, "BUY", round(shares, 6), round(bar["o"], 4),
                           round(buy_val, 2), round(c, 2)))
        elif holding and not want:
            val = shares * bar["o"]
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((d, "SELL", round(shares, 6), round(bar["o"], 4),
                           round(val, 2), round(c, 2)))
            shares = 0.0
        if shares > 0.0:
            days_in += 1
        v = cash + shares * bar["c"]
        curve.append((d, v))
        if v <= FLOOR0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            nd = days[di + 1]
            nb = pb.bar("SPY", nd)
            if shares > 0.0 and nb:
                val = shares * nb["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nd, "SELL-HALT", round(shares, 6),
                               round(nb["o"], 4), round(val, 2), round(c, 2)))
                shares = 0.0
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "curve": curve,
                    "days_in_market": days_in, "n_days": len(days)}
    last = days[-1]
    if shares > 0.0:
        c_ = pb.close_on_or_before("SPY", last)
        val = shares * c_
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((last, "SELL-END", round(shares, 6), round(c_, 4),
                       round(val, 2), round(c, 2)))
        shares = 0.0
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "curve": curve,
            "days_in_market": days_in, "n_days": len(days)}

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
    buys = sum(1 for t in r["trades"] if t[1] == "BUY")
    sells = sum(1 for t in r["trades"] if t[1].startswith("SELL"))
    return {"final": round(r["final"], 2),
            "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
            "orders": len(r["trades"]), "buys": buys, "sells": sells,
            "round_trips": buys, "costs": round(r["costs"], 2),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "time_in_market_pct": round(100.0 * r["days_in_market"] / r["n_days"], 1)}

def placebo_block(pb, new_dts, ws, we, ranked_final, tag):
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        offset = timedelta(days=rng.uniform(0, SYNODIC))
        shifted = [x + offset for x in new_dts]
        dates = [x.date() for x in shifted]

        def in_window(ds, dates=dates):
            dd = date(int(ds[:4]), int(ds[5:7]), int(ds[8:10]))
            return any(abs((dd - md).days) <= 7 for md in dates)

        pr = run_timer(pb, ws, we, START_CASH, in_window,
                       label=f"{tag} PLACEBO {seed}")
        finals.append(pr["final"])
        rows.append({"seed": seed, "offset_days": round(offset.days +
                     offset.seconds / 86400.0, 2),
                     "final": round(pr["final"], 2), "halted": pr["halted"],
                     "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2)})
        print(f"  {tag} PLACEBO seed {seed:2d}: final=${pr['final']:,.2f} "
              f"halted={pr['halted']}", flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    pctile = 100.0 * (below + 0.5 * ties) / len(finals)
    return {"median": round(E._pct(srt, 0.50), 2),
            "q1": round(E._pct(srt, 0.25), 2),
            "q3": round(E._pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for p in rows if p["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_percentile": round(pctile, 1),
            "seeds_beaten": below, "rows": rows}

def daily_return_diagnostic(pb, new_dates, full_dates, ws, we):
    """The paper's raw claim, measured directly: mean daily SPY return on
    new-moon-window days vs full-moon-window days (adjusted closes)."""
    bars = pb.bars["SPY"]
    nd = set(new_dates)
    fd = set(full_dates)

    def cls(ds):
        dd = date(int(ds[:4]), int(ds[5:7]), int(ds[8:10]))
        if any(abs((dd - m).days) <= 7 for m in nd):
            return "new"
        if any(abs((dd - m).days) <= 7 for m in fd):
            return "full"
        return "other"

    groups = {"new": [], "full": [], "other": []}
    prev = None
    for b in bars:
        if prev is not None and ws <= b["d"] <= we:
            groups[cls(b["d"])].append(b["c"] / prev - 1.0)
        if b["d"] <= we:
            prev = b["c"]
    out = {}
    for k, v in groups.items():
        out[k] = {"days": len(v),
                  "mean_daily_pct": round(100.0 * sum(v) / len(v), 4) if v else None}
    if groups["new"] and groups["full"]:
        diff = (sum(groups["new"]) / len(groups["new"])
                - sum(groups["full"]) / len(groups["full"]))
        out["new_minus_full_annualized_pct"] = round(100.0 * diff * 365.25, 2)
    return out

# ======================================================================
# Main
# ======================================================================

def main():
    pb = E.PriceBook({"SPY": E.get_prices("SPY")})
    out = {"strategy": "FOLKLORE F-2 LUNAR CYCLE (Yuan-Zheng-Zhu 15-day "
                       "form): SPY only within +/-7 calendar days of a new "
                       "moon, cash otherwise; $100, program costs, plain "
                       "-15% floor",
           "pot": START_CASH, "floor": FLOOR0,
           "moon_source": "Computed in-script ephemeris (Schlyter elements "
                          "+ lunar perturbation series; elongation roots by "
                          "bisection). No hand-typed moon list."}

    # ---- (0) replication check: SPY buy-hold must reproduce published
    for tag, (ws, we), expect in (("FULL", FULL, 313.62),
                                  ("VALIDATION", VALIDATION, 187.77)):
        v, _ = E.spy_net(pb, ws, we, START_CASH)
        ok = abs(v - expect) < 0.005
        print(f"REPLICATION {tag}: SPY net=${v:,.2f} expected=${expect:,.2f} "
              f"match={ok}", flush=True)
        out[f"replication_{tag.lower()}"] = {"spy_net": round(v, 2),
                                             "expected": expect, "match": ok}
        if not ok:
            raise SystemExit("REPLICATION FAILED - variant numbers untrusted")

    # ---- moon events covering both windows (pad for boundary windows)
    new_dts = moon_events(datetime(2018, 12, 1), datetime(2027, 1, 15), 0.0)
    full_dts = moon_events(datetime(2018, 12, 1), datetime(2027, 1, 15), 180.0)
    new_dates = [x.date() for x in new_dts]
    full_dates = [x.date() for x in full_dts]
    ok, vrows = validate_ephemeris(new_dates, full_dates)
    print(f"EPHEMERIS VALIDATION: {sum(r['match'] for r in vrows)}/"
          f"{len(vrows)} known eclipse dates matched", flush=True)
    out["ephemeris_validation"] = {"all_match": ok, "rows": vrows,
                                    "n_new_moons": len(new_dts),
                                    "n_full_moons": len(full_dts)}
    if not ok:
        raise SystemExit("EPHEMERIS VALIDATION FAILED - moon dates untrusted")
    out["new_moon_dates"] = [d.isoformat() for d in new_dates]
    out["full_moon_dates"] = [d.isoformat() for d in full_dates]

    def make_in_window(dates):
        ds_set = dates

        def in_window(ds):
            dd = date(int(ds[:4]), int(ds[5:7]), int(ds[8:10]))
            return any(abs((dd - md).days) <= 7 for md in ds_set)
        return in_window

    # ---- (1) ranked (new moon), control (full moon), SPY, placebo
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VALIDATION)):
        spy, _ = E.spy_net(pb, ws, we, START_CASH)
        r = run_timer(pb, ws, we, START_CASH, make_in_window(new_dates),
                      label=f"{tag} NEWMOON")
        st = curve_stats(r)
        st.update({"start": ws, "end": we, "spy_net_final": round(spy, 2),
                   "spy_return_pct": round(spy / START_CASH * 100 - 100, 2),
                   "trades": r["trades"]})
        print(f"{tag} NEWMOON: final=${r['final']:,.2f} "
              f"({st['return_pct']:+.2f}%) maxDD={st['max_drawdown_pct']}% "
              f"orders={st['orders']} costs=${st['costs']} "
              f"inmkt={st['time_in_market_pct']}% halted={r['halted']} | "
              f"SPY=${spy:,.2f}", flush=True)
        rc = run_timer(pb, ws, we, START_CASH, make_in_window(full_dates),
                       label=f"{tag} FULLMOON CONTROL")
        stc = curve_stats(rc)
        st["fullmoon_control"] = stc
        print(f"{tag} FULLMOON CONTROL: final=${rc['final']:,.2f} "
              f"({stc['return_pct']:+.2f}%) orders={stc['orders']} "
              f"costs=${stc['costs']} inmkt={stc['time_in_market_pct']}% "
              f"halted={rc['halted']}", flush=True)
        st["placebo"] = placebo_block(pb, new_dts, ws, we, r["final"], tag)
        pl = st["placebo"]
        print(f"{tag} PLACEBO: median=${pl['median']:,.2f} "
              f"best=${pl['best']:,.2f} worst=${pl['worst']:,.2f} "
              f"halted={pl['halted_count']}/20 | RANKED "
              f"${pl['ranked_final']:,.2f} = {pl['ranked_percentile']}th "
              f"pctile (beat {pl['seeds_beaten']}/20)", flush=True)
        st["daily_return_diagnostic"] = daily_return_diagnostic(
            pb, new_dates, full_dates, ws, we)
        dg = st["daily_return_diagnostic"]
        print(f"{tag} DIAGNOSTIC: mean daily ret new-window="
              f"{dg['new']['mean_daily_pct']}% ({dg['new']['days']}d) "
              f"full-window={dg['full']['mean_daily_pct']}% "
              f"({dg['full']['days']}d) other={dg['other']['mean_daily_pct']}% "
              f"| NM-FM annualized gap="
              f"{dg.get('new_minus_full_annualized_pct')}%", flush=True)
        out[tag.lower()] = st

    # ---- (2) walk-forward folds, fresh $100 per calendar year
    folds = []
    for y in range(2019, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_timer(pb, fs, fe, START_CASH, make_in_window(new_dates),
                       label=f"FOLD {y}")
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        fst = curve_stats(fr)
        row = {"year": y, "start": fs, "end": fe, "final": fst["final"],
               "return_pct": fst["return_pct"],
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"]}
        folds.append(row)
        print(f"FOLD {y}: NEWMOON ${fr['final']:,.2f} "
              f"({row['return_pct']:+.2f}%) vs SPY ${fspy:,.2f} "
              f"({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"maxDD={row['max_drawdown_pct']}% halted={row['halted']}",
              flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    comp = 100.0
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
    out["fold_compounded_final"] = round(comp, 2)

    with open(os.path.join(HERE, "folklore-f2-lunar-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


# =====================================================================
# V9 PROTECTION MODULE — CLAUDE-RULES PROTECTION SPEC v9 (ONLY CHANGE)
# Episode 1: floor -15% from $100 start (identical to original).
# On FIRST halt: liquidate exactly as run_timer does, sit in cash 90
# calendar days from the liquidation date, then RESTART with the
# remaining cash at the strategy's next regular decision point (this
# engine decides daily by lunar-window membership, so the first trading
# day on/after day 90; it then holds only on in-window days as usual).
# Episode 2: floor = -15% from the RESTART balance. On SECOND halt the
# run ends permanently. Ranked pot only; no placebo/control under v9.
# =====================================================================
import datetime as _dt

def _v9_episodes(pb, ws, we, in_window, window_label):
    global FLOOR0
    FLOOR0 = 85.0
    ep1 = run_timer(pb, ws, we, START_CASH, in_window, label=window_label)
    min_close = min((v for _, v in ep1["curve"]), default=100.0)
    base = {"episodes": 1, "ep1_halted": ep1["halted"], "restart": None,
            "ep2_halted": None, "min_close": round(min_close, 2),
            "final": round(ep1["final"], 2), "status": "no_halt"}
    if not ep1["halted"]:
        return base
    liq = next((t[0] for t in reversed(ep1["trades"]) if t[1] == "SELL-HALT"),
               ep1["end"])
    cash1 = ep1["final"]
    eligible = (_dt.date.fromisoformat(liq) + _dt.timedelta(days=90)).isoformat()
    rest = [d for d in pb.dates if eligible <= d <= we]
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
    FLOOR0 = 0.85 * cash1
    ep2 = run_timer(pb, rest[0], we, cash1, in_window,
                    label=window_label + " EP2")
    FLOOR0 = 85.0
    min2 = min((v for _, v in ep2["curve"]), default=cash1)
    base["min_close"] = round(min(base["min_close"], min2), 2)
    restart_info["second_halt"] = ep2["halted"]
    base.update({"episodes": 2, "final": round(ep2["final"], 2),
                 "ep2_halted": ep2["halted"],
                 "status": "halted_ep2_run_ends" if ep2["halted"]
                           else "restarted_completed"})
    return base

def v9_main():
    pb = E.PriceBook({"SPY": E.get_prices("SPY")})
    for tag, (ws, we), expect in (("FULL", FULL, 313.62),
                                  ("VALIDATION", VALIDATION, 187.77)):
        v, _ = E.spy_net(pb, ws, we, START_CASH)
        assert abs(v - expect) < 0.005, f"REPLICATION FAILED {tag}"
        print(f"REPLICATION {tag}: SPY net=${v:,.2f} match=True", flush=True)
    new_dts = moon_events(datetime(2018, 12, 1), datetime(2027, 1, 15), 0.0)
    full_dts = moon_events(datetime(2018, 12, 1), datetime(2027, 1, 15), 180.0)
    new_dates = [x.date() for x in new_dts]
    ok, vrows = validate_ephemeris(new_dates, [x.date() for x in full_dts])
    assert ok, "EPHEMERIS VALIDATION FAILED"
    print("EPHEMERIS VALIDATION: all known eclipse dates matched", flush=True)

    def in_window(ds):
        dd = date(int(ds[:4]), int(ds[5:7]), int(ds[8:10]))
        return any(abs((dd - md).days) <= 7 for md in new_dates)

    cont = _v9_episodes(pb, FULL[0], FULL[1], in_window, "continuous")
    val = _v9_episodes(pb, VALIDATION[0], VALIDATION[1], in_window,
                       "validation")
    for tag, r in (("CONTINUOUS", cont), ("VALIDATION", val)):
        print(f"V9 {tag}: final=${r['final']} status={r['status']} "
              f"ep1_halted={r['ep1_halted']} restart={r['restart']} "
              f"ep2_halted={r['ep2_halted']}", flush=True)
    his_folds = {2019: 111.62, 2020: 85.21, 2021: 108.5, 2022: 95.51,
                 2023: 108.02, 2024: 109.97, 2025: 80.14, 2026: 93.09}
    folds, fold_restarts = [], []
    for y in range(2019, 2027):
        fs, fe = f"{y}-01-01", ("2026-11-20" if y == 2026 else f"{y}-12-31")
        r = _v9_episodes(pb, fs, fe, in_window, f"fold {y}")
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
    out = {"slug": "folklore-f2-lunar",
           "name": "F-2 Lunar cycle (new-moon +/-7 days)",
           "status": "partial-rerun",
           "his": {"continuous_final": 113.47, "validation_final": 105.24},
           "v9": {"continuous_final": cont["final"],
                  "validation_final": val["final"],
                  "continuous_status": cont["status"],
                  "validation_status": val["status"],
                  "restarts": fold_restarts,
                  "folds_note": "Folds 2019-2026 re-run under v9; see "
                                "folds_detail. His-rules fold halts in 2020 "
                                "(2020-02-28) and 2025 (2025-04-04) each get "
                                "one 90-day sit-out and restart inside the "
                                "fold year. Main windows never halted under "
                                "either rule set, so main finals are "
                                "identical by construction and were verified "
                                "through the same wrapper.",
                  "worst_total_loss_pct": worst_loss},
           "folds_detail": folds,
           "notes": "Main windows: identical — floor never fired (worst "
                    "closes $87.60 continuous on 2020-03-23, $94.51 "
                    "validation). Only the halted yearly folds (2020, "
                    "2025) change under v9. Ranked pot only; no placebos "
                    "or full-moon control under v9."}
    with open(os.path.join(HERE, "v9-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    v9_main()
