"""The daily cycle (new code, design Section 4.1).

One run does the following, in order, and stops at the first failure
with the reason written to the audit log:

  1. Load config and resolve the effective mode through data/mode.py.
     If STOP ALL is set, the cycle reports and exits. No orders.
  2. Fetch current prices and refresh fundamentals for the 30 pond
     names plus SPY. Validate every series. Bad or missing data means
     no trading that day, stated in the report, never a guess.
  3. Load the pot. Mark it to the new closes. Run the floor check on
     the daily close, exactly as tested (pots/pot.py on_daily_close,
     the adopted protection rules).
  4. On a selection date (quarterly), run the champion ranking on
     point in time data and compute the target five positions at equal
     weight, subject to the 20 percent cap. The rebalance executes at
     the next open after the selection date, as in the book: a cycle
     that runs on the selection day itself records the pending
     selection and trades on the next run.
  5. Diff targets against the pot's positions and build the order
     list. Pass the list through caps, then through preview.
  6. Submission happens only on an explicit confirmation of the
     preview (the user's run command). In paper mode the orders go to
     the user's own Alpaca paper account; without paper keys the cycle
     applies the fills to the pot's own record only and labels the run
     SIMULATED, never paper.
  7. Read back fills, apply them to the pot at the fill prices with
     the program's cost convention, and reconcile against the broker
     record. Any mismatch is written to the audit log and the daily
     report as a mismatch, never silently absorbed.
  8. Save pot state (the pot saves itself atomically on every trade),
     write the daily report, and record the cycle in the audit log.

Live mode in Phase 1: the cycle refuses to submit live orders. The
frozen mode gate can enable live, and this app's own paper trial gate
(data audit, ruling 1) must also pass before the dashboard will
enable it, but the Phase 1 cycle itself trades on paper only; the
live path is Phase 2 work and the refusal is audit logged.

Pond events (DECISIONS.md ruling 3) are handled in step 2/4: a ticker
change recorded in config ("ticker_changes": {"OLD": "NEW"}) carries
the position under the new ticker; a pond name whose prices stop
arriving (acquired or delisted) is sold in the pot's record at its
last available price and the pot runs with four names until the next
selection date. Every pond event is audit logged and reported.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

from data import mode as _mode
from engines import common as _common
from pots import definitions as _defs
from pots.pot import Pot
from . import audit as _audit
from . import caps as _caps
from . import preview as _preview
from . import ranking as _ranking

_MIN_ORDER_NOTIONAL = 0.01
_STALE_DAYS = 10  # a pond name with no bar this many calendar days
                  # before the latest market date is treated as gone


class CycleError(RuntimeError):
    """A named, plain-language cycle failure. The cycle stops; the
    reason is in the audit log and the result dict."""


# ----------------------------------------------------------------------------
# Data sources (injectable for tests; defaults hit the real services)
# ----------------------------------------------------------------------------
def _default_price_source(symbols, end_date: str, cfg: dict) -> dict:
    from data.loaders import TiingoLoader
    loader = TiingoLoader(cfg)
    start = (date.fromisoformat(end_date) - timedelta(days=560)).isoformat()
    out = {}
    for sym in symbols:
        bars = loader.load(sym, start_date=start, end_date=end_date)
        out[sym] = [{"d": b.date, "o": (b.open if b.open else b.close),
                     "c": b.close} for b in bars]
    return out


def _default_fundamentals_source():
    return _ranking.fetch_fundamentals()


def _default_client(cfg):
    from data.alpaca import AlpacaClient
    return AlpacaClient.from_config(cfg)


# ----------------------------------------------------------------------------
# Kill switch completion (design gate 6.6)
# ----------------------------------------------------------------------------
def engage_kill_switch(state_dir=None, cfg: dict | None = None,
                       client=None) -> dict:
    """Engage STOP ALL and cancel every resting order at the broker.

    The stop flag lands FIRST (serialised against submission by
    data.mode), so no new order can slip in while cancels run. The
    kill switch does NOT liquidate positions: what is held stays held,
    and the result says so. Cancellation results are returned order by
    order. When no broker client can be built (no keys), the stop
    still engages and the result says the broker side could not be
    reached, so nobody believes orders were cancelled that were not.
    """
    sd = Path(state_dir) if state_dir else _mode.STATE_DIR
    _mode.set_stopped(True, state_dir=sd)
    _audit.record("kill_switch", state_dir=sd, engaged=True,
                  note="STOP ALL engaged. Positions were NOT sold.")
    result = {"stopped": True, "positions_sold": False,
              "cancellations": None, "cancel_error": None}
    try:
        client = client or _default_client(cfg if cfg is not None
                                             else _mode.load_config_strict())
    except Exception as e:
        result["cancel_error"] = (f"no broker client could be built "
                                  f"({type(e).__name__}); resting orders, "
                                  f"if any, were NOT cancelled by the app")
        _audit.record("kill_switch_cancel", state_dir=sd, ok=False,
                      error=result["cancel_error"])
        return result
    try:
        cancellations = client.cancel_all_open_orders()
    except Exception as e:
        result["cancel_error"] = (f"the broker cancel call failed "
                                  f"({type(e).__name__}: {e}); resting "
                                  f"orders may still be open at the broker")
        _audit.record("kill_switch_cancel", state_dir=sd, ok=False,
                      error=result["cancel_error"])
        return result
    result["cancellations"] = cancellations
    for c in cancellations:
        _audit.record("kill_switch_cancel", state_dir=sd, ok=True,
                      order_id=c.get("order_id"), symbol=c.get("symbol"),
                      status=c.get("status"))
    if not cancellations:
        _audit.record("kill_switch_cancel", state_dir=sd, ok=True,
                      order_id=None, note="no open orders to cancel")
    return result


# ----------------------------------------------------------------------------
# The cycle
# ----------------------------------------------------------------------------
def _closes_on_or_before(bars: list[dict], asof: str) -> float | None:
    best = None
    for b in bars:
        if b["d"] <= asof:
            best = b["c"]
        else:
            break
    return best


def _bar_on(bars: list[dict], day: str) -> dict | None:
    for b in bars:
        if b["d"] == day:
            return b
    return None


def run_cycle(*, today: str | None = None, cfg: dict | None = None,
              state_dir=None, price_source=None, fundamentals_source=None,
              client=None, confirm: bool = False,
              preview_id: str | None = None) -> dict:
    """Run one daily cycle. See the module docstring for the steps.

    Returns a result dict; never raises for an expected failure (the
    failure is in result["status"] / result["reason"] and in the audit
    log). With orders to place and confirm=False, the result status is
    "awaiting_confirmation" and the preview is in result["preview"]:
    nothing has been sent."""
    sd = Path(state_dir) if state_dir else _mode.STATE_DIR
    today = today or date.today().isoformat()
    cfg = cfg if cfg is not None else _mode.load_config_strict()
    eff = _mode.effective_mode(cfg)
    result: dict = {"date": today, "mode": eff, "status": "started",
                    "orders": [], "mismatches": []}

    def fail(reason: str, event: str = "cycle_failed") -> dict:
        result["status"] = "failed"
        result["reason"] = reason
        _audit.record(event, state_dir=sd, mode=eff, date=today,
                      reason=reason)
        return result

    # -- step 1: mode and stop -------------------------------------------
    _audit.record("cycle_start", state_dir=sd, mode=eff, date=today)
    if _mode.is_stopped(sd):
        return fail("the engine is STOPPED (STOP ALL); the cycle "
                    "placed no orders. Resume from the dashboard when "
                    "ready.")
    if eff == _mode.LIVE:
        return fail("Phase 1 of this app trades on PAPER only. The "
                    "config resolves to LIVE, so the cycle refused to "
                    "run rather than place a live order. Switch back "
                    "to PAPER to run the daily cycle.")
    try:
        pot_size = _caps.pot_size_from_config(cfg)
    except _caps.CapsError as e:
        return fail(str(e), event="cap_refusal")

    # -- the pot -----------------------------------------------------------
    defn = _defs.PotDefinition(
        "champion", "Champion — Value + Momentum (V+M)", "promoted",
        start_balance=pot_size, selection_cadence="quarterly",
        description=_defs.BY_ID["champion"].description)
    try:
        pot = _defs.build_pot(defn, state_dir=sd, start_date=today)
    except Exception as e:
        return fail(f"the pot could not be loaded ({type(e).__name__}: "
                    f"{e}); no trading today")
    if abs(pot.start_balance - pot_size) > 0.005:
        return fail(f"the saved pot was started at "
                    f"${pot.start_balance:,.2f} but the config now asks "
                    f"for ${pot_size:,.2f}. The app will not silently "
                    f"resize a running pot; set champion_pot_size back "
                    f"to ${pot.start_balance:,.2f} or start a fresh pot.")
    result["pot_start_balance"] = pot.start_balance

    # -- ticker changes (ruling 3) ----------------------------------------
    renames: dict[str, str] = {}
    changes = cfg.get("ticker_changes") or {}
    if isinstance(changes, dict):
        for old, new in changes.items():
            old, new = str(old).strip().upper(), str(new).strip().upper()
            if new and new != old:
                renames[old] = new
            if old in pot.positions and new and new != old:
                if new in pot.positions:
                    # Adversarial fix step, attack Y3: a rename onto
                    # a name the pot already holds must never
                    # silently overwrite that position. Refuse the
                    # whole run, loudly, and leave both positions
                    # exactly as they were.
                    _audit.record(
                        "pond_event", state_dir=sd,
                        kind="ticker_change_collision", old=old, new=new,
                        date=today,
                        note="REFUSED: the pot already holds the new "
                             "ticker; carrying the old position onto "
                             "it would silently overwrite and destroy "
                             "that position. Both positions were left "
                             "untouched. Resolve the ticker_changes "
                             "entry in the config and run again.")
                    return fail(
                        f"ticker change {old} -> {new} was REFUSED: "
                        f"the pot already holds {new}, and carrying "
                        f"{old} onto it would silently overwrite that "
                        f"position. Nothing was traded and both "
                        f"positions are untouched. Fix the "
                        f"ticker_changes entry in config.local.json "
                        f"(or remove it) and run again.",
                        event="pond_event_collision")
                pot.positions[new] = pot.positions.pop(old)
                if old in pot.last_prices:
                    pot.last_prices[new] = pot.last_prices.pop(old)
                pot.save()
                _audit.record("pond_event", state_dir=sd, kind="ticker_change",
                              old=old, new=new, date=today,
                              note="position carried under the new ticker")

    # -- step 2: fetch and validate ---------------------------------------
    champ = _ranking.champion_module()
    fetch_symbols = [renames.get(t, t) for t in champ.UNIVERSE] + ["SPY"]
    try:
        prices = (price_source or (lambda syms, end, c: _default_price_source(syms, end, c)))(
            fetch_symbols, today, cfg)
    except Exception as e:
        return fail(f"price fetch failed ({type(e).__name__}: {e}); "
                    f"no trading today", event="data_failure")
    try:
        missing = [sym for sym in fetch_symbols if not prices.get(sym)]
        if "SPY" in missing:
            raise CycleError("no price data returned for SPY")
        if len(missing) > 5:
            raise CycleError(
                f"no price data returned for {len(missing)} pond names "
                f"({', '.join(missing[:5])}...); too much of the pond is "
                f"missing to trust the day")
        for sym in fetch_symbols:
            if prices.get(sym):
                _common.validate_price_series(sym, prices[sym],
                                              engine="daily cycle")
    except (CycleError, ValueError) as e:
        return fail(f"{e}; no trading today", event="data_failure")
    pb = _ranking.build_price_book(prices)
    market_days = [d for d in pb.dates if d <= today]
    if not market_days:
        return fail("no market days on or before today in the fetched "
                    "data; no trading today", event="data_failure")
    asof = market_days[-1]
    result["asof"] = asof
    # Freshness is measured against TODAY, not against the data's own
    # last day (adversarial fix step, attack Y5): a feed that has
    # stopped entirely returns complete, well formed series that all
    # end long ago, and per name staleness against the data's own
    # last day cannot see it. A uniformly stale feed is a data
    # failure: no trading, and no cycle_complete is recorded, so a
    # stale run can never masquerade as a current paper cycle.
    stale_days = (date.fromisoformat(today) - date.fromisoformat(asof)).days
    if stale_days > _STALE_DAYS:
        return fail(f"the newest price data is dated {asof}, "
                    f"{stale_days} days before today ({today}); the "
                    f"price feed looks stopped, so no trading today "
                    f"and this run is not recorded as a completed "
                    f"cycle", event="data_failure")

    # pond events: names whose prices stopped arriving (ruling 3)
    asof_date = date.fromisoformat(asof)
    gone = []
    for t in champ.UNIVERSE:
        sym = renames.get(t, t)
        bars = prices.get(sym) or []
        last = bars[-1]["d"] if bars else None
        if last is None or (asof_date - date.fromisoformat(last)).days > _STALE_DAYS:
            gone.append(sym)
    for sym in gone:
        held = sym in pot.positions
        _audit.record("pond_event", state_dir=sd,
                      kind="delisted_or_acquired", symbol=sym, date=today,
                      held=held,
                      note=("held position will be sold in the pot record "
                            "at its last available price; the pot runs "
                            "with four names until the next selection date"
                            if held else
                            "name excluded from scoring until it returns "
                            "or the pond is re-ranked"))
        if held:
            last_px = pot.last_prices.get(sym) or _closes_on_or_before(
                prices.get(sym) or [], asof)
            if last_px:
                try:
                    pot.sell(sym, pot.positions[sym]["shares"], float(last_px),
                             asof, reason="pond_event_delisted")
                    result.setdefault("pond_event_sales", []).append(
                        {"symbol": sym, "price": float(last_px)})
                except Exception as e:
                    return fail(f"pond event sale for {sym} failed "
                                f"({type(e).__name__}: {e})")

    closes = {}
    for sym in fetch_symbols:
        if not prices.get(sym):
            continue  # a gone name; the pond event path below handles it
        c = _closes_on_or_before(prices[sym], asof)
        if c is None:
            return fail(f"no close on or before {asof} for {sym}; no "
                        f"trading today", event="data_failure")
        closes[sym] = c
    for sym in pot.positions:
        if sym not in closes:
            return fail(f"no usable price for held name {sym}; the pot "
                        f"cannot be marked or floor checked, so no "
                        f"trading today", event="data_failure")

    # -- step 3: mark and floor check --------------------------------------
    sel_dates = _ranking.selection_dates(pb, "2019-01-01", asof)
    is_sel = bool(sel_dates) and sel_dates[-1] == asof
    held_before = {sym: pos["shares"] for sym, pos in pot.positions.items()}
    try:
        close_result = pot.on_daily_close(asof, closes,
                                          is_selection_date=is_sel)
    except Exception as e:
        return fail(f"the daily close failed ({type(e).__name__}: {e}); "
                    f"state was rolled back by the pot")
    result["close_result"] = close_result
    if close_result in ("halt", "ended"):
        _audit.record("floor_halt", state_dir=sd, date=asof,
                      status=pot.protection.status,
                      balance=round(pot.cash, 2))
        result["status"] = "halted" if close_result == "halt" else "ended"
        # The pot's own record liquidated at the close. The broker side
        # follows: market sells for everything that was held, so the
        # paper account matches the pot. A failure here is a named
        # mismatch, never silently absorbed.
        liq_mismatches = _broker_liquidation(
            held_before, cfg=cfg, client=client, sd=sd, asof=asof,
            result=result)
        _finish(result, pot, sd, eff, today, reconciled=not liq_mismatches)
        return result

    # -- step 4: selection ---------------------------------------------------
    pending = pot.meta.get("pending_selection")
    latest_sel = sel_dates[-1] if sel_dates else None
    if is_sel and pot.protection.status == "active" \
            and pot.meta.get("last_selection_executed") != asof:
        pending = asof  # executes at the NEXT open, as in the book
        pot.meta["pending_selection"] = asof
        pot.save()
        result["selection_computed_for"] = asof
    execute_sel = None
    if pending and pending < asof \
            and pot.meta.get("last_selection_executed") != pending \
            and pot.protection.status == "active":
        execute_sel = pending
    if close_result == "restarted":
        # The restart lands on a selection date; that date's selection
        # executes on this run at today's open.
        execute_sel = latest_sel or asof

    if execute_sel is not None:
        out = _execute_selection(
            pot=pot, pb=pb, prices=prices, asof=asof, sel_date=execute_sel,
            cfg=cfg, pot_size=pot_size, eff=eff, sd=sd, today=today,
            fundamentals_source=fundamentals_source, client=client,
            confirm=confirm, preview_id=preview_id, result=result,
            renames=renames)
        if out is not None:
            return out

    # -- step 8 (no orders): report and record ------------------------------
    _finish(result, pot, sd, eff, today, reconciled=True)
    result["status"] = "complete"
    return result


def _execute_selection(*, pot: Pot, pb, prices, asof: str, sel_date: str,
                       cfg, pot_size: float, eff: str, sd: Path,
                       today: str, fundamentals_source, client,
                       confirm: bool, preview_id, result: dict,
                       renames: dict | None = None):
    """Steps 4 to 7 for one selection. Returns a finished result dict,
    or None when the cycle should fall through to the plain finish."""
    def fail(reason: str, event: str = "cycle_failed") -> dict:
        result["status"] = "failed"
        result["reason"] = reason
        _audit.record(event, state_dir=sd, mode=eff, date=today,
                      reason=reason)
        return result

    try:
        equity_rows, shares_rows = (fundamentals_source
                                    or _default_fundamentals_source)()
    except Exception as e:
        return fail(f"fundamentals fetch failed ({type(e).__name__}: "
                    f"{e}); no trading today", event="data_failure")
    try:
        ranking = _ranking.rank_on_date(pb, equity_rows, shares_rows, sel_date,
                                        renames=renames)
    except ValueError as e:
        return fail(f"{e}; no trading today", event="data_failure")
    picks = ranking["picks"]
    _audit.record("ranking", state_dir=sd, date=sel_date, picks=picks,
                  pool=ranking["pool"])
    result["picks"] = picks

    opens = {}
    for sym in set(list(pot.positions) + picks):
        bar = _bar_on(prices[sym], asof)
        if bar is None:
            return fail(f"no bar for {sym} on the execution day {asof}; "
                        f"no trading today", event="data_failure")
        opens[sym] = bar["o"]
    equity = pot.cash + sum(pos["shares"] * opens[sym]
                            for sym, pos in pot.positions.items())
    if not math.isfinite(equity) or equity <= 0:
        return fail("pot equity at the execution open is not a positive "
                    "finite number; no trading today")
    each = equity / 5.0
    targets = {t: each for t in picks}
    held_values = {sym: pos["shares"] * opens[sym]
                   for sym, pos in pot.positions.items()}

    orders = []
    for sym in sorted(held_values):
        diff = held_values[sym] - targets.get(sym, 0.0)
        if diff > _MIN_ORDER_NOTIONAL:
            orders.append({"symbol": sym, "side": "sell",
                           "notional": round(diff, 2), "order_type": "market",
                           "time_in_force": "day"})
    for sym in picks:
        diff = targets[sym] - held_values.get(sym, 0.0)
        if diff > _MIN_ORDER_NOTIONAL:
            # Buy notionals carry the program's own cost provision:
            # the original caps every buy at cash / 1.001 so the pot
            # can always settle the fill plus its 0.10 percent cost
            # from its own cash. Dividing the buy by 1.001 here is
            # that same rule, applied at sizing time.
            orders.append({"symbol": sym, "side": "buy",
                           "notional": round(diff / 1.001, 2),
                           "order_type": "market",
                           "time_in_force": "day"})
    result["orders"] = orders

    # Resolve the broker client once, here. Whether this run is
    # SIMULATED (no paper keys, so orders would be applied to the
    # pot's own record only) is a fact about the run that the audit
    # log and the paper trial gate both need, on every path out of
    # this function, including the no orders path below (adversarial
    # fix step, attack Y2: simulated events are recorded as
    # simulated and never count toward the trial).
    broker_client = client
    simulated = False
    if broker_client is None:
        try:
            broker_client = _default_client(cfg)
        except Exception:
            simulated = True  # no paper keys: the pot's own record only
    result["simulated"] = simulated

    if not orders:
        pot.meta["last_selection_executed"] = sel_date
        pot.meta.pop("pending_selection", None)
        pot.save()
        _audit.record("selection_cycle_complete", state_dir=sd, mode=eff,
                      date=asof, selection_date=sel_date, orders=0,
                      reconciled=True, simulated=simulated)
        return None

    # -- step 5: caps, then preview -----------------------------------------
    try:
        _caps.check_order_list(orders, held_values, equity, pot_size)
    except _caps.CapsError as e:
        _audit.record("cap_refusal", state_dir=sd, date=asof,
                      reason=str(e), orders=orders)
        return fail(f"cap refusal: {e}", event="cap_refusal")
    preview = _preview.build_preview(orders, eff, opens, held_values,
                                     equity, caps_ok=True)
    if not confirm:
        _preview.save_preview(preview, sd)
        _audit.record("preview_shown", state_dir=sd, date=asof,
                      preview_id=preview["preview_id"], orders=orders)
        result["preview"] = preview
        result["status"] = "awaiting_confirmation"
        return result
    # Confirmation binds to the preview the user actually saw: the one
    # saved on disk, named by id, inside its 15 minute life. The fresh
    # order list built by this run must match it order for order; if
    # prices moved enough to change the list, the confirmation is
    # refused and a fresh preview must be shown.
    try:
        saved = _preview.require_confirmation(_preview.load_preview(sd),
                                              preview_id, state_dir=sd)
        def _shape(rows):
            return sorted((r["symbol"], r["side"], round(float(r["notional"]), 2))
                          for r in rows)
        if _shape(saved["orders"]) != _shape(preview["orders"]):
            raise _preview.PreviewError(
                "the order list changed since that preview was shown "
                "(prices moved); run the cycle again to see a fresh "
                "preview. Nothing was sent.")
    except _preview.PreviewError as e:
        _audit.record("preview_expired", state_dir=sd, date=asof,
                      preview_id=preview_id, reason=str(e))
        return fail(str(e), event="preview_expired")
    _preview.save_preview(preview, sd)
    _audit.record("preview_shown", state_dir=sd, date=asof,
                  preview_id=preview["preview_id"], orders=orders)
    _audit.record("preview_confirmed", state_dir=sd, date=asof,
                  preview_id=saved["preview_id"])
    result["preview"] = preview

    # -- step 6: submit -------------------------------------------------------
    # Idempotency (adversarial fix step, attack Y8): client_order_ids
    # are derived from the selection date, the order's place in the
    # list, and its symbol, NEVER from the preview id, so re-running
    # the same selection computes the SAME ids. Before anything is
    # submitted, the audit log is checked for orders already
    # submitted for this selection: a recognised order is read back
    # from the broker and NEVER resubmitted.
    prior = _prior_submissions(sd, sel_date)
    submitted = []   # (order, response, client_order_id) placed now
    already = []     # (order, response or None, client_order_id)
    submit_error = None
    if not simulated:
        held_now = dict(held_values)
        for i, order in enumerate(orders):
            coid = f"champ-{sel_date}-{i}-{order['symbol']}"
            key = (order["symbol"], order["side"])
            if key in prior:
                prev = prior[key]
                resp = None
                reader = getattr(broker_client,
                                 "order_by_client_order_id", None)
                if reader is not None:
                    try:
                        got = reader(str(prev.get("client_order_id")
                                         or coid))
                        if isinstance(got, dict) and got.get("id"):
                            resp = got
                    except Exception:
                        resp = None
                already.append((order, resp,
                                str(prev.get("client_order_id") or coid)))
                _audit.record(
                    "order_already_submitted", state_dir=sd, date=asof,
                    symbol=order["symbol"], side=order["side"],
                    client_order_id=already[-1][2],
                    selection_date=sel_date,
                    note="this order was already submitted for this "
                         "selection on an earlier run; it was read "
                         "back, NOT resubmitted")
                n = float(order["notional"])
                held_now[order["symbol"]] = \
                    held_now.get(order["symbol"], 0.0) \
                    + (n if order["side"] == "buy" else -n)
                if held_now[order["symbol"]] <= 0.005:
                    held_now.pop(order["symbol"], None)
                continue
            try:
                _caps.check_single_order(order, held_now, equity, pot_size)
            except _caps.CapsError as e:
                _audit.record("cap_refusal", state_dir=sd, date=asof,
                              reason=str(e), orders=[order],
                              stage="submission")
                return fail(f"cap refusal at submission: {e}",
                            event="cap_refusal")
            try:
                resp = broker_client.submit_order(
                    order["symbol"], order["side"],
                    notional=order["notional"], order_type="market",
                    time_in_force="day", client_order_id=coid)
            except Exception as e:
                _audit.record("order_failed", state_dir=sd, date=asof,
                              symbol=order["symbol"], side=order["side"],
                              client_order_id=coid,
                              selection_date=sel_date,
                              error=f"{type(e).__name__}: {e}",
                              outcome_unknown=bool(getattr(e, "outcome_unknown", False)))
                submit_error = (order, e)
                break
            submitted.append((order, resp, coid))
            _audit.record("order_submitted", state_dir=sd, date=asof,
                          symbol=order["symbol"], side=order["side"],
                          notional=order["notional"],
                          broker_order_id=resp.get("id"),
                          client_order_id=coid,
                          selection_date=sel_date)
            n = float(order["notional"])
            held_now[order["symbol"]] = held_now.get(order["symbol"], 0.0) \
                + (n if order["side"] == "buy" else -n)
            if held_now[order["symbol"]] <= 0.005:
                held_now.pop(order["symbol"], None)

    # -- step 7: apply fills to the pot and reconcile -------------------------
    if simulated:
        mismatches, partials, unfilled = [], [], []
        for order in orders:
            sym = order["symbol"]
            fill_px = opens[sym]
            fill_gross = order["notional"]
            try:
                if order["side"] == "buy":
                    pot.buy_value(sym, fill_gross, fill_px, asof,
                                  reason=f"selection {sel_date}")
                else:
                    held_shares = pot.positions.get(sym, {}).get(
                        "shares", 0.0)
                    pot.sell(sym, min(fill_gross / fill_px, held_shares),
                             fill_px, asof,
                             reason=f"selection {sel_date}")
            except Exception as e:
                mismatches.append({
                    "symbol": sym, "side": order["side"],
                    "detail": f"fill could not be applied to the pot "
                              f"record ({type(e).__name__}: {e})"})
    else:
        entries = [(o, r, c, False) for (o, r, c) in submitted] \
            + [(o, r, c, True) for (o, r, c) in already]
        mismatches, partials, unfilled = _apply_broker_fills(
            entries, pot=pot, opens=opens, asof=asof,
            sel_date=sel_date, sd=sd)

    invested = sum(pos["shares"] * opens.get(sym, 0.0)
                   for sym, pos in pot.positions.items())
    result["invested_fraction"] = (round(invested / equity, 4)
                                   if equity else None)
    if partials:
        result["partial_fills"] = partials
        result["warning"] = (
            f"partial fills on {', '.join(partials)}: the broker "
            f"filled only part of those orders, so the pot is "
            f"{result['invested_fraction']:.0%} invested and the rest "
            f"is in cash until the next selection date. Each partial "
            f"fill is recorded as a reconciliation mismatch in the "
            f"audit log.")

    if submit_error is not None:
        # Adversarial fix step, attack Y6: the fills that DID happen
        # have been applied above. Now read the broker back and
        # reconcile the pot record to it before stopping, loudly.
        order, exc = submit_error
        mismatches.extend(_reconcile_with_broker(
            pot, broker_client, opens=opens, asof=asof, sd=sd,
            sel_date=sel_date))
        _record_mismatches(mismatches, sd, asof)
        result["mismatches"] = mismatches
        _audit.record("fill_reconciled", state_dir=sd, date=asof,
                      orders=len(orders), mismatches=len(mismatches),
                      simulated=False, partial_submission=True)
        result["status"] = "failed"
        result["reason"] = (
            f"order submission failed for {order['symbol']} "
            f"({type(exc).__name__}: {exc}); the cycle stopped. The "
            f"fills that had already happened were applied to the pot "
            f"record, and the broker account was read back and "
            f"reconciled (see the broker_reconciliation event in the "
            f"audit log). The selection was NOT marked executed, so a "
            f"later run recognises the orders already placed and does "
            f"not resubmit them. Check open orders at the broker "
            f"before running again.")
        _audit.record("cycle_failed", state_dir=sd, mode=eff,
                      date=today, reason=result["reason"])
        _finish(result, pot, sd, eff, today, reconciled=False)
        return result

    _record_mismatches(mismatches, sd, asof)
    result["mismatches"] = mismatches
    _audit.record("fill_reconciled", state_dir=sd, date=asof,
                  orders=len(orders), mismatches=len(mismatches),
                  simulated=simulated)

    if unfilled:
        # Orders accepted by the broker but reporting no fill yet
        # (attack Y8): they are working at the broker, so the
        # selection stays pending and the next run reads their fills
        # back through the idempotency path above. Nothing is
        # resubmitted, and the mismatch records above say exactly
        # what is outstanding.
        _audit.record("selection_incomplete", state_dir=sd, date=asof,
                      selection_date=sel_date, unfilled=len(unfilled),
                      note="orders are working at the broker with no "
                           "fill reported yet; the selection stays "
                           "pending and their fills will be read back "
                           "on the next run. Nothing was resubmitted.")
        result["warning"] = (
            f"{len(unfilled)} order(s) were accepted by the broker "
            f"but reported no fill yet. They were NOT resubmitted and "
            f"must not be placed again by hand; the next cycle run "
            f"reads their fills back. The selection is recorded as "
            f"incomplete, with a reconciliation mismatch for each "
            f"outstanding order.")
        _finish(result, pot, sd, eff, today, reconciled=False)
        result["status"] = "complete"
        return result

    pot.meta["last_selection_executed"] = sel_date
    pot.meta.pop("pending_selection", None)
    pot.save()
    _audit.record("selection_cycle_complete", state_dir=sd, mode=eff,
                  date=asof, selection_date=sel_date,
                  orders=len(orders), reconciled=not mismatches,
                  simulated=simulated,
                  invested_fraction=result["invested_fraction"])
    _finish(result, pot, sd, eff, today, reconciled=not mismatches)
    result["status"] = "complete"
    return result


def _prior_submissions(sd: Path, sel_date: str) -> dict:
    """Orders already submitted for a selection, keyed by
    (symbol, side), read tolerantly from the audit log. This is an
    idempotency lookup, not evidence: lines are parsed one by one
    and unparseable lines are skipped (the gate's chain verification
    is what guards the log as evidence)."""
    out: dict = {}
    try:
        lines = _audit.audit_path(sd).read_text(
            encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return out
    import json as _json
    for line in lines:
        try:
            e = _json.loads(line)
        except Exception:
            continue
        if isinstance(e, dict) and e.get("event") == "order_submitted" \
                and e.get("selection_date") == sel_date:
            out[(str(e.get("symbol")), str(e.get("side")))] = e
    return out


def _record_mismatches(mismatches: list[dict], sd: Path,
                       asof: str) -> None:
    """Write one reconciliation_mismatch event per mismatch. (The
    Y8 crash lived here: mismatch_id was passed both explicitly and
    inside the unpacked dict. The id is now set on the dict and
    excluded from the unpacked fields.)"""
    for m in mismatches:
        mid = m.get("mismatch_id") or f"{asof}-{m['symbol']}-{m['side']}"
        m["mismatch_id"] = mid
        fields = {k: v for k, v in m.items() if k != "mismatch_id"}
        _audit.record("reconciliation_mismatch", state_dir=sd,
                      date=asof, mismatch_id=mid, **fields)


def _apply_broker_fills(entries, *, pot: Pot, opens, asof: str,
                        sel_date: str, sd: Path):
    """Apply broker fill responses to the pot record. `entries` are
    (order, response, client_order_id, was_prior) tuples. Returns
    (mismatches, partial_symbols, unfilled_entries): an order whose
    response carries no fill is unfilled (working at the broker, NOT
    applied, NOT to be resubmitted); a partial fill is applied at its
    true size and recorded as a mismatch (attack Y7); a fill read
    back for an order submitted on an earlier run resolves that
    order's outstanding mismatch records (attack Y8)."""
    mismatches: list[dict] = []
    partials: list[str] = []
    unfilled: list = []
    for order, resp, _coid, was_prior in entries:
        sym = order["symbol"]
        if resp is None:
            mismatches.append({
                "symbol": sym, "side": order["side"],
                "detail": "this order was submitted for this "
                          "selection on an earlier run; its current "
                          "state could not be read back from the "
                          "broker, so its effect is NOT in the pot "
                          "record. It was NOT resubmitted"})
            unfilled.append(order)
            continue
        fill_qty = float(resp.get("filled_qty") or 0)
        fill_px = float(resp.get("filled_avg_price") or 0)
        fill_gross = round(fill_qty * fill_px, 2) if fill_px else 0.0
        if fill_qty <= 0 or fill_px <= 0:
            mismatches.append({
                "symbol": sym, "side": order["side"],
                "detail": "the broker response carried no fill; the "
                          "order's effect is NOT in the pot record"})
            unfilled.append(order)
            continue
        expected_qty = order["notional"] / fill_px
        if fill_qty < expected_qty * 0.999:
            partials.append(sym)
            mismatches.append({
                "symbol": sym, "side": order["side"], "partial": True,
                "detail": f"partial fill: the broker filled "
                          f"{fill_qty:.4f} of about {expected_qty:.4f} "
                          f"shares ({fill_qty / expected_qty:.0%} of "
                          f"the order); the pot holds the filled part "
                          f"only and the unfilled remainder stayed in "
                          f"cash until the next selection date"})
        try:
            if order["side"] == "buy":
                trade = pot.buy_value(sym, fill_gross, fill_px, asof,
                                      reason=f"selection {sel_date}")
            else:
                held_shares = pot.positions.get(sym, {}).get(
                    "shares", 0.0)
                trade = pot.sell(sym, min(fill_qty, held_shares),
                                 fill_px, asof,
                                 reason=f"selection {sel_date}")
        except Exception as e:
            mismatches.append({
                "symbol": sym, "side": order["side"],
                "detail": f"fill could not be applied to the pot "
                          f"record ({type(e).__name__}: {e})"})
            continue
        if abs(trade.gross - fill_gross) > 0.01:
            mismatches.append({
                "symbol": sym, "side": order["side"],
                "detail": f"pot record gross ${trade.gross:,.2f} "
                          f"differs from broker fill gross "
                          f"${fill_gross:,.2f}"})
        if was_prior:
            for e in _audit.read_events(sd):
                if e.get("event") == "reconciliation_mismatch" \
                        and e.get("symbol") == sym \
                        and e.get("side") == order["side"] \
                        and e.get("mismatch_id"):
                    _audit.record(
                        "mismatch_resolved", state_dir=sd, date=asof,
                        mismatch_id=e["mismatch_id"],
                        note="the fill was read back from the broker "
                             "on a later run and applied to the pot "
                             "record")
    return mismatches, partials, unfilled


def _reconcile_with_broker(pot: Pot, broker_client, *, opens, asof: str,
                           sd: Path, sel_date: str) -> list[dict]:
    """Read the broker back after a submission failure and reconcile
    the pot record to it (adversarial fix step, attack Y6). The
    broker is the source of truth for what it holds: positions it
    reports are brought into the pot record at the broker's own
    average entry price where it gives one. A pot position the
    broker does not report is NOT silently deleted on a read back
    alone (a read back can itself be incomplete; deleting on it is
    how records get destroyed): it is returned as an unresolved
    mismatch, loudly, for resolution. A read back that fails is
    itself a mismatch, and the caller halts. Every outcome is
    written to the audit log as a broker_reconciliation event."""
    mismatches: list[dict] = []
    try:
        broker_positions = broker_client.positions()
    except Exception as e:
        mismatches.append({
            "symbol": "*", "side": "reconcile",
            "detail": f"broker positions could not be read back after "
                      f"the submission failure ({type(e).__name__}: "
                      f"{e}); the pot record may diverge from the "
                      f"broker and the run is halted for manual "
                      f"reconciliation"})
        _audit.record("broker_reconciliation", state_dir=sd,
                      date=asof, ok=False, selection_date=sel_date,
                      readback_failed=True)
        return mismatches
    open_orders = None
    try:
        oo = broker_client.open_orders()
        open_orders = len(oo) if isinstance(oo, list) else None
    except Exception:
        open_orders = None
    broker_qty: dict[str, float] = {}
    broker_px: dict[str, float] = {}
    for p in broker_positions or []:
        if not isinstance(p, dict):
            continue
        sym = str(p.get("symbol") or "").strip().upper()
        try:
            q = float(p.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        if sym and q > 0:
            broker_qty[sym] = q
            try:
                px = float(p.get("avg_entry_price") or 0)
            except (TypeError, ValueError):
                px = 0.0
            if px > 0:
                broker_px[sym] = px
    adjustments = []
    for sym, q in sorted(broker_qty.items()):
        held = pot.positions.get(sym, {}).get("shares", 0.0)
        if abs(held - q) <= 1e-6:
            continue
        px = broker_px.get(sym) or opens.get(sym) \
            or pot.last_prices.get(sym)
        if not px:
            mismatches.append({
                "symbol": sym, "side": "reconcile",
                "detail": f"the broker holds {q} shares of {sym} but "
                          f"no price is available to record them at; "
                          f"the divergence is unresolved"})
            continue
        try:
            if held < q:
                pot.buy_value(sym, (q - held) * px, px, asof,
                              reason="broker_reconciliation")
            else:
                pot.sell(sym, held - q, px, asof,
                         reason="broker_reconciliation")
            adjustments.append({"symbol": sym, "from_shares": held,
                                "to_shares": q, "price": px})
        except Exception as e:
            mismatches.append({
                "symbol": sym, "side": "reconcile",
                "detail": f"the broker holds {q} shares of {sym} "
                          f"against {held} in the pot record, and "
                          f"adjusting the record failed "
                          f"({type(e).__name__}: {e})"})
    for sym in sorted(pot.positions):
        if sym not in broker_qty:
            mismatches.append({
                "symbol": sym, "side": "reconcile",
                "detail": f"the pot record holds {sym} but the broker "
                          f"reports no position in it; the position "
                          f"is LEFT in the record and this divergence "
                          f"is unresolved, because a read back alone "
                          f"is not proof a position is gone"})
    _audit.record("broker_reconciliation", state_dir=sd, date=asof,
                  ok=not mismatches, selection_date=sel_date,
                  adjustments=adjustments,
                  broker_positions=broker_qty,
                  open_orders=open_orders)
    return mismatches


def _broker_liquidation(held_before: dict, *, cfg, client, sd: Path,
                        asof: str, result: dict) -> list[dict]:
    """Submit broker side market sells for a halt liquidation. Returns
    the list of mismatches (empty when the broker side matched or when
    there was nothing to sell). Without a broker client the pot record
    stands alone and the run is labelled simulated."""
    mismatches: list[dict] = []
    if not held_before:
        return mismatches
    broker_client = client
    if broker_client is None:
        try:
            broker_client = _default_client(cfg)
        except Exception:
            result["simulated"] = True
            _audit.record("liquidation", state_dir=sd, date=asof,
                          simulated=True,
                          note="no broker client; liquidation recorded "
                               "in the pot record only")
            return mismatches
    for sym, shares in sorted(held_before.items()):
        coid = f"champ-halt-{asof}-{sym}"
        try:
            resp = broker_client.submit_order(
                sym, "sell", qty=shares, order_type="market",
                time_in_force="day", client_order_id=coid)
            _audit.record("order_submitted", state_dir=sd, date=asof,
                          symbol=sym, side="sell", qty=shares,
                          broker_order_id=resp.get("id"),
                          client_order_id=coid, reason="floor_halt")
        except Exception as e:
            mid = f"{asof}-{sym}-liquidation"
            mismatches.append({"symbol": sym, "side": "sell",
                               "mismatch_id": mid,
                               "detail": f"halt liquidation sell at the "
                                         f"broker failed ({type(e).__name__}: "
                                         f"{e}); the position may still be "
                                         f"held at the broker"})
            _audit.record("reconciliation_mismatch", state_dir=sd,
                          date=asof, mismatch_id=mid,
                          symbol=sym, side="sell",
                          detail=mismatches[-1]["detail"])
    result["mismatches"] = mismatches
    return mismatches


def _finish(result: dict, pot: Pot, sd: Path, eff: str, today: str,
            reconciled: bool) -> None:
    """Step 8: sync the dashboard state, write the daily report, and
    record the completed cycle. Report failures are surfaced in the
    result, never hidden, and never block the audit record."""
    try:
        import sync_state
        if sd.resolve() == sync_state.STATE_DIR.resolve():
            sync_state.main()
    except Exception as e:
        result["sync_error"] = f"{type(e).__name__}: {e}"
    try:
        from reports.daily_report import write_daily_report
        import sync_state
        states = sync_state.load_report_states(sd)
        if states:
            out_dir = None
            if sd.resolve() != sync_state.STATE_DIR.resolve():
                out_dir = sd / "reports"  # test installs keep their own
            result["report"] = write_daily_report(
                states, report_date=result.get("asof") or today,
                output_dir=out_dir)
    except Exception as e:
        result["report_error"] = f"{type(e).__name__}: {e}"
    _audit.record("cycle_complete", state_dir=sd, mode=eff, date=today,
                  asof=result.get("asof"), reconciled=reconciled,
                  simulated=bool(result.get("simulated")),
                  status=result.get("status"))
