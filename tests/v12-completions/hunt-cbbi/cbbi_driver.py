#!/usr/bin/env python3
"""Driver for the VENDORED CBBI code (github.com/Zaczero/CBBI).
Vendored at commit 31e4b869d1ecd425040885b820cb75e39a879299 (HEAD of the
clone taken 2026-11-22; the first commit on or before 2026-11-22).
No parameter adjusted. Each metric is computed by the code's own class;
a metric that raises is logged and dropped — the Confidence is the code's
own mean_horizontal over the available metric columns (main.py line ~207),
exactly the code's averaging-over-available behavior.
Run with the venv python: /tmp/cbbenv/bin/python cbbi_driver.py
The vendored tree lives in this folder at vendored-CBBI/ (durable record);
this driver + the output cbbi_series.json sit beside it."""
import json, os, sys, traceback
HERE0 = os.path.dirname(os.path.abspath(__file__))
VEND = os.path.join(HERE0, "vendored-CBBI")
sys.path.insert(0, os.path.join(HERE0, "shim"))
sys.path.insert(0, VEND)
os.chdir(VEND)
import polars as pl
from fetch_bitcoin_data import fetch_bitcoin_data
# metric list replicated from main.get_metrics() (importing main.py itself
# would drag in its plotting stack; the metric classes are the algorithm)
from metrics.mvrv_z_score import MVRVMetric
from metrics.pi_cycle import PiCycleMetric
from metrics.puell_multiple import PuellMetric
from metrics.reserve_risk import ReserveRiskMetric
from metrics.rhodl_ratio import RHODLMetric
from metrics.rupl import RUPLMetric
from metrics.trolololo import TrolololoMetric
from metrics.two_year_moving_average import TwoYearMovingAverageMetric
from metrics.woobull_topcap_cvdd import WoobullMetric

def get_metrics():
    return [PiCycleMetric(), RUPLMetric(), RHODLMetric(), PuellMetric(),
            TwoYearMovingAverageMetric(), TrolololoMetric(), MVRVMetric(),
            ReserveRiskMetric(), WoobullMetric()]

HERE = HERE0

def main():
    df = fetch_bitcoin_data()
    avail = {}
    cols = []
    import asyncio
    from matplotlib.axes import Axes
    for m in get_metrics():
        name = type(m).__name__
        try:
            series = asyncio.run(m.calculate(df, [Axes(), Axes()]))
            col = m.name
            df = df.with_columns(series.alias(col))
            avail[name] = f"OK nonnull={series.drop_nulls().len()}"
            cols.append(col)
        except Exception as e:
            avail[name] = f"FAILED: {type(e).__name__}: {e}"
            traceback.print_exc()
    print(json.dumps(avail, indent=1))
    if not cols:
        json.dump({"status": "NO_METRICS_COMPUTED", "availability": avail},
                  open(os.path.join(HERE, "cbbi_series.json"), "w"), indent=1)
        return
    df = df.with_columns(Confidence=pl.mean_horizontal([pl.col(c).fill_nan(None) for c in cols]))
    dates = df.get_column("Date").dt.strftime("%Y-%m-%d").to_list()
    conf = df.get_column("Confidence").to_list()
    price = df.get_column("Price").to_list()
    series = {d: {"cbbi": (None if c is None else round(float(c) * 100, 3)), "price": float(p)}
              for d, c, p in zip(dates, conf, price)}
    json.dump({"commit": "31e4b869d1ecd425040885b820cb75e39a879299", "availability": avail,
               "metric_columns": cols, "series": series},
              open(os.path.join(HERE, "cbbi_series.json"), "w"), indent=1)
    print("series days:", len(series), "first:", min(series), "last:", max(series))

if __name__ == "__main__": main()
