"""Console annotation services — never mutate production evaluation/selection rows."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.daily.db.models import (
    AnnotationItem,
    AnnotationRun,
    Post,
    PostEvaluation,
    PostSummary,
    Run,
    RunPost,
    SelectionItem,
    SelectionRun,
)
from app.daily.enums import (
    ALL_REASON_CODES,
    DEFAULT_ANNOTATION_POLICY_VERSION,
    DEPRECATED_REASON_CODES,
    HIDDEN_REASON_CODES,
    UI_EXCLUDE_REASON_CODES,
    UI_EXCLUDE_REASON_ORDER,
    UI_INCLUDE_REASON_CODES,
    UI_INCLUDE_REASON_ORDER,
    AnnotationRunStatus,
    HumanLabel,
    SelectionItemStatus,
    TaskStatus,
)
from app.daily.ranking import RankableEvaluation, deterministic_top_k


class AnnotationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def annotation_run_to_dict(row: AnnotationRun) -> dict[str, Any]:
    return {
        "annotation_run_id": row.id,
        "source_run_id": row.source_run_id,
        "annotation_policy_version": row.annotation_policy_version,
        "status": row.status,
        "annotator": row.annotator,
        "total_items": row.total_items,
        "reviewed_items": row.reviewed_items,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "completed_at": _iso(row.completed_at),
    }


def annotation_item_to_dict(row: AnnotationItem) -> dict[str, Any]:
    return {
        "annotation_item_id": row.id,
        "annotation_run_id": row.annotation_run_id,
        "post_id": row.post_id,
        "summary_id": row.summary_id,
        "evaluation_id": row.evaluation_id,
        "machine_selected": row.machine_selected,
        "machine_rank": row.machine_rank,
        "machine_top_k_rank": row.machine_top_k_rank,
        "human_label": row.human_label,
        "human_rank": row.human_rank,
        "confidence": row.confidence,
        "reason_codes": list(row.reason_codes or []),
        "note": row.note,
        "version": row.version,
        "reviewed_at": _iso(row.reviewed_at),
        "updated_at": _iso(row.updated_at),
    }


def _recount_reviewed(session: Session, annotation_run: AnnotationRun) -> None:
    # Session factory uses autoflush=False; flush so SQL count sees pending label writes.
    session.flush()
    count = session.scalar(
        select(func.count())
        .select_from(AnnotationItem)
        .where(
            AnnotationItem.annotation_run_id == annotation_run.id,
            AnnotationItem.human_label.is_not(None),
        )
    )
    annotation_run.reviewed_items = int(count or 0)
    annotation_run.updated_at = _utcnow()


def create_annotation_run(
    session: Session,
    *,
    source_run_id: str,
    annotation_policy_version: str = DEFAULT_ANNOTATION_POLICY_VERSION,
    annotator: str | None = None,
) -> AnnotationRun:
    run = session.get(Run, source_run_id)
    if run is None:
        raise AnnotationError("run_not_found", f"unknown source_run_id: {source_run_id}")

    existing = session.execute(
        select(AnnotationRun).where(
            AnnotationRun.source_run_id == source_run_id,
            AnnotationRun.annotation_policy_version == annotation_policy_version,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AnnotationError(
            "annotation_run_exists",
            "annotation run already exists for this source_run_id and policy version",
        )

    candidates = list(
        session.scalars(
            select(RunPost).where(RunPost.run_id == source_run_id, RunPost.is_candidate.is_(True))
        ).all()
    )
    if not candidates:
        raise AnnotationError("no_candidates", "source run has no candidates")

    evaluations = {
        e.post_id: e
        for e in session.scalars(
            select(PostEvaluation).where(
                PostEvaluation.run_id == source_run_id,
                PostEvaluation.status == TaskStatus.SUCCESS.value,
            )
        ).all()
    }
    # Accept-partial runs may leave media-only / failed-summary candidates without
    # evaluations. Annotate the evaluable subset instead of blocking the whole run.
    annotatable = [c for c in candidates if c.post_id in evaluations]
    if not annotatable:
        raise AnnotationError(
            "evaluations_incomplete",
            "no candidates have successful evaluations to annotate",
        )

    posts = {
        p.post_id: p
        for p in session.scalars(
            select(Post).where(Post.post_id.in_([c.post_id for c in annotatable]))
        ).all()
    }

    rankables = []
    for post_id, ev in evaluations.items():
        post = posts.get(post_id)
        rankables.append(
            RankableEvaluation(
                post_id=post_id,
                importance_score=float(ev.importance_score or 0.0),
                information_gain_score=float(ev.information_gain_score or 0.0),
                specificity_score=float(ev.specificity_score or 0.0),
                frontier_score=float(ev.frontier_score or 0.0),
                published_at=post.published_at if post else None,
            )
        )
    top_k = deterministic_top_k(rankables, top_k=run.top_k or 50)
    top_k_rank = {item.post_id: idx + 1 for idx, item in enumerate(top_k)}

    sel_run = session.execute(
        select(SelectionRun).where(SelectionRun.run_id == source_run_id)
    ).scalar_one_or_none()
    sel_by_post: dict[str, SelectionItem] = {}
    if sel_run is not None:
        for item in session.scalars(
            select(SelectionItem).where(SelectionItem.selection_run_id == sel_run.id)
        ).all():
            sel_by_post[item.post_id] = item

    annotation = AnnotationRun(
        source_run_id=source_run_id,
        annotation_policy_version=annotation_policy_version,
        status=AnnotationRunStatus.PENDING.value,
        annotator=annotator,
        total_items=len(annotatable),
        reviewed_items=0,
    )
    session.add(annotation)
    session.flush()

    for cand in annotatable:
        ev = evaluations[cand.post_id]
        summary = session.get(PostSummary, ev.summary_id)
        if summary is None or summary.status != TaskStatus.SUCCESS.value:
            raise AnnotationError(
                "summary_missing",
                f"bound summary missing/unsuccessful for post {cand.post_id}",
            )
        if summary.run_id != source_run_id or summary.post_id != cand.post_id:
            raise AnnotationError(
                "summary_run_mismatch",
                f"summary {ev.summary_id} is not bound to this run/post",
            )
        sel = sel_by_post.get(cand.post_id)
        machine_selected = bool(
            sel and sel.selection_status == SelectionItemStatus.SELECTED.value
        )
        session.add(
            AnnotationItem(
                annotation_run_id=annotation.id,
                post_id=cand.post_id,
                summary_id=ev.summary_id,
                evaluation_id=ev.id,
                machine_selected=machine_selected,
                machine_rank=sel.final_rank if sel and machine_selected else None,
                machine_top_k_rank=top_k_rank.get(cand.post_id),
                reason_codes=[],
                version=1,
            )
        )

    try:
        session.flush()
    except IntegrityError as exc:
        raise AnnotationError("integrity_error", str(exc)) from exc
    return annotation


def list_annotation_runs(session: Session, *, limit: int = 50) -> list[AnnotationRun]:
    limit = max(1, min(limit, 200))
    return list(
        session.scalars(
            select(AnnotationRun).order_by(AnnotationRun.created_at.desc()).limit(limit)
        ).all()
    )


def get_annotation_run(session: Session, annotation_run_id: str) -> AnnotationRun:
    row = session.get(AnnotationRun, annotation_run_id)
    if row is None:
        raise AnnotationError("annotation_run_not_found", "annotation run not found")
    return row


def list_annotation_items(session: Session, annotation_run_id: str) -> list[AnnotationItem]:
    get_annotation_run(session, annotation_run_id)
    return list(
        session.scalars(
            select(AnnotationItem)
            .where(AnnotationItem.annotation_run_id == annotation_run_id)
            .order_by(
                AnnotationItem.machine_top_k_rank.asc().nulls_last(),
                AnnotationItem.post_id,
            )
        ).all()
    )


def annotation_meta() -> dict[str, Any]:
    """Console annotation vocabulary (single source of truth for UI)."""
    include = list(UI_INCLUDE_REASON_ORDER)
    exclude = list(UI_EXCLUDE_REASON_ORDER)
    return {
        "policy_version": DEFAULT_ANNOTATION_POLICY_VERSION,
        "human_labels": [m.value for m in HumanLabel],
        "reason_codes": {
            "include": include,
            "exclude": exclude,
        },
        "deprecated_reason_codes": sorted(DEPRECATED_REASON_CODES),
        "validation": {
            "reason_codes_min": 1,
            "reason_codes_soft_max": 3,
            "other_requires_note": True,
            "duplicate_requires_note": True,
        },
        "confidence": {"min": 0.0, "max": 1.0, "step": 0.05, "default": 0.8},
        # Backward-compatible aliases for older clients / fallbacks.
        "labels": [m.value for m in HumanLabel],
        "include_reason_codes": include,
        "exclude_reason_codes": exclude,
        "hidden_reason_codes": sorted(HIDDEN_REASON_CODES),
        "reason_rules": {
            "include_exclude_min": 1,
            "include_exclude_soft_max": 3,
            "other_requires_note": True,
            "duplicate_requires_note": True,
        },
    }


def update_annotation_item(
    session: Session,
    *,
    annotation_run_id: str,
    annotation_item_id: str,
    human_label: str | None = None,
    human_rank: int | None = None,
    confidence: float | None = None,
    reason_codes: list[str] | None = None,
    note: str | None = None,
    expected_version: int | None = None,
    clear_human_rank: bool = False,
) -> AnnotationItem:
    annotation = get_annotation_run(session, annotation_run_id)
    if annotation.status == AnnotationRunStatus.COMPLETED.value:
        raise AnnotationError("annotation_completed", "completed annotation run is read-only")

    item = session.get(AnnotationItem, annotation_item_id)
    if item is None or item.annotation_run_id != annotation_run_id:
        raise AnnotationError("annotation_item_not_found", "annotation item not found")

    if expected_version is not None and item.version != expected_version:
        raise AnnotationError(
            "version_conflict",
            f"expected version {expected_version}, current {item.version}",
        )

    previous_reason_codes = list(item.reason_codes or [])
    reason_codes_provided = reason_codes is not None

    if human_label is not None:
        try:
            HumanLabel(human_label)
        except ValueError as exc:
            raise AnnotationError("invalid_human_label", f"invalid human_label: {human_label}") from exc
        item.human_label = human_label

    if clear_human_rank:
        item.human_rank = None
    elif human_rank is not None:
        if human_rank < 1:
            raise AnnotationError("invalid_human_rank", "human_rank must be >= 1")
        item.human_rank = human_rank

    if confidence is not None:
        if confidence < 0.0 or confidence > 1.0:
            raise AnnotationError("invalid_confidence", "confidence must be in [0, 1]")
        item.confidence = confidence

    if reason_codes is not None:
        bad = [c for c in reason_codes if c not in ALL_REASON_CODES]
        if bad:
            raise AnnotationError("invalid_reason_codes", f"unknown reason_codes: {bad}")
        item.reason_codes = list(reason_codes)

    if note is not None:
        item.note = note

    # If label moved to uncertain/duplicate, force empty reasons when client omitted them
    # but previous row still had reasons (including legacy). Callers should send [].
    if item.human_label in {HumanLabel.UNCERTAIN.value, HumanLabel.DUPLICATE.value}:
        if reason_codes is None and list(item.reason_codes or []):
            raise AnnotationError(
                "invalid_reason_codes",
                f"{item.human_label} must not include reason_codes; send reason_codes=[] when changing label",
            )

    _validate_annotation_payload(
        human_label=item.human_label,
        reason_codes=list(item.reason_codes or []),
        note=item.note,
        previous_reason_codes=previous_reason_codes,
        reason_codes_provided=reason_codes_provided,
    )

    item.version += 1
    item.reviewed_at = _utcnow()
    item.updated_at = _utcnow()

    if annotation.status == AnnotationRunStatus.PENDING.value:
        annotation.status = AnnotationRunStatus.IN_PROGRESS.value
    _recount_reviewed(session, annotation)
    session.flush()
    return item


def _multiset_equal(a: list[str], b: list[str]) -> bool:
    return sorted(a) == sorted(b)


def _validate_annotation_payload(
    *,
    human_label: str | None,
    reason_codes: list[str],
    note: str | None,
    previous_reason_codes: list[str],
    reason_codes_provided: bool,
) -> None:
    """Validate merged annotation fields.

    Legacy deprecated codes (e.g. duplicate_event):
    1. reason_codes omitted from PATCH → previous list kept by caller
    2. provided and multiset-equal to previous → allow (including deprecated)
    3. only other fields changed (omit reasons) → same as (1)
    New introduction / change of deprecated codes → reject.
    """
    if human_label is None:
        return
    note_text = (note or "").strip()
    legacy_unchanged = _multiset_equal(reason_codes, previous_reason_codes)

    if reason_codes_provided and not legacy_unchanged:
        introduced = [c for c in reason_codes if c in DEPRECATED_REASON_CODES]
        if introduced:
            raise AnnotationError(
                "deprecated_reason_code",
                f"deprecated reason_codes cannot be newly introduced or changed: {introduced}",
            )

    def _codes_allowed_for_label(ui_set: frozenset[str]) -> None:
        for c in reason_codes:
            if c in ui_set:
                continue
            if c in DEPRECATED_REASON_CODES and legacy_unchanged:
                continue
            raise AnnotationError(
                "invalid_reason_codes",
                f"codes not valid for {human_label}: {[c]}",
            )

    if human_label == HumanLabel.INCLUDE.value:
        _codes_allowed_for_label(UI_INCLUDE_REASON_CODES)
        if not reason_codes:
            raise AnnotationError("reasons_required", "include requires at least one reason code")
        if "other" in reason_codes and not note_text:
            raise AnnotationError("other_reason_required", "note is required when reason_codes includes other")
        return

    if human_label == HumanLabel.EXCLUDE.value:
        _codes_allowed_for_label(UI_EXCLUDE_REASON_CODES)
        if not reason_codes:
            raise AnnotationError("reasons_required", "exclude requires at least one reason code")
        if "other" in reason_codes and not note_text:
            raise AnnotationError("other_reason_required", "note is required when reason_codes includes other")
        return

    if human_label in {HumanLabel.UNCERTAIN.value, HumanLabel.DUPLICATE.value}:
        if reason_codes:
            raise AnnotationError(
                "invalid_reason_codes",
                f"{human_label} must not include reason_codes",
            )
        if human_label == HumanLabel.DUPLICATE.value and not note_text:
            raise AnnotationError(
                "duplicate_note_required",
                "note is required for duplicate (describe what it duplicates)",
            )
        return


def complete_annotation_run(session: Session, annotation_run_id: str) -> AnnotationRun:
    annotation = get_annotation_run(session, annotation_run_id)
    if annotation.status == AnnotationRunStatus.COMPLETED.value:
        return annotation
    _recount_reviewed(session, annotation)
    annotation.status = AnnotationRunStatus.COMPLETED.value
    annotation.completed_at = _utcnow()
    annotation.updated_at = _utcnow()
    session.flush()
    return annotation


def reopen_annotation_run(session: Session, annotation_run_id: str) -> AnnotationRun:
    annotation = get_annotation_run(session, annotation_run_id)
    annotation.status = (
        AnnotationRunStatus.IN_PROGRESS.value
        if annotation.reviewed_items > 0
        else AnnotationRunStatus.PENDING.value
    )
    annotation.completed_at = None
    annotation.updated_at = _utcnow()
    session.flush()
    return annotation


def cancel_annotation_run(session: Session, annotation_run_id: str) -> dict[str, Any]:
    """Delete an annotation task that has no saved human labels.

    Used to discard accidental / unsaved pending tasks. Never touches production tables.
    """
    annotation = get_annotation_run(session, annotation_run_id)
    _recount_reviewed(session, annotation)
    if annotation.reviewed_items > 0:
        raise AnnotationError(
            "annotation_has_reviews",
            "cannot cancel: at least one item already has a human label; complete or keep editing",
        )
    if annotation.status == AnnotationRunStatus.COMPLETED.value:
        raise AnnotationError("annotation_completed", "completed annotation run cannot be cancelled")

    payload = annotation_run_to_dict(annotation)
    session.execute(
        delete(AnnotationItem).where(AnnotationItem.annotation_run_id == annotation_run_id)
    )
    session.delete(annotation)
    session.flush()
    return {"cancelled": True, **payload}


def purge_unsaved_annotation_runs(session: Session) -> int:
    """Remove pending/in_progress annotation runs with zero saved human labels."""
    rows = list(
        session.scalars(
            select(AnnotationRun).where(
                AnnotationRun.status.in_(
                    [
                        AnnotationRunStatus.PENDING.value,
                        AnnotationRunStatus.IN_PROGRESS.value,
                    ]
                )
            )
        ).all()
    )
    purged = 0
    for row in rows:
        _recount_reviewed(session, row)
        if row.reviewed_items > 0:
            continue
        session.execute(
            delete(AnnotationItem).where(AnnotationItem.annotation_run_id == row.id)
        )
        session.delete(row)
        purged += 1
    if purged:
        session.flush()
    return purged


def build_annotation_diff(session: Session, annotation_run_id: str) -> dict[str, Any]:
    items = list_annotation_items(session, annotation_run_id)
    buckets: dict[str, list[dict[str, Any]]] = {
        "machine_selected_human_include": [],
        "machine_selected_human_exclude": [],
        "machine_not_selected_human_include": [],
        "machine_not_selected_human_exclude": [],
        "uncertain_or_duplicate": [],
        "unreviewed": [],
    }
    for item in items:
        payload = annotation_item_to_dict(item)
        if item.human_label is None:
            buckets["unreviewed"].append(payload)
            continue
        if item.human_label in {HumanLabel.UNCERTAIN.value, HumanLabel.DUPLICATE.value}:
            buckets["uncertain_or_duplicate"].append(payload)
            continue
        if item.machine_selected and item.human_label == HumanLabel.INCLUDE.value:
            buckets["machine_selected_human_include"].append(payload)
        elif item.machine_selected and item.human_label == HumanLabel.EXCLUDE.value:
            buckets["machine_selected_human_exclude"].append(payload)
        elif (not item.machine_selected) and item.human_label == HumanLabel.INCLUDE.value:
            buckets["machine_not_selected_human_include"].append(payload)
        elif (not item.machine_selected) and item.human_label == HumanLabel.EXCLUDE.value:
            buckets["machine_not_selected_human_exclude"].append(payload)

    exclude_reasons: dict[str, int] = {}
    include_reasons: dict[str, int] = {}
    for item in items:
        codes = list(item.reason_codes or [])
        target = (
            include_reasons
            if item.human_label == HumanLabel.INCLUDE.value
            else exclude_reasons
            if item.human_label == HumanLabel.EXCLUDE.value
            else None
        )
        if target is None:
            continue
        for code in codes:
            target[code] = target.get(code, 0) + 1

    return {
        "annotation_run_id": annotation_run_id,
        "counts": {k: len(v) for k, v in buckets.items()},
        "false_positives": len(buckets["machine_selected_human_exclude"]),
        "false_negatives": len(buckets["machine_not_selected_human_include"]),
        "buckets": {
            **buckets,
            # Explicit splits for Diff UI (uncertain/duplicate never count as TN).
            "uncertain": [
                annotation_item_to_dict(i)
                for i in items
                if i.human_label == HumanLabel.UNCERTAIN.value
            ],
            "duplicate": [
                annotation_item_to_dict(i)
                for i in items
                if i.human_label == HumanLabel.DUPLICATE.value
            ],
        },
        "top_exclude_reasons": sorted(exclude_reasons.items(), key=lambda x: -x[1]),
        "top_include_reasons": sorted(include_reasons.items(), key=lambda x: -x[1]),
    }
