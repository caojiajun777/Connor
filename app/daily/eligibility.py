from __future__ import annotations

from app.x_watchlist.schemas import PostType


def is_cursor_eligible(
    *,
    post_type: str,
    is_pinned: bool = False,
    is_quoted_original_expansion: bool = False,
    is_recommended: bool = False,
) -> bool:
    """Whether a timeline item may act as cursor_after / cursor_reached anchor.

    Bare reposts, pins, recommended content, and quoted-original expansions are
    still collectible — they just must not drive the cursor.
    """
    if is_pinned or is_recommended or is_quoted_original_expansion:
        return False
    if post_type == PostType.REPOST.value:
        return False
    if post_type in {
        PostType.ORIGINAL.value,
        PostType.REPLY.value,
        PostType.QUOTE.value,
    }:
        return True
    # unknown: treat as ineligible until we have a stable account-owned id signal
    return False


def cursor_eligible_from_normalized(
    post_type: str,
    is_pinned: bool,
    *,
    social_context: str | None = None,
) -> bool:
    context = (social_context or "").lower()
    is_recommended = "who to follow" in context or "suggested" in context
    return is_cursor_eligible(
        post_type=post_type,
        is_pinned=is_pinned,
        is_recommended=is_recommended,
    )
