import csv, json, statistics
from datetime import date, timedelta

BASE = "/home/hatch/workspace/stock-app/backtests/cd-benchmark/"
rates = {}
with open(BASE+"cd-rates-monthly.csv") as f:
    for row in csv.DictReader(f):
        y,m = map(int, row["month"].split("-"))
        rates[(y,m)] = (float(row["cd12_apy_pct"])/100.0, float(row["cd6_apy_pct"])/100.0)

def add_months(d, k):
    y = d.year + (d.month-1+k)//12
    m = (d.month-1+k)%12 + 1
    mdays = [31,29 if (y%4==0 and (y%100!=0 or y%400==0)) else 28,31,30,31,30,31,31,30,31,30,31][m-1]
    return date(y, m, min(d.day, mdays))

def roller_value(start, end, term_months, col):
    """$100 at start, CD at prevailing rate of start month, renew at each term maturity
    into the then-prevailing rate, daily accrual at locked APY, value at end (accrued)."""
    if end <= start: return 100.0
    bal, cur = 100.0, start
    while True:
        r = rates[(cur.year, cur.month)][col]
        mat = add_months(cur, term_months)
        seg_end = min(mat, end)
        days = (seg_end - cur).days
        bal *= (1.0 + r) ** (days/365.0)
        if seg_end >= end: return bal
        cur = mat

END = date(2026,11,20)
roads = {
 "judging_road_jan2023_nov2026": (date(2023,1,1), END, "January 1, 2023 to November 20, 2026 (just under 4 years)"),
 "middle_road_jan2019_nov2026": (date(2019,1,2), END, "January 2, 2019 to November 20, 2026 (just under 8 years)"),
 "road_10yr_nov2016_nov2026": (date(2016,11,21), END, "November 21, 2016 to November 20, 2026 (10 years)"),
 "road_17yr_jan2010_nov2026": (date(2010,1,4), END, "January 4, 2010 to November 20, 2026 (16 years, 10.5 months)"),
}
out = {"roads": {}, "windows_12m_roller": {}, "meta": {}}
for name,(s,e,label) in roads.items():
    out["roads"][name] = {
        "label": label,
        "cd12_final": round(roller_value(s,e,12,0),2),
        "cd6_final": round(roller_value(s,e,6,1),2),
    }

horizons = [("1 day",1),("7 days (1 week)",7),("14 days (2 weeks)",14),("30 days (1 month)",30),
            ("3 months",91),("6 months",182),("1 year",365),("2 years",730),("3 years",1095),
            ("4 years",1460),("6 years",2190),("8 years",2920),("10 years",3650)]
GRID0 = date(2010,1,4)
ndays = (END-GRID0).days
for label,h in horizons:
    gains = []
    for i in range(0, ndays-h+1):
        s = GRID0 + timedelta(days=i)
        v = roller_value(s, s+timedelta(days=h), 12, 0)
        gains.append(v-100.0)
    gains.sort()
    n = len(gains)
    out["windows_12m_roller"][label] = {
        "horizon_days": h, "n_windows": n,
        "pct_positive": round(100.0*sum(1 for g in gains if g>0)/n,1),
        "typical_gain": round(gains[n//2] if n%2==1 else (gains[n//2-1]+gains[n//2])/2, 4),
        "best_gain": round(gains[-1],2), "worst_gain": round(gains[0],4),
        "average_gain": round(sum(gains)/n,4),
    }

cpi = {"2010-01":216.687, "2016-11":241.353, "2019-01":251.712, "2023-01":299.170, "2026-10":337.511}
out["cpi"] = cpi
out["cpi_change_jan2010_to_oct2026_pct"] = round((cpi["2026-10"]/cpi["2010-01"]-1)*100,2)
out["meta"] = {
 "engine": "SPEC.md frozen 2026-11-23: monthly prevailing rate = last weekly posting in month (prior rule) / published monthly value (revised rule); daily accrual (1+APY)^(1/365); renewal at calendar 12-month (or 6-month) maturity at then-prevailing rate; window value = accrued balance at window end.",
 "today_fdIC_nov16_2026": {"cd12_pct": 1.81, "cd6_pct": 1.40},
}
with open(BASE+"results.json","w") as f:
    json.dump(out, f, indent=1)
print(json.dumps(out, indent=1))
