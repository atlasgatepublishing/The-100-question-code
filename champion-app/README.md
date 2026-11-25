# The Champion App: source code

Published by Atlas Gate Publishing, Springfield, Illinois, as the companion application to the book *The $100 Question: We Tested Every Trading Strategy We Could Find*.

## What this is

The book tested many trading systems and kept one champion: value plus momentum. Each quarter it ranks a pond of 30 large companies as they stood in November 2016, buys the top five at equal weight, and holds them under a plain 15 percent floor. This folder holds the source code of the app that runs that champion, and only that champion. Everything else the book tested stays in the book.

The rules are the book's adopted rules, unchanged:

* Five equal positions; no name is more than 20 percent of the pot at selection.
* A plain 15 percent floor measured from each episode's starting balance. No profit ladder.
* On a first floor hit, the position set is sold, the pot sits in cash for 90 calendar days, and it gets one restart at the next regular selection date under a fresh 15 percent floor measured from the restart balance.
* On a second floor hit, the run ends permanently.
* If a pond company is acquired or delisted mid run, its position is sold at the last available price and the pot runs with four names until the next selection date. A company that merely changes its ticker carries its position under the new ticker.
* SPY buy and hold stands beside the pot at all times, on the same dollars and the same dates, as the baseline.

The published replay record, $100 start, the book's cost convention (0.10 percent of trade value per side plus $0.01 per sell order):

| Engine | 2019 to 2026 | 2023 to 2026 |
|---|---|---|
| Champion, value plus momentum | $544.47 | $288.05 |
| SPY buy and hold, same dollars and dates | $313.62 | $187.77 |

Run `python run.py integrity` and the app checks its own copy of the champion against those four figures, to the cent, before you are asked to trust anything else.

## What you get: source code, and nothing else

This folder is source code. There is no installer, no executable, and no one click version, and there will not be one posted here. You download the code, read it if you wish, and run it yourself, with your own Python, on your own computer, with your own broker account. Atlas Gate Publishing never holds your funds, never sees your credentials, and runs no server that your data passes through. Your keys are stored only in `config.local.json` on your own machine, encrypted at rest on Windows with DPAPI.

The app is free under the Atlas Gate non commercial licence. The full text ships in this folder as `LICENSE`: free for personal use, and nobody may sell this code or this app, repackage it, or bundle it into a paid product or service.

## What you need

* Python 3.10 or newer. The app is written in plain Python and uses the standard library, with one exception: the optional Tiingo price path in `data/loaders.py` imports the third party `requests` package, so install that too if you use a Tiingo key.
* For the backtest and the integrity check: no account of any kind. The replay reads the program's cached data when it is present; on a machine without the caches, the champion original fetches the price series it needs from Yahoo Finance in its own download path and caches them, so a first replay on a new machine needs network access and takes longer. The daily cycle does not use the caches at all; it fetches current prices and EDGAR fundamentals at run time.
* For paper trading: a free Alpaca paper account and your own paper key pair from Alpaca. Paper trading is simulated by Alpaca against live market data; no real money moves. A free Tiingo key, added as `tiingo_api_key` in `config.local.json`, can supply end of day prices.

## Honest status of this release

Read this section before you run anything.

* **Paper trading only.** In this release the app trades on paper. Live trading is locked in the code itself, at the broker adapter as well as in the daily cycle and the dashboard, and the live path is not included. A hand edited configuration cannot unlock it.
* **Tested, with the counts stated.** Before posting, this code passed the project's full test programme: the integrity gate, 4 of 4 published figures reproduced to the cent; the daily cycle suite, 107 of 107 checks; the dashboard authentication suite, 20 passed and 0 failed; the release manifest suite, 5 of 5; and the frozen trading mode and persistence suites, all passing. It then went through a separate adversarial pass of 52 attacks aimed at its caps, its paper trial gate, its kill switch, its audit log, and its order path. Twelve attacks found real defects. All twelve were fixed, and the attacks were re-run against the fixed code; the project's fix report records each one.
* **Not yet verified against a real paper account.** Every broker behaviour above was tested against fake transports and dummy keys. This code has **not** yet been verified end to end against a live Alpaca paper account: order acceptance, fill reporting, position read back, and the cancel endpoints have not yet been exercised against the real service. This folder will be updated when that check is done, and this paragraph will say so when it is.
* **No promise of profit.** Nothing here claims that anyone will make money. See the disclaimer at the end of this file, which is carried in full.

## How to start

All commands run from inside this folder.

1. Copy `config.example.json` to `config.local.json`.
2. Verify your copy against the release manifest: `python run.py verify`
3. Check the record: `python run.py integrity`
4. Add your own keys: `python run.py setup-keys` (your free Alpaca **paper** key pair; the setup flow stores them in your local config only).
5. Set your pot size as `champion_pot_size` in `config.local.json`. The default is $100. The app ships with a hard ceiling of **$10,000 per pot** that no setting inside the app can raise; the ceiling can only change in a new release. Caps are checked twice: when the order list is built, and again on each order at submission.
6. Run the daily cycle: `python run.py cycle`. On a quarterly selection date the cycle ranks the pond, builds the orders, and stops at an **order preview**: symbol, side, amount, latest price, estimated resulting weight, and the cap check result. Nothing is submitted without your explicit confirmation of that preview: `python run.py cycle --confirm <id>`, using the preview id the first run shows you.
7. Watch it: `python run.py` opens the dashboard at http://localhost:8765

Version 1 runs on your home computer with a manual daily run. Run it once a day. The app can only act while it is running: a floor breach that happens while the machine is off is acted on at the next run, at the then current price. The floor is enforced when the app is awake; it is not a resting broker order.

## The kill switch

STOP ALL (the dashboard's Trading Mode page, the panic page, or `python run.py kill-switch`) halts all order placement and cancels every resting order at the broker, and reports the result order by order. It does **not** sell anything you hold; positions stay in your account for you to manage. The stop persists on disk across restarts, and deleting or corrupting the stop state fails safe: the app treats damaged state as a stop, not as permission.

## The audit log

Everything the app does is written to an append only audit log at `state/audit_log.jsonl` in this folder: cycle runs, rankings, previews, orders, fills, reconciliation results, cap refusals, pond events, floor halts, mode changes, and kill switch events. Entries are hash chained, so an edited, deleted, or reordered entry breaks the chain and is detected. The paper trial gate reads this log: live enabling in a future release requires a completed paper trial of 90 days including at least one completed quarterly selection cycle, with no unresolved reconciliation mismatch, proven from this log. Practice runs with no broker keys are labelled simulated and never count as trial evidence.

## Honesty labels that ship with the app

* Replay is not a promise. The champion is proven in replay only; the judging years were looked at many times, and free data carries survivorship flattery: delisted names are under represented in every free stack.
* Live results are expected to be **lower** than the replay record. Plan on the program's haircut: roughly 18 to 23 percent a year if the edge holds at all, against 24 to 31 percent in replay. The edge may not hold.
* Execution prices live will differ from replay prices in the ordinary ways: the backtest selects and trades on its recorded price basis, and real fills arrive at real prices. The paper trial measures that difference; it is not assumed away.
* The forward paper trial is the only judge that has not seen the answers. That is why it gates everything else.

## Disclaimer

This app and the book are educational material, not investment advice, and Atlas Gate Publishing is not your financial adviser. The program is provided as is, with no warranty of any kind and no promise that it works, that it is free of bugs, or that it will make money. Its strategy is proven only in historical replay, not proven live. Backtested performance does not predict future results. Anyone who uses it, in any mode, trades their own account at their own risk and can lose money. See `LICENSE` for the terms.
