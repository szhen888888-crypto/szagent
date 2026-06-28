"""Versioned prompt file loading utilities."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from productv2.config import PROJECT_ROOT


PROMPTS_ROOT = PROJECT_ROOT / "prompts"
OVERRIDES_PATH = PROMPTS_ROOT / "versions.json"
_VERSION_PATTERN = re.compile(r"(?:^|_)v(?P<version>\d+)$")


@dataclass(frozen=True)
class LoadedPrompt:
    """A prompt selected from a versioned prompt directory."""

    path: Path
    version: int
    text: str


@dataclass(frozen=True)
class PromptSections:
    """Parsed sections from one prompt file."""

    system: str
    user: str


def load_prompt_overrides() -> dict[str, int]:
    """Return per-directory pinned versions from ``prompts/versions.json``.

    The map is ``{"<relative prompt dir>": <version int>}``. A missing or
    malformed file yields an empty map (default behaviour: latest version).
    """

    if not OVERRIDES_PATH.is_file():
        return {}
    try:
        raw = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    overrides: dict[str, int] = {}
    for key, value in raw.items():
        try:
            overrides[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return overrides


def save_prompt_overrides(overrides: dict[str, int]) -> None:
    """Persist per-directory pinned versions, dropping empty entries."""

    cleaned = {str(key): int(value) for key, value in overrides.items()}
    OVERRIDES_PATH.parent.mkdir(parents=True, exist_ok=True)
    if cleaned:
        OVERRIDES_PATH.write_text(
            json.dumps(cleaned, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    elif OVERRIDES_PATH.is_file():
        OVERRIDES_PATH.unlink()


def list_prompt_versions(prompt_dir: str | Path) -> list[tuple[int, Path]]:
    """Return ``(version, path)`` pairs in a directory, ascending by version."""

    directory = _prompt_directory(prompt_dir)
    versioned = [
        candidate
        for candidate in (_versioned_prompt_file(path) for path in directory.iterdir())
        if candidate is not None
    ]
    return sorted(versioned, key=lambda item: (item[0], item[1].name))


def load_latest_prompt(prompt_dir: str | Path) -> LoadedPrompt:
    """Load the effective prompt file from a directory.

    `prompt_dir` can be absolute or relative to the repository `prompts/` root.
    By default the highest numeric `_vN` file wins; a pinned version in
    ``prompts/versions.json`` overrides that when the pinned file exists.
    Unversioned files are ignored.
    """

    directory = _prompt_directory(prompt_dir)
    versioned = list_prompt_versions(directory)
    if not versioned:
        raise FileNotFoundError(
            f"No versioned prompt files found in {directory}; expected *_vN.*"
        )

    rel = _relative_prompt_dir(directory)
    override = load_prompt_overrides().get(rel) if rel is not None else None
    selected = None
    if override is not None:
        selected = next(
            (item for item in versioned if item[0] == override),
            None,
        )
    if selected is None:
        selected = max(versioned, key=lambda item: (item[0], item[1].name))

    version, path = selected
    return LoadedPrompt(
        path=path,
        version=version,
        text=path.read_text(encoding="utf-8").strip(),
    )


def load_latest_prompt_text(prompt_dir: str | Path) -> str:
    """Load only the text from the effective prompt file in a directory."""

    return load_latest_prompt(prompt_dir).text


def load_latest_prompt_sections(prompt_dir: str | Path) -> PromptSections:
    """Load `[system]` and `[user]` sections from the effective prompt file."""

    return parse_prompt_sections(load_latest_prompt_text(prompt_dir))



def parse_prompt_sections(text: str) -> PromptSections:
    """Parse a prompt file containing `[system]` and `[user]` headings."""

    sections: dict[str, list[str]] = {"system": [], "user": []}
    active_section: str | None = None
    for line in text.splitlines():
        stripped = line.strip().lower()
        if stripped in {"[system]", "[user]"}:
            active_section = stripped.strip("[]")
            continue
        if active_section is not None:
            sections[active_section].append(line)

    system = "\n".join(sections["system"]).strip()
    user = "\n".join(sections["user"]).strip()
    if not system or not user:
        raise ValueError("Prompt file must contain non-empty [system] and [user] sections")
    return PromptSections(system=system, user=user)


def render_prompt_template(
    template: str,
    values: dict[str, object],
    *,
    strict: bool = True,
) -> str:
    """Render `{name}` placeholders without treating other braces specially.

    Literal JSON braces in the template are left untouched. When ``strict`` is
    set, every provided value must have a matching ``{name}`` placeholder so a
    renamed or mistyped variable surfaces immediately instead of silently
    rendering nothing.
    """

    if strict:
        missing = [key for key in values if "{" + key + "}" not in template]
        if missing:
            raise KeyError(
                "Prompt template is missing placeholders for: "
                + ", ".join(sorted(missing))
            )
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def current_prompt_manifest() -> dict[str, int]:
    """Return the effective version per prompt directory under ``prompts/``.

    Folded into AI checkpoint keys so a prompt version bump (or a pinned
    override change) invalidates cached results instead of silently reusing
    output from a different prompt version.
    """

    latest: dict[str, int] = {}
    if not PROMPTS_ROOT.is_dir():
        return latest
    for path in PROMPTS_ROOT.rglob("*"):
        if not path.is_file():
            continue
        match = _VERSION_PATTERN.search(path.stem)
        if not match:
            continue
        rel = path.parent.relative_to(PROMPTS_ROOT).as_posix()
        version = int(match.group("version"))
        latest[rel] = max(latest.get(rel, 0), version)

    overrides = load_prompt_overrides()
    return {rel: overrides.get(rel, version) for rel, version in latest.items()}


def _prompt_directory(prompt_dir: str | Path) -> Path:
    directory = Path(prompt_dir)
    if not directory.is_absolute():
        directory = PROMPTS_ROOT / directory
    if not directory.is_dir():
        raise FileNotFoundError(f"Prompt directory not found: {directory}")
    return directory


def _relative_prompt_dir(directory: Path) -> str | None:
    try:
        return directory.resolve().relative_to(PROMPTS_ROOT.resolve()).as_posix()
    except ValueError:
        return None


def _versioned_prompt_file(path: Path) -> tuple[int, Path] | None:
    if not path.is_file():
        return None
    match = _VERSION_PATTERN.search(path.stem)
    if not match:
        return None
    return int(match.group("version")), path

