"""Dashboard bearer-token authentication helpers."""

from __future__ import annotations

import os

WS_AUTH_PROTOCOL = "quantai-dashboard"


def dashboard_auth_token() -> str:
    return os.getenv("DASHBOARD_AUTH_TOKEN", "").strip()


def extract_bearer_token(authorization: str) -> str:
    return authorization.removeprefix("Bearer ").strip() if authorization else ""


def token_from_request(
    *,
    authorization: str = "",
    query_token: str = "",
    header_token: str = "",
    subprotocols: list[str] | None = None,
) -> str:
    """Resolve client token from headers, query (legacy), or WebSocket subprotocol."""
    if authorization:
        token = extract_bearer_token(authorization)
        if token:
            return token
    if header_token:
        return header_token.strip()
    if query_token:
        return query_token.strip()
    if subprotocols:
        for proto in subprotocols:
            candidate = proto.strip()
            if candidate and candidate != WS_AUTH_PROTOCOL:
                return candidate
    return ""


def is_dashboard_authorized(
    *,
    authorization: str = "",
    query_token: str = "",
    header_token: str = "",
    subprotocols: list[str] | None = None,
) -> bool:
    expected = dashboard_auth_token()
    if not expected:
        return True
    supplied = token_from_request(
        authorization=authorization,
        query_token=query_token,
        header_token=header_token,
        subprotocols=subprotocols,
    )
    return supplied == expected
