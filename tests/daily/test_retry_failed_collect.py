from __future__ import annotations

from unittest.mock import MagicMock

from app.daily.retry_failed_collect import (
    AccountFailureInfo,
    classify_failure_bucket,
    list_failed_handles,
    retry_failed_collect,
    select_worth_retry_handles,
)


def test_list_failed_handles_filters_retryable_statuses() -> None:
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        ("Alpha", "failed_retryable"),
        ("Beta", "success"),
        ("Gamma", "page_incomplete"),
        ("Delta", "failed_permanent"),
        ("Epsilon", "known_data_gap"),
    ]
    assert list_failed_handles(session, "run-1") == ["Alpha", "Gamma"]


def test_classify_service_error_worth_retry() -> None:
    bucket, worth = classify_failure_bucket(
        collection_status="failed_retryable",
        error="X returned a service error or generic page failure.",
    )
    assert bucket == "x_service_error"
    assert worth is True


def test_classify_auth_not_worth_retry() -> None:
    bucket, worth = classify_failure_bucket(
        collection_status="failed_retryable",
        reason_code="login_required",
        error="login required",
    )
    assert bucket == "auth_session"
    assert worth is False


def test_select_worth_retry_stops_below_threshold() -> None:
    failures = [
        AccountFailureInfo("a", "failed_retryable", None, "service error", True, "x_service_error"),
        AccountFailureInfo("b", "failed_retryable", None, "service error", True, "x_service_error"),
        AccountFailureInfo("c", "failed_retryable", "login_required", "login", False, "auth_session"),
    ]
    to_retry, skipped, residual, stop = select_worth_retry_handles(failures, stop_below=5)
    assert to_retry == []
    assert stop == "below_threshold"
    assert residual == ["a", "b"]
    assert skipped == ["c"]


def test_select_worth_retry_starts_when_above_threshold() -> None:
    failures = [
        AccountFailureInfo(
            f"h{i}", "failed_retryable", None, "service error", True, "x_service_error"
        )
        for i in range(6)
    ]
    to_retry, skipped, residual, stop = select_worth_retry_handles(failures, stop_below=5)
    assert stop is None
    assert len(to_retry) == 6
    assert residual == []
    assert skipped == []


def test_until_done_waits_before_first_and_between_passes(monkeypatch) -> None:
    monkeypatch.setenv("CONNOR_PUBLISH_DEADLINE_ENABLED", "0")
    sleeps: list[float] = []

    class FakeRuntime:
        settings = MagicMock(watchlist_path="config/x_watchlist.yaml")

        def __init__(self) -> None:
            self.session_factory = MagicMock()
            session = MagicMock()
            self.session_factory.return_value.__enter__.return_value = session
            self.session_factory.return_value.__exit__.return_value = False
            session.get.return_value = MagicMock(id="run-1")
            # list_account_failures path uses scalars(); keep empty so explicit handles drive target.
            session.execute.return_value.scalars.return_value = []
            session.execute.return_value.all.return_value = []

        def _run_live_collect(self, run_id: str, **kwargs):  # noqa: ANN003
            del run_id
            handles = kwargs["handles"]
            if len(handles) >= 6:
                # Clear all but two.
                statuses = {h: "success" for h in handles}
                for h in handles[:2]:
                    statuses[h] = "failed_retryable"
                return {
                    "account_count": len(handles),
                    "new_post_count": 1,
                    "collection_complete": False,
                    "account_statuses": statuses,
                    "failed_handles": handles[:2],
                }
            return {
                "account_count": len(handles),
                "new_post_count": 1,
                "collection_complete": True,
                "account_statuses": {h: "success" for h in handles},
                "failed_handles": [],
            }

        def close(self) -> None:
            return None

    # With stop_below=5, after first pass only 2 remain -> stop without second wait/pass.
    result = retry_failed_collect(
        run_id="run-1",
        handles=[f"h{i}" for i in range(6)],
        until_done=True,
        wait_before_first=True,
        interval_sec=15,
        max_passes=5,
        stop_below=5,
        include_missing=False,
        sleep_fn=sleeps.append,
        runtime=FakeRuntime(),
    )
    assert result.ok is True
    assert result.stop_reason == "below_threshold"
    assert len(result.remaining_failed) == 2
    assert sleeps == [15]
    assert len(result.passes) == 1


def test_until_done_stops_at_publish_deadline(monkeypatch) -> None:
    monkeypatch.setenv("CONNOR_PUBLISH_DEADLINE_HOUR", "12")
    monkeypatch.setenv("CONNOR_PUBLISH_DEADLINE_RESERVE_MIN", "90")
    monkeypatch.setattr(
        "app.daily.retry_failed_collect.collect_retry_past_deadline",
        lambda *args, **kwargs: True,
    )

    class FakeRuntime:
        settings = MagicMock(watchlist_path="config/x_watchlist.yaml")

        def __init__(self) -> None:
            self.session_factory = MagicMock()
            session = MagicMock()
            self.session_factory.return_value.__enter__.return_value = session
            self.session_factory.return_value.__exit__.return_value = False
            session.get.return_value = MagicMock(id="run-1")
            session.execute.return_value.scalars.return_value = []
            session.execute.return_value.all.return_value = []

        def _run_live_collect(self, run_id: str, **kwargs):  # noqa: ANN003
            raise AssertionError("should not collect after publish deadline")

        def close(self) -> None:
            return None

    result = retry_failed_collect(
        run_id="run-1",
        handles=[f"h{i}" for i in range(8)],
        until_done=True,
        wait_before_first=True,
        interval_sec=15,
        stop_below=5,
        include_missing=False,
        runtime=FakeRuntime(),
    )
    assert result.ok is True
    assert result.stop_reason == "publish_deadline"
    assert len(result.remaining_failed) == 8
    assert result.passes == []
