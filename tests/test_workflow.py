import pytest
import sqlite3
from pathlib import Path
import json

from PIL import Image

import productv2.graph as graph_module
import productv2.workflow_checkpoints as checkpoints_module
from productv2.dev_graph import product_listing
from productv2.graph import MAX_WEARING_REGENERATE_ATTEMPTS
from productv2.graph import _route_manual_review_decision
from productv2.graph import build_listing_graph
from productv2.graph import compile_listing_graph
from productv2.enroute import EnrouteReference, list_category_wearing_references
from productv2.enroute_learning import sync_enroute_learning_library
from productv2.reference_analysis_service import WearingStyleProfileSelection
from productv2.vision import SizeReferenceDetection
from productv2.wearing import save_generated_wearing_image


def _write_enroute_reference(root: Path, category: str, name: str) -> Path:
    product_dir = root / category / name
    product_dir.mkdir(parents=True)
    Image.new("RGB", (10, 10), "white").save(product_dir / "02.jpg")
    (product_dir / "metadata.json").write_text(
        json.dumps(
            {
                "product_id": f"{category}:{name}",
                "handle": name,
                "title": name,
            }
        ),
        encoding="utf-8",
    )
    return product_dir


def _candidate_state(database_path: Path, enroute_dir: Path | None = None) -> dict:
    return {
        "database_path": str(database_path),
        **({"enroute_bestsellers_dir": str(enroute_dir)} if enroute_dir else {}),
        "candidates": [
            {
                "id": 1,
                "product_id": "p-1",
                "platform": "1688",
                "rawdata": {"title": "Layered necklace"},
                "status": "processing",
                "main_image": "",
                "wearing_image": "",
                "detail_image": "",
                "size_ratio_image": "",
                "multi_angle_image": "",
                "locked_at": "",
                "locked_by": "",
                "created_at": "",
                "updated_at": "",
            }
        ],
    }


def test_dev_graph_exports_compiled_product_listing_graph() -> None:
    assert product_listing is not None
    assert type(product_listing).__name__ == "CompiledStateGraph"


def test_build_listing_graph_contains_manual_review_nodes() -> None:
    graph = build_listing_graph()
    compiled = graph.compile()

    assert type(compiled).__name__ == "CompiledStateGraph"
    assert "wait_manual_review" in graph.nodes
    assert "mark_failed_and_reload_candidates" in graph.nodes
    assert "learn_enroute_profiles" in graph.nodes
    assert "select_wearing_style_profile" in graph.nodes
    assert "compile_wearing_generation_prompt" in graph.nodes


def test_enroute_learning_references_run_serially(monkeypatch, tmp_path) -> None:
    references = [
        EnrouteReference(
            product_id="ref-1",
            category="necklaces",
            product_dir=tmp_path / "ref-1",
            image_path=tmp_path / "ref-1" / "02.jpg",
            metadata={},
        ),
        EnrouteReference(
            product_id="ref-2",
            category="necklaces",
            product_dir=tmp_path / "ref-2",
            image_path=tmp_path / "ref-2" / "02.jpg",
            metadata={},
        ),
    ]
    calls: list[str] = []

    def fake_learn_one(state, _database_path, reference, _logger):
        assert list((state.get("ai_checkpoints") or {}).keys()) == ["existing"]
        calls.append(reference.product_id)
        return {
            "status": "ok",
            "enroute_product_id": reference.product_id,
        }

    monkeypatch.setattr(
        graph_module,
        "_learn_one_enroute_reference",
        fake_learn_one,
    )

    state = {"ai_checkpoints": {"existing": {"status": "ok"}}}
    outputs = graph_module._learn_enroute_references(
        state,
        database_path=tmp_path / "productv2.db",
        references=references,
    )

    assert [item["enroute_product_id"] for item in outputs] == ["ref-1", "ref-2"]
    assert calls == ["ref-1", "ref-2"]
    assert list(state["ai_checkpoints"].keys()) == ["existing"]


def test_manual_review_router_branches_by_action() -> None:
    assert _route_manual_review_decision(
        {"manual_review_decision": {"action": "approve"}}
    ) == "build_listing_drafts"
    assert _route_manual_review_decision(
        {
            "manual_review_decision": {"action": "regenerate"},
            "wearing_generation_attempt": 1,
        }
    ) == "generate_wearing_image"
    assert _route_manual_review_decision(
        {
            "manual_review_decision": {"action": "regenerate"},
            "wearing_generation_attempt": MAX_WEARING_REGENERATE_ATTEMPTS,
        }
    ) == "mark_failed_and_reload_candidates"
    assert _route_manual_review_decision(
        {"manual_review_decision": {"action": "reject"}}
    ) == "mark_failed_and_reload_candidates"


def test_mark_failed_and_reload_candidates_updates_database(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    from productv2.db import init_database

    init_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO products (
                product_id, platform, rawdata, status, locked_at, locked_by
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("p-1", "1688", "{}", "processing", "2026-01-01T00:00:00", "worker"),
        )

    output = graph_module._mark_failed_and_reload_candidates(
        {
            "database_path": str(database_path),
            "candidates": [
                {
                    "id": 1,
                    "product_id": "p-1",
                    "platform": "1688",
                    "rawdata": {},
                    "status": "processing",
                    "main_image": "",
                    "wearing_image": "",
                    "detail_image": "",
                    "size_ratio_image": "",
                    "multi_angle_image": "",
                    "locked_at": "2026-01-01T00:00:00",
                    "locked_by": "worker",
                    "created_at": "",
                    "updated_at": "",
                }
            ],
            "manual_review_decision": {"reason": "人工拒绝"},
        }
    )

    assert output["failed_product"]["status"] == "failed"
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT status, locked_at, locked_by
            FROM products
            WHERE product_id = ? AND platform = ?
            """,
            ("p-1", "1688"),
        ).fetchone()
    assert row == ("failed", None, None)


def test_build_listing_drafts_approve_persists_wearing_image_and_unlocks(
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    wearing_image = tmp_path / "wearing_image_attempt_1.png"
    wearing_image.write_text("fake image", encoding="utf-8")
    from productv2.db import init_database

    init_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO products (
                product_id, platform, rawdata, status, locked_at, locked_by
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "p-1",
                "1688",
                json.dumps({"title": "Layered necklace"}),
                "processing",
                "2026-01-01T00:00:00",
                "worker",
            ),
        )

    output = graph_module._build_listing_drafts(
        {
            "database_path": str(database_path),
            "candidates": [
                {
                    "id": 1,
                    "product_id": "p-1",
                    "platform": "1688",
                    "rawdata": {"title": "Layered necklace"},
                    "status": "processing",
                    "main_image": "",
                    "wearing_image": "",
                    "detail_image": "",
                    "size_ratio_image": "",
                    "multi_angle_image": "",
                    "locked_at": "2026-01-01T00:00:00",
                    "locked_by": "worker",
                    "created_at": "",
                    "updated_at": "",
                }
            ],
            "selected_product": {
                "product_id": "p-1",
                "platform": "1688",
                "status": "processing",
                "wearing_image": "",
            },
            "wearing_image_result": {
                "status": "ok",
                "generated_image_path": str(wearing_image),
            },
            "manual_review_decision": {"action": "approve"},
        }
    )

    assert output["approved_product"] == {
        "product_id": "p-1",
        "platform": "1688",
        "status": "done",
        "wearing_image": str(wearing_image),
    }
    assert output["selected_product"]["status"] == "done"
    assert output["selected_product"]["wearing_image"] == str(wearing_image)
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT status, wearing_image, locked_at, locked_by
            FROM products
            WHERE product_id = ? AND platform = ?
            """,
            ("p-1", "1688"),
        ).fetchone()
    assert row == ("done", str(wearing_image), None, None)


def test_build_listing_drafts_without_approve_does_not_finalize_product(
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    from productv2.db import init_database

    init_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO products (
                product_id, platform, rawdata, status, locked_at, locked_by
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("p-1", "1688", "{}", "processing", "2026-01-01T00:00:00", "worker"),
        )

    output = graph_module._build_listing_drafts(
        {
            "database_path": str(database_path),
            "candidates": [
                {
                    "id": 1,
                    "product_id": "p-1",
                    "platform": "1688",
                    "rawdata": {},
                    "status": "processing",
                    "main_image": "",
                    "wearing_image": "",
                    "detail_image": "",
                    "size_ratio_image": "",
                    "multi_angle_image": "",
                    "locked_at": "2026-01-01T00:00:00",
                    "locked_by": "worker",
                    "created_at": "",
                    "updated_at": "",
                }
            ],
            "manual_review_decision": {},
        }
    )

    assert output["approved_product"] == {}
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT status, wearing_image, locked_at, locked_by
            FROM products
            WHERE product_id = ? AND platform = ?
            """,
            ("p-1", "1688"),
        ).fetchone()
    assert row == ("processing", "", "2026-01-01T00:00:00", "worker")


def test_mark_failed_and_reload_candidates_propagates_database_errors(
    monkeypatch,
) -> None:
    def fake_update_product_fields(**_kwargs):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        graph_module,
        "update_product_fields",
        fake_update_product_fields,
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        graph_module._mark_failed_and_reload_candidates(
            {
                "database_path": "/tmp/missing.db",
                "candidates": [
                    {
                        "id": 1,
                        "product_id": "p-1",
                        "platform": "1688",
                        "rawdata": {},
                        "status": "processing",
                        "main_image": "",
                        "wearing_image": "",
                        "detail_image": "",
                        "size_ratio_image": "",
                        "multi_angle_image": "",
                        "locked_at": "",
                        "locked_by": "",
                        "created_at": "",
                        "updated_at": "",
                    }
                ],
                "manual_review_decision": {"reason": "人工拒绝"},
            }
        )


def test_save_generated_wearing_image_uses_attempt_name(tmp_path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (10, 10), "red").save(source)

    import base64

    data_url = (
        "data:image/png;base64,"
        + base64.b64encode(source.read_bytes()).decode("ascii")
    )
    output = save_generated_wearing_image(data_url, tmp_path, attempt=2)

    assert output == tmp_path / "wearing_image_attempt_2.png"
    assert output.exists()


def test_merge_main_images_download_failure_stops_without_failed_state(
    monkeypatch,
    tmp_path,
) -> None:
    def fake_merge_remote_images_to_numbered_collage(**_kwargs):
        raise ValueError("No downloadable images available for collage.")

    monkeypatch.setattr(
        graph_module,
        "merge_remote_images_to_numbered_collage",
        fake_merge_remote_images_to_numbered_collage,
    )

    state = {
        "product_assets_dir": str(tmp_path),
        "candidates": [
            {
                "id": 1,
                "product_id": "p-1",
                "platform": "1688",
                "rawdata": {
                    "title": "Layered necklace",
                    "detail": {"image_urls": ["https://example.test/missing.jpg"]},
                },
                "status": "processing",
                "main_image": "",
                "wearing_image": "",
                "detail_image": "",
                "size_ratio_image": "",
                "multi_angle_image": "",
                "locked_at": "",
                "locked_by": "",
                "created_at": "",
                "updated_at": "",
            }
        ],
    }

    with pytest.raises(ValueError, match="No downloadable images"):
        graph_module._merge_main_images(state)

    assert "main_image_result" not in state


def test_size_reference_detection_result_is_checkpointed(monkeypatch, tmp_path) -> None:
    collage = tmp_path / "main_image_collage.jpg"
    source_dir = tmp_path / "main_image_sources"
    source_dir.mkdir()
    size_ref = source_dir / "1.jpg"
    main = source_dir / "2.jpg"
    Image.new("RGB", (10, 10), "white").save(collage)
    Image.new("RGB", (10, 10), "gray").save(size_ref)
    Image.new("RGB", (10, 10), "blue").save(main)
    calls = {"count": 0}

    def fake_detect_size_reference_images(_collage_path, logger=None):
        calls["count"] += 1
        return SizeReferenceDetection(
            can_judge_size=True,
            image_numbers=[1],
            size_reference_image_number=1,
            main_image_number=2,
            reason="有参照",
        )

    monkeypatch.setattr(
        graph_module,
        "detect_size_reference_images",
        fake_detect_size_reference_images,
    )

    state = {
        "selected_product": {
            "id": 1,
            "product_id": "p-1",
            "platform": "1688",
            "status": "processing",
        },
        "main_image_result": {
            "status": "ok",
            "path": str(collage),
            "source_image_count": 2,
            "numbered_sources": [
                {"index": 1, "path": str(size_ref), "url": "https://example.test/1.jpg"},
                {"index": 2, "path": str(main), "url": "https://example.test/2.jpg"},
            ],
        },
    }

    first = graph_module._detect_size_reference(state)
    second = graph_module._detect_size_reference({**state, **first})

    assert calls["count"] == 1
    assert "detect_size_reference" in first["ai_checkpoints"]
    assert first["size_reference_result"]["is_product_qualified"] is True
    assert first["size_reference_result"]["qualification_checks"]["size_reference"][
        "passed"
    ] is True
    assert second["size_reference_result"]["checkpoint"] == "hit"


def test_unusable_size_reference_marks_product_failed_and_reloads(
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    collage = tmp_path / "main_image_collage.jpg"
    source_dir = tmp_path / "main_image_sources"
    source_dir.mkdir()
    main = source_dir / "1.jpg"
    Image.new("RGB", (10, 10), "white").save(collage)
    Image.new("RGB", (10, 10), "gray").save(main)
    from productv2.db import init_database

    init_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO products (
                product_id, platform, rawdata, status, locked_at, locked_by
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "p-1",
                "1688",
                json.dumps({"title": "Poster only"}),
                "processing",
                "2026-01-01T00:00:00",
                "worker",
            ),
        )

    def fake_detect_size_reference_images(_collage_path, logger=None):
        return SizeReferenceDetection(
            can_judge_size=False,
            image_numbers=[],
            size_reference_image_number=None,
            main_image_number=1,
            reason="仅看到文字宣传图，无人体、手部或佩戴参照，无法判断尺寸比例",
        )

    monkeypatch.setattr(
        graph_module,
        "detect_size_reference_images",
        fake_detect_size_reference_images,
    )
    state = {
        "database_path": str(database_path),
        "selected_product": {
            "id": 1,
            "product_id": "p-1",
            "platform": "1688",
            "status": "processing",
        },
        "candidates": [
            {
                "id": 1,
                "product_id": "p-1",
                "platform": "1688",
                "rawdata": {},
                "status": "processing",
                "main_image": "",
                "wearing_image": "",
                "detail_image": "",
                "size_ratio_image": "",
                "multi_angle_image": "",
                "locked_at": "2026-01-01T00:00:00",
                "locked_by": "worker",
                "created_at": "",
                "updated_at": "",
            }
        ],
        "main_image_result": {
            "status": "ok",
            "path": str(collage),
            "source_image_count": 1,
            "numbered_sources": [{"index": 1, "path": str(main), "url": ""}],
        },
    }

    detected = graph_module._detect_size_reference(state)

    assert detected["size_reference_result"]["status"] == "failed"
    assert detected["size_reference_result"]["is_product_qualified"] is False
    assert detected["size_reference_result"]["failure_type"] == "product_unqualified"
    assert detected["size_reference_result"]["failure_detail"] == (
        "size_reference_unusable"
    )
    assert detected["size_reference_result"]["failed_checks"] == ["size_reference"]
    assert graph_module._size_reference_next_step({**state, **detected}) == (
        "mark_failed_and_reload_candidates"
    )

    reloaded = graph_module._mark_failed_and_reload_candidates({**state, **detected})

    assert reloaded["failed_product"]["status"] == "failed"
    assert reloaded["failed_product"]["reason"] == (
        "仅看到文字宣传图，无人体、手部或佩戴参照，无法判断尺寸比例"
    )
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT status, locked_at, locked_by
            FROM products
            WHERE product_id = ? AND platform = ?
            """,
            ("p-1", "1688"),
        ).fetchone()
    assert row == ("failed", None, None)


def test_product_qualification_failed_check_marks_product_failed(
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    collage = tmp_path / "main_image_collage.jpg"
    source_dir = tmp_path / "main_image_sources"
    source_dir.mkdir()
    size_ref = source_dir / "1.jpg"
    main = source_dir / "2.jpg"
    Image.new("RGB", (10, 10), "white").save(collage)
    Image.new("RGB", (10, 10), "gray").save(size_ref)
    Image.new("RGB", (10, 10), "blue").save(main)
    from productv2.db import init_database

    init_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO products (
                product_id, platform, rawdata, status, locked_at, locked_by
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "p-2",
                "1688",
                json.dumps({"title": "Low quality"}),
                "processing",
                "2026-01-01T00:00:00",
                "worker",
            ),
        )

    def fake_detect_size_reference_images(_collage_path, logger=None):
        return SizeReferenceDetection(
            is_product_qualified=False,
            qualification_checks={
                "size_reference": {"passed": True, "reason": "有佩戴参照"},
                "future_quality_rule": {
                    "passed": False,
                    "reason": "预留质检项失败",
                },
            },
            failed_checks=["future_quality_rule"],
            can_judge_size=True,
            image_numbers=[1],
            size_reference_image_number=1,
            main_image_number=2,
            reason="预留质检项失败",
        )

    monkeypatch.setattr(
        graph_module,
        "detect_size_reference_images",
        fake_detect_size_reference_images,
    )
    state = {
        "database_path": str(database_path),
        "selected_product": {
            "id": 1,
            "product_id": "p-2",
            "platform": "1688",
            "status": "processing",
        },
        "candidates": [
            {
                "id": 1,
                "product_id": "p-2",
                "platform": "1688",
                "rawdata": {},
                "status": "processing",
                "main_image": "",
                "wearing_image": "",
                "detail_image": "",
                "size_ratio_image": "",
                "multi_angle_image": "",
                "locked_at": "2026-01-01T00:00:00",
                "locked_by": "worker",
                "created_at": "",
                "updated_at": "",
            }
        ],
        "main_image_result": {
            "status": "ok",
            "path": str(collage),
            "source_image_count": 2,
            "numbered_sources": [
                {"index": 1, "path": str(size_ref), "url": ""},
                {"index": 2, "path": str(main), "url": ""},
            ],
        },
    }

    detected = graph_module._detect_size_reference(state)

    assert detected["size_reference_result"]["status"] == "failed"
    assert detected["size_reference_result"]["failure_type"] == "product_unqualified"
    assert detected["size_reference_result"]["failure_detail"] == "future_quality_rule"
    assert detected["size_reference_result"]["failed_checks"] == [
        "future_quality_rule"
    ]
    assert graph_module._size_reference_next_step({**state, **detected}) == (
        "mark_failed_and_reload_candidates"
    )

    reloaded = graph_module._mark_failed_and_reload_candidates({**state, **detected})

    assert reloaded["failed_product"]["status"] == "failed"
    assert reloaded["failed_product"]["reason"] == "预留质检项失败"


def test_failed_size_reference_checkpoint_is_not_reused(monkeypatch, tmp_path) -> None:
    collage = tmp_path / "main_image_collage.jpg"
    Image.new("RGB", (10, 10), "white").save(collage)
    calls = {"count": 0}

    def fake_detect_size_reference_images(_collage_path, logger=None):
        calls["count"] += 1
        return SizeReferenceDetection(
            can_judge_size=True,
            image_numbers=[1],
            size_reference_image_number=1,
            main_image_number=1,
            reason="重试成功",
        )

    monkeypatch.setattr(
        graph_module,
        "detect_size_reference_images",
        fake_detect_size_reference_images,
    )

    state = {
        "selected_product": {
            "id": 1,
            "product_id": "p-1",
            "platform": "1688",
            "status": "processing",
        },
        "main_image_result": {
            "status": "ok",
            "path": str(collage),
            "source_image_count": 1,
            "numbered_sources": [{"index": 1, "path": str(collage), "url": ""}],
        },
    }
    checkpoint_input = checkpoints_module.checkpoint_input(
        product=checkpoints_module.selected_product_identity(state),
        collage_path=str(collage),
        source_image_count=1,
        numbered_sources=[{"index": 1, "path": str(collage), "url": ""}],
    )
    state["ai_checkpoints"] = {
        "detect_size_reference": checkpoints_module.build_ai_checkpoint(
            checkpoint_key="detect_size_reference",
            checkpoint_input=checkpoint_input,
            checkpoint_result={"status": "failed", "reason": "HTTP 503"},
            source="llm_error",
        )
    }

    output = graph_module._detect_size_reference(state)

    assert calls["count"] == 1
    assert output["size_reference_result"]["status"] == "ok"
    assert "checkpoint" not in output["size_reference_result"]


def test_size_reference_detection_exception_stops_without_failed_state(
    monkeypatch,
    tmp_path,
) -> None:
    collage = tmp_path / "main_image_collage.jpg"
    Image.new("RGB", (10, 10), "white").save(collage)

    def fake_detect_size_reference_images(_collage_path, logger=None):
        raise RuntimeError("HTTP 503")

    monkeypatch.setattr(
        graph_module,
        "detect_size_reference_images",
        fake_detect_size_reference_images,
    )

    state = {
        "selected_product": {
            "id": 1,
            "product_id": "p-1",
            "platform": "1688",
            "status": "processing",
        },
        "main_image_result": {
            "status": "ok",
            "path": str(collage),
            "source_image_count": 1,
            "numbered_sources": [{"index": 1, "path": str(collage), "url": ""}],
        },
    }

    with pytest.raises(RuntimeError, match="HTTP 503"):
        graph_module._detect_size_reference(state)

    assert "size_reference_result" not in state
    assert "failed_product" not in state


def test_wearing_image_generation_result_is_checkpointed(
    monkeypatch,
    tmp_path,
) -> None:
    generated = tmp_path / "wearing_image_attempt_1.png"
    generated.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (10, 10), "green").save(generated)
    calls = {"count": 0}

    def fake_generate_wearing_image(*_args, **_kwargs):
        calls["count"] += 1
        return {
            "status": "ok",
            "reason": "wearing_image_generated",
            "generated_image_path": str(generated),
            "attempt": 1,
        }

    monkeypatch.setattr(
        graph_module,
        "generate_wearing_image",
        fake_generate_wearing_image,
    )
    state = {
        "selected_product": {
            "id": 1,
            "product_id": "p-1",
            "platform": "1688",
            "status": "processing",
        },
        "candidates": [
            {
                "id": 1,
                "product_id": "p-1",
                "platform": "1688",
                "rawdata": {},
                "status": "processing",
                "main_image": "",
                "wearing_image": "",
                "detail_image": "",
                "size_ratio_image": "",
                "multi_angle_image": "",
                "locked_at": "",
                "locked_by": "",
                "created_at": "",
                "updated_at": "",
            }
        ],
        "product_assets_dir": str(tmp_path),
        "size_reference_result": {
            "status": "ok",
        },
        "wearing_generation_prompt_result": {
            "status": "ok",
            "prompt": "compiled prompt",
            "input_images": [str(tmp_path / "main.jpg"), str(tmp_path / "size.jpg")],
        },
    }
    Image.new("RGB", (10, 10), "white").save(tmp_path / "main.jpg")
    Image.new("RGB", (10, 10), "gray").save(tmp_path / "size.jpg")

    first = graph_module._generate_wearing_image(state)
    second = graph_module._generate_wearing_image({**state, **first})

    assert calls["count"] == 1
    assert "generate_wearing_image_attempt_1" in first["ai_checkpoints"]
    assert second["wearing_image_result"]["checkpoint"] == "hit"


def test_wearing_style_selection_invalid_enroute_stops_without_failed_state(
    monkeypatch,
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    from productv2.db import init_database, upsert_enroute_image_analysis

    init_database(database_path)
    main = tmp_path / "main.jpg"
    size = tmp_path / "size.jpg"
    Image.new("RGB", (10, 10), "white").save(main)
    Image.new("RGB", (10, 10), "gray").save(size)
    upsert_enroute_image_analysis(
        database_path,
        enroute_product_id="necklaces:cached",
        enroute_category="necklaces",
        image_path="/cached/02.jpg",
        analysis_json={"summary": "profile", "is_valid_human_reference": True},
        summary="缓存摘要",
    )
    from productv2.db import upsert_model_profile

    upsert_model_profile(
        database_path,
        profile_key="romantic_rebel",
        name="Romantic Rebel",
        summary="固定模特摘要",
        image_path="/tmp/model.jpg",
    )

    def fake_select_wearing_style_profile(*_args, **_kwargs):
        return WearingStyleProfileSelection(
            selected_enroute_product_id="necklaces:missing",
            selected_model_profile_key="romantic_rebel",
            reason="测试无效选择",
        )

    monkeypatch.setattr(
        graph_module,
        "select_wearing_style_profile",
        fake_select_wearing_style_profile,
    )
    state = {
        "database_path": str(database_path),
        "enroute_reference_result": {
            "status": "ok",
            "category": "necklaces",
            "learning_references": [],
        },
        "size_reference_result": {
            "status": "ok",
            "selected_images": {
                "main_image": {"path": str(main)},
                "size_reference_image": {"path": str(size)},
            },
        },
    }

    with pytest.raises(ValueError, match="Selected Enroute analysis"):
        graph_module._select_wearing_style_profile(state)

    assert "enroute_analysis_result" not in state


def test_enroute_selection_plans_five_learning_items_when_cache_below_target(
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    enroute_dir = tmp_path / "enroute-bestsellers"
    from productv2.db import init_database, upsert_enroute_image_analysis

    init_database(database_path)
    for index in range(8):
        _write_enroute_reference(enroute_dir, "necklaces", f"{index:02d}-necklace")
    sync_enroute_learning_library(
        database_path,
        list_category_wearing_references(enroute_dir, "necklaces"),
        category="necklaces",
    )
    for index in range(3):
        upsert_enroute_image_analysis(
            database_path,
            enroute_product_id=f"necklaces:{index:02d}-necklace",
            enroute_category="necklaces",
            image_path=str(
                enroute_dir / "necklaces" / f"{index:02d}-necklace" / "02.jpg"
            ),
            analysis_json={
                "summary": f"缓存摘要 {index}",
                "is_valid_human_reference": True,
            },
            summary=f"缓存摘要 {index}",
        )

    output = graph_module._select_enroute_reference(_candidate_state(database_path))
    result = output["enroute_reference_result"]

    assert result["status"] == "ok"
    assert result["category"] == "necklaces"
    assert result["reference_source"] == "database"
    assert result["reference_count"] == 8
    assert result["cached_analysis_count"] == 3
    assert result["learning_count"] == 5
    assert len(result["learning_references"]) == 5


def test_enroute_selection_plans_one_learning_item_when_cache_at_target(
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    enroute_dir = tmp_path / "enroute-bestsellers"
    from productv2.db import init_database, upsert_enroute_image_analysis

    init_database(database_path)
    for index in range(8):
        _write_enroute_reference(enroute_dir, "necklaces", f"{index:02d}-necklace")
    sync_enroute_learning_library(
        database_path,
        list_category_wearing_references(enroute_dir, "necklaces"),
        category="necklaces",
    )
    for index in range(5):
        upsert_enroute_image_analysis(
            database_path,
            enroute_product_id=f"necklaces:{index:02d}-necklace",
            enroute_category="necklaces",
            image_path=str(
                enroute_dir / "necklaces" / f"{index:02d}-necklace" / "02.jpg"
            ),
            analysis_json={
                "summary": f"缓存摘要 {index}",
                "is_valid_human_reference": True,
            },
            summary=f"缓存摘要 {index}",
        )

    output = graph_module._select_enroute_reference(_candidate_state(database_path))
    result = output["enroute_reference_result"]

    assert result["status"] == "ok"
    assert result["cached_analysis_count"] == 5
    assert result["learning_count"] == 1
    assert len(result["learning_references"]) == 1


def test_enroute_learning_cache_accepts_current_human_reference_schema(
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    from productv2.db import init_database, upsert_enroute_image_analysis

    init_database(database_path)
    upsert_enroute_image_analysis(
        database_path,
        enroute_product_id="necklaces:current-schema",
        enroute_category="necklaces",
        image_path="/cached/02.jpg",
        analysis_json={
            "is_valid_human_reference": True,
            "analysis_scope": {"task": "photographic_reverse_profile_only"},
            "observed_facts": {
                "composition_observation": {"shot_type": "collarbone crop"}
            },
        },
        summary="当前 prompt_v2 profile",
    )

    from productv2.enroute_learning import valid_enroute_analysis_cache

    cached = valid_enroute_analysis_cache(database_path, "necklaces")

    assert len(cached) == 1
    assert cached[0]["enroute_product_id"] == "necklaces:current-schema"


def test_compile_listing_graph_still_available_for_local_checks() -> None:
    compiled = compile_listing_graph()
    assert type(compiled).__name__ == "CompiledStateGraph"
