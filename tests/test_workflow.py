import json
import sqlite3
from pathlib import Path

from PIL import Image

import productv2.graph as graph_module
from productv2.graph import run_listing_workflow
from productv2.state import get_extra


def test_listing_workflow_builds_drafts_from_candidate_data(tmp_path) -> None:
    data_path = tmp_path / "candidates.json"
    log_dir = tmp_path / "logs"
    data_path.write_text(
        json.dumps(
            [
                {
                    "product_id": "fixture-1",
                    "platform": "1688",
                    "rawdata": {
                        "title": "Fixture Product 1",
                        "url": "https://example.test/fixture-1",
                    },
                },
                {
                    "product_id": "fixture-2",
                    "platform": "1688",
                    "rawdata": {
                        "title": "Fixture Product 2",
                        "url": "https://example.test/fixture-2",
                    },
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = run_listing_workflow(data_path=data_path, limit=2, workflow_logs_dir=log_dir)

    assert result["metrics"]["candidate_count"] == 2
    assert result["metrics"]["draft_count"] == 2
    assert len(result["drafts"]) == 2
    assert result["drafts"][0]["product_id"]
    assert result["drafts"][0]["title"]
    log_path = Path(result["metrics"]["workflow_log_path"])
    assert log_path.exists()
    assert log_path.parent == log_dir
    assert log_path.suffix == ".log"
    assert log_path.name.startswith("Fixture Product 1__1688__fixture-1")
    log_text = log_path.read_text(encoding="utf-8")
    assert "事件：工作流开始" in log_text
    assert "事件：逻辑单元开始" in log_text
    assert "逻辑单元：load_candidates" in log_text
    assert "事件：逻辑单元结束" in log_text
    assert "逻辑单元：prepare_review_queue" in log_text
    assert "事件：工作流结束" in log_text


def test_listing_workflow_falls_back_to_database_when_json_missing(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    missing_data_path = tmp_path / "missing.json"

    from productv2.db import seed_candidate_products

    data_path = tmp_path / "candidates.json"
    data_path.write_text(
        json.dumps(
            [
                {
                    "product_id": "db-fixture-1",
                    "platform": "1688",
                    "rawdata": {
                        "title": "Database Fixture Product",
                        "url": "https://example.test/db-fixture-1",
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    seed_candidate_products(database_path=database_path, data_path=data_path)

    result = run_listing_workflow(
        data_path=missing_data_path,
        database_path=database_path,
        limit=1,
    )

    assert result["metrics"]["candidate_source"] == "database_adapter_selection"
    assert result["metrics"]["candidate_count"] == 1
    assert result["metrics"]["unfinished_count"] == 1
    assert result["metrics"]["selected_adapter"] == "1688"
    assert result["metrics"]["skipped_without_adapter_count"] == 0
    assert result["metrics"]["main_image_result"]["status"] == "failed"
    assert result["metrics"]["size_reference_result"]["status"] == "skipped"
    assert result["drafts"][0]["product_id"] == "db-fixture-1"


def test_listing_workflow_merges_main_images_without_updating_database(
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    missing_data_path = tmp_path / "missing.json"
    assets_dir = tmp_path / "products"
    log_dir = tmp_path / "logs"
    model_profiles_dir = tmp_path / "model_profiles"
    model_dir = model_profiles_dir / "romantic_rebel_european"
    model_dir.mkdir(parents=True)
    model_image_path = model_dir / "model.jpg"
    model_metadata_path = model_dir / "metadata.json"
    Image.new("RGB", (64, 64), "blue").save(model_image_path)
    model_metadata_path.write_text("{}", encoding="utf-8")

    from productv2.db import seed_candidate_products

    data_path = tmp_path / "candidates.json"
    data_path.write_text(
        json.dumps(
            [
                {
                    "product_id": "db-fixture-2",
                    "platform": "1688",
                    "rawdata": {
                        "title": "Database Fixture Product",
                        "url": "https://example.test/db-fixture-2",
                        "detail": {
                            "image_urls": [
                                "https://cbu01.alicdn.com/img/ibank/a.jpg_.webp"
                            ]
                        },
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    seed_candidate_products(database_path=database_path, data_path=data_path)

    def fake_merge_remote_images_to_collage(image_urls, output_path, **_kwargs):
        assert image_urls == ["https://cbu01.alicdn.com/img/ibank/a.jpg_.webp"]
        Image.new("RGB", (64, 64), "white").save(output_path)
        from productv2.images import ImageCollageResult, NumberedImageSource

        source_dir = output_path.parent / "main_image_sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), "white").save(source_dir / "1.jpg")
        Image.new("RGB", (64, 64), "white").save(source_dir / "2.jpg")
        return ImageCollageResult(
            path=output_path,
            source_images=[
                NumberedImageSource(
                    index=1,
                    url="https://cbu01.alicdn.com/img/ibank/a.jpg_.webp",
                    path=source_dir / "1.jpg",
                ),
                NumberedImageSource(
                    index=2,
                    url="https://cbu01.alicdn.com/img/ibank/a-main.jpg_.webp",
                    path=source_dir / "2.jpg",
                )
            ],
        )

    def fake_detect_size_reference_images(collage_path):
        from productv2.vision import SizeReferenceDetection

        assert collage_path == str(
            assets_dir / "1688" / "db-fixture-2" / "main_image_collage.jpg"
        )
        return SizeReferenceDetection(
            can_judge_size=True,
            image_numbers=[1],
            size_reference_image_number=1,
            main_image_number=2,
            reason="有模特佩戴图",
        )

    def fake_select_enroute_wearing_reference(candidate, library_dir):
        from productv2.enroute import EnrouteReference

        reference_dir = tmp_path / "enroute" / "necklaces" / "01-reference"
        reference_dir.mkdir(parents=True, exist_ok=True)
        reference_path = reference_dir / "02.jpg"
        Image.new("RGB", (64, 64), "white").save(reference_path)
        return EnrouteReference(
            product_id="enroute-reference-1",
            category="necklaces",
            product_dir=reference_dir,
            image_path=reference_path,
            metadata={
                "title": "Reference Necklace",
                "handle": "reference-necklace",
                "product_type": "Necklaces",
                "source_url": "https://example.test/reference-necklace",
            },
        )

    def fake_analyze_enroute_reference_image(image_path, **kwargs):
        assert kwargs["model_profiles"]
        from productv2.reference_analysis import EnrouteReferenceAnalysis
        from productv2.reference_analysis import ClothingStyleAnalysis
        from productv2.reference_analysis import SceneStyleAnalysis
        from productv2.reference_analysis import ShootingStyleAnalysis

        return EnrouteReferenceAnalysis(
            is_valid_wearing_reference=True,
            summary="LLM 摘要：短链适配强，锁骨链适配强，中长链可用，长链需要更宽构图。",
            selected_model_profile={
                "profile_key": "romantic_rebel_european",
                "name": "Romantic Rebel",
                "image_path": str(model_image_path),
                "reason": "冷淡松弛气质匹配",
            },
            clothing_style=ClothingStyleAnalysis(
                category="细肩带基础上装",
                fabric_texture="细密棉质纹理",
                styling_keywords=["低饱和", "日常新浪漫"],
            ),
            scene_style=SceneStyleAnalysis(background_feel="简洁低干扰"),
            shooting_style=ShootingStyleAnalysis(
                shot_type="collarbone crop",
                framing="下半脸到锁骨",
                lighting="柔和窗光",
            ),
            reason=f"参考图可用：{image_path}",
        )

    monkeypatch.setattr(
        graph_module,
        "merge_remote_images_to_numbered_collage",
        fake_merge_remote_images_to_collage,
    )
    monkeypatch.setattr(
        graph_module,
        "detect_size_reference_images",
        fake_detect_size_reference_images,
    )
    monkeypatch.setattr(
        graph_module,
        "select_enroute_wearing_reference",
        fake_select_enroute_wearing_reference,
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_enroute_reference_image",
        fake_analyze_enroute_reference_image,
    )

    result = run_listing_workflow(
        data_path=missing_data_path,
        database_path=database_path,
        product_assets_dir=assets_dir,
        model_profiles_dir=model_profiles_dir,
        workflow_logs_dir=log_dir,
        limit=1,
    )

    collage_path = assets_dir / "1688" / "db-fixture-2" / "main_image_collage.jpg"
    assert result["metrics"]["main_image_result"]["status"] == "ok"
    assert result["metrics"]["main_image_result"]["path"] == str(collage_path)
    assert result["metrics"]["main_image_result"]["temporary"] is True
    assert result["metrics"]["main_image_result"]["numbered_sources"] == [
        {
            "index": 1,
            "url": "https://cbu01.alicdn.com/img/ibank/a.jpg_.webp",
            "path": str(collage_path.parent / "main_image_sources" / "1.jpg"),
        },
        {
            "index": 2,
            "url": "https://cbu01.alicdn.com/img/ibank/a-main.jpg_.webp",
            "path": str(collage_path.parent / "main_image_sources" / "2.jpg"),
        },
    ]
    assert result["metrics"]["size_reference_result"] == {
        "status": "ok",
        "can_judge_size": True,
        "image_numbers": [1],
        "size_reference_image_number": 1,
        "main_image_number": 2,
        "selected_images": {
            "size_reference_image": {
                "number": 1,
                "path": str(collage_path.parent / "main_image_sources" / "1.jpg"),
                "url": "https://cbu01.alicdn.com/img/ibank/a.jpg_.webp",
            },
            "main_image": {
                "number": 2,
                "path": str(collage_path.parent / "main_image_sources" / "2.jpg"),
                "url": "https://cbu01.alicdn.com/img/ibank/a-main.jpg_.webp",
            },
        },
        "reason": "有模特佩戴图",
    }
    reference_path = tmp_path / "enroute" / "necklaces" / "01-reference" / "02.jpg"
    assert result["metrics"]["enroute_reference_result"] == {
        "status": "ok",
        "enroute_product_id": "enroute-reference-1",
        "category": "necklaces",
        "image_path": str(reference_path),
        "product_dir": str(reference_path.parent),
        "metadata": {
            "title": "Reference Necklace",
            "handle": "reference-necklace",
            "product_type": "Necklaces",
            "source_url": "https://example.test/reference-necklace",
        },
    }
    assert result["metrics"]["enroute_analysis_result"]["status"] == "ok"
    assert result["metrics"]["enroute_analysis_result"]["cache"] == "miss"
    assert result["metrics"]["enroute_analysis_result"]["enroute_product_id"] == (
        "enroute-reference-1"
    )
    assert result["metrics"]["enroute_analysis_result"]["reference_image_path"] == str(
        reference_path
    )
    assert result["metrics"]["enroute_analysis_result"]["summary"] == (
        "LLM 摘要：短链适配强，锁骨链适配强，中长链可用，长链需要更宽构图。"
    )
    assert result["metrics"]["enroute_analysis_result"]["analysis"][
        "clothing_style"
    ]["styling_keywords"] == ["低饱和", "日常新浪漫"]
    assert result["metrics"]["enroute_analysis_result"]["analysis"][
        "scene_style"
    ]["background_feel"] == "简洁低干扰"
    assert result["metrics"]["enroute_analysis_result"]["analysis"][
        "shooting_style"
    ]["shot_type"] == "collarbone crop"
    assert result["metrics"]["enroute_analysis_result"]["analysis"][
        "selected_model_profile"
    ]["profile_key"] == "romantic_rebel_european"
    log_path = Path(result["metrics"]["workflow_log_path"])
    log_text = log_path.read_text(encoding="utf-8")
    assert "事件：分支判断" in log_text
    assert "逻辑单元：detect_size_reference" in log_text
    assert "- 分支逻辑 (branch): select_enroute_reference" in log_text
    assert "逻辑单元：analyze_enroute_reference" in log_text
    assert (
        f"- enroute_analysis_result.reference_image_path: {reference_path}"
        in log_text
    )
    wearing_result = result["metrics"]["wearing_image_result"]
    assert wearing_result["status"] == "reserved"
    assert wearing_result["reason"] == "wearing_image_generation_not_implemented"
    assert wearing_result["product_id"] == "db-fixture-2"
    assert wearing_result["platform"] == "1688"
    assert wearing_result["size_reference_image_numbers"] == [1]
    assert wearing_result["marked_main_image_path"] == str(
        collage_path.parent / "wearing_generation_inputs" / "01_main_image.jpg"
    )
    assert wearing_result["marked_size_reference_image_path"] == str(
        collage_path.parent
        / "wearing_generation_inputs"
        / "02_size_reference.jpg"
    )
    assert wearing_result["enroute_reference_image_path"] == str(reference_path)
    assert "参考图 01 标记为主图" in wearing_result["prompt"]
    assert "参考图 02 标记为尺寸参考图" in wearing_result["prompt"]
    assert wearing_result["selected_model_profile"]["profile_key"] == (
        "romantic_rebel_european"
    )
    assert str(model_image_path) in wearing_result["input_images"]
    assert "产品一致性" in wearing_result["prompt"]
    assert "尺寸一致性" in wearing_result["prompt"]
    assert collage_path.exists()
    assert Path(wearing_result["marked_main_image_path"]).exists()
    assert Path(wearing_result["marked_size_reference_image_path"]).exists()
    assert get_extra("main_image_collage")["path"] == str(collage_path)
    assert get_extra("size_reference_detection")["image_numbers"] == [1]
    assert get_extra("selected_size_reference_image_path") == str(
        collage_path.parent / "main_image_sources" / "1.jpg"
    )
    assert get_extra("selected_main_image_path") == str(
        collage_path.parent / "main_image_sources" / "2.jpg"
    )
    assert get_extra("selected_product_images") == {
        "size_reference_image": {
            "number": 1,
            "path": str(collage_path.parent / "main_image_sources" / "1.jpg"),
            "url": "https://cbu01.alicdn.com/img/ibank/a.jpg_.webp",
        },
        "main_image": {
            "number": 2,
            "path": str(collage_path.parent / "main_image_sources" / "2.jpg"),
            "url": "https://cbu01.alicdn.com/img/ibank/a-main.jpg_.webp",
        },
    }
    assert get_extra("selected_enroute_reference_image_path") == str(reference_path)
    assert get_extra("selected_enroute_reference_metadata")["title"] == (
        "Reference Necklace"
    )
    assert get_extra("enroute_reference_analysis")["analysis"]["clothing_style"][
        "category"
    ] == "细肩带基础上装"
    assert get_extra("wearing_image_generation")["status"] == "reserved"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT main_image, wearing_image
            FROM products
            WHERE product_id = ? AND platform = ?
            """,
            ("db-fixture-2", "1688"),
        ).fetchone()

    assert row[0] == ""
    assert row[1] == ""

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        cached = connection.execute(
            """
            SELECT enroute_product_id, enroute_category, summary, analysis_json
            FROM enroute_image_analyses
            WHERE enroute_product_id = ?
            """,
            ("enroute-reference-1",),
        ).fetchone()

    assert cached["enroute_product_id"] == "enroute-reference-1"
    assert cached["enroute_category"] == "necklaces"
    assert cached["summary"] == (
        "LLM 摘要：短链适配强，锁骨链适配强，中长链可用，长链需要更宽构图。"
    )
    assert json.loads(cached["analysis_json"])["clothing_style"]["category"] == (
        "细肩带基础上装"
    )


def test_listing_workflow_marks_llm_failure_and_reselects_next_product(
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    missing_data_path = tmp_path / "missing.json"
    assets_dir = tmp_path / "products"

    from productv2.db import init_database

    init_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO products (product_id, platform, rawdata, status)
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    "retry-first",
                    "1688",
                    json.dumps(
                        {
                            "title": "First Product",
                            "url": "https://example.test/retry-first",
                            "detail": {
                                "image_urls": [
                                    "https://cbu01.alicdn.com/img/ibank/first.jpg_.webp"
                                ]
                            },
                        }
                    ),
                    "all_pendding",
                ),
                (
                    "retry-second",
                    "1688",
                    json.dumps(
                        {
                            "title": "Second Product",
                            "url": "https://example.test/retry-second",
                            "detail": {
                                "image_urls": [
                                    "https://cbu01.alicdn.com/img/ibank/second.jpg_.webp"
                                ]
                            },
                        }
                    ),
                    "all_pendding",
                ),
            ],
        )

    class NoShuffleRandom:
        def shuffle(self, values):
            return None

    monkeypatch.setattr("productv2.selection.random.Random", lambda: NoShuffleRandom())

    def fake_merge_remote_images_to_collage(image_urls, output_path, **_kwargs):
        Image.new("RGB", (64, 64), "white").save(output_path)
        from productv2.images import ImageCollageResult, NumberedImageSource

        source_dir = output_path.parent / "main_image_sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), "white").save(source_dir / "1.jpg")
        return ImageCollageResult(
            path=output_path,
            source_images=[
                NumberedImageSource(
                    index=1,
                    url=image_urls[0],
                    path=source_dir / "1.jpg",
                )
            ],
        )

    detect_calls = []

    def fake_detect_size_reference_images(collage_path):
        from productv2.vision import SizeReferenceDetection

        detect_calls.append(str(collage_path))
        if "retry-first" in str(collage_path):
            raise RuntimeError("llm failed")
        return SizeReferenceDetection(
            can_judge_size=True,
            image_numbers=[1],
            size_reference_image_number=1,
            main_image_number=1,
            reason="第二条有佩戴参照",
        )

    def fake_select_enroute_wearing_reference(candidate, library_dir):
        from productv2.enroute import EnrouteReference

        reference_dir = tmp_path / "enroute" / "necklaces" / "02-reference"
        reference_dir.mkdir(parents=True, exist_ok=True)
        reference_path = reference_dir / "02.jpg"
        Image.new("RGB", (64, 64), "white").save(reference_path)
        return EnrouteReference(
            product_id="enroute-reference-2",
            category="necklaces",
            product_dir=reference_dir,
            image_path=reference_path,
            metadata={"title": "Retry Reference"},
        )

    def fake_analyze_enroute_reference_image(image_path, **_kwargs):
        from productv2.reference_analysis import EnrouteReferenceAnalysis
        from productv2.reference_analysis import ShootingStyleAnalysis

        return EnrouteReferenceAnalysis(
            is_valid_wearing_reference=True,
            summary="LLM 摘要：适合项链短链和锁骨链。",
            selected_model_profile={
                "profile_key": "romantic_rebel_european",
                "name": "Romantic Rebel",
                "image_path": "/tmp/model.jpg",
                "reason": "冷淡松弛气质匹配",
            },
            shooting_style=ShootingStyleAnalysis(shot_type="collarbone crop"),
            reason=f"参考图可用：{image_path}",
        )

    monkeypatch.setattr(
        graph_module,
        "merge_remote_images_to_numbered_collage",
        fake_merge_remote_images_to_collage,
    )
    monkeypatch.setattr(
        graph_module,
        "detect_size_reference_images",
        fake_detect_size_reference_images,
    )
    monkeypatch.setattr(
        graph_module,
        "select_enroute_wearing_reference",
        fake_select_enroute_wearing_reference,
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_enroute_reference_image",
        fake_analyze_enroute_reference_image,
    )

    result = run_listing_workflow(
        data_path=missing_data_path,
        database_path=database_path,
        product_assets_dir=assets_dir,
        limit=1,
    )

    assert len(detect_calls) == 2
    assert result["drafts"][0]["product_id"] == "retry-second"
    assert result["metrics"]["size_reference_result"] == {
        "status": "ok",
        "can_judge_size": True,
        "image_numbers": [1],
        "size_reference_image_number": 1,
        "main_image_number": 1,
        "selected_images": {
            "size_reference_image": {
                "number": 1,
                "path": str(
                    assets_dir
                    / "1688"
                    / "retry-second"
                    / "main_image_sources"
                    / "1.jpg"
                ),
                "url": "https://cbu01.alicdn.com/img/ibank/second.jpg_.webp",
            },
            "main_image": {
                "number": 1,
                "path": str(
                    assets_dir
                    / "1688"
                    / "retry-second"
                    / "main_image_sources"
                    / "1.jpg"
                ),
                "url": "https://cbu01.alicdn.com/img/ibank/second.jpg_.webp",
            },
        },
        "reason": "第二条有佩戴参照",
    }
    assert result["metrics"]["wearing_image_result"]["status"] == "reserved"
    assert result["metrics"]["wearing_image_result"]["product_id"] == "retry-second"
    assert result["metrics"]["enroute_analysis_result"]["status"] == "ok"
    assert result["metrics"]["enroute_analysis_result"]["analysis"]["shooting_style"][
        "shot_type"
    ] == "collarbone crop"

    with sqlite3.connect(database_path) as connection:
        rows = {
            row[0]: row[1:]
            for row in connection.execute(
                """
                SELECT product_id, status, locked_at, locked_by
                FROM products
                ORDER BY id
                """
            ).fetchall()
        }

    assert rows["retry-first"] == ("failed", None, None)
    assert rows["retry-second"][0] == "processing"
    assert rows["retry-second"][1] is not None
    assert rows["retry-second"][2] is not None


def test_listing_workflow_uses_cached_enroute_analysis(
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    missing_data_path = tmp_path / "missing.json"
    assets_dir = tmp_path / "products"

    from productv2.db import seed_candidate_products
    from productv2.db import upsert_enroute_image_analysis

    data_path = tmp_path / "candidates.json"
    data_path.write_text(
        json.dumps(
            [
                {
                    "product_id": "db-fixture-cache",
                    "platform": "1688",
                    "rawdata": {
                        "title": "Cached Necklace Product",
                        "url": "https://example.test/db-fixture-cache",
                        "detail": {
                            "image_urls": [
                                "https://cbu01.alicdn.com/img/ibank/cache.jpg_.webp"
                            ]
                        },
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    seed_candidate_products(database_path=database_path, data_path=data_path)
    upsert_enroute_image_analysis(
        database_path,
        enroute_product_id="cached-enroute-1",
        enroute_category="necklaces",
        enroute_title="Cached Reference",
        enroute_handle="cached-reference",
        image_path="/cached/02.jpg",
            analysis_json={
                "is_valid_wearing_reference": True,
                "selected_model_profile": {
                    "profile_key": "romantic_rebel_european",
                    "name": "Romantic Rebel",
                    "image_path": "/cached/model.jpg",
                    "reason": "缓存模特选择",
                },
                "clothing_style": {"category": "缓存衣物"},
                "shooting_style": {"shot_type": "cached crop"},
            },
        summary="适合项链佩戴图，重点适配短链、锁骨链、中长链",
    )

    def fake_merge_remote_images_to_collage(image_urls, output_path, **_kwargs):
        Image.new("RGB", (64, 64), "white").save(output_path)
        from productv2.images import ImageCollageResult, NumberedImageSource

        source_dir = output_path.parent / "main_image_sources"
        source_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), "white").save(source_dir / "1.jpg")
        return ImageCollageResult(
            path=output_path,
            source_images=[
                NumberedImageSource(
                    index=1,
                    url=image_urls[0],
                    path=source_dir / "1.jpg",
                )
            ],
        )

    def fake_detect_size_reference_images(collage_path):
        from productv2.vision import SizeReferenceDetection

        return SizeReferenceDetection(
            can_judge_size=True,
            image_numbers=[1],
            size_reference_image_number=1,
            main_image_number=1,
            reason="有模特佩戴图",
        )

    def fake_select_enroute_wearing_reference(candidate, library_dir):
        from productv2.enroute import EnrouteReference

        reference_dir = tmp_path / "enroute" / "necklaces" / "cached-reference"
        reference_dir.mkdir(parents=True, exist_ok=True)
        reference_path = reference_dir / "02.jpg"
        Image.new("RGB", (64, 64), "white").save(reference_path)
        return EnrouteReference(
            product_id="cached-enroute-1",
            category="necklaces",
            product_dir=reference_dir,
            image_path=reference_path,
            metadata={"title": "Cached Reference", "handle": "cached-reference"},
        )

    def fail_analyze_enroute_reference_image(image_path):
        raise AssertionError("LLM should not be called when cache exists")

    monkeypatch.setattr(
        graph_module,
        "merge_remote_images_to_numbered_collage",
        fake_merge_remote_images_to_collage,
    )
    monkeypatch.setattr(
        graph_module,
        "detect_size_reference_images",
        fake_detect_size_reference_images,
    )
    monkeypatch.setattr(
        graph_module,
        "select_enroute_wearing_reference",
        fake_select_enroute_wearing_reference,
    )
    monkeypatch.setattr(
        graph_module,
        "analyze_enroute_reference_image",
        fail_analyze_enroute_reference_image,
    )

    result = run_listing_workflow(
        data_path=missing_data_path,
        database_path=database_path,
        product_assets_dir=assets_dir,
        limit=1,
    )

    assert result["metrics"]["enroute_analysis_result"]["cache"] == "hit"
    assert result["metrics"]["enroute_analysis_result"]["enroute_product_id"] == (
        "cached-enroute-1"
    )
    assert result["metrics"]["enroute_analysis_result"]["analysis"][
        "clothing_style"
    ]["category"] == "缓存衣物"
