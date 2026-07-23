"""Smoke-test a few X profiles via MCP after collect fixes."""

from __future__ import annotations

import asyncio
import json
import sys

from app.x_watchlist.mcp_client import MCPClientError, XNewsMCPClient


HANDLES = [
    "OpenAI",  # official baseline
    "sama",  # employee / high-profile
    "scaling01",  # often analyst-ish; may 404 — replaced below if needed
]


async def probe(handle: str) -> dict:
    async with XNewsMCPClient() as client:
        try:
            result = await client.profile_posts(handle, limit=5, offset=0)
            posts = result.get("posts") or []
            return {
                "handle": handle,
                "ok": True,
                "count": result.get("count", len(posts)),
                "first_screen_empty": result.get("first_screen_empty"),
                "scroll_stop_reason": result.get("scroll_stop_reason"),
                "sample_ids": [p.get("post_id") for p in posts[:3] if isinstance(p, dict)],
            }
        except MCPClientError as exc:
            return {
                "handle": handle,
                "ok": False,
                "reason_code": exc.reason_code,
                "error": str(exc),
            }


async def main(handles: list[str]) -> int:
    results = []
    for handle in handles:
        print(f"probing @{handle} ...", flush=True)
        row = await probe(handle)
        results.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        await asyncio.sleep(1.5)

    ok = sum(1 for r in results if r.get("ok") and (r.get("count") or 0) > 0)
    empty = [r["handle"] for r in results if r.get("ok") and not (r.get("count") or 0)]
    failed = [r["handle"] for r in results if not r.get("ok")]
    print(
        json.dumps(
            {"summary": {"with_posts": ok, "empty_ok": empty, "failed": failed}},
            ensure_ascii=False,
        ),
        flush=True,
    )
    # Pass if baseline OpenAI works and at least one other returns posts or soft-empty without hard fail.
    baseline = next((r for r in results if r["handle"].lower() == "openai"), None)
    if not baseline or not baseline.get("ok") or not (baseline.get("count") or 0):
        return 1
    return 0 if not failed else 1


if __name__ == "__main__":
    handles = sys.argv[1:] or [
        "OpenAI",
        "AnthropicAI",
        "karpathy",
    ]
    raise SystemExit(asyncio.run(main(handles)))
