"""Command line entrypoint for the product listing workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from productv2.config import Settings
from productv2.db import (
    RAW_IMPORT_STATUS,
    import_raw_data_directory,
    init_database,
    reset_products_for_processing,
    seed_candidate_products,
)
from productv2.graph import run_listing_workflow


def add_startup_arguments(
    parser: argparse.ArgumentParser,
    default=argparse.SUPPRESS,
) -> None:
    parser.add_argument(
        "--database-path",
        type=Path,
        default=default,
        help="Path to the SQLite database file.",
    )
    parser.add_argument(
        "--raw-data-dir",
        type=Path,
        default=default,
        help="Directory to scan for raw JSON files before running.",
    )


def add_workflow_arguments(
    parser: argparse.ArgumentParser,
    default=argparse.SUPPRESS,
) -> None:
    parser.add_argument(
        "--data-path",
        type=Path,
        default=default,
        help="Path to candidate product JSON data.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=default,
        help="Maximum number of candidate products to process.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all candidate products, ignoring the default limit.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="productv2",
        description="Run the LangGraph product listing draft workflow.",
    )
    add_startup_arguments(parser, default=None)
    add_workflow_arguments(parser, default=None)

    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser(
        "run",
        help="Run the LangGraph product listing draft workflow.",
    )
    add_startup_arguments(run_parser)
    add_workflow_arguments(run_parser)

    init_db_parser = subparsers.add_parser(
        "init-db",
        help="Initialize the SQLite database schema.",
    )
    add_startup_arguments(init_db_parser)
    init_db_parser.add_argument(
        "--seed-candidates",
        action="store_true",
        help="Seed products from the candidate product JSON data.",
    )
    add_workflow_arguments(init_db_parser)

    reset_db_parser = subparsers.add_parser(
        "reset-db",
        help="Reset product rows to the initial processable state.",
    )
    add_startup_arguments(reset_db_parser)
    reset_db_parser.add_argument(
        "--status",
        default=RAW_IMPORT_STATUS,
        help="Status to write to every product row after reset.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = Settings()
    database_path = args.database_path or settings.productv2_database_path
    if args.command == "reset-db":
        summary = reset_products_for_processing(
            database_path=database_path,
            status=args.status,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    raw_import_summary = import_raw_data_directory(
        database_path=database_path,
        raw_data_dir=args.raw_data_dir or settings.productv2_raw_data_dir,
    )

    if args.command == "init-db":
        initialized_path = init_database(database_path)
        seeded_count = 0

        if args.seed_candidates:
            limit = None if args.all else args.limit
            seeded_count = seed_candidate_products(
                database_path=initialized_path,
                data_path=args.data_path or settings.productv2_data_path,
                limit=limit,
            )

        print(
            json.dumps(
                {
                    "database_path": str(initialized_path),
                    "products_seeded": seeded_count,
                    "raw_import": raw_import_summary,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    limit = None if args.all else args.limit
    result = run_listing_workflow(
        data_path=args.data_path,
        database_path=database_path,
        product_assets_dir=settings.productv2_product_assets_dir,
        enroute_bestsellers_dir=settings.productv2_enroute_bestsellers_dir,
        model_profiles_dir=settings.productv2_model_profiles_dir,
        workflow_logs_dir=settings.productv2_workflow_logs_dir,
        limit=limit if limit is not None else settings.productv2_default_limit,
    )
    result["metrics"]["raw_import"] = raw_import_summary

    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
    print(json.dumps(result["drafts"][:3], ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "enroute_reverse_analysis": result["metrics"].get(
                    "enroute_analysis_result",
                    {},
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
