"""Northflank monitoring dashboard — re-exports refactored API."""

from src.web.app import create_app, run_dashboard

__all__ = ["create_app", "run_dashboard"]
