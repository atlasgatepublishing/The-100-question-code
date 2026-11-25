#!/usr/bin/env python3
"""Standalone check: dividend-adjusted SPY buy-and-hold on the DECADE
window (2016-11-21 -> 2026-11-20), tournament cost convention, from the
Yahoo chart API adjclose series. Used to verify the SPEC reference
$367.80 printed in results.json / RESULTS.md. Simulation only."""
import json
import urllib.request
from datetime import date, datetime, timezone

START, END = date(2016, 11, 21), date(2026, 11, 20)
p1 = int(datetime(2016, 11, 1, tzinfo=timezone.utc).timestamp())
p2 = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp())
url = ("https://query1.finance.yahoo.com/v8/finance/chart/SPY"
       f"?period1={p1}&period2={p2}&interval=1d&events=div,splits")
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=60) as resp:
    payload = json.loads(resp.read().decode("utf-8"))
result = payload["chart"]["result"][0]
adj = result["indicators"]["adjclose"][0]["adjclose"]
ts = result["timestamp"]
rows = []
for i, t in enumerate(ts):
    d = datetime.fromtimestamp(t, tz=timezone.utc).date()
    if adj[i] is not None and START <= d <= END:
        rows.append((d, adj[i]))
first_adj, last_adj = rows[0][1], rows[-1][1]
buy_value = 100.0 / 1.001
shares = buy_value / first_adj
sell_value = shares * last_adj
net = sell_value - (0.001 * sell_value + 0.01)
print(f"first {rows[0][0]} adjclose {first_adj:.4f}; "
      f"last {rows[-1][0]} adjclose {last_adj:.4f}")
print(f"dividend-adjusted SPY decade, net of tournament costs: ${net:.2f}")
