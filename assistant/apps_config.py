"""Helpers for the [apps.allowlist] config table."""
from __future__ import annotations


def allowlist(cfg: dict) -> dict[str, str]:
    table = cfg.get("apps", {}).get("allowlist", {})
    return {str(k).lower(): str(v) for k, v in table.items()}
