"""Data layer: free price/filing loaders, trading mode, broker adapter.

loaders.py only READS market data (replay / Tiingo / EDGAR). mode.py owns
the paper/live switch and the STOP ALL flag (fail-safe: paper). alpaca.py
is the only module that can place an order, and only through the mode
gate. Keys come from config.local.json only -- never code, never logs.
"""
from .loaders import ReplayLoader, TiingoLoader, EdgarLoader, load_config, Bar
from . import mode
from .alpaca import AlpacaClient, AlpacaError
__all__ = ["ReplayLoader", "TiingoLoader", "EdgarLoader", "load_config", "Bar",
           "mode", "AlpacaClient", "AlpacaError"]
