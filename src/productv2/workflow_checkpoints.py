"""Workflow AI checkpoint helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from productv2.config import Settings, llm_provider_fingerprint
from productv2.prompt_loader import current_prompt_manifest


WorkflowState = dict[str, Any]


def _runtime_fingerprint() -> dict[str, Any]:
    """Identity of the prompt/model/provider stack feeding an AI checkpoint.

    Folding this into every checkpoint input means a prompt bump, model swap,
    or provider change invalidates cached results instead of silently reusing
    output produced by a different configuration.
    """

    settings = Settings()
    return {
        "prompts": current_prompt_manifest(),
        "model": settings.openai_model,
        "providers": llm_provider_fingerprint(settings),
    }



def with_ai_checkpoint(
    state: WorkflowState,
    update: WorkflowState,
    *,
    checkpoint_key: str,
    checkpoint_input: dict[str, Any],
    checkpoint_result: dict[str, Any],
    source: str,
) -> WorkflowState:
    checkpoint = build_ai_checkpoint(
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


def build_ai_checkpoint(
    *,
    checkpoint_key: str,
    checkpoint_input: dict[str, Any],
    checkpoint_result: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    return {
        "key": checkpoint_key,
        "type": checkpoint_type(checkpoint_key),
        "source": source,
        "input": jsonable(checkpoint_input),
        "input_hash": stable_hash(checkpoint_input),
        "status": str(checkpoint_result.get("status") or ""),
        "result": jsonable(checkpoint_result),
        "attempt_count": 1,
    }


def get_ai_checkpoint_result(
    state: WorkflowState,
    checkpoint_key: str,
    checkpoint_input: dict[str, Any],
) -> dict[str, Any] | None:
    checkpoints = state.get("ai_checkpoints")
    if not isinstance(checkpoints, dict):
        return None
    checkpoint = checkpoints.get(checkpoint_key)
    if not isinstance(checkpoint, dict):
        return None
    if checkpoint.get("input_hash") != stable_hash(checkpoint_input):
        return None
    if checkpoint.get("status") in {"failed", "error"}:
        return None
    result = checkpoint.get("result")
    if isinstance(result, dict) and result.get("status") in {"failed", "error"}:
        return None
    return dict(result) if isinstance(result, dict) else None


def checkpoint_input(**items: Any) -> dict[str, Any]:
    payload = jsonable(items)
    payload.setdefault("_runtime", _runtime_fingerprint())
    return payload


def checkpoint_type(checkpoint_key: str) -> str:
    if checkpoint_key.startswith("generate_wearing_image"):
        return "image_ai"
    return "llm"


def selected_product_identity(state: WorkflowState) -> dict[str, Any]:
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


def merge_checkpoint_update(
    state: WorkflowState,
    update: WorkflowState,
) -> WorkflowState:
    if state.get("ai_checkpoints"):
        return {**update, "ai_checkpoints": state["ai_checkpoints"]}
    return update


def stable_hash(value: Any) -> str:
    raw = json.dumps(jsonable(value), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(jsonable(item) for item in value)
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump())
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value
