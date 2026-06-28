"""Local control API for the Productv2 LangGraph console."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from productv2.cli import (
    _api_get_json,
    _list_thread_runs,
    _summarize_thread_progress,
    list_workflow_threads_via_api,
    restart_workflow_via_api,
    start_workflow_via_api,
)
from productv2.config import PROJECT_ROOT
from productv2.config import Settings
from productv2.db import RAW_IMPORT_STATUS
from productv2.db import clear_enroute_image_analyses
from productv2.db import get_product_by_identity
from productv2.db import list_enroute_image_analyses
from productv2.db import update_product_fields
from productv2.feishu_long_connection import FeishuLongConnectionServer
from productv2.feishu_long_connection import list_feishu_event_log
from productv2.manual_review import manual_review_payload_from_state
from productv2.model_profiles import VIRTUAL_MODEL_PROFILES
from productv2.model_profiles import virtual_model_profile_summary
from productv2.prompts_service import (
    PromptAccessError,
    create_prompt_version,
    list_prompts,
    set_prompt_override,
    write_prompt,
)
from productv2.review_channels import notify_feishu_review


DEFAULT_LANGGRAPH_API_URL = "http://127.0.0.1:2024"
DEFAULT_ASSISTANT_ID = "product_listing"
DEFAULT_LANGGRAPH_HOST = "127.0.0.1"
DEFAULT_LANGGRAPH_PORT = 2024


logger = logging.getLogger(__name__)
_review_notification_lock = threading.Lock()
_review_watcher_stop = threading.Event()
_review_watcher_thread: threading.Thread | None = None
_feishu_long_connection_server: FeishuLongConnectionServer | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _start_review_watcher()
    _start_feishu_long_connection()
    try:
        yield
    finally:
        _stop_review_watcher()


app = FastAPI(title="Productv2 Control API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StartServerRequest(BaseModel):
    host: str = DEFAULT_LANGGRAPH_HOST
    port: int = DEFAULT_LANGGRAPH_PORT
    allow_blocking: bool = True
    no_browser: bool = True


class WorkflowStartRequest(BaseModel):
    api_url: str = DEFAULT_LANGGRAPH_API_URL
    assistant_id: str = DEFAULT_ASSISTANT_ID
    thread_id: str = ""
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowRestartRequest(BaseModel):
    api_url: str = DEFAULT_LANGGRAPH_API_URL
    assistant_id: str = DEFAULT_ASSISTANT_ID
    thread_id: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    resume: Any | None = None
    thread_limit: int = 20


class ClearFlowsRequest(BaseModel):
    api_url: str = DEFAULT_LANGGRAPH_API_URL
    assistant_id: str = DEFAULT_ASSISTANT_ID
    thread_limit: int = Field(default=100, ge=1, le=100)
    reset_status: str = RAW_IMPORT_STATUS


class ResumeThreadRequest(BaseModel):
    api_url: str = DEFAULT_LANGGRAPH_API_URL
    assistant_id: str = DEFAULT_ASSISTANT_ID
    resume: Any = Field(default_factory=dict)


class PromptSaveRequest(BaseModel):
    dir: str
    version: int
    content: str


class PromptVersionRequest(BaseModel):
    dir: str
    content: str


class PromptOverrideRequest(BaseModel):
    dir: str
    version: int | None = None


_managed_process: subprocess.Popen[str] | None = None
_managed_started_at: float | None = None


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.get("/api/feishu/events")
def feishu_events(limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    events = list_feishu_event_log(limit)
    return {
        "total": len(events),
        "events": events,
    }


@app.get("/api/server/status")
def server_status(
    api_url: str = Query(DEFAULT_LANGGRAPH_API_URL),
) -> dict[str, Any]:
    process = _current_managed_process()
    online = _langgraph_online(api_url)
    return {
        "api_url": api_url.rstrip("/"),
        "online": online,
        "managed": process is not None,
        "pid": process.pid if process is not None else None,
        "started_at": _managed_started_at,
        "uptime_seconds": (
            round(time.monotonic() - _managed_started_at, 1)
            if process is not None and _managed_started_at is not None
            else None
        ),
    }


@app.post("/api/server/start")
def start_server(payload: StartServerRequest) -> dict[str, Any]:
    global _managed_process, _managed_started_at

    api_url = f"http://{payload.host}:{payload.port}"
    process = _current_managed_process()
    if process is not None:
        return {**server_status(api_url), "message": "LangGraph dev 已由控制台启动。"}
    if _langgraph_online(api_url):
        return {
            **server_status(api_url),
            "message": "LangGraph API 已在线，但不是由当前控制台进程托管。",
        }

    command = [
        "uv",
        "run",
        "langgraph",
        "dev",
        "--host",
        payload.host,
        "--port",
        str(payload.port),
    ]
    if payload.allow_blocking:
        command.append("--allow-blocking")
    if payload.no_browser:
        command.append("--no-browser")

    log_dir = PROJECT_ROOT / ".control"
    log_dir.mkdir(exist_ok=True)
    log_file = (log_dir / "langgraph-dev.log").open("a", encoding="utf-8")
    _managed_process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    _managed_started_at = time.monotonic()
    return {
        **server_status(api_url),
        "command": command,
        "log_path": str(log_dir / "langgraph-dev.log"),
        "message": "LangGraph dev 启动中。",
    }


@app.post("/api/server/stop")
def stop_server() -> dict[str, Any]:
    global _managed_process, _managed_started_at

    process = _current_managed_process()
    if process is None:
        return {"stopped": False, "message": "没有由控制台托管的 LangGraph 进程。"}

    _terminate_process_group(process)
    _managed_process = None
    _managed_started_at = None
    return {"stopped": True, "message": "LangGraph dev 已停止。"}


@app.post("/api/server/restart")
def restart_server(payload: StartServerRequest) -> dict[str, Any]:
    stop_server()
    return start_server(payload)


@app.get("/api/threads")
def list_threads(
    api_url: str = Query(DEFAULT_LANGGRAPH_API_URL),
    assistant_id: str = Query(DEFAULT_ASSISTANT_ID),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    result = list_workflow_threads_via_api(
        api_url=api_url,
        assistant_id=assistant_id,
        thread_limit=limit,
    )
    _hydrate_threads_from_database(result)
    _notify_manual_review_threads(result, api_url=api_url, assistant_id=assistant_id)
    return result


@app.get("/api/threads/{thread_id}/state")
def thread_state(
    thread_id: str,
    api_url: str = Query(DEFAULT_LANGGRAPH_API_URL),
) -> dict[str, Any]:
    try:
        base_url = api_url.rstrip("/")
        state = _api_get_json(base_url, f"/threads/{thread_id}/state")
        runs = _list_thread_runs(base_url, thread_id)
        result = {
            "thread_id": thread_id,
            "api_url": base_url,
            "state": state,
            "runs": runs,
            "progress": _summarize_thread_progress(
                state=state,
                thread={"thread_id": thread_id},
                runs=runs,
            ),
        }
        database_product = _database_product_from_state(state)
        if database_product:
            result["database_product"] = database_product
        return result
    except SystemExit as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/files/image")
def image_file(path: str = Query(..., min_length=1)) -> FileResponse:
    resolved_path = _resolve_project_file(path)
    if not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="image file not found")
    return FileResponse(
        resolved_path,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/model-profiles")
def model_profiles() -> dict[str, Any]:
    settings = Settings()
    root = Path(settings.productv2_model_profiles_dir)
    profiles: list[dict[str, Any]] = []
    for profile in VIRTUAL_MODEL_PROFILES:
        image_path = root / profile.key / "model.jpg"
        metadata_path = root / profile.key / "metadata.json"
        image_stat = image_path.stat() if image_path.exists() else None
        profiles.append(
            {
                "profile_key": profile.key,
                "name": profile.name,
                "ethnicity": profile.ethnicity,
                "age_feel": profile.age_feel,
                "face": profile.face,
                "skin": profile.skin,
                "hair": profile.hair,
                "temperament": profile.temperament,
                "wardrobe": profile.wardrobe,
                "poses": profile.poses,
                "expression": profile.expression,
                "best_for": list(profile.best_for),
                "prompt": profile.prompt,
                "negative_prompt": profile.negative_prompt,
                "summary": virtual_model_profile_summary(profile),
                "image_path": str(image_path) if image_path.exists() else "",
                "metadata_path": str(metadata_path) if metadata_path.exists() else "",
                "image_exists": image_path.exists(),
                "image_mtime_ns": image_stat.st_mtime_ns if image_stat else 0,
            }
        )
    return {"profiles": profiles}


@app.get("/api/enroute-learning")
def enroute_learning() -> dict[str, Any]:
    settings = Settings()
    rows = list_enroute_image_analyses(settings.productv2_database_path)
    categories: dict[str, int] = {}
    items: list[dict[str, Any]] = []
    for row in rows:
        category = str(row.get("enroute_category") or "未分类")
        categories[category] = categories.get(category, 0) + 1
        analysis = row.get("analysis_json") if isinstance(row.get("analysis_json"), dict) else {}
        selected_model = (
            analysis.get("selected_model_profile", {})
            if isinstance(analysis, dict)
            else {}
        )
        items.append(
            {
                **row,
                "analysis": analysis,
                "selected_model_profile": (
                    selected_model if isinstance(selected_model, dict) else {}
                ),
            }
        )
    return {
        "total": len(items),
        "categories": [
            {"category": category, "count": count}
            for category, count in sorted(categories.items())
        ],
        "items": items,
    }


@app.delete("/api/enroute-learning")
def clear_enroute_learning() -> dict[str, Any]:
    settings = Settings()
    result = clear_enroute_image_analyses(settings.productv2_database_path)
    return {
        **result,
        "message": f"已清理 {result['deleted_count']} 条 Enroute 逆向分析缓存。",
    }


@app.get("/api/prompts")
def get_prompts() -> dict[str, Any]:
    return {"prompts": list_prompts()}


@app.put("/api/prompts/content")
def save_prompt_content(payload: PromptSaveRequest) -> dict[str, Any]:
    try:
        return write_prompt(payload.dir, payload.version, payload.content)
    except PromptAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/prompts/version")
def add_prompt_version(payload: PromptVersionRequest) -> dict[str, Any]:
    try:
        return create_prompt_version(payload.dir, payload.content)
    except PromptAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/prompts/override")
def update_prompt_override(payload: PromptOverrideRequest) -> dict[str, Any]:
    try:
        return set_prompt_override(payload.dir, payload.version)
    except PromptAccessError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/workflows/start")
def start_workflow(payload: WorkflowStartRequest) -> dict[str, Any]:
    try:
        return start_workflow_via_api(
            api_url=payload.api_url,
            assistant_id=payload.assistant_id,
            thread_id=payload.thread_id or None,
            input_payload=payload.input,
        )
    except SystemExit as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/workflows/restart")
def restart_workflow(payload: WorkflowRestartRequest) -> dict[str, Any]:
    try:
        return restart_workflow_via_api(
            api_url=payload.api_url,
            assistant_id=payload.assistant_id,
            thread_id=payload.thread_id or None,
            input_payload=payload.input,
            resume_payload=payload.resume,
            thread_limit=payload.thread_limit,
        )
    except SystemExit as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/workflows/clear-flows")
def clear_workflow_flows(payload: ClearFlowsRequest) -> dict[str, Any]:
    try:
        return _clear_workflow_flows(
            api_url=payload.api_url,
            assistant_id=payload.assistant_id,
            thread_limit=payload.thread_limit,
            reset_status=payload.reset_status,
        )
    except SystemExit as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/threads/{thread_id}/resume")
def resume_thread(thread_id: str, payload: ResumeThreadRequest) -> dict[str, Any]:
    if payload.resume is None:
        raise HTTPException(status_code=400, detail="resume payload is required")
    try:
        return _resume_thread(
            api_url=payload.api_url,
            assistant_id=payload.assistant_id,
            thread_id=thread_id,
            resume_payload=payload.resume,
        )
    except SystemExit as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/review/feishu/callback")
def feishu_review_callback(payload: dict[str, Any]) -> dict[str, Any]:
    _verify_feishu_callback(payload)
    if payload.get("type") == "url_verification" and payload.get("challenge"):
        return {"challenge": payload["challenge"]}
    action = _extract_feishu_review_action(payload)
    if action is None:
        return {"status": "ignored", "reason": "not_review_action"}
    try:
        return _resume_thread(
            api_url=action["api_url"],
            assistant_id=action["assistant_id"],
            thread_id=action["thread_id"],
            resume_payload={"action": action["action"]},
        )
    except SystemExit as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _resume_thread(
    *,
    api_url: str,
    assistant_id: str,
    thread_id: str,
    resume_payload: Any,
) -> dict[str, Any]:
    from productv2.cli import _api_post_json, _studio_url

    base_url = api_url.rstrip("/")
    run = _api_post_json(
        base_url,
        f"/threads/{thread_id}/runs",
        {
            "assistant_id": assistant_id,
            "command": {"resume": resume_payload},
            "multitask_strategy": "reject",
        },
    )
    return {
        "mode": "resumed",
        "api_url": base_url,
        "assistant_id": assistant_id,
        "thread_id": thread_id,
        "run_id": run["run_id"],
        "state_url": f"{base_url}/threads/{thread_id}/state",
        "studio_url": _studio_url(base_url, thread_id),
        "resume_payload": resume_payload,
        "multitask_strategy": "reject",
    }


def _clear_workflow_flows(
    *,
    api_url: str,
    assistant_id: str,
    thread_limit: int,
    reset_status: str = RAW_IMPORT_STATUS,
) -> dict[str, Any]:
    base_url = api_url.rstrip("/")
    result = list_workflow_threads_via_api(
        api_url=base_url,
        assistant_id=assistant_id,
        thread_limit=thread_limit,
    )
    if result.get("online") is False:
        return {
            "mode": "clear_flows",
            "api_url": base_url,
            "assistant_id": assistant_id,
            "online": False,
            "error": result.get("error", ""),
            "deleted_threads": 0,
            "products_reset": 0,
            "skipped_products": 0,
            "items": [],
            "message": "LangGraph API 不在线，未清理 flow。",
        }

    settings = Settings()
    items: list[dict[str, Any]] = []
    seen_products: set[tuple[str, str]] = set()
    threads = [
        thread for thread in result.get("threads", []) if isinstance(thread, dict)
    ]
    for thread in threads:
        thread_id = str(thread.get("thread_id") or "")
        if not thread_id:
            continue
        item: dict[str, Any] = {"thread_id": thread_id}
        state: Any = {}
        try:
            state = _api_get_json(base_url, f"/threads/{thread_id}/state")
            item["state_loaded"] = True
        except SystemExit as exc:
            item["state_loaded"] = False
            item["state_error"] = str(exc)

        identity = _product_identity_from_thread_state_or_summary(state, thread)
        if identity:
            product_id, platform = identity
            item["product_id"] = product_id
            item["platform"] = platform

        try:
            _api_delete_json(base_url, f"/threads/{thread_id}")
            item["deleted"] = True
        except SystemExit as exc:
            item["deleted"] = False
            item["delete_error"] = str(exc)
            items.append(item)
            continue

        if not identity:
            item["database_reset"] = False
            item["database_skip_reason"] = "missing_product_identity"
            items.append(item)
            continue

        if identity in seen_products:
            item["database_reset"] = False
            item["database_skip_reason"] = "duplicate_product_identity"
            items.append(item)
            continue

        seen_products.add(identity)
        try:
            product = update_product_fields(
                settings.productv2_database_path,
                identity[0],
                identity[1],
                status=reset_status,
                locked_at=None,
                locked_by=None,
            )
            item["database_reset"] = True
            item["database_product"] = {
                "product_id": product.product_id,
                "platform": product.platform,
                "status": product.status,
                "locked_at": product.locked_at,
                "locked_by": product.locked_by,
            }
        except Exception as exc:
            item["database_reset"] = False
            item["database_error"] = f"{type(exc).__name__}: {exc}"
        items.append(item)

    deleted_count = sum(1 for item in items if item.get("deleted") is True)
    products_reset = sum(1 for item in items if item.get("database_reset") is True)
    skipped_products = sum(
        1
        for item in items
        if item.get("deleted") is True and item.get("database_reset") is not True
    )
    return {
        "mode": "clear_flows",
        "api_url": base_url,
        "assistant_id": assistant_id,
        "online": True,
        "thread_count": len(threads),
        "deleted_threads": deleted_count,
        "products_reset": products_reset,
        "skipped_products": skipped_products,
        "items": items,
        "message": (
            f"已清理 {deleted_count} 个 flow，并恢复 {products_reset} 个商品为"
            f" {reset_status}。"
        ),
    }


def _api_delete_json(base_url: str, path: str) -> Any:
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.delete(f"{base_url}{path}")
            response.raise_for_status()
            if response.content:
                return response.json()
            return {}
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        raise SystemExit(
            f"LangGraph API 请求失败：HTTP {exc.response.status_code} {detail}"
        ) from exc
    except httpx.HTTPError as exc:
        raise SystemExit(f"无法连接 LangGraph API：{base_url}，{exc}") from exc


def _product_identity_from_thread_state_or_summary(
    state: Any,
    thread: dict[str, Any],
) -> tuple[str, str] | None:
    for product in _candidate_products_from_state(state):
        identity = _product_identity_from_mapping(product)
        if identity:
            return identity
    summary = thread.get("summary")
    if isinstance(summary, dict):
        identity = _product_identity_from_mapping(summary)
        if identity:
            return identity
    return None


def _candidate_products_from_state(state: Any) -> list[dict[str, Any]]:
    if not isinstance(state, dict):
        return []
    values = state.get("values")
    if not isinstance(values, dict):
        return []
    candidates: list[dict[str, Any]] = []
    selected = values.get("selected_product")
    if isinstance(selected, dict):
        candidates.append(selected)
    failed = values.get("failed_product")
    if isinstance(failed, dict):
        product = failed.get("product")
        if isinstance(product, dict):
            candidates.append(product)
        candidates.append(failed)
    return candidates


def _product_identity_from_mapping(value: dict[str, Any]) -> tuple[str, str] | None:
    product_id = str(value.get("product_id") or "").strip()
    platform = str(value.get("platform") or "").strip()
    if product_id and platform:
        return product_id, platform
    return None


def _start_feishu_long_connection(settings: Settings | None = None) -> dict[str, Any]:
    global _feishu_long_connection_server
    if _feishu_long_connection_server is not None:
        return _feishu_long_connection_server.start()
    active_settings = settings or Settings()
    _feishu_long_connection_server = FeishuLongConnectionServer(
        active_settings,
        action_handler=_resume_feishu_review_action,
    )
    result = _feishu_long_connection_server.start()
    if result.get("status") == "started":
        logger.info("Feishu long connection started")
    elif result.get("status") == "skipped":
        logger.info("Feishu long connection skipped: %s", result.get("reason"))
    return result


def _resume_feishu_review_action(action: dict[str, str]) -> dict[str, Any]:
    return _resume_thread(
        api_url=action["api_url"],
        assistant_id=action["assistant_id"],
        thread_id=action["thread_id"],
        resume_payload={"action": action["action"]},
    )


def _start_review_watcher(settings: Settings | None = None) -> None:
    global _review_watcher_thread
    active_settings = settings or Settings()
    if not active_settings.review_watcher_enabled:
        logger.info("manual review watcher disabled")
        return
    if _review_watcher_thread is not None and _review_watcher_thread.is_alive():
        return
    _review_watcher_stop.clear()
    _review_watcher_thread = threading.Thread(
        target=_review_watcher_loop,
        args=(active_settings,),
        name="productv2-review-watcher",
        daemon=True,
    )
    _review_watcher_thread.start()


def _stop_review_watcher() -> None:
    global _review_watcher_thread
    _review_watcher_stop.set()
    thread = _review_watcher_thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)
    _review_watcher_thread = None


def _review_watcher_loop(settings: Settings) -> None:
    while not _review_watcher_stop.is_set():
        try:
            result = _scan_manual_review_notifications(settings=settings)
            if int(result.get("notified_threads") or 0) > 0:
                logger.info("manual review watcher notified: %s", result)
        except Exception:  # pragma: no cover - watcher must never kill the API
            logger.exception("manual review watcher scan failed")
        interval = max(float(settings.review_watcher_interval or 0), 1.0)
        _review_watcher_stop.wait(interval)


def _scan_manual_review_notifications(
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or Settings()
    if not active_settings.review_watcher_enabled:
        return {
            "enabled": False,
            "notified_threads": 0,
            "message": "manual review watcher disabled",
        }
    result = list_workflow_threads_via_api(
        api_url=active_settings.review_watcher_api_url,
        assistant_id=active_settings.review_watcher_assistant_id,
        thread_limit=active_settings.review_watcher_thread_limit,
    )
    if result.get("online") is False:
        return {
            "enabled": True,
            "online": False,
            "api_url": result.get("api_url"),
            "assistant_id": active_settings.review_watcher_assistant_id,
            "notified_threads": 0,
            "error": result.get("error", ""),
        }

    _notify_manual_review_threads(
        result,
        api_url=active_settings.review_watcher_api_url,
        assistant_id=active_settings.review_watcher_assistant_id,
    )
    processed_threads = [
        thread
        for thread in result.get("threads", [])
        if isinstance(thread, dict)
        and isinstance(thread.get("review_notification"), dict)
    ]
    sent_threads = [
        thread
        for thread in processed_threads
        if isinstance(thread.get("review_notification"), dict)
        and thread["review_notification"].get("status") == "sent"
    ]
    return {
        "enabled": True,
        "online": True,
        "api_url": active_settings.review_watcher_api_url.rstrip("/"),
        "assistant_id": active_settings.review_watcher_assistant_id,
        "notified_threads": len(sent_threads),
        "processed_threads": len(processed_threads),
        "threads": [
            {
                "thread_id": thread.get("thread_id"),
                "review_notification": thread.get("review_notification"),
            }
            for thread in processed_threads
        ],
    }


def _notify_manual_review_threads(
    result: dict[str, Any],
    *,
    api_url: str,
    assistant_id: str,
) -> None:
    with _review_notification_lock:
        _notify_manual_review_threads_unlocked(
            result,
            api_url=api_url,
            assistant_id=assistant_id,
        )


def _notify_manual_review_threads_unlocked(
    result: dict[str, Any],
    *,
    api_url: str,
    assistant_id: str,
) -> None:
    threads = result.get("threads")
    if not isinstance(threads, list):
        return
    for thread in threads:
        thread_dict = thread if isinstance(thread, dict) else {}
        summary = thread_dict.get("summary")
        if not isinstance(summary, dict) or not summary.get("needs_manual_review"):
            continue
        thread_id = str(thread_dict.get("thread_id") or "")
        if not thread_id:
            continue
        try:
            state = _api_get_json(api_url.rstrip("/"), f"/threads/{thread_id}/state")
            payload = manual_review_payload_from_state(state)
            if not payload:
                continue
            thread_dict["review_notification"] = notify_feishu_review(
                payload,
                settings=Settings(),
                review_context={
                    "api_url": api_url,
                    "assistant_id": assistant_id,
                    "thread_id": thread_id,
                },
            )
        except Exception as exc:  # pragma: no cover - keep thread listing robust
            thread_dict["review_notification"] = {
                "status": "failed",
                "reason": "review_notification_error",
                "error": f"{type(exc).__name__}: {exc}",
            }


def _hydrate_threads_from_database(result: dict[str, Any]) -> None:
    threads = result.get("threads")
    if not isinstance(threads, list):
        return
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        summary = thread.get("summary")
        if not isinstance(summary, dict):
            continue
        product_id = str(summary.get("product_id") or "")
        platform = str(summary.get("platform") or "")
        if not product_id or not platform:
            continue
        database_product = _database_product_by_identity(product_id, platform)
        if not database_product:
            continue
        thread["database_product"] = database_product
        summary["database_product_status"] = database_product.get("status")
        summary["database_wearing_image"] = database_product.get("wearing_image")
        summary["database_locked_at"] = database_product.get("locked_at")
        summary["database_locked_by"] = database_product.get("locked_by")
        summary["product_status"] = database_product.get("status")
        if database_product.get("wearing_image"):
            summary["persisted_wearing_image"] = database_product["wearing_image"]


def _database_product_from_state(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    values = state.get("values")
    if not isinstance(values, dict):
        return {}
    product = values.get("selected_product")
    if not isinstance(product, dict):
        return {}
    return _database_product_by_identity(
        str(product.get("product_id") or ""),
        str(product.get("platform") or ""),
    )


def _database_product_by_identity(product_id: str, platform: str) -> dict[str, Any]:
    if not product_id or not platform:
        return {}
    product = get_product_by_identity(
        Settings().productv2_database_path,
        product_id,
        platform,
    )
    if product is None:
        return {}
    return product.model_dump()


def _extract_feishu_review_action(payload: dict[str, Any]) -> dict[str, str] | None:
    value: Any = None
    for source in (payload, payload.get("event")):
        if not isinstance(source, dict):
            continue
        action_payload = source.get("action")
        if isinstance(action_payload, dict) and isinstance(
            action_payload.get("value"), dict
        ):
            value = action_payload["value"]
            break
        if isinstance(source.get("value"), dict):
            value = source["value"]
            break
    if not isinstance(value, dict):
        return None
    action = str(value.get("action") or "").lower()
    if action not in {"approve", "regenerate", "reject"}:
        return None
    thread_id = str(value.get("thread_id") or "")
    api_url = str(value.get("api_url") or DEFAULT_LANGGRAPH_API_URL)
    assistant_id = str(value.get("assistant_id") or DEFAULT_ASSISTANT_ID)
    if not thread_id:
        return None
    return {
        "action": action,
        "thread_id": thread_id,
        "api_url": api_url,
        "assistant_id": assistant_id,
    }


def _verify_feishu_callback(payload: dict[str, Any]) -> None:
    settings = Settings()
    expected = (
        settings.feishu_verification_token.get_secret_value()
        if settings.feishu_verification_token
        else ""
    )
    if not expected:
        return
    token = str(payload.get("token") or "")
    if token != expected:
        raise HTTPException(status_code=403, detail="invalid feishu callback token")


def _current_managed_process() -> subprocess.Popen[str] | None:
    global _managed_process, _managed_started_at
    if _managed_process is None:
        return None
    if _managed_process.poll() is None:
        return _managed_process
    _managed_process = None
    _managed_started_at = None
    return None


def _langgraph_online(api_url: str) -> bool:
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(f"{api_url.rstrip('/')}/ok")
            return response.status_code < 500
    except httpx.HTTPError:
        return False


def _resolve_project_file(path: str) -> Path:
    raw_path = Path(path).expanduser()
    resolved_path = (
        raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
    ).resolve()
    project_root = PROJECT_ROOT.resolve()
    if not resolved_path.is_relative_to(project_root):
        raise HTTPException(status_code=403, detail="file path is outside project root")
    return resolved_path


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=5)
