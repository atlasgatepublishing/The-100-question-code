"""Cloning-13F NATIVE run (v11): quarterly, each tracked manager's rank-1 disclosed holding,
freshest filing filed strictly before selection date, equal weight, NO floor/stop.
Picks parsed (read-only) from v10-retest cloning-13f data."""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
import shutil; shutil.copy("/tmp/w07/native_lib.py", os.path.join(os.path.dirname(__file__), "native_lib.py"))
from native_lib import get_bars, spy_calendar
import pandas as pd, numpy as np

HERE = os.path.dirname(__file__)
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/cloning-13f/data")

def main():
    picks = json.load(open(os.path.join(DATA, "picks_raw.json")))
    cusip = json.load(open(os.path.join(DATA, "cusip_map.json")))
    spy = spy_calendar(HERE)
    dates = sorted(picks.keys())
    # selection dates are quarterly keys already point-in-time (filing filed before date) in the harvest
    cash = 100.0; holdings = {}  # ticker -> shares
    curve = []; costs = 0.0; orders = 0; sel_idx = 0
    cal = list(spy.loc["2019-01-02":"2026-11-20"].index)
    sel_dates = [pd.Timestamp(d) for d in dates]
    def price(t, d, field="close"):
        df = get_bars(t, HERE)
        if df is None: return None
        v = df[field].asof(d)
        return float(v) if v and v == v else None
    for d in cal:
        if d in sel_dates:
            # sell all at open-ish (close used for both legs, cost applied)
            eq = cash + sum(sh * (price(t, d) or 0) for t, sh in holdings.items())
            new = {}
            for cik, info in picks[str(d.date())].items():
                r1 = info.get("rank1") or {}
                m = cusip.get(r1.get("cusip", ""), {})
                if m.get("ticker"): new[m["ticker"]] = new.get(m["ticker"], 0) + 1
            cash = eq; holdings = {}
            if new:
                per_name = eq / len(new)
                for t, cnt in new.items():
                    amt = per_name * cnt / sum(new.values()) * len(new) / len(new)  # equal per manager slot
                    amt = eq * cnt / sum(new.values())
                    p = price(t, d)
                    if not p: cash -= 0; continue
                    spend = min(amt, cash); cr = spend * 0.001; costs += cr; orders += 1
                    holdings[t] = holdings.get(t, 0) + (spend - cr) / p; cash -= spend
        eq = cash + sum(sh * (price(t, d) or 0) for t, sh in holdings.items())
        curve.append((str(d.date()), round(eq, 4)))
    vals = [v for _, v in curve]; peak = -1; maxdd = 0
    for v in vals:
        peak = max(peak, v); maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0)
    # validation fold: restart curve at 2023-01-03 value ratio
    v0 = dict(curve)
    start23 = [v for dt, v in curve if dt >= "2023-01-03"][0]
    final = vals[-1]
    out = {"family": "cloning-13f", "final_2019_2026": final, "max_dd_pct": round(maxdd * 100, 2),
           "costs": round(costs, 2), "orders": orders, "curve": curve,
           "validation_ratio_2023_to_end": round(final / start23, 4),
           "validation_final_on_100": round(100 * final / start23, 2),
           "spy_2019_2026": 313.62, "spy_validation": 187.77,
           "crosscheck_v10_quarterly_with_floor_never_fired": 344.56}
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "curve"}, indent=1))

if __name__ == "__main__": main()
