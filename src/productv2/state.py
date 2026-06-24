"""Process-wide product state synchronized with SQLite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from productv2.config import DEFAULT_DATABASE_PATH
from productv2.db import FAILED_STATUS
from productv2.db import update_product_fields
from productv2.models import CandidateProduct


_CURRENT_PRODUCT: CandidateProduct | None = None
_DATABASE_PATH: Path = DEFAULT_DATABASE_PATH
_EXTRAS: dict[str, Any] = {}


IMAGE_FIELDS = {
    "main_image",
    "wearing_image",
    "detail_image",
    "size_ratio_image",
    "multi_angle_image",
}


def initialize_product_state(
    product: CandidateProduct,
    database_path: str | Path = DEFAULT_DATABASE_PATH,
) -> CandidateProduct:
    """Initialize process-wide product state from a database product row."""

    global _CURRENT_PRODUCT, _DATABASE_PATH, _EXTRAS
    _CURRENT_PRODUCT = product
    _DATABASE_PATH = Path(database_path)
    _EXTRAS = {}
    return _CURRENT_PRODUCT


def get_current_product() -> CandidateProduct:
    if _CURRENT_PRODUCT is None:
        raise RuntimeError("Product state has not been initialized.")
    return _CURRENT_PRODUCT


def clear_product_state() -> None:
    global _CURRENT_PRODUCT, _EXTRAS
    _CURRENT_PRODUCT = None
    _EXTRAS = {}


def update_current_product(**fields: Any) -> CandidateProduct:
    """Update product state and synchronize mutable fields with SQLite."""

    global _CURRENT_PRODUCT
    current = get_current_product()
    updated = update_product_fields(
        database_path=_DATABASE_PATH,
        product_id=current.product_id,
        platform=current.platform,
        **fields,
    )
    _CURRENT_PRODUCT = updated
    return updated


def set_status(status: str) -> CandidateProduct:
    return update_current_product(status=status)


def mark_failed() -> CandidateProduct:
    return update_current_product(
        status=FAILED_STATUS,
        locked_at=None,
        locked_by=None,
    )


def set_image(field: str, value: str) -> CandidateProduct:
    if field not in IMAGE_FIELDS:
        raise ValueError(f"Unsupported image field: {field}")
    return update_current_product(**{field: value})


def set_extra(key: str, value: Any) -> None:
    """Set runtime-only state data that is not persisted to SQLite."""

    _EXTRAS[key] = value


def get_extra(key: str, default: Any = None) -> Any:
    return _EXTRAS.get(key, default)


def get_state_snapshot() -> dict[str, Any]:
    return {
        "product": get_current_product().model_dump(),
        "extras": dict(_EXTRAS),
    }
