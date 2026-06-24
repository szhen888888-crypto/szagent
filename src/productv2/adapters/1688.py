"""1688 platform adapter."""

from __future__ import annotations

from typing import Any

from productv2.models import CandidateProduct


class Adapter:
    platform = "1688"

    def can_handle(self, candidate: CandidateProduct) -> bool:
        return candidate.platform == self.platform

    def get_main_images(self, candidate: CandidateProduct) -> list[str]:
        """Return product image URLs suitable for PDP/main images."""

        return [
            url
            for url in _extract_image_urls(candidate.rawdata)
            if _is_product_image_url(url)
        ]

    def get_specification_images(self, candidate: CandidateProduct) -> list[str]:
        """Return specification image URLs when present in raw 1688 data."""

        detail = _detail(candidate.rawdata)
        spec_sources = (
            detail.get("specification_images"),
            detail.get("sku_images"),
            detail.get("spec_images"),
            candidate.rawdata.get("specification_images"),
            candidate.rawdata.get("sku_images"),
            candidate.rawdata.get("spec_images"),
        )
        images: list[str] = []
        for source in spec_sources:
            images.extend(_flatten_urls(source))
        return _dedupe(images)


def _detail(rawdata: dict[str, Any]) -> dict[str, Any]:
    detail = rawdata.get("detail")
    return detail if isinstance(detail, dict) else {}


def _extract_image_urls(rawdata: dict[str, Any]) -> list[str]:
    detail = _detail(rawdata)
    candidates = (
        detail.get("image_urls"),
        rawdata.get("image_urls"),
        rawdata.get("images"),
    )
    urls: list[str] = []
    for candidate in candidates:
        urls.extend(_flatten_urls(candidate))
    return _dedupe(urls)


def _flatten_urls(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.startswith(("http://", "https://")) else []
    if isinstance(value, dict):
        urls: list[str] = []
        for nested_value in value.values():
            urls.extend(_flatten_urls(nested_value))
        return urls
    if isinstance(value, list):
        urls = []
        for item in value:
            urls.extend(_flatten_urls(item))
        return urls
    return []


def _is_product_image_url(url: str) -> bool:
    lower_url = url.lower()
    return (
        lower_url.startswith(("http://", "https://"))
        and not lower_url.endswith(".svg")
        and "alicdn.com" in lower_url
    )


def _dedupe(urls: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped
