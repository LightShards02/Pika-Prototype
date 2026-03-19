"""Tests for core.codebase_snapshot."""

from __future__ import annotations

import unittest
from pathlib import Path

from core.codebase_snapshot import (
    _build_call_graph,
    _build_file_tree,
    _collect_source_files,
    _detect_language,
    _extract_file_summary,
    _get_codebase_transmission_config,
    build_codebase_snapshot,
)


class ConfigTests(unittest.TestCase):
    """Tests for _get_codebase_transmission_config."""

    def test_returns_defaults_when_config_empty(self) -> None:
        """Returns defaults when codebase_transmission not in config."""
        result = _get_codebase_transmission_config({})
        self.assertIn("max_summary_chars", result)
        self.assertIn("exclude_patterns", result)
        self.assertEqual(result["max_summary_chars"], 200_000)

    def test_merges_project_config_overrides(self) -> None:
        """Project config overrides defaults."""
        config = {"codebase_transmission": {"max_summary_chars": 50_000}}
        result = _get_codebase_transmission_config(config)
        self.assertEqual(result["max_summary_chars"], 50_000)


class CollectFilesTests(unittest.TestCase):
    """Tests for _collect_source_files."""

    def test_collects_python_files(self) -> None:
        """Collects .py files, excludes __pycache__."""
        root = Path(__file__).parent / "test_data_codebase_snapshot" / "collect"
        root.mkdir(parents=True, exist_ok=True)
        (root / "a.py").write_text("x = 1")
        (root / "b.py").write_text("y = 2")
        (root / "sub").mkdir(exist_ok=True)
        (root / "sub" / "c.py").write_text("z = 3")
        (root / "__pycache__").mkdir(exist_ok=True)
        (root / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"x")
        try:
            config = {}
            files = _collect_source_files(root, config)
            paths = [str(f.relative_to(root)).replace("\\", "/") for f in files]
            self.assertIn("a.py", paths)
            self.assertIn("b.py", paths)
            self.assertIn("sub/c.py", paths)
            self.assertNotIn("__pycache__/a.cpython-312.pyc", paths)
        finally:
            for f in root.rglob("*"):
                if f.is_file():
                    f.unlink()
            for d in sorted(root.rglob("*"), key=lambda p: -len(p.parts)):
                if d.is_dir() and d != root:
                    d.rmdir()

    def test_respects_include_extensions(self) -> None:
        """Only includes configured extensions."""
        root = Path(__file__).parent / "test_data_codebase_snapshot" / "extensions"
        root.mkdir(parents=True, exist_ok=True)
        (root / "a.py").write_text("x = 1")
        (root / "b.js").write_text("y = 2")
        try:
            config = {"codebase_transmission": {"include_extensions": [".py"]}}
            files = _collect_source_files(root, config)
            exts = [f.suffix for f in files]
            self.assertIn(".py", exts)
            self.assertNotIn(".js", exts)
        finally:
            for f in root.glob("*"):
                if f.is_file():
                    f.unlink()


class DetectLanguageTests(unittest.TestCase):
    """Tests for _detect_language."""

    def test_python(self) -> None:
        self.assertEqual(_detect_language(Path("x.py")), "python")

    def test_typescript(self) -> None:
        self.assertEqual(_detect_language(Path("x.ts")), "typescript")

    def test_unknown(self) -> None:
        self.assertIsNone(_detect_language(Path("x.xyz")))


class ExtractFileSummaryTests(unittest.TestCase):
    """Tests for _extract_file_summary."""

    def test_extracts_python_symbols(self) -> None:
        """Extracts class and function symbols from Python."""
        root = Path(__file__).parent / "test_data_codebase_snapshot" / "extract"
        root.mkdir(parents=True, exist_ok=True)
        py_file = root / "mod.py"
        py_file.write_text(
            '"""Module doc."""\n'
            "class Foo:\n"
            '    """A class."""\n'
            "    x: int = 0\n"
            "    def bar(self) -> None:\n"
            "        pass\n"
            "def baz() -> int:\n"
            "    return 1\n"
        )
        try:
            summary = _extract_file_summary(py_file, root, {}, set())
            self.assertIsNotNone(summary)
            assert summary is not None
            self.assertEqual(summary.rel_path, "mod.py")
            names = [s.name for s in summary.symbols]
            self.assertIn("Foo", names)
            self.assertIn("Foo.bar", names)
            self.assertIn("baz", names)
        finally:
            py_file.unlink(missing_ok=True)


class BuildFileTreeTests(unittest.TestCase):
    """Tests for _build_file_tree."""

    def test_renders_indented_tree(self) -> None:
        """Renders directory structure."""
        root = Path(__file__).parent / "test_data_codebase_snapshot" / "tree"
        root.mkdir(parents=True, exist_ok=True)
        (root / "sub").mkdir(exist_ok=True)
        files = [root / "a.py", root / "sub" / "b.py"]
        for f in files:
            f.write_text("")
        try:
            tree = _build_file_tree(files, root)
            self.assertIn("a.py", tree)
            self.assertIn("sub/", tree)
            self.assertIn("b.py", tree)
        finally:
            for f in files:
                f.unlink(missing_ok=True)


class BuildCodebaseSnapshotTests(unittest.TestCase):
    """Tests for build_codebase_snapshot."""

    def test_returns_fallback_when_no_files(self) -> None:
        """Returns fallback when codebase_dir has no source files."""
        root = Path(__file__).parent / "test_data_codebase_snapshot" / "empty"
        root.mkdir(parents=True, exist_ok=True)
        result = build_codebase_snapshot(root, {})
        self.assertIn("No source files", result)

    def test_returns_snapshot_with_python_files(self) -> None:
        """Returns per-file snapshot for Python project."""
        root = Path(__file__).parent / "test_data_codebase_snapshot" / "snapshot"
        root.mkdir(parents=True, exist_ok=True)
        (root / "main.py").write_text(
            "def hello() -> str:\n"
            '    """Return greeting."""\n'
            "    return 'hi'\n"
        )
        try:
            result = build_codebase_snapshot(root, {})
            self.assertIn("# Codebase Snapshot", result)
            self.assertIn("## File Tree", result)
            self.assertIn("## Files", result)
            self.assertIn("### main.py", result)
            self.assertIn("#### Symbols", result)
            self.assertIn("def hello", result)
            self.assertIn("Return greeting", result)
            self.assertIn("## Call Graph", result)
        finally:
            (root / "main.py").unlink(missing_ok=True)
