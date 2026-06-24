"""Domain models for candidate products and listing drafts."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field


class CandidateProduct(BaseModel):
    id: int | None = None
    product_id: str
    platform: str
    rawdata: dict[str, Any] = Field(default_factory=dict)
    status: str | None = None
    main_image: str = ""
    wearing_image: str = ""
    detail_image: str = ""
    size_ratio_image: str = ""
    multi_angle_image: str = ""
    locked_at: str | None = None
    locked_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ListingDraft(BaseModel):
    product_id: str
    platform: str
    title: str
    source_url: str | None = None
    price_text: str | None = None
    material: str | None = None
    moq_text: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: Literal["draft"] = "draft"
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_candidate(cls, candidate: CandidateProduct) -> "ListingDraft":
        rawdata = candidate.rawdata
        detail = rawdata.get("detail") if isinstance(rawdata.get("detail"), dict) else {}

        title = _clean_text(str(rawdata.get("title") or ""))
        source_url = rawdata.get("url") or rawdata.get("requested_url")
        warnings: list[str] = []

        if not title:
            warnings.append("missing_title")
        if not source_url:
            warnings.append("missing_source_url")

        return cls(
            product_id=candidate.product_id,
            platform=candidate.platform,
            title=title,
            source_url=str(source_url) if source_url else None,
            price_text=_optional_text(detail.get("price_text")),
            material=_optional_text(detail.get("material")),
            moq_text=_optional_text(detail.get("moq_text")),
            tags=_extract_tags(rawdata),
            warnings=warnings,
        )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _clean_text(str(value))
    return text or None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_tags(rawdata: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for key in ("motif_id", "candidate_id", "platform"):
        value = rawdata.get(key)
        if value:
            tags.append(str(value))
    return tags
