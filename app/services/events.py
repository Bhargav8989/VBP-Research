import logging
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Iterator
from urllib.parse import quote

import httpx
import yfinance as yf

from app.cache import cache

logger = logging.getLogger(__name__)

EVENT_CACHE_TTL_SECONDS = 12 * 3600  # 12 hours

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

DATE_FORMATS = (
    "%d-%b-%Y %H:%M:%S",
    "%d-%b-%Y %H:%M",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
)


def _parse_date(raw: Any) -> str | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text or text == "-":
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Fallback regex for embedded DD-Mon-YYYY
    match = re.search(r"(\d{1,2}-[A-Za-z]{3}-\d{4})", text)
    if match:
        try:
            return datetime.strptime(match.group(1), "%d-%b-%Y").strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


@contextmanager
def _nse_client() -> Iterator[httpx.Client]:
    with httpx.Client(
        timeout=15.0,
        follow_redirects=True,
        headers=NSE_HEADERS,
    ) as client:
        # Prime NSE session cookies
        try:
            client.get("https://www.nseindia.com/")
        except Exception as exc:
            logger.debug("NSE homepage cookie prime warning: %s", exc)
        yield client


def _fetch_nse_results(symbol: str, client: httpx.Client) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    sym_encoded = quote(symbol)

    # 1. Quarterly Financial Results API
    url = (
        f"https://www.nseindia.com/api/corporates-financial-results"
        f"?index=equities&symbol={sym_encoded}&period=Quarterly"
    )
    try:
        resp = client.get(url)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    dt = (
                        _parse_date(item.get("filingDate"))
                        or _parse_date(item.get("broadCastDate"))
                        or _parse_date(item.get("re_broadcast_timestamp"))
                    )
                    if not dt:
                        continue
                    period_end = item.get("toDate") or ""
                    label = f"Qtr Result ({period_end})" if period_end else "Quarterly Result"
                    events.append(
                        {
                            "date": dt,
                            "event_type": "RESULTS",
                            "label": label,
                            "source": "NSE Financial Results",
                        }
                    )
    except Exception as exc:
        logger.warning("NSE financial results fetch failed for %s: %s", symbol, exc)

    # 2. Corporate Announcements supplement (catches the latest quarterly results)
    ann_url = (
        f"https://www.nseindia.com/api/corporate-announcements"
        f"?index=equities&symbol={sym_encoded}"
    )
    try:
        resp = client.get(ann_url)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    desc = (item.get("desc") or "").upper()
                    text = (item.get("attchmntText") or "").upper()
                    if (
                        "FINANCIAL RESULT" in desc
                        or ("OUTCOME OF BOARD MEETING" in desc and "RESULT" in text)
                    ):
                        dt = _parse_date(item.get("an_dt")) or _parse_date(item.get("sort_date"))
                        if dt:
                            events.append(
                                {
                                    "date": dt,
                                    "event_type": "RESULTS",
                                    "label": (item.get("desc") or "Financial Result").strip(),
                                    "source": "NSE Announcements",
                                }
                            )
    except Exception as exc:
        logger.warning("NSE announcements (results) fetch failed for %s: %s", symbol, exc)

    return events


def _fetch_nse_agms(symbol: str, client: httpx.Client) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    sym_encoded = quote(symbol)

    # 1. Corporate Actions API (contains historical Annual General Meeting records)
    actions_url = (
        f"https://www.nseindia.com/api/corporates-corporateActions"
        f"?index=equities&symbol={sym_encoded}"
    )
    try:
        resp = client.get(actions_url)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    subject = (item.get("subject") or "").strip()
                    subj_upper = subject.upper()
                    if "ANNUAL GENERAL MEETING" in subj_upper or re.search(r"\bAGM\b", subj_upper):
                        dt = (
                            _parse_date(item.get("exDate"))
                            or _parse_date(item.get("bcStartDate"))
                            or _parse_date(item.get("recDate"))
                        )
                        if dt:
                            events.append(
                                {
                                    "date": dt,
                                    "event_type": "AGM",
                                    "label": subject[:80] if subject else "Annual General Meeting",
                                    "source": "NSE Corporate Actions",
                                }
                            )
    except Exception as exc:
        logger.warning("NSE corporate actions (AGM) fetch failed for %s: %s", symbol, exc)

    # 2. Corporate Announcements API (for AGM proceedings / updates)
    ann_url = (
        f"https://www.nseindia.com/api/corporate-announcements"
        f"?index=equities&symbol={sym_encoded}"
    )
    try:
        resp = client.get(ann_url)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                for item in data:
                    desc = (item.get("desc") or "").strip()
                    desc_upper = desc.upper()
                    if (
                        "ANNUAL GENERAL MEETING" in desc_upper
                        or "SHAREHOLDERS MEETING" in desc_upper
                        or re.search(r"\bAGM\b", desc_upper)
                    ):
                        # Prefer AGM proceedings / outcome dates over early notice dates
                        text_upper = (item.get("attchmntText") or "").upper()
                        if "NOTICE" in desc_upper and "PROCEEDING" not in text_upper:
                            continue
                        dt = _parse_date(item.get("an_dt")) or _parse_date(item.get("sort_date"))
                        if dt:
                            events.append(
                                {
                                    "date": dt,
                                    "event_type": "AGM",
                                    "label": desc[:80],
                                    "source": "NSE Announcements",
                                }
                            )
    except Exception as exc:
        logger.warning("NSE announcements (AGM) fetch failed for %s: %s", symbol, exc)

    return events


def _fetch_yfinance_earnings(symbol: str) -> list[dict[str, str]]:
    """Fallback earnings/results dates via Yahoo Finance."""
    events: list[dict[str, str]] = []
    ticker_sym = symbol if symbol.endswith((".NS", ".BO")) else f"{symbol}.NS"
    try:
        ticker = yf.Ticker(ticker_sym)
        df = ticker.get_earnings_dates(limit=40)
        if df is not None and not df.empty:
            for dt_idx in df.index:
                dt_str = dt_idx.tz_localize(None).strftime("%Y-%m-%d") if getattr(dt_idx, "tzinfo", None) else dt_idx.strftime("%Y-%m-%d")
                events.append(
                    {
                        "date": dt_str,
                        "event_type": "RESULTS",
                        "label": "Quarterly Earnings",
                        "source": "Yahoo Finance",
                    }
                )
    except Exception as exc:
        logger.warning("yfinance earnings dates fetch failed for %s: %s", ticker_sym, exc)
    return events


def _fetch_nse_upcoming_calendar(
    symbol: str,
    event_type: str,
    client: httpx.Client,
) -> list[dict[str, str]]:
    """Fetch announced upcoming Board Meetings (Results) & AGMs from NSE Event Calendar."""
    events: list[dict[str, str]] = []
    sym_encoded = quote(symbol)
    url = f"https://www.nseindia.com/api/event-calendar?index=equities&symbol={sym_encoded}"
    try:
        resp = client.get(url)
        if resp.status_code != 200:
            return events
        data = resp.json()
        if not isinstance(data, list):
            return events
        for item in data:
            item_sym = (item.get("symbol") or "").strip().upper()
            if item_sym and item_sym != symbol:
                continue
            purpose = (item.get("purpose") or "").strip()
            desc = (item.get("bm_desc") or "").strip()
            combined = f"{purpose} {desc}".upper()
            dt = _parse_date(item.get("date"))
            if not dt:
                continue

            if event_type == "RESULTS" and ("RESULT" in combined or "FINANCIAL" in combined):
                events.append(
                    {
                        "date": dt,
                        "event_type": "RESULTS",
                        "label": purpose[:80] if purpose else "Upcoming Financial Result",
                        "source": "NSE Event Calendar",
                    }
                )
            elif event_type == "AGM" and (
                "ANNUAL GENERAL MEETING" in combined or re.search(r"\bAGM\b", combined)
            ):
                events.append(
                    {
                        "date": dt,
                        "event_type": "AGM",
                        "label": purpose[:80] if purpose else "Upcoming AGM",
                        "source": "NSE Event Calendar",
                    }
                )
    except Exception as exc:
        logger.warning("NSE event calendar fetch failed for %s: %s", symbol, exc)
    return events


def deduplicate_events(events: list[dict[str, str]], min_gap_days: int = 10) -> list[dict[str, str]]:
    """Sort descending by date and merge duplicate announcements within min_gap_days."""
    if not events:
        return []

    sorted_events = sorted(events, key=lambda e: e["date"], reverse=True)
    deduped: list[dict[str, str]] = []
    for ev in sorted_events:
        ev_dt = datetime.strptime(ev["date"], "%Y-%m-%d")
        is_dup = False
        for existing in deduped:
            ex_dt = datetime.strptime(existing["date"], "%Y-%m-%d")
            if abs((ev_dt - ex_dt).days) <= min_gap_days:
                is_dup = True
                break
        if not is_dup:
            deduped.append(ev)
    return deduped


def fetch_corporate_events(
    symbol: str,
    event_type: str = "RESULTS",
    force_refresh: bool = False,
) -> list[dict[str, str]]:
    """
    Fetch historical Results or AGM dates for an NSE stock.
    event_type: 'RESULTS' or 'AGM'
    """
    sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    ev_type = event_type.strip().upper()
    if ev_type not in {"RESULTS", "AGM"}:
        raise ValueError(f"Unsupported event_type: {event_type}. Use RESULTS or AGM.")

    cache_key = f"events_v2:{sym}:{ev_type}"
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    collected: list[dict[str, str]] = []
    with _nse_client() as client:
        # Always check NSE Upcoming Event Calendar first
        collected.extend(_fetch_nse_upcoming_calendar(sym, ev_type, client))
        if ev_type == "RESULTS":
            collected.extend(_fetch_nse_results(sym, client))
            # Always merge yfinance earnings dates (often includes upcoming earnings date)
            collected.extend(_fetch_yfinance_earnings(sym))
            deduped = deduplicate_events(collected, min_gap_days=20)
        else:
            collected.extend(_fetch_nse_agms(sym, client))
            deduped = deduplicate_events(collected, min_gap_days=180)

    # Filter out absurdly far future dates (> 120 days ahead)
    cutoff_future = (datetime.now() + timedelta(days=120)).strftime("%Y-%m-%d")
    deduped = [e for e in deduped if e["date"] <= cutoff_future]

    if deduped:
        cache.set(cache_key, deduped, ttl_seconds=EVENT_CACHE_TTL_SECONDS)

    return deduped
