"""1688 platform adapter."""

from __future__ import annotations

import re
from typing import Any

from productv2.models import CandidateProduct


_WEBP_RENDERED_IBANK_RE = re.compile(
    r"/img/ibank/.+\.(?:jpe?g|png)_\.webp(?:$|[?#])",
    re.IGNORECASE,
)


class Adapter:
    platform = "1688"

    def can_handle(self, candidate: CandidateProduct) -> bool:
        return candidate.platform == self.platform

    def get_main_images(self, candidate: CandidateProduct) -> list[str]:
        """Return product image URLs suitable for PDP/main images."""

        return _extract_main_image_urls(candidate.rawdata)

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


def _extract_main_image_urls(rawdata: dict[str, Any]) -> list[str]:
    explicit_urls = _extract_explicit_main_image_urls(rawdata)
    if explicit_urls:
        return explicit_urls

    urls = _extract_image_urls(rawdata)
    return _first_contiguous_image_block(urls, _is_main_carousel_image_url)


def _extract_explicit_main_image_urls(rawdata: dict[str, Any]) -> list[str]:
    detail = _detail(rawdata)
    candidates = (
        detail.get("main_image_urls"),
        detail.get("main_images"),
        detail.get("carousel_images"),
        detail.get("album_images"),
        rawdata.get("main_image_urls"),
        rawdata.get("main_images"),
        rawdata.get("carousel_images"),
        rawdata.get("album_images"),
    )
    urls: list[str] = []
    for candidate in candidates:
        urls.extend(
            url for url in _flatten_urls(candidate) if _is_product_image_url(url)
        )
    return _dedupe(urls)


def _first_contiguous_image_block(urls: list[str], predicate) -> list[str]:
    block: list[str] = []
    for url in urls:
        if predicate(url):
            block.append(url)
        elif block:
            break
    return block


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
    if not lower_url.startswith(("http://", "https://")):
        return False
    if "alicdn.com" not in lower_url:
        return False
    if lower_url.endswith(".svg"):
        return False
    if "_sum." in lower_url or lower_url.endswith("_sum.jpg"):
        return False
    if "-tps-" in lower_url:
        return False
    return (
        "/img/ibank/" in lower_url
        or "/imgextra/" in lower_url
    )


def _is_main_carousel_image_url(url: str) -> bool:
    """Match 1688 PDP carousel originals from the mixed DOM image list."""

    lower_url = url.lower()
    return (
        _is_product_image_url(url)
        and _WEBP_RENDERED_IBANK_RE.search(lower_url) is not None
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
