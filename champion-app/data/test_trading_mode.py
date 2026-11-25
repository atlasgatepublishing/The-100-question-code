"""Trading-mode + Alpaca adapter proof. No network, no real keys.

Run:  python3 data/test_trading_mode.py   (from app/)
Covers the safety shape of the paper->live switch:
  * default is paper; a live request without live keys fails SAFE to paper
  * enabling live needs the exact typed phrase AND the user's live keys
  * the adapter picks the endpoint by effective mode (paper vs live)
  * STOP ALL blocks every order before any network call, in both modes
  * the stop flag persists on disk across a fresh read
  * key material never appears in reprs, messages, or status dicts
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data import mode
from data.alpaca import AlpacaClient, AlpacaError, PAPER_BASE, LIVE_BASE

DUMMY_PAPER = {"alpaca_paper_key_id": "PAPERKEYID0001",
               "alpaca_paper_secret_key": "paper-secret-DUMMY"}
DUMMY_LIVE = {"alpaca_live_key_id": "LIVEKEYID0002",
              "alpaca_live_secret_key": "live-secret-DUMMY"}
ALL_SECRETS = [v for v in list(DUMMY_PAPER.values()) + list(DUMMY_LIVE.values())]


_cfg_counter = [0]


def write_cfg(td: Path, cfg: dict) -> Path:
    _cfg_counter[0] += 1
    p = Path(td) / f"config-{_cfg_counter[0]}.local.json"
    p.write_text(json.dumps(cfg))
    return p


class SpyTransport:
    """Records calls instead of making them; returns a canned account."""

    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        return 200, '{"id":"acct","status":"ACTIVE"}'


def check_no_secrets(text: str, where: str):
    for s in ALL_SECRETS:
        assert s not in text, f"secret leaked into {where}: {s}"


def main():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        sd = td / "state"

        # 1. No config at all -> paper, no keys, not stopped.
        st = mode.mode_status({}, state_dir=sd)
        assert st["effective_mode"] == "paper" and not st["is_live"]
        assert not st["paper_keys_present"] and not st["live_keys_present"]
        assert st["problem"] is None and st["stopped"] is False

        # 2. Config asks for live but has NO live keys -> fails safe to paper.
        cfgp = write_cfg(td, {"trading_mode": "live", **DUMMY_PAPER})
        cfg = json.loads(cfgp.read_text())
        st = mode.mode_status(cfg, state_dir=sd)
        assert st["configured_mode"] == "live"
        assert st["effective_mode"] == "paper", "must fail safe to paper"
        assert st["problem"] and "PAPER" in st["problem"]
        check_no_secrets(json.dumps(st), "mode_status")

        # 3. Enable with the WRONG phrase -> refused, config untouched.
        ok, msg = mode.enable_live("yes please", path=cfgp)
        assert not ok and "NOT enabled" in msg
        assert json.loads(cfgp.read_text())["trading_mode"] == "live"  # unchanged value from step 2 setup
        cfgp2 = write_cfg(td, dict(DUMMY_LIVE))  # fresh paper-default config with live keys
        ok, msg = mode.enable_live("I UNDERSTAND", path=cfgp2)
        assert not ok, "partial phrase must refuse"
        assert mode.configured_mode(json.loads(cfgp2.read_text())) == "paper"

        # 4. Enable with the right phrase but NO live keys -> refused.
        cfgp3 = write_cfg(td, dict(DUMMY_PAPER))
        ok, msg = mode.enable_live(mode.CONFIRMATION_PHRASE, path=cfgp3)
        assert not ok and "no Alpaca LIVE keys" in msg
        assert mode.configured_mode(json.loads(cfgp3.read_text())) == "paper"
        check_no_secrets(msg, "enable refusal")

        # 5. Right phrase + live keys -> enabled; status shows live.
        ok, msg = mode.enable_live(mode.CONFIRMATION_PHRASE, path=cfgp2)
        assert ok, msg
        cfg = json.loads(cfgp2.read_text())
        assert mode.effective_mode(cfg) == "live"
        st = mode.mode_status(cfg, state_dir=sd)
        assert st["is_live"] and st["live_keys_present"] and st["problem"] is None
        check_no_secrets(msg + json.dumps(st), "enable success")

        # 6. Adapter endpoint selection follows the EFFECTIVE mode.
        spy = SpyTransport()
        client = AlpacaClient.from_config(cfg, transport=spy, state_dir=sd)
        assert client.mode == "live" and client.base == LIVE_BASE
        acct = client.account()
        assert acct["status"] == "ACTIVE"
        method, url, headers, _ = spy.calls[-1]
        assert url == LIVE_BASE + "/v2/account"
        assert headers["APCA-API-KEY-ID"] == DUMMY_LIVE["alpaca_live_key_id"]
        check_no_secrets(repr(client), "client repr")

        # Same config with live keys REMOVED -> paper client, paper endpoint.
        cfg_paper = {**DUMMY_PAPER, "trading_mode": "live"}
        spy2 = SpyTransport()
        client2 = AlpacaClient.from_config(cfg_paper, transport=spy2, state_dir=sd)
        assert client2.mode == "paper" and client2.base == PAPER_BASE

        # No keys at all -> client construction refuses.
        try:
            AlpacaClient.from_config({}, transport=spy2, state_dir=sd)
            raise AssertionError("client without keys must refuse")
        except AlpacaError:
            pass

        # 7. Phase 1 live lock at the adapter (adversarial fix step,
        #    attack A1): a LIVE order is refused by the adapter itself,
        #    before any network call, whatever the config says. (The
        #    frozen suite expected the live order to go through; that
        #    expectation is the defect A1 documents, and this step now
        #    pins the Phase 1 behaviour instead.) A paper order on a
        #    paper client still goes through.
        spy3 = SpyTransport()
        client3 = AlpacaClient.from_config(cfg, transport=spy3, state_dir=sd)
        try:
            client3.submit_order("AAPL", "buy", notional=10.0)
            raise AssertionError("Phase 1 adapter must refuse live orders")
        except AlpacaError as e:
            assert "Phase 1" in str(e)
        assert not spy3.calls, "a refused live order makes no network call"
        spy3p = SpyTransport()
        client3p = AlpacaClient.from_config({**DUMMY_PAPER},
                                            transport=spy3p, state_dir=sd)
        client3p.submit_order("AAPL", "buy", notional=10.0)
        assert spy3p.calls and spy3p.calls[-1][1] == PAPER_BASE + "/v2/orders"

        # 8. STOP ALL: persisted on disk, blocks orders before ANY network
        #    call, in live AND paper clients alike.
        info = mode.set_stopped(True, state_dir=sd)
        assert info["stopped"] and info["stopped_at"]
        assert mode.is_stopped(state_dir=sd) is True  # fresh read from disk
        allowed, reason = mode.orders_permitted(cfg, state_dir=sd)
        assert not allowed and "STOPPED" in reason
        for c in (client3, client2):
            before = len(spy3.calls)
            try:
                c.submit_order("AAPL", "buy", notional=10.0)
                raise AssertionError("stopped engine must refuse orders")
            except AlpacaError as e:
                assert "STOP ALL" in str(e)
        assert len(spy3.calls) == before, "no network call may happen while stopped"

        # 9. Resume clears the flag; paper orders flow again. The
        #    live client stays refused: the Phase 1 lock is not the
        #    stop, and resuming does not lift it.
        mode.set_stopped(False, state_dir=sd)
        assert mode.is_stopped(state_dir=sd) is False
        client3p.submit_order("AAPL", "buy", notional=10.0)
        try:
            client3.submit_order("AAPL", "buy", notional=10.0)
            raise AssertionError("live orders stay refused in Phase 1")
        except AlpacaError as e:
            assert "Phase 1" in str(e)

        # 10. Back to paper: disable_live flips config, effective mode paper.
        ok, msg = mode.disable_live(path=cfgp2)
        assert ok
        cfg = json.loads(cfgp2.read_text())
        assert mode.effective_mode(cfg) == "paper"
        check_no_secrets(msg, "disable message")

        # 11. (QA B1) A corrupt STOP ALL file fails CLOSED, and deleting
        #     the primary control file while stopped does NOT resume:
        #     the redundant marker still says stopped.
        mode.set_stopped(True, state_dir=sd)
        (sd / "engine_control.json").write_text("CORRUPT{{{")
        assert mode.is_stopped(state_dir=sd) is True
        allowed, _ = mode.orders_permitted(cfg, state_dir=sd)
        assert not allowed
        mode.set_stopped(True, state_dir=sd)
        (sd / "engine_control.json").unlink()
        assert mode.is_stopped(state_dir=sd) is True, "marker must keep the stop"
        mode.set_stopped(False, state_dir=sd)
        assert mode.is_stopped(state_dir=sd) is False

        # 12. (QA B7) The confirmation phrase is EXACT: surrounding
        #     whitespace refuses, non-string input refuses cleanly.
        cfgp4 = write_cfg(td, dict(DUMMY_LIVE))
        ok, _ = mode.enable_live(" " + mode.CONFIRMATION_PHRASE + " ", path=cfgp4)
        assert not ok
        ok, _ = mode.enable_live(123, path=cfgp4)
        assert not ok
        assert mode.configured_mode(json.loads(cfgp4.read_text())) == "paper"

        # 13. (QA B4) Every order carries a client_order_id.
        spy4 = SpyTransport()
        client4 = AlpacaClient.from_config({**DUMMY_PAPER}, transport=spy4, state_dir=sd)
        client4.submit_order("AAPL", "buy", notional=10.0)
        payload = json.loads(spy4.calls[-1][3])
        assert payload.get("client_order_id"), "order must carry client_order_id"

    print("test_trading_mode: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
