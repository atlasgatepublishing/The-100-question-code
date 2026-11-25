#!/usr/bin/env python3
"""
V12 COMPLETIONS -- lottery (penny-stock lottery pot, listed form).

Implements CONSTRUCTION-SPEC.md exactly as frozen: the v10-retest
headline configuration E4+N3 (Terry's documented pot design) at its
native daily cadence, run on the program roads v10 did not run
(LONG 2010->2026, CONT 2019->2026, VAL 2023->2026) plus DECADE
re-run on the fresh cache as an integrity cross-check against v10's
published daily cell ($67.05, 0/20 placebos).

The simulation engine is NOT re-implemented: this script imports the
v10-retest lottery module (backtests/v10-retest/lottery/run_v10.py,
read-only) and calls its Store / screen_for_month / cadence_dates /
simulate_cadence / stats_of unchanged. Only the data fetch differs:
a fresh Yahoo chart-API pull (2009-11-01 -> 2026-11-22, so the first
monthly screens have their trailing 20 days) into THIS folder's
data_cache/. Same source, same fields, split-adjusted, not
dividend-adjusted, as v10.

Placebos: 20 seeded random-rank twins per road (seeds 1..20), the
v10 definition -- identical screens, eligibility, sizing, caps,
exits, costs and floor; only the ranking is random.

Outputs: results.json (per-road summaries, placebo finals, equity
curves, trades). RESULTS.md is written by hand from results.json.
"""

import importlib.util
import json
import os
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data_cache")
os.makedirs(CACHE, exist_ok=True)

V10_PATH = os.path.join(
    HERE, "..", "..", "v10-retest", "lottery", "run_v10.py")
spec = importlib.util.spec_from_file_location("lottery_v10", V10_PATH)
v10 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v10)

ET = ZoneInfo("America/New_York")
FETCH_START = datetime(2009, 11, 1, tzinfo=timezone.utc)
FETCH_END = datetime(2026, 11, 22, tzinfo=timezone.utc)

ROADS = {
    "LONG":   ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-02", "2026-11-20"),
    "VAL":    ("2023-01-03", "2026-11-20"),
}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
V10_DECADE_PUBLISHED = {"final": 67.05, "placebo_beaten": 0}


def fetch_chart(symbol):
    path = os.path.join(CACHE, f"{symbol}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    p1 = int(FETCH_START.timestamp())
    p2 = int(FETCH_END.timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={p1}&period2={p2}&interval=1d")
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    with open(path, "w") as f:
        json.dump(data, f)
    time.sleep(0.25)
    return data


def parse_bars(symbol):
    data = fetch_chart(symbol)
    result = data.get("chart", {}).get("result")
    if not result:
        return {}, {}
    r = result[0]
    meta = r.get("meta", {})
    ts = r.get("timestamp", []) or []
    q = r.get("indicators", {}).get("quote", [{}])[0]
    bars = {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, tz=ET).strftime("%Y-%m-%d")
        try:
            bar = {"open": q["open"][i], "high": q["high"][i],
                   "low": q["low"][i], "close": q["close"][i],
                   "volume": q["volume"][i]}
        except (KeyError, IndexError, TypeError):
            continue
        if None in bar.values():
            continue
        bars[d] = bar
    return meta, bars


def main():
    all_bars, all_meta, failed = {}, {}, []
    for sym in v10.CANDIDATES + ["SPY"]:
        try:
            meta, bars = parse_bars(sym)
        except Exception as e:
            meta, bars = {}, {}
            failed.append(sym)
            print(f"FETCH FAIL {sym}: {e}")
        all_meta[sym], all_bars[sym] = meta, bars
        if not bars and sym not in failed:
            failed.append(sym)
    print(f"data: failed={sorted(set(failed))}")
    store = v10.Store(all_bars)
    all_days = sorted(all_bars["SPY"].keys())

    # Monthly PIT screens across the whole span (v10 function, unchanged)
    months = v10.run_months("2009-12", "2026-11")
    universes = {}
    for mk in months:
        _, passed = v10.screen_for_month(mk, all_days, store, all_meta)
        universes[mk] = passed

    roads_out = {}
    for road, (start, end) in ROADS.items():
        run_days = [d for d in all_days if start <= d <= end]
        span_days = (datetime.strptime(end, "%Y-%m-%d")
                     - datetime.strptime(start, "%Y-%m-%d")).days
        cad_set = v10.cadence_dates("daily", run_days)
        res = v10.simulate_cadence(store, all_days, run_days, universes,
                                   cad_set, "N3")
        st = v10.stats_of(res, span_days)
        placebo_finals = []
        for seed in range(1, 21):
            pres = v10.simulate_cadence(store, all_days, run_days,
                                        universes, cad_set, "RANDOM",
                                        seed=seed)
            placebo_finals.append(round(pres["final_balance"], 2))
        beaten = sum(1 for f in placebo_finals if st["final"] > f)
        cell = {
            "road": road, "window": [start, end],
            "config": "E4+N3 (frozen v10 headline), daily cadence",
            "final": st["final"], "cagr_pct": st["cagr_pct"],
            "max_dd_pct": st["max_dd_pct"], "costs": st["costs"],
            "spread_costs": st["spread_costs"],
            "fee_costs": st["fee_costs"],
            "orders": st["orders"], "round_trips": st["round_trips"],
            "win_rate_pct": st["win_rate_pct"],
            "gap_through_stops": st["gap_through_stops"],
            "halts": res["halt_events"], "restarts": res["restarts"],
            "spy_buyhold_ref": SPY_REF[road],
            "champion_vm": CHAMPION[road],
            "placebo_beaten": beaten,
            "placebo_finals": placebo_finals,
            "equity_curve": [[d, v] for d, v in res["daily"]],
            "trades": res["trades"],
        }
        roads_out[road] = cell
        print(f"ROAD {road}: final ${st['final']:.2f} CAGR "
              f"{st['cagr_pct']:+.2f}% DD {st['max_dd_pct']:.2f}% "
              f"costs ${st['costs']:.2f} orders {st['orders']} "
              f"halts {len(res['halt_events'])} placebo {beaten}/20")

    dec = roads_out["DECADE"]
    integrity = {
        "check": "DECADE daily re-run on fresh 2009->2026 cache vs "
                 "v10 published daily cell",
        "v10_published_final": V10_DECADE_PUBLISHED["final"],
        "v12_rerun_final": dec["final"],
        "v10_published_placebo_beaten": V10_DECADE_PUBLISHED["placebo_beaten"],
        "v12_rerun_placebo_beaten": dec["placebo_beaten"],
        "match": (abs(dec["final"] - V10_DECADE_PUBLISHED["final"]) < 0.005
                  and dec["placebo_beaten"]
                  == V10_DECADE_PUBLISHED["placebo_beaten"]),
    }
    print(f"INTEGRITY DECADE: v12 ${dec['final']:.2f} vs v10 "
          f"${V10_DECADE_PUBLISHED['final']:.2f} -> "
          f"{'MATCH' if integrity['match'] else 'DIFFERS (reported, not patched)'}")

    results = {
        "slug": "lottery",
        "family": "Penny-stock lottery pot, listed form (CONSTRUCTED "
                  "stand-in for the unbuildable OTC native habitat)",
        "spec": "CONSTRUCTION-SPEC.md (frozen 2026-11-22 before any run)",
        "hunt": "HUNT-LOG.md -- no free PIT OTC archive incl. the dead "
                "exists for any program road; OTC habitat closed with "
                "the exact missing archive named (OTC Markets Group "
                "historical EOD file, paid licence).",
        "engine": "v10-retest lottery module imported unchanged "
                  "(screen/rank/simulate/stats); fresh Yahoo cache in "
                  "this folder, 2009-11-01 -> 2026-11-22.",
        "failed_symbols": sorted(set(failed)),
        "integrity_decade_crosscheck": integrity,
        "roads": roads_out,
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("Wrote results.json")


if __name__ == "__main__":
    main()
