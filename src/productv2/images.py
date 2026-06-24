"""Image download and collage helpers."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageOps

from productv2.config import DEFAULT_PRODUCT_ASSETS_DIR
from productv2.models import CandidateProduct


@dataclass(frozen=True)
class NumberedImageSource:
    index: int
    url: str
    path: Path | None = None


@dataclass(frozen=True)
class ImageCollageResult:
    path: Path
    source_images: list[NumberedImageSource]


def product_asset_dir(
    candidate: CandidateProduct,
    assets_dir: str | Path = DEFAULT_PRODUCT_ASSETS_DIR,
) -> Path:
    """Return the product-specific asset directory."""

    path = Path(assets_dir) / candidate.platform / candidate.product_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def merge_remote_images_to_collage(
    image_urls: list[str],
    output_path: str | Path,
    max_images: int = 6,
    tile_size: int = 512,
    timeout: float = 20.0,
) -> Path:
    """Download images and merge them into a single JPEG collage."""

    return merge_remote_images_to_numbered_collage(
        image_urls=image_urls,
        output_path=output_path,
        max_images=max_images,
        tile_size=tile_size,
        timeout=timeout,
    ).path


def merge_remote_images_to_numbered_collage(
    image_urls: list[str],
    output_path: str | Path,
    max_images: int = 6,
    tile_size: int = 512,
    timeout: float = 20.0,
) -> ImageCollageResult:
    """Download images and merge them into a numbered JPEG collage."""

    images: list[Image.Image] = []
    source_urls: list[str] = []
    for url in image_urls[:max_images]:
        image = _download_image(url, timeout=timeout)
        if image is not None:
            images.append(image)
            source_urls.append(url)

    if not images:
        raise ValueError("No downloadable images available for collage.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    numbered_source_paths = _save_numbered_source_images(images, output.parent)
    collage = build_image_collage(
        images,
        tile_size=tile_size,
        labels=[str(index) for index in range(1, len(images) + 1)],
    )
    collage.save(output, format="JPEG", quality=92, optimize=True)
    return ImageCollageResult(
        path=output,
        source_images=[
            NumberedImageSource(
                index=index,
                url=url,
                path=numbered_source_paths[index - 1],
            )
            for index, url in enumerate(source_urls, start=1)
        ],
    )


def build_image_collage(
    images: list[Image.Image],
    tile_size: int = 512,
    labels: list[str] | None = None,
) -> Image.Image:
    """Build a square-tile collage from already loaded images."""

    count = len(images)
    columns = min(3, count)
    rows = (count + columns - 1) // columns
    canvas = Image.new("RGB", (columns * tile_size, rows * tile_size), "white")

    for index, image in enumerate(images):
        prepared = ImageOps.contain(image.convert("RGB"), (tile_size, tile_size))
        tile = Image.new("RGB", (tile_size, tile_size), "white")
        x = (tile_size - prepared.width) // 2
        y = (tile_size - prepared.height) // 2
        tile.paste(prepared, (x, y))
        if labels and index < len(labels):
            _draw_label(tile, labels[index])
        canvas.paste(tile, ((index % columns) * tile_size, (index // columns) * tile_size))

    return canvas


def _draw_label(image: Image.Image, label: str) -> None:
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=36)
    padding = 12
    text_box = draw.textbbox((0, 0), label, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    box = (
        padding,
        padding,
        padding + text_width + 18,
        padding + text_height + 14,
    )
    draw.rectangle(box, fill="black")
    draw.text(
        (padding + 9, padding + 7),
        label,
        fill="white",
        font=font,
    )


def _save_numbered_source_images(images: list[Image.Image], output_dir: Path) -> list[Path]:
    source_dir = output_dir / "main_image_sources"
    source_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for index, image in enumerate(images, start=1):
        path = source_dir / f"{index}.jpg"
        image.convert("RGB").save(path, format="JPEG", quality=92, optimize=True)
        paths.append(path)
    return paths


def _download_image(url: str, timeout: float) -> Image.Image | None:
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).copy()
    except Exception:  # noqa: BLE001
        return None
