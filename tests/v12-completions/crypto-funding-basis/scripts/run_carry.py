#!/usr/bin/env python3
"""crypto-funding-basis — paper-record run of the documented funding-carry forms.
Spec: ../CONSTRUCTION-SPEC.md (frozen before this run). Forms:
  A always-on long-spot/short-perp carry (published form)
  B funding-sign gate (CONSTRUCTED 7d trailing-mean gate) + 20 shuffled-gate placebos
Capital: $100 pot per coin book; $50 spot + $50 margin, 1x short, fixed quantity.
Costs: spot 0.50%/side, perp 0.20%/side. House variant: permanent halt at equity <= $85.
Native tempo for period stats: monthly (funding settles 8h; monthly is the reporting
cadence of the source papers and the program)."""
import json, os, math, random
import pandas as pd, numpy as np

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
POT = 100.0
SPOT_FEE, PERP_FEE = 0.005, 0.002
END = pd.Timestamp("2026-10-31 23:59:59", tz="UTC")

def load(coin):
    f = pd.read_csv(os.path.join(DATA, f"{coin}_funding.csv"))
    f["t"] = pd.to_datetime(f["calc_time"], unit="ms", utc=True)
    k = pd.read_csv(os.path.join(DATA, f"{coin}_klines8h.csv"))
    k["t"] = pd.to_datetime(k["open_time"], unit="ms", utc=True)
    k = k.set_index("t")["open"]
    f = f[f["t"] <= END].sort_values("t")
    # mark price at funding instant: Binance calc_time carries ms jitter past the
    # 8h boundary, so floor to the 8h bar and use that bar's OPEN (price at the
    # settlement instant). An exact-timestamp join silently dropped ~45% of
    # events in the first pass; that pass's numbers were discarded, not patched.
    f["bar_t"] = f["t"].dt.floor("8h")
    f["mark"] = f["bar_t"].map(k)
    n0 = len(f)
    f = f.dropna(subset=["mark"]).reset_index(drop=True)
    print("load", f.name if hasattr(f, "name") else "", "events kept", len(f), "of", n0)
    return f

def run_book(f, start, gate=None, house=False):
    """gate: array of bool per funding event (True = book ON for the interval ending
    at the NEXT event; decision at event i uses data <= i). Returns equity series
    indexed by funding time, plus stats."""
    idx = f.index[f["t"] >= start]
    if len(idx) == 0:
        return None
    i0 = idx[0]
    eq = POT
    on = False
    qty = 0.0
    cash_curve = []
    total_fees = 0.0
    funding_net = 0.0
    n_switch = 0
    halted = False
    for pos, i in enumerate(idx):
        want = True if gate is None else bool(gate[i])
        if pos == 0:
            want = True if gate is None else want
        if want and not on:
            p = f.at[i, "mark"]
            notional = (eq / 2.0)
            qty = notional / p
            fees = notional * SPOT_FEE + notional * PERP_FEE
            eq -= fees; total_fees += fees; on = True; n_switch += 1
        elif on and not want:
            p = f.at[i, "mark"]
            notional = qty * p
            fees = notional * SPOT_FEE + notional * PERP_FEE
            eq -= fees; total_fees += fees; on = False; qty = 0.0; n_switch += 1
        if on:
            pay = qty * f.at[i, "mark"] * f.at[i, "last_funding_rate"]
            eq += pay; funding_net += pay
        cash_curve.append((f.at[i, "t"], eq))
        if house and eq <= 85.0:
            halted = True
            # book closed at halt: charge exit fees if on
            if on:
                notional = qty * f.at[i, "mark"]
                fees = notional * SPOT_FEE + notional * PERP_FEE
                eq -= fees; total_fees += fees
                cash_curve[-1] = (f.at[i, "t"], eq)
            break
    # final liquidation if still on (only for non-halted full runs)
    if on and not halted:
        i = idx[-1]
        notional = qty * f.at[i, "mark"]
        fees = notional * SPOT_FEE + notional * PERP_FEE
        eq -= fees; total_fees += fees
        cash_curve[-1] = (f.at[i, "t"], eq)
    s = pd.Series(dict(cash_curve))
    s.index = pd.DatetimeIndex(s.index)
    return {"equity": s, "final": float(eq), "fees": total_fees,
            "funding_net": funding_net, "switches": n_switch, "halted": halted}

def max_dd(s):
    return float((s / s.cummax() - 1).min()) if len(s) else 0.0

def period_stats(s, freq="M"):
    """Actual period-by-period record at monthly tempo from the equity curve."""
    m = s.resample(freq).last().dropna()
    # prepend pot at start
    vals = np.concatenate([[POT], m.values])
    rets = np.diff(vals) / vals[:-1]
    if len(rets) == 0:
        return {}
    win = rets > 0
    # longest losing streak
    longest_loss = cur = 0
    for w in win:
        cur = 0 if w else cur + 1
        longest_loss = max(longest_loss, cur)
    # longest stretch between new highs (in periods)
    peak = vals[0]; since_high = 0; longest_gap = 0
    for v in vals[1:]:
        if v >= peak:
            peak = v; since_high = 0
        else:
            since_high += 1; longest_gap = max(longest_gap, since_high)
    return {"periods": int(len(rets)), "pct_periods_profitable": round(100 * float(win.mean()), 1),
            "median_period_pct": round(100 * float(np.median(rets)), 3),
            "best_period_pct": round(100 * float(rets.max()), 2),
            "worst_period_pct": round(100 * float(rets.min()), 2),
            "longest_losing_streak_periods": int(longest_loss),
            "longest_stretch_between_new_highs_periods": int(longest_gap),
            "mean_period_pct_secondary_average": round(100 * float(rets.mean()), 3)}

def yearly(s):
    out = {}
    m = s.resample("M").last().dropna()
    prev = POT
    for t, v in m.items():
        y = str(t.year)
        if y not in out:
            out[y] = {"start": prev}
        out[y]["end"] = float(v)
        prev = float(v)
    return {y: round(d["end"] / d["start"] * 100 if False else d["end"], 2) for y, d in out.items()}

def btc_hold(f, start):
    sub = f[f["t"] >= start]
    p0, p1 = sub["mark"].iloc[0], sub["mark"].iloc[-1]
    qty = (POT * (1 - SPOT_FEE)) / p0
    final = qty * p1 * (1 - SPOT_FEE)
    s = (sub.set_index("t")["mark"] * qty)
    s.iloc[:] = s.values  # mark-to-market pre-exit-fee
    return {"final": round(float(final), 2), "max_dd": round(100 * max_dd(s), 1),
            "period_stats_monthly": period_stats(s)}

def main():
    results = {"family": "crypto-funding-basis", "label": "PAPER RECORD — not a tradable pot",
               "pot": POT, "costs": {"spot_per_side": SPOT_FEE, "perp_per_side": PERP_FEE},
               "coins": {}}
    basket_curves = {}
    for coin in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        f = load(coin)
        first_full = f["t"].iloc[0]
        results["coins"][coin] = {"data_start": str(first_full), "n_funding_events": int(len(f)),
                                  "mean_funding_8h_pct": round(100 * float(f["last_funding_rate"].mean()), 4),
                                  "pct_events_positive": round(100 * float((f["last_funding_rate"] > 0).mean()), 1)}
        # gate: trailing 21-event mean > 0, strictly past (shift by 1)
        trail = f["last_funding_rate"].rolling(21).mean().shift(1)
        gate = (trail > 0).fillna(True).values
        for wname, start in [("FULL", f["t"].iloc[0]), ("VALera_2023", pd.Timestamp("2023-01-01", tz="UTC"))]:
            if start < f["t"].iloc[0]:
                start = f["t"].iloc[0]
            A = run_book(f, start, gate=None)
            Ah = run_book(f, start, gate=None, house=True)
            B = run_book(f, start, gate=gate)
            Bh = run_book(f, start, gate=gate, house=True)
            # placebos for B: shuffled funding drives the gate, real funding pays
            plac = []
            rng_master = random.Random(42)
            rates = f["last_funding_rate"].values.copy()
            for seed in range(20):
                rng = random.Random(1000 + seed)
                sh = rates.copy(); rng.shuffle(sh)
                tg = pd.Series(sh).rolling(21).mean().shift(1)
                g = (tg > 0).fillna(True).values
                r = run_book(f, start, gate=g)
                plac.append(r["final"])
            entry = {
                "formA_always_on_native": {"final": round(A["final"], 2), "max_dd_pct": round(100 * max_dd(A["equity"]), 2),
                                           "funding_net": round(A["funding_net"], 2), "fees": round(A["fees"], 2),
                                           "period_stats_monthly": period_stats(A["equity"]),
                                           "year_end_equity": yearly(A["equity"])},
                "formA_house_floor": {"final": round(Ah["final"], 2), "halted": Ah["halted"]},
                "formB_funding_sign_gate_constructed": {"final": round(B["final"], 2), "max_dd_pct": round(100 * max_dd(B["equity"]), 2),
                                                        "funding_net": round(B["funding_net"], 2), "fees": round(B["fees"], 2),
                                                        "switches": B["switches"],
                                                        "period_stats_monthly": period_stats(B["equity"]),
                                                        "year_end_equity": yearly(B["equity"])},
                "formB_house_floor": {"final": round(Bh["final"], 2), "halted": Bh["halted"]},
                "formB_placebo_shuffled_gate": {"median_final": round(float(np.median(plac)), 2),
                                                "min_final": round(min(plac), 2), "max_final": round(max(plac), 2),
                                                "real_beats_placebos": int(sum(1 for p in plac if B["final"] > p))},
                "btc_buyhold_bar": btc_hold(f, start) if coin == "BTCUSDT" else None,
                "coin_buyhold": btc_hold(f, start),
            }
            results["coins"][coin][wname] = entry
            if wname == "FULL":
                basket_curves.setdefault("A", {})[coin] = A["equity"]
                basket_curves.setdefault("B", {})[coin] = B["equity"]
    # basket: coins with FULL window from their own start; equity = mean of available books (each $100)
    bk = {}
    for form in ["A", "B"]:
        curves = basket_curves[form]
        df = pd.DataFrame(curves).ffill()
        basket = df.mean(axis=1)
        bk[form] = {"final_mean_of_books": round(float(basket.iloc[-1]), 2),
                    "max_dd_pct": round(100 * max_dd(basket), 2),
                    "period_stats_monthly": period_stats(basket),
                    "note": "each coin book starts at its own first funding month; basket = mean of books present (ffill across 8h grid)"}
    results["basket_FULL"] = bk
    with open(os.path.join(HERE, "..", "results.json"), "w") as fh:
        json.dump(results, fh, indent=1, default=str)
    # save equity curves (monthly) for the period record
    curves_out = {}
    for coin in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        f = load(coin)
        trail = f["last_funding_rate"].rolling(21).mean().shift(1)
        gate = (trail > 0).fillna(True).values
        for form, g in [("A", None), ("B", gate)]:
            r = run_book(f, f["t"].iloc[0], gate=g)
            m = r["equity"].resample("M").last()
            curves_out[f"{coin}_{form}"] = {str(t.date()): round(float(v), 4) for t, v in m.items()}
    with open(os.path.join(HERE, "..", "equity_curves_monthly.json"), "w") as fh:
        json.dump(curves_out, fh, indent=1)
    print(json.dumps({c: {w: results["coins"][c][w]["formA_always_on_native"]["final"] for w in ["FULL", "VALera_2023"]} for c in results["coins"]}, indent=1))
    print("basket", bk)

if __name__ == "__main__":
    main()
