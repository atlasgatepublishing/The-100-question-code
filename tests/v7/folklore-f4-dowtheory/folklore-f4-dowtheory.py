#!/usr/bin/env python3
"""
FOLKLORE TEST F-4 — DOW THEORY CONFIRMATION (reduced mechanical core).
Terry's AI stock app. Simulation only.

THE SPEC (frozen in research/v7-completeness/folklore-audit.md, Spec F-4,
implemented verbatim — no parameter adjusted, nothing reinterpreted):

  DECLARED REDUCTION: this test grades the confirmation tenet only — the
  one Dow Theory claim that can be stated without interpretation. "Lines,"
  volume confirmation, and secondary-reaction sizing are excluded as
  untestable-by-ambiguity. A verdict here grades the mechanical core,
  NOT Hamilton's interpreted practice and not the whole theory.

  Universe/data: DIA (Industrials) and IYT (Transports) daily closes;
  the traded asset is SPY (the theory times the market, and SPY is the
  program's market instrument).

  Rule: a BULLISH CONFIRMATION occurs when both DIA and IYT have printed
  a new 52-week closing high within the same rolling 20-session window
  -> hold SPY from the next open. A BEARISH CONFIRMATION occurs when
  both have printed a new 52-week closing low within the same rolling
  20-session window -> move to cash at the next open. Between
  confirmations, keep the current position. Start flat; the first
  confirmation decides the first position.

  Mechanical readings fixed by the audit chassis (stated, not tuned):
  - "New 52-week closing high" = a close strictly above every close of
    the prior 252 sessions; "low" symmetric. Flags are computed on the
    full fetched history (2015 onward) so the lookback is fully warmed
    before the 2019 window opens.
  - A confirmation EVENT is the session on which the pair completes:
    one index prints today and the other has printed within the prior
    19 sessions (both prints inside a 20-session window ending today).
  - Confirmation events are counted only on sessions inside the judging
    window; the pot starts flat in cash at each window's open regardless
    of any confirmation printed before the window (the spec's "start
    flat; the first confirmation decides the first position").
  - If a bullish and a bearish completion ever landed on the same
    session, the bearish one would govern (risk-off precedence); the
    run logs whether this ever happens. (It is near-impossible: it would
    need both indices at 52-week highs and 52-week lows within 20
    sessions of each other.)

Program chassis (audit standard, identical to the champion engines):
  - $100 pot, fractional shares, long only.
  - Prices: Yahoo Finance chart API, dividend+split adjusted (adjclose;
    opens scaled by adjclose/close) — total-return basis, same method as
    value-momentum-plainfloor.py / leveraged-trend.py.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Protection: plain -15% floor ($85 on the $100 pot), checked on the
    daily close; close at/below floor -> liquidate at next open, run ends.
  - Execution: signals computed on closes -> execute at the next open.
  - End of window: liquidate at the final close (program convention).
  - Cash earns 0%.

Windows:
  CONTINUOUS  2019-01-01 -> 2026-11-20   (champion reference $544.47,
                                           SPY buy-hold reference $313.62)
  VALIDATION  2023-01-01 -> 2026-11-20   (champion reference $288.05,
                                           SPY buy-hold reference $187.77)

Benchmarks/controls:
  - SPY BUY-HOLD as a program pot (same costs, same plain floor),
    bought at the window's first open.
  - 20-SEED RANDOM PLACEBO (audit chassis): each seed takes the
    strategy's own invested spells in that window — same number of
    spells, same spell lengths, same total days invested — and places
    them at random (cash gaps re-drawn; internal gaps >= 1 session so
    spells stay separate). Only the PLACEMENT is randomized. Placebo
    pots run through the identical engine, floor included.
  - NO-FLOOR diagnostic finals for the strategy, so the report can say
    what the floor did or did not do.

Promotion bar (program standing bar): beat SPY buy-hold AND the placebo
median on validation.
"""
import json, os, random, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data")
os.makedirs(CACHE, exist_ok=True)

COST_RATE = 0.0010          # 0.10% per side
SELL_FEE = 0.01             # $0.01 per sell order
START_CASH = 100.0
FLOOR = 85.0                # plain -15% floor on the $100 pot
LOOKBACK = 252              # 52 weeks of sessions
PAIR_WINDOW = 20            # rolling sessions for the confirmation pair

WINDOWS = {
    "continuous": ("2019-01-01", "2026-11-20"),
    "validation": ("2023-01-01", "2026-11-20"),
}
REFERENCES = {
    "continuous": {"champion_vm": 544.47, "spy_buyhold": 313.62},
    "validation": {"champion_vm": 288.05, "spy_buyhold": 187.77},
}


# ------------------------------------------------------------------ data
def fetch(ticker):
    path = os.path.join(CACHE, f"{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path) as f:
            return json.load(f)
    p1 = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 21, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div,splits")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def load_series(ticker):
    """dict date -> (adj_open, adj_close); house construction."""
    data = fetch(ticker)
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


SERIES = {t: load_series(t) for t in ("SPY", "DIA", "IYT")}
CAL = sorted(SERIES["SPY"].keys())            # master calendar = SPY days
CAL_IDX = {d: i for i, d in enumerate(CAL)}


def aligned_closes(ticker):
    """Closes on the master calendar, forward-filled (house convention)."""
    s = SERIES[ticker]
    out = []
    last = None
    for d in CAL:
        if d in s:
            last = s[d][1]
        out.append(last)
    return out


CLOSES = {t: aligned_closes(t) for t in ("SPY", "DIA", "IYT")}


def open_on(ticker, date):
    s = SERIES[ticker]
    if date in s:
        return s[date][0]
    i = CAL_IDX[date]
    for j in range(i, -1, -1):
        if CAL[j] in s:
            return s[CAL[j]][1]
    return None


# ------------------------------------------------------- confirmation core
def extreme_flags(closes):
    """(new_high[i], new_low[i]): close strictly beyond every close of
    the prior LOOKBACK sessions. None until the lookback is full."""
    n = len(closes)
    hi = [False] * n
    lo = [False] * n
    for i in range(LOOKBACK, n):
        window = closes[i - LOOKBACK:i]
        if closes[i] > max(window):
            hi[i] = True
        if closes[i] < min(window):
            lo[i] = True
    return hi, lo


FLAGS = {}
for t in ("DIA", "IYT"):
    FLAGS[t] = extreme_flags(CLOSES[t])

# Confirmation events over the full calendar: EVENTS[i] in
# {None, "bullish", "bearish"} — the session the pair completes.
EVENTS = [None] * len(CAL)
COLLISIONS = []
_last_hi = {"DIA": None, "IYT": None}
_last_lo = {"DIA": None, "IYT": None}
for i in range(len(CAL)):
    bull = bear = False
    for t in ("DIA", "IYT"):
        if FLAGS[t][0][i]:
            _last_hi[t] = i
        if FLAGS[t][1][i]:
            _last_lo[t] = i
    lh = _last_hi.values()
    ll = _last_lo.values()
    if (FLAGS["DIA"][0][i] or FLAGS["IYT"][0][i]) and None not in lh \
            and max(lh) - min(lh) <= PAIR_WINDOW - 1:
        bull = True
    if (FLAGS["DIA"][1][i] or FLAGS["IYT"][1][i]) and None not in ll \
            and max(ll) - min(ll) <= PAIR_WINDOW - 1:
        bear = True
    if bull and bear:
        COLLISIONS.append(CAL[i])
        EVENTS[i] = "bearish"        # risk-off precedence (see header)
    elif bull:
        EVENTS[i] = "bullish"
    elif bear:
        EVENTS[i] = "bearish"


# ------------------------------------------------------------------ engine
def run_pot(start, end, desired_by_day, floor_on=True, label="",
            initial_pending=None):
    """One program pot trading SPY. desired_by_day: dict CAL-index ->
    desired invested state as decided at that day's close (changes
    execute at the next open). Days absent from the dict keep the
    current state. Starts flat in cash; initial_pending, if given, is a
    state decided before the window that executes at the first open
    (used only by the buy-hold control)."""
    days = [d for d in CAL if start <= d <= end]
    cash = START_CASH
    shares = 0.0
    holding = False
    total_costs = 0.0
    trades = []
    switches = []
    curve = []
    invested_days = 0
    halted = None
    halt_info = None
    pending = initial_pending

    def buy_all(d):
        nonlocal cash, shares, holding, total_costs
        o = open_on("SPY", d)
        sh = (cash / (1.0 + COST_RATE)) / o
        c = cash - sh * o
        total_costs += c
        trades.append((d, "BUY", round(sh * o, 2), round(c, 4)))
        cash = 0.0
        shares = sh
        holding = True

    def sell_all(d, at_open=True, tag="SELL"):
        nonlocal cash, shares, holding, total_costs
        if at_open:
            px = open_on("SPY", d)
        else:
            px = CLOSES["SPY"][CAL_IDX[d]]
        val = shares * px
        c = val * COST_RATE + SELL_FEE
        total_costs += c
        trades.append((d, tag, round(val, 2), round(c, 4)))
        cash = val - c
        shares = 0.0
        holding = False
        return cash

    for di, d in enumerate(days):
        if pending is not None:
            if pending and not holding:
                buy_all(d)
                switches.append((d, True))
            elif not pending and holding:
                sell_all(d)
                switches.append((d, False))
            pending = None
        v = cash + (shares * CLOSES["SPY"][CAL_IDX[d]] if holding else 0.0)
        curve.append((d, v))
        if holding:
            invested_days += 1
        if floor_on and v <= FLOOR and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor": FLOOR}
            if holding:
                nd = days[di + 1]
                final = sell_all(nd, at_open=True, tag="SELL-HALT")
                halt_info["fill_date"] = nd
                halt_info["fill_value"] = round(final, 2)
            else:
                final = cash
                halt_info["fill_date"] = d
                halt_info["fill_value"] = round(final, 2)
            return _finish(label, final, total_costs, trades, switches,
                           curve, invested_days, days, halted, halt_info)
        want = desired_by_day.get(CAL_IDX[d])
        if want is not None and want != holding:
            # a state decided at today's close executes at the next
            # open; if the run ends first, it simply never executes
            pending = want
    if holding:
        final = sell_all(days[-1], at_open=False, tag="SELL-END")
    else:
        final = cash
    return _finish(label, final, total_costs, trades, switches, curve,
                   invested_days, days, halted, halt_info)


def _finish(label, final, total_costs, trades, switches, curve,
            invested_days, days, halted, halt_info):
    peak = -1.0
    max_dd = 0.0
    worst = None
    for d, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak)
        if worst is None or v < worst[1]:
            worst = (d, v)
    return {
        "label": label,
        "final": round(final, 2),
        "return_pct": round(final / START_CASH * 100 - 100, 2),
        "total_costs": round(total_costs, 2),
        "n_trades": len(trades),
        "trades": trades,
        "switches": switches,
        "n_switches": len(switches),
        "invested_days": invested_days,
        "window_days": len(days),
        "pct_days_invested": round(100.0 * invested_days / len(days), 1)
        if days else 0.0,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "worst_close": [worst[0], round(worst[1], 2)] if worst else None,
        "halted": halted,
        "halt_info": halt_info,
        "curve": [(d, round(v, 2)) for d, v in curve],
    }


def strategy_desired(start, end):
    """Desired-state decisions from F-4 confirmation events inside the
    window. Returns (desired_by_day, event_log). Start flat: state is
    False until the first in-window confirmation decides otherwise."""
    desired = {}
    state = False
    log = []
    for d in CAL:
        if d < start or d > end:
            continue
        ev = EVENTS[CAL_IDX[d]]
        if ev is not None:
            new_state = (ev == "bullish")
            acted = new_state != state
            log.append({"date": d, "event": ev, "acted_on": acted})
            if acted:
                state = new_state
                desired[CAL_IDX[d]] = state
    return desired, log


def invested_state_series(res, start, end):
    """Boolean invested-at-close per day the run lived, rebuilt from
    its switches: a switch executes at the day's open, so that day's
    close is already in the new state. The series stops where the
    run's curve stops (a halted run has no later states)."""
    days = [d for d in CAL if start <= d <= end][:len(res["curve"])]
    state = False
    sw = {d: s for d, s in res["switches"]}
    out = []
    for d in days:
        if d in sw:
            state = sw[d]
        out.append(state)
    return out


def spells_of(state_series):
    spells = []
    run = 0
    for s in state_series:
        if s:
            run += 1
        elif run:
            spells.append(run)
            run = 0
    if run:
        spells.append(run)
    return spells


def placebo_desired(state_series, days, seed):
    """Rebuild (desired_by_day, initial_pending) with the strategy's
    own spells placed at random over the window. Cash days are re-split
    into gaps (first, internal >= 1 so spells stay separate, last) by
    random composition. Only placement is randomized: spell count,
    spell lengths, and total invested days are the strategy's own."""
    spells = spells_of(state_series)
    n = len(days)
    invested = sum(spells)
    cash_days = n - invested
    if not spells:
        return {}, None
    rng = random.Random(seed)
    n_gaps = len(spells) + 1
    internal = len(spells) - 1
    free = cash_days - internal          # internal gaps keep >= 1
    gaps = [0] * n_gaps
    for g in range(1, n_gaps - 1):
        gaps[g] = 1
    for _ in range(free):
        gaps[rng.randrange(n_gaps)] += 1
    path = []
    for gi, g in enumerate(gaps):
        path.extend([False] * g)
        if gi < len(spells):
            path.extend([True] * spells[gi])
    assert len(path) == n, (len(path), n)
    desired = {}
    initial_pending = None
    prev = False
    for i, d in enumerate(days):
        if path[i] != prev:
            if i == 0:
                initial_pending = path[i]
            else:
                # decided at the prior day's close, executes at this
                # day's open — the same convention as the strategy
                desired[CAL_IDX[days[i - 1]]] = path[i]
            prev = path[i]
    return desired, initial_pending


def pct(sorted_vals, q):
    if not sorted_vals:
        return None
    i = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return sorted_vals[i]


# --------------------------------------------------------------------- main
def main():
    out = {
        "test": "Folklore F-4 — Dow Theory confirmation (reduced mechanical core)",
        "spec_source": "research/v7-completeness/folklore-audit.md, Spec F-4 (frozen)",
        "caveat": "Tests the confirmation tenet only — the mechanical core, "
                  "not Hamilton's interpreted practice and not the whole theory.",
        "data": {
            "source": "Yahoo Finance chart API (cached in ./data)",
            "basis": "adjclose closes; opens scaled by adjclose/close",
            "first_date": CAL[0],
            "last_date": CAL[-1],
            "confirmation_collisions": COLLISIONS,
        },
        "chassis": {
            "start_cash": START_CASH, "cost_rate_per_side": COST_RATE,
            "sell_fee": SELL_FEE, "floor": FLOOR,
            "lookback_sessions": LOOKBACK, "pair_window_sessions": PAIR_WINDOW,
        },
        "windows": {},
    }
    for name, (start, end) in WINDOWS.items():
        days = [d for d in CAL if start <= d <= end]
        desired, event_log = strategy_desired(start, end)
        res = run_pot(start, end, desired, floor_on=True, label=f"F-4 {name}")
        res_nf = run_pot(start, end, desired, floor_on=False,
                         label=f"F-4 {name} (no floor)")
        # SPY buy-hold control: bought at the window's first open,
        # held (same costs, same plain floor)
        bh = run_pot(start, end, {}, floor_on=True,
                     label=f"SPY buy-hold {name}", initial_pending=True)
        # placebo: spell-matched random placement, 20 seeds
        state_series = invested_state_series(res, start, end)
        finals = []
        for seed in range(1, 21):
            pd_, p_init = placebo_desired(state_series, days, seed)
            pr = run_pot(start, end, pd_, floor_on=True,
                         label=f"placebo {name} seed {seed}",
                         initial_pending=p_init)
            finals.append(pr["final"])
        finals_sorted = sorted(finals)
        med = pct(finals_sorted, 0.5)
        beaten = sum(1 for f in finals if f < res["final"])
        ties = sum(1 for f in finals if f == res["final"])
        placebo = {
            "seeds": 20,
            "finals": [round(f, 2) for f in finals],
            "median": med,
            "q1": pct(finals_sorted, 0.25),
            "q3": pct(finals_sorted, 0.75),
            "best": finals_sorted[-1] if finals_sorted else None,
            "worst": finals_sorted[0] if finals_sorted else None,
            "strategy_seeds_beaten": beaten,
            "strategy_percentile": round(100.0 * (beaten + 0.5 * ties) / 20, 1)
            if finals else None,
            "strategy_spells": spells_of(state_series),
        }
        curve = res.pop("curve")
        bh_curve = bh.pop("curve")
        out["windows"][name] = {
            "window": [days[0], days[-1]],
            "reference": REFERENCES[name],
            "strategy": res,
            "strategy_no_floor_final": res_nf["final"],
            "spy_buyhold": bh,
            "placebo": placebo,
            "confirmation_events": event_log,
            "n_confirmations": len(event_log),
            "n_bullish": sum(1 for e in event_log if e["event"] == "bullish"),
            "n_bearish": sum(1 for e in event_log if e["event"] == "bearish"),
            "curve": curve,
            "spy_buyhold_curve": bh_curve,
        }
        w = out["windows"][name]
        print(f"[{name}] F-4 final=${res['final']:,.2f} "
              f"({res['return_pct']:+.2f}%) switches={res['n_switches']} "
              f"invested={res['pct_days_invested']}% maxDD={res['max_drawdown_pct']}% "
              f"halted={res['halted']} | SPY BH=${bh['final']:,.2f} "
              f"(ref ${REFERENCES[name]['spy_buyhold']:,.2f}) | "
              f"placebo median=${med:,.2f} beaten={beaten}/20 | "
              f"confirmations={len(event_log)} "
              f"(bull {w['n_bullish']} / bear {w['n_bearish']})", flush=True)
    with open(os.path.join(HERE, "folklore-f4-dowtheory-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
