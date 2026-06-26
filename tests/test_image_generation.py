from productv2.config import Settings
from productv2.image_generation import ImageGenerationClient
from productv2.image_generation import ImageGenerationRequest
from productv2.image_generation import parse_image_generation_response
from productv2.workflow_logging import WorkflowRunLogger


def test_image_generation_client_builds_grsai_payload_and_urls() -> None:
    client = ImageGenerationClient(
        Settings(
            image_generation_api_key="sk-test",
            image_generation_api_base="https://example.test/v1/api",
            image_generation_model="gpt-image-2",
            image_generation_aspect_ratio="1024x1024",
            image_generation_reply_type="json",
        )
    )

    payload = client._build_payload(
        ImageGenerationRequest(
            prompt="生成产品佩戴图",
            images=["https://example.test/ref.jpg"],
        )
    )

    assert client.generate_url == "https://example.test/v1/api/generate"
    assert client.result_url == "https://example.test/v1/api/result"
    assert payload == {
        "model": "gpt-image-2",
        "prompt": "生成产品佩戴图",
        "images": ["https://example.test/ref.jpg"],
        "aspectRatio": "1024x1024",
        "replyType": "json",
    }


def test_parse_image_generation_response_extracts_urls() -> None:
    result = parse_image_generation_response(
        {
            "id": "task-1",
            "status": "succeeded",
            "progress": 100,
            "results": [{"url": "https://example.test/out.png"}],
        }
    )

    assert result.id == "task-1"
    assert result.status == "succeeded"
    assert result.progress == 100
    assert result.urls == ["https://example.test/out.png"]


def test_image_generation_generate_polls_running_task(monkeypatch) -> None:
    client = ImageGenerationClient(Settings(image_generation_api_key="sk-test"))
    calls = []

    def fake_create(request):
        calls.append(("create", request.prompt))
        return parse_image_generation_response({"id": "task-1", "status": "running"})

    def fake_poll(task_id, database_path=None):
        calls.append(("poll", task_id))
        return parse_image_generation_response(
            {
                "id": task_id,
                "status": "succeeded",
                "results": [{"url": "https://example.test/out.png"}],
            }
        )

    monkeypatch.setattr(client, "create", fake_create)
    monkeypatch.setattr(client, "poll", fake_poll)

    result = client.generate("生成产品佩戴图")

    assert calls == [("create", "生成产品佩戴图"), ("poll", "task-1")]
    assert result.status == "succeeded"
    assert result.urls == ["https://example.test/out.png"]


def test_image_generation_client_logs_raw_input_output(monkeypatch, tmp_path) -> None:
    logger = WorkflowRunLogger(tmp_path, run_id="image-ai-log")
    client = ImageGenerationClient(
        Settings(
            image_generation_api_key="sk-test",
            image_generation_api_base="https://example.test",
            image_generation_model="gpt-image-2",
            productv2_database_path=tmp_path / "locks.db",
        ),
        logger=logger,
    )

    class FakeResponse:
        is_error = False
        status_code = 200

        def json(self):
            return {
                "id": "task-1",
                "status": "succeeded",
                "results": [{"url": "https://example.test/out.png"}],
            }

    def fake_request_with_retries(method, url, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(client, "_request_with_retries", fake_request_with_retries)

    result = client.generate(
        "生成产品佩戴图",
        images=["https://example.test/ref.jpg"],
        wait=False,
    )

    assert result.status == "succeeded"
    log_text = logger.path.read_text(encoding="utf-8")
    assert "事件：图片 AI 原始输入" in log_text
    assert "事件：图片 AI 原始输出" in log_text
    assert "- 调用上下文 (request_context): image_generation_create" in log_text
    assert "- 原始请求数据 (raw_payload):" in log_text
    assert "- 提示词 (prompt): 生成产品佩戴图" in log_text
    assert "- images:" in log_text
    assert "https://example.test/ref.jpg" in log_text
    assert "- 原始响应 JSON (raw_response_json):" in log_text
    assert "https://example.test/out.png" in log_text


def test_image_generation_create_uses_ai_call_lock_cache(monkeypatch, tmp_path) -> None:
    client = ImageGenerationClient(
        Settings(
            image_generation_api_key="sk-test",
            image_generation_api_base="https://example.test",
            image_generation_model="gpt-image-2",
            productv2_database_path=tmp_path / "locks.db",
        )
    )
    calls = []

    class FakeResponse:
        is_error = False
        status_code = 200

        def json(self):
            return {
                "id": "task-1",
                "status": "succeeded",
                "results": [{"url": "https://example.test/out.png"}],
            }

    def fake_request_with_retries(method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr(client, "_request_with_retries", fake_request_with_retries)
    request = ImageGenerationRequest(
        prompt="生成产品佩戴图",
        images=["https://example.test/ref.jpg"],
    )

    first = client.create(request)
    second = client.create(request)

    assert first.id == "task-1"
    assert second.id == "task-1"
    assert len(calls) == 1
    assert calls[0]["kwargs"]["max_attempts"] == 1


def test_image_generation_generate_uses_async_reply_and_result_polling(
    monkeypatch,
    tmp_path,
) -> None:
    client = ImageGenerationClient(
        Settings(
            image_generation_api_key="sk-test",
            image_generation_api_base="https://example.test",
            image_generation_model="gpt-image-2",
            image_generation_reply_type="async",
            image_generation_poll_interval=0.01,
            productv2_database_path=tmp_path / "locks.db",
        )
    )
    calls = []

    class FakeResponse:
        is_error = False
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    def fake_request_with_retries(method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        if method == "POST":
            assert kwargs["json"]["replyType"] == "async"
            return FakeResponse({"id": "task-1", "status": "running", "progress": 0})
        if len([call for call in calls if call["method"] == "GET"]) == 1:
            return FakeResponse({"id": "task-1", "status": "running", "progress": 50})
        return FakeResponse(
            {
                "id": "task-1",
                "status": "succeeded",
                "progress": 100,
                "results": [{"url": "https://example.test/out.png"}],
            }
        )

    monkeypatch.setattr(client, "_request_with_retries", fake_request_with_retries)

    result = client.generate("生成产品佩戴图", wait=True)

    assert result.status == "succeeded"
    assert result.urls == ["https://example.test/out.png"]
    assert [call["method"] for call in calls] == ["POST", "GET", "GET"]


def test_image_generation_poll_reclaims_stale_lock(monkeypatch, tmp_path) -> None:
    database_path = tmp_path / "locks.db"
    task_id = "task-1"
    client = ImageGenerationClient(
        Settings(
            image_generation_api_key="sk-test",
            image_generation_api_base="https://example.test",
            image_generation_poll_timeout=0.01,
            image_generation_poll_interval=0.01,
            productv2_database_path=database_path,
        )
    )
    calls = []

    class FakeResponse:
        is_error = False
        status_code = 200

        def json(self):
            return {
                "id": task_id,
                "status": "succeeded",
                "progress": 100,
                "results": [{"url": "https://example.test/out.png"}],
            }

    def fake_request_with_retries(method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        return FakeResponse()

    monkeypatch.setattr(client, "_request_with_retries", fake_request_with_retries)

    first = client.poll(task_id, database_path=database_path)
    second = client.poll(task_id, database_path=database_path)

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    assert second.urls == ["https://example.test/out.png"]
    assert [call["method"] for call in calls] == ["GET"]
