"""Tests for core.vocab_loader."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.errors import PromptParseError
from core.vocab_loader import (
    format_control_vocab_section,
    load_control_vocab,
    resolve_control_vocab_content,
)


class LoadControlVocabTests(unittest.TestCase):
    """Tests for load_control_vocab."""

    def test_load_valid_vocab(self) -> None:
        """Load valid YAML with categories and terms."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("""version: 1
categories:
  architecture:
    - term: SADS
      definition: Software Architecture Design Specification.
    - term: SRS
      definition: Software Requirements Specification.
  statuses:
    - term: mapped
      definition: Implementation fully matches the design spec.
""")
            path = Path(f.name)
        try:
            vocab = load_control_vocab(path)
            self.assertEqual(vocab["version"], 1)
            self.assertIn("architecture", vocab["categories"])
            arch = vocab["categories"]["architecture"]
            self.assertEqual(len(arch), 2)
            self.assertEqual(arch[0]["term"], "SADS")
            self.assertEqual(arch[0]["definition"], "Software Architecture Design Specification.")
            self.assertIn("statuses", vocab["categories"])
        finally:
            path.unlink(missing_ok=True)

    def test_load_empty_file_returns_empty_categories(self) -> None:
        """Empty or null YAML returns version and empty categories."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("")
            path = Path(f.name)
        try:
            vocab = load_control_vocab(path)
            self.assertEqual(vocab.get("version", 1), 1)
            self.assertEqual(vocab.get("categories", {}), {})
        finally:
            path.unlink(missing_ok=True)

    def test_load_missing_file_raises(self) -> None:
        """Missing file raises PromptParseError."""
        with self.assertRaises(PromptParseError) as ctx:
            load_control_vocab(Path("/nonexistent/vocab.yaml"))
        self.assertIn("not found", str(ctx.exception))

    def test_load_malformed_yaml_raises(self) -> None:
        """Malformed YAML raises PromptParseError."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("categories:\n  - invalid: [")
            path = Path(f.name)
        try:
            with self.assertRaises(PromptParseError) as ctx:
                load_control_vocab(path)
            self.assertIn("Invalid YAML", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)

    def test_load_invalid_root_type_raises(self) -> None:
        """Root must be object."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("- list\n- root")
            path = Path(f.name)
        try:
            with self.assertRaises(PromptParseError) as ctx:
                load_control_vocab(path)
            self.assertIn("root must be an object", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)

    def test_load_invalid_categories_type_raises(self) -> None:
        """Categories must be object."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("categories: [a, b]")
            path = Path(f.name)
        try:
            with self.assertRaises(PromptParseError) as ctx:
                load_control_vocab(path)
            self.assertIn("categories", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)

    def test_load_missing_term_raises(self) -> None:
        """Item must have non-empty term."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("""categories:
  x:
    - definition: only def, no term
""")
            path = Path(f.name)
        try:
            with self.assertRaises(PromptParseError) as ctx:
                load_control_vocab(path)
            self.assertIn("term", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)

    def test_load_missing_definition_raises(self) -> None:
        """Item must have definition string."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("""categories:
  x:
    - term: T1
""")
            path = Path(f.name)
        try:
            with self.assertRaises(PromptParseError) as ctx:
                load_control_vocab(path)
            self.assertIn("definition", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)

    def test_load_synonyms_optional_list_of_strings(self) -> None:
        """Optional synonyms list is loaded and validated."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("""categories:
  x:
    - term: T1
      definition: Def1
      synonyms: [alias1, alias2]
    - term: T2
      definition: Def2
""")
            path = Path(f.name)
        try:
            vocab = load_control_vocab(path)
            items = vocab["categories"]["x"]
            self.assertEqual(items[0]["term"], "T1")
            self.assertEqual(items[0]["synonyms"], ["alias1", "alias2"])
            self.assertNotIn("synonyms", items[1])
        finally:
            path.unlink(missing_ok=True)

    def test_load_synonyms_non_list_raises(self) -> None:
        """Synonyms must be a list when present."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("""categories:
  x:
    - term: T1
      definition: Def1
      synonyms: not-a-list
""")
            path = Path(f.name)
        try:
            with self.assertRaises(PromptParseError) as ctx:
                load_control_vocab(path)
            self.assertIn("synonyms", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)

    def test_load_synonyms_non_string_item_raises(self) -> None:
        """Each synonym must be a string."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write("""categories:
  x:
    - term: T1
      definition: Def1
      synonyms: [ok, 123]
""")
            path = Path(f.name)
        try:
            with self.assertRaises(PromptParseError) as ctx:
                load_control_vocab(path)
            self.assertIn("synonyms", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)


class FormatControlVocabSectionTests(unittest.TestCase):
    """Tests for format_control_vocab_section."""

    def test_format_produces_prompt_friendly_text(self) -> None:
        """Formatted output has categories and term: definition lines."""
        vocab = {
            "version": 1,
            "categories": {
                "architecture": [
                    {"term": "SADS", "definition": "Software Architecture Design Specification."},
                    {"term": "SRS", "definition": "Software Requirements Specification."},
                ],
                "statuses": [
                    {"term": "mapped", "definition": "Implementation fully matches the spec."},
                ],
            },
        }
        result = format_control_vocab_section(vocab)
        self.assertIn("Controlled Vocabulary:", result)
        self.assertIn("[Architecture]", result)
        self.assertIn("- SADS: Software Architecture Design Specification.", result)
        self.assertIn("- SRS: Software Requirements Specification.", result)
        self.assertIn("[Statuses]", result)
        self.assertIn("- mapped: Implementation fully matches the spec.", result)

    def test_format_empty_categories_returns_empty(self) -> None:
        """Empty categories returns empty string."""
        vocab = {"version": 1, "categories": {}}
        result = format_control_vocab_section(vocab)
        self.assertEqual(result, "")

    def test_format_categories_with_empty_lists_skips_them(self) -> None:
        """Categories with empty item lists are skipped."""
        vocab = {
            "version": 1,
            "categories": {
                "empty_cat": [],
                "populated": [{"term": "T1", "definition": "Def1"}],
            },
        }
        result = format_control_vocab_section(vocab)
        self.assertNotIn("Empty_cat", result)
        self.assertIn("[Populated]", result)
        self.assertIn("- T1: Def1", result)

    def test_format_none_categories_returns_empty(self) -> None:
        """None or missing categories returns empty."""
        self.assertEqual(format_control_vocab_section({}), "")
        self.assertEqual(format_control_vocab_section({"categories": None}), "")

    def test_format_includes_synonyms_when_present(self) -> None:
        """Terms with synonyms render as 'term (also: x, y, z): definition'."""
        vocab = {
            "version": 1,
            "categories": {
                "architecture": [
                    {"term": "SADS", "definition": "Design spec.", "synonyms": ["design spec", "SADS table"]},
                    {"term": "SRS", "definition": "Requirements doc."},
                ],
            },
        }
        result = format_control_vocab_section(vocab)
        self.assertIn("- SADS (also: design spec, SADS table): Design spec.", result)
        self.assertIn("- SRS: Requirements doc.", result)

    def test_format_empty_synonyms_list_omits_also_suffix(self) -> None:
        """Empty synonyms list is treated as no synonyms."""
        vocab = {
            "version": 1,
            "categories": {
                "x": [{"term": "T1", "definition": "Def1", "synonyms": []}],
            },
        }
        result = format_control_vocab_section(vocab)
        self.assertIn("- T1: Def1", result)
        self.assertNotIn("(also:", result)


class ResolveControlVocabContentTests(unittest.TestCase):
    """Tests for resolve_control_vocab_content."""

    def test_resolve_not_configured_returns_empty(self) -> None:
        """When control_vocab_path not configured, returns empty string."""
        config = {"project": {"name": "x", "root_dir": ".", "state": {}}}
        result = resolve_control_vocab_content(config, Path("/tmp"))
        self.assertEqual(result, "")

    def test_resolve_empty_project_returns_empty(self) -> None:
        """When project section missing, returns empty string."""
        config = {}
        result = resolve_control_vocab_content(config, Path("/tmp"))
        self.assertEqual(result, "")

    def test_resolve_file_not_found_returns_empty(self) -> None:
        """When file does not exist, returns empty string (logs warning)."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            config = {
                "project": {
                    "name": "x",
                    "root_dir": ".",
                    "state": {},
                    "control_vocab_path": "nonexistent_vocab.yaml",
                }
            }
            result = resolve_control_vocab_content(config, project_root)
            self.assertEqual(result, "")

    def test_resolve_valid_file_returns_formatted_content(self) -> None:
        """When file exists and is valid, returns formatted vocab section."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            vocab_path = project_root / "vocab.yaml"
            vocab_path.write_text("""version: 1
categories:
  domain:
    - term: spec_id
      definition: Stable spec identifier.
""", encoding="utf-8")
            config = {
                "project": {
                    "name": "x",
                    "root_dir": ".",
                    "state": {},
                    "control_vocab_path": "vocab.yaml",
                }
            }
            result = resolve_control_vocab_content(config, project_root)
            self.assertIn("Controlled Vocabulary:", result)
            self.assertIn("[Domain]", result)
            self.assertIn("- spec_id: Stable spec identifier.", result)

    def test_resolve_malformed_file_raises(self) -> None:
        """When file exists but YAML is malformed, raises PromptParseError."""
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            vocab_path = project_root / "vocab.yaml"
            vocab_path.write_text("categories: [invalid", encoding="utf-8")
            config = {
                "project": {
                    "name": "x",
                    "root_dir": ".",
                    "state": {},
                    "control_vocab_path": "vocab.yaml",
                }
            }
            with self.assertRaises(PromptParseError):
                resolve_control_vocab_content(config, project_root)


class IntegrationTests(unittest.TestCase):
    """Integration: vocab appears in rendered prompt when configured."""

    def test_vocab_injected_into_rendered_prompt(self) -> None:
        """When vocab is configured, it appears in the rendered prompt."""
        from core.agent_invoker import render_prompt

        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            vocab_path = project_root / "vocab.yaml"
            vocab_path.write_text("""version: 1
categories:
  domain:
    - term: spec_id
      definition: Stable spec identifier.
""", encoding="utf-8")
            config = {
                "project": {
                    "name": "x",
                    "root_dir": ".",
                    "state": {},
                    "control_vocab_path": "vocab.yaml",
                }
            }
            content = resolve_control_vocab_content(config, project_root)
            template_vars = {
                "control_vocab_section": content,
                "other_var": "other_value",
            }
            prompt = render_prompt(
                "System: use terms correctly.",
                "User: {{control_vocab_section}}\n\nOther: {{other_var}}",
                template_vars,
            )
            self.assertIn("Controlled Vocabulary:", prompt)
            self.assertIn("- spec_id: Stable spec identifier.", prompt)
            self.assertIn("other_value", prompt)
