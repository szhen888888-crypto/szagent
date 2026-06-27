"""Human-reference reverse-analysis service for Enroute experiment prompts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from productv2.config import Settings
from productv2.prompt_loader import load_latest_prompt_sections
from productv2.vision import (
    _extract_json_object,
    _image_file_to_data_url,
    request_responses_stream_text,
)


PROMPT_DIR = "experiments/enroute_reverse_human"


def _string(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


def _boolean(description: str) -> dict[str, Any]:
    return {"type": "boolean", "description": description}


def _object(properties: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _nullable_object(properties: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": ["object", "null"],
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _string_array(description: str) -> dict[str, Any]:
    return {
        "type": "array",
        "description": description,
        "items": {"type": "string"},
    }


def _estimate_parameter(description: str) -> dict[str, Any]:
    return _object(
        {
            "estimate": _string(description),
            "confidence": _string("high | medium | low"),
            "evidence": _string("Concrete visible evidence for this estimate."),
        }
    )


def _estimate_parameter_with_lock(description: str) -> dict[str, Any]:
    return _object(
        {
            "estimate": _string(description),
            "suggested_downstream_lock": _string(
                "Suggested downstream lock value; not a generation prompt."
            ),
            "confidence": _string("high | medium | low"),
            "evidence": _string("Concrete visible evidence for this estimate."),
        }
    )


ANALYSIS_SCOPE_SCHEMA = _object(
    {
        "task": _string("Must be photographic_reverse_profile_only."),
        "not_prompt_generation": _boolean("Must be true."),
        "exif_status": _string("Must state visual estimate only, not real EXIF."),
    }
)


OBSERVED_FACTS_SCHEMA = _object(
    {
        "human_visible_area": _object(
            {
                "visible_body_range": _string("Visible human body range."),
                "exposed_skin_regions": _string("Visible skin regions."),
                "clear_body_regions": _string("Clear, unobstructed body regions."),
                "occluded_body_regions": _string(
                    "Body regions blocked by hair, cloth, hand, shadow, or unnamed occluders."
                ),
                "unsupported_regions": _string("Body regions not visible in frame."),
                "body_region_visibility": _string("Visibility of key body regions."),
            }
        ),
        "composition_observation": _object(
            {
                "shot_type": _string("Shot type."),
                "aspect_ratio": _string("Visible aspect ratio."),
                "crop_boundaries": _string("Crop boundaries."),
                "subject_position": _string("Subject position in frame."),
                "subject_scale": _string("Approximate subject scale."),
                "negative_space": _string("Negative-space location and percentage."),
                "occlusion_map": _string(
                    "Map visible occlusion to blocked body regions without naming non-human objects."
                ),
            }
        ),
        "camera_observation": _object(
            {
                "camera_angle": _string("Observed camera angle."),
                "perspective_effect": _string(
                    "Face/body/hand perspective distortion or compression."
                ),
                "focus_area": _string("Sharpest visible area."),
                "depth_of_field_observation": _string(
                    "Subject/background sharpness and blur relationship."
                ),
            }
        ),
        "lighting_observation": _object(
            {
                "visible_light_direction": _string("Visible key-light direction."),
                "highlight_locations": _string("Specific highlight locations."),
                "shadow_locations": _string("Specific shadow locations."),
                "shadow_edge_quality": _string("Shadow edge quality."),
                "contrast_observation": _string("Visible evidence of contrast strength."),
            }
        ),
        "pose_observation": _object(
            {
                "head_angle": _string("Head yaw, pitch, and roll observation."),
                "gaze": _string("Gaze direction and camera contact."),
                "mouth_and_jaw": _string("Mouth, mouth-corner, jaw, and chin state."),
                "neck_position": _string("Neck extension, tilt, twist, or occlusion."),
                "shoulder_position": _string("Shoulder line and visibility."),
                "torso_angle": _string("Torso direction and rotation."),
                "hand_position": _string("Hand visibility; use unavailable text when absent."),
            }
        ),
        "hair_observation": _object(
            {
                "hair_structure": _string("Visible hair structure."),
                "hair_position": _string("Where hair falls over body regions."),
                "hair_occlusion": _string("Body regions occluded by hair."),
                "strand_detail": _string("Strand edges, flyaways, clumps, curls, or flat sheets."),
            }
        ),
        "clothing_observation": _object(
            {
                "garment_type": _string("Visible garment type."),
                "neckline": _string("Neckline shape and height."),
                "shoulder_or_sleeve": _string("Shoulder, strap, or sleeve structure."),
                "fabric_surface": _string("Visible fabric surface."),
                "fit_and_folds": _string("Fit, folds, stretching, and drape direction."),
                "skin_exposure_effect": _string("Body exposure caused by clothing."),
            }
        ),
        "background_observation": _object(
            {
                "background_type": _string("Background type."),
                "background_complexity": _string("Element count and complexity."),
                "spatial_depth": _string("Visible depth layers."),
                "visible_color_palette": _string(
                    "Colors from skin, hair, clothing, and background only."
                ),
                "texture_visibility": _string("Background texture visibility."),
                "subject_competition": _string(
                    "High brightness, contrast, text, or complex shapes competing with the human subject."
                ),
            }
        ),
        "observed_makeup_facts": _object(
            {
                "skin_texture": _string("Visible skin texture, pores, spots, or retouching."),
                "skin_highlight": _string("Skin highlight locations."),
                "base_finish": _string("Visible base finish."),
                "eye_makeup": _string("Visible eyeliner, lashes, or eyeshadow borders."),
                "lip_observation": _string(
                    "Lip color depth, saturation, lip-line border, and highlight location."
                ),
            }
        ),
    }
)


CAMERA_ESTIMATE_SCHEMA = _object(
    {
        "exif_status": _string("Must be visual_estimate_only_not_real_exif."),
        "aspect_ratio_estimate": _estimate_parameter("Aspect ratio estimate."),
        "shot_size_estimate": _estimate_parameter("Shot size estimate."),
        "camera_height_estimate": _estimate_parameter(
            "Visual-equivalent camera height."
        ),
        "camera_distance_estimate": _estimate_parameter(
            "Visual-equivalent camera-to-subject distance."
        ),
        "focal_length_35mm_equivalent_estimate": _estimate_parameter_with_lock(
            "Visual-equivalent 35mm focal length estimate."
        ),
        "aperture_look_estimate": _estimate_parameter_with_lock(
            "Visual-equivalent aperture look."
        ),
        "camera_yaw_estimate": _estimate_parameter("Camera yaw estimate."),
        "camera_pitch_estimate": _estimate_parameter("Camera pitch estimate."),
        "camera_roll_estimate": _estimate_parameter("Camera roll estimate."),
        "focus_target_estimate": _estimate_parameter("Focus target estimate."),
        "depth_of_field_estimate": _estimate_parameter("Depth-of-field estimate."),
    }
)


LIGHTING_ESTIMATE_SCHEMA = _object(
    {
        "key_light_position": _estimate_parameter(
            "Key-light direction, height, and angle."
        ),
        "key_light_size": _estimate_parameter("Key-light size or softness."),
        "fill_light": _estimate_parameter("Fill-light direction and intensity."),
        "background_light": _estimate_parameter("Background-light state."),
        "contrast_ratio_estimate": _estimate_parameter("Visual contrast ratio."),
        "shadow_quality": _estimate_parameter("Shadow edge, direction, and contrast."),
        "highlight_pattern": _estimate_parameter("Highlight distribution pattern."),
    }
)


POSE_ESTIMATE_SCHEMA = _object(
    {
        "coordinate_system": _string("Normalized keypoint coordinate system."),
        "head_yaw": _estimate_parameter("Head yaw estimate."),
        "head_pitch": _estimate_parameter("Head pitch estimate."),
        "head_roll": _estimate_parameter("Head roll estimate."),
        "gaze_target": _estimate_parameter("Gaze target estimate."),
        "chin_position": _estimate_parameter("Chin position estimate."),
        "shoulder_line": _estimate_parameter("Shoulder line and tilt estimate."),
        "torso_rotation": _estimate_parameter("Torso rotation estimate."),
        "neck_exposure": _estimate_parameter("Neck exposure and occlusion estimate."),
        "body_region_visibility": _estimate_parameter(
            "Visible and unavailable body regions."
        ),
        "pose_keypoints": _object(
            {
                "left_eye": _string("x,y or unavailable text."),
                "right_eye": _string("x,y or unavailable text."),
                "nose_tip": _string("x,y or unavailable text."),
                "mouth_center": _string("x,y or unavailable text."),
                "chin": _string("x,y or unavailable text."),
                "neck_center": _string("x,y or unavailable text."),
                "left_shoulder": _string("x,y or unavailable text."),
                "right_shoulder": _string("x,y or unavailable text."),
                "clavicle_center": _string("x,y or unavailable text."),
            }
        ),
    }
)


ESTIMATED_SHOOTING_PROFILE_SCHEMA = _object(
    {
        "camera_estimate": CAMERA_ESTIMATE_SCHEMA,
        "lighting_estimate": LIGHTING_ESTIMATE_SCHEMA,
        "pose_estimate": POSE_ESTIMATE_SCHEMA,
        "composition_profile": _object(
            {
                "framing_pattern": _string("Framing and crop pattern."),
                "subject_scale_pattern": _string("Subject scale pattern."),
                "negative_space_pattern": _string("Negative-space pattern."),
                "crop_risk": _string("Information loss caused by crop."),
            }
        ),
        "background_profile": _object(
            {
                "background_type": _string("Background type."),
                "background_depth": _string("Background depth."),
                "background_texture": _string("Background texture."),
                "background_distraction_sources": _string("Background distraction sources."),
            }
        ),
        "retouching_and_makeup_policy": _object(
            {
                "observed_retouching": _string("Visible retouching and skin processing."),
                "makeup_transfer_policy": _string(
                    "Must be fixed_default_not_reference."
                ),
                "inherit_reference_makeup": _boolean("Must be false by default."),
                "fixed_default_makeup_rule": _string("Fixed default makeup policy."),
            }
        ),
    }
)


CONFIDENCE_AND_LIMITS_SCHEMA = _object(
    {
        "high_confidence": _string_array("High-confidence observations."),
        "medium_confidence": _string_array("Medium-confidence visual estimates."),
        "low_confidence": _string_array("Low-confidence visual estimates."),
        "not_inferable_from_single_image": _string_array(
            "True capture parameters not inferable from one image."
        ),
    }
)


TRANSFER_NOTES_SCHEMA = _object(
    {
        "stable_reference_features": _string_array(
            "Stable features for a downstream compiler; not generation commands."
        ),
        "unstable_or_low_confidence_features": _string_array(
            "Low-confidence or unstable features."
        ),
        "do_not_transfer_from_reference": _string_array(
            "Reference elements that should not be inherited downstream."
        ),
    }
)


HUMAN_REFERENCE_REVERSE_SCHEMA = _object(
    {
        "is_valid_human_reference": _boolean(
            "Whether the image is a valid human reference image."
        ),
        "invalid_reason": _string(
            "Empty for valid images; concrete reason for invalid images."
        ),
        "analysis_scope": ANALYSIS_SCOPE_SCHEMA,
        "observed_facts": _nullable_object(
            OBSERVED_FACTS_SCHEMA["properties"],
        ),
        "estimated_shooting_profile": _nullable_object(
            ESTIMATED_SHOOTING_PROFILE_SCHEMA["properties"],
        ),
        "confidence_and_limits": CONFIDENCE_AND_LIMITS_SCHEMA,
        "transfer_notes": TRANSFER_NOTES_SCHEMA,
    }
)


def human_reference_prompt_sections() -> tuple[str, str]:
    sections = load_latest_prompt_sections(PROMPT_DIR)
    return sections.system, sections.user


def build_human_reference_reverse_payload(
    settings: Settings,
    image_url: str,
    *,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    system_prompt, user_prompt = human_reference_prompt_sections()
    active_schema = schema or HUMAN_REFERENCE_REVERSE_SCHEMA
    return {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_prompt},
                    {
                        "type": "input_image",
                        "image_url": image_url,
                        "detail": "high",
                    },
                ],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "enroute_reverse_human_shooting_profile",
                "strict": True,
                "schema": active_schema,
            }
        },
        "stream": True,
    }


def analyze_human_reference_image(
    image_path: str | Path,
    *,
    schema: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    active_settings = settings or Settings()
    active_schema = schema or HUMAN_REFERENCE_REVERSE_SCHEMA
    payload = build_human_reference_reverse_payload(
        active_settings,
        _image_file_to_data_url(Path(image_path)),
        schema=active_schema,
    )
    text = request_responses_stream_text(
        active_settings,
        payload,
        max_retries=0,
        request_context="enroute_human_reference_experiment",
    )
    return _extract_json_object(text)
