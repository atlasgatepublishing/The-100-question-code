#!/usr/bin/env python3
"""One-time parse of the v12 gap-a10 Yahoo cache (read-only) into a fast
pickle in THIS folder: per-ticker adj-close series, dividend events,
expected-month patterns, PIT membership intervals, SPY calendar."""
import csv, json, os, pickle, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/gap-a10-div-capture/data")

def load_ticker(t):
    path = os.path.join(DATA, f"px_{t}.json")
    if not os.path.exists(path) or os.path.getsize(path) <= 200: return None
    j = json.load(open(path))
    if not j.get("chart", {}).get("result"): return None
    res = j["chart"]["result"][0]
    if "timestamp" not in res: return None
    ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    dates, adjv = [], []
    for i, tt in enumerate(ts):
        c = q["close"][i]
        if c is None: continue
        dates.append(time.strftime("%Y-%m-%d", time.gmtime(tt)))
        adjv.append(adj[i] if adj and adj[i] else c)
    divs = []
    for dv in (res.get("events", {}) or {}).get("dividends", {}).values():
        divs.append((time.strftime("%Y-%m-%d", time.gmtime(dv["date"])), dv["amount"]))
    divs.sort()
    return dates, adjv, divs

def main():
    rows = list(csv.DictReader(open(os.path.join(DATA, "sp500_ticker_start_end.csv"))))
    member = {}
    for r in rows:
        member.setdefault(r["ticker"], []).append((r["start_date"], r["end_date"] or "9999-12-31"))
    data = {}
    for t in sorted(member):
        lt = load_ticker(t)
        if lt is None: continue
        dates, adjv, divs = lt
        pay_months = {}
        for dd, _amt in divs:
            pay_months.setdefault(int(dd[:4]), set()).add(int(dd[5:7]))
        data[t] = {"dates": dates, "adj": adjv, "divs": divs, "pay_months": pay_months}
    spy = load_ticker("SPY")
    out = {"member": member, "data": data,
           "spy_dates": spy[0], "spy_adj": spy[1]}
    with open(os.path.join(HERE, "cache.pkl"), "wb") as f:
        pickle.dump(out, f, protocol=4)
    print("cached tickers:", len(data))

if __name__ == "__main__":
    main()
