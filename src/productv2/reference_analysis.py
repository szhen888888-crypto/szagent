"""LLM reverse analysis for Enroute wearing references."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from productv2.config import Settings
from productv2.vision import (
    _extract_json_object,
    _image_file_to_data_url,
    _message_text,
    _log_llm_parsed_output,
    _log_llm_request,
    _log_llm_response,
    request_responses_stream_parsed,
)
from productv2.workflow_logging import WorkflowRunLogger, describe_file_for_log


class ModelStyleAnalysis(BaseModel):
    face_style: str = ""
    expression: str = ""
    skin_finish: str = ""
    posture: str = ""
    mood: str = ""


class ClothingStyleAnalysis(BaseModel):
    category: str = ""
    silhouette: str = ""
    neckline_and_straps: str = ""
    sleeve_and_length: str = ""
    fabric_texture: str = ""
    material_weight: str = ""
    color_mood: str = ""
    fit_and_exposure: str = ""
    styling_details: str = ""
    styling_keywords: list[str] = Field(default_factory=list)


class SceneStyleAnalysis(BaseModel):
    mood: str = ""
    spatial_feel: str = ""
    background_feel: str = ""
    color_temperature: str = ""
    texture_feel: str = ""


class ShootingStyleAnalysis(BaseModel):
    shot_type: str = ""
    framing: str = ""
    camera_angle: str = ""
    lighting: str = ""
    lens_feel: str = ""
    composition: str = ""
    image_texture: str = ""


class SelectedModelProfile(BaseModel):
    profile_key: str = ""
    name: str = ""
    image_path: str = ""
    reason: str = ""


class EnrouteReferenceAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_valid_wearing_reference: bool = False
    summary: str = ""
    selected_model_profile: SelectedModelProfile = Field(
        default_factory=SelectedModelProfile
    )
    model_style: ModelStyleAnalysis = Field(default_factory=ModelStyleAnalysis)
    clothing_style: ClothingStyleAnalysis = Field(default_factory=ClothingStyleAnalysis)
    scene_style: SceneStyleAnalysis = Field(default_factory=SceneStyleAnalysis)
    shooting_style: ShootingStyleAnalysis = Field(default_factory=ShootingStyleAnalysis)
    reason: str = ""


class EnrouteAnalysisSelection(BaseModel):
    selected_enroute_product_id: str = ""
    reason: str = ""


ENROUTE_REFERENCE_ANALYSIS_SYSTEM_PROMPT = """
你正在逆向分析一张 Enroute Jewelry 的 02.jpg 佩戴参考图。目标不是复制这张图，而是提炼可用于生成 inyourday 佩戴图的摄影、造型、构图和氛围规则。

inyourday 模特风格标准：
- Gen Z 新浪漫日常创作者，不是传统珠宝模特。
- early 20s，年轻但不幼稚。
- 亲近、松弛、有一点冷淡和叛逆感，不甜腻、不乖巧。
- 脸可以好看，但不能像超模、明星、整容网红、淘宝模特；要像真实欧美日常时尚创作者。
- 真实皮肤纹理，低妆感，柔雾或轻微缎光，不要塑料磨皮。
- 自然披发、微湿感、碎发、低束发，比精致 salon 造型更随意。
- 低饱和背心、细肩带、旧感针织、半透网纱、牛仔、黑/灰/象牙白基础单品。
- 姿势偏轴、侧脸、下半脸、肩颈、锁骨、腰上中景，像被朋友或杂志摄影师捕捉的一瞬间。
- 表情冷静、不讨好、不大笑、不营业。
- 首饰要成为个人风格的一部分，不要僵硬商品展示。

可选固定虚拟模特 profile：
{model_profile_options}

重要限制：
- 参考图中的首饰/商品只用于判断这是佩戴参考图。输出中禁止描述参考图里的任何产品细节。
- 不要描述参考图中的首饰颜色、材质、形状、数量、叠戴方式、垂落结构、宝石、链条、耳部饰品、手部饰品、腕部饰品等具体商品信息。
- 不要出现“Enroute”“enroute”“金色”“银色”“珍珠”“吊坠”“戒指”“耳饰”“耳环”“手链”“项链叠戴”“金饰”等参考商品细节词。
- 不要在 reason 中写任何参考图产品细节。后续流程会单独注入待处理商品信息，你这里只输出模特、衣物、场景和拍摄规则。
- scene_style 只描述感觉、氛围、空间气质、色温和质感，不描述具体实物、道具、墙砖、瓷砖、家具、背景物件。
- clothing_style 必须详细描述衣物本身，尤其款式、领口/肩带/袖长/衣长、面料纹理、厚薄重量、贴合度、露肤方式和穿搭细节。

请判断这张参考图是否适合作为佩戴图参考，并按多维度提炼：
1. model_style：脸部风格、表情、皮肤质感、姿态、情绪。不要输出年龄感和发型字段。
2. clothing_style：衣服品类、廓形、领口肩带、袖长衣长、面料纹理、厚薄重量、色彩感觉、贴合与露肤、穿搭细节、穿搭关键词。
3. scene_style：只描述场景感觉，不描述具体实物。包括整体情绪、空间感、背景感觉、色温、质感。
4. shooting_style：镜头类型、构图范围、机位角度、光线、镜头感、画面构成、影像质感。
5. summary：由你判断并写出摘要，重点说明该画面风格适合哪类饰品佩戴图；如果适合项链，必须分别说明短链、锁骨链、中长链、长链的适配程度和构图理由。
6. selected_model_profile：必须从可选固定虚拟模特 profile 中选择最适合承接该参考图风格的一个。只能返回给定的 profile_key、name、image_path，并用 reason 说明选择依据。

只输出 JSON，不要输出 Markdown。

JSON 格式：
{
  "is_valid_wearing_reference": true,
  "summary": "说明适合哪类饰品；项链需说明短链、锁骨链、中长链、长链适配程度",
  "selected_model_profile": {
    "profile_key": "从可选 profile_key 中选择一个",
    "name": "对应模特名",
    "image_path": "对应模特图片路径",
    "reason": "为什么该模特最适合"
  },
  "model_style": {
    "face_style": "简短中文描述",
    "expression": "简短中文描述",
    "skin_finish": "简短中文描述",
    "posture": "简短中文描述",
    "mood": "简短中文描述"
  },
  "clothing_style": {
    "category": "衣物品类",
    "silhouette": "廓形描述",
    "neckline_and_straps": "领口、肩带或肩部结构描述",
    "sleeve_and_length": "袖长和衣长描述",
    "fabric_texture": "面料纹理描述",
    "material_weight": "面料厚薄、垂坠或支撑感描述",
    "color_mood": "只描述低饱和、冷暖、明暗等色彩感觉，不写具体首饰颜色",
    "fit_and_exposure": "贴合度和露肤方式描述",
    "styling_details": "衣物穿搭细节描述",
    "styling_keywords": ["中文短词"]
  },
  "scene_style": {
    "mood": "场景情绪",
    "spatial_feel": "空间感觉",
    "background_feel": "背景感觉，不写具体实物",
    "color_temperature": "色温感觉",
    "texture_feel": "质感感觉"
  },
  "shooting_style": {
    "shot_type": "collarbone crop / waist-up / hand close-up / ear close-up",
    "framing": "简短中文描述",
    "camera_angle": "简短中文描述",
    "lighting": "简短中文描述",
    "lens_feel": "简短中文描述",
    "composition": "简短中文描述",
    "image_texture": "简短中文描述"
  },
  "reason": "简短中文原因"
}
""".strip()

ENROUTE_REFERENCE_ANALYSIS_USER_PROMPT = """
请分析这张佩戴参考图，按 system prompt 的规则输出 JSON。
""".strip()

ENROUTE_ANALYSIS_SELECTION_SYSTEM_PROMPT = """
你正在从同类目 Enroute 逆向 JSON 摘要缓存中，为当前产品选择一条最适合的佩戴图风格参考。

选择依据：
- 只根据当前产品主图、当前产品尺寸参考图、以及下面的逆向 JSON 摘要列表选择。
- 匹配重点只区分长 / 中 / 短的适配关系。
- 不要讨论具体饰品类型，不要扩展额外维度。
- 只能从摘要列表中的 enroute_product_id 选择一个。
- 只输出 JSON，不要输出 Markdown，不要输出解释文本。

逆向 JSON 摘要列表：
{analysis_summaries}

JSON 格式：
{
  "selected_enroute_product_id": "从摘要列表中选择一个 enroute_product_id",
  "reason": "简短中文原因"
}
""".strip()

ENROUTE_ANALYSIS_SELECTION_USER_PROMPT = """
图 1 是当前产品主图，图 2 是当前产品尺寸参考图。请只输出选择结果 JSON。
""".strip()

DEFAULT_MODEL_PROFILE_OPTIONS = "暂无可选固定模特 profile。"


def analyze_enroute_reference_image(
    image_path: str | Path,
    settings: Settings | None = None,
    model: Any | None = None,
    model_profiles: list[dict[str, Any]] | None = None,
    logger: WorkflowRunLogger | None = None,
    database_path: str | Path | None = None,
) -> EnrouteReferenceAnalysis:
    """Use OpenAI Responses streaming to reverse analyze a wearing reference."""

    path = Path(image_path)
    if model is not None:
        _log_llm_request(
            logger,
            context="enroute_reference_analysis_model",
            payload={
                "image_file": describe_file_for_log(path),
                "raw_messages": _vision_messages(path, model_profiles),
            },
        )
        response = model.invoke(_vision_messages(path, model_profiles))
        text = _message_text(response)
        _log_llm_response(
            logger,
            context="enroute_reference_analysis_model",
            text=text,
        )
        parsed = parse_enroute_reference_analysis(text)
        _log_llm_parsed_output(
            logger,
            context="enroute_reference_analysis_model",
            parsed=parsed.model_dump(),
        )
        return parsed

    active_settings = settings or Settings()
    image_url = _image_file_to_data_url(path)
    payload = build_enroute_reference_analysis_payload(
        active_settings,
        image_url,
        model_profiles=model_profiles,
    )
    _log_llm_request(
        logger,
        context="enroute_reference_analysis",
        payload={
            "image_file": describe_file_for_log(path),
            "raw_payload": payload,
        },
    )
    return request_responses_stream_parsed(
        active_settings,
        payload,
        parse_enroute_reference_analysis,
        logger=logger,
        request_context="enroute_reference_analysis",
        database_path=database_path,
    )


def build_enroute_reference_analysis_payload(
    settings: Settings,
    image_url: str,
    model_profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build an OpenAI Responses vision request payload for reference analysis."""

    payload: dict[str, Any] = {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": build_enroute_reference_analysis_system_prompt(
                            model_profiles
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": ENROUTE_REFERENCE_ANALYSIS_USER_PROMPT,
                    },
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
    if settings.enroute_analysis_temperature is not None:
        payload["temperature"] = settings.enroute_analysis_temperature
    if settings.enroute_analysis_top_p is not None:
        payload["top_p"] = settings.enroute_analysis_top_p
    return payload


def select_enroute_analysis_from_summaries(
    main_image_path: str | Path,
    size_reference_image_path: str | Path,
    analysis_summaries: list[dict[str, Any]],
    settings: Settings | None = None,
    model: Any | None = None,
    logger: WorkflowRunLogger | None = None,
    database_path: str | Path | None = None,
) -> EnrouteAnalysisSelection:
    """Use LLM to select one cached Enroute analysis summary for current product."""

    main_path = Path(main_image_path)
    size_path = Path(size_reference_image_path)
    if model is not None:
        messages = _selection_vision_messages(
            main_path,
            size_path,
            analysis_summaries,
        )
        _log_llm_request(
            logger,
            context="enroute_analysis_selection_model",
            payload={
                "main_image_file": describe_file_for_log(main_path),
                "size_reference_image_file": describe_file_for_log(size_path),
                "raw_messages": messages,
            },
        )
        response = model.invoke(messages)
        text = _message_text(response)
        _log_llm_response(
            logger,
            context="enroute_analysis_selection_model",
            text=text,
        )
        parsed = parse_enroute_analysis_selection(text)
        _log_llm_parsed_output(
            logger,
            context="enroute_analysis_selection_model",
            parsed=parsed.model_dump(),
        )
        return parsed

    active_settings = settings or Settings()
    payload = build_enroute_analysis_selection_payload(
        active_settings,
        _image_file_to_data_url(main_path),
        _image_file_to_data_url(size_path),
        analysis_summaries,
    )
    _log_llm_request(
        logger,
        context="enroute_analysis_selection",
        payload={
            "main_image_file": describe_file_for_log(main_path),
            "size_reference_image_file": describe_file_for_log(size_path),
            "raw_payload": payload,
        },
    )
    return request_responses_stream_parsed(
        active_settings,
        payload,
        parse_enroute_analysis_selection,
        logger=logger,
        request_context="enroute_analysis_selection",
        database_path=database_path,
    )


def build_enroute_analysis_selection_payload(
    settings: Settings,
    main_image_url: str,
    size_reference_image_url: str,
    analysis_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build an OpenAI Responses vision request for cached Enroute selection."""

    payload: dict[str, Any] = {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": build_enroute_analysis_selection_system_prompt(
                            analysis_summaries
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": ENROUTE_ANALYSIS_SELECTION_USER_PROMPT,
                    },
                    {
                        "type": "input_image",
                        "image_url": main_image_url,
                        "detail": "high",
                    },
                    {
                        "type": "input_image",
                        "image_url": size_reference_image_url,
                        "detail": "high",
                    },
                ],
            },
        ],
        "stream": True,
    }
    if settings.enroute_analysis_temperature is not None:
        payload["temperature"] = settings.enroute_analysis_temperature
    if settings.enroute_analysis_top_p is not None:
        payload["top_p"] = settings.enroute_analysis_top_p
    return payload


def parse_enroute_analysis_selection(text: str) -> EnrouteAnalysisSelection:
    payload = _extract_json_object(text)
    return EnrouteAnalysisSelection.model_validate(payload)


def build_enroute_analysis_selection_system_prompt(
    analysis_summaries: list[dict[str, Any]],
) -> str:
    return ENROUTE_ANALYSIS_SELECTION_SYSTEM_PROMPT.replace(
        "{analysis_summaries}",
        json_dumps_for_prompt(analysis_summaries),
    )


def parse_enroute_reference_analysis(text: str) -> EnrouteReferenceAnalysis:
    payload = _extract_json_object(text)
    analysis = EnrouteReferenceAnalysis.model_validate(payload)
    analysis.clothing_style.styling_keywords = _clean_instruction_list(
        analysis.clothing_style.styling_keywords
    )
    return analysis


def build_enroute_reference_analysis_system_prompt(
    model_profiles: list[dict[str, Any]] | None = None,
) -> str:
    return ENROUTE_REFERENCE_ANALYSIS_SYSTEM_PROMPT.replace(
        "{model_profile_options}",
        format_model_profile_options(model_profiles),
    )


def format_model_profile_options(
    model_profiles: list[dict[str, Any]] | None = None,
) -> str:
    if not model_profiles:
        return DEFAULT_MODEL_PROFILE_OPTIONS
    lines: list[str] = []
    for profile in model_profiles:
        profile_key = str(profile.get("profile_key") or "").strip()
        name = str(profile.get("name") or "").strip()
        image_path = str(profile.get("image_path") or "").strip()
        summary = str(profile.get("summary") or "").strip()
        if not profile_key:
            continue
        lines.append(
            f"- profile_key={profile_key}; name={name}; image_path={image_path}; "
            f"summary={summary}"
        )
    return "\n".join(lines) if lines else DEFAULT_MODEL_PROFILE_OPTIONS


def _vision_messages(
    path: Path,
    model_profiles: list[dict[str, Any]] | None = None,
) -> list[Any]:
    return [
        {
            "role": "system",
            "content": build_enroute_reference_analysis_system_prompt(model_profiles),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": ENROUTE_REFERENCE_ANALYSIS_USER_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": _image_file_to_data_url(path),
                        "detail": "high",
                    },
                },
            ],
        }
    ]


def _selection_vision_messages(
    main_path: Path,
    size_path: Path,
    analysis_summaries: list[dict[str, Any]],
) -> list[Any]:
    return [
        {
            "role": "system",
            "content": build_enroute_analysis_selection_system_prompt(
                analysis_summaries
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": ENROUTE_ANALYSIS_SELECTION_USER_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": _image_file_to_data_url(main_path),
                        "detail": "high",
                    },
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": _image_file_to_data_url(size_path),
                        "detail": "high",
                    },
                },
            ],
        },
    ]


def json_dumps_for_prompt(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _clean_instruction_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            cleaned.append(text)
    return cleaned
