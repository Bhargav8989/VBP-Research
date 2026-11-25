import logging
from typing import Optional

import pandas as pd
import yfinance as yf

from app.cache import cache

logger = logging.getLogger(__name__)

PRICE_CACHE_TTL_SECONDS = 6 * 3600  # 6 hours
NIFTY_TICKER = "^NSEI"


def _normalize_yf_df(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize yfinance DataFrame into clean date-indexed OHLCV."""
    if df is None or df.empty:
        return pd.DataFrame()

    # Handle MultiIndex columns returned by newer yfinance versions
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]

    required = ["Open", "High", "Low", "Close", "Volume"]
    available = [c for c in required if c in df.columns]
    if "Close" not in available:
        return pd.DataFrame()

    out = df[available].copy()
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.dropna(subset=["Close"])
    out.index.name = "Date"
    return out


def _serialize_df(df: pd.DataFrame) -> list[dict]:
    records = []
    for dt, row in df.iterrows():
        records.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "open": round(float(row.get("Open", row["Close"])), 4),
                "high": round(float(row.get("High", row["Close"])), 4),
                "low": round(float(row.get("Low", row["Close"])), 4),
                "close": round(float(row["Close"]), 4),
                "volume": int(row.get("Volume", 0) or 0),
            }
        )
    return records


def _deserialize_df(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["Date"] = pd.to_datetime(df["date"])
    df = df.set_index("Date").drop(columns=["date"])
    df = df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )
    return df.sort_index()


def fetch_price_history(
    symbol: str,
    period: str = "10y",
    exchange: str = "NS",
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, str]:
    """
    Fetch daily OHLCV history for an Indian stock via yfinance.
    Returns (DataFrame, resolved_ticker).
    """
    clean_symbol = symbol.strip().upper()
    if clean_symbol.startswith("^") or clean_symbol.endswith((".NS", ".BO")):
        candidates = [clean_symbol]
    else:
        secondary = "BO" if exchange == "NS" else "NS"
        candidates = [f"{clean_symbol}.{exchange}", f"{clean_symbol}.{secondary}"]

    cache_key = f"prices_v1:{candidates[0]}:{period}"
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached and cached.get("records"):
            return _deserialize_df(cached["records"]), cached["ticker"]

    for ticker in candidates:
        try:
            raw = yf.download(
                ticker,
                period=period,
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            df = _normalize_yf_df(raw)
            if not df.empty:
                cache.set(
                    cache_key,
                    {"ticker": ticker, "records": _serialize_df(df)},
                    ttl_seconds=PRICE_CACHE_TTL_SECONDS,
                )
                return df, ticker
        except Exception as exc:
            logger.warning("Failed fetching prices for %s: %s", ticker, exc)

    return pd.DataFrame(), candidates[0]


def fetch_benchmark_history(period: str = "10y", force_refresh: bool = False) -> Optional[pd.DataFrame]:
    """Fetch Nifty 50 (^NSEI) daily history for relative alpha calculations."""
    df, _ = fetch_price_history(NIFTY_TICKER, period=period, force_refresh=force_refresh)
    return df if not df.empty else None
