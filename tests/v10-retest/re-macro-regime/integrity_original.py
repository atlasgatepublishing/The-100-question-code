#!/usr/bin/env python3
"""
FOUR-BOX MACRO-REGIME TILT (Bridgewater shadow, long-only) — Terry's AI stock
app, simulation only. Spec: research/v7-completeness/firm-reverse-engineering.md
section 4.3, implemented EXACTLY as written. Run once, no tuning.

Rule (frozen):
  Data: vintage CPI and industrial production — point-in-time: at each
  month-end decision date, only the vintage actually published by that date.
  Regime: growth is RISING if the latest vintage INDPRO year-over-year change
  is higher than it was 6 months earlier, else FALLING; inflation likewise
  from CPI year-over-year. (Within-vintage reading: both YoY values are
  computed from the single vintage snapshot available at the decision date —
  YoY at the latest observation vs YoY six observation-months earlier.)
  Weights (SPY / TLT / GLD / DBC), fixed by the spec's table:
    Rising growth,  falling inflation -> 70 / 20 / 10 /  0
    Rising growth,  rising  inflation -> 40 /  0 / 20 / 40
    Falling growth, rising  inflation -> 10 / 10 / 50 / 30
    Falling growth, falling inflation -> 20 / 60 / 20 /  0
  Timing: decide at month-end close on the latest available vintage; fill at
  next trading day's open; monthly cadence; full rebalance to table weights.
  Costs: 0.10% of trade value per side + $0.01 per sell order (program
  standard); a 2x-cost stress is reported alongside.
  Floor: plain -15% — a daily close at or below $85 halts the pot (liquidate
  at next open) and the halt is the result.
  Judging: continuous 2019-01-01 -> 2026-11-20 and validation
  2023-01-01 -> 2026-11-20 vs SPY buy-hold (net), vs static 60/40 SPY/TLT
  buy-hold (net), vs the promoted ETF trend sleeve (published numbers), and
  vs 20 shuffled-regime placebos. Pre-registered gate: beat SPY AND the
  shuffled-regime placebo median on validation, with continuous max
  drawdown better than SPY's.

DATA ACCESS (documented in the report): ALFRED's and FRED's web hosts are
unreachable from this sandbox (connection timeouts) and the FRED API needs a
personal key this program does not hold. The vintage data therefore comes
from the Federal Reserve Bank of Philadelphia's Real-Time Data Set for
Macroeconomists (Croushore & Stark) — the other Federal Reserve archival of
the same series' vintages: PCPI (CPI-U, seasonally adjusted = CPIAUCSL) and
IPT (total industrial production = INDPRO). Its vintage columns are dated by
month; a decision at the end of month M uses the vintage column for month M,
whose latest observation is month M-1 — the data physically published by
that month-end. Prices: the program's existing Yahoo caches in
backtests/v3/data_etf (dividend+split adjusted; opens scaled by
adjclose/close) — the same series the trend sleeve used; SPY buy-hold
replicates the program's published $313.62 / $187.77 to the cent.
"""
import json, math, os, random, statistics, sys, urllib.request
from datetime import datetime, timezone

ASSETS = ["SPY", "TLT", "GLD", "DBC"]
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
PRICE_CACHE = "/home/hatch/workspace/stock-app/backtests/v3/data_etf"
os.makedirs(DATA_DIR, exist_ok=True)

COST_RATE = 0.0010
SELL_FEE = 0.01
START_CASH = 100.0
FLOOR = 85.0

WEIGHTS = {
    ("R", "F"): {"SPY": 0.70, "TLT": 0.20, "GLD": 0.10, "DBC": 0.00},
    ("R", "R"): {"SPY": 0.40, "TLT": 0.00, "GLD": 0.20, "DBC": 0.40},
    ("F", "R"): {"SPY": 0.10, "TLT": 0.10, "GLD": 0.50, "DBC": 0.30},
    ("F", "F"): {"SPY": 0.20, "TLT": 0.60, "GLD": 0.20, "DBC": 0.00},
}
BOX_NAME = {
    ("R", "F"): "Rising growth / Falling inflation",
    ("R", "R"): "Rising growth / Rising inflation",
    ("F", "R"): "Falling growth / Rising inflation",
    ("F", "F"): "Falling growth / Falling inflation",
}

# ---------------------------------------------------------------- prices
def load_series(ticker):
    """dict date->(adj_open, adj_close) from the program's Yahoo cache."""
    path = os.path.join(PRICE_CACHE, f"{ticker}.json")
    with open(path) as f:
        data = json.load(f)
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = None
    if "adjclose" in res["indicators"]:
        adj = res["indicators"]["adjclose"][0]["adjclose"]
    out = {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        c = q["close"][i]
        o = q["open"][i]
        if c is None or o is None:
            continue
        if adj is not None and adj[i]:
            ratio = adj[i] / c
            out[d] = (o * ratio, adj[i])
        else:
            out[d] = (o, c)
    return out


SERIES = {t: load_series(t) for t in ASSETS}
CAL = sorted(SERIES["SPY"].keys())
CAL_IDX = {d: i for i, d in enumerate(CAL)}


def close_on(ticker, date):
    s = SERIES[ticker]
    if date in s:
        return s[date][1]
    i = CAL_IDX[date]
    for j in range(i - 1, -1, -1):
        if CAL[j] in s:
            return s[CAL[j]][1]
    return None


def open_on(ticker, date):
    s = SERIES[ticker]
    if date in s:
        return s[date][0]
    return close_on(ticker, date)


# ---------------------------------------------------------------- macro vintages
MACRO_FILES = {
    "CPI": ("pcpiMvMd.xlsx", "PCPI",
            "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/real-time-data/data-files/xlsx/pcpiMvMd.xlsx"),
    "IP": ("iptMvMd.xlsx", "IPT",
           "https://www.philadelphiafed.org/-/media/FRBP/Assets/Surveys-And-Data/real-time-data/data-files/xlsx/iptMvMd.xlsx"),
}


def fetch_macro():
    for _, (fn, _, url) in MACRO_FILES.items():
        path = os.path.join(DATA_DIR, fn)
        if not os.path.exists(path):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
                f.write(r.read())


def parse_vintage_label(label, prefix):
    """'PCPI18M12' -> (2018, 12)."""
    rest = label[len(prefix):]
    yy, mm = rest.split("M")
    yy = int(yy)
    year = 1900 + yy if yy >= 62 else 2000 + yy
    return year, int(mm)


def load_matrix(series_key):
    """Return {(vintage_year, vintage_month): {obs_index: value}}.
    obs_index = obs_year*12 + (obs_month-1)."""
    import openpyxl
    fn, prefix, _ = MACRO_FILES[series_key]
    wb = openpyxl.load_workbook(os.path.join(DATA_DIR, fn), read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    header = rows[0]
    vintages = []
    for h in header[1:]:
        vintages.append(parse_vintage_label(str(h), prefix))
    out = {}
    for r in rows[1:]:
        d = str(r[0])
        y, m = d.split(":")
        oi = int(y) * 12 + (int(m) - 1)
        for ci, v in enumerate(r[1:]):
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            out.setdefault(vintages[ci], {})[oi] = fv
    return out


def _at_or_before(snap, idx):
    """Value at idx, or at the nearest available observation at or before
    idx. Needed exactly once in this data: CPI for 2025-10 was never
    published (BLS cancelled the release during the fall-2025 federal
    shutdown), leaving a permanent hole in every later vintage."""
    while idx not in snap:
        idx -= 1
    return snap[idx]


def classify(matrix, dec_year, dec_month):
    """Regime from the vintage published by the end of (dec_year, dec_month).
    Returns (direction 'R'/'F', detail dict). Direction: YoY at the latest
    observation vs YoY six observation-months earlier, same vintage."""
    snap = matrix.get((dec_year, dec_month))
    if snap is None:
        raise KeyError(f"no vintage for {dec_year}-{dec_month:02d}")
    latest = max(snap.keys())
    yoy_now = _at_or_before(snap, latest) / _at_or_before(snap, latest - 12) - 1.0
    yoy_prev = _at_or_before(snap, latest - 6) / _at_or_before(snap, latest - 18) - 1.0
    direction = "R" if yoy_now > yoy_prev else "F"
    ly, lm = divmod(latest, 12)
    detail = {
        "latest_obs": f"{ly}-{lm + 1:02d}",
        "yoy_now_pct": round(yoy_now * 100, 3),
        "yoy_6mo_earlier_pct": round(yoy_prev * 100, 3),
    }
    return direction, detail


def build_schedule(mat_cpi, mat_ip, first_dec, last_dec):
    """Monthly decisions from first_dec to last_dec inclusive, each a
    (year, month) decision month. Returns list of dicts."""
    sched = []
    y, m = first_dec
    while (y, m) <= last_dec:
        g, gd = classify(mat_ip, y, m)
        i, idd = classify(mat_cpi, y, m)
        box = (g, i)
        sched.append({
            "decision_month": f"{y}-{m:02d}",
            "growth": g, "inflation": i, "box": BOX_NAME[box],
            "weights": WEIGHTS[box],
            "ip_latest_obs": gd["latest_obs"], "ip_yoy_now": gd["yoy_now_pct"],
            "ip_yoy_prev": gd["yoy_6mo_earlier_pct"],
            "cpi_latest_obs": idd["latest_obs"], "cpi_yoy_now": idd["yoy_now_pct"],
            "cpi_yoy_prev": idd["yoy_6mo_earlier_pct"],
        })
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return sched


# ---------------------------------------------------------------- engine
def month_eval_days(first_day, last_day):
    """Last trading day of each calendar month in [first_day, last_day]."""
    days = [d for d in CAL if first_day <= d <= last_day]
    by_month = {}
    for d in days:
        by_month.setdefault(d[:7], []).append(d)
    return {max(ds) for ds in by_month.values()}


def simulate(start, end, schedule, cost_rate=COST_RATE, sell_fee=SELL_FEE):
    """schedule: list of decision dicts (chronological). The decision for
    calendar month M is made at the close of M's last trading day and filled
    at the next trading day's open. The run's first decision month is the
    month just before `start`'s month (so the pot is invested from the
    first trading day >= start)."""
    first_eval_month = schedule[0]["decision_month"]
    # trading days from the first decision month through end
    days = [d for d in CAL if d[:7] >= first_eval_month and d <= end]
    eval_days = month_eval_days(days[0], end)
    sched_by_month = {s["decision_month"]: s for s in schedule}

    cash = START_CASH
    shares = {t: 0.0 for t in ASSETS}
    orders = 0
    total_costs = 0.0
    trades_log = []
    curve = []
    pending = None
    halted = None
    in_force = []  # (fill_date, decision_month, weights) actually applied

    def equity_at(date, price_fn):
        eq = cash
        for t in ASSETS:
            if shares[t] > 0:
                p = price_fn(t, date)
                if p:
                    eq += shares[t] * p
        return eq

    for di, d in enumerate(days):
        # --- execute pending rebalance at today's open ---
        if pending is not None:
            targets, dec_month = pending
            eq_open = equity_at(d, open_on)
            for t in ASSETS:  # sells first
                tgt_val = targets.get(t, 0.0) * eq_open
                cur_val = shares[t] * open_on(t, d)
                diff = cur_val - tgt_val
                if diff > 0.01 and shares[t] > 0:
                    sell_val = min(diff, cur_val)
                    sh = sell_val / open_on(t, d)
                    cost = sell_val * cost_rate + sell_fee
                    cash += sell_val - cost
                    shares[t] -= sh
                    if shares[t] < 1e-9:
                        shares[t] = 0.0
                    orders += 1
                    total_costs += cost
                    trades_log.append((d, "SELL", t, round(sell_val, 2)))
            buy_list = []
            for t in ASSETS:
                tgt_val = targets.get(t, 0.0) * eq_open
                cur_val = shares[t] * open_on(t, d)
                diff = tgt_val - cur_val
                if diff > 0.01:
                    buy_list.append((t, diff))
            tot_buy = sum(v for _, v in buy_list)
            if tot_buy > 0:
                scale = min(1.0, cash / (tot_buy * (1 + cost_rate)))
                for t, diff in buy_list:
                    buy_val = diff * scale
                    if buy_val < 0.01:
                        continue
                    cost = buy_val * cost_rate
                    cash -= buy_val + cost
                    shares[t] += buy_val / open_on(t, d)
                    orders += 1
                    total_costs += cost
                    trades_log.append((d, "BUY", t, round(buy_val, 2)))
            in_force.append((d, dec_month, dict(targets)))
            pending = None

        # --- mark to close; floor check ---
        eq_close = equity_at(d, close_on)
        if d >= start:
            curve.append((d, eq_close))
        if eq_close <= FLOOR:
            if di + 1 < len(days):
                nd = days[di + 1]
                # liquidate at next open
                for t in ASSETS:
                    if shares[t] > 0:
                        val = shares[t] * open_on(t, nd)
                        cost = val * cost_rate + sell_fee
                        cash += val - cost
                        total_costs += cost
                        orders += 1
                        trades_log.append((nd, "SELL-HALT", t, round(val, 2)))
                        shares[t] = 0.0
                halted = nd
                if nd >= start:
                    curve.append((nd, cash))
            else:
                # breach on the final day: value at close less liquidation cost
                liq = cash
                for t in ASSETS:
                    if shares[t] > 0:
                        val = shares[t] * close_on(t, d)
                        liq += val - (val * cost_rate + sell_fee)
                cash = liq
                halted = d
                if curve and curve[-1][0] == d:
                    curve[-1] = (d, cash)
            break

        # --- month-end decision at today's close ---
        if d in eval_days and di + 1 < len(days):
            s = sched_by_month.get(d[:7])
            if s is not None:
                pending = (s["weights"], s["decision_month"])

    final_eq = curve[-1][1] if curve else START_CASH
    return {"final": final_eq, "curve": curve, "orders": orders,
            "costs": total_costs, "halted": halted, "trades": trades_log,
            "in_force": in_force}


def metrics(res):
    curve = res["curve"]
    yrs = (datetime.strptime(curve[-1][0], "%Y-%m-%d")
           - datetime.strptime(curve[0][0], "%Y-%m-%d")).days / 365.25
    cagr = (res["final"] / START_CASH) ** (1 / yrs) - 1 if yrs > 0 else 0.0
    peak, maxdd, worst = -1e18, 0.0, None
    for d, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            dd = eq / peak - 1.0
            if dd < maxdd:
                maxdd = dd
        if worst is None or eq < worst[1]:
            worst = (d, eq)
    return {"cagr": cagr, "maxdd": maxdd, "years": yrs,
            "worst_close": worst}


def buy_hold(weights, start, end):
    """Static buy-hold, net of costs (house convention, matches published
    program SPY figures to the cent)."""
    days = [d for d in CAL if start <= d <= end]
    d0, d1 = days[0], days[-1]
    total = 0.0
    for t, w in weights.items():
        amt = START_CASH * w
        sh = (amt - amt * COST_RATE) / open_on(t, d0)
        val = sh * close_on(t, d1)
        total += val - (val * COST_RATE + SELL_FEE)
    return total


def spy_curve(start, end):
    """Daily equity curve of $100 SPY buy-hold (for drawdown)."""
    days = [d for d in CAL if start <= d <= end]
    d0 = days[0]
    amt = START_CASH
    sh = (amt - amt * COST_RATE) / open_on("SPY", d0)
    return [(d, sh * close_on("SPY", d)) for d in days]


def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            mdd = min(mdd, eq / peak - 1.0)
    return mdd


def turnover_of(schedule):
    """Mean monthly sum |delta weight| across the schedule's decisions."""
    prev = None
    tot, n = 0.0, 0
    for s in schedule:
        w = s["weights"]
        if prev is not None:
            tot += sum(abs(w[t] - prev[t]) for t in ASSETS)
            n += 1
        prev = w
    return tot / n if n else 0.0


def run_window(mat_cpi, mat_ip, start, end, first_dec, last_dec, label):
    schedule = build_schedule(mat_cpi, mat_ip, first_dec, last_dec)
    res = simulate(start, end, schedule)
    m = metrics(res)
    spy = buy_hold({"SPY": 1.0}, start, end)
    s6040 = buy_hold({"SPY": 0.6, "TLT": 0.4}, start, end)
    stress = simulate(start, end, schedule, cost_rate=COST_RATE * 2, sell_fee=SELL_FEE * 2)
    # placebos: permute this window's weight vectors across its decision months
    base_weights = [s["weights"] for s in schedule]
    placebo_finals = []
    placebo_turns = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        perm = base_weights[:]
        rng.shuffle(perm)
        psched = []
        for s, w in zip(schedule, perm):
            s2 = dict(s)
            s2["weights"] = w
            psched.append(s2)
        pres = simulate(start, end, psched)
        placebo_finals.append({"seed": seed, "final": round(pres["final"], 2),
                               "halted": pres["halted"]})
        placebo_turns.append(turnover_of(psched))
    pf = sorted(p["final"] for p in placebo_finals)
    med = statistics.median(pf)
    beaten = sum(1 for p in placebo_finals if res["final"] > p["final"])
    rec = {
        "label": label, "start": start, "end": end,
        "final": round(res["final"], 2),
        "return_pct": round((res["final"] / START_CASH - 1) * 100, 2),
        "cagr_pct": round(m["cagr"] * 100, 2),
        "maxdd_pct": round(m["maxdd"] * 100, 2),
        "worst_close": [m["worst_close"][0], round(m["worst_close"][1], 2)],
        "orders": res["orders"], "costs": round(res["costs"], 2),
        "halted": res["halted"],
        "spy_final": round(spy, 2), "spy6040_final": round(s6040, 2),
        "stress2x_final": round(stress["final"], 2),
        "stress2x_halted": stress["halted"],
        "mean_monthly_turnover": round(turnover_of(schedule), 4),
        "placebo": {
            "median": round(med, 2),
            "q1": round(pf[4], 2), "q3": round(pf[14], 2),
            "best": round(pf[-1], 2), "worst": round(pf[0], 2),
            "seeds_beaten": beaten,
            "mean_monthly_turnover_median": round(statistics.median(placebo_turns), 4),
            "rows": placebo_finals,
        },
        "schedule": schedule,
        "year_end": {},
    }
    for d, eq in res["curve"]:
        rec["year_end"][d[:4]] = round(eq, 2)
    print(f"\n== {label} ({start} -> {end}) ==")
    print(f"strategy final=${res['final']:.2f} ({rec['return_pct']:+.2f}%) CAGR={rec['cagr_pct']:+.2f}% "
          f"maxDD={rec['maxdd_pct']:.2f}% orders={res['orders']} costs=${res['costs']:.2f} halted={res['halted']}")
    print(f"SPY=${spy:.2f}  60/40=${s6040:.2f}  2x-cost stress=${stress['final']:.2f} (halted={stress['halted']})")
    print(f"placebo median=${med:.2f} q1=${pf[4]:.2f} q3=${pf[14]:.2f} best=${pf[-1]:.2f} worst=${pf[0]:.2f} "
          f"| strategy beat {beaten}/20")
    return rec


def main():
    fetch_macro()
    mat_cpi = load_matrix("CPI")
    mat_ip = load_matrix("IP")
    out = {"strategy": "FOUR-BOX MACRO-REGIME TILT (Bridgewater shadow) — spec 4.3, firm-reverse-engineering.md",
           "pot": START_CASH, "floor": FLOOR,
           "costs": "0.10%/side + $0.01/sell; 2x stress doubles both"}

    cont = run_window(mat_cpi, mat_ip, "2019-01-01", "2026-11-20", (2018, 12), (2026, 10),
                      "CONTINUOUS")
    out["continuous"] = cont
    val = run_window(mat_cpi, mat_ip, "2023-01-01", "2026-11-20", (2022, 12), (2026, 10),
                     "VALIDATION")
    out["validation"] = val

    spy_dd = max_dd(spy_curve("2019-01-01", "2026-11-20"))
    out["spy_continuous_maxdd_pct"] = round(spy_dd * 100, 2)
    print(f"\nSPY continuous max drawdown: {spy_dd * 100:.2f}%")

    gates = {
        "validation_beats_spy": val["final"] > val["spy_final"],
        "validation_beats_placebo_median": val["final"] > val["placebo"]["median"],
        "continuous_maxdd_better_than_spy": cont["maxdd_pct"] > out["spy_continuous_maxdd_pct"],
    }
    gates["promoted"] = all(gates.values())
    out["gates"] = gates
    print("GATES:", json.dumps(gates, indent=1))

    with open(os.path.join(HERE, "re-macro-regime-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("\nDONE — saved re-macro-regime-results.json")


if __name__ == "__main__":
    main()
