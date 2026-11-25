#!/usr/bin/env python3
"""V13 BEST RULES — hunt-tax-loss-reversal. Simulation only.
Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES: published January loser trade unchanged (rank pond by Jan->Nov
cumulative return, worst 20, price > $5 raw close at formation, buy at
December close, sell at January close, equal weight, 0.30%/side habitat
costs, zero-on-vanish) + idle capital PARKED IN SPY (0.10%/side + $0.01/sell)
+ NO floor. Cash-idle twin (identical January trades) printed for attribution.
Placebos: 20 random December baskets (n=20) + 11 phase-shifted calendar
variants (same construction, formation at each other month-end).
Data: shared read-only pxfull cache (dividend-adjusted closes), 154-name pond.
"""
import json, os, random, statistics, time
from bisect import bisect_right

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
START = 100.0
COST_BASKET = 0.003   # 0.30%/side, habitat rate (spec choice 7)
COST_SPY = 0.001      # 0.10%/side liquid rate
SELL_FEE = 0.01
N_HOLD = 20
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 142.83, "DECADE": 123.32, "CONT": 101.92, "VAL": 94.11}  # v12 n=10 idle

# ---------- load ----------
def load(tk):
    j = json.load(open(os.path.join(DATA, f"pxfull_{tk}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    dates, A, R = [], [], []
    for i, t in enumerate(ts):
        if adj[i] is None or q["close"][i] is None: continue
        dates.append(time.strftime("%Y-%m-%d", time.gmtime(t))); A.append(float(adj[i])); R.append(float(q["close"][i]))
    return dates, A, R

POND = sorted(fn[len("pxfull_"):-len(".json")] for fn in os.listdir(DATA)
              if fn.startswith("pxfull_") and fn != "pxfull_SPY.json")
SER = {}
for tk in POND + ["SPY"]:
    d, a, r = load(tk); SER[tk] = (d, a, r)
CAL = SER["SPY"][0]  # master calendar = SPY trading days

def price_on(tk, date, raw=False):
    """Last available bar on or before date. Returns (px, bar_date) or (None, None)."""
    d, a, r = SER[tk]
    i = bisect_right(d, date) - 1
    if i < 0: return None, None
    return (r[i] if raw else a[i]), d[i]

def month_last(year, month):
    """Last SPY trading day in given year-month, or None."""
    cand = [d for d in CAL if d[:4] == str(year) and d[5:7] == f"{month:02d}"]
    return cand[-1] if cand else None

def add_months(year, month, k):
    m = month + k; y = year + (m - 1) // 12; m = (m - 1) % 12 + 1
    return y, m

# ---------- formation construction ----------
def formation(form_year, form_month):
    """Returns dict(buy_date, sell_date, ranked=[(ret,tk)...]) or None.
    Rank window: close at month-end (form-11 months) -> close at month-end (form-1 month).
    For December: Jan close -> Nov close of the same year (the published proxy)."""
    buy = month_last(form_year, form_month)
    sy, sm = add_months(form_year, form_month, 1)
    sell = month_last(sy, sm)
    ey, em = add_months(form_year, form_month, -1)
    by, bm = add_months(form_year, form_month, -11)
    rank_end = month_last(ey, em); rank_base = month_last(by, bm)
    if not buy or not sell or not rank_end or not rank_base: return None
    ranked = []
    for tk in POND:
        p_end, _ = price_on(tk, rank_end); p_base, _ = price_on(tk, rank_base)
        p_raw, bd = price_on(tk, buy, raw=True)
        if p_end is None or p_base is None or p_raw is None or bd != buy: continue
        if p_raw <= 5: continue
        ranked.append((p_end / p_base - 1.0, tk))
    ranked.sort()
    return {"buy": buy, "sell": sell, "ranked": ranked}

# ---------- simulation ----------
def simulate(road, form_month=12, seed=None, park=True):
    a, b = ROADS[road]
    days = [d for d in CAL if a <= d <= b]
    forms = {}
    for y in range(int(a[:4]) - 1, int(b[:4]) + 1):
        f = formation(y, form_month)
        if f and a <= f["buy"] and f["sell"] <= b: forms[f["buy"]] = f
    sell_map = {f["sell"]: f for f in forms.values()}
    cash = START; spy_sh = 0.0; pos = {}  # tk -> shares
    costs = 0.0; vanished = 0; legs = []  # per-formation leg record
    leg_open = None; curve = []
    def equity(d):
        eq = cash
        if spy_sh: eq += spy_sh * price_on("SPY", d)[0]
        for tk, sh in pos.items():
            px, bd = price_on(tk, d)
            if px is None or (d > bd and (d[:4] != bd[:4] or True) and _stale(bd, d)): px = 0.0
            eq += sh * (px or 0.0)
        return eq
    for d in days:
        # exits first (a sell date is never a buy date here, but keep order safe)
        if d in sell_map and pos:
            leg_val = 0.0
            for tk, sh in list(pos.items()):
                px, bd = price_on(tk, d)
                if px is None or _stale(bd, d): vanished += 1; px = 0.0
                gross = sh * px; fee = gross * COST_BASKET
                cash += gross - fee; costs += fee; leg_val += gross
                del pos[tk]
            if leg_open is not None:
                spy_px_buy, _ = price_on("SPY", leg_open["buy"]); spy_px_sell, _ = price_on("SPY", d)
                legs.append({"form": leg_open["buy"], "exit": d,
                             "leg_ret_pct": round((cash / leg_open["eq_before"] - 1) * 100, 4) if leg_open["eq_before"] else None,
                             "spy_same_window_pct": round((spy_px_sell / spy_px_buy - 1) * 100, 4)})
                leg_open = None
            if park:
                px, _ = price_on("SPY", d); amt = cash
                spy_sh = amt * (1 - COST_SPY) / px; cash = 0.0; costs += amt * COST_SPY
        if d in forms and not pos:
            f = forms[d]
            eq = equity(d)
            if spy_sh:
                px, _ = price_on("SPY", d); gross = spy_sh * px
                fee = gross * COST_SPY + SELL_FEE; cash += gross - fee; costs += fee; spy_sh = 0.0
                eq = cash
            if seed is not None:
                rng = random.Random(seed * 1000 + int(d[:4]))
                picks = [tk for _, tk in rng.sample(f["ranked"], min(N_HOLD, len(f["ranked"])))]
            else:
                picks = [tk for _, tk in f["ranked"][:N_HOLD]]
            leg_open = {"buy": d, "eq_before": eq, "picks": picks}
            for tk in picks:
                px, _ = price_on(tk, d); amt = eq / len(picks)
                pos[tk] = amt * (1 - COST_BASKET) / px; cash -= amt; costs += amt * COST_BASKET
        if d == days[0] and park and not pos and spy_sh == 0.0 and cash > 0:
            px, _ = price_on("SPY", d); spy_sh = cash * (1 - COST_SPY) / px; costs += cash * COST_SPY; cash = 0.0
        curve.append((d, round(equity(d), 4)))
    # final liquidation mark: curve already marks to market; final = last equity (positions marked, no exit fee on SPY park; basket never open at road end by construction)
    final = curve[-1][1]
    peak = -1.0; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak if peak > 0 else 0.0)
    return {"final": round(final, 2), "max_dd_pct": round(mdd * 100, 2), "costs": round(costs, 2),
            "vanished": vanished, "legs": legs, "curve": curve}

def _stale(bar_date, date):
    """Bar is stale if the ticker has no bar within 15 calendar days before date."""
    if bar_date is None: return True
    from datetime import date as _date
    y1, m1, d1 = map(int, bar_date.split("-")); y2, m2, d2 = map(int, date.split("-"))
    return (_date(y2, m2, d2) - _date(y1, m1, d1)).days > 15

def annual_returns(curve):
    """Full-year returns per calendar year from daily curve (year-end vs prior year-end)."""
    ye = {}
    for d, e in curve: ye[d[:4]] = e
    yrs = sorted(ye); out = []
    prev = START
    # first year measured from road start value: use first curve point's year start = START
    seen_first = curve[0][0][:4]
    for y in yrs:
        out.append((y, ye[y] / prev - 1.0)); prev = ye[y]
    return out

def dist_stats(rets):
    """rets: list of fractional period returns."""
    if not rets: return None
    pos_share = sum(1 for r in rets if r > 0) / len(rets)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    # longest stretch between new highs on the compounded index
    idx = 1.0; peak = 1.0; since_high = 0; longest = 0
    for r in rets:
        idx *= (1 + r)
        if idx >= peak: peak = idx; longest = max(longest, since_high); since_high = 0
        else: since_high += 1
    longest = max(longest, since_high)
    return {"n_periods": len(rets), "median_pct": round(statistics.median(rets) * 100, 2),
            "share_positive_pct": round(pos_share * 100, 1),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_streak": streak, "longest_between_new_highs_periods": longest,
            "mean_pct_secondary": round(statistics.mean(rets) * 100, 2)}

# ---------- run ----------
def main():
    t0 = time.time(); out = {"program": "v13-best-rules", "family": "hunt-tax-loss-reversal",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {"holdings": N_HOLD, "signal": "Jan->Nov cumulative return ascending (worst losers)",
                     "entry": "December close", "exit": "January close", "idle_capital": "SPY parked",
                     "floor": None, "costs_basket": "0.30%/side", "costs_spy": "0.10%/side + $0.01/sell",
                     "start_cash": START},
        "roads": {}}
    for road in ROADS:
        mine = simulate(road, park=True)
        twin = simulate(road, park=False)
        pb = [simulate(road, seed=s, park=True)["final"] for s in range(1, 21)]
        pb_twin = [simulate(road, seed=s, park=False)["final"] for s in range(1, 21)]
        shifts = {}
        for m in range(1, 12):
            shifts[f"form_month_{m:02d}"] = simulate(road, form_month=m, park=True)["final"]
        leg_rets = [l["leg_ret_pct"] / 100 for l in mine["legs"]]
        excess = [(l["leg_ret_pct"] - l["spy_same_window_pct"]) / 100 for l in mine["legs"]]
        entry = {
            "my_rules_parked": {k: mine[k] for k in ("final", "max_dd_pct", "costs", "vanished")},
            "idle_twin": {k: twin[k] for k in ("final", "max_dd_pct", "costs", "vanished")},
            "published_v12_n10_idle": PUBLISHED[road], "spy_ref": SPYREF[road], "champion_vm": CHAMP[road],
            "placebos_random_baskets_parked": pb, "placebos_beaten_parked": sum(1 for x in pb if mine["final"] > x),
            "placebos_random_baskets_idle": pb_twin, "placebos_beaten_idle": sum(1 for x in pb_twin if twin["final"] > x),
            "phase_shifted_placebos_parked": shifts,
            "phase_shifts_beaten": sum(1 for v in shifts.values() if mine["final"] > v),
            "legs": mine["legs"],
            "dist_january_legs": dist_stats(leg_rets),
            "dist_january_excess_vs_spy": dist_stats(excess),
            "dist_parked_annual": dist_stats([r for _, r in annual_returns(mine["curve"])]),
            "dist_idle_annual": dist_stats([r for _, r in annual_returns(twin["curve"])]),
            "curve_parked": mine["curve"], "curve_idle": twin["curve"],
            "beats_champion": mine["final"] > CHAMP[road],
        }
        out["roads"][road] = entry
        print(f"{road}: parked ${mine['final']} (DD {mine['max_dd_pct']}%) idle-twin ${twin['final']} "
              f"pub ${PUBLISHED[road]} SPY ${SPYREF[road]} champ ${CHAMP[road]} | pb beaten parked "
              f"{entry['placebos_beaten_parked']}/20 idle {entry['placebos_beaten_idle']}/20 | "
              f"shifts beaten {entry['phase_shifts_beaten']}/11 | vanished {mine['vanished']} | "
              f"legs {len(mine['legs'])}", flush=True)
    # ---- confirmation (frozen bars in spec s.10) ----
    triggered = [r for r in ROADS if out["roads"][r]["beats_champion"]]
    out["confirmation"] = {"triggered_roads": triggered, "ran": False}
    if triggered:
        out["confirmation"]["ran"] = True
        folds = {}
        for y in range(2017, 2027):
            ROADS[f"F{y}"] = (f"{y}-01-01", f"{y}-12-31")
        # yearly folds use calendar-year roads via simulate with custom road entries
        wins = 0; fold_detail = {}
        for y in range(2017, 2027):
            key = f"F{y}"
            m = simulate(key, park=True)["final"]
            # published form within the fold = idle twin construction at n=10 is not reproduced here;
            # fold comparison per spec is my-rules vs published-form full-year score: published form in a
            # single calendar year = its January leg only (idle twin at N_HOLD=20 differs in count) ->
            # use idle twin n=20 as the conservative stand-in and label it.
            t = simulate(key, park=False)["final"]
            fold_detail[str(y)] = {"my_rules": m, "idle_form_proxy": t}
            if m > t: wins += 1
            del ROADS[key]
        h1 = ("2016-11-21", "2021-11-20"); h2 = ("2021-11-22", "2026-11-20")
        ROADS["H1"], ROADS["H2"] = h1, h2
        hw = 0; half_detail = {}
        for k in ("H1", "H2"):
            m = simulate(k, park=True)["final"]; t = simulate(k, park=False)["final"]
            half_detail[k] = {"my_rules": m, "idle_form_proxy": t}
            if m > t: hw += 1
        del ROADS["H1"], ROADS["H2"]
        out["confirmation"].update({"fold_wins_of_10": wins, "half_wins_of_2": hw,
                                    "folds": fold_detail, "halves": half_detail,
                                    "confirmed": wins >= 6 and hw >= 1,
                                    "note": "Fold/half comparison uses the idle twin (same January trades, cash otherwise, n=20) as the published-form stand-in; the true published form (n=10, idle) differs only in basket count."})
        print("CONFIRMATION:", out["confirmation"]["fold_wins_of_10"], "/10 folds,",
              out["confirmation"]["half_wins_of_2"], "/2 halves, confirmed =",
              out["confirmation"]["confirmed"], flush=True)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print(f"DONE {time.time()-t0:.1f}s", flush=True)

if __name__ == "__main__":
    main()
