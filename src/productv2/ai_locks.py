"""Persistent idempotency locks for external AI calls."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from productv2.config import DEFAULT_DATABASE_PATH, Settings
from productv2.db import (
    acquire_ai_call_lock,
    get_ai_call_lock,
    update_ai_call_lock_result,
)
from productv2.workflow_logging import WorkflowRunLogger


T = TypeVar("T")


class AICallInProgressError(RuntimeError):
    """Raised when another process still owns an AI call lock."""


class AICallFailedError(RuntimeError):
    """Raised when a persisted AI call already failed."""


def make_ai_call_key(call_type: str, request: dict[str, Any]) -> str:
    """Build a stable key for one external AI call."""

    return f"{call_type}:{_stable_hash(request)}"


def run_with_ai_call_lock(
    *,
    database_path: str | Path | None = None,
    call_type: str,
    request: dict[str, Any],
    execute: Callable[[], T],
    result_to_json: Callable[[T], dict[str, Any]],
    result_from_json: Callable[[dict[str, Any]], T],
    settings: Settings | None = None,
    logger: WorkflowRunLogger | None = None,
    stale_after_seconds: float | None = None,
) -> T:
    """Run an external AI call once for a stable request and cache the result."""

    active_settings = settings or Settings()
    active_database_path = database_path or active_settings.productv2_database_path
    active_stale_after = (
        active_settings.ai_call_lock_stale_after
        if stale_after_seconds is None
        else stale_after_seconds
    )
    call_key = make_ai_call_key(call_type, request)
    owner = f"productv2-ai-{uuid.uuid4().hex}"
    wait_deadline = time.monotonic() + max(0.0, active_settings.ai_call_lock_wait_timeout)

    while True:
        lock = acquire_ai_call_lock(
            active_database_path,
            call_key=call_key,
            call_type=call_type,
            request=request,
            owner=owner,
            stale_after_seconds=active_stale_after,
        )
        if lock["acquired"]:
            break
        if lock.get("status") == "succeeded":
            if logger is not None:
                logger.write(
                    "ai_call_lock_hit",
                    data={
                        "call_type": call_type,
                        "call_key": call_key,
                        "status": lock.get("status"),
                    },
                )
            return result_from_json(dict(lock.get("result") or {}))
        if lock.get("status") == "failed":
            error = str(lock.get("error") or "AI call failed")
            raise AICallFailedError(error)
        if logger is not None:
            logger.write(
                "ai_call_lock_wait",
                data={
                    "call_type": call_type,
                    "call_key": call_key,
                    "status": lock.get("status"),
                    "owner": lock.get("owner"),
                },
            )
        remaining_wait = wait_deadline - time.monotonic()
        if remaining_wait <= 0:
            raise AICallInProgressError(f"AI call still in progress: {call_key}")
        lock = _wait_for_lock(
            active_database_path,
            call_key,
            timeout=remaining_wait,
            interval=active_settings.ai_call_lock_poll_interval,
            stale_after_seconds=active_stale_after,
        )
        if lock.get("status") == "succeeded":
            if logger is not None:
                logger.write(
                    "ai_call_lock_hit",
                    data={
                        "call_type": call_type,
                        "call_key": call_key,
                        "status": lock.get("status"),
                    },
                )
            return result_from_json(dict(lock.get("result") or {}))
        if lock.get("status") == "failed":
            error = str(lock.get("error") or "AI call failed")
            raise AICallFailedError(error)
        if lock.get("stale"):
            continue
        raise AICallInProgressError(f"AI call still in progress: {call_key}")

    if logger is not None:
        logger.write(
            "ai_call_lock_acquired",
            data={
                "call_type": call_type,
                "call_key": call_key,
                "owner": owner,
                "reclaimed": lock.get("reclaimed", False),
            },
        )

    try:
        result = execute()
    except Exception as exc:
        update_ai_call_lock_result(
            active_database_path,
            call_key=call_key,
            status="failed",
            result={},
            error=f"{type(exc).__name__}: {exc}",
        )
        raise

    result_json = result_to_json(result)
    update_ai_call_lock_result(
        active_database_path,
        call_key=call_key,
        status="succeeded",
        result=result_json,
    )
    if logger is not None:
        logger.write(
            "ai_call_lock_saved",
            data={
                "call_type": call_type,
                "call_key": call_key,
                "status": "succeeded",
            },
        )
    return result


def _wait_for_lock(
    database_path: str | Path,
    call_key: str,
    *,
    timeout: float,
    interval: float,
    stale_after_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(0.0, timeout)
    sleep_interval = max(0.1, interval)
    while True:
        lock = get_ai_call_lock(database_path, call_key)
        if lock is None:
            raise AICallInProgressError(f"AI call lock disappeared: {call_key}")
        if lock.get("status") != "in_progress":
            return lock
        if _lock_is_stale(lock, stale_after_seconds):
            return {**lock, "stale": True}
        if time.monotonic() >= deadline:
            return lock
        time.sleep(sleep_interval)


def _lock_is_stale(lock: dict[str, Any], stale_after_seconds: float) -> bool:
    locked_at = _parse_datetime(str(lock.get("locked_at") or ""))
    if locked_at is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - locked_at).total_seconds()
    return age_seconds >= max(0.0, stale_after_seconds)


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


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
    try:
        json.dumps(value)
    except TypeError:
        if hasattr(value, "model_dump"):
            return _jsonable(value.model_dump())
        return str(value)
    return value
