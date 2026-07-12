# M1 Golden Run Fixture

Lightweight snapshot for Milestone 2 development. Not a full production archive.

| Field | Value |
|---|---|
| source_run_id | `20260713T002854-ab9c7c70` |
| collected_at | 2026-07-13T00:28:54+08:00 (run start) |
| window | `2026-07-10T00:28:54+08:00` → `2026-07-13T00:28:54+08:00` |
| schema_version | `x-clean-posts/v1` |
| accounts | 35 enabled, 35 succeeded, 0 failed |
| clean_posts | 63 |
| status | `success` |

## Files

- `clean_posts.json` — `x-clean-posts/v1` envelope; engagement metrics removed
- `coverage.json` — run coverage report
- `account_results.json` — per-account success / retained counts
- `raw_posts.sample.json` — up to 2 raw posts per handle; metric labels stripped

## Notes

- Point-in-time sample for Prompt/schema iteration only.
- Do not treat as live current X content.
- Full raw run remains local under `data/` (gitignored).
