#!/usr/bin/env python3
"""
NOVEL TEST N-PV1 — "THE STANDING BID" (rejected-excursion / shadow-share
sort) — Terry's AI stock app, v8 novel ("never been done") track.
Simulation only.

Implements Rule N-PV1 from research/v8-novel/novel-price-volume.md
VERBATIM. The spec is frozen: no parameter was improved, re-cut, or
reinterpreted. Forced readings are declared in the report BEFORE results
and summarized in the header notes of the results JSON.

Spec N-PV1 as written:
  - Universe: the honest top-30 pond as of Nov 2016 (champion engine's
    UNIVERSE). Data: daily OHLC from the champion engine's Yahoo caches.
  - Signal: on the last trading day of each month, for each pond name
    take the trailing 20 trading days (including the signal day). For
    each day with range R = High - Low > 0, lower-shadow share
    LS = (min(Open, Close) - Low) / R and upper-shadow share
    US = (High - max(Open, Close)) / R. Score S = mean(LS) - mean(US)
    over the valid days. A name with fewer than 15 valid (R > 0) days
    in the window is ineligible that month.
  - Entry/exit: rank eligible names by S descending; buy the top 5,
    equal weight (1/5 of current pot value each), at the next session's
    open. Hold one month. At each month-end, sell ALL holdings and
    re-buy the new top 5 at the next open (full rotation, no netting).

House chassis (program-wide): $100 pot, long-only; costs 0.10% of trade
value per side + $0.01 per sell order; plain -15% floor at pot level
(close at/below $85 -> liquidate at next open, run ends — champion
engine semantics); windows continuous 2019-01-01->2026-11-20 and
validation 2023-01-01->2026-11-20; benchmarks SPY buy-hold net of the
same costs (the champion engine's spy_net, imported) and a 20-seed
random placebo (random 5 names drawn from the same month's eligible
set, identical dates and mechanics).

INVENTED-RULE BAR (harsher than for published families; this rule was
invented in 2026 and is reported as "1 of 12 invented rules"): the best
possible verdict is CANDIDATE — only a forward paper trial can promote
an invented rule. CANDIDATE requires ALL of: (1) validation final >
SPY $187.77, (2) validation placebo 20/20, (3) continuous final > SPY
$313.62, (4) no floor halt on either main window. Anything less is
NOT A CANDIDATE.

Prices: raw payloads read from the champion engine's own two cache
dirs, in the engine's own lookup order (backtests/v4/data/ first, then
backtests/v4/value-momentum-honest-data/). The engine stores adjusted
opens/closes only (Yahoo adjclose/close ratio method); highs/lows are
adjusted by the identical ratio from the same payloads, exactly as the
Ichimoku test (backtests/v7/folklore-f5-ichimoku/) constructed them.
Integrity: this script asserts its adjusted opens/closes equal the
champion engine's bars for every pond name and SPY, and that the
engine's spy_net reproduces the published $313.62 / $187.77 to the
cent, before any variant number is taken.
"""
import importlib.util
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
CACHE_DIRS = [os.path.join(V4, "data"),
              os.path.join(V4, "value-momentum-honest-data")]

START_CASH = 100.0
FLOOR0 = 85.0
WINDOWS = (("FULL", "2019-01-01", "2026-11-20"),
           ("VALIDATION", "2023-01-01", "2026-11-20"))
PLACEBO_SEEDS = list(range(1, 21))
CHAMPION = {"FULL": 544.47, "VALIDATION": 288.05}
SPY_PUBLISHED = {"FULL": 313.62, "VALIDATION": 187.77}
TOP_N = 5
TRAIL_DAYS = 20
MIN_VALID = 15

# ------------------------------------------------------------ champion engine
spec = importlib.util.spec_from_file_location(
    "champion", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
UNIVERSE = list(E.UNIVERSE)


def load_ohlc(ticker):
    """Adjusted OHLC from the champion engine's cached Yahoo payload,
    champion ratio method (adjclose/close applied to O, H, L; close =
    adjclose). Mirrors the engine's cache lookup order."""
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
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if c is None or o is None or h is None or l is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": o * ratio, "h": h * ratio,
                     "l": l * ratio, "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


# ------------------------------------------------------------------ signal
def shadow_score(bars, upto_idx):
    """S = mean(LS) - mean(US) over the trailing TRAIL_DAYS bars ending
    at upto_idx (inclusive), counting only days with R > 0. Returns
    (score, n_valid) or (None, n_valid) if fewer than MIN_VALID valid
    days."""
    lo = max(0, upto_idx - TRAIL_DAYS + 1)
    ls_sum = us_sum = 0.0
    n_valid = 0
    for b in bars[lo:upto_idx + 1]:
        r = b["h"] - b["l"]
        if r <= 0:
            continue
        ls_sum += (min(b["o"], b["c"]) - b["l"]) / r
        us_sum += (b["h"] - max(b["o"], b["c"])) / r
        n_valid += 1
    if n_valid < MIN_VALID:
        return None, n_valid
    return ls_sum / n_valid - us_sum / n_valid, n_valid


# ------------------------------------------------------------------- engine
def run_rotation(bars_by_t, calendar, start, end, picker, label=""):
    """One $100 pot under the N-PV1 monthly full-rotation mechanics.

    picker(signal_date, scores) -> list of tickers to hold next month,
    where scores = {ticker: S} for that month's eligible set (already
    computed by this function; the ranked picker sorts it, the placebo
    picker samples it). Signal days are the last calendar trading day
    of each month inside the window whose next calendar day is also
    inside the window. Targets are 1/5 of the pot's signal-day close
    value per name, executed at the next open: sell everything first,
    then buy (full rotation, no netting — champion cost semantics).
    Floor check on each close (champion semantics); end-of-window
    liquidation at the final close."""
    days = [d for d in calendar if start <= d <= end]
    day_set = set(days)
    idx_of = {t: {b["d"]: i for i, b in enumerate(bl)}
              for t, bl in bars_by_t.items()}
    bar_of = {t: {b["d"]: b for b in bl} for t, bl in bars_by_t.items()}

    # signal days: last trading day of a month, with a next day in-window
    signal_days = set()
    for k, d in enumerate(days[:-1]):
        if days[k + 1][5:7] != d[5:7]:
            signal_days.add(d)

    cash = START_CASH
    positions = {}            # ticker -> shares
    pending = None            # (picks, each_value)
    trades = []
    total_costs = 0.0
    curve = []
    halted = None
    halt_info = None
    end_date = days[-1]
    monthly = []              # per-signal record (ranked runs fill scores)

    def close_value(d):
        v = cash
        for t, sh in positions.items():
            b = None
            bl = bars_by_t[t]
            # close on or before d
            i = idx_of[t].get(d)
            if i is None:
                # last bar <= d
                import bisect
                ds = [x["d"] for x in bl]
                j = bisect.bisect_right(ds, d) - 1
                if j >= 0:
                    b = bl[j]
            else:
                b = bl[i]
            if b:
                v += sh * b["c"]
        return v

    for k, d in enumerate(days):
        # ---- execute pending rotation at today's open
        if pending is not None:
            picks, each = pending
            pending = None
            # sell everything (full rotation, no netting)
            for t in list(positions):
                b = bar_of[t].get(d)
                if not b:
                    continue
                val = positions[t] * b["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((d, t, "SELL", positions[t], b["o"], val, c))
                del positions[t]
            # buy the new top set toward 1/5-pot targets
            for t in picks:
                b = bar_of[t].get(d)
                if not b:
                    continue
                buy_val = min(each, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / b["o"]
                c = buy_val * 0.001
                cash -= buy_val + c
                total_costs += c
                positions[t] = sh
                trades.append((d, t, "BUY", sh, b["o"], buy_val, c))
        # ---- close equity + floor check (champion semantics)
        v = close_value(d)
        curve.append((d, v))
        if v <= FLOOR0 and k < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            nd = days[k + 1]
            for t in list(positions):
                b = bar_of[t].get(nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t],
                                   b["o"], val, c))
            positions = {}
            end_date = nd
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": end_date,
                    "halt_info": halt_info, "curve": curve,
                    "monthly": monthly}
        # ---- signal on today's close (month-end)
        if d in signal_days:
            scores = {}
            for t in UNIVERSE:
                i = idx_of[t].get(d)
                if i is None:
                    continue
                s, nv = shadow_score(bars_by_t[t], i)
                if s is not None:
                    scores[t] = s
            picks = picker(d, scores)
            monthly.append({"signal_date": d,
                            "eligible": len(scores),
                            "scores": {t: round(s, 4)
                                       for t, s in sorted(
                                           scores.items(),
                                           key=lambda kv: -kv[1])},
                            "picks": list(picks)})
            pending = (list(picks), v / TOP_N)
    # end of window: liquidate at final close
    last = days[-1]
    for t in list(positions):
        b = bar_of[t].get(last)
        if b:
            val = positions[t] * b["c"]
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((last, t, "SELL-END", positions[t], b["c"],
                           val, c))
    positions = {}
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": end_date,
            "halt_info": None, "curve": curve, "monthly": monthly}


def ranked_picker(d, scores):
    return sorted(scores, key=lambda t: -scores[t])[:TOP_N]


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
            "n_buys": sum(1 for t in r["trades"] if t[2] == "BUY"),
            "n_sells": sum(1 for t in r["trades"] if t[2].startswith("SELL")),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "year_end_closes": year_end,
            "monthly_signals": r["monthly"],
            "trades": [(t[0], t[1], t[2], round(t[4], 4), round(t[5], 2),
                        round(t[6], 2)) for t in r["trades"]]}


def placebo_block(bars_by_t, calendar, start, end, ranked_final, tag):
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)

        def placebo_picker(d, scores, rng=rng):
            elig = sorted(scores)
            return rng.sample(elig, min(TOP_N, len(elig)))

        pr = run_rotation(bars_by_t, calendar, start, end, placebo_picker,
                          label=f"{tag} PLACEBO {seed}")
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"],
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
    bars_by_t = {}
    for t in UNIVERSE + ["SPY"]:
        bars_by_t[t] = load_ohlc(t)
    calendar = sorted({b["d"] for bl in bars_by_t.values() for b in bl})

    out = {"strategy": "NOVEL N-PV1 THE STANDING BID (rejected-excursion / "
                       "shadow-share monthly top-5 sort), $100, plain "
                       "-15% floor",
           "spec_source": "research/v8-novel/novel-price-volume.md, "
                          "Rule N-PV1",
           "invented_rule_context": "1 of 12 invented rules (v8 novel "
                                    "track); best possible verdict is "
                                    "CANDIDATE — only a forward paper "
                                    "trial can promote an invented rule",
           "pot": START_CASH, "floor": FLOOR0}

    # ---- integrity: adjusted O/C must equal the champion engine's bars
    # for every name, and spy_net must reproduce the published figures.
    total_mism = 0
    per_ticker = {}
    for t in UNIVERSE + ["SPY"]:
        eng = E.get_prices(t)
        mine = {b["d"]: b for b in bars_by_t[t]}
        mism = 0
        for eb in eng:
            mb = mine.get(eb["d"])
            if mb is None or abs(mb["o"] - eb["o"]) > 1e-9 or \
                    abs(mb["c"] - eb["c"]) > 1e-9:
                mism += 1
        per_ticker[t] = {"engine_bars": len(eng), "mismatches": mism}
        total_mism += mism
    out["integrity_bars_match"] = {"per_ticker": per_ticker,
                                   "total_mismatches": total_mism}
    print(f"BAR INTEGRITY: total mismatches={total_mism} across "
          f"{len(per_ticker)} tickers", flush=True)
    if total_mism:
        raise SystemExit("BAR MISMATCH — variant numbers untrusted")
    pb = E.PriceBook({t: E.get_prices(t) for t in UNIVERSE + ["SPY"]})
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

    # ---- ranked runs + placebo
    for tag, ws, we in WINDOWS:
        spy, spy_costs = E.spy_net(pb, ws, we, START_CASH)
        r = run_rotation(bars_by_t, calendar, ws, we, ranked_picker,
                         label=f"{tag} N-PV1")
        st = curve_stats(r)
        st.update({"start": ws, "end": we,
                   "spy_net_final": round(spy, 2),
                   "spy_costs": round(spy_costs, 2),
                   "spy_return_pct": round(spy / START_CASH * 100 - 100, 2),
                   "champion_final": CHAMPION[tag]})
        print(f"{tag} N-PV1 STANDING BID: final=${r['final']:,.2f} "
              f"({st['return_pct']:+.2f}%) trades={st['n_trades']} "
              f"costs=${st['costs']} maxDD={st['max_drawdown_pct']}% "
              f"halted={r['halted']} | SPY=${spy:,.2f}", flush=True)
        st["placebo"] = placebo_block(bars_by_t, calendar, ws, we,
                                      r["final"], tag)
        pl = st["placebo"]
        print(f"{tag} PLACEBO: median=${pl['median']:,.2f} "
              f"best=${pl['best']:,.2f} worst=${pl['worst']:,.2f} "
              f"halted={pl['halted_count']}/20 | RANKED "
              f"${pl['ranked_final']:,.2f} = {pl['ranked_percentile']}th "
              f"pctile (beat {pl['seeds_beaten']}/20)", flush=True)
        out[tag.lower()] = st

    val, full = out["validation"], out["full"]
    gates = {
        "validation_beats_spy": val["final"] > SPY_PUBLISHED["VALIDATION"],
        "validation_placebo_20_of_20":
            val["placebo"]["seeds_beaten"] == 20,
        "continuous_beats_spy": full["final"] > SPY_PUBLISHED["FULL"],
        "no_floor_halt_either_window":
            val["halted"] is None and full["halted"] is None}
    out["candidate_gates"] = gates
    out["verdict"] = "CANDIDATE" if all(gates.values()) \
        else "NOT A CANDIDATE"
    print(f"CANDIDATE GATES: {gates} -> {out['verdict']}", flush=True)

    with open(os.path.join(HERE, "novel-pv1-standing-bid-results.json"),
              "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
