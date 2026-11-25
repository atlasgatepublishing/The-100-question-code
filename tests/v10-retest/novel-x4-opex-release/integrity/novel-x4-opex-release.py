#!/usr/bin/env python3
"""
NOVEL N-4 — OPEx-WEEK PINNING RELEASE (invented 2026, v8 novel track).
Terry's AI stock app. Simulation only.

THE SPEC (research/v8-novel/novel-cross-calendar.md, rule N-4, FROZEN —
implemented exactly as written; run once, no tuning):

  Expiration day E: the third Friday of the month; if that Friday is not
  a trading day, E is the nearest prior trading day. OpEx week is E and
  the 4 trading days preceding it.

  Compression ratio (per pond name, on closes through the day before E):
    A = mean |daily return| over the first 4 days of OpEx week (the 4
        trading days ending the day before E)
    B = mean |daily return| over the trailing 60 trading days ending on
        that same day
    CR = A / B
  Pre-week trend: return from the close 10 trading days before E to the
  close on the day before E.
  Eligibility: CR <= 0.70 AND pre-week trend > 0.
  Selection/entry: rank eligible names by CR ascending, take top 5, buy
  at the CLOSE of E, equal weight in fifths of the pot (each name 20%);
  any unused weight (fewer than 5 eligible) stays in SPY during the
  window. If none eligible, no trade.
  Exit: sell the basket at the close of the 5th trading day after E and
  return that weight to SPY. Outside the window the pot holds SPY.

  Placebos (both are part of the frozen spec):
    (a) random names — same dates and mechanics, 5 pond names drawn at
        random per event, 20 seeds;
    (b) CALENDAR placebo — the identical compression screen run on the
        SECOND Friday of each month (a non-expiration dated week), same
        mechanics. If the second-Friday screen does as well, the
        expiration date itself is doing no work and the rule fails on
        its own terms.

  Chassis (spec section 0): $100 pot; costs 0.10% of trade value per
  side + $0.01 per sell order; plain -15% floor ($85) on the daily
  close -> liquidate at next open, run ends. Universe: the honest
  top-30 pond as of Nov 2016 (champion engine's UNIVERSE) + SPY.
  Windows: FULL 2019-01-02 -> 2026-11-20, VALIDATION 2023-01-03 ->
  2026-11-20. Trades at the closes the spec names (the section-0
  exception for mechanism-defined closes).

INVENTED-IN-2026 JUDGING (pre-registered in the tasking; harsher than
for published families): this is 1 of 12 invented rules. The best
possible verdict is CANDIDATE — only a forward paper trial can promote
an invented rule. CANDIDATE requires ALL of:
  1. validation final > SPY buy-hold $187.77
  2. validation placebo >= 19/20 beaten, INCLUDING beating the
     second-Friday calendar placebo on validation
  3. continuous final > SPY buy-hold $313.62
  4. no floor halt on either main window
Anything less = NOT A CANDIDATE, reported plainly.

FORCED READINGS (stated here and in the report, before results):
  1. Weighting: "equal weight" + "any pot weight not used stays in SPY"
     is read as fifths of the pot — each selected name is bought with
     20% of the pot's value at the close of E; with k < 5 eligible,
     (5-k)/5 of the pot simply never leaves SPY.
  2. The second-Friday calendar placebo uses the identical anchor
     convention as E: the second Friday of the month, or the nearest
     prior trading day if it is not one; its "week" is that day and
     the 4 trading days preceding it; CR/trend windows, entry at its
     close, exit at the close of the 5th trading day after it — all
     identical.
  3. Event membership: an event belongs to a window iff E falls inside
     the window AND the exit day (5th trading day after E) is on or
     before the window's last day. (Nov 2026's E is 2026-11-20, the
     final day itself; its exit is unobservable inside the window, so
     it is excluded from both windows.)
  4. All day counts are SPY-calendar trading days. A name's signal
     windows are read off the SPY calendar: A uses the returns on
     calendar days p-4..p-1, B the returns on p-60..p-1, the trend
     compares closes at p-10 and p-1, where p is E's calendar index.
     A name is screenable for an event only if it has closes on every
     calendar day p-61..p (entry day included); otherwise it is
     skipped for that event (program skip convention, never patched).
  5. Cost mechanics follow the champion engine exactly: sells are
     charged value*0.10% + $0.01; buys are charged value*0.10% (no
     ticket fee) and are capped by available cash (buy_val =
     min(target, cash/1.001)). Full-pot SPY purchases (window start,
     post-exit rebuys) spend all cash champion-style: shares =
     (cash/1.001)/price, the remainder being the buy cost — identical
     to the champion's spy_net construction, so SPY-only stretches of
     the pot are mechanically identical to the control.
  6. The pot enters SPY at the OPEN of the window's first trading day
     (as the buy-hold control does); all later trades are at the
     closes the spec names. Floor halts liquidate at the next open,
     champion semantics. End of window: everything is liquidated at
     the final close with sell costs (champion SELL-END semantics).
  7. Random-placebo draws: per event, 5 distinct names sampled from
     the full 30-name pond (eligibility ignored — the placebo
     randomizes the rule's SELECTION, per spec section 0), drawn
     chronologically with random.Random(seed), seeds 1..20. A drawn
     name with no close on E is dropped and its fifth stays in SPY
     (same skip convention as the ranked run).

Data: the program's cached Yahoo chart payloads (backtests/v4/data,
then backtests/v4/value-momentum-honest-data), champion construction:
close = adjclose (total-return basis), open = raw open x
adjclose/close. Integrity: the champion engine's own spy_net, run on
these bars, must reproduce the published SPY nets ($313.62 / $187.77)
to the cent before any strategy number is taken.
"""
import calendar as _cal
import importlib.util
import json
import math
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
CACHE_DIRS = [os.path.join(V4, "data"),
              os.path.join(V4, "value-momentum-honest-data")]

START_CASH = 100.0
FLOOR0 = 85.0
WINDOWS = (("FULL", "2019-01-02", "2026-11-20"),
           ("VALIDATION", "2023-01-03", "2026-11-20"))
PLACEBO_SEEDS = list(range(1, 21))
CHAMPION = {"FULL": 544.47, "VALIDATION": 288.05}
SPY_PUBLISHED = {"FULL": 313.62, "VALIDATION": 187.77}
CR_MAX = 0.70
TOP_N = 5

# ------------------------------------------------------------ champion engine
spec = importlib.util.spec_from_file_location(
    "champion", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
UNIVERSE = list(E.UNIVERSE)


def load_bars(ticker):
    """Champion-construction bars {d, o, c} from the cached payloads."""
    path = None
    for d in CACHE_DIRS:
        p = os.path.join(d, f"px_{ticker}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            path = p
            break
    if path is None:
        raise SystemExit(f"no cached payload for {ticker}")
    with open(path, "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


# ------------------------------------------------------------------ calendar
def nth_friday(year, month, n):
    """Date string of the n-th Friday of the month."""
    fridays = [d for d in range(1, _cal.monthrange(year, month)[1] + 1)
               if _cal.weekday(year, month, d) == 4]
    return f"{year:04d}-{month:02d}-{fridays[n - 1]:02d}"


def build_events(cal_index, start, end, which_friday):
    """Event anchors: for each month in range, anchor = last trading day
    on or before the n-th Friday; event kept iff anchor in window and
    exit day (anchor + 5 trading days) <= end. Returns list of calendar
    indices p (the anchor day E)."""
    months = []
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    while (y, m) <= (ey, em):
        months.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    out = []
    dates = sorted(cal_index)
    for (y, m) in months:
        target = nth_friday(y, m, which_friday)
        # last trading day <= target
        p = None
        for d in dates:
            if d <= target:
                p = cal_index[d]
            else:
                break
        if p is None:
            continue
        e_day = dates[p]
        if not (start <= e_day <= end):
            continue
        if p + 5 >= len(dates) or dates[p + 5] > end:
            continue
        out.append(p)
    return out


# -------------------------------------------------------------------- screen
def screen(closes, p):
    """Compression screen at anchor index p. closes: ticker -> aligned
    close list over the SPY calendar (None where no bar). Returns
    (ranked, detail): ranked = eligible tickers sorted by CR ascending;
    detail = {ticker: (CR, trend)} for every screenable name."""
    ranked = []
    detail = {}
    for t in UNIVERSE:
        c = closes[t]
        if p - 61 < 0 or any(c[j] is None for j in range(p - 61, p + 1)):
            continue
        a = sum(abs(c[j] / c[j - 1] - 1.0) for j in range(p - 4, p)) / 4.0
        b = sum(abs(c[j] / c[j - 1] - 1.0) for j in range(p - 60, p)) / 60.0
        if b <= 0:
            continue
        cr = a / b
        trend = c[p - 1] / c[p - 10] - 1.0
        detail[t] = (cr, trend)
        if cr <= CR_MAX and trend > 0:
            ranked.append(t)
    ranked.sort(key=lambda t: detail[t][0])
    return ranked, detail


# -------------------------------------------------------------------- engine
def run_pot(cal, closes, opens, events, start, end, label=""):
    """One $100 pot. events: list of dicts {p, picks} in chronological
    order (picks already chosen — ranked, calendar-placebo, or random).
    Holds SPY outside event windows; basket from close of E to close of
    E+5. Champion cost/floor semantics throughout."""
    days = [d for d in cal if start <= d <= end]
    pos_of = {d: i for i, d in enumerate(cal)}
    ev_in = {e["p"]: e for e in events}
    ev_out = {e["p"] + 5: e for e in events}
    cash = START_CASH
    pos = {}          # ticker -> shares ('SPY' for the index holding)
    trades = []
    total_costs = 0.0
    orders = 0
    curve = []
    halted = None
    event_rows = []

    def close_px(t, d):
        i = pos_of[d]
        v = closes[t][i]
        if v is not None:
            return v
        # champion convention: last close on or before d
        j = i
        while j >= 0 and closes[t][j] is None:
            j -= 1
        return closes[t][j] if j >= 0 else None

    def equity_close(d):
        v = cash
        for t, sh in pos.items():
            px = close_px(t, d)
            if px:
                v += sh * px
        return v

    def sell(t, sh, px, d, tag):
        nonlocal cash, total_costs, orders
        val = sh * px
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        orders += 1
        trades.append((d, t, tag, round(sh, 4), round(px, 4),
                       round(val, 2), round(c, 2)))
        return val

    def buy_value(t, target, px, d, tag):
        """Champion buy: value capped by cash/1.001, 0.10% cost on top."""
        nonlocal cash, total_costs, orders
        buy_val = min(target, cash / 1.001)
        if buy_val <= 0.005 or px is None or px <= 0:
            return 0.0
        sh = buy_val / px
        c = buy_val * 0.001
        cash -= buy_val + c
        total_costs += c
        orders += 1
        pos[t] = pos.get(t, 0.0) + sh
        trades.append((d, t, tag, round(sh, 4), round(px, 4),
                       round(buy_val, 2), round(c, 2)))
        return buy_val

    def buy_all_in(t, px, d, tag):
        """Spend ALL cash on t (champion spy_net construction)."""
        nonlocal cash, total_costs, orders
        if cash <= 0.005 or px is None or px <= 0:
            return
        buy_val = cash / 1.001
        sh = buy_val / px
        c = cash - buy_val
        cash = 0.0
        total_costs += c
        orders += 1
        pos[t] = pos.get(t, 0.0) + sh
        trades.append((d, t, tag, round(sh, 4), round(px, 4),
                       round(buy_val, 2), round(c, 2)))

    for di, d in enumerate(days):
        p = pos_of[d]
        if di == 0:
            # enter SPY at the first day's open (control construction)
            o = opens["SPY"][p]
            buy_all_in("SPY", o, d, "BUY-START")
        # entry at the close of E
        if p in ev_in:
            e = ev_in[p]
            picks = [t for t in e["picks"] if closes[t][p] is not None]
            if picks:
                v = equity_close(d)
                k = len(picks)
                spy_px = closes["SPY"][p]
                # sell (k/5) of pot value out of SPY
                if pos.get("SPY", 0.0) > 0 and spy_px:
                    target_val = (k / 5.0) * v
                    sh_sell = min(pos["SPY"], target_val / spy_px)
                    if sh_sell > 1e-9:
                        sell("SPY", sh_sell, spy_px, d, "SELL-ROT")
                        pos["SPY"] -= sh_sell
                        if pos["SPY"] < 1e-9:
                            del pos["SPY"]
                for t in picks:
                    buy_value(t, v / 5.0, closes[t][p], d, "BUY")
                e["traded_picks"] = list(picks)
        # exit at the close of the 5th trading day after E
        if p in ev_out:
            e = ev_out[p]
            held = [t for t in list(pos) if t != "SPY"]
            for t in held:
                px = close_px(t, d)
                if px:
                    sell(t, pos[t], px, d, "SELL-EXIT")
                del pos[t]
            if held:
                buy_all_in("SPY", closes["SPY"][p], d, "BUY-BACK")
        # daily close: curve + floor
        v = equity_close(d)
        curve.append((d, v))
        if v <= FLOOR0 and di < len(days) - 1:
            halted = d
            nd = days[di + 1]
            np_ = pos_of[nd]
            for t in list(pos):
                o = opens[t][np_]
                if o:
                    sell(t, pos[t], o, nd, "SELL-HALT")
                del pos[t]
            return _result(label, cash, total_costs, orders, trades,
                           curve, halted, nd, events, cal, closes)
    # end of window: liquidate at final close
    last = days[-1]
    for t in list(pos):
        px = close_px(t, last)
        if px:
            sell(t, pos[t], px, last, "SELL-END")
        del pos[t]
    return _result(label, cash, total_costs, orders, trades, curve,
                   None, last, events, cal, closes)


def _result(label, cash, total_costs, orders, trades, curve, halted, end,
            events, cal, closes):
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = round(v, 2)
    ev_rows = []
    for e in events:
        p = e["p"]
        picks = e.get("traded_picks", e["picks"])
        if picks:
            rets = [closes[t][p + 5] / closes[t][p] - 1.0 for t in picks
                    if closes[t][p] and closes[t][p + 5]]
            basket_ret = sum(rets) / len(rets) if rets else None
        else:
            basket_ret = None
        spy_ret = closes["SPY"][p + 5] / closes["SPY"][p] - 1.0
        ev_rows.append({
            "E": cal[p], "exit": cal[p + 5],
            "n_eligible": e.get("n_eligible"),
            "picks": picks,
            "CRs": {t: round(e["detail"][t][0], 4)
                    for t in e.get("detail", {}) if t in picks},
            "basket_ret_pct": (round(basket_ret * 100, 3)
                               if basket_ret is not None else None),
            "spy_ret_pct": round(spy_ret * 100, 3),
        })
    return {"label": label, "final": round(cash, 2), "costs": round(total_costs, 2),
            "orders": orders, "halted": halted, "end": end,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "year_end_closes": year_end,
            "events": ev_rows, "trades": trades}


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


# ---------------------------------------------------------------------- main
def main():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = load_bars(t)
        print(f"{t}: {len(bars[t])} bars {bars[t][0]['d']}..{bars[t][-1]['d']}",
              flush=True)

    # integrity: champion engine's own spy_net on these bars
    pb = E.PriceBook(bars)
    integrity = {}
    for wname, ws, we in WINDOWS:
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        integrity[wname] = {"spy_net": round(s, 2),
                            "published": SPY_PUBLISHED[wname],
                            "match": round(s, 2) == SPY_PUBLISHED[wname]}
        print(f"INTEGRITY {wname}: spy_net=${s:,.2f} published="
              f"${SPY_PUBLISHED[wname]:,.2f} match={integrity[wname]['match']}",
              flush=True)
    if not all(v["match"] for v in integrity.values()):
        raise SystemExit("INTEGRITY FAILURE — SPY control does not "
                         "reproduce published figures; no strategy "
                         "numbers taken.")

    cal = [b["d"] for b in bars["SPY"]]
    cal_index = {d: i for i, d in enumerate(cal)}
    closes, opens = {}, {}
    for t in UNIVERSE + ["SPY"]:
        by_date = {b["d"]: b for b in bars[t]}
        closes[t] = [by_date[d]["c"] if d in by_date else None for d in cal]
        opens[t] = [by_date[d]["o"] if d in by_date else None for d in cal]

    out = {
        "strategy": "NOVEL N-4 OPEx-WEEK PINNING RELEASE (invented 2026), "
                    "$100, plain -15% floor",
        "spec_source": "research/v8-novel/novel-cross-calendar.md, Rule N-4",
        "invented_rule_context": "1 of 12 invented rules (v8 novel track); "
                                 "best possible verdict is CANDIDATE — only "
                                 "a forward paper trial can promote an "
                                 "invented rule",
        "pot": START_CASH, "floor": FLOOR0,
        "integrity_spy": integrity,
    }
    gates = {}
    for wname, ws, we in WINDOWS:
        # ranked events (third Friday)
        ranked_events = []
        for p in build_events(cal_index, ws, we, 3):
            ranked, detail = screen(closes, p)
            ranked_events.append({"p": p, "picks": ranked[:TOP_N],
                                  "n_eligible": len(ranked),
                                  "detail": detail})
        r = run_pot(cal, closes, opens, ranked_events, ws, we,
                    label=f"{wname} RANKED")
        # calendar placebo events (second Friday, identical screen)
        cal_events = []
        for p in build_events(cal_index, ws, we, 2):
            ranked, detail = screen(closes, p)
            cal_events.append({"p": p, "picks": ranked[:TOP_N],
                               "n_eligible": len(ranked),
                               "detail": detail})
        cp = run_pot(cal, closes, opens, cal_events, ws, we,
                     label=f"{wname} CALENDAR-PLACEBO")
        # random placebos on the ranked event dates
        finals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            evs = []
            for e in ranked_events:
                picks = rng.sample(sorted(UNIVERSE), TOP_N)
                evs.append({"p": e["p"], "picks": picks,
                            "n_eligible": None, "detail": {}})
            pr = run_pot(cal, closes, opens, evs, ws, we,
                         label=f"{wname} PLACEBO-{seed}")
            finals.append(pr["final"])
        finals_sorted = sorted(finals)
        beaten = sum(1 for f in finals if r["final"] > f)
        med = _pct(finals_sorted, 0.5)
        p95 = _pct(finals_sorted, 0.95)
        n_ev = len(ranked_events)
        n_active = sum(1 for e in ranked_events if e["n_eligible"] > 0)
        elig = [e["n_eligible"] for e in ranked_events]
        wins = sum(1 for e in r["events"]
                   if e["basket_ret_pct"] is not None
                   and e["basket_ret_pct"] > e["spy_ret_pct"])
        traded = [e for e in r["events"] if e["basket_ret_pct"] is not None]
        out[wname.lower()] = {
            "ranked": {k: r[k] for k in
                       ("final", "costs", "orders", "halted", "end",
                        "worst_close", "worst_close_date",
                        "max_drawdown_pct", "max_drawdown_date",
                        "year_end_closes")},
            "events": r["events"],
            "trades": r["trades"],
            "n_events": n_ev, "n_events_with_eligible": n_active,
            "mean_eligible": round(sum(elig) / len(elig), 2) if elig else None,
            "events_basket_beat_spy": wins,
            "events_traded": len(traded),
            "calendar_placebo": {k: cp[k] for k in
                                 ("final", "costs", "orders", "halted",
                                  "worst_close", "max_drawdown_pct")},
            "calendar_placebo_events": cp["events"],
            "placebo_finals": finals,
            "placebo_median": round(med, 2), "placebo_p95": round(p95, 2),
            "placebo_beaten": beaten,
            "spy_net": SPY_PUBLISHED[wname],
            "champion_reference": CHAMPION[wname],
        }
        print(f"== {wname} RANKED final=${r['final']:,.2f} costs="
              f"${r['costs']:,.2f} orders={r['orders']} halted={r['halted']} "
              f"| events={n_ev} active={n_active} mean_elig="
              f"{out[wname.lower()]['mean_eligible']} | placebo median="
              f"${med:,.2f} beaten={beaten}/20 | calendar placebo="
              f"${cp['final']:,.2f} | SPY=${SPY_PUBLISHED[wname]:,.2f}",
              flush=True)

    v = out["validation"]
    f = out["full"]
    gates = {
        "validation_beats_spy": v["ranked"]["final"] > SPY_PUBLISHED["VALIDATION"],
        "validation_placebo_at_least_19_of_20": v["placebo_beaten"] >= 19,
        "validation_beats_calendar_placebo":
            v["ranked"]["final"] > v["calendar_placebo"]["final"],
        "continuous_beats_spy": f["ranked"]["final"] > SPY_PUBLISHED["FULL"],
        "no_floor_halt_either_window":
            v["ranked"]["halted"] is None and f["ranked"]["halted"] is None,
    }
    out["candidate_gates"] = gates
    out["verdict"] = ("CANDIDATE" if all(gates.values())
                      else "NOT A CANDIDATE")
    print(f"GATES: {gates} -> {out['verdict']}", flush=True)
    with open(os.path.join(HERE, "novel-x4-opex-release-results.json"),
              "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
