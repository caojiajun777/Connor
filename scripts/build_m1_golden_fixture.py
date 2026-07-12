from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.x_watchlist.test_clean_posts_contract import load_clean_posts_v1

run = Path("data/x_watchlist_runs/20260713T002854-ab9c7c70")
out = Path("fixtures/m1_golden_run")
out.mkdir(parents=True, exist_ok=True)

clean = json.loads((run / "clean_posts.json").read_text(encoding="utf-8"))
coverage = json.loads((run / "coverage.json").read_text(encoding="utf-8"))
account_results = json.loads((run / "account_results.json").read_text(encoding="utf-8"))
raw = json.loads((run / "raw_posts.json").read_text(encoding="utf-8"))

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
| collected_at | 2026-07-13T00:28:54+08:00 (run start) |
| window | `{clean["window_start"]}` → `{clean["window_end"]}` |
| schema_version | `{clean["schema_version"]}` |
| accounts | {coverage["accounts_enabled"]} enabled, {coverage["accounts_succeeded"]} succeeded, {coverage["accounts_failed"]} failed |
| clean_posts | {len(slim_posts)} |
| status | `{coverage["status"]}` |

## Files

- `clean_posts.json` — `x-clean-posts/v1` envelope; engagement metrics removed
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
    r"auth_token",
    r"\bct0\b",
    r"password",
    r"SECRET",
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
