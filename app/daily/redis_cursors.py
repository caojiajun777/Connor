from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from app.daily.config import DailySettings


@dataclass
class WorkingCursor:
    post_id: str
    published_at: str | None = None
    last_success_at: str | None = None
    source_run_id: str | None = None

    def to_redis_payload(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> WorkingCursor:
        post_id = data.get("post_id")
        if not post_id:
            raise ValueError("cursor payload missing post_id")
        return cls(
            post_id=str(post_id),
            published_at=_optional_str(data.get("published_at")),
            last_success_at=_optional_str(data.get("last_success_at")),
            source_run_id=_optional_str(data.get("source_run_id")),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class RedisLike(Protocol):
    def get(self, name: str) -> Any: ...

    def set(self, name: str, value: str) -> Any: ...

    def delete(self, *names: str) -> Any: ...


class RedisCursorStore:
    """Working cursors in Redis — long-lived keys with NO TTL."""

    def __init__(self, client: RedisLike, *, key_prefix: str | None = None):
        settings = DailySettings.from_env()
        self._client = client
        self._prefix = key_prefix or settings.cursor_key_prefix

    def key_for(self, handle: str) -> str:
        clean = handle.lstrip("@").lower()
        return f"{self._prefix}{clean}"

    def get(self, handle: str) -> WorkingCursor | None:
        raw = self._client.get(self.key_for(handle))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f"invalid cursor payload for {handle}")
        return WorkingCursor.from_mapping(data)

    def set(self, handle: str, cursor: WorkingCursor) -> None:
        # Intentionally no EX/PX — working cursors must not expire.
        payload = json.dumps(cursor.to_redis_payload(), ensure_ascii=False)
        self._client.set(self.key_for(handle), payload)

    def delete(self, handle: str) -> None:
        self._client.delete(self.key_for(handle))

    def get_many(self, handles: list[str]) -> dict[str, WorkingCursor]:
        result: dict[str, WorkingCursor] = {}
        for handle in handles:
            cursor = self.get(handle)
            if cursor is not None:
                result[handle.lstrip("@").lower()] = cursor
        return result


def connect_redis(redis_url: str) -> Any:
    import redis

    return redis.Redis.from_url(redis_url, decode_responses=True)
