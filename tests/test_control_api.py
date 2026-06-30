from fastapi.testclient import TestClient

from productv2.manual_review import WearingImageReviewRequest
from productv2 import control_api


def test_control_api_lists_threads(monkeypatch) -> None:
    def fake_list_workflow_threads_via_api(**kwargs):
        return {
            "online": True,
            "api_url": kwargs["api_url"],
            "assistant_id": kwargs["assistant_id"],
            "threads": [
                {
                    "thread_id": "thread-1",
                    "status": "interrupted",
                    "summary": {"product_id": "p1", "next": ["wait_manual_review"]},
                }
            ],
        }

    monkeypatch.setattr(
        control_api,
        "list_workflow_threads_via_api",
        fake_list_workflow_threads_via_api,
    )

    client = TestClient(control_api.app)
    response = client.get("/api/threads?api_url=http://testserver&assistant_id=graph")

    assert response.status_code == 200
    assert response.json()["threads"][0]["thread_id"] == "thread-1"


def test_control_api_thread_summary_uses_database_product_status(monkeypatch) -> None:
    def fake_list_workflow_threads_via_api(**kwargs):
        return {
            "online": True,
            "api_url": kwargs["api_url"],
            "assistant_id": kwargs["assistant_id"],
            "threads": [
                {
                    "thread_id": "thread-1",
                    "status": "idle",
                    "summary": {
                        "product_id": "p1",
                        "platform": "1688",
                        "product_status": "processing",
                    },
                }
            ],
        }

    product = type(
        "ProductStub",
        (),
        {
            "model_dump": lambda self: {
                "product_id": "p1",
                "platform": "1688",
                "status": "done",
                "wearing_image": "data/products/1688/p1/wearing.png",
                "locked_at": None,
                "locked_by": None,
            }
        },
    )()

    monkeypatch.setattr(
        control_api,
        "list_workflow_threads_via_api",
        fake_list_workflow_threads_via_api,
    )
    monkeypatch.setattr(
        control_api,
        "get_product_by_identity",
        lambda *_args, **_kwargs: product,
    )

    client = TestClient(control_api.app)
    response = client.get("/api/threads?api_url=http://testserver&assistant_id=graph")

    assert response.status_code == 200
    summary = response.json()["threads"][0]["summary"]
    assert summary["product_status"] == "done"
    assert summary["database_product_status"] == "done"
    assert summary["persisted_wearing_image"] == "data/products/1688/p1/wearing.png"


def test_control_api_lists_feishu_events(monkeypatch) -> None:
    monkeypatch.setattr(
        control_api,
        "list_feishu_event_log",
        lambda limit: [{"message": {"message_id": "om-1"}, "limit": limit}],
    )

    client = TestClient(control_api.app)
    response = client.get("/api/feishu/events?limit=1")

    assert response.status_code == 200
    assert response.json() == {
        "total": 1,
        "events": [{"message": {"message_id": "om-1"}, "limit": 1}],
    }


def test_control_api_thread_state_includes_ai_call_summaries(monkeypatch) -> None:
    state = {
        "values": {
            "selected_product": {"product_id": "p1", "platform": "1688"},
            "ai_checkpoints": {
                "compile_wearing_generation_prompt": {
                    "key": "compile_wearing_generation_prompt",
                    "type": "llm",
                    "source": "llm_compiler",
                    "input": {
                        "product": {"product_id": "p1", "platform": "1688"},
                        "_runtime": {
                            "model": "gpt-5.5",
                            "providers": [
                                {"name": "primary", "api_base": "https://llm"}
                            ],
                            "prompts": {"wearing/compile_generation_prompt": 1},
                        },
                    },
                    "input_hash": "hash-1",
                    "status": "ok",
                    "result": {
                        "status": "ok",
                        "prompt": "compiled prompt",
                        "input_images": ["main.jpg", "size.jpg", "model.jpg"],
                        "enroute_reference_image_path": "enroute.jpg",
                    },
                    "attempt_count": 1,
                },
                "generate_wearing_image_attempt_1": {
                    "key": "generate_wearing_image_attempt_1",
                    "type": "image_ai",
                    "source": "image_ai",
                    "input": {
                        "attempt": 1,
                        "wearing_generation_prompt_result": {
                            "prompt": "compiled prompt",
                            "input_images": ["main.jpg", "size.jpg", "model.jpg"],
                        },
                        "_runtime": {
                            "model": "gpt-5.5",
                            "providers": [
                                {"name": "primary", "api_base": "https://llm"}
                            ],
                        },
                    },
                    "input_hash": "hash-2",
                    "status": "ok",
                    "result": {
                        "status": "ok",
                        "generated_image_path": "wearing.png",
                        "image_generation": {"id": "task-1", "status": "succeeded"},
                    },
                    "attempt_count": 1,
                },
            },
        },
    }

    monkeypatch.setattr(control_api, "_api_get_json", lambda *_args, **_kwargs: state)
    monkeypatch.setattr(control_api, "_list_thread_runs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        control_api,
        "get_product_by_identity",
        lambda *_args, **_kwargs: None,
    )

    client = TestClient(control_api.app)
    response = client.get("/api/threads/thread-1/state?api_url=http://testserver")

    assert response.status_code == 200
    ai_calls = response.json()["ai_calls"]
    assert ai_calls[0]["label"] == "LLM 编排生图提示词"
    assert ai_calls[0]["output"]["prompt"] == "compiled prompt"
    assert [image["path"] for image in ai_calls[0]["images"]] == [
        "main.jpg",
        "size.jpg",
        "model.jpg",
        "enroute.jpg",
    ]
    assert ai_calls[1]["label"] == "图片 AI 生成穿戴图"
    assert ai_calls[1]["input"]["grsai_input_images"] == [
        "main.jpg",
        "size.jpg",
        "model.jpg",
    ]
    assert ai_calls[1]["images"][-1]["path"] == "wearing.png"


def test_control_api_notifies_feishu_for_manual_review_threads(monkeypatch) -> None:
    def fake_list_workflow_threads_via_api(**kwargs):
        return {
            "online": True,
            "api_url": kwargs["api_url"],
            "assistant_id": kwargs["assistant_id"],
            "threads": [
                {
                    "thread_id": "thread-1",
                    "status": "interrupted",
                    "summary": {
                        "needs_manual_review": True,
                        "next": ["wait_manual_review"],
                    },
                }
            ],
        }

    monkeypatch.setattr(
        control_api,
        "list_workflow_threads_via_api",
        fake_list_workflow_threads_via_api,
    )
    monkeypatch.setattr(
        control_api,
        "_api_get_json",
        lambda *_args, **_kwargs: {
            "interrupts": [
                {
                    "value": WearingImageReviewRequest(
                        generated_image_path="/tmp/wearing.png"
                    ).model_dump()
                }
            ]
        },
    )

    calls = []

    def fake_notify_feishu_review(payload, **kwargs):
        calls.append((payload, kwargs))
        return {"status": "sent", "message_id": "msg-1"}

    monkeypatch.setattr(control_api, "notify_feishu_review", fake_notify_feishu_review)

    client = TestClient(control_api.app)
    response = client.get("/api/threads?api_url=http://testserver&assistant_id=graph")

    assert response.status_code == 200
    assert calls[0][0]["type"] == "wearing_image_review"
    assert calls[0][1]["review_context"]["thread_id"] == "thread-1"
    assert response.json()["threads"][0]["review_notification"]["status"] == "sent"


def test_control_api_scans_manual_review_notifications(monkeypatch) -> None:
    settings = type(
        "SettingsStub",
        (),
        {
            "review_watcher_enabled": True,
            "review_watcher_api_url": "http://testserver",
            "review_watcher_assistant_id": "graph",
            "review_watcher_thread_limit": 50,
            "review_watcher_interval": 5,
        },
    )()

    def fake_list_workflow_threads_via_api(**kwargs):
        return {
            "online": True,
            "api_url": kwargs["api_url"],
            "assistant_id": kwargs["assistant_id"],
            "threads": [
                {
                    "thread_id": "thread-1",
                    "status": "interrupted",
                    "summary": {"needs_manual_review": True},
                }
            ],
        }

    monkeypatch.setattr(
        control_api,
        "list_workflow_threads_via_api",
        fake_list_workflow_threads_via_api,
    )
    monkeypatch.setattr(
        control_api,
        "_api_get_json",
        lambda *_args, **_kwargs: {
            "values": {
                "manual_review_request": WearingImageReviewRequest(
                    generated_image_path="/tmp/wearing.png"
                ).model_dump()
            }
        },
    )
    monkeypatch.setattr(
        control_api,
        "notify_feishu_review",
        lambda *_args, **_kwargs: {"status": "sent", "message_id": "msg-1"},
    )

    result = control_api._scan_manual_review_notifications(settings=settings)

    assert result["enabled"] is True
    assert result["online"] is True
    assert result["notified_threads"] == 1
    assert result["processed_threads"] == 1
    assert result["threads"][0]["thread_id"] == "thread-1"


def test_control_api_scan_manual_review_notifications_can_be_disabled() -> None:
    settings = type(
        "SettingsStub",
        (),
        {
            "review_watcher_enabled": False,
        },
    )()

    result = control_api._scan_manual_review_notifications(settings=settings)

    assert result == {
        "enabled": False,
        "notified_threads": 0,
        "message": "manual review watcher disabled",
    }


def test_control_api_scan_manual_review_notifications_handles_offline(
    monkeypatch,
) -> None:
    settings = type(
        "SettingsStub",
        (),
        {
            "review_watcher_enabled": True,
            "review_watcher_api_url": "http://testserver",
            "review_watcher_assistant_id": "graph",
            "review_watcher_thread_limit": 50,
        },
    )()

    monkeypatch.setattr(
        control_api,
        "list_workflow_threads_via_api",
        lambda **_kwargs: {
            "online": False,
            "api_url": "http://testserver",
            "error": "connection refused",
            "threads": [],
        },
    )

    result = control_api._scan_manual_review_notifications(settings=settings)

    assert result["enabled"] is True
    assert result["online"] is False
    assert result["notified_threads"] == 0
    assert result["error"] == "connection refused"


def test_control_api_starts_feishu_long_connection(monkeypatch) -> None:
    created = []

    class FakeFeishuLongConnectionServer:
        def __init__(self, settings, *, action_handler):
            created.append((settings, action_handler))

        def start(self):
            return {"status": "started"}

    monkeypatch.setattr(
        control_api,
        "_feishu_long_connection_server",
        None,
    )
    monkeypatch.setattr(
        control_api,
        "FeishuLongConnectionServer",
        FakeFeishuLongConnectionServer,
    )

    result = control_api._start_feishu_long_connection(settings=object())

    assert result == {"status": "started"}
    assert created[0][1] is control_api._resume_feishu_review_action


def test_control_api_resumes_feishu_review_action(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        control_api,
        "_resume_thread",
        lambda **kwargs: calls.append(kwargs) or {"mode": "resumed"},
    )

    result = control_api._resume_feishu_review_action(
        {
            "action": "reject",
            "thread_id": "thread-1",
            "api_url": "http://testserver",
            "assistant_id": "graph",
        }
    )

    assert result == {"mode": "resumed"}
    assert calls == [
        {
            "api_url": "http://testserver",
            "assistant_id": "graph",
            "thread_id": "thread-1",
            "resume_payload": {"action": "reject"},
        }
    ]


def test_control_api_restarts_workflow(monkeypatch) -> None:
    def fake_restart_workflow_via_api(**kwargs):
        return {
            "mode": "resume_required",
            "api_url": kwargs["api_url"],
            "assistant_id": kwargs["assistant_id"],
            "thread_id": "thread-1",
        }

    monkeypatch.setattr(
        control_api,
        "restart_workflow_via_api",
        fake_restart_workflow_via_api,
    )

    client = TestClient(control_api.app)
    response = client.post(
        "/api/workflows/restart",
        json={"api_url": "http://testserver", "assistant_id": "graph"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "resume_required"


def test_control_api_clears_workflow_flows_and_resets_products(monkeypatch) -> None:
    def fake_list_workflow_threads_via_api(**kwargs):
        return {
            "online": True,
            "api_url": kwargs["api_url"],
            "assistant_id": kwargs["assistant_id"],
            "threads": [
                {
                    "thread_id": "thread-1",
                    "status": "interrupted",
                    "summary": {"product_id": "summary-p1", "platform": "1688"},
                },
                {
                    "thread_id": "thread-2",
                    "status": "idle",
                    "summary": {"product_id": "summary-p2", "platform": "1688"},
                },
            ],
        }

    states = {
        "/threads/thread-1/state": {
            "values": {
                "selected_product": {
                    "product_id": "state-p1",
                    "platform": "1688",
                    "status": "processing",
                }
            }
        },
        "/threads/thread-2/state": {"values": {}},
    }
    deleted_paths = []
    product_updates = []

    def fake_update_product_fields(_database_path, product_id, platform, **fields):
        product_updates.append((product_id, platform, fields))
        return type(
            "ProductStub",
            (),
            {
                "product_id": product_id,
                "platform": platform,
                "status": fields["status"],
                "locked_at": fields["locked_at"],
                "locked_by": fields["locked_by"],
            },
        )()

    monkeypatch.setattr(
        control_api,
        "list_workflow_threads_via_api",
        fake_list_workflow_threads_via_api,
    )
    monkeypatch.setattr(
        control_api,
        "_api_get_json",
        lambda _base_url, path: states[path],
    )
    monkeypatch.setattr(
        control_api,
        "_api_delete_json",
        lambda _base_url, path: deleted_paths.append(path) or {},
    )
    monkeypatch.setattr(
        control_api,
        "update_product_fields",
        fake_update_product_fields,
    )
    monkeypatch.setattr(
        control_api,
        "Settings",
        lambda: type("SettingsStub", (), {"productv2_database_path": "test.db"})(),
    )

    client = TestClient(control_api.app)
    response = client.post(
        "/api/workflows/clear-flows",
        json={"api_url": "http://testserver", "assistant_id": "graph"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "clear_flows"
    assert payload["deleted_threads"] == 2
    assert payload["products_reset"] == 2
    assert deleted_paths == ["/threads/thread-1", "/threads/thread-2"]
    assert product_updates == [
        (
            "state-p1",
            "1688",
            {"status": "all_pendding", "locked_at": None, "locked_by": None},
        ),
        (
            "summary-p2",
            "1688",
            {"status": "all_pendding", "locked_at": None, "locked_by": None},
        ),
    ]


def test_control_api_stops_single_flow_active_runs(monkeypatch) -> None:
    cancelled = []

    monkeypatch.setattr(
        control_api,
        "_list_thread_runs",
        lambda _base_url, _thread_id: [
            {"run_id": "run-pending", "status": "pending"},
            {"run_id": "run-running", "status": "running"},
            {"run_id": "run-success", "status": "success"},
        ],
    )
    monkeypatch.setattr(
        control_api,
        "_api_cancel_run",
        lambda base_url, thread_id, run_id: cancelled.append(
            (base_url, thread_id, run_id)
        )
        or {},
    )

    client = TestClient(control_api.app)
    response = client.post(
        "/api/threads/thread-1/stop",
        json={"api_url": "http://testserver"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "stop_flow"
    assert payload["run_count"] == 3
    assert payload["active_runs"] == 2
    assert payload["cancelled_runs"] == 2
    assert cancelled == [
        ("http://testserver", "thread-1", "run-pending"),
        ("http://testserver", "thread-1", "run-running"),
    ]
    assert payload["items"][2]["skip_reason"] == "inactive_status"


def test_control_api_deletes_single_flow_and_resets_product(monkeypatch) -> None:
    deleted_paths = []
    product_updates = []

    monkeypatch.setattr(
        control_api,
        "_api_get_json",
        lambda _base_url, path: {
            "/threads/thread-1/state": {
                "values": {
                    "selected_product": {
                        "product_id": "state-p1",
                        "platform": "1688",
                        "status": "processing",
                    }
                }
            }
        }[path],
    )
    monkeypatch.setattr(
        control_api,
        "_api_delete_json",
        lambda _base_url, path: deleted_paths.append(path) or {},
    )

    def fake_update_product_fields(_database_path, product_id, platform, **fields):
        product_updates.append((product_id, platform, fields))
        return type(
            "ProductStub",
            (),
            {
                "product_id": product_id,
                "platform": platform,
                "status": fields["status"],
                "locked_at": fields["locked_at"],
                "locked_by": fields["locked_by"],
            },
        )()

    monkeypatch.setattr(
        control_api,
        "update_product_fields",
        fake_update_product_fields,
    )
    monkeypatch.setattr(
        control_api,
        "Settings",
        lambda: type("SettingsStub", (), {"productv2_database_path": "test.db"})(),
    )

    client = TestClient(control_api.app)
    response = client.delete(
        "/api/threads/thread-1"
        "?api_url=http%3A%2F%2Ftestserver&assistant_id=graph"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "delete_flow"
    assert payload["deleted_threads"] == 1
    assert payload["products_reset"] == 1
    assert deleted_paths == ["/threads/thread-1"]
    assert product_updates == [
        (
            "state-p1",
            "1688",
            {"status": "all_pendding", "locked_at": None, "locked_by": None},
        )
    ]


def test_control_api_reports_external_langgraph_server(monkeypatch) -> None:
    monkeypatch.setattr(control_api, "_langgraph_online", lambda api_url: True)
    monkeypatch.setattr(control_api, "_current_managed_process", lambda: None)

    client = TestClient(control_api.app)
    response = client.post("/api/server/start", json={"port": 2024})

    assert response.status_code == 200
    assert response.json()["online"] is True
    assert response.json()["managed"] is False
    assert "不是由当前控制台进程托管" in response.json()["message"]


def test_control_api_starts_langgraph_with_no_reload_by_default(
    monkeypatch,
    tmp_path,
) -> None:
    started = {}

    class ProcessStub:
        pid = 123

        def poll(self):
            return None

    def fake_popen(command, **kwargs):
        started["command"] = command
        started["kwargs"] = kwargs
        return ProcessStub()

    monkeypatch.setattr(control_api, "_managed_process", None)
    monkeypatch.setattr(control_api, "_managed_started_at", None)
    monkeypatch.setattr(control_api, "_langgraph_online", lambda api_url: False)
    monkeypatch.setattr(control_api.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(control_api, "PROJECT_ROOT", tmp_path)

    client = TestClient(control_api.app)
    response = client.post("/api/server/start", json={"port": 2024})

    assert response.status_code == 200
    command = started["command"]
    assert command[:3] == ["uv", "run", "langgraph"]
    assert "--allow-blocking" in command
    assert "--no-browser" in command
    assert "--no-reload" in command


def test_control_api_resume_requires_payload() -> None:
    client = TestClient(control_api.app)
    response = client.post(
        "/api/threads/thread-1/resume",
        json={"resume": None},
    )

    assert response.status_code == 400


def test_control_api_feishu_callback_resumes_thread(monkeypatch) -> None:
    calls = []

    def fake_resume_thread(**kwargs):
        calls.append(kwargs)
        return {
            "mode": "resumed",
            "thread_id": kwargs["thread_id"],
            "resume_payload": kwargs["resume_payload"],
        }

    monkeypatch.setattr(control_api, "_resume_thread", fake_resume_thread)

    client = TestClient(control_api.app)
    response = client.post(
        "/api/review/feishu/callback",
        json={
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
        },
    )

    assert response.status_code == 200
    assert calls == [
        {
            "api_url": "http://testserver",
            "assistant_id": "graph",
            "thread_id": "thread-1",
            "resume_payload": {"action": "approve"},
        }
    ]
    assert response.json()["resume_payload"] == {"action": "approve"}


def test_control_api_feishu_url_verification() -> None:
    client = TestClient(control_api.app)
    response = client.post(
        "/api/review/feishu/callback",
        json={"type": "url_verification", "challenge": "challenge-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-token"}


def test_control_api_feishu_callback_rejects_invalid_token(monkeypatch) -> None:
    monkeypatch.setattr(
        control_api,
        "Settings",
        lambda: type(
            "SettingsStub",
            (),
            {"feishu_verification_token": type("Secret", (), {"get_secret_value": lambda self: "expected"})()},
        )(),
    )

    client = TestClient(control_api.app)
    response = client.post(
        "/api/review/feishu/callback",
        json={"token": "bad", "event": {"action": {"value": {"action": "approve"}}}},
    )

    assert response.status_code == 403


def test_control_api_serves_project_image_file(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "data" / "products" / "demo.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"fake-image")
    monkeypatch.setattr(control_api, "PROJECT_ROOT", tmp_path)

    client = TestClient(control_api.app)
    response = client.get("/api/files/image?path=data/products/demo.png")

    assert response.status_code == 200
    assert response.content == b"fake-image"


def test_control_api_rejects_image_file_outside_project(tmp_path, monkeypatch) -> None:
    outside_path = tmp_path.parent / "outside.png"
    outside_path.write_bytes(b"fake-image")
    monkeypatch.setattr(control_api, "PROJECT_ROOT", tmp_path)

    client = TestClient(control_api.app)
    response = client.get(f"/api/files/image?path={outside_path}")

    assert response.status_code == 403


def test_control_api_lists_model_profiles(tmp_path, monkeypatch) -> None:
    model_path = tmp_path / "model_profiles" / "romantic_rebel_european" / "model.jpg"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"fake-image")
    monkeypatch.setattr(
        control_api,
        "Settings",
        lambda: type("SettingsStub", (), {"productv2_model_profiles_dir": model_path.parent.parent})(),
    )

    client = TestClient(control_api.app)
    response = client.get("/api/model-profiles")

    assert response.status_code == 200
    profiles = response.json()["profiles"]
    profile = next(
        item
        for item in profiles
        if item["profile_key"] == "romantic_rebel_european"
    )
    assert profile["name"] == "Romantic Rebel"
    assert profile["image_exists"] is True
    assert profile["image_path"] == str(model_path)
    assert profile["image_mtime_ns"] > 0
    assert "snake chain" in profile["best_for"]


def test_control_api_lists_enroute_learning(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "productv2.db"
    monkeypatch.setattr(
        control_api,
        "Settings",
        lambda: type(
            "SettingsStub",
            (),
            {"productv2_database_path": database_path},
        )(),
    )

    from productv2.db import upsert_enroute_image_analysis, upsert_enroute_learning_reference

    upsert_enroute_learning_reference(
        database_path,
        enroute_product_id="necklaces:demo",
        enroute_category="necklaces",
        enroute_title="Demo Necklace",
        enroute_handle="demo-necklace",
        product_dir="/tmp/enroute",
        image_path="/tmp/enroute/02.jpg",
        status="learned",
    )
    upsert_enroute_image_analysis(
        database_path,
        enroute_product_id="necklaces:demo",
        enroute_category="necklaces",
        enroute_title="Demo Necklace",
        enroute_handle="demo-necklace",
        image_path="/tmp/enroute/02.jpg",
        analysis_json={
            "summary": "适合短链。",
            "selected_model_profile": {
                "profile_key": "romantic_rebel_european",
                "name": "Romantic Rebel",
            },
        },
        summary="适合短链。",
    )

    client = TestClient(control_api.app)
    response = client.get("/api/enroute-learning")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["categories"] == [{"category": "necklaces", "count": 1}]
    assert payload["statuses"] == [{"status": "learned", "count": 1}]
    assert payload["items"][0]["enroute_product_id"] == "necklaces:demo"
    assert (
        payload["items"][0]["selected_model_profile"]["profile_key"]
        == "romantic_rebel_european"
    )


def test_control_api_clears_enroute_learning(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "productv2.db"
    monkeypatch.setattr(
        control_api,
        "Settings",
        lambda: type(
            "SettingsStub",
            (),
            {"productv2_database_path": database_path},
        )(),
    )

    from productv2.db import load_model_profiles, sync_default_model_profiles
    from productv2.db import upsert_enroute_image_analysis, upsert_enroute_learning_reference

    sync_default_model_profiles(database_path, tmp_path / "model_profiles")
    upsert_enroute_learning_reference(
        database_path,
        enroute_product_id="necklaces:demo",
        enroute_category="necklaces",
        enroute_title="Demo Necklace",
        enroute_handle="demo-necklace",
        product_dir="/tmp/enroute",
        image_path="/tmp/enroute/02.jpg",
        status="learned",
    )
    upsert_enroute_image_analysis(
        database_path,
        enroute_product_id="necklaces:demo",
        enroute_category="necklaces",
        enroute_title="Demo Necklace",
        enroute_handle="demo-necklace",
        image_path="/tmp/enroute/02.jpg",
        analysis_json={"summary": "适合短链。"},
        summary="适合短链。",
    )

    client = TestClient(control_api.app)
    response = client.delete("/api/enroute-learning")

    assert response.status_code == 200
    assert response.json()["deleted_count"] == 1
    assert response.json()["reference_deleted_count"] == 1
    assert response.json()["total_after"] == 0
    assert response.json()["message"] == (
        "已清理 1 条 Enroute 逆向分析缓存，1 条学习参考记录。"
    )
    assert client.get("/api/enroute-learning").json()["total"] == 0
    assert len(load_model_profiles(database_path)) > 0
