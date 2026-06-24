"""SQLite database schema and seed helpers."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from productv2.config import (
    DEFAULT_CANDIDATE_DATA,
    DEFAULT_DATABASE_PATH,
    DEFAULT_RAW_DATA_DIR,
)
from productv2.data import load_candidate_products, load_candidate_products_from_json_file
from productv2.model_profiles import VIRTUAL_MODEL_PROFILES, virtual_model_profile_summary
from productv2.models import CandidateProduct


RAW_IMPORT_STATUS = "all_pendding"
PROCESSING_STATUS = "processing"
FAILED_STATUS = "failed"
COMPLETED_STATUSES = ("done", "completed", "published", FAILED_STATUS)
PRODUCT_COLUMNS = """
    id, product_id, platform, rawdata, status, main_image, wearing_image,
    detail_image, size_ratio_image, multi_angle_image, locked_at, locked_by,
    created_at, updated_at
"""

PRODUCTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    rawdata TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'candidate',
    main_image TEXT NOT NULL DEFAULT '',
    wearing_image TEXT NOT NULL DEFAULT '',
    detail_image TEXT NOT NULL DEFAULT '',
    size_ratio_image TEXT NOT NULL DEFAULT '',
    multi_angle_image TEXT NOT NULL DEFAULT '',
    locked_at TEXT DEFAULT NULL,
    locked_by TEXT DEFAULT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (product_id, platform)
);
"""

PRODUCTS_STATUS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_products_status ON products (status);
"""

PRODUCTS_LOCK_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_products_lock ON products (locked_at);
"""

ENROUTE_IMAGE_ANALYSES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS enroute_image_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    enroute_product_id TEXT NOT NULL,
    enroute_category TEXT NOT NULL,
    enroute_title TEXT NOT NULL DEFAULT '',
    enroute_handle TEXT NOT NULL DEFAULT '',
    image_path TEXT NOT NULL,
    image_position INTEGER NOT NULL DEFAULT 2,
    analysis_json TEXT NOT NULL DEFAULT '{}',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (enroute_product_id)
);
"""

ENROUTE_IMAGE_ANALYSES_CATEGORY_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_enroute_image_analyses_category
ON enroute_image_analyses (enroute_category);
"""

MODEL_PROFILES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS model_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_key TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    image_path TEXT NOT NULL DEFAULT '',
    metadata_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (profile_key)
);
"""


def connect_database(database_path: str | Path = DEFAULT_DATABASE_PATH) -> sqlite3.Connection:
    """Open a SQLite connection and ensure the parent directory exists."""

    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_database(database_path: str | Path = DEFAULT_DATABASE_PATH) -> Path:
    """Create the SQLite database and product table if they do not exist."""

    path = Path(database_path)
    with connect_database(path) as connection:
        connection.execute(PRODUCTS_TABLE_SQL)
        connection.execute(ENROUTE_IMAGE_ANALYSES_TABLE_SQL)
        connection.execute(MODEL_PROFILES_TABLE_SQL)
        _ensure_products_column(connection, "locked_at", "TEXT DEFAULT NULL")
        _ensure_products_column(connection, "locked_by", "TEXT DEFAULT NULL")
        connection.execute(PRODUCTS_STATUS_INDEX_SQL)
        connection.execute(PRODUCTS_LOCK_INDEX_SQL)
        connection.execute(ENROUTE_IMAGE_ANALYSES_CATEGORY_INDEX_SQL)
    return path


def _ensure_products_column(
    connection: sqlite3.Connection,
    column_name: str,
    column_definition: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(products)").fetchall()
    }
    if column_name not in columns:
        connection.execute(
            f"ALTER TABLE products ADD COLUMN {column_name} {column_definition}"
        )


def upsert_candidate_product(
    connection: sqlite3.Connection,
    candidate: CandidateProduct,
    status: str = "candidate",
) -> None:
    """Insert or update one candidate product by product_id and platform."""

    rawdata = json.dumps(candidate.rawdata, ensure_ascii=False, separators=(",", ":"))
    connection.execute(
        """
        INSERT INTO products (product_id, platform, rawdata, status)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(product_id, platform) DO UPDATE SET
            rawdata = excluded.rawdata,
            status = excluded.status,
            updated_at = CURRENT_TIMESTAMP
        """,
        (candidate.product_id, candidate.platform, rawdata, status),
    )


def seed_candidate_products(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    data_path: str | Path = DEFAULT_CANDIDATE_DATA,
    limit: int | None = None,
    status: str = "candidate",
) -> int:
    """Load candidate product JSON data into the products table."""

    init_database(database_path)
    candidates = load_candidate_products(data_path=data_path, limit=limit)
    with connect_database(database_path) as connection:
        for candidate in candidates:
            upsert_candidate_product(connection, candidate, status=status)
    return len(candidates)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_candidate(row: sqlite3.Row) -> CandidateProduct:
    return CandidateProduct(
        id=row["id"],
        product_id=row["product_id"],
        platform=row["platform"],
        rawdata=json.loads(row["rawdata"]),
        status=row["status"],
        main_image=row["main_image"],
        wearing_image=row["wearing_image"],
        detail_image=row["detail_image"],
        size_ratio_image=row["size_ratio_image"],
        multi_angle_image=row["multi_angle_image"],
        locked_at=row["locked_at"],
        locked_by=row["locked_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def import_raw_data_directory(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    raw_data_dir: str | Path = DEFAULT_RAW_DATA_DIR,
    status: str = RAW_IMPORT_STATUS,
) -> dict[str, Any]:
    """Import JSON files from the raw data directory and delete successful files."""

    raw_dir = Path(raw_data_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    init_database(database_path)

    summary: dict[str, Any] = {
        "raw_data_dir": str(raw_dir),
        "files_scanned": 0,
        "files_imported": 0,
        "products_imported": 0,
        "failed_files": [],
    }

    for json_file in sorted(raw_dir.glob("*.json")):
        if not json_file.is_file():
            continue

        summary["files_scanned"] += 1
        try:
            imported_count = import_raw_data_file(
                database_path=database_path,
                json_file=json_file,
                status=status,
            )
        except Exception as exc:  # noqa: BLE001
            summary["failed_files"].append(
                {"path": str(json_file), "error": f"{type(exc).__name__}: {exc}"}
            )
            continue

        json_file.unlink()
        summary["files_imported"] += 1
        summary["products_imported"] += imported_count

    return summary


def import_raw_data_file(
    database_path: str | Path,
    json_file: str | Path,
    status: str = RAW_IMPORT_STATUS,
) -> int:
    """Import one raw JSON file into the products table."""

    candidates = load_candidate_products_from_json_file(json_file)
    with connect_database(database_path) as connection:
        for candidate in candidates:
            upsert_candidate_product(connection, candidate, status=status)
    return len(candidates)


def load_products_from_database(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    limit: int | None = None,
    status: str | None = None,
) -> list[CandidateProduct]:
    """Load candidate products from the products table."""

    init_database(database_path)
    query = f"SELECT {PRODUCT_COLUMNS} FROM products"
    params: list[object] = []
    clauses: list[str] = []

    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    with connect_database(database_path) as connection:
        rows = connection.execute(query, params).fetchall()

    return [_row_to_candidate(row) for row in rows]


def load_unfinished_products_from_database(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
) -> list[CandidateProduct]:
    """Load all products that are not in a completed status."""

    init_database(database_path)
    placeholders = ", ".join("?" for _ in COMPLETED_STATUSES)
    query = f"""
        SELECT {PRODUCT_COLUMNS}
        FROM products
        WHERE LOWER(status) NOT IN ({placeholders})
          AND locked_at IS NULL
        ORDER BY id
    """

    with connect_database(database_path) as connection:
        rows = connection.execute(query, COMPLETED_STATUSES).fetchall()

    return [_row_to_candidate(row) for row in rows]


def get_product_by_identity(
    database_path: str | Path,
    product_id: str,
    platform: str,
) -> CandidateProduct | None:
    init_database(database_path)
    with connect_database(database_path) as connection:
        row = connection.execute(
            f"""
            SELECT {PRODUCT_COLUMNS}
            FROM products
            WHERE product_id = ? AND platform = ?
            """,
            (product_id, platform),
        ).fetchone()

    return _row_to_candidate(row) if row else None


def lock_product(
    database_path: str | Path,
    product_id: str,
    platform: str,
    locked_by: str | None = None,
    status: str | None = PROCESSING_STATUS,
) -> CandidateProduct | None:
    """Lock a product if it is still unlocked, then return the updated row."""

    init_database(database_path)
    lock_owner = locked_by or f"productv2-{uuid.uuid4().hex}"
    locked_at = _utc_now()

    with connect_database(database_path) as connection:
        if status is None:
            cursor = connection.execute(
                """
                UPDATE products
                SET locked_at = ?, locked_by = ?, updated_at = CURRENT_TIMESTAMP
                WHERE product_id = ? AND platform = ? AND locked_at IS NULL
                """,
                (locked_at, lock_owner, product_id, platform),
            )
        else:
            cursor = connection.execute(
                """
                UPDATE products
                SET locked_at = ?, locked_by = ?, status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE product_id = ? AND platform = ? AND locked_at IS NULL
                """,
                (locked_at, lock_owner, status, product_id, platform),
            )
        if cursor.rowcount != 1:
            return None

    return get_product_by_identity(database_path, product_id, platform)


def update_product_fields(
    database_path: str | Path,
    product_id: str,
    platform: str,
    **fields: str,
) -> CandidateProduct:
    """Update mutable product fields and return the updated product."""

    allowed_fields = {
        "status",
        "main_image",
        "wearing_image",
        "detail_image",
        "size_ratio_image",
        "multi_angle_image",
        "locked_at",
        "locked_by",
    }
    invalid_fields = set(fields) - allowed_fields
    if invalid_fields:
        raise ValueError(f"Unsupported product update fields: {sorted(invalid_fields)}")
    if not fields:
        product = get_product_by_identity(database_path, product_id, platform)
        if product is None:
            raise ValueError(f"Product not found: {platform}/{product_id}")
        return product

    assignments = [f"{field} = ?" for field in fields]
    assignments.append("updated_at = CURRENT_TIMESTAMP")
    values: list[object] = list(fields.values()) + [product_id, platform]

    init_database(database_path)
    with connect_database(database_path) as connection:
        connection.execute(
            f"""
            UPDATE products
            SET {", ".join(assignments)}
            WHERE product_id = ? AND platform = ?
            """,
            values,
        )

    product = get_product_by_identity(database_path, product_id, platform)
    if product is None:
        raise ValueError(f"Product not found: {platform}/{product_id}")
    return product


def reset_products_for_processing(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    status: str = RAW_IMPORT_STATUS,
) -> dict[str, Any]:
    """Reset product rows to the initial processable state."""

    init_database(database_path)
    with connect_database(database_path) as connection:
        total_count = connection.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        connection.execute(
            """
            UPDATE products
            SET status = ?,
                main_image = '',
                wearing_image = '',
                detail_image = '',
                size_ratio_image = '',
                multi_angle_image = '',
                locked_at = NULL,
                locked_by = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (status,),
        )

    return {
        "database_path": str(database_path),
        "products_reset": int(total_count),
        "status": status,
        "images_cleared": True,
        "locks_cleared": True,
    }


def get_enroute_image_analysis(
    database_path: str | Path,
    enroute_product_id: str,
) -> dict[str, Any] | None:
    """Load one cached Enroute image analysis by unique Enroute product id."""

    init_database(database_path)
    with connect_database(database_path) as connection:
        row = connection.execute(
            """
            SELECT id, enroute_product_id, enroute_category, enroute_title,
                   enroute_handle, image_path, image_position, analysis_json,
                   summary, created_at, updated_at
            FROM enroute_image_analyses
            WHERE enroute_product_id = ?
            """,
            (enroute_product_id,),
        ).fetchone()

    return _row_to_enroute_image_analysis(row) if row else None


def upsert_enroute_image_analysis(
    database_path: str | Path,
    *,
    enroute_product_id: str,
    enroute_category: str,
    enroute_title: str = "",
    enroute_handle: str = "",
    image_path: str,
    image_position: int = 2,
    analysis_json: dict[str, Any],
    summary: str,
) -> dict[str, Any]:
    """Insert or update cached Enroute image analysis."""

    init_database(database_path)
    analysis_text = json.dumps(analysis_json, ensure_ascii=False, separators=(",", ":"))
    with connect_database(database_path) as connection:
        connection.execute(
            """
            INSERT INTO enroute_image_analyses (
                enroute_product_id, enroute_category, enroute_title,
                enroute_handle, image_path, image_position, analysis_json, summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(enroute_product_id) DO UPDATE SET
                enroute_category = excluded.enroute_category,
                enroute_title = excluded.enroute_title,
                enroute_handle = excluded.enroute_handle,
                image_path = excluded.image_path,
                image_position = excluded.image_position,
                analysis_json = excluded.analysis_json,
                summary = excluded.summary,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                enroute_product_id,
                enroute_category,
                enroute_title,
                enroute_handle,
                image_path,
                image_position,
                analysis_text,
                summary,
            ),
        )

    cached = get_enroute_image_analysis(database_path, enroute_product_id)
    if cached is None:
        raise ValueError(f"Enroute image analysis not found: {enroute_product_id}")
    return cached


def _row_to_enroute_image_analysis(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "enroute_product_id": row["enroute_product_id"],
        "enroute_category": row["enroute_category"],
        "enroute_title": row["enroute_title"],
        "enroute_handle": row["enroute_handle"],
        "image_path": row["image_path"],
        "image_position": row["image_position"],
        "analysis_json": json.loads(row["analysis_json"]),
        "summary": row["summary"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def upsert_model_profile(
    database_path: str | Path,
    *,
    profile_key: str,
    name: str = "",
    summary: str,
    image_path: str,
    metadata_path: str = "",
) -> dict[str, Any]:
    """Insert or update one fixed virtual model profile record."""

    init_database(database_path)
    with connect_database(database_path) as connection:
        connection.execute(
            """
            INSERT INTO model_profiles (
                profile_key, name, summary, image_path, metadata_path
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(profile_key) DO UPDATE SET
                name = excluded.name,
                summary = excluded.summary,
                image_path = excluded.image_path,
                metadata_path = excluded.metadata_path,
                updated_at = CURRENT_TIMESTAMP
            """,
            (profile_key, name, summary, image_path, metadata_path),
        )

    profile = get_model_profile(database_path, profile_key)
    if profile is None:
        raise ValueError(f"Model profile not found: {profile_key}")
    return profile


def get_model_profile(
    database_path: str | Path,
    profile_key: str,
) -> dict[str, Any] | None:
    """Load one fixed virtual model profile record."""

    init_database(database_path)
    with connect_database(database_path) as connection:
        row = connection.execute(
            """
            SELECT id, profile_key, name, summary, image_path, metadata_path,
                   created_at, updated_at
            FROM model_profiles
            WHERE profile_key = ?
            """,
            (profile_key,),
        ).fetchone()

    return _row_to_model_profile(row) if row else None


def load_model_profiles(database_path: str | Path) -> list[dict[str, Any]]:
    """Load fixed virtual model profile records for LLM selection."""

    init_database(database_path)
    with connect_database(database_path) as connection:
        rows = connection.execute(
            """
            SELECT id, profile_key, name, summary, image_path, metadata_path,
                   created_at, updated_at
            FROM model_profiles
            ORDER BY id
            """
        ).fetchall()

    return [_row_to_model_profile(row) for row in rows]


def sync_default_model_profiles(
    database_path: str | Path,
    model_profile_dir: str | Path,
) -> list[dict[str, Any]]:
    """Sync configured virtual model profiles and generated image paths into SQLite."""

    root = Path(model_profile_dir)
    synced: list[dict[str, Any]] = []
    for profile in VIRTUAL_MODEL_PROFILES:
        image_path = root / profile.key / "model.jpg"
        metadata_path = root / profile.key / "metadata.json"
        synced.append(
            upsert_model_profile(
                database_path,
                profile_key=profile.key,
                name=profile.name,
                summary=virtual_model_profile_summary(profile),
                image_path=str(image_path) if image_path.exists() else "",
                metadata_path=str(metadata_path) if metadata_path.exists() else "",
            )
        )
    return synced


def _row_to_model_profile(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "profile_key": row["profile_key"],
        "name": row["name"],
        "summary": row["summary"],
        "image_path": row["image_path"],
        "metadata_path": row["metadata_path"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
