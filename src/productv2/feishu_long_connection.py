"""Feishu long-connection event receiver for manual review actions."""

from __future__ import annotations

import logging
import threading
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import lark_oapi as lark
from lark_oapi.api.im.v1.model.p2_im_message_receive_v1 import P2ImMessageReceiveV1
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)

from productv2.config import Settings


ReviewActionHandler = Callable[[dict[str, str]], dict[str, Any]]
MessageHandler = Callable[[dict[str, Any]], None]

logger = logging.getLogger(__name__)


class FeishuLongConnectionServer:
    def __init__(
        self,
        settings: Settings,
        *,
        action_handler: ReviewActionHandler,
        message_handler: MessageHandler | None = None,
    ) -> None:
        self.settings = settings
        self.action_handler = action_handler
        self.message_handler = message_handler or append_feishu_event_log
        self._thread: threading.Thread | None = None

    def start(self) -> dict[str, Any]:
        if not feishu_long_connection_enabled(self.settings):
            return {"status": "skipped", "reason": "feishu_long_connection_disabled"}
        if self._thread is not None and self._thread.is_alive():
            return {"status": "running"}
        self._thread = threading.Thread(
            target=self._run,
            name="productv2-feishu-long-connection",
            daemon=True,
        )
        self._thread.start()
        return {"status": "started"}

    def _run(self) -> None:
        secret = (
            self.settings.feishu_app_secret.get_secret_value()
            if self.settings.feishu_app_secret
            else ""
        )
        verification_token = (
            self.settings.feishu_verification_token.get_secret_value()
            if self.settings.feishu_verification_token
            else ""
        )
        handler = (
            lark.EventDispatcherHandler.builder("", verification_token)
            .register_p2_card_action_trigger(self.handle_card_action)
            .register_p2_im_message_receive_v1(self.handle_message_receive)
            .build()
        )
        try:
            lark.ws.Client(
                self.settings.feishu_app_id,
                secret,
                event_handler=handler,
                domain=self.settings.feishu_api_base,
            ).start()
        except Exception:  # pragma: no cover - SDK owns reconnect loop/logging
            logger.exception("Feishu long connection stopped unexpectedly")

    def handle_card_action(
        self,
        event: P2CardActionTrigger | dict[str, Any],
    ) -> P2CardActionTriggerResponse:
        card_event = extract_card_action_event(event)
        action = extract_card_review_action(event)
        if action is None:
            self.message_handler(
                {
                    **card_event,
                    "status": "ignored",
                    "reason": "not_review_action",
                }
            )
            return _toast_response("warning", "未识别的审核动作。")
        try:
            result = self.action_handler(action)
        except (Exception, SystemExit) as exc:
            logger.exception("Feishu card review action failed")
            self.message_handler(
                {
                    **card_event,
                    "action": action,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            return _toast_response("error", f"审核提交失败：{_failure_label(exc)}")
        self.message_handler(
            {
                **card_event,
                "action": action,
                "status": "handled",
                "result": _review_action_result_summary(result),
            }
        )
        return _review_done_response(action, result)

    def handle_message_receive(
        self,
        event: P2ImMessageReceiveV1 | dict[str, Any],
    ) -> None:
        message_event = extract_message_receive_event(event)
        self.message_handler(message_event)


def feishu_long_connection_enabled(settings: Settings) -> bool:
    return bool(
        settings.feishu_long_connection_enabled
        and settings.feishu_app_id
        and settings.feishu_app_secret
    )


def extract_card_review_action(
    event: P2CardActionTrigger | dict[str, Any],
) -> dict[str, str] | None:
    payload = _event_to_dict(event)
    action_payload = _dict_value(
        _dict_value(payload.get("event")).get("action")
        or _dict_value(payload.get("action"))
    )
    value = action_payload.get("value")
    if not isinstance(value, dict):
        value = _dict_value(payload.get("value"))
    action = str(value.get("action") or "").lower()
    if action not in {"approve", "regenerate", "reject"}:
        return None
    thread_id = str(value.get("thread_id") or "")
    if not thread_id:
        return None
    return {
        "action": action,
        "thread_id": thread_id,
        "api_url": str(value.get("api_url") or "http://127.0.0.1:2024"),
        "assistant_id": str(value.get("assistant_id") or "product_listing"),
    }


def extract_card_action_event(
    event: P2CardActionTrigger | dict[str, Any],
) -> dict[str, Any]:
    payload = _event_to_dict(event)
    event_payload = _dict_value(payload.get("event"))
    action_payload = _dict_value(event_payload.get("action") or payload.get("action"))
    context = _dict_value(event_payload.get("context") or payload.get("context"))
    operator = _dict_value(event_payload.get("operator") or payload.get("operator"))
    return {
        "received_at": datetime.now(UTC).isoformat(),
        "event_type": "card.action.trigger",
        "action_value": _dict_value(action_payload.get("value")),
        "context": context,
        "operator": operator,
        "raw": payload,
    }


def extract_message_receive_event(
    event: P2ImMessageReceiveV1 | dict[str, Any],
) -> dict[str, Any]:
    payload = _event_to_dict(event)
    event_payload = _dict_value(payload.get("event"))
    sender = _dict_value(event_payload.get("sender"))
    message = _dict_value(event_payload.get("message"))
    content = message.get("content")
    parsed_content: Any = None
    if isinstance(content, str) and content.strip():
        try:
            parsed_content = json.loads(content)
        except json.JSONDecodeError:
            parsed_content = content
    return {
        "received_at": datetime.now(UTC).isoformat(),
        "event_type": "im.message.receive_v1",
        "sender": sender,
        "message": {
            "message_id": message.get("message_id"),
            "chat_id": message.get("chat_id"),
            "chat_type": message.get("chat_type"),
            "message_type": message.get("message_type"),
            "content": content,
            "parsed_content": parsed_content,
        },
        "raw": payload,
    }


def append_feishu_event_log(event: dict[str, Any]) -> None:
    log_path = feishu_event_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def list_feishu_event_log(limit: int = 20) -> list[dict[str, Any]]:
    log_path = feishu_event_log_path()
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    events: list[dict[str, Any]] = []
    for line in lines[-max(limit, 1) :]:
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, dict):
            events.append(loaded)
    return events


def feishu_event_log_path() -> Path:
    from productv2.config import PROJECT_ROOT

    return PROJECT_ROOT / ".control" / "feishu-events.log"


def _event_to_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    event = getattr(value, "event", None)
    if event is None:
        return {}
    message = getattr(event, "message", None)
    sender = getattr(event, "sender", None)
    if message is not None:
        return {
            "event": {
                "sender": _object_attrs(
                    sender,
                    ["sender_type", "tenant_key"],
                    nested={"sender_id": ["user_id", "open_id", "union_id"]},
                ),
                "message": _object_attrs(
                    message,
                    [
                        "message_id",
                        "root_id",
                        "parent_id",
                        "create_time",
                        "update_time",
                        "chat_id",
                        "thread_id",
                        "chat_type",
                        "message_type",
                        "content",
                    ],
                ),
            }
        }
    action = getattr(event, "action", None)
    action_value = getattr(action, "value", None)
    context = getattr(event, "context", None)
    operator = getattr(event, "operator", None)
    return {
        "event": {
            "action": {
                "value": action_value if isinstance(action_value, dict) else {},
            },
            "context": _object_attrs(
                context,
                [
                    "open_message_id",
                    "open_chat_id",
                    "open_thread_id",
                    "delivery_type",
                    "token",
                ],
            ),
            "operator": _object_attrs(
                operator,
                ["tenant_key"],
                nested={"operator_id": ["user_id", "open_id", "union_id"]},
            ),
        }
    }


def _object_attrs(
    value: Any,
    attrs: list[str],
    *,
    nested: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    if value is None:
        return {}
    result = {
        attr: getattr(value, attr)
        for attr in attrs
        if getattr(value, attr, None) is not None
    }
    for attr, child_attrs in (nested or {}).items():
        child = getattr(value, attr, None)
        if child is not None:
            result[attr] = _object_attrs(child, child_attrs)
    return result


def _toast_response(toast_type: str, content: str) -> P2CardActionTriggerResponse:
    return P2CardActionTriggerResponse(
        {
            "toast": {
                "type": toast_type,
                "content": content,
            }
        }
    )


def _review_done_response(
    action: dict[str, str],
    result: dict[str, Any],
) -> P2CardActionTriggerResponse:
    return P2CardActionTriggerResponse(
        {
            "toast": {
                "type": "success",
                "content": _success_message(action["action"]),
            },
            "card": {
                "type": "raw",
                "data": build_review_done_card(action, result),
            },
        }
    )


def build_review_done_card(
    action: dict[str, str],
    result: dict[str, Any],
) -> dict[str, Any]:
    label, template = _review_action_style(action["action"])
    reviewed_at = datetime.now(UTC).isoformat()
    run_id = str(result.get("run_id") or "-") if isinstance(result, dict) else "-"
    thread_id = action.get("thread_id") or "-"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": f"Productv2 审核已处理：{label}"},
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**审核结果**：{label}\n"
                        f"**Thread**：{thread_id}\n"
                        f"**Run ID**：{run_id}\n"
                        f"**处理时间**：{reviewed_at}"
                    ),
                },
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "该审核动作已提交到 LangGraph，原审核按钮已失效。",
                    }
                ],
            },
        ],
    }


def _review_action_style(action: str) -> tuple[str, str]:
    styles = {
        "approve": ("通过", "green"),
        "regenerate": ("重生成", "orange"),
        "reject": ("拒绝", "red"),
    }
    return styles.get(action, ("已处理", "blue"))


def _success_message(action: str) -> str:
    labels = {
        "approve": "已提交通过。",
        "regenerate": "已提交重生成。",
        "reject": "已提交拒绝。",
    }
    return labels.get(action, "已提交审核动作。")


def _failure_label(exc: BaseException) -> str:
    if isinstance(exc, SystemExit):
        return "LangGraph 请求失败"
    return type(exc).__name__


def _review_action_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    return {
        "mode": result.get("mode"),
        "thread_id": result.get("thread_id"),
        "run_id": result.get("run_id"),
        "state_url": result.get("state_url"),
        "multitask_strategy": result.get("multitask_strategy"),
    }


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
