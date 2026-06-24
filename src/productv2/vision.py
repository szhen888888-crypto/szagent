"""LLM vision checks for generated product image collages."""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

import httpx
from pydantic import BaseModel, Field

from productv2.config import Settings
from productv2.workflow_logging import (
    WorkflowRunLogger,
    describe_file_for_log,
    prepare_ai_log_data,
)


T = TypeVar("T")


class EmptyLLMResponseError(RuntimeError):
    """Raised when the streaming LLM endpoint returns no text."""


class SizeReferenceDetection(BaseModel):
    can_judge_size: bool = False
    image_numbers: list[int] = Field(default_factory=list)
    size_reference_image_number: int | None = None
    main_image_number: int | None = None
    reason: str = ""


SIZE_REFERENCE_PROMPT = """
你正在检查一张由多张商品图合并成的编号拼图。每张子图左上角有白色数字编号。

任务：
1. 判断是否存在可以通过人体参照判断产品尺寸、比例或佩戴效果的子图。
2. 返回一个最适合作为尺寸参考图的子图编号：优先选择模特佩戴、人体局部、手、脖子、耳朵、手腕等参照最清楚的图。
3. 返回一个与该尺寸参考图对应的产品主图编号：优先选择同一产品的纯产品图、PDP 封面图、干净背景、结构/材质/颜色清楚的图，不要选择人体佩戴图作为主图，除非没有纯产品图。
4. image_numbers 返回所有能用于尺寸/比例判断的子图编号。
5. 如果没有人体、手、脖子、耳朵、手腕、模特佩戴等参照，则 can_judge_size=false、image_numbers=[]、size_reference_image_number=null；仍然尽量返回 main_image_number。
6. 只输出 JSON，不要输出 Markdown。

JSON 格式：
{
  "can_judge_size": true,
  "image_numbers": [1, 3],
  "size_reference_image_number": 1,
  "main_image_number": 2,
  "reason": "简短中文原因"
}
""".strip()


def detect_size_reference_images(
    collage_path: str | Path,
    settings: Settings | None = None,
    model: Any | None = None,
    logger: WorkflowRunLogger | None = None,
) -> SizeReferenceDetection:
    """Use OpenAI Responses streaming to detect images with human size reference."""

    path = Path(collage_path)
    if model is not None:
        _log_llm_request(
            logger,
            context="size_reference_detection_model",
            payload={
                "image_file": describe_file_for_log(path),
                "raw_messages": _vision_messages(path),
            },
        )
        response = model.invoke(_vision_messages(path))
        text = _message_text(response)
        _log_llm_response(
            logger,
            context="size_reference_detection_model",
            text=text,
        )
        parsed = parse_size_reference_detection(text)
        _log_llm_parsed_output(
            logger,
            context="size_reference_detection_model",
            parsed=parsed.model_dump(),
        )
        return parsed

    active_settings = settings or Settings()
    image_url = _image_file_to_data_url(path)
    payload = build_responses_vision_payload(active_settings, image_url)
    _log_llm_request(
        logger,
        context="size_reference_detection",
        payload={
            "image_file": describe_file_for_log(path),
            "raw_payload": payload,
        },
    )
    return request_responses_stream_parsed(
        active_settings,
        payload,
        parse_size_reference_detection,
        logger=logger,
        request_context="size_reference_detection",
    )


def build_responses_vision_payload(settings: Settings, image_url: str) -> dict[str, Any]:
    """Build an OpenAI Responses vision request payload."""

    return {
        "model": settings.openai_model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": SIZE_REFERENCE_PROMPT},
                    {
                        "type": "input_image",
                        "image_url": image_url,
                        "detail": "high",
                    },
                ],
            }
        ],
        "stream": True,
    }


def request_responses_stream_text(
    settings: Settings,
    payload: dict[str, Any],
    max_retries: int | None = None,
    logger: WorkflowRunLogger | None = None,
    request_context: str = "responses_stream",
) -> str:
    """Call the Responses streaming endpoint with raw HTTP/SSE."""

    api_key = (
        settings.openai_api_key.get_secret_value()
        if settings.openai_api_key
        else None
    )
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required for LLM vision detection")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }
    retry_count = settings.openai_max_retries if max_retries is None else max_retries
    attempts = max(1, retry_count + 1)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            _log_llm_request(
                logger,
                context=request_context,
                payload={
                    "attempt": attempt + 1,
                    "endpoint": responses_endpoint_url(settings.openai_api_base),
                    "raw_payload": payload,
                },
            )
            with httpx.stream(
                "POST",
                responses_endpoint_url(settings.openai_api_base),
                headers=headers,
                json=payload,
                timeout=settings.openai_timeout,
            ) as response:
                _raise_for_http_error(response)
                text = collect_responses_stream_text(response.iter_lines())
                _log_llm_response(
                    logger,
                    context=request_context,
                    text=text,
                    attempt=attempt + 1,
                )
                if not text.strip():
                    raise EmptyLLMResponseError("Responses API returned empty text")
                return text
        except httpx.HTTPStatusError as exc:
            _log_llm_error(logger, request_context, exc, attempt + 1)
            status_code = exc.response.status_code
            if attempt == attempts - 1 or not _is_retryable_status(status_code):
                raise
            last_error = exc
        except httpx.TransportError as exc:
            _log_llm_error(logger, request_context, exc, attempt + 1)
            if attempt == attempts - 1:
                raise
        except EmptyLLMResponseError as exc:
            _log_llm_error(logger, request_context, exc, attempt + 1)
            if attempt == attempts - 1:
                raise
            last_error = exc
    raise RuntimeError("Responses API stream ended before a response was returned") from (
        last_error
    )


def request_responses_stream_parsed(
    settings: Settings,
    payload: dict[str, Any],
    parser: Callable[[str], T],
    logger: WorkflowRunLogger | None = None,
    request_context: str = "responses_stream",
) -> T:
    """Call Responses streaming and retry empty or unparsable model output."""

    attempts = max(1, settings.openai_max_retries + 1)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            text = request_responses_stream_text(
                settings,
                payload,
                max_retries=0,
                logger=logger,
                request_context=request_context,
            )
            parsed = parser(text)
            _log_llm_parsed_output(
                logger,
                context=request_context,
                parsed=parsed.model_dump() if hasattr(parsed, "model_dump") else parsed,
            )
            return parsed
        except httpx.HTTPStatusError as exc:
            _log_llm_error(logger, request_context, exc, attempt + 1)
            status_code = exc.response.status_code
            if attempt == attempts - 1 or not _is_retryable_status(status_code):
                raise
            last_error = exc
        except (httpx.TransportError, EmptyLLMResponseError, ValueError) as exc:
            _log_llm_error(logger, request_context, exc, attempt + 1)
            if attempt == attempts - 1:
                raise
            last_error = exc
    raise RuntimeError("Responses API output could not be parsed") from last_error


def responses_endpoint_url(api_base: str) -> str:
    """Normalize an OpenAI-compatible base URL to the Responses endpoint."""

    base = api_base.rstrip("/")
    if base.endswith("/responses"):
        return base
    if base.endswith("/v1"):
        return f"{base}/responses"
    return f"{base}/v1/responses"


def collect_responses_stream_text(stream: Iterable[str | bytes]) -> str:
    """Collect text deltas from OpenAI Responses SSE lines."""

    chunks: list[str] = []
    data_lines: list[str] = []
    for raw_line in stream:
        line = _stream_line_to_text(raw_line).rstrip("\r\n")
        if not line:
            _collect_sse_data_event(data_lines, chunks)
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").lstrip())
        elif line.startswith("{"):
            data_lines.append(line)
    _collect_sse_data_event(data_lines, chunks)
    return "".join(chunks)


def parse_size_reference_detection(text: str) -> SizeReferenceDetection:
    payload = _extract_json_object(text)
    detection = SizeReferenceDetection.model_validate(payload)
    detection.image_numbers = sorted(
        {number for number in detection.image_numbers if number > 0}
    )
    if not _positive_int(detection.size_reference_image_number):
        detection.size_reference_image_number = (
            detection.image_numbers[0] if detection.image_numbers else None
        )
    if not _positive_int(detection.main_image_number):
        detection.main_image_number = None
    detection.can_judge_size = bool(detection.image_numbers) and detection.can_judge_size
    if not detection.can_judge_size:
        detection.size_reference_image_number = None
    return detection


def _image_file_to_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    suffix = path.suffix.lower()
    mime_type = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime_type};base64,{encoded}"


def _vision_messages(path: Path) -> list[Any]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": SIZE_REFERENCE_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": _image_file_to_data_url(path), "detail": "high"},
                },
            ],
        }
    ]


def _message_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _positive_int(value: int | None) -> bool:
    return isinstance(value, int) and value > 0


def _raise_for_http_error(response: httpx.Response) -> None:
    if not response.is_error:
        return
    body = response.read().decode("utf-8", errors="replace").strip()
    if len(body) > 500:
        body = f"{body[:500]}..."
    message = f"Responses API request failed with HTTP {response.status_code}"
    if body:
        message = f"{message}: {body}"
    raise httpx.HTTPStatusError(
        message,
        request=response.request,
        response=response,
    )


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 429, 500, 502, 503, 504}


def _stream_line_to_text(line: str | bytes) -> str:
    if isinstance(line, bytes):
        return line.decode("utf-8", errors="replace")
    return line


def _collect_sse_data_event(data_lines: list[str], chunks: list[str]) -> None:
    if not data_lines:
        return
    data = "\n".join(data_lines).strip()
    data_lines.clear()
    if not data or data == "[DONE]":
        return
    event = json.loads(data)
    event_type = event.get("type", "")
    if event_type == "response.output_text.delta":
        chunks.append(str(event.get("delta", "")))
    elif event_type == "response.output_text.done" and not chunks:
        chunks.append(str(event.get("text", "")))
    elif event_type == "response.completed" and not chunks:
        chunks.append(_extract_completed_response_text(event))


def _extract_completed_response_text(event: dict[str, Any]) -> str:
    response = event.get("response")
    if not isinstance(response, dict):
        return ""
    output = response.get("output")
    if not isinstance(output, list):
        return ""

    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text")
            if block.get("type") == "output_text" and isinstance(text, str):
                parts.append(text)
    return "".join(parts)


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _log_llm_request(
    logger: WorkflowRunLogger | None,
    *,
    context: str,
    payload: dict[str, Any],
) -> None:
    if logger is None:
        return
    logger.write(
        "llm_request",
        data={
            "request_context": context,
            **prepare_ai_log_data(payload),
        },
    )


def _log_llm_response(
    logger: WorkflowRunLogger | None,
    *,
    context: str,
    text: str,
    attempt: int | None = None,
) -> None:
    if logger is None:
        return
    data: dict[str, Any] = {
        "request_context": context,
        "raw_response_text": text,
    }
    if attempt is not None:
        data["attempt"] = attempt
    logger.write("llm_response", data=data)


def _log_llm_parsed_output(
    logger: WorkflowRunLogger | None,
    *,
    context: str,
    parsed: Any,
) -> None:
    if logger is None:
        return
    logger.write(
        "llm_parsed_output",
        data={
            "request_context": context,
            "parsed_output": prepare_ai_log_data(parsed),
        },
    )


def _log_llm_error(
    logger: WorkflowRunLogger | None,
    context: str,
    exc: Exception,
    attempt: int,
) -> None:
    if logger is None:
        return
    logger.write(
        "llm_error",
        data={
            "request_context": context,
            "attempt": attempt,
            "error_type": type(exc).__name__,
            "error": str(exc),
        },
    )
