#!/usr/bin/env python3
"""W5 suite -- Horizon Picker page, per-pot CD benchmark, first-run setup.

Covers:
  * /picker renders all 9 buckets in Terry's order, with tier labels
    (PROMOTED / CANDIDATE / VARIANT-CANDIDATE), against BOTH the shipped
    picker.py registry AND a stub implementing the task contract
    (BUCKETS as name strings, available_offerings() -> {bucket: [dict]}).
  * The floor-free Yearly offering carries its red floor-free warning
    banner, before its select control; the 3 Days honest note shows.
  * Selecting an offering creates its own $100 pot file.
  * The pot page benchmark section: "CD comparison not yet available."
    when cd_shadow.series() returns None; real numbers when a fake
    series is injected (a fake data/cd_shadow.py in the throwaway copy).
  * First-run setup: fresh install (no config at all) -> setup page ->
    create name+password -> hash-only storage -> logout -> password-only
    login (name displayed, never re-asked) -> wrong password refused ->
    /setup closed permanently (GET and POST 404, hash unchanged).

Boots the real server in throwaway copies ONLY; the real install is
never touched (no config.local.json is created there).
Run: python3 dashboard/test_picker_login.py   (exit 0 = pass)
"""
import http.cookiejar
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

APP_SRC = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PASSWORD = "dummy-setup-password-42"
OWNER = "Terry Test"

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail if not cond else ''}", flush=True)

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None

class Browser:
    def __init__(self, port):
        self.port = port
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), NoRedirect())
    def req(self, method, path, fields=None):
        data = urlencode(fields).encode() if fields is not None else None
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method)
        if data is not None:
            r.add_header("Content-Type", "application/x-www-form-urlencoded")
            r.add_header("Origin", f"http://127.0.0.1:{self.port}")
        try:
            with self.opener.open(r, timeout=10) as resp:
                return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    def token(self, path):
        _, _, b = self.req("GET", path)
        m = re.search(r'name="csrf_token" value="([^"]+)"', b)
        assert m, f"no csrf token on {path}"
        return m.group(1)
    def login(self, password):
        return self.req("POST", "/login",
                        {"csrf_token": self.token("/login"), "password": password})

def make_copy(cfg, extra=None):
    """Throwaway copy of the app. cfg=None means NO config file at all
    (a pristine first-run install). extra: {relpath: text} overlays."""
    tmp = tempfile.mkdtemp(prefix="ag-w5-test-")
    app = Path(tmp) / "app"
    shutil.copytree(APP_SRC, app, ignore=shutil.ignore_patterns(
        "__pycache__", "config.local.json"))
    if cfg is not None:
        (app / "config.local.json").write_text(json.dumps(cfg))
    for rel, text in (extra or {}).items():
        p = app / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp, app

def boot(app, port):
    env = dict(os.environ, DASHBOARD_PORT=str(port))
    proc = subprocess.Popen([sys.executable, str(app / "dashboard" / "server.py")],
                            cwd=str(app), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    b = Browser(port)
    for _ in range(60):
        try:
            b.req("GET", "/favicon.ico"); return proc
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("server did not start")

BUCKETS = ["Daily", "3 Days", "Weekly", "Bi-Weekly", "Monthly",
           "Every 3 Months", "Every 6 Months", "Yearly", "Long"]

CONTRACT_PICKER_STUB = '''
BUCKETS = ["Daily", "3 Days", "Weekly", "Bi-Weekly", "Monthly",
           "Every 3 Months", "Every 6 Months", "Yearly", "Long"]

def available_offerings():
    return {
        "Daily": [{"pot_id": "champion", "name": "Stub Champion Daily",
                   "tier": "PROMOTED", "finals_text": "Final $544.47 per $100",
                   "worst_fall": -21.5, "floor_free": False, "warning": None,
                   "note": None, "is_default": True}],
        "3 Days": [{"pot_id": "champion", "name": "Stub Daily Borrowed",
                    "tier": "CANDIDATE", "finals_text": "Final $544.47 per $100",
                    "worst_fall": -21.5, "floor_free": False, "warning": None,
                    "note": "STUB THREE DAY HONEST NOTE", "is_default": False}],
        "Yearly": [{"pot_id": "champion", "name": "Stub Floor Free Yearly",
                    "tier": "VARIANT-CANDIDATE", "finals_text": "Final $1,487.30 per $100",
                    "worst_fall": -33.5, "floor_free": True,
                    "warning": "STUB FLOOR FREE WARNING TEXT", "note": None,
                    "is_default": False}],
    }
'''

CD_NONE = '''
def series(start_date, end_date, start_cash=100.0):
    return None
'''

CD_FAKE = '''
def series(start_date, end_date, start_cash=100.0):
    return [[start_date, float(start_cash)], [end_date, 112.34]]
'''

def picker_checks(tag, body):
    pos = -1
    in_order = True
    for b in BUCKETS:
        i = body.find(f">{b}<")
        if i < 0 or i < pos:
            in_order = False
            break
        pos = i
    check(f"{tag}: all 9 buckets render in Terry's order", in_order)
    for label in ("PROMOTED", "CANDIDATE", "VARIANT-CANDIDATE"):
        check(f"{tag}: tier label {label} shown", label in body)

def main():
    # ---------- 1. picker against the shipped registry ----------
    tmp, app = make_copy({"trading_mode": "paper"}); port = free_port(); proc = boot(app, port)
    try:
        b = Browser(port)
        s, _, body = b.req("GET", "/picker")
        check("picker page renders (shipped registry)", s == 200, f"status={s}")
        if s == 200:
            picker_checks("shipped registry", body)
            yi = body.find("Yearly")
            seg = body[yi:yi + 6000] if yi >= 0 else ""
            check("shipped registry: floor-free warning banner on the Yearly card",
                  "floor-free-banner" in seg and "NO -15% safety floor" in seg)
            check("shipped registry: floor-free warning appears BEFORE the select control",
                  0 <= seg.find("floor-free-banner") < seg.find("/picker/select"))
            check("shipped registry: 3 Days honest note present",
                  "No system in the tested record works on a 3-day rhythm" in body)
            check("shipped registry: champion marked as the app default",
                  "APP DEFAULT" in body)
        # selecting an offering creates its own pot
        tok = None
        m = re.search(r'name="csrf_token" value="([^"]+)"', body)
        tok = m.group(1) if m else b.token("/mode")
        s, h, _ = b.req("POST", "/picker/select", {"csrf_token": tok, "pot_id": "champion"})
        check("picker select -> 303 back to /picker",
              s == 303 and (h.get("Location") or "").startswith("/picker"), f"status={s}")
        check("picker select created the champion pot file ($100 pot machinery)",
              (app / "state" / "champion.json").exists())
    finally:
        proc.terminate(); shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 2. picker against the task-contract stub ----------
    tmp, app = make_copy({"trading_mode": "paper"}, {"picker.py": CONTRACT_PICKER_STUB})
    port = free_port(); proc = boot(app, port)
    try:
        b = Browser(port)
        s, _, body = b.req("GET", "/picker")
        check("picker page renders (contract stub)", s == 200, f"status={s}")
        if s == 200:
            picker_checks("contract stub", body)
            yi = body.find("Yearly")
            seg = body[yi:yi + 6000] if yi >= 0 else ""
            check("contract stub: floor-free warning on the Yearly offering card",
                  "floor-free-banner" in seg and "STUB FLOOR FREE WARNING TEXT" in seg)
            check("contract stub: 3 Days note present", "STUB THREE DAY HONEST NOTE" in body)
            check("contract stub: published finals + worst fall shown before select",
                  seg.find("Final $1,487.30") >= 0
                  and seg.find("Final $1,487.30") < seg.find("/picker/select"))
    finally:
        proc.terminate(); shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 3. CD benchmark: not available ----------
    tmp, app = make_copy({"trading_mode": "paper"}, {"data/cd_shadow.py": CD_NONE})
    port = free_port(); proc = boot(app, port)
    try:
        b = Browser(port)
        s, _, body = b.req("GET", "/pot?id=vm")
        check("pot page renders with CD module returning None", s == 200, f"status={s}")
        check("benchmark heading names pot vs SPY vs bank CD",
              "This pot vs SPY vs what a bank CD would have done over the same stretch" in body)
        check("CD section shows the not-available text when series() is None",
              "CD comparison not yet available." in body)
    finally:
        proc.terminate(); shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 4. CD benchmark: fake series injected ----------
    tmp, app = make_copy({"trading_mode": "paper"}, {"data/cd_shadow.py": CD_FAKE})
    port = free_port(); proc = boot(app, port)
    try:
        b = Browser(port)
        s, _, body = b.req("GET", "/pot?id=vm")
        check("pot page renders with a fake CD series", s == 200, f"status={s}")
        check("CD section shows the injected CD value ($112.34)",
              "$112.34" in body and "Bank CD" in body)
        check("not-available text absent when a series exists",
              "CD comparison not yet available." not in body)
    finally:
        proc.terminate(); shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 5. first-run setup flow ----------
    tmp, app = make_copy(None)  # pristine: no config.local.json at all
    port = free_port(); proc = boot(app, port)
    try:
        b = Browser(port)
        s, h, _ = b.req("GET", "/")
        check("fresh install: GET / -> 303 to /setup",
              s == 303 and h.get("Location") == "/setup", f"status={s} loc={h.get('Location')}")
        s, _, body = b.req("GET", "/setup")
        check("setup page renders with name + password fields",
              s == 200 and 'name="owner_name"' in body and 'name="password"' in body,
              f"status={s}")
        tok = b.token("/setup")
        s, _, _ = b.req("POST", "/setup", {"csrf_token": tok, "owner_name": OWNER,
                                           "password": PASSWORD,
                                           "password_confirm": "different-password"})
        check("mismatched passwords refused (400), nothing saved", s == 400, f"status={s}")
        check("no config written after a refused setup",
              not (app / "config.local.json").exists())
        tok = b.token("/setup")
        s, h, _ = b.req("POST", "/setup", {"csrf_token": tok, "owner_name": OWNER,
                                           "password": PASSWORD,
                                           "password_confirm": PASSWORD})
        check("setup create -> 303 to /", s == 303 and h.get("Location") == "/",
              f"status={s} loc={h.get('Location')}")
        cfg_text = (app / "config.local.json").read_text()
        cfg = json.loads(cfg_text)
        check("config stores a password hash + salt",
              bool(cfg.get("dashboard_password_hash")) and bool(cfg.get("dashboard_password_salt")))
        check("config stores the owner name", cfg.get("dashboard_owner_name") == OWNER)
        check("plaintext password is nowhere in the config", PASSWORD not in cfg_text)
        hash_before = cfg["dashboard_password_hash"]
        s, _, _ = b.req("GET", "/")
        check("after setup the creator is signed in (GET / -> 200)", s == 200, f"status={s}")
        # logout, then password-only entry
        tok = b.token("/mode")
        s, _, _ = b.req("POST", "/logout", {"csrf_token": tok})
        check("logout -> 303", s == 303, f"status={s}")
        s, _, body = b.req("GET", "/login")
        check("login page displays the stored owner name", s == 200 and OWNER in body,
              f"status={s}")
        check("login page never re-asks for the name (password only)",
              'name="owner_name"' not in body and 'name="password"' in body)
        s, _, _ = b.login("wrong-password")
        check("wrong password refused (401)", s == 401, f"status={s}")
        s, h, _ = b.login(PASSWORD)
        check("correct password -> 303 to / (password-only entry)",
              s == 303 and h.get("Location") == "/", f"status={s}")
        # setup is closed permanently now
        s, _, _ = b.req("GET", "/setup")
        check("GET /setup after creation -> 404 (closed)", s == 404, f"status={s}")
        tok = b.token("/mode")
        s, _, _ = b.req("POST", "/setup", {"csrf_token": tok, "owner_name": "Mallory",
                                           "password": "another-password-1",
                                           "password_confirm": "another-password-1"})
        check("POST /setup after creation -> 404 (closed)", s == 404, f"status={s}")
        cfg2 = json.loads((app / "config.local.json").read_text())
        check("credentials unchanged after the closed-setup POST",
              cfg2.get("dashboard_password_hash") == hash_before
              and cfg2.get("dashboard_owner_name") == OWNER)
    finally:
        proc.terminate(); shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
    return 1 if FAIL else 0

if __name__ == "__main__":
    raise SystemExit(main())
