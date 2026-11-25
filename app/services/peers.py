import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx
import yfinance as yf
from bs4 import BeautifulSoup

from app.cache import cache
from app.services.analyzer import analyze_events
from app.services.events import fetch_corporate_events
from app.services.prices import fetch_price_history

logger = logging.getLogger(__name__)

PEERS_CACHE_TTL = 7 * 24 * 3600  # 7 days

# Fast sector buckets for major NSE equities (resolves in 0ms)
SECTOR_GROUPS: dict[str, list[str]] = {
    "IT Services": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT", "COFORGE", "MPHASIS"],
    "Private Banks": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK", "FEDERALBNK", "IDFCFIRSTB"],
    "PSU Banks": ["SBIN", "BANKBARODA", "PNB", "CANBK", "UNIONBANK", "INDIANB"],
    "NBFC & Finance": ["BAJFINANCE", "BAJAJFINSV", "JIOFIN", "CHOLAFIN", "SHRIRAMFIN", "MUTHOOTFIN", "PFC", "RECLTD"],
    "Oil, Gas & Energy": ["RELIANCE", "ONGC", "IOC", "BPCL", "HINDPETRO", "GAIL", "IGL", "MGL"],
    "Automobiles": ["TATAMOTORS", "M&M", "MARUTI", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "TVSMOTOR", "ASHOKLEY"],
    "Pharma & Healthcare": ["SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "LUPIN", "AUROPHARMA", "TORNTPHARM", "APOLLOHOSP"],
    "FMCG & Consumer": ["ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "TATACONSUM", "DABUR", "MARICO", "GODREJCP", "COLPAL"],
    "Metals & Mining": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "COALINDIA", "NMDC", "JINDALSTEL", "SAIL"],
    "Cement": ["ULTRACEMCO", "AMBUJACEM", "SHREECEM", "ACC", "DALBHARAT", "RAMCOCEM", "JKCEMENT"],
    "Power & Utilities": ["NTPC", "POWERGRID", "TATAPOWER", "ADANIPOWER", "JSWENERGY", "NHPC", "TORNTPOWER"],
    "Infra & Capital Goods": ["LT", "SIEMENS", "ABB", "CGPOWER", "BHEL", "CUMMINSIND", "THERMAX"],
    "Defence & Aerospace": ["HAL", "BEL", "MAZDOCK", "COCHINSHIP", "BDL", "DATAPATTNS"],
    "Telecom": ["BHARTIARTL", "IDEA", "INDUSTOWER", "TATACOMM"],
    "Retail & Paints": ["TRENT", "DMART", "TITAN", "ASIANPAINT", "BERGEPTS", "PIDILITIND", "KALYANKJIL"],
    "Ports & Logistics": ["ADANIPORTS", "CONCOR", "DELHIVERY", "INDIGO", "BLUEDART"],
    "Chemicals": ["SRF", "PIIND", "UPL", "DEEPAKNTR", "NAVINFLUOR", "TATACHEM", "AARTIIND"],
}


def get_auto_peers(symbol: str, max_peers: int = 5) -> dict[str, Any]:
    """
    Automatically find up to `max_peers` (default 5) NSE peer symbols in the same sector.
    Uses curated sector groups first, then falls back to Screener/Yahoo industry matching.
    """
    sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    cache_key = f"auto_peers_v1:{sym}:{max_peers}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    # 1. Fast curated sector match
    for sector_name, members in SECTOR_GROUPS.items():
        if sym in members:
            peers = [m for m in members if m != sym][:max_peers]
            res = {"sector": sector_name, "peers": peers}
            cache.set(cache_key, res, ttl_seconds=PEERS_CACHE_TTL)
            return res

    # 2. Screener sector/peers fallback
    sector_label = "Sector Peers"
    peers: list[str] = []
    try:
        with httpx.Client(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        ) as client:
            r = client.get(f"https://www.screener.in/company/{sym}/consolidated/")
            if r.status_code != 200:
                r = client.get(f"https://www.screener.in/company/{sym}/")
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "lxml")
                sec_links = soup.select("#peers a[href*='/market/']")
                if sec_links:
                    sector_label = sec_links[-1].get_text(strip=True) or sector_label
                for a in soup.select("#peers table a[href*='/company/']"):
                    href = a.get("href") or ""
                    m = re.search(r"/company/([A-Z0-9\-&]+)/", href, flags=re.I)
                    if m:
                        p_sym = m.group(1).upper()
                        if p_sym != sym and p_sym not in peers and not p_sym.isdigit():
                            peers.append(p_sym)
                    if len(peers) >= max_peers:
                        break
    except Exception as exc:
        logger.debug("Screener peer lookup warning for %s: %s", sym, exc)

    # 3. Yahoo Finance sector keyword fallback if still empty
    if not peers:
        try:
            info = yf.Ticker(f"{sym}.NS").info or {}
            ind = (info.get("industry") or info.get("sector") or "").lower()
            if ind:
                sector_label = info.get("industry") or info.get("sector") or sector_label
                for bucket_name, members in SECTOR_GROUPS.items():
                    if any(w in bucket_name.lower() for w in ind.split()[:2]):
                        peers = [m for m in members if m != sym][:max_peers]
                        break
        except Exception:
            pass

    res = {"sector": sector_label, "peers": peers[:max_peers]}
    if peers:
        cache.set(cache_key, res, ttl_seconds=PEERS_CACHE_TTL)
    return res


def _analyze_single_peer(
    peer_sym: str,
    event_type: str,
    before: int,
    after: int,
    limit: int,
) -> dict[str, Any] | None:
    try:
        events = fetch_corporate_events(peer_sym, event_type=event_type)
        if not events:
            return None
        df, _ = fetch_price_history(peer_sym, period="5y")
        if df.empty:
            return None
        res = analyze_events(
            price_df=df,
            events=events,
            before_days=before,
            after_days=after,
            day_mode="trading",
            normalize_to="start",
            benchmark_df=None,
            max_events=limit,
        )
        s = res.get("summary") or {}
        if not s.get("events_analyzed"):
            return None
        return {
            "symbol": peer_sym,
            "events_analyzed": s.get("events_analyzed"),
            "avg_pre_return_pct": s.get("avg_pre_return_pct"),
            "avg_event_day_return_pct": s.get("avg_event_day_return_pct"),
            "avg_post_return_pct": s.get("avg_post_return_pct"),
            "avg_total_return_pct": s.get("avg_total_return_pct"),
            "total_win_rate_pct": s.get("total_win_rate_pct"),
        }
    except Exception as exc:
        logger.debug("Peer event analysis failed for %s: %s", peer_sym, exc)
        return None


def compare_sector_peers(
    symbol: str,
    event_type: str = "RESULTS",
    before: int = 20,
    after: int = 10,
    limit: int = 8,
    max_peers: int = 5,
) -> dict[str, Any]:
    """Compare up to 5 auto-selected sector peers on the same Result/AGM window."""
    if event_type not in ("RESULTS", "AGM"):
        return {"sector": "", "peers": []}

    info = get_auto_peers(symbol, max_peers=max_peers)
    peer_syms = info.get("peers") or []
    if not peer_syms:
        return {"sector": info.get("sector", ""), "peers": []}

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_analyze_single_peer, p, event_type, before, after, limit): p
            for p in peer_syms[:max_peers]
        }
        for fut in as_completed(futures):
            row = fut.result()
            if row:
                rows.append(row)

    # Sort by Avg Total Return descending
    rows.sort(key=lambda r: r.get("avg_total_return_pct") or -999, reverse=True)
    return {"sector": info.get("sector", "Sector Peers"), "peers": rows}
