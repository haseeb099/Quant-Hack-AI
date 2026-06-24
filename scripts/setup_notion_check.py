#!/usr/bin/env python3
"""Validate Notion integration setup — API key, database access, property schema."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

# Expected property names and acceptable Notion types per database.
DATABASE_SPECS: dict[str, dict[str, Any]] = {
    "NOTION_TRADE_JOURNAL_DS_ID": {
        "label": "Trade Journal",
        "required": {
            "Name": {"title"},
            "Symbol": {"rich_text"},
            "Direction": {"select"},
            "Status": {"rich_text"},
            "Confidence": {"number"},
            "Regime": {"rich_text"},
            "Session": {"rich_text"},
        },
        "direction_options": {"BUY", "SELL", "HOLD"},
    },
    "NOTION_AGENT_PERF_DS_ID": {
        "label": "Agent Performance",
        "required": {
            "Name": {"title"},
            "Agent": {"rich_text"},
            "Win Rate": {"number"},
            "Avg R": {"number"},
            "Samples": {"number"},
        },
        "optional": {"Symbol": {"rich_text"}},
    },
    "NOTION_RISK_EVENTS_DS_ID": {
        "label": "Risk Events",
        "required": {
            "Name": {"title"},
            "Event Type": {"rich_text"},
            "Message": {"rich_text"},
            "Severity": {"select"},
            "Timestamp": {"rich_text"},
        },
        "optional": {"Details": {"rich_text"}},
    },
    "NOTION_TASKS_DS_ID": {
        "label": "Tasks",
        "required": {
            "Name": {"title"},
            "Status": {"select", "status"},
        },
        "optional": {"Notes": {"rich_text"}},
    },
}


def _normalize_id(raw: str) -> str:
    return raw.strip().replace("-", "")


def _fix_hint(env_key: str, issue: str) -> str:
    label = DATABASE_SPECS.get(env_key, {}).get("label", env_key)
    if issue == "missing_env":
        return (
            f"  -> Set {env_key} in .env to the {label} database ID "
            f"(Notion URL .../{label.lower().replace(' ', '-')}?v=... -> copy 32-char ID)."
        )
    if issue == "missing_property":
        return f"  -> In Notion {label} database: add the missing property with the exact name and type shown above."
    if issue == "wrong_type":
        return f"  -> In Notion {label} database: change the property type to match the expected type."
    if issue == "direction_options":
        return "  -> In Trade Journal -> Direction (select): add options BUY, SELL, and HOLD."
    if issue == "no_access":
        return (
            f"  -> Open the {label} database in Notion -> ... -> Connections -> "
            "add your QuantAI integration."
        )
    if issue == "invalid_id":
        return f"  -> Check {env_key}: must be a 32-character database ID (hyphens optional)."
    return f"  -> Review {env_key} and Notion {label} setup."


def _check_select_options(prop: dict[str, Any], expected: set[str]) -> list[str]:
    issues: list[str] = []
    options: set[str] = set()
    if prop.get("type") == "select":
        for opt in (prop.get("select") or {}).get("options") or []:
            options.add(str(opt.get("name", "")).upper())
    if expected and not expected.issubset(options):
        missing = ", ".join(sorted(expected - options))
        issues.append(f"Direction select missing options: {missing}")
    return issues


def _validate_database(
    client: Any,
    env_key: str,
    db_id: str,
    spec: dict[str, Any],
) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    fixes: list[str] = []
    label = spec["label"]

    normalized = _normalize_id(db_id)
    if len(normalized) != 32:
        errors.append(f"{label}: invalid database ID length ({len(normalized)} chars, expected 32)")
        fixes.append(_fix_hint(env_key, "invalid_id"))
        return False, errors, fixes

    try:
        db = client.databases.retrieve(database_id=db_id)
    except Exception as exc:
        msg = str(exc).lower()
        if "unauthorized" in msg or "401" in msg:
            errors.append(f"{label}: API key rejected — check NOTION_API_KEY")
            fixes.append("  -> Regenerate secret at notion.so/my-integrations and update NOTION_API_KEY in .env")
        elif "not found" in msg or "404" in msg:
            errors.append(f"{label}: database not found — wrong ID or integration lacks access")
            fixes.append(_fix_hint(env_key, "no_access"))
        else:
            errors.append(f"{label}: retrieve failed — {exc}")
            fixes.append(_fix_hint(env_key, "no_access"))
        return False, errors, fixes

    props = db.get("properties") or {}
    required = spec.get("required") or {}
    optional = spec.get("optional") or {}

    for prop_name, allowed_types in required.items():
        if prop_name not in props:
            errors.append(f"{label}: missing required property '{prop_name}'")
            fixes.append(_fix_hint(env_key, "missing_property"))
            continue
        actual_type = props[prop_name].get("type")
        if actual_type not in allowed_types:
            expected = "/".join(sorted(allowed_types))
            errors.append(
                f"{label}: '{prop_name}' is type '{actual_type}', expected {expected}",
            )
            fixes.append(_fix_hint(env_key, "wrong_type"))

    for prop_name, allowed_types in optional.items():
        if prop_name not in props:
            continue
        actual_type = props[prop_name].get("type")
        if actual_type not in allowed_types:
            expected = "/".join(sorted(allowed_types))
            errors.append(
                f"{label}: optional '{prop_name}' is type '{actual_type}', expected {expected}",
            )
            fixes.append(_fix_hint(env_key, "wrong_type"))

    if env_key == "NOTION_TRADE_JOURNAL_DS_ID" and "Direction" in props:
        for opt_issue in _check_select_options(
            props["Direction"],
            spec.get("direction_options") or set(),
        ):
            errors.append(f"{label}: {opt_issue}")
            fixes.append(_fix_hint(env_key, "direction_options"))

    extra = set(props) - set(required) - set(optional)
    if extra:
        print(f"  [info] {label}: extra properties (OK): {', '.join(sorted(extra))}")

    ok = len(errors) == 0
    if ok:
        print(f"  [PASS] {label} — schema OK, integration can access database")
    return ok, errors, fixes


def main() -> int:
    api_key = os.getenv("NOTION_API_KEY", "").strip()
    print("QuantAI Notion setup check\n")

    if not api_key:
        print("[FAIL] NOTION_API_KEY is not set")
        print("  -> Create integration: https://www.notion.so/my-integrations")
        print("  -> Copy secret_... into NOTION_API_KEY in .env")
        print("  -> See docs/NOTION_SETUP.md for database setup steps")
        return 1

    if not api_key.startswith("secret_") and not api_key.startswith("ntn_"):
        print("[WARN] NOTION_API_KEY format looks unusual (expected secret_... or ntn_...)")

    try:
        from notion_client import Client
    except ImportError:
        print("[FAIL] notion-client not installed")
        print("  -> Run: pip install notion-client")
        return 1

    client = Client(auth=api_key)

    try:
        client.users.me()
        print("[PASS] NOTION_API_KEY — authenticated\n")
    except Exception as exc:
        print(f"[FAIL] NOTION_API_KEY — authentication failed: {exc}")
        print("  -> Regenerate secret at notion.so/my-integrations and update .env")
        return 1

    all_ok = True
    all_errors: list[str] = []
    all_fixes: list[str] = []
    configured = 0

    for env_key, spec in DATABASE_SPECS.items():
        db_id = os.getenv(env_key, "").strip()
        if not db_id:
            print(f"[SKIP] {spec['label']} — {env_key} not set")
            all_fixes.append(_fix_hint(env_key, "missing_env"))
            continue

        configured += 1
        ok, errors, fixes = _validate_database(client, env_key, db_id, spec)
        if not ok:
            all_ok = False
            for err in errors:
                print(f"  [FAIL] {err}")
            all_errors.extend(errors)
            all_fixes.extend(fixes)

    az_page = os.getenv("NOTION_AZ_PAGE_ID", "").strip()
    if az_page:
        print(f"\n[info] NOTION_AZ_PAGE_ID set (optional guide page)")
    else:
        print("\n[info] NOTION_AZ_PAGE_ID not set — A–Z guide syncs to Tasks DB only")

    sync_flag = os.getenv("NOTION_SYNC_ENABLED", "").strip().lower()
    from src.integrations.notion_sync import notion_sync_enabled

    print(f"\nSync enabled: {notion_sync_enabled()} (NOTION_SYNC_ENABLED={sync_flag or 'auto'})")

    if configured == 0:
        print("\n[FAIL] No database IDs configured")
        for fix in dict.fromkeys(all_fixes):
            print(fix)
        return 1

    if not all_ok:
        print("\n--- Fix instructions ---")
        for fix in dict.fromkeys(all_fixes):
            print(fix)
        print("\nAfter fixes, restart the engine and run:")
        print("  python scripts/sync_notion_az.py --guide-page")
        return 1

    print("\nAll configured Notion databases validated.")
    print("Next: python scripts/sync_notion_az.py --guide-page")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
