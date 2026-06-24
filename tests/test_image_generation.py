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

    def fake_poll(task_id):
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
