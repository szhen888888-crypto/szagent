"""LangGraph workflow for product image processing."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from productv2.adapters import get_platform_adapter
from productv2.config import Settings
from productv2.data import load_candidate_products
from productv2.db import (
    FAILED_STATUS,
    get_enroute_image_analysis,
    import_raw_data_directory,
    load_model_profiles,
    sync_default_model_profiles,
    update_product_fields,
    upsert_enroute_image_analysis,
)
from productv2.enroute import EnrouteReference
from productv2.enroute_learning import (
    enroute_analysis_is_valid_profile,
    mark_enroute_reference_failed,
    mark_enroute_reference_learned,
    mark_enroute_reference_learning,
    plan_enroute_learning_for_candidate,
    reference_from_learning_row,
    valid_enroute_analysis_cache,
)
from productv2.images import merge_remote_images_to_numbered_collage, product_asset_dir
from productv2.manual_review import (
    REVIEW_ACTION_APPROVE,
    REVIEW_ACTION_RECOMPILE_PROMPT,
    REVIEW_ACTION_REGENERATE,
    REVIEW_ACTION_REJECT,
    build_wearing_image_review_request,
    normalize_manual_review_decision,
)
from productv2.models import CandidateProduct, ListingDraft
from productv2.reference_analysis_service import (
    analyze_enroute_reference_image,
    select_wearing_style_profile,
    summarize_enroute_profile,
)
from productv2.selection import select_unfinished_product_with_adapter
from productv2.state import initialize_product_state, set_extra
from productv2.vision import detect_size_reference_images
from productv2.wearing import compile_wearing_generation_prompt, generate_wearing_image
from productv2.workflow_checkpoints import (
    checkpoint_input as build_checkpoint_input,
    get_ai_checkpoint_result,
    merge_checkpoint_update,
    selected_product_identity,
    with_ai_checkpoint,
)
from productv2.workflow_logging import (
    WorkflowRunLogger,
    log_branch_decision,
    wrap_node_with_logging,
)
from productv2.workflow_paths import (
    database_path as resolve_database_path,
    model_profiles_dir,
    product_assets_dir,
    raw_data_dir,
    workflow_logs_dir,
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
    enroute_learning_result: dict[str, Any]
    enroute_analysis_result: dict[str, Any]
    wearing_style_selection_result: dict[str, Any]
    wearing_generation_prompt_result: dict[str, Any]
    wearing_image_result: dict[str, Any]
    wearing_generation_attempt: int
    manual_review_request: dict[str, Any]
    manual_review_decision: dict[str, Any]
    approved_product: dict[str, Any]
    failed_product: dict[str, Any]
    ai_checkpoints: dict[str, Any]
    metrics: dict[str, Any]


MAX_WEARING_REGENERATE_ATTEMPTS = 3
PROMPT_RETRY_REVIEW_ACTIONS = {REVIEW_ACTION_RECOMPILE_PROMPT}
IMAGE_RETRY_REVIEW_ACTIONS = {REVIEW_ACTION_REGENERATE, *PROMPT_RETRY_REVIEW_ACTIONS}
ENROUTE_LEARNING_TARGET_CACHE_SIZE = 5
ENROUTE_LEARNING_INITIAL_BATCH_SIZE = 5
ENROUTE_LEARNING_INCREMENTAL_BATCH_SIZE = 1
APPROVED_STATUS = "done"


def _load_candidates(
    state: ListingWorkflowState,
    logger: WorkflowRunLogger | None = None,
) -> ListingWorkflowState:
    db_path = resolve_database_path(state)
    raw_import_summary = import_raw_data_directory(
        database_path=db_path,
        raw_data_dir=raw_data_dir(state),
    )
    sync_default_model_profiles(
        db_path,
        model_profiles_dir(state),
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
            database_path=db_path,
        )
        candidates = [selection.candidate] if selection.candidate else []
        if selection.candidate is not None:
            initialize_product_state(
                selection.candidate,
                database_path=db_path,
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
            product_assets_dir(state),
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
    checkpoint_input = build_checkpoint_input(
        product=selected_product_identity(state),
        collage_path=main_image_result.get("path", ""),
        source_image_count=main_image_result.get("source_image_count", 0),
        numbered_sources=main_image_result.get("numbered_sources", []),
    )
    cached = get_ai_checkpoint_result(state, checkpoint_key, checkpoint_input)
    if cached is not None:
        result = dict(cached)
        result["checkpoint"] = "hit"
        set_extra("size_reference_detection", result)
        return with_ai_checkpoint(
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
        database_path=resolve_database_path(state),
    )

    size_reference_result = {
        "status": "ok",
        "is_product_qualified": detection.is_product_qualified,
        "qualification_checks": _qualification_checks_from_detection(detection),
        "failed_checks": detection.failed_checks,
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
    size_reference_ready = _has_required_size_reference(size_reference_result)
    failed_checks = [
        str(item)
        for item in size_reference_result.get("failed_checks", [])
        if str(item).strip()
    ]
    if not size_reference_ready and "size_reference" not in failed_checks:
        failed_checks.append("size_reference")
    if not size_reference_result.get("is_product_qualified", True) and not failed_checks:
        failed_checks.append("product_qualification")
    if failed_checks or not size_reference_ready:
        size_reference_result["status"] = "failed"
        size_reference_result["is_product_qualified"] = False
        size_reference_result["failed_checks"] = failed_checks
        qualification_checks = dict(size_reference_result.get("qualification_checks") or {})
        if not size_reference_ready:
            qualification_checks["size_reference"] = {
                "passed": False,
                "reason": (
                    size_reference_result.get("reason")
                    or "未检测到可用于判断尺寸比例的佩戴或人体参照图"
                ),
                "image_numbers": size_reference_result.get("image_numbers", []),
                "size_reference_image_number": size_reference_result.get(
                    "size_reference_image_number"
                ),
            }
        size_reference_result["qualification_checks"] = qualification_checks
        size_reference_result["failure_type"] = "product_unqualified"
        size_reference_result["failure_detail"] = (
            "size_reference_unusable"
            if "size_reference" in failed_checks
            else failed_checks[0]
        )
        size_reference_result["reason"] = (
            size_reference_result.get("reason")
            or "未检测到可用于判断尺寸比例的佩戴或人体参照图"
        )
    set_extra("size_reference_detection", size_reference_result)
    return with_ai_checkpoint(
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
        branch = "mark_failed_and_reload_candidates"
    elif state.get("size_reference_result", {}).get("status") == "ok":
        branch = "select_enroute_reference"
    else:
        branch = "build_listing_drafts"
    if logger is not None:
        log_branch_decision(logger, "detect_size_reference", branch, state)
    return branch


def _has_required_size_reference(size_reference_result: dict[str, Any]) -> bool:
    selected_images = size_reference_result.get("selected_images", {})
    if not isinstance(selected_images, dict):
        return False
    return (
        bool(size_reference_result.get("can_judge_size"))
        and bool(size_reference_result.get("size_reference_image_number"))
        and bool((selected_images.get("main_image") or {}).get("path"))
        and bool((selected_images.get("size_reference_image") or {}).get("path"))
    )


def _qualification_checks_from_detection(detection: Any) -> dict[str, Any]:
    checks = dict(getattr(detection, "qualification_checks", {}) or {})
    checks.setdefault(
        "size_reference",
        {
            "passed": bool(getattr(detection, "can_judge_size", False)),
            "image_numbers": list(getattr(detection, "image_numbers", []) or []),
            "size_reference_image_number": getattr(
                detection,
                "size_reference_image_number",
                None,
            ),
            "reason": str(getattr(detection, "reason", "") or ""),
        },
    )
    return checks


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

    database_path = resolve_database_path(state)
    plan = plan_enroute_learning_for_candidate(
        candidates[0],
        database_path=database_path,
        target_cache_size=ENROUTE_LEARNING_TARGET_CACHE_SIZE,
        initial_batch_size=ENROUTE_LEARNING_INITIAL_BATCH_SIZE,
        incremental_batch_size=ENROUTE_LEARNING_INCREMENTAL_BATCH_SIZE,
    )
    if plan.category is None or not plan.references:
        result = {
            "status": "skipped",
            "reason": "no_matching_enroute_reference",
        }
        set_extra("enroute_reference_selection", result)
        return {"enroute_reference_result": result}

    result = {
        "status": "ok",
        "category": plan.category,
        "reference_count": len(plan.references),
        "reference_source": "database",
        "cached_analysis_count": plan.cached_analysis_count,
        "unlearned_count": len(plan.unlearned_rows),
        "learning_count": len(plan.learning_rows),
        "cache_status_synced_count": plan.cache_status_synced_count,
        "learning_references": [
            _enroute_reference_payload(reference_from_learning_row(row))
            for row in plan.learning_rows
        ],
        "learning_reference_rows": plan.learning_rows,
    }
    set_extra("enroute_reference_selection", result)
    return {"enroute_reference_result": result}


def _learn_enroute_profiles(
    state: ListingWorkflowState,
    logger: WorkflowRunLogger | None = None,
) -> ListingWorkflowState:
    enroute_reference_result = state.get("enroute_reference_result", {})
    if enroute_reference_result.get("status") != "ok":
        result = {
            "status": "skipped",
            "reason": enroute_reference_result.get("reason", "reference_not_ready"),
        }
        set_extra("enroute_profile_learning", result)
        return {"enroute_learning_result": result}

    database_path = resolve_database_path(state)
    category = str(enroute_reference_result.get("category") or "")
    if not category:
        result = {
            "status": "skipped",
            "reason": "enroute_category_missing",
        }
        set_extra("enroute_profile_learning", result)
        return {"enroute_learning_result": result}

    learning_references = _learning_references_from_result(
        enroute_reference_result,
        category,
    )
    if learning_references:
        _learn_enroute_references(
            state,
            database_path=database_path,
            references=learning_references,
            logger=logger,
        )

    cached = valid_enroute_analysis_cache(database_path, category)
    result = {
        "status": "ok",
        "category": category,
        "learning_count": len(learning_references),
        "cached_analysis_count_after_learning": len(cached),
    }
    set_extra("enroute_profile_learning", result)
    return merge_checkpoint_update(
        state,
        {
            "enroute_learning_result": result,
            "enroute_reference_result": {
                **enroute_reference_result,
                "cached_analysis_count_after_learning": len(cached),
            },
        },
    )


def _select_wearing_style_profile(
    state: ListingWorkflowState,
    logger: WorkflowRunLogger | None = None,
) -> ListingWorkflowState:
    enroute_reference_result = state.get("enroute_reference_result", {})
    if enroute_reference_result.get("status") != "ok":
        result = {
            "status": "skipped",
            "reason": enroute_reference_result.get("reason", "reference_not_ready"),
        }
        set_extra("wearing_style_profile_selection", result)
        return {
            "wearing_style_selection_result": result,
            "enroute_analysis_result": result,
        }

    database_path = resolve_database_path(state)
    category = str(enroute_reference_result.get("category") or "")
    if not category:
        result = {
            "status": "skipped",
            "reason": "enroute_category_missing",
        }
        set_extra("wearing_style_profile_selection", result)
        return {
            "wearing_style_selection_result": result,
            "enroute_analysis_result": result,
        }

    cached = valid_enroute_analysis_cache(database_path, category)
    if not cached:
        result = {
            "status": "skipped",
            "reason": "no_cached_enroute_analysis",
            "category": category,
        }
        set_extra("wearing_style_profile_selection", result)
        return {
            "wearing_style_selection_result": result,
            "enroute_analysis_result": result,
        }

    enroute_summaries = _enroute_cache_summaries(cached)
    model_profiles = load_model_profiles(database_path)
    model_summaries = _model_profile_summaries(model_profiles)
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
        }
        set_extra("wearing_style_profile_selection", result)
        return {
            "wearing_style_selection_result": result,
            "enroute_analysis_result": result,
        }

    checkpoint_key = "select_wearing_style_profile"
    checkpoint_input = build_checkpoint_input(
        main_image_path=main_image_path,
        size_reference_image_path=size_reference_image_path,
        enroute_profile_summaries=enroute_summaries,
        model_profile_summaries=model_summaries,
    )
    cached_checkpoint = get_ai_checkpoint_result(
        state,
        checkpoint_key,
        checkpoint_input,
    )
    if cached_checkpoint is not None:
        result = dict(cached_checkpoint)
        result["checkpoint"] = "hit"
        set_extra("wearing_style_profile_selection", result)
        return with_ai_checkpoint(
            state,
            {
                "wearing_style_selection_result": result,
                "enroute_analysis_result": result,
            },
            checkpoint_key=checkpoint_key,
            checkpoint_input=checkpoint_input,
            checkpoint_result=result,
            source="state_hit",
        )

    selection = select_wearing_style_profile(
        main_image_path,
        size_reference_image_path,
        enroute_summaries,
        model_summaries,
        **_kwargs_with_optional_logger(
            select_wearing_style_profile,
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
    selected_model = _find_model_profile(
        model_profiles,
        selection.selected_model_profile_key,
    )
    if selected_model is None:
        raise ValueError(
            "Selected model profile is not in model_profiles: "
            f"{selection.selected_model_profile_key or '<empty>'}"
        )

    result = {
        "status": "ok",
        "cache": "selected",
        "reference_image_path": selected["image_path"],
        "enroute_reference_image_path": selected["image_path"],
        "enroute_product_id": selected["enroute_product_id"],
        "category": selected["enroute_category"],
        "summary": selected["summary"],
        "analysis": selected["analysis_json"],
        "selected_model_profile": selected_model,
        "selection": selection.model_dump(),
    }
    set_extra("wearing_style_profile_selection", result)
    set_extra("selected_enroute_reference_image_path", selected["image_path"])
    set_extra(
        "enroute_reference_selection",
        {
            **enroute_reference_result,
            "selected_enroute_product_id": selected["enroute_product_id"],
            "selected_image_path": selected["image_path"],
            "selection_reason": selection.reason,
            "selected_model_profile_key": selection.selected_model_profile_key,
        },
    )
    return with_ai_checkpoint(
        state,
        {
            "wearing_style_selection_result": result,
            "enroute_analysis_result": result,
            "enroute_reference_result": {
                **enroute_reference_result,
                "selected_enroute_product_id": selected["enroute_product_id"],
                "selected_image_path": selected["image_path"],
                "selection_reason": selection.reason,
                "selected_model_profile_key": selection.selected_model_profile_key,
            },
        },
        checkpoint_key=checkpoint_key,
        checkpoint_input=checkpoint_input,
        checkpoint_result=result,
        source="llm_selector",
    )


def _compile_wearing_generation_prompt(
    state: ListingWorkflowState,
    logger: WorkflowRunLogger | None = None,
) -> ListingWorkflowState:
    candidates = [
        CandidateProduct.model_validate(candidate)
        for candidate in state.get("candidates", [])
    ]
    if not candidates:
        return {
            "wearing_generation_prompt_result": {
                "status": "skipped",
                "reason": "no_candidate",
            }
        }

    selection_result = state.get("wearing_style_selection_result", {})
    if selection_result.get("status") != "ok":
        result = {
            "status": "skipped",
            "reason": selection_result.get("reason", "style_profile_not_ready"),
        }
        set_extra("wearing_generation_prompt", result)
        return {"wearing_generation_prompt_result": result}

    enroute_profile = _enroute_profile_from_selection(selection_result)
    model_profile = dict(selection_result.get("selected_model_profile") or {})
    if not enroute_profile or not model_profile:
        result = {
            "status": "skipped",
            "reason": "selected_enroute_or_model_profile_missing",
        }
        set_extra("wearing_generation_prompt", result)
        return {"wearing_generation_prompt_result": result}

    checkpoint_key = "compile_wearing_generation_prompt"
    checkpoint_input = build_checkpoint_input(
        product=selected_product_identity(state),
        size_reference_result=state.get("size_reference_result", {}),
        wearing_style_selection_result=selection_result,
        product_assets_dir=str(
            product_asset_dir(candidates[0], product_assets_dir(state))
        ),
    )
    review_action = str(
        state.get("manual_review_decision", {}).get("action") or ""
    ).lower()
    cached = (
        None
        if review_action in PROMPT_RETRY_REVIEW_ACTIONS
        else get_ai_checkpoint_result(state, checkpoint_key, checkpoint_input)
    )
    if cached is not None:
        result = dict(cached)
        missing = [
            path
            for path in result.get("input_images", [])
            if path and not Path(str(path)).is_file()
        ]
        if not missing:
            result["checkpoint"] = "hit"
            set_extra("wearing_generation_prompt", result)
            return with_ai_checkpoint(
                state,
                {"wearing_generation_prompt_result": result},
                checkpoint_key=checkpoint_key,
                checkpoint_input=checkpoint_input,
                checkpoint_result=result,
                source="state_hit",
            )

    result = compile_wearing_generation_prompt(
        candidates[0],
        state.get("size_reference_result", {}),
        enroute_profile,
        model_profile,
        selection_reason=str(
            (selection_result.get("selection") or {}).get("reason")
            or selection_result.get("reason")
            or ""
        ),
        output_dir=product_asset_dir(candidates[0], product_assets_dir(state)),
        logger=logger,
        database_path=resolve_database_path(state),
    )
    set_extra("wearing_generation_prompt", result)
    return with_ai_checkpoint(
        state,
        {"wearing_generation_prompt_result": result},
        checkpoint_key=checkpoint_key,
        checkpoint_input=checkpoint_input,
        checkpoint_result=result,
        source="llm_compiler",
    )


def _learn_enroute_references(
    state: ListingWorkflowState,
    *,
    database_path: str | Path,
    references: list[EnrouteReference],
    logger: WorkflowRunLogger | None = None,
) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    for reference in references:
        result = _learn_one_enroute_reference(
            state,
            database_path,
            reference,
            logger,
        )
        outputs.append(result)
    return outputs


def _learn_one_enroute_reference(
    state: ListingWorkflowState,
    database_path: str | Path,
    reference: EnrouteReference,
    logger: WorkflowRunLogger | None,
) -> dict[str, Any]:
    cached = get_enroute_image_analysis(database_path, reference.product_id)
    if cached is not None and enroute_analysis_is_valid_profile(cached["analysis_json"]):
        mark_enroute_reference_learned(
            database_path,
            reference,
            analysis_id=int(cached["id"]),
            workflow_log_path=str(state.get("workflow_log_path") or ""),
        )
        result = _enroute_cached_analysis_result(cached, cache="hit")
        return result

    workflow_log_path = str(state.get("workflow_log_path") or "")
    mark_enroute_reference_learning(
        database_path,
        reference,
        workflow_log_path=workflow_log_path,
    )
    try:
        analysis = analyze_enroute_reference_image(
            reference.image_path,
            **_kwargs_with_optional_logger(
                analyze_enroute_reference_image,
                logger=logger,
                database_path=database_path,
            ),
        )
    except Exception as exc:
        mark_enroute_reference_failed(
            database_path,
            reference,
            error=f"{type(exc).__name__}: {exc}",
            workflow_log_path=workflow_log_path,
        )
        raise

    analysis_json = analysis.model_dump()
    metadata = reference.metadata
    cached_analysis = upsert_enroute_image_analysis(
        database_path,
        enroute_product_id=reference.product_id,
        enroute_category=reference.category,
        enroute_title=str(metadata.get("title") or ""),
        enroute_handle=str(metadata.get("handle") or ""),
        image_path=str(reference.image_path),
        image_position=2,
        analysis_json=analysis_json,
        summary=summarize_enroute_profile(analysis_json),
    )
    mark_enroute_reference_learned(
        database_path,
        reference,
        analysis_id=int(cached_analysis["id"]),
        workflow_log_path=workflow_log_path,
    )
    result = {
        "status": "ok",
        "cache": "miss",
        "reference_image_path": str(reference.image_path),
        "enroute_product_id": reference.product_id,
        "category": reference.category,
        "summary": summarize_enroute_profile(analysis_json),
        "analysis": analysis_json,
    }
    return result


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


def _model_profile_summaries(model_profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "profile_key": str(profile.get("profile_key") or ""),
            "name": str(profile.get("name") or ""),
            "summary": str(profile.get("summary") or ""),
            "image_path": str(profile.get("image_path") or ""),
        }
        for profile in model_profiles
        if str(profile.get("profile_key") or "")
    ]


def _find_model_profile(
    model_profiles: list[dict[str, Any]],
    profile_key: str,
) -> dict[str, Any] | None:
    selected_key = str(profile_key or "")
    for profile in model_profiles:
        if str(profile.get("profile_key") or "") == selected_key:
            return dict(profile)
    return None


def _enroute_profile_from_selection(selection_result: dict[str, Any]) -> dict[str, Any]:
    analysis = selection_result.get("analysis")
    if not isinstance(analysis, dict):
        return {}
    return {
        "enroute_product_id": str(selection_result.get("enroute_product_id") or ""),
        "category": str(selection_result.get("category") or ""),
        "summary": str(selection_result.get("summary") or ""),
        "image_path": str(
            selection_result.get("reference_image_path")
            or selection_result.get("enroute_reference_image_path")
            or ""
        ),
        "analysis": analysis,
    }


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


def _learning_references_from_result(
    enroute_reference_result: dict[str, Any],
    category: str,
) -> list[EnrouteReference]:
    rows = [
        item
        for item in enroute_reference_result.get("learning_reference_rows", [])
        if isinstance(item, dict)
    ]
    if rows:
        return [reference_from_learning_row(row) for row in rows]

    return [
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


def merge_checkpoint_update(
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
        database_path=resolve_database_path(state),
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


def _mark_current_candidate_approved(
    state: ListingWorkflowState,
) -> dict[str, Any]:
    decision = state.get("manual_review_decision", {})
    if str(decision.get("action") or "").lower() != "approve":
        return {}
    candidates = [
        CandidateProduct.model_validate(candidate)
        for candidate in state.get("candidates", [])
    ]
    if not candidates:
        return {}
    candidate = candidates[0]
    if candidate.id is None:
        return {}
    wearing_image_result = state.get("wearing_image_result", {})
    generated_image_path = (
        str(wearing_image_result.get("generated_image_path") or "")
        if isinstance(wearing_image_result, dict)
        else ""
    )
    if not generated_image_path:
        raise ValueError("Cannot approve product without generated wearing image path.")
    approved_product = update_product_fields(
        database_path=resolve_database_path(state),
        product_id=candidate.product_id,
        platform=candidate.platform,
        status=APPROVED_STATUS,
        wearing_image=generated_image_path,
        locked_at=None,
        locked_by=None,
    )
    return {
        "product_id": approved_product.product_id,
        "platform": approved_product.platform,
        "status": approved_product.status,
        "wearing_image": approved_product.wearing_image,
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
    should_regenerate = (
        str(review_decision.get("action") or "").lower() in IMAGE_RETRY_REVIEW_ACTIONS
    )
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
    checkpoint_input = build_checkpoint_input(
        product=selected_product_identity(state),
        attempt=next_attempt,
        wearing_generation_prompt_result=state.get(
            "wearing_generation_prompt_result",
            {},
        ),
        product_assets_dir=str(
            product_asset_dir(
                candidates[0],
                product_assets_dir(state),
            )
        ),
    )
    cached = None if should_regenerate else get_ai_checkpoint_result(
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
            return with_ai_checkpoint(
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
        state.get("wearing_generation_prompt_result", {}),
        product_asset_dir(
            candidates[0],
            product_assets_dir(state),
        ),
        logger=logger,
        attempt=next_attempt,
        database_path=resolve_database_path(state),
    )
    set_extra("wearing_image_generation", wearing_image_result)
    return with_ai_checkpoint(
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

    payload = build_wearing_image_review_request(
        product=state.get("selected_product") or (
            state.get("candidates", [{}])[0] if state.get("candidates") else {}
        ),
        wearing_image_result=wearing_image_result,
        attempt=int(state.get("wearing_generation_attempt") or 1),
    )
    decision = interrupt(payload)
    return {
        "manual_review_request": payload,
        "manual_review_decision": normalize_manual_review_decision(decision),
    }


def _route_manual_review_decision(
    state: ListingWorkflowState,
    logger: WorkflowRunLogger | None = None,
) -> str:
    decision = state.get("manual_review_decision", {})
    action = str(decision.get("action") or "").lower()
    if action == REVIEW_ACTION_APPROVE:
        branch = "build_listing_drafts"
    elif action == REVIEW_ACTION_REGENERATE:
        attempt = int(state.get("wearing_generation_attempt") or 0)
        branch = (
            "generate_wearing_image"
            if attempt < MAX_WEARING_REGENERATE_ATTEMPTS
            else "mark_failed_and_reload_candidates"
        )
    elif action == REVIEW_ACTION_RECOMPILE_PROMPT:
        attempt = int(state.get("wearing_generation_attempt") or 0)
        branch = (
            "compile_wearing_generation_prompt"
            if attempt < MAX_WEARING_REGENERATE_ATTEMPTS
            else "mark_failed_and_reload_candidates"
        )
    elif action == REVIEW_ACTION_REJECT:
        branch = "mark_failed_and_reload_candidates"
    else:
        branch = "mark_failed_and_reload_candidates"
    if logger is not None:
        log_branch_decision(logger, "wait_manual_review", branch, state)
    return branch


def _mark_failed_and_reload_candidates(
    state: ListingWorkflowState,
) -> ListingWorkflowState:
    failure_reason = str(
        state.get("manual_review_decision", {}).get("reason")
        or state.get("size_reference_result", {}).get("reason")
        or ""
    )
    failed_product = _mark_current_candidate_failed(
        state,
        reason=failure_reason,
    )
    return {
        "candidates": [],
        "selected_product": {},
        "failed_product": failed_product,
        "manual_review_request": {},
        "manual_review_decision": {},
        "size_reference_result": {},
        "wearing_image_result": {},
        "wearing_generation_attempt": 0,
    }


def _build_listing_drafts(state: ListingWorkflowState) -> ListingWorkflowState:
    candidates = [
        CandidateProduct.model_validate(candidate)
        for candidate in state.get("candidates", [])
    ]
    drafts = [ListingDraft.from_candidate(candidate) for candidate in candidates]
    approved_product = _mark_current_candidate_approved(state)
    selected_product = dict(state.get("selected_product") or {})
    if approved_product:
        selected_product.update(
            {
                "status": approved_product["status"],
                "wearing_image": approved_product["wearing_image"],
                "locked_at": None,
                "locked_by": None,
            }
        )

    return {
        "drafts": [draft.model_dump() for draft in drafts],
        "selected_product": selected_product,
        "approved_product": approved_product,
    }


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
    if state.get("enroute_learning_result"):
        existing_metrics["enroute_learning_result"] = state["enroute_learning_result"]
    if state.get("enroute_analysis_result"):
        existing_metrics["enroute_analysis_result"] = state["enroute_analysis_result"]
    if state.get("wearing_style_selection_result"):
        existing_metrics["wearing_style_selection_result"] = state[
            "wearing_style_selection_result"
        ]
    if state.get("wearing_generation_prompt_result"):
        existing_metrics["wearing_generation_prompt_result"] = state[
            "wearing_generation_prompt_result"
        ]
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
        "learn_enroute_profiles",
        _node(
            "learn_enroute_profiles",
            _learn_enroute_profiles,
            logger,
            pass_logger=True,
        ),
    )
    workflow.add_node(
        "select_wearing_style_profile",
        _node(
            "select_wearing_style_profile",
            _select_wearing_style_profile,
            logger,
            pass_logger=True,
        ),
    )
    workflow.add_node(
        "compile_wearing_generation_prompt",
        _node(
            "compile_wearing_generation_prompt",
            _compile_wearing_generation_prompt,
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
            "mark_failed_and_reload_candidates": "mark_failed_and_reload_candidates",
            "select_enroute_reference": "select_enroute_reference",
            "build_listing_drafts": "build_listing_drafts",
        },
    )
    workflow.add_edge("select_enroute_reference", "learn_enroute_profiles")
    workflow.add_edge("learn_enroute_profiles", "select_wearing_style_profile")
    workflow.add_edge(
        "select_wearing_style_profile",
        "compile_wearing_generation_prompt",
    )
    workflow.add_edge("compile_wearing_generation_prompt", "generate_wearing_image")
    workflow.add_edge("generate_wearing_image", "wait_manual_review")
    workflow.add_conditional_edges(
        "wait_manual_review",
        _route("wait_manual_review", _route_manual_review_decision, logger),
        {
            "build_listing_drafts": "build_listing_drafts",
            "compile_wearing_generation_prompt": "compile_wearing_generation_prompt",
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
    active_logger = WorkflowRunLogger(log_dir=workflow_logs_dir(state))
    active_logger.write(
        "workflow_start",
        data={"input_state_keys": sorted(str(key) for key in state.keys())},
    )
    return active_logger


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
