"""Read-time mainland exchange freshness; unknown calendars never imply freshness."""
import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from .conventions import SHANGHAI, parse_time


@lru_cache(maxsize=1)
def exchange_calendar():
    path = Path(__file__).resolve().parents[2] / "assets" / "cn-exchange-calendar-2026.json"
    return json.loads(path.read_text(encoding="utf-8"))


def expected_session(as_of=None):
    now = parse_time(as_of) if as_of else datetime.now(SHANGHAI)
    now = now.astimezone(SHANGHAI)
    calendar = exchange_calendar()
    day = now.date()
    if not calendar["coverage_start"] <= day.isoformat() <= calendar["coverage_end"]:
        return None
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        day -= timedelta(days=1)
    closed = set(calendar["closed_dates"])
    while day.weekday() >= 5 or day.isoformat() in closed:
        day -= timedelta(days=1)
    return day.isoformat() if day.isoformat() >= calendar["coverage_start"] else None


def quote_freshness(quote, as_of=None):
    now = parse_time(as_of) if as_of else datetime.now(SHANGHAI)
    now = now.astimezone(SHANGHAI)
    expected = expected_session(now.isoformat())
    if expected is None:
        return {"status": "unknown", "reason": "calendar_out_of_coverage"}
    try:
        observed = parse_time(quote["as_of"]).astimezone(SHANGHAI)
    except (ValueError, TypeError):
        return {"status": "unknown", "reason": "invalid_quote_timestamp"}
    if observed > now:
        return {"status": "unavailable", "reason": "observation_after_cutoff"}
    if observed.date().isoformat() != expected:
        return {"status": "stale", "reason": "wrong_exchange_session", "expected_session": expected}
    # Count only time during the two continuous trading windows, including lunch/after-close reads.
    if now.date() == observed.date():
        minutes = 0.0
        for start_hour, start_minute, end_hour, end_minute in ((9, 30, 11, 30), (13, 0, 15, 0)):
            start = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
            end = now.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
            minutes += max(0, (min(now, end) - max(observed, start)).total_seconds() / 60)
        if minutes > 20:
            return {"status": "stale", "reason": "quote_behind_trading_clock", "trading_minutes_behind": round(minutes, 1)}
    if quote.get("quality") in {"stale", "unavailable", "incomplete"}:
        return {"status": quote["quality"], "reason": "source_quality"}
    return {"status": "current_session", "expected_session": expected,
            "latency": quote.get("latency", "unknown")}
