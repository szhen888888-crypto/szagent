"""Wearing image generation preparation."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageDraw, ImageFont

from productv2.image_generation import get_image_generator, image_file_to_data_url
from productv2.models import CandidateProduct
from productv2.prompt_loader import load_latest_prompt_text, render_prompt_template
from productv2.workflow_logging import WorkflowRunLogger


WEARING_IMAGE_PROMPT_DIR = "wearing/generate_wearing_image"


def generate_wearing_image(
    candidate: CandidateProduct,
    size_reference_result: dict[str, Any],
    enroute_analysis_result: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
    logger: WorkflowRunLogger | None = None,
    attempt: int = 1,
    database_path: str | Path | None = None,
) -> dict[str, Any]:
    """Generate a wearing image from marked product references and style analysis."""

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
    prompt = build_wearing_image_prompt(
        candidate,
        enroute_analysis_result or {},
    )
    selected_model_profile = _selected_model_profile(enroute_analysis_result or {})
    enroute_reference_image_path = str(
        (enroute_analysis_result or {}).get("reference_image_path") or ""
    )
    input_images = [
        str(marked_main_image_path),
        str(marked_size_reference_image_path),
    ]
    if selected_model_profile.get("image_path"):
        input_images.append(str(selected_model_profile["image_path"]))

    prepared_result = {
        "product_id": candidate.product_id,
        "platform": candidate.platform,
        "size_reference_image_numbers": size_reference_result.get("image_numbers", []),
        "marked_main_image_path": str(marked_main_image_path),
        "marked_size_reference_image_path": str(marked_size_reference_image_path),
        "enroute_reference_image_path": enroute_reference_image_path,
        "selected_model_profile": selected_model_profile,
        "input_images": input_images,
        "prompt": prompt,
    }

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
        **prepared_result,
        "status": "ok",
        "reason": "wearing_image_generated",
        "generated_image_path": str(generated_image_path),
        "generated_image_url": generation_result.urls[0],
        "image_generation": generation_summary,
        "attempt": attempt,
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


def build_wearing_image_prompt(
    candidate: CandidateProduct,
    enroute_analysis_result: dict[str, Any],
) -> str:
    """Build a prompt from reverse analysis and marked product references."""

    analysis = enroute_analysis_result.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}
    summary = str(enroute_analysis_result.get("summary") or analysis.get("summary") or "")
    selected_model_profile = _selected_model_profile(enroute_analysis_result)

    selected_model_profile_block = ""
    if selected_model_profile:
        selected_model_profile_block = "\n".join(
            [
                "选定固定模特：",
                json.dumps(selected_model_profile, ensure_ascii=False, indent=2),
            ],
        )
    return render_prompt_template(
        load_latest_prompt_text(WEARING_IMAGE_PROMPT_DIR),
        {
            "product_id": candidate.product_id,
            "platform": candidate.platform,
            "summary": summary,
            "selected_model_profile_block": selected_model_profile_block,
            "analysis_json": json.dumps(analysis, ensure_ascii=False, indent=2),
        },
    )


def _selected_model_profile(enroute_analysis_result: dict[str, Any]) -> dict[str, Any]:
    analysis = enroute_analysis_result.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}
    selected = analysis.get("selected_model_profile")
    if not isinstance(selected, dict):
        return {}
    return {
        "profile_key": str(selected.get("profile_key") or ""),
        "name": str(selected.get("name") or ""),
        "image_path": str(selected.get("image_path") or ""),
        "reason": str(selected.get("reason") or ""),
    }


def _label_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("Arial Unicode.ttf", size=size)
    except OSError:
        try:
            return ImageFont.truetype("Arial.ttf", size=size)
        except OSError:
            return ImageFont.load_default(size=size)
