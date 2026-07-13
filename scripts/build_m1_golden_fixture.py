from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.editorial.loader import load_clean_posts_v1

run = Path("data/x_watchlist_runs/20260713T165938-61722273")
out = Path("fixtures/m1_golden_run")
out.mkdir(parents=True, exist_ok=True)

clean = json.loads((run / "clean_posts.json").read_text(encoding="utf-8"))
coverage = json.loads((run / "coverage.json").read_text(encoding="utf-8"))
account_results = json.loads((run / "account_results.json").read_text(encoding="utf-8"))
raw = json.loads((run / "raw_posts.json").read_text(encoding="utf-8"))
run_meta = json.loads((run / "run.json").read_text(encoding="utf-8"))

slim_posts = []
for post in clean["posts"]:
    item = dict(post)
    item.pop("engagement", None)
    slim_posts.append(item)

clean_fixture = {
    "schema_version": clean["schema_version"],
    "run_id": clean["run_id"],
    "window_start": clean["window_start"],
    "window_end": clean["window_end"],
    "posts": slim_posts,
}

by_handle: dict[str, list[dict]] = defaultdict(list)
for item in raw:
    handle = item.get("_watchlist_handle") or item.get("author_handle") or "unknown"
    by_handle[str(handle)].append(item)

drop_keys = {"reply_label", "repost_label", "like_label", "view_label"}
sample: list[dict] = []
for _handle, items in by_handle.items():
    for item in items[:2]:
        sample.append({k: v for k, v in item.items() if k not in drop_keys})

(out / "clean_posts.json").write_text(
    json.dumps(clean_fixture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
(out / "coverage.json").write_text(
    json.dumps(coverage, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
(out / "account_results.json").write_text(
    json.dumps(account_results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
(out / "raw_posts.sample.json").write_text(
    json.dumps(sample, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)

readme = f"""# M1 Golden Run Fixture

Lightweight snapshot for Milestone 2 development. Not a full production archive.

| Field | Value |
|---|---|
| source_run_id | `{clean["run_id"]}` |
| collected_at | `{run_meta.get("started_at", "")}` |
| window | `{clean["window_start"]}` → `{clean["window_end"]}` |
| schema_version | `{clean["schema_version"]}` |
| accounts | {coverage["accounts_enabled"]} enabled, {coverage["accounts_succeeded"]} succeeded, {coverage["accounts_failed"]} failed |
| fetch_returned_empty | {coverage.get("accounts_fetch_returned_empty", 0)} ({", ".join(coverage.get("fetch_returned_empty_handles") or []) or "none"}) |
| empty_window | {coverage.get("accounts_empty_window", 0)} |
| clean_posts | {len(slim_posts)} |
| by_source_type | `{json.dumps(coverage.get("by_source_type") or {}, ensure_ascii=False)}` |
| status | `{coverage["status"]}` |

## Files

- `clean_posts.json` — `x-clean-posts/v1` envelope; engagement metrics removed; includes optional media/context fields
- `coverage.json` — run coverage report
- `account_results.json` — per-account success / retained counts
- `raw_posts.sample.json` — up to 2 raw posts per handle; metric labels stripped

## Notes

- Point-in-time sample for Prompt/schema iteration only.
- Do not treat as live current X content.
- Full raw run remains local under `data/` (gitignored).
"""
(out / "README.md").write_text(readme, encoding="utf-8")

loaded = load_clean_posts_v1(out / "clean_posts.json")
blob = "\n".join(path.read_text(encoding="utf-8") for path in out.iterdir())
sensitive_patterns = [
    r"auth_token\s*[:=]",
    r"\bct0\s*[:=]",
    r"password\s*[:=]",
    r"codex-x-news-agent",
    r"C:\\\\Users\\\\90556",
    r"C:/Users/90556",
]
hits = [pat for pat in sensitive_patterns if re.search(pat, blob, re.I)]
sizes = {path.name: path.stat().st_size for path in out.iterdir()}
print("posts", len(loaded["posts"]))
print("sizes", sizes)
print("total_bytes", sum(sizes.values()))
print("sensitive_hits", hits)
assert not hits, f"sensitive data found: {hits}"
print("fixture_ok")
