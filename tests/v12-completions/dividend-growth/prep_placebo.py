#!/usr/bin/env python3
"""One-time prep: PIT pools + placebo price matrix (float32 .npy) aligned to SPY calendar."""
import bisect, csv, json, os, sys
from datetime import date
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)
STALE_DAYS = 45
END = "2026-11-20"

def load_bars(t):
    j = json.load(open(os.path.join(DATA, f"px_{t}.json")))
    bars = [(b[0][:10], float(b[1])) for b in j["bars"]]
    bars.sort()
    return bars

SPY_BARS = load_bars("SPY")
CAL = [d for d, _ in SPY_BARS if d <= END]
CAL_ORD = np.array([date.fromisoformat(d).toordinal() for d in CAL])
N = len(CAL)

PIT = []
with open(os.path.join(DATA, "sp500_hist.csv")) as f:
    for row in csv.DictReader(f):
        PIT.append((row["date"], row["tickers"].split(",")))
PIT_DATES = [d for d, _ in PIT]

def pit_members(d):
    i = bisect.bisect_right(PIT_DATES, d) - 1
    return PIT[i][1]

def last_td_of_month(y, m):
    ds = [d for d in CAL if d[:4] == str(y) and d[5:7] == f"{m:02d}"]
    return ds[-1] if ds else None

pool_names = set()
for y in range(2010, 2027):
    pool_names.update(pit_members(last_td_of_month(y, 1)))
pool_names = sorted(pool_names)
print("pool names:", len(pool_names), flush=True)

import duckdb
con = duckdb.connect()
rows = {}
B = 100
for s in range(0, len(pool_names), B):
    batch = pool_names[s:s + B]
    df = con.sql(
        "SELECT ticker, CAST(date AS DATE) d, adj_close FROM read_parquet(?) "
        "WHERE ticker IN (SELECT UNNEST(?)) AND adj_close IS NOT NULL "
        "AND date >= DATE '2009-01-01' ORDER BY ticker, date",
        params=[os.path.join(DATA, "prices_jb.parquet"), batch]).df()
    for t, grp in df.groupby("ticker"):
        rows[t] = (grp["d"].astype(str).tolist(), grp["adj_close"].astype(float).tolist())
    del df
    print("batch", s, "done, tapes:", len(rows), flush=True)

tickers = sorted(rows)
mat = np.full((len(tickers), N), np.nan, dtype=np.float32)
for r, t in enumerate(tickers):
    ds, ps = rows[t]
    bd = np.array([date.fromisoformat(d).toordinal() for d in ds])
    j = np.searchsorted(bd, CAL_ORD, side="right") - 1
    for i in range(N):
        k = j[i]
        if k >= 0 and CAL_ORD[i] - bd[k] <= STALE_DAYS:
            mat[r, i] = ps[k]
        elif k >= 0:
            mat[r, i] = 0.0
np.save(os.path.join(DATA, "placebo_matrix.npy"), mat)
json.dump({"tickers": tickers, "cal": CAL}, open(os.path.join(DATA, "placebo_index.json"), "w"))
pools = {}
idx = {t: i for i, t in enumerate(tickers)}
for y in range(2010, 2027):
    fd = last_td_of_month(y, 1)
    ci = CAL.index(fd)
    ok = []
    for t in pit_members(fd):
        cand = t if t in idx else t.replace(".", "-")
        if cand in idx and not np.isnan(mat[idx[cand], ci]) and mat[idx[cand], ci] > 0:
            ok.append(cand)
    pools[str(y)] = ok
json.dump(pools, open(os.path.join(DATA, "pools.json"), "w"))
print("saved matrix", mat.shape, "pools:", {y: len(v) for y, v in pools.items()})
