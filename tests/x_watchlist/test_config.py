from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.x_watchlist.config import WatchlistConfigError, filter_accounts, load_watchlist


def test_load_watchlist_merges_defaults(watchlist_yaml: Path) -> None:
    config = load_watchlist(watchlist_yaml)
    assert config.version == 1
    openai = next(account for account in config.accounts if account.handle == "OpenAI")
    assert openai.priority == "P0"
    assert openai.include_replies is True
    assert openai.max_posts_per_run == 10

    employee = next(account for account in config.accounts if account.handle == "thsottiaux")
    assert employee.include_replies is True

    leak = next(account for account in config.accounts if account.handle == "LuminaXspace")
    assert leak.priority == "P1"
    assert leak.max_posts_per_run == 10
    assert leak.include_reposts is True


def test_filter_accounts_enabled_and_handles(watchlist_yaml: Path) -> None:
    config = load_watchlist(watchlist_yaml)
    enabled = filter_accounts(config, enabled_only=True)
    assert all(account.enabled for account in enabled)
    assert "DisabledAcct" not in {account.handle for account in enabled}

    subset = filter_accounts(config, handles=["@OpenAI", "LuminaXspace"], enabled_only=True)
    assert {account.handle for account in subset} == {"OpenAI", "LuminaXspace"}


def test_load_watchlist_rejects_duplicate_handles(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "accounts": [
                    {
                        "handle": "OpenAI",
                        "display_name": "OpenAI",
                        "source_type": "official",
                    },
                    {
                        "handle": "openai",
                        "display_name": "OpenAI Dup",
                        "source_type": "official",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(WatchlistConfigError, match="Duplicate handle"):
        load_watchlist(path)


def test_load_real_project_watchlist() -> None:
    path = Path(__file__).resolve().parents[2] / "config" / "x_watchlist.yaml"
    config = load_watchlist(path)
    enabled = filter_accounts(config, enabled_only=True)
    assert config.version == 2
    assert len(config.accounts) == 125
    assert len(enabled) == len(config.accounts)
    by_type = {}
    for account in config.accounts:
        by_type[account.source_type] = by_type.get(account.source_type, 0) + 1
    assert by_type == {"official": 35, "employee": 54, "analyst": 20, "leak": 16}
    handles = {account.handle.lower() for account in enabled}
    assert "openai" in handles
    assert "thsottiaux" in handles
    assert "luminaxspace" in handles
    assert "zai_org" in handles
    assert "xiaomimimo" in handles
    assert "xiaomimimodevs" in handles
    assert "spacexai" in handles
    assert "xai" not in handles
    assert "cursor_ai" in handles
    assert "cognition" in handles
    assert "semianalysis_" in handles
    assert "btibor91" in handles
    assert "sama" in handles
    assert "polynoamial" in handles
    assert "miramurati" in handles
    assert "natolambert" in handles
    assert "microsoftai" in handles
    assert "nvidiaai" in handles
    assert "runwayml" in handles
    assert "figure_robot" in handles
    assert "vllm_project" in handles
    assert "deepseek_ai" in handles
    assert "sybilhyz" in handles
    assert "zhs05232838" in handles
    assert "guodaya" in handles
    assert "teortaxestex" in handles
    assert "linearuncle" in handles
    assert "oran_ge" in handles
    assert "miaai_lab" in handles
    openai = next(account for account in config.accounts if account.handle == "OpenAI")
    assert openai.max_posts_per_run == 0
    logan = next(account for account in config.accounts if account.handle == "OfficialLoganK")
    assert logan.organization == "Google"
    thibault = next(account for account in config.accounts if account.handle == "thsottiaux")
    assert thibault.display_name == "Thibault Sottiaux"
    assert thibault.role == "Codex engineering"
    junyang = next(account for account in config.accounts if account.handle == "JustinLin610")
    assert junyang.source_type == "analyst"
    assert junyang.display_name == "Junyang Lin"
    alex = next(account for account in config.accounts if account.handle == "alexandr_wang")
    assert alex.organization == "Meta"
    assert alex.role == "Chief AI Officer"
    simon = next(account for account in config.accounts if account.handle == "simonw")
    assert simon.source_type == "analyst"
    assert simon.priority == "P1"
    assert simon.organization is None
    arena = next(account for account in config.accounts if account.handle == "arena")
    assert arena.source_type == "leak"
