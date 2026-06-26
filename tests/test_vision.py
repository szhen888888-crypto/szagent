import json
import sqlite3

import httpx

from productv2.config import Settings
from productv2.vision import build_responses_vision_payload
from productv2.vision import parse_size_reference_detection
from productv2.vision import collect_responses_stream_text
from productv2.vision import request_responses_stream_parsed
from productv2.vision import request_responses_stream_text
from productv2.vision import responses_endpoint_url
from productv2.workflow_logging import WorkflowRunLogger


def test_parse_size_reference_detection_normalizes_numbers() -> None:
    detection = parse_size_reference_detection(
        """
        {
          "can_judge_size": true,
          "image_numbers": [3, 1, 3],
          "size_reference_image_number": 3,
          "main_image_number": 2,
          "reason": "有佩戴图"
        }
        """
    )

    assert detection.can_judge_size is True
    assert detection.image_numbers == [1, 3]
    assert detection.size_reference_image_number == 3
    assert detection.main_image_number == 2
    assert detection.reason == "有佩戴图"


def test_parse_size_reference_detection_requires_numbers() -> None:
    detection = parse_size_reference_detection(
        '{"can_judge_size": true, "image_numbers": [], "reason": "没有人体参照"}'
    )

    assert detection.can_judge_size is False
    assert detection.image_numbers == []
    assert detection.size_reference_image_number is None


def test_parse_size_reference_detection_falls_back_to_first_reference_number() -> None:
    detection = parse_size_reference_detection(
        '{"can_judge_size": true, "image_numbers": [2, 1], "reason": "旧格式"}'
    )

    assert detection.can_judge_size is True
    assert detection.image_numbers == [1, 2]
    assert detection.size_reference_image_number == 1
    assert detection.main_image_number is None


def test_collect_responses_stream_text_reads_sse_delta_events() -> None:
    text = collect_responses_stream_text(
        [
            "event: response.created",
            'data: {"type":"response.created"}',
            "",
            "event: response.output_text.delta",
            "data: "
            + json.dumps(
                {
                    "type": "response.output_text.delta",
                    "delta": '{"can_judge_size":',
                }
            ),
            "",
            b'data: {"type":"response.output_text.delta","delta":"false}"}',
            b"",
            "data: [DONE]",
            "",
        ]
    )

    assert text == '{"can_judge_size":false}'


def test_responses_endpoint_url_normalizes_base_url() -> None:
    assert responses_endpoint_url("https://example.test") == (
        "https://example.test/v1/responses"
    )
    assert responses_endpoint_url("https://example.test/v1") == (
        "https://example.test/v1/responses"
    )
    assert responses_endpoint_url("https://example.test/responses") == (
        "https://example.test/responses"
    )


def test_build_responses_vision_payload_uses_streaming_input_format() -> None:
    settings = Settings(openai_model="gpt-test")

    payload = build_responses_vision_payload(
        settings,
        "data:image/png;base64,fixture",
    )

    assert payload["model"] == "gpt-test"
    assert payload["stream"] is True
    content = payload["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert content[1] == {
        "type": "input_image",
        "image_url": "data:image/png;base64,fixture",
        "detail": "high",
    }


def test_request_responses_stream_text_posts_raw_http_sse(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        is_error = False
        status_code = 200

        def __init__(self) -> None:
            self.request = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def iter_lines(self):
            yield 'data: {"type":"response.output_text.delta","delta":"ok"}'
            yield ""
            yield "data: [DONE]"
            yield ""

    def fake_stream(method, url, headers, json, timeout):
        calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr("productv2.vision.httpx.stream", fake_stream)

    text = request_responses_stream_text(
        Settings(
            openai_api_key="sk-test",
            openai_api_base="https://example.test",
            openai_timeout=12,
        ),
        {"model": "gpt-test", "input": [], "stream": True},
    )

    assert text == "ok"
    assert calls == [
        {
            "method": "POST",
            "url": "https://example.test/v1/responses",
            "headers": {
                "Authorization": "Bearer sk-test",
                "Accept": "text/event-stream",
                "Content-Type": "application/json",
            },
            "json": {"model": "gpt-test", "input": [], "stream": True},
            "timeout": 12,
        }
    ]


def test_request_responses_stream_text_retries_empty_output(monkeypatch) -> None:
    calls = []

    class FakeResponse:
        is_error = False
        status_code = 200

        def __init__(self, text: str) -> None:
            self.request = None
            self.text = text

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def iter_lines(self):
            if self.text:
                yield json.dumps(
                    {
                        "type": "response.output_text.delta",
                        "delta": self.text,
                    }
                )
            yield ""
            yield "data: [DONE]"
            yield ""

    def fake_stream(method, url, headers, json, timeout):
        calls.append({"method": method, "url": url})
        return FakeResponse("" if len(calls) == 1 else "ok")

    monkeypatch.setattr("productv2.vision.httpx.stream", fake_stream)

    text = request_responses_stream_text(
        Settings(
            openai_api_key="sk-test",
            openai_api_base="https://example.test",
            openai_max_retries=2,
        ),
        {"model": "gpt-test", "input": [], "stream": True},
    )

    assert text == "ok"
    assert len(calls) == 2


def test_request_responses_stream_text_falls_back_to_next_provider(
    monkeypatch,
) -> None:
    calls = []

    class FakeResponse:
        def __init__(self, url: str) -> None:
            self.request = httpx.Request("POST", url)
            self.status_code = 500 if "primary" in url else 200
            self.is_error = self.status_code >= 400

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        @property
        def text(self):
            return "server error" if self.is_error else ""

        def read(self):
            return self.text.encode("utf-8")

        def iter_lines(self):
            yield 'data: {"type":"response.output_text.delta","delta":"ok"}'
            yield ""
            yield "data: [DONE]"
            yield ""

    def fake_stream(method, url, headers, json, timeout):
        calls.append(
            {
                "url": url,
                "authorization": headers["Authorization"],
            }
        )
        return FakeResponse(url)

    monkeypatch.setattr("productv2.vision.httpx.stream", fake_stream)

    text = request_responses_stream_text(
        Settings(
            openai_api_key="sk-primary",
            openai_api_base="https://primary.test",
            openai_max_retries=0,
            openai_fallback_providers=(
                '[{"name":"backup","api_base":"https://backup.test",'
                '"api_key":"sk-backup"}]'
            ),
        ),
        {"model": "gpt-test", "input": [], "stream": True},
    )

    assert text == "ok"
    assert calls == [
        {
            "url": "https://primary.test/v1/responses",
            "authorization": "Bearer sk-primary",
        },
        {
            "url": "https://backup.test/v1/responses",
            "authorization": "Bearer sk-backup",
        },
    ]


def test_request_responses_stream_parsed_retries_parse_failure(
    monkeypatch,
    tmp_path,
) -> None:
    calls = []

    class FakeResponse:
        is_error = False
        status_code = 200

        def __init__(self, text: str) -> None:
            self.request = None
            self.text = text

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def iter_lines(self):
            yield json.dumps(
                {
                    "type": "response.output_text.delta",
                    "delta": self.text,
                }
            )
            yield ""
            yield "data: [DONE]"
            yield ""

    def fake_stream(method, url, headers, json, timeout):
        calls.append({"method": method, "url": url})
        text = '{"broken":' if len(calls) == 1 else '{"ok": true}'
        return FakeResponse(text)

    monkeypatch.setattr("productv2.vision.httpx.stream", fake_stream)

    result = request_responses_stream_parsed(
        Settings(
            openai_api_key="sk-test",
            openai_api_base="https://example.test",
            openai_max_retries=2,
            productv2_database_path=tmp_path / "locks.db",
        ),
        {"model": "gpt-test", "input": [], "stream": True},
        json.loads,
    )

    assert result == {"ok": True}
    assert len(calls) == 2


def test_request_responses_stream_parsed_uses_ai_call_lock_cache(
    monkeypatch,
    tmp_path,
) -> None:
    calls = []

    class FakeResponse:
        is_error = False
        status_code = 200
        request = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def iter_lines(self):
            yield json.dumps(
                {
                    "type": "response.output_text.delta",
                    "delta": '{"ok": true}',
                }
            )
            yield ""
            yield "data: [DONE]"
            yield ""

    def fake_stream(method, url, headers, json, timeout):
        calls.append({"method": method, "url": url})
        return FakeResponse()

    monkeypatch.setattr("productv2.vision.httpx.stream", fake_stream)
    settings = Settings(
        openai_api_key="sk-test",
        openai_api_base="https://example.test",
        openai_fallback_providers=(
            '[{"name":"backup","api_base":"https://backup.test",'
            '"api_key":"sk-backup"}]'
        ),
        productv2_database_path=tmp_path / "locks.db",
    )
    payload = {"model": "gpt-test", "input": [], "stream": True}

    first = request_responses_stream_parsed(settings, payload, json.loads)
    second = request_responses_stream_parsed(settings, payload, json.loads)

    assert first == {"ok": True}
    assert second == {"ok": True}
    assert len(calls) == 1
    with sqlite3.connect(tmp_path / "locks.db") as connection:
        request_json = connection.execute(
            """
            SELECT request_json
            FROM ai_call_locks
            WHERE call_type = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            ("llm:responses_stream",),
        ).fetchone()[0]
    request_payload = json.loads(request_json)
    assert request_payload["providers"] == [
        {"name": "primary", "api_base": "https://example.test"},
        {"name": "backup", "api_base": "https://backup.test"},
    ]
    assert "sk-backup" not in request_json


def test_request_responses_stream_logs_raw_input_output(monkeypatch, tmp_path) -> None:
    logger = WorkflowRunLogger(tmp_path, run_id="llm-log")

    class FakeResponse:
        is_error = False
        status_code = 200

        def __init__(self) -> None:
            self.request = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def iter_lines(self):
            yield json.dumps(
                {
                    "type": "response.output_text.delta",
                    "delta": '{"ok": true}',
                }
            )
            yield ""
            yield "data: [DONE]"
            yield ""

    def fake_stream(method, url, headers, json, timeout):
        return FakeResponse()

    monkeypatch.setattr("productv2.vision.httpx.stream", fake_stream)

    result = request_responses_stream_parsed(
        Settings(
            openai_api_key="sk-test",
            openai_api_base="https://example.test",
            productv2_database_path=tmp_path / "locks.db",
        ),
        {"model": "gpt-test", "input": [{"role": "user", "content": "原始提示"}]},
        json.loads,
        logger=logger,
        request_context="fixture_llm",
    )

    assert result == {"ok": True}
    log_text = logger.path.read_text(encoding="utf-8")
    assert "事件：LLM 原始输入" in log_text
    assert "事件：LLM 原始输出" in log_text
    assert "事件：LLM 解析结果" in log_text
    assert "- 调用上下文 (request_context): fixture_llm" in log_text
    assert "- 原始请求数据 (raw_payload):" in log_text
    assert "原始提示" in log_text
    assert "- 原始响应文本 (raw_response_text): {\"ok\": true}" in log_text
    assert "- 解析后输出 (parsed_output):" in log_text
