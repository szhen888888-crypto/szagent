import json
import sqlite3

from productv2.db import init_database
from productv2.models import CandidateProduct
from productv2.state import (
    clear_product_state,
    get_current_product,
    get_extra,
    get_state_snapshot,
    initialize_product_state,
    set_extra,
    set_image,
    set_status,
)


def test_product_state_updates_status_and_images_in_database(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    init_database(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO products (product_id, platform, rawdata, status)
            VALUES (?, ?, ?, ?)
            """,
            ("p-1", "1688", json.dumps({"title": "demo"}), "processing"),
        )

    initialize_product_state(
        CandidateProduct(
            product_id="p-1",
            platform="1688",
            rawdata={"title": "demo"},
            status="processing",
        ),
        database_path=database_path,
    )

    set_image("main_image", "https://example.test/main.jpg")
    updated = set_status("image_ready")

    assert updated.status == "image_ready"
    assert get_current_product().main_image == "https://example.test/main.jpg"

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT status, main_image
            FROM products
            WHERE product_id = ? AND platform = ?
            """,
            ("p-1", "1688"),
        ).fetchone()

    assert row["status"] == "image_ready"
    assert row["main_image"] == "https://example.test/main.jpg"
    clear_product_state()


def test_product_state_extras_are_runtime_only(tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    init_database(database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO products (product_id, platform, rawdata, status)
            VALUES (?, ?, ?, ?)
            """,
            ("p-1", "1688", json.dumps({"title": "demo"}), "processing"),
        )

    initialize_product_state(
        CandidateProduct(
            product_id="p-1",
            platform="1688",
            rawdata={"title": "demo"},
            status="processing",
        ),
        database_path=database_path,
    )

    set_extra("main_image_collage", {"path": "tmp/collage.jpg"})

    assert get_extra("main_image_collage") == {"path": "tmp/collage.jpg"}
    assert get_state_snapshot()["extras"]["main_image_collage"]["path"] == "tmp/collage.jpg"

    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT main_image
            FROM products
            WHERE product_id = ? AND platform = ?
            """,
            ("p-1", "1688"),
        ).fetchone()

    assert row[0] == ""
    clear_product_state()
