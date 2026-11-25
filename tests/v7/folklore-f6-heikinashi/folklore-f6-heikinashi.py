#!/usr/bin/env python3
"""
FOLKLORE TEST F-6 — HEIKIN-ASHI COLOR TURNS — Terry's AI stock app.
Simulation only. No broker orders were placed.

THE SPEC IS FROZEN (research/v7-completeness/folklore-audit.md, Spec F-6).
Implemented verbatim; no parameter added, removed, or adjusted:

  Universe/data: SPY daily OHLC.
  Heikin-Ashi recursion: HA-Close = (O+H+L+C)/4;
    HA-Open = (prior HA-Open + prior HA-Close)/2, seeded with (O+C)/2 of
    the first bar; HA-High/HA-Low = max/min of H, HA-Open, HA-Close
    (and L likewise) — defined by the spec but not used by the color rule.
  Rule: a candle is GREEN if HA-Close > HA-Open, RED otherwise.
    Enter SPY at the next open after the first green candle following at
    least one red candle. Exit at the next open after the first red
    candle following entry. No additional filters.

House chassis (folklore audit, standing program yardsticks): $100 pot,
long-only, execution at the next session's open after a signal computed
on closes, costs 0.10% of trade value per side + $0.01 per sell order,
plain -15% floor at the pot level (a close at or below $85 liquidates
everything at the next open and ends the run, exactly as in the champion
engine), judging windows continuous 2019-01-01 -> 2026-11-20 and
validation 2023-01-01 -> 2026-11-20, benchmarks SPY buy-hold net of the
same costs and the 20-seed random placebo distribution. Promotion bar:
beat SPY AND the placebo median on validation.

FORCED READINGS (stated here, before any result — the spec leaves these
points to the implementer; each is resolved by the champion engine's own
convention, never by what would flatter the result):
  R1 PRICE BASIS. The recursion runs on the program's adjusted OHLC:
     raw Yahoo O/H/L/C each multiplied by the bar's adjclose/close
     ratio, close := adjclose. That is exactly the adjustment the
     champion engine's get_prices applies (its bars carry adjusted open
     and adjusted close); H and L are extended by the same ratio so the
     four prices stay one consistent series. The script verifies its
     adjusted open/close equal the champion engine's bar series to the
     cent for every bar before any strategy number is taken.
  R2 SEEDING / WARM-UP. The recursion is seeded once, at the first
     cached bar (2017-06-01), per the spec's seed rule, and runs over
     the full cache before either window opens (~19 months of warm-up
     precede the continuous window). It is NOT re-seeded at a window
     start.
  R3 WINDOW START. The pot starts flat in cash at each window's open.
     Signals are taken only from candles whose day falls inside the
     window (the champion engine's day-loop convention): if SPY is
     already mid-green-run at a window's first day, the pot waits for
     the next red->green turn inside the window. Candle COLORS still
     use the full pre-window recursion (R2).
  R4 EXIT SCAN. The exit scan begins with the entry execution day's own
     candle: a red candle on the day an entry executes is "the first
     red candle following entry" and exits at the next open.
  R5 PLACEBO. Per window, the placebo preserves the ranked run's
     realized trade count and holding durations (in event-index days:
     entry open to exit open, or to the final close for a position
     liquidated at the window's end), shuffles their order, and
     re-places them as non-overlapping blocks at random positions
     (free days distributed across the gaps by multinomial assignment),
     seeds 1..20 (the program's PLACEBO_SEEDS). Identical costs, floor,
     and execution; a placebo that breaches the floor halts identically.
     Only the TIMING of the in/out switches is randomized — that is the
     one thing the HA signal claims to know.

Data: the champion engine's cached SPY payload, read-only
(backtests/v4/data/px_SPY.json, the same file the champion's SHARED
cache reads). Integrity gate: the champion's own spy_net, imported
verbatim, must reproduce the published SPY nets ($313.62 continuous,
$187.77 validation) to the cent before any variant number is trusted.
"""
import importlib.util
import json
import math
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
CHAMP_PATH = os.path.join(V4, "value-momentum-plainfloor.py")
SPY_CACHE = os.path.join(V4, "data", "px_SPY.json")

START_CASH = 100.0
FLOOR0 = 85.0
PLACEBO_SEEDS = list(range(1, 21))  # twenty seeds: 1..20 (house standard)
WINDOWS = (("FULL", "2019-01-01", "2026-11-20", 313.62),
           ("VALIDATION", "2023-01-01", "2026-11-20", 187.77))


# ------------------------------------------------------------------ data
def load_champion():
    spec = importlib.util.spec_from_file_location("champ", CHAMP_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_spy_adjusted_ohlc():
    """Adjusted OHLC from the champion's cached SPY payload, using the
    champion engine's own adjustment (ratio = adjclose/close applied to
    the raw prices; close := adjclose). Mirrors get_prices' handling:
    bars with no close are skipped; a missing open falls back to the
    adjusted close (same convention extended to high/low)."""
    with open(SPY_CACHE, "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    fallbacks = 0
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0

        def adj_px(x):
            nonlocal fallbacks
            if x:
                return x * ratio
            fallbacks += 1
            return a

        bars.append({"d": d, "o": adj_px(o), "h": adj_px(h),
                     "l": adj_px(l), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars, fallbacks


def heikin_ashi_colors(bars):
    """The frozen recursion. Green iff HA-Close > HA-Open, else red."""
    colors = []
    ha_o = ha_c = None
    for i, b in enumerate(bars):
        ha_c = (b["o"] + b["h"] + b["l"] + b["c"]) / 4.0
        ha_o = (b["o"] + b["c"]) / 2.0 if i == 0 else (ha_o + ha_c) / 2.0
        colors.append("G" if ha_c > ha_o else "R")
    return colors


# ---------------------------------------------------------------- engine
def run_window(bars, day_idx, colors=None, schedule=None):
    """One pot over one window. Exactly one of colors (ranked HA signals)
    or schedule (placebo: dict window-pos -> list of 'BUY'/'SELL' actions
    to execute at that day's open, SELL before BUY) must be given.
    Accounting — all-in buys (buy_val = cash/1.001, cost 0.10%), sells
    (cost 0.10% + $0.01), floor on closes with next-open liquidation,
    end-of-window liquidation at the final close — is the champion
    engine's, shared by both signal sources."""
    cash = START_CASH
    shares = 0.0
    total_costs = 0.0
    trades = []          # dicts with window positions for block extraction
    curve = []
    halted = None
    halt_info = None
    pending = None       # ranked mode: action signalled today, executes tomorrow
    open_entry = None    # (pos, total_debit) of the current position
    n = len(day_idx)

    def do_buy(pos, gi):
        nonlocal cash, shares, total_costs, open_entry
        o = bars[gi]["o"]
        buy_val = cash / 1.001
        c = buy_val * 0.001
        shares = buy_val / o
        cash -= buy_val + c
        total_costs += c
        open_entry = (pos, buy_val + c)
        trades.append({"pos": pos, "date": bars[gi]["d"], "side": "BUY",
                       "price": o, "value": buy_val, "cost": c})

    def do_sell(pos, gi, kind, price):
        nonlocal cash, shares, total_costs, open_entry
        val = shares * price
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        pnl = (val - c) - open_entry[1] if open_entry else None
        trades.append({"pos": pos, "date": bars[gi]["d"], "side": kind,
                       "price": price, "value": val, "cost": c,
                       "roundtrip_pnl": pnl})
        shares = 0.0
        open_entry = None

    for pos, gi in enumerate(day_idx):
        # (1) execute at today's open
        if schedule is not None:
            for act in schedule.get(pos, []):
                if act == "SELL" and shares > 0:
                    do_sell(pos, gi, "SELL", bars[gi]["o"])
                elif act == "BUY" and shares == 0:
                    do_buy(pos, gi)
        elif pending is not None:
            if pending == "BUY" and shares == 0:
                do_buy(pos, gi)
            elif pending == "SELL" and shares > 0:
                do_sell(pos, gi, "SELL", bars[gi]["o"])
            pending = None
        # (2) ranked signal on today's candle (close)
        if schedule is None:
            if shares == 0 and pending is None:
                if colors[gi] == "G" and colors[gi - 1] == "R":
                    pending = "BUY"
            elif shares > 0 and pending is None:
                if colors[gi] == "R":
                    pending = "SELL"
        # (3) mark to close; floor check (champion convention)
        v = cash + shares * bars[gi]["c"]
        curve.append((bars[gi]["d"], v))
        if v <= FLOOR0 and pos < n - 1:
            halted = bars[gi]["d"]
            halt_info = {"signal_date": halted, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            ngi = day_idx[pos + 1]
            if shares > 0:
                do_sell(pos + 1, ngi, "SELL-HALT", bars[ngi]["o"])
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "halt_info": halt_info, "curve": curve}
    # end of window: liquidate at the final close (champion convention)
    if shares > 0:
        gi = day_idx[-1]
        do_sell(n - 1, gi, "SELL-END", bars[gi]["c"])
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "halt_info": None, "curve": curve}


def curve_stats(r, n_days):
    curve = r["curve"]
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    worst, worst_d = None, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
        if worst is None or v < worst:
            worst, worst_d = v, d
    buys = [t for t in r["trades"] if t["side"] == "BUY"]
    exits = [t for t in r["trades"] if t["side"] != "BUY"]
    wins = sum(1 for t in exits if t["roundtrip_pnl"] is not None
               and t["roundtrip_pnl"] > 0)
    return {"final": round(r["final"], 2),
            "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
            "round_trips": len(buys), "orders": len(r["trades"]),
            "win_rate_pct": (round(100.0 * wins / len(exits), 1)
                             if exits else None),
            "costs": round(r["costs"], 2), "halted": r["halted"],
            "halt_info": r["halt_info"],
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": round(worst, 2) if worst is not None else None,
            "worst_close_date": worst_d}


def extract_blocks(r, n_days):
    """Realized blocks of the ranked run in event-index space:
    (entry_pos, exit_event) where exit_event is the window position of
    the exit open, or n_days (virtual) for a final-close liquidation."""
    blocks = []
    entry = None
    for t in r["trades"]:
        if t["side"] == "BUY":
            entry = t["pos"]
        elif entry is not None:
            ev = n_days if t["side"] == "SELL-END" else t["pos"]
            blocks.append((entry, ev))
            entry = None
    return blocks


def placebo_schedule(blocks, n_days, rng):
    """Re-place the ranked run's holding durations at random
    non-overlapping positions (reading R5). Returns a schedule dict."""
    durations = [ev - en for en, ev in blocks]
    rng.shuffle(durations)
    k = len(durations)
    free = n_days - sum(durations)
    gaps = [0] * (k + 1)
    for _ in range(max(free, 0)):
        gaps[rng.randrange(k + 1)] += 1
    schedule = {}
    s = gaps[0]
    for i, d in enumerate(durations):
        schedule.setdefault(s, []).append("BUY")
        e = s + d
        if e <= n_days - 1:
            # a SELL at the same open as the next BUY executes first
            # (run_window processes the list in SELL-then-BUY order as
            # appended below: sells were appended before later buys only
            # if placed earlier — enforce by sorting at build end)
            schedule.setdefault(e, []).append("SELL")
        s = e + gaps[i + 1]
    for pos in schedule:
        schedule[pos].sort(key=lambda a: 0 if a == "SELL" else 1)
    return schedule


def placebo_block(bars, day_idx, blocks, ranked_final, tag):
    n_days = len(day_idx)
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        sched = placebo_schedule(blocks, n_days, rng)
        pr = run_window(bars, day_idx, schedule=sched)
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2)})
        print(f"  {tag} PLACEBO seed {seed:2d}: final=${pr['final']:,.2f} "
              f"halted={pr['halted']}", flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    pctile = 100.0 * (below + 0.5 * ties) / len(finals)

    def _pct(vals, q):
        if len(vals) == 1:
            return vals[0]
        pos = q * (len(vals) - 1)
        lo, hi = int(math.floor(pos)), int(math.ceil(pos))
        if lo == hi:
            return vals[lo]
        frac = pos - lo
        return vals[lo] * (1 - frac) + vals[hi] * frac

    return {"median": round(_pct(srt, 0.50), 2),
            "q1": round(_pct(srt, 0.25), 2),
            "q3": round(_pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for p in rows if p["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_percentile": round(pctile, 1),
            "seeds_beaten": below, "rows": rows}


# ------------------------------------------------------------------- main
def main():
    champ = load_champion()
    bars, fallbacks = load_spy_adjusted_ohlc()

    # ---- integrity gate 1: my adjusted series IS the champion's series
    eng_bars = champ.get_prices("SPY")
    assert len(eng_bars) == len(bars), (len(eng_bars), len(bars))
    max_oc_diff = 0.0
    for eb, mb in zip(eng_bars, bars):
        assert eb["d"] == mb["d"]
        max_oc_diff = max(max_oc_diff, abs(eb["o"] - mb["o"]),
                          abs(eb["c"] - mb["c"]))
    print(f"SERIES CHECK: {len(bars)} SPY bars {bars[0]['d']}..{bars[-1]['d']}; "
          f"max |adjusted open/close - champion engine| = {max_oc_diff:.2e}; "
          f"OHLC fallback bars used: {fallbacks}", flush=True)
    assert max_oc_diff < 1e-9

    # ---- integrity gate 2: champion spy_net reproduces published nets
    pb = champ.PriceBook({"SPY": eng_bars})
    for tag, ws, we, expect in WINDOWS:
        spy, _ = champ.spy_net(pb, ws, we, START_CASH)
        ok = abs(spy - expect) < 0.005
        print(f"REPLICATION {tag}: SPY net=${spy:,.2f} expected=${expect:,.2f} "
              f"match={ok}", flush=True)
        assert ok, "SPY replication failed — variant numbers untrusted"

    colors = heikin_ashi_colors(bars)
    out = {"strategy": "FOLKLORE F-6 HEIKIN-ASHI COLOR TURNS: SPY only, "
                       "enter next open after first green HA candle "
                       "following >=1 red; exit next open after first red "
                       "HA candle following entry; $100, plain -15% floor",
           "pot": START_CASH, "floor": FLOOR0,
           "data_bars": len(bars), "data_range": [bars[0]["d"], bars[-1]["d"]]}

    for tag, ws, we, expect_spy in WINDOWS:
        day_idx = [i for i, b in enumerate(bars) if ws <= b["d"] <= we]
        spy, spy_costs = champ.spy_net(pb, ws, we, START_CASH)
        r = run_window(bars, day_idx, colors=colors)
        st = curve_stats(r, len(day_idx))
        blocks = extract_blocks(r, len(day_idx))
        st["exposure_pct"] = round(
            100.0 * sum(ev - en for en, ev in blocks) / len(day_idx), 1)
        st.update({"start": bars[day_idx[0]]["d"],
                   "end": bars[day_idx[-1]]["d"],
                   "trading_days": len(day_idx),
                   "spy_net_final": round(spy, 2),
                   "spy_return_pct": round(spy / START_CASH * 100 - 100, 2),
                   "trades": [{k: (round(v, 4) if isinstance(v, float) else v)
                               for k, v in t.items()} for t in r["trades"]]})
        print(f"{tag} HEIKIN-ASHI: final=${r['final']:,.2f} "
              f"({st['return_pct']:+.2f}%) round_trips={st['round_trips']} "
              f"win_rate={st['win_rate_pct']}% exposure={st['exposure_pct']}% "
              f"maxDD={st['max_drawdown_pct']}% costs=${st['costs']} "
              f"halted={r['halted']} | SPY=${spy:,.2f}", flush=True)
        print(f"   blocks (entry_pos, exit_event): {blocks}", flush=True)
        st["placebo"] = placebo_block(bars, day_idx, blocks, r["final"], tag)
        pl = st["placebo"]
        print(f"{tag} PLACEBO: median=${pl['median']:,.2f} "
              f"best=${pl['best']:,.2f} worst=${pl['worst']:,.2f} "
              f"halted={pl['halted_count']}/20 | RANKED ${pl['ranked_final']:,.2f} "
              f"= {pl['ranked_percentile']}th pctile "
              f"(beat {pl['seeds_beaten']}/20)", flush=True)
        out[tag.lower()] = st

    with open(os.path.join(HERE, "folklore-f6-heikinashi-results.json"),
              "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
