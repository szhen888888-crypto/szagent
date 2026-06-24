"""Global image generation client."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from productv2.config import Settings


class ImageGenerationResult(BaseModel):
    id: str
    status: str
    urls: list[str] = Field(default_factory=list)
    progress: int | None = None
    error: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class ImageGenerationRequest:
    prompt: str
    images: list[str] = field(default_factory=list)
    aspect_ratio: str | None = None
    model: str | None = None
    reply_type: str | None = None


class ImageGenerationClient:
    """Client for the configured Grsai image generation API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def generate(
        self,
        prompt: str,
        images: list[str] | None = None,
        aspect_ratio: str | None = None,
        model: str | None = None,
        wait: bool = True,
    ) -> ImageGenerationResult:
        request = ImageGenerationRequest(
            prompt=prompt,
            images=images or [],
            aspect_ratio=aspect_ratio,
            model=model,
        )
        result = self.create(request)
        if wait and result.status == "running":
            return self.poll(result.id)
        return result

    def create(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        payload = self._build_payload(request)
        response = self._request_with_retries(
            "POST",
            self.generate_url,
            json=payload,
        )
        return parse_image_generation_response(response.json())

    def poll(self, task_id: str) -> ImageGenerationResult:
        deadline = time.monotonic() + self.settings.image_generation_poll_timeout
        result = self.get_result(task_id)
        while result.status == "running":
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Image generation task timed out: {task_id}")
            time.sleep(self.settings.image_generation_poll_interval)
            result = self.get_result(task_id)
        return result

    def get_result(self, task_id: str) -> ImageGenerationResult:
        response = self._request_with_retries(
            "GET",
            self.result_url,
            params={"id": task_id},
        )
        return parse_image_generation_response(response.json())

    @property
    def generate_url(self) -> str:
        return f"{_normalize_base_url(self.settings.image_generation_api_base)}/v1/api/generate"

    @property
    def result_url(self) -> str:
        return f"{_normalize_base_url(self.settings.image_generation_api_base)}/v1/api/result"

    def _build_payload(self, request: ImageGenerationRequest) -> dict[str, Any]:
        return {
            "model": request.model or self.settings.image_generation_model,
            "prompt": request.prompt,
            "images": request.images,
            "aspectRatio": request.aspect_ratio
            or self.settings.image_generation_aspect_ratio,
            "replyType": request.reply_type or self.settings.image_generation_reply_type,
        }

    def _request_with_retries(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        api_key = (
            self.settings.image_generation_api_key.get_secret_value()
            if self.settings.image_generation_api_key
            else None
        )
        if not api_key:
            raise ValueError("IMAGE_GENERATION_API_KEY is required")

        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {api_key}"
        if method.upper() == "POST":
            headers.setdefault("Content-Type", "application/json")

        attempts = max(1, self.settings.image_generation_max_retries + 1)
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                with httpx.Client(
                    timeout=self.settings.image_generation_timeout,
                    follow_redirects=True,
                ) as client:
                    response = client.request(method, url, headers=headers, **kwargs)
                _raise_for_http_error(response)
                return response
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if attempt == attempts - 1 or not _is_retryable_status(
                    exc.response.status_code
                ):
                    raise
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt == attempts - 1:
                    raise
        raise RuntimeError("Image generation request failed") from last_exc


def get_image_generator(settings: Settings | None = None) -> ImageGenerationClient:
    return ImageGenerationClient(settings=settings)


def parse_image_generation_response(payload: dict[str, Any]) -> ImageGenerationResult:
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    urls = [
        item["url"]
        for item in results
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    ]
    return ImageGenerationResult(
        id=str(payload.get("id") or ""),
        status=str(payload.get("status") or ""),
        urls=urls,
        progress=payload.get("progress")
        if isinstance(payload.get("progress"), int)
        else None,
        error=str(payload.get("error") or ""),
        raw=payload,
    )


def image_file_to_data_url(path: str | Path) -> str:
    import base64

    image_path = Path(path)
    suffix = image_path.suffix.lower()
    mime_type = "image/png" if suffix == ".png" else "image/jpeg"
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _normalize_base_url(api_base: str) -> str:
    base = api_base.rstrip("/")
    for suffix in ("/v1/api/generate", "/v1/api/result", "/v1/api", "/v1"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return base.rstrip("/")


def _raise_for_http_error(response: httpx.Response) -> None:
    if not response.is_error:
        return
    body = response.text.strip()
    if len(body) > 500:
        body = f"{body[:500]}..."
    message = f"Image generation request failed with HTTP {response.status_code}"
    if body:
        message = f"{message}: {body}"
    raise httpx.HTTPStatusError(
        message,
        request=response.request,
        response=response,
    )


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 429, 500, 502, 503, 504}
