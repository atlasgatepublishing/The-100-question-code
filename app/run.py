"""Atlas Gate stock app — top-level runner.

Usage (from this folder, plain Python 3, no installs needed):
    python run.py              -> sync saved pot state, then serve the dashboard
    python run.py dashboard    -> same as above
    python run.py sync         -> only rebuild state/app_state.json from saved pots
    python run.py integrity    -> run the engine integrity gate (replay, ~20s)
    python run.py mode         -> print the trading mode (paper/live), key
                                  presence, and STOP ALL state -- never values
    python run.py verify       -> verify this copy against release_manifest.json
                                  (release.py); exit 0 if every shipped file
                                  matches, 1 if anything is missing, changed,
                                  or extra
    python run.py protect-keys -> encrypt the API keys stored in
                                  config.local.json at rest (Windows DPAPI
                                  where available; see data.mode); prints what
                                  it did and exits 0/1
    python run.py dashboard-password [--clear]
                               -> set the dashboard password (prompted, never
                                  echoed; stored only as a salted hash in
                                  config.local.json) -- or, with --clear,
                                  remove the stored password and turn
                                  dashboard authentication off

The dashboard is at http://localhost:8765 (set DASHBOARD_PORT to change).

Trading mode: PAPER by default (simulated money). LIVE mode -- real orders
in your own Alpaca account, with your own live keys -- is enabled only from
the dashboard's Trading Mode page, by typing the confirmation phrase, and
only when your live keys are in config.local.json. It fails safe to paper.
See README.md, "Paper and live: the switch".
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
    # Accept (ok, message), {"ok":..., "message":...}, a bare bool, or a str.
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
        try:
            from app.dashboard.auth import hash_password  # type: ignore
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


def main() -> int:
    # F14: reject unknown extra arguments cleanly instead of ignoring them.
    # The one command that takes an argument is dashboard-password --clear.
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
    if len(sys.argv) > 2:
        print(f"run.py: unexpected extra argument(s): {' '.join(sys.argv[2:])}",
              file=sys.stderr)
        print(__doc__, file=sys.stderr)
        return 2
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dashboard"
    if cmd in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if cmd == "verify":
        return _cmd_verify()
    if cmd == "protect-keys":
        return _cmd_protect_keys()
    if cmd == "integrity":
        return subprocess.call(
            [sys.executable, "-m", "app.engines.integrity_test"],
            cwd=str(APP_DIR.parent))
    if cmd == "mode":
        sys.path.insert(0, str(APP_DIR))
        from data import mode as _m
        s = _m.mode_status()
        print(f"configured mode : {s['configured_mode']}")
        print(f"effective mode  : {s['effective_mode']}"
              + ("  (LIVE - REAL MONEY)" if s["is_live"] else "  (paper - simulated money)"))
        print(f"paper keys      : {'present' if s['paper_keys_present'] else 'not set'}")
        print(f"live keys       : {'present' if s['live_keys_present'] else 'not set'}")
        print(f"engine          : {'STOPPED (STOP ALL)' if s['stopped'] else 'running'}")
        if s["problem"]:
            print(f"note            : {s['problem']}")
        return 0
    if cmd in ("sync", "dashboard"):
        sys.path.insert(0, str(APP_DIR.parent))
        from app.sync_state import main as sync
        try:
            sync()
        except Exception as e:
            # F7/F13 (run.py side): one clean line, no traceback. For the
            # dashboard command a failed sync must not stop the dashboard
            # from starting on whatever state is already on disk.
            print(f"run.py: state sync failed ({type(e).__name__}: {e})",
                  file=sys.stderr)
            if cmd == "sync":
                return 1
            print("run.py: starting the dashboard with the existing state.",
                  file=sys.stderr)
        if cmd == "sync":
            return 0
        # R2-N6: supervise the dashboard child -- a SIGTERM to run.py
        # alone (what test harnesses and service managers send) must not
        # orphan the server on its port. Ctrl+C reaches the whole
        # process group anyway; the handler covers the targeted case.
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
