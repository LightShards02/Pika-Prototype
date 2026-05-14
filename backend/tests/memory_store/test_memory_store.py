"""Unit tests for core.memory_store."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import memory_store


def test_memory_files_locked_order() -> None:
    assert memory_store.memory_files() == ("memory", "lessons", "tasks", "gaps")


def test_is_valid_file_accepts_whitelist() -> None:
    for name in ("memory", "lessons", "tasks", "gaps"):
        assert memory_store.is_valid_file(name)
    for bogus in ("bogus", "memory.md", "", "Memory"):
        assert not memory_store.is_valid_file(bogus)


def test_read_file_returns_empty_for_missing(tmp_path: Path) -> None:
    assert memory_store.read_file(tmp_path, "lessons") == ""


def test_read_file_rejects_unknown_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        memory_store.read_file(tmp_path, "bogus")


def test_read_all_returns_all_four_keys(tmp_path: Path) -> None:
    out = memory_store.read_all(tmp_path)
    assert set(out.keys()) == {"memory", "lessons", "tasks", "gaps"}
    assert all(v == "" for v in out.values())


def test_write_then_read_round_trip(tmp_path: Path) -> None:
    memory_store.write_file(tmp_path, "lessons", "- one\n- two\n")
    assert memory_store.read_file(tmp_path, "lessons") == "- one\n- two\n"
    bundle = memory_store.read_all(tmp_path)
    assert bundle["lessons"] == "- one\n- two\n"
    assert bundle["memory"] == ""


def test_write_file_atomic_leaves_no_tmp(tmp_path: Path) -> None:
    memory_store.write_file(tmp_path, "tasks", "T1")
    mdir = memory_store.memory_dir(tmp_path)
    leftover = [p for p in mdir.glob("*.tmp")]
    assert leftover == []


def test_write_file_rejects_unknown_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        memory_store.write_file(tmp_path, "bogus", "x")


def test_bootstrap_creates_four_files(tmp_path: Path) -> None:
    memory_store.bootstrap(tmp_path)
    mdir = memory_store.memory_dir(tmp_path)
    assert mdir.is_dir()
    for name in ("memory", "lessons", "tasks", "gaps"):
        path = mdir / f"{name}.md"
        assert path.is_file()
        assert path.read_text(encoding="utf-8").startswith("# ")


def test_bootstrap_idempotent_preserves_content(tmp_path: Path) -> None:
    memory_store.bootstrap(tmp_path)
    memory_store.write_file(tmp_path, "lessons", "custom-lesson")
    memory_store.bootstrap(tmp_path)
    assert memory_store.read_file(tmp_path, "lessons") == "custom-lesson"


def test_render_for_prompt_locked_shape() -> None:
    rendered = memory_store.render_for_prompt(
        {"memory": "M", "lessons": "L", "tasks": "T", "gaps": "G"}
    )
    assert rendered.startswith("# Workspace Memory\n")
    assert "## Workspace Memory" in rendered
    assert "## Lessons" in rendered
    assert "## Tasks" in rendered
    assert "## Gaps" in rendered
    idx_mem = rendered.index("## Workspace Memory")
    idx_les = rendered.index("## Lessons")
    idx_tsk = rendered.index("## Tasks")
    idx_gap = rendered.index("## Gaps")
    assert idx_mem < idx_les < idx_tsk < idx_gap
    assert "M" in rendered and "L" in rendered and "T" in rendered and "G" in rendered


def test_render_for_prompt_partial_dict_renders_empty_sections() -> None:
    rendered = memory_store.render_for_prompt({"lessons": "L"})
    assert "## Workspace Memory" in rendered
    assert "## Lessons" in rendered
    assert "## Tasks" in rendered
    assert "## Gaps" in rendered
    assert "L" in rendered


def test_render_for_prompt_none_or_empty() -> None:
    rendered = memory_store.render_for_prompt(None)
    assert "## Workspace Memory" in rendered
    assert "## Gaps" in rendered
    rendered2 = memory_store.render_for_prompt({})
    assert rendered2 == rendered


def test_memory_template_value_handles_missing_ctx_attr() -> None:
    class FakeCtx:
        pass

    assert memory_store.memory_template_value(FakeCtx()) == ""


def test_memory_template_value_renders_when_set() -> None:
    class FakeCtx:
        memory_context = {"lessons": "lesson-x"}

    out = memory_store.memory_template_value(FakeCtx())
    assert "## Lessons" in out
    assert "lesson-x" in out
