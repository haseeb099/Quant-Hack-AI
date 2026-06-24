"""Attach to an already-running MT5 terminal without forcing a second login."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MT5Credentials:
    login: int | None
    password: str | None
    server: str | None
    path: str | None


def _strip_env_quotes(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_mt5_credentials() -> MT5Credentials:
    login_raw = os.getenv("MT5_LOGIN")
    login = int(login_raw) if login_raw else None
    password = _strip_env_quotes(os.getenv("MT5_PASSWORD"))
    server = _strip_env_quotes(os.getenv("MT5_SERVER"))
    path = _strip_env_quotes(os.getenv("MT5_PATH"))
    return MT5Credentials(login=login, password=password, server=server, path=path)


def normalize_server(server: str | None) -> str | None:
    if not server:
        return None
    return server.strip()


def server_candidates(server: str | None) -> list[str]:
    """Return server strings to try for mt5.login(), most likely first."""
    normalized = normalize_server(server)
    if not normalized:
        return []
    candidates = [normalized]
    if ":" in normalized:
        host_only = normalized.rsplit(":", 1)[0]
        if host_only and host_only not in candidates:
            candidates.append(host_only)
    return candidates


def account_matches(acc: Any, login: int | None) -> bool:
    if acc is None or login is None:
        return False
    return int(getattr(acc, "login", 0)) == int(login)


def _format_account(acc: Any) -> str:
    if acc is None:
        return "none"
    return f"{getattr(acc, 'login', '?')}@{getattr(acc, 'server', '?')}"


def _login_server_candidates(server: str | None) -> list[str | None]:
    try:
        from src.integrations.mt5_config import server_candidates_from_profile

        candidates = server_candidates_from_profile(server)
    except Exception:
        candidates = server_candidates(server)
    return candidates or [None]


def _try_login(mt5: Any, login: int, password: str, server: str | None) -> tuple[bool, str]:
    for candidate in _login_server_candidates(server):
        kwargs: dict[str, Any] = {"login": login, "password": password}
        if candidate:
            kwargs["server"] = candidate
        if mt5.login(**kwargs):
            acc = mt5.account_info()
            return True, f"Logged in as {_format_account(acc)}"
        last = mt5.last_error()
        if candidate:
            continue
        return False, f"Login failed: {last}"
    return False, f"Login failed for all server values: {mt5.last_error()}"


def ensure_mt5_session(*, require_login: bool = True, auto_enable_api: bool = True) -> tuple[bool, str]:
    """Connect to MT5 without launching a duplicate terminal login.

    Order of attempts:
    1. Attach to the first running terminal (no path, no credentials in initialize).
    2. If already logged in with MT5_LOGIN, reuse that session.
    3. If logged in as a different account, call mt5.login() only when credentials are set.
    4. If no terminal is running, start MT5 via MT5_PATH without passing login to initialize.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return False, "MetaTrader5 package not installed"

    if auto_enable_api:
        try:
            from src.integrations.mt5_config import ensure_mt5_api_enabled, read_mt5_profile

            profile = read_mt5_profile()
            if not profile.get("api_enabled"):
                _, api_detail = ensure_mt5_api_enabled()
                return False, (
                    f"{api_detail} "
                    "This blocks the Python API with 'Authorization failed'. "
                    "Restart MT5, ensure account is logged in, then retry."
                )
        except Exception:
            pass

    creds = load_mt5_credentials()

    if mt5.initialize():
        acc = mt5.account_info()
        if account_matches(acc, creds.login):
            return True, f"Reusing running terminal ({_format_account(acc)})"
        if acc is not None and creds.login is None:
            return True, f"Attached to running terminal ({_format_account(acc)})"
        if acc is not None and not require_login:
            return True, f"Attached to running terminal ({_format_account(acc)})"
        if acc is not None and creds.login and creds.password:
            ok, detail = _try_login(mt5, creds.login, creds.password, creds.server)
            if ok:
                return True, detail
            return False, (
                f"Terminal is logged in as {_format_account(acc)} but switching to "
                f"{creds.login} failed: {detail}"
            )
        if acc is None and creds.login and creds.password:
            ok, detail = _try_login(mt5, creds.login, creds.password, creds.server)
            return (True, detail) if ok else (False, detail)
        if acc is not None:
            return True, f"Attached to running terminal ({_format_account(acc)})"
        return False, "MT5 terminal connected but no account is logged in"

    attach_err = mt5.last_error()

    if attach_err and attach_err[0] == -6:
        return False, (
            "MT5 Python API blocked (Authorization failed). "
            "Ensure MetaTrader 5 is running, logged into account "
            f"{creds.login or '(set MT5_LOGIN)'}, and the Algo Trading button "
            "in the MT5 toolbar is ON (green). "
            "Also verify Tools -> Options -> Expert Advisors -> "
            "'Allow algorithmic trading' is checked, then restart MT5."
        )

    if creds.path and mt5.initialize(path=creds.path):
        acc = mt5.account_info()
        if account_matches(acc, creds.login):
            return True, f"Started terminal with saved session ({_format_account(acc)})"
        if acc is not None and creds.login and int(getattr(acc, "login", 0)) != creds.login:
            return False, (
                f"Terminal opened as {_format_account(acc)} but MT5_LOGIN is {creds.login}. "
                "Log into the correct account in MT5 first, or update .env."
            )
        if acc is None and creds.login and creds.password:
            ok, detail = _try_login(mt5, creds.login, creds.password, creds.server)
            return (True, detail) if ok else (False, detail)
        if acc is not None:
            return True, f"Terminal started ({_format_account(acc)})"
        return False, "MT5 started but no account is logged in"

    return False, (
        f"Could not connect to MT5: attach={attach_err}, path={mt5.last_error()}. "
        "Start MetaTrader 5 manually, log into account "
        f"{creds.login or '(set MT5_LOGIN)'}, enable Algorithmic Trading, then retry. "
        "MT5_SERVER should match the server name shown in MT5 (File -> Login to Trade Account), "
        "not necessarily the IP address."
    )
