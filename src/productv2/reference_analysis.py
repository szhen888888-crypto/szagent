"""Compatibility exports for Enroute reference analysis.

The implementation lives in `productv2.reference_analysis_service` so workflow
nodes and tests can call the same service layer.
"""

from productv2.reference_analysis_service import (
    ClothingStyleAnalysis,
    DEFAULT_MODEL_PROFILE_OPTIONS,
    ENROUTE_ANALYSIS_SELECTION_PROMPT_DIR,
    ENROUTE_REFERENCE_ANALYSIS_PROMPT_DIR,
    EnrouteAnalysisSelection,
    EnrouteReferenceAnalysis,
    ModelStyleAnalysis,
    SceneStyleAnalysis,
    SelectedModelProfile,
    ShootingStyleAnalysis,
    analyze_enroute_reference_image,
    build_enroute_analysis_selection_payload,
    build_enroute_analysis_selection_system_prompt,
    build_enroute_reference_analysis_payload,
    build_enroute_reference_analysis_system_prompt,
    enroute_analysis_selection_user_prompt,
    enroute_reference_analysis_user_prompt,
    format_model_profile_options,
    json_dumps_for_prompt,
    parse_enroute_analysis_selection,
    parse_enroute_reference_analysis,
    select_enroute_analysis_from_summaries,
)

__all__ = [
    "ClothingStyleAnalysis",
    "DEFAULT_MODEL_PROFILE_OPTIONS",
    "ENROUTE_ANALYSIS_SELECTION_PROMPT_DIR",
    "ENROUTE_REFERENCE_ANALYSIS_PROMPT_DIR",
    "EnrouteAnalysisSelection",
    "EnrouteReferenceAnalysis",
    "ModelStyleAnalysis",
    "SceneStyleAnalysis",
    "SelectedModelProfile",
    "ShootingStyleAnalysis",
    "analyze_enroute_reference_image",
    "build_enroute_analysis_selection_payload",
    "build_enroute_analysis_selection_system_prompt",
    "build_enroute_reference_analysis_payload",
    "build_enroute_reference_analysis_system_prompt",
    "enroute_analysis_selection_user_prompt",
    "enroute_reference_analysis_user_prompt",
    "format_model_profile_options",
    "json_dumps_for_prompt",
    "parse_enroute_analysis_selection",
    "parse_enroute_reference_analysis",
    "select_enroute_analysis_from_summaries",
]
