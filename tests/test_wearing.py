from pathlib import Path

from PIL import Image

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


def test_generate_wearing_image_prepares_marked_inputs_and_prompt(tmp_path) -> None:
    main = tmp_path / "main.jpg"
    size = tmp_path / "size.jpg"
    model = tmp_path / "model.jpg"
    Image.new("RGB", (80, 100), "white").save(main)
    Image.new("RGB", (80, 100), "gray").save(size)
    Image.new("RGB", (80, 100), "blue").save(model)

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

    assert result["status"] == "reserved"
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
