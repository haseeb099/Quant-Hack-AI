"""Read and update MetaTrader 5 terminal configuration files."""

from __future__ import annotations

import configparser
import os
import re
from pathlib import Path


def _metaquotes_root() -> Path:
    appdata = os.getenv("APPDATA")
    if not appdata:
        raise FileNotFoundError("APPDATA is not set")
    return Path(appdata) / "MetaQuotes" / "Terminal"


def find_common_ini() -> Path | None:
    """Return the active terminal common.ini, if present."""
    root = _metaquotes_root()
    if not root.is_dir():
        return None

    candidates = sorted(root.glob("*/config/common.ini"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _read_ini_bytes(path: Path) -> tuple[bytes, str]:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe"):
        encoding = "utf-16-le"
    elif raw.startswith(b"\xfe\xff"):
        encoding = "utf-16-be"
    else:
        encoding = "utf-8"
    text = raw.decode(encoding)
    if encoding.startswith("utf-16"):
        text = text.lstrip("\ufeff")
    return raw, text


def _write_ini_bytes(path: Path, raw: bytes, text: str) -> None:
    if raw.startswith(b"\xff\xfe"):
        path.write_bytes(b"\xff\xfe" + text.encode("utf-16-le"))
    elif raw.startswith(b"\xfe\xff"):
        path.write_bytes(b"\xfe\xff" + text.encode("utf-16-be"))
    else:
        path.write_text(text, encoding="utf-8")


def _read_ini_text(path: Path) -> str:
    _, text = _read_ini_bytes(path)
    return text.lstrip("\n").lstrip("\r")


def read_common_ini(path: Path | None = None) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.optionxform = str  # preserve case
    ini_path = path or find_common_ini()
    if ini_path is None or not ini_path.is_file():
        return parser
    parser.read_string(_read_ini_text(ini_path), source=str(ini_path))
    return parser


def _set_ini_key(text: str, key: str, value: str) -> tuple[str, bool]:
    pattern = rf"(?m)^{re.escape(key)}\s*=\s*.*$"
    if re.search(pattern, text):
        return re.sub(pattern, f"{key}={value}", text, count=1), True
    return text, False


def read_mt5_profile(path: Path | None = None) -> dict[str, str | int | None]:
    """Return saved login/server from MT5 common.ini."""
    parser = read_common_ini(path)
    common = parser["Common"] if parser.has_section("Common") else {}
    experts = parser["Experts"] if parser.has_section("Experts") else {}

    login_raw = common.get("Login")
    login = int(login_raw) if login_raw and str(login_raw).strip().isdigit() else None
    server = common.get("Server")

    return {
        "login": login,
        "server": server.strip() if server else None,
        "api_enabled": str(experts.get("Api", "0")).strip() == "1",
        "algo_enabled": str(experts.get("Enabled", "0")).strip() == "1",
        "dll_import_enabled": str(experts.get("AllowDllImport", "0")).strip() == "1",
        "path": str(path or find_common_ini() or ""),
    }


def ensure_mt5_api_enabled(*, restart_hint: bool = True) -> tuple[bool, str]:
    """Enable Python API access in MT5 common.ini.

    MT5 blocks MetaTrader5.initialize() with Authorization failed when Experts/Api=0.
    Stop MetaTrader 5 before writing so the terminal does not overwrite the file on exit.
    """
    import subprocess

    ini_path = find_common_ini()
    if ini_path is None:
        return False, "Could not find MetaQuotes Terminal config (common.ini)"

    raw, text = _read_ini_bytes(ini_path)
    changes: list[str] = []
    updated = text

    for key, label in (
        ("Api", "Python API access"),
        ("Enabled", "Algorithmic trading"),
        ("AllowDllImport", "DLL imports (ZeroMQ bridge)"),
        ("Account", "Keep algo trading on account switch"),
        ("Profile", "Keep algo trading on profile switch"),
    ):
        match = re.search(rf"(?m)^{re.escape(key)}\s*=\s*(\d+)", updated)
        desired = "0" if key in ("Account", "Profile") else "1"
        if match and match.group(1) == desired:
            continue
        if match:
            updated, _ = _set_ini_key(updated, key, desired)
            changes.append(label)
        elif "[Experts]" in updated:
            updated = updated.replace("[Experts]\r\n", f"[Experts]\r\n{key}={desired}\r\n", 1)
            changes.append(label)

    if not changes:
        return True, f"MT5 API already enabled ({ini_path})"

    if subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.count("terminal64.exe"):
        return False, (
            "Close MetaTrader 5 before enabling API settings, then run this script again. "
            "MT5 overwrites common.ini on exit if it is running during edits."
        )

    _write_ini_bytes(ini_path, raw, updated)
    detail = f"Enabled {', '.join(changes)} in {ini_path}"
    if restart_hint:
        detail += ". Restart MetaTrader 5 for changes to take effect."
    return True, detail


def server_candidates_from_profile(server: str | None) -> list[str]:
    """Build server candidate list using env value plus saved MT5 profile."""
    from src.integrations.mt5_session import server_candidates

    candidates = server_candidates(server)
    profile = read_mt5_profile()
    profile_server = profile.get("server")
    if profile_server and profile_server not in candidates:
        candidates.append(str(profile_server))
    return candidates
