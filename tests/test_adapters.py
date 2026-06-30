import random
import importlib

from productv2.adapters import adapter_module_name, has_platform_adapter
from productv2.db import init_database
from productv2.models import CandidateProduct
from productv2.selection import select_unfinished_product_with_adapter


def test_adapter_discovery_finds_1688_platform_module() -> None:
    assert adapter_module_name("1688") == "1688"
    assert has_platform_adapter("1688") is True
    assert has_platform_adapter("missing-platform") is False


def test_selection_skips_all_unfinished_products_when_adapters_are_missing(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    init_database(database_path)

    import sqlite3

    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO products (product_id, platform, rawdata, status)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("p-missing", "missing-platform", "{}", "all_pendding"),
                ("p-other", "other-platform", "{}", "all_pendding"),
                ("p-done", "missing-platform", "{}", "published"),
            ],
        )

    selection = select_unfinished_product_with_adapter(
        database_path=database_path,
        rng=random.Random(1),
    )

    assert selection.unfinished_count == 2
    assert selection.candidate is None
    assert selection.selected_adapter_name is None
    assert len(selection.skipped_without_adapter) == 2


def test_selection_loads_unfinished_products_locks_and_uses_adapter(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    init_database(database_path)

    import sqlite3

    with sqlite3.connect(database_path) as connection:
        connection.executemany(
            """
            INSERT INTO products (product_id, platform, rawdata, status)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("p-missing", "missing-platform", "{}", "all_pendding"),
                ("p-1688", "1688", "{}", "all_pendding"),
                ("p-locked", "1688", "{}", "all_pendding"),
            ],
        )
        connection.execute(
            """
            UPDATE products
            SET locked_at = ?, locked_by = ?
            WHERE product_id = ?
            """,
            ("2026-06-23T00:00:00", "worker-1", "p-locked"),
        )

    selection = select_unfinished_product_with_adapter(
        database_path=database_path,
        rng=random.Random(1),
        locked_by="test-worker",
    )

    assert selection.unfinished_count == 2
    assert selection.candidate is not None
    assert selection.candidate.product_id == "p-1688"
    assert selection.selected_adapter_name == "1688"
    assert selection.candidate.status == "processing"
    assert selection.candidate.locked_at is not None
    assert selection.candidate.locked_by == "test-worker"


def test_1688_adapter_extracts_main_and_specification_images() -> None:
    adapter_module = importlib.import_module("productv2.adapters.1688")

    candidate = CandidateProduct(
        product_id="p-1",
        platform="1688",
        rawdata={
            "detail": {
                "image_urls": [
                    "https://img.alicdn.com/icon.svg",
                    "https://img.alicdn.com/imgextra/i2/O1CN01pa-55-tps-24-24.svg",
                    "https://cbu01.alicdn.com/img/ibank/main.jpg_.webp",
                    "https://cbu01.alicdn.com/img/ibank/main.jpg_.webp",
                    "https://cbu01.alicdn.com/img/ibank/main.jpg_sum.jpg",
                ],
                "sku_images": {
                    "red": "https://cbu01.alicdn.com/img/ibank/red.jpg_.webp"
                },
            }
        },
    )

    adapter = adapter_module.Adapter()

    assert adapter.get_main_images(candidate) == [
        "https://cbu01.alicdn.com/img/ibank/main.jpg_.webp"
    ]
    assert adapter.get_specification_images(candidate) == [
        "https://cbu01.alicdn.com/img/ibank/red.jpg_.webp"
    ]
