# Connor Console Phase 1 — Schema / API Gap Analysis

**Date:** 2026-07-14  
**Baseline:** `v0.3.0-daily-core`

## Existing (keep readonly)

| Asset | Notes |
|-------|--------|
| [`app/daily/api.py`](../app/daily/api.py) | `GET /runs`, `/runs/{id}`, `/selection`, `/evaluations` — not under `/api/console`, thin DTOs |
| Production tables | `runs`, `account_runs`, `posts`, `run_posts`, `post_summaries`, `post_evaluations`, `selection_*` |
| `publication_status` | Exists on `selection_items`; Console **must not** mutate |
| Schema init | `Base.metadata.create_all` via `init_schema` — **no Alembic yet** |

## Gaps for Phase 1

| Need | Gap |
|------|-----|
| Annotation tables | Missing `annotation_runs` / `annotation_items` |
| Console API namespace | Need `/api/console/*` with richer candidate payload (post + summary + eval + selection) |
| Versions / errors endpoints | Missing dedicated routes (data exists on `runs` / `account_runs` / task rows) |
| Write path | No annotation create/patch/complete/reopen/diff |
| Optimistic lock | Need `annotation_items.version` |
| Frontend | No `frontend/` console app |
| Alembic | Deferred to follow-up; Phase 1 uses `create_all` for new tables on `connor_daily` |

## Immutability checks (tests must assert)

Creating/updating annotations must not change row counts or fields on:

`post_evaluations`, `selection_items`, `selection_runs`, `post_summaries`, `posts`.
