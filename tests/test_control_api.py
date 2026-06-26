from fastapi.testclient import TestClient

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


def test_control_api_reports_external_langgraph_server(monkeypatch) -> None:
    monkeypatch.setattr(control_api, "_langgraph_online", lambda api_url: True)
    monkeypatch.setattr(control_api, "_current_managed_process", lambda: None)

    client = TestClient(control_api.app)
    response = client.post("/api/server/start", json={"port": 2024})

    assert response.status_code == 200
    assert response.json()["online"] is True
    assert response.json()["managed"] is False
    assert "不是由当前控制台进程托管" in response.json()["message"]


def test_control_api_resume_requires_payload() -> None:
    client = TestClient(control_api.app)
    response = client.post(
        "/api/threads/thread-1/resume",
        json={"resume": None},
    )

    assert response.status_code == 400


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
