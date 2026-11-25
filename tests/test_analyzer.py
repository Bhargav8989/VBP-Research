import pandas as pd

from app.main import STATIC_DIR, health_check, serve_frontend
from app.services.analyzer import analyze_events
from app.services.events import deduplicate_events
from app.services.stocks import search_stocks


def _make_sample_prices(days: int = 120, start_price: float = 100.0) -> pd.DataFrame:
    dates = pd.bdate_range("2025-01-01", periods=days)
    # Deterministic upward drift (+1 per trading day)
    closes = [start_price + i for i in range(days)]
    volumes = [100000] * days
    # Volume spike around day 50
    volumes[49] = 300000
    volumes[50] = 500000
    volumes[51] = 250000
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Close": closes,
            "Volume": volumes,
        },
        index=dates,
    )


def test_analyze_events_trading_days_basic():
    df = _make_sample_prices(120, start_price=100.0)
    t0_date = df.index[50].strftime("%Y-%m-%d")  # Close = 150.0
    events = [{"date": t0_date, "event_type": "RESULTS", "label": "Q4 Result", "source": "Test"}]

    result = analyze_events(
        price_df=df,
        events=events,
        before_days=20,
        after_days=10,
        day_mode="trading",
        normalize_to="start",
    )

    assert len(result["events"]) == 1
    ev = result["events"][0]
    assert ev["t0_date"] == t0_date
    assert ev["start_price"] == 130.0  # day 30
    assert ev["t0_price"] == 150.0     # day 50
    assert ev["end_price"] == 160.0    # day 60
    assert ev["pre_return_pct"] == round(((150.0 - 130.0) / 130.0) * 100, 2)
    assert ev["post_return_pct"] == round(((160.0 - 150.0) / 150.0) * 100, 2)
    assert ev["volume_surge_ratio"] > 3.0
    assert len(ev["trace"]) == 31  # T-20 .. T0 .. T+10 inclusive
    assert ev["trace"][0]["offset"] == -20
    assert ev["trace"][20]["offset"] == 0
    assert ev["trace"][-1]["offset"] == 10
    assert result["summary"]["events_analyzed"] == 1
    assert result["summary"]["pre_win_rate_pct"] == 100.0


def test_analyze_events_with_benchmark_and_event_normalization():
    df = _make_sample_prices(120, start_price=100.0)
    bench = _make_sample_prices(120, start_price=200.0)  # Slower % growth than stock
    t0_date = df.index[50].strftime("%Y-%m-%d")
    events = [{"date": t0_date, "event_type": "AGM", "label": "AGM 2025", "source": "Test"}]

    result = analyze_events(
        price_df=df,
        events=events,
        before_days=20,
        after_days=10,
        day_mode="trading",
        normalize_to="event",
        benchmark_df=bench,
    )

    ev = result["events"][0]
    t0_point = [p for p in ev["trace"] if p["offset"] == 0][0]
    assert t0_point["pct_change"] == 0.0
    assert ev["total_alpha_pct"] is not None
    assert ev["total_alpha_pct"] > 0


def test_analyze_events_calendar_mode():
    df = _make_sample_prices(120, start_price=100.0)
    t0_date = df.index[50].strftime("%Y-%m-%d")
    events = [{"date": t0_date, "event_type": "RESULTS", "label": "Q4", "source": "Test"}]

    result = analyze_events(
        price_df=df,
        events=events,
        before_days=20,
        after_days=10,
        day_mode="calendar",
    )

    ev = result["events"][0]
    offsets = [p["offset"] for p in ev["trace"]]
    assert min(offsets) >= -20
    assert max(offsets) <= 10
    assert 0 in offsets


def test_deduplicate_events():
    events = [
        {"date": "2025-07-18", "label": "A"},
        {"date": "2025-07-20", "label": "B"},
        {"date": "2025-04-21", "label": "C"},
    ]
    deduped = deduplicate_events(events, min_gap_days=10)
    assert len(deduped) == 2
    assert deduped[0]["date"] == "2025-07-20"
    assert deduped[1]["date"] == "2025-04-21"


def test_stock_search_fallback():
    results = search_stocks("RELIANCE")
    assert any(r["symbol"] == "RELIANCE" for r in results)


def test_frontend_and_health_routes():
    assert health_check()["status"] == "ok"
    home = serve_frontend()
    assert str(home.path).endswith("index.html")
    html_text = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert "VBP Research" in html_text
    assert (STATIC_DIR / "vbp-logo.png").exists()
    assert (STATIC_DIR / "app.js").exists()
    assert (STATIC_DIR / "styles.css").exists()
