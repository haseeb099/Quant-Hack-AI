"""RapidAPI finance clients — Yahoo news, Forex Factory calendar, company cash flow."""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

DEFAULT_YAHOO_HOST = "yahoo-finance166.p.rapidapi.com"
DEFAULT_FOREX_FACTORY_HOST = "forex-factory-scraper1.p.rapidapi.com"
DEFAULT_FINANCE_HOST = "real-time-finance-data.p.rapidapi.com"
DEFAULT_FOREX_FACTORY_TIMEZONE = "GMT-06:00 Central Time (US & Canada)"


def rapidapi_key() -> str:
    return os.getenv("RAPIDAPI_KEY", "").strip()


def parse_yahoo_pub_date(value: Any) -> str:
    """Normalize Yahoo/RapidAPI publication timestamps to UTC ISO."""
    if value is None or value == "":
        return datetime.now(timezone.utc).isoformat()

    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    text = str(value).strip()
    if text.isdigit():
        ts = float(text)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).astimezone(timezone.utc).isoformat()
    except ValueError:
        pass

    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(text).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        pass

    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except ValueError:
            continue

    logger.debug("Could not parse Yahoo pubDate %r — using now", text[:80])
    return datetime.now(timezone.utc).isoformat()


def rapidapi_headers(host: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "x-rapidapi-host": host,
        "x-rapidapi-key": rapidapi_key(),
    }


def _get_json(url: str, *, host: str, timeout: float = 20.0) -> Any | None:
    key = rapidapi_key()
    if not key:
        return None
    req = urllib.request.Request(url, headers=rapidapi_headers(host))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode()[:300]
        except Exception:
            pass
        logger.warning("RapidAPI HTTP %s (%s): %s", exc.code, host, body or exc.reason)
        return None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("RapidAPI fetch failed (%s): %s", host, exc)
        return None


def fetch_yahoo_news(
    *,
    region: str | None = None,
    snippet_count: int | None = None,
    host: str | None = None,
) -> list[dict[str, Any]]:
    """Return normalized Yahoo Finance headlines from RapidAPI."""
    host = host or os.getenv("RAPIDAPI_YAHOO_HOST", DEFAULT_YAHOO_HOST)
    region = region or os.getenv("RAPIDAPI_YAHOO_REGION", "US")
    snippet_count = snippet_count or int(os.getenv("RAPIDAPI_YAHOO_SNIPPET_COUNT", "500"))
    params = urllib.parse.urlencode({
        "snippetCount": str(snippet_count),
        "region": region,
    })
    url = f"https://{host}/api/news/list?{params}"
    data = _get_json(url, host=host)
    if not isinstance(data, dict):
        return []

    stream = (
        data.get("data", {})
        .get("ntk", {})
        .get("stream", [])
    )
    headlines: list[dict[str, Any]] = []
    for item in stream:
        if not isinstance(item, dict):
            continue
        editorial = item.get("editorialContent") or {}
        content = editorial.get("content") or editorial
        title = (content.get("title") or editorial.get("title") or "").strip()
        if not title:
            continue
        published = (
            content.get("pubDate")
            or content.get("displayTime")
            or editorial.get("publishTime")
            or ""
        )
        provider = content.get("provider") or {}
        click_url = content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
        headlines.append({
            "title": title,
            "source": provider.get("displayName") or "Yahoo Finance",
            "url": click_url.get("url", "") if isinstance(click_url, dict) else str(click_url or ""),
            "published_at": parse_yahoo_pub_date(published),
            "summary": content.get("summary") or "",
        })
    logger.info("RapidAPI Yahoo news: %d raw headlines fetched", len(headlines))
    return headlines


def _forex_factory_timezone() -> str:
    return os.getenv("RAPIDAPI_FOREX_FACTORY_TIMEZONE", DEFAULT_FOREX_FACTORY_TIMEZONE)


def _forex_factory_time_format() -> str:
    return os.getenv("RAPIDAPI_FOREX_FACTORY_TIME_FORMAT", "12h").strip().lower()


def _parse_forex_factory_datetime(date_str: str, time_str: str) -> str:
    """Parse Forex Factory date/time into UTC ISO."""
    date_str = (date_str or "").strip()
    time_str = (time_str or "").strip().lower()
    if not date_str:
        return datetime.now(timezone.utc).isoformat()

    tz_label = _forex_factory_timezone()
    offset_hours = _timezone_offset_hours(tz_label)
    tz = timezone(timedelta(hours=offset_hours))

    time_format = _forex_factory_time_format()
    dt: datetime | None = None
    for fmt in (
        ("%Y-%m-%d %I:%M%p", time_format == "12h"),
        ("%Y-%m-%d %H:%M", time_format == "24h"),
        ("%Y-%m-%d %I:%M %p", time_format == "12h"),
    ):
        if not fmt[1]:
            continue
        try:
            dt = datetime.strptime(f"{date_str} {time_str}", fmt[0]).replace(tzinfo=tz)
            break
        except ValueError:
            continue

    if dt is None:
        try:
            base = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=tz)
            dt = base
        except ValueError:
            return datetime.now(timezone.utc).isoformat()

    return dt.astimezone(timezone.utc).isoformat()


def _timezone_offset_hours(label: str) -> int:
    match = re.search(r"GMT([+-]\d{1,2}):?\d{0,2}", label or "")
    if match:
        return int(match.group(1))
    # Competition default: London summer time if label mentions BST/ London
    lowered = (label or "").lower()
    if "london" in lowered or "british" in lowered:
        return 1
    return -6


def forex_factory_impact_tier(impact: str) -> str:
    level = (impact or "").strip().lower()
    if "high" in level:
        return "tier_1"
    if "medium" in level:
        return "tier_2"
    if "holiday" in level or "non-economic" in level or "bank" in level:
        return "tier_3"
    return "tier_3"


def fetch_forex_factory_calendar(
    *,
    day: datetime | None = None,
    host: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch economic calendar events for a single day."""
    host = host or os.getenv("RAPIDAPI_FOREX_FACTORY_HOST", DEFAULT_FOREX_FACTORY_HOST)
    day = day or datetime.now(timezone.utc)
    params = urllib.parse.urlencode({
        "year": str(day.year),
        "month": str(day.month),
        "day": str(day.day),
        "currency": "ALL",
        "event_name": "ALL",
        "timezone": _forex_factory_timezone(),
        "time_format": _forex_factory_time_format(),
    })
    url = f"https://{host}/get_calendar_details?{params}"
    data = _get_json(url, host=host, timeout=30.0)
    if isinstance(data, dict) and data.get("success") is False:
        logger.warning("Forex Factory API error: %s", data.get("detail") or data.get("error_code"))
        return []
    if not isinstance(data, list):
        return []
    return data


def fetch_forex_factory_calendar_window(
    *,
    days_ahead: int = 1,
    host: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch today and upcoming calendar days."""
    now = datetime.now(ZoneInfo("UTC"))
    events: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for offset in range(max(days_ahead, 0) + 1):
        day = now + timedelta(days=offset)
        for raw in fetch_forex_factory_calendar(day=day, host=host):
            key = (
                str(raw.get("date") or ""),
                str(raw.get("time") or ""),
                str(raw.get("name") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            events.append(raw)
    return events


def parse_forex_factory_event(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": (item.get("name") or "Economic event").strip(),
        "currency": (item.get("currency") or "").strip().upper(),
        "impact": forex_factory_impact_tier(str(item.get("impact") or "")),
        "scheduled_at": _parse_forex_factory_datetime(
            str(item.get("date") or ""),
            str(item.get("time") or ""),
        ),
        "actual": str(item.get("actual") or ""),
        "forecast": str(item.get("forecast") or ""),
        "previous": str(item.get("previous") or ""),
    }


def fetch_company_cash_flow(
    *,
    symbol: str | None = None,
    period: str | None = None,
    host: str | None = None,
) -> dict[str, Any] | None:
    """Fetch latest company cash-flow statement (macro context only — not pricing)."""
    host = host or os.getenv("RAPIDAPI_FINANCE_HOST", DEFAULT_FINANCE_HOST)
    symbol = symbol or os.getenv("RAPIDAPI_FINANCE_CASH_FLOW_SYMBOL", "AAPL:NASDAQ")
    period = period or os.getenv("RAPIDAPI_FINANCE_CASH_FLOW_PERIOD", "QUARTERLY")
    params = urllib.parse.urlencode({
        "symbol": symbol,
        "period": period,
        "language": "en",
    })
    url = f"https://{host}/company-cash-flow?{params}"
    data = _get_json(url, host=host)
    if not isinstance(data, dict) or data.get("status") != "OK":
        return None
    payload = data.get("data")
    return payload if isinstance(payload, dict) else None


def cash_flow_macro_notes(payload: dict[str, Any]) -> str:
    """Summarize cash-flow trend for macro overlay notes."""
    rows = payload.get("cash_flow") or []
    if not rows:
        return ""
    latest = rows[0]
    symbol = payload.get("symbol") or "equity"
    fcf = latest.get("free_cash_flow")
    ops = latest.get("cash_from_operations")
    if fcf is None and ops is None:
        return f"{symbol} cash-flow data available"
    parts = [f"{symbol} FCF {fcf:,}" if fcf is not None else None]
    if ops is not None:
        parts.append(f"operating cash {ops:,}")
    if len(rows) > 1:
        prev_fcf = rows[1].get("free_cash_flow")
        if fcf is not None and prev_fcf not in (None, 0):
            change_pct = ((fcf - prev_fcf) / abs(prev_fcf)) * 100
            parts.append(f"QoQ FCF {change_pct:+.1f}%")
    return " — ".join(p for p in parts if p)
