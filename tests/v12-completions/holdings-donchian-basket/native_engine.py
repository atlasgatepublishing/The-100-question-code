#!/usr/bin/env python3
"""COPY of the v11 native Turtle engine (read-only original untouched), with
ONE change for the v12 holdings-count sweep: run() takes total_cap
(default 12 = the published cap) replacing the hard-coded 12-unit total
cap in can_add(). Nothing else differs. See SWEEP-SPEC.md.
Original header follows:
V11 NATIVE RUN — the Turtle Trading System (Dennis/Eckhardt 1983; rules
published by Curtis Faith, 'Way of the Turtle' 2007, and the original
Turtle rules document Faith released in 2003).

Frozen spec (see NATIVE-SPEC.md):
- N = 20-day Wilder-smoothed Average True Range.
- Unit size = (1% of effective equity) / N  (dollars-per-point = 1 for ETFs).
- System 1: enter on 20-day Donchian breakout (intraday trigger at the
  channel level), exit on 10-day opposite channel; SKIP the entry if the
  last System-1 breakout in that market/direction would have been a winner;
  55-day breakout is the failsafe entry when a System-1 entry was skipped.
- System 2: enter on 55-day breakout, always taken; exit on 20-day
  opposite channel.
- Stops: 2N from the most recent unit's entry, applied to the whole position.
- Pyramiding: add 1 unit per +1/2N favourable move, max 4 units per market.
- Caps (documented simplification of the Turtle correlation limits):
  4 units/market, 6 units in the closely-correlated equity group
  {SPY,QQQ,IWM}, 6 in {IEFA,EEM}, 12 units total.
- Loss rule (simplified, documented): effective equity for sizing is cut
  20% for each full 10% drawdown from peak equity (0.8^k).
- Long AND short, per the native system. No -15% program floor — the
  Turtle discipline is the 2N stop + unit caps, stated in the spec.
Costs: program standard 0.10% of notional per side + $0.01 per sell order.
Habitat: 9 ETFs (SPY QQQ IWM IEFA EEM GLD TLT VNQ DBC) as the tradable
proxy for the Turtles' futures markets — deviation documented in the spec.
Data (read-only): backtests/v3/tournament2-data/*.csv, full OHLC from
2015-01-02 (warm-up year before the first window).
"""
import csv, json, pathlib, random

DATA = pathlib.Path.home() / "workspace/stock-app/backtests/v3/tournament2-data"
SYMS = ["SPY", "QQQ", "IWM", "IEFA", "EEM", "GLD", "TLT", "VNQ", "DBC"]
GROUPS = [{"SPY", "QQQ", "IWM"}, {"IEFA", "EEM"}]
START = 100.0
COST = 0.001
SELL_FEE = 0.01

def load():
    out = {}
    for s in SYMS:
        rows = list(csv.DictReader(open(DATA / f"{s}.csv")))
        out[s] = {"d": [r["date"] for r in rows],
                  "o": [float(r["open"]) for r in rows],
                  "h": [float(r["high"]) for r in rows],
                  "l": [float(r["low"]) for r in rows],
                  "c": [float(r["close"]) for r in rows]}
    return out

B = load()
DATES = B["SPY"]["d"]
IDX = {d: i for i, d in enumerate(DATES)}
NDAYS = len(DATES)

def wilder_n(s):
    tr = [0.0] * NDAYS
    for i in range(1, NDAYS):
        h, l, pc = B[s]["h"][i], B[s]["l"][i], B[s]["c"][i - 1]
        tr[i] = max(h - l, abs(h - pc), abs(pc - l))
    n = [None] * NDAYS
    if NDAYS > 20:
        n[20] = sum(tr[1:21]) / 20.0
        for i in range(21, NDAYS):
            n[i] = (n[i - 1] * 19 + tr[i]) / 20.0
    return n

NVAL = {s: wilder_n(s) for s in SYMS}

def chan(s, i, days, kind):
    """Channel over the `days` sessions BEFORE day i (prior channel)."""
    if i < days:
        return None
    seg = (B[s]["h"] if kind == "h" else B[s]["l"])[i - days:i]
    return max(seg) if kind == "h" else min(seg)

class Pos:
    __slots__ = ("sym", "dir", "units", "shares", "last_entry", "system")
    def __init__(self, sym, dirn, shares, entry, system):
        self.sym, self.dir, self.units = sym, dirn, 1
        self.shares, self.last_entry, self.system = shares, entry, system

def run(window_start, window_end, system, placebo_seed=None, total_cap=12):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    s_i, e_i = IDX[window_start], IDX[window_end]
    cash = START
    positions = {}          # sym -> Pos
    costs = 0.0; orders = 0; entries = 0
    peak = START
    curve = []
    # System-1 shadow tracker: per (sym,dir): {"active":bool,"entry":..,"n":..} and last outcome
    shadow = {}
    last_s1_winner = {}
    # placebo: pre-generate random entry schedule matched later — instead use
    # per-day random probability calibrated on the fly (entries/day of real run
    # is unknown ahead); placebo mode uses fixed p per flat market-day.
    PLACEBO_P = 0.004

    def eff_equity(eq):
        dd = (peak - eq) / peak if peak > 0 else 0.0
        k = int(dd / 0.10)
        return eq * (0.8 ** k)

    def equity(i, price_key="c"):
        return cash + sum(p.shares * p.dir * B[p.sym][price_key][i] for p in positions.values())

    def total_units():
        return sum(p.units for p in positions.values())

    def group_units(g):
        return sum(p.units for s, p in positions.items() if s in g)

    def can_add(sym):
        if sym in positions and positions[sym].units >= 4:
            return False
        if total_units() >= total_cap:
            return False
        for g in GROUPS:
            if sym in g and group_units(g) >= 6:
                return False
        return True

    def buy(sym, shares, price):
        nonlocal cash, costs, orders
        fee = shares * price * COST
        cash -= shares * price + fee; costs += fee; orders += 1

    def sell(sym, shares, price):
        nonlocal cash, costs, orders
        fee = shares * price * COST + SELL_FEE
        cash += shares * price - fee; costs += fee; orders += 1

    def gross_notional(i):
        return sum(abs(p.shares * B[p.sym]["o"][i]) for p in positions.values())

    def cash_constrain(sym, unit_shares, i, price):
        """Cash-account habitat constraint (documented in NATIVE-SPEC.md):
        the Turtles traded futures on margin; a $100 cash pot cannot.
        Gross notional may not exceed current equity — a unit is scaled
        down to the room available, and skipped if the room is trivial."""
        eq_now = equity(i, "o")
        room = eq_now - gross_notional(i)
        if room <= 0:
            return 0.0
        if unit_shares * price > room:
            unit_shares = room / price
            if unit_shares * price < 0.25 * (0.01 * eq_now / NVAL[sym][i]) * price:
                return 0.0
        return unit_shares

    def open_pos(sym, dirn, i, price, sysname):
        nonlocal entries
        n = NVAL[sym][i]
        if not n or n <= 0 or not can_add(sym):
            return False
        eq = eff_equity(equity(i, "o"))
        unit_shares = (0.01 * eq) / n
        unit_shares = cash_constrain(sym, unit_shares, i, price)
        if unit_shares <= 0:
            return False
        if dirn > 0:
            buy(sym, unit_shares, price)
        else:
            sell(sym, unit_shares, price)
        positions[sym] = Pos(sym, dirn, unit_shares, price, sysname)
        entries += 1
        return True

    def close_pos(sym, i, price):
        p = positions.pop(sym)
        if p.dir > 0:
            sell(sym, p.shares, price)
        else:
            buy(sym, p.shares, price)

    for i in range(s_i, e_i + 1):
        # --- update shadows (System 1 hypothetical breakouts) ---
        if system == 1:
            for s in SYMS:
                n = NVAL[s][i]
                if not n:
                    continue
                hi20, lo20 = chan(s, i, 20, "h"), chan(s, i, 20, "l")
                hi10, lo10 = chan(s, i, 10, "h"), chan(s, i, 10, "l")
                for dirn, lvl, exlvl in ((1, hi20, lo10), (-1, lo20, hi10)):
                    key = (s, dirn)
                    sh = shadow.get(key)
                    if sh and sh["active"]:
                        stop = sh["entry"] - dirn * 2 * sh["n"]
                        hit_stop = (B[s]["l"][i] <= stop) if dirn > 0 else (B[s]["h"][i] >= stop)
                        hit_exit = (B[s]["l"][i] <= exlvl) if dirn > 0 else (B[s]["h"][i] >= exlvl)
                        if hit_stop:
                            last_s1_winner[key] = False; sh["active"] = False
                        elif hit_exit:
                            pnl_dir = (exlvl - sh["entry"]) * dirn
                            last_s1_winner[key] = pnl_dir > 0; sh["active"] = False
                    # arm a new shadow when no shadow is active and the breakout crosses
                    cur = shadow.get(key)
                    if (cur is None or not cur["active"]) and lvl is not None:
                        crossed = (B[s]["h"][i] >= lvl) if dirn > 0 else (B[s]["l"][i] <= lvl)
                        if crossed:
                            fill = max(B[s]["o"][i], lvl) if dirn > 0 else min(B[s]["o"][i], lvl)
                            shadow[key] = {"active": True, "entry": fill, "n": n}
        # --- manage open positions: stops, exits, adds ---
        for s in list(positions.keys()):
            p = positions[s]
            n = NVAL[s][i]
            if not n:
                continue
            stop = p.last_entry - p.dir * 2 * n
            if p.dir > 0 and B[s]["l"][i] <= stop:
                close_pos(s, i, min(B[s]["o"][i], stop)); continue
            if p.dir < 0 and B[s]["h"][i] >= stop:
                close_pos(s, i, max(B[s]["o"][i], stop)); continue
            ex_days = 10 if p.system == 1 else 20
            ex = chan(s, i, ex_days, "l" if p.dir > 0 else "h")
            if ex is not None:
                if p.dir > 0 and B[s]["l"][i] <= ex:
                    close_pos(s, i, min(B[s]["o"][i], ex)); continue
                if p.dir < 0 and B[s]["h"][i] >= ex:
                    close_pos(s, i, max(B[s]["o"][i], ex)); continue
            # pyramid add at +1/2N from last entry
            trig = p.last_entry + p.dir * 0.5 * n
            crossed = (B[s]["h"][i] >= trig) if p.dir > 0 else (B[s]["l"][i] <= trig)
            if crossed and can_add(s):
                eq = eff_equity(equity(i, "o"))
                unit_shares = (0.01 * eq) / n
                fill = max(B[s]["o"][i], trig) if p.dir > 0 else min(B[s]["o"][i], trig)
                unit_shares = cash_constrain(s, unit_shares, i, fill)
                if unit_shares <= 0:
                    continue
                if p.dir > 0:
                    buy(s, unit_shares, fill)
                else:
                    sell(s, unit_shares, fill)
                p.shares += unit_shares; p.units += 1; p.last_entry = fill
        # --- new entries ---
        ent_days = 20 if system == 1 else 55
        for s in SYMS:
            if s in positions:
                continue
            n = NVAL[s][i]
            if not n:
                continue
            lvl_h, lvl_l = chan(s, i, ent_days, "h"), chan(s, i, ent_days, "l")
            if lvl_h is None:
                continue
            if rng is not None:
                if rng.random() < PLACEBO_P:
                    dirn = rng.choice([1, -1])
                    price = B[s]["o"][i]
                    open_pos(s, dirn, i, price, system)
                continue
            for dirn, lvl in ((1, lvl_h), (-1, lvl_l)):
                crossed = (B[s]["h"][i] >= lvl) if dirn > 0 else (B[s]["l"][i] <= lvl)
                if not crossed:
                    continue
                if system == 1 and last_s1_winner.get((s, dirn)):
                    # skipped — but 55-day failsafe may force entry
                    fs_h, fs_l = chan(s, i, 55, "h"), chan(s, i, 55, "l")
                    fs = fs_h if dirn > 0 else fs_l
                    fs_cross = (B[s]["h"][i] >= fs) if dirn > 0 else (B[s]["l"][i] <= fs)
                    if not fs_cross:
                        continue
                    lvl = fs
                fill = max(B[s]["o"][i], lvl) if dirn > 0 else min(B[s]["o"][i], lvl)
                open_pos(s, dirn, i, fill, system)
                break
        eq_c = equity(i)
        peak = max(peak, eq_c)
        curve.append({"d": DATES[i], "eq": round(eq_c, 4)})
    final = curve[-1]["eq"] if curve else START
    pk, maxdd = START, 0.0
    for pt in curve:
        pk = max(pk, pt["eq"]); maxdd = max(maxdd, (pk - pt["eq"]) / pk if pk else 0)
    yearly = {}
    for pt in curve:
        yearly[pt["d"][:4]] = pt["eq"]
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "entries": entries,
            "open_positions_end": len(positions), "curve": curve, "year_end_equity": yearly}

WINDOWS = {"DECADE": ("2016-11-21", "2026-11-20"),
           "CONT": ("2019-01-02", "2026-11-20"),
           "VAL": ("2023-01-03", "2026-11-20")}

def main():
    out = {"strategy": "Turtle Trading System (Faith 2003/2007 published rules), ETF habitat",
           "markets": SYMS, "windows": {}}
    for name, (a, b) in WINDOWS.items():
        w = {}
        for system in (1, 2):
            r = run(a, b, system)
            twins = [run(a, b, system, placebo_seed=5500 + 31 * system + k)["final"] for k in range(20)]
            beaten = sum(1 for t in twins if r["final"] > t)
            w[f"system{system}"] = {**r, "placebo_beaten": f"{beaten}/20", "placebo_finals": twins}
            print(name, f"S{system}", "final", r["final"], "dd", r["max_dd_pct"], "costs", r["costs"],
                  "orders", r["orders"], "entries", r["entries"], "| placebo", beaten, "/20")
        out["windows"][name] = {"window": [a, b], **w}
    pathlib.Path(__file__).with_name("turtle_results.json").write_text(json.dumps(out, indent=1))
    print("saved turtle_results.json")

if __name__ == "__main__":
    main()
