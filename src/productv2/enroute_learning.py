"""Service for managing local Enroute learning references."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from productv2.db import (
    get_enroute_image_analysis,
    list_enroute_image_analyses_by_category,
    list_enroute_learning_references,
    prune_enroute_learning_references,
    update_enroute_learning_reference_status,
    upsert_enroute_learning_reference,
)
from productv2.enroute import EnrouteReference, infer_enroute_category
from productv2.models import CandidateProduct


LEARNING_STATUS_PENDING = "pending"
LEARNING_STATUS_LEARNING = "learning"
LEARNING_STATUS_LEARNED = "learned"
LEARNING_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class EnrouteLearningPlan:
    category: str | None
    references: list[EnrouteReference]
    rows: list[dict[str, Any]]
    cached_analysis_count: int
    unlearned_rows: list[dict[str, Any]]
    learning_rows: list[dict[str, Any]]
    synced_count: int
    pruned_count: int
    cache_status_synced_count: int = 0


def sync_enroute_learning_library(
    database_path: str | Path,
    references: list[EnrouteReference],
    *,
    category: str | None = None,
) -> dict[str, Any]:
    """Sync local Enroute 02.jpg references into the learning-reference table."""

    active_ids: set[str] = set()
    for reference in references:
        active_ids.add(reference.product_id)
        cached_analysis = get_enroute_image_analysis(database_path, reference.product_id)
        upsert_enroute_learning_reference(
            database_path,
            enroute_product_id=reference.product_id,
            enroute_category=reference.category,
            enroute_title=str(reference.metadata.get("title") or ""),
            enroute_handle=str(reference.metadata.get("handle") or ""),
            product_dir=str(reference.product_dir),
            image_path=str(reference.image_path),
            image_position=2,
            source_url=str(reference.metadata.get("source_url") or ""),
            metadata=reference.metadata,
            status=(
                LEARNING_STATUS_LEARNED
                if cached_analysis is not None
                else LEARNING_STATUS_PENDING
            ),
        )
        if cached_analysis is not None:
            update_enroute_learning_reference_status(
                database_path,
                enroute_product_id=reference.product_id,
                status=LEARNING_STATUS_LEARNED,
                analysis_id=int(cached_analysis["id"]),
            )

    pruned_count = prune_enroute_learning_references(
        database_path,
        active_product_ids=active_ids,
        enroute_category=category,
    )
    return {
        "synced_count": len(references),
        "pruned_count": pruned_count,
    }


def sync_enroute_learning_statuses_from_cache(
    database_path: str | Path,
    category: str,
) -> int:
    """Reconcile learning-reference statuses with valid cached analyses."""

    valid_cache_by_product_id = {
        str(row.get("enroute_product_id") or ""): row
        for row in valid_enroute_analysis_cache(database_path, category)
    }
    if not valid_cache_by_product_id:
        return 0

    synced_count = 0
    for row in list_enroute_learning_references(database_path, category):
        product_id = str(row.get("enroute_product_id") or "")
        cached = valid_cache_by_product_id.get(product_id)
        if cached is None:
            continue
        cached_id = int(cached["id"])
        if row.get("status") == LEARNING_STATUS_LEARNED and row.get("analysis_id") == cached_id:
            continue
        update_enroute_learning_reference_status(
            database_path,
            enroute_product_id=product_id,
            status=LEARNING_STATUS_LEARNED,
            analysis_id=cached_id,
        )
        synced_count += 1
    return synced_count


def plan_enroute_learning_for_candidate(
    candidate: CandidateProduct,
    *,
    database_path: str | Path,
    target_cache_size: int,
    initial_batch_size: int,
    incremental_batch_size: int,
) -> EnrouteLearningPlan:
    """Build a learning plan from persisted reference states."""

    category = infer_enroute_category(candidate)
    if category is None:
        return EnrouteLearningPlan(
            category=category,
            references=[],
            rows=[],
            cached_analysis_count=0,
            unlearned_rows=[],
            learning_rows=[],
            synced_count=0,
            pruned_count=0,
        )

    cache_status_synced_count = sync_enroute_learning_statuses_from_cache(
        database_path,
        category,
    )
    rows = list_enroute_learning_references(database_path, category)
    if not rows:
        return EnrouteLearningPlan(
            category=category,
            references=[],
            rows=[],
            cached_analysis_count=0,
            unlearned_rows=[],
            learning_rows=[],
            synced_count=0,
            pruned_count=0,
            cache_status_synced_count=cache_status_synced_count,
        )

    references = [reference_from_learning_row(row) for row in rows]
    cached_ids = {
        str(row.get("enroute_product_id") or "")
        for row in valid_enroute_analysis_cache(database_path, category)
    }
    cached_rows = [
        row for row in rows if str(row.get("enroute_product_id") or "") in cached_ids
    ]
    cached_ids = {str(row.get("enroute_product_id") or "") for row in cached_rows}
    unlearned_rows = [
        row
        for row in rows
        if str(row.get("enroute_product_id") or "") not in cached_ids
    ]
    learning_batch_size = (
        initial_batch_size
        if len(cached_rows) < target_cache_size
        else incremental_batch_size
    )
    learning_rows = unlearned_rows[: min(learning_batch_size, len(unlearned_rows))]
    return EnrouteLearningPlan(
        category=category,
        references=references,
        rows=rows,
        cached_analysis_count=len(cached_rows),
        unlearned_rows=unlearned_rows,
        learning_rows=learning_rows,
        synced_count=0,
        pruned_count=0,
        cache_status_synced_count=cache_status_synced_count,
    )


def enroute_analysis_is_valid_profile(analysis_json: dict[str, Any]) -> bool:
    """Return whether a cached Enroute analysis is usable as a style profile."""

    if not isinstance(analysis_json, dict) or not analysis_json:
        return False
    if analysis_json.get("is_valid_human_reference") is False:
        return False
    if analysis_json.get("is_valid_wearing_reference") is False:
        return False
    return True


def valid_enroute_analysis_cache(
    database_path: str | Path,
    category: str,
) -> list[dict[str, Any]]:
    """Load valid cached analyses for one Enroute category."""

    return [
        row
        for row in list_enroute_image_analyses_by_category(database_path, category)
        if enroute_analysis_is_valid_profile(row.get("analysis_json", {}))
    ]


def reference_from_learning_row(row: dict[str, Any]) -> EnrouteReference:
    """Convert a persisted learning row into the workflow reference object."""

    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return EnrouteReference(
        product_id=str(row.get("enroute_product_id") or ""),
        category=str(row.get("enroute_category") or ""),
        product_dir=Path(str(row.get("product_dir") or "")),
        image_path=Path(str(row.get("image_path") or "")),
        metadata=dict(metadata),
    )


def mark_enroute_reference_learning(
    database_path: str | Path,
    reference: EnrouteReference,
    *,
    workflow_log_path: str = "",
) -> dict[str, Any]:
    """Mark a reference as actively being learned."""

    return update_enroute_learning_reference_status(
        database_path,
        enroute_product_id=reference.product_id,
        status=LEARNING_STATUS_LEARNING,
        last_workflow_log_path=workflow_log_path,
    )


def mark_enroute_reference_learned(
    database_path: str | Path,
    reference: EnrouteReference,
    *,
    analysis_id: int | None,
    workflow_log_path: str = "",
) -> dict[str, Any]:
    """Mark a reference as learned after analysis cache write succeeds."""

    return update_enroute_learning_reference_status(
        database_path,
        enroute_product_id=reference.product_id,
        status=LEARNING_STATUS_LEARNED,
        analysis_id=analysis_id,
        last_workflow_log_path=workflow_log_path,
    )


def mark_enroute_reference_failed(
    database_path: str | Path,
    reference: EnrouteReference,
    *,
    error: str,
    workflow_log_path: str = "",
) -> dict[str, Any]:
    """Mark a learning attempt as failed."""

    return update_enroute_learning_reference_status(
        database_path,
        enroute_product_id=reference.product_id,
        status=LEARNING_STATUS_FAILED,
        last_error=error,
        last_workflow_log_path=workflow_log_path,
        increment_attempts=True,
    )
