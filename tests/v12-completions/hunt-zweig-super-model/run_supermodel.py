#!/usr/bin/env python3
"""hunt-zweig-super-model — Zweig Super Model (Winning on Wall Street, 1986):
Monetary Model (Prime Rate + Fed Indicator + Installment Debt, 0-8 model
points) + Four Percent momentum leg (+2/0). Buy at total >= 6, sell at <= 3.
All scoring conventions logged in SCORING-CHOICES.md BEFORE this run.
FRED series are data inputs to a backtest; only derived signals are stored."""
import csv, io, json, os, random, urllib.request
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine_core.py")).read())
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ewpond.py")).read())

HERE = os.path.dirname(os.path.abspath(__file__))

def fred(series):
    raw = urllib.request.urlopen(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}", timeout=60).read().decode()
    out = []
    for r in csv.DictReader(io.StringIO(raw)):
        try: out.append((r["observation_date"], float(r[series])))
        except Exception: pass
    out.sort()
    return out

def add_months(dstr, m):
    y, mo, dd = map(int, dstr.split("-"))
    mo2 = mo + m
    y += (mo2 - 1) // 12; mo2 = (mo2 - 1) % 12 + 1
    return date(y, mo2, min(dd, 28)).isoformat()

# ---------- Prime Rate Indicator ----------
def prime_points(dprime):
    """Returns list of (date, points) — points change only on signal dates;
    state carried forward by the caller. Book rules (see SCORING-CHOICES)."""
    pts = 0
    events = []
    peak = trough = None
    seq_dir = 0; seq_count = 0; seq_cum = 0.0
    prev = None
    state = 0  # 0 = sell/neutral(0 pts), 1 = buy(2 pts)
    for d, v in dprime:
        if prev is None:
            prev = v; peak = trough = v; continue
        if v == prev: continue
        direction = 1 if v > prev else -1
        if state == 0:
            peak = max(peak, prev) if peak is not None else prev
            if direction == -1:
                if seq_dir != -1: seq_dir, seq_count, seq_cum = -1, 0, 0.0
                seq_count += 1; seq_cum += prev - v
                base = peak
                if (base < 8.0) or seq_count >= 2 or seq_cum >= 1.0 - 1e-9:
                    state = 1; events.append((d, 2, f"prime BUY (peak {base}%, cuts {seq_count}, cum {seq_cum:.2f})"))
                    trough = v; seq_dir = 0; seq_count = 0; seq_cum = 0.0
            else:
                peak = v; seq_dir = 0; seq_count = 0; seq_cum = 0.0
        else:
            trough = min(trough, prev) if trough is not None else prev
            if direction == 1:
                if seq_dir != 1: seq_dir, seq_count, seq_cum = 1, 0, 0.0
                seq_count += 1; seq_cum += v - prev
                base = trough
                if (base >= 8.0) or seq_count >= 2 or seq_cum >= 1.0 - 1e-9:
                    state = 0; events.append((d, 0, f"prime SELL (trough {base}%, rises {seq_count}, cum {seq_cum:.2f})"))
                    peak = v; seq_dir = 0; seq_count = 0; seq_cum = 0.0
            else:
                trough = v; seq_dir = 0; seq_count = 0; seq_cum = 0.0
        prev = v
    return events

# ---------- Fed Indicator ----------
class FedLeg:
    def __init__(self): self.pts = 0; self.set_date = None
    def move(self, d, direction):
        if direction < 0:  # cut
            self.pts = 2; self.set_date = d
        else:  # hike
            self.pts = -1; self.set_date = d
    def value(self, d):
        if self.set_date is None or self.pts == 0: return 0
        if self.pts == 2:
            if d > add_months(self.set_date, 12): return 0
            if d > add_months(self.set_date, 6): return 1
            return 2
        if self.pts == -1:
            if d > add_months(self.set_date, 6): return 0
            return -1
        return self.pts

def change_events(series, min_step=0.01):
    ev = []
    prev = None
    for d, v in series:
        if prev is not None and abs(v - prev) >= min_step:
            ev.append((d, 1 if v > prev else -1))
        prev = v
    return ev

def main():
    dprime = fred("DPRIME")
    dftar = fred("DFEDTARU")
    disc_m = fred("INTDSRUSM193N")
    totalsl = fred("TOTALSL")
    prime_ev = prime_points(dprime)
    ff_ev = change_events([x for x in dftar if x[0] >= "2008-01-01"])
    # discount: monthly changes through 2021-08, then bridge to FF events
    disc_ev = []
    prev = None
    for d, v in disc_m:
        if prev is not None and abs(v - prev[1]) >= 0.01:
            disc_ev.append((d, 1 if v > prev[1] else -1))
        prev = (d, v)
    disc_last = disc_m[-1][0]
    disc_ev += [(d, dr) for d, dr in ff_ev if d > "2021-08-01"]
    rr_ev = [("2020-03-26", -1)]  # reserve requirements eliminated = cut (easing)
    # weekly evaluation dates from SPY
    spy = load_stock("SPY")
    wk = {}
    for b in spy:
        y, m, dd = map(int, b["d"].split("-"))
        wk[date(y, m, dd).isocalendar()[:2]] = b["d"]
    eval_dates = [wk[k] for k in sorted(wk)]
    # four-percent momentum leg
    ws = ew_pond_weekly()
    fp_targets, fp_events = four_percent_states(ws)
    # installment: YoY with 2-month publication lag
    tsl = {d[:7]: v for d, v in totalsl}
    months_sorted = sorted(tsl)
    def installment_pts(eval_date):
        m = eval_date[:7]
        y, mo = int(m[:4]), int(m[5:7])
        mo -= 2
        while mo <= 0: mo += 12; y -= 1
        key = f"{y:04d}-{mo:02d}"
        y2 = y - 1
        key_prev = f"{y2:04d}-{mo:02d}"
        if key in tsl and key_prev in tsl and tsl[key_prev] > 0:
            yoy = (tsl[key] / tsl[key_prev] - 1.0) * 100.0
            return (2 if yoy < 9.0 else 0), round(yoy, 2)
        return None, None
    legs = {"ff": FedLeg(), "disc": FedLeg(), "rr": FedLeg()}
    ev_map = {"ff": ff_ev, "disc": disc_ev, "rr": rr_ev}
    ev_idx = {"ff": 0, "disc": 0, "rr": 0}
    prime_state = 0; pi = 0
    weekly = []
    for d in eval_dates:
        while pi < len(prime_ev) and prime_ev[pi][0] <= d:
            prime_state = prime_ev[pi][1]; pi += 1
        for k in legs:
            while ev_idx[k] < len(ev_map[k]) and ev_map[k][ev_idx[k]][0] <= d:
                legs[k].move(ev_map[k][ev_idx[k]][0], ev_map[k][ev_idx[k]][1]); ev_idx[k] += 1
        raw = sum(legs[k].value(d) for k in legs)
        fed_model = 4 if raw >= 2 else 2 if raw >= 0 else 1 if raw >= -2 else 0
        inst, yoy = installment_pts(d)
        if inst is None: continue
        monetary = prime_state + fed_model + inst
        mom = 2 if fp_targets.get(d, 0) == 1 else 0
        # four-percent targets keyed by pond week dates may differ by a day; use last fp state on/before d
        weekly.append({"date": d, "prime_pts": prime_state, "fed_raw": raw, "fed_model_pts": fed_model,
                       "installment_pts": inst, "installment_yoy": yoy, "monetary": monetary,
                       "momentum_pts": mom, "super": monetary + mom})
    # momentum leg alignment fix: recompute mom from fp state series directly
    fp_dates = sorted(fp_targets)
    import bisect
    for w in weekly:
        j = bisect.bisect_right(fp_dates, w["date"]) - 1
        w["momentum_pts"] = 2 if (j >= 0 and fp_targets[fp_dates[j]] == 1) else 0
        w["super"] = w["monetary"] + w["momentum_pts"]
    with open(os.path.join(HERE, "signal_series.csv"), "w") as f:
        f.write("date,prime_pts,fed_raw,fed_model_pts,installment_pts,installment_yoy,monetary,momentum_pts,super\n")
        for w in weekly:
            f.write(f"{w['date']},{w['prime_pts']},{w['fed_raw']},{w['fed_model_pts']},{w['installment_pts']},{w['installment_yoy']},{w['monetary']},{w['momentum_pts']},{w['super']}\n")
    def state_machine(score_key, buy_at, sell_at):
        targets = {}; state = 0; events = []
        for w in weekly:
            sc = w[score_key]
            if state == 0 and sc >= buy_at:
                state = 1; events.append([w["date"], "BUY", sc])
            elif state == 1 and sc <= sell_at:
                state = 0; events.append([w["date"], "SELL", sc])
            targets[w["date"]] = state
        return targets, events
    super_targets, super_events = state_machine("super", 6, 3)
    mon_targets, mon_events = state_machine("monetary", 6, 2)
    out = {"family": "hunt-zweig-super-model (Zweig Super Model, 1986)",
           "ledger_disposition": "HUNT-FOUND (deep-hunt-newsletters)",
           "honesty_label": "Scoring per the book as rendered by the InvestStrat worksheet; prose choices logged in SCORING-CHOICES.md before the run; installment leg on revised G.19 with a 2-month lag — FENCED (revision hole)",
           "chassis": "$100; SPY; weekly evaluation at Friday close, trade next session open; 0.10%/side + $0.01 sell fee; native = no floor; house = v9 chassis",
           "holdings_grid": "NOT-APPLICABLE — market timer, no selection",
           "coins": "NOT-APPLICABLE — defined on US monetary series and the Value Line index; no coin analogue published (spec (e))",
           "prime_events": [[d, p, note] for d, p, note in prime_ev],
           "fed_funds_events": ff_ev, "discount_events": disc_ev, "reserve_events": rr_ev,
           "super_events": super_events, "monetary_events": mon_events,
           "weekly_scores_first_last": [weekly[0], weekly[-1]], "roads": {}}
    print("super events:", super_events, flush=True)
    print("monetary events:", mon_events, flush=True)
    def shifted(targets, seed):
        dates = sorted(targets); vals = [targets[d] for d in dates]
        rng = random.Random(seed); k = rng.randrange(1, len(vals))
        vals = vals[k:] + vals[:k]
        return dict(zip(dates, vals))
    for name, (s, e) in ROADS.items():
        rec = {}
        for form, ch in (("native", False), ("house_v9", True)):
            r = simulate_targets(spy, super_targets, s, e, STK_COST, STK_SELL_FEE, chassis=ch)
            rec[form] = {**r, "period_stats_monthly": period_stats(r["equity_curve"], "monthly")}
        rm = simulate_targets(spy, mon_targets, s, e, STK_COST, STK_SELL_FEE)
        rec["monetary_standalone_secondary"] = {"final": rm["final"], "max_dd_pct": rm["max_dd_pct"],
                                                "rule": "Monetary Model alone: buy >= 6, sell <= 2 (published standalone rule, reported for the record)"}
        bh = buy_hold(spy, s, e, STK_COST, STK_SELL_FEE)
        rec["benchmark_hold"] = {"name": "SPY buy-and-hold", "final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                 "period_stats_monthly": period_stats(bh["equity_curve"], "monthly")}
        pf = []
        for seed in range(1, 21):
            pf.append(simulate_targets(spy, shifted(super_targets, seed), s, e, STK_COST, STK_SELL_FEE)["final"])
        rec["placebo_native"] = {"seed_finals": pf, "beaten_of_20": sum(1 for p in pf if rec["native"]["final"] > p),
                                 "design": "circular shift of the weekly in/out state series (20 seeds)"}
        rec["champion_vm"] = CHAMP[name]; rec["spy_program_ref"] = SPYREF[name]
        out["roads"][name] = rec
        print(f"SPY {name}: super native ${rec['native']['final']} house ${rec['house_v9']['final']} monetary-alone ${rm['final']} hold ${rec['benchmark_hold']['final']} placebos {rec['placebo_native']['beaten_of_20']}/20", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
