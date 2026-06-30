import json
from pathlib import Path

import httpx

from productv2.config import Settings
from productv2.review_channels import (
    FeishuReviewClient,
    build_feishu_review_card,
    notify_feishu_review,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        productv2_product_assets_dir=tmp_path,
        feishu_app_id="cli-test",
        feishu_app_secret="secret",
        feishu_receive_id="ou-test",
        feishu_receive_id_type="open_id",
    )


def test_build_feishu_review_card_contains_images_and_actions(tmp_path) -> None:
    settings = _settings(tmp_path)
    card = build_feishu_review_card(
        {
            "product": {
                "product_id": "p1",
                "platform": "1688",
                "rawdata": {"title": "测试商品"},
            },
            "attempt": 1,
        },
        [
            {"label": "主图", "status": "uploaded", "image_key": "img-main"},
            {"label": "尺寸图", "status": "uploaded", "image_key": "img-size"},
            {"label": "穿戴图", "status": "uploaded", "image_key": "img-wearing"},
        ],
        settings,
        review_context={
            "api_url": "http://127.0.0.1:2024",
            "assistant_id": "product_listing",
            "thread_id": "thread-1",
        },
    )

    image_keys = [
        element["img_key"] for element in card["elements"] if element.get("tag") == "img"
    ]
    action = next(
        element for element in card["elements"] if element.get("tag") == "action"
    )

    assert image_keys == ["img-main", "img-size", "img-wearing"]
    assert [button["value"]["action"] for button in action["actions"][:3]] == [
        "approve",
        "regenerate",
        "reject",
    ]
    assert action["actions"][0]["value"]["thread_id"] == "thread-1"


def test_notify_feishu_review_uploads_images_and_sends_message(tmp_path) -> None:
    for name in ("main.jpg", "size.jpg", "wearing.jpg"):
        (tmp_path / name).write_bytes(b"fake-image")
    settings = _settings(tmp_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/tenant_access_token/internal"):
            return httpx.Response(200, json={"code": 0, "tenant_access_token": "tenant"})
        if request.url.path.endswith("/im/v1/images"):
            return httpx.Response(
                200,
                json={"code": 0, "data": {"image_key": f"img-{len(requests)}"}},
            )
        if request.url.path.endswith("/im/v1/messages"):
            return httpx.Response(
                200,
                json={"code": 0, "data": {"message_id": "msg-1"}},
            )
        return httpx.Response(404)

    client = FeishuReviewClient(
        settings,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = notify_feishu_review(
        {
            "type": "wearing_image_review",
            "product": {"product_id": "p1", "platform": "1688", "rawdata": {}},
            "marked_main_image_path": str(tmp_path / "main.jpg"),
            "marked_size_reference_image_path": str(tmp_path / "size.jpg"),
            "generated_image_path": str(tmp_path / "wearing.jpg"),
            "attempt": 1,
        },
        state={"product_assets_dir": str(tmp_path)},
        settings=settings,
        client=client,
        review_context={
            "api_url": "http://127.0.0.1:2024",
            "assistant_id": "product_listing",
            "thread_id": "thread-1",
        },
    )

    assert result["status"] == "sent"
    assert result["review_context"]["thread_id"] == "thread-1"
    assert [item["action"] for item in result["action_values"]] == [
        "approve",
        "regenerate",
        "reject",
    ]
    assert result["message_id"] == "msg-1"
    assert [item["status"] for item in result["image_keys"]] == [
        "uploaded",
        "uploaded",
        "uploaded",
    ]
    assert sum(1 for request in requests if request.url.path.endswith("/im/v1/images")) == 3


def test_notify_feishu_review_reuses_marker_with_matching_action_values(tmp_path) -> None:
    settings = _settings(tmp_path)
    payload = {
        "type": "wearing_image_review",
        "product": {"product_id": "p1", "platform": "1688", "rawdata": {}},
        "generated_image_path": str(tmp_path / "wearing.jpg"),
        "attempt": 1,
    }
    marker_dir = tmp_path / "1688" / "p1" / "review_notifications"
    marker_dir.mkdir(parents=True)
    marker = {
        "status": "sent",
        "message_id": "msg-cached",
        "review_context": {
            "api_url": "http://127.0.0.1:2024",
            "assistant_id": "product_listing",
            "thread_id": "thread-1",
        },
        "action_values": [
            {
                "api_url": "http://127.0.0.1:2024",
                "assistant_id": "product_listing",
                "thread_id": "thread-1",
                "action": "approve",
            }
        ],
    }
    marker_path = next_marker_path(marker_dir, payload)
    marker_path.write_text(json.dumps(marker), encoding="utf-8")

    result = notify_feishu_review(
        payload,
        state={"product_assets_dir": str(tmp_path)},
        settings=settings,
        client=object(),
        review_context=marker["review_context"],
    )

    assert result["cache"] == "hit"
    assert result["message_id"] == "msg-cached"


def test_notify_feishu_review_resends_old_marker_without_action_values(tmp_path) -> None:
    settings = _settings(tmp_path)
    (tmp_path / "wearing.jpg").write_bytes(b"fake-image")
    payload = {
        "type": "wearing_image_review",
        "product": {"product_id": "p1", "platform": "1688", "rawdata": {}},
        "generated_image_path": str(tmp_path / "wearing.jpg"),
        "attempt": 1,
    }
    marker_dir = tmp_path / "1688" / "p1" / "review_notifications"
    marker_dir.mkdir(parents=True)
    marker_path = next_marker_path(marker_dir, payload)
    marker_path.write_text(
        json.dumps({"status": "sent", "message_id": "old-msg"}),
        encoding="utf-8",
    )

    class FakeClient:
        def send_manual_review(self, _payload, *, review_context=None):
            return {"message_id": "new-msg", "image_keys": []}

    result = notify_feishu_review(
        payload,
        state={"product_assets_dir": str(tmp_path)},
        settings=settings,
        client=FakeClient(),
        review_context={
            "api_url": "http://127.0.0.1:2024",
            "assistant_id": "product_listing",
            "thread_id": "thread-1",
        },
    )

    assert result["cache"] == "miss"
    assert result["message_id"] == "new-msg"
    assert result["action_values"][0]["thread_id"] == "thread-1"


def test_notify_feishu_review_skips_when_not_configured() -> None:
    result = notify_feishu_review(
        {"type": "wearing_image_review"},
        settings=Settings(feishu_app_id="", feishu_receive_id=""),
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "feishu_not_configured"


def next_marker_path(marker_dir: Path, payload: dict) -> Path:
    from productv2.review_channels import manual_review_notification_key

    return marker_dir / f"feishu_{manual_review_notification_key(payload)}.json"
