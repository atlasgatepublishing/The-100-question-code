#!/usr/bin/env python3
"""
V12 CONSTRUCTED — Liu-Tsyvinski-Wu crypto factor baskets, LONG LEG ONLY.

Construction frozen in CONSTRUCTION-SPEC.md before this run:
  - Universe: v4 CoinMarketCap weekly-snapshot PIT universe (97 coins,
    monthly selections of Sunday snapshots, snapshot_date carried),
    read-only from backtests/v4/crypto-basket-pit-data/.
  - Long top quintile (k = ceil(N/5)), equal weight, fully invested.
  - Sorts: momentum trailing 7/14/21/28 days (published grid, all run);
    secondary TRUNCATED-SIZE (smallest quintile of the snapshot).
  - Cadence: weekly (Mondays, signal = prior close, trade at open) and
    monthly variant (first Monday).
  - Costs 0.60%/side. Death rule: no real bar for >7 days -> value $0,
    never carried (BINANCE-DATA-END exception: Binance series all end
    2026-10-31 in the source files; those keep last close to window end).
  - Rule sets: NATIVE (no floor) and V9 (plain -15% floor, $85 on $100).
  - Windows: FULL 2017-01-01->2026-11-20, DESIGN ->2022-12-31,
    VALIDATION 2023-01-01->2026-11-20. Bar: BTC buy-hold net same costs.
  - Placebos: 20 seeds, random k from the same rankable set, weekly,
    native, every momentum horizon, FULL + VALIDATION.

Registry / price-source map / credible-start repairs are inherited
unchanged from v4 crypto-basket-pit.py (documented there coin by coin).
This script NEVER writes to the v4 folder: caches are read from it, and
HYPE is taken as v4's documented exclusion without any fetch attempt.
"""

import json
import math
import os
import random
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
V4DATA = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/crypto-basket-pit-data")

COST = 0.006            # 0.60% per side (spec)
POT = 100.0
STALE_DAYS = 7          # death rule: >7 days without a real bar -> $0
BINANCE_DATA_END = "2026-10-31"

WINDOWS = {
    "full":       ("2017-01-01", "2026-11-20"),
    "design":     ("2017-01-01", "2022-12-31"),
    "validation": ("2023-01-01", "2026-11-20"),
}
HORIZONS = [7, 14, 21, 28]
PLACEBO_SEEDS = list(range(1, 21))

BINANCE_MAP = {
    1720: "IOTAUSDT", 3890: "MATICUSDT", 28321: "POLUSDT",
    24478: "PEPEUSDT", 29470: "USDEUSDT", 36148: "USD1USDT",
    7083: "UNIUSDT", 20947: "SUIUSDT",
}
KRAKEN_MAP = {11419: "TONUSD"}
YAHOO_MAP = {4172: "LUNC-USD", 7129: "USTC-USD", 2280: "FIL-USD"}
EXCLUDED = {
    1513: "BitConnect: no price series on any free source",
    291: "MaidSafeCoin: Yahoo carries a 1-bar stub only",
    1408: "Iconomi: Yahoo carries a 1-bar stub only",
    1087: "Factom: Yahoo carries a 1-bar stub only",
    576: "GameCredits: Yahoo carries a 1-bar stub only",
    1229: "DigixDAO: Yahoo carries a 1-bar stub only",
    1343: "Stratis: Yahoo carries a 1-bar stub only",
    1904: "VeChain (VEN): no free series; never eligible (inside its own lookback)",
    1455: "Golem (GNT): Yahoo series is a corrupted wrong-era stub",
    35491: "MemeCore (M): Yahoo M-USD is a different token",
    37263: "Canton (CC): no free series; launched Nov 2025",
    32196: "Hyperliquid (HYPE): no Yahoo/Binance spot series (v4 bybit attempt failed)",
}
CREDIBLE_START = {
    2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31",
}


def _load(name):
    with open(os.path.join(V4DATA, name)) as f:
        return json.load(f)


def build_registry(snaps):
    coins = {}
    for month, info in snaps.items():
        for c in info["top20"]:
            coins.setdefault(c["cmc_id"],
                             {"symbol": c["symbol"], "slug": c["slug"]})
    reg = {}
    for cid, meta in coins.items():
        if cid in EXCLUDED:
            reg[cid] = {**meta, "source": "excluded",
                        "reason": EXCLUDED[cid], "rows": []}
            continue
        if cid in BINANCE_MAP:
            rows = _load(f"b_{BINANCE_MAP[cid]}.json")
            src = f"binance:{BINANCE_MAP[cid]}"
        elif cid in KRAKEN_MAP:
            rows = _load(f"k_{KRAKEN_MAP[cid]}.json")
            src = f"kraken:{KRAKEN_MAP[cid]}"
        else:
            ticker = YAHOO_MAP.get(cid, f"{meta['symbol']}-USD")
            rows = _load(f"y_{ticker}.json")
            src = f"yahoo:{ticker}"
        if cid in CREDIBLE_START:
            rows = [r for r in rows if r["d"] >= CREDIBLE_START[cid]]
        if len(rows) < 60:
            reg[cid] = {**meta, "source": "excluded",
                        "reason": f"price series too short/absent "
                                  f"({len(rows)} bars via {src})",
                        "rows": []}
        else:
            reg[cid] = {**meta, "source": src, "reason": None, "rows": rows}
    return reg


class Market:
    """BTC calendar; per-coin forward-filled closes, last-bar index,
    cumulative bar counts — same plumbing as v4, new valuation rule."""

    def __init__(self, reg):
        self.reg = reg
        btc_rows = reg[1]["rows"]
        self.cal = [r["d"] for r in btc_rows]
        self.cal_index = {d: i for i, d in enumerate(self.cal)}
        self.bars = {}
        self.closes_ff = {}
        self.last_bar = {}
        self.bar_count = {}
        for cid, info in reg.items():
            if info["source"] == "excluded":
                continue
            bars = {r["d"]: (r["o"], r["c"]) for r in info["rows"]}
            self.bars[cid] = bars
            ff, lb, cnt = [], [], []
            last_close, last_i, n = None, -1, 0
            for i, d in enumerate(self.cal):
                if d in bars:
                    last_close = bars[d][1]
                    last_i = i
                    n += 1
                ff.append(last_close)
                lb.append(last_i)
                cnt.append(n)
            self.closes_ff[cid] = ff
            self.last_bar[cid] = lb
            self.bar_count[cid] = cnt

    def trade_open(self, cid, i):
        d = self.cal[i]
        if d in self.bars[cid]:
            return self.bars[cid][d][0]
        if i > 0 and self.cal[i - 1] in self.bars[cid]:
            return self.bars[cid][self.cal[i - 1]][1]
        return None

    def is_dead(self, cid, i):
        """Death rule: last real bar > STALE_DAYS old -> dead ($0),
        except a Binance series ending exactly at the source data end
        (truncation, not death)."""
        lb = self.last_bar[cid][i]
        if lb < 0:
            return True
        if i - lb <= STALE_DAYS:
            return False
        if (self.reg[cid]["source"].startswith("binance")
                and self.cal[lb] >= BINANCE_DATA_END):
            return False
        return True

    def value_close(self, cid, i):
        if self.is_dead(cid, i):
            return 0.0
        v = self.closes_ff[cid][i]
        return v if v is not None else 0.0

    def momentum(self, cid, j, h):
        """Trailing h-day return at signal index j, real bars at both
        ends (7-day tolerance), or None."""
        if cid not in self.bars:
            return None
        lb = self.last_bar[cid]
        if lb[j] < 0 or j - lb[j] > STALE_DAYS:
            return None
        if j - h < 0:
            return None
        a_i = lb[j - h]
        if a_i < 0 or (j - h) - a_i > STALE_DAYS:
            return None
        if lb[j] - a_i < h - STALE_DAYS:
            return None
        if self.bar_count[cid][lb[j]] < h + 7:
            return None
        a, b = self.closes_ff[cid][a_i], self.closes_ff[cid][lb[j]]
        if a is None or b is None or a <= 0:
            return None
        return b / a - 1.0

    def fresh(self, cid, j):
        if cid not in self.bars:
            return False
        lb = self.last_bar[cid][j]
        return lb >= 0 and j - lb <= STALE_DAYS


def snapshot_universe(snaps_by_date, signal_date):
    """Latest stored snapshot with snapshot_date <= signal date.
    snaps_by_date: sorted list of (snapshot_date 'YYYY-MM-DD', [cmc_id...],
    {cmc_id: rank})."""
    uni, ranks = [], {}
    for sd, ids, rk in snaps_by_date:
        if sd <= signal_date:
            uni, ranks = ids, rk
        else:
            break
    return uni, ranks


class Result:
    def __init__(self):
        self.final = None
        self.orders = 0
        self.costs = 0.0
        self.halt_date = None
        self.max_dd = 0.0
        self.curve = []
        self.events = []       # deaths (write-to-zero while held)
        self.resurrections = 0
        self.rebalances = 0
        self.avg_n_rankable = None
        self._rank_sum = 0
        self.picks_log = []


def simulate(mkt, snaps_by_date, start_d, end_d, sort_key, horizon=None,
             cadence="weekly", ruleset="native", mode="ranked", seed=42):
    """sort_key: 'momentum' (needs horizon) or 'size'."""
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    floor = 85.0 if ruleset == "v9" else None
    cash = float(POT)
    pos = {}
    entry_avg = {}
    dead_flag = {}
    res = Result()
    pending_liq = False

    def equity_at(i, price_fn):
        tot = cash
        for cid, sh in pos.items():
            tot += sh * price_fn(cid, i)
        return tot

    def note_collapse(cid, exit_px, when):
        if cid in entry_avg and entry_avg[cid] > 0 and exit_px <= 0.10 * entry_avg[cid]:
            res.events.append({
                "type": "collapse_exit", "coin": mkt.reg[cid]["symbol"],
                "cmc_id": cid, "date": when,
                "entry_px": entry_avg[cid], "exit_px": exit_px,
                "loss_pct": round((exit_px / entry_avg[cid] - 1) * 100, 2)})

    for i in range(i0, i1 + 1):
        d = cal[i]
        dt = datetime.strptime(d, "%Y-%m-%d")

        # ---- death / resurrection bookkeeping -------------------------
        for cid in list(pos):
            dead = mkt.is_dead(cid, i)
            if dead and not dead_flag.get(cid):
                lb = mkt.last_bar[cid][i]
                res.events.append({
                    "type": "write_off_zero", "coin": mkt.reg[cid]["symbol"],
                    "cmc_id": cid, "date": d,
                    "last_bar_date": cal[lb] if lb >= 0 else None,
                    "last_px": mkt.closes_ff[cid][lb] if lb >= 0 else None,
                    "shares": pos[cid],
                    "written_off_value": round(
                        pos[cid] * (mkt.closes_ff[cid][lb] or 0.0), 2)
                    if lb >= 0 else 0.0})
                dead_flag[cid] = True
            elif not dead and dead_flag.get(cid):
                dead_flag[cid] = False
                res.resurrections += 1

        # ---- floor liquidation ----------------------------------------
        if pending_liq:
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    note_collapse(cid, 0.0, d)
                    del pos[cid]
                    entry_avg.pop(cid, None)
                    continue
                val = pos[cid] * px
                fee = val * COST
                cash += val - fee
                res.costs += fee
                res.orders += 1
                note_collapse(cid, px, d)
                del pos[cid]
                entry_avg.pop(cid, None)
            res.halt_date = d
            res.final = cash
            res.curve.append((d, cash))
            break

        # ---- rebalance -------------------------------------------------
        is_rebal = (dt.weekday() == 0 and i > i0) if cadence == "weekly" \
            else (dt.weekday() == 0 and dt.day <= 7 and i > i0)
        if is_rebal and i > 0:
            res.rebalances += 1
            j = i - 1
            universe, ranks = snapshot_universe(snaps_by_date, cal[j])
            scored = []
            for cid in universe:
                if sort_key == "momentum":
                    s = mkt.momentum(cid, j, horizon)
                else:  # size: rankable = fresh price; score = snapshot rank
                    s = float(ranks[cid]) if mkt.fresh(cid, j) else None
                if s is not None:
                    scored.append((cid, s))
            res._rank_sum += len(scored)
            if scored:
                if mode == "ranked":
                    scored.sort(key=lambda x: -x[1])
                    k = max(1, math.ceil(len(scored) / 5))
                    picks = [cid for cid, _ in scored[:k]]
                else:
                    names = sorted(cid for cid, _ in scored)
                    k = max(1, math.ceil(len(names) / 5))
                    picks = rng.sample(names, min(k, len(names)))
                res.picks_log.append({
                    "date": d,
                    "picks": [mkt.reg[c]["symbol"] for c in picks],
                    "n_rankable": len(scored)})
                eq_open = equity_at(i, lambda c, ii: (
                    mkt.trade_open(c, ii) or mkt.value_close(c, ii)))
                target = {cid: eq_open / len(picks) for cid in picks}
                # sells first
                for cid in list(pos):
                    if mkt.is_dead(cid, i):
                        note_collapse(cid, 0.0, d)
                        del pos[cid]
                        entry_avg.pop(cid, None)
                        continue
                    px = mkt.trade_open(cid, i)
                    if px is None:
                        continue          # temporarily untradeable: hold
                    cur_val = pos[cid] * px
                    want = target.get(cid, 0.0)
                    if cur_val > want + 0.01:
                        sell_val = cur_val - want
                        fee = sell_val * COST
                        cash += sell_val - fee
                        res.costs += fee
                        res.orders += 1
                        pos[cid] -= sell_val / px
                        if want <= 0.0 or pos[cid] * px < 0.01:
                            note_collapse(cid, px, d)
                            del pos[cid]
                            entry_avg.pop(cid, None)
                # buys
                for cid in picks:
                    px = mkt.trade_open(cid, i)
                    if px is None:
                        continue
                    cur_val = pos.get(cid, 0.0) * px
                    deficit = target[cid] - cur_val
                    if deficit <= 0.01:
                        continue
                    buy_val = min(deficit, cash / (1.0 + COST))
                    if buy_val <= 0.01:
                        continue
                    fee = buy_val * COST
                    cash -= buy_val + fee
                    res.costs += fee
                    res.orders += 1
                    sh_new = buy_val / px
                    old_sh = pos.get(cid, 0.0)
                    if old_sh > 0 and cid in entry_avg:
                        entry_avg[cid] = (entry_avg[cid] * old_sh
                                          + px * sh_new) / (old_sh + sh_new)
                    else:
                        entry_avg[cid] = px
                    pos[cid] = old_sh + sh_new

        # ---- daily close ------------------------------------------------
        eq_close = cash + sum(sh * mkt.value_close(cid, i)
                              for cid, sh in pos.items())
        res.curve.append((d, eq_close))
        if floor is not None and eq_close <= floor:
            pending_liq = True
            if i == i1:
                tot = cash
                for cid, sh in list(pos.items()):
                    v = mkt.value_close(cid, i)
                    if v > 0:
                        tot += sh * v * (1 - COST)
                        res.costs += sh * v * COST
                        res.orders += 1
                res.final = tot
                res.halt_date = d
                pos.clear()
                break

    if res.final is None:
        res.final = res.curve[-1][1]
    peak = -1.0
    for d, eq in res.curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
    if res.rebalances:
        res.avg_n_rankable = round(res._rank_sum / res.rebalances, 2)
    return res


def btc_hold(mkt, start_d, end_d):
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    buy_px = mkt.trade_open(1, i0)
    sh = (POT * (1 - COST)) / buy_px
    peak, dd, final = -1.0, 0.0, None
    for i in range(i0, i1 + 1):
        v = sh * mkt.closes_ff[1][i] * (1 - COST)
        final = v
        peak = max(peak, v)
        if peak > 0:
            dd = min(dd, v / peak - 1.0)
    return final, dd


def years_between(a, b):
    return (datetime.strptime(b, "%Y-%m-%d")
            - datetime.strptime(a, "%Y-%m-%d")).days / 365.25


def summ(r, yrs, btc, btc_dd):
    return {
        "final": round(r.final, 2),
        "ret_pct": round((r.final / POT - 1) * 100, 2),
        "cagr_pct": round(((r.final / POT) ** (1 / yrs) - 1) * 100, 2)
        if r.final > 0 else -100.0,
        "max_dd_pct": round(r.max_dd * 100, 2),
        "orders": r.orders, "costs": round(r.costs, 2),
        "halt_date": r.halt_date,
        "rebalances": r.rebalances,
        "avg_n_rankable": r.avg_n_rankable,
        "n_events": len(r.events), "events": r.events,
        "resurrections": r.resurrections,
        "btc_final": round(btc, 2),
        "btc_ret_pct": round((btc / POT - 1) * 100, 2),
        "btc_max_dd_pct": round(btc_dd * 100, 2),
        "beats_btc": r.final > btc,
        "curve": [[d, round(e, 4)] for d, e in r.curve],
    }


def pct(sorted_vals, q):
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    f = pos - lo
    return sorted_vals[lo] * (1 - f) + sorted_vals[hi] * f


def main():
    with open(os.path.join(V4DATA, "snapshots.json")) as f:
        snaps = json.load(f)
    snaps_by_date = []
    for month in sorted(snaps):
        info = snaps[month]
        sd = info["snapshot_date"]
        sd = f"{sd[:4]}-{sd[4:6]}-{sd[6:8]}"
        ids = [c["cmc_id"] for c in info["top20"]]
        rk = {c["cmc_id"]: c["rank"] for c in info["top20"]}
        snaps_by_date.append((sd, ids, rk))
    snaps_by_date.sort()

    reg = build_registry(snaps)
    mkt = Market(reg)
    reg_summary = {}
    for cid, info in sorted(reg.items()):
        rows = info["rows"]
        reg_summary[str(cid)] = {
            "symbol": info["symbol"], "slug": info["slug"],
            "source": info["source"], "reason": info["reason"],
            "bars": len(rows),
            "first": rows[0]["d"] if rows else None,
            "last": rows[-1]["d"] if rows else None}
    n_excl = sum(1 for v in reg_summary.values()
                 if v["source"] == "excluded")
    print(f"registry: {len(reg_summary)} coins, {n_excl} excluded",
          flush=True)

    out = {"family": "crypto-basket (LTW) — CONSTRUCTED long leg",
           "cost_rate_per_side": COST, "pot": POT,
           "registry": reg_summary, "runs": {}, "placebos": {}}
    ranked_finals = {}

    for wname, (sd, ed) in WINDOWS.items():
        yrs = years_between(sd, ed)
        btc, btc_dd = btc_hold(mkt, sd, ed)
        for cadence in ("weekly", "monthly"):
            for ruleset in ("native", "v9"):
                for h in HORIZONS:
                    key = f"{wname}|mom{h}d|{cadence}|{ruleset}"
                    r = simulate(mkt, snaps_by_date, sd, ed, "momentum",
                                 horizon=h, cadence=cadence,
                                 ruleset=ruleset)
                    out["runs"][key] = summ(r, yrs, btc, btc_dd)
                    out["runs"][key]["picks_log"] = r.picks_log
                    if cadence == "weekly" and ruleset == "native":
                        ranked_finals[(wname, h)] = r.final
                    print(f"{key}: ${r.final:.2f} DD {r.max_dd*100:.1f}% "
                          f"orders {r.orders} costs ${r.costs:.2f} "
                          f"halt {r.halt_date} BTC ${btc:.2f}", flush=True)
                # size (weekly cadence only — size is a level, cadence
                # grid adds nothing the spec requires; monthly size run too
                # for symmetry of the grid)
                key = f"{wname}|size-truncated|{cadence}|{ruleset}"
                r = simulate(mkt, snaps_by_date, sd, ed, "size",
                             cadence=cadence, ruleset=ruleset)
                out["runs"][key] = summ(r, yrs, btc, btc_dd)
                out["runs"][key]["picks_log"] = r.picks_log
                print(f"{key}: ${r.final:.2f} DD {r.max_dd*100:.1f}% "
                      f"orders {r.orders} costs ${r.costs:.2f} "
                      f"halt {r.halt_date} BTC ${btc:.2f}", flush=True)

    # placebos: weekly, native, momentum horizons, full + validation
    for wname in ("full", "validation"):
        sd, ed = WINDOWS[wname]
        btc, _ = btc_hold(mkt, sd, ed)
        for h in HORIZONS:
            finals, rows = [], []
            for seed in PLACEBO_SEEDS:
                r = simulate(mkt, snaps_by_date, sd, ed, "momentum",
                             horizon=h, cadence="weekly",
                             ruleset="native", mode="placebo", seed=seed)
                finals.append(r.final)
                rows.append({"seed": seed, "final": round(r.final, 2),
                             "max_dd_pct": round(r.max_dd * 100, 2),
                             "orders": r.orders,
                             "costs": round(r.costs, 2)})
            sf = sorted(finals)
            rk = ranked_finals[(wname, h)]
            n_beat = sum(1 for v in finals if rk > v)
            key = f"{wname}|mom{h}d|weekly|native"
            out["placebos"][key] = {
                "n_seeds": len(finals),
                "median_final": round(pct(sf, 0.5), 2),
                "p25_final": round(pct(sf, 0.25), 2),
                "p75_final": round(pct(sf, 0.75), 2),
                "best_final": round(sf[-1], 2),
                "worst_final": round(sf[0], 2),
                "ranked_final": round(rk, 2),
                "ranked_beats_n_of_20": n_beat,
                "btc_final": round(btc, 2),
                "rows": rows}
            print(f"placebo {key}: median ${pct(sf,0.5):.2f} "
                  f"ranked ${rk:.2f} beats {n_beat}/20", flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved results.json")


if __name__ == "__main__":
    main()
