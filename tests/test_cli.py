import json
import sqlite3

from productv2 import cli
from productv2.cli import main
from productv2.db import RAW_IMPORT_STATUS, init_database


def test_import_raw_cli_imports_all_raw_json_files(
    capsys,
    tmp_path,
) -> None:
    database_path = tmp_path / "productv2.db"
    raw_data_dir = tmp_path / "raw"
    raw_data_dir.mkdir()
    for index in (1, 2):
        (raw_data_dir / f"batch-{index}.json").write_text(
            json.dumps(
                [
                    {
                        "product_id": f"raw-{index}",
                        "platform": "1688",
                        "rawdata": {"title": f"Raw Product {index}"},
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    main(
        [
            "--database-path",
            str(database_path),
            "--raw-data-dir",
            str(raw_data_dir),
            "import-raw",
        ]
    )

    output = capsys.readouterr().out
    summary = json.loads(output)
    assert summary["files_scanned"] == 2
    assert summary["files_imported"] == 2
    assert summary["products_imported"] == 2
    assert not list(raw_data_dir.glob("*.json"))

    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT product_id, status FROM products ORDER BY product_id"
        ).fetchall()

    assert rows == [("raw-1", RAW_IMPORT_STATUS), ("raw-2", RAW_IMPORT_STATUS)]


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


def test_restart_workflow_prefers_interrupted_thread_without_resume(
    monkeypatch,
) -> None:
    def fake_post(base_url, path, payload):
        assert base_url == "http://testserver"
        if path == "/threads/search" and payload["status"] == "busy":
            return []
        if path == "/threads/search" and payload["status"] == "interrupted":
            return [
                {
                    "thread_id": "thread-1",
                    "status": "interrupted",
                    "updated_at": "2026-06-25T01:00:00+00:00",
                    "metadata": {"graph_id": "product_listing"},
                }
            ]
        raise AssertionError(f"unexpected POST {path}: {payload}")

    def fake_get(base_url, path):
        assert path == "/threads/thread-1/state"
        return {
            "values": {
                "selected_product": {
                    "product_id": "p1",
                    "platform": "1688",
                    "status": "processing",
                    "rawdata": {"title": "Product 1"},
                },
                "wearing_image_result": {
                    "status": "ok",
                    "generated_image_path": "data/products/1688/p1/wearing.png",
                },
            },
            "next": ["wait_manual_review"],
            "interrupts": [
                {
                    "id": "interrupt-1",
                    "value": {
                        "type": "wearing_image_review",
                        "generated_image_path": "data/products/1688/p1/wearing.png",
                        "attempt": 1,
                        "options": ["approve", "regenerate", "reject"],
                    },
                }
            ],
        }

    monkeypatch.setattr(cli, "_api_post_json", fake_post)
    monkeypatch.setattr(cli, "_api_get_json", fake_get)

    result = cli.restart_workflow_via_api(
        api_url="http://testserver",
        assistant_id="product_listing",
    )

    assert result["mode"] == "resume_required"
    assert result["thread_id"] == "thread-1"
    assert result["summary"]["product_id"] == "p1"
    assert result["summary"]["interrupt_count"] == 1


def test_restart_workflow_resumes_interrupted_thread_when_payload_is_given(
    monkeypatch,
) -> None:
    posts = []

    def fake_post(base_url, path, payload):
        posts.append((path, payload))
        if path == "/threads/search" and payload["status"] == "busy":
            return []
        if path == "/threads/search" and payload["status"] == "interrupted":
            return [
                {
                    "thread_id": "thread-1",
                    "status": "interrupted",
                    "updated_at": "2026-06-25T01:00:00+00:00",
                    "metadata": {"graph_id": "product_listing"},
                }
            ]
        if path == "/threads/thread-1/runs":
            return {"run_id": "run-1"}
        raise AssertionError(f"unexpected POST {path}: {payload}")

    monkeypatch.setattr(cli, "_api_post_json", fake_post)
    monkeypatch.setattr(
        cli,
        "_api_get_json",
        lambda base_url, path: {
            "values": {},
            "next": ["wait_manual_review"],
            "interrupts": [
                {
                    "id": "interrupt-1",
                    "value": {
                        "type": "wearing_image_review",
                        "options": ["approve", "regenerate", "reject"],
                    },
                }
            ],
        },
    )

    result = cli.restart_workflow_via_api(
        api_url="http://testserver",
        assistant_id="product_listing",
        resume_payload={"action": "approve"},
    )

    assert result["mode"] == "resumed"
    assert result["run_id"] == "run-1"
    assert posts[-1] == (
        "/threads/thread-1/runs",
        {
            "assistant_id": "product_listing",
            "command": {"resume": {"action": "approve"}},
            "multitask_strategy": "reject",
        },
    )


def test_restart_workflow_starts_new_thread_when_none_unfinished(monkeypatch) -> None:
    def fake_post(base_url, path, payload):
        if path == "/threads/search":
            return []
        if path == "/threads":
            return {"thread_id": "thread-new"}
        if path == "/threads/thread-new/runs":
            return {"run_id": "run-new"}
        raise AssertionError(f"unexpected POST {path}: {payload}")

    monkeypatch.setattr(cli, "_api_post_json", fake_post)

    result = cli.restart_workflow_via_api(
        api_url="http://testserver",
        assistant_id="product_listing",
    )

    assert result["mode"] == "started_after_no_unfinished_thread"
    assert result["thread_id"] == "thread-new"


def test_restart_workflow_skips_interrupted_thread_without_interrupt_payload(
    monkeypatch,
) -> None:
    def fake_post(base_url, path, payload):
        if path == "/threads/search" and payload["status"] == "busy":
            return []
        if path == "/threads/search" and payload["status"] == "interrupted":
            return [
                {
                    "thread_id": "thread-stale",
                    "status": "interrupted",
                    "updated_at": "2026-06-25T01:28:15+00:00",
                    "metadata": {"graph_id": "product_listing"},
                }
            ]
        if path == "/threads":
            return {"thread_id": "thread-new"}
        if path == "/threads/thread-new/runs":
            return {"run_id": "run-new"}
        raise AssertionError(f"unexpected POST {path}: {payload}")

    def fake_get(base_url, path):
        assert path == "/threads/thread-stale/state"
        return {
            "values": {
                "selected_product": {
                    "product_id": "661767228117",
                    "platform": "1688",
                    "status": "processing",
                }
            },
            "next": ["detect_size_reference"],
            "interrupts": [],
        }

    monkeypatch.setattr(cli, "_api_post_json", fake_post)
    monkeypatch.setattr(cli, "_api_get_json", fake_get)

    result = cli.restart_workflow_via_api(
        api_url="http://testserver",
        assistant_id="product_listing",
    )

    assert result["mode"] == "started_after_no_unfinished_thread"
    assert result["thread_id"] == "thread-new"
    assert result["skipped_threads"][0]["thread_id"] == "thread-stale"
    assert (
        result["skipped_threads"][0]["reason"]
        == "interrupted_without_interrupt_payload"
    )


def test_restart_workflow_with_selected_thread_does_not_switch_to_other_thread(
    monkeypatch,
) -> None:
    posts = []

    def fake_get(base_url, path):
        assert base_url == "http://testserver"
        assert path == "/threads/thread-stale/state"
        return {
            "values": {
                "selected_product": {
                    "product_id": "661767228117",
                    "platform": "1688",
                    "status": "processing",
                },
                "size_reference_result": {
                    "status": "failed",
                    "reason": "HTTP 503",
                },
            },
            "next": ["detect_size_reference"],
            "interrupts": [],
        }

    def fake_post(base_url, path, payload):
        posts.append((path, payload))
        assert base_url == "http://testserver"
        if path == "/threads/thread-stale/runs":
            return {"run_id": "run-retry"}
        raise AssertionError("selected thread recovery must not search other threads")

    monkeypatch.setattr(cli, "_api_get_json", fake_get)
    monkeypatch.setattr(cli, "_api_post_json", fake_post)

    result = cli.restart_workflow_via_api(
        api_url="http://testserver",
        assistant_id="product_listing",
        thread_id="thread-stale",
    )

    assert result["mode"] == "selected_thread_restarted"
    assert result["thread_id"] == "thread-stale"
    assert result["run_id"] == "run-retry"
    assert "普通节点重试" in result["message"]
    assert result["summary"]["stop_reason"] == "尺寸检测失败"
    assert posts == [
        (
            "/threads/thread-stale/runs",
            {
                "assistant_id": "product_listing",
                "input": {},
                "multitask_strategy": "reject",
            },
        )
    ]


def test_thread_summary_prefers_task_error_over_stale_failed_state() -> None:
    summary = cli._summarize_thread_state(
        {
            "values": {
                "selected_product": {
                    "product_id": "p-1",
                    "platform": "1688",
                    "status": "processing",
                },
                "size_reference_result": {
                    "status": "failed",
                    "reason": "历史尺寸检测失败",
                },
            },
            "next": ["detect_size_reference"],
            "interrupts": [],
            "tasks": [
                {
                    "id": "task-1",
                    "error": "RuntimeError: HTTP 503",
                }
            ],
        }
    )

    assert summary["stop_reason_code"] == "task_error"
    assert summary["stop_reason"] == "节点执行异常"
    assert summary["stop_reason_detail"] == "RuntimeError: HTTP 503"


def test_thread_progress_summarizes_running_node() -> None:
    progress = cli._summarize_thread_progress(
        state={
            "next": ["generate_wearing_image"],
            "tasks": [
                {
                    "id": "task-1",
                    "name": "generate_wearing_image",
                    "error": None,
                    "interrupts": [],
                }
            ],
        },
        thread={"status": "busy"},
        runs=[
            {
                "run_id": "run-1",
                "status": "running",
                "created_at": "2026-06-26T05:00:00+00:00",
                "updated_at": "2026-06-26T05:01:00+00:00",
                "multitask_strategy": "reject",
            }
        ],
    )

    assert progress["running"] is True
    assert progress["phase"] == "generate_wearing_image"
    assert progress["phase_label"] == "生成穿戴图"
    assert progress["active_run"]["run_id"] == "run-1"
    assert "第三方图片接口" in progress["message"]


def test_thread_progress_shows_manual_review_instead_of_completed() -> None:
    progress = cli._summarize_thread_progress(
        state={
            "next": ["wait_manual_review"],
            "interrupts": [
                {
                    "id": "interrupt-1",
                    "value": {"type": "wearing_image_review"},
                }
            ],
            "tasks": [
                {
                    "id": "task-1",
                    "name": "wait_manual_review",
                    "error": None,
                    "interrupts": [{"id": "interrupt-1"}],
                }
            ],
        },
        thread={"status": "interrupted"},
        runs=[
            {
                "run_id": "run-1",
                "status": "success",
                "created_at": "2026-06-26T05:00:00+00:00",
                "updated_at": "2026-06-26T05:01:00+00:00",
                "multitask_strategy": "reject",
            }
        ],
    )

    assert progress["running"] is False
    assert progress["phase"] == "wait_manual_review"
    assert progress["status"] == "manual_review"
    assert progress["status_label"] == "等待人工审核"
    assert progress["message"] == "穿戴图已生成，等待人工审核。"


def test_thread_summary_prefers_pending_node_over_stale_failed_product() -> None:
    summary = cli._summarize_thread_state(
        {
            "values": {
                "selected_product": {
                    "product_id": "p-1",
                    "platform": "1688",
                    "status": "processing",
                },
                "failed_product": {
                    "product_id": "old-p",
                    "status": "failed",
                    "reason": "历史失败",
                },
            },
            "next": ["generate_wearing_image"],
            "interrupts": [],
        }
    )

    assert summary["stop_reason_code"] == "waiting_wearing_generation"
    assert summary["stop_reason"] == "停在穿戴图生成"
