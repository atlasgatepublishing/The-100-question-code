# BUILD REPORT — AI Stock Trading App v1
Built 2026-11-21 (coordinator + 4 parallel module agents). Simulation/paper only.
**Updated 2026-11-21 (v1.1): the paper→live switch was added at Terry's
direction — see the v1.1 section at the end of this report. Statements
below that say "paper only" describe v1 as originally built.**

## Verdict
The app is built and verified. The integrity gate — the rule that an engine
which cannot reproduce its published record does not ship — **passed 11/11,
to the cent**, re-run independently by the coordinator after assembly.

## Integrity results (replay, $100 start, plain −15% floor basis)
`python3 -m app.engines.integrity_test` → `ALL PASS: 11/11` (full output in
`engines/integrity_results.json`):

| Engine | Continuous | Validation |
|---|---|---|
| Value + Momentum (champion) | $544.47 ✓ | $288.05 ✓ |
| Lazy Prices | $504.34 ✓ | $324.12 ✓ |
| Momentum Basket | $439.45 ✓ | $208.27 ✓ |
| N-F3 Paying in Stock | $505.43 ✓ | $289.53 ✓ |
| Switch B (continuous) | $549.43 ✓ | — |
| SPY shadow | $313.62 ✓ | $187.77 ✓ |

**Source correction found during the port (important):** the brief named
`v4/value-momentum.py` and `v4/momentum-basket.py` as the champion/basket
sources, but those scripts do NOT produce the published figures (they give
$99.61 halted / $627.39 and $1,632.09 / $306.99 respectively). The published
records come from the validated variants, which are what the app ports:
champion = `v4/value-momentum-plainfloor.py`; basket =
`v4/momentum-basket-honest.py` run with the ladder-free plain floor (the
program's own walk-forward re-run confirmed the ladder never changed these
windows: identical $439.45). Each engine module's docstring documents this.

## What was built
- `engines/` — vm, lazy_prices, momentum_basket, nf3, switch_b, spy shadow,
  common interface, integrity test + results.
- `data/` — replay loader (project caches, works with no keys), Tiingo free
  EOD + SEC EDGAR loaders for live-paper mode; keys only from
  `config.local.json` (never in code, never logged); `config.example.json`
  provided.
- `pots/` — Pot + ledger (hard $100 budget, fractional shares, costs
  0.10%/side + flat $0.01 per sell order — the backtest code's actual
  convention; a brief that said "per share" was corrected against the code
  on disk and the correction is documented in `pot.py`), the adopted v9
  protection state machine (plain −15% floor, no ladder, first halt →
  liquidate + 90 days cash + one restart under an episode-2 −15% floor,
  second halt ends the run), and the seven pot definitions. **No Pot 2 /
  free-money pot exists** (asserted in code and in the persistence test).
- **Persistence** — every pot writes its complete state (cash, positions,
  ledger, protection/episode state, halt + restart dates) to
  `state/<pot_id>.json` atomically after every change. `pots/test_persistence.py`
  PASSED: save → kill → reload reproduces every field, and restart
  eligibility is computed from the saved halt date + 90 calendar days
  (2026-02-02 → 2026-05-03), never from process uptime. A second-halt pot
  reloads from disk as permanently ended.
- `watcher/` — radar/display only, structurally incapable of originating a
  trade (no trading imports; verified by grep). Form 4 / 13D / 13G / 13F /
  congressional with the design's weighting and honest lag labels; news
  risk-gate display (8-K item codes). Offline it serves clearly labeled
  SAMPLE records.
- `reports/` — daily report (Terry's full spec, .md + .json, dated) and
  final report generators; labeled sample outputs in `reports/output/`.
- `dashboard/` — stdlib-only local web dashboard (no pip installs; runs on
  Terry's Windows PC with plain Python 3). Dark-first + light theme,
  verdict row, alerts strip, every pot plotted against SPY, holdings rail,
  strict green/red = gain/loss only, tabular numerals. Launched and
  **screenshotted by the coordinator** — all four pages visually inspected
  (screenshots saved as `dashboard/overview.png`, `pot.png`, `watcher.png`,
  `reports.png`).
- `run.py` — `python run.py` (dashboard), `run.py integrity`, `run.py sync`.
- `sync_state.py` — aggregates per-pot state files into the dashboard's
  combined state file; writes nothing when no pots exist yet, so the
  dashboard stays in its labeled replay mode.
- `README.md` — run instructions, keys instructions, and the hosting
  section (below).

## Persistence & hosting (Terry's 2026-11-21 addition)
- All pot state persists to disk continuously and resumes exactly after
  any shutdown; halt/restart clocks run on saved calendar dates.
- README recommends a small paid always-on VPS for 24/7 operation and
  states the home-PC trade-off honestly: free but part-time — while the
  machine is off, nothing trades and nothing watches.
- **Limitation stated in the README:** while the app is off it cannot act.
  A floor breach during downtime is acted on at next startup, at the
  then-available price. The floor is enforced when the app is awake; it
  is not a resting broker order.

## Bugs found and fixed during integration
1. Dashboard labeled demo data "LIVE STATE": an empty combined state file
   flipped the dashboard's mode flag while it was still showing replay
   numbers. Fixed in `dashboard/server.py` (mode only becomes "live" when
   real pots overlay) and in `sync_state.py` (no file written when no
   pots exist). Re-screenshotted: header now reads
   "REPLAY RECORD — DEMO DATA".

## Incomplete / known limitations (with reasons)
1. **Live-paper trading loop is not wired end-to-end.** The loaders,
   pots, protection, reports, and dashboard all exist and are tested, but
   the daily live-paper cycle (fetch → run engines → write state →
   report) activates only when Terry creates his own Alpaca Paper +
   Tiingo keys and fills `config.local.json`. Until then the app runs in
   replay mode and the dashboard shows the labeled replay record. This is
   by design: keys are Terry's to create, never handled by the build.
2. **Dashboard demo labels for two candidate lanes are imprecise**
   (cosmetic): the demo pot named "N-F3 Blend Sleeve" shows the standalone
   N-F3 final ($505.43), and demo holdings/trades are illustrative
   constructions around the published finals — labeled demo in the UI,
   but the lane name should read "N-F3 Paying in Stock" in a future pass.
3. **Watcher live mode is best-effort**: it lists recent EDGAR filings per
   symbol; full Form 4 ownership-XML parsing is the documented production
   path and is not yet implemented. Sample/replay mode is complete.
4. **Penny lottery pot** has its filters implemented as functions
   (sub-$5 listed, ≥$250k avg daily dollar volume, ≤5% spread,
   filings-current, limit-only, no averaging down) but has no live quote
   feed until keys exist; it has never traded, in keeping with its
   quarantine status.
5. The AI-infrastructure watch pot is track-only by instruction — no
   floor treatment has been decided for it, so it takes no floor actions.

## Safety audit (v1; superseded in part by v1.1 below)
- No real-money capability anywhere: no live broker order endpoints exist
  in the code; Alpaca access, when keys are added, is the Paper API only.
- No API keys in code or logs; `config.local.json` is git-ignored.
- The watcher imports nothing from trading/pot code (grep-verified).

---

# v1.1 — Paper→live switch (2026-11-21, Terry's direction)

Terry's call: users download the app to actually make money, so it must
have an area to switch from paper to real money — with their OWN live
keys, on their OWN machine, by their OWN deliberate act. Built exactly in
that shape; the safety design was not optional.

## What changed
- **`data/mode.py` (new)** — the single gate for real money. Mode is a
  per-installation setting in `config.local.json` (`"trading_mode"`),
  default `"paper"`. The **effective** mode is live only when the config
  says live AND the user's own Alpaca live keys are present in the same
  file; anything else resolves to PAPER with the reason surfaced
  (fail safe, never fail live). Also owns the persisted STOP ALL flag
  (`state/engine_control.json`) and the `orders_permitted()` gate.
- **`data/alpaca.py` (new)** — the only module that can place an order,
  isolated in `data/` as specified. Endpoint selected by effective mode:
  paper → `https://paper-api.alpaca.markets`, live →
  `https://api.alpaca.markets`. Standard-library only. `submit_order()`
  checks the stop flag **before any network call** and refuses while
  STOP ALL is set. There is deliberately no bulk/liquidate helper.
  Keys travel only in headers to Alpaca; never logged, never in URLs,
  never in reprs or error messages (asserted in tests).
- **`config.example.json`** — added `alpaca_paper_key_id/secret_key`,
  `alpaca_live_key_id/secret_key`, and `"trading_mode": "paper"`.
- **Dashboard** — header now permanently shows the trading mode on every
  page: pill **PAPER — SIMULATED MONEY** / **LIVE — REAL MONEY** (the
  replay/demo pill is kept alongside when showing replay data — the v1
  honest-label machinery was extended, not replaced). In live mode a
  full-width red banner ("LIVE MODE — REAL MONEY … STOP ALL") sits under
  the header on every page; when stopped, an amber banner ("ENGINE
  STOPPED — NO ORDERS WILL BE PLACED … Resume engine") replaces it.
  Footer honesty line is mode-specific. New **Trading Mode** page
  (`/mode`, new template): current mode + key presence (present/not set,
  never values), the paper-first recommendation in plain words (proven
  only in replay; designed path is a 60–90 day paper trial first; live
  expected lower, haircut 18–23%/yr vs 24–31%; own account, own risk),
  the enable form requiring the typed phrase
  `I UNDERSTAND THIS TRADES REAL MONEY`, a switch-back-to-paper control,
  and the STOP ALL section stating precisely that stopping places no
  further orders and liquidates nothing — positions stay in the user's
  broker for the user to manage. POST actions: `/mode/enable-live`,
  `/mode/disable-live`, `/mode/stop-all`, `/mode/resume` (303 redirects;
  every refusal leaves the app in PAPER). `/api/state` now also reports
  `trading_mode` and `engine_stopped`.
- **`run.py`** — new `python run.py mode` (mode, key presence, stop
  state; never values); docstring updated.
- **Engines and pots were NOT touched.** The v9 protections live in
  `pots/` and are mode-agnostic, so they apply identically in live mode
  by construction; the penny pot's listed-only/filter rules and its
  "floor is a target, not a guarantee" label are unchanged. Pot 2 remains
  absent (persistence test still asserts the seven defined pots).

## Verification (all re-run after the change)
- **Integrity gate: 11/11 PASS, to the cent** — V+M $544.47/$288.05,
  Lazy Prices $504.34/$324.12, Momentum Basket $439.45/$208.27, N-F3
  $505.43/$289.53, Switch B $549.43, SPY $313.62/$187.77. Unchanged.
- **Persistence test: PASSED** (halt 2026-02-02 → restart eligible
  2026-05-03; second-halt pot reloads as ended; no Pot 2).
- **New `data/test_trading_mode.py`: ALL PASS** — default paper; live
  requested without live keys fails safe to paper with the reason;
  wrong/partial phrase refused with config untouched; right phrase
  without keys refused; right phrase + dummy keys enables; adapter picks
  paper vs live endpoint by effective mode; STOP ALL persists on disk
  and blocks orders in both modes with **zero network calls** (spy
  transport); resume re-enables; disable returns to paper; dummy secret
  strings asserted absent from every message, status dict, and repr.
- **End-to-end over HTTP**, in a throwaway copy of the app with dummy
  keys (the real install was never given a config file): enable refused
  without keys → wrong phrase refused → correct phrase enabled LIVE →
  header pill + banner + STOP ALL visible → STOP ALL set (API reports
  `engine_stopped: true`, banner flips) → resume → switch back to paper.
  Screenshots visually inspected and saved: `dashboard/mode-paper.png`
  (paper header), `dashboard/mode-enable.png` (Trading Mode page with
  the confirmation form), `dashboard/mode-live.png` (live header +
  banner), `dashboard/mode-stopped.png` (stopped banner + alerts).
- **Real install confirmed pristine afterwards**: no `config.local.json`
  exists, `state/` holds no control file, `python run.py mode` reports
  paper / keys not set / engine running.

## Honest limitations of v1.1
- The switch, gate, adapter, and UI are built and tested with dummy keys
  and a fake transport. **No real Alpaca account (paper or live) has been
  connected yet, and no real order has ever been placed.** The end-to-end
  daily cycle still activates only when the user adds their own keys —
  v1 limitation #1 stands, now for both account types.
- STOP ALL stops this app from placing further orders. It is not a
  broker-side kill switch: it cannot cancel orders already resting at
  Alpaca, and it does not touch existing positions — by design, and the
  README and the Trading Mode page both say so in plain words.
- The downtime caveat now applies to live mode: while the app/machine is
  off it cannot act, in live mode exactly as in paper (README updated).

---

# Deep adversarial QA — two rounds (2026-11-21, Terry's order)

The full record is **QA-REPORT.md** (same directory) — book-grade:
function inventory, every break in plain language, the fix, and the
re-test, with the rounds reported separately. Summary:

- **Round 1** (4 areas): 7 Critical, 20 High, ~27 Medium, ~11 Low —
  including an unvalidated `sell()` that manufactured shares, a NaN
  price disabling the −15% floor, STOP ALL failing open on a corrupt
  control file, a symlink serving `config.local.json` (live secret)
  from the dashboard, and missing CSRF protection. All fixed; each
  fix lane added regression suites. The coordinator caught one more
  by eye in the screenshots: the live banner's STOP ALL form rendered
  a literal `{csrf_field()}` and would have 403'd from every page but
  one — fixed, with a permanent regression test.
- **Round 2** (five fresh agents, five partitions, per Terry's
  structure): every partition found Round 1 fixes incomplete
  somewhere — 3 Critical, 14 High, 22 Medium, 21 Low. Headlines: a
  hardlink (not symlink) still served the config secret; DNS
  rebinding defeated both CSRF defences (no Host allowlist); a
  duplicate `stopped` key silently un-stopped the engine; the
  config-write registry forgot revocations after 8 writes; NaN
  fundamentals and NaN floors produced plausible garbage / disabled
  protection; the integrity gate verified only the final figure and
  now verifies orders, costs and halt state too, and tests itself
  under any folder name. All fixed and re-verified.
- **Standing rule (Terry, ~21:18) applied throughout:** after ANY
  code change, the full verification ran from the top — integrity
  11/11 to the cent, persistence, trading-mode, every regression
  suite, fresh screenshots. Final run: **everything green**
  (QA-REPORT.md §9 has the table).
- **Final code state:** the app as left on 2026-11-21 after the §9
  verification is the post-testing snapshot — the book's source-code
  appendix must be re-printed from THIS state, not from any earlier
  build.
- **Honest limits:** no real Alpaca account has ever been connected
  and no real order placed; broker-side order-id de-dup is
  undetermined; live feeds untested (QA-REPORT.md §10). The install
  is left pristine for the penetration phase that follows
  (attack-surface leads in QA-REPORT.md §11).

---

# ADDENDUM — App v2: The Horizon Picker (built 2026-11-23)

Terry's final app slate (2026-11-23 ~21:06), superseding the 2026-11-21
champion-only decision: the app lets each user CHOOSE their strategy by
how long they want to hold. The champion remains the default and the
Long bucket's centerpiece. Built by a coordinator + 6 parallel module
agents, then integrated and re-verified from the top by the coordinator
(Terry's code rule: any code change → full verification).

## What the picker offers (bucket → offerings, tiers shown before selection)

| Bucket | Offering(s) | Tier | Published record |
|---|---|---|---|
| Daily | Quality-Momentum, daily form | CANDIDATE (horizon crown) | decade $847.62 · luck 20/20 · worst fall −32.1% |
| 3 Days | Quality-Momentum, daily form (borrowed) | CANDIDATE | Same daily form, under the printed note: "No system in the tested record works on a 3-day rhythm. This is the daily system — the closest tested form." No 3-day strategy was invented. |
| Weekly | Quality-Momentum, weekly form | CANDIDATE (confirmed) | decade $1,164.49 · worst fall −32.1% |
| Bi-Weekly | Quality-Momentum, biweekly form | CANDIDATE | decade $1,096.12 · fence states luck 14/20 — a pass, but a thin one |
| Monthly | Quality-Momentum, monthly form | CANDIDATE | decade $1,097.93 · fence states luck 13/20 — the thinnest pass in the record |
| Monthly | Momentum Basket | PROMOTED | $439.45 / $208.27 |
| Every 3 Months | N-F3 Paying in Stock, quarterly horizon form | CANDIDATE (invented rule — candidate ceiling, stated on the card) | decade $737.97 · luck 20/20 · worst fall −31.5% |
| Every 3 Months | Lazy Prices | PROMOTED | $504.34 / $324.12 |
| Every 6 Months | N-F3 Paying in Stock, semiannual horizon form | CANDIDATE (invented rule) | decade $848.79 · luck 17/20 · worst fall −29.3% |
| Yearly | Accruals at 2 holdings | VARIANT-CANDIDATE | decade-window $1,487.30 · worst fall −33.5% · **floor-free exactly as tested**, red warning banner on the card before selection |
| Long | Champion — Value + Momentum | PROMOTED (app default) | $544.47 / $288.05 · 17-year road $1,415.62 |

Pots stay separate $100 pots, never blended (14 pot definitions; the
no-Pot-2 assertion stands). Protections run exactly as each strategy
was tested: v9 house rules for the QM and N-F3 horizon forms (their
published chassis), floor-free for Accruals with the warning shown in
the UI — the app never silently changes a strategy's rules.

## Engine ports — integrity gate (the app's standing rule)

Every offered strategy was ported by loading its ORIGINAL backtest
script verbatim and gated against its published finals BEFORE it
appeared in the picker:
- `engines/quality_momentum.py` ← `v10-retest/quality-momentum/qm_v10.py`:
  daily/weekly/biweekly/monthly decade finals + weekly continuous,
  finals, orders AND costs to the cent.
- `engines/nf3_horizon.py` ← `v10-retest/novel-f3-paying-in-stock/sweep.py`:
  quarterly $737.97, semiannual $848.79 (finals, costs, orders, halts).
- `engines/accruals.py` ← `v12-completions/catalog-hxz-accruals/scripts/engine.py`:
  Dac@2 floor-free cell, 6/6 roads to the cent (finals, costs, max-DD,
  monthly curve cross-checked; the original publishes no trade list, so
  its gate cross-checks the full monthly curve instead of orders).
**Exclusions: NONE.** All three ports passed; no strategy is offered on
an approximation.

## CD shadow (display benchmark, not a tradable pot)

`data/cd_shadow.py` implements the pot-page section "This pot vs SPY vs
what a bank CD would have done over the same stretch." At the v2 close
the benchmark build (`backtests/cd-benchmark/`) had landed only in
part (SPEC.md, HUNT-LOG.md, cd-rates-monthly.csv — the roller's rate
input, not a value series), so the module sat in its honest absent
state: `available()` False, pot pages printing "CD comparison not yet
available," no CD numbers invented anywhere.

**CD ACTIVATION — follow-up, 2026-11-23.** The benchmark build has
since completed (`results.json`, `compute_cd.py`), and the canonical
monthly value series has been exported from that build's OWN
computation: `backtests/cd-benchmark/cd-value-series.csv` (204 points:
fresh $100 on January 4, 2010, month-end values of the frozen SPEC.md
term strategy — `cd12_value` the headline 12-month roller, `cd6_value`
the 6-month sensitivity; derived by `export_cd_series.py` running
`compute_cd.py`'s own `roller_value` verbatim; documented in that
folder's `cd-value-series.md`). No app code changed — the module
picked the series up by name pattern and ratio, exactly as designed.
Activation verified from the top, per the code rule:

- `data/test_cd_shadow.py`: **ALL PASS, 19 checks** (was 14 in the
  absent state) — the real-data section self-activated: all five
  standard windows consistent, non-decreasing, finals $108.03 /
  $106.53 / $106.53 / $108.64 / $111.40.
- **Live HTTP smoke (throwaway copy, dummy password):** the champion
  pot page now renders the full three-way section — this pot $544.47 ·
  SPY $313.62 · **Bank CD (shadow) $107.30 (+7.30%)** over the pot's
  replay window (January 2016 to December 2025). The not-available
  text is gone.
- **Master integrity gate re-run after the change: ALL PASS 24/24**,
  to the cent. **Persistence suite: PASSED.** Install left pristine
  (no config.local.json; state/ holds only README.txt).

One honest fence, recorded in full in the benchmark folder's
`cd-value-series.md`: against the benchmark's printed road finals
(fresh rollers starting on each road's own date), the in-app shadow —
the canonical January-2010 roller's growth over the window — matches
the 17-year road **to the cent ($111.40)**, sits **one cent under** on
the judging ($106.53 vs $106.54) and middle ($108.03 vs $108.04)
roads, and **26 cents over** on the 10-year road ($108.64 vs
$108.38). The differences are the roller's path dependence, not
error: a November-starting roller renews every November and locked
the 2022–23 rate rises later than the January-renewing canonical
path. The series was not adjusted to force a match. This follow-up
changed no app code (a data file in the benchmark folder plus this
report), so the FINAL CODE STATE below stands as written.

## Login (Terry's spec, 2026-11-22)

First run: a pristine install redirects every page to /setup, where the
user creates a name + password. Only a salted PBKDF2 hash
(`dashboard/auth.py`, 200,000 iterations) plus the name
(`dashboard_owner_name`) is stored in config.local.json — never the
plaintext (verified). After setup, /setup closes permanently (404) and
entry is password-only; the login page greets the stored name and never
re-asks it. All prior protections unchanged (sessions, per-session
CSRF, lockout, Host allowlist, bind/refusal rules). The penetration
phase remains STOPPED — it was not resumed by this build.

## Verification (coordinator, after the last code change, from the top)

- **Master integrity gate: ALL PASS 24/24** — the original 11/11
  reproduced to the cent, plus 13 new picker-engine checks (finals,
  orders, costs, halt state). `engines/integrity_results.json` is the
  passing record; standalone gates also pass (QM 5/5 cells,
  N-F3 horizon 2/2, Accruals 6/6).
- Persistence PASSED on the 14-pot slate (one stale assertion updated:
  `pots/test_persistence.py` hard-coded the old 7-pot count — now
  asserts the 14-pot v2 slate and the presence of every picker pot).
- Picker suite PASSED (9 buckets in Terry's order/names, tiers + fences
  on every offering, 3-Days note, floor-free flag + warning, accruals
  conditionality, no Pot 2). Dashboard: picker/login 42/42, auth 20/20,
  sessions/CSRF 12/12, banner/CSRF PASS, adversarial 58/58 + round-2
  regressions PASS. Mode gate: trading-mode ALL PASS, adversarial mode
  22/22 + round-2 PASS. Pots adversarial 19/19 + 15/15. Engines/data/
  watcher/reports adversarial suites all PASS. Keystore, redact,
  endpoint-whitelist, env-override, git-tripwire, loaders suites PASS.
  Release verify OK. CD shadow 14/14 (absent-state + fixture math).
- **Live HTTP smoke (throwaway copy, dummy password):** pristine
  install → every page 303-redirects to /setup; setup POST creates
  hash-only credentials and signs in; /setup then returns 404; /picker
  renders all 9 buckets with tier badges, the 3-Days note, the Yearly
  floor-free warning, and the champion's APP DEFAULT badge; /pot shows
  the SPY + CD benchmark section with the honest not-available text.
- Install left pristine: no config.local.json, state/ holds only
  README.txt, no real broker contact (dummy transports only, as always).

## FINAL CODE STATE — for the book's code appendix

**The book's Appendix E must be re-printed from the app code as it
stands at the close of this build (App v2, 2026-11-23).** New/changed
files vs v1.1: `picker.py` (new), `test_picker.py` (new),
`engines/quality_momentum.py`, `engines/nf3_horizon.py`,
`engines/accruals.py` + their standalone integrity tests/results
(new), `engines/integrity_test.py` + `integrity_results.json`
(extended to 24 checks), `pots/definitions.py` (14 pots),
`pots/test_persistence.py` (slate assertion), `data/cd_shadow.py` +
`data/test_cd_shadow.py` (new), `dashboard/server.py`,
`dashboard/auth.py` (one helper), `dashboard/templates/picker.html` +
`setup.html` (new), `dashboard/templates/pot.html` +
`login.html` (benchmark section, owner greeting),
`dashboard/test_picker_login.py` (new). If any later build changes the
app again, the appendix re-prints again — the appendix always matches
the shipped code.
