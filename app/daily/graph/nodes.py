from __future__ import annotations

from pathlib import Path
from typing import Any

from app.daily.config import DailySettings
from app.daily.enums import CollectionStatus
from app.daily.graph.state import DailyGraphState
from app.daily.versions import freeze_run_versions
from app.x_watchlist.config import filter_accounts, load_watchlist


def node_acquire_run_lock(state: DailyGraphState) -> dict[str, Any]:
    """Real PG advisory lock is acquired by the runner wrapper when enabled."""
    return {"lock_acquired": True, "errors": list(state.get("errors") or [])}


def node_initialize_run(state: DailyGraphState) -> dict[str, Any]:
    settings = DailySettings.from_env()
    frozen = freeze_run_versions(settings, settings.watchlist_path)
    meta = dict(state.get("meta") or {})
    meta["frozen_versions"] = frozen
    run_id = state.get("run_id")
    return {
        "run_id": run_id,
        "meta": meta,
        "accept_partial": bool(state.get("accept_partial", False)),
        "accept_gap": bool(state.get("accept_gap", False)),
    }


def node_load_watchlist(state: DailyGraphState) -> dict[str, Any]:
    settings = DailySettings.from_env()
    path = Path(settings.watchlist_path)
    config = load_watchlist(path)
    accounts = filter_accounts(config, handles=None, enabled_only=True)
    handles = [a.handle for a in accounts]
    meta = dict(state.get("meta") or {})
    meta["watchlist_path"] = str(path)
    meta["account_count"] = len(handles)
    return {"watchlist_handles": handles, "meta": meta}


def node_collect_accounts_loop(state: DailyGraphState) -> dict[str, Any]:
    """M3b: per-account collect is invoked by runner when not dry_run.

    In graph dry-run mode we only record intent; runner fills results when
    `run_collect=True`.
    """
    dry = bool(state.get("dry_run", True))
    precomputed = (state.get("meta") or {}).get("collect_loop_result")
    if precomputed:
        return {
            "collection_complete": bool(precomputed.get("collection_complete")),
            "cursor_sync_complete": bool(precomputed.get("cursor_sync_complete")),
            "account_statuses": dict(precomputed.get("account_statuses") or {}),
            "new_post_count": int(precomputed.get("new_post_count") or 0),
            "paused_reason": precomputed.get("paused_reason"),
            "meta": {
                **dict(state.get("meta") or {}),
                "collect_stub": False,
                "dry_run": dry,
            },
        }
    return {
        "collection_complete": True if dry else False,
        "account_statuses": {},
        "new_post_count": 0,
        "meta": {
            **dict(state.get("meta") or {}),
            "collect_stub": True,
            "dry_run": dry,
        },
    }


def node_cursor_sync_gate(state: DailyGraphState) -> dict[str, Any]:
    complete = bool(state.get("cursor_sync_complete", True))
    meta = dict(state.get("meta") or {})
    if not complete:
        meta["cursor_sync_gate"] = "pending"
        return {
            "cursor_sync_complete": False,
            "paused_reason": state.get("paused_reason") or "cursor_sync_pending",
            "meta": meta,
        }
    meta["cursor_sync_gate"] = "complete"
    return {"cursor_sync_complete": True, "meta": meta}


def node_collection_gate(state: DailyGraphState) -> dict[str, Any]:
    statuses = dict(state.get("account_statuses") or {})
    blocking = [
        f"{handle}:{status}"
        for handle, status in statuses.items()
        if status
        in {
            CollectionStatus.PAGE_INCOMPLETE.value,
            CollectionStatus.SAFETY_LIMIT_REACHED.value,
            CollectionStatus.KNOWN_DATA_GAP.value,
            CollectionStatus.FAILED_RETRYABLE.value,
            CollectionStatus.FAILED_PERMANENT.value,
        }
        and not (
            status == CollectionStatus.KNOWN_DATA_GAP.value and state.get("accept_gap")
        )
    ]
    if blocking and not state.get("collection_complete"):
        return {
            "collection_complete": False,
            "paused_reason": "blocking_accounts:" + ",".join(blocking),
        }
    if state.get("paused_reason") and not state.get("collection_complete"):
        return {
            "collection_complete": False,
            "paused_reason": state.get("paused_reason"),
        }
    return {"collection_complete": True, "paused_reason": None}


def node_freeze_candidate_snapshot(state: DailyGraphState) -> dict[str, Any]:
    precomputed = (state.get("meta") or {}).get("candidate_snapshot_result")
    if precomputed:
        return {
            "candidate_count": int(precomputed.get("candidate_count") or 0),
            "meta": {
                **dict(state.get("meta") or {}),
                "candidate_snapshot": precomputed,
            },
        }
    # Dry-run without DB: treat new_post_count as candidate count.
    count = int(state.get("new_post_count") or 0)
    return {
        "candidate_count": count,
        "meta": {
            **dict(state.get("meta") or {}),
            "candidate_snapshot": {"frozen": True, "candidate_count": count, "dry": True},
        },
    }


def node_summarize_all_candidates(state: DailyGraphState) -> dict[str, Any]:
    precomputed = (state.get("meta") or {}).get("summarize_result")
    if precomputed:
        return {
            "summary_complete": bool(precomputed.get("gate_complete", False)),
            "summary_coverage": precomputed.get("summary_coverage"),
            "missing_summary_post_ids": list(precomputed.get("missing_post_ids") or []),
            "meta": {
                **dict(state.get("meta") or {}),
                "summarize": precomputed,
            },
        }
    # Dry stub: pretend all candidates summarized.
    count = int(state.get("candidate_count") or 0)
    return {
        "summary_complete": True,
        "summary_coverage": f"{count} / {count}",
        "missing_summary_post_ids": [],
        "meta": {
            **dict(state.get("meta") or {}),
            "summarize": {"dry_stub": True, "succeeded": count},
        },
    }


def node_summary_gate(state: DailyGraphState) -> dict[str, Any]:
    precomputed = (state.get("meta") or {}).get("summary_gate_result")
    accept_partial = bool(state.get("accept_partial", False))
    if precomputed:
        complete = bool(precomputed.get("complete"))
        paused = bool(precomputed.get("paused"))
        should_retry = bool(precomputed.get("should_retry"))
        if should_retry and not accept_partial:
            return {
                "summary_complete": False,
                "paused_reason": "summary_retryable",
                "summary_coverage": precomputed.get("summary_coverage"),
                "missing_summary_post_ids": list(precomputed.get("missing_post_ids") or []),
            }
        if paused and not complete:
            return {
                "summary_complete": False,
                "paused_reason": precomputed.get("reason") or "summary_paused",
                "summary_coverage": precomputed.get("summary_coverage"),
                "missing_summary_post_ids": list(precomputed.get("missing_post_ids") or []),
            }
        return {
            "summary_complete": complete,
            "paused_reason": None if complete else state.get("paused_reason"),
            "summary_coverage": precomputed.get("summary_coverage"),
            "missing_summary_post_ids": list(precomputed.get("missing_post_ids") or []),
            "meta": {
                **dict(state.get("meta") or {}),
                "selection_status": precomputed.get("selection_status"),
            },
        }

    # Without precomputed gate: trust summarize node.
    if state.get("summary_complete"):
        return {
            "summary_complete": True,
            "paused_reason": None,
            "summary_coverage": state.get("summary_coverage"),
            "missing_summary_post_ids": list(state.get("missing_summary_post_ids") or []),
        }
    return {
        "summary_complete": False,
        "paused_reason": "summary_incomplete",
        "summary_coverage": state.get("summary_coverage"),
        "missing_summary_post_ids": list(state.get("missing_summary_post_ids") or []),
    }


def node_evaluate_all_candidates(state: DailyGraphState) -> dict[str, Any]:
    if state.get("summary_complete") is False:
        return {
            "evaluation_complete": False,
            "paused_reason": state.get("paused_reason"),
        }
    precomputed = (state.get("meta") or {}).get("evaluate_result")
    gate = (state.get("meta") or {}).get("evaluation_gate_result")
    if precomputed is not None:
        complete = bool((gate or {}).get("complete", False))
        return {
            "evaluation_complete": complete,
            "meta": {
                **dict(state.get("meta") or {}),
                "evaluate": precomputed,
                "evaluation_coverage": (gate or {}).get("evaluation_coverage"),
            },
        }
    return {
        "evaluation_complete": True,
        "meta": {**dict(state.get("meta") or {}), "evaluate": {"dry_stub": True}},
    }


def node_evaluation_gate(state: DailyGraphState) -> dict[str, Any]:
    if state.get("summary_complete") is False:
        return {
            "evaluation_complete": False,
            "paused_reason": state.get("paused_reason"),
        }
    precomputed = (state.get("meta") or {}).get("evaluation_gate_result")
    accept_partial = bool(state.get("accept_partial", False))
    if precomputed:
        complete = bool(precomputed.get("complete"))
        paused = bool(precomputed.get("paused"))
        should_retry = bool(precomputed.get("should_retry"))
        if should_retry and not accept_partial:
            return {
                "evaluation_complete": False,
                "paused_reason": "evaluation_retryable",
            }
        if paused and not complete:
            return {
                "evaluation_complete": False,
                "paused_reason": precomputed.get("reason") or "evaluation_paused",
            }
        return {
            "evaluation_complete": complete,
            "paused_reason": None if complete else state.get("paused_reason"),
            "meta": {
                **dict(state.get("meta") or {}),
                "evaluation_coverage": precomputed.get("evaluation_coverage"),
                "selection_status": precomputed.get("selection_status")
                or (state.get("meta") or {}).get("selection_status"),
            },
        }
    if state.get("evaluation_complete"):
        return {"evaluation_complete": True, "paused_reason": None}
    return {
        "evaluation_complete": False,
        "paused_reason": "evaluation_incomplete",
    }


def node_select_top_k(state: DailyGraphState) -> dict[str, Any]:
    if state.get("summary_complete") is False or state.get("evaluation_complete") is False:
        return {
            "meta": dict(state.get("meta") or {}),
            "paused_reason": state.get("paused_reason"),
        }
    precomputed = (state.get("meta") or {}).get("selection_result")
    if precomputed:
        return {
            "meta": {
                **dict(state.get("meta") or {}),
                "top_k_post_ids": list(precomputed.get("top_k_post_ids") or []),
                "top_k": precomputed.get("top_k"),
            }
        }
    return {"meta": {**dict(state.get("meta") or {}), "top_k_stub": True}}


def node_editorial_final_selection(state: DailyGraphState) -> dict[str, Any]:
    if state.get("summary_complete") is False or state.get("evaluation_complete") is False:
        return {
            "selection_complete": False,
            "paused_reason": state.get("paused_reason"),
        }
    precomputed = (state.get("meta") or {}).get("selection_result")
    if precomputed:
        return {
            "selection_complete": precomputed.get("status") == "success",
            "meta": {
                **dict(state.get("meta") or {}),
                "selected_post_ids": list(precomputed.get("selected_post_ids") or []),
            },
        }
    # Dry path without selection_result: mark complete only if evaluation completed.
    return {"selection_complete": bool(state.get("evaluation_complete", True))}


def node_persist_selection(state: DailyGraphState) -> dict[str, Any]:
    if state.get("summary_complete") is False or state.get("evaluation_complete") is False:
        return {
            "selection_complete": False,
            "paused_reason": state.get("paused_reason"),
        }
    precomputed = (state.get("meta") or {}).get("selection_result")
    if precomputed:
        return {
            "selection_complete": precomputed.get("status") == "success",
            "meta": {
                **dict(state.get("meta") or {}),
                "selection_run_id": precomputed.get("selection_run_id"),
                # Explicit: selection never implies published.
                "publication_note": "selection_items.publication_status stays unpublished",
            },
        }
    return {"selection_complete": bool(state.get("selection_complete", True))}



def node_finalize_run(state: DailyGraphState) -> dict[str, Any]:
    return {
        "meta": {**dict(state.get("meta") or {}), "finalized": True},
        "paused_reason": state.get("paused_reason"),
    }


def node_release_run_lock(state: DailyGraphState) -> dict[str, Any]:
    return {"lock_acquired": False}
