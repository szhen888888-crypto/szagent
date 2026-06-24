import json
import sqlite3

import pytest

from productv2.db import (
    RAW_IMPORT_STATUS,
    get_enroute_image_analysis,
    import_raw_data_directory,
    init_database,
    load_model_profiles,
    load_products_from_database,
    load_unfinished_products_from_database,
    reset_products_for_processing,
    seed_candidate_products,
    sync_default_model_profiles,
    upsert_enroute_image_analysis,
    upsert_model_profile,
)


def write_candidate_fixture(path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "product_id": "fixture-1",
                    "platform": "1688",
                    "rawdata": {"title": "Fixture Product 1"},
                },
                {
                    "product_id": "fixture-2",
                    "platform": "1688",
                    "rawdata": {"title": "Fixture Product 2"},
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_init_database_creates_products_table_with_defaults(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"

    init_database(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        columns = {
            row["name"]: row
            for row in connection.execute("PRAGMA table_info(products)").fetchall()
        }

        assert columns["product_id"]["notnull"] == 1
        assert columns["platform"]["notnull"] == 1
        assert columns["rawdata"]["notnull"] == 1
        assert columns["status"]["notnull"] == 1
        assert columns["locked_at"]["notnull"] == 0
        assert columns["locked_by"]["notnull"] == 0

        for image_column in (
            "main_image",
            "wearing_image",
            "detail_image",
            "size_ratio_image",
            "multi_angle_image",
        ):
            assert columns[image_column]["notnull"] == 1
            assert columns[image_column]["dflt_value"] == "''"

        connection.execute(
            """
            INSERT INTO products (product_id, platform, rawdata)
            VALUES (?, ?, ?)
            """,
            ("p-1", "1688", json.dumps({"title": "demo"})),
        )
        row = connection.execute(
            """
            SELECT status, main_image, wearing_image, detail_image,
                   size_ratio_image, multi_angle_image
            FROM products
            WHERE product_id = ? AND platform = ?
            """,
            ("p-1", "1688"),
        ).fetchone()

        assert row["status"] == "candidate"
        assert row["main_image"] == ""
        assert row["wearing_image"] == ""
        assert row["detail_image"] == ""
        assert row["size_ratio_image"] == ""
        assert row["multi_angle_image"] == ""

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO products (product_id, platform, rawdata)
                VALUES (?, ?, ?)
                """,
                ("p-1", "1688", "{}"),
            )


def test_init_database_creates_enroute_image_analysis_cache(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"

    init_database(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        columns = {
            row["name"]: row
            for row in connection.execute(
                "PRAGMA table_info(enroute_image_analyses)"
            ).fetchall()
        }

    assert columns["enroute_product_id"]["notnull"] == 1
    assert columns["enroute_category"]["notnull"] == 1
    assert columns["analysis_json"]["notnull"] == 1
    assert columns["summary"]["notnull"] == 1


def test_init_database_creates_model_profiles_table(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"

    init_database(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        columns = {
            row["name"]: row
            for row in connection.execute("PRAGMA table_info(model_profiles)").fetchall()
        }

    assert columns["profile_key"]["notnull"] == 1
    assert columns["summary"]["notnull"] == 1
    assert columns["image_path"]["notnull"] == 1


def test_upsert_and_load_model_profiles(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"

    first = upsert_model_profile(
        database_path,
        profile_key="romantic_rebel_european",
        name="Romantic Rebel",
        summary="深色头发，冷淡叛逆，适合蛇链。",
        image_path="/tmp/model.jpg",
        metadata_path="/tmp/metadata.json",
    )
    second = upsert_model_profile(
        database_path,
        profile_key="romantic_rebel_european",
        name="Romantic Rebel",
        summary="更新后的摘要。",
        image_path="/tmp/model-v2.jpg",
    )

    assert second["id"] == first["id"]
    assert second["summary"] == "更新后的摘要。"
    assert load_model_profiles(database_path)[0]["image_path"] == "/tmp/model-v2.jpg"


def test_sync_default_model_profiles_writes_generated_paths(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    model_dir = tmp_path / "model_profiles"
    profile_dir = model_dir / "romantic_rebel_european"
    profile_dir.mkdir(parents=True)
    (profile_dir / "model.jpg").write_bytes(b"fake")
    (profile_dir / "metadata.json").write_text("{}", encoding="utf-8")

    profiles = sync_default_model_profiles(database_path, model_dir)

    assert len(profiles) == 5
    romantic = next(
        profile
        for profile in profiles
        if profile["profile_key"] == "romantic_rebel_european"
    )
    assert "Romantic Rebel" in romantic["summary"]
    assert romantic["image_path"] == str(profile_dir / "model.jpg")
    assert romantic["metadata_path"] == str(profile_dir / "metadata.json")


def test_upsert_enroute_image_analysis_caches_by_unique_product(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"

    first = upsert_enroute_image_analysis(
        database_path,
        enroute_product_id="enroute-1",
        enroute_category="necklaces",
        enroute_title="Reference Necklace",
        enroute_handle="reference-necklace",
        image_path="/tmp/02.jpg",
        analysis_json={
            "is_valid_wearing_reference": True,
            "clothing_style": {"category": "细肩带基础上装"},
        },
        summary="适合项链佩戴图，重点适配短链、锁骨链、中长链",
    )
    second = upsert_enroute_image_analysis(
        database_path,
        enroute_product_id="enroute-1",
        enroute_category="necklaces",
        enroute_title="Reference Necklace Updated",
        enroute_handle="reference-necklace",
        image_path="/tmp/02-updated.jpg",
        analysis_json={
            "is_valid_wearing_reference": True,
            "clothing_style": {"category": "半透针织"},
        },
        summary="适合项链佩戴图，长链需更宽构图",
    )

    assert first["enroute_product_id"] == "enroute-1"
    assert second["id"] == first["id"]
    assert second["image_path"] == "/tmp/02-updated.jpg"
    assert second["analysis_json"]["clothing_style"]["category"] == "半透针织"

    cached = get_enroute_image_analysis(database_path, "enroute-1")

    assert cached is not None
    assert cached["summary"] == "适合项链佩戴图，长链需更宽构图"

    with sqlite3.connect(database_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM enroute_image_analyses"
        ).fetchone()[0]

    assert count == 1


def test_seed_candidate_products_upserts_candidate_data(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    data_path = tmp_path / "candidates.json"
    write_candidate_fixture(data_path)

    seeded_count = seed_candidate_products(
        database_path=database_path,
        data_path=data_path,
        limit=2,
    )

    assert seeded_count == 2
    with sqlite3.connect(database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        assert count == 2

    products = load_products_from_database(database_path=database_path, limit=1)

    assert len(products) == 1
    assert products[0].product_id == "fixture-1"
    assert products[0].rawdata["title"] == "Fixture Product 1"
    assert products[0].locked_at is None
    assert products[0].locked_by is None


def test_load_unfinished_products_filters_completed_and_locked_statuses(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    init_database(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO products (
                product_id, platform, rawdata, status, locked_at, locked_by
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                ("p-1", "1688", "{}", "all_pendding", None, None),
                ("p-2", "1688", "{}", "candidate", None, None),
                ("p-3", "1688", "{}", "published", None, None),
                ("p-4", "1688", "{}", "completed", None, None),
                ("p-5", "1688", "{}", "all_pendding", "2026-06-23T00:00:00", "worker-1"),
                ("p-6", "1688", "{}", "failed", None, None),
            ],
        )

    products = load_unfinished_products_from_database(database_path=database_path)

    assert [product.product_id for product in products] == ["p-1", "p-2"]


def test_reset_products_for_processing_clears_status_images_and_locks(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    init_database(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO products (
                product_id, platform, rawdata, status, main_image, wearing_image,
                detail_image, size_ratio_image, multi_angle_image, locked_at, locked_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "p-reset",
                "1688",
                "{}",
                "processing",
                "/tmp/main.jpg",
                "/tmp/wearing.jpg",
                "/tmp/detail.jpg",
                "/tmp/size.jpg",
                "/tmp/multi.jpg",
                "2026-06-24T00:00:00",
                "worker-1",
            ),
        )

    summary = reset_products_for_processing(database_path)

    assert summary["products_reset"] == 1
    assert summary["status"] == RAW_IMPORT_STATUS
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT status, main_image, wearing_image, detail_image,
                   size_ratio_image, multi_angle_image, locked_at, locked_by
            FROM products
            WHERE product_id = ? AND platform = ?
            """,
            ("p-reset", "1688"),
        ).fetchone()

    assert row["status"] == RAW_IMPORT_STATUS
    assert row["main_image"] == ""
    assert row["wearing_image"] == ""
    assert row["detail_image"] == ""
    assert row["size_ratio_image"] == ""
    assert row["multi_angle_image"] == ""
    assert row["locked_at"] is None
    assert row["locked_by"] is None


def test_import_raw_data_directory_imports_and_deletes_json_files(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    raw_data_dir = tmp_path / "raw"
    raw_data_dir.mkdir()
    raw_file = raw_data_dir / "batch.json"
    raw_file.write_text(
        json.dumps(
            [
                {
                    "product_id": "raw-1",
                    "platform": "1688",
                    "rawdata": {"title": "Raw Product 1"},
                },
                {
                    "product_id": "raw-2",
                    "platform": "1688",
                    "rawdata": {"title": "Raw Product 2"},
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = import_raw_data_directory(
        database_path=database_path,
        raw_data_dir=raw_data_dir,
    )

    assert summary["files_scanned"] == 1
    assert summary["files_imported"] == 1
    assert summary["products_imported"] == 2
    assert summary["failed_files"] == []
    assert not raw_file.exists()

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT product_id, status, main_image, wearing_image, detail_image,
                   size_ratio_image, multi_angle_image
            FROM products
            ORDER BY product_id
            """
        ).fetchall()

    assert [row["product_id"] for row in rows] == ["raw-1", "raw-2"]
    for row in rows:
        assert row["status"] == RAW_IMPORT_STATUS
        assert row["main_image"] == ""
        assert row["wearing_image"] == ""
        assert row["detail_image"] == ""
        assert row["size_ratio_image"] == ""
        assert row["multi_angle_image"] == ""


def test_import_raw_data_directory_keeps_failed_json_file(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    raw_data_dir = tmp_path / "raw"
    raw_data_dir.mkdir()
    raw_file = raw_data_dir / "bad.json"
    raw_file.write_text("{not-json", encoding="utf-8")

    summary = import_raw_data_directory(
        database_path=database_path,
        raw_data_dir=raw_data_dir,
    )

    assert summary["files_scanned"] == 1
    assert summary["files_imported"] == 0
    assert summary["products_imported"] == 0
    assert len(summary["failed_files"]) == 1
    assert raw_file.exists()

    data_path = tmp_path / "candidates.json"
    write_candidate_fixture(data_path)
    seeded_count = seed_candidate_products(
        database_path=database_path,
        data_path=data_path,
        limit=2,
    )

    assert seeded_count == 2
    with sqlite3.connect(database_path) as connection:
        count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        assert count == 2
