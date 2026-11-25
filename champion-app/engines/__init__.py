"""Ported strategy engines for Terry's AI stock app.

Each module exposes the common interface documented in
``engines.common``: ``run(prices, fundamentals, start_cash,
protection) -> result dict``.

Engines: vm (champion), lazy_prices, momentum_basket, nf3, switch_b,
plus spy (shadow SPY buy-and-hold benchmark). Replay mode only —
every engine reproduces its published backtest record from the
original scripts' cached data; see integrity_test.py.
"""
from . import common  # noqa: F401
