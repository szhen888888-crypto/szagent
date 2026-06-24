"""Platform adapter discovery."""

from productv2.adapters.registry import (
    adapter_module_name,
    get_platform_adapter,
    has_platform_adapter,
)

__all__ = [
    "adapter_module_name",
    "get_platform_adapter",
    "has_platform_adapter",
]
