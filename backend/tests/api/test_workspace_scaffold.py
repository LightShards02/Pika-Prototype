"""Unit tests for ``api.workspace_scaffold``."""

from __future__ import annotations

from pathlib import Path

from api.workspace_scaffold import seed_default_config_if_missing


def test_seed_creates_config_when_missing(tmp_path: Path) -> None:
    """A missing ``config/config.yaml`` is created and ``True`` is returned."""
    workspace = tmp_path / "freshws"
    workspace.mkdir()

    result = seed_default_config_if_missing(workspace)

    assert result is True
    target = workspace / "config" / "config.yaml"
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    # {{ name }} substitution uses the workspace dir's basename.
    assert "{{ name }}" not in text
    assert 'name: "freshws"' in text


def test_seed_is_noop_when_config_exists(tmp_path: Path) -> None:
    """An existing ``config/config.yaml`` is never overwritten."""
    workspace = tmp_path / "existing"
    (workspace / "config").mkdir(parents=True)
    existing_path = workspace / "config" / "config.yaml"
    original = "existing: untouched\n"
    existing_path.write_text(original, encoding="utf-8")

    result = seed_default_config_if_missing(workspace)

    assert result is False
    # File bytes must be byte-equal to the pre-call contents.
    assert existing_path.read_text(encoding="utf-8") == original


def test_seed_substitutes_workspace_name_from_basename(tmp_path: Path) -> None:
    """The ``{{ name }}`` placeholder uses ``workspace_root.name``."""
    workspace = tmp_path / "my-cool-ws"
    workspace.mkdir()

    result = seed_default_config_if_missing(workspace)

    assert result is True
    text = (workspace / "config" / "config.yaml").read_text(encoding="utf-8")
    assert 'name: "my-cool-ws"' in text
    assert "{{ name }}" not in text
