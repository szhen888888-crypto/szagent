"""In-memory product selection using platform adapters."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

from productv2.adapters import adapter_module_name, get_platform_adapter, has_platform_adapter
from productv2.config import DEFAULT_DATABASE_PATH
from productv2.db import lock_product, load_unfinished_products_from_database
from productv2.models import CandidateProduct


@dataclass(frozen=True)
class ProductSelection:
    candidate: CandidateProduct | None
    adapter: object | None
    unfinished_count: int
    skipped_without_adapter: list[dict[str, str]] = field(default_factory=list)

    @property
    def selected_adapter_name(self) -> str | None:
        if self.candidate is None:
            return None
        return adapter_module_name(self.candidate.platform)


def select_unfinished_product_with_adapter(
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    rng: random.Random | None = None,
    lock: bool = True,
    locked_by: str | None = None,
) -> ProductSelection:
    """Select one unfinished product whose platform has an adapter.

    The database is read once for all unfinished products. Randomization and adapter
    checks happen in memory.
    """

    products = load_unfinished_products_from_database(database_path=database_path)
    shuffled_products = list(products)
    active_rng = rng or random.Random()
    active_rng.shuffle(shuffled_products)

    skipped_without_adapter: list[dict[str, str]] = []
    for product in shuffled_products:
        if not has_platform_adapter(product.platform):
            skipped_without_adapter.append(
                {"product_id": product.product_id, "platform": product.platform}
            )
            continue

        adapter = get_platform_adapter(product.platform)
        if hasattr(adapter, "can_handle") and not adapter.can_handle(product):
            skipped_without_adapter.append(
                {"product_id": product.product_id, "platform": product.platform}
            )
            continue

        selected_product = product
        if lock:
            locked_product = lock_product(
                database_path=database_path,
                product_id=product.product_id,
                platform=product.platform,
                locked_by=locked_by,
            )
            if locked_product is None:
                skipped_without_adapter.append(
                    {"product_id": product.product_id, "platform": product.platform}
                )
                continue
            selected_product = locked_product

        return ProductSelection(
            candidate=selected_product,
            adapter=adapter,
            unfinished_count=len(products),
            skipped_without_adapter=skipped_without_adapter,
        )

    return ProductSelection(
        candidate=None,
        adapter=None,
        unfinished_count=len(products),
        skipped_without_adapter=skipped_without_adapter,
    )
