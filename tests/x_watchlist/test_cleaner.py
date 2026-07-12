from __future__ import annotations

from datetime import datetime, timezone

from tests.x_watchlist.conftest import make_post

from app.x_watchlist.cleaner import clean_posts
from app.x_watchlist.schemas import AccountCursor


def test_clean_posts_filters_window_type_and_dupes(sample_account, window) -> None:
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
    )

    retained_ids = [post.post_id for post in result.posts]
    assert retained_ids == ["1", "5"]
    assert result.stats.duplicates_removed == 1
    assert result.stats.out_of_window_removed == 1
    assert result.stats.reposts_removed == 1
    assert result.stats.replies_removed == 1
    assert result.stats.empty_removed == 1


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


def test_clean_posts_skips_old_pinned_via_cursor(sample_account, window) -> None:
    start, end = window
    cursor = AccountCursor(
        handle="OpenAI",
        last_seen_post_id="50",
        last_seen_published_at="2026-07-11T09:00:00+00:00",
    )
    posts = [
        make_post(
            post_id="40",
            published_at="2026-07-11T08:00:00+00:00",
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
        cursors_by_handle={"openai": cursor},
    )
    assert [post.post_id for post in result.posts] == ["60"]
    assert result.stats.pinned_skipped == 1


def test_clean_posts_timezone_aware_window(sample_account) -> None:
    start = datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 12, 0, 0, tzinfo=timezone.utc)
    posts = [make_post(post_id="7", published_at="2026-07-11T23:59:59+00:00", text="ok")]
    result = clean_posts(
        posts,
        accounts_by_handle={"openai": sample_account},
        window_start=start,
        window_end=end,
    )
    assert len(result.posts) == 1
