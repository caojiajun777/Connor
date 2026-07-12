from __future__ import annotations

import json
from pathlib import Path

from app.x_watchlist.schemas import AccountCursor, NormalizedPost, utc_now_iso


class CursorStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._cursors: dict[str, AccountCursor] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._cursors = {}
            return
        with self.path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid cursor file format: {self.path}")
        for handle, data in raw.items():
            payload = dict(data) if isinstance(data, dict) else {}
            payload["handle"] = payload.get("handle") or handle
            self._cursors[str(payload["handle"]).lower()] = AccountCursor.model_validate(payload)

    def get(self, handle: str) -> AccountCursor | None:
        return self._cursors.get(handle.lstrip("@").lower())

    def all(self) -> dict[str, AccountCursor]:
        return dict(self._cursors)

    def update_from_success(
        self,
        handle: str,
        posts: list[NormalizedPost],
        collected_at: str | None = None,
    ) -> AccountCursor:
        clean_handle = handle.lstrip("@")
        key = clean_handle.lower()
        existing = self._cursors.get(key) or AccountCursor(handle=clean_handle)

        newest_post: NormalizedPost | None = None
        for post in posts:
            if newest_post is None:
                newest_post = post
                continue
            if post.published_at > newest_post.published_at:
                newest_post = post
            elif post.published_at == newest_post.published_at:
                try:
                    if int(post.post_id) > int(newest_post.post_id):
                        newest_post = post
                except ValueError:
                    pass

        updated = AccountCursor(
            handle=clean_handle,
            last_successful_collected_at=collected_at or utc_now_iso(),
            last_seen_post_id=newest_post.post_id if newest_post else existing.last_seen_post_id,
            last_seen_published_at=newest_post.published_at if newest_post else existing.last_seen_published_at,
            updated_at=utc_now_iso(),
        )
        self._cursors[key] = updated
        return updated

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            cursor.handle.lower(): cursor.model_dump(exclude={"handle"})
            | {"handle": cursor.handle}
            for cursor in self._cursors.values()
        }
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
