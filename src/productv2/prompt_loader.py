"""Versioned prompt file loading utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from productv2.config import PROJECT_ROOT


PROMPTS_ROOT = PROJECT_ROOT / "prompts"
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


def load_latest_prompt(prompt_dir: str | Path) -> LoadedPrompt:
    """Load the highest numeric `_vN` prompt file from a directory.

    `prompt_dir` can be absolute or relative to the repository `prompts/` root.
    Only direct files in that folder are considered. A file named
    `system_v2.md` wins over `system_v1.md`; unversioned files are ignored.
    """

    directory = _prompt_directory(prompt_dir)
    candidates = [_versioned_prompt_file(path) for path in directory.iterdir()]
    versioned = [candidate for candidate in candidates if candidate is not None]
    if not versioned:
        raise FileNotFoundError(
            f"No versioned prompt files found in {directory}; expected *_vN.*"
        )
    version, path = max(versioned, key=lambda item: (item[0], item[1].name))
    return LoadedPrompt(
        path=path,
        version=version,
        text=path.read_text(encoding="utf-8").strip(),
    )


def load_latest_prompt_text(prompt_dir: str | Path) -> str:
    """Load only the text from the latest prompt file in a directory."""

    return load_latest_prompt(prompt_dir).text


def load_latest_prompt_sections(prompt_dir: str | Path) -> PromptSections:
    """Load `[system]` and `[user]` sections from the latest prompt file."""

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
    """Return the latest version per prompt directory under ``prompts/``.

    Folded into AI checkpoint keys so a prompt version bump invalidates cached
    results instead of silently reusing output from an older prompt.
    """

    manifest: dict[str, int] = {}
    if not PROMPTS_ROOT.is_dir():
        return manifest
    for path in PROMPTS_ROOT.rglob("*"):
        if not path.is_file():
            continue
        match = _VERSION_PATTERN.search(path.stem)
        if not match:
            continue
        rel = path.parent.relative_to(PROMPTS_ROOT).as_posix()
        version = int(match.group("version"))
        manifest[rel] = max(manifest.get(rel, 0), version)
    return manifest


def _prompt_directory(prompt_dir: str | Path) -> Path:
    directory = Path(prompt_dir)
    if not directory.is_absolute():
        directory = PROMPTS_ROOT / directory
    if not directory.is_dir():
        raise FileNotFoundError(f"Prompt directory not found: {directory}")
    return directory


def _versioned_prompt_file(path: Path) -> tuple[int, Path] | None:
    if not path.is_file():
        return None
    match = _VERSION_PATTERN.search(path.stem)
    if not match:
        return None
    return int(match.group("version")), path
