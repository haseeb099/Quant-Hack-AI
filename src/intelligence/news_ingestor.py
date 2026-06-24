"""News headline ingestion with fixture, NewsAPI, and JBlanked sources."""

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

from src.intelligence.jblanked_client import (
    fetch_jblanked_events,
    jblanked_api_key,
    parse_jblanked_date,
)
from src.intelligence.models import NewsItem
from src.intelligence.rapidapi_client import fetch_yahoo_news, parse_yahoo_pub_date, rapidapi_key

logger = logging.getLogger(__name__)

_CRYPTO_SYMBOLS = {"BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BAR/USD"}
_METAL_SYMBOLS = {"XAU/USD", "XAG/USD"}
_SECTOR_QUERIES: dict[str, list[str]] = {
    "crypto": [
        "bitcoin", "crypto", "cryptocurrency", "ethereum", "blockchain", "defi", "token",
    ],
    "forex": [
        "dollar", "euro", "fed", "ecb", "forex", "currency", "interest rate", "central bank",
    ],
    "metals": ["gold", "silver", "precious", "bullion", "xau", "xag"],
}


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
        self.live_mode = bool(config.get("live_mode", False))
        self.newsapi_base = news_cfg.get("newsapi_base_url", "https://newsapi.org/v2/everything")
        self.jblanked_base = news_cfg.get(
            "jblanked_base_url", "https://www.jblanked.com/news/api"
        ).rstrip("/")
        self.jblanked_source = news_cfg.get("jblanked_source", "mql5")
        self.jblanked_mode = news_cfg.get("jblanked_mode", "calendar")
        self.rapidapi_yahoo_region = news_cfg.get("rapidapi_yahoo_region", "US")
        self.rapidapi_yahoo_snippet_count = int(news_cfg.get("rapidapi_yahoo_snippet_count", 500))
        self.symbol_queries: dict[str, list[str]] = config.get("symbol_queries", {})
        self.currency_symbols: dict[str, list[str]] = config.get("currency_symbols", {})
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
            "ETH/USD": [
                ("Ethereum network activity rises as DeFi volumes recover", "CoinDesk"),
                ("ETH holds support amid broader crypto consolidation", "Reuters"),
                ("Ethereum ETF speculation drives institutional interest", "Bloomberg"),
            ],
            "SOL/USD": [
                ("Solana ecosystem growth boosts SOL trading volumes", "The Block"),
                ("SOL rebounds after network upgrade completes smoothly", "CoinTelegraph"),
                ("Solana developers report rising daily active addresses", "Decrypt"),
            ],
            "XRP/USD": [
                ("XRP legal clarity hopes lift ripple-linked tokens", "Reuters"),
                ("XRP trading volume spikes on exchange listing news", "CoinDesk"),
                ("Ripple payment corridor expansion supports XRP demand", "Bloomberg"),
            ],
            "BAR/USD": [
                ("Altcoin BAR gains on niche exchange liquidity push", "CryptoNews"),
                ("BAR token holders watch macro risk for crypto beta", "MarketWatch"),
                ("BAR consolidates as traders await sector catalyst", "CoinTelegraph"),
            ],
            "XAU/USD": [
                ("Gold edges higher on safe-haven demand", "Kitco"),
                ("Fed rate outlook supports bullion", "Reuters"),
                ("XAU tests resistance as dollar softens", "FXStreet"),
            ],
            "EUR/USD": [
                ("Euro steady ahead of ECB decision", "Reuters"),
                ("EUR/USD range-bound in London session", "DailyFX"),
                ("Eurozone PMI data keeps EUR/USD in tight range", "FXStreet"),
            ],
        }
        items = fixtures.get(symbol, [
            (f"{symbol} holds steady in tight range ahead of data", "MarketWatch"),
            (f"Traders await macro catalyst for {symbol}", "Reuters"),
            (f"{symbol} range-bound with muted session flows", "Bloomberg"),
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
            if self.source == "newsapi":
                logger.warning(
                    "NewsAPI key missing — using fixture headlines for %s until NEWS_API_KEY is set",
                    symbol,
                )
                return self._fixture_headlines(symbol)
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
            logger.warning("NewsAPI fetch failed for %s: %s — using fixture headlines", symbol, exc)
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
        if not out:
            logger.warning("NewsAPI returned no articles for %s — using fixture headlines", symbol)
            return self._fixture_headlines(symbol)
        return out

    def _jblanked_api_key(self) -> str:
        return jblanked_api_key()

    def _parse_jblanked_date(self, value: str) -> str:
        return parse_jblanked_date(value)

    def _symbol_currencies(self, symbol: str) -> set[str]:
        parts = symbol.split("/")
        if len(parts) == 2:
            return {parts[0].upper(), parts[1].upper()}
        return {parts[0].upper()}

    def _jblanked_event_title(self, event: dict) -> str:
        currency = (event.get("Currency") or "").strip()
        name = (event.get("Name") or "Economic event").strip()
        title = f"{currency}: {name}" if currency else name
        impact = (event.get("Impact") or "").strip()
        if impact and impact.lower() not in ("none", "n/a"):
            title = f"{title} ({impact} impact)"
        actual = event.get("Actual")
        forecast = event.get("Forecast")
        if actual not in (None, "", "N/A") and forecast not in (None, "", "N/A"):
            title = f"{title} — Actual {actual} vs Forecast {forecast}"
        return title

    def _jblanked_get(self, path: str) -> list[dict] | None:
        source = self.jblanked_source
        if path.endswith("/list/") or "list" in path:
            mode = "list"
        else:
            mode = "calendar"
        return fetch_jblanked_events(
            source=source,
            mode=mode,
            base_url=self.jblanked_base,
            api_key=self._jblanked_api_key(),
        )

    def _fetch_jblanked_events(self) -> list[dict] | None:
        mode = "list" if self.jblanked_mode == "list" else "calendar"
        return fetch_jblanked_events(
            source=self.jblanked_source,
            mode=mode,
            base_url=self.jblanked_base,
            api_key=self._jblanked_api_key(),
        )

    def _events_for_symbol(self, events: list[dict], symbol: str) -> list[dict]:
        currencies = self._symbol_currencies(symbol)
        matched = [
            event for event in events
            if (event.get("Currency") or "").upper() in currencies
        ]
        if matched:
            return matched

        for currency, symbols in self.currency_symbols.items():
            if symbol in symbols:
                return [
                    event for event in events
                    if (event.get("Currency") or "").upper() == currency.upper()
                ]
        return []

    def _jblanked_events_to_items(self, events: list[dict], symbol: str) -> list[NewsItem]:
        out: list[NewsItem] = []
        for event in events[: self.max_headlines]:
            title = self._jblanked_event_title(event)
            if not title:
                continue
            published_at = self._parse_jblanked_date(
                str(event.get("Date") or _utc_now().isoformat())
            )
            out.append(NewsItem(
                title=title,
                source=f"JBlanked/{self.jblanked_source}",
                url=f"https://www.jblanked.com/news/api/{self.jblanked_source}/list/",
                published_at=published_at,
                symbol=symbol,
                category=(event.get("Category") or ""),
            ))
        return out

    def _headline_matches_symbol(self, title: str, summary: str, symbol: str) -> bool:
        text = f"{title} {summary}".lower()
        queries = self.symbol_queries.get(symbol, [])
        if not queries:
            base = symbol.split("/")[0].lower()
            return base in text
        return any(q.lower() in text for q in queries)

    def _sector_for_symbol(self, symbol: str) -> str | None:
        if symbol in _CRYPTO_SYMBOLS:
            return "crypto"
        if symbol in _METAL_SYMBOLS:
            return "metals"
        if "/" in symbol:
            return "forex"
        return None

    def _headline_matches_sector(self, title: str, summary: str, sector: str) -> bool:
        text = f"{title} {summary}".lower()
        queries = _SECTOR_QUERIES.get(sector, [])
        return any(q.lower() in text for q in queries)

    def _filter_yahoo_headlines(
        self,
        symbol: str,
        headlines: list[dict],
        *,
        allow_sector_fallback: bool = True,
    ) -> tuple[list[NewsItem], dict[str, int]]:
        """Filter Yahoo headlines for a symbol; optionally fall back to sector matches."""
        cutoff = _utc_now() - timedelta(hours=self.lookback_hours)
        stats = {"raw": len(headlines), "symbol_match": 0, "after_lookback": 0, "sector_match": 0}

        def _to_item(item: dict) -> NewsItem | None:
            title = (item.get("title") or "").strip()
            if not title:
                return None
            published_at = parse_yahoo_pub_date(item.get("published_at"))
            try:
                if datetime.fromisoformat(published_at.replace("Z", "+00:00")) < cutoff:
                    return None
            except ValueError:
                pass
            return NewsItem(
                title=title,
                source=item.get("source") or "Yahoo Finance",
                url=item.get("url") or "",
                published_at=published_at,
                symbol=symbol,
            )

        out: list[NewsItem] = []
        for item in headlines:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            summary = (item.get("summary") or "").strip()
            if not self._headline_matches_symbol(title, summary, symbol):
                continue
            stats["symbol_match"] += 1
            news_item = _to_item(item)
            if news_item is None:
                continue
            stats["after_lookback"] += 1
            out.append(news_item)
            if len(out) >= self.max_headlines:
                break

        if not out and allow_sector_fallback:
            sector = self._sector_for_symbol(symbol)
            if sector:
                for item in headlines:
                    title = (item.get("title") or "").strip()
                    if not title:
                        continue
                    summary = (item.get("summary") or "").strip()
                    if not self._headline_matches_sector(title, summary, sector):
                        continue
                    stats["sector_match"] += 1
                    news_item = _to_item(item)
                    if news_item is None:
                        continue
                    out.append(news_item)
                    if len(out) >= self.max_headlines:
                        break

        return out, stats

    def _fetch_rapidapi_yahoo(self, symbol: str, cached_headlines: list[dict] | None) -> list[NewsItem]:
        if not rapidapi_key():
            logger.warning(
                "RapidAPI key missing — using fixture headlines for %s until RAPIDAPI_KEY is set",
                symbol,
            )
            return self._fixture_headlines(symbol)

        headlines = cached_headlines if cached_headlines is not None else fetch_yahoo_news(
            region=self.rapidapi_yahoo_region,
            snippet_count=self.rapidapi_yahoo_snippet_count,
        )
        if not headlines:
            logger.warning("RapidAPI Yahoo news empty for %s — using fixture headlines", symbol)
            return self._fixture_headlines(symbol)

        items, stats = self._filter_yahoo_headlines(symbol, headlines)
        logger.info(
            "News filter %s: raw=%d symbol_match=%d after_lookback=%d sector_match=%d kept=%d",
            symbol,
            stats["raw"],
            stats["symbol_match"],
            stats["after_lookback"],
            stats["sector_match"],
            len(items),
        )

        if not items:
            if self.live_mode:
                return []
            logger.warning(
                "RapidAPI Yahoo returned no matching headlines for %s — using fixture headlines",
                symbol,
            )
            return self._fixture_headlines(symbol)
        return items

    def _fetch_jblanked(self, symbol: str, cached_events: list[dict] | None) -> list[NewsItem]:
        api_key = self._jblanked_api_key()
        if not api_key:
            logger.warning(
                "JBlanked API key missing — using fixture headlines for %s until "
                "JBLANKED_API_KEY or NEWS_API_KEY is set",
                symbol,
            )
            return self._fixture_headlines(symbol)

        events = cached_events if cached_events is not None else self._fetch_jblanked_events()
        if events is None:
            logger.warning("JBlanked fetch failed for %s — using fixture headlines", symbol)
            return self._fixture_headlines(symbol)

        symbol_events = self._events_for_symbol(events, symbol)
        items = self._jblanked_events_to_items(symbol_events, symbol)
        if not items:
            if self.live_mode and events is not None:
                return []
            logger.warning("JBlanked returned no events for %s — using fixture headlines", symbol)
            return self._fixture_headlines(symbol)
        return items

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
        jblanked_events: list[dict] | None = None
        yahoo_headlines: list[dict] | None = None
        if self.source == "jblanked":
            jblanked_events = self._fetch_jblanked_events()
        elif self.source in ("rapidapi_yahoo", "rapidapi"):
            yahoo_headlines = fetch_yahoo_news(
                region=self.rapidapi_yahoo_region,
                snippet_count=self.rapidapi_yahoo_snippet_count,
            )

        for symbol in symbols:
            if self.source == "newsapi":
                items = self._fetch_newsapi(symbol)
            elif self.source == "jblanked":
                items = self._fetch_jblanked(symbol, jblanked_events)
            elif self.source in ("rapidapi_yahoo", "rapidapi"):
                items = self._fetch_rapidapi_yahoo(symbol, yahoo_headlines)
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
