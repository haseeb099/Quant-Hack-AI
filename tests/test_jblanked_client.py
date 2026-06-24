"""Tests for JBlanked API client."""

from __future__ import annotations

import json

from src.intelligence.jblanked_client import fetch_jblanked_events, jblanked_headers


def test_jblanked_headers_match_docs() -> None:
    headers = jblanked_headers("test-key")
    assert headers["Authorization"] == "Api-Key test-key"
    assert headers["Content-Type"] == "application/json"
    assert "User-Agent" in headers


def test_fetch_jblanked_events_parses_list(monkeypatch) -> None:
    sample = [{"Name": "CPI", "Currency": "USD", "Date": "2026.06.22 13:30:00"}]

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(sample).encode()

    monkeypatch.setattr(
        "src.intelligence.jblanked_client.urllib.request.urlopen",
        lambda *args, **kwargs: FakeResponse(),
    )

    events = fetch_jblanked_events(api_key="test-key-with-enough-length")
    assert events == sample
