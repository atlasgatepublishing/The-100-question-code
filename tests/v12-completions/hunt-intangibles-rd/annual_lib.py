"""Annual selection chassis on the w04 broad EDGAR stack (read-only) +
family-local EDGAR frames for R&D / advertising / capex. Mirrors the
holdings-piotroski house/native conventions: native = tiered habitat
costs, no floor; house = program costs 0.10%/side + v9 floor checked on
monthly closes vs episode (formation-year) anchor, halt -> cash to next
formation, one restart, second halt ends the run."""
import json, os, sys, random, statistics, importlib.util

ENG = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/engine_w04.py")
spec = importlib.util.spec_from_file_location("engine_w04", ENG)
E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)
E.D = E.Data(); D = E.D
ym = E.ym

_SNAP_CACHE = {}

def load_my_frames(frames_dir):
    out = {}
    for fn in os.listdir(frames_dir):
        if not fn.endswith(".json"): continue
        concept, rest = fn[:-5].rsplit("_", 1)
        year = int(rest[:-1]); kind = rest[-1]
        raw = json.load(open(os.path.join(frames_dir, fn)))
        d = {}
        for e in raw.get("data", []):
            if str(e.get("end", ""))[:4] != str(year): continue
            cik = e["cik"]; v = e["val"]
            if cik not in d or v > d[cik]: d[cik] = v
        out[(concept, year)] = d
    return out

def run_annual(picks_by_F, formations, form, pool_by_F=None, placebo_seed=None):
    """picks_by_F: {F: ranked [cik]} (already count-capped).
    placebo_seed: if set, picks replaced per formation by a random sample
    of pool_by_F[F] of the same size."""
    cash = 100.0; curve = []; total_costs = 0.0; n_orders = 0; yearly = []
    ep_anchor = 100.0; halts = 0; ended = False; halted_year = False
    snaps = _SNAP_CACHE
    def snap(F):
        if F not in snaps: snaps[F] = E.snapshot(F)
        return snaps[F]
    for F in formations:
        s = snap(F)
        picks = list(picks_by_F.get(F, []))
        if placebo_seed is not None:
            pool = list(pool_by_F.get(F, []))
            rng = random.Random(placebo_seed * 7919 + F); rng.shuffle(pool)
            picks = pool[:len(picks)]
        start_val = cash
        if ended or halted_year or not picks:
            yearly.append({"formation": F, "picks": [], "ret": 0.0, "n": 0})
            for mm in [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]:
                curve.append([mm, round(cash, 2)])
            halted_year = False
            continue
        ep_anchor = cash
        w = cash / len(picks); pos = {}
        for c in picks:
            rate = E.cost_rate(s[c]["cap"]) if form == "native" else 0.001
            cost = w * rate; total_costs += cost; n_orders += 1
            pos[c] = (w - cost) / s[c]["px_adj"]
        months = [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        halted_mid = False
        for mm in months:
            val = 0.0
            for c, sh in pos.items():
                p = D.price(c, mm, adj=True)
                if p is None: p = s[c]["px_adj"]
                val += sh * p
            if form == "house" and not halted_mid and val <= 0.85 * ep_anchor:
                # liquidate at this monthly close
                end_val = 0.0
                for c, sh in pos.items():
                    p = D.price(c, mm, adj=True) or s[c]["px_adj"]
                    gross = sh * p; cst = gross * 0.001; total_costs += cst; n_orders += 1
                    end_val += gross - cst
                cash = end_val; halts += 1; halted_mid = True
                if halts >= 2: ended = True
                else: halted_year = True
                curve.append([mm, round(cash, 2)])
                # remaining months of this formation year stay in cash
                rest = months[months.index(mm) + 1:]
                for mm2 in rest: curve.append([mm2, round(cash, 2)])
                break
            curve.append([mm, round(val, 2)])
        if halted_mid:
            yearly.append({"formation": F, "picks": [s[c]["ticker"] for c in picks],
                           "ret": round(cash / start_val - 1, 4) if start_val else 0.0, "n": len(picks), "halted": True})
            continue
        end_val = 0.0
        for c, sh in pos.items():
            p = D.price(c, ym(F + 1, 6), adj=True) or s[c]["px_adj"]
            gross = sh * p
            rate = E.cost_rate(s[c]["cap"]) if form == "native" else 0.001
            cost = gross * rate; total_costs += cost; n_orders += 1; end_val += gross - cost
        cash = end_val
        yearly.append({"formation": F, "picks": [s[c]["ticker"] for c in picks],
                       "ret": round(cash / start_val - 1, 4) if start_val else 0.0, "n": len(picks)})
    peak = 100.0; maxdd = 0.0
    for _, v in curve: peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    return {"final": round(cash, 2), "max_dd": round(maxdd, 4), "costs": round(total_costs, 2),
            "orders": n_orders, "halts": halts, "curve": curve, "yearly": yearly}

def period_stats_annual(curve):
    """Annual tempo distribution from a monthly-marked curve: use the
    June-to-June yearly values embedded in yearly rets instead — here we
    resample curve to June values."""
    june = {}
    for d, v in curve:
        if d[5:7] == "06": june[d[:4]] = v
    keys = sorted(june)
    if len(keys) < 2: return None
    rets = [june[keys[i]] / june[keys[i - 1]] - 1 for i in range(1, len(keys))]
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    peak = 100.0; since = 0; longest = 0
    for _, v in curve:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {"periods": len(rets), "share_positive": round(pos / len(rets), 3),
            "median": round(statistics.median(rets), 4), "best": round(max(rets), 4),
            "worst": round(min(rets), 4), "longest_losing_streak": streak,
            "longest_between_highs_months": longest,
            "average_secondary": round(statistics.mean(rets), 4)}

COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
ROADS_ANNUAL = {"FULL": list(range(2017, 2026)), "CONT": list(range(2019, 2026)), "VAL": list(range(2023, 2026))}
