#!/usr/bin/env python3
"""
MOMENTUM BASKET + NET STOCK ISSUANCE VETO — one-variable ablation.
Terry's AI stock app, simulation only.

Base strategy: the survivorship-honest momentum basket
(momentum-basket-honest.py) — the program's leading candidate. Engine,
costs, floor, universe, windows are imported from that module unchanged.

THE ONE CHANGE: at each monthly selection, a name that would otherwise be
picked is VETOED if its trailing 12-month net share issuance (point-in-time
from SEC EDGAR companyfacts, split-adjusted) exceeds +5%/yr. It is replaced
by the next-ranked eligible name, or cash if none remains.

Hypothesis (audit research/what-actually-works.md §3.11, item 7 of the
ranked shortlist): heavy net issuers underperform (Pontiff & Woodgate 2008:
-0.33%/mo per SD of net issuance, t ~ -6.72; Hou-Xue-Zhang's most robust
cluster; Fama-French 2008 call it pervasive). The audit grades issuance
ALIVE as a screen — this ablation decides whether it earns a place in the
app. Kept only if validation improves.

Issuance construction (per ticker, one series):
  Concept priority: (1) dei:EntityCommonStockSharesOutstanding,
  (2) us-gaap:CommonStockSharesIssued,
  (3) us-gaap:WeightedAverageNumberOfSharesOutstandingBasic.
  First concept with >=30 usable observations spanning 2015..2025 wins.
  Observations are deduped by period end (shortest duration wins; ties
  go to the EARLIEST filing — the value as first reported, the only one
  visible in real time) and SPLIT-ADJUSTED
  into current share units using Yahoo split events. Only TRUE splits are
  applied: a Yahoo "split" event counts if its ratio, reduced to lowest
  terms, has both terms <= 20 (splits are small-integer exchanges, e.g.
  4:1, 20:1, 1:8, 3:2). Non-integer distribution factors (GE's spinoff
  adjustments 1281:1000 etc.) do not change the parent's share count and
  are excluded.
  Coverage: 28 of 30 names have a usable series. BRK-B and V tag no
  shares-outstanding / weighted-average-share concept in companyfacts
  covering 2016-2026 (Berkshire's weighted-average series ends 2015,
  Visa has none at all), so those two can never be vetoed — a documented
  data limitation, disclosed in the report. XOM's CIK is overridden to
  the long-standing registrant (34088): company_tickers.json currently
  maps the ticker to a recently-registered entity with no history.
  As of a signal date D, only facts with filed <= D are visible.
  Current shares = latest period end among visible facts; year-ago shares
  = visible fact whose period end is closest to (current end - 365 days),
  required within [current-430d, current-300d]. Issuance is annualized:
  (cur/ago)^(365.25/days) - 1. If no year-ago point exists, no veto.

Self-check: with the veto disabled this script must reproduce the honest
basket's published finals to the cent (full $439.45/$215.61, validation
$208.27/$103.18). It runs that check first and prints the comparison.

Data: EDGAR companyfacts + company_tickers (free, no key) and Yahoo
split events, cached under ./basket-issuance-veto-data/. Price data is
the honest basket's own cache (read-only reuse).
"""

import bisect
import importlib.util
import json
import math
import os
import time
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "basket-issuance-veto-data")
os.makedirs(CACHE, exist_ok=True)

# --------------------------------------------------------------------------
# Load the honest-basket engine (hyphenated filename -> importlib)
# --------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location(
    "honest_basket", os.path.join(HERE, "momentum-basket-honest.py"))
hb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hb)

UNIVERSE = hb.UNIVERSE
FLOORS = hb.FLOORS
COST_RATE = hb.COST_RATE
SELL_FEE = hb.SELL_FEE
WINDOWS = hb.WINDOWS

UA = "AtlasGateResearch terry-research@example.com"
VETO_THRESHOLD = 0.05          # +5%/yr net issuance -> veto

# company_tickers.json currently maps XOM to a recently-registered entity
# (CIK 2115436, facts only from 2024); the operating company's long-standing
# registrant is CIK 34088. Override it.
CIK_OVERRIDES = {"XOM": 34088}

CONCEPTS = [
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesIssued"),
    ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic"),
]


# --------------------------------------------------------------------------
# Fetch helpers (cached)
# --------------------------------------------------------------------------
def fetch(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, headers=headers or {"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            if blob[:2] == b"\x1f\x8b":
                import gzip
                blob = gzip.decompress(blob)
            with open(path, "wb") as f:
                f.write(blob)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")


def get_ciks():
    blob = fetch("https://www.sec.gov/files/company_tickers.json",
                 os.path.join(CACHE, "company_tickers.json"))
    raw = json.loads(blob)
    return {row["ticker"]: int(row["cik_str"]) for row in raw.values()}


def get_companyfacts(cik):
    path = os.path.join(CACHE, f"facts_{cik:010d}.json")
    blob = fetch(f"https://data.sec.gov/api/xbrl/companyfacts/"
                 f"CIK{cik:010d}.json", path,
                 headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    return json.loads(blob)


def get_splits(ticker):
    """True-split events [(date, ratio)] from Yahoo; see module docstring
    for the small-integer classification rule."""
    import calendar
    path = os.path.join(CACHE, f"splits_{ticker}.json")
    if os.path.exists(path):
        with open(path) as f:
            return [tuple(x) for x in json.load(f)]
    p1 = calendar.timegm(time.strptime("2014-01-01", "%Y-%m-%d"))
    p2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d&events=split")
    blob = fetch(url, path + ".raw", headers={"User-Agent": "Mozilla/5.0"})
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    raw_splits = (res.get("events") or {}).get("splits") or {}
    out = []
    for ts, s in sorted(raw_splits.items()):
        num, den = float(s["numerator"]), float(s["denominator"])
        g = math.gcd(int(num), int(den)) if num == int(num) and den == int(den) else 1
        rn, rd = int(num) // g, int(den) // g
        if rn <= 20 and rd <= 20:            # true split (small integers)
            d = time.strftime("%Y-%m-%d", time.gmtime(int(ts)))
            out.append((d, num / den))
    with open(path, "w") as f:
        json.dump(out, f)
    os.remove(path + ".raw")
    time.sleep(0.2)
    return out


# --------------------------------------------------------------------------
# Point-in-time issuance series
# --------------------------------------------------------------------------
class IssuanceSeries:
    def __init__(self, ticker, facts, splits):
        self.ticker = ticker
        self.splits = splits                 # [(date, ratio)] true splits
        self.concept = None
        self.obs = []                        # [(end, filed, adj_value)]
        for ns, concept in CONCEPTS:
            obs = self._build(facts, ns, concept)
            if obs is None:
                continue
            ends = [o[0] for o in obs]
            if (len(obs) >= 30 and min(ends) <= "2017-01-01"
                    and max(ends) >= "2025-06-01"):
                self.concept = f"{ns}:{concept}"
                self.obs = obs
                break
        self._filed = [o[1] for o in self.obs]

    def _adj_factor(self, end_d):
        """Multiply a share count stated as of end_d into current units."""
        f = 1.0
        for d, ratio in self.splits:
            if d > end_d:
                f *= ratio
        return f

    def _build(self, facts, ns, concept):
        try:
            units = facts["facts"][ns][concept]["units"]
        except KeyError:
            return None
        if "shares" not in units:
            return None
        entries = units["shares"]
        by_end = {}
        for e in entries:
            if "end" not in e or "filed" not in e or "val" not in e:
                continue
            if e["val"] is None or e["val"] <= 0:
                continue
            dur = 0
            if "start" in e:
                try:
                    dur = (date.fromisoformat(e["end"])
                           - date.fromisoformat(e["start"])).days
                except ValueError:
                    continue
            key = e["end"]
            cur = by_end.get(key)
            # dedup: shortest duration wins; tie -> EARLIEST filed wins.
            # The earliest filing is the value as first reported — the
            # only one visible in real time. (Latest-filed would import
            # next year's comparative columns and make every observation
            # visible ~1 year late; caught in review on DIS, whose Fox
            # issuance then appeared a year after the fact.)
            if (cur is None or dur < cur[0]
                    or (dur == cur[0] and e["filed"] < cur[1])):
                by_end[key] = (dur, e["filed"], float(e["val"]))
        if not by_end:
            return None
        obs = []
        for end, (dur, filed, val) in by_end.items():
            obs.append((end, filed, val * self._adj_factor(end)))
        obs.sort(key=lambda o: o[1])         # sort by filed date
        return obs

    def issuance_asof(self, asof):
        """Annualized trailing ~12m net issuance using only facts filed
        on/before asof. None when it cannot be measured."""
        if not self.obs:
            return None
        n = bisect.bisect_right(self._filed, asof)
        if n == 0:
            return None
        visible = self.obs[:n]
        cur = max(visible, key=lambda o: o[0])
        e1, v1 = cur[0], cur[2]
        d1 = date.fromisoformat(e1)
        target = d1 - timedelta(days=365)
        lo = (d1 - timedelta(days=430)).isoformat()
        hi = (d1 - timedelta(days=300)).isoformat()
        best = None
        for end, filed, val in visible:
            if lo <= end <= hi:
                gap = abs((date.fromisoformat(end) - target).days)
                if best is None or gap < best[0]:
                    best = (gap, end, val)
        if best is None:
            return None
        _, e0, v0 = best
        days = (d1 - date.fromisoformat(e0)).days
        if days <= 0 or v0 <= 0:
            return None
        return (v1 / v0) ** (365.25 / days) - 1.0


# --------------------------------------------------------------------------
# Simulation — hb.simulate copied verbatim except the ranked pick step,
# which applies the veto. mode is always the ranked basket.
# --------------------------------------------------------------------------
def simulate_veto(mkt, start_d, end_d, pot0, series=None, veto_log=None):
    """series: {ticker: IssuanceSeries} or None (veto disabled).
    veto_log: optional list; veto events are appended as dicts."""
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    floor0, ladder = FLOORS[pot0]
    floor = floor0
    cash = float(pot0)
    pos = {}
    res = hb.Result()
    pending_liquidation = False
    mark_px = {}
    cur_month = None

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        month_key = d[:7]

        if pending_liquidation:
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    px = mkt.close_px(t, i)
                val = pos[t] * px
                fee = val * COST_RATE + SELL_FEE
                cash += val - fee
                res.costs += fee
                res.orders += 1
                if t in mark_px:
                    res.sel_total += 1
                    if px > mark_px[t]:
                        res.sel_wins += 1
                del pos[t]
            mark_px.clear()
            res.halt_date = d
            res.final = cash
            res.equity_curve.append((d, cash))
            break

        if month_key != cur_month and i > 0:
            cur_month = month_key
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is not None and t in mark_px:
                    res.sel_total += 1
                    if px > mark_px[t]:
                        res.sel_wins += 1
            j = i - 1
            elig = []
            for t in UNIVERSE:
                sma200 = mkt.sma(t, j, 200)
                c = mkt.close_px(t, j)
                if sma200 is None or c is None or c <= sma200:
                    continue
                mom = mkt.momentum_12_1(t, j)
                if mom is None:
                    continue
                elig.append((t, mom))
            elig.sort(key=lambda x: -x[1])
            ranked = [t for t, _ in elig]
            base_picks = ranked[:5]
            if series is None:
                picks = base_picks
            else:
                signal_d = mkt.cal[j]
                picks = []
                vetoed = []
                for t in ranked:
                    if len(picks) >= 5:
                        break
                    iss = series[t].issuance_asof(signal_d)
                    if iss is not None and iss > VETO_THRESHOLD:
                        if t in base_picks:
                            vetoed.append((t, iss))
                        continue
                    picks.append(t)
                if veto_log is not None:
                    entrants = [t for t in picks if t not in base_picks]
                    for k, (t, iss) in enumerate(vetoed):
                        veto_log.append({
                            "date": d,
                            "signal_date": signal_d,
                            "ticker": t,
                            "issuance_pct": round(iss * 100, 2),
                            "replacement": (entrants[k] if k < len(entrants)
                                            else "cash"),
                        })

            eq_open = equity_at(i, use_open=True)
            target_val = {t: 0.20 * eq_open for t in picks}

            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos[t] * px
                want = target_val.get(t, 0.0)
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - fee
                    res.costs += fee
                    res.orders += 1
                    pos[t] -= sh
                    if want <= 0.0 or pos[t] * px < 0.01:
                        del pos[t]
            for t in picks:
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos.get(t, 0.0) * px
                deficit = target_val[t] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee
                res.costs += fee
                res.orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px
            mark_px = {}
            for t in pos:
                px = mkt.open_px(t, i)
                if px is not None:
                    mark_px[t] = px

        eq_close = equity_at(i, use_open=False)
        res.equity_curve.append((d, eq_close))
        for thresh, new_floor in ladder:
            if eq_close >= thresh:
                floor = max(floor, new_floor)
        if eq_close <= floor:
            pending_liquidation = True
            if i == i1:
                tot = cash
                for t, sh in list(pos.items()):
                    val = sh * mkt.close_px(t, i)
                    fee = val * COST_RATE + SELL_FEE
                    tot += val - fee
                    res.costs += fee
                    res.orders += 1
                res.final = tot
                res.halt_date = d
                pos.clear()
                break

    if res.final is None:
        res.final = res.equity_curve[-1][1]
    peak = -1.0
    for d, eq in res.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
    month_end = {}
    for d, eq in res.equity_curve:
        month_end[d[:7]] = eq
    keys = sorted(month_end)
    for a, b in zip(keys, keys[1:]):
        r = month_end[b] / month_end[a] - 1.0
        res.months += 1
        res.month_rets.append(r)
        if r > 0:
            res.month_wins += 1
    return res


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
PUBLISHED_BASE = {   # honest basket published finals (self-check target)
    ("full", 100): 439.45, ("full", 50): 215.61,
    ("validation", 100): 208.27, ("validation", 50): 103.18,
}


def _summ(r, pot, yrs, bench):
    return {
        "final": round(r.final, 2),
        "ret_pct": round((r.final / pot - 1) * 100, 2),
        "cagr_pct": round(hb.cagr(r.final, pot, yrs) * 100, 2),
        "orders": r.orders,
        "costs": round(r.costs, 2),
        "max_dd_pct": round(r.max_dd * 100, 2),
        "halt": r.halt_date,
        "bench_final": round(bench, 2),
        "bench_ret_pct": round((bench / pot - 1) * 100, 2),
    }


def main():
    ciks = get_ciks()
    ciks.update(CIK_OVERRIDES)
    series = {}
    concept_map = {}
    splits_map = {}
    for t in UNIVERSE:
        facts = get_companyfacts(ciks[t])
        splits = get_splits(t)
        s = IssuanceSeries(t, facts, splits)
        series[t] = s
        concept_map[t] = s.concept
        splits_map[t] = splits
        print(f"{t}: concept={s.concept} obs={len(s.obs)} splits={splits}",
              flush=True)
    missing = [t for t in UNIVERSE if series[t].concept is None]
    if missing:
        print(f"WARNING: no usable issuance series for {missing} "
              f"(those names can never be vetoed)", flush=True)

    mkt = hb.Market(UNIVERSE)
    out = {"concept_map": concept_map,
           "splits_applied": {t: splits_map[t] for t in UNIVERSE},
           "veto_threshold_pct": VETO_THRESHOLD * 100}

    # ---- self-check: veto disabled must reproduce the published finals --
    print("\nSELF-CHECK (veto disabled vs published honest basket):",
          flush=True)
    check = {}
    for wname in ("full", "validation"):
        sd, ed = WINDOWS[wname]
        for pot in (100, 50):
            r = simulate_veto(mkt, sd, ed, pot, series=None)
            pub = PUBLISHED_BASE[(wname, pot)]
            ok = abs(round(r.final, 2) - pub) < 0.005
            check[f"{wname}|{pot}"] = {
                "reproduced": round(r.final, 2), "published": pub, "ok": ok}
            print(f"  {wname}|${pot}: reproduced={r.final:.2f} "
                  f"published={pub:.2f} ok={ok}", flush=True)
    out["self_check"] = check

    # ---- veto runs -------------------------------------------------------
    for wname in ("validation", "full"):
        sd, ed = WINDOWS[wname]
        yrs = hb.years_between(sd, ed)
        for pot in (100, 50):
            bench = hb.spy_net(mkt, sd, ed, pot)
            log = []
            r = simulate_veto(mkt, sd, ed, pot, series=series,
                              veto_log=log)
            key = f"{wname}|{pot}|veto"
            s = _summ(r, pot, yrs, bench)
            s["base_final"] = PUBLISHED_BASE[(wname, pot)]
            s["delta_vs_base"] = round(r.final - PUBLISHED_BASE[(wname, pot)], 2)
            s["veto_events"] = log
            s["n_vetoes"] = len(log)
            out[key] = s
            print(f"{key}: final={r.final:.2f} "
                  f"ret={(r.final/pot-1)*100:+.2f}% "
                  f"base={PUBLISHED_BASE[(wname, pot)]:.2f} "
                  f"delta={r.final - PUBLISHED_BASE[(wname, pot)]:+.2f} "
                  f"maxDD={r.max_dd*100:.2f}% halt={r.halt_date} "
                  f"vetoes={len(log)} SPYnet={bench:.2f}", flush=True)

    with open(os.path.join(HERE, "basket-issuance-veto-results.json"),
              "w") as f:
        json.dump(out, f, indent=1)
    print("saved basket-issuance-veto-results.json")


if __name__ == "__main__":
    main()
