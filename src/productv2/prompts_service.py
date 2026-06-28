"""Read/write access to versioned prompt files for the control console."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from productv2.prompt_loader import (
    PROMPTS_ROOT,
    list_prompt_versions,
    load_prompt_overrides,
    save_prompt_overrides,
)


class PromptAccessError(ValueError):
    """Raised when a prompt directory/version request is invalid or unsafe."""


# Ordered by the position each prompt is invoked during the LangGraph workflow.
# `order` drives the console list ordering; unmapped prompts fall after the
# workflow prompts and before standalone experiments.
PROMPT_METADATA: dict[str, dict[str, Any]] = {
    "vision/size_reference": {
        "order": 1,
        "label": "尺寸参考识别",
        "node": "detect_size_reference",
        "purpose": "检查商品主图拼图，判断哪张子图能用人体参照判断尺寸，并选出尺寸参考图与产品主图编号。",
    },
    "reference_analysis/enroute_reference": {
        "order": 2,
        "label": "Enroute 逆向分析",
        "node": "analyze_enroute_reference",
        "purpose": "逆向同类目 Enroute 佩戴图，提炼模特、服装、场景和拍摄风格，并选择固定虚拟模特。",
    },
    "reference_analysis/enroute_selection": {
        "order": 3,
        "label": "Enroute 参考选择",
        "node": "analyze_enroute_reference",
        "purpose": "用当前产品主图与尺寸参考图，从已逆向的缓存摘要中选出最适配的一条风格参考。",
    },
    "wearing/generate_wearing_image": {
        "order": 4,
        "label": "穿戴图生成",
        "node": "generate_wearing_image",
        "purpose": "综合产品图、尺寸参考、固定模特与逆向风格，生成 inyourday 风格的首饰佩戴图提示词。",
    },
    "experiments/enroute_reverse_human": {
        "order": 99,
        "label": "人物参考逆向（实验）",
        "node": "",
        "purpose": "实验脚本：对人物参考图做摄影逆向分析，当前未接入主工作流。",
    },
}

_DEFAULT_PROMPT_ORDER = 90


def _prompt_meta(rel: str) -> dict[str, Any]:
    meta = PROMPT_METADATA.get(rel)
    if meta is not None:
        return {
            "order": meta["order"],
            "label": meta["label"],
            "node": meta["node"],
            "purpose": meta["purpose"],
        }
    return {
        "order": _DEFAULT_PROMPT_ORDER,
        "label": rel.rsplit("/", 1)[-1],
        "node": "",
        "purpose": "",
    }


def list_prompts() -> list[dict[str, Any]]:
    """Return every prompt directory with versions, selection, and workflow role.

    Sorted by the order each prompt is invoked in the workflow.
    """

    overrides = load_prompt_overrides()
    prompts: list[dict[str, Any]] = []
    for directory in _discover_prompt_dirs():
        rel = directory.relative_to(PROMPTS_ROOT).as_posix()
        versions = list_prompt_versions(directory)
        if not versions:
            continue
        override = overrides.get(rel)
        effective = _effective_version(versions, override)
        prompts.append(
            {
                "dir": rel,
                **_prompt_meta(rel),
                "override": override,
                "effective_version": effective,
                "versions": [
                    {
                        "version": version,
                        "file": path.name,
                        "is_effective": version == effective,
                    }
                    for version, path in versions
                ],
                "content": _read_version_text(versions, effective),
            }
        )
    prompts.sort(key=lambda item: (item["order"], item["dir"]))
    return prompts



def read_prompt(dir_rel: str, version: int) -> str:
    """Return the raw text of one prompt version."""

    directory = _resolve_prompt_dir(dir_rel)
    path = _version_path(directory, version)
    return path.read_text(encoding="utf-8")


def write_prompt(dir_rel: str, version: int, content: str) -> dict[str, Any]:
    """Overwrite an existing prompt version's content."""

    directory = _resolve_prompt_dir(dir_rel)
    path = _version_path(directory, version)
    path.write_text(_normalize_content(content), encoding="utf-8")
    return _dir_summary(directory)


def create_prompt_version(dir_rel: str, content: str) -> dict[str, Any]:
    """Create the next prompt version (max + 1) and return the updated summary."""

    directory = _resolve_prompt_dir(dir_rel)
    versions = list_prompt_versions(directory)
    if not versions:
        raise PromptAccessError(f"No existing prompt versions in {dir_rel}")
    next_version = max(version for version, _ in versions) + 1
    base = _base_name(versions[-1][1])
    new_path = directory / f"{base}_v{next_version}.md"
    if new_path.exists():
        raise PromptAccessError(f"Prompt version already exists: {new_path.name}")
    new_path.write_text(_normalize_content(content), encoding="utf-8")
    summary = _dir_summary(directory)
    summary["created_version"] = next_version
    return summary


def set_prompt_override(dir_rel: str, version: int | None) -> dict[str, Any]:
    """Pin (or clear) the effective version for one prompt directory."""

    directory = _resolve_prompt_dir(dir_rel)
    rel = directory.relative_to(PROMPTS_ROOT).as_posix()
    overrides = load_prompt_overrides()
    if version is None:
        overrides.pop(rel, None)
    else:
        available = {ver for ver, _ in list_prompt_versions(directory)}
        if version not in available:
            raise PromptAccessError(
                f"Version {version} does not exist in {rel}"
            )
        overrides[rel] = version
    save_prompt_overrides(overrides)
    return _dir_summary(directory)


def _discover_prompt_dirs() -> list[Path]:
    if not PROMPTS_ROOT.is_dir():
        return []
    directories: set[Path] = set()
    for path in PROMPTS_ROOT.rglob("*"):
        if path.is_file() and _VERSION_FILE.search(path.stem):
            directories.add(path.parent)
    return sorted(directories)


def _resolve_prompt_dir(dir_rel: str) -> Path:
    candidate = (PROMPTS_ROOT / dir_rel).resolve()
    root = PROMPTS_ROOT.resolve()
    if candidate != root and root not in candidate.parents:
        raise PromptAccessError(f"Prompt directory is outside prompts root: {dir_rel}")
    if not candidate.is_dir():
        raise PromptAccessError(f"Prompt directory not found: {dir_rel}")
    return candidate


def _version_path(directory: Path, version: int) -> Path:
    for ver, path in list_prompt_versions(directory):
        if ver == version:
            return path
    raise PromptAccessError(f"Prompt version {version} not found in {directory.name}")


def _effective_version(
    versions: list[tuple[int, Path]],
    override: int | None,
) -> int:
    available = {version for version, _ in versions}
    if override is not None and override in available:
        return override
    return max(available)


def _read_version_text(versions: list[tuple[int, Path]], version: int) -> str:
    for ver, path in versions:
        if ver == version:
            return path.read_text(encoding="utf-8")
    return ""


def _dir_summary(directory: Path) -> dict[str, Any]:
    rel = directory.relative_to(PROMPTS_ROOT).as_posix()
    overrides = load_prompt_overrides()
    versions = list_prompt_versions(directory)
    override = overrides.get(rel)
    effective = _effective_version(versions, override)
    return {
        "dir": rel,
        **_prompt_meta(rel),
        "override": override,
        "effective_version": effective,
        "versions": [
            {
                "version": version,
                "file": path.name,
                "is_effective": version == effective,
            }
            for version, path in versions
        ],
        "content": _read_version_text(versions, effective),
    }


def _base_name(path: Path) -> str:
    return _VERSION_FILE.sub("", path.stem) or "prompt"


def _normalize_content(content: str) -> str:
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if not text.endswith("\n"):
        text += "\n"
    return text


_VERSION_FILE = re.compile(r"(?:^|_)v\d+$")
