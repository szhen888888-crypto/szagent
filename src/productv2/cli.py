"""Command line entrypoint for the product listing workflow."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from urllib import parse, request
from urllib.error import HTTPError, URLError
from pathlib import Path
from typing import Any, Sequence

from productv2.config import Settings
from productv2.db import (
    RAW_IMPORT_STATUS,
    import_raw_data_directory,
    init_database,
    reset_ai_call_locks,
    reset_products_for_processing,
    seed_candidate_products,
)


def add_startup_arguments(
    parser: argparse.ArgumentParser,
    default=argparse.SUPPRESS,
) -> None:
    parser.add_argument(
        "--database-path",
        type=Path,
        default=default,
        help="Path to the SQLite database file.",
    )
    parser.add_argument(
        "--raw-data-dir",
        type=Path,
        default=default,
        help="Directory to scan for raw JSON files before running.",
    )


def add_seed_arguments(
    parser: argparse.ArgumentParser,
    default=argparse.SUPPRESS,
) -> None:
    parser.add_argument(
        "--data-path",
        type=Path,
        default=default,
        help="Path to candidate product JSON data.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=default,
        help="Maximum number of candidate products to process.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all candidate products, ignoring the default limit.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="productv2",
        description="Productv2 database and raw-data utility commands.",
    )
    add_startup_arguments(parser, default=None)

    subparsers = parser.add_subparsers(dest="command")

    init_db_parser = subparsers.add_parser(
        "init-db",
        help="Initialize the SQLite database schema.",
    )
    add_startup_arguments(init_db_parser)
    init_db_parser.add_argument(
        "--seed-candidates",
        action="store_true",
        help="Seed products from the candidate product JSON data.",
    )
    add_seed_arguments(init_db_parser)

    reset_db_parser = subparsers.add_parser(
        "reset-db",
        help="Reset product rows to the initial processable state.",
    )
    add_startup_arguments(reset_db_parser)
    reset_db_parser.add_argument(
        "--status",
        default=RAW_IMPORT_STATUS,
        help="Status to write to every product row after reset.",
    )

    import_raw_parser = subparsers.add_parser(
        "import-raw",
        help="Import JSON files from the configured raw data directory.",
    )
    add_startup_arguments(import_raw_parser)

    start_workflow_parser = subparsers.add_parser(
        "start-workflow",
        help="Start the LangGraph workflow through the local LangGraph API.",
    )
    start_workflow_parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:2024",
        help="LangGraph API base URL.",
    )
    start_workflow_parser.add_argument(
        "--assistant-id",
        default="product_listing",
        help="LangGraph assistant/graph id.",
    )
    start_workflow_parser.add_argument(
        "--thread-id",
        default="",
        help="Existing thread id to reuse. Empty creates a new thread.",
    )
    start_workflow_parser.add_argument(
        "--input-json",
        default="{}",
        help="JSON input payload for the workflow.",
    )

    restart_workflow_parser = subparsers.add_parser(
        "restart-workflow",
        help="Resume an unfinished LangGraph thread first; start a new one if none exists.",
    )
    restart_workflow_parser.add_argument(
        "--api-url",
        default="http://127.0.0.1:2024",
        help="LangGraph API base URL.",
    )
    restart_workflow_parser.add_argument(
        "--assistant-id",
        default="product_listing",
        help="LangGraph assistant/graph id.",
    )
    restart_workflow_parser.add_argument(
        "--input-json",
        default="{}",
        help="JSON input payload used only when a new workflow is started.",
    )
    restart_workflow_parser.add_argument(
        "--resume-json",
        default="",
        help=(
            "JSON value passed to LangGraph Command(resume=...). "
            "Example: '{\"action\":\"approve\"}'."
        ),
    )
    restart_workflow_parser.add_argument(
        "--thread-limit",
        type=int,
        default=20,
        help="Maximum unfinished threads to inspect.",
    )

    control_api_parser = subparsers.add_parser(
        "control-api",
        help="Run the local Productv2 control API for the web console.",
    )
    control_api_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface for the control API.",
    )
    control_api_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port for the control API.",
    )

    control_ui_parser = subparsers.add_parser(
        "control-ui",
        help="Run the local shadcn web console dev server.",
    )
    control_ui_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host interface for the web console.",
    )
    control_ui_parser.add_argument(
        "--port",
        type=int,
        default=5173,
        help="Port for the web console.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = Settings()
    database_path = args.database_path or settings.productv2_database_path
    if args.command == "reset-db":
        _progress(f"重置数据库：{database_path}")
        summary = reset_products_for_processing(
            database_path=database_path,
            status=args.status,
        )
        summary.update(reset_ai_call_locks(database_path=database_path))
        _progress(
            f"重置完成：{summary['products_reset']} 条产品，状态={summary['status']}"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    raw_data_dir = args.raw_data_dir or settings.productv2_raw_data_dir
    if args.command == "init-db":
        _progress(f"扫描原始数据目录：{raw_data_dir}")
        raw_import_summary = import_raw_data_directory(
            database_path=database_path,
            raw_data_dir=raw_data_dir,
        )
        _progress(_raw_import_progress(raw_import_summary))
        _progress(f"初始化数据库：{database_path}")
        initialized_path = init_database(database_path)
        seeded_count = 0

        if args.seed_candidates:
            limit = None if args.all else args.limit
            _progress(
                "导入候选商品数据："
                f"{args.data_path or settings.productv2_data_path}"
            )
            seeded_count = seed_candidate_products(
                database_path=initialized_path,
                data_path=args.data_path or settings.productv2_data_path,
                limit=limit,
            )
        _progress(f"数据库初始化完成：seeded={seeded_count}")

        print(
            json.dumps(
                {
                    "database_path": str(initialized_path),
                    "products_seeded": seeded_count,
                    "raw_import": raw_import_summary,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "import-raw":
        _progress(f"扫描原始数据目录：{raw_data_dir}")
        raw_import_summary = import_raw_data_directory(
            database_path=database_path,
            raw_data_dir=raw_data_dir,
        )
        _progress(_raw_import_progress(raw_import_summary))
        print(json.dumps(raw_import_summary, ensure_ascii=False, indent=2))
        return

    if args.command == "start-workflow":
        result = start_workflow_via_api(
            api_url=args.api_url,
            assistant_id=args.assistant_id,
            thread_id=args.thread_id or None,
            input_payload=json.loads(args.input_json),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "restart-workflow":
        result = restart_workflow_via_api(
            api_url=args.api_url,
            assistant_id=args.assistant_id,
            input_payload=json.loads(args.input_json),
            resume_payload=(
                json.loads(args.resume_json) if args.resume_json else None
            ),
            thread_limit=args.thread_limit,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "control-api":
        import uvicorn

        uvicorn.run(
            "productv2.control_api:app",
            host=args.host,
            port=args.port,
            reload=False,
        )
        return

    if args.command == "control-ui":
        import subprocess

        subprocess.run(
            [
                "npm",
                "run",
                "dev",
                "--",
                "--host",
                args.host,
                "--port",
                str(args.port),
            ],
            cwd=Path(__file__).resolve().parents[2] / "web",
            check=True,
        )
        return

    raise SystemExit(
        "主 workflow 已迁移到 langgraph dev。请使用：uv run langgraph dev --allow-blocking"
    )


def _progress(message: str) -> None:
    print(f"[进度] {message}", file=sys.stderr, flush=True)


def _raw_import_progress(summary: dict[str, Any]) -> str:
    failed_count = len(summary.get("failed_files") or [])
    return (
        "原始数据扫描完成："
        f"文件={summary.get('files_scanned', 0)}，"
        f"导入文件={summary.get('files_imported', 0)}，"
        f"导入产品={summary.get('products_imported', 0)}，"
        f"失败={failed_count}"
    )


def start_workflow_via_api(
    *,
    api_url: str,
    assistant_id: str,
    thread_id: str | None = None,
    input_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a LangGraph thread if needed and start one workflow run."""

    base_url = api_url.rstrip("/")
    active_thread_id = thread_id or _api_post_json(base_url, "/threads", {})["thread_id"]
    try:
        run = _api_post_json(
            base_url,
            f"/threads/{active_thread_id}/runs",
            {
                "assistant_id": assistant_id,
                "input": input_payload or {},
                "multitask_strategy": "reject",
            },
        )
    except SystemExit as exc:
        if _is_thread_running_conflict(exc):
            return _already_running_response(
                base_url=base_url,
                assistant_id=assistant_id,
                thread_id=active_thread_id,
            )
        raise
    run_id = run["run_id"]
    return {
        "mode": "started",
        "api_url": base_url,
        "assistant_id": assistant_id,
        "thread_id": active_thread_id,
        "run_id": run_id,
        "state_url": f"{base_url}/threads/{active_thread_id}/state",
        "studio_url": (
            "https://smith.langchain.com/studio/"
            f"?baseUrl={base_url}&threadId={active_thread_id}"
        ),
        "multitask_strategy": "reject",
    }


def restart_workflow_via_api(
    *,
    api_url: str,
    assistant_id: str,
    thread_id: str | None = None,
    input_payload: dict[str, Any] | None = None,
    resume_payload: Any | None = None,
    thread_limit: int = 20,
) -> dict[str, Any]:
    """Resume an unfinished LangGraph thread first; otherwise start a new run."""

    base_url = api_url.rstrip("/")
    if thread_id:
        return _restart_selected_thread_via_api(
            base_url=base_url,
            assistant_id=assistant_id,
            thread_id=thread_id,
            resume_payload=resume_payload,
        )

    busy_thread = _latest_thread(
        _search_threads(
            base_url,
            status="busy",
            limit=thread_limit,
        ),
        assistant_id=assistant_id,
    )
    if busy_thread is not None:
        thread_id = str(busy_thread["thread_id"])
        return {
            "mode": "already_running",
            "api_url": base_url,
            "assistant_id": assistant_id,
            "thread_id": thread_id,
            "thread_status": busy_thread.get("status"),
            "updated_at": busy_thread.get("updated_at"),
            "state_url": f"{base_url}/threads/{thread_id}/state",
            "studio_url": _studio_url(base_url, thread_id),
            "message": "存在正在运行的 thread，未创建新 workflow。",
        }

    interrupted_threads = _sorted_matching_threads(
        _search_threads(base_url, status="interrupted", limit=thread_limit),
        assistant_id=assistant_id,
    )
    skipped_threads: list[dict[str, Any]] = []
    for interrupted_thread in interrupted_threads:
        thread_id = str(interrupted_thread["thread_id"])
        state = _api_get_json(base_url, f"/threads/{thread_id}/state")
        summary = _summarize_thread_state(state)
        if int(summary.get("interrupt_count") or 0) <= 0:
            skipped_threads.append(
                {
                    "thread_id": thread_id,
                    "thread_status": interrupted_thread.get("status"),
                    "updated_at": interrupted_thread.get("updated_at"),
                    "reason": "interrupted_without_interrupt_payload",
                    "summary": summary,
                }
            )
            continue
        if resume_payload is None:
            return {
                "mode": "resume_required",
                "api_url": base_url,
                "assistant_id": assistant_id,
                "thread_id": thread_id,
                "thread_status": interrupted_thread.get("status"),
                "updated_at": interrupted_thread.get("updated_at"),
                "state_url": f"{base_url}/threads/{thread_id}/state",
                "studio_url": _studio_url(base_url, thread_id),
                "summary": summary,
                "skipped_threads": skipped_threads,
                "message": (
                    "存在等待人工审核的 thread，安全恢复未自动继续。"
                    "请在任务详情中提交 approve / regenerate / reject。"
                ),
            }
        try:
            run = _api_post_json(
                base_url,
                f"/threads/{thread_id}/runs",
                {
                    "assistant_id": assistant_id,
                    "command": {"resume": resume_payload},
                    "multitask_strategy": "reject",
                },
            )
        except SystemExit as exc:
            if _is_thread_running_conflict(exc):
                return _already_running_response(
                    base_url=base_url,
                    assistant_id=assistant_id,
                    thread_id=thread_id,
                    thread_status=interrupted_thread.get("status"),
                    updated_at=interrupted_thread.get("updated_at"),
                    summary=summary,
                )
            raise
        return {
            "mode": "resumed",
            "api_url": base_url,
            "assistant_id": assistant_id,
            "thread_id": thread_id,
            "run_id": run["run_id"],
            "thread_status": interrupted_thread.get("status"),
            "updated_at": interrupted_thread.get("updated_at"),
            "state_url": f"{base_url}/threads/{thread_id}/state",
            "studio_url": _studio_url(base_url, thread_id),
            "summary": summary,
            "skipped_threads": skipped_threads,
            "resume_payload": resume_payload,
            "multitask_strategy": "reject",
        }

    result = start_workflow_via_api(
        api_url=base_url,
        assistant_id=assistant_id,
        input_payload=input_payload or {},
    )
    result["mode"] = "started_after_no_unfinished_thread"
    result["message"] = "未找到未完成 thread，已创建新 workflow。"
    if skipped_threads:
        result["skipped_threads"] = skipped_threads
    return result


def _restart_selected_thread_via_api(
    *,
    base_url: str,
    assistant_id: str,
    thread_id: str,
    resume_payload: Any | None,
) -> dict[str, Any]:
    state = _api_get_json(base_url, f"/threads/{thread_id}/state")
    summary = _summarize_thread_state(state)
    if int(summary.get("interrupt_count") or 0) <= 0:
        try:
            run = _api_post_json(
                base_url,
                f"/threads/{thread_id}/runs",
                {
                    "assistant_id": assistant_id,
                    "input": {},
                    "multitask_strategy": "reject",
                },
            )
        except SystemExit as exc:
            if _is_thread_running_conflict(exc):
                return _already_running_response(
                    base_url=base_url,
                    assistant_id=assistant_id,
                    thread_id=thread_id,
                    summary=summary,
                )
            raise
        return {
            "mode": "selected_thread_restarted",
            "api_url": base_url,
            "assistant_id": assistant_id,
            "thread_id": thread_id,
            "run_id": run["run_id"],
            "state_url": f"{base_url}/threads/{thread_id}/state",
            "studio_url": _studio_url(base_url, thread_id),
            "summary": summary,
            "multitask_strategy": "reject",
            "message": (
                "当前选中的 thread 没有人工审核 payload，"
                f"已按普通节点重试继续执行。原停止原因：{summary.get('stop_reason') or '-'}。"
            ),
        }
    if resume_payload is None:
        return {
            "mode": "resume_required",
            "api_url": base_url,
            "assistant_id": assistant_id,
            "thread_id": thread_id,
            "state_url": f"{base_url}/threads/{thread_id}/state",
            "studio_url": _studio_url(base_url, thread_id),
            "summary": summary,
            "message": (
                "当前选中的 thread 正在等待人工审核。"
                "请在任务详情中提交 approve / regenerate / reject。"
            ),
        }
    try:
        run = _api_post_json(
            base_url,
            f"/threads/{thread_id}/runs",
            {
                "assistant_id": assistant_id,
                "command": {"resume": resume_payload},
                "multitask_strategy": "reject",
            },
        )
    except SystemExit as exc:
        if _is_thread_running_conflict(exc):
            return _already_running_response(
                base_url=base_url,
                assistant_id=assistant_id,
                thread_id=thread_id,
                summary=summary,
            )
        raise
    return {
        "mode": "resumed",
        "api_url": base_url,
        "assistant_id": assistant_id,
        "thread_id": thread_id,
        "run_id": run["run_id"],
        "state_url": f"{base_url}/threads/{thread_id}/state",
        "studio_url": _studio_url(base_url, thread_id),
        "summary": summary,
        "resume_payload": resume_payload,
        "multitask_strategy": "reject",
    }


def list_workflow_threads_via_api(
    *,
    api_url: str,
    assistant_id: str,
    statuses: Sequence[str] = ("busy", "interrupted", "idle", "error"),
    thread_limit: int = 20,
) -> dict[str, Any]:
    """List LangGraph threads with summarized state for the control console."""

    base_url = api_url.rstrip("/")
    threads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for status in statuses:
        try:
            status_threads = _search_threads(
                base_url,
                status=status,
                limit=thread_limit,
            )
        except SystemExit as exc:
            return {
                "api_url": base_url,
                "assistant_id": assistant_id,
                "online": False,
                "error": str(exc),
                "threads": [],
            }
        for thread in _sorted_matching_threads(
            status_threads,
            assistant_id=assistant_id,
        ):
            thread_id = str(thread.get("thread_id") or "")
            if not thread_id or thread_id in seen:
                continue
            seen.add(thread_id)
            summary: dict[str, Any] = {}
            progress: dict[str, Any] = {}
            state_error = ""
            try:
                state = _api_get_json(base_url, f"/threads/{thread_id}/state")
                summary = _summarize_thread_state(state)
                progress = _summarize_thread_progress(
                    state=state,
                    thread=thread,
                    runs=_safe_list_thread_runs(base_url, thread_id),
                )
            except SystemExit as exc:
                state_error = str(exc)
            threads.append(
                {
                    "thread_id": thread_id,
                    "status": thread.get("status"),
                    "created_at": thread.get("created_at"),
                    "updated_at": thread.get("updated_at"),
                    "metadata": thread.get("metadata") or {},
                    "state_url": f"{base_url}/threads/{thread_id}/state",
                    "studio_url": _studio_url(base_url, thread_id),
                    "summary": summary,
                    "progress": progress,
                    "state_error": state_error,
                }
            )
    return {
        "api_url": base_url,
        "assistant_id": assistant_id,
        "online": True,
        "threads": sorted(
            threads,
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        ),
    }


def _search_threads(
    base_url: str,
    *,
    status: str,
    limit: int,
) -> list[dict[str, Any]]:
    payload = {
        "status": status,
        "limit": max(1, limit),
        "select": [
            "thread_id",
            "created_at",
            "updated_at",
            "metadata",
            "status",
        ],
    }
    result = _api_post_json(base_url, "/threads/search", payload)
    if not isinstance(result, list):
        raise SystemExit(f"LangGraph API 返回格式异常：/threads/search => {result!r}")
    return [item for item in result if isinstance(item, dict)]


def _list_thread_runs(base_url: str, thread_id: str) -> list[dict[str, Any]]:
    result = _api_get_json(base_url, f"/threads/{thread_id}/runs")
    if not isinstance(result, list):
        raise SystemExit(
            f"LangGraph API 返回格式异常：/threads/{thread_id}/runs => {result!r}"
        )
    return [item for item in result if isinstance(item, dict)]


def _safe_list_thread_runs(base_url: str, thread_id: str) -> list[dict[str, Any]]:
    try:
        return _list_thread_runs(base_url, thread_id)
    except SystemExit:
        return []


def _latest_thread(
    threads: list[dict[str, Any]],
    *,
    assistant_id: str,
) -> dict[str, Any] | None:
    matching = _sorted_matching_threads(threads, assistant_id=assistant_id)
    if not matching:
        return None
    return matching[0]


def _sorted_matching_threads(
    threads: list[dict[str, Any]],
    *,
    assistant_id: str,
) -> list[dict[str, Any]]:
    matching = [
        thread
        for thread in threads
        if _thread_matches_assistant(thread, assistant_id=assistant_id)
    ]
    return sorted(
        matching,
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )


def _thread_matches_assistant(
    thread: dict[str, Any],
    *,
    assistant_id: str,
) -> bool:
    metadata = thread.get("metadata")
    if not isinstance(metadata, dict):
        return True
    graph_id = metadata.get("graph_id")
    stored_assistant_id = metadata.get("assistant_id")
    return (
        not graph_id
        or graph_id == assistant_id
        or stored_assistant_id == assistant_id
    )


def _summarize_thread_state(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    values = state.get("values")
    if not isinstance(values, dict):
        values = {}
    product = values.get("selected_product")
    if not isinstance(product, dict):
        product = {}
    rawdata = product.get("rawdata")
    if not isinstance(rawdata, dict):
        rawdata = {}
    wearing_image_result = values.get("wearing_image_result")
    if not isinstance(wearing_image_result, dict):
        wearing_image_result = {}
    interrupts = state.get("interrupts")
    if not isinstance(interrupts, list):
        interrupts = []
    next_nodes = _normalize_next_nodes(state.get("next"))
    interrupt_summaries = [_summarize_interrupt(item) for item in interrupts]
    generated_image_path = wearing_image_result.get("generated_image_path")
    if not generated_image_path:
        generated_image_path = _first_generated_image_path(interrupt_summaries)
    stop_reason = _summarize_stop_reason(
        values=values,
        next_nodes=next_nodes,
        interrupt_summaries=interrupt_summaries,
        state=state,
    )
    return {
        "product_id": product.get("product_id"),
        "platform": product.get("platform"),
        "product_status": product.get("status"),
        "product_title": rawdata.get("title"),
        "next": next_nodes,
        "current_node_label": _format_node_labels(next_nodes),
        "generated_image_path": generated_image_path,
        "wearing_image_status": wearing_image_result.get("status"),
        "wearing_image_status_label": _status_label(
            wearing_image_result.get("status")
        ),
        "interrupt_count": len(interrupts),
        "interrupts": interrupt_summaries,
        "can_resume": len(interrupts) > 0,
        "needs_manual_review": stop_reason["code"] == "manual_review_required",
        "stop_reason_code": stop_reason["code"],
        "stop_reason": stop_reason["label"],
        "stop_reason_detail": stop_reason["detail"],
    }


def _summarize_interrupt(interrupt: Any) -> dict[str, Any]:
    if not isinstance(interrupt, dict):
        return {"value": interrupt}
    value = interrupt.get("value")
    if not isinstance(value, dict):
        return {"id": interrupt.get("id"), "value": value}
    return {
        "id": interrupt.get("id"),
        "type": value.get("type"),
        "generated_image_path": value.get("generated_image_path"),
        "attempt": value.get("attempt"),
        "options": value.get("options"),
    }


def _summarize_thread_progress(
    *,
    state: Any,
    thread: dict[str, Any] | None = None,
    runs: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    state_dict = state if isinstance(state, dict) else {}
    thread_dict = thread or {}
    next_nodes = _normalize_next_nodes(state_dict.get("next"))
    tasks = [
        _summarize_task(task)
        for task in state_dict.get("tasks", [])
        if isinstance(task, dict)
    ]
    active_run = _active_run(runs)
    current_node = _current_progress_node(next_nodes, tasks)
    progress_status = _progress_status(
        state=state_dict,
        current_node=current_node,
        active_run=active_run,
        thread=thread_dict,
    )
    started_at = (
        active_run.get("created_at")
        or state_dict.get("created_at")
        or thread_dict.get("updated_at")
        or thread_dict.get("created_at")
    )
    updated_at = (
        active_run.get("updated_at")
        or thread_dict.get("updated_at")
        or state_dict.get("created_at")
    )
    elapsed_seconds = _elapsed_seconds(started_at) if active_run else None
    return {
        "phase": current_node,
        "phase_label": _NODE_LABELS.get(current_node, current_node) if current_node else "",
        "status": progress_status,
        "status_label": _run_status_label(progress_status),
        "message": _progress_message(
            current_node=current_node,
            active_run=active_run,
            tasks=tasks,
            state=state_dict,
        ),
        "active_run": _summarize_run(active_run) if active_run else {},
        "running": bool(active_run and active_run.get("status") == "running"),
        "started_at": started_at,
        "updated_at": updated_at,
        "elapsed_seconds": elapsed_seconds,
        "elapsed_label": _format_duration(elapsed_seconds),
        "tasks": tasks,
    }


def _summarize_task(task: dict[str, Any]) -> dict[str, Any]:
    interrupts = task.get("interrupts")
    if not isinstance(interrupts, list):
        interrupts = []
    return {
        "id": task.get("id"),
        "name": task.get("name"),
        "label": _NODE_LABELS.get(str(task.get("name") or ""), str(task.get("name") or "")),
        "error": task.get("error"),
        "interrupt_count": len(interrupts),
    }


def _active_run(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    for run in runs:
        if run.get("status") == "running":
            return run
    return runs[0] if runs else {}


def _summarize_run(run: dict[str, Any]) -> dict[str, Any]:
    if not run:
        return {}
    return {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "status_label": _run_status_label(run.get("status")),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "multitask_strategy": run.get("multitask_strategy"),
    }


def _current_progress_node(
    next_nodes: Sequence[str],
    tasks: Sequence[dict[str, Any]],
) -> str:
    for task in tasks:
        name = task.get("name")
        if name:
            return str(name)
    return str(next_nodes[0]) if next_nodes else ""


def _progress_status(
    *,
    state: dict[str, Any],
    current_node: str,
    active_run: dict[str, Any],
    thread: dict[str, Any],
) -> str:
    if active_run.get("status") == "running":
        return "running"
    interrupts = state.get("interrupts")
    if isinstance(interrupts, list) and interrupts:
        if current_node == "wait_manual_review":
            return "manual_review"
        return "interrupted"
    return str(active_run.get("status") or thread.get("status") or "")


def _progress_message(
    *,
    current_node: str,
    active_run: dict[str, Any],
    tasks: Sequence[dict[str, Any]],
    state: dict[str, Any],
) -> str:
    task_error = next((str(task.get("error")) for task in tasks if task.get("error")), "")
    if task_error:
        return f"节点执行异常：{task_error}"
    if active_run.get("status") == "running":
        if current_node == "generate_wearing_image":
            return "正在生成穿戴图，可能正在等待第三方图片接口返回。"
        if current_node:
            return f"正在执行：{_NODE_LABELS.get(current_node, current_node)}。"
        return "任务正在运行。"
    interrupts = state.get("interrupts")
    if isinstance(interrupts, list) and interrupts:
        if current_node == "wait_manual_review":
            return "穿戴图已生成，等待人工审核。"
        return f"工作流已暂停：{_NODE_LABELS.get(current_node, current_node)}。"
    if current_node:
        return f"当前停在：{_NODE_LABELS.get(current_node, current_node)}。"
    return "当前没有运行中的节点。"


def _run_status_label(status: Any) -> str:
    labels = {
        "running": "运行中",
        "interrupted": "已暂停",
        "manual_review": "等待人工审核",
        "success": "已完成",
        "error": "异常",
        "pending": "等待中",
    }
    return labels.get(str(status or ""), str(status or ""))


def _elapsed_seconds(started_at: Any) -> int | None:
    started = _parse_iso_datetime(started_at)
    if started is None:
        return None
    return max(0, int((datetime.now(timezone.utc) - started).total_seconds()))


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds}s"
    minutes, second = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {second}s"
    hours, minute = divmod(minutes, 60)
    return f"{hours}h {minute}m"


_NODE_LABELS = {
    "load_candidates": "选择商品",
    "prepare_main_images": "准备主图",
    "detect_size_reference": "尺寸检测",
    "select_enroute_reference": "选择 Enroute 参考图",
    "analyze_enroute_reference": "分析参考图",
    "generate_wearing_image": "生成穿戴图",
    "wait_manual_review": "人工审核",
}

_STATUS_LABELS = {
    "ok": "已生成",
    "failed": "失败",
    "error": "失败",
    "skipped": "已跳过",
    "processing": "处理中",
}


def _normalize_next_nodes(next_value: Any) -> list[str]:
    if isinstance(next_value, list):
        return [str(item) for item in next_value if item]
    if isinstance(next_value, str) and next_value:
        return [next_value]
    return []


def _format_node_labels(next_nodes: Sequence[str]) -> str:
    if not next_nodes:
        return "无待执行节点"
    return "、".join(_NODE_LABELS.get(node, node) for node in next_nodes)


def _status_label(status: Any) -> str:
    if not status:
        return ""
    return _STATUS_LABELS.get(str(status), str(status))


def _first_generated_image_path(interrupts: Sequence[dict[str, Any]]) -> Any:
    for interrupt in interrupts:
        path = interrupt.get("generated_image_path")
        if path:
            return path
    return None


def _summarize_stop_reason(
    *,
    values: dict[str, Any],
    next_nodes: Sequence[str],
    interrupt_summaries: Sequence[dict[str, Any]],
    state: dict[str, Any],
) -> dict[str, str]:
    wearing_image_result = values.get("wearing_image_result")
    if not isinstance(wearing_image_result, dict):
        wearing_image_result = {}
    size_reference_result = values.get("size_reference_result")
    if not isinstance(size_reference_result, dict):
        size_reference_result = {}
    failed_product = values.get("failed_product")
    if not isinstance(failed_product, dict):
        failed_product = {}

    if any(
        interrupt.get("type") == "wearing_image_review"
        for interrupt in interrupt_summaries
    ):
        return {
            "code": "manual_review_required",
            "label": "需要人工审核",
            "detail": "穿戴图已生成，工作流正在等待 approve / regenerate / reject。",
        }

    if interrupt_summaries:
        interrupt_type = str(interrupt_summaries[0].get("type") or "未知暂停")
        return {
            "code": "workflow_interrupted",
            "label": "工作流已暂停",
            "detail": f"暂停类型：{interrupt_type}",
        }

    task_error = _first_task_error(state)
    if task_error:
        return {
            "code": "task_error",
            "label": "节点执行异常",
            "detail": task_error,
        }

    wearing_status = str(wearing_image_result.get("status") or "")
    wearing_reason = str(wearing_image_result.get("reason") or "")
    if wearing_status == "ok" and "wait_manual_review" in next_nodes:
        return {
            "code": "generated_without_review_interrupt",
            "label": "已生成穿戴图，但未进入可审核暂停",
            "detail": "当前 state 没有人工审核 interrupt，不能直接提交审核结果。",
        }
    if wearing_status == "ok":
        return {
            "code": "wearing_image_generated",
            "label": "穿戴图已生成",
            "detail": "当前没有人工审核暂停。",
        }
    if wearing_status in {"failed", "error"}:
        return {
            "code": "wearing_image_failed",
            "label": "穿戴图生成失败",
            "detail": wearing_reason or "图片生成节点返回失败。",
        }
    if wearing_status == "skipped":
        return {
            "code": "wearing_image_skipped",
            "label": "穿戴图生成已跳过",
            "detail": _reason_label(wearing_reason),
        }

    size_status = str(size_reference_result.get("status") or "")
    if size_status in {"failed", "error"}:
        return {
            "code": "size_reference_failed",
            "label": "尺寸检测失败",
            "detail": str(size_reference_result.get("reason") or "尺寸检测节点返回失败。"),
        }

    if next_nodes:
        node = next_nodes[0]
        if node == "detect_size_reference":
            return {
                "code": "waiting_size_reference",
                "label": "停在尺寸检测",
                "detail": "还没有可审核的穿戴图。",
            }
        if node == "generate_wearing_image":
            return {
                "code": "waiting_wearing_generation",
                "label": "停在穿戴图生成",
                "detail": "当前还没有进入人工审核暂停。",
            }
        if node == "wait_manual_review":
            return {
                "code": "waiting_review_without_interrupt",
                "label": "到达人工审核节点，但没有审核暂停",
                "detail": "当前 state 没有 interrupt payload，不能直接提交审核结果。",
            }
        return {
            "code": "waiting_node",
            "label": f"停在{_NODE_LABELS.get(node, node)}",
            "detail": "当前没有人工审核暂停。",
        }

    if failed_product:
        return {
            "code": "product_failed",
            "label": "商品处理失败",
            "detail": _reason_label(str(failed_product.get("reason") or "")),
        }

    return {
        "code": "no_pending_node",
        "label": "没有待执行节点",
        "detail": "当前 state 未显示暂停或待执行节点。",
    }


def _first_task_error(state: dict[str, Any]) -> str:
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        return ""
    for task in tasks:
        if not isinstance(task, dict):
            continue
        error = task.get("error")
        if error:
            return str(error)
    return ""


def _reason_label(reason: str) -> str:
    if reason == "selected_main_or_size_reference_missing":
        return "缺少选定主图或尺寸参考图。"
    if reason == "selected_product_images_missing":
        return "缺少可用于生成的商品图片。"
    return reason or "未提供详细原因。"


def _studio_url(base_url: str, thread_id: str) -> str:
    return (
        "https://smith.langchain.com/studio/"
        f"?baseUrl={parse.quote(base_url, safe='')}&threadId={thread_id}"
    )


def _already_running_response(
    *,
    base_url: str,
    assistant_id: str,
    thread_id: str,
    thread_status: Any | None = None,
    updated_at: Any | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "mode": "already_running",
        "api_url": base_url,
        "assistant_id": assistant_id,
        "thread_id": thread_id,
        "state_url": f"{base_url}/threads/{thread_id}/state",
        "studio_url": _studio_url(base_url, thread_id),
        "message": "当前 thread 已有任务在运行，未重复提交恢复请求。",
    }
    if thread_status is not None:
        result["thread_status"] = thread_status
    if updated_at is not None:
        result["updated_at"] = updated_at
    if summary is not None:
        result["summary"] = summary
    return result


def _is_thread_running_conflict(exc: SystemExit) -> bool:
    message = str(exc)
    return (
        "HTTP 409" in message
        and "Thread is already running a task" in message
    )


def _api_get_json(base_url: str, path: str) -> Any:
    req = request.Request(f"{base_url}{path}", method="GET")
    try:
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"LangGraph API 请求失败：HTTP {exc.code} {detail}") from exc
    except URLError as exc:
        raise SystemExit(f"无法连接 LangGraph API：{base_url}，{exc.reason}") from exc


def _api_post_json(base_url: str, path: str, payload: dict[str, Any]) -> Any:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"LangGraph API 请求失败：HTTP {exc.code} {detail}") from exc
    except URLError as exc:
        raise SystemExit(f"无法连接 LangGraph API：{base_url}，{exc.reason}") from exc
