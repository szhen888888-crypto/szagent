import json
from pathlib import Path

from PIL import Image

from productv2.db import (
    get_enroute_learning_reference,
    init_database,
    upsert_enroute_image_analysis,
)
from productv2.enroute_learning import (
    LEARNING_STATUS_FAILED,
    LEARNING_STATUS_LEARNED,
    mark_enroute_reference_failed,
    mark_enroute_reference_learned,
    mark_enroute_reference_learning,
    plan_enroute_learning_for_candidate,
    reference_from_learning_row,
    sync_enroute_learning_statuses_from_cache,
    sync_enroute_learning_library,
)
from productv2.enroute import list_category_wearing_references
from productv2.models import CandidateProduct


def _candidate() -> CandidateProduct:
    return CandidateProduct(
        id=1,
        product_id="p-1",
        platform="1688",
        rawdata={"title": "Layered necklace"},
        status="processing",
    )


def _write_reference(root: Path, category: str, name: str) -> Path:
    product_dir = root / category / name
    product_dir.mkdir(parents=True)
    Image.new("RGB", (10, 10), "white").save(product_dir / "02.jpg")
    (product_dir / "metadata.json").write_text(
        json.dumps(
            {
                "product_id": f"{category}:{name}",
                "handle": name,
                "title": name,
                "source_url": f"https://example.test/{name}",
            }
        ),
        encoding="utf-8",
    )
    return product_dir


def test_plan_syncs_reference_table_and_plans_initial_batch(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    library_dir = tmp_path / "enroute-bestsellers"
    init_database(database_path)
    for index in range(8):
        _write_reference(library_dir, "necklaces", f"{index:02d}-necklace")
    sync_enroute_learning_library(
        database_path,
        list_category_wearing_references(library_dir, "necklaces"),
        category="necklaces",
    )
    for index in range(3):
        upsert_enroute_image_analysis(
            database_path,
            enroute_product_id=f"necklaces:{index:02d}-necklace",
            enroute_category="necklaces",
            image_path=str(
                library_dir / "necklaces" / f"{index:02d}-necklace" / "02.jpg"
            ),
            analysis_json={"is_valid_human_reference": True},
            summary=f"缓存摘要 {index}",
        )

    plan = plan_enroute_learning_for_candidate(
        _candidate(),
        database_path=database_path,
        target_cache_size=5,
        initial_batch_size=5,
        incremental_batch_size=1,
    )

    assert plan.category == "necklaces"
    assert len(plan.rows) == 8
    assert plan.cached_analysis_count == 3
    assert len(plan.unlearned_rows) == 5
    assert len(plan.learning_rows) == 5
    assert plan.learning_rows[0]["enroute_product_id"] == "necklaces:03-necklace"


def test_plan_uses_incremental_batch_after_target_cache(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    library_dir = tmp_path / "enroute-bestsellers"
    init_database(database_path)
    for index in range(8):
        _write_reference(library_dir, "necklaces", f"{index:02d}-necklace")
    sync_enroute_learning_library(
        database_path,
        list_category_wearing_references(library_dir, "necklaces"),
        category="necklaces",
    )
    for index in range(5):
        upsert_enroute_image_analysis(
            database_path,
            enroute_product_id=f"necklaces:{index:02d}-necklace",
            enroute_category="necklaces",
            image_path=str(
                library_dir / "necklaces" / f"{index:02d}-necklace" / "02.jpg"
            ),
            analysis_json={"is_valid_human_reference": True},
            summary=f"缓存摘要 {index}",
        )

    plan = plan_enroute_learning_for_candidate(
        _candidate(),
        database_path=database_path,
        target_cache_size=5,
        initial_batch_size=5,
        incremental_batch_size=1,
    )

    assert plan.cached_analysis_count == 5
    assert len(plan.learning_rows) == 1
    assert plan.learning_rows[0]["enroute_product_id"] == "necklaces:05-necklace"
    assert get_enroute_learning_reference(
        database_path,
        "necklaces:00-necklace",
    )["status"] == LEARNING_STATUS_LEARNED


def test_plan_reconciles_learning_statuses_from_existing_cache(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    library_dir = tmp_path / "enroute-bestsellers"
    init_database(database_path)
    for index in range(8):
        _write_reference(library_dir, "necklaces", f"{index:02d}-necklace")
    sync_enroute_learning_library(
        database_path,
        list_category_wearing_references(library_dir, "necklaces"),
        category="necklaces",
    )
    for index in range(5):
        upsert_enroute_image_analysis(
            database_path,
            enroute_product_id=f"necklaces:{index:02d}-necklace",
            enroute_category="necklaces",
            image_path=str(
                library_dir / "necklaces" / f"{index:02d}-necklace" / "02.jpg"
            ),
            analysis_json={"is_valid_human_reference": True},
            summary=f"缓存摘要 {index}",
        )
        mark_enroute_reference_failed(
            database_path,
            reference_from_learning_row(
                get_enroute_learning_reference(
                    database_path,
                    f"necklaces:{index:02d}-necklace",
                )
            ),
            error="历史状态未同步",
        )

    assert get_enroute_learning_reference(
        database_path,
        "necklaces:00-necklace",
    )["status"] == LEARNING_STATUS_FAILED

    plan = plan_enroute_learning_for_candidate(
        _candidate(),
        database_path=database_path,
        target_cache_size=5,
        initial_batch_size=5,
        incremental_batch_size=1,
    )

    assert plan.cache_status_synced_count == 5
    assert plan.cached_analysis_count == 5
    assert len(plan.learning_rows) == 1
    assert plan.learning_rows[0]["enroute_product_id"] == "necklaces:05-necklace"
    assert get_enroute_learning_reference(
        database_path,
        "necklaces:00-necklace",
    )["status"] == LEARNING_STATUS_LEARNED


def test_sync_enroute_learning_statuses_from_cache_only_uses_valid_cache(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    library_dir = tmp_path / "enroute-bestsellers"
    init_database(database_path)
    for name in ("valid-necklace", "invalid-necklace"):
        _write_reference(library_dir, "necklaces", name)
    sync_enroute_learning_library(
        database_path,
        list_category_wearing_references(library_dir, "necklaces"),
        category="necklaces",
    )
    upsert_enroute_image_analysis(
        database_path,
        enroute_product_id="necklaces:valid-necklace",
        enroute_category="necklaces",
        image_path=str(library_dir / "necklaces" / "valid-necklace" / "02.jpg"),
        analysis_json={"is_valid_human_reference": True},
        summary="有效缓存",
    )
    mark_enroute_reference_failed(
        database_path,
        reference_from_learning_row(
            get_enroute_learning_reference(
                database_path,
                "necklaces:valid-necklace",
            )
        ),
        error="历史状态未同步",
    )
    upsert_enroute_image_analysis(
        database_path,
        enroute_product_id="necklaces:invalid-necklace",
        enroute_category="necklaces",
        image_path=str(library_dir / "necklaces" / "invalid-necklace" / "02.jpg"),
        analysis_json={"is_valid_human_reference": False},
        summary="无效缓存",
    )

    synced_count = sync_enroute_learning_statuses_from_cache(
        database_path,
        "necklaces",
    )

    assert synced_count == 1
    assert get_enroute_learning_reference(
        database_path,
        "necklaces:valid-necklace",
    )["status"] == LEARNING_STATUS_LEARNED
    assert get_enroute_learning_reference(
        database_path,
        "necklaces:invalid-necklace",
    )["status"] == "pending"


def test_sync_prunes_deleted_local_references(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    library_dir = tmp_path / "enroute-bestsellers"
    init_database(database_path)
    first = _write_reference(library_dir, "necklaces", "01-necklace")
    second = _write_reference(library_dir, "necklaces", "02-necklace")
    references = [
        reference_from_learning_row(
            {
                "enroute_product_id": "necklaces:01-necklace",
                "enroute_category": "necklaces",
                "product_dir": str(first),
                "image_path": str(first / "02.jpg"),
                "metadata": {"title": "01-necklace"},
            }
        ),
        reference_from_learning_row(
            {
                "enroute_product_id": "necklaces:02-necklace",
                "enroute_category": "necklaces",
                "product_dir": str(second),
                "image_path": str(second / "02.jpg"),
                "metadata": {"title": "02-necklace"},
            }
        ),
    ]
    sync_enroute_learning_library(database_path, references, category="necklaces")

    sync_enroute_learning_library(database_path, references[:1], category="necklaces")

    assert get_enroute_learning_reference(database_path, "necklaces:02-necklace") is None


def test_learning_status_helpers_update_row(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    product_dir = _write_reference(tmp_path / "enroute-bestsellers", "necklaces", "demo")
    reference = reference_from_learning_row(
        {
            "enroute_product_id": "necklaces:demo",
            "enroute_category": "necklaces",
            "product_dir": str(product_dir),
            "image_path": str(product_dir / "02.jpg"),
            "metadata": {"title": "demo"},
        }
    )
    sync_enroute_learning_library(database_path, [reference], category="necklaces")

    mark_enroute_reference_learning(
        database_path,
        reference,
        workflow_log_path="/tmp/workflow.log",
    )
    failed = mark_enroute_reference_failed(
        database_path,
        reference,
        error="LLM timeout",
    )
    learned = mark_enroute_reference_learned(
        database_path,
        reference,
        analysis_id=12,
    )

    assert failed["status"] == LEARNING_STATUS_FAILED
    assert failed["learning_attempts"] == 1
    assert learned["status"] == LEARNING_STATUS_LEARNED
    assert learned["analysis_id"] == 12
