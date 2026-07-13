from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.editorial.editor import mock_editorial_response, run_editorial_llm
from app.editorial.loader import compress_posts_for_llm, load_clean_posts_v1
from app.editorial.llm_client import LLMSettings, OpenAICompatibleClient
from app.editorial.schemas import (
    DEFAULT_TOP_N,
    EDITORIAL_PICKS_SCHEMA_VERSION,
    EditorialPicksEnvelope,
    EditorialTrace,
    PROMPT_VERSION,
)
from app.editorial.validator import validate_editorial_response


@dataclass
class EditorialOptions:
    input_path: Path
    output_dir: Path
    dry_run: bool = False
    prompt_version: str = PROMPT_VERSION
    top_n: int = DEFAULT_TOP_N
    run_id: str | None = None


@dataclass
class EditorialRunResult:
    run_id: str
    output_dir: Path
    picks_path: Path
    trace_path: Path
    ranked_count: int
    top20_count: int
    input_post_count: int
    status: str

    # Backward-compatible aliases for older callers/tests.
    @property
    def events_path(self) -> Path:
        return self.picks_path

    @property
    def event_count(self) -> int:
        return self.ranked_count


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_editorial(options: EditorialOptions) -> EditorialRunResult:
    clean = load_clean_posts_v1(options.input_path)
    posts = clean["posts"]
    source_run_id = str(clean["run_id"])
    compressed = compress_posts_for_llm(posts)
    known_posts = {str(post["post_id"]): post for post in posts}

    run_id = options.run_id or datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    out_dir = options.output_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if options.dry_run:
        raw_response = mock_editorial_response(compressed)
        model_name = "mock-dry-run"
        raw_model_payload = raw_response.model_dump()
        reasoning_content = None
    else:
        settings = LLMSettings.from_env()
        client = OpenAICompatibleClient(settings)
        raw_response = run_editorial_llm(
            source_run_id=source_run_id,
            window_start=str(clean["window_start"]),
            window_end=str(clean["window_end"]),
            posts=compressed,
            prompt_version=options.prompt_version,
            top_n=options.top_n,
            client=client,
        )
        model_name = settings.model
        raw_model_payload = {
            "parsed": raw_response.model_dump(),
            "usage": (client.last_raw_response or {}).get("usage"),
        }
        reasoning_content = client.last_reasoning_content

    validated = validate_editorial_response(
        raw_response,
        known_posts=known_posts,
        top_n=options.top_n,
    )

    envelope = EditorialPicksEnvelope(
        schema_version=EDITORIAL_PICKS_SCHEMA_VERSION,
        source_run_id=source_run_id,
        prompt_version=options.prompt_version,
        top_n=options.top_n,
        ranked_items=validated.ranked_items,
        top20=validated.top20,
    )
    trace = EditorialTrace(
        source_run_id=source_run_id,
        prompt_version=options.prompt_version,
        model=model_name,
        input_post_count=len(posts),
        ranked_count=len(validated.ranked_items),
        top_n=options.top_n,
        post_traces=validated.post_traces,
        light_groups=validated.light_groups,
        validation_warnings=validated.warnings,
        raw_model_response=raw_model_payload,
    )

    picks_path = out_dir / "picks.json"
    trace_path = out_dir / "editorial_trace.json"
    _write_json(picks_path, envelope.model_dump())
    _write_json(trace_path, trace.model_dump())
    if reasoning_content:
        (out_dir / "reasoning.txt").write_text(reasoning_content, encoding="utf-8")
    _write_json(
        out_dir / "editorial_run.json",
        {
            "run_id": run_id,
            "status": "dry_run" if options.dry_run else "success",
            "source_run_id": source_run_id,
            "input_path": str(options.input_path),
            "input_post_count": len(posts),
            "ranked_count": len(validated.ranked_items),
            "top20_count": len(validated.top20),
            "prompt_version": options.prompt_version,
            "schema_version": EDITORIAL_PICKS_SCHEMA_VERSION,
            "model": model_name,
            "top_n": options.top_n,
            "coverage_ok": len(validated.missing_post_ids) == 0
            and len(validated.covered_post_ids) == len(posts),
            "reasoning_effort": None if options.dry_run else "max",
        },
    )

    return EditorialRunResult(
        run_id=run_id,
        output_dir=out_dir,
        picks_path=picks_path,
        trace_path=trace_path,
        ranked_count=len(validated.ranked_items),
        top20_count=len(validated.top20),
        input_post_count=len(posts),
        status="dry_run" if options.dry_run else "success",
    )
