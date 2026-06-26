from productv2.config import Settings
from productv2.reference_analysis import (
    build_enroute_analysis_selection_payload,
    build_enroute_reference_analysis_payload,
    format_model_profile_options,
    parse_enroute_analysis_selection,
    parse_enroute_reference_analysis,
)


def test_parse_enroute_reference_analysis_cleans_instruction_lists() -> None:
    analysis = parse_enroute_reference_analysis(
        """
        {
          "is_valid_wearing_reference": true,
          "summary": "适合项链佩戴图：短链和锁骨链很适配，中长链可用，长链需要更宽构图。",
          "selected_model_profile": {
            "profile_key": "romantic_rebel_european",
            "name": "Romantic Rebel",
            "image_path": "/tmp/model.jpg",
            "reason": "冷淡松弛气质最接近"
          },
          "model_style": {
            "face_style": "真实欧美日常创作者",
            "expression": "冷静，不营业",
            "skin_finish": "真实纹理，低妆感",
            "posture": "偏轴侧身，肩颈放松",
            "mood": "冷淡松弛"
          },
          "clothing_style": {
            "category": "细肩带基础上装",
            "silhouette": "贴身短款",
            "neckline_and_straps": "低领细肩带",
            "sleeve_and_length": "无袖，衣长在胸口附近",
            "fabric_texture": "细密棉质纹理",
            "material_weight": "轻薄柔软，有贴合感",
            "color_mood": "低饱和中性色",
            "fit_and_exposure": "露出肩颈和锁骨",
            "styling_details": "肩带自然贴合身体线条",
            "styling_keywords": ["低饱和", "", "日常新浪漫"]
          },
          "scene_style": {
            "mood": "安静、松弛",
            "spatial_feel": "近距离私密空间感",
            "background_feel": "简洁、低干扰",
            "color_temperature": "柔和偏暖",
            "texture_feel": "轻微粗粝"
          },
          "shooting_style": {
            "shot_type": "collarbone crop",
            "framing": "裁到下半脸和锁骨",
            "camera_angle": "轻微俯拍",
            "lighting": "柔和窗光",
            "lens_feel": "近距离杂志抓拍",
            "composition": "偏轴构图",
            "image_texture": "柔雾"
          },
          "reason": "适合作为项链佩戴参考"
        }
        """
    )

    assert analysis.is_valid_wearing_reference is True
    assert analysis.summary == (
        "适合项链佩戴图：短链和锁骨链很适配，中长链可用，长链需要更宽构图。"
    )
    assert analysis.selected_model_profile.profile_key == "romantic_rebel_european"
    assert analysis.selected_model_profile.image_path == "/tmp/model.jpg"
    assert analysis.shooting_style.shot_type == "collarbone crop"
    assert analysis.model_style.model_dump() == {
        "face_style": "真实欧美日常创作者",
        "expression": "冷静，不营业",
        "skin_finish": "真实纹理，低妆感",
        "posture": "偏轴侧身，肩颈放松",
        "mood": "冷淡松弛",
    }
    assert analysis.clothing_style.category == "细肩带基础上装"
    assert analysis.clothing_style.styling_keywords == ["低饱和", "日常新浪漫"]
    assert analysis.scene_style.background_feel == "简洁、低干扰"


def test_build_enroute_reference_analysis_payload_uses_responses_vision() -> None:
    payload = build_enroute_reference_analysis_payload(
        Settings(
            openai_model="gpt-test",
            enroute_analysis_temperature=0.9,
            enroute_analysis_top_p=0.8,
        ),
        "data:image/jpeg;base64,fixture",
        model_profiles=[
            {
                "profile_key": "romantic_rebel_european",
                "name": "Romantic Rebel",
                "image_path": "/tmp/model.jpg",
                "summary": "冷淡叛逆，适合蛇链。",
            }
        ],
    )

    assert payload["model"] == "gpt-test"
    assert payload["stream"] is True
    assert payload["temperature"] == 0.9
    assert payload["top_p"] == 0.8
    system_content = payload["input"][0]["content"]
    user_content = payload["input"][1]["content"]
    assert payload["input"][0]["role"] == "system"
    assert system_content[0]["type"] == "input_text"
    assert "Enroute Jewelry" in system_content[0]["text"]
    assert "clothing_style" in system_content[0]["text"]
    assert "scene_style" in system_content[0]["text"]
    assert "shooting_style" in system_content[0]["text"]
    assert "selected_model_profile" in system_content[0]["text"]
    assert "romantic_rebel_european" in system_content[0]["text"]
    assert "/tmp/model.jpg" in system_content[0]["text"]
    assert "product_context" not in system_content[0]["text"]
    assert "age_sense" not in system_content[0]["text"]
    assert "hair_style" not in system_content[0]["text"]
    assert "generation_instructions" not in system_content[0]["text"]
    assert "negative_instructions" not in system_content[0]["text"]
    assert user_content[1] == {
        "type": "input_image",
        "image_url": "data:image/jpeg;base64,fixture",
        "detail": "high",
    }


def test_format_model_profile_options_lists_summary_and_image_path() -> None:
    text = format_model_profile_options(
        [
            {
                "profile_key": "cool_romantic_black",
                "name": "Cool Romantic",
                "image_path": "/tmp/black-model.jpg",
                "summary": "冷静松弛，适合银链。",
            }
        ]
    )

    assert "profile_key=cool_romantic_black" in text
    assert "name=Cool Romantic" in text
    assert "image_path=/tmp/black-model.jpg" in text
    assert "冷静松弛" in text


def test_build_enroute_analysis_selection_payload_puts_summaries_in_system_prompt() -> None:
    payload = build_enroute_analysis_selection_payload(
        Settings(
            openai_model="gpt-test",
            enroute_analysis_temperature=0.7,
            enroute_analysis_top_p=0.8,
        ),
        "data:image/jpeg;base64,main",
        "data:image/jpeg;base64,size",
        [
            {
                "enroute_product_id": "necklaces:short",
                "summary": "适合短链，锁骨区域构图明确。",
            },
            {
                "enroute_product_id": "necklaces:long",
                "summary": "适合长链，需要更宽松的胸前范围。",
            },
        ],
    )

    system_text = payload["input"][0]["content"][0]["text"]
    user_content = payload["input"][1]["content"]

    assert payload["model"] == "gpt-test"
    assert payload["stream"] is True
    assert payload["temperature"] == 0.7
    assert payload["top_p"] == 0.8
    assert payload["input"][0]["role"] == "system"
    assert "逆向 JSON 摘要列表" in system_text
    assert "necklaces:short" in system_text
    assert "适合短链" in system_text
    assert "长 / 中 / 短" in system_text
    assert user_content[0]["type"] == "input_text"
    assert user_content[1] == {
        "type": "input_image",
        "image_url": "data:image/jpeg;base64,main",
        "detail": "high",
    }
    assert user_content[2] == {
        "type": "input_image",
        "image_url": "data:image/jpeg;base64,size",
        "detail": "high",
    }


def test_parse_enroute_analysis_selection_reads_minimal_json() -> None:
    selection = parse_enroute_analysis_selection(
        """
        {
          "selected_enroute_product_id": "necklaces:short",
          "reason": "当前尺寸参考更接近短链构图"
        }
        """
    )

    assert selection.selected_enroute_product_id == "necklaces:short"
    assert selection.reason == "当前尺寸参考更接近短链构图"
