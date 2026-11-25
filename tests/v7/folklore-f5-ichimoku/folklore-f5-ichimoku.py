#!/usr/bin/env python3
"""
FOLKLORE TEST F-5 — ICHIMOKU CLOUD (default 9/26/52 parameters) — Terry's AI
stock app. Simulation only.

Implements Spec F-5 from research/v7-completeness/folklore-audit.md VERBATIM.
The spec is frozen: no parameter was improved, re-cut, or reinterpreted.
Forced readings (data construction / state machine) are declared in the
report BEFORE results and summarized in the header notes of the results JSON.

Spec F-5 as written:
  - Universe/data: SPY daily OHLC. Tenkan-sen = (9-day high + 9-day low)/2;
    Kijun-sen = (26-day high + 26-day low)/2; Senkou Span A = (Tenkan+Kijun)/2
    plotted 26 days ahead; Senkou Span B = (52-day high + 52-day low)/2
    plotted 26 days ahead. Signals use only spans computable from data
    available on the day: the cloud compared against on day t is formed by
    the span values computed from data through day t-26.
  - Rule: hold SPY when the close is above the cloud AND Tenkan > Kijun.
    Exit to cash when the close falls below the cloud OR Tenkan < Kijun.
    Evaluate daily, execute next open.

House chassis (folklore audit, program-wide): $100 pot, long-only; execution
at the next session's open after a signal computed on closes; costs 0.10% of
trade value per side + $0.01 per sell order; plain -15% floor at pot level
(close at/below $85 -> liquidate at next open, run ends — champion engine
semantics); windows continuous 2019-01-01->2026-11-20 and validation
2023-01-01->2026-11-20 (first trading days 2019-01-02 / 2023-01-03, the
champion engine's own window dates); benchmarks SPY buy-hold net of the same
costs (the champion engine's spy_net, imported and run on the engine's own
PriceBook) and a 20-seed random placebo (see report for construction);
promotion bar: beat SPY AND the placebo median on validation.

Prices: the program's shared cache ~/workspace/stock-app/backtests/v4/data/
px_SPY.json (Yahoo chart payload), read-only. Adjusted OHLC use the champion
engine's own ratio method (adjclose/close) — the engine stores adjusted open
and close; highs/lows, which the engine does not store, are adjusted by the
identical ratio. Integrity: this script asserts its adjusted opens/closes
equal the champion engine's bars for every date, and that the engine's
spy_net reproduces the published $313.62 / $187.77 to the cent before any
variant number is taken.
"""
import importlib.util
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
CACHE = os.path.join(V4, "data", "px_SPY.json")

START_CASH = 100.0
FLOOR0 = 85.0
WINDOWS = (("FULL", "2019-01-01", "2026-11-20"),
           ("VALIDATION", "2023-01-01", "2026-11-20"))
PLACEBO_SEEDS = list(range(1, 21))
CHAMPION = {"FULL": 544.47, "VALIDATION": 288.05}
SPY_PUBLISHED = {"FULL": 313.62, "VALIDATION": 187.77}

# ------------------------------------------------------------ champion engine
spec = importlib.util.spec_from_file_location(
    "champion", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)


def load_spy_ohlc():
    """Adjusted OHLC from the shared Yahoo payload, champion ratio method."""
    with open(CACHE, "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    import time
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if c is None or o is None or h is None or l is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": o * ratio, "h": h * ratio,
                     "l": l * ratio, "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


# ----------------------------------------------------------------- ichimoku
def ichimoku(bars):
    """Return per-index dict with tenkan, kijun, cloud_top, cloud_bot
    (None where not yet computable). Cloud on day t uses span values
    computed from data through day t-26 (the displaced construction)."""
    H = [b["h"] for b in bars]
    L = [b["l"] for b in bars]
    n = len(bars)

    def mid(i, k):
        if i < k - 1:
            return None
        return (max(H[i - k + 1:i + 1]) + min(L[i - k + 1:i + 1])) / 2.0

    tenkan = [mid(i, 9) for i in range(n)]
    kijun = [mid(i, 26) for i in range(n)]
    span_a_at = [((tenkan[i] + kijun[i]) / 2.0)
                 if tenkan[i] is not None and kijun[i] is not None else None
                 for i in range(n)]
    span_b_at = [mid(i, 52) for i in range(n)]
    out = []
    for t in range(n):
        src = t - 26
        a = span_a_at[src] if src >= 0 else None
        b = span_b_at[src] if src >= 0 else None
        if a is None or b is None:
            top = bot = None
        else:
            top, bot = max(a, b), min(a, b)
        out.append({"tenkan": tenkan[t], "kijun": kijun[t],
                    "cloud_top": top, "cloud_bot": bot})
    return out


def entry_ok(bars, ich, i):
    x = ich[i]
    if x["cloud_top"] is None or x["tenkan"] is None or x["kijun"] is None:
        return False
    return bars[i]["c"] > x["cloud_top"] and x["tenkan"] > x["kijun"]


def exit_ok(bars, ich, i):
    x = ich[i]
    if x["cloud_bot"] is None or x["tenkan"] is None or x["kijun"] is None:
        return False
    return bars[i]["c"] < x["cloud_bot"] or x["tenkan"] < x["kijun"]


def always_on_state(bars, ich, upto_idx):
    """State (True=long) of the F-5 state machine run from the first valid
    signal day through upto_idx — used only to document whether the flat
    window start coincides with the always-on reading."""
    state = False
    for i in range(len(bars)):
        if i > upto_idx:
            break
        if ich[i]["cloud_top"] is None:
            continue
        if not state and entry_ok(bars, ich, i):
            state = True
        elif state and exit_ok(bars, ich, i):
            state = False
    return state


# ------------------------------------------------------------------- engine
def run_timer(bars, start, end, mode, ich=None, toggles=None, label=""):
    """One $100 pot. mode='strategy' uses the F-5 conditions; mode='placebo'
    toggles the desired state on the given global bar indices (signal days).
    Mechanics mirror the champion engine: pending signal executes at the
    next open; buy cost 0.10% of value; sell cost 0.10% + $0.01; floor check
    on the close, halt liquidation at the next open; end-of-window
    liquidation at the final close."""
    days = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    cash = START_CASH
    shares = 0.0
    pending = None            # 'BUY' or 'SELL', executes at next day's open
    desired_long = False      # placebo state machine
    trades = []
    total_costs = 0.0
    curve = []
    halted = None
    halt_info = None
    end_date = bars[days[-1]]["d"]
    switches = 0              # executed BUY/SELL trades (excl. END/HALT)

    for k, i in enumerate(days):
        d = bars[i]["d"]
        # execute pending at today's open
        if pending == "BUY" and shares == 0.0:
            buy_val = cash / 1.001
            sh = buy_val / bars[i]["o"]
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            shares = sh
            trades.append((d, "BUY", sh, bars[i]["o"], buy_val, c))
            switches += 1
        elif pending == "SELL" and shares > 0.0:
            val = shares * bars[i]["o"]
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((d, "SELL", shares, bars[i]["o"], val, c))
            shares = 0.0
            switches += 1
        pending = None
        # signal on today's close
        if mode == "strategy":
            if shares == 0.0 and entry_ok(bars, ich, i):
                pending = "BUY"
            elif shares > 0.0 and exit_ok(bars, ich, i):
                pending = "SELL"
        else:  # placebo
            if i in toggles:
                desired_long = not desired_long
                if desired_long and shares == 0.0:
                    pending = "BUY"
                elif not desired_long and shares > 0.0:
                    pending = "SELL"
        # close equity + floor check (champion semantics)
        v = cash + shares * bars[i]["c"]
        curve.append((d, v))
        if v <= FLOOR0 and k < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            if shares > 0.0:
                nd = bars[days[k + 1]]
                val = shares * nd["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nd["d"], "SELL-HALT", shares, nd["o"], val, c))
                shares = 0.0
                end_date = nd["d"]
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": end_date,
                    "halt_info": halt_info, "curve": curve,
                    "switches": switches}
    # end of window: liquidate at final close
    if shares > 0.0:
        last = bars[days[-1]]
        val = shares * last["c"]
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((last["d"], "SELL-END", shares, last["c"], val, c))
        shares = 0.0
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": end_date,
            "halt_info": None, "curve": curve, "switches": switches}


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
            "costs": round(r["costs"], 2),
            "n_trades": len(r["trades"]),
            "n_buys": sum(1 for t in r["trades"] if t[1] == "BUY"),
            "n_sells": sum(1 for t in r["trades"] if t[1].startswith("SELL")),
            "switches": r["switches"],
            "halted": r["halted"], "halt_info": r["halt_info"],
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "year_end_closes": year_end,
            "trades": [(t[0], t[1], round(t[3], 4), round(t[4], 2),
                        round(t[5], 2)) for t in r["trades"]]}


def time_in_market(bars, r, start, end):
    """Fraction of window days (through the run's end) holding shares at the
    close, reconstructed from the trade list."""
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    if r["halted"]:
        days = [d for d in days if d <= r["end"]]
    held = set()
    cur = False
    ti = 0
    tr = {t[0]: t[1] for t in r["trades"]}
    # trades execute at the open of their date: holding from that date's close
    events = [(t[0], t[1]) for t in r["trades"]]
    ei = 0
    for d in days:
        while ei < len(events) and events[ei][0] <= d:
            cur = events[ei][1] == "BUY"
            ei += 1
        if cur:
            held.add(d)
    return round(100.0 * len(held) / len(days), 1) if days else 0.0


def placebo_block(bars, start, end, n_switches, ranked_final, tag):
    days_idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    candidates = days_idx[:-1]           # a signal needs a next open
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        toggles = set(rng.sample(candidates, min(n_switches, len(candidates))))
        pr = run_timer(bars, start, end, "placebo", toggles=toggles,
                       label=f"{tag} PLACEBO {seed}")
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "switches": pr["switches"],
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


def main():
    bars = load_spy_ohlc()
    ich = ichimoku(bars)
    out = {"strategy": "FOLKLORE F-5 ICHIMOKU (default 9/26/52), SPY only, "
                       "$100, plain -15% floor",
           "spec_source": "research/v7-completeness/folklore-audit.md, Spec F-5",
           "pot": START_CASH, "floor": FLOOR0}

    # ---- integrity: adjusted O/C must equal the champion engine's bars,
    # and the engine's spy_net must reproduce the published SPY figures.
    eng_bars = E.get_prices("SPY")
    mine = {b["d"]: b for b in bars}
    mism = 0
    for eb in eng_bars:
        mb = mine.get(eb["d"])
        if mb is None or abs(mb["o"] - eb["o"]) > 1e-9 or \
                abs(mb["c"] - eb["c"]) > 1e-9:
            mism += 1
    out["integrity_bars_match"] = {"engine_bars": len(eng_bars),
                                   "mismatches": mism}
    print(f"BAR INTEGRITY: engine bars={len(eng_bars)} mismatches={mism}",
          flush=True)
    if mism:
        raise SystemExit("BAR MISMATCH — variant numbers untrusted")
    pb = E.PriceBook({"SPY": eng_bars})
    out["integrity_spy"] = {}
    for tag, ws, we in WINDOWS:
        spy, spy_costs = E.spy_net(pb, ws, we, START_CASH)
        ok = abs(spy - SPY_PUBLISHED[tag]) < 0.005
        out["integrity_spy"][tag] = {"spy_net": round(spy, 2),
                                     "published": SPY_PUBLISHED[tag],
                                     "match": ok}
        print(f"SPY INTEGRITY {tag}: ${spy:,.2f} vs published "
              f"${SPY_PUBLISHED[tag]:,.2f} match={ok}", flush=True)
        if not ok:
            raise SystemExit("SPY RECONCILIATION FAILED")

    # ---- always-on state at each window start (forced-reading evidence)
    out["always_on_state_at_start"] = {}
    for tag, ws, we in WINDOWS:
        first_idx = next(i for i, b in enumerate(bars) if b["d"] >= ws)
        st = always_on_state(bars, ich, first_idx - 1)
        out["always_on_state_at_start"][tag] = {
            "window_first_day": bars[first_idx]["d"],
            "always_on_state_entering": "LONG" if st else "FLAT",
            "pot_starts": "FLAT (champion chassis)"}
        print(f"{tag}: always-on state entering {bars[first_idx]['d']} = "
              f"{'LONG' if st else 'FLAT'}", flush=True)

    # ---- ranked runs + placebo
    for tag, ws, we in WINDOWS:
        spy, spy_costs = E.spy_net(pb, ws, we, START_CASH)
        r = run_timer(bars, ws, we, "strategy", ich=ich, label=f"{tag} F-5")
        st = curve_stats(r)
        st.update({"start": ws, "end": we,
                   "spy_net_final": round(spy, 2),
                   "spy_costs": round(spy_costs, 2),
                   "spy_return_pct": round(spy / START_CASH * 100 - 100, 2),
                   "champion_final": CHAMPION[tag],
                   "time_in_market_pct": time_in_market(bars, r, ws, we)})
        print(f"{tag} F-5 ICHIMOKU: final=${r['final']:,.2f} "
              f"({st['return_pct']:+.2f}%) trades={st['n_trades']} "
              f"switches={st['switches']} costs=${st['costs']} "
              f"maxDD={st['max_drawdown_pct']}% halted={r['halted']} "
              f"in-market={st['time_in_market_pct']}% | SPY=${spy:,.2f}",
              flush=True)
        st["placebo"] = placebo_block(bars, ws, we, r["switches"],
                                      r["final"], tag)
        pl = st["placebo"]
        print(f"{tag} PLACEBO: median=${pl['median']:,.2f} "
              f"best=${pl['best']:,.2f} worst=${pl['worst']:,.2f} "
              f"halted={pl['halted_count']}/20 | RANKED "
              f"${pl['ranked_final']:,.2f} = {pl['ranked_percentile']}th "
              f"pctile (beat {pl['seeds_beaten']}/20)", flush=True)
        out[tag.lower()] = st

    val = out["validation"]
    out["promotion_bar"] = {
        "beat_spy_validation": val["final"] > val["spy_net_final"],
        "beat_placebo_median_validation":
            val["final"] > val["placebo"]["median"],
        "promoted": val["final"] > val["spy_net_final"] and
                    val["final"] > val["placebo"]["median"]}

    with open(os.path.join(HERE, "folklore-f5-ichimoku-results.json"),
              "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
