"""Local control API for the Productv2 LangGraph console."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

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


DEFAULT_LANGGRAPH_API_URL = "http://127.0.0.1:2024"
DEFAULT_ASSISTANT_ID = "product_listing"
DEFAULT_LANGGRAPH_HOST = "127.0.0.1"
DEFAULT_LANGGRAPH_PORT = 2024


app = FastAPI(title="Productv2 Control API", version="0.1.0")
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


class ResumeThreadRequest(BaseModel):
    api_url: str = DEFAULT_LANGGRAPH_API_URL
    assistant_id: str = DEFAULT_ASSISTANT_ID
    resume: Any = Field(default_factory=dict)


_managed_process: subprocess.Popen[str] | None = None
_managed_started_at: float | None = None


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok"}


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
    return list_workflow_threads_via_api(
        api_url=api_url,
        assistant_id=assistant_id,
        thread_limit=limit,
    )


@app.get("/api/threads/{thread_id}/state")
def thread_state(
    thread_id: str,
    api_url: str = Query(DEFAULT_LANGGRAPH_API_URL),
) -> dict[str, Any]:
    try:
        base_url = api_url.rstrip("/")
        state = _api_get_json(base_url, f"/threads/{thread_id}/state")
        runs = _list_thread_runs(base_url, thread_id)
        return {
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
    except SystemExit as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/files/image")
def image_file(path: str = Query(..., min_length=1)) -> FileResponse:
    resolved_path = _resolve_project_file(path)
    if not resolved_path.exists() or not resolved_path.is_file():
        raise HTTPException(status_code=404, detail="image file not found")
    return FileResponse(resolved_path)


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
