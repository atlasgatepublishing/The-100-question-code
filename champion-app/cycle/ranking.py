"""The champion's ranking for a single selection date (new code).

The frozen champion original computes its ranking inside run_pot()
over a whole window. A daily cycle needs the ranking for ONE date.
This module produces it by calling the vendored original's own
helpers (pit_value, percentile_ranks, PriceBook) and following
run_pot()'s scoring block step for step: book to market from point in
time EDGAR equity and shares, 12 minus 1 month momentum from the
price bars, percentile average of the two, top five. Names that
cannot be scored are excluded, never patched, exactly as in the
original. The equivalence is not asserted, it is tested:
cycle/test_cycle.py runs run_pot() with record_pools=True over the
published windows and checks that rank_on_date() returns the
original's own recorded picks at every selection date.
"""
from __future__ import annotations

from engines import vm as _vm

UNIVERSE = list(_vm._orig().UNIVERSE)


def champion_module():
    """The vendored champion original (loaded by engines.vm)."""
    return _vm._orig()


def build_price_book(prices: dict) -> object:
    champ = champion_module()
    return champ.PriceBook(prices)


def fundamentals_from_facts(facts_by_ticker: dict) -> tuple[dict, dict]:
    """Build (equity_rows, shares_rows) from EDGAR companyfacts dicts,
    with the original's exact series merges and priorities (the same
    construction engines/vm.py uses for replay)."""
    champ = champion_module()
    equity_rows, shares_rows = {}, {}
    for t in champ.UNIVERSE:
        facts = facts_by_ticker.get(t) or {}
        equity_rows[t] = (
            champ.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2)
            + champ.pit_series(
                facts, "us-gaap",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                prio=1))
        shares_rows[t] = (
            champ.pit_series(facts, "dei",
                             "EntityCommonStockSharesOutstanding", prio=3)
            + champ.pit_series(facts, "us-gaap",
                               "CommonStockSharesOutstanding", prio=2)
            + champ.pit_series(
                facts, "us-gaap",
                "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    return equity_rows, shares_rows


def fetch_fundamentals() -> tuple[dict, dict]:
    """Live fundamentals: EDGAR companyfacts for the pond, fetched by
    the original's own loaders (cached by the original's cache rules),
    with its XOM parent CIK override."""
    champ = champion_module()
    ciks = champ.get_ciks()
    overrides = {"XOM": 34088}  # champion engine's parent-CIK fix
    facts = {}
    for t in champ.UNIVERSE:
        cik = overrides.get(t, ciks[t][0])
        facts[t] = champ.get_companyfacts(cik)
    return fundamentals_from_facts(facts)


def rank_on_date(pb, equity_rows: dict, shares_rows: dict,
                 on_date: str, renames: dict | None = None) -> dict:
    """The champion's ranking on one selection date.

    Returns {"date", "picks" (top five, ranked), "pool" (every scored
    ticker), "scores": {ticker: {"book_to_market", "momentum",
    "combined"}}}. Raises ValueError when fewer than five names can
    be scored: the original refuses to pick from a pool under five,
    and so does this.

    `renames` maps a pond ticker to its current ticker after a ticker
    change (DECISIONS.md ruling 3): fundamentals stay with the
    company (the EDGAR rows are keyed by the original ticker), prices
    and the returned picks use the current ticker, so the renamed
    company competes and is held under its new name."""
    champ = champion_module()
    renames = {str(k).strip().upper(): str(v).strip().upper()
               for k, v in (renames or {}).items()}
    d = on_date
    scores = {}
    for t in champ.UNIVERSE:
        dt = renames.get(t, t)
        be = champ.pit_value(equity_rows.get(t, []), d)
        so = champ.pit_value(shares_rows.get(t, []), d)
        px = pb.close_on_or_before(dt, d)
        if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
            continue
        mcap = so[2] * px
        if mcap <= 0:
            continue
        bm = be[2] / mcap
        bl = pb.bars.get(dt, [])
        didx = None
        for i, b in enumerate(bl):
            if b["d"] == d:
                didx = i
                break
        if didx is None or didx < 253:
            continue
        mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
        scores[dt] = (bm, mom)
    if len(scores) < 5:
        raise ValueError(
            f"champion ranking on {d}: only {len(scores)} of "
            f"{len(champ.UNIVERSE)} pond names could be scored (point "
            f"in time fundamentals or price history missing); refusing "
            f"to pick from a pool under five")
    vr = champ.percentile_ranks({t: v[0] for t, v in scores.items()})
    mr = champ.percentile_ranks({t: v[1] for t, v in scores.items()})
    combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
    picks = sorted(combined, key=lambda t: -combined[t])[:5]
    return {"date": d, "picks": picks, "pool": sorted(scores),
            "scores": {t: {"book_to_market": scores[t][0],
                           "momentum": scores[t][1],
                           "combined": combined[t]} for t in scores}}


def selection_dates(pb, start: str, end: str) -> list[str]:
    """Quarterly selection dates in [start, end] on this price
    calendar, by the original's own rule."""
    champ = champion_module()
    return champ.quarter_selection_dates(pb, start, end)
