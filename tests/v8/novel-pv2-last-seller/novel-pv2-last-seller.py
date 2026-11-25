#!/usr/bin/env python3
"""
NOVEL RULE N-PV2 — "THE LAST SELLER" (volume-climax exhaustion).
Invented 2026 for Terry's AI stock-app program. Simulation only.

FROZEN SPEC (research/v8-novel/novel-price-volume.md, Rule N-PV2, verbatim):
  - Universe: honest top-30 pond as of Nov 2016 (same list as champion).
  - Event on day t for a pond name iff
      (i)  volume on t is STRICTLY greater than volume on each of the
           prior 126 trading days of that name (a 126-day volume high), AND
      (ii) close-to-close return on t <= -1.5%.
  - Entry: buy at the NEXT session's open with 1/5 of the pot's current
    value (cash + holdings marked at the signal-day close).
  - Max 5 concurrent positions; one position per name; a name already
    held cannot re-trigger; it may trigger again only after exit.
  - If more names trigger for one entry day than can be taken, rank by
    volume / trailing 20-day median volume (descending), take the first;
    the rest are logged and skipped.
  - Exit: sell at the open of the 21st trading day after the entry day
    (entry day counted as the 1st trading day -> the open of the entry
    name's bar 20 bars after the entry bar; 20 full trading days held).
  - No per-position stop; the pot-level plain -15% floor ($85.00) is the
    only stop: a close at/below $85 liquidates everything at the next
    open and ends the run.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Cash idle at 0%. Windows: continuous 2019-01-01 -> 2026-11-20 and
    validation 2023-01-01 -> 2026-11-20, fresh $100 pot each.

DATA: the champion engine's cached Yahoo chart payloads, read-only
(v4/data first, then v4/value-momentum-honest-data — the champion's own
precedence). Prices constructed EXACTLY as the champion engine does
(close = adjclose; open = raw open x adjclose/close). Volume is the
payload's `volume` field used verbatim (Yahoo split-adjusted share
volume; the event is a within-name relative comparison).

PLACEBO (task definition): same event dates, random pond names, matched
mechanics — 20 seeds. Construction follows the program's event-test
precedent (gap A-7): the ranked run's TAKEN entry slots (signal date,
entry date) are replayed; for each seed each slot buys a uniform random
pond name (seeded RNG, draws independent per slot; positions keyed by
slot, so a seed may hold two slices of one name). Slice = 1/5 of the
placebo pot's own value marked at the signal-day close; entry at the
drawn name's open on the entry date (first bar on/after it); exit at
the open of the drawn name's bar 20 bars after its entry bar; same
costs, same floor, same window-end liquidation.

VERDICT VOCABULARY (invented rule — harsher bar, per task):
  CANDIDATE requires ALL of: validation final > SPY $187.77;
  validation placebo 20/20 (ranked beats every seed); continuous final
  > SPY $313.62; no floor halt on either main window. Anything less is
  NOT A CANDIDATE. An invented rule can never be "promoted" by a
  backtest — only a forward paper trial can promote it.
"""
import json, math, os, random, statistics, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
CACHE_DIRS = [os.path.join(V4, "data"),
              os.path.join(V4, "value-momentum-honest-data")]

POND = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
        "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
        "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
        "KO", "PEP", "WFC"]

START_CASH = 100.0
FLOOR0 = 85.0
VOL_LOOKBACK = 126
DOWN_GATE = -0.015
HOLD_BARS = 20            # exit at open of entry bar + 20 bars
MAX_POS = 5
SEEDS = list(range(1, 21))
WINDOWS = [("CONTINUOUS", "2019-01-01", "2026-11-20"),
           ("VALIDATION", "2023-01-01", "2026-11-20")]
SPY_PUBLISHED = {"CONTINUOUS": 313.62, "VALIDATION": 187.77}
CHAMPION = {"CONTINUOUS": 544.47, "VALIDATION": 288.05}


# ------------------------------------------------------------------ data
def load_payload(ticker):
    for d in CACHE_DIRS:
        p = os.path.join(d, f"px_{ticker}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            with open(p, "rb") as f:
                return json.loads(f.read())
    raise FileNotFoundError(f"no cached payload for {ticker}")


def get_bars(ticker):
    """Champion-engine bar construction + verbatim Yahoo volume."""
    j = load_payload(ticker)
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
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a,
                     "v": q["volume"][i]})
    bars.sort(key=lambda b: b["d"])
    return bars


class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.idx = {t: {b["d"]: i for i, b in enumerate(bl)}
                    for t, bl in bars_by_ticker.items()}

    def bar_on(self, t, d):
        i = self.idx.get(t, {}).get(d)
        return self.bars[t][i] if i is not None else None

    def close_on_or_before(self, t, d):
        bl = self.bars.get(t, [])
        best = None
        for b in bl:
            if b["d"] <= d:
                best = b
            else:
                break
        return best["c"] if best else None


def spy_net(pb, start, end, start_cash=START_CASH):
    """Champion engine's spy_net, verbatim construction."""
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar_on("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost


# ---------------------------------------------------------------- events
def detect_events(pb):
    """All (name, signal bar) pairs satisfying the frozen event rule,
    over the full cached series. Returns list of dicts."""
    events = []
    for t in POND:
        bl = pb.bars[t]
        for i in range(VOL_LOOKBACK, len(bl)):
            v = bl[i]["v"]
            if v is None:
                continue
            if not all(v > bl[k]["v"] for k in range(i - VOL_LOOKBACK, i)
                       if bl[k]["v"] is not None):
                continue
            # any missing volume inside the lookback disqualifies the day
            if any(bl[k]["v"] is None for k in range(i - VOL_LOOKBACK, i)):
                continue
            ret = bl[i]["c"] / bl[i - 1]["c"] - 1.0
            if ret <= DOWN_GATE:
                med20 = statistics.median(
                    bl[k]["v"] for k in range(i - 20, i))
                events.append({
                    "ticker": t, "signal_date": bl[i]["d"],
                    "signal_idx": i, "ret_pct": round(ret * 100, 2),
                    "vol_ratio": (v / med20) if med20 else None,
                    "entry_date": (bl[i + 1]["d"] if i + 1 < len(bl)
                                   else None),
                })
    events.sort(key=lambda e: (e["signal_date"], e["ticker"]))
    return events


# ---------------------------------------------------------------- engine
def run_pot(pb, start, end, entry_plan, label=""):
    """entry_plan: dict entry_date -> list of slot dicts with keys
    ticker, signal_date. For the ranked run the tickers are the event
    names (eligibility — held/slot ranking — is resolved by the caller
    into this plan only for slots it intends to attempt; see
    build_ranked_plan). For placebo runs the tickers are the drawn
    names and every slot is attempted (cash rule still applies).
    Positions keyed by an incrementing slot id."""
    days = [d for d in pb.dates if start <= d <= end]
    cash = START_CASH
    positions = {}      # slot id -> dict(ticker, shares, entry_date,
                        #                exit_date, buy_cost_total, slice)
    trades = []
    total_costs = 0.0
    curve = []
    equity_by_date = {}
    halted = None
    halt_info = None
    pending_halt = False
    slot_seq = [0]
    taken = []          # slots actually entered (for placebo schedule)
    skipped_cash = 0

    def pot_close(d):
        v = cash
        for p in positions.values():
            c = pb.close_on_or_before(p["ticker"], d)
            if c:
                v += p["shares"] * c
        return v

    for di, d in enumerate(days):
        if pending_halt:
            sig = halt_info["signal_date"]
            for sid in list(positions):
                p = positions[sid]
                nb = next((b for b in pb.bars[p["ticker"]]
                           if b["d"] > sig), None)
                if nb is None:
                    continue
                val = p["shares"] * nb["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nb["d"], p["ticker"], "SELL-HALT",
                               p["shares"], nb["o"], val, c))
                p["exit_date_actual"] = nb["d"]
                p["sell_value_net"] = val - c
                del positions[sid]
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": sig,
                    "halt_info": halt_info, "curve": curve,
                    "taken": taken, "skipped_cash": skipped_cash,
                    "positions_done": []}
        # exits at today's open (exit_date is a bar date of the name)
        for sid in list(positions):
            p = positions[sid]
            if p["exit_date"] is not None and p["exit_date"] == d:
                b = pb.bar_on(p["ticker"], d)
                val = p["shares"] * b["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((d, p["ticker"], "SELL-EXIT", p["shares"],
                               b["o"], val, c))
                p["exit_date_actual"] = d
                p["sell_value_net"] = val - c
                del positions[sid]
        # entries at today's open
        for slot in entry_plan.get(d, []):
            t = slot["ticker"]
            sig = slot["signal_date"]
            marked = equity_by_date.get(sig)
            if marked is None:
                marked = pot_close(sig)
            slice_val = marked / 5.0
            b = pb.bar_on(t, d)
            if b is None:
                # drawn/entry name has no bar today: first bar on/after
                bl = pb.bars[t]
                cand = [x for x in bl if x["d"] >= d]
                if not cand or cand[0]["d"] > end:
                    continue
                b = cand[0]
            buy_val = min(slice_val, cash / 1.001)
            if buy_val <= 0.005:
                skipped_cash += 1
                continue
            sh = buy_val / b["o"]
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            ei = pb.idx[t][b["d"]]
            exit_date = (pb.bars[t][ei + HOLD_BARS]["d"]
                         if ei + HOLD_BARS < len(pb.bars[t]) else None)
            slot_seq[0] += 1
            positions[slot_seq[0]] = {
                "ticker": t, "shares": sh, "entry_date": b["d"],
                "exit_date": exit_date, "buy_cost_total": buy_val + c,
                "slice": buy_val, "signal_date": sig}
            trades.append((b["d"], t, "BUY", sh, b["o"], buy_val, c))
            taken.append({"signal_date": sig, "entry_date": b["d"],
                          "ticker": t})
        v = pot_close(d)
        curve.append((d, v))
        equity_by_date[d] = v
        if v <= FLOOR0 and di < len(days) - 1:
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            pending_halt = True
    last = days[-1]
    done = []
    for sid in list(positions):
        p = positions[sid]
        px = pb.close_on_or_before(p["ticker"], last)
        if px:
            val = p["shares"] * px
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((last, p["ticker"], "SELL-END", p["shares"],
                           px, val, c))
            p["exit_date_actual"] = last
            p["sell_value_net"] = val - c
        done.append(p)
        del positions[sid]
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": halted, "halt_info": halt_info,
            "curve": curve, "taken": taken,
            "skipped_cash": skipped_cash, "positions_done": done}


def build_ranked_plan(pb, events, start, end):
    """Resolve the ranked run's eligibility day by day, exactly per spec:
    window membership by SIGNAL date; a name already held (entry made,
    exit date after the new entry date — exits at the entry day's own
    open free the name first) cannot re-trigger; at most 5 concurrent;
    overflow ranked by vol_ratio descending (ties: ticker). Returns
    (entry_plan, census)."""
    in_window = [e for e in events if start <= e["signal_date"] <= end]
    census = {"total_events": len(in_window), "entered": 0,
              "skipped_held": 0, "skipped_slots": 0,
              "skipped_entry_beyond_window": 0,
              "planned_but_not_taken": 0,
              "by_year": {}}
    for e in in_window:
        census["by_year"][e["signal_date"][:4]] = \
            census["by_year"].get(e["signal_date"][:4], 0) + 1
    by_entry = {}
    for e in in_window:
        if e["entry_date"] is None or e["entry_date"] > end:
            census["skipped_entry_beyond_window"] += 1
            continue
        by_entry.setdefault(e["entry_date"], []).append(e)
    plan = {}
    held_until = {}     # ticker -> exit_date (None = to window end)
    for d in sorted(by_entry):
        cands = by_entry[d]
        # names whose position exits at today's open are free again
        held_now = {t for t, xd in held_until.items()
                    if xd is None or xd > d}
        fresh = []
        for e in cands:
            if e["ticker"] in held_now:
                census["skipped_held"] += 1
            else:
                fresh.append(e)
        slots = MAX_POS - len(held_now)
        fresh.sort(key=lambda e: (-(e["vol_ratio"] or 0), e["ticker"]))
        take = fresh[:max(slots, 0)]
        census["skipped_slots"] += len(fresh) - len(take)
        for e in take:
            bl = pb.bars[e["ticker"]]
            ei = pb.idx[e["ticker"]][e["entry_date"]]
            xd = (bl[ei + HOLD_BARS]["d"]
                  if ei + HOLD_BARS < len(bl) else None)
            held_until[e["ticker"]] = xd
            plan.setdefault(d, []).append(
                {"ticker": e["ticker"], "signal_date": e["signal_date"],
                 "event": e})
            census["entered"] += 1
    return plan, census


def curve_stats(curve):
    worst_d, worst = min(curve, key=lambda kv: kv[1])
    peak, maxdd = curve[0][1], 0.0
    for _, v in curve:
        peak = max(peak, v)
        maxdd = min(maxdd, v / peak - 1.0)
    return {"worst_close": round(worst, 2), "worst_close_date": worst_d,
            "max_drawdown_pct": round(maxdd * 100, 2)}


def summarize(r):
    return {"final": round(r["final"], 2),
            "return_pct": round((r["final"] / START_CASH - 1) * 100, 2),
            "costs": round(r["costs"], 2),
            "n_trades": len(r["trades"]),
            "n_entries": len(r["taken"]),
            "halted": r["halted"], "halt_info": r["halt_info"],
            **curve_stats(r["curve"])}


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


# ------------------------------------------------------------------ main
def main():
    bars = {}
    for t in POND + ["SPY"]:
        bars[t] = get_bars(t)
        print(f"{t}: {len(bars[t])} bars "
              f"{bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = PriceBook(bars)

    # ---- integrity gate: SPY buy-hold must reproduce published nets
    for wname, ws, we in WINDOWS:
        s, _ = spy_net(pb, ws, we)
        print(f"SPY gate {wname}: computed ${s:,.2f} vs published "
              f"${SPY_PUBLISHED[wname]:,.2f}", flush=True)
        assert abs(round(s, 2) - SPY_PUBLISHED[wname]) <= 0.01, \
            f"SPY gate FAILED on {wname}: {s:.2f}"
    print("SPY gate PASSED to the cent on both windows.", flush=True)

    # ---- event census (before any pot is run)
    all_events = detect_events(pb)
    print(f"Total pond events 2017-06->2026-11 (full cache): "
          f"{len(all_events)}", flush=True)

    out = {"strategy": "NOVEL N-PV2 'THE LAST SELLER' (invented 2026)",
           "spec_source": "research/v8-novel/novel-price-volume.md",
           "invented_rule_disclaimer":
               "Invented in 2026 and judged on 2019-2026 data; best "
               "possible verdict is CANDIDATE (forward paper trial "
               "only can promote an invented rule).",
           "windows": {}}
    for wname, ws, we in WINDOWS:
        plan, census = build_ranked_plan(pb, all_events, ws, we)
        planned_takes = census["entered"]
        r = run_pot(pb, ws, we, plan, label=f"N-PV2 {wname}")
        ranked = summarize(r)
        # reconcile census against what the pot actually did (a floor
        # halt or a cash-short entry can leave a planned take untaken)
        census["entered"] = len(r["taken"])
        census["planned_but_not_taken"] = planned_takes - len(r["taken"])
        census["skipped_insufficient_cash"] = r["skipped_cash"]
        # placebo: replay taken slots with random names
        placebo_finals, placebo_detail = [], []
        for seed in SEEDS:
            rng = random.Random(seed)
            pplan = {}
            for slot in r["taken"]:
                nm = rng.choice(POND)
                pplan.setdefault(slot["entry_date"], []).append(
                    {"ticker": nm, "signal_date": slot["signal_date"]})
            pr = run_pot(pb, ws, we, pplan,
                         label=f"N-PV2 {wname} placebo {seed}")
            placebo_finals.append(round(pr["final"], 2))
            placebo_detail.append({"seed": seed,
                                   "final": round(pr["final"], 2),
                                   "halted": pr["halted"]})
        sf = sorted(placebo_finals)
        beaten = sum(1 for f in placebo_finals
                     if ranked["final"] > f)
        win_events = [e for e in all_events
                      if ws <= e["signal_date"] <= we]
        out["windows"][wname] = {
            "window": [ws, we],
            "census": census,
            "events": [{"ticker": e["ticker"],
                        "signal_date": e["signal_date"],
                        "ret_pct": e["ret_pct"],
                        "vol_ratio": (round(e["vol_ratio"], 2)
                                      if e["vol_ratio"] else None),
                        "entry_date": e["entry_date"]}
                       for e in win_events],
            "ranked": ranked,
            "entries_taken": r["taken"],
            "spy_net": SPY_PUBLISHED[wname],
            "champion": CHAMPION[wname],
            "placebo": {"finals": placebo_finals,
                        "median": round(_pct(sf, 0.5), 2),
                        "p25": round(_pct(sf, 0.25), 2),
                        "p75": round(_pct(sf, 0.75), 2),
                        "best": sf[-1], "worst": sf[0],
                        "ranked_beats": beaten,
                        "detail": placebo_detail},
            "trades": [list(t) for t in r["trades"]],
        }
        print(f"== {wname}: events={census['total_events']} "
              f"entered={census['entered']} held-skip="
              f"{census['skipped_held']} slot-skip="
              f"{census['skipped_slots']} | ranked final="
              f"${ranked['final']:,.2f} costs=${ranked['costs']:,.2f} "
              f"halted={ranked['halted']} | placebo median="
              f"${round(_pct(sf, 0.5), 2):,.2f} beats={beaten}/20",
              flush=True)

    # ---- verdict per the task's four prongs
    val = out["windows"]["VALIDATION"]["ranked"]
    con = out["windows"]["CONTINUOUS"]["ranked"]
    val_beats = out["windows"]["VALIDATION"]["placebo"]["ranked_beats"]
    prongs = {
        "validation_beats_spy": val["final"] > SPY_PUBLISHED["VALIDATION"],
        "validation_placebo_20_of_20": val_beats == 20,
        "continuous_beats_spy": con["final"] > SPY_PUBLISHED["CONTINUOUS"],
        "no_floor_halt_either_window": (val["halted"] is None
                                        and con["halted"] is None),
    }
    out["verdict"] = {"prongs": prongs,
                       "candidate": all(prongs.values()),
                       "verdict": ("CANDIDATE" if all(prongs.values())
                                   else "NOT A CANDIDATE"),
                       "framing": "1 of 12 invented rules"}
    print(f"VERDICT: {out['verdict']['verdict']}  prongs={prongs}",
          flush=True)
    with open(os.path.join(HERE, "novel-pv2-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
