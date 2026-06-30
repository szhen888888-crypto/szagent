from productv2.config import Settings
from productv2.feishu_long_connection import (
    FeishuLongConnectionServer,
    append_feishu_event_log,
    build_review_done_card,
    extract_card_action_event,
    extract_card_review_action,
    extract_message_receive_event,
    list_feishu_event_log,
    feishu_long_connection_enabled,
)


def test_extract_card_review_action_from_card_event_dict() -> None:
    action = extract_card_review_action(
        {
            "event": {
                "action": {
                    "value": {
                        "action": "approve",
                        "thread_id": "thread-1",
                        "api_url": "http://testserver",
                        "assistant_id": "graph",
                    }
                }
            }
        }
    )

    assert action == {
        "action": "approve",
        "thread_id": "thread-1",
        "api_url": "http://testserver",
        "assistant_id": "graph",
    }


def test_extract_card_review_action_accepts_recompile_prompt() -> None:
    action = extract_card_review_action(
        {
            "event": {
                "action": {
                    "value": {
                        "action": "recompile_prompt",
                        "thread_id": "thread-1",
                        "api_url": "http://testserver",
                        "assistant_id": "graph",
                    }
                }
            }
        }
    )

    assert action == {
        "action": "recompile_prompt",
        "thread_id": "thread-1",
        "api_url": "http://testserver",
        "assistant_id": "graph",
    }


def test_extract_card_review_action_rejects_unknown_action() -> None:
    action = extract_card_review_action(
        {
            "event": {
                "action": {
                    "value": {
                        "action": "unknown",
                        "thread_id": "thread-1",
                    }
                }
            }
        }
    )

    assert action is None


def test_feishu_long_connection_handler_resumes_review_action() -> None:
    calls = []
    events = []
    server = FeishuLongConnectionServer(
        Settings(
            feishu_app_id="cli-test",
            feishu_app_secret="secret",
            feishu_receive_id="ou-test",
        ),
        action_handler=lambda action: calls.append(action) or {"mode": "resumed"},
        message_handler=events.append,
    )

    response = server.handle_card_action(
        {
            "event": {
                "action": {
                    "value": {
                        "action": "regenerate",
                        "thread_id": "thread-1",
                        "api_url": "http://testserver",
                        "assistant_id": "graph",
                    }
                }
            }
        }
    )

    assert calls == [
        {
            "action": "regenerate",
            "thread_id": "thread-1",
            "api_url": "http://testserver",
            "assistant_id": "graph",
        }
    ]
    assert response.toast.type == "success"
    assert response.card.type == "raw"
    assert "重生成" in response.card.data["header"]["title"]["content"]
    assert not any(
        element.get("tag") == "action" for element in response.card.data["elements"]
    )


def test_feishu_long_connection_handler_logs_card_action() -> None:
    events = []
    server = FeishuLongConnectionServer(
        Settings(
            feishu_app_id="cli-test",
            feishu_app_secret="secret",
            feishu_receive_id="ou-test",
        ),
        action_handler=lambda action: {
            "mode": "resumed",
            "thread_id": action["thread_id"],
            "run_id": "run-1",
        },
        message_handler=events.append,
    )

    server.handle_card_action(
        {
            "event": {
                "context": {"open_message_id": "om-test"},
                "operator": {
                    "operator_id": {"open_id": "ou-test"},
                    "tenant_key": "tenant",
                },
                "action": {
                    "value": {
                        "action": "approve",
                        "thread_id": "thread-1",
                        "api_url": "http://testserver",
                        "assistant_id": "graph",
                    }
                },
            }
        }
    )

    assert events[0]["event_type"] == "card.action.trigger"
    assert events[0]["status"] == "handled"
    assert events[0]["action"]["action"] == "approve"
    assert events[0]["action"]["thread_id"] == "thread-1"
    assert events[0]["context"]["open_message_id"] == "om-test"
    assert events[0]["result"]["run_id"] == "run-1"


def test_feishu_long_connection_handler_logs_system_exit_failure() -> None:
    events = []

    def raise_system_exit(_action):
        raise SystemExit("LangGraph API 请求失败：HTTP 409")

    server = FeishuLongConnectionServer(
        Settings(
            feishu_app_id="cli-test",
            feishu_app_secret="secret",
            feishu_receive_id="ou-test",
        ),
        action_handler=raise_system_exit,
        message_handler=events.append,
    )

    response = server.handle_card_action(
        {
            "event": {
                "context": {"open_message_id": "om-test"},
                "action": {
                    "value": {
                        "action": "approve",
                        "thread_id": "thread-1",
                        "api_url": "http://testserver",
                        "assistant_id": "graph",
                    }
                },
            }
        }
    )

    assert response.toast.type == "error"
    assert response.toast.content == "审核提交失败：LangGraph 请求失败"
    assert events[0]["status"] == "failed"
    assert events[0]["action"]["action"] == "approve"
    assert "HTTP 409" in events[0]["error"]


def test_extract_card_action_event_from_dict() -> None:
    event = extract_card_action_event(
        {
            "event": {
                "context": {"open_message_id": "om-test"},
                "action": {
                    "value": {
                        "action": "reject",
                        "thread_id": "thread-1",
                    }
                },
            }
        }
    )

    assert event["event_type"] == "card.action.trigger"
    assert event["context"]["open_message_id"] == "om-test"
    assert event["action_value"]["action"] == "reject"


def test_build_review_done_card_marks_approve_as_success() -> None:
    card = build_review_done_card(
        {"action": "approve", "thread_id": "thread-1"},
        {"run_id": "run-1"},
    )

    assert card["header"]["template"] == "green"
    assert card["header"]["title"]["content"] == "Productv2 审核已处理：通过"
    assert "thread-1" in card["elements"][0]["text"]["content"]
    assert "run-1" in card["elements"][0]["text"]["content"]


def test_extract_message_receive_event_from_dict() -> None:
    event = extract_message_receive_event(
        {
            "event": {
                "sender": {
                    "sender_type": "user",
                    "sender_id": {"open_id": "ou-test"},
                },
                "message": {
                    "message_id": "om-test",
                    "chat_id": "oc-test",
                    "chat_type": "p2p",
                    "message_type": "text",
                    "content": "{\"text\":\"测试消息\"}",
                },
            }
        }
    )

    assert event["event_type"] == "im.message.receive_v1"
    assert event["sender"]["sender_id"]["open_id"] == "ou-test"
    assert event["message"]["message_type"] == "text"
    assert event["message"]["parsed_content"] == {"text": "测试消息"}


def test_feishu_long_connection_handler_logs_message() -> None:
    messages = []
    server = FeishuLongConnectionServer(
        Settings(
            feishu_app_id="cli-test",
            feishu_app_secret="secret",
        ),
        action_handler=lambda action: {"mode": "ignored"},
        message_handler=messages.append,
    )

    server.handle_message_receive(
        {
            "event": {
                "sender": {"sender_type": "user"},
                "message": {
                    "message_id": "om-test",
                    "message_type": "text",
                    "content": "{\"text\":\"hello\"}",
                },
            }
        }
    )

    assert messages[0]["message"]["message_id"] == "om-test"
    assert messages[0]["message"]["parsed_content"] == {"text": "hello"}


def test_feishu_event_log_roundtrip(tmp_path, monkeypatch) -> None:
    log_path = tmp_path / "feishu-events.log"
    monkeypatch.setattr(
        "productv2.feishu_long_connection.feishu_event_log_path",
        lambda: log_path,
    )

    append_feishu_event_log({"message": {"message_id": "om-1"}})
    append_feishu_event_log({"message": {"message_id": "om-2"}})

    assert list_feishu_event_log(limit=1) == [{"message": {"message_id": "om-2"}}]
    assert [event["message"]["message_id"] for event in list_feishu_event_log()] == [
        "om-1",
        "om-2",
    ]


def test_feishu_long_connection_enabled_requires_credentials() -> None:
    assert feishu_long_connection_enabled(
        Settings(
            feishu_long_connection_enabled=True,
            feishu_app_id="cli-test",
            feishu_app_secret="secret",
        )
    )
    assert not feishu_long_connection_enabled(
        Settings(feishu_long_connection_enabled=True, feishu_app_id="")
    )
    assert not feishu_long_connection_enabled(
        Settings(
            feishu_long_connection_enabled=False,
            feishu_app_id="cli-test",
            feishu_app_secret="secret",
        )
    )
