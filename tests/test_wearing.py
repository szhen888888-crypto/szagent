from pathlib import Path

import pytest
from PIL import Image

import productv2.wearing as wearing_module
from productv2.config import Settings
from productv2.image_generation import ImageGenerationResult
from productv2.models import CandidateProduct
from productv2.wearing import build_wearing_prompt_compiler_payload
from productv2.wearing import compile_wearing_generation_prompt
from productv2.wearing import create_labeled_reference_image
from productv2.wearing import generate_wearing_image
from productv2.wearing import trim_compiled_wearing_prompt
from productv2.wearing import WEARING_PROMPT_COMPILER_MAX_OUTPUT_CHARS


def test_create_labeled_reference_image_adds_white_bottom_bar(tmp_path) -> None:
    source = tmp_path / "source.jpg"
    Image.new("RGB", (80, 100), "red").save(source)

    output = create_labeled_reference_image(source, tmp_path / "marked.jpg", "01 主图")

    with Image.open(output) as image:
        assert image.size[0] == 80
        assert image.size[1] > 100
        assert image.getpixel((40, image.size[1] - 4)) == (255, 255, 255)


def test_build_wearing_prompt_compiler_payload_uses_material_contract() -> None:
    payload = build_wearing_prompt_compiler_payload(
        CandidateProduct(product_id="p-1", platform="1688", rawdata={}),
        {
            "summary": "适合短链和锁骨链。",
            "analysis": {"shooting_style": {"shot_type": "collarbone crop"}},
        },
        {
            "profile_key": "romantic_rebel_european",
            "name": "Romantic Rebel",
            "image_path": "/tmp/model.jpg",
        },
        selection_reason="气质匹配",
        settings=Settings(openai_model="gpt-test"),
    )
    system_text = payload["input"][0]["content"][0]["text"]

    assert payload["model"] == "gpt-test"
    assert payload["stream"] is True
    assert payload["max_output_tokens"] == 1600
    assert "图 01 标记为主图" in system_text
    assert "图 02 标记为尺寸参考图" in system_text
    assert "产品锁定" in system_text
    assert "尺寸佩戴锁定" in system_text
    assert "最终生成文字必须使用中文" in system_text
    assert "JSON 风格多维参数 prompt" in system_text
    assert "最终 prompt 必须使用 JSON 风格多维参数定位照片" in system_text
    assert "Enroute滤镜与后期" in system_text
    assert "无法从 Enroute profile 精确推断时" in system_text
    assert "目光与面向角度" in system_text
    assert "gaze_direction" in system_text
    assert "face_yaw_relative_to_camera" in system_text
    assert "face_pitch_relative_to_camera" in system_text
    assert "torso_yaw_relative_to_camera" in system_text
    assert "相对摄像机角度" in system_text
    assert "不是拼接所有材料" in system_text
    assert "最大输出 5000 字符" in system_text
    assert "禁止湿发" in system_text
    assert "wet hair" in system_text
    assert "滤镜基调" in system_text
    assert "romantic_rebel_european" in system_text
    assert "collarbone crop" in system_text


def test_trim_compiled_wearing_prompt_limits_output_to_5000_chars() -> None:
    long_prompt = "x" * (WEARING_PROMPT_COMPILER_MAX_OUTPUT_CHARS + 100)

    trimmed = trim_compiled_wearing_prompt(long_prompt)

    assert len(trimmed) == WEARING_PROMPT_COMPILER_MAX_OUTPUT_CHARS


def test_compile_wearing_generation_prompt_prepares_marked_inputs(
    monkeypatch,
    tmp_path,
) -> None:
    main = tmp_path / "main.jpg"
    size = tmp_path / "size.jpg"
    model = tmp_path / "model.jpg"
    Image.new("RGB", (80, 100), "white").save(main)
    Image.new("RGB", (80, 100), "gray").save(size)
    Image.new("RGB", (80, 100), "blue").save(model)

    def fake_request_compiled_wearing_prompt(**kwargs):
        assert kwargs["model_profile"]["profile_key"] == "romantic_rebel_european"
        assert len(kwargs["input_images"]) == 3
        return "compiled prompt with collarbone crop"

    monkeypatch.setattr(
        wearing_module,
        "request_compiled_wearing_prompt",
        fake_request_compiled_wearing_prompt,
    )

    result = compile_wearing_generation_prompt(
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
            "image_path": "/tmp/enroute/02.jpg",
            "analysis": {"shooting_style": {"shot_type": "collarbone crop"}},
        },
        {
            "profile_key": "romantic_rebel_european",
            "name": "Romantic Rebel",
            "image_path": str(model),
        },
        output_dir=tmp_path / "product",
    )

    assert result["status"] == "ok"
    assert result["reason"] == "wearing_generation_prompt_compiled"
    assert result["prompt"] == "compiled prompt with collarbone crop"
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
    for image_path in result["input_images"]:
        assert Path(image_path).exists()


def test_compile_wearing_generation_prompt_removes_stale_marked_inputs(
    monkeypatch,
    tmp_path,
) -> None:
    main = tmp_path / "main.jpg"
    size = tmp_path / "size.jpg"
    model = tmp_path / "model.jpg"
    Image.new("RGB", (80, 100), "white").save(main)
    Image.new("RGB", (80, 100), "gray").save(size)
    Image.new("RGB", (80, 100), "blue").save(model)
    marked_dir = tmp_path / "product" / "wearing_generation_inputs"
    marked_dir.mkdir(parents=True)
    stale_input = marked_dir / "stale.jpg"
    stale_input.write_text("stale", encoding="utf-8")

    monkeypatch.setattr(
        wearing_module,
        "request_compiled_wearing_prompt",
        lambda **_kwargs: "compiled prompt",
    )

    compile_wearing_generation_prompt(
        CandidateProduct(product_id="p-1", platform="1688", rawdata={}),
        {
            "image_numbers": [2],
            "selected_images": {
                "main_image": {"path": str(main)},
                "size_reference_image": {"path": str(size)},
            },
        },
        {"image_path": "/tmp/enroute/02.jpg"},
        {
            "profile_key": "romantic_rebel_european",
            "name": "Romantic Rebel",
            "image_path": str(model),
        },
        output_dir=tmp_path / "product",
    )

    assert sorted(path.name for path in marked_dir.iterdir()) == [
        "01_main_image.jpg",
        "02_size_reference.jpg",
    ]
    assert not stale_input.exists()


def test_generate_wearing_image_uses_compiled_prompt(
    monkeypatch,
    tmp_path,
) -> None:
    main = tmp_path / "01_main_image.jpg"
    size = tmp_path / "02_size_reference.jpg"
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
            assert prompt == "compiled prompt"
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
            "status": "ok",
            "prompt": "compiled prompt",
            "input_images": [str(main), str(size), str(model)],
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
                "status": "ok",
                "prompt": "compiled prompt",
                "input_images": [str(main), str(size)],
            },
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
                "status": "ok",
                "prompt": "compiled prompt",
                "input_images": [str(main), str(size)],
            },
            tmp_path / "product",
        )
