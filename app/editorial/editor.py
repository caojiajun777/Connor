from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from app.editorial.llm_client import OpenAICompatibleClient
from app.editorial.schemas import DEFAULT_TOP_N, LLMEditorResponse, PROMPT_VERSION


class EditorialLLM(Protocol):
    def complete_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        ...


def prompt_dir() -> Path:
    return Path(__file__).resolve().parent / "prompts"


def load_prompt(version: str = PROMPT_VERSION) -> str:
    path = prompt_dir() / f"{version}_editorial_system.md"
    if not path.exists():
        raise FileNotFoundError(f"Editorial prompt not found: {path}")
    return path.read_text(encoding="utf-8")


def build_user_prompt(
    *,
    source_run_id: str,
    window_start: str,
    window_end: str,
    posts: list[dict[str, Any]],
    top_n: int = DEFAULT_TOP_N,
) -> str:
    payload = {
        "source_run_id": source_run_id,
        "window_start": window_start,
        "window_end": window_end,
        "post_count": len(posts),
        "top_n": top_n,
        "posts": posts,
    }
    return (
        "Rank the following X watchlist posts by cognitive value for AI-frontier readers.\n"
        "Parse every post, extract core_info with uncertainty preserved, then produce a complete "
        f"unique ranking. The daily shortlist is the top {top_n} of that ranking.\n"
        "Return JSON only, matching the required schema.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def run_editorial_llm(
    *,
    source_run_id: str,
    window_start: str,
    window_end: str,
    posts: list[dict[str, Any]],
    client: EditorialLLM | None = None,
    prompt_version: str = PROMPT_VERSION,
    top_n: int = DEFAULT_TOP_N,
) -> LLMEditorResponse:
    system_prompt = load_prompt(prompt_version)
    user_prompt = build_user_prompt(
        source_run_id=source_run_id,
        window_start=window_start,
        window_end=window_end,
        posts=posts,
        top_n=top_n,
    )
    llm = client or OpenAICompatibleClient()
    raw = llm.complete_json(system_prompt=system_prompt, user_prompt=user_prompt)
    return LLMEditorResponse.model_validate(raw)


def mock_editorial_response(posts: list[dict[str, Any]]) -> LLMEditorResponse:
    """Deterministic offline ranker for dry-run / tests (no LLM call).

    Heuristic: longer, more specific text ranks higher (proxy for specificity),
    then newer published_at. Every input post gets exactly one ranked slot.
    """

    def sort_key(post: dict[str, Any]) -> tuple[int, str]:
        text = (post.get("text") or "").strip()
        return (len(text), str(post.get("published_at") or ""))

    ordered = sorted(posts, key=sort_key, reverse=True)
    items: list[dict[str, Any]] = []
    for rank, post in enumerate(ordered, start=1):
        text = (post.get("text") or "").strip()
        post_id = str(post.get("post_id") or "")
        title = text[:80] if text else f"post {post_id}"
        core = text[:280] if text else "(empty text)"
        specificity = "high" if len(text) >= 120 else "medium" if len(text) >= 40 else "low"
        items.append(
            {
                "post_id": post_id,
                "rank": rank,
                "title": title,
                "core_info": core,
                "attribution": "mock-dry-run",
                "caveats": "",
                "ranking_rationale": (
                    f"mock rank {rank}: longer/more specific text first "
                    f"(len={len(text)}, specificity≈{specificity})"
                ),
                "signals": {
                    "impact": "medium",
                    "novelty": "medium",
                    "frontier": "medium",
                    "specificity": specificity,
                },
                "bundled_post_ids": [],
            }
        )
    return LLMEditorResponse.model_validate({"items": items, "light_groups": []})
