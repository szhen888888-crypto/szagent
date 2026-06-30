"""LLM reverse analysis for Enroute wearing references."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from productv2.config import Settings
from productv2.prompt_loader import load_latest_prompt_sections, render_prompt_template
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
    makeup_style: str = ""
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

    is_valid_wearing_reference: bool | None = None
    is_valid_human_reference: bool | None = None
    invalid_reason: str = ""
    analysis_scope: dict[str, Any] = Field(default_factory=dict)
    observed_facts: dict[str, Any] | None = None
    estimated_shooting_profile: dict[str, Any] | None = None
    confidence_and_limits: dict[str, Any] = Field(default_factory=dict)
    transfer_notes: dict[str, Any] = Field(default_factory=dict)
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


class WearingStyleProfileSelection(BaseModel):
    selected_enroute_product_id: str = ""
    selected_model_profile_key: str = ""
    reason: str = ""


ENROUTE_REFERENCE_ANALYSIS_PROMPT_DIR = "reference_analysis/enroute_reference"
ENROUTE_ANALYSIS_SELECTION_PROMPT_DIR = "reference_analysis/enroute_selection"
WEARING_STYLE_SELECTION_PROMPT_DIR = "wearing/style_profile_selection"

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
        use_ai_call_lock=False,
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
                        "text": enroute_reference_analysis_user_prompt(),
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


def select_wearing_style_profile(
    main_image_path: str | Path,
    size_reference_image_path: str | Path,
    enroute_profile_summaries: list[dict[str, Any]],
    model_profile_summaries: list[dict[str, Any]],
    settings: Settings | None = None,
    model: Any | None = None,
    logger: WorkflowRunLogger | None = None,
    database_path: str | Path | None = None,
) -> WearingStyleProfileSelection:
    """Select one Enroute profile and one fixed model profile for generation."""

    main_path = Path(main_image_path)
    size_path = Path(size_reference_image_path)
    if model is not None:
        messages = _wearing_style_selection_messages(
            main_path,
            size_path,
            enroute_profile_summaries,
            model_profile_summaries,
        )
        _log_llm_request(
            logger,
            context="wearing_style_profile_selection_model",
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
            context="wearing_style_profile_selection_model",
            text=text,
        )
        parsed = parse_wearing_style_profile_selection(text)
        _log_llm_parsed_output(
            logger,
            context="wearing_style_profile_selection_model",
            parsed=parsed.model_dump(),
        )
        return parsed

    active_settings = settings or Settings()
    payload = build_wearing_style_selection_payload(
        active_settings,
        _image_file_to_data_url(main_path),
        _image_file_to_data_url(size_path),
        enroute_profile_summaries,
        model_profile_summaries,
    )
    _log_llm_request(
        logger,
        context="wearing_style_profile_selection",
        payload={
            "main_image_file": describe_file_for_log(main_path),
            "size_reference_image_file": describe_file_for_log(size_path),
            "raw_payload": payload,
        },
    )
    return request_responses_stream_parsed(
        active_settings,
        payload,
        parse_wearing_style_profile_selection,
        logger=logger,
        request_context="wearing_style_profile_selection",
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
                        "text": enroute_analysis_selection_user_prompt(),
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


def build_wearing_style_selection_payload(
    settings: Settings,
    main_image_url: str,
    size_reference_image_url: str,
    enroute_profile_summaries: list[dict[str, Any]],
    model_profile_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a Responses vision request for style + model selection."""

    payload: dict[str, Any] = {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": build_wearing_style_selection_system_prompt(
                            enroute_profile_summaries,
                            model_profile_summaries,
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": wearing_style_selection_user_prompt(),
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


def parse_wearing_style_profile_selection(text: str) -> WearingStyleProfileSelection:
    payload = _extract_json_object(text)
    return WearingStyleProfileSelection.model_validate(payload)


def build_enroute_analysis_selection_system_prompt(
    analysis_summaries: list[dict[str, Any]],
) -> str:
    return render_prompt_template(
        load_latest_prompt_sections(ENROUTE_ANALYSIS_SELECTION_PROMPT_DIR).system,
        {"analysis_summaries": json_dumps_for_prompt(analysis_summaries)},
    )


def build_wearing_style_selection_system_prompt(
    enroute_profile_summaries: list[dict[str, Any]],
    model_profile_summaries: list[dict[str, Any]],
) -> str:
    return render_prompt_template(
        load_latest_prompt_sections(WEARING_STYLE_SELECTION_PROMPT_DIR).system,
        {
            "enroute_profile_summaries": json_dumps_for_prompt(
                enroute_profile_summaries
            ),
            "model_profile_summaries": json_dumps_for_prompt(model_profile_summaries),
        },
    )


def parse_enroute_reference_analysis(text: str) -> EnrouteReferenceAnalysis:
    payload = _extract_json_object(text)
    analysis = EnrouteReferenceAnalysis.model_validate(payload)
    analysis.clothing_style.styling_keywords = _clean_instruction_list(
        analysis.clothing_style.styling_keywords
    )
    if not analysis.summary:
        analysis.summary = summarize_enroute_profile(analysis.model_dump())
    return analysis


def build_enroute_reference_analysis_system_prompt(
    model_profiles: list[dict[str, Any]] | None = None,
) -> str:
    return render_prompt_template(
        load_latest_prompt_sections(ENROUTE_REFERENCE_ANALYSIS_PROMPT_DIR).system,
        {"model_profile_options": format_model_profile_options(model_profiles)},
    )


def enroute_reference_analysis_user_prompt() -> str:
    return load_latest_prompt_sections(ENROUTE_REFERENCE_ANALYSIS_PROMPT_DIR).user


def enroute_analysis_selection_user_prompt() -> str:
    return load_latest_prompt_sections(ENROUTE_ANALYSIS_SELECTION_PROMPT_DIR).user


def wearing_style_selection_user_prompt() -> str:
    return load_latest_prompt_sections(WEARING_STYLE_SELECTION_PROMPT_DIR).user


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
                {"type": "text", "text": enroute_reference_analysis_user_prompt()},
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
                {"type": "text", "text": enroute_analysis_selection_user_prompt()},
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


def _wearing_style_selection_messages(
    main_path: Path,
    size_path: Path,
    enroute_profile_summaries: list[dict[str, Any]],
    model_profile_summaries: list[dict[str, Any]],
) -> list[Any]:
    return [
        {
            "role": "system",
            "content": build_wearing_style_selection_system_prompt(
                enroute_profile_summaries,
                model_profile_summaries,
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": wearing_style_selection_user_prompt()},
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


def summarize_enroute_profile(profile: dict[str, Any]) -> str:
    """Build a compact summary for profile-selection prompts and cache rows."""

    explicit = str(profile.get("summary") or "").strip()
    if explicit:
        return explicit
    if profile.get("is_valid_human_reference") is False:
        return str(profile.get("invalid_reason") or "无效人物参考图").strip()

    parts: list[str] = []
    transfer_notes = profile.get("transfer_notes")
    if isinstance(transfer_notes, dict):
        stable = transfer_notes.get("stable_reference_features")
        if isinstance(stable, list):
            parts.extend(str(item).strip() for item in stable[:4] if str(item).strip())

    observed = profile.get("observed_facts")
    if isinstance(observed, dict):
        clothing = observed.get("clothing_observation")
        if isinstance(clothing, dict):
            for key in ("garment_type", "neckline", "skin_exposure_effect"):
                value = str(clothing.get(key) or "").strip()
                if value:
                    parts.append(value)
        composition = observed.get("composition_observation")
        if isinstance(composition, dict):
            for key in ("shot_type", "crop_boundaries", "subject_scale"):
                value = str(composition.get(key) or "").strip()
                if value:
                    parts.append(value)

    shooting = profile.get("estimated_shooting_profile")
    if isinstance(shooting, dict):
        camera = shooting.get("camera_estimate")
        if isinstance(camera, dict):
            for key in ("shot_size_estimate", "focal_length_35mm_equivalent_estimate"):
                value = _estimate_text(camera.get(key))
                if value:
                    parts.append(value)
        lighting = shooting.get("lighting_estimate")
        if isinstance(lighting, dict):
            value = _estimate_text(lighting.get("key_light_position"))
            if value:
                parts.append(value)

    legacy_sections = [
        profile.get("model_style"),
        profile.get("clothing_style"),
        profile.get("scene_style"),
        profile.get("shooting_style"),
    ]
    for section in legacy_sections:
        if isinstance(section, dict):
            for value in section.values():
                if isinstance(value, list):
                    parts.extend(str(item).strip() for item in value if str(item).strip())
                else:
                    text = str(value or "").strip()
                    if text:
                        parts.append(text)

    deduped: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if part in seen:
            continue
        seen.add(part)
        deduped.append(part)
        if len(deduped) >= 8:
            break
    return "；".join(deduped) or "人物摄影参考 profile"


def _estimate_text(value: Any) -> str:
    if isinstance(value, dict):
        estimate = str(value.get("estimate") or "").strip()
        evidence = str(value.get("evidence") or "").strip()
        return "，".join(part for part in (estimate, evidence) if part)
    return str(value or "").strip()


def json_dumps_for_prompt(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _clean_instruction_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = str(value).strip()
        if text:
            cleaned.append(text)
    return cleaned
