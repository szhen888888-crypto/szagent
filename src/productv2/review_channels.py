"""Manual review notification channels."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from productv2.config import Settings
from productv2.manual_review import MANUAL_REVIEW_ACTIONS


class FeishuAPIError(RuntimeError):
    """Raised when Feishu returns a non-success response."""


def notify_feishu_review(
    payload: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    settings: Settings | None = None,
    client: "FeishuReviewClient | None" = None,
    review_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_settings = settings or Settings()
    if not _feishu_enabled(active_settings):
        return {
            "status": "skipped",
            "reason": "feishu_not_configured",
        }

    notification_key = manual_review_notification_key(payload)
    marker_path = _notification_marker_path(payload, state, active_settings, notification_key)
    normalized_review_context = normalize_review_context(review_context or {})
    if marker_path.exists():
        cached = _read_marker(marker_path)
        if cached and _marker_matches_review_context(cached, normalized_review_context):
            return {
                **cached,
                "status": "sent",
                "cache": "hit",
                "marker_path": str(marker_path),
            }

    active_client = client or FeishuReviewClient(active_settings)
    send_result = active_client.send_manual_review(
        payload,
        review_context=normalized_review_context,
    )
    result = {
        "status": "sent",
        "cache": "miss",
        "channel": "feishu",
        "notification_key": notification_key,
        "marker_path": str(marker_path),
        "review_context": normalized_review_context,
        "action_values": review_action_values(normalized_review_context),
        "sent_at": datetime.now(UTC).isoformat(),
        **send_result,
    }
    _write_marker(marker_path, result)
    return result


def manual_review_notification_key(payload: dict[str, Any]) -> str:
    product = _dict_value(payload.get("product"))
    raw = {
        "type": payload.get("type"),
        "platform": product.get("platform"),
        "product_id": product.get("product_id") or product.get("id"),
        "attempt": payload.get("attempt"),
        "generated_image_path": payload.get("generated_image_path"),
    }
    digest = hashlib.sha256(
        json.dumps(raw, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return digest[:24]


def normalize_review_context(review_context: dict[str, Any]) -> dict[str, str]:
    return {
        "thread_id": str(review_context.get("thread_id") or ""),
        "api_url": str(review_context.get("api_url") or ""),
        "assistant_id": str(review_context.get("assistant_id") or ""),
    }


def review_action_values(review_context: dict[str, Any]) -> list[dict[str, str]]:
    context = normalize_review_context(review_context)
    if not context["thread_id"] or not context["api_url"] or not context["assistant_id"]:
        return []
    return [{**context, "action": action} for action in MANUAL_REVIEW_ACTIONS]


class FeishuReviewClient:
    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self.http_client = http_client or httpx.Client(timeout=30)

    def send_manual_review(
        self,
        payload: dict[str, Any],
        *,
        review_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = self._tenant_access_token()
        image_keys = self._upload_review_images(token, payload)
        card = build_feishu_review_card(
            payload,
            image_keys,
            self.settings,
            review_context=review_context or {},
        )
        message = self._send_interactive_message(token, card)
        return {
            "message_id": _dict_value(message.get("data")).get("message_id", ""),
            "image_keys": image_keys,
        }

    def _tenant_access_token(self) -> str:
        secret = (
            self.settings.feishu_app_secret.get_secret_value()
            if self.settings.feishu_app_secret
            else ""
        )
        data = self._post_json(
            "/open-apis/auth/v3/tenant_access_token/internal",
            {
                "app_id": self.settings.feishu_app_id,
                "app_secret": secret,
            },
            auth_token="",
        )
        token = str(
            data.get("tenant_access_token")
            or _dict_value(data.get("data")).get("tenant_access_token")
            or ""
        )
        if not token:
            raise FeishuAPIError("Feishu tenant_access_token missing")
        return token

    def _upload_review_images(
        self,
        token: str,
        payload: dict[str, Any],
    ) -> list[dict[str, str]]:
        uploaded: list[dict[str, str]] = []
        for label, raw_path in _review_image_paths(payload):
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                uploaded.append(
                    {
                        "label": label,
                        "path": raw_path,
                        "status": "missing",
                    }
                )
                continue
            image_key = self._upload_image(token, path)
            uploaded.append(
                {
                    "label": label,
                    "path": raw_path,
                    "status": "uploaded",
                    "image_key": image_key,
                }
            )
        return uploaded

    def _upload_image(self, token: str, path: Path) -> str:
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as image_file:
            response = self.http_client.post(
                _url(self.settings, "/open-apis/im/v1/images"),
                headers={"Authorization": f"Bearer {token}"},
                data={"image_type": "message"},
                files={"image": (path.name, image_file, mime_type)},
            )
        data = _parse_feishu_response(response, "/open-apis/im/v1/images")
        image_key = str(_dict_value(data.get("data")).get("image_key") or "")
        if not image_key:
            raise FeishuAPIError(f"Feishu image_key missing for {path}")
        return image_key

    def _send_interactive_message(
        self,
        token: str,
        card: dict[str, Any],
    ) -> dict[str, Any]:
        return self._post_json(
            "/open-apis/im/v1/messages",
            {
                "receive_id": self.settings.feishu_receive_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
            auth_token=token,
            params={"receive_id_type": self.settings.feishu_receive_id_type},
        )

    def _post_json(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        auth_token: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        response = self.http_client.post(
            _url(self.settings, path),
            json=payload,
            headers=headers,
            params=params,
        )
        return _parse_feishu_response(response, path)


def build_feishu_review_card(
    payload: dict[str, Any],
    image_keys: list[dict[str, str]],
    settings: Settings,
    *,
    review_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    product = _dict_value(payload.get("product"))
    rawdata = _dict_value(product.get("rawdata"))
    title = str(rawdata.get("title") or product.get("product_id") or "未命名商品")
    product_id = str(product.get("product_id") or product.get("id") or "-")
    platform = str(product.get("platform") or "-")
    attempt = str(payload.get("attempt") or "-")

    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**商品**：{title}\n"
                    f"**产品 ID**：{product_id}\n"
                    f"**平台**：{platform}\n"
                    f"**生成 Attempt**：{attempt}"
                ),
            },
        },
        {"tag": "hr"},
    ]
    for item in image_keys:
        label = item.get("label", "图片")
        if item.get("status") == "uploaded" and item.get("image_key"):
            elements.extend(
                [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": f"**{label}**"},
                    },
                    {
                        "tag": "img",
                        "img_key": item["image_key"],
                        "alt": {"tag": "plain_text", "content": label},
                    },
                ]
            )
        else:
            elements.append(
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**{label}**：本地图片不存在，未上传。",
                    },
                }
            )
    actions = _review_card_actions(review_context or {}, settings)
    if actions:
        elements.append({"tag": "action", "actions": actions})
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "Productv2 穿戴图待审核"},
        },
        "elements": elements,
    }


def _review_card_actions(
    review_context: dict[str, Any],
    settings: Settings,
) -> list[dict[str, Any]]:
    context = {
        "thread_id": review_context.get("thread_id", ""),
        "api_url": review_context.get("api_url", ""),
        "assistant_id": review_context.get("assistant_id", ""),
    }
    actions: list[dict[str, Any]] = []
    if context["thread_id"] and context["api_url"] and context["assistant_id"]:
        actions.extend(
            [
                _review_action_button("通过", "primary", {**context, "action": "approve"}),
                _review_action_button(
                    "重生成",
                    "default",
                    {**context, "action": "regenerate"},
                ),
                _review_action_button(
                    "重编排提示词",
                    "default",
                    {**context, "action": "recompile_prompt"},
                ),
                _review_action_button("拒绝", "danger", {**context, "action": "reject"}),
            ]
        )
    if settings.feishu_review_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "打开审核控制台"},
                "type": "default",
                "url": settings.feishu_review_url,
            }
        )
    return actions


def _review_action_button(
    text: str,
    button_type: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": button_type,
        "value": value,
    }


def _review_image_paths(payload: dict[str, Any]) -> list[tuple[str, str]]:
    candidates = [
        ("主图", payload.get("marked_main_image_path")),
        ("尺寸图", payload.get("marked_size_reference_image_path")),
        ("穿戴图", payload.get("generated_image_path")),
    ]
    return [
        (label, str(path))
        for label, path in candidates
        if isinstance(path, str) and path.strip()
    ]


def _feishu_enabled(settings: Settings) -> bool:
    return bool(
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_receive_id
    )


def _notification_marker_path(
    payload: dict[str, Any],
    state: dict[str, Any] | None,
    settings: Settings,
    notification_key: str,
) -> Path:
    product = _dict_value(payload.get("product"))
    platform = str(product.get("platform") or "unknown")
    product_id = str(product.get("product_id") or product.get("id") or "unknown")
    root = Path(
        (state or {}).get("product_assets_dir") or settings.productv2_product_assets_dir
    )
    return (
        root
        / platform
        / product_id
        / "review_notifications"
        / f"feishu_{notification_key}.json"
    )


def _read_marker(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _marker_matches_review_context(
    marker: dict[str, Any],
    review_context: dict[str, str],
) -> bool:
    if not review_context["thread_id"]:
        return True
    marker_context = normalize_review_context(_dict_value(marker.get("review_context")))
    marker_actions = marker.get("action_values")
    if marker_context != review_context:
        return False
    return isinstance(marker_actions, list) and bool(marker_actions)


def _write_marker(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _parse_feishu_response(response: httpx.Response, context: str) -> dict[str, Any]:
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise FeishuAPIError(f"Feishu {context} returned non-object response")
    if int(data.get("code", 0) or 0) != 0:
        raise FeishuAPIError(
            f"Feishu {context} failed: code={data.get('code')} msg={data.get('msg')}"
        )
    return data


def _url(settings: Settings, path: str) -> str:
    return f"{settings.feishu_api_base.rstrip('/')}/{path.lstrip('/')}"


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
