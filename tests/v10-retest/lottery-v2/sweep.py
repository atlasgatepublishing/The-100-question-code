#!/usr/bin/env python3
"""
lottery-v2 -- THE GREAT RETEST (v10) CADENCE SWEEP.

Strategy: penny-stock lottery pot, v2 form (backtests/v2/lottery-v2.py).
Variant A only (variant B's SPY-200dma entry block never bound in the
original run -- B finished trade-for-trade identical to A -- so the sweep
runs the A form and says so).

ORIGINAL v2 RULES (integrity form, window 2025-11-21 -> 2026-11-20):
  - Candidate list: 71 tickers assembled Nov 2026 (survivorship-tilted,
    stated in the original report). Monthly point-in-time screen on the
    last trading day of the prior month: US exchange-listed equity
    (Yahoo meta exchangeName in {NMS,NGM,NCM,NYQ,ASE,AMX},
    instrumentType EQUITY), close < $5.00, trailing-20-day average daily
    DOLLAR volume > $20,000,000 (v0 used $5M and a monthly screen too).
  - Evening ranking (v0 mechanics): score = prior-day % gain x volume
    spike (day volume / trailing-20d avg volume), positive scores only,
    held names excluded. Buys decided the evening before, filled at the
    next day's open.
  - At most ONE new entry per day (top-ranked only), at most 2 new
    entries per calendar week; max 5 positions; max 15% of pot per name
    (v0: 20%); no averaging down.
  - Exits checked daily on the bar: stop -15% from entry, take-profit
    +40% (v0: -10%/+25%); stop fills first if both touched; gap-down
    opens fill at the open.
  - Costs: 2.0% of trade value on EVERY buy and sell + $0.01 per sell
    order. (This 2%/side proportional charge IS the penny book's modeled
    spread/slippage -- reported separately below as the spread component;
    the $0.01 is the order-fee component.)
  - Cost gate: skip if round-trip cost (4.0% of position) > 10% of the
    +40% target gain (also 4.0%) -- as specified it can never bind; kept
    for fidelity.
  - ORIGINAL protection: Terry's floor LADDER ($85 start; $100 after a
    $125 close; $125 after a $150 close); a close at/below the floor
    liquidated at the next open and ENDED the run.
  - v2 vs v0: $20M volume bar (v0 $5M), 1 entry/day + 2/week (v0 bought
    every ranked name daily), 15% tickets (v0 20%), -15%/+40% exits
    (v0 -10%/+25%). v2 vs Terry's later v3 decision: v3 moved to a
    16-config book on a point-in-time listed sub-$5 universe with
    min-volume / max-spread filters and limit orders; v2 instead used
    this fixed, hindsight-assembled 71-name candidate list, a $20M
    dollar-volume screen, and market-style fills at the open with the
    2%/side friction model standing in for spread. Those v3 changes are
    NOT back-ported here -- the sweep runs the v2 form.

SWEEP TREATMENT (SPEC uniform cadence definition, stated):
  - Road: DECADE 2016-11-21 -> 2026-11-20, $100 per cell.
  - Cadence governs the SCREEN / REVIEW rhythm: the universe screen,
    the evening ranking + entry decision, and the stop/TP exit checks
    happen ONLY on cadence dates. Screen date and signal day are the
    last trading day before the cadence date; entries fill at the
    cadence date's open; exits are judged on the cadence date's bar.
    (Native cadence = daily: v2 screened monthly but ranked/entered and
    checked exits daily; under the uniform rule the daily cell refreshes
    the screen daily too -- the one stated deviation inside the native
    cell.)
  - The 2-entries-per-calendar-week cap and 1-entry-per-decision cap
    are kept verbatim (non-binding at weekly-and-slower cadences).
  - Protection: v9 rules substituted for the ladder -- plain -15%
    floor from the episode's starting balance, checked on EVERY
    trading day's close (protection layer, not cadence-governed);
    first halt liquidates at the next open, cash sits 90 calendar
    days, restart at the next cadence date with an episode-2 floor of
    -15% from the restart balance; second halt ends the run.
    IN A PENNY BOOK THE FLOOR IS A TARGET, NOT A GUARANTEE: gap-down
    opens and no-bar days can carry the pot through the floor before
    any liquidation can happen, and liquidation fills use the next
    available bar.
  - Placebos: 20 seeds per cell; on each entry decision the twin buys
    a uniformly random name from the same evening's positive-score
    ranked list (same screen, sizing, exits, cadence, protections).

Data: Yahoo chart API daily OHLCV fetched 2016-01-01..2026-11-22 into
data_cache_decade/ by fetch_decade.py (split-adjusted, not
dividend-adjusted -- same convention as the original). Fetch failures
(excluded everywhere, documented, never patched): SAVA, SDIG, GREE,
MULN, NKLA, GOEV, TEF, NGD.
"""
import bisect, json, os, random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data_cache_decade")
ET = ZoneInfo("America/New_York")

START, END = "2016-11-21", "2026-11-20"
START_CASH = 100.00
MAX_POSITIONS = 5
MAX_PER_NAME_FRAC = 0.15
STOP_FRAC, TP_FRAC = 0.15, 0.40
COST_RATE, SELL_FEE = 0.02, 0.01
SCREEN_MAX_PRICE = 5.00
SCREEN_MIN_AVG_DV = 20_000_000
MAX_ENTRIES_PER_WEEK = 2
GATE_COST_FRAC, GATE_LIMIT_FRAC = 0.04, 0.04
LISTED = {"NMS", "NGM", "NCM", "NYQ", "ASE", "AMX"}
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

CANDIDATES = [
    "PLUG", "FCEL", "BLDP", "SNDL", "ACB", "CGC", "TLRY", "OGI", "CRON",
    "BYND", "GERN", "IOVA", "RXRX", "PACB", "DNA", "EDIT", "OCGN", "SAVA",
    "BTBT", "SDIG", "GREE", "CAN", "EBON", "SOS", "MULN", "FFAI", "NKLA",
    "GOEV", "WKHS", "BLNK", "EVGO", "CHPT", "SPCE", "JBLU", "ULCC", "AMC",
    "BB", "NOK", "KOSS", "VFS", "PSNY", "NIO", "GRAB", "FINV", "NNDM",
    "DDD", "EXK", "FSM", "HYMC", "TEF", "BBAI", "OPEN", "PTON", "TDOC",
    "LCID", "CLOV", "ACHR", "CIFR", "AGEN", "INO", "NVAX", "LX", "IQ",
    "TUYA", "NGD", "BTG", "DNN", "CLNE", "GEVO",
]

# ---------------------------------------------------------------- data
def load_symbol(sym):
    path = os.path.join(CACHE, f"{sym}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    res = data.get("chart", {}).get("result")
    if not res:
        return None
    r = res[0]
    meta = r.get("meta", {})
    q = r.get("indicators", {}).get("quote", [{}])[0]
    dates, O, H, L, C, V = [], [], [], [], [], []
    for i, t in enumerate(r.get("timestamp", []) or []):
        try:
            o, h, l, c, v = (q["open"][i], q["high"][i], q["low"][i],
                             q["close"][i], q["volume"][i])
        except (KeyError, IndexError, TypeError):
            continue
        if None in (o, h, l, c, v):
            continue
        dates.append(datetime.fromtimestamp(t, tz=ET).strftime("%Y-%m-%d"))
        O.append(o); H.append(h); L.append(l); C.append(c); V.append(v)
    if not dates:
        return None
    idx = {d: i for i, d in enumerate(dates)}
    # prefix sums for trailing-20d avg volume and dollar volume
    pv = [0.0]; pdv = [0.0]
    for c, v in zip(C, V):
        pv.append(pv[-1] + v); pdv.append(pdv[-1] + c * v)
    return {"meta": meta, "dates": dates, "O": O, "H": H, "L": L,
            "C": C, "V": V, "idx": idx, "pv": pv, "pdv": pdv}

def bar_on(S, day):
    i = S["idx"].get(day)
    if i is None:
        return None
    return (S["O"][i], S["H"][i], S["L"][i], S["C"][i], S["V"][i])

def last_close(S, day):
    j = bisect.bisect_right(S["dates"], day) - 1
    return S["C"][j] if j >= 0 else None

def trailing_avg(S, day, n, dollar=False):
    """Average over the n bars ending on `day` (inclusive). None if < n."""
    i = S["idx"].get(day)
    if i is None or i + 1 < n:
        return None
    arr = S["pdv"] if dollar else S["pv"]
    return (arr[i + 1] - arr[i + 1 - n]) / n

# ---------------------------------------------------------------- screens
def screen(symbols, day):
    passed = []
    for sym, S in symbols.items():
        b = bar_on(S, day)
        if b is None:
            continue
        adv = trailing_avg(S, day, 20, dollar=True)
        if adv is None:
            continue
        if (S["meta"].get("exchangeName") in LISTED
                and S["meta"].get("instrumentType") == "EQUITY"
                and b[3] < SCREEN_MAX_PRICE and adv > SCREEN_MIN_AVG_DV):
            passed.append(sym)
    return sorted(passed)

def rank(symbols, universe, day, held):
    ranked = []
    for s in universe:
        if s in held:
            continue
        S = symbols[s]
        i = S["idx"].get(day)
        if i is None or i == 0:
            continue
        prev_close = S["C"][i - 1]
        if prev_close <= 0:
            continue
        gain = (S["C"][i] / prev_close - 1) * 100
        av = trailing_avg(S, day, 20)
        spike = (S["V"][i] / av) if av else 0.0
        score = gain * spike
        if score > 0:
            ranked.append((score, s))
    ranked.sort(reverse=True)
    return [s for _, s in ranked]

# ---------------------------------------------------------------- cadence dates
def cadence_dates(tdays, cadence):
    inwin = [d for d in tdays if START <= d <= END]
    if cadence == "daily":
        return inwin
    out, seen = [], set()
    if cadence == "weekly":
        keyf = lambda d: datetime.strptime(d, "%Y-%m-%d").date().isocalendar()[:2]
    elif cadence == "biweekly":
        # group ISO weeks; anchor week index from the first in-window week
        first = datetime.strptime(inwin[0], "%Y-%m-%d").date()
        monday0 = first - timedelta(days=first.weekday())
        def keyf(d, _m=monday0):
            dt = datetime.strptime(d, "%Y-%m-%d").date()
            wk = ((dt - timedelta(days=dt.weekday())) - _m).days // 7
            return ("bi", wk // 2, wk % 2 == 0)
        out = []
        for d in inwin:
            k = keyf(d)
            if k[2] and k[:2] not in seen:
                seen.add(k[:2]); out.append(d)
        return out
    elif cadence == "monthly":
        keyf = lambda d: d[:7]
    elif cadence == "quarterly":
        keyf = lambda d: (d[:4], (int(d[5:7]) - 1) // 3)
    elif cadence == "semiannual":
        keyf = lambda d: (d[:4], 0 if int(d[5:7]) <= 6 else 1)
    elif cadence == "annual":
        keyf = lambda d: d[:4]
    for d in inwin:
        k = keyf(d)
        if k not in seen:
            seen.add(k); out.append(d)
    return out

# ---------------------------------------------------------------- simulation
def simulate(symbols, tdays, cdates, rng=None):
    """rng=None -> real (top-ranked); rng given -> placebo twin."""
    tix = {d: i for i, d in enumerate(tdays)}
    cash = START_CASH
    positions = {}            # sym -> {shares, entry, outlay}
    episode = 1
    ep_start_balance = START_CASH
    floor = 0.85 * ep_start_balance
    state = "active"          # active | sitout | done
    restart_on_or_after = None
    halts = []
    curve = []
    costs_spread = 0.0        # 2%/side proportional (spread/slippage model)
    costs_fees = 0.0          # $0.01 sell-order fees
    orders = 0
    entries_by_week = {}
    gap_through = 0
    pending_halt = None       # (trigger_date, trigger_close)

    def equity(day, field="C"):
        eq = cash
        for s, p in positions.items():
            S = symbols[s]
            i = S["idx"].get(day)
            if i is not None:
                eq += p["shares"] * getattr(S, field)[i] if False else p["shares"] * S[field][i]
            else:
                c = last_close(S, day)
                eq += p["shares"] * (c if c else p["entry"])
        return eq

    def do_sell(day, sym, price):
        nonlocal cash, costs_spread, costs_fees, orders
        p = positions.pop(sym)
        gross = p["shares"] * price
        costs_spread += gross * COST_RATE
        costs_fees += SELL_FEE
        orders += 1
        cash += gross * (1 - COST_RATE) - SELL_FEE

    def liquidate(day, at_open):
        for s in list(positions):
            S = symbols[s]
            b = bar_on(S, day)
            if b is not None:
                price = b[0] if at_open else b[3]
            else:
                price = last_close(S, day)
            if price:
                do_sell(day, s, price)

    def week_key(day):
        return datetime.strptime(day, "%Y-%m-%d").date().isocalendar()[:2]

    cset = set(cdates)
    for ti, day in enumerate(tdays):
        if day < START or day > END:
            continue
        # pending halt liquidation at today's open
        if pending_halt is not None:
            trig_date, trig_close = pending_halt
            liquidate(day, at_open=True)
            rec = {"episode": episode, "trigger_date": trig_date,
                   "trigger_close": round(trig_close, 2),
                   "floor": round(floor, 2), "liquidation_date": day,
                   "balance_after": round(cash, 2)}
            halts.append(rec)
            pending_halt = None
            if episode == 1:
                episode = 2
                state = "sitout"
                restart_on_or_after = (datetime.strptime(day, "%Y-%m-%d").date()
                                       + timedelta(days=90)).strftime("%Y-%m-%d")
            else:
                state = "done"
            curve.append([day, round(cash, 2)])
            if state == "done":
                # fill remaining curve flat
                for d2 in tdays[ti + 1:]:
                    if START <= d2 <= END:
                        curve.append([d2, round(cash, 2)])
                break
            continue

        if state == "sitout":
            if day in cset and day >= restart_on_or_after:
                state = "active"
                ep_start_balance = cash
                floor = 0.85 * ep_start_balance
                halts[-1]["restart_date"] = day
                halts[-1]["restart_balance"] = round(cash, 2)
            else:
                curve.append([day, round(cash, 2)])
                continue

        if state == "active" and day in cset:
            sig_i = ti - 1
            sig_day = tdays[sig_i] if sig_i >= 0 else None
            if sig_day is not None:
                universe = screen(symbols, sig_day)
                # ---- exits on cadence date (before entry, using today's bar;
                # a name entered today is not exit-checked until next cadence
                # date at slower cadences; at daily cadence the original
                # checked same-day -- exits here run before entry so a
                # same-day entry is first checked next cadence date: the
                # uniform cadence rule, stated)
                for s in list(positions):
                    b = bar_on(symbols[s], day)
                    if b is None:
                        continue
                    entry = positions[s]["entry"]
                    stop, tp = entry * (1 - STOP_FRAC), entry * (1 + TP_FRAC)
                    if b[2] <= stop:
                        if b[0] < stop:
                            gap_through += 1
                            do_sell(day, s, b[0])
                        else:
                            do_sell(day, s, stop)
                    elif b[1] >= tp:
                        do_sell(day, s, tp)
                # ---- entry
                ranked = rank(symbols, universe, sig_day, set(positions))
                pick = None
                if ranked:
                    pick = ranked[0] if rng is None else rng.choice(ranked)
                if pick is not None:
                    wk = week_key(day)
                    if (entries_by_week.get(wk, 0) < MAX_ENTRIES_PER_WEEK
                            and pick not in positions
                            and len(positions) < MAX_POSITIONS):
                        b = bar_on(symbols[pick], day)
                        if b is not None and b[0] > 0:
                            amount = min(MAX_PER_NAME_FRAC * equity(day, "O"), cash)
                            if amount >= 1.00 and not (GATE_COST_FRAC * amount > GATE_LIMIT_FRAC * amount):
                                shares = amount / (b[0] * (1 + COST_RATE))
                                costs_spread += amount - shares * b[0]
                                orders += 1
                                cash -= amount
                                positions[pick] = {"shares": shares,
                                                   "entry": b[0],
                                                   "outlay": amount}
                                entries_by_week[wk] = entries_by_week.get(wk, 0) + 1
        # end-of-run liquidation
        if day == END:
            liquidate(day, at_open=False)
            curve.append([day, round(cash, 2)])
            break
        eq_close = equity(day, "C") if positions else cash
        curve.append([day, round(eq_close, 2)])
        # v9 floor check on every close
        if state == "active" and eq_close <= floor:
            pending_halt = (day, eq_close)
    # if run ended mid-halt-pending (halt on final day handled above by
    # liquidation-at-close ordering) -- pending_halt on END day:
    final = cash
    peak, max_dd = START_CASH, 0.0
    for _, v in curve:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1)
    days = (datetime.strptime(END, "%Y-%m-%d") - datetime.strptime(START, "%Y-%m-%d")).days
    cagr = ((final / START_CASH) ** (365.25 / days) - 1) * 100 if final > 0 else -100.0
    return {"final": round(final, 2), "cagr_pct": round(cagr, 2),
            "max_dd_pct": round(max_dd * 100, 2),
            "costs": round(costs_spread + costs_fees, 2),
            "costs_spread": round(costs_spread, 2),
            "costs_fees": round(costs_fees, 2),
            "orders": orders, "halts": halts,
            "restart": any("restart_date" in h for h in halts),
            "second_halt": len(halts) >= 2,
            "gap_through_stops": gap_through,
            "equity_curve": curve}

# ---------------------------------------------------------------- main
def main():
    symbols = {}
    failed = []
    for sym in CANDIDATES:
        S = load_symbol(sym)
        if S is None:
            failed.append(sym)
        else:
            symbols[sym] = S
    spy = load_symbol("SPY")
    tdays = [d for d in spy["dates"] if "2016-01-01" <= d <= END]
    print(f"symbols loaded: {len(symbols)}; failed: {failed}")
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    summary = {}
    for cad in CADENCES:
        cd = cadence_dates(tdays, cad)
        res = simulate(symbols, tdays, cd)
        twins = []
        for seed in range(1, 21):
            t = simulate(symbols, tdays, cd, rng=random.Random(seed))
            twins.append(t["final"])
        beaten = sum(1 for f in twins if res["final"] > f)
        cell = dict(res)
        cell["cadence"] = cad
        cell["placebo_finals"] = twins
        cell["placebo_beaten"] = beaten
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f)
        summary[cad] = {"final": res["final"], "cagr_pct": res["cagr_pct"],
                        "max_dd_pct": res["max_dd_pct"], "costs": res["costs"],
                        "costs_spread": res["costs_spread"],
                        "orders": res["orders"], "halts": len(res["halts"]),
                        "restart": res["restart"],
                        "second_halt": res["second_halt"],
                        "placebo_beaten": beaten}
        print(cad, summary[cad], flush=True)
    with open(os.path.join(HERE, "sweep_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)

if __name__ == "__main__":
    main()
