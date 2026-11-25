#!/usr/bin/env python3
"""v12 value-momentum-ey orchestrator: (1) finish any missing/truncated
Yahoo price payloads sequentially (direct write, verified parse);
(2) DECADE cadence grid; (3) confirmation roads for money cadences
(final > SPY and placebo_beaten > 10, per the frozen spec); (4) period
record at the native quarterly tempo from the DECADE quarterly curve;
(5) finalize results.json. Resumable: every stage skips saved artifacts.
"""
import json, os, sys, time, urllib.request, urllib.parse, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)


def fix_prices():
    seed = json.load(open(os.path.join(DATA, "tradable_universe.json")))
    tickers = sorted({v["ticker"] for v in seed["tradable"].values()}) + ["SPY"]
    p1 = int(datetime.datetime(2008, 1, 1, tzinfo=datetime.timezone.utc).timestamp())
    p2 = int(datetime.datetime(2026, 11, 22, tzinfo=datetime.timezone.utc).timestamp())
    todo = [t for t in tickers
            if not (os.path.exists(os.path.join(DATA, f"pxfull_{t}.json"))
                    and os.path.getsize(os.path.join(DATA, f"pxfull_{t}.json")) > 1000)]
    print(f"price fix: {len(todo)} to fetch", flush=True)
    fails = []
    for i, t in enumerate(todo):
        u = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
             "?period1=%d&period2=%d&interval=1d&events=div,split"
             % (urllib.parse.quote(t), p1, p2))
        ok = False
        for attempt in range(3):
            try:
                r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                blob = urllib.request.urlopen(r, timeout=30).read()
                d = json.loads(blob)
                if not d["chart"]["result"]:
                    raise ValueError("empty result")
                path = os.path.join(DATA, f"pxfull_{t}.json")
                if os.path.exists(path):
                    os.unlink(path)
                with open(path, "wb") as f:
                    f.write(blob)
                if os.path.getsize(path) != len(blob):
                    raise IOError("short write")
                ok = True
                break
            except Exception as e:
                print(f"  {t} attempt {attempt}: {e}", flush=True)
                time.sleep(3 * (attempt + 1))
        if not ok:
            fails.append(t)
        if (i + 1) % 50 == 0:
            print(f"  price fix {i + 1}/{len(todo)}", flush=True)
    print(f"price fix done, fails={fails}", flush=True)
    return fails


def period_record(curve, cadence_label):
    """Period-by-period record at the strategy's native tempo (quarterly):
    resample the daily curve to calendar-quarter ends."""
    import statistics
    q = {}
    for d, v in curve:
        key = (int(d[:4]), (int(d[5:7]) - 1) // 3)
        q[key] = (d, v)
    keys = sorted(q)
    vals = [q[k][1] for k in keys]
    rets = []
    for a, b in zip(vals, vals[1:]):
        if a > 0:
            rets.append(b / a - 1.0)
    if not rets:
        return {}
    win = sum(1 for r in rets if r > 0)
    longest_loss = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        longest_loss = max(longest_loss, cur)
    # longest stretch between new highs (in periods, on quarter-end values)
    peak = -1.0
    last_high_i = 0
    longest_gap = 0
    for i, v in enumerate(vals):
        if v >= peak:
            peak = v
            longest_gap = max(longest_gap, i - last_high_i)
            last_high_i = i
    longest_gap = max(longest_gap, len(vals) - 1 - last_high_i)
    return {
        "tempo": cadence_label,
        "n_periods": len(rets),
        "periods_made_money": win,
        "share_made_money_pct": round(100.0 * win / len(rets), 1),
        "median_period_pct": round(100.0 * statistics.median(rets), 2),
        "best_period_pct": round(100.0 * max(rets), 2),
        "worst_period_pct": round(100.0 * min(rets), 2),
        "longest_losing_streak_periods": longest_loss,
        "longest_stretch_between_new_highs_periods": longest_gap,
        "mean_period_pct_secondary_average": round(100.0 * statistics.mean(rets), 2),
    }


def main():
    fails = fix_prices()
    import run_v12 as R
    pb, scorer, tickers, missing_px = R.build_world()
    print(f"world tickers={len(tickers)} missing_px={len(missing_px)}", flush=True)

    # ---- grid (skip cadences whose cell file already exists and parses)
    summary = {}
    money = []
    for cadence in R.CADENCES:
        cell_path = os.path.join(R.CELLS, f"{cadence}.json")
        cell = None
        if os.path.exists(cell_path) and os.path.getsize(cell_path) > 1000:
            try:
                cell = json.load(open(cell_path))
            except Exception:
                cell = None
        if cell is None:
            cell = R.run_cell(pb, scorer, "DECADE", cadence)
            with open(cell_path, "w") as f:
                json.dump(cell, f, indent=1)
        summary[cadence] = cell
        print(f"DECADE {cadence}: ${cell['final']} spy ${cell['spy_final']} "
              f"placebo {cell['placebo_beaten']}/20", flush=True)
        if cell["final"] > cell["spy_final"] and (cell["placebo_beaten"] or 0) > 10:
            money.append(cadence)
    print("money cadences:", money, flush=True)

    # ---- confirmation for money cadences
    for cadence in money:
        for road in ("LONG", "CONT", "VAL"):
            cp = os.path.join(R.CONF, f"{road.lower()}-{cadence}.json")
            if os.path.exists(cp) and os.path.getsize(cp) > 1000:
                try:
                    json.load(open(cp))
                    print(f"confirm {road} {cadence}: already saved", flush=True)
                    continue
                except Exception:
                    pass
            cell = R.run_cell(pb, scorer, road, cadence)
            with open(cp, "w") as f:
                json.dump(cell, f, indent=1)
            print(f"confirm {road} {cadence}: ${cell['final']} spy "
                  f"${cell['spy_final']} placebo {cell['placebo_beaten']}/20",
                  flush=True)

    # ---- period record at native tempo (quarterly), DECADE curve
    qc = summary.get("quarterly")
    if qc:
        rec = period_record(qc["equity_curve"], "quarterly (native)")
        json.dump(rec, open(os.path.join(HERE, "period_record.json"), "w"), indent=1)
        print("period record:", rec, flush=True)

    # ---- finalize
    import finalize  # noqa: F401  (writes results.json on import? no - it runs at import)
    print("RUN_ALL DONE", flush=True)


if __name__ == "__main__":
    main()
