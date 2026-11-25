import logging
import math
import re
from contextlib import contextmanager
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Iterator, Optional

from urllib.parse import quote

import httpx
import yfinance as yf
from bs4 import BeautifulSoup

from app.cache import cache

logger = logging.getLogger(__name__)

IPO_LIST_CACHE_KEY = "all_ipo_list_v3"
IPO_LIST_TTL_SECONDS = 1800  # 30 minutes
IPO_DETAIL_TTL_SECONDS = 900  # 15 minutes
PEER_CACHE_TTL_SECONDS = 6 * 3600  # 6 hours

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/market-data/all-upcoming-issues-ipo",
}

DATE_FORMATS = (
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d %b %Y",
)


def _safe_float(val: Any) -> Optional[float]:
    if val is None or val == "" or val == "-":
        return None
    if isinstance(val, (int, float)):
        if math.isnan(val) or math.isinf(val):
            return None
        return float(val)
    cleaned = re.sub(r"[^0-9.\-]", "", str(val))
    if not cleaned or cleaned in {"-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _safe_round(val: Optional[float], digits: int = 2) -> Optional[float]:
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return None
    return round(float(val), digits)


def _parse_date(raw: Any) -> Optional[str]:
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
    return None


def _parse_price_band(raw: Any) -> tuple[Optional[float], Optional[float]]:
    if not raw:
        return None, None
    nums = re.findall(r"\d+(?:\.\d+)?", str(raw).replace(",", ""))
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    if len(nums) == 1:
        v = float(nums[0])
        return v, v
    return None, None


def _detect_segment(item: dict[str, Any]) -> str:
    raw = " ".join(
        str(item.get(k) or "")
        for k in ("series", "category", "subType", "issueType", "securityType")
    ).upper()
    if "SME" in raw or "SM" == (item.get("series") or "").strip().upper():
        return "SME"
    return "MAINBOARD"


@contextmanager
def _nse_client() -> Iterator[httpx.Client]:
    with httpx.Client(timeout=15.0, follow_redirects=True, headers=NSE_HEADERS) as client:
        try:
            client.get("https://www.nseindia.com/")
        except Exception as exc:
            logger.debug("NSE IPO cookie prime warning: %s", exc)
        yield client


def _compute_ipo_status(
    open_dt: Optional[str],
    close_dt: Optional[str],
    listing_dt: Optional[str],
    fallback_status: str = "UPCOMING",
) -> str:
    """Compute exact IPO status from open, close, and listing dates against today."""
    today = datetime.now().strftime("%Y-%m-%d")
    if listing_dt and today >= listing_dt:
        return "LISTED"
    if open_dt and today < open_dt:
        return "UPCOMING"
    if open_dt and close_dt and open_dt <= today <= close_dt:
        return "OPEN"
    if close_dt and today > close_dt:
        if listing_dt and today < listing_dt:
            return "ALLOTMENT"
        # If no listing_dt is known, treat within 10 days after close as ALLOTMENT, older as LISTED
        try:
            days_since_close = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(close_dt, "%Y-%m-%d")).days
            return "ALLOTMENT" if days_since_close <= 10 else "LISTED"
        except ValueError:
            return "ALLOTMENT"
    return fallback_status


def _estimate_allotment_date(close_dt: Optional[str], listing_dt: Optional[str]) -> Optional[str]:
    """In India's T+3 IPO cycle, allotment is typically 1 business day after close (or T-2 before listing)."""
    base_dt_str = close_dt
    if not base_dt_str:
        return None
    try:
        dt = datetime.strptime(base_dt_str, "%Y-%m-%d") + timedelta(days=1)
        while dt.weekday() >= 5:  # skip Sat/Sun
            dt += timedelta(days=1)
        cand = dt.strftime("%Y-%m-%d")
        if listing_dt and cand >= listing_dt:
            return None
        return cand
    except ValueError:
        return None


def _normalize_nse_ipo(item: dict[str, Any], default_status: str) -> Optional[dict[str, Any]]:
    symbol = (item.get("symbol") or "").strip().upper()
    name = (
        item.get("companyName")
        or item.get("company")
        or item.get("company_name")
        or symbol
    ).strip()
    if not name and not symbol:
        return None

    p_min, p_max = _parse_price_band(
        item.get("issuePrice")
        or item.get("priceRange")
        or item.get("priceBand")
        or item.get("issue_price")
    )
    if p_min is None and item.get("priceRange"):
        p_min, p_max = _parse_price_band(item.get("priceRange"))

    open_dt = _parse_date(
        item.get("issueStartDate") or item.get("ipoStartDate") or item.get("openDate")
    )
    close_dt = _parse_date(
        item.get("issueEndDate") or item.get("ipoEndDate") or item.get("closeDate")
    )
    listing_dt = _parse_date(item.get("listingDate"))
    sub_total = _safe_float(item.get("noOfTime") or item.get("subscription"))
    issue_size_shares = _safe_float(item.get("issueSize"))
    issue_size_cr = None
    if issue_size_shares is not None:
        if issue_size_shares > 100000 and p_max:
            issue_size_cr = _safe_round((issue_size_shares * p_max) / 1e7, 2)
        else:
            issue_size_cr = _safe_round(issue_size_shares, 2)

    lot_size = _safe_float(item.get("minBidQuantity") or item.get("lotSize"))
    status = _compute_ipo_status(open_dt, close_dt, listing_dt, fallback_status=default_status)

    return {
        "symbol": symbol or re.sub(r"[^A-Z0-9]", "", name.upper())[:12],
        "company_name": name,
        "segment": _detect_segment(item),
        "exchange": "NSE",
        "status": status,
        "open_date": open_dt,
        "close_date": close_dt,
        "allotment_date": _estimate_allotment_date(close_dt, listing_dt),
        "listing_date": listing_dt,
        "price_min": p_min,
        "price_max": p_max,
        "lot_size": int(lot_size) if lot_size else None,
        "issue_size_cr": issue_size_cr,
        "fresh_issue_pct": None,
        "subscription_total": _safe_round(sub_total, 2),
        "chittorgarh_url": None,
        "source": "NSE",
    }


def _fetch_chittorgarh_all_ipos() -> list[dict[str, Any]]:
    """Fetch all Indian IPOs (NSE + BSE, Mainboard + SME) for the current FY from Chittorgarh."""
    now = datetime.now()
    y, m = now.year, now.month
    fy = f"{y}-{str(y + 1)[-2:]}" if m >= 4 else f"{y - 1}-{str(y)[-2:]}"
    url = f"https://webnodejs.chittorgarh.com/cloud/report/data-read/82/1/{m}/{y}/{fy}/0/all/0"
    out: list[dict[str, Any]] = []
    try:
        with httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        ) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return out
            rows = (resp.json() or {}).get("reportTableData") or []
            for item in rows[:120]:
                comp_html = item.get("Company") or ""
                soup_a = BeautifulSoup(comp_html, "lxml").select_one("a[href]")
                ch_url = soup_a.get("href") if soup_a else None
                name = soup_a.get_text(" ", strip=True) if soup_a else (item.get("~IPO") or "").strip()
                if not name:
                    continue

                cat_raw = (item.get("Issue Category") or "").upper()
                listing_at = (item.get("Listing at") or "").upper()
                segment = "SME" if ("SME" in cat_raw or "SME" in listing_at) else "MAINBOARD"

                has_nse = "NSE" in listing_at
                has_bse = "BSE" in listing_at
                if has_nse and has_bse:
                    exchange = "NSE/BSE"
                elif has_bse:
                    exchange = "BSE"
                elif has_nse:
                    exchange = "NSE"
                else:
                    exchange = "BSE/NSE"

                open_dt = (item.get("~Issue_Open_Date") or "")[:10] or _parse_date(item.get("Opening Date"))
                close_dt = (item.get("~IssueCloseDate") or "")[:10] or _parse_date(item.get("Closing Date"))
                listing_dt = (item.get("~ListingDate") or "")[:10] or _parse_date(item.get("Listing Date"))
                if listing_dt and listing_dt.startswith("1970"):
                    listing_dt = None

                p_min, p_max = _parse_price_band(item.get("Issue Price (Rs.)"))
                issue_cr = _safe_float(item.get("Total Issue Amount (Incl.Firm reservations) (Rs.cr.)"))
                if issue_cr == 0.0:
                    issue_cr = _safe_float(item.get("Issue Amount (Rs.cr.)"))
                if issue_cr == 0.0:
                    issue_cr = None
                fresh_pct = _safe_float(item.get("Fresh Capital as % of Issue Amount"))

                nse_sym = (item.get("~nse_symbol") or "").strip().upper()
                bse_code = str(item.get("~bse_script_code") or "").strip()
                sym = nse_sym or bse_code or re.sub(r"[^A-Z0-9]", "", name.upper())[:12]

                status = _compute_ipo_status(open_dt, close_dt, listing_dt, fallback_status="UPCOMING")
                out.append(
                    {
                        "symbol": sym,
                        "nse_symbol": nse_sym,
                        "bse_code": bse_code,
                        "company_name": name,
                        "segment": segment,
                        "exchange": exchange,
                        "status": status,
                        "open_date": open_dt or None,
                        "close_date": close_dt or None,
                        "allotment_date": _estimate_allotment_date(close_dt, listing_dt),
                        "listing_date": listing_dt or None,
                        "price_min": p_min,
                        "price_max": p_max,
                        "lot_size": None,
                        "issue_size_cr": _safe_round(issue_cr, 2) if issue_cr else None,
                        "fresh_issue_pct": _safe_round(fresh_pct, 1) if fresh_pct is not None else None,
                        "subscription_total": None,
                        "chittorgarh_url": ch_url,
                        "source": "Chittorgarh",
                    }
                )
    except Exception as exc:
        logger.warning("Chittorgarh all-IPO fetch failed: %s", exc)
    return out


def fetch_ipo_list(
    segment: str = "ALL",
    status: str = "ALL",
    exchange: str = "ALL",
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """
    Fetch Open, Allotment, Upcoming, and Listed IPOs across BOTH NSE & BSE
    (Mainboard & SME), with accurate date-based statuses.
    """
    all_ipos: Optional[list[dict[str, Any]]] = None
    if not force_refresh:
        all_ipos = cache.get(IPO_LIST_CACHE_KEY)

    if all_ipos is None:
        nse_rows: list[dict[str, Any]] = []
        endpoints = [
            ("https://www.nseindia.com/api/ipo-current-issue", "OPEN"),
            ("https://www.nseindia.com/api/all-upcoming-issues?category=ipo", "UPCOMING"),
            ("https://www.nseindia.com/api/public-past-issues", "LISTED"),
            ("https://www.nseindia.com/api/ipo-past-issues", "LISTED"),
        ]
        try:
            with _nse_client() as client:
                for url, st in endpoints:
                    try:
                        resp = client.get(url)
                        if resp.status_code != 200:
                            continue
                        data = resp.json()
                        rows = data.get("data", []) if isinstance(data, dict) else data
                        if not isinstance(rows, list):
                            continue
                        for item in rows[:40]:
                            norm = _normalize_nse_ipo(item, st)
                            if norm:
                                nse_rows.append(norm)
                    except Exception as exc:
                        logger.warning("NSE IPO endpoint %s failed: %s", url, exc)
        except Exception as exc:
            logger.warning("NSE IPO client error: %s", exc)

        ch_rows = _fetch_chittorgarh_all_ipos()

        # Merge NSE + Chittorgarh (deduplicate by symbol or first 2 name tokens)
        merged: list[dict[str, Any]] = []
        by_token_key: dict[str, int] = {}
        by_sym: dict[str, int] = {}

        def _name_key(cname: str) -> str:
            toks = _clean_company_tokens(cname)
            return "_".join(toks[:2]) if toks else cname.lower()[:12]

        for row in ch_rows:
            nk = _name_key(row["company_name"])
            if nk in by_token_key:
                continue
            idx = len(merged)
            merged.append(row)
            by_token_key[nk] = idx
            if row.get("nse_symbol"):
                by_sym[row["nse_symbol"]] = idx

        for n_row in nse_rows:
            sym = n_row["symbol"]
            nk = _name_key(n_row["company_name"])
            match_idx = by_sym.get(sym) if sym in by_sym else by_token_key.get(nk)
            if match_idx is not None:
                existing = merged[match_idx]
                # Enrich Chittorgarh row with NSE symbol, lot size, live subscription
                existing["symbol"] = sym
                existing["nse_symbol"] = sym
                if n_row.get("lot_size") and not existing.get("lot_size"):
                    existing["lot_size"] = n_row["lot_size"]
                if n_row.get("subscription_total") is not None:
                    existing["subscription_total"] = n_row["subscription_total"]
                if "NSE" not in (existing.get("exchange") or ""):
                    existing["exchange"] = "NSE/BSE" if "BSE" in (existing.get("exchange") or "") else "NSE"
                if n_row.get("listing_date") and not existing.get("listing_date"):
                    existing["listing_date"] = n_row["listing_date"]
                existing["status"] = _compute_ipo_status(
                    existing.get("open_date"),
                    existing.get("close_date"),
                    existing.get("listing_date"),
                    fallback_status=existing["status"],
                )
            else:
                idx = len(merged)
                merged.append(n_row)
                by_token_key[nk] = idx
                by_sym[sym] = idx

        if merged:
            order = {"OPEN": 0, "ALLOTMENT": 1, "UPCOMING": 2, "LISTED": 3}
            merged.sort(key=lambda x: x.get("open_date") or "", reverse=True)
            merged.sort(key=lambda x: order.get(x["status"], 9))
            all_ipos = merged[:100]
            cache.set(IPO_LIST_CACHE_KEY, all_ipos, ttl_seconds=IPO_LIST_TTL_SECONDS)
        else:
            all_ipos = []

    seg = segment.strip().upper()
    st_filter = status.strip().upper()
    ex_filter = exchange.strip().upper()

    filtered = all_ipos
    if seg in {"MAINBOARD", "SME"}:
        filtered = [i for i in filtered if i["segment"] == seg]
    if st_filter in {"OPEN", "ALLOTMENT", "UPCOMING", "LISTED"}:
        filtered = [i for i in filtered if i["status"] == st_filter]
    if ex_filter in {"NSE", "BSE"}:
        filtered = [i for i in filtered if ex_filter in (i.get("exchange") or "").upper()]
    return filtered


def fetch_ipo_detail(
    symbol: str,
    company_name: str = "",
    chittorgarh_url: str = "",
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Fetch live NSE IPO detail (/api/ipo-detail?symbol=...) including:
    - Live QIB / NII / Retail / Total subscription (bidDetails)
    - Bid Lot, Price Range, Issue Size, Fresh vs OFS hint (issueInfo)
    - Plus Yahoo Finance 3-year financials if the stock is already listed.
    """
    sym = symbol.strip().upper()
    cache_key = f"nse_ipo_detail_v2:{sym}"
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    detail: dict[str, Any] = {
        "symbol": sym,
        "lot_size": None,
        "price_min": None,
        "price_max": None,
        "issue_size_cr": None,
        "fresh_issue_pct": None,
        "sub_qib": None,
        "sub_nii": None,
        "sub_retail": None,
        "sub_total": None,
    }

    try:
        with _nse_client() as client:
            payload: dict[str, Any] = {}
            for url in (
                f"https://www.nseindia.com/api/ipo-detail?symbol={sym}&series=SME",
                f"https://www.nseindia.com/api/ipo-detail?symbol={sym}",
            ):
                resp = client.get(url)
                if resp.status_code == 200:
                    candidate = resp.json() or {}
                    data_list = (candidate.get("issueInfo") or {}).get("dataList") or []
                    if len(data_list) > 2:
                        payload = candidate
                        break
                    if not payload and candidate.get("bidDetails"):
                        payload = candidate

            if payload:

                # 1. Parse issueInfo dataList first (needed for lot size & net public shares)
                issue_size_text = ""
                for item in (payload.get("issueInfo") or {}).get("dataList") or []:
                    title = (item.get("title") or "").strip().lower()
                    val = str(item.get("value") or "").strip()
                    if not title or not val:
                        continue
                    if "price range" in title:
                        p_min, p_max = _parse_price_band(val)
                        if p_min is not None:
                            detail["price_min"] = p_min
                        if p_max is not None:
                            detail["price_max"] = p_max
                    elif "lot size" in title or "bid lot" in title or "minimum order quantity" in title:
                        lot = _safe_float(val.split("Equity")[0].split("equity")[0])
                        if lot and not detail["lot_size"]:
                            detail["lot_size"] = int(lot)
                    elif "issue size" in title:
                        issue_size_text = val

                total_issue_shares: Optional[float] = None
                net_public_shares: Optional[float] = None

                # Infer Fresh vs OFS %, issue size in Cr, and net public shares
                if issue_size_text:
                    txt_up = issue_size_text.upper()
                    has_ofs = "OFFER FOR SALE" in txt_up or "OFS" in txt_up
                    has_fresh = "FRESH ISSUE" in txt_up
                    if has_ofs and not has_fresh:
                        detail["fresh_issue_pct"] = 0.0
                    elif has_fresh and not has_ofs:
                        detail["fresh_issue_pct"] = 100.0

                    sh_match = re.search(r"(\d[\d,]+)\s+EQUITY\s+SHARES", txt_up)
                    if sh_match:
                        total_issue_shares = _safe_float(sh_match.group(1))

                    cr_match = re.search(r"(\d[\d,]*\.?\d*)\s*(?:CRORE|CR\.?)\b", txt_up)
                    if cr_match:
                        detail["issue_size_cr"] = _safe_float(cr_match.group(1))
                    elif total_issue_shares and detail["price_max"]:
                        detail["issue_size_cr"] = _safe_round((total_issue_shares * detail["price_max"]) / 1e7, 2)

                    if total_issue_shares:
                        mm_match = re.search(r"MARKET\s+MAKER[^0-9]*(\d[\d,]+)\s+EQUITY\s+SHARES", txt_up)
                        anc_match = re.search(r"ANCHOR[^0-9]*(\d[\d,]+)\s+EQUITY\s+SHARES", txt_up)
                        mm_shares = _safe_float(mm_match.group(1)) if mm_match else 0.0
                        anc_shares = _safe_float(anc_match.group(1)) if anc_match else 0.0
                        net_public_shares = max(1.0, total_issue_shares - (mm_shares or 0.0) - (anc_shares or 0.0))

                # 2. Parse live subscription (bidDetails), with shares-bid fallback for SME IPOs
                total_shares_bid: Optional[float] = None
                for row in payload.get("bidDetails") or []:
                    cat = (row.get("category") or "").upper()
                    sr = str(row.get("srNo") or "").strip()
                    times = _safe_float(row.get("noOfTime"))
                    offered = _safe_float(row.get("noOfSharesOffered"))
                    bid = _safe_float(row.get("noOfsharesBid") or row.get("noOfshareBid"))

                    # If NSE reports noOfTime=0 but offered > 0 & bid > 0, compute ratio
                    if (times is None or times == 0.0) and offered and offered > 0 and bid and bid > 0:
                        times = bid / offered
                    # If offered is 0 while bid > 0 (common in SME), don't record misleading 0.00x
                    if times == 0.0 and bid and bid > 0 and (not offered or offered == 0.0):
                        times = None

                    if sr == "1" or ("QUALIFIED INSTITUTIONAL" in cat and "1(" not in sr):
                        if times is not None:
                            detail["sub_qib"] = _safe_round(times, 2)
                    elif sr == "2" or (cat.startswith("NON INSTITUTIONAL") and "." not in sr):
                        if times is not None:
                            detail["sub_nii"] = _safe_round(times, 2)
                    elif sr == "3" or ("RETAIL" in cat and "(" not in sr and "." not in sr):
                        if times is not None:
                            detail["sub_retail"] = _safe_round(times, 2)
                    elif "TOTAL" in cat:
                        if bid and bid > 0:
                            total_shares_bid = bid
                        if times is not None:
                            detail["sub_total"] = _safe_round(times, 2)

                # Fallback for SME IPOs where NSE omits noOfTime in bidDetails Total
                if (detail["sub_total"] is None or detail["sub_total"] == 0.0) and total_shares_bid and net_public_shares:
                    detail["sub_total"] = _safe_round(total_shares_bid / net_public_shares, 2)

                cache.set(cache_key, detail, ttl_seconds=IPO_DETAIL_TTL_SECONDS)
    except Exception as exc:
        logger.warning("NSE ipo-detail fetch failed for %s: %s", sym, exc)

    # 1. Primary RHP / Financial Source: Chittorgarh (Mainboard & SME RHP financials + Post-IPO EPS/MCap)
    ch_data = fetch_chittorgarh_ipo_fundamentals(
        symbol=sym,
        company_name=company_name,
        chittorgarh_url=chittorgarh_url,
        force_refresh=force_refresh,
    )
    if ch_data.get("found"):
        for k in ("price_max", "lot_size", "issue_size_cr", "fresh_issue_pct"):
            if detail.get(k) is None and ch_data.get(k) is not None:
                detail[k] = ch_data[k]
        detail["fundamentals"] = ch_data
    else:
        # 2. Silent backup: Yahoo Finance (if already listed) -> Screener
        yf_data = fetch_listed_ipo_fundamentals(sym)
        if not yf_data.get("found"):
            scr_data = fetch_screener_ipo_fundamentals(
                symbol=sym,
                company_name=company_name,
                price_max=detail.get("price_max"),
                force_refresh=force_refresh,
            )
            if scr_data.get("found"):
                yf_data = scr_data
        detail["fundamentals"] = yf_data

    # 3. Official SEBI Prospectus / RHP document link
    detail["sebi_prospectus_url"] = fetch_sebi_prospectus_url(company_name or sym, force_refresh=force_refresh)
    return detail


def _clean_company_tokens(name: str) -> list[str]:
    cleaned = re.sub(
        r"\b(LIMITED|LTD\.?|PRIVATE|PVT\.?|INDIA|HOLDINGS|IPO|PROSPECTUS|CORP\.?|CORPORATION)\b",
        " ",
        name or "",
        flags=re.I,
    )
    return [t.lower() for t in re.findall(r"[a-zA-Z0-9]+", cleaned) if len(t) >= 2]


def fetch_sebi_prospectus_url(company_name: str, force_refresh: bool = False) -> Optional[str]:
    """Match IPO company name against SEBI's official Public Issues Prospectus filings list."""
    tokens = _clean_company_tokens(company_name)
    if not tokens:
        return None

    cache_key = "sebi_prospectus_list_v1"
    filings: Optional[list[dict[str, str]]] = None if force_refresh else cache.get(cache_key)

    if filings is None:
        filings = []
        url = "https://www.sebi.gov.in/sebiweb/home/HomeAction.do?doListing=yes&sid=3&ssid=15&smid=12"
        try:
            with httpx.Client(
                timeout=12.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            ) as client:
                r = client.get(url)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "lxml")
                    for tr in soup.select("table tr"):
                        a = tr.select_one("a[href]")
                        if a and a.get("href"):
                            filings.append(
                                {
                                    "title": a.get_text(" ", strip=True).lower(),
                                    "url": a.get("href"),
                                }
                            )
            if filings:
                cache.set(cache_key, filings, ttl_seconds=PEER_CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.warning("SEBI filings list fetch failed: %s", exc)
            return None

    key_tokens = tokens[:2]
    for f in filings:
        if all(tok in f["title"] for tok in key_tokens):
            return f["url"]
    return None


def fetch_chittorgarh_ipo_fundamentals(
    symbol: str,
    company_name: str = "",
    chittorgarh_url: str = "",
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Primary RHP financials fetcher from Chittorgarh (Mainboard & SME):
    - 3-Year Revenue & PAT (annual Mar columns)
    - Net Worth & Total Borrowing
    - Post-IPO EPS & Post-IPO Market Cap
    - Fresh Issue vs OFS %, Lot Size, Issue Size
    """
    sym = symbol.strip().upper()
    cache_key = f"chittorgarh_ipo_v1:{sym}"
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    out: dict[str, Any] = {"symbol": sym, "found": False}
    tokens = _clean_company_tokens(company_name or sym)
    if not tokens:
        return out

    try:
        with httpx.Client(
            timeout=12.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        ) as client:
            # Use direct chittorgarh_url if provided, else match in cached list
            target_url = chittorgarh_url.strip() if chittorgarh_url else None
            if not target_url:
                list_cache_key = "chittorgarh_ipo_list_v1"
                ipo_links: Optional[list[dict[str, str]]] = None if force_refresh else cache.get(list_cache_key)
                if ipo_links is None:
                    ipo_links = []
                    lr = client.get("https://www.chittorgarh.com/ipo/ipo_list.asp")
                    if lr.status_code == 200:
                        lsoup = BeautifulSoup(lr.text, "lxml")
                        for a in lsoup.select("a[href]"):
                            href = a.get("href") or ""
                            if "/ipo/" in href and "-ipo/" in href:
                                full_url = href if href.startswith("http") else f"https://www.chittorgarh.com{href}"
                                ipo_links.append({"title": a.get_text(" ", strip=True).lower(), "url": full_url})
                        if ipo_links:
                            cache.set(list_cache_key, ipo_links, ttl_seconds=PEER_CACHE_TTL_SECONDS)

                match_tokens = tokens[:2] if len(tokens) >= 2 else tokens[:1]
                for item in ipo_links:
                    if all(tok in item["title"] for tok in match_tokens):
                        target_url = item["url"]
                        break

            if not target_url:
                return out

            pr = client.get(target_url)
            if pr.status_code != 200:
                return out

            soup = BeautifulSoup(pr.text, "lxml")
            revs: list[Optional[float]] = [None, None, None]
            pats: list[Optional[float]] = [None, None, None]
            net_worth_cr: Optional[float] = None
            total_debt_cr: Optional[float] = None
            eps: Optional[float] = None
            mcap_cr: Optional[float] = None
            fresh_pct: Optional[float] = None
            total_issue_cr: Optional[float] = None
            fresh_issue_cr: Optional[float] = None
            lot_size: Optional[int] = None
            price_max: Optional[float] = None

            for tbl in soup.select("table"):
                rows = [[td.get_text(" ", strip=True) for td in tr.select("th, td")] for tr in tbl.select("tr")]
                if not rows:
                    continue
                head_txt = " ".join(rows[0]).lower()

                # A. 3-Year Financials Table ("Period Ended")
                if "period ended" in head_txt:
                    headers = rows[0]
                    # Prefer annual "31 Mar" columns; otherwise take non-header columns
                    mar_indices = [i for i, h in enumerate(headers) if i > 0 and "mar" in h.lower()]
                    if len(mar_indices) >= 2:
                        # Chittorgarh orders newest -> oldest; reverse to oldest -> newest
                        sel_idx = list(reversed(mar_indices[:3]))
                    else:
                        sel_idx = list(reversed(range(1, min(len(headers), 4))))

                    for rw in rows[1:]:
                        if not rw:
                            continue
                        lbl = rw[0].strip().lower()
                        if "total income" in lbl or lbl == "revenue":
                            vals = [_safe_float(rw[i]) if i < len(rw) else None for i in sel_idx]
                            while len(vals) < 3:
                                vals.insert(0, None)
                            revs = vals[-3:]
                        elif "profit after tax" in lbl or lbl == "pat":
                            vals = [_safe_float(rw[i]) if i < len(rw) else None for i in sel_idx]
                            while len(vals) < 3:
                                vals.insert(0, None)
                            pats = vals[-3:]
                        elif "net worth" in lbl:
                            # Take most recent column (index 1, or first annual col)
                            for c_idx in range(1, len(rw)):
                                v = _safe_float(rw[c_idx])
                                if v is not None:
                                    net_worth_cr = v
                                    break
                        elif "borrowing" in lbl or "total debt" in lbl:
                            for c_idx in range(1, len(rw)):
                                v = _safe_float(rw[c_idx])
                                if v is not None:
                                    total_debt_cr = v
                                    break

                # B. Valuation Metric Table (Pre IPO / Post IPO EPS & Market Cap)
                elif "valuation metric" in head_txt or ("pre ipo" in head_txt and "post ipo" in head_txt):
                    for rw in rows[1:]:
                        if not rw:
                            continue
                        lbl = rw[0].strip().lower()
                        # Prefer Post-IPO column (index 2) if present, else Pre-IPO (index 1)
                        val_post = _safe_float(rw[2]) if len(rw) > 2 else None
                        val_pre = _safe_float(rw[1]) if len(rw) > 1 else None
                        if "eps" in lbl:
                            eps = val_post if val_post is not None else val_pre
                        elif "market cap" in lbl:
                            mcap_cr = val_post if val_post is not None else val_pre

                # C. Issue Details / Fresh vs OFS
                else:
                    for rw in rows:
                        if len(rw) < 2:
                            continue
                        lbl = rw[0].strip().lower()
                        val_txt = rw[1].strip()
                        if lbl == "sale type":
                            vt_up = val_txt.upper()
                            if "FRESH" in vt_up and "OFS" not in vt_up and "OFFER FOR SALE" not in vt_up:
                                fresh_pct = 100.0
                            elif ("OFS" in vt_up or "OFFER FOR SALE" in vt_up) and "FRESH" not in vt_up:
                                fresh_pct = 0.0
                        elif "total issue size" in lbl:
                            m = re.search(r"₹\s*([\d,\.]+)\s*Cr", val_txt, flags=re.I)
                            if m:
                                total_issue_cr = _safe_float(m.group(1))
                        elif lbl.startswith("fresh issue"):
                            m = re.search(r"₹\s*([\d,\.]+)\s*Cr", val_txt, flags=re.I)
                            if m:
                                fresh_issue_cr = _safe_float(m.group(1))
                        elif lbl == "lot size" and not lot_size:
                            lv = _safe_float(val_txt.split("Share")[0])
                            if lv:
                                lot_size = int(lv)
                        elif lbl == "price band" and not price_max:
                            _, pmx = _parse_price_band(val_txt)
                            if pmx:
                                price_max = pmx

            if fresh_pct is None and total_issue_cr and total_issue_cr > 0 and fresh_issue_cr is not None:
                fresh_pct = _safe_round(min(100.0, (fresh_issue_cr / total_issue_cr) * 100.0), 1)

            if any(v is not None for v in revs + pats) or eps is not None or mcap_cr is not None:
                out = {
                    "symbol": sym,
                    "found": True,
                    "source": "Chittorgarh RHP",
                    "chittorgarh_url": target_url,
                    "price_max": price_max,
                    "lot_size": lot_size,
                    "issue_size_cr": total_issue_cr,
                    "fresh_issue_pct": fresh_pct,
                    "market_cap_cr": mcap_cr,
                    "eps": eps,
                    "net_worth_cr": net_worth_cr,
                    "total_debt_cr": total_debt_cr,
                    "rev_fy1": revs[0],
                    "rev_fy2": revs[1],
                    "rev_fy3": revs[2],
                    "pat_fy1": pats[0],
                    "pat_fy2": pats[1],
                    "pat_fy3": pats[2],
                }
                cache.set(cache_key, out, ttl_seconds=PEER_CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Chittorgarh IPO fundamentals fetch failed for %s: %s", sym, exc)
    return out


def _extract_screener_table_row(sec: Any, row_prefix: str) -> list[Optional[float]]:
    """Extract last 3 annual numeric columns (excluding TTM) from a Screener table section."""
    if not sec:
        return [None, None, None]
    headers: list[str] = []
    header_tr = sec.select_one("thead tr")
    if header_tr:
        headers = [th.get_text(strip=True) for th in header_tr.select("th")]

    for tr in sec.select("tbody tr"):
        cols = [td.get_text(strip=True) for td in tr.select("td")]
        if not cols:
            continue
        label = cols[0].replace("+", "").strip().lower()
        if label.startswith(row_prefix.lower()):
            vals: list[Optional[float]] = []
            for idx in range(1, len(cols)):
                h = headers[idx].upper() if idx < len(headers) else ""
                if "TTM" in h:
                    continue
                vals.append(_safe_float(cols[idx]))
            last3 = vals[-3:]
            while len(last3) < 3:
                last3.insert(0, None)
            return last3
    return [None, None, None]


def fetch_screener_ipo_fundamentals(
    symbol: str,
    company_name: str = "",
    price_max: Optional[float] = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """
    Fetch 3-year P&L, Balance Sheet (Net Worth & Debt), Market Cap, and EPS
    from Screener.in for upcoming / newly closed Indian IPOs.
    """
    sym = symbol.strip().upper()
    cache_key = f"screener_ipo_fund_v1:{sym}"
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    search_terms = []
    if company_name:
        cleaned_name = re.sub(r"\b(LIMITED|LTD\.?|PRIVATE|PVT\.?)\b", "", company_name, flags=re.I).strip()
        words = cleaned_name.split()
        if len(words) >= 2:
            search_terms.append(" ".join(words[:3]))
        elif words:
            search_terms.append(words[0])
    search_terms.append(sym)

    out: dict[str, Any] = {"symbol": sym, "found": False}
    try:
        with httpx.Client(
            timeout=12.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        ) as client:
            comp_url = None
            for q in search_terms:
                if not q:
                    continue
                sr = client.get(f"https://www.screener.in/api/company/search/?q={quote(q)}")
                if sr.status_code == 200:
                    hits = sr.json() or []
                    if hits and isinstance(hits, list):
                        comp_url = hits[0].get("url")
                        if comp_url:
                            break

            if not comp_url:
                return out

            page = client.get(f"https://www.screener.in{comp_url}")
            if page.status_code != 200:
                return out

            soup = BeautifulSoup(page.text, "lxml")
            ratios: dict[str, Optional[float]] = {}
            for li in soup.select("#top-ratios li"):
                spans = li.select("span")
                if len(spans) >= 2:
                    k = spans[0].get_text(strip=True).lower()
                    v = _safe_float(spans[1].get_text(strip=True))
                    ratios[k] = v

            pl_sec = soup.select_one("#profit-loss")
            bs_sec = soup.select_one("#balance-sheet")

            revs = _extract_screener_table_row(pl_sec, "Sales")
            pats = _extract_screener_table_row(pl_sec, "Net Profit")
            eq_cap = _extract_screener_table_row(bs_sec, "Equity Capital")
            reserves = _extract_screener_table_row(bs_sec, "Reserves")
            borrowings = _extract_screener_table_row(bs_sec, "Borrowings")

            net_worth_cr = None
            if eq_cap[-1] is not None or reserves[-1] is not None:
                net_worth_cr = _safe_round((eq_cap[-1] or 0.0) + (reserves[-1] or 0.0), 2)

            total_debt_cr = _safe_round(borrowings[-1], 2) if borrowings[-1] is not None else None
            mcap_cr = ratios.get("market cap")
            stock_pe = ratios.get("stock p/e")
            curr_price = ratios.get("current price")

            eps = None
            eff_price = price_max or curr_price
            if eff_price and stock_pe and stock_pe > 0:
                eps = _safe_round(eff_price / stock_pe, 2)
            elif eff_price and mcap_cr and mcap_cr > 0 and pats[-1] and pats[-1] > 0:
                eps = _safe_round((pats[-1] / mcap_cr) * eff_price, 2)

            if any(v is not None for v in revs + pats) or mcap_cr is not None:
                out = {
                    "symbol": sym,
                    "found": True,
                    "source": "Screener (RHP)",
                    "current_price": curr_price,
                    "market_cap_cr": mcap_cr,
                    "eps": eps,
                    "net_worth_cr": net_worth_cr,
                    "total_debt_cr": total_debt_cr,
                    "rev_fy1": revs[0],
                    "rev_fy2": revs[1],
                    "rev_fy3": revs[2],
                    "pat_fy1": pats[0],
                    "pat_fy2": pats[1],
                    "pat_fy3": pats[2],
                }
                cache.set(cache_key, out, ttl_seconds=PEER_CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Screener IPO fundamentals fetch failed for %s: %s", sym, exc)
    return out


def fetch_peer_metrics(symbols: list[str], force_refresh: bool = False) -> list[dict[str, Any]]:
    """Fetch live valuation & profitability ratios for listed NSE peers via Yahoo Finance."""
    results: list[dict[str, Any]] = []
    for raw_sym in symbols[:8]:
        sym = raw_sym.strip().upper().replace(".NS", "").replace(".BO", "")
        if not sym:
            continue
        cache_key = f"peer_metrics_v1:{sym}"
        if not force_refresh:
            cached = cache.get(cache_key)
            if cached:
                results.append(cached)
                continue

        ticker_sym = f"{sym}.NS"
        try:
            info = yf.Ticker(ticker_sym).info or {}
            price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
            pe = _safe_float(info.get("trailingPE") or info.get("forwardPE"))
            pb = _safe_float(info.get("priceToBook"))
            roe_raw = _safe_float(info.get("returnOnEquity"))
            roe_pct = _safe_round(roe_raw * 100, 2) if roe_raw is not None else None
            dte_raw = _safe_float(info.get("debtToEquity"))
            # yfinance debtToEquity is in percentage (e.g. 45.0 = 0.45x)
            dte = _safe_round(dte_raw / 100.0, 2) if dte_raw is not None else None
            pm_raw = _safe_float(info.get("profitMargins"))
            pm_pct = _safe_round(pm_raw * 100, 2) if pm_raw is not None else None
            mcap = _safe_float(info.get("marketCap"))
            mcap_cr = _safe_round(mcap / 1e7, 1) if mcap else None

            if price is not None or pe is not None:
                entry = {
                    "symbol": sym,
                    "name": info.get("shortName") or info.get("longName") or sym,
                    "price": _safe_round(price, 2),
                    "pe": _safe_round(pe, 2),
                    "pb": _safe_round(pb, 2),
                    "roe_pct": roe_pct,
                    "debt_to_equity": dte,
                    "profit_margin_pct": pm_pct,
                    "market_cap_cr": mcap_cr,
                }
                cache.set(cache_key, entry, ttl_seconds=PEER_CACHE_TTL_SECONDS)
                results.append(entry)
        except Exception as exc:
            logger.warning("Peer metrics fetch failed for %s: %s", sym, exc)
    return results


def fetch_listed_ipo_fundamentals(symbol: str) -> dict[str, Any]:
    """
    Attempt to auto-fill 3-year financials & valuation from Yahoo Finance
    for an already-listed IPO symbol.
    """
    sym = symbol.strip().upper().replace(".NS", "").replace(".BO", "")
    ticker_sym = f"{sym}.NS"
    out: dict[str, Any] = {"symbol": sym, "found": False}
    try:
        t = yf.Ticker(ticker_sym)
        info = t.info or {}
        price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
        if price is None:
            return out

        mcap = _safe_float(info.get("marketCap"))
        eps = _safe_float(info.get("trailingEps"))
        bv = _safe_float(info.get("bookValue"))
        shares = _safe_float(info.get("sharesOutstanding"))
        total_debt = _safe_float(info.get("totalDebt"))

        net_worth_cr = _safe_round((bv * shares) / 1e7, 2) if (bv and shares) else None
        total_debt_cr = _safe_round(total_debt / 1e7, 2) if total_debt is not None else None
        mcap_cr = _safe_round(mcap / 1e7, 2) if mcap else None

        # Extract last 3 annual Revenue & Net Income (in ₹ Cr)
        revs: list[Optional[float]] = [None, None, None]
        pats: list[Optional[float]] = [None, None, None]
        fin = t.financials
        if fin is not None and not fin.empty:
            cols = list(fin.columns)[:3]
            cols = list(reversed(cols))  # chronological: oldest -> latest
            rev_row = next((r for r in ("Total Revenue", "Operating Revenue") if r in fin.index), None)
            pat_row = next((r for r in ("Net Income", "Net Income Common Stockholders") if r in fin.index), None)
            offset = 3 - len(cols)
            for idx, col in enumerate(cols):
                if rev_row:
                    v = _safe_float(fin.loc[rev_row, col])
                    revs[offset + idx] = _safe_round(v / 1e7, 2) if v is not None else None
                if pat_row:
                    v = _safe_float(fin.loc[pat_row, col])
                    pats[offset + idx] = _safe_round(v / 1e7, 2) if v is not None else None

        out = {
            "symbol": sym,
            "found": True,
            "company_name": info.get("longName") or info.get("shortName") or sym,
            "sector": info.get("sector") or "",
            "industry": info.get("industry") or "",
            "current_price": _safe_round(price, 2),
            "market_cap_cr": mcap_cr,
            "eps": _safe_round(eps, 2),
            "net_worth_cr": net_worth_cr,
            "total_debt_cr": total_debt_cr,
            "rev_fy1": revs[0],
            "rev_fy2": revs[1],
            "rev_fy3": revs[2],
            "pat_fy1": pats[0],
            "pat_fy2": pats[1],
            "pat_fy3": pats[2],
        }
    except Exception as exc:
        logger.warning("Listed IPO fundamentals fetch failed for %s: %s", sym, exc)
    return out


def _calc_cagr(start_val: Optional[float], end_val: Optional[float], years: int = 2) -> Optional[float]:
    if not start_val or not end_val or start_val <= 0 or end_val <= 0 or years <= 0:
        return None
    return _safe_round((((end_val / start_val) ** (1.0 / years)) - 1.0) * 100.0, 2)


def analyze_ipo_report(data: dict[str, Any]) -> dict[str, Any]:
    """
    Generate a complete, plain-English Fundamental & Valuation Analysis Report
    for an Indian Mainboard (Regular) or SME IPO. Strictly GMP-free.
    """
    company_name = (data.get("company_name") or "Selected IPO").strip()
    segment = (data.get("segment") or "MAINBOARD").strip().upper()
    if segment not in {"MAINBOARD", "SME"}:
        segment = "MAINBOARD"

    price_max = _safe_float(data.get("price_max"))
    lot_size = _safe_float(data.get("lot_size"))
    issue_size_cr = _safe_float(data.get("issue_size_cr"))
    fresh_issue_pct = _safe_float(data.get("fresh_issue_pct"))
    if fresh_issue_pct is None:
        fresh_issue_pct = 100.0
    fresh_issue_pct = max(0.0, min(100.0, fresh_issue_pct))
    ofs_pct = _safe_round(100.0 - fresh_issue_pct, 1)

    # 3-Year Financials (₹ Cr)
    rev1 = _safe_float(data.get("rev_fy1"))
    rev2 = _safe_float(data.get("rev_fy2"))
    rev3 = _safe_float(data.get("rev_fy3"))
    pat1 = _safe_float(data.get("pat_fy1"))
    pat2 = _safe_float(data.get("pat_fy2"))
    pat3 = _safe_float(data.get("pat_fy3"))

    net_worth_cr = _safe_float(data.get("net_worth_cr"))
    total_debt_cr = _safe_float(data.get("total_debt_cr"))
    eps = _safe_float(data.get("eps"))
    market_cap_cr = _safe_float(data.get("post_issue_mcap_cr"))

    # Subscription (times)
    sub_qib = _safe_float(data.get("sub_qib"))
    sub_nii = _safe_float(data.get("sub_nii"))
    sub_retail = _safe_float(data.get("sub_retail"))
    sub_total = _safe_float(data.get("sub_total"))

    # Peers
    peer_symbols = [s.strip().upper() for s in (data.get("peer_symbols") or []) if s and s.strip()]
    peers = fetch_peer_metrics(peer_symbols) if peer_symbols else []
    manual_peer_pe = _safe_float(data.get("peer_median_pe"))

    peer_pes = [p["pe"] for p in peers if p.get("pe") and p["pe"] > 0]
    peer_median_pe = _safe_round(median(peer_pes), 2) if peer_pes else manual_peer_pe

    # --- Core Financial & Valuation Ratios ---
    min_investment = _safe_round(price_max * lot_size, 0) if (price_max and lot_size) else None

    # Derive IPO P/E
    ipo_pe = None
    if price_max and eps and eps > 0:
        ipo_pe = _safe_round(price_max / eps, 2)
    elif market_cap_cr and pat3 and pat3 > 0:
        ipo_pe = _safe_round(market_cap_cr / pat3, 2)

    # Derive EPS if missing but market cap & pat3 given
    if eps is None and price_max and ipo_pe and ipo_pe > 0:
        eps = _safe_round(price_max / ipo_pe, 2)

    # Derive Post-Issue Market Cap if missing but pat3 & ipo_pe known
    if market_cap_cr is None and pat3 and pat3 > 0 and ipo_pe:
        market_cap_cr = _safe_round(pat3 * ipo_pe, 2)

    ipo_pb = _safe_round(market_cap_cr / net_worth_cr, 2) if (market_cap_cr and net_worth_cr and net_worth_cr > 0) else None
    price_to_sales = _safe_round(market_cap_cr / rev3, 2) if (market_cap_cr and rev3 and rev3 > 0) else None

    roe_pct = _safe_round((pat3 / net_worth_cr) * 100.0, 2) if (pat3 is not None and net_worth_cr and net_worth_cr > 0) else None
    debt_to_equity = _safe_round(total_debt_cr / net_worth_cr, 2) if (total_debt_cr is not None and net_worth_cr and net_worth_cr > 0) else None

    # Growth & Margins
    rev_cagr = _calc_cagr(rev1, rev3, years=2)
    pat_cagr = _calc_cagr(pat1, pat3, years=2)

    m1 = _safe_round((pat1 / rev1) * 100.0, 2) if (pat1 is not None and rev1 and rev1 > 0) else None
    m2 = _safe_round((pat2 / rev2) * 100.0, 2) if (pat2 is not None and rev2 and rev2 > 0) else None
    m3 = _safe_round((pat3 / rev3) * 100.0, 2) if (pat3 is not None and rev3 and rev3 > 0) else None

    # Pre-IPO Window-Dressing Spike Detector
    margin_spike_flag = False
    if m3 is not None and m1 is not None and m2 is not None:
        prior_avg = (m1 + m2) / 2.0
        if prior_avg > 0 and m3 > prior_avg * 2.0 and (m3 - prior_avg) >= 5.0:
            margin_spike_flag = True

    # Valuation vs Peers & Implied Fair Price
    implied_fair_price = None
    valuation_diff_pct = None
    valuation_tag = "Needs Peer P/E"
    if ipo_pe is not None and peer_median_pe and peer_median_pe > 0:
        valuation_diff_pct = _safe_round(((ipo_pe - peer_median_pe) / peer_median_pe) * 100.0, 1)
        if eps and eps > 0:
            implied_fair_price = _safe_round(eps * peer_median_pe, 2)
        if valuation_diff_pct <= -15:
            valuation_tag = "Undervalued"
        elif valuation_diff_pct <= 15:
            valuation_tag = "Fairly Priced"
        else:
            valuation_tag = "Expensive"
    elif ipo_pe is not None:
        if ipo_pe <= 20:
            valuation_tag = "Reasonable"
        elif ipo_pe <= 40:
            valuation_tag = "Moderate"
        else:
            valuation_tag = "Expensive"
    elif pat3 is not None and pat3 <= 0:
        valuation_tag = "Loss-Making"

    # --- Scoring Engine (0–100) + Plain-English Insights ---
    strengths: list[str] = []
    risks: list[str] = []

    # 1. Fundamental Score (max 40)
    fund_score = 20
    if rev_cagr is not None:
        if rev_cagr >= 20:
            fund_score += 7
            strengths.append(f"Healthy revenue growth of {rev_cagr:.1f}% per year over the last 2 years.")
        elif rev_cagr >= 10:
            fund_score += 3
        elif rev_cagr < 5:
            fund_score -= 5
            risks.append(f"Slow top-line growth ({rev_cagr:.1f}% CAGR) — business expansion looks sluggish.")

    if pat_cagr is not None:
        if pat_cagr >= 25:
            fund_score += 7
            strengths.append(f"Strong profit growth ({pat_cagr:.1f}% annual PAT CAGR).")
        elif pat_cagr < 0:
            fund_score -= 7
            risks.append(f"Profits have shrunk ({pat_cagr:.1f}% CAGR) heading into the IPO.")
    elif pat3 is not None and pat3 <= 0:
        fund_score -= 12
        risks.append("Company is currently loss-making — higher downside risk if growth slows.")

    if roe_pct is not None:
        if roe_pct >= 18:
            fund_score += 6
            strengths.append(f"Strong return on equity (ROE {roe_pct:.1f}%), showing efficient use of capital.")
        elif roe_pct < 10:
            fund_score -= 4
            risks.append(f"Low ROE ({roe_pct:.1f}%) — capital efficiency is weak compared to quality peers.")

    if debt_to_equity is not None:
        if debt_to_equity <= 0.4:
            fund_score += 4
            strengths.append(f"Comfortable balance sheet with low debt (Debt/Equity {debt_to_equity:.2f}x).")
        elif debt_to_equity >= 1.2:
            fund_score -= 6
            risks.append(f"High debt load (Debt/Equity {debt_to_equity:.2f}x) — check if IPO money is going to repay loans.")

    if margin_spike_flag:
        fund_score -= 8
        risks.append(
            f"Pre-IPO profit jump alert: latest profit margin ({m3:.1f}%) is over 2x its earlier average ({(m1 + m2) / 2:.1f}%). Verify in the RHP whether this is sustainable."
        )

    if ofs_pct is not None:
        if ofs_pct >= 60:
            fund_score -= 5
            risks.append(f"{ofs_pct:.0f}% of the issue is Offer for Sale (OFS) — most of the money goes to existing owners exiting, not business growth.")
        elif fresh_issue_pct >= 80:
            fund_score += 3
            strengths.append(f"{fresh_issue_pct:.0f}% Fresh Issue — almost all IPO funds go directly into the company.")

    fund_score = max(0, min(40, fund_score))

    # 2. Valuation Score (max 35)
    val_score = 18
    if valuation_diff_pct is not None:
        if valuation_diff_pct <= -15:
            val_score = 33
            strengths.append(
                f"Attractively priced: IPO P/E ({ipo_pe}x) is {abs(valuation_diff_pct):.0f}% cheaper than listed peers ({peer_median_pe}x)."
            )
        elif valuation_diff_pct <= 10:
            val_score = 25
            strengths.append(
                f"Fairly priced in line with listed peers (IPO P/E {ipo_pe}x vs Peer Median {peer_median_pe}x)."
            )
        elif valuation_diff_pct <= 35:
            val_score = 14
            risks.append(
                f"Priced at a {valuation_diff_pct:.0f}% premium to peers (IPO P/E {ipo_pe}x vs {peer_median_pe}x) — leaves less room for listing upside."
            )
        else:
            val_score = 6
            risks.append(
                f"Expensive valuation: IPO P/E ({ipo_pe}x) is {valuation_diff_pct:.0f}% above peers ({peer_median_pe}x)."
            )
    elif ipo_pe is not None:
        if ipo_pe <= 18:
            val_score = 28
            strengths.append(f"Reasonable standalone P/E of {ipo_pe}x at the upper price band.")
        elif ipo_pe <= 35:
            val_score = 20
        else:
            val_score = 10
            risks.append(f"High standalone P/E ({ipo_pe}x) — requires strong future growth to justify.")
    elif pat3 is not None and pat3 <= 0:
        val_score = 6

    # 3. Demand / Subscription Score (max 25, official NSE subscription only — no GMP)
    demand_score = 12
    if sub_qib is not None and sub_qib > 0:
        if sub_qib >= 20:
            demand_score = 24
            strengths.append(f"Strong institutional backing: QIBs subscribed {sub_qib:.1f}x, showing serious big-money confidence.")
        elif sub_qib >= 5:
            demand_score = 19
            strengths.append(f"Healthy QIB institutional interest ({sub_qib:.1f}x subscribed).")
        elif sub_qib < 1.5 and (sub_retail or 0) >= 5:
            demand_score = 7
            risks.append(
                f"Possible retail trap: Retail subscribed {sub_retail:.1f}x while QIBs are weak at {sub_qib:.1f}x."
            )
        elif sub_qib < 1.0:
            demand_score = 6
            risks.append(f"Weak institutional interest so far (QIB {sub_qib:.2f}x).")
    elif sub_total is not None and sub_total > 0:
        if sub_total >= 25:
            demand_score = 22
            strengths.append(f"Heavy overall subscription ({sub_total:.1f}x).")
        elif sub_total >= 5:
            demand_score = 17
        elif sub_total < 1.5:
            demand_score = 8
            risks.append(f"Muted overall subscription ({sub_total:.2f}x).")

    # SME-specific risk reminders
    if segment == "SME":
        lot_note = f" (min ~₹{int(min_investment):,} per lot)" if min_investment else ""
        risks.append(
            f"SME IPO risk{lot_note}: shares trade only in full lots after listing, so liquidity is lower and circuit swings can be sharp."
        )

    overall_score = max(0, min(100, fund_score + val_score + demand_score))

    # Plain-English Verdicts (aligned with scores & demand)
    if (demand_score >= 21 and overall_score >= 65) or (demand_score >= 19 and val_score >= 18 and overall_score >= 65):
        listing_verdict = "Strong Listing Potential"
        listing_note = "Heavy buyer demand and solid overall score support a strong listing pop."
    elif val_score <= 10 or (sub_qib is not None and sub_qib < 1.5 and (sub_retail or 0) >= 5):
        listing_verdict = "Caution / Risky for Listing"
        listing_note = "Stretched pricing or weak institutional backing makes short-term listing gains risky."
    else:
        listing_verdict = "Moderate / Selective"
        listing_note = "Wait for final QIB/total subscription numbers before deciding on a short-term listing bet."

    if ((fund_score >= 32 and val_score >= 14) or (fund_score >= 28 and val_score >= 20)) and not margin_spike_flag:
        long_term_verdict = "Good for Long Term"
        long_term_note = "Strong growth, healthy return ratios, and reasonable pricing make this worth holding beyond listing."
    elif fund_score <= 16 or margin_spike_flag or (pat3 is not None and pat3 <= 0):
        long_term_verdict = "Avoid / Wait for 2 Quarters"
        long_term_note = "Fundamental red flags or unverified profit jump — safer to watch 2 post-listing quarterly results first."
    else:
        long_term_verdict = "Neutral / Track Post-Listing"
        long_term_note = "Decent business, but no clear margin of safety yet. Consider accumulating only on post-listing dips."

    # 2-sentence human-readable summary
    val_phrase = (
        f"priced {abs(valuation_diff_pct):.0f}% {'below' if valuation_diff_pct < 0 else 'above'} peers"
        if valuation_diff_pct is not None
        else (f"priced at {ipo_pe}x P/E" if ipo_pe else "awaiting full earnings data")
    )
    seg_label = "SME IPO" if segment == "SME" else "Mainboard IPO"
    plain_summary = (
        f"{company_name} ({seg_label}) scores {overall_score}/100 overall and is {val_phrase}. "
        f"Listing view: {listing_verdict}. Long-term view: {long_term_verdict}."
    )

    # --- Listing Price Prediction (Strictly Fundamental + Official Subscription, No GMP) ---
    listing_prediction = _estimate_listing_price(
        price_max=price_max,
        lot_size=lot_size,
        valuation_diff_pct=valuation_diff_pct,
        fund_score=fund_score,
        margin_spike_flag=margin_spike_flag,
        pat3=pat3,
        sub_qib=sub_qib,
        sub_total=sub_total,
    )

    return {
        "company_name": company_name,
        "segment": segment,
        "scores": {
            "overall": overall_score,
            "fundamental": fund_score,
            "fundamental_max": 40,
            "valuation": val_score,
            "valuation_max": 35,
            "demand": demand_score,
            "demand_max": 25,
        },
        "verdict": {
            "listing": listing_verdict,
            "listing_note": listing_note,
            "long_term": long_term_verdict,
            "long_term_note": long_term_note,
            "plain_summary": plain_summary,
        },
        "listing_prediction": listing_prediction,
        "valuation": {
            "price_max": price_max,
            "lot_size": int(lot_size) if lot_size else None,
            "min_investment": min_investment,
            "issue_size_cr": issue_size_cr,
            "fresh_issue_pct": _safe_round(fresh_issue_pct, 1),
            "ofs_pct": ofs_pct,
            "post_issue_mcap_cr": market_cap_cr,
            "eps": eps,
            "ipo_pe": ipo_pe,
            "ipo_pb": ipo_pb,
            "price_to_sales": price_to_sales,
            "peer_median_pe": peer_median_pe,
            "implied_fair_price": implied_fair_price,
            "valuation_diff_pct": valuation_diff_pct,
            "valuation_tag": valuation_tag,
        },
        "fundamentals": {
            "rev_cagr_pct": rev_cagr,
            "pat_cagr_pct": pat_cagr,
            "roe_pct": roe_pct,
            "debt_to_equity": debt_to_equity,
            "margin_spike_flag": margin_spike_flag,
            "yearly": [
                {"year": "FY-2", "revenue": rev1, "pat": pat1, "margin_pct": m1},
                {"year": "FY-1", "revenue": rev2, "pat": pat2, "margin_pct": m2},
                {"year": "Latest FY", "revenue": rev3, "pat": pat3, "margin_pct": m3},
            ],
        },
        "subscription": {
            "qib": sub_qib,
            "nii": sub_nii,
            "retail": sub_retail,
            "total": sub_total,
        },
        "peers": peers,
        "strengths": strengths,
        "risks": risks,
        "disclaimer": "Based strictly on official exchange/financial data (no unofficial GMP). For educational research only — not SEBI-registered investment advice.",
    }


def _estimate_listing_price(
    price_max: Optional[float],
    lot_size: Optional[float],
    valuation_diff_pct: Optional[float],
    fund_score: int,
    margin_spike_flag: bool,
    pat3: Optional[float],
    sub_qib: Optional[float],
    sub_total: Optional[float],
) -> dict[str, Any]:
    """
    Estimate a realistic listing price range strictly from:
    1) Valuation discount/premium vs peers
    2) Fundamental quality score
    3) Official NSE subscription demand (QIB / Total)
    """
    if not price_max or price_max <= 0:
        return {"available": False, "note": "Upper issue price not available yet."}

    drivers: list[str] = []
    # 1. Valuation component (-12% to +18%)
    val_adj = 0.0
    if valuation_diff_pct is not None:
        if valuation_diff_pct <= -25:
            val_adj = 18.0
            drivers.append(f"valuation discount ({abs(valuation_diff_pct):.0f}% below peers)")
        elif valuation_diff_pct <= -10:
            val_adj = 10.0
            drivers.append(f"reasonable pricing ({abs(valuation_diff_pct):.0f}% below peers)")
        elif valuation_diff_pct <= 15:
            val_adj = 2.0
        elif valuation_diff_pct <= 35:
            val_adj = -5.0
            drivers.append(f"premium pricing (+{valuation_diff_pct:.0f}% vs peers)")
        else:
            val_adj = -12.0
            drivers.append(f"expensive valuation (+{valuation_diff_pct:.0f}% vs peers)")

    # 2. Fundamental component (-8% to +6%)
    fund_adj = 0.0
    if fund_score >= 30:
        fund_adj = 6.0
        drivers.append("strong fundamentals")
    elif fund_score >= 24:
        fund_adj = 3.0
    elif fund_score <= 15:
        fund_adj = -6.0
        drivers.append("weak fundamentals")
    if margin_spike_flag:
        fund_adj -= 4.0
    if pat3 is not None and pat3 <= 0:
        fund_adj -= 5.0

    # 3. Official Subscription Demand component
    sub_adj = 0.0
    sub_known = False
    eff_sub = sub_qib if (sub_qib is not None and sub_qib > 0) else (sub_total if (sub_total is not None and sub_total > 0) else None)
    if eff_sub is not None:
        sub_known = True
        if eff_sub >= 50:
            sub_adj = 32.0
            drivers.append(f"very heavy demand ({eff_sub:.1f}x)")
        elif eff_sub >= 20:
            sub_adj = 20.0
            drivers.append(f"strong demand ({eff_sub:.1f}x)")
        elif eff_sub >= 5:
            sub_adj = 9.0
            drivers.append(f"healthy demand ({eff_sub:.1f}x)")
        elif eff_sub >= 1.5:
            sub_adj = 2.0
            drivers.append(f"moderate demand ({eff_sub:.1f}x)")
        else:
            sub_adj = -4.0
            drivers.append(f"weak demand ({eff_sub:.1f}x)")

    mid_pct = max(-25.0, min(60.0, val_adj + fund_adj + sub_adj))
    spread = 4.0 if sub_known else 6.0
    low_pct = _safe_round(mid_pct - spread, 1)
    high_pct = _safe_round(mid_pct + spread, 1)
    mid_pct_r = _safe_round(mid_pct, 1)

    est_low = _safe_round(price_max * (1.0 + low_pct / 100.0), 1)
    est_high = _safe_round(price_max * (1.0 + high_pct / 100.0), 1)
    est_mid = _safe_round(price_max * (1.0 + mid_pct_r / 100.0), 1)
    lot_profit_mid = _safe_round((est_mid - price_max) * lot_size, 0) if lot_size else None

    # Fundamentals-only estimate (Valuation + Company Health only, ignoring subscription)
    f_mid_pct = max(-25.0, min(30.0, val_adj + fund_adj))
    f_low_pct = _safe_round(f_mid_pct - 5.0, 1)
    f_high_pct = _safe_round(f_mid_pct + 5.0, 1)
    f_mid_pct_r = _safe_round(f_mid_pct, 1)

    f_est_low = _safe_round(price_max * (1.0 + f_low_pct / 100.0), 1)
    f_est_high = _safe_round(price_max * (1.0 + f_high_pct / 100.0), 1)
    f_est_mid = _safe_round(price_max * (1.0 + f_mid_pct_r / 100.0), 1)
    f_lot_profit_mid = _safe_round((f_est_mid - price_max) * lot_size, 0) if lot_size else None

    if not sub_known:
        note = "Bidding not open / 0x yet — reflects fundamentals & valuation only."
    elif drivers:
        note = "Driven by " + ", ".join(drivers) + "."
    else:
        note = "Balanced valuation and moderate demand point to a steady listing."

    return {
        "available": True,
        "issue_price": price_max,
        "est_low": est_low,
        "est_high": est_high,
        "est_mid": est_mid,
        "gain_low_pct": low_pct,
        "gain_high_pct": high_pct,
        "gain_mid_pct": mid_pct_r,
        "lot_profit_mid": lot_profit_mid,
        "subscription_used": sub_known,
        "note": note,
        "fundamentals_only": {
            "est_low": f_est_low,
            "est_high": f_est_high,
            "est_mid": f_est_mid,
            "gain_low_pct": f_low_pct,
            "gain_high_pct": f_high_pct,
            "gain_mid_pct": f_mid_pct_r,
            "lot_profit_mid": f_lot_profit_mid,
        },
    }
