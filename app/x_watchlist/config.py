from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.x_watchlist.schemas import SourceType, WatchlistConfig, XSourceAccount

DEFAULT_RULES: dict[str, dict[str, Any]] = {
    "official": {
        "include_originals": True,
        "include_quotes": True,
        "include_replies": True,
        "include_reposts": True,
        "max_posts_per_run": 0,
        "priority": "P0",
    },
    "employee": {
        "include_originals": True,
        "include_quotes": True,
        "include_replies": True,
        "include_reposts": True,
        "max_posts_per_run": 0,
        "priority": "P0",
    },
    "leak": {
        "include_originals": True,
        "include_quotes": True,
        "include_replies": True,
        "include_reposts": True,
        "max_posts_per_run": 0,
        "priority": "P1",
    },
}

# Analyst-type accounts inherit leak defaults unless overridden in YAML defaults block.
ANALYST_SOURCE_TYPES = {
    SourceType.ANALYST.value,
    SourceType.TECHNICAL_ANALYST.value,
    SourceType.LEAK_AND_OPINION.value,
    SourceType.PRODUCT_SIGNAL.value,
    SourceType.BENCHMARK.value,
}

VALID_SOURCE_TYPES = {item.value for item in SourceType}


class WatchlistConfigError(Exception):
    """Raised when watchlist YAML is invalid."""


def _resolve_defaults_key(source_type: str) -> str:
    if source_type in DEFAULT_RULES:
        return source_type
    if source_type in ANALYST_SOURCE_TYPES:
        return "leak"
    raise WatchlistConfigError(
        f"Unknown source_type '{source_type}'. Valid values: {sorted(VALID_SOURCE_TYPES)}"
    )


def _merge_account(raw: dict[str, Any], yaml_defaults: dict[str, dict[str, Any]]) -> XSourceAccount:
    source_type = raw.get("source_type")
    if not source_type:
        raise WatchlistConfigError(f"Account {raw.get('handle', '<unknown>')} missing source_type")

    defaults_key = _resolve_defaults_key(source_type)
    merged: dict[str, Any] = {}
    merged.update(DEFAULT_RULES[defaults_key])
    if defaults_key in yaml_defaults:
        merged.update(yaml_defaults[defaults_key])
    merged.update(raw)
    merged["handle"] = str(merged["handle"]).lstrip("@")

    try:
        account = XSourceAccount.model_validate(merged)
    except ValidationError as exc:
        raise WatchlistConfigError(
            f"Invalid account config for handle={raw.get('handle')}: {exc}"
        ) from exc

    if account.source_type not in VALID_SOURCE_TYPES:
        raise WatchlistConfigError(
            f"Account {account.handle} has invalid source_type '{account.source_type}'"
        )
    if account.max_posts_per_run < 0 or account.max_posts_per_run > 200:
        raise WatchlistConfigError(
            f"Account {account.handle} max_posts_per_run must be between 0 and 200 "
            "(0 = keep all in-window posts)"
        )
    return account


def load_watchlist(path: str | Path) -> WatchlistConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise WatchlistConfigError(f"Watchlist file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise WatchlistConfigError("Watchlist root must be a mapping")

    yaml_defaults = raw.get("defaults", {})
    if not isinstance(yaml_defaults, dict):
        raise WatchlistConfigError("'defaults' must be a mapping")

    accounts_raw = raw.get("accounts")
    if not isinstance(accounts_raw, list) or not accounts_raw:
        raise WatchlistConfigError("'accounts' must be a non-empty list")

    accounts: list[XSourceAccount] = []
    seen_handles: set[str] = set()
    for entry in accounts_raw:
        if not isinstance(entry, dict):
            raise WatchlistConfigError("Each account entry must be a mapping")
        account = _merge_account(entry, yaml_defaults)
        if account.handle.lower() in seen_handles:
            raise WatchlistConfigError(f"Duplicate handle in watchlist: {account.handle}")
        seen_handles.add(account.handle.lower())
        accounts.append(account)

    return WatchlistConfig(version=int(raw.get("version", 1)), accounts=accounts)


def filter_accounts(
    config: WatchlistConfig,
    handles: list[str] | None = None,
    enabled_only: bool = True,
) -> list[XSourceAccount]:
    selected = config.accounts
    if enabled_only:
        selected = [account for account in selected if account.enabled]
    if handles:
        wanted = {handle.lstrip("@").lower() for handle in handles}
        selected = [account for account in selected if account.handle.lower() in wanted]
    return selected
