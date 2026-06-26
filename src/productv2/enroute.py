"""Local Enroute reference image selection."""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from productv2.config import DEFAULT_ENROUTE_BESTSELLERS_DIR
from productv2.models import CandidateProduct


ENROUTE_CATEGORIES = ("earrings", "bracelets", "necklaces", "rings")


@dataclass(frozen=True)
class EnrouteReference:
    product_id: str
    category: str
    product_dir: Path
    image_path: Path
    metadata: dict[str, Any]

    def model_dump(self) -> dict[str, Any]:
        return {
            "product_id": self.product_id,
            "category": self.category,
            "product_dir": str(self.product_dir),
            "image_path": str(self.image_path),
            "metadata": self.metadata,
        }


def select_enroute_wearing_reference(
    candidate: CandidateProduct,
    library_dir: str | Path = DEFAULT_ENROUTE_BESTSELLERS_DIR,
    rng: random.Random | None = None,
) -> EnrouteReference | None:
    """Select an Enroute product 02.jpg reference from the matching category."""

    root = Path(library_dir)
    if not root.exists():
        return None

    category = infer_enroute_category(candidate)
    if category is None:
        return None

    references = _load_category_references(root, category)
    if not references:
        return None

    active_rng = rng or random.Random()
    return active_rng.choice(references)


def list_enroute_wearing_references(
    candidate: CandidateProduct,
    library_dir: str | Path = DEFAULT_ENROUTE_BESTSELLERS_DIR,
) -> tuple[str | None, list[EnrouteReference]]:
    """Load all local 02.jpg references from the candidate's matching category."""

    root = Path(library_dir)
    if not root.exists():
        return None, []

    category = infer_enroute_category(candidate)
    if category is None:
        return None, []

    return category, _load_category_references(root, category)


def infer_enroute_category(candidate: CandidateProduct) -> str | None:
    """Infer the closest Enroute category from product raw data."""

    haystack = _candidate_text(candidate)
    category_terms = {
        "necklaces": (
            "necklace",
            "pendant",
            "chain",
            "choker",
            "lariat",
            "项链",
            "吊坠",
        ),
        "earrings": (
            "earring",
            "earrings",
            "ear cuff",
            "hoop",
            "stud",
            "耳环",
            "耳饰",
            "耳钉",
        ),
        "bracelets": (
            "bracelet",
            "bangle",
            "watch bracelet",
            "手链",
            "手镯",
        ),
        "rings": (
            "ring",
            "戒指",
            "指环",
        ),
    }
    scores = {
        category: sum(1 for term in terms if term in haystack)
        for category, terms in category_terms.items()
    }
    best_category, best_score = max(scores.items(), key=lambda item: item[1])
    return best_category if best_score > 0 else None


def _load_category_references(root: Path, category: str) -> list[EnrouteReference]:
    category_dir = root / category
    if not category_dir.is_dir():
        return []

    references: list[EnrouteReference] = []
    for product_dir in sorted(path for path in category_dir.iterdir() if path.is_dir()):
        image_path = product_dir / "02.jpg"
        if not image_path.is_file():
            continue
        metadata = _load_metadata(product_dir / "metadata.json")
        references.append(
            EnrouteReference(
                product_id=_reference_product_id(category, product_dir, metadata),
                category=category,
                product_dir=product_dir,
                image_path=image_path,
                metadata=metadata,
            )
        )
    return references


def _load_metadata(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _reference_product_id(
    category: str,
    product_dir: Path,
    metadata: dict[str, Any],
) -> str:
    product_id = metadata.get("product_id")
    if product_id:
        return str(product_id)
    handle = metadata.get("handle")
    if handle:
        return f"{category}:{handle}"
    return f"{category}:{product_dir.name}"


def _candidate_text(candidate: CandidateProduct) -> str:
    rawdata = candidate.rawdata
    values: list[str] = [
        candidate.product_id,
        candidate.platform,
        str(rawdata.get("title") or ""),
        str(rawdata.get("candidate_id") or ""),
        str(rawdata.get("motif_id") or ""),
        str(rawdata.get("query") or ""),
        str(rawdata.get("keyword") or ""),
    ]
    detail = rawdata.get("detail")
    if isinstance(detail, dict):
        values.extend(
            [
                str(detail.get("title") or ""),
                str(detail.get("category") or ""),
                str(detail.get("product_type") or ""),
            ]
        )
    text = " ".join(values).lower()
    return re.sub(r"[_\-/]+", " ", text)
