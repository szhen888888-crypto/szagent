from productv2.config import Settings
from productv2.image_generation import ImageGenerationClient
from productv2.image_generation import ImageGenerationRequest
from productv2.image_generation import parse_image_generation_response


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
