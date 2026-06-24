"""JBlanked News API client — https://www.jblanked.com/news/api/docs/"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://www.jblanked.com/news/api"
DEFAULT_USER_AGENT = "QuantAI/1.0 (Model-To-Market; Python)"


def jblanked_api_key() -> str:
    return (
        os.getenv("JBLANKED_API_KEY", "").strip()
        or os.getenv("NEWS_API_KEY", "").strip()
    )


def jblanked_headers(api_key: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Api-Key {api_key}",
        "Accept": "application/json",
        "User-Agent": os.getenv("JBLANKED_USER_AGENT", DEFAULT_USER_AGENT),
    }


def fetch_jblanked_events(
    *,
    source: str = "mql5",
    mode: str = "calendar",
    base_url: str = DEFAULT_BASE_URL,
    api_key: str | None = None,
) -> list[dict] | None:
    """Fetch calendar/list events. Returns None on HTTP failure, [] on empty success."""
    key = api_key or jblanked_api_key()
    if not key:
        return None

    if mode == "list":
        path = f"{source}/list/"
    else:
        path = f"{source}/calendar/today/"

    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    req = urllib.request.Request(url, headers=jblanked_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode()[:200]
        except Exception:
            pass
        logger.warning(
            "JBlanked HTTP %s for %s: %s",
            exc.code,
            path,
            body or exc.reason,
        )
        return None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("JBlanked fetch failed (%s): %s", path, exc)
        return None

    if isinstance(data, list):
        return data
    logger.warning("JBlanked unexpected payload for %s: %s", path, type(data).__name__)
    return None


def parse_jblanked_date(value: str) -> str:
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return datetime.now(timezone.utc).isoformat()


def jblanked_impact_tier(impact: str) -> str:
    level = (impact or "").strip().lower()
    if level == "high":
        return "tier_1"
    if level == "medium":
        return "tier_2"
    return "tier_3"
