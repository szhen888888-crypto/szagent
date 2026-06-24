import importlib.util
import json
import sys
from pathlib import Path

from PIL import Image


def load_downloader_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "enroute-bestsellers"
        / "download.py"
    )
    spec = importlib.util.spec_from_file_location("enroute_downloader", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_slugify_and_product_dir_name() -> None:
    downloader = load_downloader_module()

    assert downloader.slugify("Waterdrop Necklace!") == "waterdrop-necklace"
    assert downloader.product_dir_name(
        1,
        {"handle": "waterdrop-necklace", "title": "Waterdrop Necklace"},
    ) == "01-waterdrop-necklace"


def test_download_category_stops_between_target_and_max_images(
    monkeypatch,
    tmp_path,
) -> None:
    downloader = load_downloader_module()
    products = [
        {
            "id": 1,
            "title": "First",
            "handle": "first",
            "images": [
                {"position": 1, "src": "https://example.test/1.jpg"},
                {"position": 2, "src": "https://example.test/2.jpg"},
            ],
        },
        {
            "id": 2,
            "title": "Second",
            "handle": "second",
            "images": [
                {"position": 1, "src": "https://example.test/3.jpg"},
                {"position": 2, "src": "https://example.test/4.jpg"},
            ],
        },
        {
            "id": 3,
            "title": "Third",
            "handle": "third",
            "images": [
                {"position": 1, "src": "https://example.test/5.jpg"},
                {"position": 2, "src": "https://example.test/6.jpg"},
            ],
        },
    ]

    monkeypatch.setattr(
        downloader,
        "iter_best_selling_products",
        lambda client, category, page_size: iter(products),
    )

    def fake_download_image_as_jpeg(client, source_url, output_path, force=False):
        Image.new("RGB", (16, 16), "white").save(output_path)
        return {"status": "downloaded", "width": 16, "height": 16}

    monkeypatch.setattr(
        downloader,
        "download_image_as_jpeg",
        fake_download_image_as_jpeg,
    )

    summary = downloader.download_category(
        client=object(),
        category="necklaces",
        output_dir=tmp_path,
        min_images_per_category=3,
        target_images_per_category=4,
        max_images_per_category=5,
    )

    assert summary.category == "necklaces"
    assert summary.downloaded_images == 4
    assert summary.products_seen == 2
    assert summary.products_saved == 2
    assert (tmp_path / "necklaces" / "01-first" / "01.jpg").exists()
    metadata = json.loads(
        (tmp_path / "necklaces" / "01-first" / "metadata.json").read_text(
            encoding="utf-8"
        )
    )
    assert metadata["category"] == "necklaces"
    assert metadata["handle"] == "first"
    assert len(metadata["downloaded_images"]) == 2


def test_validate_image_bounds_rejects_invalid_values() -> None:
    downloader = load_downloader_module()

    try:
        downloader.validate_image_bounds(50, 40, 70)
    except ValueError as exc:
        assert "target-images-per-category" in str(exc)
    else:
        raise AssertionError("Expected invalid image bounds to raise ValueError")
