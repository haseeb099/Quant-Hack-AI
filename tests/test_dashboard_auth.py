"""Dashboard authentication tests."""

from __future__ import annotations

import pytest

from src.web.auth import WS_AUTH_PROTOCOL, is_dashboard_authorized


def test_dashboard_auth_accepts_bearer_header(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "secret-token")
    assert is_dashboard_authorized(authorization="Bearer secret-token")


def test_dashboard_auth_accepts_ws_subprotocol(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "secret-token")
    assert is_dashboard_authorized(
        subprotocols=[WS_AUTH_PROTOCOL, "secret-token"],
    )


def test_dashboard_auth_rejects_missing_token_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "secret-token")
    assert not is_dashboard_authorized()


def test_dashboard_auth_open_when_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("DASHBOARD_AUTH_TOKEN", raising=False)
    assert is_dashboard_authorized()
