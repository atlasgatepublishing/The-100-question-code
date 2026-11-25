#!/usr/bin/env python3
"""
GAP TEST A-4 — DISTRESS-RISK AVOIDANCE (Campbell, Hilscher & Szilagyi
2008) — Terry's AI stock app. Simulation only.
NO parameter tuning: the frozen spec from
research/v7-completeness/missing-families.md (Table A, item A-4) is run
ONCE, exactly as published, and judged against the promoted champion.

THE STRATEGY (CHS 2008, "In Search of Distress Risk", Journal of
Finance 63(6)): estimate each firm's 12-month failure probability from
the paper's published dynamic logit; since 1981 the highest-probability
stocks have delivered anomalously LOW returns, so the long leg is the
SAFEST names. Program form (the frozen spec): quarterly, compute the
CHS failure probability for every pond name from EDGAR point-in-time
financials + price bars; hold the 5 LOWEST-probability names, equal
weight.

THE PUBLISHED MODEL (CHS Table IV, 12-month lag column — the column
the Wharton mispricing documentation by Stambaugh, Yu & Yuan uses
verbatim to reproduce the measure):

  pi = -9.16 - 20.26*NIMTAAVG + 1.42*TLMTA - 7.13*EXRETAVG
       + 1.41*SIGMA - 0.045*RSIZE - 2.13*CASHMTA + 0.075*MB
       - 0.058*PRICE
  failure probability = 1 / (1 + exp(-pi))

Variable definitions (CHS appendix + Wharton documentation):
  MTA       = market equity (ME) + total liabilities (TL)
  NIMTA_q   = quarterly net income / MTA at that quarter end
  NIMTAAVG  = geometric weighted average of the last 4 quarterly NIMTA,
              weights prop. to [1, phi^3, phi^6, phi^9],
              phi = 2^(-1/3) (CHS eq. 2; weight halves each quarter)
  TLMTA     = TL / MTA (current)
  EXRET_m   = log(1+R_firm) - log(1+R_SPY) for calendar month m
  EXRETAVG  = geometric weighted average of the last 12 monthly EXRET,
              weights prop. to phi^(j-1), phi = 2^(-1/3) (CHS eq. 3)
  SIGMA     = sqrt(252/(N-1) * sum of squared daily returns) over the
              prior 3 months, centered on zero (CHS appendix formula);
              coded missing with fewer than five nonzero returns
  RSIZE     = log(ME / S&P 500 total market value)   [see R3]
  CASHMTA   = (cash + short-term investments) / MTA (current)
  MB        = ME / adjusted book equity, book equity increased by 10%
              of (ME - BE) and floored at $1mm (Wharton doc)  [see R2]
  PRICE     = log(min(price per share, 15))

PROGRAM FORMAT (identical chassis to the champion / Piotroski runs):
  - Universe: the champion's honest point-in-time top-30 as of Nov 2016.
  - Quarterly selection (first trading day of Jan/Apr/Jul/Oct),
    rebalance at next open; hold top 5, equal weight (target = pot/5;
    unfilled slots stay in cash).
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Protection: PLAIN -15% floor only ($85 on the $100 pot, no ladder).
    Close at/below floor -> liquidate at next open, run ends.
  - Pot: $100 only.
  - Placebo: 20 seeds (1..20) on BOTH windows — random 5 drawn from the
    SAME scored pool the ranked rule picks from at each selection.

POINT-IN-TIME DISCIPLINE (identical to the champion): every fact must
be FILED strictly before the selection date; current balance-sheet
items pass the engine's ~18-month filed-freshness gate (548 days, via
E.pit_value); for any historical period end, the latest filing before
the selection date wins (restatements enter only once filed).

FORCED READINGS (declared here, BEFORE any result; uniform, not tuned):
  R1. Coefficients: CHS Table IV, 12-month lag column, as reproduced
      verbatim in the Wharton mispricing documentation (Stambaugh, Yu
      & Yuan). The spec names this column ("12-month failure
      probability ... published CHS coefficients").
  R2. MB: the paper names MB only as "the market-to-book ratio"; the
      Wharton documentation — the spec's own reproduction source —
      implements it as ME / adjusted book equity, with book equity
      increased by 10% of (ME - BE) "following Campbell, Hilscher, and
      Szilagyi (2008)" and floored at $1 (read as $1,000,000, EDGAR
      values being in dollars). Book equity = the champion's
      StockholdersEquity chain.
  R3. RSIZE denominator: the S&P 500 aggregate market capitalization is
      not available in the program's free caches. RSIZE is computed
      against the aggregate market cap of the 30-name pond at the same
      date. The denominator is COMMON to every name at a date, so the
      cross-sectional sort — the only thing the strategy trades on —
      is identical to the published form; probability LEVELS shift by
      the constant -0.045*log(index/pond) and are reported with this
      caveat attached.
  R4. PRICE uses the program's split/dividend-adjusted closes (the only
      price series the chassis carries). The $15 truncation binds for
      nearly every pond name either way; the reading can matter only
      for a name whose adjusted close is below $15 (GE in early years).
  R5. UNSCORABLE NAMES. A name is excluded from a selection date's
      scored pool — counted and listed, never patched — if any of these
      is missing: the current balance-sheet bundle (TL, cash, book
      equity, shares; each filed < selection date and inside the
      548-day freshness gate), a selection-day close, or any
      firm-specific content in BOTH averaged series at once (no usable
      NIMTA quarter and no usable EXRET month).
      Within the averages, CHS's OWN published missing-data procedure
      applies: a missing NIMTA lag slot, a missing EXRET month, or a
      missing SIGMA is replaced by that component's cross-sectional
      mean across the scored pool at that date (the paper replaces
      missing lags of NIMTA/EXRET and missing SIGMA exactly this way).
      Balance-sheet items are never mean-filled — CHS publish no such
      replacement for them.
  R6. CASH input chain (pick-one per period end, latest filed wins):
      CashAndCashEquivalentsAtCarryingValue (prio 3) >
      CashAndDueFromBanks (prio 2) >
      CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents
      (prio 1). Tagging evidence (inspected before the judged run):
      JPMorgan files its balance-sheet cash ONLY as CashAndDueFromBanks
      after Feb 2019 (its CarryingValue tagging stops with the FY2018
      10-K); BAC/WFC file the same bank line. And after ASU 2016-18,
      GE, MMM, PG, Berkshire and Chevron stop tagging the plain
      CarryingValue line (last filings 2017-2024) and present/tag only
      the combined cash + restricted-cash line — GE's balance sheet
      literally presents that combined line. The combined concept
      includes restricted cash, a small, uniform overstatement against
      Compustat CHEQ; stated, not adjusted. STI chain:
      ShortTermInvestments > AvailableForSaleSecuritiesCurrent >
      MarketableSecuritiesCurrent >
      AvailableForSaleSecuritiesDebtSecuritiesCurrent. A name with no
      STI fact for a period end carries STI = 0 for that end (the
      Compustat CHEQ convention: cash and short-term investments with
      IVST unreported reads as cash only).
  R12. TOTAL LIABILITIES construction. AMZN, WMT, KO, VZ, DIS and
      INTC never tag a plain "Liabilities" total in companyfacts (only
      current/noncurrent pieces, the latter often untagged too), and
      AT&T's total is stale after 2016. Declared construction: TL =
      the filed Liabilities total where tagged; otherwise TL = Assets
      - StockholdersEquity for the same period end, paired from the
      same filing (the accounting identity — both are filed totals,
      so the derived total inherits the later of the two filed dates).
      Direct facts outrank derived rows at equal filed dates. This
      applies to the current bundle and to quarter-end TL alike.
      (Visa and Berkshire remain unscorable on SHARES: the champion's
      own freshness gate rejects Visa's stale share facts, and
      Berkshire's share counts are Class-A-denominated against a
      Class-B price series — the same exclusions the champion's pond
      carries. Not patched, here or there.)
  R7. QUARTERLY NET INCOME series, as known at the selection date:
      direct quarterly facts (NetIncomeLoss > ProfitLoss) with period
      duration 80-100 days; PLUS a derived fourth quarter = full-year
      fact (350-380 days) minus the nine-month fact (260-290 days)
      with the same period start, both filed before the selection
      date, known from the full-year fact's filed date (the standard
      Compustat-quarterly equivalent; EDGAR filers rarely tag Q4
      standalone). Per quarter end, latest filed wins.
  R8. Balance-sheet values AT a quarter end (for NIMTA denominators)
      and shares at a quarter end are taken from facts filed before
      the selection date with period end at that quarter end (shares:
      end within [q-10d, q+45d] to admit dei cover dates, else the
      latest end before q). Later comparative filings restate share
      counts for splits, and latest-filed-wins reads them on the
      current (split-adjusted) basis, consistent with the adjusted
      price series. This program's filed-date discipline governs over
      the Wharton doc's Compustat RDQ/prior-quarter convention.
  R9. WINSORIZATION: per CHS's appendix and the Wharton doc, all
      explanatory variables except PRICE are winsorized cross-
      sectionally at the 5th/95th percentiles of the scored pool at
      each selection date (linear-interpolation percentiles, the
      engine's own _pct). PRICE is truncated at $15 by construction.
  R10. Ties in failure probability are broken alphabetically by ticker
      (a deterministic tie-break the top-5 format forces; with
      continuous probabilities exact ties are not expected).
  R11. EXRET and SIGMA are computed from the program's adjusted daily
      closes (CHS used CRSP returns; SPY is the program's S&P 500).

Runs:
  (0) REPLICATION CHECK — the imported champion engine must reproduce
      the published $544.47 (continuous) and $288.05 (validation) to
      the cent before any variant number is taken.
  (0b) DIAGNOSTIC RUN 1 (preserved as gap-a4-distress-run1-diagnostic
      .log / -results-run1-diagnostic.json): the first execution used
      the single "Liabilities" concept and a two-concept cash chain;
      the exclusion report showed 13 pond names unscorable at most
      dates on tagging grounds alone. The tagging evidence above (R6,
      R12) was inspected and the constructions declared BEFORE the
      judged run; run 1's numbers (FULL $426.04, VALIDATION $171.98
      on the narrowed 17-20-name pool) are disclosed in the report,
      not buried. The judged run below is run ONCE under the declared
      constructions.
  (1) Ranked CHS distress-avoidance: CONTINUOUS 2019-01-02 ->
      2026-11-20 and VALIDATION 2023-01-03 -> 2026-11-20.
  (2) PLACEBO: 20 seeds on BOTH windows, same scored pools.
  (3) WALK-FORWARD: fresh $100 pot per calendar year 2020-2026, vs SPY.
  (4) DISTRIBUTION: the scored failure probabilities at every
      selection date (the spec's stated prior — probabilities bunching
      near zero on mega-caps, leaving no discrimination — is reported
      on the numbers either way).

Judged against the champion (published): validation $288.05 |
continuous $544.47 | placebo beats 18/20 validation (median $201.15)
and 19/20 continuous (median $308.81) | folds 4 wins / 7 | SPY net
$187.77 validation / $313.62 continuous (recomputed in-run as control).

Data: SEC EDGAR companyfacts + Yahoo prices, reused read-only from the
v4 caches (./data and ./value-momentum-honest-data under backtests/v4).
"""
import importlib.util
import json
import math
import os
import random
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
PHI = 2.0 ** (-1.0 / 3.0)          # CHS phi, eqs. (2) and (3)

# CHS Table IV, 12-month lag column (published; Wharton doc verbatim)
COEF = {"const": -9.16, "NIMTAAVG": -20.26, "TLMTA": 1.42,
        "EXRETAVG": -7.13, "SIGMA": 1.41, "RSIZE": -0.045,
        "CASHMTA": -2.13, "MB": 0.075, "PRICE": -0.058}
WINSOR_VARS = ["NIMTAAVG", "TLMTA", "EXRETAVG", "SIGMA", "RSIZE",
               "CASHMTA", "MB"]

def _ord(dstr):
    return _date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()

def _from_ord(o):
    d = _date.fromordinal(o)
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"

# ------------------------------------------- point-in-time fact series
def flow_rows(facts, chain):
    """Duration facts (net income): (filed, start, end, val, prio)."""
    rows = []
    for taxonomy, concept, prio in chain:
        try:
            units = facts["facts"][taxonomy][concept]["units"]
        except KeyError:
            continue
        key = "USD" if "USD" in units else list(units)[0]
        for e in units[key]:
            if "filed" not in e or "val" not in e or "start" not in e or "end" not in e:
                continue
            rows.append((e["filed"], e["start"], e["end"], float(e["val"]), prio))
    return rows

def instant_rows(facts, chain):
    """Instant facts via the engine's own pit_series: (filed, end, val, prio)."""
    rows = []
    for taxonomy, concept, prio in chain:
        rows += E.pit_series(facts, taxonomy, concept, prio=prio)
    return rows

def build_concept_rows(facts, equity_rows):
    """CHS inputs for one ticker as point-in-time row lists.
    'liab' merges direct Liabilities facts (prio 1) with identity-
    derived rows TL = Assets - StockholdersEquity paired from the same
    filing (prio 0) — R12. 'cash'/'sti' follow the R6 chains."""
    direct_liab = instant_rows(facts, [("us-gaap", "Liabilities", 1)])
    assets = instant_rows(facts, [("us-gaap", "Assets", 0)])
    a_by = {}
    for filed, end, val, prio in assets:
        a_by[(filed, end)] = val
    e_by = {}
    for filed, end, val, prio in equity_rows:
        k = (filed, end)
        if k not in e_by or prio > e_by[k][0]:
            e_by[k] = (prio, val)
    derived = []
    for (filed, end), aval in a_by.items():
        if (filed, end) in e_by:
            derived.append((filed, end, aval - e_by[(filed, end)][1], 0))
    return {
        "ni": flow_rows(facts, [("us-gaap", "NetIncomeLoss", 2),
                                ("us-gaap", "ProfitLoss", 1)]),
        "liab": direct_liab + derived,
        "cash": instant_rows(facts, [("us-gaap", "CashAndCashEquivalentsAtCarryingValue", 3),
                                     ("us-gaap", "CashAndDueFromBanks", 2),
                                     ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", 1)]),
        "sti": instant_rows(facts, [("us-gaap", "ShortTermInvestments", 4),
                                    ("us-gaap", "AvailableForSaleSecuritiesCurrent", 3),
                                    ("us-gaap", "MarketableSecuritiesCurrent", 2),
                                    ("us-gaap", "AvailableForSaleSecuritiesDebtSecuritiesCurrent", 1)]),
    }

def _at_end(rows, e_ord, asof, tol=10):
    """Instant value FOR period end e_ord, as known at asof: facts filed
    strictly before asof with end within +/-tol days; latest filed wins,
    then priority, then latest end (the engine's tie-break)."""
    best = None
    for filed, end, val, prio in rows:
        if filed < asof and abs(_ord(end) - e_ord) <= tol:
            key = (filed, prio, end)
            if best is None or key > best[0]:
                best = (key, val)
    return best[1] if best else None

def _shares_at(shares_rows, q_ord, asof):
    """Shares outstanding for quarter end q_ord, as known at asof (R8):
    facts filed < asof with end in [q-10d, q+45d] (dei cover dates sit
    just after quarter end), latest filed wins; else the latest end
    strictly before q filed < asof; else None."""
    best = None
    for filed, end, val, prio in shares_rows:
        if filed < asof and q_ord - 10 <= _ord(end) <= q_ord + 45:
            key = (filed, prio, end)
            if best is None or key > best[0]:
                best = (key, val)
    if best is not None:
        return best[1]
    best = None
    for filed, end, val, prio in shares_rows:
        if filed < asof and _ord(end) < q_ord:
            key = (filed, prio, end)
            if best is None or key > best[0]:
                best = (key, val)
    return best[1] if best else None

def quarter_ni_series(ni_rows, asof):
    """Quarterly net income by period end, as known at asof (R7).
    Returns {end_str: val}: direct 80-100d facts plus derived Q4 =
    FY(350-380d) - 9M(260-290d, same start), known from the FY filed
    date. Per end, the latest filed wins (then priority)."""
    direct, fy, m9 = {}, {}, {}
    for filed, start, end, val, prio in ni_rows:
        if filed >= asof:
            continue
        dur = _ord(end) - _ord(start)
        key = (filed, prio)
        if 80 <= dur <= 100:
            if end not in direct or key > direct[end][0]:
                direct[end] = (key, val)
        elif 350 <= dur <= 380:
            if end not in fy or key > fy[end][0]:
                fy[end] = (key, val, start, filed)
        elif 260 <= dur <= 290:
            k2 = (start, end)
            if k2 not in m9 or key > m9[k2][0]:
                m9[k2] = (key, val)
    out = {e: v for e, (k, v) in direct.items()}
    for end, (key, fval, start, ffiled) in fy.items():
        # nine-month fact: same start, end before the FY end
        cands = [(k, v) for (s, e2), (k, v) in m9.items()
                 if s == start and _ord(e2) < _ord(end)]
        if not cands:
            continue
        k9, v9 = max(cands)
        q4 = fval - v9
        # known from the FY filing; it displaces a direct fact for the
        # same end only if filed later than that fact
        if end in direct and direct[end][0] >= (ffiled, 0):
            continue
        if end not in out or (ffiled, 0) > direct.get(end, (("", -1), 0))[0]:
            out[end] = q4
    return out

# ------------------------------------------------------------ price math
def month_end_closes(bars):
    """{'YYYY-MM': last adjusted close in that calendar month}."""
    out = {}
    for b in bars:
        out[b["d"][:7]] = b["c"]
    return out

def _shift_month(ym, k):
    """Shift a 'YYYY-MM' key by k months (k may be negative)."""
    y, m = int(ym[:4]), int(ym[5:7])
    idx = y * 12 + (m - 1) + k
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"

def exret_months(pb, t, d, spy_me):
    """The 12 completed calendar months before selection date d:
    {month_key: EXRET} with EXRET = log(1+R_firm) - log(1+R_SPY);
    months whose return cannot be computed are absent (R5 fill)."""
    me = month_end_closes(pb.bars[t])
    last_completed = _shift_month(d[:7], -1)
    out = {}
    for j in range(12):
        mk = _shift_month(last_completed, -j)
        pk = _shift_month(mk, -1)
        if mk in me and pk in me and mk in spy_me and pk in spy_me:
            rf = me[mk] / me[pk] - 1.0
            rs = spy_me[mk] / spy_me[pk] - 1.0
            if rf > -1.0 and rs > -1.0:
                out[mk] = math.log(1.0 + rf) - math.log(1.0 + rs)
    return out

def sigma_3m(pb, t, d):
    """CHS SIGMA: sqrt(252/(N-1) * sum r^2) over the prior 3 calendar
    months of daily returns (zero-centered, appendix formula). None if
    fewer than five nonzero returns (CHS's missing rule)."""
    do = _ord(d)
    y, m = int(d[:4]), int(d[5:7])
    m0 = m - 3
    y0 = y
    while m0 <= 0:
        m0 += 12
        y0 -= 1
    start_ord = _date(y0, m0, int(d[8:10])).toordinal()
    bars = pb.bars.get(t, [])
    closes = [b["c"] for b in bars if start_ord - 10 <= _ord(b["d"]) <= do]
    # keep only returns whose END date is inside the 3-month window
    dates = [b["d"] for b in bars if start_ord - 10 <= _ord(b["d"]) <= do]
    rets = []
    for i in range(1, len(closes)):
        if _ord(dates[i]) > start_ord:
            rets.append(closes[i] / closes[i - 1] - 1.0)
    nz = sum(1 for r in rets if r != 0.0)
    if nz < 5 or len(rets) < 2:
        return None
    ss = sum(r * r for r in rets)
    return math.sqrt(252.0 / (len(rets) - 1) * ss)

# ------------------------------------------------------------- selection
SELECTION_CACHE = {}

def compute_selection(pb, d, data, spy_me):
    """CHS failure probability for every pond name at selection date d
    (cached per date — ranked and placebo pots share the identical
    scored pool). Returns {scored: {t: {prob, logit, inputs...}},
    picks: [5 lowest-probability tickers], excluded: {t: reason}}."""
    if d in SELECTION_CACHE:
        return SELECTION_CACHE[d]

    # ---- pass 1: raw inputs per name
    raw = {}
    excluded = {}
    pond_me = {}
    for t in UNIVERSE:
        rows = data["concepts"][t]
        tl = E.pit_value(rows["liab"], d)
        cashv = E.pit_value(rows["cash"], d)
        stiv = E.pit_value(rows["sti"], d)
        be = E.pit_value(data["equity"].get(t, []), d)
        so = E.pit_value(data["shares"].get(t, []), d)
        px = pb.close_on_or_before(t, d)
        if px is not None and so is not None and so[2] > 0:
            pond_me[t] = so[2] * px
        missing = []
        if tl is None:
            missing.append("TL")
        if cashv is None:
            missing.append("CASH")
        if be is None:
            missing.append("BE")
        if so is None or so[2] <= 0:
            missing.append("SHARES")
        if px is None:
            missing.append("PRICE")
        if missing:
            excluded[t] = "missing current bundle: " + ",".join(missing)
            continue
        me_now = so[2] * px
        mta_now = tl[2] + me_now
        if mta_now <= 0:
            excluded[t] = "non-positive MTA"
            continue
        # NIMTA slots: 4 most recent quarter ends known at d
        niq = quarter_ni_series(rows["ni"], d)
        ends = sorted(niq.keys(), reverse=True)[:4]
        nimta_slots = []
        for e in ends:
            eo = _ord(e)
            tl_q = _at_end(rows["liab"], eo, d)
            sh_q = _shares_at(data["shares"].get(t, []), eo, d)
            px_q = pb.close_on_or_before(t, e)
            if tl_q is None or sh_q is None or px_q is None or sh_q <= 0:
                nimta_slots.append(None)
            else:
                mta_q = tl_q + sh_q * px_q
                nimta_slots.append(niq[e] / mta_q if mta_q > 0 else None)
        while len(nimta_slots) < 4:
            nimta_slots.append(None)
        exr = exret_months(pb, t, d, spy_me)
        sig = sigma_3m(pb, t, d)
        if all(v is None for v in nimta_slots) and not exr:
            excluded[t] = "no NIMTA quarters and no EXRET months"
            continue
        be_adj = be[2] + 0.1 * (me_now - be[2])
        if be_adj < 1_000_000.0:
            be_adj = 1_000_000.0
        raw[t] = {
            "nimta_slots": nimta_slots,
            "exret": exr,
            "sigma": sig,
            "TLMTA": tl[2] / mta_now,
            "CASHMTA": (cashv[2] + (stiv[2] if stiv else 0.0)) / mta_now,
            "MB": me_now / be_adj,
            "PRICE": math.log(min(px, 15.0)),
            "me": me_now,
            "ni_ends": ends,
        }

    # ---- pass 2: CHS cross-sectional-mean fill for missing components
    last_completed = _shift_month(d[:7], -1)
    month_keys = [_shift_month(last_completed, -j) for j in range(12)]
    slot_means = []
    for j in range(4):
        vals = [r["nimta_slots"][j] for r in raw.values()
                if r["nimta_slots"][j] is not None]
        slot_means.append(sum(vals) / len(vals) if vals else None)
    month_means = {}
    for mk in month_keys:
        vals = [r["exret"][mk] for r in raw.values() if mk in r["exret"]]
        month_means[mk] = (sum(vals) / len(vals)) if vals else None
    sig_vals = [r["sigma"] for r in raw.values() if r["sigma"] is not None]
    sig_mean = (sum(sig_vals) / len(sig_vals)) if sig_vals else None

    pond_total = sum(pond_me.values())
    scored = {}
    for t, r in raw.items():
        slots = []
        ok = True
        for j in range(4):
            v = r["nimta_slots"][j]
            if v is None:
                v = slot_means[j]
            if v is None:
                ok = False
                break
            slots.append(v)
        if not ok:
            excluded[t] = "NIMTA slot with no cross-sectional mean"
            continue
        wq = [(1.0 - PHI ** 3) / (1.0 - PHI ** 12) * PHI ** (3 * j)
              for j in range(4)]
        nimtaavg = sum(w * v for w, v in zip(wq, slots))
        exw = [(1.0 - PHI) / (1.0 - PHI ** 12) * PHI ** j for j in range(12)]
        exsum, wsum = 0.0, 0.0
        for j, mk in enumerate(month_keys):
            v = r["exret"].get(mk)
            if v is None:
                v = month_means[mk]
            if v is None:
                ok = False
                break
            exsum += exw[j] * v
            wsum += exw[j]
        if not ok:
            excluded[t] = "EXRET month with no cross-sectional mean"
            continue
        exretavg = exsum  # weights already normalized over 12 months
        sig = r["sigma"] if r["sigma"] is not None else sig_mean
        if sig is None:
            excluded[t] = "SIGMA unavailable pond-wide"
            continue
        scored[t] = {
            "NIMTAAVG": nimtaavg, "TLMTA": r["TLMTA"],
            "EXRETAVG": exretavg, "SIGMA": sig,
            "RSIZE": math.log(r["me"] / pond_total) if pond_total > 0 else None,
            "CASHMTA": r["CASHMTA"], "MB": r["MB"], "PRICE": r["PRICE"],
            "nimta_slots": r["nimta_slots"], "ni_ends": r["ni_ends"],
            "n_exret_months": len(r["exret"]),
            "sigma_filled": r["sigma"] is None,
        }
        if scored[t]["RSIZE"] is None:
            del scored[t]
            excluded[t] = "no pond market-cap total"

    # ---- pass 3: winsorize (R9), logit, probability, rank ascending
    if scored:
        for var in WINSOR_VARS:
            vals = sorted(s[var] for s in scored.values())
            lo = E._pct(vals, 0.05)
            hi = E._pct(vals, 0.95)
            for s in scored.values():
                s[var + "_raw"] = s[var]
                s[var] = min(max(s[var], lo), hi)
        for t, s in scored.items():
            pi = (COEF["const"] + COEF["NIMTAAVG"] * s["NIMTAAVG"]
                  + COEF["TLMTA"] * s["TLMTA"]
                  + COEF["EXRETAVG"] * s["EXRETAVG"]
                  + COEF["SIGMA"] * s["SIGMA"]
                  + COEF["RSIZE"] * s["RSIZE"]
                  + COEF["CASHMTA"] * s["CASHMTA"]
                  + COEF["MB"] * s["MB"]
                  + COEF["PRICE"] * s["PRICE"])
            s["logit"] = pi
            s["prob"] = 1.0 / (1.0 + math.exp(-pi)) if pi > -700 else 0.0
        picks = sorted(scored, key=lambda t: (scored[t]["prob"], t))[:5]
    else:
        picks = []
    sel = {"scored": scored, "picks": picks, "excluded": excluded}
    SELECTION_CACHE[d] = sel
    return sel

# ------------------------------------------------------------------ engine
def run_pot_chs(pb, data, spy_me, start, end, start_cash,
                floor0, ladder, placebo_rng=None, label="",
                quiet=False, record_pools=False):
    """Champion run_pot (value-momentum-plainfloor.py) copied verbatim
    EXCEPT the selection scoring block: scored pool = names with a
    computable CHS failure probability under the declared readings;
    ranked picks = 5 LOWEST probabilities; placebo picks = random
    sample of the same scored pool. Each pick's target is pot/5
    (unfilled slots stay in cash). Execution, costs, floor, halt and
    liquidation mechanics are unchanged."""
    cash = start_cash
    floor = floor0
    positions = {}  # ticker -> shares
    trades = []     # (date, ticker, side, shares, price, value, cost)
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []      # (date, close equity) — instrumentation only
    pools = []      # (date, scored probs, picks)
    sel_dates = E.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None  # list of (ticker, target_value) to execute at next open

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        """Execute at open of day d toward target dollar values (dict t->value).
        Sells first, then buys. Returns total cost."""
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        # sells / trims
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        # buys
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for di, d in enumerate(days):
        # execute pending rebalance at today's open
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        # selection day: compute targets from data filed before today
        if d in sel_set:
            sel = compute_selection(pb, d, data, spy_me)
            scored = sel["scored"]
            if len(scored) >= 1:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scored),
                                               min(5, len(scored)))
                else:
                    picks = sel["picks"]
                if record_pools:
                    pools.append((d,
                                  {t: round(scored[t]["prob"], 8) for t in scored},
                                  {t: scored[t]["logit"] for t in scored},
                                  list(sel["excluded"].keys()),
                                  list(picks)))
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} scored={len(scored)} "
                          f"excluded={len(sel['excluded'])} picks={picks} "
                          f"pot=${pv:,.2f}", flush=True)
        # end of day: ladder then floor check
        v = portfolio_close(d)
        curve.append((d, v))
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor:
                floor = newfloor
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            # liquidate at next open
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": pools, "curve": curve}
    # end of window: liquidate at final close
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "pools": pools, "curve": curve}

def curve_stats(r):
    curve = r["curve"]
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"max_drawdown_pct": round(maxdd * 100, 2), "max_drawdown_date": maxdd_d,
            "orders": len(r["trades"]), "costs": round(r["costs"], 2),
            "halted": r["halted"], "final": round(r["final"], 2)}

def placebo_block(pb, data, spy_me, ws, we, ranked_final, tag):
    finals, prow = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        rp = run_pot_chs(pb, data, spy_me, ws, we, START_CASH, FLOOR0, LADDER,
                         placebo_rng=rng, label=f"{tag} PLACEBO s{seed}",
                         quiet=True)
        finals.append(rp["final"])
        prow.append({"seed": seed, "final": round(rp["final"], 2),
                     "ret_pct": round((rp["final"] / START_CASH - 1) * 100, 2),
                     "costs": round(rp["costs"], 2),
                     "orders": len(rp["trades"]), "halted": rp["halted"]})
        print(f"  [{tag}] placebo seed {seed:2d}: final=${rp['final']:,.2f} "
              f"halted={rp['halted']} orders={len(rp['trades'])}", flush=True)
    sfin = sorted(finals)
    n_beat = sum(1 for v in finals if ranked_final > v)
    dist = {"n_seeds": len(finals),
            "median_final": round(E._pct(sfin, 0.50), 2),
            "p25_final": round(E._pct(sfin, 0.25), 2),
            "p75_final": round(E._pct(sfin, 0.75), 2),
            "best_final": round(sfin[-1], 2),
            "worst_final": round(sfin[0], 2),
            "mean_final": round(sum(finals) / len(finals), 2),
            "n_halted": sum(1 for r_ in prow if r_["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_minus_median": round(ranked_final - E._pct(sfin, 0.50), 2),
            "ranked_beats_n_of_20": n_beat,
            "ranked_percentile": round(100.0 * n_beat / len(finals), 1),
            "rows": prow}
    print(f"== {tag} PLACEBO_DIST median=${dist['median_final']:,.2f} "
          f"p25=${dist['p25_final']:,.2f} p75=${dist['p75_final']:,.2f} "
          f"best=${dist['best_final']:,.2f} worst=${dist['worst_final']:,.2f} "
          f"halted={dist['n_halted']}/20 | ranked=${ranked_final:,.2f} "
          f"beats {n_beat}/20 ({dist['ranked_percentile']}th pct)", flush=True)
    return dist

# --------------------------------------------------------------------- main
def main():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}   # carried over verbatim from champion
    equity_rows, shares_rows, concepts = {}, {}, {}
    missing = []
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        eq = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
              E.pit_series(facts, "us-gaap",
                           "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                           prio=1))
        so = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
              E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
              E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        equity_rows[t], shares_rows[t] = eq, so
        concepts[t] = build_concept_rows(facts, eq)
        thin = [k for k, v in concepts[t].items() if not v]
        if thin:
            missing.append((t, thin))
        print(f"{t}: equity={len(eq)} shares={len(so)} " +
              " ".join(f"{k}={len(v)}" for k, v in concepts[t].items()), flush=True)
        time.sleep(0.05)
    if missing:
        print("EMPTY CONCEPT SERIES:", missing, flush=True)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
        print(f"{t}: {len(bars[t])} bars {bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = E.PriceBook(bars)
    data = {"equity": equity_rows, "shares": shares_rows, "concepts": concepts}
    spy_me = month_end_closes(bars["SPY"])

    FULL = ("2019-01-02", "2026-11-20")
    VAL = ("2023-01-03", "2026-11-20")
    out = {"variant": "CHS (2008) distress-risk avoidance: quarterly CHS "
                      "12-month failure probability (Table IV coefficients), "
                      "hold 5 LOWEST-probability names, equal weight, "
                      "plain -15% floor",
           "baseline": "promoted value+momentum (B/M + 12-1 momentum), plain floor",
           "coefficients": COEF,
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "placebo_seeds": PLACEBO_SEEDS}

    # ---- (0) replication check: imported champion engine, published numbers
    rep = {}
    for tag, (ws, we), published in (("FULL", FULL, 544.47), ("VALIDATION", VAL, 288.05)):
        rb = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, label=f"REPLICATION CHAMPION {tag}", quiet=True)
        rep[tag] = {"final": round(rb["final"], 2), "published": published,
                    "match": round(rb["final"], 2) == published,
                    "orders": len(rb["trades"]), "halted": rb["halted"]}
        print(f"== REPLICATION champion {tag}: final=${rb['final']:,.2f} "
              f"published=${published:,.2f} match={rep[tag]['match']}", flush=True)
    out["replication_champion"] = rep

    # ---- (1) ranked CHS runs
    ranked = {}
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        r = run_pot_chs(pb, data, spy_me, ws, we, START_CASH, FLOOR0, LADDER,
                        label=f"CHS {tag}", record_pools=True)
        diag = E.diagnostics(r, FLOOR0)
        ranked[tag] = r["final"]
        out[f"ranked_{tag}"] = {"final": round(r["final"], 2),
                                "ret_pct": round((r["final"] / START_CASH - 1) * 100, 2),
                                "costs": round(r["costs"], 2),
                                "orders": len(r["trades"]), "halted": r["halted"],
                                "halt_info": r["halt_info"], "spy_net": round(s, 2),
                                "diag": diag, "pools": r["pools"],
                                "trades": r["trades"]}
        print(f"== CHS {tag} final=${r['final']:,.2f} costs=${r['costs']:,.2f} "
              f"orders={len(r['trades'])} halted={r['halted']} | SPY net=${s:,.2f} "
              f"| maxDD={diag['max_drawdown_pct']}%", flush=True)

    # ---- (2) placebo on both windows (same scored pools as ranked)
    out["placebo_VALIDATION"] = placebo_block(pb, data, spy_me, VAL[0], VAL[1],
                                              ranked["VALIDATION"], "VALIDATION")
    out["placebo_FULL"] = placebo_block(pb, data, spy_me, FULL[0], FULL[1],
                                        ranked["FULL"], "FULL")

    # ---- (3) walk-forward folds, fresh $100 per calendar year 2020-2026
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot_chs(pb, data, spy_me, fs, fe, START_CASH, FLOOR0, LADDER,
                         label=f"FOLD {y}", quiet=True)
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        fst = curve_stats(fr)
        row = {"year": y, "start": fs, "end": fe, "final": fst["final"],
               "return_pct": round(fr["final"] / START_CASH * 100 - 100, 2),
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"]}
        folds.append(row)
        print(f"FOLD {y}: CHS ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) vs "
              f"SPY ${fspy:,.2f} ({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"maxDD={row['max_drawdown_pct']}% orders={row['orders']} halted={row['halted']}",
              flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    print(f"FOLD RECORD: {out['fold_record']} (champion: 4 wins, 3 losses)", flush=True)

    # ---- (4) distribution of scored failure probabilities + coverage
    all_probs, per_date, pick_counts, excl_counts = [], [], {}, {}
    pool_sizes = {}
    for d, sel in sorted(SELECTION_CACHE.items()):
        probs = sorted(s["prob"] for s in sel["scored"].values())
        pool_sizes[d] = len(probs)
        if probs:
            all_probs += probs
            per_date.append({
                "date": d, "n_scored": len(probs),
                "min": probs[0], "p25": E._pct(probs, 0.25),
                "median": E._pct(probs, 0.50), "p75": E._pct(probs, 0.75),
                "max": probs[-1], "spread_pp": (probs[-1] - probs[0]) * 100.0,
                "iqr_pp": (E._pct(probs, 0.75) - E._pct(probs, 0.25)) * 100.0})
        for t in sel["picks"]:
            pick_counts[t] = pick_counts.get(t, 0) + 1
        for t, why in sel["excluded"].items():
            excl_counts.setdefault(t, []).append([d, why])
    sp = sorted(all_probs)
    dist = {"n_selection_dates": len(SELECTION_CACHE),
            "pool_sizes": pool_sizes,
            "n_scored_obs": len(sp),
            "pooled": {"min": sp[0], "p25": E._pct(sp, 0.25),
                       "median": E._pct(sp, 0.50), "p75": E._pct(sp, 0.75),
                       "max": sp[-1], "mean": sum(sp) / len(sp)} if sp else None,
            "per_date": per_date,
            "mean_spread_pp": (sum(r["spread_pp"] for r in per_date) / len(per_date)) if per_date else None,
            "mean_iqr_pp": (sum(r["iqr_pp"] for r in per_date) / len(per_date)) if per_date else None,
            "n_dates_spread_lt_1pp": sum(1 for r in per_date if r["spread_pp"] < 1.0),
            "n_dates_spread_lt_5pp": sum(1 for r in per_date if r["spread_pp"] < 5.0),
            "pick_counts": dict(sorted(pick_counts.items(), key=lambda kv: -kv[1])),
            "excluded": excl_counts}
    out["distribution"] = dist
    print(f"DISTRIBUTION: {dist['n_selection_dates']} dates, "
          f"{dist['n_scored_obs']} scored obs; pooled median prob="
          f"{dist['pooled']['median']:.6f} p25={dist['pooled']['p25']:.6f} "
          f"p75={dist['pooled']['p75']:.6f} max={dist['pooled']['max']:.6f}; "
          f"mean spread={dist['mean_spread_pp']:.2f}pp mean IQR={dist['mean_iqr_pp']:.2f}pp; "
          f"dates with spread<1pp: {dist['n_dates_spread_lt_1pp']}, <5pp: "
          f"{dist['n_dates_spread_lt_5pp']}", flush=True)
    print(f"PICKS: {dist['pick_counts']}", flush=True)
    print(f"EXCLUDED: { {t: len(v) for t, v in excl_counts.items()} }", flush=True)

    with open(os.path.join(HERE, "gap-a4-distress-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
