# Atlas Gate — AI Stock App Dashboard

Local web dashboard for Terry's AI stock app. It runs entirely on your own
machine, uses **only the Python standard library** (no pip installs, no
internet, no CDN files), and never sends data anywhere.

## Run it

From the app folder:

```
cd stock-app\app
python dashboard\server.py
```

Then open in your browser:

```
http://localhost:8765
```

Stop it with Ctrl+C. To use a different port, set `DASHBOARD_PORT`
(e.g. `set DASHBOARD_PORT=8770` on Windows) before running.

Requires plain Python 3 (3.8+). Nothing to install.

## Binding, authentication, and sessions

- **Bind:** the server binds to `127.0.0.1` (loopback) by default, via
  `"dashboard_bind"` in `../config.local.json`. It is reachable only from
  this machine. A non-loopback bind is a deliberate act: it requires
  `"dashboard_allow_remote_exposure": true` **and** a dashboard password
  (below) — without both, the server refuses to start on a non-loopback
  address. `"dashboard_remote_host"` names the one extra hostname the
  Host-header allowlist accepts when remote exposure is configured.
- **Viewing it from another machine (e.g. a VPS):** do not expose the
  port. Keep the loopback bind on the server and use an SSH tunnel from
  your own computer — `ssh -L 8765:127.0.0.1:8765 user@your-vps` — then
  open `http://localhost:8765`. The app provides **no TLS of its own**;
  anything beyond the tunnel needs a TLS reverse proxy or a VPN.
- **Dashboard password:** set one from the app folder with
  `python run.py dashboard-password` (remove it with
  `python run.py dashboard-password --clear`). Only a salted hash
  (`dashboard_password_salt` / `dashboard_password_hash`, PBKDF2-HMAC via
  the standard library) is stored in `../config.local.json`, together
  with `"dashboard_auth_enabled": true`. The password is **mandatory for
  any non-loopback bind** and recommended on loopback too. There are no
  default credentials, ever.
- **Sessions:** logging in exchanges the password for a session cookie
  marked `HttpOnly; SameSite=Lax` (plus `Secure` when the dashboard is
  served behind TLS). The session id is **rotated at login** so a planted
  session id cannot be reused (fixation defence). Unauthenticated
  requests to every page and to `/api/state` are refused/redirected to
  the login page. Repeated failed logins trigger a lockout counter —
  brute-forcing the password is deliberately slow and then blocked.
- **Host and CSRF defences (unchanged in spirit, now load-bearing):**
  requests whose `Host` is not in the allowlist (`localhost`,
  `127.0.0.1`, `::1`, plus `dashboard_remote_host` when configured) are
  refused — that is the DNS-rebinding defence. Every state-changing POST
  requires the per-session CSRF token, and a POST whose `Origin`/`Referer`
  host is not the dashboard's own host is refused.

## Pages

| Page | URL | What it shows |
|---|---|---|
| Overview | `/` | Verdict row (total balance + day change), alerts strip, every pot plotted against SPY, pots table, holdings rail |
| Pot Detail | `/pot` | One pot: equity curve vs SPY, positions, trade log, floor / episode / restart status |
| Watcher | `/watcher` | Radar feed: insider Form 4, 13D, 13F, congressional items with priority flags. Radar only — never trades |
| Reports | `/reports` | Dated daily reports; click one to read it |
| Trading Mode | `/mode` | Paper/live switch: current mode, key presence, the paper-first warning, the typed-confirmation live enable, switch back to paper, and STOP ALL |
| Key leaked? (panic) | `/panic` | "My key may have leaked": STOP ALL first, then the numbered recovery steps — regenerate the pair at Alpaca (which revokes the old pair immediately), replace the keys in `config.local.json`, verify the app sees the new keys and check the account for orders you do not recognise |

## Trading mode in the header

Every page's header shows the trading mode permanently:
**PAPER — SIMULATED MONEY** or **LIVE — REAL MONEY** (plus a
"Replay record — demo data" pill when the numbers on screen are the
replay record). In live mode a red banner with a **STOP ALL** button sits
under the header on every page; while the engine is stopped, an amber
"ENGINE STOPPED" banner with a Resume button replaces it. Mode is set in
`../config.local.json` and can only be switched to live from the Trading
Mode page, by typing the confirmation phrase, with the user's own live
keys present — otherwise the app stays in paper and says why. See the
main README's "Paper and live: the switch" section. Screenshots:
`mode-paper.png`, `mode-enable.png`, `mode-live.png`, `mode-stopped.png`
in this folder.

## Where the data comes from

- **Live state:** JSON files in `../state/` (relative to this folder, i.e.
  `stock-app/app/state/`). If a file contains a `pots` list, the dashboard
  uses it and shows the file's last-write time as the "state saved to disk"
  indicator in the footer.
- **Reports:** files in `../reports/output/` (`.json`, `.md`, `.html`, `.txt`).
- **Demo fallback:** when those folders are empty, the dashboard shows
  clearly-labeled **DEMO / replay-record** data generated from the published
  backtest finals ($100 start): Value + Momentum $544.47, Lazy Prices
  $504.34, Momentum Basket $439.45, N-F3 $505.43, Midpoint Switch B $549.43,
  SPY buy-and-hold $313.62. A banner in the alerts strip and a pill in the
  header say so on every page.

There is also a small JSON endpoint at `/api/state` for debugging.

## Safety behaviour (adversarial-QA fix round)

- **Report files** are served only if they are real files physically inside
  `../reports/output/` — a symlink planted there that points elsewhere
  (including at `config.local.json`) is refused, and report bodies are
  always shown as escaped text, never as raw HTML, so a dropped `.html`
  file cannot run script in the dashboard.
- **Mode/engine POSTs** (enable-live, switch to paper, STOP ALL, resume)
  require the per-server-run form token rendered into every form, and a
  POST whose `Origin`/`Referer` host is not the dashboard's own host is
  refused — a web page open in another tab cannot silently switch the app
  to live or stop the engine. Post-redirect messages are stored server-side
  and carried by an opaque one-time id; the Trading Mode page never
  reflects arbitrary `?msg=` text.
- **Malformed state** never takes the dashboard down: a bad pot entry is
  skipped or corrected with a visible warning on the page, and the Trading
  Mode page and STOP ALL keep working. With live state on screen, watcher
  items and equity curves come from the live record only — a pot with no
  curve of its own shows an explicit "no equity history yet" note instead
  of the replay curve, and sample watcher data keeps its SAMPLE tag.
- Unknown pot/report ids get a real **404** page; error pages show a fixed
  generic message (detail goes to the server console only); the reports
  list tags shipped sample reports **SAMPLE** and does not list
  `README.txt`. If the port is already in use, startup prints one clean
  line instead of a traceback.
- Regression tests: `python3 dashboard/test_adversarial.py` spins the
  server on an ephemeral port against a throwaway copy of the app and
  checks all of the above (dummy keys only; the real install is untouched).

## Design notes

- Dark theme by default; toggle to light in the header (choice is remembered
  in the browser).
- Green/red are used **only** for gain/loss direction — never as decoration.
- Figures are right-aligned with tabular numerals; tickers are in a mono font.
- The footer carries the standing honesty line on every page, worded for
  the active trading mode (paper: simulated money only; live: real money in
  your own account, at your own risk), and backtest returns are flattered
  by survivorship bias because no free data stack is bias-free.
- The footer also shows the app **version and release hash** (the
  `manifest_sha256` from `release_manifest.json`, built by
  `release.py`). Compare it with the value published in the official
  repository's release notes: a copy whose footer hash does not match is
  not the copy that was published — do not enter keys into it. Run
  `python run.py verify` from the app folder for the full per-file check.
