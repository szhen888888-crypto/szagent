"""Candidate product data loading utilities."""

from __future__ import annotations

import json
from pathlib import Path

from productv2.config import DEFAULT_CANDIDATE_DATA
from productv2.models import CandidateProduct


def load_candidate_products(
    data_path: str | Path = DEFAULT_CANDIDATE_DATA,
    limit: int | None = None,
) -> list[CandidateProduct]:
    """Load candidate product records from the repository JSON data."""

    return load_candidate_products_from_json_file(data_path=data_path, limit=limit)


def load_candidate_products_from_json_file(
    data_path: str | Path,
    limit: int | None = None,
) -> list[CandidateProduct]:
    """Load candidate product records from a JSON file.

    Supported JSON shapes:
    - a list of candidate product records
    - one candidate product record object
    - an object containing a records list under products, items, data, or records
    """

    path = Path(data_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = _extract_candidate_records(payload, path)

    selected_records = records[:limit] if limit is not None else records
    return [CandidateProduct.model_validate(record) for record in selected_records]


def _extract_candidate_records(payload: object, path: Path) -> list[object]:
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        if {"product_id", "platform"}.issubset(payload):
            return [payload]

        for key in ("products", "items", "data", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return value

    raise ValueError(f"Expected candidate product records in {path}")
