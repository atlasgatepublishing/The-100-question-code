"""Data loaders for Terry's AI stock app.

PAPER / REPLAY ONLY. This module contains NO live-broker order endpoints
and NO real-money capability of any kind. It only *reads* price/filing data.

Sources (all free, per DESIGN.md):
  * ReplayLoader  -- the project's own cached prices under backtests/
                     (v4/data/px_*.json Yahoo-chart format, and
                      v4/momentum-basket-data/<SYM>.json [{d,o,c}, ...]).
                     Works with NO API keys at all -- this is the default.
  * TiingoLoader  -- Tiingo free EOD (https://api.tiingo.com). Key read ONLY
                     from app/config.local.json. No key -> loader is inert
                     and raises a clear error only if actually called.
  * EdgarLoader   -- SEC EDGAR public JSON (company tickers / submissions).
                     No key needed; EDGAR asks for a descriptive User-Agent,
                     taken from config.local.json if present.

Keys are NEVER hardcoded and NEVER logged. config.local.json is local-only
(git-ignored style); see config.example.json.
"""
from __future__ import annotations
import json, logging, math, os, sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class DataValidationError(ValueError):
    """Cached/input price data is malformed or fails validation.

    Subclasses ValueError so existing callers that catch ValueError keep
    working, while new code can catch this precise type.
    """


def _valid_price(v) -> bool:
    """A usable price is a real, finite, strictly positive number."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(float(v)) and float(v) > 0


def _num_or_none(v):
    """Coerce to float, or None for bools / non-numbers (R2-M5).

    float(True) == 1.0, so a JSON close of `true` used to become a $1.00
    bar wherever a loader coerced BEFORE _clean_bars could validate the
    raw value. Every loader coercion now goes through here."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _valid_date_str(s) -> bool:
    """R2-M6: a bar date must be a real ISO calendar date — '2024-02-30',
    'not-a-date' and None (stringified to 'None') used to load as bars
    and corrupt engine windowing via lexicographic comparison."""
    if not isinstance(s, str):
        return False
    try:
        date.fromisoformat(s)
        return True
    except ValueError:
        return False


def _clean_bars(bars: list["Bar"], source: str) -> list["Bar"]:
    """Loader-boundary validation (QA H-1/M-3).

    Behaviour, chosen so the engines stay total on the bars that survive:
    a bar whose close (or a present open/high/low) is zero, negative, NaN
    or otherwise non-finite is DROPPED, with a logged warning naming the
    source, symbol date and bad value — it is never passed downstream,
    where it previously produced NaN / negative engine finals or a
    ZeroDivisionError. Bars are then sorted by date; duplicate dates keep
    the LAST occurrence (matching the old ``closes()`` dict semantics) and
    the de-duplication is logged, never silent.
    """
    kept: list[Bar] = []
    for b in bars:
        if not _valid_date_str(b.date):
            # R2-M6: an impossible/garbage date is a boundary failure,
            # dropped loudly like a bad close.
            log.warning("%s: dropping bar — date %r is not a real ISO calendar date",
                        source, b.date)
            continue
        if not _valid_price(b.close):
            log.warning("%s: dropping bar %s — close=%r is not a positive finite price",
                        source, b.date, b.close)
            continue
        b.close = float(b.close)
        # R2-L1: a bad open/high/low no longer destroys a good close —
        # the offending field is nulled (and logged) and the bar is
        # kept; engines trade on closes. R2-L2: adj_close must be a
        # positive finite price and volume non-negative, else nulled
        # with a log line (previously silent / unchecked).
        for field_name in ("open", "high", "low", "adj_close"):
            v = getattr(b, field_name)
            if v is not None and not _valid_price(v):
                log.warning("%s: bar %s — %s=%r is not a positive finite price; field dropped, bar kept",
                            source, b.date, field_name, v)
                setattr(b, field_name, None)
            elif v is not None:
                setattr(b, field_name, float(v))
        v = b.volume
        if v is not None:
            fv = _num_or_none(v)
            if fv is None or fv < 0:
                log.warning("%s: bar %s — volume=%r is not a non-negative number; field dropped, bar kept",
                            source, b.date, v)
                b.volume = None
            else:
                b.volume = fv
        kept.append(b)
    kept.sort(key=lambda b: b.date)
    deduped: list[Bar] = []
    for b in kept:
        if deduped and deduped[-1].date == b.date:
            log.warning("%s: duplicate date %s — keeping last bar", source, b.date)
            deduped[-1] = b
        else:
            deduped.append(b)
    return deduped

APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = APP_DIR.parent
BACKTESTS_DIR = PROJECT_DIR / "backtests"
CONFIG_PATH = APP_DIR / "config.local.json"

@dataclass
class Bar:
    date: str; open: float|None; high: float|None; low: float|None
    close: float; adj_close: float|None; volume: float|None
    def to_dict(self): return self.__dict__.copy()

def load_config(path: Path|None=None) -> dict:
    """Return local config dict; {} when absent. Never logs values.

    QA M-14: a PRESENT but corrupt config is no longer swallowed
    silently — a warning naming the file and the parse error is printed
    to stderr (values are never printed), so "why won't Tiingo load" is
    debuggable. An absent config still returns {} quietly.
    """
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        cfg = {}
        _tiingo_env = os.environ.get("TIINGO_API_KEY")
        if _tiingo_env:
            cfg["tiingo_api_key"] = _tiingo_env
        return cfg
    try:
        cfg = json.loads(p.read_text())
        if isinstance(cfg, dict):
            _tiingo_env = os.environ.get("TIINGO_API_KEY")
            if _tiingo_env:
                cfg["tiingo_api_key"] = _tiingo_env
        return cfg
    except Exception as e:
        print(f"WARNING: could not parse config {p} ({type(e).__name__}: {e}); "
              "falling back to no-config (replay) behaviour.", file=sys.stderr)
        log.warning("could not parse config %s: %s", p, e)
        _tiingo_env = os.environ.get("TIINGO_API_KEY")
        return {"tiingo_api_key": _tiingo_env} if _tiingo_env else {}

def _cfg_key(cfg: dict, *names: str) -> str:
    for n in names:
        v = cfg.get(n)
        if isinstance(v, str) and v.strip(): return v.strip()
    return ""

class ReplayLoader:
    """Reads cached backtest prices. No keys, no network."""
    def __init__(self, backtests_dir: Path|None=None):
        self.root = Path(backtests_dir) if backtests_dir else BACKTESTS_DIR
        self.px_dir = self.root/"v4"/"data"
        self.basket_dir = self.root/"v4"/"momentum-basket-data"
        self.honest_dir = self.root/"v4"/"momentum-basket-honest-data"
    def available_symbols(self) -> list[str]:
        syms=set()
        if self.px_dir.exists():
            syms |= {p.stem[3:] for p in self.px_dir.glob("px_*.json")}
        for d in (self.basket_dir, self.honest_dir):
            if d.exists(): syms |= {p.stem for p in d.glob("*.json")}
        return sorted(syms)
    def load(self, symbol: str) -> list[Bar]:
        symbol=symbol.upper()
        px=self.px_dir/f"px_{symbol}.json"
        if px.exists(): return self._load_chart(px)
        for d in (self.basket_dir, self.honest_dir):
            f=d/f"{symbol}.json"
            if f.exists(): return self._load_simple(f)
        # value-momentum-honest-data also uses px_*.json
        alt=self.root/"v4"/"value-momentum-honest-data"/f"px_{symbol}.json"
        if alt.exists(): return self._load_chart(alt)
        raise FileNotFoundError(f"No cached replay data for {symbol} under {self.root}")
    @staticmethod
    def _load_chart(path: Path) -> list[Bar]:
        # QA M-2: malformed files raise a named error identifying the file,
        # never a bare KeyError/TypeError with no context.
        try:
            raw=json.loads(path.read_text())
        except Exception as e:
            raise DataValidationError(f"{path}: not valid JSON ({type(e).__name__}: {e})") from e
        try:
            res=raw["chart"]["result"][0]
            ts=res.get("timestamp") or []; q=res["indicators"]["quote"][0]
            adj=(res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or [None]*len(ts)
            closes=q["close"]
        except (KeyError, TypeError, IndexError, AttributeError) as e:
            raise DataValidationError(f"{path}: malformed Yahoo-chart data (missing {e})") from e
        out=[]
        for i,t in enumerate(ts):
            try:
                c=closes[i]
            except IndexError as e:
                raise DataValidationError(f"{path}: close series shorter than timestamps") from e
            if c is None: continue
            close_f=_num_or_none(c)  # R2-M5: bool closes never become $1.00
            if close_f is None:
                log.warning("%s: dropping bar %s — close=%r is not numeric", path, t, c)
                continue
            def _at(series, i=i):
                try: return series[i]
                except (IndexError, TypeError, KeyError): return None
            try:
                bar_date=datetime.fromtimestamp(t, tz=timezone.utc).date().isoformat()
            except (TypeError, ValueError, OverflowError, OSError) as e:
                # R2-L3: a string/absurd timestamp used to crash with a
                # bare TypeError naming no file.
                raise DataValidationError(f"{path}: timestamp {t!r} is not a valid epoch value ({e})") from e
            out.append(Bar(date=bar_date,
                open=_at(q.get("open") or []), high=_at(q.get("high") or []),
                low=_at(q.get("low") or []), close=close_f,
                adj_close=_at(adj), volume=_at(q.get("volume") or [])))
        return _clean_bars(out, str(path))
    @staticmethod
    def _load_simple(path: Path) -> list[Bar]:
        try:
            raw=json.loads(path.read_text())
        except Exception as e:
            raise DataValidationError(f"{path}: not valid JSON ({type(e).__name__}: {e})") from e
        if not isinstance(raw, list):
            raise DataValidationError(f"{path}: expected a JSON list of bars, got {type(raw).__name__}")
        out=[]
        for i,r in enumerate(raw):
            if not isinstance(r, dict) or "d" not in r or "c" not in r:
                raise DataValidationError(f"{path}: row {i} is missing required 'd'/'c' keys: {str(r)[:80]!r}")
            close_f=_num_or_none(r["c"])  # R2-M5: bool closes never become $1.00
            if close_f is None:
                log.warning("%s: dropping row %s — close=%r is not numeric", path, r["d"], r["c"])
                continue
            out.append(Bar(date=str(r["d"]), open=r.get("o"), high=r.get("h"), low=r.get("l"),
                           close=close_f, adj_close=r.get("adj") or r.get("c"), volume=r.get("v")))
        return _clean_bars(out, str(path))
    def closes(self, symbol: str) -> dict[str,float]:
        return {b.date: b.close for b in self.load(symbol)}
    def spy_shadow(self, start_balance: float, start_date: str, end_date: str|None=None) -> dict:
        """Shadow SPY: same dollars/dates, buy-and-hold SPY (DESIGN.md benchmark)."""
        bars=[b for b in self.load("SPY") if b.date>=start_date and (end_date is None or b.date<=end_date)]
        if not bars: raise ValueError("No SPY bars in range")
        # QA M-4: explicit guard (loader cleaning already drops bad bars,
        # so this is defence in depth, not an accidental falsy check).
        if not _valid_price(bars[0].close):
            raise DataValidationError(f"SPY start price on {bars[0].date} is not positive/finite: {bars[0].close!r}")
        if not start_balance:
            raise ValueError("spy_shadow: start_balance must be non-zero")
        shares=start_balance/bars[0].close
        return {"symbol":"SPY","start_date":bars[0].date,"end_date":bars[-1].date,
                "start_balance":start_balance,"shares":shares,
                "final_value":round(shares*bars[-1].close,2),
                "return_pct":round((shares*bars[-1].close/start_balance-1)*100,2)}

class TiingoLoader:
    """Tiingo free EOD. Paper/replay data only -- no order capability."""
    BASE="https://api.tiingo.com/tiingo/daily"
    def __init__(self, config: dict|None=None):
        self._key=_cfg_key(config if config is not None else load_config(), "tiingo_api_key","TIINGO_API_KEY")
    @property
    def available(self) -> bool: return bool(self._key)
    def load(self, symbol: str, start_date: str="2010-01-01", end_date: str|None=None) -> list[Bar]:
        if not self._key: raise RuntimeError("No Tiingo key in app/config.local.json -- replay mode only. Add a free key there to use live-paper EOD.")
        import requests  # local import; replay mode needs no network stack use
        params={"startDate":start_date,"format":"json","token":self._key}
        if end_date: params["endDate"]=end_date
        r=requests.get(f"{self.BASE}/{symbol.upper()}/prices", params=params, timeout=30); r.raise_for_status()
        bars=[]
        for row in r.json():
            close_f=_num_or_none(row.get("close"))  # R2-M5: no $1.00 bool bars
            raw_date=row.get("date")
            if close_f is None or not isinstance(raw_date, str):
                log.warning("tiingo %s: dropping row %s — close/date not usable", symbol, raw_date); continue
            bars.append(Bar(date=raw_date[:10], open=row.get("open"), high=row.get("high"), low=row.get("low"),
                        close=close_f, adj_close=row.get("adjClose"), volume=row.get("volume")))
        return _clean_bars(bars, f"tiingo:{symbol.upper()}")

class EdgarLoader:
    """SEC EDGAR public data. Free, no key; descriptive UA per SEC fair-access rules."""
    def __init__(self, config: dict|None=None):
        cfg=config if config is not None else load_config()
        ua=_cfg_key(cfg,"edgar_user_agent","EDGAR_USER_AGENT")
        self.headers={"User-Agent": ua or "AtlasGate StockApp research (local personal use)", "Accept":"application/json"}
    def company_tickers(self) -> dict:
        import requests
        r=requests.get("https://www.sec.gov/files/company_tickers.json", headers=self.headers, timeout=30); r.raise_for_status(); return r.json()
    def submissions(self, cik: str|int) -> dict:
        import requests
        r=requests.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", headers=self.headers, timeout=30); r.raise_for_status(); return r.json()
