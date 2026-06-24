import json
import sqlite3

from productv2.cli import main
from productv2.db import RAW_IMPORT_STATUS, init_database


def test_reset_db_cli_accepts_global_database_path_before_subcommand(
    capsys,
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    raw_data_dir = tmp_path / "raw"
    raw_data_dir.mkdir()
    raw_file = raw_data_dir / "batch.json"
    raw_file.write_text(
        json.dumps(
            [
                {
                    "product_id": "raw-new",
                    "platform": "1688",
                    "rawdata": {"title": "Should Not Import"},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    init_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO products (
                product_id, platform, rawdata, status, main_image, locked_at, locked_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "cli-reset",
                "1688",
                "{}",
                "processing",
                "/tmp/main.jpg",
                "2026-06-24T00:00:00",
                "worker-1",
            ),
        )

    main(
        [
            "--database-path",
            str(database_path),
            "--raw-data-dir",
            str(raw_data_dir),
            "reset-db",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert output["products_reset"] == 1
    assert output["status"] == RAW_IMPORT_STATUS
    assert raw_file.exists()

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT product_id, status, main_image, locked_at, locked_by
            FROM products
            ORDER BY product_id
            """
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["product_id"] == "cli-reset"
    assert rows[0]["status"] == RAW_IMPORT_STATUS
    assert rows[0]["main_image"] == ""
    assert rows[0]["locked_at"] is None
    assert rows[0]["locked_by"] is None


def test_reset_db_cli_accepts_database_path_after_subcommand(capsys, tmp_path) -> None:
    database_path = tmp_path / "productv2.db"
    init_database(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO products (product_id, platform, rawdata, status)
            VALUES (?, ?, ?, ?)
            """,
            ("cli-reset-after", "1688", "{}", "processing"),
        )

    main(["reset-db", "--database-path", str(database_path), "--status", "candidate"])

    output = json.loads(capsys.readouterr().out)
    assert output["products_reset"] == 1
    assert output["status"] == "candidate"

    with sqlite3.connect(database_path) as connection:
        status = connection.execute(
            """
            SELECT status
            FROM products
            WHERE product_id = ? AND platform = ?
            """,
            ("cli-reset-after", "1688"),
        ).fetchone()[0]

    assert status == "candidate"
