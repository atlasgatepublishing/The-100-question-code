#!/usr/bin/env python3
"""Transport-accelerated fetch. Primary per-symbol files come from the
Hugging Face mirror of the SAME Binance Vision archive (one parquet per
symbol instead of 164 monthly zips). VERIFIED against exchange-original
files already on disk in the sibling crypto-funding-basis folder before
use (see verify step below). Symbols ABSENT from the mirror are the
delisted ones (the mirror only carries currently-trading contracts) --
those fall back to the exchange's own monthly zips via fetch_data.py's
parts, assembled here. Output CSVs are identical in format either way."""
import io, os, zipfile, json, sys
from concurrent.futures import ThreadPoolExecutor
import requests
import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
PARTS = os.path.join(ROOT, "parts")
HF = "https://huggingface.co/datasets/linxy/USDT-M_Perpetual_Futures/resolve/main"
SNAP = "/home/hatch/workspace/stock-app/backtests/v12-completions/crypto-basket-pit/data/weekly_snapshots.json"
EXCLUDE = {"USDT","USDC","DAI","BUSD","TUSD","UST","USD1","USDE","WBTC"}
MAP = {"SHIB": "1000SHIBUSDT", "PEPE": "1000PEPEUSDT", "MIOTA": "IOTAUSDT"}

snaps = json.load(open(SNAP))
pit_syms = set()
for d, v in snaps.items():
    if d < "2020-01-01": continue
    for c in v["top20"]: pit_syms.add(c["symbol"])
COINS = {}
for s in sorted(pit_syms - EXCLUDE):
    COINS[MAP.get(s, s + "USDT")] = s
print("candidates:", len(COINS), flush=True)

# ---- verification: HF BTC funding vs exchange-original sibling file ----
sib = "/home/hatch/workspace/stock-app/backtests/v12-completions/crypto-funding-basis/data/BTCUSDT_funding.csv"
orig = pd.read_csv(sib)
r = requests.get(f"{HF}/BTCUSDT/BTCUSDT_fundingRate.parquet", timeout=120)
assert r.status_code == 200, r.status_code
hf = pd.read_parquet(io.BytesIO(r.content))
print("HF BTC funding cols:", list(hf.columns), "rows", len(hf), flush=True)
hf = hf.sort_values("calc_time").reset_index(drop=True)
orig["t"] = pd.to_datetime(orig["calc_time"], unit="ms").dt.floor("s")
hf["t"] = hf["calc_time"].dt.floor("s")
_m = pd.merge(orig, hf, on="t", suffixes=("_o", "_h"), how="inner")
same_rate = (_m["last_funding_rate_o"] == _m["last_funding_rate_h"]).mean()
print(f"VERIFY BTC funding vs exchange original: {len(_m)} matched timestamps, rate match {same_rate:.4f}", flush=True)
assert len(_m) > 7000 and same_rate > 0.999, "HF mirror does not match exchange original -- abort"

MONTHS = []
y, m = 2020, 1
while (y, m) <= (2026, 10):
    MONTHS.append(f"{y:04d}-{m:02d}"); m += 1
    if m == 13: y, m = y + 1, 1
BASE = "https://data.binance.vision/data/futures/um/monthly"

def vision_month(kind, coin, mo):
    part = os.path.join(PARTS, f"{coin}_{kind}_{mo}.csv")
    if os.path.exists(part): return open(part).read()
    if os.path.exists(part + ".404"): return None
    url = (f"{BASE}/fundingRate/{coin}/{coin}-fundingRate-{mo}.zip" if kind == "fundingRate"
           else f"{BASE}/klines/{coin}/1d/{coin}-1d-{mo}.zip")
    try: r = requests.get(url, timeout=60)
    except Exception: return None
    if r.status_code != 200:
        open(part + ".404", "w").write(""); return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    text = z.read(z.namelist()[0]).decode()
    lines = text.strip().splitlines()
    if lines and (lines[0].startswith("calc_time") or lines[0].startswith("open_time")):
        lines = lines[1:]
    if kind == "klines": lines = [",".join(ln.split(",")[:6]) for ln in lines]
    open(part, "w").write("\n".join(lines) + "\n")
    return "\n".join(lines) + "\n"

def write_df(df, cols, path):
    # NOTE: pandas to_csv direct-to-file hits a sandbox EPERM in this VM;
    # writing the in-memory string via plain open() works (same pattern as fetch_data.py).
    with open(path, "w") as fh:
        fh.write(df[cols].to_csv(index=False))

def fetch_symbol(perp):
    out_f = os.path.join(ROOT, f"{perp}_funding.csv")
    out_k = os.path.join(ROOT, f"{perp}_klines1d.csv")
    if (os.path.exists(out_f) and os.path.getsize(out_f) > 100
            and os.path.exists(out_k) and os.path.getsize(out_k) > 100):
        return perp, "cached", None
    # try HF
    try:
        rf = requests.get(f"{HF}/{perp}/{perp}_fundingRate.parquet", timeout=120)
        rk = requests.get(f"{HF}/{perp}/{perp}_1d.parquet", timeout=120)
    except Exception as e:
        rf = rk = None
    if rf is not None and rf.status_code == 200 and rk.status_code == 200:
        f = pd.read_parquet(io.BytesIO(rf.content)).sort_values("calc_time").copy()
        k = pd.read_parquet(io.BytesIO(rk.content)).sort_values("open_time").copy()
        # HF timestamps arrive as datetime64; normalize to epoch ms like the Vision CSVs
        f["calc_time"] = (f["calc_time"].astype("int64") // 10**6)
        k["open_time"] = (k["open_time"].astype("int64") // 10**6)
        # top-up: HF mirror lags Vision by ~2 months -- append Vision months after HF's last
        fmax, kmax = int(f["calc_time"].max()), int(k["open_time"].max())
        start_mo = str(pd.to_datetime(fmax, unit="ms", utc=True).strftime("%Y-%m"))
        extra_f, extra_k = [], []
        for mo in MONTHS[MONTHS.index(start_mo):]:
            t = vision_month("fundingRate", perp, mo)
            if t: extra_f.append(t)
            t = vision_month("klines", perp, mo)
            if t: extra_k.append(t)
        if extra_f:
            ef = pd.read_csv(io.StringIO("calc_time,funding_interval_hours,last_funding_rate\n" + "".join(extra_f)))
            f = pd.concat([f[["calc_time", "funding_interval_hours", "last_funding_rate"]],
                           ef[ef["calc_time"] > fmax]], ignore_index=True)
        if extra_k:
            ek = pd.read_csv(io.StringIO("open_time,open,high,low,close,volume\n" + "".join(extra_k)))
            k = pd.concat([k[["open_time", "open", "high", "low", "close", "volume"]],
                           ek[ek["open_time"] > kmax]], ignore_index=True)
        f = f.drop_duplicates("calc_time").sort_values("calc_time")
        k = k.drop_duplicates("open_time").sort_values("open_time")
        write_df(f, ["calc_time", "funding_interval_hours", "last_funding_rate"], out_f)
        write_df(k, ["open_time", "open", "high", "low", "close", "volume"], out_k)
        span = (str(pd.to_datetime(f["calc_time"].iloc[0], unit="ms", utc=True).date()),
                str(pd.to_datetime(f["calc_time"].iloc[-1], unit="ms", utc=True).date()))
        return perp, "hf+vision-topup", span
    # fallback: exchange monthly zips (delisted symbols)
    flines, klines = [], []
    for mo in MONTHS:
        t = vision_month("fundingRate", perp, mo)
        if t: flines.append(t)
        t = vision_month("klines", perp, mo)
        if t: klines.append(t)
    if not flines:
        return perp, "absent", None
    with open(out_f, "w") as fh:
        fh.write("calc_time,funding_interval_hours,last_funding_rate\n"); fh.write("".join(flines))
    with open(out_k, "w") as fh:
        fh.write("open_time,open,high,low,close,volume\n"); fh.write("".join(klines))
    return perp, "vision-fallback", (len(flines), len(klines))

spans = {}
with ThreadPoolExecutor(max_workers=6) as ex:
    for perp, how, span in ex.map(fetch_symbol, sorted(COINS)):
        spans[perp] = {"cmc": COINS[perp], "source": how, "span": span}
        print(perp, COINS[perp], how, span, flush=True)
# spans.json in the shape run_carry.py expects (funding_months>0 = has data)
sp2 = {}
for perp, s in spans.items():
    has = s["source"] in ("hf+vision-topup", "vision-fallback", "cached")
    if has and s["source"] != "cached":
        f = pd.read_csv(os.path.join(ROOT, f"{perp}_funding.csv"), usecols=["calc_time"])
        t0 = pd.to_datetime(f["calc_time"].min(), unit="ms", utc=True)
        t1 = pd.to_datetime(f["calc_time"].max(), unit="ms", utc=True)
        sp2[perp] = {"cmc": s["cmc"], "funding_months": 1, "kline_months": 1,
                     "first": str(t0.date()), "last": str(t1.date()), "source": s["source"], "rows": int(len(f))}
    elif has:
        sp2[perp] = {"cmc": s["cmc"], "funding_months": 1, "source": "cached"}
    else:
        sp2[perp] = {"cmc": s["cmc"], "funding_months": 0, "source": "absent"}
json.dump(sp2, open(os.path.join(ROOT, "spans.json"), "w"), indent=1)
print("done", {v: sum(1 for s in spans.values() if s["source"] == v) for v in ("hf+vision-topup", "vision-fallback", "absent", "cached")})
