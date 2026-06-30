"""Wearing image generation preparation."""

from __future__ import annotations

import base64
import json
from pathlib import Path
import shutil
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageDraw, ImageFont

from productv2.config import Settings
from productv2.image_generation import get_image_generator, image_file_to_data_url
from productv2.models import CandidateProduct
from productv2.prompt_loader import load_latest_prompt_sections, render_prompt_template
from productv2.vision import (
    _image_file_to_data_url,
    _log_llm_request,
    _log_llm_response,
    request_responses_stream_text,
)
from productv2.workflow_logging import WorkflowRunLogger


WEARING_PROMPT_COMPILER_DIR = "wearing/compile_generation_prompt"
WEARING_PROMPT_COMPILER_MAX_OUTPUT_CHARS = 5000
WEARING_PROMPT_COMPILER_MAX_OUTPUT_TOKENS = 1600


def generate_wearing_image(
    candidate: CandidateProduct,
    wearing_generation_prompt_result: dict[str, Any],
    output_dir: str | Path | None = None,
    logger: WorkflowRunLogger | None = None,
    attempt: int = 1,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    """Generate a wearing image from a compiled prompt and prepared inputs."""

    prompt = str(wearing_generation_prompt_result.get("prompt") or "").strip()
    input_images = [
        str(image_path)
        for image_path in wearing_generation_prompt_result.get("input_images", [])
        if str(image_path).strip()
    ]
    if not prompt or not input_images:
        return {
            "status": "skipped",
            "reason": "compiled_prompt_or_input_images_missing",
            "product_id": candidate.product_id,
            "platform": candidate.platform,
        }

    active_output_dir = (
        Path(output_dir)
        if output_dir is not None
        else Path(input_images[0]).parent.parent
    )

    missing_input_images = [
        image_path for image_path in input_images if not Path(image_path).is_file()
    ]
    if missing_input_images:
        raise FileNotFoundError(
            "Wearing image generation input images are missing: "
            + ", ".join(missing_input_images)
        )

    generator = get_image_generator(logger=logger)
    generation_kwargs: dict[str, Any] = {
        "prompt": prompt,
        "images": [image_file_to_data_url(image_path) for image_path in input_images],
        "wait": True,
    }
    if database_path is not None:
        generation_kwargs["database_path"] = database_path
    generation_result = generator.generate(**generation_kwargs)

    generation_summary = {
        "id": generation_result.id,
        "status": generation_result.status,
        "progress": generation_result.progress,
        "urls": generation_result.urls,
        "error": generation_result.error,
    }
    if generation_result.status.lower() not in {
        "succeeded",
        "success",
        "completed",
        "done",
    }:
        raise RuntimeError(
            "Image generation did not succeed: "
            + json.dumps(generation_summary, ensure_ascii=False)
        )
    if not generation_result.urls:
        raise RuntimeError(
            "Image generation returned no URL: "
            + json.dumps(generation_summary, ensure_ascii=False)
        )

    generated_image_path = save_generated_wearing_image(
        generation_result.urls[0],
        active_output_dir,
        attempt=attempt,
        timeout=generator.settings.image_generation_timeout,
    )

    return {
        **wearing_generation_prompt_result,
        "status": "ok",
        "reason": "wearing_image_generated",
        "product_id": candidate.product_id,
        "platform": candidate.platform,
        "generated_image_path": str(generated_image_path),
        "generated_image_url": generation_result.urls[0],
        "image_generation": generation_summary,
        "attempt": attempt,
    }


def compile_wearing_generation_prompt(
    candidate: CandidateProduct,
    size_reference_result: dict[str, Any],
    enroute_profile: dict[str, Any],
    model_profile: dict[str, Any],
    *,
    selection_reason: str = "",
    output_dir: str | Path | None = None,
    logger: WorkflowRunLogger | None = None,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    """Prepare inputs and compile the final image-generation prompt."""

    selected_images = size_reference_result.get("selected_images", {})
    if not isinstance(selected_images, dict):
        selected_images = {}

    main_image = selected_images.get("main_image", {})
    size_reference_image = selected_images.get("size_reference_image", {})
    main_image_path = str(main_image.get("path") or "")
    size_reference_image_path = str(size_reference_image.get("path") or "")

    if not main_image_path or not size_reference_image_path:
        return {
            "status": "skipped",
            "reason": "selected_main_or_size_reference_missing",
            "product_id": candidate.product_id,
            "platform": candidate.platform,
            "size_reference_image_numbers": size_reference_result.get(
                "image_numbers",
                [],
            ),
        }

    active_output_dir = Path(output_dir) if output_dir is not None else Path(main_image_path).parent
    marked_dir = active_output_dir / "wearing_generation_inputs"
    reset_directory(marked_dir)
    marked_main_image_path = create_labeled_reference_image(
        main_image_path,
        marked_dir / "01_main_image.jpg",
        "01 主图",
    )
    marked_size_reference_image_path = create_labeled_reference_image(
        size_reference_image_path,
        marked_dir / "02_size_reference.jpg",
        "02 尺寸参考图",
    )
    selected_model_profile = _model_profile_payload(model_profile)
    enroute_reference_image_path = str(enroute_profile.get("image_path") or "")
    input_images = [
        str(marked_main_image_path),
        str(marked_size_reference_image_path),
    ]
    if selected_model_profile.get("image_path"):
        input_images.append(str(selected_model_profile["image_path"]))

    missing_input_images = [
        image_path for image_path in input_images if not Path(image_path).is_file()
    ]
    if missing_input_images:
        raise FileNotFoundError(
            "Wearing prompt input images are missing: "
            + ", ".join(missing_input_images)
        )

    prompt = request_compiled_wearing_prompt(
        candidate=candidate,
        enroute_profile=enroute_profile,
        model_profile=selected_model_profile,
        input_images=input_images,
        selection_reason=selection_reason,
        logger=logger,
        database_path=database_path,
    )

    return {
        "status": "ok",
        "reason": "wearing_generation_prompt_compiled",
        "product_id": candidate.product_id,
        "platform": candidate.platform,
        "size_reference_image_numbers": size_reference_result.get("image_numbers", []),
        "marked_main_image_path": str(marked_main_image_path),
        "marked_size_reference_image_path": str(marked_size_reference_image_path),
        "enroute_reference_image_path": enroute_reference_image_path,
        "selected_model_profile": selected_model_profile,
        "input_images": input_images,
        "prompt": prompt,
        "selection_reason": selection_reason,
    }


def save_generated_wearing_image(
    image_url: str,
    output_dir: str | Path,
    attempt: int = 1,
    timeout: float | None = 600.0,
) -> Path:
    """Save one generated wearing image to the product asset directory."""

    active_output_dir = Path(output_dir)
    active_output_dir.mkdir(parents=True, exist_ok=True)

    image_bytes, suffix = _read_generated_image(image_url, timeout=timeout)
    output_stem = f"wearing_image_attempt_{max(1, attempt)}"
    for stale_path in active_output_dir.glob(f"{output_stem}.*"):
        if stale_path.is_file():
            stale_path.unlink()
    output_path = active_output_dir / f"{output_stem}{suffix}"
    output_path.write_bytes(image_bytes)
    return output_path


def reset_directory(path: str | Path) -> Path:
    directory = Path(path)
    if directory.exists():
        if directory.is_dir():
            shutil.rmtree(directory)
        else:
            directory.unlink()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _read_generated_image(
    image_url: str,
    timeout: float | None,
) -> tuple[bytes, str]:
    if image_url.startswith("data:image/") and ";base64," in image_url:
        header, encoded = image_url.split(";base64,", 1)
        mime_type = header.removeprefix("data:")
        return base64.b64decode(encoded), _suffix_for_mime_type(mime_type)

    response = httpx.get(image_url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
    suffix = _suffix_for_mime_type(content_type)
    if suffix == ".jpg":
        suffix = _suffix_from_url(image_url) or suffix
    return response.content, suffix


def _suffix_for_mime_type(mime_type: str) -> str:
    normalized = mime_type.lower()
    if normalized == "image/png":
        return ".png"
    if normalized == "image/webp":
        return ".webp"
    if normalized in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    return ".jpg"


def _suffix_from_url(image_url: str) -> str:
    suffix = Path(urlparse(image_url).path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ""


def create_labeled_reference_image(
    source_path: str | Path,
    output_path: str | Path,
    label: str,
) -> Path:
    """Create a copy with a white bottom bar and visible label text."""

    source = Path(source_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as image:
        prepared = image.convert("RGB")
        bar_height = max(64, prepared.height // 10)
        canvas = Image.new(
            "RGB",
            (prepared.width, prepared.height + bar_height),
            "white",
        )
        canvas.paste(prepared, (0, 0))
        draw = ImageDraw.Draw(canvas)
        font = _label_font(max(22, bar_height // 3))
        text_box = draw.textbbox((0, 0), label, font=font)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        draw.text(
            (
                max(16, (prepared.width - text_width) // 2),
                prepared.height + (bar_height - text_height) // 2,
            ),
            label,
            fill="black",
            font=font,
        )
        canvas.save(output, format="JPEG", quality=92, optimize=True)
    return output


def request_compiled_wearing_prompt(
    *,
    candidate: CandidateProduct,
    enroute_profile: dict[str, Any],
    model_profile: dict[str, Any],
    input_images: list[str],
    selection_reason: str = "",
    logger: WorkflowRunLogger | None = None,
    database_path: str | Path | None = None,
) -> str:
    """Use the configured LLM to compile the final image-generation prompt."""

    active_settings = Settings()
    payload = build_wearing_prompt_compiler_payload(
        candidate,
        enroute_profile,
        model_profile,
        input_images=input_images,
        selection_reason=selection_reason,
        settings=active_settings,
    )
    _log_llm_request(
        logger,
        context="wearing_generation_prompt_compiler",
        payload={"raw_payload": payload},
    )
    text = request_responses_stream_text(
        active_settings,
        payload,
        logger=logger,
        request_context="wearing_generation_prompt_compiler",
    )
    _log_llm_response(
        logger,
        context="wearing_generation_prompt_compiler",
        text=text,
    )
    return trim_compiled_wearing_prompt(text)


def build_wearing_prompt_compiler_payload(
    candidate: CandidateProduct,
    enroute_profile: dict[str, Any],
    model_profile: dict[str, Any],
    *,
    input_images: list[str] | None = None,
    selection_reason: str = "",
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or Settings()
    sections = load_latest_prompt_sections(WEARING_PROMPT_COMPILER_DIR)
    system_prompt = render_prompt_template(
        sections.system,
        {
            "product_id": candidate.product_id,
            "platform": candidate.platform,
            "model_profile_json": json.dumps(
                model_profile,
                ensure_ascii=False,
                indent=2,
            ),
            "enroute_profile_json": json.dumps(
                enroute_profile,
                ensure_ascii=False,
                indent=2,
            ),
            "selection_reason": selection_reason,
        },
    )
    return {
        "model": active_settings.openai_model,
        "max_output_tokens": WEARING_PROMPT_COMPILER_MAX_OUTPUT_TOKENS,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": sections.user},
                    *[
                        {
                            "type": "input_image",
                            "image_url": _image_file_to_data_url(Path(image_path)),
                            "detail": "high",
                        }
                        for image_path in (input_images or [])
                    ],
                ],
            },
        ],
        "stream": True,
    }


def trim_compiled_wearing_prompt(text: str) -> str:
    prompt = text.strip()
    if len(prompt) <= WEARING_PROMPT_COMPILER_MAX_OUTPUT_CHARS:
        return prompt
    return prompt[:WEARING_PROMPT_COMPILER_MAX_OUTPUT_CHARS].rstrip()


def _model_profile_payload(selected: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_key": str(selected.get("profile_key") or ""),
        "name": str(selected.get("name") or ""),
        "summary": str(selected.get("summary") or ""),
        "image_path": str(selected.get("image_path") or ""),
        "metadata_path": str(selected.get("metadata_path") or ""),
    }


def _label_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("Arial Unicode.ttf", size=size)
    except OSError:
        try:
            return ImageFont.truetype("Arial.ttf", size=size)
        except OSError:
            return ImageFont.load_default(size=size)
