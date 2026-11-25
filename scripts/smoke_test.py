"""Quick end-to-end smoke test for Phase 1 APIs (live NSE + Yahoo Finance)."""
import json

from app.services.analyzer import analyze_events
from app.services.events import fetch_corporate_events
from app.services.prices import fetch_benchmark_history, fetch_price_history
from app.services.stocks import search_stocks


def main() -> None:
    print("1. Searching stocks for 'RELIANCE'...")
    stocks = search_stocks("RELIANCE", limit=3)
    print("   Matches:", stocks)

    print("\n2. Fetching price history for RELIANCE and Nifty 50...")
    price_df, ticker = fetch_price_history("RELIANCE", period="5y")
    bench_df = fetch_benchmark_history(period="5y")
    print(f"   {ticker}: {len(price_df)} trading days (latest: {price_df.index[-1].strftime('%Y-%m-%d') if not price_df.empty else 'N/A'})")
    print(f"   ^NSEI: {len(bench_df) if bench_df is not None else 0} trading days")

    for ev_type in ("RESULTS", "AGM"):
        print(f"\n3. Fetching {ev_type} dates for RELIANCE...")
        events = fetch_corporate_events("RELIANCE", event_type=ev_type)
        print(f"   Found {len(events)} {ev_type} events. Latest 5:", [e["date"] for e in events[:5]])
        if events and not price_df.empty:
            res = analyze_events(
                price_df=price_df,
                events=events,
                before_days=20,
                after_days=10,
                day_mode="trading",
                normalize_to="start",
                benchmark_df=bench_df,
                max_events=8,
            )
            print(f"   Summary ({ev_type}):", json.dumps(res["summary"], indent=2))


if __name__ == "__main__":
    main()
