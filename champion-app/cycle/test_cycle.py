"""Phase 1 tests for the derived champion app's new code.

Run:  python3 cycle/test_cycle.py   (from the app folder)
Fake transports and dummy keys only. No broker account is touched.

Covers: ranking equivalence against the champion original (the
original is the oracle), the hard caps, the kill switch cancelling
resting orders at the broker, the paper trial gate, the pond event
paths (ticker change carries, delisted name sold), the audit log's
append only behaviour, preview confirmation rules, a full fake
paper selection cycle end to end, and the keystore test double
(the sanctioned hook in data/keystore.py) standing in for Windows
DPAPI on this Linux machine.
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cycle import audit as _audit
from cycle import caps as _caps
from cycle import daily_cycle as _cycle
from cycle import first_run as _first_run
from cycle import preview as _preview
from cycle import ranking as _ranking

CHECKS = 0


def check(cond, label):
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(f"CHECK FAILED: {label}")
    print(f"  ok {CHECKS:02d}: {label}")


def replay_data():
    from engines import vm as _vm
    champ = _vm._orig()
    bars = {t: champ.get_prices(t) for t in list(champ.UNIVERSE) + ["SPY"]}
    pb, eq, sh = _vm._load_data(None, None)
    return champ, bars, pb, eq, sh


def price_source_factory(bars, upto):
    def source(symbols, start, end):
        out = {}
        for s in symbols:
            series = bars.get(s) or []
            out[s] = [dict(b) for b in series if b["d"] <= upto]
        return out
    return source


class FakeClient:
    """A paper broker stand in: fills at the day's open."""

    def __init__(self, bars, day):
        self.bars = bars
        self.day = day
        self.submitted = []
        self.open = []

    def _open_price(self, symbol):
        for b in self.bars[symbol]:
            if b["d"] == self.day:
                return b["o"]
        raise KeyError(symbol)

    def submit_order(self, symbol, side, qty=None, notional=None,
                     order_type="market", time_in_force="day",
                     client_order_id=None, **kw):
        px = self._open_price(symbol)
        if notional is not None:
            q = float(notional) / px
        else:
            q = float(qty)
        self.submitted.append({"symbol": symbol, "side": side,
                                "qty": q, "notional": notional,
                                "client_order_id": client_order_id})
        return {"id": f"fake-{len(self.submitted)}", "status": "filled",
                "filled_qty": repr(q), "filled_avg_price": repr(px),
                "client_order_id": client_order_id}

    def open_orders(self):
        return list(self.open)

    def cancel_all_open_orders(self):
        out = [{"order_id": o["id"], "symbol": o.get("symbol"),
                "status": "cancelled"} for o in self.open]
        self.open = []
        return out

    def account(self):
        return {"equity": "100000.00", "cash": "100000.00"}

    def positions(self):
        return []


def test_ranking_equivalence(champ, bars, pb, eq, sh):
    print("ranking equivalence (the original is the oracle)")
    res = champ.run_pot(pb, eq, sh, "2023-01-01", "2026-11-20", 100.0,
                        85.0, [], None, "oracle", quiet=True,
                        record_pools=True)
    pools = res["pools"]
    check(len(pools) >= 10, f"oracle recorded {len(pools)} selection pools")
    for pool_date, pool_names, pool_picks in pools:
        ranked = _ranking.rank_on_date(pb, eq, sh, pool_date)
        check(ranked["picks"] == pool_picks,
              f"picks match on {pool_date}: {ranked['picks']}")
        check(ranked["pool"] == pool_names,
              f"scored pool matches on {pool_date} "
              f"({len(pool_names)} names)")


def test_caps():
    print("hard caps")
    check(_caps.POT_CEILING == 10_000.0, "shipped ceiling is $10,000")
    try:
        _caps.pot_size_from_config({"champion_pot_size": 10_000.01})
        check(False, "pot size above the ceiling refused")
    except _caps.CapsError:
        check(True, "pot size above the ceiling refused")
    check(_caps.pot_size_from_config({"champion_pot_size": 10_000}) == 10_000.0,
          "pot size at the ceiling allowed")
    check(_caps.pot_size_from_config({}) == 100.0,
          "default pot size is $100")
    equity = 500.0
    held = {"AAPL": 100.0}
    ok_orders = [{"symbol": "MSFT", "side": "buy", "notional": 100.0,
                  "order_type": "market", "time_in_force": "day"}]
    _caps.check_order_list(ok_orders, held, equity, 500.0)
    check(True, "a legal order list passes")

    def refused(orders, label, held=held, equity=equity, pot_size=500.0):
        try:
            _caps.check_order_list(orders, held, equity, pot_size)
            check(False, label)
        except _caps.CapsError:
            check(True, label)

    refused([{"symbol": "MSFT", "side": "buy", "notional": 100.01,
              "order_type": "market", "time_in_force": "day"}],
            "a position over 20 percent is refused")
    many = {f"S{i}": 100.0 for i in range(5)}
    refused([{"symbol": "NEWCO", "side": "buy", "notional": 50.0,
              "order_type": "market", "time_in_force": "day"}],
            "a sixth position is refused", held=many)
    refused([{"symbol": "AAPL", "side": "sell", "notional": 100.01,
              "order_type": "market", "time_in_force": "day"}],
            "a sell beyond the holding is refused (no shorting)")
    refused([{"symbol": "MSFT", "side": "buy", "notional": 50.0,
              "order_type": "limit", "time_in_force": "day"}],
            "a non market order is refused")
    refused([{"symbol": "MSFT", "side": "buy", "notional": 50.0,
              "order_type": "market", "time_in_force": "gtc"}],
            "a non day order is refused")
    refused(ok_orders, "a pot already over its set size refuses buys",
            equity=600.0, pot_size=500.0)
    try:
        _caps.check_single_order(
            {"symbol": "MSFT", "side": "buy", "notional": 100.01,
             "order_type": "market", "time_in_force": "day"},
            held, equity, 500.0)
        check(False, "the per order recheck refuses an over cap order")
    except _caps.CapsError:
        check(True, "the per order recheck refuses an over cap order")


def test_audit_and_paper_gate():
    print("audit log and the paper trial gate")
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td)
        _audit.record("cycle_complete", state_dir=sd, mode="paper",
                      reconciled=True)
        _audit.record("cycle_complete", state_dir=sd, mode="paper",
                      reconciled=True)
        evs = _audit.read_events(sd)
        check([e["event"] for e in evs] == ["cycle_complete"] * 2,
              "events read back in order")
        size1 = _audit.audit_path(sd).stat().st_size
        _audit.record("note", state_dir=sd)
        check(_audit.audit_path(sd).stat().st_size > size1,
              "the log only grows (append only)")
        st = _audit.paper_trial_status(sd)
        check(not st["complete"] and st["started"] is not None,
              "trial clock starts at the first reconciled paper cycle")

    now = datetime.now()

    class _FakeNow(datetime):
        """A clock the test can set, so aged entries are written by
        record() itself, hash chain and all. (The audit log is hash
        chained since the adversarial fix step: rewriting ts fields
        in the file afterwards is exactly the tampering the chain
        exists to catch, so the test ages entries at write time.)"""
        fixed = None

        @classmethod
        def now(cls, tz=None):
            return cls.fixed

    def log_with(events_spec):
        td = tempfile.mkdtemp()
        sd = Path(td)
        orig = _audit.datetime
        _audit.datetime = _FakeNow
        try:
            for ev, extra in events_spec:
                extra = dict(extra)
                age = extra.pop("age_days", None)
                _FakeNow.fixed = (now - timedelta(days=age)
                                  if age is not None else now)
                _audit.record(ev, state_dir=sd, **extra)
        finally:
            _audit.datetime = orig
        return sd

    start = ("cycle_complete", {"mode": "paper", "reconciled": True,
                                 "age_days": 100})
    sel = ("selection_cycle_complete", {"mode": "paper", "age_days": 50})
    sd = log_with([start, sel])
    st = _audit.paper_trial_status(sd)
    check(st["complete"], "90 days plus a selection cycle completes the trial")
    check(_audit.live_unlock_blocker(sd) is None,
          "no blocker once the trial is complete")
    sd = log_with([("cycle_complete", {"mode": "paper", "reconciled": True,
                                        "age_days": 89}), sel])
    st = _audit.paper_trial_status(sd)
    check(not st["complete"] and st["days"] == 89,
          "89 days is not enough")
    blocker = _audit.live_unlock_blocker(sd) or ""
    check("paper trial is not complete" in blocker
          and "day 89 of 90" in blocker,
          "the blocker names the unmet trial")
    sd = log_with([start])
    check(not _audit.paper_trial_status(sd)["complete"],
          "no selection cycle, no completion")
    sd = log_with([start, sel,
                   ("reconciliation_mismatch",
                    {"mismatch_id": "m1", "age_days": 10})])
    st = _audit.paper_trial_status(sd)
    check(not st["complete"] and st["unresolved_mismatches"] == 1,
          "an unresolved mismatch blocks completion")
    _audit.record("mismatch_resolved", state_dir=sd, mismatch_id="m1")
    check(_audit.paper_trial_status(sd)["complete"],
          "a resolved mismatch unblocks completion")


def test_preview_rules():
    print("preview confirmation rules")
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td)
        pv = _preview.build_preview(
            [{"symbol": "AAPL", "side": "buy", "notional": 20.0,
              "order_type": "market", "time_in_force": "day"}],
            mode="paper", prices={"AAPL": 100.0}, held_values={},
            pot_equity=100.0, caps_ok=True)
        _preview.save_preview(pv, sd)
        got = _preview.require_confirmation(_preview.load_preview(sd),
                                            pv["preview_id"])
        check(got["preview_id"] == pv["preview_id"],
              "a fresh preview confirms")
        try:
            _preview.require_confirmation(_preview.load_preview(sd),
                                          "nope")
            check(False, "an unknown preview id is refused")
        except _preview.PreviewError:
            check(True, "an unknown preview id is refused")
        try:
            _preview.require_confirmation(
                _preview.load_preview(sd), pv["preview_id"],
                now=datetime.now() + timedelta(minutes=16))
            check(False, "an expired preview is refused")
        except _preview.PreviewError:
            check(True, "an expired preview is refused")
        bad = _preview.build_preview([], mode="paper", prices={},
                                     held_values={}, pot_equity=100.0,
                                     caps_ok=False)
        _preview.save_preview(bad, sd)
        try:
            _preview.require_confirmation(_preview.load_preview(sd),
                                          bad["preview_id"])
            check(False, "a cap failed preview can never be confirmed")
        except _preview.PreviewError:
            check(True, "a cap failed preview can never be confirmed")
        try:
            _preview.require_confirmation(None, "anything")
            check(False, "confirming with no preview on record is refused")
        except _preview.PreviewError:
            check(True, "confirming with no preview on record is refused")


def test_kill_switch_and_adapter(bars):
    print("kill switch and the adapter's cancel methods")
    from data import mode as _mode
    from data.alpaca import AlpacaClient, AlpacaError

    open_orders = [
        {"id": "ord-1", "symbol": "AAPL", "side": "buy", "status": "new"},
        {"id": "ord-2", "symbol": "MSFT", "side": "sell", "status": "new"},
    ]
    calls = []

    def transport(method, url, headers, body):
        calls.append((method, url))
        if method == "GET" and "/v2/orders" in url and "status=open" in url:
            return 200, json.dumps(open_orders)
        if method == "DELETE" and url.endswith("/v2/orders"):
            return 207, json.dumps([{"id": o["id"], "status": 200}
                                     for o in open_orders])
        if method == "DELETE" and "/v2/orders/" in url:
            return 204, ""
        if method == "POST" and url.endswith("/v2/orders"):
            return 200, json.dumps({"id": "ord-3", "status": "filled",
                                     "filled_qty": "1",
                                     "filled_avg_price": "10"})
        if method == "GET" and url.endswith("/v2/account"):
            return 200, "{}"
        return 404, "{}"

    with tempfile.TemporaryDirectory() as td:
        sd = Path(td)
        client = AlpacaClient("paper", "PAPERKEY123", "secretsecret123",
                              transport=transport, state_dir=sd)
        out = client.cancel_all_open_orders()
        check([c["order_id"] for c in out] == ["ord-1", "ord-2"],
              "cancel all reports each resting order")
        one = client.cancel_order("ord-9")
        check(isinstance(one, dict)
              and ("DELETE", "https://paper-api.alpaca.markets/v2/orders/ord-9")
              in [(m, u) for m, u in calls],
              "single order cancel issues the DELETE for that order")

        # STOP ALL blocks submission before any transport call.
        _mode.set_stopped(True, state_dir=sd)
        calls.clear()
        try:
            client.submit_order("AAPL", "buy", notional=10.0)
            check(False, "STOP ALL blocks order submission")
        except AlpacaError:
            check(True, "STOP ALL blocks order submission")
        check(calls == [], "no transport call happens while stopped")

        # The completed kill switch: stop lands, cancels reported,
        # positions untouched (no sell call exists to make).
        _mode.set_stopped(False, state_dir=sd)
        fake = FakeClient(bars, "2026-10-02")
        fake.open = [dict(o) for o in open_orders]
        res = _cycle.engage_kill_switch(state_dir=sd, client=fake)
        check(res["stopped"] is True and _mode.is_stopped(state_dir=sd),
              "the kill switch sets STOP ALL")
        check([c["order_id"] for c in res["cancellations"]]
              == ["ord-1", "ord-2"],
              "the kill switch reports each cancellation")
        check(res["positions_sold"] is False
              and any("NOT sold" in str(e.get("note", ""))
                      for e in _audit.read_events(sd)
                      if e["event"] == "kill_switch"),
              "the kill switch states positions were not sold")
        check(fake.open == [], "resting orders are gone at the broker")


def test_first_run_and_keystore():
    print("first run setup and the keystore test double")
    from data import keystore as _ks
    from data import mode as _mode
    with tempfile.TemporaryDirectory() as td:
        cfg = Path(td) / "config.local.json"
        ok, msg = _first_run.setup_paper_keys("PAPERKEY123",
                                              "secretsecret123",
                                              config_path=cfg)
        check(ok and "PAPER" in msg, "setup reports paper mode")
        loaded = _mode.load_config_strict(cfg)
        check(loaded.get("alpaca_paper_key_id") == "PAPERKEY123",
              "paper keys round trip through the config")
        check(loaded.get("trading_mode") == "paper"
              and _mode.effective_mode(loaded) == "paper",
              "mode is paper")
        ok2, _msg2 = _first_run.setup_paper_keys("short",
                                                 "secretsecret123",
                                                 config_path=cfg)
        check(not ok2, "a malformed key id is refused")

        # The sanctioned test double stands in for DPAPI on Linux.
        # Provider contract (data/keystore.py): protect takes the
        # plaintext string and returns str or bytes (bytes are base64
        # wrapped by the keystore); unprotect receives the base64
        # blob string and returns str or bytes.
        import base64 as _b64

        def fake_protect(s: str) -> bytes:
            return s.encode("utf-8")[::-1]

        def fake_unprotect(blob: str) -> bytes:
            return _b64.b64decode(blob)[::-1]

        _ks._set_provider_for_tests(fake_protect, fake_unprotect)
        try:
            check(_ks.available(), "test double makes the keystore "
                  "available off Windows")
            ok3, msg3 = _mode.encrypt_config_keys(cfg)
            raw = cfg.read_text()
            check(ok3 and "dpapi:" in raw and "PAPERKEY123" not in raw,
                  "keys are encrypted at rest through the provider")
            check(_mode.load_config_strict(cfg).get("alpaca_paper_key_id")
                  == "PAPERKEY123", "encrypted keys decrypt on load")
            check("encrypted" in msg3.lower(), "the message says keys "
                  "are encrypted at rest")
        finally:
            _ks._set_provider_for_tests(None, None)
        check(not _ks.available(), "without a provider this Linux "
              "machine has no DPAPI (the Windows build uses real DPAPI)")


def test_full_cycle_and_pond_events(champ, bars, pb, eq, sh):
    print("full fake paper selection cycle and pond events")
    ps = lambda upto: price_source_factory(bars, upto)
    fs = lambda: (eq, sh)
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td) / "state"
        cfg = {"champion_pot_size": 100}
        r1 = _cycle.run_cycle(today="2026-10-01", state_dir=sd, cfg=cfg,
                              price_source=ps("2026-10-01"),
                              fundamentals_source=fs)
        check(r1["status"] == "complete" and not r1["orders"],
              "selection day records the pending selection, trades "
              "nothing yet")
        fake = FakeClient(bars, "2026-10-02")
        r2 = _cycle.run_cycle(today="2026-10-02", state_dir=sd, cfg=cfg,
                              price_source=ps("2026-10-02"),
                              fundamentals_source=fs, client=fake)
        check(r2["status"] == "awaiting_confirmation",
              "the execution day stops at the preview without "
              "confirmation")
        check(len(r2["preview"]["orders"]) == 5,
              "the preview carries five buys")
        check(fake.submitted == [], "nothing was submitted unconfirmed")
        pid = r2["preview"]["preview_id"]
        r3 = _cycle.run_cycle(today="2026-10-02", state_dir=sd, cfg=cfg,
                              price_source=ps("2026-10-02"),
                              fundamentals_source=fs, client=fake,
                              confirm=True, preview_id=pid)
        check(r3["status"] == "complete", "the confirmed run completes")
        check(len(fake.submitted) == 5, "five orders reached the broker")
        from pots.pot import Pot
        pot = Pot.load("champion", state_dir=sd)
        expected = _ranking.rank_on_date(pb, eq, sh, "2026-10-01")["picks"]
        check(sorted(pot.positions) == sorted(expected),
              f"the pot holds the ranked five: {sorted(pot.positions)}")
        check(abs(pot.equity() - 100.0) < 1.0,
              f"pot equity stays whole after costs: ${pot.equity():.2f}")
        evs = _audit.read_events(sd)
        kinds = [e["event"] for e in evs]
        check("selection_cycle_complete" in kinds,
              "the selection cycle is in the audit log")
        check("order_submitted" in kinds and "cycle_complete" in kinds,
              "submission and completion are in the audit log")
        st = _audit.paper_trial_status(sd)
        check(st["selection_cycle_done"] and not st["complete"],
              "the trial records the cycle but 90 days have not passed")

        # A plain day after the cycle: no trades, floor checked.
        r4 = _cycle.run_cycle(today="2026-10-05", state_dir=sd, cfg=cfg,
                              price_source=ps("2026-10-05"),
                              fundamentals_source=fs, client=fake)
        check(r4["status"] == "complete" and not r4["orders"],
              "a non selection day trades nothing")

    # Ticker change carries the position under the new ticker.
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td) / "state"
        cfg = {"ticker_changes": {"GE": "GEHC"}}
        from pots.definitions import build_pot, BY_ID
        pot = build_pot(BY_ID["champion"], state_dir=sd,
                        start_date="2026-09-30")
        pot.buy_value("GE", 50.0, 100.0, "2026-09-30", "test")
        pot.save()
        bars2 = dict(bars)
        bars2["GEHC"] = bars["GE"]
        r = _cycle.run_cycle(today="2026-10-01", state_dir=sd, cfg=cfg,
                             price_source=price_source_factory(
                                 bars2, "2026-10-01"),
                             fundamentals_source=fs)
        pot = Pot.load("champion", state_dir=sd)
        check("GEHC" in pot.positions and "GE" not in pot.positions,
              "the position carries under the new ticker")
        evs = _audit.read_events(sd)
        check(any(e["event"] == "pond_event"
                  and e.get("kind") == "ticker_change" for e in evs),
              "the ticker change is audit logged")

    # A held name whose prices stopped is sold at its last price and
    # the run continues with four.
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td) / "state"
        cfg = {}
        from pots.definitions import build_pot, BY_ID
        pot = build_pot(BY_ID["champion"], state_dir=sd,
                        start_date="2026-09-01")
        stale = [b for b in bars["VZ"] if b["d"] <= "2026-09-10"]
        last_px = stale[-1]["c"]
        pot.buy_value("VZ", 50.0, last_px, "2026-09-01", "test")
        pot.buy_value("BAC", 40.0, bars["BAC"][-1]["c"], "2026-09-01",
                      "test")
        pot.save()
        bars3 = dict(bars)
        bars3["VZ"] = stale
        r = _cycle.run_cycle(today="2026-10-01", state_dir=sd, cfg=cfg,
                             price_source=price_source_factory(
                                 bars3, "2026-10-01"),
                             fundamentals_source=fs)
        pot = Pot.load("champion", state_dir=sd)
        check("VZ" not in pot.positions and "BAC" in pot.positions,
              "the delisted name is sold at its last price, the run "
              "continues with the rest")
        check(any(e["event"] == "pond_event"
                  and e.get("kind") == "delisted_or_acquired"
                  for e in _audit.read_events(sd)),
              "the delisting is audit logged")

    # Phase 1 refuses live mode outright.
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td) / "state"
        cfg = {"trading_mode": "live",
               "live_enabled_at": "2026-01-01",
               "alpaca_live_key_id": "LIVEKEY1234",
               "alpaca_live_secret_key": "livesecret1234"}
        r = _cycle.run_cycle(today="2026-10-01", state_dir=sd, cfg=cfg,
                             price_source=ps("2026-10-01"),
                             fundamentals_source=fs)
        check(r["status"] == "failed" and "Phase 1" in r["reason"],
              "live mode is refused in Phase 1")


class PartialFillClient(FakeClient):
    """Fills exactly half of every order's quantity."""

    def submit_order(self, symbol, side, qty=None, notional=None, **kw):
        px = self._open_price(symbol)
        full_q = float(notional) / px if notional is not None else float(qty)
        q = full_q / 2.0
        self.submitted.append({"symbol": symbol, "side": side, "qty": q,
                               "notional": notional,
                               "client_order_id": kw.get("client_order_id")})
        return {"id": f"fake-{len(self.submitted)}", "status": "filled",
                "filled_qty": repr(q), "filled_avg_price": repr(px),
                "client_order_id": kw.get("client_order_id")}


def test_adversarial_fixes(champ, bars, pb, eq, sh):
    print("adversarial fix step regressions (G1-G3, Y2, Y3, Y5, Y7, P1)")
    from datetime import date as _date
    ps = lambda upto: price_source_factory(bars, upto)
    fs = lambda: (eq, sh)

    # The audit log is hash chained: an edited or deleted line breaks
    # the chain and the gate fails closed (attacks G1, G2, G3).
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td)
        for ev in ("cycle_start", "note", "cycle_complete"):
            _audit.record(ev, state_dir=sd, mode="paper", reconciled=True)
        ok, problem = _audit.verify_integrity(sd)
        check(ok and problem is None, "a freshly written log verifies")
        p = _audit.audit_path(sd)
        lines = p.read_text().splitlines()
        lines[1] = lines[1].replace('"note"', '"noteX"')
        p.write_text("\n".join(lines) + "\n")
        ok, problem = _audit.verify_integrity(sd)
        check(not ok and problem, "an edited line breaks the chain")
        st = _audit.paper_trial_status(sd)
        check(not st["complete"] and st["log_integrity"] == "broken",
              "the gate fails closed on a damaged log")
        p.write_text("\n".join([lines[0], lines[2]]) + "\n")
        ok, _ = _audit.verify_integrity(sd)
        check(not ok, "a deleted line breaks the chain")

    # Simulated cycles never count toward the trial (attack Y2).
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td)
        _audit.record("cycle_complete", state_dir=sd, mode="paper",
                      reconciled=True, simulated=True)
        _audit.record("selection_cycle_complete", state_dir=sd,
                      mode="paper", simulated=True)
        st = _audit.paper_trial_status(
            sd, today=_date.today() + timedelta(days=120))
        check(not st["complete"] and st["started"] is None
              and not st["selection_cycle_done"],
              "simulated runs are not paper trial evidence")

    # A preview's expiry cannot be extended by editing its file (P1).
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td)
        pv = _preview.build_preview(
            [{"symbol": "AAPL", "side": "buy", "notional": 20.0,
              "order_type": "market", "time_in_force": "day"}],
            mode="paper", prices={"AAPL": 100.0}, held_values={},
            pot_equity=100.0, caps_ok=True)
        _preview.save_preview(pv, sd)
        data = json.loads((sd / _preview.PREVIEW_FILE).read_text())
        data["expires_at"] = (datetime.now() + timedelta(days=365)
                              ).isoformat(timespec="seconds")
        (sd / _preview.PREVIEW_FILE).write_text(json.dumps(data))
        try:
            _preview.require_confirmation(_preview.load_preview(sd),
                                          pv["preview_id"],
                                          state_dir=sd)
            check(False, "an edited preview expiry is refused")
        except _preview.PreviewError:
            check(True, "an edited preview expiry is refused")

    # A ticker change onto a held name is refused, loudly (Y3).
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td) / "state"
        from pots.definitions import build_pot, BY_ID
        from pots.pot import Pot
        pot = build_pot(BY_ID["champion"], state_dir=sd,
                        start_date="2026-09-30")
        cvx_px = [b for b in bars["CVX"] if b["d"] <= "2026-09-30"][-1]["c"]
        xom_px = [b for b in bars["XOM"] if b["d"] <= "2026-09-30"][-1]["c"]
        pot.buy_value("CVX", 6.0, cvx_px, "2026-09-30", "test")
        pot.buy_value("XOM", 6.0, xom_px, "2026-09-30", "test")
        pot.save()
        xom_before = Pot.load("champion", state_dir=sd) \
            .positions["XOM"]["shares"]
        r = _cycle.run_cycle(today="2026-10-05", state_dir=sd,
                             cfg={"ticker_changes": {"CVX": "XOM"}},
                             price_source=ps("2026-10-05"),
                             fundamentals_source=fs)
        pot = Pot.load("champion", state_dir=sd)
        check(r["status"] == "failed"
              and "CVX" in pot.positions
              and abs(pot.positions["XOM"]["shares"] - xom_before) < 1e-9,
              "a ticker change onto a held name is refused and both "
              "positions survive")
        check(any(e.get("kind") == "ticker_change_collision"
                  for e in _audit.read_events(sd)
                  if e["event"] == "pond_event"),
              "the collision is audit logged as its own event kind")

    # A uniformly stale feed is refused against today (Y5).
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td) / "state"
        r = _cycle.run_cycle(today="2026-11-20", state_dir=sd, cfg={},
                             price_source=ps("2026-09-01"),
                             fundamentals_source=fs)
        check(r["status"] == "failed" and "looks stopped" in r["reason"],
              "a feed 80 days stale is refused, not traded on")
        check(not any(e["event"] == "cycle_complete"
                      for e in _audit.read_events(sd)),
              "a stale run records no completed cycle")

    # Partial fills surface as mismatches, with the invested
    # fraction reported (Y7); order ids are selection derived (Y8).
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td) / "state"
        cfg = {"champion_pot_size": 100}
        _cycle.run_cycle(today="2026-10-01", state_dir=sd, cfg=cfg,
                         price_source=ps("2026-10-01"),
                         fundamentals_source=fs)
        fake = PartialFillClient(bars, "2026-10-02")
        r2 = _cycle.run_cycle(today="2026-10-02", state_dir=sd, cfg=cfg,
                              price_source=ps("2026-10-02"),
                              fundamentals_source=fs, client=fake)
        r3 = _cycle.run_cycle(today="2026-10-02", state_dir=sd, cfg=cfg,
                              price_source=ps("2026-10-02"),
                              fundamentals_source=fs, client=fake,
                              confirm=True,
                              preview_id=r2["preview"]["preview_id"])
        check(r3["status"] == "complete" and r3["mismatches"],
              "half size fills complete only with mismatch records")
        check(r3.get("partial_fills")
              and r3["invested_fraction"] is not None
              and r3["invested_fraction"] < 0.75,
              "the invested fraction after partial fills is reported")
        check(all(str(s["client_order_id"]).startswith(
                  "champ-2026-10-01-") for s in fake.submitted),
              "client order ids derive from the selection, not the "
              "preview, so a re-run recognises them")


def main():
    champ, bars, pb, eq, sh = replay_data()
    test_ranking_equivalence(champ, bars, pb, eq, sh)
    test_caps()
    test_audit_and_paper_gate()
    test_preview_rules()
    test_kill_switch_and_adapter(bars)
    test_first_run_and_keystore()
    test_full_cycle_and_pond_events(champ, bars, pb, eq, sh)
    test_adversarial_fixes(champ, bars, pb, eq, sh)
    print(f"CYCLE TESTS PASSED ({CHECKS} checks)")


if __name__ == "__main__":
    main()
