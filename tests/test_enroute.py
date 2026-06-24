import json

from PIL import Image

from productv2.enroute import infer_enroute_category
from productv2.enroute import select_enroute_wearing_reference
from productv2.models import CandidateProduct


def _write_reference(root, category, name, title):
    product_dir = root / category / name
    product_dir.mkdir(parents=True)
    Image.new("RGB", (16, 16), "white").save(product_dir / "02.jpg")
    (product_dir / "metadata.json").write_text(
        json.dumps(
            {
                "category": category,
                "title": title,
                "handle": name,
                "product_type": category.title(),
                "source_url": f"https://example.test/{name}",
            }
        ),
        encoding="utf-8",
    )
    return product_dir


def test_infer_enroute_category_from_candidate_text() -> None:
    assert (
        infer_enroute_category(
            CandidateProduct(
                product_id="p-1",
                platform="1688",
                rawdata={"title": "Vintage pearl cross necklace"},
            )
        )
        == "necklaces"
    )
    assert (
        infer_enroute_category(
            CandidateProduct(
                product_id="p-2",
                platform="1688",
                rawdata={"motif_id": "gold_wave_hoop_earrings"},
            )
        )
        == "earrings"
    )


def test_select_enroute_reference_uses_matching_category_only(tmp_path) -> None:
    _write_reference(tmp_path, "rings", "01-ring", "Ring Reference")
    necklace_dir = _write_reference(
        tmp_path,
        "necklaces",
        "01-necklace",
        "Necklace Reference",
    )
    candidate = CandidateProduct(
        product_id="p-1",
        platform="1688",
        rawdata={"title": "Pearl cross necklace"},
    )

    reference = select_enroute_wearing_reference(candidate, library_dir=tmp_path)

    assert reference is not None
    assert reference.category == "necklaces"
    assert reference.image_path == necklace_dir / "02.jpg"
    assert reference.metadata["title"] == "Necklace Reference"


def test_select_enroute_reference_does_not_fallback_to_other_category(tmp_path) -> None:
    _write_reference(tmp_path, "rings", "01-ring", "Ring Reference")
    candidate = CandidateProduct(
        product_id="p-1",
        platform="1688",
        rawdata={"title": "Pearl cross necklace"},
    )

    reference = select_enroute_wearing_reference(candidate, library_dir=tmp_path)

    assert reference is None
