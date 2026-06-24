"""Adapter module discovery helpers."""

from __future__ import annotations

import importlib
import importlib.util
import re
from typing import Any


ADAPTERS_PACKAGE = "productv2.adapters"


def adapter_module_name(platform: str) -> str:
    """Normalize a platform name to an adapter module filename."""

    normalized = re.sub(r"[^0-9a-zA-Z_]+", "_", platform.strip().lower()).strip("_")
    if not normalized:
        raise ValueError("Platform name is empty.")
    return normalized


def has_platform_adapter(platform: str) -> bool:
    """Return whether an adapter module exists for the platform."""

    module_name = f"{ADAPTERS_PACKAGE}.{adapter_module_name(platform)}"
    return importlib.util.find_spec(module_name) is not None


def get_platform_adapter(platform: str) -> Any:
    """Load and instantiate the platform adapter."""

    module_name = f"{ADAPTERS_PACKAGE}.{adapter_module_name(platform)}"
    module = importlib.import_module(module_name)
    adapter_class = getattr(module, "Adapter")
    return adapter_class()
