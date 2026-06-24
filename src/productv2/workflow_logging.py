"""Per-run workflow readable Chinese text logging."""

from __future__ import annotations

import json
import hashlib
import re
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from productv2.config import DEFAULT_WORKFLOW_LOGS_DIR


class WorkflowRunLogger:
    """Append readable events for one workflow run."""

    def __init__(
        self,
        log_dir: str | Path = DEFAULT_WORKFLOW_LOGS_DIR,
        run_id: str | None = None,
    ) -> None:
        self.run_id = run_id or _new_run_id()
        self.path = Path(log_dir) / f"{self.run_id}.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "\n".join(
                [
                    "工作流运行日志",
                    f"运行编号：{self.run_id}",
                    "=" * 80,
                    "",
                ]
            ),
            encoding="utf-8",
        )

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
            file.write(_format_log_event(record))
            file.write("\n")

    def rename_for_product(
        self,
        *,
        product_name: str,
        product_id: str,
        platform: str,
    ) -> Path:
        """Rename the current run log file using the selected product name."""

        name_part = _safe_filename(product_name) or "未命名产品"
        platform_part = _safe_filename(platform) or "unknown-platform"
        product_part = _safe_filename(product_id) or self.run_id
        target = self.path.parent / f"{name_part}__{platform_part}__{product_part}.log"
        if target == self.path:
            return self.path
        target = _unique_path(target)
        previous_path = self.path
        previous_path.rename(target)
        self.path = target
        self.write(
            "log_file_renamed",
            data={
                "product_name": product_name,
                "product_id": product_id,
                "platform": platform,
                "previous_log_path": str(previous_path),
                "current_log_path": str(target),
            },
        )
        return self.path


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
                "input": _summarize_workflow_log_data(state),
                "summary": summarize_state(state),
                "memory_logic": {
                    "available_state_keys": sorted(str(key) for key in state.keys()),
                },
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
                "output": _summarize_workflow_log_data(output),
                "summary": summarize_state(output),
                "decisions": extract_decisions(output),
                "memory_logic": {
                    "state_update_keys": sorted(str(key) for key in output.keys()),
                    "state_update_count": len(output),
                },
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
            if key == "candidates" and isinstance(item, list):
                summary[key] = _summarize_candidates(item)
            elif key in {"rawdata", "prompt", "analysis"}:
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


EVENT_LABELS = {
    "workflow_start": "工作流开始",
    "workflow_end": "工作流结束",
    "workflow_error": "工作流异常",
    "log_file_renamed": "日志文件重命名",
    "node_start": "逻辑单元开始",
    "node_end": "逻辑单元结束",
    "node_error": "逻辑单元异常",
    "branch_decision": "分支判断",
    "llm_request": "LLM 原始输入",
    "llm_response": "LLM 原始输出",
    "llm_parsed_output": "LLM 解析结果",
    "llm_error": "LLM 异常",
    "llm_parse_error": "LLM 解析异常",
    "image_ai_request": "图片 AI 原始输入",
    "image_ai_response": "图片 AI 原始输出",
    "image_ai_error": "图片 AI 异常",
}

NODE_DESCRIPTIONS = {
    "load_candidates": "扫描当前输入状态，从显式 JSON 或 SQLite 中加载候选商品，并选择一个有平台适配器的可处理商品。",
    "merge_main_images": "调用平台适配器获取商品主图，下载可用图片并合并为带编号的临时拼图。",
    "detect_size_reference": "调用视觉 LLM 检查编号拼图，判断是否存在人体参照，并确定尺寸参考图和产品主图编号。",
    "select_enroute_reference": "根据当前商品类目，从本地 Enroute 参考图库中选择同类目的 02.jpg 佩戴参考图。",
    "analyze_enroute_reference": "调用 LLM 逆向分析 Enroute 佩戴参考图，提炼模特、衣物、场景和拍摄风格，并读取或写入缓存。",
    "generate_wearing_image": "准备佩戴图生成所需的标记主图、尺寸参考图、固定模特图和图片生成 prompt；当前不实际调用生图接口。",
    "build_listing_drafts": "基于当前候选商品生成旧版上架草稿数据，当前不是主图片流程的完成标准。",
    "prepare_review_queue": "汇总运行指标、节点结果和待复核草稿，并输出最终工作流结果。",
}

FIELD_LABELS = {
    "input": "输入数据",
    "output": "输出数据",
    "summary": "状态记忆摘要",
    "decisions": "判断结果",
    "branch": "分支逻辑",
    "memory_logic": "状态记忆逻辑",
    "metrics": "运行指标",
    "endpoint": "接口地址",
    "attempt": "调用次数",
    "request_context": "调用上下文",
    "raw_payload": "原始请求数据",
    "raw_messages": "原始消息数据",
    "raw_response_text": "原始响应文本",
    "raw_response_json": "原始响应 JSON",
    "parsed_output": "解析后输出",
    "image_path": "图片路径",
    "prompt": "提示词",
    "product_name": "产品名称",
    "previous_log_path": "原日志路径",
    "current_log_path": "当前日志路径",
    "candidate_count": "候选数量",
    "candidate_summaries": "候选摘要",
    "rawdata_keys": "原始数据字段",
    "error_type": "异常类型",
    "error": "异常信息",
    "traceback": "异常堆栈",
}


def prepare_ai_log_data(value: Any) -> Any:
    """Keep AI inputs/outputs readable while preserving raw prompts and responses."""

    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): prepare_ai_log_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [prepare_ai_log_data(item) for item in value]
    if isinstance(value, tuple):
        return [prepare_ai_log_data(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image/") and ";base64," in value:
        prefix, encoded = value.split(";base64,", 1)
        return {
            "raw_type": "data_url_image",
            "mime_type": prefix.removeprefix("data:"),
            "base64_length": len(encoded),
            "sha256": hashlib.sha256(encoded.encode("ascii", errors="ignore")).hexdigest(),
            "preview": f"{prefix};base64,{encoded[:80]}...",
        }
    return _jsonable(value)


def describe_file_for_log(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    info: dict[str, Any] = {
        "path": str(file_path),
        "exists": file_path.exists(),
    }
    if not file_path.exists() or not file_path.is_file():
        return info
    data = file_path.read_bytes()
    info.update(
        {
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "suffix": file_path.suffix,
        }
    )
    return info


def _format_log_event(record: dict[str, Any]) -> str:
    event_name = str(record["event"])
    event_label = EVENT_LABELS.get(event_name, event_name)
    lines = [
        "-" * 80,
        f"时间：{record['ts']}",
        f"事件：{event_label}",
        f"事件代码：{event_name}",
        f"运行编号：{record['run_id']}",
    ]
    if record.get("node"):
        lines.append(f"逻辑单元：{record['node']}")
        description = NODE_DESCRIPTIONS.get(str(record["node"]))
        if description:
            lines.append(f"逻辑单元说明：{description}")
    data = record.get("data") or {}
    if data:
        lines.extend(["", "数据："])
        lines.extend(_format_log_value(data, level=1))
    return "\n".join(lines) + "\n"


def _format_log_value(value: Any, level: int) -> list[str]:
    if isinstance(value, dict):
        return _format_log_dict(value, level)
    if isinstance(value, list):
        return _format_log_list(value, level)
    return [f"{_indent(level)}- {_format_scalar(value)}"]


def _format_log_dict(value: dict[str, Any], level: int) -> list[str]:
    lines: list[str] = []
    for key, item in value.items():
        key_text = _field_label(str(key))
        if isinstance(item, dict):
            lines.append(f"{_indent(level)}- {key_text}:")
            lines.extend(_format_log_dict(item, level + 1))
        elif isinstance(item, list):
            lines.append(f"{_indent(level)}- {key_text}:")
            lines.extend(_format_log_list(item, level + 1))
        else:
            lines.append(f"{_indent(level)}- {key_text}: {_format_scalar(item)}")
    return lines


def _format_log_list(value: list[Any], level: int) -> list[str]:
    if not value:
        return [f"{_indent(level)}- 空列表"]

    lines: list[str] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, dict):
            lines.append(f"{_indent(level)}- 第{index}项:")
            lines.extend(_format_log_dict(item, level + 1))
        elif isinstance(item, list):
            lines.append(f"{_indent(level)}- 第{index}项:")
            lines.extend(_format_log_list(item, level + 1))
        else:
            lines.append(f"{_indent(level)}- {_format_scalar(item)}")
    return lines


def _format_scalar(value: Any) -> str:
    if value is None:
        return "空"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "":
        return '""'
    if "\n" in text:
        return "\n" + _indented_block(text)
    return text


def _field_label(key: str) -> str:
    if key in FIELD_LABELS:
        return f"{FIELD_LABELS[key]} ({key})"
    return key


def _indented_block(text: str) -> str:
    return "\n".join(f"    {line}" for line in text.splitlines())


def _indent(level: int) -> str:
    return "  " * level


def _summarize_workflow_log_data(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key == "candidates" and isinstance(item, list):
                result[key] = _summarize_candidates(item)
            elif isinstance(item, dict):
                result[key] = _summarize_workflow_log_data(item)
            elif isinstance(item, list):
                result[key] = [_summarize_workflow_log_data(child) for child in item]
            else:
                result[key] = item
        return result
    if isinstance(value, list):
        return [_summarize_workflow_log_data(item) for item in value]
    return value


def _summarize_candidates(candidates: list[Any]) -> dict[str, Any]:
    return {
        "candidate_count": len(candidates),
        "candidate_summaries": [
            _candidate_summary(candidate)
            for candidate in candidates[:10]
        ],
        **({"truncated": True} if len(candidates) > 10 else {}),
    }


def _candidate_summary(candidate: Any) -> dict[str, Any]:
    if hasattr(candidate, "model_dump"):
        candidate = candidate.model_dump()
    if not isinstance(candidate, dict):
        return {"value": str(candidate)}

    rawdata = candidate.get("rawdata")
    rawdata_dict = rawdata if isinstance(rawdata, dict) else {}
    title = str(rawdata_dict.get("title") or candidate.get("title") or "").strip()
    return {
        "id": candidate.get("id"),
        "product_id": candidate.get("product_id"),
        "platform": candidate.get("platform"),
        "title": title,
        "status": candidate.get("status"),
        "locked_at": candidate.get("locked_at"),
        "locked_by": candidate.get("locked_by"),
        "rawdata_keys": sorted(str(key) for key in rawdata_dict.keys()),
    }


def _safe_filename(value: str, max_length: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = re.sub(r'[\\/:*?"<>|]+', "-", text)
    text = text.strip(" .")
    if len(text) > max_length:
        text = text[:max_length].rstrip(" .")
    return text


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem}__{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}__{uuid.uuid4().hex[:8]}{suffix}")
