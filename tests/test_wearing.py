from pathlib import Path

import pytest
from PIL import Image

import productv2.wearing as wearing_module
from productv2.config import Settings
from productv2.image_generation import ImageGenerationResult
from productv2.models import CandidateProduct
from productv2.wearing import build_wearing_image_prompt
from productv2.wearing import create_labeled_reference_image
from productv2.wearing import generate_wearing_image


def test_create_labeled_reference_image_adds_white_bottom_bar(tmp_path) -> None:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (80, 100), "red").save(source)

    output = create_labeled_reference_image(source, tmp_path / "marked.jpg", "01 主图")

    with Image.open(output) as image:
        assert image.size[0] == 80
        assert image.size[1] > 100
        assert image.getpixel((40, image.size[1] - 4)) == (255, 255, 255)


def test_build_wearing_image_prompt_uses_analysis_and_consistency_rules() -> None:
    prompt = build_wearing_image_prompt(
        CandidateProduct(product_id="p-1", platform="1688", rawdata={}),
        {
            "summary": "适合短链和锁骨链。",
            "reference_image_path": "/tmp/enroute/02.jpg",
            "analysis": {
                "selected_model_profile": {
                    "profile_key": "romantic_rebel_european",
                    "name": "Romantic Rebel",
                    "image_path": "/tmp/model.jpg",
                    "reason": "气质匹配",
                },
                "model_style": {"mood": "冷淡松弛"},
                "clothing_style": {"category": "细肩带贴身上衣"},
            },
        },
    )

    assert "参考图 01 标记为主图" in prompt
    assert "参考图 02 标记为尺寸参考图" in prompt
    assert "产品一致性" in prompt
    assert "尺寸一致性" in prompt
    assert "适合短链和锁骨链" in prompt
    assert "细肩带贴身上衣" in prompt
    assert "romantic_rebel_european" in prompt
    assert "/tmp/model.jpg" in prompt


def test_generate_wearing_image_prepares_marked_inputs_and_prompt(
    monkeypatch,
    tmp_path,
) -> None:
    main = tmp_path / "main.jpg"
    size = tmp_path / "size.jpg"
    model = tmp_path / "model.jpg"
    generated = tmp_path / "generated.png"
    Image.new("RGB", (80, 100), "white").save(main)
    Image.new("RGB", (80, 100), "gray").save(size)
    Image.new("RGB", (80, 100), "blue").save(model)
    Image.new("RGB", (80, 100), "green").save(generated)
    data_url = wearing_module.image_file_to_data_url(generated)

    class FakeImageGenerator:
        settings = Settings(image_generation_api_key="sk-test")

        def generate(self, *, prompt, images, wait):
            assert wait is True
            assert "collarbone crop" in prompt
            assert len(images) == 3
            return ImageGenerationResult(
                id="task-1",
                status="succeeded",
                progress=100,
                urls=[data_url],
            )

    monkeypatch.setattr(
        wearing_module,
        "get_image_generator",
        lambda logger=None: FakeImageGenerator(),
    )

    result = generate_wearing_image(
        CandidateProduct(product_id="p-1", platform="1688", rawdata={}),
        {
            "image_numbers": [2],
            "selected_images": {
                "main_image": {"path": str(main)},
                "size_reference_image": {"path": str(size)},
            },
        },
        {
            "summary": "适合短链和锁骨链。",
            "reference_image_path": "/tmp/enroute/02.jpg",
            "analysis": {
                "selected_model_profile": {
                    "profile_key": "romantic_rebel_european",
                    "name": "Romantic Rebel",
                    "image_path": str(model),
                    "reason": "气质匹配",
                },
                "shooting_style": {"shot_type": "collarbone crop"},
            },
        },
        tmp_path / "product",
    )

    assert result["status"] == "ok"
    assert result["reason"] == "wearing_image_generated"
    assert result["attempt"] == 1
    assert result["generated_image_path"] == str(
        tmp_path / "product" / "wearing_image_attempt_1.png"
    )
    assert Path(result["generated_image_path"]).exists()
    assert result["input_images"] == [
        str(tmp_path / "product" / "wearing_generation_inputs" / "01_main_image.jpg"),
        str(
            tmp_path
            / "product"
            / "wearing_generation_inputs"
            / "02_size_reference.jpg"
        ),
        str(model),
    ]
    assert result["enroute_reference_image_path"] == "/tmp/enroute/02.jpg"
    assert result["selected_model_profile"]["profile_key"] == "romantic_rebel_european"
    assert "collarbone crop" in result["prompt"]
    for image_path in result["input_images"]:
        assert Path(image_path).exists()


def test_generate_wearing_image_raises_image_generation_exception(
    monkeypatch,
    tmp_path,
) -> None:
    main = tmp_path / "main.jpg"
    size = tmp_path / "size.jpg"
    Image.new("RGB", (80, 100), "white").save(main)
    Image.new("RGB", (80, 100), "gray").save(size)

    class FakeImageGenerator:
        settings = Settings(image_generation_api_key="sk-test")

        def generate(self, **_kwargs):
            raise RuntimeError("HTTP 503")

    monkeypatch.setattr(
        wearing_module,
        "get_image_generator",
        lambda logger=None: FakeImageGenerator(),
    )

    with pytest.raises(RuntimeError, match="HTTP 503"):
        generate_wearing_image(
            CandidateProduct(product_id="p-1", platform="1688", rawdata={}),
            {
                "image_numbers": [2],
                "selected_images": {
                    "main_image": {"path": str(main)},
                    "size_reference_image": {"path": str(size)},
                },
            },
            {},
            tmp_path / "product",
        )


def test_generate_wearing_image_raises_when_generation_status_failed(
    monkeypatch,
    tmp_path,
) -> None:
    main = tmp_path / "main.jpg"
    size = tmp_path / "size.jpg"
    Image.new("RGB", (80, 100), "white").save(main)
    Image.new("RGB", (80, 100), "gray").save(size)

    class FakeImageGenerator:
        settings = Settings(image_generation_api_key="sk-test")

        def generate(self, **_kwargs):
            return ImageGenerationResult(
                id="task-1",
                status="failed",
                progress=100,
                error="third party error",
            )

    monkeypatch.setattr(
        wearing_module,
        "get_image_generator",
        lambda logger=None: FakeImageGenerator(),
    )

    with pytest.raises(RuntimeError, match="Image generation did not succeed"):
        generate_wearing_image(
            CandidateProduct(product_id="p-1", platform="1688", rawdata={}),
            {
                "image_numbers": [2],
                "selected_images": {
                    "main_image": {"path": str(main)},
                    "size_reference_image": {"path": str(size)},
                },
            },
            {},
            tmp_path / "product",
        )
