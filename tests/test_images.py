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
