from statistics import mean, median
from typing import Any, Optional

import pandas as pd


def _safe_round(val: Optional[float], digits: int = 2) -> Optional[float]:
    if val is None or pd.isna(val):
        return None
    return round(float(val), digits)


def _pct_return(start_val: float, end_val: float) -> float:
    if not start_val:
        return 0.0
    return ((end_val - start_val) / start_val) * 100.0


def _find_t0_position(dates: pd.DatetimeIndex, event_ts: pd.Timestamp) -> Optional[int]:
    """
    Snap event_ts to the exact trading day if open, otherwise the next trading day.
    Returns integer index position in `dates`, or None if out of bounds.
    """
    pos = int(dates.searchsorted(event_ts, side="left"))
    if pos >= len(dates):
        # Allow a 3-day grace window if the event is on a recent weekend/holiday
        if len(dates) > 0 and (event_ts - dates[-1]).days <= 3:
            return len(dates) - 1
        return None
    # If the snapped trading day is more than 10 days away, treat as missing data
    if (dates[pos] - event_ts).days > 10:
        return None
    return pos


def analyze_events(
    price_df: pd.DataFrame,
    events: list[dict[str, str]],
    before_days: int = 20,
    after_days: int = 10,
    day_mode: str = "trading",
    normalize_to: str = "start",
    benchmark_df: Optional[pd.DataFrame] = None,
    max_events: int = 12,
) -> dict[str, Any]:
    """
    Run an event-study analysis on `price_df` around each date in `events`.

    Parameters:
    - before_days: Number of days before T0 (default 20)
    - after_days: Number of days after T0 (default 10)
    - day_mode: 'trading' (market sessions) or 'calendar' (calendar days)
    - normalize_to: 'start' (0% at window start) or 'event' (0% at T0)
    - benchmark_df: Optional Nifty 50 DataFrame for alpha calculations
    - max_events: Maximum number of most recent valid events to include
    """
    if price_df is None or price_df.empty:
        return {"events": [], "average_trace": [], "summary": {}}

    df = price_df.sort_index()
    dates = df.index
    bench_close = benchmark_df["Close"].sort_index() if benchmark_df is not None and not benchmark_df.empty else None

    analyzed_events: list[dict[str, Any]] = []
    upcoming_candidates: list[dict[str, str]] = []
    latest_market_date = dates[-1]
    # Map offset -> list of values across events for computing average trace
    offset_buckets: dict[int, dict[str, list[float]]] = {}

    for ev in events:
        event_ts = pd.Timestamp(ev["date"])
        if event_ts > latest_market_date:
            upcoming_candidates.append(ev)
            continue

        if len(analyzed_events) >= max_events:
            continue

        t0_pos = _find_t0_position(dates, event_ts)
        if t0_pos is None:
            continue

        t0_date = dates[t0_pos]

        if day_mode == "calendar":
            start_ts = t0_date - pd.Timedelta(days=before_days)
            end_ts = t0_date + pd.Timedelta(days=after_days)
            start_pos = int(dates.searchsorted(start_ts, side="left"))
            end_pos = int(dates.searchsorted(end_ts, side="right")) - 1
        else:
            start_pos = max(0, t0_pos - before_days)
            end_pos = min(len(dates) - 1, t0_pos + after_days)

        # Require at least some pre-event history so the trace is meaningful
        if start_pos >= t0_pos or end_pos < t0_pos:
            continue

        window = df.iloc[start_pos : end_pos + 1]
        if window.empty:
            continue

        start_close = float(window["Close"].iloc[0])
        t0_close = float(df["Close"].iloc[t0_pos])
        end_close = float(window["Close"].iloc[-1])
        base_close = t0_close if normalize_to == "event" else start_close

        # Event-day reaction (T-1 -> T0) and next-day reaction (T0 -> T+1)
        prev_close = float(df["Close"].iloc[t0_pos - 1]) if t0_pos > 0 else t0_close
        next_close = float(df["Close"].iloc[t0_pos + 1]) if t0_pos + 1 < len(df) else t0_close
        event_day_return = _pct_return(prev_close, t0_close)
        next_day_return = _pct_return(t0_close, next_close) if t0_pos + 1 < len(df) else None

        pre_return = _pct_return(start_close, t0_close)
        post_return = _pct_return(t0_close, end_close)
        total_return = _pct_return(start_close, end_close)

        # Volume surge: avg volume around [T-1, T+1] vs 20-day baseline before window
        baseline_start = max(0, start_pos - 20)
        baseline_vols = df["Volume"].iloc[baseline_start:start_pos] if start_pos > baseline_start else window["Volume"]
        baseline_avg_vol = float(baseline_vols.mean()) if not baseline_vols.empty else 0.0
        event_vol_slice = df["Volume"].iloc[max(0, t0_pos - 1) : min(len(df), t0_pos + 2)]
        event_avg_vol = float(event_vol_slice.mean()) if not event_vol_slice.empty else 0.0
        volume_surge = (event_avg_vol / baseline_avg_vol) if baseline_avg_vol > 0 else None

        # Benchmark alignment
        bench_base = None
        bench_start = None
        bench_t0 = None
        bench_end = None
        if bench_close is not None:
            aligned_bench = bench_close.reindex(window.index, method="ffill")
            if not aligned_bench.isna().all():
                bench_start = float(aligned_bench.iloc[0]) if not pd.isna(aligned_bench.iloc[0]) else None
                bench_t0_val = aligned_bench.loc[t0_date] if t0_date in aligned_bench.index else None
                bench_t0 = float(bench_t0_val) if bench_t0_val is not None and not pd.isna(bench_t0_val) else None
                bench_end = float(aligned_bench.iloc[-1]) if not pd.isna(aligned_bench.iloc[-1]) else None
                bench_base = bench_t0 if normalize_to == "event" else bench_start
        else:
            aligned_bench = None

        pre_alpha = (
            pre_return - _pct_return(bench_start, bench_t0)
            if bench_start and bench_t0
            else None
        )
        post_alpha = (
            post_return - _pct_return(bench_t0, bench_end)
            if bench_t0 and bench_end
            else None
        )
        total_alpha = (
            total_return - _pct_return(bench_start, bench_end)
            if bench_start and bench_end
            else None
        )

        # Build daily trace
        trace: list[dict[str, Any]] = []
        pct_series: list[float] = []

        for rel_idx, (dt, row) in enumerate(window.iterrows()):
            abs_pos = start_pos + rel_idx
            if day_mode == "calendar":
                offset = int((dt - t0_date).days)
            else:
                offset = abs_pos - t0_pos

            close_val = float(row["Close"])
            pct_val = _pct_return(base_close, close_val)
            pct_series.append(pct_val)

            b_pct = None
            alpha_val = None
            if aligned_bench is not None and bench_base:
                b_val = aligned_bench.loc[dt]
                if not pd.isna(b_val):
                    b_pct = _pct_return(bench_base, float(b_val))
                    alpha_val = pct_val - b_pct

            trace.append(
                {
                    "offset": offset,
                    "date": dt.strftime("%Y-%m-%d"),
                    "close": _safe_round(close_val, 2),
                    "volume": int(row.get("Volume", 0) or 0),
                    "pct_change": _safe_round(pct_val, 2),
                    "benchmark_pct_change": _safe_round(b_pct, 2),
                    "alpha": _safe_round(alpha_val, 2),
                }
            )

            bucket = offset_buckets.setdefault(offset, {"pct": [], "bench": [], "alpha": []})
            bucket["pct"].append(pct_val)
            if b_pct is not None:
                bucket["bench"].append(b_pct)
            if alpha_val is not None:
                bucket["alpha"].append(alpha_val)

        # Max gain and max drawdown relative to window start
        rel_from_start = [_pct_return(start_close, float(c)) for c in window["Close"]]
        max_gain = max(rel_from_start) if rel_from_start else 0.0
        max_drawdown = min(rel_from_start) if rel_from_start else 0.0

        expected_post = after_days if day_mode == "trading" else max(1, int(after_days * 0.6))
        actual_post_sessions = end_pos - t0_pos
        is_ongoing = actual_post_sessions < expected_post and end_pos == len(dates) - 1

        analyzed_events.append(
            {
                "event_date": ev["date"],
                "t0_date": t0_date.strftime("%Y-%m-%d"),
                "label": ev.get("label", ev.get("event_type", "Event")),
                "source": ev.get("source", "Custom"),
                "is_ongoing": is_ongoing,
                "start_price": _safe_round(start_close, 2),
                "t0_price": _safe_round(t0_close, 2),
                "end_price": _safe_round(end_close, 2),
                "pre_return_pct": _safe_round(pre_return, 2),
                "event_day_return_pct": _safe_round(event_day_return, 2),
                "next_day_return_pct": _safe_round(next_day_return, 2),
                "post_return_pct": _safe_round(post_return, 2),
                "total_return_pct": _safe_round(total_return, 2),
                "pre_alpha_pct": _safe_round(pre_alpha, 2),
                "post_alpha_pct": _safe_round(post_alpha, 2),
                "total_alpha_pct": _safe_round(total_alpha, 2),
                "max_gain_pct": _safe_round(max_gain, 2),
                "max_drawdown_pct": _safe_round(max_drawdown, 2),
                "volume_surge_ratio": _safe_round(volume_surge, 2),
                "trace": trace,
            }
        )

    # Compute average trace sorted by offset
    average_trace: list[dict[str, Any]] = []
    for offset in sorted(offset_buckets.keys()):
        b = offset_buckets[offset]
        pcts = b["pct"]
        if not pcts:
            continue
        average_trace.append(
            {
                "offset": offset,
                "count": len(pcts),
                "avg_pct_change": _safe_round(mean(pcts), 2),
                "median_pct_change": _safe_round(median(pcts), 2),
                "min_pct_change": _safe_round(min(pcts), 2),
                "max_pct_change": _safe_round(max(pcts), 2),
                "avg_benchmark_pct_change": _safe_round(mean(b["bench"]), 2) if b["bench"] else None,
                "avg_alpha": _safe_round(mean(b["alpha"]), 2) if b["alpha"] else None,
            }
        )

    # Compute summary KPIs
    summary: dict[str, Any] = {}
    if analyzed_events:
        pre_vals = [e["pre_return_pct"] for e in analyzed_events if e["pre_return_pct"] is not None]
        post_vals = [e["post_return_pct"] for e in analyzed_events if e["post_return_pct"] is not None]
        ev_vals = [e["event_day_return_pct"] for e in analyzed_events if e["event_day_return_pct"] is not None]
        tot_vals = [e["total_return_pct"] for e in analyzed_events if e["total_return_pct"] is not None]
        vol_vals = [e["volume_surge_ratio"] for e in analyzed_events if e["volume_surge_ratio"] is not None]
        tot_alphas = [e["total_alpha_pct"] for e in analyzed_events if e["total_alpha_pct"] is not None]

        best_ev = max(analyzed_events, key=lambda e: e["total_return_pct"] or -9999)
        worst_ev = min(analyzed_events, key=lambda e: e["total_return_pct"] or 9999)

        summary = {
            "events_analyzed": len(analyzed_events),
            "avg_pre_return_pct": _safe_round(mean(pre_vals), 2) if pre_vals else None,
            "median_pre_return_pct": _safe_round(median(pre_vals), 2) if pre_vals else None,
            "pre_win_rate_pct": _safe_round((sum(1 for v in pre_vals if v > 0) / len(pre_vals)) * 100, 1) if pre_vals else None,
            "avg_event_day_return_pct": _safe_round(mean(ev_vals), 2) if ev_vals else None,
            "avg_post_return_pct": _safe_round(mean(post_vals), 2) if post_vals else None,
            "median_post_return_pct": _safe_round(median(post_vals), 2) if post_vals else None,
            "post_win_rate_pct": _safe_round((sum(1 for v in post_vals if v > 0) / len(post_vals)) * 100, 1) if post_vals else None,
            "avg_total_return_pct": _safe_round(mean(tot_vals), 2) if tot_vals else None,
            "total_win_rate_pct": _safe_round((sum(1 for v in tot_vals if v > 0) / len(tot_vals)) * 100, 1) if tot_vals else None,
            "avg_total_alpha_pct": _safe_round(mean(tot_alphas), 2) if tot_alphas else None,
            "avg_volume_surge_ratio": _safe_round(mean(vol_vals), 2) if vol_vals else None,
            "best_event": {"date": best_ev["t0_date"], "total_return_pct": best_ev["total_return_pct"]},
            "worst_event": {"date": worst_ev["t0_date"], "total_return_pct": worst_ev["total_return_pct"]},
        }

    # Build upcoming / future event tracker (earliest future date > latest market date)
    upcoming_event: Optional[dict[str, Any]] = None
    if upcoming_candidates:
        next_ev = sorted(upcoming_candidates, key=lambda e: e["date"])[0]
        next_ts = pd.Timestamp(next_ev["date"])
        cal_days_until = int((next_ts - latest_market_date).days)
        # Approximate trading sessions until event (business days excluding Sat/Sun)
        bdays = len(pd.bdate_range(latest_market_date + pd.Timedelta(days=1), next_ts))
        trading_days_until = max(1, bdays)

        live_trace: list[dict[str, Any]] = []
        current_pre_return = None
        if day_mode == "calendar":
            in_window = cal_days_until <= before_days
            if in_window:
                start_ts = next_ts - pd.Timedelta(days=before_days)
                start_pos = int(dates.searchsorted(start_ts, side="left"))
                live_win = df.iloc[start_pos:]
                if not live_win.empty:
                    base_c = float(live_win["Close"].iloc[0])
                    for dt, row in live_win.iterrows():
                        c_val = float(row["Close"])
                        live_trace.append(
                            {
                                "offset": int((dt - next_ts).days),
                                "date": dt.strftime("%Y-%m-%d"),
                                "close": _safe_round(c_val, 2),
                                "pct_change": _safe_round(_pct_return(base_c, c_val), 2),
                            }
                        )
                    current_pre_return = _safe_round(_pct_return(base_c, float(live_win["Close"].iloc[-1])), 2)
        else:
            in_window = trading_days_until <= before_days
            if in_window:
                sessions_elapsed = before_days - trading_days_until
                start_pos = max(0, len(dates) - 1 - sessions_elapsed)
                live_win = df.iloc[start_pos:]
                if not live_win.empty:
                    base_c = float(live_win["Close"].iloc[0])
                    n_live = len(live_win)
                    for idx_in_win, (dt, row) in enumerate(live_win.iterrows()):
                        c_val = float(row["Close"])
                        offset_val = -(trading_days_until + (n_live - 1 - idx_in_win))
                        live_trace.append(
                            {
                                "offset": offset_val,
                                "date": dt.strftime("%Y-%m-%d"),
                                "close": _safe_round(c_val, 2),
                                "pct_change": _safe_round(_pct_return(base_c, c_val), 2),
                            }
                        )
                    current_pre_return = _safe_round(_pct_return(base_c, float(live_win["Close"].iloc[-1])), 2)

        upcoming_event = {
            "event_date": next_ev["date"],
            "label": next_ev.get("label", next_ev.get("event_type", "Upcoming Event")),
            "source": next_ev.get("source", "NSE Event Calendar"),
            "calendar_days_until": cal_days_until,
            "trading_days_until": trading_days_until,
            "in_pre_window": len(live_trace) > 0,
            "current_pre_return_pct": current_pre_return,
            "trace": live_trace,
        }

    recommendations = _build_recommendations(
        summary=summary,
        analyzed_events=analyzed_events,
        before_days=before_days,
        after_days=after_days,
    )

    return {
        "events": analyzed_events,
        "average_trace": average_trace,
        "summary": summary,
        "recommendations": recommendations,
        "upcoming_event": upcoming_event,
    }


def _build_recommendations(
    summary: dict[str, Any],
    analyzed_events: list[dict[str, Any]],
    before_days: int,
    after_days: int,
) -> dict[str, Any]:
    """
    Generate historical data-driven buying/trading signals for:
    1) Regular (Cash / Equity Delivery)
    2) Futures & Options (F&O)
    Strictly derived from the analyzed event-study statistics.
    """
    if not summary or not analyzed_events:
        return {}

    n = summary.get("events_analyzed", 0)
    avg_pre = summary.get("avg_pre_return_pct") or 0.0
    pre_wr = summary.get("pre_win_rate_pct") or 0.0
    avg_post = summary.get("avg_post_return_pct") or 0.0
    post_wr = summary.get("post_win_rate_pct") or 0.0
    avg_tot = summary.get("avg_total_return_pct") or 0.0
    tot_wr = summary.get("total_win_rate_pct") or 0.0
    avg_alpha = summary.get("avg_total_alpha_pct")
    vol_surge = summary.get("avg_volume_surge_ratio") or 1.0

    abs_ev_moves = [abs(e["event_day_return_pct"]) for e in analyzed_events if e.get("event_day_return_pct") is not None]
    avg_abs_t0 = _safe_round(mean(abs_ev_moves), 2) if abs_ev_moves else 0.0

    drawdowns = [e["max_drawdown_pct"] for e in analyzed_events if e.get("max_drawdown_pct") is not None]
    avg_dd = _safe_round(mean(drawdowns), 2) if drawdowns else -3.0
    suggested_sl = round(min(-2.0, max(-12.0, (avg_dd or -3.0) * 1.1)), 1)

    # Confidence based on sample size & win-rate edge
    best_wr = max(pre_wr, post_wr, tot_wr)
    if n >= 6 and best_wr >= 70:
        confidence = "High"
    elif n >= 4 and best_wr >= 55:
        confidence = "Medium"
    else:
        confidence = "Low"

    # --- 1. Regular (Cash / Equity Delivery) ---
    if avg_tot >= 2.0 and tot_wr >= 60 and avg_pre > 0 and avg_post >= 0:
        reg_signal = "BUY & HOLD THROUGH EVENT"
        reg_bias = "Bullish"
        reg_entry = f"T-{before_days}"
        reg_exit = f"T+{after_days}"
        reg_reason = (
            f"Consistent full-window strength: avg {avg_tot:+.2f}% ({tot_wr:.0f}% win rate) "
            f"with positive pre-event ({avg_pre:+.2f}%) and post-event ({avg_post:+.2f}%) drift."
        )
    elif avg_pre >= 1.5 and pre_wr >= 60:
        reg_signal = "BUY PRE-EVENT RUN-UP"
        reg_bias = "Bullish (Pre-Event)"
        reg_entry = f"T-{before_days}"
        reg_exit = "T-1 / T0 (Before Announcement)"
        reg_reason = (
            f"Strong pre-event rally averaging {avg_pre:+.2f}% ({pre_wr:.0f}% win rate), "
            f"while post-event averages {avg_post:+.2f}% — better to book profit into T0."
        )
    elif avg_post >= 1.5 and post_wr >= 60:
        reg_signal = "BUY POST-EVENT DRIFT"
        reg_bias = "Bullish (Post-Event)"
        reg_entry = "T0 / T+1 (After Event)"
        reg_exit = f"T+{after_days}"
        reg_reason = (
            f"Stock tends to outperform after the event ({avg_post:+.2f}%, {post_wr:.0f}% win rate) "
            f"compared to pre-event ({avg_pre:+.2f}%). Wait for event clarity before entering."
        )
    elif avg_tot <= -1.5 and tot_wr <= 40:
        reg_signal = "AVOID / WAIT FOR DIP"
        reg_bias = "Bearish"
        reg_entry = "Stay in Cash"
        reg_exit = f"Re-evaluate after T+{after_days}"
        reg_reason = (
            f"Historically weak around this event (avg {avg_tot:+.2f}%, only {tot_wr:.0f}% positive). "
            f"Avoid fresh delivery buying until post-event dust settles."
        )
    else:
        reg_signal = "NEUTRAL / ACCUMULATE ON DIPS"
        reg_bias = "Neutral"
        reg_entry = "Staggered near support"
        reg_exit = f"T+{after_days}"
        reg_reason = (
            f"Mixed historical edge (Pre {avg_pre:+.2f}%, Post {avg_post:+.2f}%, Total {avg_tot:+.2f}%). "
            f"No strong one-sided seasonal pattern across the last {n} events."
        )

    if avg_alpha is not None:
        reg_reason += f" Avg Nifty 50 alpha: {avg_alpha:+.2f}%."

    # --- 2. Futures & Options (F&O) ---
    if avg_pre >= 2.0 and pre_wr >= 65:
        fo_signal = "LONG FUTURES / BULL CALL SPREAD"
        fo_bias = "Bullish"
        fo_entry = f"T-{before_days}"
        fo_exit = "T-1 (Exit before IV Crush)"
        fo_reason = (
            f"High-probability pre-event momentum ({avg_pre:+.2f}%, {pre_wr:.0f}% win rate). "
            f"Bull Call Spread caps theta/IV risk; exit before T0 to avoid post-event IV crush."
        )
    elif avg_pre <= -2.0 and pre_wr <= 35:
        fo_signal = "SHORT FUTURES / BEAR PUT SPREAD"
        fo_bias = "Bearish"
        fo_entry = f"T-{before_days}"
        fo_exit = "T-1 / T0"
        fo_reason = (
            f"Recurring pre-event weakness ({avg_pre:+.2f}%, {100 - pre_wr:.0f}% down-move rate). "
            f"Bear Put Spread defines max risk against sudden pre-event short covering."
        )
    elif avg_post >= 2.0 and post_wr >= 65:
        fo_signal = "POST-EVENT LONG CALL / FUTURES"
        fo_bias = "Bullish (Post-Event)"
        fo_entry = "T+1 (After IV Crush)"
        fo_exit = f"T+{after_days}"
        fo_reason = (
            f"Strong post-event follow-through ({avg_post:+.2f}%, {post_wr:.0f}% win rate). "
            f"Entering at T+1 benefits from cheaper post-event option premiums (IV crush)."
        )
    elif (avg_abs_t0 or 0.0) >= 2.2 or vol_surge >= 1.5:
        fo_signal = "LONG STRADDLE / STRANGLE (VOL PLAY)"
        fo_bias = "Volatile / Non-Directional"
        fo_entry = "T-5 to T-2"
        fo_exit = "T0 / T+1 Open"
        fo_reason = (
            f"Elevated event-day swing (avg |T0| move {avg_abs_t0:.2f}%, volume {vol_surge:.2f}x) "
            f"with mixed direction. Non-directional volatility play fits better than naked futures."
        )
    elif (avg_abs_t0 or 0.0) <= 1.2 and abs(avg_tot) <= 1.5:
        fo_signal = "IRON CONDOR / SHORT STRANGLE (IV CRUSH)"
        fo_bias = "Range-Bound"
        fo_entry = "T-2 / T-1"
        fo_exit = "T+1 / T+2"
        fo_reason = (
            f"Muted event-day reaction (avg |T0| move {avg_abs_t0:.2f}%) and tight range. "
            f"Defined-risk Iron Condor can harvest post-event implied volatility crush."
        )
    else:
        fo_signal = "NO TRADE / LIGHT HEDGED SPREAD"
        fo_bias = "Neutral"
        fo_entry = "Wait for Breakout"
        fo_exit = "Strict Stop-Loss"
        fo_reason = (
            f"No high-conviction F&O edge (Pre {avg_pre:+.2f}%, Post {avg_post:+.2f}%, "
            f"avg |T0| move {avg_abs_t0:.2f}%). Avoid leveraged directional bets."
        )

    return {
        "confidence": confidence,
        "sample_size": n,
        "regular": {
            "title": "Regular (Cash / Delivery)",
            "signal": reg_signal,
            "bias": reg_bias,
            "entry": reg_entry,
            "exit": reg_exit,
            "stop_loss_pct": suggested_sl,
            "reason": reg_reason,
        },
        "fo": {
            "title": "Futures & Options (F&O)",
            "signal": fo_signal,
            "bias": fo_bias,
            "entry": fo_entry,
            "exit": fo_exit,
            "avg_t0_abs_move_pct": avg_abs_t0,
            "stop_loss_pct": suggested_sl,
            "reason": fo_reason,
        },
        "disclaimer": "Auto-generated from historical event-study statistics for educational research only — not SEBI-registered investment advice.",
    }


STANDARD_RANGES = [
    (10, 5, "Short / F&O"),
    (20, 10, "Standard"),
    (30, 15, "Swing"),
    (45, 20, "Positional"),
]


def compute_range_comparison(
    price_df: pd.DataFrame,
    events: list[dict[str, str]],
    day_mode: str = "trading",
    max_events: int = 12,
) -> list[dict[str, Any]]:
    """Compare standard before/after windows so the user can see which range works best."""
    rows: list[dict[str, Any]] = []
    for b_days, a_days, style in STANDARD_RANGES:
        res = analyze_events(
            price_df=price_df,
            events=events,
            before_days=b_days,
            after_days=a_days,
            day_mode=day_mode,
            normalize_to="start",
            benchmark_df=None,
            max_events=max_events,
        )
        s = res.get("summary") or {}
        if not s.get("events_analyzed"):
            continue
        avg_pre = s.get("avg_pre_return_pct") or 0.0
        avg_post = s.get("avg_post_return_pct") or 0.0
        avg_tot = s.get("avg_total_return_pct") or 0.0
        tot_wr = s.get("total_win_rate_pct") or 0.0
        pre_wr = s.get("pre_win_rate_pct") or 0.0
        # Simple composite edge score combining return & consistency
        score = (avg_tot * (tot_wr / 100.0)) + (max(0.0, avg_pre) * (pre_wr / 100.0) * 0.5)
        rows.append(
            {
                "label": f"{b_days}/{a_days}",
                "before": b_days,
                "after": a_days,
                "style": style,
                "avg_pre_return_pct": s.get("avg_pre_return_pct"),
                "pre_win_rate_pct": s.get("pre_win_rate_pct"),
                "avg_post_return_pct": s.get("avg_post_return_pct"),
                "avg_total_return_pct": s.get("avg_total_return_pct"),
                "total_win_rate_pct": s.get("total_win_rate_pct"),
                "is_best": False,
                "_score": score,
            }
        )

    if rows:
        best_row = max(rows, key=lambda r: r["_score"])
        best_row["is_best"] = True
        for r in rows:
            r.pop("_score", None)

    return rows
