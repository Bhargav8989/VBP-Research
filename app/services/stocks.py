import csv
import io
import logging
from typing import Any

import httpx

from app.cache import cache

logger = logging.getLogger(__name__)

NSE_EQUITY_CSV_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
CACHE_KEY_STOCKS = "nse_equity_list_v1"
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days

# Lightweight fallback list of popular NSE stocks so search always works even offline.
FALLBACK_STOCKS: list[dict[str, str]] = [
    {"symbol": "RELIANCE", "name": "Reliance Industries Limited", "isin": "INE002A01018", "series": "EQ"},
    {"symbol": "TCS", "name": "Tata Consultancy Services Limited", "isin": "INE467B01029", "series": "EQ"},
    {"symbol": "HDFCBANK", "name": "HDFC Bank Limited", "isin": "INE040A01034", "series": "EQ"},
    {"symbol": "ICICIBANK", "name": "ICICI Bank Limited", "isin": "INE090A01021", "series": "EQ"},
    {"symbol": "INFY", "name": "Infosys Limited", "isin": "INE009A01021", "series": "EQ"},
    {"symbol": "BHARTIARTL", "name": "Bharti Airtel Limited", "isin": "INE397D01024", "series": "EQ"},
    {"symbol": "SBIN", "name": "State Bank of India", "isin": "INE062A01020", "series": "EQ"},
    {"symbol": "ITC", "name": "ITC Limited", "isin": "INE154A01025", "series": "EQ"},
    {"symbol": "LT", "name": "Larsen & Toubro Limited", "isin": "INE018A01030", "series": "EQ"},
    {"symbol": "HINDUNILVR", "name": "Hindustan Unilever Limited", "isin": "INE030A01027", "series": "EQ"},
    {"symbol": "BAJFINANCE", "name": "Bajaj Finance Limited", "isin": "INE296A01024", "series": "EQ"},
    {"symbol": "KOTAKBANK", "name": "Kotak Mahindra Bank Limited", "isin": "INE237A01028", "series": "EQ"},
    {"symbol": "AXISBANK", "name": "Axis Bank Limited", "isin": "INE238A01034", "series": "EQ"},
    {"symbol": "MARUTI", "name": "Maruti Suzuki India Limited", "isin": "INE585B01010", "series": "EQ"},
    {"symbol": "SUNPHARMA", "name": "Sun Pharmaceutical Industries Limited", "isin": "INE044A01036", "series": "EQ"},
    {"symbol": "TATAMOTORS", "name": "Tata Motors Limited", "isin": "INE155A01022", "series": "EQ"},
    {"symbol": "NTPC", "name": "NTPC Limited", "isin": "INE733E01010", "series": "EQ"},
    {"symbol": "TITAN", "name": "Titan Company Limited", "isin": "INE280A01028", "series": "EQ"},
    {"symbol": "M&M", "name": "Mahindra & Mahindra Limited", "isin": "INE101A01026", "series": "EQ"},
    {"symbol": "ULTRACEMCO", "name": "UltraTech Cement Limited", "isin": "INE481G01011", "series": "EQ"},
    {"symbol": "HCLTECH", "name": "HCL Technologies Limited", "isin": "INE860A01027", "series": "EQ"},
    {"symbol": "WIPRO", "name": "Wipro Limited", "isin": "INE075A01022", "series": "EQ"},
    {"symbol": "ASIANPAINT", "name": "Asian Paints Limited", "isin": "INE021A01026", "series": "EQ"},
    {"symbol": "ADANIENT", "name": "Adani Enterprises Limited", "isin": "INE423A01024", "series": "EQ"},
    {"symbol": "ADANIPORTS", "name": "Adani Ports and Special Economic Zone Limited", "isin": "INE742F01042", "series": "EQ"},
    {"symbol": "POWERGRID", "name": "Power Grid Corporation of India Limited", "isin": "INE752E01010", "series": "EQ"},
    {"symbol": "ONGC", "name": "Oil & Natural Gas Corporation Limited", "isin": "INE213A01029", "series": "EQ"},
    {"symbol": "COALINDIA", "name": "Coal India Limited", "isin": "INE522F01014", "series": "EQ"},
    {"symbol": "JSWSTEEL", "name": "JSW Steel Limited", "isin": "INE019A01038", "series": "EQ"},
    {"symbol": "TATASTEEL", "name": "Tata Steel Limited", "isin": "INE081A01020", "series": "EQ"},
    {"symbol": "BAJAJ-AUTO", "name": "Bajaj Auto Limited", "isin": "INE917I01010", "series": "EQ"},
    {"symbol": "NESTLEIND", "name": "Nestle India Limited", "isin": "INE239A01024", "series": "EQ"},
    {"symbol": "TECHM", "name": "Tech Mahindra Limited", "isin": "INE669C01036", "series": "EQ"},
    {"symbol": "DRREDDY", "name": "Dr. Reddy's Laboratories Limited", "isin": "INE089A01023", "series": "EQ"},
    {"symbol": "CIPLA", "name": "Cipla Limited", "isin": "INE059A01026", "series": "EQ"},
    {"symbol": "ZOMATO", "name": "Zomato Limited", "isin": "INE758T01015", "series": "EQ"},
    {"symbol": "TRENT", "name": "Trent Limited", "isin": "INE849A01020", "series": "EQ"},
    {"symbol": "BEL", "name": "Bharat Electronics Limited", "isin": "INE263A01024", "series": "EQ"},
    {"symbol": "HAL", "name": "Hindustan Aeronautics Limited", "isin": "INE066F01020", "series": "EQ"},
    {"symbol": "DMART", "name": "Avenue Supermarts Limited", "isin": "INE192R01011", "series": "EQ"},
]

_in_memory_stocks: list[dict[str, str]] | None = None


def _download_nse_equity_list() -> list[dict[str, str]]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/csv,*/*",
    }
    with httpx.Client(timeout=15.0, follow_redirects=True, headers=headers) as client:
        resp = client.get(NSE_EQUITY_CSV_URL)
        resp.raise_for_status()
        text = resp.text

    reader = csv.DictReader(io.StringIO(text))
    stocks: list[dict[str, str]] = []
    for row in reader:
        symbol = (row.get("SYMBOL") or "").strip().upper()
        name = (row.get("NAME OF COMPANY") or "").strip()
        series = (row.get(" SERIES") or row.get("SERIES") or "EQ").strip().upper()
        isin = (row.get(" ISIN NUMBER") or row.get("ISIN NUMBER") or "").strip()
        if symbol and name:
            stocks.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "isin": isin,
                    "series": series,
                }
            )
    return stocks


def get_all_stocks(force_refresh: bool = False) -> list[dict[str, str]]:
    """Return cached NSE equity list, fetching from NSE archives if needed."""
    global _in_memory_stocks
    if _in_memory_stocks is not None and not force_refresh:
        return _in_memory_stocks

    if not force_refresh:
        cached = cache.get(CACHE_KEY_STOCKS)
        if cached:
            _in_memory_stocks = cached
            return cached

    try:
        stocks = _download_nse_equity_list()
        if len(stocks) > 100:
            cache.set(CACHE_KEY_STOCKS, stocks, ttl_seconds=CACHE_TTL_SECONDS)
            _in_memory_stocks = stocks
            logger.info("Loaded %d NSE equities from official archive.", len(stocks))
            return stocks
    except Exception as exc:
        logger.warning("Failed to download NSE equity list, using fallback: %s", exc)

    _in_memory_stocks = FALLBACK_STOCKS
    return FALLBACK_STOCKS


def search_stocks(query: str, limit: int = 15) -> list[dict[str, Any]]:
    """Fast ranked search across NSE symbols and company names."""
    q = (query or "").strip().upper()
    stocks = get_all_stocks()
    if not q:
        return stocks[:limit]

    exact: list[dict[str, str]] = []
    prefix_symbol: list[dict[str, str]] = []
    prefix_name: list[dict[str, str]] = []
    substring: list[dict[str, str]] = []

    for item in stocks:
        sym = item["symbol"]
        name_upper = item["name"].upper()
        if sym == q:
            exact.append(item)
        elif sym.startswith(q):
            prefix_symbol.append(item)
        elif name_upper.startswith(q):
            prefix_name.append(item)
        elif q in sym or q in name_upper:
            substring.append(item)

    results = exact + prefix_symbol + prefix_name + substring
    return results[:limit]


def get_stock_info(symbol: str) -> dict[str, str]:
    """Lookup metadata for a single NSE symbol."""
    sym = symbol.strip().upper()
    for item in get_all_stocks():
        if item["symbol"] == sym:
            return item
    return {"symbol": sym, "name": sym, "isin": "", "series": "EQ"}
