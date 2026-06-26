"""LangGraph workflow for product image processing."""

from __future__ import annotations

import hashlib
import inspect
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from productv2.adapters import get_platform_adapter
from productv2.config import (
    DEFAULT_ENROUTE_BESTSELLERS_DIR,
    DEFAULT_MODEL_PROFILES_DIR,
    DEFAULT_PRODUCT_ASSETS_DIR,
    DEFAULT_WORKFLOW_LOGS_DIR,
    Settings,
)
from productv2.data import load_candidate_products
from productv2.db import (
    FAILED_STATUS,
    get_enroute_image_analysis,
    import_raw_data_directory,
    list_enroute_image_analyses_by_category,
    load_model_profiles,
    sync_default_model_profiles,
    update_product_fields,
    upsert_enroute_image_analysis,
)
from productv2.enroute import EnrouteReference, list_enroute_wearing_references
from productv2.images import merge_remote_images_to_numbered_collage, product_asset_dir
from productv2.models import CandidateProduct, ListingDraft
from productv2.reference_analysis import (
    analyze_enroute_reference_image,
    select_enroute_analysis_from_summaries,
)
from productv2.selection import select_unfinished_product_with_adapter
from productv2.state import initialize_product_state, set_extra
from productv2.vision import detect_size_reference_images
from productv2.wearing import generate_wearing_image
from productv2.workflow_logging import (
    WorkflowRunLogger,
    log_branch_decision,
    wrap_node_with_logging,
)


class ListingWorkflowState(TypedDict, total=False):
    data_path: str | None
    database_path: str
    raw_data_dir: str
    product_assets_dir: str
    enroute_bestsellers_dir: str
    model_profiles_dir: str
    workflow_logs_dir: str
    workflow_log_path: str
    limit: int | None
    candidates: list[dict[str, Any]]
    selected_product: dict[str, Any]
    drafts: list[dict[str, Any]]
    review_queue: list[dict[str, Any]]
    main_image_result: dict[str, Any]
    size_reference_result: dict[str, Any]
    enroute_reference_result: dict[str, Any]
    enroute_analysis_result: dict[str, Any]
    wearing_image_result: dict[str, Any]
    wearing_generation_attempt: int
    manual_review_request: dict[str, Any]
    manual_review_decision: dict[str, Any]
    failed_product: dict[str, Any]
    ai_checkpoints: dict[str, Any]
    metrics: dict[str, Any]


MAX_WEARING_REGENERATE_ATTEMPTS = 3
ENROUTE_CACHE_TARGET_COUNT = 5
ENROUTE_LEARNING_CONCURRENCY = 5


def _load_candidates(
    state: ListingWorkflowState,
    logger: WorkflowRunLogger | None = None,
) -> ListingWorkflowState:
    database_path = _database_path(state)
    raw_import_summary = import_raw_data_directory(
        database_path=database_path,
        raw_data_dir=_raw_data_dir(state),
    )
    sync_default_model_profiles(
        database_path,
        _model_profiles_dir(state),
    )
    data_path = state.get("data_path")
    if data_path:
        path = Path(data_path)
        if not path.exists():
            raise FileNotFoundError(f"Candidate data file not found: {path}")
        candidates = load_candidate_products(
            data_path=path,
            limit=state.get("limit"),
        )
        if candidates and logger is not None:
            logger.rename_for_product(
                product_name=_candidate_log_name(candidates[0]),
                product_id=candidates[0].product_id,
                platform=candidates[0].platform,
            )
        source = "json"
    else:
        selection = select_unfinished_product_with_adapter(
            database_path=database_path,
        )
        candidates = [selection.candidate] if selection.candidate else []
        if selection.candidate is not None:
            initialize_product_state(
                selection.candidate,
                database_path=database_path,
            )
            if logger is not None:
                logger.rename_for_product(
                    product_name=_candidate_log_name(selection.candidate),
                    product_id=selection.candidate.product_id,
                    platform=selection.candidate.platform,
                )
        source = "database_adapter_selection"

    selected_product = candidates[0].model_dump() if candidates else {}
    result: ListingWorkflowState = {
        "candidates": [candidate.model_dump() for candidate in candidates],
        "selected_product": selected_product,
        "metrics": {
            "candidate_count": len(candidates),
            "candidate_source": source,
            "raw_import": raw_import_summary,
            **(
                {
                    "unfinished_count": selection.unfinished_count,
                    "selected_adapter": selection.selected_adapter_name,
                    "skipped_without_adapter_count": len(
                        selection.skipped_without_adapter
                    ),
                }
                if source == "database_adapter_selection"
                else {}
            ),
        },
    }
    if logger is not None:
        result["workflow_log_path"] = str(logger.path)
    return result


def _merge_main_images(state: ListingWorkflowState) -> ListingWorkflowState:
    candidates = [
        CandidateProduct.model_validate(candidate)
        for candidate in state.get("candidates", [])
    ]
    if not candidates:
        return {"main_image_result": {"status": "skipped", "reason": "no_candidate"}}

    candidate = candidates[0]
    if candidate.id is None:
        return {
            "main_image_result": {
                "status": "skipped",
                "reason": "candidate_not_from_database",
            }
        }

    adapter = get_platform_adapter(candidate.platform)
    image_urls = adapter.get_main_images(candidate)
    output_path = (
        product_asset_dir(
            candidate,
            _product_assets_dir(state),
        )
        / "main_image_collage.jpg"
    )

    collage = merge_remote_images_to_numbered_collage(
        image_urls=image_urls,
        output_path=output_path,
    )

    main_image_result = {
        "status": "ok",
        "path": str(collage.path),
        "temporary": True,
        "source_image_count": len(image_urls),
        "numbered_sources": [
            {
                "index": source.index,
                "url": source.url,
                "path": str(source.path) if source.path is not None else "",
            }
            for source in collage.source_images
        ],
    }
    set_extra("main_image_collage", main_image_result)
    return {"main_image_result": main_image_result}


def _detect_size_reference(
    state: ListingWorkflowState,
    logger: WorkflowRunLogger | None = None,
) -> ListingWorkflowState:
    main_image_result = state.get("main_image_result", {})
    if main_image_result.get("status") != "ok":
        return {
            "size_reference_result": {
                "status": "skipped",
                "reason": "main_image_not_ready",
            }
        }

    checkpoint_key = "detect_size_reference"
    checkpoint_input = _checkpoint_input(
        product=_selected_product_identity(state),
        collage_path=main_image_result.get("path", ""),
        source_image_count=main_image_result.get("source_image_count", 0),
        numbered_sources=main_image_result.get("numbered_sources", []),
    )
    cached = _get_ai_checkpoint_result(state, checkpoint_key, checkpoint_input)
    if cached is not None:
        result = dict(cached)
        result["checkpoint"] = "hit"
        set_extra("size_reference_detection", result)
        return _with_ai_checkpoint(
            state,
            {"size_reference_result": result},
            checkpoint_key=checkpoint_key,
            checkpoint_input=checkpoint_input,
            checkpoint_result=result,
            source="state_hit",
        )

    detection = _call_with_optional_logger(
        detect_size_reference_images,
        main_image_result["path"],
        logger=logger,
        database_path=_database_path(state),
    )

    size_reference_result = {
        "status": "ok",
        "can_judge_size": detection.can_judge_size,
        "image_numbers": detection.image_numbers,
        "size_reference_image_number": detection.size_reference_image_number,
        "main_image_number": detection.main_image_number,
        "reason": detection.reason,
    }
    selected_images = _selected_product_images(
        main_image_result,
        size_reference_result,
    )
    if selected_images:
        size_reference_result["selected_images"] = selected_images
        set_extra("selected_product_images", selected_images)
    set_extra("size_reference_detection", size_reference_result)
    return _with_ai_checkpoint(
        state,
        {"size_reference_result": size_reference_result},
        checkpoint_key=checkpoint_key,
        checkpoint_input=checkpoint_input,
        checkpoint_result=size_reference_result,
        source="llm",
    )


def _size_reference_next_step(
    state: ListingWorkflowState,
    logger: WorkflowRunLogger | None = None,
) -> str:
    if state.get("size_reference_result", {}).get("status") == "failed":
        branch = "retry_load_candidates"
    elif state.get("size_reference_result", {}).get("status") == "ok":
        branch = "select_enroute_reference"
    else:
        branch = "build_listing_drafts"
    if logger is not None:
        log_branch_decision(logger, "detect_size_reference", branch, state)
    return branch


def _selected_product_images(
    main_image_result: dict[str, Any],
    size_reference_result: dict[str, Any],
) -> dict[str, Any]:
    numbered_sources = {
        source.get("index"): source
        for source in main_image_result.get("numbered_sources", [])
        if isinstance(source, dict)
    }
    size_reference_source = numbered_sources.get(
        size_reference_result.get("size_reference_image_number")
    )
    main_image_source = numbered_sources.get(size_reference_result.get("main_image_number"))

    selected_images: dict[str, Any] = {}
    if size_reference_source and size_reference_source.get("path"):
        selected_images["size_reference_image"] = {
            "number": size_reference_source["index"],
            "path": size_reference_source["path"],
            "url": size_reference_source.get("url", ""),
        }
        set_extra("selected_size_reference_image_path", size_reference_source["path"])
    if main_image_source and main_image_source.get("path"):
        selected_images["main_image"] = {
            "number": main_image_source["index"],
            "path": main_image_source["path"],
            "url": main_image_source.get("url", ""),
        }
        set_extra("selected_main_image_path", main_image_source["path"])
    return selected_images


def _candidate_log_name(candidate: CandidateProduct) -> str:
    rawdata = candidate.rawdata if isinstance(candidate.rawdata, dict) else {}
    title = str(rawdata.get("title") or "").strip()
    return title or candidate.product_id


def _select_enroute_reference(state: ListingWorkflowState) -> ListingWorkflowState:
    candidates = [
        CandidateProduct.model_validate(candidate)
        for candidate in state.get("candidates", [])
    ]
    if not candidates:
        return {
            "enroute_reference_result": {
                "status": "skipped",
                "reason": "no_candidate",
            }
        }

    category, references = list_enroute_wearing_references(
        candidates[0],
        library_dir=_enroute_bestsellers_dir(state),
    )
    if category is None or not references:
        result = {
            "status": "skipped",
            "reason": "no_matching_enroute_reference",
        }
        set_extra("enroute_reference_selection", result)
        return {"enroute_reference_result": result}

    cached = _valid_enroute_analysis_cache(_database_path(state), category)
    cached_ids = {str(row.get("enroute_product_id") or "") for row in cached}
    unlearned = [
        reference for reference in references if reference.product_id not in cached_ids
    ]
    learning_limit = (
        min(ENROUTE_CACHE_TARGET_COUNT, len(unlearned))
        if len(cached) < ENROUTE_CACHE_TARGET_COUNT
        else min(1, len(unlearned))
    )
    learning_references = unlearned[:learning_limit]
    result = {
        "status": "ok",
        "category": category,
        "reference_count": len(references),
        "cached_analysis_count": len(cached),
        "unlearned_count": len(unlearned),
        "learning_count": len(learning_references),
        "learning_references": [
            _enroute_reference_payload(reference)
            for reference in learning_references
        ],
    }
    set_extra("enroute_reference_selection", result)
    return {"enroute_reference_result": result}


def _analyze_enroute_reference(
    state: ListingWorkflowState,
    logger: WorkflowRunLogger | None = None,
) -> ListingWorkflowState:
    enroute_reference_result = state.get("enroute_reference_result", {})
    if enroute_reference_result.get("status") != "ok":
        result = {
            "status": "skipped",
            "reason": enroute_reference_result.get("reason", "reference_not_ready"),
        }
        set_extra("enroute_reference_analysis", result)
        return {"enroute_analysis_result": result}

    database_path = _database_path(state)
    category = str(enroute_reference_result.get("category") or "")
    if not category:
        result = {
            "status": "skipped",
            "reason": "enroute_category_missing",
        }
        set_extra("enroute_reference_analysis", result)
        return {"enroute_analysis_result": result}

    model_profiles = load_model_profiles(database_path)
    learning_references = [
        EnrouteReference(
            product_id=str(item.get("enroute_product_id") or ""),
            category=str(item.get("category") or category),
            product_dir=Path(str(item.get("product_dir") or "")),
            image_path=Path(str(item.get("image_path") or "")),
            metadata=dict(item.get("metadata") or {}),
        )
        for item in enroute_reference_result.get("learning_references", [])
        if isinstance(item, dict)
    ]
    learning_outputs: list[dict[str, Any]] = []
    checkpoint_state: ListingWorkflowState = state
    if learning_references:
        checkpoint_state, learning_outputs = _learn_enroute_references(
            checkpoint_state,
            database_path=database_path,
            references=learning_references,
            model_profiles=model_profiles,
            logger=logger,
        )

    cached = _valid_enroute_analysis_cache(database_path, category)
    if not cached:
        result = {
            "status": "skipped",
            "reason": "no_cached_enroute_analysis",
            "category": category,
            "learning_results": learning_outputs,
        }
        set_extra("enroute_reference_analysis", result)
        return _merge_checkpoint_update(
            checkpoint_state,
            {
                "enroute_analysis_result": result,
                "enroute_reference_result": {
                    **enroute_reference_result,
                    "learning_results": learning_outputs,
                    "cached_analysis_count_after_learning": 0,
                },
            },
        )

    summaries = _enroute_cache_summaries(cached)
    selected_images = (
        state.get("size_reference_result", {}).get("selected_images", {})
        if isinstance(state.get("size_reference_result"), dict)
        else {}
    )
    main_image_path = str((selected_images.get("main_image") or {}).get("path") or "")
    size_reference_image_path = str(
        (selected_images.get("size_reference_image") or {}).get("path") or ""
    )
    if not main_image_path or not size_reference_image_path:
        result = {
            "status": "skipped",
            "reason": "selected_product_images_missing",
            "category": category,
            "learning_results": learning_outputs,
        }
        set_extra("enroute_reference_analysis", result)
        return _merge_checkpoint_update(
            checkpoint_state,
            {"enroute_analysis_result": result},
        )

    checkpoint_key = "select_enroute_analysis"
    checkpoint_input = _checkpoint_input(
        main_image_path=main_image_path,
        size_reference_image_path=size_reference_image_path,
        analysis_summaries=summaries,
    )
    cached_checkpoint = _get_ai_checkpoint_result(
        checkpoint_state,
        checkpoint_key,
        checkpoint_input,
    )
    if cached_checkpoint is not None:
        result = dict(cached_checkpoint)
        result["checkpoint"] = "hit"
        set_extra("enroute_reference_analysis", result)
        return _with_ai_checkpoint(
            checkpoint_state,
            {
                "enroute_analysis_result": result,
                "enroute_reference_result": {
                    **enroute_reference_result,
                    "learning_results": learning_outputs,
                    "cached_analysis_count_after_learning": len(cached),
                },
            },
            checkpoint_key=checkpoint_key,
            checkpoint_input=checkpoint_input,
            checkpoint_result=result,
            source="state_hit",
        )

    selection = select_enroute_analysis_from_summaries(
        main_image_path,
        size_reference_image_path,
        summaries,
        **_kwargs_with_optional_logger(
            select_enroute_analysis_from_summaries,
            logger=logger,
            database_path=database_path,
        ),
    )

    selected_id = selection.selected_enroute_product_id
    selected = next(
        (
            row
            for row in cached
            if str(row.get("enroute_product_id") or "") == selected_id
        ),
        None,
    )
    if selected is None:
        raise ValueError(
            "Selected Enroute analysis is not in cache: "
            f"{selected_id or '<empty>'}"
        )

    result = {
        "status": "ok",
        "cache": "selected",
        "reference_image_path": selected["image_path"],
        "enroute_product_id": selected["enroute_product_id"],
        "category": selected["enroute_category"],
        "summary": selected["summary"],
        "analysis": selected["analysis_json"],
        "selection": selection.model_dump(),
        "learning_results": learning_outputs,
    }
    set_extra("enroute_reference_analysis", result)
    set_extra("selected_enroute_reference_image_path", selected["image_path"])
    set_extra(
        "enroute_reference_selection",
        {
            **enroute_reference_result,
            "selected_enroute_product_id": selected["enroute_product_id"],
            "selected_image_path": selected["image_path"],
            "selection_reason": selection.reason,
        },
    )
    return _with_ai_checkpoint(
        checkpoint_state,
        {
            "enroute_analysis_result": result,
            "enroute_reference_result": {
                **enroute_reference_result,
                "selected_enroute_product_id": selected["enroute_product_id"],
                "selected_image_path": selected["image_path"],
                "selection_reason": selection.reason,
                "learning_results": learning_outputs,
                "cached_analysis_count_after_learning": len(cached),
            },
        },
        checkpoint_key=checkpoint_key,
        checkpoint_input=checkpoint_input,
        checkpoint_result=result,
        source="llm_selector",
    )


def _analysis_has_model_selection(analysis_json: dict[str, Any]) -> bool:
    selected = analysis_json.get("selected_model_profile")
    return isinstance(selected, dict) and bool(selected.get("profile_key"))


def _valid_enroute_analysis_cache(
    database_path: str | Path,
    category: str,
) -> list[dict[str, Any]]:
    return [
        row
        for row in list_enroute_image_analyses_by_category(database_path, category)
        if _analysis_has_model_selection(row.get("analysis_json", {}))
    ]


def _learn_enroute_references(
    state: ListingWorkflowState,
    *,
    database_path: str | Path,
    references: list[EnrouteReference],
    model_profiles: list[dict[str, Any]],
    logger: WorkflowRunLogger | None = None,
) -> tuple[ListingWorkflowState, list[dict[str, Any]]]:
    checkpoint_state = state
    outputs: list[dict[str, Any]] = []
    with ThreadPoolExecutor(
        max_workers=min(ENROUTE_LEARNING_CONCURRENCY, len(references))
    ) as executor:
        future_map = {
            executor.submit(
                _learn_one_enroute_reference,
                checkpoint_state,
                database_path,
                reference,
                model_profiles,
                logger,
            ): reference
            for reference in references
        }
        for future in as_completed(future_map):
            result, checkpoint_key, checkpoint_input, source = future.result()
            outputs.append(result)
            checkpoint_state = _with_ai_checkpoint(
                checkpoint_state,
                {},
                checkpoint_key=checkpoint_key,
                checkpoint_input=checkpoint_input,
                checkpoint_result=result,
                source=source,
            )
    outputs.sort(key=lambda item: str(item.get("enroute_product_id") or ""))
    return checkpoint_state, outputs


def _learn_one_enroute_reference(
    state: ListingWorkflowState,
    database_path: str | Path,
    reference: EnrouteReference,
    model_profiles: list[dict[str, Any]],
    logger: WorkflowRunLogger | None,
) -> tuple[dict[str, Any], str, dict[str, Any], str]:
    checkpoint_key = _enroute_learning_checkpoint_key(reference)
    checkpoint_input = _checkpoint_input(
        reference_image_path=str(reference.image_path),
        enroute_product_id=reference.product_id,
        category=reference.category,
        model_profiles=[
            {
                "profile_key": profile.get("profile_key", ""),
                "name": profile.get("name", ""),
                "image_path": profile.get("image_path", ""),
            }
            for profile in model_profiles
        ],
    )
    cached_checkpoint = _get_ai_checkpoint_result(
        state,
        checkpoint_key,
        checkpoint_input,
    )
    if cached_checkpoint is not None:
        result = dict(cached_checkpoint)
        result["checkpoint"] = "hit"
        return result, checkpoint_key, checkpoint_input, "state_hit"

    cached = get_enroute_image_analysis(database_path, reference.product_id)
    if cached is not None and _analysis_has_model_selection(cached["analysis_json"]):
        result = _enroute_cached_analysis_result(cached, cache="hit")
        return result, checkpoint_key, checkpoint_input, "database_cache"

    analysis = analyze_enroute_reference_image(
        reference.image_path,
        **_kwargs_with_optional_logger(
            analyze_enroute_reference_image,
            logger=logger,
            model_profiles=model_profiles,
            database_path=database_path,
        ),
    )

    analysis_json = analysis.model_dump()
    metadata = reference.metadata
    upsert_enroute_image_analysis(
        database_path,
        enroute_product_id=reference.product_id,
        enroute_category=reference.category,
        enroute_title=str(metadata.get("title") or ""),
        enroute_handle=str(metadata.get("handle") or ""),
        image_path=str(reference.image_path),
        image_position=2,
        analysis_json=analysis_json,
        summary=analysis.summary,
    )
    result = {
        "status": "ok",
        "cache": "miss",
        "reference_image_path": str(reference.image_path),
        "enroute_product_id": reference.product_id,
        "category": reference.category,
        "summary": analysis.summary,
        "analysis": analysis_json,
    }
    return result, checkpoint_key, checkpoint_input, "llm"


def _enroute_cached_analysis_result(
    cached: dict[str, Any],
    *,
    cache: str,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "cache": cache,
        "reference_image_path": cached["image_path"],
        "enroute_product_id": cached["enroute_product_id"],
        "category": cached["enroute_category"],
        "summary": cached["summary"],
        "analysis": cached["analysis_json"],
    }


def _enroute_cache_summaries(cached_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "enroute_product_id": row["enroute_product_id"],
            "summary": row["summary"],
        }
        for row in cached_rows
    ]


def _enroute_reference_payload(reference: EnrouteReference) -> dict[str, Any]:
    metadata = reference.metadata
    return {
        "enroute_product_id": reference.product_id,
        "category": reference.category,
        "image_path": str(reference.image_path),
        "product_dir": str(reference.product_dir),
        "metadata": {
            "title": metadata.get("title", ""),
            "handle": metadata.get("handle", ""),
            "product_type": metadata.get("product_type", ""),
            "source_url": metadata.get("source_url", ""),
        },
    }


def _enroute_learning_checkpoint_key(reference: EnrouteReference) -> str:
    digest = hashlib.sha256(
        f"{reference.category}:{reference.product_id}".encode("utf-8")
    ).hexdigest()[:16]
    return f"learn_enroute_reference_{digest}"


def _merge_checkpoint_update(
    state: ListingWorkflowState,
    update: ListingWorkflowState,
) -> ListingWorkflowState:
    if state.get("ai_checkpoints"):
        return {**update, "ai_checkpoints": state["ai_checkpoints"]}
    return update


def _mark_current_candidate_failed(
    state: ListingWorkflowState,
    reason: str = "",
) -> dict[str, Any]:
    candidates = [
        CandidateProduct.model_validate(candidate)
        for candidate in state.get("candidates", [])
    ]
    if not candidates:
        return {}
    candidate = candidates[0]
    if candidate.id is None:
        return {}
    failed_product = update_product_fields(
        database_path=_database_path(state),
        product_id=candidate.product_id,
        platform=candidate.platform,
        status=FAILED_STATUS,
        locked_at=None,
        locked_by=None,
    )
    return {
        "product_id": failed_product.product_id,
        "platform": failed_product.platform,
        "status": failed_product.status,
        "reason": reason,
    }


def _generate_wearing_image(
    state: ListingWorkflowState,
    logger: WorkflowRunLogger | None = None,
) -> ListingWorkflowState:
    candidates = [
        CandidateProduct.model_validate(candidate)
        for candidate in state.get("candidates", [])
    ]
    if not candidates:
        return {"wearing_image_result": {"status": "skipped", "reason": "no_candidate"}}

    previous_result = state.get("wearing_image_result", {})
    review_decision = state.get("manual_review_decision", {})
    should_regenerate = review_decision.get("action") == "regenerate"
    next_attempt = int(state.get("wearing_generation_attempt") or 0) + 1
    if (
        not should_regenerate
        and isinstance(previous_result, dict)
        and previous_result.get("status") == "ok"
        and previous_result.get("generated_image_path")
        and Path(str(previous_result["generated_image_path"])).is_file()
    ):
        return {
            "wearing_image_result": {
                **previous_result,
                "cache": "state_hit",
                "checkpoint": "hit",
            }
        }

    checkpoint_key = f"generate_wearing_image_attempt_{next_attempt}"
    checkpoint_input = _checkpoint_input(
        product=_selected_product_identity(state),
        attempt=next_attempt,
        size_reference_result=state.get("size_reference_result", {}),
        enroute_analysis_result=state.get("enroute_analysis_result", {}),
        product_assets_dir=str(
            product_asset_dir(
                candidates[0],
                _product_assets_dir(state),
            )
        ),
    )
    cached = None if should_regenerate else _get_ai_checkpoint_result(
        state,
        checkpoint_key,
        checkpoint_input,
    )
    if cached is not None:
        result = dict(cached)
        generated_image_path = str(result.get("generated_image_path") or "")
        if not generated_image_path or Path(generated_image_path).is_file():
            result["checkpoint"] = "hit"
            set_extra("wearing_image_generation", result)
            return _with_ai_checkpoint(
                state,
                {
                    "wearing_image_result": result,
                    "wearing_generation_attempt": next_attempt,
                    "manual_review_decision": {},
                },
                checkpoint_key=checkpoint_key,
                checkpoint_input=checkpoint_input,
                checkpoint_result=result,
                source="state_hit",
            )

    wearing_image_result = generate_wearing_image(
        candidates[0],
        state.get("size_reference_result", {}),
        state.get("enroute_analysis_result", {}),
        product_asset_dir(
            candidates[0],
            _product_assets_dir(state),
        ),
        logger=logger,
        attempt=next_attempt,
        database_path=_database_path(state),
    )
    set_extra("wearing_image_generation", wearing_image_result)
    return _with_ai_checkpoint(
        state,
        {
            "wearing_image_result": wearing_image_result,
            "wearing_generation_attempt": next_attempt,
            "manual_review_decision": {},
        },
        checkpoint_key=checkpoint_key,
        checkpoint_input=checkpoint_input,
        checkpoint_result=wearing_image_result,
        source="image_ai",
    )


def _wait_manual_review(state: ListingWorkflowState) -> ListingWorkflowState:
    wearing_image_result = state.get("wearing_image_result", {})
    if wearing_image_result.get("status") != "ok":
        result = {
            "status": "skipped",
            "reason": wearing_image_result.get("reason", "wearing_image_not_ready"),
        }
        return {
            "manual_review_request": result,
            "manual_review_decision": {"action": "reject", "reason": result["reason"]},
        }

    payload = {
        "type": "wearing_image_review",
        "product": state.get("selected_product") or (
            state.get("candidates", [{}])[0] if state.get("candidates") else {}
        ),
        "generated_image_path": wearing_image_result.get("generated_image_path", ""),
        "generated_image_url": wearing_image_result.get("generated_image_url", ""),
        "marked_main_image_path": wearing_image_result.get("marked_main_image_path", ""),
        "marked_size_reference_image_path": wearing_image_result.get(
            "marked_size_reference_image_path",
            "",
        ),
        "enroute_reference_image_path": wearing_image_result.get(
            "enroute_reference_image_path",
            "",
        ),
        "selected_model_profile": wearing_image_result.get(
            "selected_model_profile",
            {},
        ),
        "prompt": wearing_image_result.get("prompt", ""),
        "attempt": state.get("wearing_generation_attempt", 1),
        "options": ["approve", "regenerate", "reject"],
    }
    decision = interrupt(payload)
    if not isinstance(decision, dict):
        decision = {"action": str(decision or "reject")}
    return {
        "manual_review_request": payload,
        "manual_review_decision": decision,
    }


def _route_manual_review_decision(
    state: ListingWorkflowState,
    logger: WorkflowRunLogger | None = None,
) -> str:
    decision = state.get("manual_review_decision", {})
    action = str(decision.get("action") or "").lower()
    if action == "approve":
        branch = "build_listing_drafts"
    elif action == "regenerate":
        attempt = int(state.get("wearing_generation_attempt") or 0)
        branch = (
            "generate_wearing_image"
            if attempt < MAX_WEARING_REGENERATE_ATTEMPTS
            else "mark_failed_and_reload_candidates"
        )
    elif action == "reject":
        branch = "mark_failed_and_reload_candidates"
    else:
        branch = "mark_failed_and_reload_candidates"
    if logger is not None:
        log_branch_decision(logger, "wait_manual_review", branch, state)
    return branch


def _mark_failed_and_reload_candidates(
    state: ListingWorkflowState,
) -> ListingWorkflowState:
    failed_product = _mark_current_candidate_failed(
        state,
        reason=str(state.get("manual_review_decision", {}).get("reason") or ""),
    )
    return {
        "candidates": [],
        "selected_product": {},
        "failed_product": failed_product,
        "manual_review_request": {},
        "manual_review_decision": {},
        "wearing_image_result": {},
        "wearing_generation_attempt": 0,
    }


def _build_listing_drafts(state: ListingWorkflowState) -> ListingWorkflowState:
    candidates = [
        CandidateProduct.model_validate(candidate)
        for candidate in state.get("candidates", [])
    ]
    drafts = [ListingDraft.from_candidate(candidate) for candidate in candidates]

    return {"drafts": [draft.model_dump() for draft in drafts]}


def _prepare_review_queue(state: ListingWorkflowState) -> ListingWorkflowState:
    drafts = [ListingDraft.model_validate(draft) for draft in state.get("drafts", [])]
    review_queue = [draft for draft in drafts if draft.warnings]
    existing_metrics = dict(state.get("metrics", {}))
    if state.get("main_image_result"):
        existing_metrics["main_image_result"] = state["main_image_result"]
    if state.get("size_reference_result"):
        existing_metrics["size_reference_result"] = state["size_reference_result"]
    if state.get("enroute_reference_result"):
        existing_metrics["enroute_reference_result"] = state[
            "enroute_reference_result"
        ]
    if state.get("enroute_analysis_result"):
        existing_metrics["enroute_analysis_result"] = state["enroute_analysis_result"]
    if state.get("wearing_image_result"):
        existing_metrics["wearing_image_result"] = state["wearing_image_result"]
    if state.get("ai_checkpoints"):
        existing_metrics["ai_checkpoints"] = {
            "keys": sorted(str(key) for key in state["ai_checkpoints"].keys()),
            "count": len(state["ai_checkpoints"]),
        }
    if state.get("workflow_log_path"):
        existing_metrics["workflow_log_path"] = state["workflow_log_path"]
    existing_metrics.update(
        {
            "draft_count": len(drafts),
            "ready_count": len(drafts) - len(review_queue),
            "review_count": len(review_queue),
        }
    )

    return {
        "review_queue": [draft.model_dump() for draft in review_queue],
        "metrics": existing_metrics,
    }


def build_listing_graph(logger: WorkflowRunLogger | None = None):
    workflow = StateGraph(ListingWorkflowState)
    workflow.add_node(
        "load_candidates",
        _node("load_candidates", _load_candidates, logger, pass_logger=True),
    )
    workflow.add_node(
        "merge_main_images",
        _node("merge_main_images", _merge_main_images, logger),
    )
    workflow.add_node(
        "detect_size_reference",
        _node("detect_size_reference", _detect_size_reference, logger, pass_logger=True),
    )
    workflow.add_node(
        "select_enroute_reference",
        _node("select_enroute_reference", _select_enroute_reference, logger),
    )
    workflow.add_node(
        "analyze_enroute_reference",
        _node(
            "analyze_enroute_reference",
            _analyze_enroute_reference,
            logger,
            pass_logger=True,
        ),
    )
    workflow.add_node(
        "generate_wearing_image",
        _node("generate_wearing_image", _generate_wearing_image, logger, pass_logger=True),
    )
    workflow.add_node(
        "wait_manual_review",
        _node("wait_manual_review", _wait_manual_review, logger),
    )
    workflow.add_node(
        "mark_failed_and_reload_candidates",
        _node(
            "mark_failed_and_reload_candidates",
            _mark_failed_and_reload_candidates,
            logger,
        ),
    )
    workflow.add_node(
        "build_listing_drafts",
        _node("build_listing_drafts", _build_listing_drafts, logger),
    )
    workflow.add_node(
        "prepare_review_queue",
        _node("prepare_review_queue", _prepare_review_queue, logger),
    )

    workflow.add_edge(START, "load_candidates")
    workflow.add_edge("load_candidates", "merge_main_images")
    workflow.add_edge("merge_main_images", "detect_size_reference")
    workflow.add_conditional_edges(
        "detect_size_reference",
        _route("detect_size_reference", _size_reference_next_step, logger),
        {
            "retry_load_candidates": "load_candidates",
            "select_enroute_reference": "select_enroute_reference",
            "build_listing_drafts": "build_listing_drafts",
        },
    )
    workflow.add_edge("select_enroute_reference", "analyze_enroute_reference")
    workflow.add_edge("analyze_enroute_reference", "generate_wearing_image")
    workflow.add_edge("generate_wearing_image", "wait_manual_review")
    workflow.add_conditional_edges(
        "wait_manual_review",
        _route("wait_manual_review", _route_manual_review_decision, logger),
        {
            "build_listing_drafts": "build_listing_drafts",
            "generate_wearing_image": "generate_wearing_image",
            "mark_failed_and_reload_candidates": "mark_failed_and_reload_candidates",
        },
    )
    workflow.add_edge("mark_failed_and_reload_candidates", "load_candidates")
    workflow.add_edge("build_listing_drafts", "prepare_review_queue")
    workflow.add_edge("prepare_review_queue", END)

    return workflow


def compile_listing_graph(logger: WorkflowRunLogger | None = None, checkpointer=None):
    return build_listing_graph(logger=logger).compile(checkpointer=checkpointer)


def _node(
    node_name: str,
    func,
    logger: WorkflowRunLogger | None,
    *,
    pass_logger: bool = False,
):
    def invoke(state: ListingWorkflowState) -> ListingWorkflowState:
        active_logger = _logger_for_state(state, logger)

        def call(inner_state: ListingWorkflowState) -> ListingWorkflowState:
            if pass_logger:
                return func(inner_state, active_logger)
            return func(inner_state)

        output = wrap_node_with_logging(node_name, call, active_logger)(state)
        if logger is None and isinstance(output, dict):
            output = {**output, "workflow_log_path": str(active_logger.path)}
        return output

    return invoke


def _route(
    node_name: str,
    func,
    logger: WorkflowRunLogger | None,
):
    def route(state: ListingWorkflowState) -> str:
        return func(state, _logger_for_state(state, logger))

    return route


def _logger_for_state(
    state: ListingWorkflowState,
    logger: WorkflowRunLogger | None,
) -> WorkflowRunLogger:
    if logger is not None:
        return logger
    log_path = state.get("workflow_log_path")
    if log_path:
        return WorkflowRunLogger.from_existing_path(log_path)
    active_logger = WorkflowRunLogger(log_dir=_workflow_logs_dir(state))
    active_logger.write(
        "workflow_start",
        data={"input_state_keys": sorted(str(key) for key in state.keys())},
    )
    return active_logger


def _with_ai_checkpoint(
    state: ListingWorkflowState,
    update: ListingWorkflowState,
    *,
    checkpoint_key: str,
    checkpoint_input: dict[str, Any],
    checkpoint_result: dict[str, Any],
    source: str,
) -> ListingWorkflowState:
    checkpoint = _build_ai_checkpoint(
        checkpoint_key=checkpoint_key,
        checkpoint_input=checkpoint_input,
        checkpoint_result=checkpoint_result,
        source=source,
    )
    checkpoints = dict(state.get("ai_checkpoints") or {})
    existing = checkpoints.get(checkpoint_key)
    if isinstance(existing, dict):
        checkpoint["attempt_count"] = int(existing.get("attempt_count") or 0) + 1
    checkpoints[checkpoint_key] = checkpoint
    return {
        **update,
        "ai_checkpoints": checkpoints,
    }


def _build_ai_checkpoint(
    *,
    checkpoint_key: str,
    checkpoint_input: dict[str, Any],
    checkpoint_result: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    return {
        "key": checkpoint_key,
        "type": _checkpoint_type(checkpoint_key),
        "source": source,
        "input": _jsonable(checkpoint_input),
        "input_hash": _stable_hash(checkpoint_input),
        "status": str(checkpoint_result.get("status") or ""),
        "result": _jsonable(checkpoint_result),
        "attempt_count": 1,
    }


def _get_ai_checkpoint_result(
    state: ListingWorkflowState,
    checkpoint_key: str,
    checkpoint_input: dict[str, Any],
) -> dict[str, Any] | None:
    checkpoints = state.get("ai_checkpoints")
    if not isinstance(checkpoints, dict):
        return None
    checkpoint = checkpoints.get(checkpoint_key)
    if not isinstance(checkpoint, dict):
        return None
    if checkpoint.get("input_hash") != _stable_hash(checkpoint_input):
        return None
    if checkpoint.get("status") in {"failed", "error"}:
        return None
    result = checkpoint.get("result")
    if isinstance(result, dict) and result.get("status") in {"failed", "error"}:
        return None
    return dict(result) if isinstance(result, dict) else None


def _checkpoint_input(**items: Any) -> dict[str, Any]:
    return _jsonable(items)


def _checkpoint_type(checkpoint_key: str) -> str:
    if checkpoint_key.startswith("generate_wearing_image"):
        return "image_ai"
    return "llm"


def _selected_product_identity(state: ListingWorkflowState) -> dict[str, Any]:
    product = state.get("selected_product") or (
        state.get("candidates", [{}])[0] if state.get("candidates") else {}
    )
    if not isinstance(product, dict):
        return {}
    return {
        "id": product.get("id"),
        "product_id": product.get("product_id"),
        "platform": product.get("platform"),
        "status": product.get("status"),
    }


def _stable_hash(value: Any) -> str:
    raw = json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def _database_path(state: ListingWorkflowState) -> Path:
    return Path(state.get("database_path") or Settings().productv2_database_path)


def _raw_data_dir(state: ListingWorkflowState) -> Path:
    return Path(state.get("raw_data_dir") or Settings().productv2_raw_data_dir)


def _product_assets_dir(state: ListingWorkflowState) -> Path:
    return Path(
        state.get("product_assets_dir")
        or Settings().productv2_product_assets_dir
        or DEFAULT_PRODUCT_ASSETS_DIR
    )


def _enroute_bestsellers_dir(state: ListingWorkflowState) -> Path:
    return Path(
        state.get("enroute_bestsellers_dir")
        or Settings().productv2_enroute_bestsellers_dir
        or DEFAULT_ENROUTE_BESTSELLERS_DIR
    )


def _model_profiles_dir(state: ListingWorkflowState) -> Path:
    return Path(
        state.get("model_profiles_dir")
        or Settings().productv2_model_profiles_dir
        or DEFAULT_MODEL_PROFILES_DIR
    )


def _workflow_logs_dir(state: ListingWorkflowState) -> Path:
    return Path(
        state.get("workflow_logs_dir")
        or Settings().productv2_workflow_logs_dir
        or DEFAULT_WORKFLOW_LOGS_DIR
    )


def _call_with_optional_logger(func, *args, logger: WorkflowRunLogger | None = None, **kwargs):
    return func(*args, **_kwargs_with_optional_logger(func, logger=logger, **kwargs))


def _kwargs_with_optional_logger(
    func,
    logger: WorkflowRunLogger | None = None,
    **kwargs,
) -> dict[str, Any]:
    signature = inspect.signature(func)
    parameters = signature.parameters
    accepts_var_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    filtered_kwargs = {
        key: value
        for key, value in kwargs.items()
        if accepts_var_kwargs or key in parameters
    }
    if logger is None:
        return filtered_kwargs
    if "logger" in parameters or accepts_var_kwargs:
        return {**filtered_kwargs, "logger": logger}
    return filtered_kwargs
