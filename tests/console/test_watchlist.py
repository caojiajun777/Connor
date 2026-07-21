"""Console watchlist / audit API tests (no DB dependency for happy path)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.daily.api import create_app
from app.daily.config import DailySettings


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    watchlist = {
        "version": 2,
        "accounts": [
            {
                "handle": "OpenAI",
                "display_name": "OpenAI",
                "organization": "OpenAI",
                "source_type": "official",
                "verified_at": "2020-01-01",
            },
            {
                "handle": "sama",
                "display_name": "Sam Altman",
                "organization": "OpenAI",
                "source_type": "employee",
                "role": "CEO",
                "verified_at": "2026-07-01",
            },
        ],
    }
    wl_path = tmp_path / "watchlist.yaml"
    wl_path.write_text(yaml.safe_dump(watchlist), encoding="utf-8")
    audit_root = tmp_path / "audits"

    settings = replace(DailySettings.from_env(), watchlist_path=wl_path)

    monkeypatch.setattr(
        "app.daily.console.watchlist.DailySettings.from_env",
        lambda: settings,
    )
    monkeypatch.setattr(
        "app.daily.console.watchlist.default_audit_root",
        lambda: audit_root,
    )

    return TestClient(create_app(settings, skip_schema_init=True))


def test_console_watchlist_list(client: TestClient) -> None:
    resp = client.get("/api/console/watchlist")
    assert resp.status_code == 200
    body = resp.json()
    assert body["account_count"] == 2
    assert body["stale_count"] >= 1
    handles = {a["handle"] for a in body["accounts"]}
    assert handles == {"OpenAI", "sama"}
    openai = next(a for a in body["accounts"] if a["handle"] == "OpenAI")
    assert openai["stale"] is True


def test_console_watchlist_audits_empty_then_start_dry_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.get("/api/console/watchlist/audits").json() == []

    monkeypatch.setattr(
        "app.daily.console.watchlist.run_account_audit",
        lambda *args, **kwargs: None,
    )

    class _NoThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self) -> None:
            return None

    monkeypatch.setattr("app.daily.console.watchlist.threading.Thread", _NoThread)

    resp = client.post(
        "/api/console/watchlist/audits",
        json={"handles": ["OpenAI"], "live": False},
    )
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    assert run_id

    listed = client.get("/api/console/watchlist/audits").json()
    assert any(r["run_id"] == run_id for r in listed)

    detail = client.get(f"/api/console/watchlist/audits/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["run_id"] == run_id
    status_path = Path(resp.json()["output_dir"]) / "status.json"
    assert json.loads(status_path.read_text(encoding="utf-8"))["status"] == "queued"


def test_console_blocks_live_all(client: TestClient) -> None:
    resp = client.post("/api/console/watchlist/audits", json={"all": True, "live": True})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "live_all_blocked"
