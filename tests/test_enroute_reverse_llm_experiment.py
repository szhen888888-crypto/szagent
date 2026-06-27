"""Standalone LLM experiment for Enroute human-reference reverse analysis.

Run the live LLM experiment manually with:
ENROUTE_REVERSE_IMAGE_PATH=enroute-bestsellers/earrings/01-orin-large-hoop-earrings/02.jpg \
uv run pytest -s tests/test_enroute_reverse_llm_experiment.py::test_enroute_reverse_llm_experiment

The live test calls the configured LLM every time it runs. Contract tests in
this file do not call LangGraph, the database, or the external LLM.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from productv2.config import Settings
from productv2.enroute_human_reference_service import (
    HUMAN_REFERENCE_REVERSE_SCHEMA,
    analyze_human_reference_image,
    build_human_reference_reverse_payload,
    human_reference_prompt_sections,
)


BANNED_OUTPUT_TERMS = [
    "高级感",
    "松弛感",
    "氛围感",
    "气场",
    "精致",
    "复古",
    "冷淡",
    "自然感",
    "干净",
    "时髦",
    "电影感",
    "杂志感",
    "生活感",
    "真实感",
    "少女感",
    "叛逆感",
    "优雅",
    "性感",
    "温柔",
    "酷",
    "奢华",
    "轻盈",
    "随性",
]

REFERENCE_OBJECT_OUTPUT_TERMS = [
    "首饰",
    "佩戴",
    "商品",
    "jewelry",
    "wearing",
    "product",
    "珍珠",
    "宝石",
    "钻石",
    "链条",
    "吊坠",
    "耳圈",
    "圆环",
    "戒托",
    "金属黄",
    "银灰",
    "耳环",
    "项链",
    "戒指",
    "手链",
]

FORBIDDEN_SCHEMA_NAMES = [
    "visual_summary",
    "expression_tension",
    "distraction_level",
    "focal_look",
    "fabric_weight",
    "dominant_colors",
    "primary_wearing_area",
    "jewelry_placement_zone",
    "compiled_generation_prompt",
    "generation_rules",
    "avoid_rules",
]

FORBIDDEN_SCHEMA_FIELD_TOKENS = [
    "jewelry",
    "wearing",
    "placement",
    "product",
    "首饰",
    "佩戴",
    "商品",
]

DEFAULT_EXPERIMENT_IMAGE_PATH = (
    "enroute-bestsellers/earrings/01-orin-large-hoop-earrings/02.jpg"
)

REQUIRED_VALID_FIELD_PATHS = [
    "analysis_scope.task",
    "analysis_scope.exif_status",
    "observed_facts.human_visible_area.clear_body_regions",
    "observed_facts.composition_observation.occlusion_map",
    "observed_facts.camera_observation.perspective_effect",
    "observed_facts.lighting_observation.visible_light_direction",
    "observed_facts.pose_observation.head_angle",
    "observed_facts.hair_observation.hair_structure",
    "observed_facts.clothing_observation.garment_type",
    "observed_facts.background_observation.subject_competition",
    "observed_facts.observed_makeup_facts.skin_texture",
    "estimated_shooting_profile.camera_estimate.focal_length_35mm_equivalent_estimate.estimate",
    "estimated_shooting_profile.camera_estimate.focal_length_35mm_equivalent_estimate.suggested_downstream_lock",
    "estimated_shooting_profile.camera_estimate.aperture_look_estimate.estimate",
    "estimated_shooting_profile.lighting_estimate.key_light_position.estimate",
    "estimated_shooting_profile.pose_estimate.head_yaw.estimate",
    "estimated_shooting_profile.pose_estimate.head_pitch.estimate",
    "estimated_shooting_profile.pose_estimate.head_roll.estimate",
    "estimated_shooting_profile.pose_estimate.body_region_visibility.estimate",
    "estimated_shooting_profile.retouching_and_makeup_policy.makeup_transfer_policy",
]

CORE_EVIDENCE_SECTIONS = [
    "observed_facts.human_visible_area",
    "observed_facts.composition_observation",
    "observed_facts.camera_observation",
    "observed_facts.lighting_observation",
    "observed_facts.pose_observation",
    "observed_facts.background_observation",
    "estimated_shooting_profile.camera_estimate",
    "estimated_shooting_profile.lighting_estimate",
    "estimated_shooting_profile.pose_estimate",
]

EVIDENCE_PATTERN = re.compile(
    r"("
    r"约|%|百分|度|cm|mm|m|f/|画面|左|右|上|下|边缘|裁切|遮挡|入画|"
    r"可见|不可判断|区域|位置|占比|比例|光线|主光|补光|阴影|高光|"
    r"清晰|虚化|背景|耳|颈|脖|锁骨|肩|手|脸|嘴|眉|眼|唇|"
    r"下巴|头部|x=|y=|normalized|yaw|pitch|roll|35mm|\d+"
    r")",
    re.IGNORECASE,
)


def test_enroute_reverse_llm_experiment() -> None:
    image_path = Path(os.getenv("ENROUTE_REVERSE_IMAGE_PATH", DEFAULT_EXPERIMENT_IMAGE_PATH))
    assert image_path.is_file(), f"image not found: {image_path}"

    parsed = analyze_human_reference_image(image_path)

    print("\n=== Enroute Reverse LLM Experiment JSON ===")
    print(json.dumps(parsed, ensure_ascii=False, indent=2))

    _validate_schema_shape(parsed, HUMAN_REFERENCE_REVERSE_SCHEMA)
    output_text = json.dumps(parsed, ensure_ascii=False)
    assert not [term for term in BANNED_OUTPUT_TERMS if term in output_text]
    assert not [term for term in REFERENCE_OBJECT_OUTPUT_TERMS if term in output_text]
    assert not _contains_any_key(parsed, set(FORBIDDEN_SCHEMA_NAMES))
    if parsed["is_valid_human_reference"] is False:
        _assert_invalid_reference_contract(parsed)
        return
    _assert_valid_reference_contract(parsed)


def test_prompt_contract_is_human_reference_reverse_profile() -> None:
    system_prompt, user_prompt = human_reference_prompt_sections()
    combined_prompt = system_prompt + "\n" + user_prompt

    for name in FORBIDDEN_SCHEMA_NAMES:
        if name == "compiled_generation_prompt":
            assert "不要输出 compiled_generation_prompt" in combined_prompt
        else:
            assert name not in combined_prompt

    assert "observed_facts" in combined_prompt
    assert "estimated_shooting_profile" in combined_prompt
    assert "confidence_and_limits" in combined_prompt
    assert "transfer_notes" in combined_prompt
    assert "photographic_reverse_profile_only" in combined_prompt
    assert "fixed_default_not_reference" in combined_prompt
    assert "视觉等效推定" in combined_prompt
    assert "normalized 0-100 image space" in combined_prompt
    assert "本阶段只分析" in combined_prompt
    assert "不要输出生图 prompt" in combined_prompt
    assert "酷" in BANNED_OUTPUT_TERMS

    schema_text = json.dumps(HUMAN_REFERENCE_REVERSE_SCHEMA, ensure_ascii=False)
    for token in FORBIDDEN_SCHEMA_FIELD_TOKENS:
        assert token not in schema_text
    for name in FORBIDDEN_SCHEMA_NAMES:
        assert not _schema_contains_property_name(HUMAN_REFERENCE_REVERSE_SCHEMA, name)
    assert "is_valid_human_reference" in schema_text
    assert "clear_body_regions" in schema_text
    assert "occlusion_map" in schema_text
    assert "focal_length_35mm_equivalent_estimate" in schema_text
    assert "aperture_look_estimate" in schema_text
    assert "makeup_transfer_policy" in schema_text
    assert "pose_estimate" in schema_text


def test_service_builds_human_reference_payload_from_shared_prompt() -> None:
    payload = build_human_reference_reverse_payload(
        Settings(openai_model="gpt-test"),
        "data:image/jpeg;base64,fixture",
    )

    assert payload["model"] == "gpt-test"
    assert payload["stream"] is True
    assert payload["text"]["format"]["schema"] is HUMAN_REFERENCE_REVERSE_SCHEMA
    assert payload["text"]["format"]["name"] == "enroute_reverse_human_shooting_profile"
    assert payload["input"][0]["role"] == "system"
    assert payload["input"][1]["role"] == "user"
    assert "observed_facts" in payload["input"][0]["content"][0]["text"]
    assert "estimated_shooting_profile" in payload["input"][0]["content"][0]["text"]
    assert "不要输出生图 prompt" in payload["input"][1]["content"][0]["text"]
    assert payload["input"][1]["content"][1] == {
        "type": "input_image",
        "image_url": "data:image/jpeg;base64,fixture",
        "detail": "high",
    }


def test_service_accepts_explicit_schema_override() -> None:
    custom_schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }

    payload = build_human_reference_reverse_payload(
        Settings(openai_model="gpt-test"),
        "data:image/jpeg;base64,fixture",
        schema=custom_schema,
    )

    assert payload["text"]["format"]["schema"] is custom_schema


def test_local_schema_contract_accepts_valid_and_invalid_shapes() -> None:
    valid_payload = _valid_contract_fixture()
    _validate_schema_shape(valid_payload, HUMAN_REFERENCE_REVERSE_SCHEMA)
    _assert_valid_reference_contract(valid_payload)

    invalid_payload = _invalid_contract_fixture()
    _validate_schema_shape(invalid_payload, HUMAN_REFERENCE_REVERSE_SCHEMA)
    _assert_invalid_reference_contract(invalid_payload)


def _contains_any_key(value: object, keys: set[str]) -> bool:
    if isinstance(value, dict):
        if any(key in value for key in keys):
            return True
        return any(_contains_any_key(item, keys) for item in value.values())
    if isinstance(value, list):
        return any(_contains_any_key(item, keys) for item in value)
    return False


def _schema_contains_property_name(schema: dict[str, Any], name: str) -> bool:
    properties = schema.get("properties", {})
    if name in properties:
        return True
    return any(
        isinstance(child_schema, dict)
        and _schema_contains_property_name(child_schema, name)
        for child_schema in properties.values()
    )


def _validate_schema_shape(value: object, schema: dict[str, Any], path: str = "$") -> None:
    expected_types = _schema_type_names(schema)
    assert _matches_json_type(value, expected_types), (
        f"{path} expected {sorted(expected_types)}, got "
        f"{type(value).__name__}: {value!r}"
    )

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        assert not missing, f"{path} missing required keys: {missing}"

        if schema.get("additionalProperties") is False:
            extra = [key for key in value if key not in properties]
            assert not extra, f"{path} has extra keys: {extra}"

        for key, child_schema in properties.items():
            if key in value:
                _validate_schema_shape(value[key], child_schema, f"{path}.{key}")

    if isinstance(value, list):
        item_schema = schema.get("items")
        assert item_schema, f"{path} array schema must define items"
        for index, item in enumerate(value):
            _validate_schema_shape(item, item_schema, f"{path}[{index}]")


def _schema_type_names(schema: dict[str, Any]) -> set[str]:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return set(schema_type)
    assert isinstance(schema_type, str), f"schema missing type: {schema}"
    return {schema_type}


def _matches_json_type(value: object, expected_types: set[str]) -> bool:
    if value is None:
        actual_type = "null"
    elif isinstance(value, bool):
        actual_type = "boolean"
    elif isinstance(value, str):
        actual_type = "string"
    elif isinstance(value, list):
        actual_type = "array"
    elif isinstance(value, dict):
        actual_type = "object"
    elif isinstance(value, (int, float)):
        actual_type = "number"
    else:
        actual_type = type(value).__name__
    return actual_type in expected_types


def _assert_invalid_reference_contract(parsed: dict[str, Any]) -> None:
    assert parsed["is_valid_human_reference"] is False
    assert parsed["invalid_reason"].strip()
    assert parsed["analysis_scope"]["task"] == "photographic_reverse_profile_only"
    assert parsed["analysis_scope"]["not_prompt_generation"] is True
    assert parsed["analysis_scope"]["exif_status"] == "visual_estimate_only_not_real_exif"
    assert parsed["observed_facts"] is None
    assert parsed["estimated_shooting_profile"] is None
    assert parsed["confidence_and_limits"] == {
        "high_confidence": [],
        "medium_confidence": [],
        "low_confidence": [],
        "not_inferable_from_single_image": [],
    }
    assert parsed["transfer_notes"] == {
        "stable_reference_features": [],
        "unstable_or_low_confidence_features": [],
        "do_not_transfer_from_reference": [],
    }
    assert "compiled_generation_prompt" not in parsed


def _assert_valid_reference_contract(parsed: dict[str, Any]) -> None:
    assert parsed["is_valid_human_reference"] is True
    assert parsed["invalid_reason"] == ""
    assert parsed["analysis_scope"]["task"] == "photographic_reverse_profile_only"
    assert parsed["analysis_scope"]["not_prompt_generation"] is True
    assert parsed["analysis_scope"]["exif_status"] == "visual_estimate_only_not_real_exif"
    assert isinstance(parsed["observed_facts"], dict)
    assert isinstance(parsed["estimated_shooting_profile"], dict)
    assert "compiled_generation_prompt" not in parsed

    for path in REQUIRED_VALID_FIELD_PATHS:
        value = _get_path(parsed, path)
        assert isinstance(value, str) and value.strip(), f"{path} must be non-empty"

    makeup_policy = parsed["estimated_shooting_profile"]["retouching_and_makeup_policy"]
    assert makeup_policy["makeup_transfer_policy"] == "fixed_default_not_reference"
    assert makeup_policy["inherit_reference_makeup"] is False

    _assert_estimates_have_evidence(parsed["estimated_shooting_profile"])
    _assert_evidence_density(parsed)


def _assert_estimates_have_evidence(profile: dict[str, Any]) -> None:
    estimate_objects = [
        value
        for value in _iter_objects(profile)
        if {"estimate", "confidence", "evidence"}.issubset(value)
    ]
    assert len(estimate_objects) >= 20
    for item in estimate_objects:
        assert item["estimate"].strip()
        assert item["confidence"] in {"high", "medium", "low"}
        assert item["evidence"].strip()


def _assert_evidence_density(parsed: dict[str, Any]) -> None:
    strings = list(_iter_leaf_strings(parsed))
    evidence_strings = [value for value in strings if EVIDENCE_PATTERN.search(value)]
    min_evidence_count = min(24, max(14, len(strings) // 3))
    assert len(evidence_strings) >= min_evidence_count, (
        "output lacks enough observable evidence strings: "
        f"{len(evidence_strings)}/{len(strings)}"
    )

    for section_path in CORE_EVIDENCE_SECTIONS:
        section = _get_path(parsed, section_path)
        section_strings = list(_iter_leaf_strings(section))
        assert any(EVIDENCE_PATTERN.search(value) for value in section_strings), (
            f"{section_path} lacks observable evidence"
        )


def _iter_objects(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        objects = [value]
        for item in value.values():
            objects.extend(_iter_objects(item))
        return objects
    if isinstance(value, list):
        objects: list[dict[str, Any]] = []
        for item in value:
            objects.extend(_iter_objects(item))
        return objects
    return []


def _iter_leaf_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_iter_leaf_strings(item))
        return strings
    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_iter_leaf_strings(item))
        return strings
    return []


def _get_path(value: dict[str, Any], path: str) -> object:
    current: object = value
    for part in path.split("."):
        assert isinstance(current, dict), f"{path} crosses non-object at {part}"
        assert part in current, f"{path} missing {part}"
        current = current[part]
    return current


def _valid_contract_fixture() -> dict[str, Any]:
    payload = _example_from_schema(HUMAN_REFERENCE_REVERSE_SCHEMA)
    assert isinstance(payload, dict)
    payload["is_valid_human_reference"] = True
    payload["invalid_reason"] = ""
    payload["analysis_scope"] = {
        "task": "photographic_reverse_profile_only",
        "not_prompt_generation": True,
        "exif_status": "visual_estimate_only_not_real_exif",
    }
    payload["estimated_shooting_profile"]["camera_estimate"][
        "exif_status"
    ] = "visual_estimate_only_not_real_exif"
    for estimate in _iter_estimate_objects(payload["estimated_shooting_profile"]):
        estimate["confidence"] = "high"
    makeup_policy = payload["estimated_shooting_profile"]["retouching_and_makeup_policy"]
    makeup_policy["makeup_transfer_policy"] = "fixed_default_not_reference"
    makeup_policy["inherit_reference_makeup"] = False
    return payload


def _invalid_contract_fixture() -> dict[str, Any]:
    payload = _example_from_schema(HUMAN_REFERENCE_REVERSE_SCHEMA)
    assert isinstance(payload, dict)
    payload["is_valid_human_reference"] = False
    payload["invalid_reason"] = "没有人物，画面未包含可见人体区域。"
    payload["analysis_scope"] = {
        "task": "photographic_reverse_profile_only",
        "not_prompt_generation": True,
        "exif_status": "visual_estimate_only_not_real_exif",
    }
    payload["observed_facts"] = None
    payload["estimated_shooting_profile"] = None
    payload["confidence_and_limits"] = {
        "high_confidence": [],
        "medium_confidence": [],
        "low_confidence": [],
        "not_inferable_from_single_image": [],
    }
    payload["transfer_notes"] = {
        "stable_reference_features": [],
        "unstable_or_low_confidence_features": [],
        "do_not_transfer_from_reference": [],
    }
    return payload


def _example_from_schema(schema: dict[str, Any]) -> object:
    schema_types = _schema_type_names(schema)
    if "object" in schema_types:
        return {
            key: _example_from_schema(child_schema)
            for key, child_schema in schema.get("properties", {}).items()
        }
    if "array" in schema_types:
        return ["画面左侧30度主光，x=50,y=40，70mm，f/4，锁骨区域可见。"]
    if "boolean" in schema_types:
        return False
    if "string" in schema_types:
        return "画面左侧30度主光，x=50,y=40，70mm，f/4，锁骨区域可见。"
    if "null" in schema_types:
        return None
    raise AssertionError(f"unsupported schema type: {schema_types}")


def _iter_estimate_objects(value: object) -> list[dict[str, Any]]:
    return [
        item
        for item in _iter_objects(value)
        if {"estimate", "confidence", "evidence"}.issubset(item)
    ]
