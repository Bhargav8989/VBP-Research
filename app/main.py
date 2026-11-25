from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.services.analyzer import analyze_events, compute_range_comparison
from app.services.events import fetch_corporate_events
from app.services.ipo import (
    analyze_ipo_report,
    fetch_ipo_detail,
    fetch_ipo_list,
    fetch_listed_ipo_fundamentals,
)
from app.services.peers import compare_sector_peers
from app.services.prices import fetch_benchmark_history, fetch_price_history
from app.services.stocks import get_stock_info, search_stocks

app = FastAPI(
    title="VBP Research — Indian Stock & IPO Analyzer",
    description="Lightweight event-study & IPO fundamental analyzer for NSE/BSE stocks.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def serve_frontend() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health_check() -> dict:
    return {"status": "ok", "service": "vbp-research-analyzer"}


@app.get("/api/stocks/search")
def api_search_stocks(
    q: str = Query(default="", description="Symbol or company name search query"),
    limit: int = Query(default=15, ge=1, le=50),
) -> dict:
    results = search_stocks(q, limit=limit)
    return {"query": q, "count": len(results), "results": results}


@app.get("/api/events/{symbol}")
def api_get_events(
    symbol: str,
    event_type: Literal["RESULTS", "AGM"] = Query(default="RESULTS"),
    refresh: bool = Query(default=False),
) -> dict:
    sym = symbol.strip().upper()
    events = fetch_corporate_events(sym, event_type=event_type, force_refresh=refresh)
    return {
        "symbol": sym,
        "event_type": event_type,
        "count": len(events),
        "events": events,
    }


@app.get("/api/analyze/{symbol}")
def api_analyze_stock(
    symbol: str,
    event_type: Literal["RESULTS", "AGM", "CUSTOM"] = Query(default="RESULTS"),
    before: int = Query(default=20, ge=1, le=120, description="Days before event (T-before)"),
    after: int = Query(default=10, ge=1, le=120, description="Days after event (T+after)"),
    day_mode: Literal["trading", "calendar"] = Query(default="trading"),
    normalize_to: Literal["start", "event"] = Query(default="start"),
    limit: int = Query(default=12, ge=1, le=40, description="Max past events to analyze"),
    include_nifty: bool = Query(default=True, description="Include Nifty 50 relative alpha"),
    custom_dates: Optional[str] = Query(
        default=None,
        description="Comma-separated YYYY-MM-DD dates (used when event_type=CUSTOM or to append extra dates)",
    ),
    refresh: bool = Query(default=False),
) -> dict:
    sym = symbol.strip().upper()
    stock_meta = get_stock_info(sym)

    # 1. Resolve event dates
    events: list[dict[str, str]] = []
    if event_type in ("RESULTS", "AGM"):
        events = fetch_corporate_events(sym, event_type=event_type, force_refresh=refresh)

    if custom_dates:
        parsed_custom: list[dict[str, str]] = []
        for raw_dt in custom_dates.split(","):
            raw_dt = raw_dt.strip()
            if not raw_dt:
                continue
            try:
                dt_iso = datetime.strptime(raw_dt, "%Y-%m-%d").strftime("%Y-%m-%d")
                parsed_custom.append(
                    {
                        "date": dt_iso,
                        "event_type": event_type,
                        "label": f"Custom ({dt_iso})",
                        "source": "Custom",
                    }
                )
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid custom date '{raw_dt}'. Expected YYYY-MM-DD.",
                )
        events = parsed_custom + events

    if not events:
        raise HTTPException(
            status_code=404,
            detail=f"No {event_type} dates found for {sym}. Try passing custom_dates=YYYY-MM-DD.",
        )

    # 2. Fetch price history (+ optional Nifty 50 benchmark)
    price_df, resolved_ticker = fetch_price_history(sym, period="10y", force_refresh=refresh)
    if price_df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"Could not fetch historical prices for {sym} ({resolved_ticker}).",
        )

    benchmark_df = fetch_benchmark_history(period="10y", force_refresh=refresh) if include_nifty else None

    # 3. Run event-study analysis
    analysis = analyze_events(
        price_df=price_df,
        events=events,
        before_days=before,
        after_days=after,
        day_mode=day_mode,
        normalize_to=normalize_to,
        benchmark_df=benchmark_df,
        max_events=limit,
    )

    range_comparison = compute_range_comparison(
        price_df=price_df,
        events=events,
        day_mode=day_mode,
        max_events=limit,
    )

    latest_price_date = price_df.index[-1].strftime("%Y-%m-%d")
    latest_close = round(float(price_df["Close"].iloc[-1]), 2)

    return {
        "stock": {
            **stock_meta,
            "ticker": resolved_ticker,
            "latest_date": latest_price_date,
            "latest_close": latest_close,
        },
        "params": {
            "event_type": event_type,
            "before": before,
            "after": after,
            "day_mode": day_mode,
            "normalize_to": normalize_to,
            "limit": limit,
            "include_nifty": include_nifty,
        },
        "range_comparison": range_comparison,
        **analysis,
    }


@app.get("/api/analyze/{symbol}/peers")
def api_analyze_peers(
    symbol: str,
    event_type: Literal["RESULTS", "AGM", "CUSTOM"] = Query(default="RESULTS"),
    before: int = Query(default=20, ge=1, le=120),
    after: int = Query(default=10, ge=1, le=120),
    limit: int = Query(default=8, ge=1, le=20),
) -> dict:
    sym = symbol.strip().upper()
    return compare_sector_peers(
        symbol=sym,
        event_type=event_type,
        before=before,
        after=after,
        limit=limit,
        max_peers=5,
    )


@app.get("/api/ipo/list")
def api_ipo_list(
    segment: Literal["ALL", "MAINBOARD", "SME"] = Query(default="ALL"),
    status: Literal["ALL", "OPEN", "ALLOTMENT", "UPCOMING", "LISTED"] = Query(default="ALL"),
    exchange: Literal["ALL", "NSE", "BSE"] = Query(default="ALL"),
    refresh: bool = Query(default=False),
) -> dict:
    ipos = fetch_ipo_list(segment=segment, status=status, exchange=exchange, force_refresh=refresh)
    return {
        "segment": segment,
        "status": status,
        "exchange": exchange,
        "count": len(ipos),
        "ipos": ipos,
    }


@app.get("/api/ipo/detail/{symbol}")
def api_ipo_detail(
    symbol: str,
    name: str = Query(default=""),
    ch_url: str = Query(default=""),
    refresh: bool = Query(default=False),
) -> dict:
    return fetch_ipo_detail(symbol, company_name=name, chittorgarh_url=ch_url, force_refresh=refresh)


@app.get("/api/ipo/fundamentals/{symbol}")
def api_ipo_fundamentals(symbol: str) -> dict:
    return fetch_listed_ipo_fundamentals(symbol)


@app.post("/api/ipo/analyze")
def api_ipo_analyze(payload: dict[str, Any] = Body(...)) -> dict:
    return analyze_ipo_report(payload)
