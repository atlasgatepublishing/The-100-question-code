#!/usr/bin/env python3
"""
MOMENTUM BASKET — longest honest run.

The basket needs no filings at all: its signal is prices only (own
close above its own 200-day average; 12-1 momentum), so its earliest
honest start is set purely by price history — it needs 252 prior
trading days of prices before its first selection. The price pulls
begin 2008-01-02, so at a 2010-01-04 start the signal day (2009-12-31)
has ~500 prior bars: coverage is measured and printed below, and the
run starts 2010-01-04 on the same point-in-time 2010 pond as the
champion. Its v9 protection is inside its own engine (see lr_basket).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lr_common as C  # noqa: E402
import lr_basket as B  # noqa: E402
import lr_engines as E  # noqa: E402

START, END = "2010-01-04", C.END

P = E.pool_data()
pond = E.pond_at(START)["pond"]
print(f"pond: {pond}", flush=True)

# coverage at the first signal day (prior trading day to the start)
raw = {t: C.bars_raw(P["payload_by"][t]) for t in pond}
raw["SPY"] = C.bars_raw(P["payload_by"]["SPY"])
mkt = B.Market(raw)
i0 = next(i for i, d in enumerate(mkt.cal) if d >= START)
j = i0 - 1
elig = []
for t in pond:
    sma = mkt.sma(t, j, 200)
    mom = mkt.momentum_12_1(t, j)
    c = mkt.close_px(t, j)
    if sma is not None and mom is not None and c is not None:
        elig.append(t)
print(f"signal day {mkt.cal[j]}: momentum+SMA computable for "
      f"{len(elig)}/{len(pond)} pond names", flush=True)

res = E.basket_v9(pond, START, END)
print(f"BASKET v9: final ${res['final']:,.2f} halts={res['halts']} "
      f"restart={res['restart']} spy=${res['spy_final']:,.2f}",
      flush=True)
out = {"coverage": {"signal_day": mkt.cal[j],
                    "computable": len(elig), "of": len(pond),
                    "names": elig},
       "pond": pond, "run": res}
with open(os.path.join(HERE, "results_basket.json"), "w") as f:
    json.dump(out, f, indent=1, default=str)
print("saved results_basket.json", flush=True)
