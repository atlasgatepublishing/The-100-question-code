"""The Champion app: top-level runner (Atlas Gate Publishing).

DERIVED APP ADAPTATION of the frozen companion app's run.py (recorded
in BUILD-REPORT.md): the frozen shell assumed the install folder was
named "app" inside a project root. This copy is hermetic: every
command imports from THIS folder, whatever it is called, and two
commands are new (cycle, setup-keys, kill-switch).

Usage (from this folder, plain Python 3, no installs needed):
    python run.py              -> sync saved pot state, then serve the dashboard
    python run.py dashboard    -> same as above
    python run.py sync         -> only rebuild state/app_state.json from saved pots
    python run.py integrity    -> run the engine integrity gate (replay, ~20s)
    python run.py cycle        -> run ONE daily cycle. When the cycle has
                                  orders, it prints the order preview and
                                  stops; nothing is sent. Re-run with
                                  --confirm <preview_id> (printed by the
                                  first run, valid 15 minutes) to submit.
    python run.py setup-keys   -> first run: store YOUR OWN Alpaca paper
                                  key pair in config.local.json (prompted,
                                  never echoed) and set PAPER mode. On
                                  Windows the keys are then encrypted at
                                  rest with DPAPI for your account.
    python run.py kill-switch  -> engage STOP ALL and cancel every resting
                                  order at the broker. Positions are NOT
                                  sold. Resume from the dashboard.
    python run.py mode         -> print the trading mode (paper/live), key
                                  presence, paper trial status, and STOP
                                  ALL state -- never key values
    python run.py verify       -> verify this copy against release_manifest.json
                                  (release.py); exit 0 if every shipped file
                                  matches, 1 if anything is missing, changed,
                                  or extra
    python run.py protect-keys -> encrypt the API keys stored in
                                  config.local.json at rest (Windows DPAPI
                                  where available; see data.mode)
    python run.py dashboard-password [--clear]
                               -> set the dashboard password (prompted, never
                                  echoed; stored only as a salted hash in
                                  config.local.json) -- or, with --clear,
                                  remove the stored password and turn
                                  dashboard authentication off

The dashboard is at http://localhost:8765 (set DASHBOARD_PORT to change).

Trading mode: PAPER by default (simulated money). LIVE mode is enabled
only from the dashboard's Trading Mode page, by typing the confirmation
phrase, only when your live keys are in config.local.json, and only
after the paper trial recorded in the audit log is complete (90 days
including one completed quarterly selection cycle). It fails safe to
paper. Phase 1 of this app runs its daily cycle on paper only. See
README.md.
"""
from __future__ import annotations

import getpass
import signal
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def _cmd_verify() -> int:
    sys.path.insert(0, str(APP_DIR))
    try:
        import release as _release
    except Exception as e:
        print(f"run.py: verify is unavailable ({type(e).__name__}: {e})",
              file=sys.stderr)
        return 1
    ok, problems = _release.verify(APP_DIR)
    if ok:
        print(f"verify OK: this copy matches release_manifest.json "
              f"(version {_release.VERSION})")
        return 0
    print("verify FAILED: this copy does not match release_manifest.json:")
    for problem in problems:
        print(f"  - {problem}")
    print("Do not enter keys into a copy that fails verification. "
          "Re-download from the official repository (see README.md).")
    return 1


def _cmd_protect_keys() -> int:
    sys.path.insert(0, str(APP_DIR))
    try:
        from data import mode as _m
    except Exception as e:
        print(f"run.py: protect-keys is unavailable ({type(e).__name__}: {e})",
              file=sys.stderr)
        return 1
    fn = getattr(_m, "encrypt_config_keys", None)
    if fn is None:
        print("run.py: protect-keys is not available in this copy "
              "(data.mode.encrypt_config_keys is missing). Your keys stay "
              "in config.local.json as they are; keep that file private.",
              file=sys.stderr)
        return 1
    try:
        result = fn()
    except Exception as e:
        print(f"run.py: protect-keys failed ({type(e).__name__}: {e})",
              file=sys.stderr)
        return 1
    ok, message = True, ""
    if isinstance(result, tuple) and len(result) == 2:
        ok, message = bool(result[0]), str(result[1])
    elif isinstance(result, dict):
        ok = bool(result.get("ok", False))
        message = str(result.get("message", ""))
    elif isinstance(result, bool):
        ok = result
    elif isinstance(result, str):
        message = result
    if message:
        print(message)
    return 0 if ok else 1


def _cmd_dashboard_password(clear: bool) -> int:
    sys.path.insert(0, str(APP_DIR))
    try:
        from data import mode as _m
    except Exception as e:
        print(f"run.py: dashboard-password is unavailable "
              f"({type(e).__name__}: {e})", file=sys.stderr)
        return 1
    problem = _m.config_problem() if hasattr(_m, "config_problem") else None
    if problem is not None:
        print(f"run.py: dashboard-password was NOT changed: {problem} "
              "The config file was left untouched.", file=sys.stderr)
        return 1
    cfg = _m.load_config_strict()
    if clear:
        cfg_path = getattr(_m, "CONFIG_PATH", None)
        if cfg_path is not None and not Path(cfg_path).exists():
            print("Dashboard password cleared: no config file was found, so "
                  "no password was set. No file was created.")
            return 0
        for key in ("dashboard_password_salt", "dashboard_password_hash",
                    "dashboard_auth_enabled"):
            cfg.pop(key, None)
        try:
            _m._save_config(cfg)
        except Exception as e:
            print(f"run.py: could not save config.local.json "
                  f"({type(e).__name__}: {e})", file=sys.stderr)
            return 1
        print("Dashboard password cleared: dashboard authentication is off. "
              "The dashboard can only be exposed beyond this machine if a "
              "password is set again.")
        return 0
    try:
        from dashboard.auth import hash_password
    except Exception:
        print("run.py: dashboard-password is not available in this copy "
              "(dashboard.auth is missing), so no password was set. "
              "The config file was left untouched.", file=sys.stderr)
        return 1
    try:
        pw1 = getpass.getpass("New dashboard password: ")
        pw2 = getpass.getpass("Confirm dashboard password: ")
    except (EOFError, KeyboardInterrupt):
        print("\nrun.py: dashboard-password cancelled; nothing was changed.",
              file=sys.stderr)
        return 1
    if pw1 != pw2:
        print("run.py: the two passwords did not match; nothing was changed.",
              file=sys.stderr)
        return 1
    if len(pw1) < 10:
        print("run.py: the dashboard password must be at least 10 "
              "characters; nothing was changed.", file=sys.stderr)
        return 1
    try:
        salt_b64, hash_b64 = hash_password(pw1)
    except Exception as e:
        print(f"run.py: could not hash the password "
              f"({type(e).__name__}: {e}); nothing was changed.",
              file=sys.stderr)
        return 1
    cfg["dashboard_password_salt"] = salt_b64
    cfg["dashboard_password_hash"] = hash_b64
    cfg["dashboard_auth_enabled"] = True
    try:
        _m._save_config(cfg)
    except Exception as e:
        print(f"run.py: could not save config.local.json "
              f"({type(e).__name__}: {e})", file=sys.stderr)
        return 1
    print("Dashboard password set: dashboard authentication is now ON. "
          "You will be asked for this password when you open the dashboard. "
          "Only a salted hash was stored -- the password itself is not "
          "saved anywhere.")
    return 0


def _cmd_setup_keys() -> int:
    sys.path.insert(0, str(APP_DIR))
    try:
        from cycle.first_run import setup_paper_keys
    except Exception as e:
        print(f"run.py: setup-keys is unavailable ({type(e).__name__}: {e})",
              file=sys.stderr)
        return 1
    print("First run setup: your own Alpaca PAPER keys.")
    print("Create a free paper account at alpaca.markets, generate a paper "
          "key pair there, and paste it here. The keys are stored only in "
          "config.local.json on this machine, and are never shown again.")
    try:
        key_id = input("Alpaca PAPER key id: ").strip()
        secret = getpass.getpass("Alpaca PAPER secret key (not echoed): ")
    except (EOFError, KeyboardInterrupt):
        print("\nrun.py: setup cancelled; nothing was saved.", file=sys.stderr)
        return 1
    ok, msg = setup_paper_keys(key_id, secret)
    print(msg)
    return 0 if ok else 1


def _print_preview(preview: dict) -> None:
    print(f"ORDER PREVIEW  (mode: {preview['mode'].upper()}, "
          f"pot equity ${preview['pot_equity']:,.2f}, "
          f"cap check: {'OK' if preview['caps_ok'] else 'FAILED'})")
    for o in preview["orders"]:
        px = o.get("latest_price")
        px_txt = f"@ ${px:,.2f}" if isinstance(px, (int, float)) else ""
        print(f"  {o['side'].upper():4} {o['symbol']:6} "
              f"${o['notional']:>10,.2f} {px_txt}  -> est. "
              f"${o['est_resulting_value']:,.2f} "
              f"({(o['est_resulting_weight'] or 0) * 100:.1f}% of pot)")
    print(f"Preview id: {preview['preview_id']}  (expires "
          f"{preview['expires_at']})")
    print("Nothing has been sent. To submit exactly these orders, run:")
    print(f"    python run.py cycle --confirm {preview['preview_id']}")


def _cmd_cycle(args: list[str]) -> int:
    sys.path.insert(0, str(APP_DIR))
    confirm_id = None
    if args:
        if len(args) == 2 and args[0] == "--confirm":
            confirm_id = args[1]
        else:
            print(f"run.py: unexpected argument(s) for cycle: "
                  f"{' '.join(args)}", file=sys.stderr)
            return 2
    try:
        from cycle.daily_cycle import run_cycle
    except Exception as e:
        print(f"run.py: the daily cycle is unavailable "
              f"({type(e).__name__}: {e})", file=sys.stderr)
        return 1
    result = run_cycle(confirm=bool(confirm_id), preview_id=confirm_id)
    print(f"Daily cycle {result.get('date')}: {result.get('status')}"
          + (f" (as of {result['asof']})" if result.get("asof") else ""))
    if result.get("picks"):
        print(f"Selection: {', '.join(result['picks'])}")
    if result.get("status") == "awaiting_confirmation" and result.get("preview"):
        _print_preview(result["preview"])
        return 0
    if result.get("reason"):
        print(f"Reason: {result['reason']}")
    if result.get("simulated"):
        print("Note: no Alpaca paper keys are configured, so fills were "
              "recorded in the pot's own record only (SIMULATED, not a "
              "broker paper account). Run setup-keys to connect your "
              "paper account.")
    for m in result.get("mismatches") or []:
        print(f"MISMATCH: {m.get('symbol')} {m.get('side')}: {m.get('detail')}")
    if result.get("report"):
        print(f"Daily report: {result['report']}")
    return 0 if result.get("status") in ("complete", "halted", "ended") else 1


def _cmd_kill_switch() -> int:
    sys.path.insert(0, str(APP_DIR))
    try:
        from cycle.daily_cycle import engage_kill_switch
    except Exception as e:
        print(f"run.py: kill-switch is unavailable ({type(e).__name__}: {e})",
              file=sys.stderr)
        return 1
    result = engage_kill_switch()
    print("STOP ALL engaged. No orders will be placed in any mode until "
          "you resume from the dashboard.")
    print("Positions were NOT sold; they stay in your broker account.")
    if result.get("cancellations") is None:
        print(f"Broker cancellations: NOT done ({result.get('cancel_error')}). "
              f"Check for resting orders at the broker yourself.")
    elif result["cancellations"]:
        for c in result["cancellations"]:
            print(f"  cancelled: {c.get('symbol')} order "
                  f"{c.get('order_id')} -> {c.get('status')}")
    else:
        print("Broker cancellations: no open orders were resting.")
    return 0


def _cmd_mode() -> int:
    sys.path.insert(0, str(APP_DIR))
    from data import mode as _m
    s = _m.mode_status()
    print(f"configured mode : {s['configured_mode']}")
    print(f"effective mode  : {s['effective_mode']}"
          + ("  (LIVE - REAL MONEY)" if s["is_live"] else "  (paper - simulated money)"))
    print(f"paper keys      : {'present' if s['paper_keys_present'] else 'not set'}")
    print(f"live keys       : {'present' if s['live_keys_present'] else 'not set'}")
    print(f"engine          : {'STOPPED (STOP ALL)' if s['stopped'] else 'running'}")
    try:
        from cycle import audit as _audit
        t = _audit.paper_trial_status()
        print(f"paper trial     : {'COMPLETE' if t['complete'] else 'not complete'}"
              f" (day {t['days']} of {t['days_required']}, "
              f"selection cycle: {'done' if t['selection_cycle_done'] else 'not yet'}, "
              f"unresolved mismatches: {t['unresolved_mismatches']})")
    except Exception as e:
        print(f"paper trial     : could not be read ({type(e).__name__})")
    if s["problem"]:
        print(f"note            : {s['problem']}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["dashboard-password"]:
        if len(args) == 1:
            return _cmd_dashboard_password(clear=False)
        if len(args) == 2 and args[1] == "--clear":
            return _cmd_dashboard_password(clear=True)
        print(f"run.py: unexpected argument(s) for dashboard-password: "
              f"{' '.join(args[1:])}", file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return 2
    if args[:1] == ["cycle"]:
        return _cmd_cycle(args[1:])
    if len(args) > 1:
        print(f"run.py: unexpected extra argument(s): {' '.join(args[1:])}",
              file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return 2
    cmd = args[0] if args else "dashboard"
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if cmd == "verify":
        return _cmd_verify()
    if cmd == "protect-keys":
        return _cmd_protect_keys()
    if cmd == "setup-keys":
        return _cmd_setup_keys()
    if cmd == "kill-switch":
        return _cmd_kill_switch()
    if cmd == "cycle":
        return _cmd_cycle([])
    if cmd == "integrity":
        return subprocess.call(
            [sys.executable, str(APP_DIR / "engines" / "integrity_test.py")])
    if cmd == "mode":
        return _cmd_mode()
    if cmd in ("sync", "dashboard"):
        sys.path.insert(0, str(APP_DIR))
        try:
            import sync_state
            sync_state.main()
        except Exception as e:
            print(f"run.py: state sync failed ({type(e).__name__}: {e})",
                  file=sys.stderr)
            if cmd == "sync":
                return 1
            print("run.py: starting the dashboard with the existing state.",
                  file=sys.stderr)
        if cmd == "sync":
            return 0
        proc = subprocess.Popen(
            [sys.executable, str(APP_DIR / "dashboard" / "server.py")])

        def _forward_term(signum, frame):
            proc.terminate()
            raise SystemExit(128 + signum)

        old_term = signal.signal(signal.SIGTERM, _forward_term)
        try:
            return proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
            return 130
        finally:
            signal.signal(signal.SIGTERM, old_term)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
