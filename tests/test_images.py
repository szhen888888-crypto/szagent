from PIL import Image

from productv2.images import build_image_collage, merge_remote_images_to_numbered_collage
from productv2.images import product_asset_dir
from productv2.models import CandidateProduct


def test_build_image_collage_creates_grid() -> None:
    images = [
        Image.new("RGB", (100, 200), "red"),
        Image.new("RGB", (200, 100), "blue"),
        Image.new("RGB", (120, 120), "green"),
    ]

    collage = build_image_collage(images, tile_size=64)

    assert collage.size == (192, 64)


def test_product_asset_dir_uses_platform_and_product_id(tmp_path) -> None:
    candidate = CandidateProduct(
        product_id="p-1",
        platform="1688",
        rawdata={},
    )

    path = product_asset_dir(candidate, tmp_path)

    assert path == tmp_path / "1688" / "p-1"
    assert path.exists()


def test_merge_remote_images_to_numbered_collage_saves_source_images(
    monkeypatch,
    tmp_path,
) -> None:
    def fake_download_image(url, timeout):
        return Image.new("RGB", (32, 32), "red")

    monkeypatch.setattr("productv2.images._download_image", fake_download_image)

    result = merge_remote_images_to_numbered_collage(
        ["https://example.test/a.jpg"],
        tmp_path / "product" / "main_image_collage.jpg",
    )

    source = result.source_images[0]
    assert source.index == 1
    assert source.url == "https://example.test/a.jpg"
    assert source.path == tmp_path / "product" / "main_image_sources" / "1.jpg"
    assert source.path.exists()


def test_merge_remote_images_to_numbered_collage_removes_stale_sources(
    monkeypatch,
    tmp_path,
) -> None:
    def fake_download_image(url, timeout):
        return Image.new("RGB", (32, 32), "red")

    product_dir = tmp_path / "product"
    source_dir = product_dir / "main_image_sources"
    source_dir.mkdir(parents=True)
    stale_source = source_dir / "6.jpg"
    stale_source.write_text("stale", encoding="utf-8")
    stale_collage = product_dir / "main_image_collage.jpg"
    stale_collage.write_text("stale", encoding="utf-8")

    monkeypatch.setattr("productv2.images._download_image", fake_download_image)

    result = merge_remote_images_to_numbered_collage(
        ["https://example.test/a.jpg", "https://example.test/b.jpg"],
        stale_collage,
    )

    assert [source.index for source in result.source_images] == [1, 2]
    assert sorted(path.name for path in source_dir.glob("*.jpg")) == ["1.jpg", "2.jpg"]
    assert not stale_source.exists()


def test_merge_remote_images_to_numbered_collage_collects_successful_images_after_failures(
    monkeypatch,
    tmp_path,
) -> None:
    def fake_download_image(url, timeout):
        if "bad" in url:
            return None
        return Image.new("RGB", (32, 32), "red")

    monkeypatch.setattr("productv2.images._download_image", fake_download_image)

    result = merge_remote_images_to_numbered_collage(
        [
            "https://example.test/1.jpg",
            "https://example.test/bad-2.jpg",
            "https://example.test/3.jpg",
            "https://example.test/bad-4.jpg",
            "https://example.test/5.jpg",
        ],
        tmp_path / "product" / "main_image_collage.jpg",
        max_images=3,
    )

    assert [source.url for source in result.source_images] == [
        "https://example.test/1.jpg",
        "https://example.test/3.jpg",
        "https://example.test/5.jpg",
    ]
