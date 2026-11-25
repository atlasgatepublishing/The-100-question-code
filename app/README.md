> ## ⚠ Only download this app from the official repository
>
> **The only official source for this app is: <OFFICIAL REPO URL>**
>
> Download it from nowhere else. Copies offered anywhere else — a lookalike
> repository, a "patched" or "premium" version, a download link in a video,
> chat, or email — may be fakes built to steal your brokerage keys. This is
> a documented, active attack on users of trading tools, not a theory.
>
> - **Stars and download counts prove nothing.** They can be bought or
>   faked. The address above is the only proof of where a copy came from.
> - **Verify your copy** before you put any keys in it. From the app
>   folder run:
>
>   ```
>   python run.py verify
>   ```
>
>   It checks every shipped file against the published release manifest
>   (`release_manifest.json` / `CHECKSUMS.sha256`). If it says FAILED, do
>   not use the copy — delete it and download again from the official
>   repository.
> - **The app never needs admin rights.** It runs as an ordinary user. A
>   copy that asks for admin rights, or asks you to turn off your
>   antivirus to run it, is a fake.
> - **The app never asks you to paste your keys into any web page, chat,
>   or email.** Your keys go into one local file, `config.local.json`, by
>   your own hand, on your own machine (see "Adding your keys" below).
>   Anything — a page, a message, a "support" person — that asks you to
>   paste keys anywhere else is a scam.

# Atlas Gate — AI Stock Trading App (v1)

A personal stock app for Terry. It runs the strategies that survived the
full testing program in `~/workspace/stock-app/backtests/`, each in its own
$100 pot, under the protection rules Terry adopted on 2026-11-21, and shows
everything on a local web dashboard.

**The app starts in PAPER mode — simulated money — and that is the
default.** It also has a paper→live switch (added 2026-11-21 at Terry's
direction, because the point of downloading it is to actually make money):
with the user's **own** Alpaca **live** keys, on their **own** machine, by
their **own** deliberate act, the app can trade real money in their own
brokerage account. The switch is built to fail safe — see
"Paper and live: the switch" below. There is no "Pot 2 / free money" pot —
it stays locked and does not exist here, in any mode.

## The pots (separate ledgers, never blended)

| Pot | Strategy | Status |
|---|---|---|
| Champion | Value + momentum, quarterly top-5 | Promoted |
| Lazy Prices | 10-K language-change (Lazy Prices) | Promoted |
| Momentum Basket | Cross-sectional momentum basket | Promoted |
| Candidate N-F3 | "Paying in Stock" (invented rule) | Candidate — paper trial decides |
| Candidate Switch B | Champion first half → champion/N-F3 blend | Candidate — paper trial decides |
| Penny Lottery | Listed sub-$5 only, volume/spread filters, limit orders only, no averaging down | Quarantined moonshot pot |
| AI Watch | Terry's AI-infrastructure top-5 forward pick, $20 × 5, buy-and-hold | **Tracking only** — no floor actions |

Every pot is reported beside a shadow SPY buy-and-hold on the same dollars
and dates. Backtest record each engine was verified against (replay,
$100 start): Champion $544.47, Lazy Prices $504.34, Momentum Basket
$439.45, N-F3 $505.43, Switch B $549.43, SPY $313.62 (2019→2026 window).

## Protection rules (the adopted v9 rules)

- Plain **−15% floor** measured from each episode's starting balance.
  **No profit ladder.**
- First halt: the pot liquidates, sits in cash **90 days**, then gets **one**
  restart at its next regular selection date, under a fresh −15% floor
  measured from the restart balance.
- Second halt: the run ends permanently. The result stays on the scoreboard.

## Running it

You need plain **Python 3** (3.10+; nothing to pip-install — the dashboard
and core use the standard library; pandas/numpy are only used by the
offline backtest engines).

```
cd app
python run.py            # syncs saved state, serves the dashboard
```

Then open **http://localhost:8765** in a browser.

Other commands:

```
python run.py integrity  # re-run the engine integrity gate (~20 seconds)
python run.py sync       # rebuild the dashboard state file from saved pots
python run.py mode       # show trading mode, key presence, STOP ALL state
```

Until keys are added (below), the dashboard opens on the **replay record**
— the published backtest results, clearly labeled as demo/replay data in
the header. That is deliberate: nothing pretends to be live when it isn't.
The header also always shows the trading mode: **PAPER — SIMULATED MONEY**
or **LIVE — REAL MONEY**.

### Adding your keys

Copy `config.example.json` to `config.local.json` and fill in **your own**
keys: free Alpaca **Paper** keys, your Alpaca **Live** keys (only if you
mean to use live mode), and a free Tiingo key. Keys are read only from that
local file — never put them in code, never share them, and the app never
logs or displays them (the dashboard shows only "present / not set").
Without the file, the app runs fully in replay/simulation mode.

**Never commit `config.local.json` to git** — not in this repo, not in a
fork, not "just for a minute." The shipped `.gitignore` already excludes
it, your `.env` files, and key files. If you ever did commit it, deleting
the commit is **not** enough: the keys stay in the history. Treat them as
leaked and follow "If you think a key leaked" below.

## Your Alpaca keys: what they can and cannot do

Read this before you paste a live key anywhere, including into this app.

- **A key CAN place and cancel orders, and liquidate positions.** Whoever
  holds your Alpaca key pair can trade your account — in the worst case,
  trade it down to zero. There is no smaller, safer kind of Alpaca key:
  Alpaca offers **no read-only keys** for direct API access.
- **A key CANNOT initiate ACH deposits or wire withdrawals.** Moving
  money out to a bank sits behind the Alpaca website login, not the API
  key. A leaked key can cause bad trades; it cannot empty your bank
  account directly. That is a real limit, but "only bad trades" can still
  cost everything in the brokerage account — treat a key like the account
  itself.
- **Alpaca offers no IP allowlist and no key expiry for direct keys.**
  A stolen key works from anywhere in the world, and it keeps working
  until you regenerate it. That is why how the key is *stored*, and how
  fast you *rotate* it, carry the whole weight — there is no broker-side
  safety net to fall back on.

Because the key itself cannot be shrunk, shrink everything around it:

- **Use a fresh key pair for this app only.** Generate a new pair in
  Alpaca for this app alone. Never reuse a pair you have pasted into any
  other tool, website, chat, or email — a pair shared anywhere must be
  treated as shared forever and rotated.
- **Fund a dedicated account with only what the pots may risk.** Keep the
  money this app is allowed to touch separate and limited, so the worst
  case is bounded by what you chose to put at risk.
- **Delete unused key pairs.** An old, forgotten pair is still a live
  pair. In Alpaca, review your key list and delete every pair you are not
  actively using.
- **Rotate yearly, and immediately on any suspicion.** Generate a fresh
  pair at least once a year even when nothing looks wrong, and the moment
  anything feels off, follow "If you think a key leaked" below.
- **Protect the Alpaca LOGIN, not just the keys.** Turn on multi-factor
  authentication (MFA) on your Alpaca account and review the account's
  key list from time to time. A phished password is worse than a leaked
  key: whoever logs in as you can simply mint brand-new keys, bypassing
  every protection in this app.

Generate keys only inside alpaca.markets, reached by typing the address
yourself — never from a link in an email, ad, or message.

### Keys from environment variables (alternative to the file)

On a server especially, you may prefer not to keep keys in a file at all.
These environment variables, when set, **take precedence over
`config.local.json`**:

```
ALPACA_PAPER_KEY_ID
ALPACA_PAPER_SECRET_KEY
ALPACA_LIVE_KEY_ID
ALPACA_LIVE_SECRET_KEY
TIINGO_API_KEY
```

An honest caveat: environment variables are **visible to other processes
run by the same user** on the machine. This is an alternative way to hold
keys, not a magic upgrade — use whichever fits how you run the machine,
and understand the trade-off either way.

### Encrypted key storage (Windows)

On Windows you can wrap the keys stored in `config.local.json` so the
file alone is worthless to a thief:

```
python run.py protect-keys
```

This encrypts the keys with **Windows DPAPI**, which binds the encryption
to **your Windows user account**. A stolen copy of the file, on its own,
yields nothing — it can only be decrypted by your account, on your
machine.

The limits, stated plainly:

- **Malware running as you can still decrypt the keys.** DPAPI stops a
  stolen *file*; it does not stop malicious software already running
  under your own account. Keep the machine itself clean and patched.
- **On non-Windows systems** there is no DPAPI, so the app falls back to
  a permissions-hardened plaintext file (readable only by your user
  account) and tells you so with a warning. On those systems, the file
  *is* the keys — protect the account and the machine accordingly.

### If you think a key leaked

Act first, investigate later. The dashboard carries the same steps on its
**"My key may have leaked" (panic) page**:

1. **STOP ALL** — press STOP ALL in the dashboard so the engine places no
   further orders.
2. **Regenerate the key pair at Alpaca.** Regeneration **revokes the old
   pair immediately** — anything still using the old keys stops working
   at once (it gets an authentication error). This is the step that
   actually closes the hole; nothing else does.
3. **Replace** the keys in `config.local.json` with the new pair.
4. **Verify** — confirm the app sees the new keys and runs as expected,
   and check your Alpaca account for orders or positions you do not
   recognise.

Then find out how it leaked, so the new pair does not leak the same way.

## Paper and live: the switch

The trading mode is a per-installation setting stored in
`config.local.json` (`"trading_mode": "paper"` or `"live"`), the same file
as your keys.

- **PAPER (default)** — simulated money. Orders, when the daily cycle runs,
  go to your Alpaca **paper** account. Nothing real can be lost.
- **LIVE** — real money. Orders go to your Alpaca **live** account and
  execute with real funds.

**Enabling live takes three things, all of them yours:** (1) your own
Alpaca live key id and secret key in `config.local.json`; (2) opening the
dashboard's **Trading Mode** page; (3) typing the confirmation phrase
exactly — `I UNDERSTAND THIS TRADES REAL MONEY`. No single click can
enable it. If the live keys are missing, enabling is refused and the app
stays in paper: **it fails safe, never live.** A config file that says
"live" without live keys also runs as paper, and the dashboard says why.
You can switch back to paper at any time on the same page.

**Read the paper-first warning before you switch** (it is also on the
Trading Mode page): these strategies are proven only in replay. The
designed path is a **60–90 day paper trial first**. Live results are
expected to be lower than the replay record — plan on the program's
haircut (roughly 18–23%/yr if the edge holds at all, vs 24–31% in replay),
and the edge may not hold. In live mode you are trading your own account
at your own risk.

**STOP ALL.** In live mode a red **STOP ALL** button sits in the banner
at the top of every dashboard page (it is also on the Trading Mode page,
in both modes). Pressing it halts every pot immediately: the engine will
place **no further orders** until you resume it from the dashboard.
STOP ALL does **not** sell or liquidate anything — positions you already
hold stay in your Alpaca account, untouched, for you to manage at the
broker. The stop is saved to disk, so it survives shutdowns.

**Protections are identical in live mode.** The adopted v9 rules — plain
−15% floor from each episode's starting balance, no profit ladder, first
halt → liquidate + 90 days cash + one restart under a fresh −15% floor,
second halt ends the run — apply unchanged with real money. The penny
lottery pot keeps its rules too (exchange-listed sub-$5 only,
volume/spread filters, limit orders only, no averaging down) and its
floor stays a **target, not a guarantee** in both modes.

**The downtime caveat now applies to live mode too.** Everything in the
hosting section below — the app can only act while it is running, a floor
breach during downtime is acted on at the next startup at the then-current
price — is true with real positions exactly as with paper ones. With real
money, that is the strongest argument for the always-on server.

## Where should it run? Home PC vs an always-on server (VPS)

**Recommendation: run it on a small paid always-on server (a VPS) if you
want it watching the market every day. A home PC is fine for looking at
the dashboard and running replays, but it is only part-time by nature.**

Honest trade-off, no hype:

- **Home PC — free, but part-time.** The app only works while the machine
  is on. When the machine is off, **nothing trades and nothing watches.**
  If the PC is off during market hours, that day is simply missed, and the
  app logs the gap rather than pretending it was watching.
- **VPS — always on, small monthly cost.** A basic VPS (a few dollars a
  month from any mainstream host) stays up 24/7, so the app is present for
  every market day. It is the only way the daily watch and the paper trial
  run uninterrupted. The cost is real money out, every month, for a
  simulation — weigh it against that.
- Either way, **your state is kept exactly as it was at the last
  shutdown.** Every pot writes its full state (cash, positions, ledger,
  floor/episode status, halt and restart dates) to disk after every
  change, and a restart picks up exactly where the last shutdown left
  off. All halt/restart timing is computed from saved calendar dates,
  never from how long the program has been running.

### Viewing the dashboard on a VPS — use an SSH tunnel

On a VPS the normal, safe pattern is: **the dashboard stays bound to
loopback on the server, and you view it through an SSH tunnel.** The port
is never exposed to the internet at all. From your own computer:

```
ssh -L 8765:127.0.0.1:8765 user@your-vps
```

Leave that connection open, then open **http://localhost:8765** in your
browser. The dashboard appears exactly as if it were running locally,
but the traffic travels inside the encrypted SSH connection.

**Do not just open the dashboard port to the internet.** If you choose to
expose it directly anyway, all of the following are required — the app
enforces the first two:

- `config.local.json` must set `"dashboard_allow_remote_exposure": true`
  (a deliberate, explicitly named opt-in), **and**
- a **dashboard password must be set** (next section) — the server
  refuses a non-loopback bind without one, **and**
- you must supply your own TLS. **The app provides NO TLS (HTTPS) of its
  own.** Put it behind a TLS reverse proxy, or reach it over a VPN,
  instead of sending a password and your account state across the
  internet in plain text.

And know this: search engines for exposed devices, such as Shodan,
continuously scan the whole internet and **index exposed ports within
days**. "Nobody will find my random port" is not a protection — the port
number is not a secret and scanners do not guess, they enumerate.

## The dashboard password

Set a password for the dashboard like this (you are prompted twice; the
password is never echoed and never stored — only a salted hash is kept in
`config.local.json`):

```
python run.py dashboard-password
```

To remove it again: `python run.py dashboard-password --clear`.

- The password is **MANDATORY for any non-loopback bind**: if the
  dashboard is configured to listen on anything other than `127.0.0.1`,
  the server **refuses to start** without one.
- It is **recommended on loopback too.** Other software — and any web
  page your browser visits — shares your machine; a password means
  opening the dashboard takes something only you know, not just a
  running process.
- Use at least 10 characters (the command enforces this) and do not
  reuse your Alpaca password.

**One limitation, stated plainly:** while the app is off it cannot act.
If a pot's floor is breached on a day the machine is down, the app cannot
sell that day — the breach is acted on at the next startup, at whatever
price is then available. The floor is a rule the app enforces when it is
awake; it is not a resting broker order watching while the app sleeps.
On a home PC that gets switched off, expect this to matter eventually.
**In LIVE mode this applies to real positions and real money** — it is
the strongest argument for the always-on server once real funds are in.

## What the parts do

- `engines/` — the five validated strategy engines, ported faithfully.
  `engines/integrity_test.py` proves each one reproduces its published
  backtest final **to the cent** in replay mode. An engine that cannot
  reproduce its record does not ship.
- `pots/` — pot ledgers, the protection (floor/episode/restart) state
  machine, pot definitions, disk persistence. `pots/test_persistence.py`
  proves a pot survives a save/kill/reload cycle exactly, including its
  restart date.
- `data/` — free data only: replay loader for the project's cached data;
  Tiingo free EOD and SEC EDGAR loaders. `data/mode.py` owns the
  paper/live switch and the STOP ALL flag (fail-safe to paper);
  `data/alpaca.py` is the only module that can place an order — paper
  endpoint or live endpoint, chosen by mode, and it refuses every order
  while STOP ALL is set. `data/test_trading_mode.py` proves the safety
  shape with dummy keys and no network.
- `watcher/` — the smart-money watcher (insider Form 4, 13D/13G, 13F,
  congressional trades). **Radar and display only — it can flag and
  display, it can never originate a trade.** News is a risk-gate display
  only. Offline, both show clearly labeled SAMPLE records.
- `reports/` — the daily report (per pot: balance, day and total P/L in
  $ and %, trades, win rate, positions, worst drawdown, costs, estimated
  taxes, watcher/news actions, distance to $1,000,000, SPY shadow) saved
  as dated files in `reports/output/`, plus the end-of-run final report.
- `dashboard/` — the local web dashboard (see
  `dashboard/README-dashboard.md`). Its **Trading Mode** page carries the
  mode display, the paper-first warning, the typed-confirmation live
  switch, and STOP ALL; the header shows the active mode on every page.

## Honesty labels that ship with the app

- Backtest returns are **flattered**: no free data stack is
  survivorship-bias-free, and the judging years (2023–2026) have been
  looked at many times during testing. The forward paper trial is the
  only judge that has not seen the answers.
- Live expectation, if the edge holds at all, is a fraction of the
  backtested pace (the program's haircut rule: plan on roughly
  18–23%/yr, not 24–31%).
- The penny pot's −15% floor is a **target, not a guarantee**: gaps and
  no-bid moments in penny stocks can jump straight through it.
- LIVE mode trades **your own** account with **your own** keys on **your
  own** machine. Nothing about your account is visible to anyone else,
  and the app sends nothing anywhere except orders to Alpaca itself.
- Estimated taxes in reports are estimates (short-term rate), labeled as
  such, not tax advice.

## For the publisher (release process)

This section is for whoever publishes the app — users do not need it.

1. **Build release zips from the tagged tree.** The artifact must provably
   equal the source users can read: build from the exact tagged commit,
   never from a dirty working folder. (The XZ lesson: malicious code that
   lived only in release tarballs, not in git, is a real attack.)
2. **Sign the version tag:**

   ```
   git tag -s v1.2.0
   ```

   A signed tag is the statement "a maintainer approved this exact point
   in history." Checksums alone cannot say that — whoever controls a
   download can replace a file and its hash list together.
3. **Publish `CHECKSUMS.sha256` in the repo AND in the release notes.**
   Generate it from the app folder with `python release.py build`, which
   also writes `release_manifest.json`; commit both. Publishing the
   checksums in two places means a tampered download has to match a
   second, separately controlled copy to go unnoticed. Users verify with
   `python run.py verify`.
4. **Where GitHub Actions is used, add artifact attestations** and tell
   users the one verification command:

   ```
   gh attestation verify <release-file> --repo <owner>/<repo>
   ```

   An attestation binds the artifact to this repository, its workflow,
   and its commit in a transparency log. It only helps if users actually
   run the verification — which is why the command is printed here, not
   buried.
