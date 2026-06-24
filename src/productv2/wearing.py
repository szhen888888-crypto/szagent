"""Wearing image generation preparation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from productv2.models import CandidateProduct


def generate_wearing_image(
    candidate: CandidateProduct,
    size_reference_result: dict[str, Any],
    enroute_analysis_result: dict[str, Any] | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Prepare marked references and prompt for the wearing image generation step."""

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

    return {
        "status": "reserved",
        "reason": "wearing_image_generation_not_implemented",
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

    lines = [
            "生成一张 inyourday 风格的首饰佩戴图。",
            "参考图 01 标记为主图：必须将 01 中的同一件产品佩戴在模特脖子上，保持产品结构、颜色、材质、吊坠/链条关系和可识别细节一致。",
            "参考图 02 标记为尺寸参考图：必须以 02 的真实佩戴比例为准，保持产品在脖子、锁骨和胸前区域的尺寸一致，不要放大或缩小产品。",
            "如果提供了模特三视图参考图，必须使用该固定模特的身份、五官、肤色、体型和三维比例；三视图只用于模特一致性，不改变产品。",
            "模特与画面风格参考以下逆向 JSON，只迁移模特选择、衣物风格、场景感觉和拍摄方式，不复制参考图中的产品。",
            f"商品信息：product_id={candidate.product_id}, platform={candidate.platform}",
            f"逆向摘要：{summary}",
    ]
    if selected_model_profile:
        lines.extend(
            [
                "选定固定模特：",
                json.dumps(selected_model_profile, ensure_ascii=False, indent=2),
            ]
        )
    lines.extend(
        [
            "逆向 JSON：",
            json.dumps(analysis, ensure_ascii=False, indent=2),
            "最终画面要求：产品清晰可辨但自然融入穿搭；保证产品一致性、尺寸一致性、佩戴位置合理。",
        ]
    )
    return "\n".join(lines)


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
