from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.daily.graph import nodes
from app.daily.graph.state import DailyGraphState


def build_daily_graph(*, checkpointer: Any | None = None) -> Any:
    """Daily harness. Optional checkpointer enables thread-scoped resume (M3e)."""
    graph = StateGraph(DailyGraphState)

    graph.add_node("acquire_run_lock", nodes.node_acquire_run_lock)
    graph.add_node("initialize_run", nodes.node_initialize_run)
    graph.add_node("load_watchlist", nodes.node_load_watchlist)
    graph.add_node("collect_accounts_loop", nodes.node_collect_accounts_loop)
    graph.add_node("cursor_sync_gate", nodes.node_cursor_sync_gate)
    graph.add_node("collection_gate", nodes.node_collection_gate)
    graph.add_node("freeze_candidate_snapshot", nodes.node_freeze_candidate_snapshot)
    graph.add_node("summarize_all_candidates", nodes.node_summarize_all_candidates)
    graph.add_node("summary_gate", nodes.node_summary_gate)
    graph.add_node("evaluate_all_candidates", nodes.node_evaluate_all_candidates)
    graph.add_node("evaluation_gate", nodes.node_evaluation_gate)
    graph.add_node("select_top_k", nodes.node_select_top_k)
    graph.add_node("editorial_final_selection", nodes.node_editorial_final_selection)
    graph.add_node("persist_selection", nodes.node_persist_selection)
    graph.add_node("finalize_run", nodes.node_finalize_run)
    graph.add_node("release_run_lock", nodes.node_release_run_lock)

    graph.add_edge(START, "acquire_run_lock")
    graph.add_edge("acquire_run_lock", "initialize_run")
    graph.add_edge("initialize_run", "load_watchlist")
    graph.add_edge("load_watchlist", "collect_accounts_loop")
    graph.add_edge("collect_accounts_loop", "cursor_sync_gate")
    graph.add_edge("cursor_sync_gate", "collection_gate")
    graph.add_edge("collection_gate", "freeze_candidate_snapshot")
    graph.add_edge("freeze_candidate_snapshot", "summarize_all_candidates")
    graph.add_edge("summarize_all_candidates", "summary_gate")
    graph.add_edge("summary_gate", "evaluate_all_candidates")
    graph.add_edge("evaluate_all_candidates", "evaluation_gate")
    graph.add_edge("evaluation_gate", "select_top_k")
    graph.add_edge("select_top_k", "editorial_final_selection")
    graph.add_edge("editorial_final_selection", "persist_selection")
    graph.add_edge("persist_selection", "finalize_run")
    graph.add_edge("finalize_run", "release_run_lock")
    graph.add_edge("release_run_lock", END)

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()


def run_daily_graph(
    *,
    dry_run: bool = True,
    run_id: str | None = None,
    accept_gap: bool = False,
    accept_partial: bool = False,
    collect_loop_result: dict[str, Any] | None = None,
    summary_phase_result: dict[str, Any] | None = None,
    selection_phase_result: dict[str, Any] | None = None,
) -> DailyGraphState:
    app = build_daily_graph()
    meta: dict[str, Any] = {}
    if collect_loop_result is not None:
        meta["collect_loop_result"] = collect_loop_result
    if summary_phase_result is not None:
        meta.update(
            {
                "candidate_snapshot_result": summary_phase_result.get(
                    "candidate_snapshot_result"
                ),
                "summarize_result": summary_phase_result.get("summarize_result"),
                "summary_gate_result": summary_phase_result.get("summary_gate_result"),
            }
        )
    if selection_phase_result is not None:
        meta.update(
            {
                "evaluate_result": selection_phase_result.get("evaluate_result"),
                "evaluation_gate_result": selection_phase_result.get(
                    "evaluation_gate_result"
                ),
                "selection_result": selection_phase_result.get("selection_result"),
            }
        )
    result = app.invoke(
        {
            "dry_run": dry_run,
            "run_id": run_id,
            "accept_gap": accept_gap,
            "accept_partial": accept_partial,
            "errors": [],
            "meta": meta,
        }
    )
    return result  # type: ignore[return-value]
