"""Manual review domain models and state extraction helpers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class WearingImageReviewRequest(BaseModel):
    """Canonical workflow payload for one wearing-image manual review step."""

    type: Literal["wearing_image_review"] = "wearing_image_review"
    product: dict[str, Any] = Field(default_factory=dict)
    generated_image_path: str = ""
    generated_image_url: str = ""
    marked_main_image_path: str = ""
    marked_size_reference_image_path: str = ""
    enroute_reference_image_path: str = ""
    selected_model_profile: dict[str, Any] = Field(default_factory=dict)
    prompt: str = ""
    attempt: int = 1
    options: list[str] = Field(
        default_factory=lambda: ["approve", "regenerate", "reject"]
    )


class ManualReviewDecision(BaseModel):
    """Normalized human review decision used by workflow routing."""

    action: str = ""
    reason: str = ""


ReviewRequest = WearingImageReviewRequest


def parse_manual_review_request(value: Any) -> WearingImageReviewRequest | None:
    """Return a canonical review request when the payload matches the workflow contract."""

    if not isinstance(value, dict) or value.get("type") != "wearing_image_review":
        return None
    return WearingImageReviewRequest.model_validate(value)


def manual_review_payload_from_state(state: Any) -> dict[str, Any]:
    """Extract the first manual review payload from state values or interrupts."""

    if not isinstance(state, dict):
        return {}
    values = state.get("values")
    if isinstance(values, dict):
        request = parse_manual_review_request(values.get("manual_review_request"))
        if request is not None:
            return request.model_dump()
    for source in (state.get("interrupts"), _task_interrupts(state)):
        if not isinstance(source, list):
            continue
        for interrupt in source:
            value = interrupt.get("value") if isinstance(interrupt, dict) else None
            request = parse_manual_review_request(value)
            if request is not None:
                return request.model_dump()
    return {}


def normalize_manual_review_decision(value: Any) -> dict[str, Any]:
    """Normalize resume payloads from LangGraph interrupt responses."""

    if isinstance(value, dict):
        return ManualReviewDecision.model_validate(value).model_dump(exclude_none=True)
    if value is None:
        return ManualReviewDecision().model_dump(exclude_none=True)
    return ManualReviewDecision(action=str(value)).model_dump(exclude_none=True)


def build_wearing_image_review_request(
    *,
    product: dict[str, Any],
    wearing_image_result: dict[str, Any],
    attempt: int,
) -> dict[str, Any]:
    """Build the canonical review payload from workflow state fragments."""

    return WearingImageReviewRequest(
        product=product,
        generated_image_path=str(wearing_image_result.get("generated_image_path") or ""),
        generated_image_url=str(wearing_image_result.get("generated_image_url") or ""),
        marked_main_image_path=str(
            wearing_image_result.get("marked_main_image_path") or ""
        ),
        marked_size_reference_image_path=str(
            wearing_image_result.get("marked_size_reference_image_path") or ""
        ),
        enroute_reference_image_path=str(
            wearing_image_result.get("enroute_reference_image_path") or ""
        ),
        selected_model_profile=dict(
            wearing_image_result.get("selected_model_profile") or {}
        ),
        prompt=str(wearing_image_result.get("prompt") or ""),
        attempt=attempt,
    ).model_dump()


def _task_interrupts(state: dict[str, Any]) -> list[Any]:
    collected: list[Any] = []
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        return collected
    for task in tasks:
        interrupts = task.get("interrupts") if isinstance(task, dict) else None
        if isinstance(interrupts, list):
            collected.extend(interrupts)
    return collected
