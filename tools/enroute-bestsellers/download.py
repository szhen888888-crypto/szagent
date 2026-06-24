"""Download Enroute best-selling product image references."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

import httpx
from PIL import Image, ImageOps


BASE_URL = "https://enroutejewelry.com/collections/{category}/products.json"
DEFAULT_CATEGORIES = ("earrings", "bracelets", "necklaces", "rings")
DEFAULT_OUTPUT_DIR = Path("enroute-bestsellers")
DEFAULT_PAGE_SIZE = 20
DEFAULT_MIN_IMAGES_PER_CATEGORY = 50
DEFAULT_TARGET_IMAGES_PER_CATEGORY = 60
DEFAULT_MAX_IMAGES_PER_CATEGORY = 70
DEFAULT_TIMEOUT = 30.0
SORT_BY = "best-selling"


@dataclass(frozen=True)
class CategorySummary:
    category: str
    products_seen: int
    products_saved: int
    downloaded_images: int
    skipped_images: int
    output_dir: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Enroute best-selling product images by category.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for the downloaded Enroute image library.",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=list(DEFAULT_CATEGORIES),
        help="Enroute collection categories to download.",
    )
    parser.add_argument(
        "--min-images-per-category",
        type=int,
        default=DEFAULT_MIN_IMAGES_PER_CATEGORY,
        help="Preferred lower bound for images per category.",
    )
    parser.add_argument(
        "--target-images-per-category",
        type=int,
        default=DEFAULT_TARGET_IMAGES_PER_CATEGORY,
        help="Target images per category; selected products are kept whole when possible.",
    )
    parser.add_argument(
        "--max-images-per-category",
        type=int,
        default=DEFAULT_MAX_IMAGES_PER_CATEGORY,
        help="Hard upper bound for images per category.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="Shopify products.json page size.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download images even when local files already exist.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    validate_image_bounds(
        args.min_images_per_category,
        args.target_images_per_category,
        args.max_images_per_category,
    )

    with httpx.Client(
        timeout=args.timeout,
        follow_redirects=True,
        headers={"User-Agent": "productv2-enroute-downloader/1.0"},
    ) as client:
        summaries = [
            download_category(
                client=client,
                category=category,
                output_dir=args.output_dir,
                min_images_per_category=args.min_images_per_category,
                target_images_per_category=args.target_images_per_category,
                max_images_per_category=args.max_images_per_category,
                page_size=args.page_size,
                force=args.force,
            )
            for category in args.categories
        ]

    print(json.dumps([asdict(summary) for summary in summaries], indent=2))


def validate_image_bounds(min_images: int, target_images: int, max_images: int) -> None:
    if min_images < 1:
        raise ValueError("min-images-per-category must be positive")
    if target_images < min_images:
        raise ValueError("target-images-per-category must be >= min-images-per-category")
    if max_images < target_images:
        raise ValueError("max-images-per-category must be >= target-images-per-category")


def download_category(
    client: httpx.Client,
    category: str,
    output_dir: Path,
    min_images_per_category: int = DEFAULT_MIN_IMAGES_PER_CATEGORY,
    target_images_per_category: int = DEFAULT_TARGET_IMAGES_PER_CATEGORY,
    max_images_per_category: int = DEFAULT_MAX_IMAGES_PER_CATEGORY,
    page_size: int = DEFAULT_PAGE_SIZE,
    force: bool = False,
) -> CategorySummary:
    """Download best-selling product images for one Enroute category."""

    validate_image_bounds(
        min_images_per_category,
        target_images_per_category,
        max_images_per_category,
    )

    category_output_dir = output_dir / category
    category_output_dir.mkdir(parents=True, exist_ok=True)
    downloaded_images = 0
    skipped_images = 0
    products_seen = 0
    products_saved = 0

    for product in iter_best_selling_products(client, category, page_size=page_size):
        products_seen += 1
        images = product_images(product)
        if not images:
            continue
        if (
            downloaded_images >= min_images_per_category
            and downloaded_images + len(images) > max_images_per_category
        ):
            break

        product_dir = category_output_dir / product_dir_name(products_seen, product)
        product_dir.mkdir(parents=True, exist_ok=True)
        product_downloads: list[dict[str, Any]] = []
        product_skipped = 0

        for image_index, image in enumerate(images, start=1):
            if downloaded_images >= max_images_per_category:
                product_skipped += 1
                skipped_images += 1
                continue

            image_url = str(image.get("src") or "")
            if not image_url:
                product_skipped += 1
                skipped_images += 1
                continue

            image_path = product_dir / f"{image_index:02d}.jpg"
            try:
                image_metadata = download_image_as_jpeg(
                    client,
                    image_url,
                    image_path,
                    force=force,
                )
            except Exception as exc:  # noqa: BLE001
                product_downloads.append(
                    {
                        "position": image.get("position"),
                        "source_url": image_url,
                        "local_file": image_path.name,
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                skipped_images += 1
                product_skipped += 1
                continue

            downloaded_images += 1
            product_downloads.append(
                {
                    "position": image.get("position"),
                    "source_url": image_url,
                    "local_file": image_path.name,
                    **image_metadata,
                }
            )

        write_product_metadata(
            product_dir=product_dir,
            category=category,
            product=product,
            images=product_downloads,
            skipped_images=product_skipped,
        )
        products_saved += 1

        if downloaded_images >= target_images_per_category:
            break

    return CategorySummary(
        category=category,
        products_seen=products_seen,
        products_saved=products_saved,
        downloaded_images=downloaded_images,
        skipped_images=skipped_images,
        output_dir=str(category_output_dir),
    )


def iter_best_selling_products(
    client: httpx.Client,
    category: str,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> Iterable[dict[str, Any]]:
    """Yield Enroute products in Shopify best-selling order."""

    seen_product_ids: set[int] = set()
    page = 1
    while True:
        response = client.get(
            BASE_URL.format(category=category),
            params={
                "sort_by": SORT_BY,
                "limit": page_size,
                "page": page,
            },
        )
        response.raise_for_status()
        products = response.json().get("products", [])
        if not products:
            break

        yielded = 0
        for product in products:
            product_id = product.get("id")
            if product_id in seen_product_ids:
                continue
            seen_product_ids.add(product_id)
            yielded += 1
            yield product

        if yielded == 0:
            break
        page += 1


def product_images(product: dict[str, Any]) -> list[dict[str, Any]]:
    images = product.get("images")
    if not isinstance(images, list):
        return []
    return [
        image
        for image in sorted(images, key=lambda item: item.get("position") or 0)
        if isinstance(image, dict)
    ]


def product_dir_name(product_index: int, product: dict[str, Any]) -> str:
    name = str(product.get("handle") or product.get("title") or "product")
    return f"{product_index:02d}-{slugify(name)}"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "product"


def download_image_as_jpeg(
    client: httpx.Client,
    source_url: str,
    output_path: Path,
    force: bool = False,
) -> dict[str, Any]:
    if output_path.exists() and not force:
        with Image.open(output_path) as image:
            return {
                "status": "exists",
                "width": image.width,
                "height": image.height,
            }

    response = client.get(source_url)
    response.raise_for_status()
    image = Image.open(BytesIO(response.content))
    image = ImageOps.exif_transpose(image).convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, format="JPEG", quality=92, optimize=True)
    return {
        "status": "downloaded",
        "width": image.width,
        "height": image.height,
    }


def write_product_metadata(
    product_dir: Path,
    category: str,
    product: dict[str, Any],
    images: list[dict[str, Any]],
    skipped_images: int,
) -> None:
    metadata = {
        "category": category,
        "product_id": product.get("id"),
        "title": product.get("title"),
        "handle": product.get("handle"),
        "product_type": product.get("product_type"),
        "vendor": product.get("vendor"),
        "sort_by": SORT_BY,
        "source_url": f"https://enroutejewelry.com/products/{product.get('handle')}",
        "downloaded_images": [
            image for image in images if image.get("status") in {"downloaded", "exists"}
        ],
        "failed_images": [image for image in images if image.get("status") == "failed"],
        "skipped_images": skipped_images,
    }
    (product_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
