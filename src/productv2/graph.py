"""LangGraph workflow for turning candidate products into listing drafts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from productv2.adapters import get_platform_adapter
from productv2.config import (
    DEFAULT_CANDIDATE_DATA,
    DEFAULT_DATABASE_PATH,
    DEFAULT_ENROUTE_BESTSELLERS_DIR,
    DEFAULT_MODEL_PROFILES_DIR,
    DEFAULT_PRODUCT_ASSETS_DIR,
    DEFAULT_WORKFLOW_LOGS_DIR,
)
from productv2.data import load_candidate_products
from productv2.db import (
    get_enroute_image_analysis,
    load_model_profiles,
    sync_default_model_profiles,
    upsert_enroute_image_analysis,
)
from productv2.enroute import select_enroute_wearing_reference
from productv2.images import merge_remote_images_to_numbered_collage, product_asset_dir
from productv2.models import CandidateProduct, ListingDraft
from productv2.reference_analysis import analyze_enroute_reference_image
from productv2.selection import select_unfinished_product_with_adapter
from productv2.state import initialize_product_state, mark_failed, set_extra
from productv2.vision import detect_size_reference_images
from productv2.wearing import generate_wearing_image
from productv2.workflow_logging import (
    WorkflowRunLogger,
    create_workflow_logger,
    log_branch_decision,
    wrap_node_with_logging,
)


class ListingWorkflowState(TypedDict, total=False):
    data_path: str
    database_path: str
    product_assets_dir: str
    enroute_bestsellers_dir: str
    model_profiles_dir: str
    workflow_log_path: str
    limit: int | None
    candidates: list[dict[str, Any]]
    drafts: list[dict[str, Any]]
    review_queue: list[dict[str, Any]]
    main_image_result: dict[str, Any]
    size_reference_result: dict[str, Any]
    enroute_reference_result: dict[str, Any]
    enroute_analysis_result: dict[str, Any]
    wearing_image_result: dict[str, Any]
    metrics: dict[str, Any]


def _load_candidates(state: ListingWorkflowState) -> ListingWorkflowState:
    data_path = state.get("data_path") or str(DEFAULT_CANDIDATE_DATA)
    path = Path(data_path)
    if path.exists():
        candidates = load_candidate_products(
            data_path=path,
            limit=state.get("limit"),
        )
        source = "json"
    else:
        selection = select_unfinished_product_with_adapter(
            database_path=state.get("database_path") or DEFAULT_DATABASE_PATH,
        )
        candidates = [selection.candidate] if selection.candidate else []
        if selection.candidate is not None:
            initialize_product_state(
                selection.candidate,
                database_path=state.get("database_path") or DEFAULT_DATABASE_PATH,
            )
        source = "database_adapter_selection"

    return {
        "candidates": [candidate.model_dump() for candidate in candidates],
        "metrics": {
            "candidate_count": len(candidates),
            "candidate_source": source,
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
            state.get("product_assets_dir") or DEFAULT_PRODUCT_ASSETS_DIR,
        )
        / "main_image_collage.jpg"
    )

    try:
        collage = merge_remote_images_to_numbered_collage(
            image_urls=image_urls,
            output_path=output_path,
        )
    except ValueError as exc:
        return {
            "main_image_result": {
                "status": "failed",
                "reason": str(exc),
                "source_image_count": len(image_urls),
            }
        }

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


def _detect_size_reference(state: ListingWorkflowState) -> ListingWorkflowState:
    main_image_result = state.get("main_image_result", {})
    if main_image_result.get("status") != "ok":
        return {
            "size_reference_result": {
                "status": "skipped",
                "reason": "main_image_not_ready",
            }
        }

    try:
        detection = detect_size_reference_images(main_image_result["path"])
    except Exception as exc:  # noqa: BLE001
        size_reference_result = {
            "status": "failed",
            "reason": f"{type(exc).__name__}: {exc}",
        }
        try:
            failed_product = mark_failed()
        except Exception as mark_exc:  # noqa: BLE001
            size_reference_result["mark_failed_error"] = (
                f"{type(mark_exc).__name__}: {mark_exc}"
            )
        else:
            size_reference_result["failed_product"] = {
                "product_id": failed_product.product_id,
                "platform": failed_product.platform,
                "status": failed_product.status,
            }
        set_extra("size_reference_detection", size_reference_result)
        return {"size_reference_result": size_reference_result}

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
    return {"size_reference_result": size_reference_result}


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

    reference = select_enroute_wearing_reference(
        candidates[0],
        library_dir=state.get("enroute_bestsellers_dir")
        or DEFAULT_ENROUTE_BESTSELLERS_DIR,
    )
    if reference is None:
        result = {
            "status": "skipped",
            "reason": "no_matching_enroute_reference",
        }
        set_extra("enroute_reference_selection", result)
        return {"enroute_reference_result": result}

    metadata = reference.metadata
    result = {
        "status": "ok",
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
    set_extra("selected_enroute_reference_image_path", str(reference.image_path))
    set_extra("selected_enroute_reference_metadata", result["metadata"])
    set_extra("enroute_reference_selection", result)
    return {"enroute_reference_result": result}


def _analyze_enroute_reference(state: ListingWorkflowState) -> ListingWorkflowState:
    enroute_reference_result = state.get("enroute_reference_result", {})
    if enroute_reference_result.get("status") != "ok":
        result = {
            "status": "skipped",
            "reason": enroute_reference_result.get("reason", "reference_not_ready"),
        }
        set_extra("enroute_reference_analysis", result)
        return {"enroute_analysis_result": result}

    enroute_product_id = str(enroute_reference_result.get("enroute_product_id") or "")
    database_path = state.get("database_path") or DEFAULT_DATABASE_PATH
    model_profiles = load_model_profiles(database_path)
    if enroute_product_id:
        cached = get_enroute_image_analysis(database_path, enroute_product_id)
        if cached is not None and _analysis_has_model_selection(
            cached["analysis_json"]
        ):
            result = {
                "status": "ok",
                "cache": "hit",
                "reference_image_path": cached["image_path"],
                "enroute_product_id": cached["enroute_product_id"],
                "category": cached["enroute_category"],
                "summary": cached["summary"],
                "analysis": cached["analysis_json"],
            }
            set_extra("enroute_reference_analysis", result)
            return {"enroute_analysis_result": result}

    try:
        analysis = analyze_enroute_reference_image(
            enroute_reference_result["image_path"],
            model_profiles=model_profiles,
        )
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "failed",
            "reason": f"{type(exc).__name__}: {exc}",
            "reference_image_path": enroute_reference_result["image_path"],
        }
        set_extra("enroute_reference_analysis", result)
        return {"enroute_analysis_result": result}

    analysis_json = analysis.model_dump()
    metadata = enroute_reference_result.get("metadata", {})
    summary = analysis.summary
    if enroute_product_id:
        upsert_enroute_image_analysis(
            database_path,
            enroute_product_id=enroute_product_id,
            enroute_category=enroute_reference_result.get("category", ""),
            enroute_title=str(metadata.get("title") or ""),
            enroute_handle=str(metadata.get("handle") or ""),
            image_path=enroute_reference_result["image_path"],
            image_position=2,
            analysis_json=analysis_json,
            summary=summary,
        )

    result = {
        "status": "ok",
        "cache": "miss",
        "reference_image_path": enroute_reference_result["image_path"],
        "enroute_product_id": enroute_product_id,
        "category": enroute_reference_result.get("category", ""),
        "summary": summary,
        "analysis": analysis_json,
    }
    set_extra("enroute_reference_analysis", result)
    return {"enroute_analysis_result": result}


def _analysis_has_model_selection(analysis_json: dict[str, Any]) -> bool:
    selected = analysis_json.get("selected_model_profile")
    return isinstance(selected, dict) and bool(selected.get("profile_key"))


def _generate_wearing_image(state: ListingWorkflowState) -> ListingWorkflowState:
    candidates = [
        CandidateProduct.model_validate(candidate)
        for candidate in state.get("candidates", [])
    ]
    if not candidates:
        return {"wearing_image_result": {"status": "skipped", "reason": "no_candidate"}}

    wearing_image_result = generate_wearing_image(
        candidates[0],
        state.get("size_reference_result", {}),
        state.get("enroute_analysis_result", {}),
        product_asset_dir(
            candidates[0],
            state.get("product_assets_dir") or DEFAULT_PRODUCT_ASSETS_DIR,
        ),
    )
    set_extra("wearing_image_generation", wearing_image_result)
    return {"wearing_image_result": wearing_image_result}


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
    workflow.add_node("load_candidates", _node("load_candidates", _load_candidates, logger))
    workflow.add_node("merge_main_images", _node("merge_main_images", _merge_main_images, logger))
    workflow.add_node(
        "detect_size_reference",
        _node("detect_size_reference", _detect_size_reference, logger),
    )
    workflow.add_node(
        "select_enroute_reference",
        _node("select_enroute_reference", _select_enroute_reference, logger),
    )
    workflow.add_node(
        "analyze_enroute_reference",
        _node("analyze_enroute_reference", _analyze_enroute_reference, logger),
    )
    workflow.add_node(
        "generate_wearing_image",
        _node("generate_wearing_image", _generate_wearing_image, logger),
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
        lambda state: _size_reference_next_step(state, logger),
        {
            "retry_load_candidates": "load_candidates",
            "select_enroute_reference": "select_enroute_reference",
            "build_listing_drafts": "build_listing_drafts",
        },
    )
    workflow.add_edge("select_enroute_reference", "analyze_enroute_reference")
    workflow.add_edge("analyze_enroute_reference", "generate_wearing_image")
    workflow.add_edge("generate_wearing_image", "build_listing_drafts")
    workflow.add_edge("build_listing_drafts", "prepare_review_queue")
    workflow.add_edge("prepare_review_queue", END)

    return workflow.compile()


def _node(
    node_name: str,
    func,
    logger: WorkflowRunLogger | None,
):
    if logger is None:
        return func
    return wrap_node_with_logging(node_name, func, logger)


def run_listing_workflow(
    data_path: str | Path = DEFAULT_CANDIDATE_DATA,
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    product_assets_dir: str | Path = DEFAULT_PRODUCT_ASSETS_DIR,
    enroute_bestsellers_dir: str | Path = DEFAULT_ENROUTE_BESTSELLERS_DIR,
    model_profiles_dir: str | Path = DEFAULT_MODEL_PROFILES_DIR,
    workflow_logs_dir: str | Path | None = None,
    limit: int | None = 5,
) -> ListingWorkflowState:
    sync_default_model_profiles(database_path, model_profiles_dir)
    logger = create_workflow_logger(
        workflow_logs_dir
        if workflow_logs_dir is not None
        else DEFAULT_WORKFLOW_LOGS_DIR
    )
    logger.write(
        "workflow_start",
        data={
            "data_path": str(data_path),
            "database_path": str(database_path),
            "product_assets_dir": str(product_assets_dir),
            "enroute_bestsellers_dir": str(enroute_bestsellers_dir),
            "model_profiles_dir": str(model_profiles_dir),
            "limit": limit,
            "log_path": str(logger.path),
        },
    )
    graph = build_listing_graph(logger=logger)
    try:
        result = graph.invoke(
            {
                "data_path": str(data_path),
                "database_path": str(database_path),
                "product_assets_dir": str(product_assets_dir),
                "enroute_bestsellers_dir": str(enroute_bestsellers_dir),
                "model_profiles_dir": str(model_profiles_dir),
                "workflow_log_path": str(logger.path),
                "limit": limit,
            }
        )
    except Exception as exc:
        logger.write(
            "workflow_error",
            data={"error_type": type(exc).__name__, "error": str(exc)},
        )
        raise
    logger.write(
        "workflow_end",
        data={"metrics": result.get("metrics", {}), "log_path": str(logger.path)},
    )
    return result
