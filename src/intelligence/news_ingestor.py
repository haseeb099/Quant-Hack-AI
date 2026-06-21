"""News headline ingestion with fixture and NewsAPI sources."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.intelligence.models import NewsItem

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class NewsIngestor:
    """Fetches and caches news headlines per symbol."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        news_cfg = config.get("news", {})
        self.max_headlines = int(news_cfg.get("max_headlines_per_symbol", 20))
        self.lookback_hours = int(news_cfg.get("lookback_hours", 4))
        self.source = news_cfg.get("source", "fixture")
        self.newsapi_base = news_cfg.get("newsapi_base_url", "https://newsapi.org/v2/everything")
        self.symbol_queries: dict[str, list[str]] = config.get("symbol_queries", {})
        self.cache_dir = Path(config.get("cache_dir", "data/intelligence"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_path = self.cache_dir / "news_cache.jsonl"
        self._headlines: dict[str, list[NewsItem]] = {}
        self._last_refresh: datetime | None = None

    def _fixture_headlines(self, symbol: str) -> list[NewsItem]:
        now = _utc_now()
        fixtures: dict[str, list[tuple[str, str]]] = {
            "BTC/USD": [
                ("Bitcoin holds above key support as ETF inflows steady", "CoinDesk"),
                ("Crypto regulation talks weigh on risk appetite", "Reuters"),
                ("BTC volatility rises ahead of US CPI data", "Bloomberg"),
            ],
            "XAU/USD": [
                ("Gold edges higher on safe-haven demand", "Kitco"),
                ("Fed rate outlook supports bullion", "Reuters"),
                ("XAU tests resistance as dollar softens", "FXStreet"),
            ],
            "EUR/USD": [
                ("Euro steady ahead of ECB decision", "Reuters"),
                ("EUR/USD range-bound in London session", "DailyFX"),
            ],
        }
        items = fixtures.get(symbol, [
            (f"{symbol} consolidates in low-volatility session", "MarketWatch"),
            (f"Traders await macro catalyst for {symbol}", "Reuters"),
        ])
        out: list[NewsItem] = []
        for i, (title, source) in enumerate(items):
            out.append(NewsItem(
                title=title,
                source=source,
                url=f"https://example.com/news/{symbol.replace('/', '-')}/{i}",
                published_at=(now - timedelta(minutes=30 * (i + 1))).isoformat(),
                symbol=symbol,
            ))
        return out

    def _fetch_newsapi(self, symbol: str) -> list[NewsItem]:
        api_key = os.getenv("NEWS_API_KEY", "").strip()
        if not api_key:
            return self._fixture_headlines(symbol)

        queries = self.symbol_queries.get(symbol, [symbol.split("/")[0]])
        query = " OR ".join(queries[:3])
        from_dt = (_utc_now() - timedelta(hours=self.lookback_hours)).strftime("%Y-%m-%dT%H:%M:%S")
        params = urllib.parse.urlencode({
            "q": query,
            "from": from_dt,
            "sortBy": "publishedAt",
            "pageSize": str(self.max_headlines),
            "language": "en",
            "apiKey": api_key,
        })
        url = f"{self.newsapi_base}?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            logger.warning("NewsAPI fetch failed for %s: %s", symbol, exc)
            return self._fixture_headlines(symbol)

        articles = data.get("articles", [])
        out: list[NewsItem] = []
        for article in articles[: self.max_headlines]:
            title = (article.get("title") or "").strip()
            if not title or title == "[Removed]":
                continue
            out.append(NewsItem(
                title=title,
                source=(article.get("source") or {}).get("name", "unknown"),
                url=article.get("url", ""),
                published_at=article.get("publishedAt", _utc_now().isoformat()),
                symbol=symbol,
            ))
        return out or self._fixture_headlines(symbol)

    def _append_cache(self, items: list[NewsItem]) -> None:
        with open(self.cache_path, "a", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps({
                    "title": item.title,
                    "source": item.source,
                    "url": item.url,
                    "published_at": item.published_at,
                    "symbol": item.symbol,
                }) + "\n")

    def refresh(self, symbols: list[str], force: bool = False) -> dict[str, list[NewsItem]]:
        now = _utc_now()
        if (
            not force
            and self._last_refresh
            and (now - self._last_refresh).total_seconds() < 300
        ):
            return self._headlines

        result: dict[str, list[NewsItem]] = {}
        for symbol in symbols:
            if self.source == "newsapi":
                items = self._fetch_newsapi(symbol)
            else:
                items = self._fixture_headlines(symbol)
            result[symbol] = items[: self.max_headlines]
            self._append_cache(result[symbol])

        self._headlines = result
        self._last_refresh = now
        logger.info("News refreshed for %d symbols", len(result))
        return result

    def get_headlines(self, symbol: str) -> list[NewsItem]:
        return self._headlines.get(symbol, [])
