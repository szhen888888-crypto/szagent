"""Workflow path resolution helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from productv2.config import (
    DEFAULT_ENROUTE_BESTSELLERS_DIR,
    DEFAULT_MODEL_PROFILES_DIR,
    DEFAULT_PRODUCT_ASSETS_DIR,
    DEFAULT_WORKFLOW_LOGS_DIR,
    Settings,
)


WorkflowState = dict[str, Any]


def database_path(state: WorkflowState) -> Path:
    return Path(state.get("database_path") or Settings().productv2_database_path)


def raw_data_dir(state: WorkflowState) -> Path:
    return Path(state.get("raw_data_dir") or Settings().productv2_raw_data_dir)


def product_assets_dir(state: WorkflowState) -> Path:
    return Path(
        state.get("product_assets_dir")
        or Settings().productv2_product_assets_dir
        or DEFAULT_PRODUCT_ASSETS_DIR
    )


def enroute_bestsellers_dir(state: WorkflowState) -> Path:
    return Path(
        state.get("enroute_bestsellers_dir")
        or Settings().productv2_enroute_bestsellers_dir
        or DEFAULT_ENROUTE_BESTSELLERS_DIR
    )


def model_profiles_dir(state: WorkflowState) -> Path:
    return Path(
        state.get("model_profiles_dir")
        or Settings().productv2_model_profiles_dir
        or DEFAULT_MODEL_PROFILES_DIR
    )


def workflow_logs_dir(state: WorkflowState) -> Path:
    return Path(
        state.get("workflow_logs_dir")
        or Settings().productv2_workflow_logs_dir
        or DEFAULT_WORKFLOW_LOGS_DIR
    )
