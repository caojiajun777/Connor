from __future__ import annotations

from datetime import datetime, timezone

from tests.x_watchlist.conftest import make_post

from app.x_watchlist.cleaner import clean_posts
from app.x_watchlist.schemas import AccountCursor


def test_clean_posts_keeps_all_types_filters_window_and_caps(sample_account, window) -> None:
    start, end = window
    posts = [
        make_post(post_id="1", published_at="2026-07-11T10:00:00+00:00", text="keep"),
        make_post(post_id="1", published_at="2026-07-11T10:00:00+00:00", text="dup"),
        make_post(post_id="2", published_at="2026-07-10T10:00:00+00:00", text="old"),
        make_post(post_id="3", published_at="2026-07-11T11:00:00+00:00", text="rt", post_type="repost"),
        make_post(post_id="4", published_at="2026-07-11T12:00:00+00:00", text="reply", post_type="reply"),
        make_post(post_id="5", published_at="2026-07-11T13:00:00+00:00", text="quote", post_type="quote"),
        make_post(post_id="6", published_at="2026-07-11T14:00:00+00:00", text="", post_type="original"),
    ]
    posts[-1].url = ""
    posts[-1].text = ""

    result = clean_posts(
        posts,
        accounts_by_handle={"openai": sample_account},
        window_start=start,
        window_end=end,
        max_posts_per_account=10,
    )

    retained_ids = [post.post_id for post in result.posts]
    # newest-first within account; empty/old/dup removed; all types kept
    assert retained_ids == ["5", "4", "3", "1"]
    assert result.stats.duplicates_removed == 1
    assert result.stats.out_of_window_removed == 1
    assert result.stats.empty_removed == 1
    assert result.stats.reposts_removed == 0
    assert result.stats.replies_removed == 0


def test_clean_posts_caps_at_ten_newest(sample_account, window) -> None:
    start, end = window
    posts = [
        make_post(
            post_id=str(i),
            published_at=f"2026-07-11T{i:02d}:00:00+00:00",
            text=f"post-{i}",
        )
        for i in range(1, 13)
    ]
    result = clean_posts(
        posts,
        accounts_by_handle={"openai": sample_account},
        window_start=start,
        window_end=end,
        max_posts_per_account=10,
    )
    assert len(result.posts) == 10
    assert result.posts[0].post_id == "12"
    assert result.posts[-1].post_id == "3"
    assert result.stats.truncated_to_limit == 2


def test_clean_posts_allows_employee_replies(employee_account, window) -> None:
    start, end = window
    posts = [
        make_post(
            post_id="10",
            handle="thsottiaux",
            published_at="2026-07-11T10:00:00+00:00",
            text="reply body",
            post_type="reply",
            source_type="employee",
        )
    ]
    result = clean_posts(
        posts,
        accounts_by_handle={"thsottiaux": employee_account},
        window_start=start,
        window_end=end,
    )
    assert len(result.posts) == 1


def test_clean_posts_drops_old_pinned(sample_account, window) -> None:
    start, end = window
    posts = [
        make_post(
            post_id="40",
            published_at="2026-07-10T08:00:00+00:00",
            text="old pin",
            is_pinned=True,
        ),
        make_post(
            post_id="60",
            published_at="2026-07-11T12:00:00+00:00",
            text="new",
        ),
    ]
    result = clean_posts(
        posts,
        accounts_by_handle={"openai": sample_account},
        window_start=start,
        window_end=end,
    )
    assert [post.post_id for post in result.posts] == ["60"]
    assert result.stats.pinned_old_removed == 1


def test_clean_posts_cursor_tech_dedupe(sample_account, window) -> None:
    start, end = window
    cursor = AccountCursor(
        handle="OpenAI",
        last_seen_post_id="50",
        last_seen_published_at="2026-07-11T09:00:00+00:00",
    )
    posts = [
        make_post(post_id="40", published_at="2026-07-11T08:30:00+00:00", text="seen"),
        make_post(post_id="60", published_at="2026-07-11T12:00:00+00:00", text="new"),
    ]
    result = clean_posts(
        posts,
        accounts_by_handle={"openai": sample_account},
        window_start=start,
        window_end=end,
        cursors_by_handle={"openai": cursor},
    )
    assert [post.post_id for post in result.posts] == ["60"]


def test_clean_posts_inclusive_window_end(sample_account) -> None:
    start = datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 12, 0, 0, tzinfo=timezone.utc)
    posts = [make_post(post_id="7", published_at="2026-07-12T00:00:00+00:00", text="edge")]
    result = clean_posts(
        posts,
        accounts_by_handle={"openai": sample_account},
        window_start=start,
        window_end=end,
    )
    assert len(result.posts) == 1
