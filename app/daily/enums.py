from __future__ import annotations

from enum import Enum


class RunStatus(str, Enum):
    INITIALIZING = "initializing"
    COLLECTING = "collecting"
    SUMMARIZING = "summarizing"
    EVALUATING = "evaluating"
    SELECTING = "selecting"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"


class CollectionStatus(str, Enum):
    SUCCESS = "success"
    CURSOR_NOT_FOUND_BUT_WINDOW_COVERED = "cursor_not_found_but_window_covered"
    PAGE_INCOMPLETE = "page_incomplete"
    SAFETY_LIMIT_REACHED = "safety_limit_reached"
    KNOWN_DATA_GAP = "known_data_gap"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"
    CURSOR_SYNC_PENDING = "cursor_sync_pending"


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"


class OutboxStatus(str, Enum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"


class SelectionItemStatus(str, Enum):
    SELECTED = "selected"
    NOT_SELECTED = "not_selected"


class PublicationStatus(str, Enum):
    UNPUBLISHED = "unpublished"
    PUBLISHED = "published"
    WITHDRAWN = "withdrawn"


class VisibilityStatus(str, Enum):
    VISIBLE = "visible"
    HIDDEN = "hidden"
    REMOVED_SOURCE = "removed_source"
    TAKEDOWN = "takedown"


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    GIF = "gif"


class MediaDownloadStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"


class AnnotationRunStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class HumanLabel(str, Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    # Legacy labels retained so historical annotation_items still validate.
    UNCERTAIN = "uncertain"
    DUPLICATE = "duplicate"


# Labels offered in Console Editorial UI (keep historical enum values above).
UI_HUMAN_LABELS: tuple[str, ...] = (
    HumanLabel.INCLUDE.value,
    HumanLabel.EXCLUDE.value,
)


DEFAULT_ANNOTATION_POLICY_VERSION = "annotation-policy/v2"

# Full allow-lists (including legacy codes retained for historical rows).
EXCLUDE_REASON_CODES = frozenset(
    {
        "low_information",
        "duplicate_event",  # legacy; use human_label=duplicate for new labels
        "old_information",
        "weak_source",
        "pure_promotion",
        "insufficient_evidence",
        "not_frontier",
        "too_niche",
        "already_covered",
        "low_daily_relevance",
        "bare_repost",
        "other",
    }
)

INCLUDE_REASON_CODES = frozenset(
    {
        "major_release",
        "official_confirmation",
        "high_information_gain",
        "frontier_signal",
        "important_product_update",
        "market_impact",
        "china_ai_significance",
        "underestimated_by_model",
        "other",
    }
)

# Ordered UI vocabularies — keep short for fast annotator flow.
UI_INCLUDE_REASON_ORDER: tuple[str, ...] = (
    "frontier_signal",
    "important_product_update",
    "official_confirmation",
    "other",
)

UI_EXCLUDE_REASON_ORDER: tuple[str, ...] = (
    "low_information",
    "old_information",
    "not_frontier",
    "other",
)

UI_INCLUDE_REASON_CODES = frozenset(UI_INCLUDE_REASON_ORDER)
UI_EXCLUDE_REASON_CODES = frozenset(UI_EXCLUDE_REASON_ORDER)

DEPRECATED_REASON_CODES = frozenset({"duplicate_event"})
# Alias used by older console helpers / tests
HIDDEN_REASON_CODES = DEPRECATED_REASON_CODES

ALL_REASON_CODES = EXCLUDE_REASON_CODES | INCLUDE_REASON_CODES


PIPELINE_LOCK_NAME = "connor_daily_pipeline"
