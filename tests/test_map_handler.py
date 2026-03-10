"""Tests for handlers.map."""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from core.context import RuntimeContext

from handlers.map import (
    build_template_vars,
    filter_rows_for_mapping,
    group_by_subunit,
    load_outputs_from_directory,
    merge_subunit_results,
    run_map,
    sanitize_subunit_for_filename,
    translate_map,
    validate_map_output_contract,
    validate_spec_id_unique,
    validate_subunit_column,
)

_TEST_DATA_DIR = Path(__file__).parent / "test_data_map_translate"

# Required by get_design_spec_add_if_missing; config is single source of truth
_MAP_TEST_CSV_CONTRACTS = {
    "csv_contracts": {
        "design_spec": {
            "add_if_missing": [
                "spec_id",
                "module_tag",
                "subunit",
                "mapped_code_symbols",
                "mapped_confidence",
                "mapped_consistency_score",
                "mapped_problems",
                "map_status",
                "map_assumptions",
                "mapped_at",
            ]
        }
    }
}


def _map_test_config(root: Path, **overrides: Any) -> dict[str, Any]:
    """Build map test config with command-scoped inputs/outputs."""
    base = {
        **_MAP_TEST_CSV_CONTRACTS,
        "project": {
            "name": "test",
            "root_dir": ".",
            "state": {
                "design_spec_path": "out/state/DESIGN-SPEC.csv",
                "id_registry_path": "out/state/id_registry.json",
                "sads_id_mapping_path": "out/state/sads_id_mapping.json",
            },
        },
        "commands": {
            "map": {
                "enabled": True,
                "prompt_name": "map_spec_to_code",
                "inputs": {
                    "design_spec_path": "out/state/DESIGN-SPEC.csv",
                    "codebase_dir": ".",
                    "project_context_filename": "PROJECT_CONTEXT.md",
                },
                "outputs": {
                    "backups_dir": {"path": str(root / "out" / "backups"), "no_overwrite": False},
                    "intermediate_map_dir": {"path": str(root / "out" / "intermediate" / "map"), "no_overwrite": False},
                },
            },
        },
    }
    for k, v in overrides.items():
        if k == "design_spec_path":
            base["commands"]["map"]["inputs"]["design_spec_path"] = str(v)
            base["project"]["state"]["design_spec_path"] = str(v)
        elif k == "backups_dir":
            base["commands"]["map"]["outputs"]["backups_dir"] = v
        elif k == "outputs" and isinstance(v, dict):
            base["commands"]["map"]["outputs"].update(v)
        elif k == "inputs" and isinstance(v, dict):
            base["commands"]["map"]["inputs"].update(v)
        else:
            base[k] = v
    return base


class MapOutputContractTests(unittest.TestCase):
    """Test map-output contract checks that complement JSON schema validation."""

    def testvalidate_map_output_contract_allows_missing_mappings(self) -> None:
        """Outputs without mappings are accepted (e.g., blocking manual-resolution path)."""
        validate_map_output_contract({"manual_resolution_items": [{}]})

    def testvalidate_map_output_contract_accepts_valid_spec_id_keys(self) -> None:
        """Mappings with keys matching ^[A-Za-z][0-9]+$ are accepted."""
        validate_map_output_contract(
            {
                "mappings": {
                    "A1": {"status": "mapped", "code_refs": [], "assumptions": ""},
                    "B12": {"status": "unmapped", "code_refs": [], "assumptions": ""},
                }
            }
        )

    def testvalidate_map_output_contract_accepts_dict_shape(self) -> None:
        """Dict mappings with spec_id keys are accepted and normalized."""
        output = {
            "mappings": {
                "A1": {"status": "mapped", "code_refs": [], "assumptions": ""},
            }
        }
        validate_map_output_contract(output)
        self.assertIsInstance(output["mappings"], dict)
        self.assertIn("A1", output["mappings"])

    def testvalidate_map_output_contract_accepts_list_shape(self) -> None:
        """List mappings with spec_id are accepted and normalized to dict."""
        output = {
            "mappings": [
                {"spec_id": "A1", "status": "mapped", "code_refs": [], "assumptions": ""},
                {"spec_id": "B2", "status": "unmapped", "code_refs": [], "assumptions": ""},
            ]
        }
        validate_map_output_contract(output)
        self.assertIsInstance(output["mappings"], dict)
        self.assertIn("A1", output["mappings"])
        self.assertIn("B2", output["mappings"])

    def testvalidate_map_output_contract_rejects_list_missing_spec_id(self) -> None:
        """List mappings must include spec_id on each item."""
        with self.assertRaises(ValueError) as ctx:
            validate_map_output_contract(
                {
                    "mappings": [
                        {"status": "mapped", "code_refs": [], "assumptions": ""},
                    ]
                }
            )
        self.assertIn("must include non-empty 'spec_id'", str(ctx.exception))

    def testvalidate_map_output_contract_allows_blocking_with_empty_mappings(self) -> None:
        """Blocking outputs are accepted when mappings is an empty object."""
        validate_map_output_contract(
            {
                "manual_resolution_items": [{"id": "x"}],
                "mappings": {},
            }
        )

    def testvalidate_map_output_contract_rejects_blocking_when_mapping_overlaps_entity_id(
        self,
    ) -> None:
        """When manual_resolution_items references a spec_id, that spec_id must not appear in mappings."""
        with self.assertRaises(ValueError) as ctx:
            validate_map_output_contract(
                {
                    "manual_resolution_items": [
                        {
                            "command": "agent map",
                            "entity_type": "spec",
                            "entity_id": "A1",
                            "reason": "x",
                            "details": "y",
                            "created_at": "2026-01-01T00:00:00Z",
                        }
                    ],
                    "mappings": {"A1": {"status": "mapped", "code_refs": [], "assumptions": ""}},
                }
            )
        self.assertIn("Overlapping", str(ctx.exception))

    def testvalidate_map_output_contract_allows_blocking_with_non_overlapping_mappings(
        self,
    ) -> None:
        """When manual_resolution_items references spec_ids, only those spec_ids must be absent from mappings."""
        validate_map_output_contract(
            {
                "manual_resolution_items": [
                    {
                        "command": "agent map",
                        "entity_type": "spec",
                        "entity_id": "A109-A342",
                        "reason": "chunk required",
                        "details": "dense block",
                        "created_at": "2026-01-01T00:00:00Z",
                    }
                ],
                "mappings": {
                    "A1": {"status": "mapped", "code_refs": [], "assumptions": ""},
                    "A88": {"status": "partial", "code_refs": [], "assumptions": ""},
                },
            }
        )

    def testvalidate_map_output_contract_rejects_blocking_when_range_overlaps_mappings(
        self,
    ) -> None:
        """When manual_resolution_items entity_id is a range, mappings must not contain any spec_id in that range."""
        with self.assertRaises(ValueError) as ctx:
            validate_map_output_contract(
                {
                    "manual_resolution_items": [
                        {
                            "command": "agent map",
                            "entity_type": "spec",
                            "entity_id": "A109-A342",
                            "reason": "chunk required",
                            "details": "dense block",
                            "created_at": "2026-01-01T00:00:00Z",
                        }
                    ],
                    "mappings": {
                        "A1": {"status": "mapped", "code_refs": [], "assumptions": ""},
                        "A200": {"status": "mapped", "code_refs": [], "assumptions": ""},
                    },
                }
            )
        self.assertIn("A200", str(ctx.exception))

    def testvalidate_map_output_contract_rejects_invalid_mappings_type(self) -> None:
        """Mappings must be an object with spec_id keys."""
        with self.assertRaises(ValueError) as ctx:
            validate_map_output_contract({"mappings": "bad"})
        self.assertIn("'mappings' must be an object", str(ctx.exception))

    def testvalidate_map_output_contract_rejects_invalid_mapping_keys(self) -> None:
        """Mapping keys that do not match ^[A-Za-z][0-9]+$ are rejected."""
        with self.assertRaises(ValueError) as ctx:
            validate_map_output_contract(
                {
                    "mappings": {
                        "AA_1": {"status": "mapped", "code_refs": [], "assumptions": ""},
                        "1A": {"status": "mapped", "code_refs": [], "assumptions": ""},
                    }
                }
            )
        self.assertIn("mappings keys must match ^[A-Za-z][0-9]+$", str(ctx.exception))

    def testvalidate_map_output_contract_normalizes_code_refs_with_consistency_and_problems(
        self,
    ) -> None:
        """Code_refs are normalized to include consistency_score and problems."""
        output = {
            "mappings": {
                "A1": {
                    "status": "partial",
                    "code_refs": [
                        {
                            "path": "src/Foo.cs",
                            "symbol_name": "Foo",
                            "symbol_type": "class",
                            "confidence": 0.8,
                            "consistency_score": 0.6,
                            "problems": "Semantics differ from spec.",
                        }
                    ],
                    "assumptions": "Partial match.",
                }
            }
        }
        validate_map_output_contract(output)
        refs = output["mappings"]["A1"]["code_refs"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["consistency_score"], 0.6)
        self.assertEqual(refs[0]["problems"], "Semantics differ from spec.")
        self.assertEqual(output["mappings"]["A1"]["assumptions"], "Partial match.")

    def testvalidate_map_output_contract_accepts_legacy_notes_as_problems(self) -> None:
        """Legacy code_ref.notes is normalized to problems for backward compatibility."""
        output = {
            "mappings": {
                "A1": {
                    "status": "partial",
                    "code_refs": [
                        {
                            "path": "src/Foo.cs",
                            "symbol_name": "Foo",
                            "symbol_type": "class",
                            "confidence": 0.7,
                            "consistency_score": 0.5,
                            "notes": "Legacy field.",  # legacy for problems
                        }
                    ],
                    "assumptions": "",
                }
            }
        }
        validate_map_output_contract(output)
        self.assertEqual(output["mappings"]["A1"]["code_refs"][0]["problems"], "Legacy field.")


class MapTranslateTests(unittest.TestCase):
    """Test translate_map: codex output → CSV mapping column updates."""

    def setUp(self) -> None:
        """Create test data directory."""
        _TEST_DATA_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        """Remove test data directory."""
        if _TEST_DATA_DIR.exists():
            shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)

    def testtranslate_map_updates_mapping_columns(self) -> None:
        """Translate applies mapped_code_symbols, map_status, map_assumptions, mapped_at."""
        root = _TEST_DATA_DIR / "test1"
        root.mkdir(parents=True, exist_ok=True)
        design_csv = root / "design_spec.csv"
        design_csv.write_text(
            "spec_id,subunit,title,requirement,mapped_code_symbols,map_status,map_assumptions,mapped_at\n"
            "A1,S1,Foo,Do foo,,unmapped,,\n"
            "A2,S1,Bar,Do bar,,unmapped,,\n",
            encoding="utf-8",
        )
        backups_dir = root / "out" / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)

        config = _map_test_config(root, design_spec_path=design_csv)
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-abc12345",
            project_root=str(root),
            config_path=str(root / "config.yaml"),
        )
        output = {
            "mappings": {
                "A1": {
                    "status": "mapped",
                    "code_refs": [
                        {"path": "src/Foo.cs", "symbol_name": "Foo.DoFoo", "symbol_type": "function"},
                        {"path": "src/Bar.cs", "symbol_name": "Bar.Helper", "symbol_type": "function"},
                    ],
                    "assumptions": "Implementation found in Foo and Bar.",
                },
                "A2": {
                    "status": "unmapped",
                    "code_refs": [],
                    "assumptions": "No code reference found.",
                },
            },
            "created_at": "2026-02-21T12:00:00.000Z",
        }
        inputs = {"design_spec_path": design_csv}

        translate_map(config, ctx, output, inputs)

        content = design_csv.read_text(encoding="utf-8")
        self.assertIn("Foo.DoFoo,Bar.Helper", content)
        self.assertIn("Implementation found in Foo and Bar.", content)
        self.assertIn("No code reference found.", content)
        # mapped_at normalized to YYYY-MM-DDTHH:MM:SS UTC+X
        self.assertRegex(content, r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2} UTC[+-]\d{1,2}(:\d{2})?")
        # Backup created
        map_backups = backups_dir / "map"
        self.assertTrue(map_backups.is_dir())
        backups_list = list(map_backups.glob("design_spec_*.csv"))
        self.assertGreater(len(backups_list), 0)

    def testtranslate_map_skips_dry_run(self) -> None:
        """Dry-run does not modify the design spec."""
        root = _TEST_DATA_DIR / "test2"
        root.mkdir(parents=True, exist_ok=True)
        design_csv = root / "design_spec.csv"
        original = "spec_id,title\nA1,Foo\n"
        design_csv.write_text(original, encoding="utf-8")

        config = _map_test_config(root, design_spec_path=design_csv)
        ctx = RuntimeContext(
            command="map",
            dry_run=True,
            verbose=False,
            command_only_validation=False,
            run_id="run-xyz",
            project_root=str(root),
            config_path=str(root / "config.yaml"),
        )
        output = {"mappings": {"A1": {"status": "mapped", "code_refs": [], "assumptions": "x"}}}
        inputs = {"design_spec_path": design_csv}

        translate_map(config, ctx, output, inputs)

        self.assertEqual(design_csv.read_text(encoding="utf-8"), original)

    def testtranslate_map_writes_confidence_consistency_problems(self) -> None:
        """Translate populates mapped_confidence, mapped_consistency_score, mapped_problems."""
        root = _TEST_DATA_DIR / "test_confidence"
        root.mkdir(parents=True, exist_ok=True)
        design_csv = root / "design_spec.csv"
        design_csv.write_text(
            "spec_id,subunit,title,mapped_code_symbols,mapped_confidence,mapped_consistency_score,mapped_problems,"
            "map_status,map_assumptions,mapped_at\n"
            "A1,S1,Foo,,,,,,\n",
            encoding="utf-8",
        )
        (root / "out" / "backups").mkdir(parents=True, exist_ok=True)

        config = _map_test_config(root, design_spec_path=design_csv)
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-conf",
            project_root=str(root),
            config_path=str(root / "config.yaml"),
        )
        output = {
            "mappings": {
                "A1": {
                    "status": "partial",
                    "code_refs": [
                        {
                            "path": "src/Foo.cs",
                            "symbol_name": "Foo.Bar",
                            "symbol_type": "function",
                            "confidence": 0.85,
                            "consistency_score": 0.7,
                            "problems": "Semantics differ from spec.",
                        },
                        {
                            "path": "src/Baz.cs",
                            "symbol_name": "Baz.Quux",
                            "symbol_type": "class",
                            "confidence": 0.9,
                            "consistency_score": 0.95,
                            "problems": "",
                        },
                    ],
                    "assumptions": "Partial match.",
                },
            },
            "created_at": "2026-02-21T12:00:00Z",
        }
        inputs = {"design_spec_path": design_csv}

        translate_map(config, ctx, output, inputs)

        content = design_csv.read_text(encoding="utf-8")
        self.assertIn("Foo.Bar,Baz.Quux", content)
        self.assertIn("0.85,0.90", content)
        self.assertIn("0.70,0.95", content)
        self.assertIn("Semantics differ from spec.", content)

    def testtranslate_map_raises_when_backups_dir_missing(self) -> None:
        """Translate raises when backups_dir is not configured."""
        root = _TEST_DATA_DIR / "test_no_backup"
        root.mkdir(parents=True, exist_ok=True)
        design_csv = root / "design_spec.csv"
        design_csv.write_text(
            "spec_id,subunit,title\nA1,S1,Foo\n",
            encoding="utf-8",
        )
        config = _map_test_config(root, design_spec_path=design_csv)
        del config["commands"]["map"]["outputs"]["backups_dir"]
        runtime_ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-nobackup",
            project_root=str(root),
            config_path=str(root / "config.yaml"),
        )
        output = {"mappings": {"A1": {"status": "unmapped", "code_refs": [], "assumptions": ""}}}
        inputs = {"design_spec_path": design_csv}
        with self.assertRaises(ValueError) as exc_ctx:
            translate_map(config, runtime_ctx, output, inputs)
        self.assertIn("backups_dir is required", str(exc_ctx.exception))

    def testtranslate_map_appends_missing_columns(self) -> None:
        """Missing mapping columns are appended before update."""
        root = _TEST_DATA_DIR / "test3"
        root.mkdir(parents=True, exist_ok=True)
        design_csv = root / "design_spec.csv"
        design_csv.write_text(
            "spec_id,subunit,title,requirement\nA1,S1,Foo,Do foo\n",
            encoding="utf-8",
        )
        (root / "out" / "backups").mkdir(parents=True, exist_ok=True)

        config = _map_test_config(root, design_spec_path=design_csv)
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-123",
            project_root=str(root),
            config_path=str(root / "config.yaml"),
        )
        output = {
            "mappings": {"A1": {"status": "partial", "code_refs": [{"symbol_name": "Foo"}], "assumptions": "Partial."}},
            "created_at": "2026-02-21T12:00:00Z",
        }
        inputs = {"design_spec_path": design_csv}

        translate_map(config, ctx, output, inputs)

        content = design_csv.read_text(encoding="utf-8")
        self.assertIn("mapped_code_symbols", content)
        self.assertIn("map_status", content)
        self.assertIn("map_assumptions", content)
        self.assertIn("mapped_at", content)
        self.assertIn("Foo", content)
        self.assertIn("partial", content)


class MapFilterAndGroupTests(unittest.TestCase):
    """Tests for filter_rows_for_mapping, group_by_subunit, validate_subunit_column."""

    def testvalidate_subunit_column_raises_when_missing(self) -> None:
        """Raises when subunit column is absent."""
        headers = ["spec_id", "title"]
        rows = [{"spec_id": "A1", "title": "Foo"}]
        with self.assertRaises(ValueError) as ctx:
            validate_subunit_column(headers, rows)
        self.assertIn("subunit", str(ctx.exception))

    def testvalidate_spec_id_unique_passes_when_unique(self) -> None:
        """Unique spec_ids pass validation."""
        headers = ["spec_id", "subunit"]
        rows = [
            {"spec_id": "A1", "subunit": "S1"},
            {"spec_id": "A2", "subunit": "S1"},
        ]
        validate_spec_id_unique(headers, rows)  # no raise

    def testvalidate_spec_id_unique_raises_when_duplicate(self) -> None:
        """Duplicate spec_ids raise ValueError."""
        headers = ["spec_id", "subunit"]
        rows = [
            {"spec_id": "A1", "subunit": "S1"},
            {"spec_id": "A2", "subunit": "S1"},
            {"spec_id": "A1", "subunit": "S2"},
        ]
        with self.assertRaises(ValueError) as ctx:
            validate_spec_id_unique(headers, rows)
        self.assertIn("Duplicate spec_id", str(ctx.exception))
        self.assertIn("A1", str(ctx.exception))

    def testvalidate_subunit_column_raises_when_empty(self) -> None:
        """Raises when any row has empty subunit."""
        headers = ["spec_id", "subunit", "title"]
        rows = [
            {"spec_id": "A1", "subunit": "S1", "title": "Foo"},
            {"spec_id": "A2", "subunit": "", "title": "Bar"},
        ]
        with self.assertRaises(ValueError) as ctx:
            validate_subunit_column(headers, rows)
        self.assertIn("Row 2", str(ctx.exception))
        self.assertIn("empty subunit", str(ctx.exception))

    def testvalidate_subunit_column_passes_when_all_filled(self) -> None:
        """Passes when all rows have non-empty subunit."""
        headers = ["spec_id", "subunit", "title"]
        rows = [
            {"spec_id": "A1", "subunit": "S1", "title": "Foo"},
            {"spec_id": "A2", "subunit": "S1", "title": "Bar"},
        ]
        validate_subunit_column(headers, rows)  # no raise

    def test_filter_rows_skips_mapped_when_skip_mapped_true(self) -> None:
        """Filter excludes rows with map_status=mapped when skip_mapped=True."""
        headers = ["spec_id", "map_status"]
        rows = [
            {"spec_id": "A1", "map_status": "unmapped"},
            {"spec_id": "A2", "map_status": "mapped"},
            {"spec_id": "A3", "map_status": "partial"},
        ]
        filtered = filter_rows_for_mapping(headers, rows, skip_mapped=True)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered[0]["spec_id"], "A1")
        self.assertEqual(filtered[1]["spec_id"], "A3")

    def test_filter_rows_includes_all_when_skip_mapped_false(self) -> None:
        """Filter includes all rows when skip_mapped=False."""
        headers = ["spec_id", "map_status"]
        rows = [
            {"spec_id": "A1", "map_status": "mapped"},
            {"spec_id": "A2", "map_status": "unmapped"},
        ]
        filtered = filter_rows_for_mapping(headers, rows, skip_mapped=False)
        self.assertEqual(len(filtered), 2)

    def testgroup_by_subunit_groups_correctly(self) -> None:
        """Rows are grouped by subunit value."""
        headers = ["spec_id", "subunit"]
        rows = [
            {"spec_id": "A1", "subunit": "S1"},
            {"spec_id": "A2", "subunit": "S1"},
            {"spec_id": "A3", "subunit": "S2"},
        ]
        groups = group_by_subunit(headers, rows)
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups["S1"]), 2)
        self.assertEqual(len(groups["S2"]), 1)
        self.assertEqual(groups["S1"][0]["spec_id"], "A1")
        self.assertEqual(groups["S2"][0]["spec_id"], "A3")

    def testmerge_subunit_results_combines_mappings(self) -> None:
        """Merge combines mappings from multiple subunit outputs."""
        batch_outputs = [
            {
                "mappings": {"A1": {"status": "mapped", "code_refs": [], "assumptions": ""}},
                "manual_resolution_items": [],
                "run_summary": {},
                "created_at": "2026-02-21T12:00:00Z",
            },
            {
                "mappings": {"A2": {"status": "unmapped", "code_refs": [], "assumptions": ""}},
                "manual_resolution_items": [],
                "run_summary": {},
                "created_at": "2026-02-21T12:00:00Z",
            },
        ]
        merged = merge_subunit_results(batch_outputs)
        self.assertIn("A1", merged["mappings"])
        self.assertIn("A2", merged["mappings"])
        self.assertEqual(merged["mappings"]["A1"]["status"], "mapped")
        self.assertEqual(merged["mappings"]["A2"]["status"], "unmapped")

    def testmerge_subunit_results_rejects_duplicate_spec_id(self) -> None:
        """Merge raises when same spec_id appears in multiple subunits."""
        batch_outputs = [
            {"mappings": {"A1": {"status": "mapped", "code_refs": [], "assumptions": ""}}, "manual_resolution_items": [], "run_summary": {}, "created_at": ""},
            {"mappings": {"A1": {"status": "unmapped", "code_refs": [], "assumptions": ""}}, "manual_resolution_items": [], "run_summary": {}, "created_at": ""},
        ]
        with self.assertRaises(ValueError) as ctx:
            merge_subunit_results(batch_outputs)
        self.assertIn("Duplicate spec_id", str(ctx.exception))
        self.assertIn("A1", str(ctx.exception))


class LoadOutputsFromDirectoryTests(unittest.TestCase):
    """Tests for load_outputs_from_directory."""

    def setUp(self) -> None:
        self.tmp = _TEST_DATA_DIR / "load_outputs"
        self.tmp.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load_outputs_valid_dir(self) -> None:
        """Load returns list of parsed outputs ordered by filename."""
        (self.tmp / "a.json").write_text(
            json.dumps({"mappings": {"A1": {"status": "mapped", "code_refs": [], "assumptions": ""}}}),
            encoding="utf-8",
        )
        (self.tmp / "b.json").write_text(
            json.dumps({"mappings": {"A2": {"status": "unmapped", "code_refs": [], "assumptions": ""}}}),
            encoding="utf-8",
        )
        outputs = load_outputs_from_directory(self.tmp)
        self.assertEqual(len(outputs), 2)
        self.assertIn("A1", outputs[0]["mappings"])
        self.assertIn("A2", outputs[1]["mappings"])

    def test_load_outputs_empty_dir_raises(self) -> None:
        """Empty directory raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            load_outputs_from_directory(self.tmp)
        self.assertIn("No *.json files", str(ctx.exception))

    def test_load_outputs_missing_dir_raises(self) -> None:
        """Missing directory raises ValueError."""
        missing = self.tmp / "nonexistent"
        with self.assertRaises(ValueError) as ctx:
            load_outputs_from_directory(missing)
        self.assertIn("does not exist", str(ctx.exception))

    def test_load_outputs_invalid_json_raises(self) -> None:
        """Invalid JSON in file raises ValueError."""
        (self.tmp / "bad.json").write_text("not json", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            load_outputs_from_directory(self.tmp)
        self.assertIn("Invalid or unreadable", str(ctx.exception))

    def test_load_outputs_missing_mappings_raises(self) -> None:
        """File without mappings raises ValueError."""
        (self.tmp / "no_mappings.json").write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            load_outputs_from_directory(self.tmp)
        self.assertIn("Missing 'mappings'", str(ctx.exception))


class SanitizeSubunitForFilenameTests(unittest.TestCase):
    """Tests for sanitize_subunit_for_filename."""

    def test_sanitize_subunit_special_chars(self) -> None:
        """Special chars are replaced with underscore."""
        self.assertEqual(sanitize_subunit_for_filename("SRV:CM"), "SRV_CM")
        self.assertEqual(sanitize_subunit_for_filename("a/b\\c"), "a_b_c")

    def test_sanitize_subunit_alphanumeric(self) -> None:
        """Alphanumeric and hyphen are preserved."""
        self.assertEqual(sanitize_subunit_for_filename("SRV-CM"), "SRV-CM")
        self.assertEqual(sanitize_subunit_for_filename("Subunit1"), "Subunit1")


class RunMapApplyExistingOutputsTests(unittest.TestCase):
    """Tests for run_map with apply_existing_outputs override."""

    def setUp(self) -> None:
        self.root = _TEST_DATA_DIR / "apply_existing"
        self.root.mkdir(parents=True, exist_ok=True)
        self.design_csv = self.root / "design_spec.csv"
        self.design_csv.write_text(
            "spec_id,subunit,title,mapped_code_symbols,index_status,assumptions,last_indexed_at\n"
            "A1,S1,Foo,,unmapped,,\n"
            "A2,S1,Bar,,unmapped,,\n",
            encoding="utf-8",
        )
        (self.root / "out" / "backups" / "map").mkdir(parents=True, exist_ok=True)
        self.outputs_dir = self.root / "existing_outputs"
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def test_apply_existing_outputs_translates(self) -> None:
        """With apply_existing_outputs, loads from dir, merges, translates without agent."""
        (self.outputs_dir / "map_S1.json").write_text(
            json.dumps({
                "manual_resolution_items": [],
                "run_summary": {},
                "created_at": "2026-02-21T12:00:00Z",
                "mappings": {
                    "A1": {"status": "mapped", "code_refs": [{"symbol_name": "Foo"}], "assumptions": "ok"},
                    "A2": {"status": "unmapped", "code_refs": [], "assumptions": "n/a"},
                },
            }),
            encoding="utf-8",
        )
        config = _map_test_config(
            self.root,
            design_spec_path=self.design_csv,
            outputs={"agent_runs_dir": {"path": str(self.root / "out" / "agent_runs"), "no_overwrite": False}},
        )
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-apply",
            project_root=str(self.root),
            config_path=str(self.root / "config.yaml"),
            input_overrides={"design_spec_path": str(self.design_csv), "apply_existing_outputs": str(self.outputs_dir)},
        )
        with patch("handlers.map.invoke_agent_with_schema_retry") as mock_invoke:
            result = run_map(config, ctx)
        mock_invoke.assert_not_called()
        self.assertEqual(result["status"], "completed")
        content = self.design_csv.read_text(encoding="utf-8")
        self.assertIn("Foo", content)
        self.assertIn("mapped", content)

    def test_apply_existing_outputs_nonexistent_dir_fails(self) -> None:
        """Non-existent directory returns failed."""
        config = _map_test_config(self.root, design_spec_path=self.design_csv)
        config["commands"]["map"]["outputs"] = {}
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-apply",
            project_root=str(self.root),
            config_path=str(self.root / "config.yaml"),
            input_overrides={"design_spec_path": str(self.design_csv), "apply_existing_outputs": str(self.root / "nonexistent")},
        )
        result = run_map(config, ctx)
        self.assertEqual(result["status"], "failed")
        self.assertIn("not an existing directory", result["reason"])


class RunMapPerSubunitPersistenceTests(unittest.TestCase):
    """Tests for per-subunit output persistence during normal map run."""

    def setUp(self) -> None:
        self.root = _TEST_DATA_DIR / "persist_subunit"
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "PROJECT_CONTEXT.md").write_text("# Test\n", encoding="utf-8")
        self.design_csv = self.root / "design_spec.csv"
        self.design_csv.write_text(
            "spec_id,subunit,title,mapped_code_symbols,index_status,assumptions,last_indexed_at\n"
            "A1,S1,Foo,,unmapped,,\n"
            "A2,S2,Bar,,unmapped,,\n",
            encoding="utf-8",
        )
        (self.root / "out" / "backups" / "map").mkdir(parents=True, exist_ok=True)
        self.intermediate_dir = self.root / "out" / "intermediate" / "map"
        self.intermediate_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def test_persists_subunit_outputs(self) -> None:
        """Each successful subunit outputs persist to intermediate_map_dir/run_id/map_*.json."""
        outputs_by_subunit = {
            "S1": {"manual_resolution_items": [], "run_summary": {}, "created_at": "2026-02-21T12:00:00Z", "mappings": {"A1": {"status": "mapped", "code_refs": [], "assumptions": ""}}},
            "S2": {"manual_resolution_items": [], "run_summary": {}, "created_at": "2026-02-21T12:00:00Z", "mappings": {"A2": {"status": "unmapped", "code_refs": [], "assumptions": ""}}},
        }

        def fake_invoke(prompt_name, template_vars, **kwargs):
            # Infer subunit from design_spec_rows_csv or agent_view_content in template_vars
            csv_content = template_vars.get("design_spec_rows_csv", "")
            if "A1" in csv_content:
                return outputs_by_subunit["S1"]
            return outputs_by_subunit["S2"]

        config = _map_test_config(self.root, design_spec_path=self.design_csv)
        config["commands"]["map"]["outputs"]["intermediate_map_dir"] = {
            "path": str(self.intermediate_dir),
            "no_overwrite": False,
        }
        config["commands"]["map"]["outputs"]["agent_runs_dir"] = {
            "path": str(self.root / "out" / "agent_runs"),
            "no_overwrite": False,
        }
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-persist-123",
            project_root=str(self.root),
            config_path=str(self.root / "config.yaml"),
            input_overrides={"design_spec_path": str(self.design_csv)},
        )

        with patch("handlers.map.invoke_agent_with_schema_retry", side_effect=fake_invoke):
            result = run_map(config, ctx)

        self.assertEqual(result["status"], "completed")
        run_subdir = self.intermediate_dir / "run-persist-123"
        self.assertTrue(run_subdir.is_dir(), f"Expected run subdir: {run_subdir}")
        files = list(run_subdir.glob("map_*.json"))
        self.assertEqual(len(files), 2, f"Expected 2 map_*.json files in {run_subdir}, got {files}")
        all_mappings: dict[str, Any] = {}
        for f in files:
            data = json.loads(f.read_text(encoding="utf-8"))
            self.assertIn("mappings", data)
            all_mappings.update(data["mappings"])
        self.assertIn("A1", all_mappings)
        self.assertIn("A2", all_mappings)


class RunMapManualResolutionPersistenceTests(unittest.TestCase):
    """Tests for run-scoped manual resolution persistence in map."""

    def setUp(self) -> None:
        self.root = _TEST_DATA_DIR / "manual_resolution_block"
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "PROJECT_CONTEXT.md").write_text("# Test\n", encoding="utf-8")
        self.design_csv = self.root / "design_spec.csv"
        self.design_csv.write_text(
            "spec_id,subunit,title,mapped_code_symbols,index_status,assumptions,last_indexed_at\n"
            "A1,S1,Foo,,unmapped,,\n",
            encoding="utf-8",
        )
        (self.root / "out" / "backups" / "map").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def test_blocked_run_writes_run_scoped_resolution_artifacts(self) -> None:
        """When blocked, map writes stage JSON + resolutions.yaml under run-scoped manual_resolution/."""
        blocked_output = {
            "manual_resolution_items": [
                {
                    "item_id": "MR-MAP-1",
                    "title": "Ambiguous symbol mapping",
                    "question": "Which service should handle this spec?",
                    "options": [
                        {"option_id": "opt_a", "label": "ServiceA", "effect": "Map to ServiceA"},
                        {"option_id": "opt_b", "label": "ServiceB", "effect": "Map to ServiceB"},
                    ],
                    "required": True,
                    "blocking_reason": "Multiple candidates",
                }
            ],
            "mappings": {},
            "run_summary": {},
            "created_at": "2026-03-06T12:00:00Z",
        }
        config = _map_test_config(
            self.root,
            design_spec_path=self.design_csv,
            outputs={"agent_runs_dir": {"path": str(self.root / "out" / "agent_runs"), "no_overwrite": False}},
        )
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-map-block-1",
            project_root=str(self.root),
            config_path=str(self.root / "config.yaml"),
            input_overrides={"design_spec_path": str(self.design_csv)},
        )

        with patch("handlers.map.invoke_agent_with_schema_retry", return_value=blocked_output):
            result = run_map(config, ctx)

        self.assertEqual(result["status"], "blocked")
        run_dir = self.root / "out" / "agent_runs" / "map" / "run-map-block-1"
        self.assertTrue((run_dir / "manual_resolution" / "map.json").exists())
        self.assertTrue((run_dir / "manual_resolution" / "resolutions.yaml").exists())
        run_meta_path = run_dir / "run_meta.json"
        self.assertTrue(run_meta_path.exists())
        run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
        self.assertEqual(run_meta.get("blocked_at_stage"), "map")
        self.assertEqual(run_meta.get("resolution_status"), "pending")


class CodebaseContentProviderTests(unittest.TestCase):
    """Tests for codebase_content in map template vars by provider."""

    def setUp(self) -> None:
        """Create project root with a Python file for snapshot."""
        self.root = _TEST_DATA_DIR / "codebase_content"
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "PROJECT_CONTEXT.md").write_text("# Test\n", encoding="utf-8")
        (self.root / "src").mkdir(exist_ok=True)
        (self.root / "src" / "main.py").write_text(
            "def hello() -> str:\n    return 'hi'\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        """Remove test data."""
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def test_codebase_content_populated_when_provider_api(self) -> None:
        """When provider is api, codebase_content is non-empty (AST snapshot)."""
        config = _map_test_config(self.root)
        config["agent"] = {"provider": "api"}
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-api",
            project_root=str(self.root),
            config_path=str(self.root / "config.yaml"),
        )
        inputs = {"agent_view_content": "spec_id,title\nA1,Foo\n"}
        vars_ = build_template_vars(config, self.root, ctx, inputs)
        self.assertIn("codebase_content", vars_)
        content = vars_["codebase_content"]
        self.assertNotEqual(content, "")
        self.assertIn("# Codebase Snapshot", content)
        self.assertIn("main.py", content)

    def test_codebase_content_populated_when_provider_local(self) -> None:
        """When provider is local, codebase_content is non-empty (isolated temp workspace)."""
        config = _map_test_config(self.root)
        config["agent"] = {"provider": "local"}
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-local",
            project_root=str(self.root),
            config_path=str(self.root / "config.yaml"),
        )
        inputs = {"agent_view_content": "spec_id,title\nA1,Foo\n"}
        vars_ = build_template_vars(config, self.root, ctx, inputs)
        self.assertIn("codebase_content", vars_)
        content = vars_["codebase_content"]
        self.assertNotEqual(content, "")
        self.assertIn("# Codebase Snapshot", content)
        self.assertIn("main.py", content)

    def test_codebase_content_empty_when_provider_stub(self) -> None:
        """When provider is stub, codebase_content is empty."""
        config = _map_test_config(self.root)
        config["agent"] = {"provider": "stub"}
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-stub",
            project_root=str(self.root),
            config_path=str(self.root / "config.yaml"),
        )
        inputs = {"agent_view_content": "spec_id,title\nA1,Foo\n"}
        vars_ = build_template_vars(config, self.root, ctx, inputs)
        self.assertEqual(vars_.get("codebase_content", "MISSING"), "")

    def test_template_vars_include_run_scoped_resolution_path_and_decisions(self) -> None:
        """Template vars include run-scoped resolutions.yaml path and resume decisions text."""
        config = _map_test_config(self.root)
        config["commands"]["map"]["outputs"]["agent_runs_dir"] = {
            "path": str(self.root / "out" / "agent_runs"),
            "no_overwrite": False,
        }
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-template-1",
            project_root=str(self.root),
            config_path=str(self.root / "config.yaml"),
            resolved_decisions="## Resolved Decisions\n\n- [MR-1] Use API",
        )
        inputs = {"agent_view_content": "spec_id,title\nA1,Foo\n"}
        vars_ = build_template_vars(config, self.root, ctx, inputs)
        manual_path = Path(vars_["manual_resolution_file"])
        self.assertEqual(manual_path.name, "resolutions.yaml")
        self.assertIn("run-template-1", manual_path.parts)
        self.assertIn("manual_resolution", manual_path.parts)
        self.assertEqual(vars_["resolved_decisions"], "## Resolved Decisions\n\n- [MR-1] Use API")


if __name__ == "__main__":
    unittest.main()
