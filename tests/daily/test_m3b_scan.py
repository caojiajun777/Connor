from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.daily.eligibility import cursor_eligible_from_normalized, is_cursor_eligible
from app.daily.enums import CollectionStatus
from app.daily.outbox_sync import sync_pending_cursor_outbox
from app.daily.redis_cursors import RedisCursorStore
from app.daily.scan import ScanPost, apply_report_day_cursor_policy, scan_timeline_increments
from app.x_watchlist.schemas import PostType


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, name: str):
        return self.store.get(name)

    def set(self, name: str, value: str, **kwargs):
        if any(k in kwargs for k in ("ex", "px", "exat", "pxat", "keepttl")):
            raise AssertionError(f"TTL forbidden: {kwargs}")
        self.store[name] = value
        return True

    def delete(self, *names: str):
        for name in names:
            self.store.pop(name, None)


def _post(
    post_id: str,
    hours_ago: float,
    *,
    post_type: str = PostType.ORIGINAL.value,
    is_pinned: bool = False,
    now: datetime,
) -> ScanPost:
    published = now - timedelta(hours=hours_ago)
    return ScanPost(
        post_id=post_id,
        published_at=published.isoformat(),
        post_type=post_type,
        is_pinned=is_pinned,
    )


def test_repost_and_pin_not_cursor_eligible() -> None:
    assert is_cursor_eligible(post_type=PostType.REPOST.value) is False
    assert is_cursor_eligible(post_type=PostType.ORIGINAL.value, is_pinned=True) is False
    assert is_cursor_eligible(post_type=PostType.QUOTE.value) is True
    assert is_cursor_eligible(post_type=PostType.REPLY.value) is True
    assert cursor_eligible_from_normalized(PostType.REPOST.value, False) is False


def test_scan_stops_on_eligible_cursor_excludes_old() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    posts = [
        _post("new1", 1, now=now),
        _post("new2", 2, now=now),
        _post("old", 3, now=now),
        _post("older", 4, now=now),
    ]
    result = scan_timeline_increments(
        posts,
        old_cursor_post_id="old",
        last_success_at=now - timedelta(hours=6),
        now=now,
    )
    assert [p.post_id for p in result.increments] == ["new1", "new2"]
    assert result.cursor_reached is True
    assert result.should_advance_cursor is True
    assert result.cursor_after_post_id == "new1"
    assert result.collection_status == CollectionStatus.SUCCESS.value


def test_repost_does_not_satisfy_cursor_hit() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    posts = [
        _post("new1", 1, now=now),
        _post("old", 2, post_type=PostType.REPOST.value, now=now),  # same id as cursor but repost
        _post("old", 3, now=now),  # eligible original with same id later — unusual but eligible hit
    ]
    # First "old" is repost → not a hit; included as increment. Second eligible "old" stops.
    result = scan_timeline_increments(
        posts,
        old_cursor_post_id="old",
        last_success_at=now - timedelta(hours=1),
        now=now,
    )
    assert result.cursor_reached is True
    assert [p.post_id for p in result.increments] == ["new1", "old"]
    assert result.increments[1].post_type == PostType.REPOST.value


def test_first_run_chases_72h_only() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    posts = [
        _post("a", 1, now=now),
        _post("b", 40, now=now),
        _post("c", 80, now=now),
        _post("d", 90, now=now),
    ]
    result = scan_timeline_increments(
        posts,
        old_cursor_post_id=None,
        last_success_at=None,
        now=now,
    )
    assert [p.post_id for p in result.increments] == ["a", "b"]
    assert result.window_covered is True
    assert result.should_advance_cursor is True
    assert result.cursor_after_post_id == "a"


def test_cursor_not_found_but_window_covered_advances() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    posts = [
        _post("a", 1, now=now),
        _post("b", 80, now=now),
    ]
    result = scan_timeline_increments(
        posts,
        old_cursor_post_id="missing",
        last_success_at=now - timedelta(hours=5),
        now=now,
    )
    assert result.cursor_reached is False
    assert result.window_covered is True
    assert result.collection_status == CollectionStatus.CURSOR_NOT_FOUND_BUT_WINDOW_COVERED.value
    assert result.should_advance_cursor is True


def test_known_data_gap_does_not_advance_without_accept() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    posts = [
        _post("a", 1, now=now),
        _post("b", 80, now=now),
    ]
    result = scan_timeline_increments(
        posts,
        old_cursor_post_id="missing",
        last_success_at=now - timedelta(hours=100),
        now=now,
        accept_gap=False,
    )
    assert result.known_data_gap is True
    assert result.collection_status == CollectionStatus.KNOWN_DATA_GAP.value
    assert result.should_advance_cursor is False


def test_known_data_gap_accept_allows_advance() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    posts = [
        _post("a", 1, now=now),
        _post("b", 80, now=now),
    ]
    result = scan_timeline_increments(
        posts,
        old_cursor_post_id="missing",
        last_success_at=now - timedelta(hours=100),
        now=now,
        accept_gap=True,
    )
    assert result.known_data_gap is True
    assert result.should_advance_cursor is True


def test_safety_limit_blocks_cursor_advance() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    posts = [_post(str(i), i * 0.1, now=now) for i in range(1, 6)]
    result = scan_timeline_increments(
        posts,
        old_cursor_post_id="999",
        last_success_at=now - timedelta(hours=1),
        now=now,
        max_new_posts_safety_limit=3,
        page_incomplete=True,
    )
    assert result.safety_limit_reached is True
    assert len(result.increments) == 3
    assert result.should_advance_cursor is False
    assert result.collection_status == CollectionStatus.SAFETY_LIMIT_REACHED.value


def test_no_new_eligible_keeps_cursor_before_on_hit() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    posts = [
        _post("r1", 1, post_type=PostType.REPOST.value, now=now),
        _post("old", 2, now=now),
    ]
    result = scan_timeline_increments(
        posts,
        old_cursor_post_id="old",
        last_success_at=now - timedelta(hours=1),
        now=now,
    )
    assert [p.post_id for p in result.increments] == ["r1"]
    assert result.cursor_after_post_id == "old"  # unchanged when no new eligible
    assert result.should_advance_cursor is True


def test_page_incomplete_without_boundary() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)
    posts = [_post("a", 1, now=now), _post("b", 2, now=now)]
    result = scan_timeline_increments(
        posts,
        old_cursor_post_id="missing",
        last_success_at=now - timedelta(hours=1),
        now=now,
        page_incomplete=True,
    )
    assert result.collection_status == CollectionStatus.PAGE_INCOMPLETE.value
    assert result.should_advance_cursor is False


def test_outbox_sync_writes_redis_without_ttl() -> None:
    class Row:
        def __init__(self) -> None:
            self.handle = "openai"
            self.cursor_post_id = "123"
            self.cursor_published_at = datetime(2026, 7, 13, tzinfo=timezone.utc)
            self.run_id = "run-1"
            self.status = "pending"
            self.attempt_count = 0
            self.last_error = None
            self.synced_at = None
            self.created_at = datetime.now(timezone.utc)

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def __iter__(self):
            return iter(self._rows)

    class FakeSession:
        def __init__(self, rows):
            self.rows = rows

        def scalars(self, _stmt):
            return FakeResult(self.rows)

        def flush(self):
            return None

    row = Row()
    session = FakeSession([row])
    client = FakeRedis()
    store = RedisCursorStore(client, key_prefix="connor:x:cursor:")
    result = sync_pending_cursor_outbox(session, store, run_id="run-1")
    assert result["synced"] == 1
    assert result["complete"] is True
    assert row.status == "synced"
    assert store.get("openai") is not None
    assert store.get("openai").post_id == "123"


def test_report_day_policy_keeps_only_report_day_increments() -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    # 2h ago = still 7/23 Shanghai; 30h ago = 7/22 Shanghai
    posts = [_post("today", 2, now=now), _post("yesterday", 30, now=now)]
    scan = scan_timeline_increments(
        posts,
        old_cursor_post_id=None,
        last_success_at=None,
        now=now,
    )
    shaped = apply_report_day_cursor_policy(
        scan, posts, report_date="2026-07-23", tz_name="Asia/Shanghai"
    )
    assert [p.post_id for p in shaped.increments] == ["today"]
    assert shaped.should_advance_cursor is True


def test_report_day_policy_mints_cursor_when_no_report_day_posts() -> None:
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    posts = [_post("old1", 30, now=now), _post("old2", 40, now=now)]
    scan = scan_timeline_increments(
        posts,
        old_cursor_post_id=None,
        last_success_at=None,
        now=now,
    )
    shaped = apply_report_day_cursor_policy(
        scan, posts, report_date="2026-07-23", tz_name="Asia/Shanghai"
    )
    assert shaped.increments == []
    assert shaped.should_advance_cursor is True
    assert shaped.cursor_after_post_id == "old1"
    assert shaped.collection_status == CollectionStatus.SUCCESS.value
    assert shaped.warning and "minted_cursor_no_posts_on_2026-07-23" in shaped.warning
