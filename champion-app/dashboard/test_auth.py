#!/usr/bin/env python3
"""Phase A suite -- dashboard authentication (E2) and remote bind (E1).

Covers: unauthenticated redirect/401, wrong password, lockout,
session rotation on login (old sid dead), logout, auth NOT required on
a plain loopback install with no password, remote-host allowlist with
a foreign Host still refused, and the network-exposure banner.

Boots the real server in throwaway copies; dummy password only.
Run: python3 dashboard/test_auth.py   (exit 0 = pass)
"""
import http.client
import http.cookiejar
import importlib.util
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
PASSWORD = "dummy-test-password-123"
_spec = importlib.util.spec_from_file_location("ag_auth", APP_SRC / "dashboard" / "auth.py")
_auth = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_auth)
SALT, HASH = _auth.hash_password(PASSWORD)

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
    def req(self, method, path, fields=None, headers=None, host=None):
        data = urlencode(fields).encode() if fields is not None else None
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method)
        for k, v in (headers or {}).items():
            r.add_header(k, v)
        if host:
            r.add_header("Host", host)
        if data is not None:
            r.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with self.opener.open(r, timeout=10) as resp:
                return resp.status, dict(resp.headers), resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    def token(self, path="/login"):
        _, _, b = self.req("GET", path)
        m = re.search(r'name="csrf_token" value="([^"]+)"', b)
        assert m, f"no csrf token on {path}"
        return m.group(1)
    def sid(self):
        for c in self.jar:
            if c.name == "ag_session":
                return c.value
        return None
    def login(self, password):
        return self.req("POST", "/login",
                        {"csrf_token": self.token("/login"), "password": password},
                        {"Origin": f"http://127.0.0.1:{self.port}"})

def make_copy(cfg):
    tmp = tempfile.mkdtemp(prefix="ag-auth-test-")
    app = Path(tmp) / "app"
    shutil.copytree(APP_SRC, app, ignore=shutil.ignore_patterns("__pycache__", "config.local.json"))
    (app / "config.local.json").write_text(json.dumps(cfg))
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

AUTH_CFG = {"trading_mode": "paper", "dashboard_auth_enabled": True,
            "dashboard_password_salt": SALT, "dashboard_password_hash": HASH}

def main():
    # ---------- 1. auth required (loopback + enabled + password) ----------
    tmp, app = make_copy(AUTH_CFG); port = free_port(); proc = boot(app, port)
    try:
        b = Browser(port)
        s, h, _ = b.req("GET", "/")
        check("unauthenticated GET / -> 303 to /login",
              s == 303 and h.get("Location") == "/login", f"status={s} loc={h.get('Location')}")
        s, _, body = b.req("GET", "/api/state")
        check("unauthenticated /api/state -> 401 JSON",
              s == 401 and "authentication required" in body, f"status={s}")
        s, _, body = b.req("GET", "/login")
        check("login page renders", s == 200 and 'name="password"' in body, f"status={s}")
        s, _, _ = b.login("wrong-password")
        check("wrong password refused (401)", s == 401, f"status={s}")
        s, _, _ = b.req("GET", "/")
        check("still unauthenticated after wrong password", s == 303, f"status={s}")
        old_sid = b.sid()
        s, h, _ = b.login(PASSWORD)
        check("correct password -> 303 to /", s == 303 and h.get("Location") == "/", f"status={s}")
        new_sid = b.sid()
        check("session id rotated on login", bool(old_sid and new_sid and old_sid != new_sid))
        # old sid is dead: a raw request carrying it is a fresh anonymous session
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("GET", "/", headers={"Cookie": f"ag_session={old_sid}"})
        r = c.getresponse(); r.read(); c.close()
        check("old session id dead after rotation (303 to /login)", r.status == 303, f"status={r.status}")
        s, _, _ = b.req("GET", "/")
        check("authenticated GET / -> 200", s == 200, f"status={s}")
        s, _, api = b.req("GET", "/api/state")
        check("authenticated /api/state -> 200", s == 200 and "trading_mode" in api, f"status={s}")
        # logout (CSRF-protected)
        tok = b.token("/mode")
        s, _, _ = b.req("POST", "/logout", {"csrf_token": tok},
                        {"Origin": f"http://127.0.0.1:{port}"})
        check("logout -> 303", s == 303, f"status={s}")
        s, _, _ = b.req("GET", "/")
        check("after logout, GET / -> 303 to /login again", s == 303, f"status={s}")
    finally:
        proc.terminate(); shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 2. lockout: 10 failures / 10 min -> 429 for 5 min ----------
    tmp, app = make_copy(AUTH_CFG); port = free_port(); proc = boot(app, port)
    try:
        b = Browser(port)
        last = None
        for _ in range(10):
            last, _, _ = b.login("wrong-password")
        check("10th failed login triggers lockout (429)", last == 429, f"status={last}")
        s, _, _ = b.login(PASSWORD)
        check("even the correct password is refused during lockout (429)",
              s == 429, f"status={s}")
    finally:
        proc.terminate(); shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 3. no password on loopback: existing behaviour preserved ---
    tmp, app = make_copy({"trading_mode": "paper"}); port = free_port(); proc = boot(app, port)
    try:
        b = Browser(port)
        s, _, _ = b.req("GET", "/")
        check("no-password loopback install: GET / -> 200 (no auth)", s == 200, f"status={s}")
        s, _, _ = b.req("GET", "/api/state")
        check("no-password loopback install: /api/state -> 200", s == 200, f"status={s}")
    finally:
        proc.terminate(); shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 4. remote bind: opt-in + password + remote host ------------
    cfg = dict(AUTH_CFG, dashboard_bind="0.0.0.0",
               dashboard_allow_remote_exposure=True,
               dashboard_remote_host="remote.example.test")
    tmp, app = make_copy(cfg); port = free_port(); proc = boot(app, port)
    try:
        b = Browser(port)
        s, _, _ = b.login(PASSWORD)
        check("remote bind: login works", s == 303, f"status={s}")
        s, _, body = b.req("GET", "/", host="remote.example.test")
        check("configured remote Host allowed (200)", s == 200, f"status={s}")
        check("exposure warning banner on every page while bound non-loopback",
              "THIS DASHBOARD IS EXPOSED ON THE NETWORK" in body)
        s, _, _ = b.req("GET", "/", host="evil.example")
        check("foreign Host still 403 on remote bind", s == 403, f"status={s}")
    finally:
        proc.terminate(); shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  ")
    return 1 if FAIL else 0

if __name__ == "__main__":
    raise SystemExit(main())
