"""Per-run workflow JSONL logging."""

from __future__ import annotations

import json
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from productv2.config import DEFAULT_WORKFLOW_LOGS_DIR


class WorkflowRunLogger:
    """Append structured events for one workflow run."""

    def __init__(
        self,
        log_dir: str | Path = DEFAULT_WORKFLOW_LOGS_DIR,
        run_id: str | None = None,
    ) -> None:
        self.run_id = run_id or _new_run_id()
        self.path = Path(log_dir) / f"{self.run_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        event: str,
        *,
        node: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "run_id": self.run_id,
            "event": event,
            "node": node,
            "data": _jsonable(data or {}),
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            file.write("\n")


def create_workflow_logger(
    log_dir: str | Path = DEFAULT_WORKFLOW_LOGS_DIR,
) -> WorkflowRunLogger:
    return WorkflowRunLogger(log_dir=log_dir)


def wrap_node_with_logging(
    node_name: str,
    func: Callable[[dict[str, Any]], dict[str, Any]],
    logger: WorkflowRunLogger,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Wrap a LangGraph node to log input, output, and exceptions."""

    def wrapped(state: dict[str, Any]) -> dict[str, Any]:
        logger.write(
            "node_start",
            node=node_name,
            data={
                "input": state,
                "summary": summarize_state(state),
            },
        )
        try:
            output = func(state)
        except Exception as exc:
            logger.write(
                "node_error",
                node=node_name,
                data={
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                },
            )
            raise

        logger.write(
            "node_end",
            node=node_name,
            data={
                "output": output,
                "summary": summarize_state(output),
                "decisions": extract_decisions(output),
            },
        )
        return output

    return wrapped


def log_branch_decision(
    logger: WorkflowRunLogger,
    node_name: str,
    branch_name: str,
    state: dict[str, Any],
) -> None:
    logger.write(
        "branch_decision",
        node=node_name,
        data={
            "branch": branch_name,
            "summary": summarize_state(state),
            "decisions": extract_decisions(state),
        },
    )


def summarize_state(value: Any) -> Any:
    if isinstance(value, dict):
        summary: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"rawdata", "prompt", "analysis"}:
                summary[key] = _summarize_large_value(item)
            elif isinstance(item, (dict, list)):
                summary[key] = summarize_state(item)
            else:
                summary[key] = item
        return summary
    if isinstance(value, list):
        if len(value) > 10:
            return {
                "count": len(value),
                "items": [summarize_state(item) for item in value[:10]],
                "truncated": True,
            }
        return [summarize_state(item) for item in value]
    return value


def extract_decisions(value: Any) -> dict[str, Any]:
    decisions: dict[str, Any] = {}
    _collect_decisions(value, decisions, "")
    return decisions


def _collect_decisions(value: Any, decisions: dict[str, Any], prefix: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in {
                "status",
                "reason",
                "cache",
                "can_judge_size",
                "image_numbers",
                "size_reference_image_number",
                "main_image_number",
                "selected_adapter",
                "selected_adapter_name",
                "selected_model_profile",
                "enroute_reference_image_path",
                "reference_image_path",
            }:
                decisions[path] = _jsonable(item)
            if isinstance(item, dict):
                _collect_decisions(item, decisions, path)
    elif isinstance(value, list):
        for index, item in enumerate(value[:10]):
            _collect_decisions(item, decisions, f"{prefix}[{index}]")


def _summarize_large_value(value: Any) -> Any:
    if isinstance(value, str):
        return {"length": len(value), "preview": value[:500]}
    if isinstance(value, dict):
        return {"keys": sorted(str(key) for key in value.keys()), "value": value}
    if isinstance(value, list):
        return {"count": len(value), "items": value[:10]}
    return value


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
    try:
        json.dumps(value)
    except TypeError:
        if hasattr(value, "model_dump"):
            return _jsonable(value.model_dump())
        return str(value)
    return value


def _new_run_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{uuid.uuid4().hex[:8]}"
