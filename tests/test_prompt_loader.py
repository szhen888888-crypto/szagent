from productv2.prompt_loader import load_latest_prompt, load_latest_prompt_sections
from productv2.prompt_loader import load_latest_prompt_text, parse_prompt_sections
from productv2.prompt_loader import render_prompt_template


def test_load_latest_prompt_selects_highest_version(tmp_path) -> None:
    prompt_dir = tmp_path / "prompt"
    prompt_dir.mkdir()
    (prompt_dir / "prompt_v1.md").write_text("old", encoding="utf-8")
    (prompt_dir / "prompt_v10.md").write_text("new", encoding="utf-8")
    (prompt_dir / "notes.md").write_text("ignored", encoding="utf-8")

    loaded = load_latest_prompt(prompt_dir)

    assert loaded.version == 10
    assert loaded.text == "new"
    assert loaded.path.name == "prompt_v10.md"
    assert load_latest_prompt_text(prompt_dir) == "new"


def test_render_prompt_template_replaces_named_tokens_only() -> None:
    assert render_prompt_template(
        "hello {name}; keep {unknown}",
        {"name": "world"},
    ) == "hello world; keep {unknown}"


def test_load_latest_prompt_sections_parses_system_and_user(tmp_path) -> None:
    prompt_dir = tmp_path / "prompt"
    prompt_dir.mkdir()
    (prompt_dir / "prompt_v1.md").write_text(
        "[system]\nold system\n\n[user]\nold user\n",
        encoding="utf-8",
    )
    (prompt_dir / "prompt_v2.md").write_text(
        "[system]\nnew system\n\n[user]\nnew user\n",
        encoding="utf-8",
    )

    sections = load_latest_prompt_sections(prompt_dir)

    assert sections.system == "new system"
    assert sections.user == "new user"


def test_parse_prompt_sections_requires_both_sections() -> None:
    try:
        parse_prompt_sections("[system]\nonly system")
    except ValueError as exc:
        assert "[system]" in str(exc)
        assert "[user]" in str(exc)
    else:
        raise AssertionError("expected ValueError")
