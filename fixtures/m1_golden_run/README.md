# M1 Golden Run Fixture

Lightweight snapshot for Milestone 2 development. Not a full production archive.

| Field | Value |
|---|---|
| source_run_id | `20260713T165938-61722273` |
| collected_at | `2026-07-13T16:59:38+08:00` |
| window | `2026-07-10T16:59:38+08:00` → `2026-07-13T16:59:38+08:00` |
| schema_version | `x-clean-posts/v1` |
| accounts | 35 enabled, 34 succeeded, 1 failed |
| fetch_returned_empty | 1 (TencentHunyuan) |
| empty_window | 14 |
| clean_posts | 177 |
| by_source_type | `{"leak": 46, "employee": 52, "leak_and_opinion": 34, "technical_analyst": 13, "official": 20, "analyst": 12}` |
| status | `partial` |

## Files

- `clean_posts.json` — `x-clean-posts/v1` envelope; engagement metrics removed; includes optional media/context fields
- `coverage.json` — run coverage report
- `account_results.json` — per-account success / retained counts
- `raw_posts.sample.json` — up to 2 raw posts per handle; metric labels stripped

## Notes

- Point-in-time sample for Prompt/schema iteration only.
- Do not treat as live current X content.
- Full raw run remains local under `data/` (gitignored).
