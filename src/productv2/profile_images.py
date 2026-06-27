"""Offline preparation for fixed virtual model profile images."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from productv2.config import PROJECT_ROOT, Settings
from productv2.image_generation import ImageGenerationClient, ImageGenerationRequest
from productv2.model_profiles import VIRTUAL_MODEL_PROFILES, VirtualModelProfile
from productv2.model_profiles import virtual_model_prompt_block


DEFAULT_MODEL_PROFILE_IMAGE_DIR = PROJECT_ROOT / "data" / "model_profiles"


@dataclass(frozen=True)
class PreparedModelProfileImage:
    profile_key: str
    status: str
    image_path: Path
    metadata_path: Path
    task_id: str = ""
    source_url: str = ""
    error: str = ""


def build_model_profile_image_prompt(profile: VirtualModelProfile) -> str:
    """Build a stable reference portrait prompt for a virtual model profile."""

    return "\n".join(
        [
            "Create a fixed virtual model identity reference sheet for future AI try-on generation.",
            "The output must be a premium casting reference sheet, not a fashion editorial and not a product ad.",
            "White or very light gray seamless background, clean high-end casting light, neutral camera, high realism.",
            "Single same model shown as three standing views in one image: full-body front view, full-body side view, full-body back view.",
            "The front view must show clear facial features, both eyes, nose, mouth, face shape, neck, shoulders, torso, waist, hips, legs, and body proportions.",
            "The side and back views must match the same identity, hair, skin tone, height impression, build, and body proportions exactly.",
            "Use minimal fitted casting clothes with high-end restraint: plain black or charcoal fitted tank top and plain black slim trousers or leggings.",
            "No jewelry of any kind. No necklace, earrings, rings, bracelets, watches, hair accessories, logos, text, watermark, props, shadows, dramatic styling, or decorative scene.",
            "Pose must be composed standing posture, arms relaxed naturally, not smiling, no runway pose, no crossed arms, no hand covering neck or face.",
            "Keep the model adult and early-20s in appearance, realistic skin texture, low makeup, natural hair, clear eyes, strong eye contact, and refined facial structure.",
            "Make the image useful for AI identity and body consistency: exact same person across all three views, sharp face, sharp body outline, plain background, premium presence.",
            "",
            f"Profile key: {profile.key}.",
            f"Model type: {profile.ethnicity}, {profile.age_feel}.",
            f"Face identity: {profile.face}.",
            f"Skin: {profile.skin}.",
            f"Hair: {profile.hair}.",
            f"Temperament only for expression and posture: {profile.temperament}; keep the pose reference-sheet clean but preserve high-end presence.",
        ]
    )


def prepare_model_profile_images(
    output_dir: str | Path = DEFAULT_MODEL_PROFILE_IMAGE_DIR,
    *,
    profile_keys: list[str] | None = None,
    force: bool = False,
    client: ImageGenerationClient | None = None,
) -> list[PreparedModelProfileImage]:
    """Generate and save fixed model images for the configured virtual profiles."""

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    active_profiles = [
        profile
        for profile in VIRTUAL_MODEL_PROFILES
        if profile_keys is None or profile.key in profile_keys
    ]
    active_client = client or ImageGenerationClient(Settings())

    results: list[PreparedModelProfileImage] = []
    pending: list[tuple[VirtualModelProfile, Any]] = []

    for profile in active_profiles:
        image_path = profile_image_path(root, profile.key)
        metadata_path = profile_metadata_path(root, profile.key)
        if image_path.exists() and metadata_path.exists() and not force:
            results.append(
                PreparedModelProfileImage(
                    profile_key=profile.key,
                    status="cached",
                    image_path=image_path,
                    metadata_path=metadata_path,
                )
            )
            continue

        request = ImageGenerationRequest(
            prompt=build_model_profile_image_prompt(profile),
            images=[],
            aspect_ratio="1024x1024",
        )
        creation = active_client.create(request)
        pending.append((profile, creation))

    for profile, creation in pending:
        image_path = profile_image_path(root, profile.key)
        metadata_path = profile_metadata_path(root, profile.key)
        try:
            final = active_client.poll(creation.id) if creation.status == "running" else creation
            if not final.urls:
                raise RuntimeError(f"Image generation returned no image URLs: {final.status}")
            source_url = final.urls[0]
            _save_generated_image(source_url, image_path)
            _write_profile_metadata(
                metadata_path,
                profile,
                prompt=build_model_profile_image_prompt(profile),
                task_id=final.id or creation.id,
                source_url=source_url,
                image_path=image_path,
                raw=final.raw,
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                PreparedModelProfileImage(
                    profile_key=profile.key,
                    status="failed",
                    image_path=image_path,
                    metadata_path=metadata_path,
                    task_id=creation.id,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        results.append(
            PreparedModelProfileImage(
                profile_key=profile.key,
                status="generated",
                image_path=image_path,
                metadata_path=metadata_path,
                task_id=final.id or creation.id,
                source_url=source_url,
            )
        )

    _write_manifest(root, results)
    return results


def profile_image_path(root: str | Path, profile_key: str) -> Path:
    return Path(root) / profile_key / "model.jpg"


def profile_metadata_path(root: str | Path, profile_key: str) -> Path:
    return Path(root) / profile_key / "metadata.json"


def _save_generated_image(source_url: str, image_path: Path) -> None:
    image_path.parent.mkdir(parents=True, exist_ok=True)
    if source_url.startswith("data:"):
        _, encoded = source_url.split(",", 1)
        content = base64.b64decode(encoded)
    else:
        response = httpx.get(source_url, timeout=120, follow_redirects=True)
        response.raise_for_status()
        content = response.content

    with Image.open(BytesIO(content)) as image:
        image.convert("RGB").save(image_path, format="JPEG", quality=92, optimize=True)


def _write_profile_metadata(
    metadata_path: Path,
    profile: VirtualModelProfile,
    *,
    prompt: str,
    task_id: str,
    source_url: str,
    image_path: Path,
    raw: dict[str, Any],
) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "profile_key": profile.key,
        "name": profile.name,
        "ethnicity": profile.ethnicity,
        "image_path": str(image_path),
        "task_id": task_id,
        "source_url": source_url,
        "prompt_type": "technical_three_view_identity_reference",
        "prompt": prompt,
        "raw": raw,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_manifest(root: Path, results: list[PreparedModelProfileImage]) -> None:
    manifest = [
        {
            "profile_key": result.profile_key,
            "status": result.status,
            "image_path": str(result.image_path),
            "metadata_path": str(result.metadata_path),
            "task_id": result.task_id,
            "source_url": result.source_url,
            "error": result.error,
        }
        for result in results
    ]
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
