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


PIPELINE_LOCK_NAME = "connor_daily_pipeline"
