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
    validate_code_ref_paths,
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
                "map_run_id",
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

    def testvalidate_map_output_contract_notes_not_aliased_to_problems(self) -> None:
        """code_ref.notes is no longer aliased to problems; problems stays empty string."""
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
                            "notes": "Should be ignored.",
                        }
                    ],
                    "assumptions": "",
                }
            }
        }
        validate_map_output_contract(output)
        self.assertEqual(output["mappings"]["A1"]["code_refs"][0]["problems"], "")

    def testvalidate_map_output_contract_demotes_mapped_to_partial_below_threshold(self) -> None:
        """mapped status is demoted to partial when max confidence < min_remapping_confidence_threshold."""
        output = {
            "mappings": {
                "A1": {
                    "status": "mapped",
                    "code_refs": [
                        {"path": "src/Foo.cs", "symbol_name": "Foo", "symbol_type": "class", "confidence": 0.4},
                    ],
                    "assumptions": "",
                }
            }
        }
        validate_map_output_contract(output, min_remapping_confidence_threshold=0.7)
        self.assertEqual(output["mappings"]["A1"]["status"], "partial")

    def testvalidate_map_output_contract_no_demotion_above_threshold(self) -> None:
        """mapped status stays mapped when max confidence >= min_remapping_confidence_threshold."""
        output = {
            "mappings": {
                "A1": {
                    "status": "mapped",
                    "code_refs": [
                        {"path": "src/Foo.cs", "symbol_name": "Foo", "symbol_type": "class", "confidence": 0.9},
                    ],
                    "assumptions": "",
                }
            }
        }
        validate_map_output_contract(output, min_remapping_confidence_threshold=0.7)
        self.assertEqual(output["mappings"]["A1"]["status"], "mapped")

    def testvalidate_map_output_contract_no_demotion_of_partial(self) -> None:
        """partial status is never promoted or changed by threshold demotion pass."""
        output = {
            "mappings": {
                "A1": {
                    "status": "partial",
                    "code_refs": [
                        {"path": "src/Foo.cs", "symbol_name": "Foo", "symbol_type": "class", "confidence": 0.9},
                    ],
                    "assumptions": "",
                }
            }
        }
        validate_map_output_contract(output, min_remapping_confidence_threshold=0.5)
        self.assertEqual(output["mappings"]["A1"]["status"], "partial")


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
        self.assertIn("src/Foo.cs::Foo.DoFoo,src/Bar.cs::Bar.Helper", content)
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
        self.assertIn("src/Foo.cs::Foo.Bar,src/Baz.cs::Baz.Quux", content)
        self.assertIn("0.85,0.90", content)
        self.assertIn("0.70,0.95", content)
        self.assertIn("Semantics differ from spec.", content)

    def testtranslate_map_writes_map_run_id(self) -> None:
        """Translate writes run_id[:8] into map_run_id column."""
        root = _TEST_DATA_DIR / "test_run_id"
        root.mkdir(parents=True, exist_ok=True)
        design_csv = root / "design_spec.csv"
        design_csv.write_text(
            "spec_id,subunit,title,map_status,map_run_id\n"
            "A1,S1,Foo,unmapped,\n",
            encoding="utf-8",
        )
        (root / "out" / "backups").mkdir(parents=True, exist_ok=True)

        config = _map_test_config(root, design_spec_path=design_csv)
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="runabcdef1234",
            project_root=str(root),
            config_path=str(root / "config.yaml"),
        )
        output = {
            "mappings": {"A1": {"status": "mapped", "code_refs": [], "assumptions": ""}},
            "created_at": "2026-02-21T12:00:00Z",
        }
        inputs = {"design_spec_path": design_csv}

        translate_map(config, ctx, output, inputs)

        content = design_csv.read_text(encoding="utf-8")
        self.assertIn("runabcd", content)  # run_id[:8]

    def testtranslate_map_symbol_name_only_when_path_empty(self) -> None:
        """When code_ref has no path, only symbol_name is written (no :: prefix)."""
        root = _TEST_DATA_DIR / "test_no_path"
        root.mkdir(parents=True, exist_ok=True)
        design_csv = root / "design_spec.csv"
        design_csv.write_text(
            "spec_id,subunit,title,mapped_code_symbols,map_status\n"
            "A1,S1,Foo,,unmapped\n",
            encoding="utf-8",
        )
        (root / "out" / "backups").mkdir(parents=True, exist_ok=True)

        config = _map_test_config(root, design_spec_path=design_csv)
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-nopath",
            project_root=str(root),
            config_path=str(root / "config.yaml"),
        )
        output = {
            "mappings": {
                "A1": {
                    "status": "mapped",
                    "code_refs": [{"symbol_name": "MySymbol", "symbol_type": "function"}],
                    "assumptions": "",
                }
            },
            "created_at": "2026-02-21T12:00:00Z",
        }
        inputs = {"design_spec_path": design_csv}

        translate_map(config, ctx, output, inputs)

        content = design_csv.read_text(encoding="utf-8")
        self.assertIn("MySymbol", content)
        self.assertNotIn("::", content)

    def testtranslate_map_notes_field_not_written_to_problems(self) -> None:
        """code_ref.notes is ignored; only problems field populates mapped_problems."""
        root = _TEST_DATA_DIR / "test_notes_ignored"
        root.mkdir(parents=True, exist_ok=True)
        design_csv = root / "design_spec.csv"
        design_csv.write_text(
            "spec_id,subunit,title,mapped_code_symbols,mapped_problems,map_status\n"
            "A1,S1,Foo,,, unmapped\n",
            encoding="utf-8",
        )
        (root / "out" / "backups").mkdir(parents=True, exist_ok=True)

        config = _map_test_config(root, design_spec_path=design_csv)
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-notes",
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
                            "symbol_name": "Foo",
                            "symbol_type": "class",
                            "confidence": 0.5,
                            "notes": "legacy text",  # should be ignored
                        }
                    ],
                    "assumptions": "",
                }
            },
            "created_at": "2026-02-21T12:00:00Z",
        }
        inputs = {"design_spec_path": design_csv}

        translate_map(config, ctx, output, inputs)

        content = design_csv.read_text(encoding="utf-8")
        self.assertNotIn("legacy text", content)

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

    def test_filter_rows_includes_mapped_row_below_threshold(self) -> None:
        """Mapped row with max confidence below threshold is re-included for remapping."""
        headers = ["spec_id", "map_status", "mapped_confidence"]
        rows = [
            {"spec_id": "A1", "map_status": "mapped", "mapped_confidence": "0.4,0.3"},
            {"spec_id": "A2", "map_status": "unmapped", "mapped_confidence": ""},
        ]
        filtered = filter_rows_for_mapping(
            headers, rows, skip_mapped=True, min_remapping_confidence_threshold=0.7
        )
        spec_ids = [r["spec_id"] for r in filtered]
        self.assertIn("A1", spec_ids)
        self.assertIn("A2", spec_ids)

    def test_filter_rows_excludes_mapped_row_above_threshold(self) -> None:
        """Mapped row with max confidence at or above threshold is not re-included."""
        headers = ["spec_id", "map_status", "mapped_confidence"]
        rows = [
            {"spec_id": "A1", "map_status": "mapped", "mapped_confidence": "0.9"},
        ]
        filtered = filter_rows_for_mapping(
            headers, rows, skip_mapped=True, min_remapping_confidence_threshold=0.7
        )
        self.assertEqual(len(filtered), 0)

    def test_filter_rows_threshold_zero_disables_remapping_check(self) -> None:
        """threshold=0.0 (default) means mapped rows are always skipped when skip_mapped=True."""
        headers = ["spec_id", "map_status", "mapped_confidence"]
        rows = [
            {"spec_id": "A1", "map_status": "mapped", "mapped_confidence": "0.1"},
        ]
        filtered = filter_rows_for_mapping(
            headers, rows, skip_mapped=True, min_remapping_confidence_threshold=0.0
        )
        self.assertEqual(len(filtered), 0)

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

    def testmerge_subunit_results_aggregate_status_blocked_wins(self) -> None:
        """Aggregated run_summary status is blocked when any subunit is blocked."""
        batch_outputs = [
            {"mappings": {"A1": {}}, "manual_resolution_items": [], "run_summary": {"status": "success", "summary": "ok"}, "created_at": ""},
            {"mappings": {"A2": {}}, "manual_resolution_items": [], "run_summary": {"status": "blocked", "summary": "needs review"}, "created_at": ""},
        ]
        merged = merge_subunit_results(batch_outputs)
        self.assertEqual(merged["run_summary"]["status"], "blocked")

    def testmerge_subunit_results_aggregate_status_partial_wins_over_success(self) -> None:
        """Aggregated run_summary status is partial when partial and success subunits."""
        batch_outputs = [
            {"mappings": {"A1": {}}, "manual_resolution_items": [], "run_summary": {"status": "success", "summary": "ok"}, "created_at": ""},
            {"mappings": {"A2": {}}, "manual_resolution_items": [], "run_summary": {"status": "partial", "summary": "low conf"}, "created_at": ""},
        ]
        merged = merge_subunit_results(batch_outputs)
        self.assertEqual(merged["run_summary"]["status"], "partial")

    def testmerge_subunit_results_blocking_items_summed(self) -> None:
        """Aggregated run_summary sums blocking_items from all subunits."""
        batch_outputs = [
            {"mappings": {"A1": {}}, "manual_resolution_items": [], "run_summary": {"status": "partial", "blocking_items": 2}, "created_at": ""},
            {"mappings": {"A2": {}}, "manual_resolution_items": [], "run_summary": {"status": "partial", "blocking_items": 3}, "created_at": ""},
        ]
        merged = merge_subunit_results(batch_outputs)
        self.assertEqual(merged["run_summary"]["blocking_items"], 5)

    def testmerge_subunit_results_summary_joined_with_semicolon(self) -> None:
        """Aggregated run_summary.summary joins all non-empty summaries with '; '."""
        batch_outputs = [
            {"mappings": {"A1": {}}, "manual_resolution_items": [], "run_summary": {"status": "success", "summary": "part one"}, "created_at": ""},
            {"mappings": {"A2": {}}, "manual_resolution_items": [], "run_summary": {"status": "success", "summary": "part two"}, "created_at": ""},
        ]
        merged = merge_subunit_results(batch_outputs)
        self.assertIn("part one", merged["run_summary"]["summary"])
        self.assertIn("part two", merged["run_summary"]["summary"])
        self.assertIn("; ", merged["run_summary"]["summary"])


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


class ValidateCodeRefPathsTests(unittest.TestCase):
    """Tests for validate_code_ref_paths."""

    def setUp(self) -> None:
        self.tmp = _TEST_DATA_DIR / "code_ref_paths"
        self.tmp.mkdir(parents=True, exist_ok=True)
        (self.tmp / "src").mkdir(exist_ok=True)
        (self.tmp / "src" / "Foo.cs").write_text("// Foo", encoding="utf-8")

    def tearDown(self) -> None:
        if self.tmp.exists():
            shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_paths_exist_returns_empty_list(self) -> None:
        """No invalid entries when all code_ref paths exist under codebase_dir."""
        output = {
            "mappings": {
                "A1": {
                    "status": "mapped",
                    "code_refs": [{"path": "src/Foo.cs", "symbol_name": "Foo", "symbol_type": "class"}],
                    "assumptions": "",
                }
            }
        }
        result = validate_code_ref_paths(output, self.tmp)
        self.assertEqual(result, [])

    def test_missing_path_returns_entry(self) -> None:
        """Missing path returns entry with spec_id, path, symbol_name."""
        output = {
            "mappings": {
                "A1": {
                    "status": "mapped",
                    "code_refs": [{"path": "src/Missing.cs", "symbol_name": "Missing", "symbol_type": "class"}],
                    "assumptions": "",
                }
            }
        }
        result = validate_code_ref_paths(output, self.tmp)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["spec_id"], "A1")
        self.assertEqual(result[0]["path"], "src/Missing.cs")
        self.assertEqual(result[0]["symbol_name"], "Missing")

    def test_empty_path_is_skipped(self) -> None:
        """code_ref with empty path is silently skipped."""
        output = {
            "mappings": {
                "A1": {
                    "status": "partial",
                    "code_refs": [{"path": "", "symbol_name": "Foo", "symbol_type": "class"}],
                    "assumptions": "",
                }
            }
        }
        result = validate_code_ref_paths(output, self.tmp)
        self.assertEqual(result, [])

    def test_no_code_refs_returns_empty_list(self) -> None:
        """Mappings without code_refs return empty list."""
        output = {
            "mappings": {
                "A1": {"status": "unmapped", "code_refs": [], "assumptions": ""},
            }
        }
        result = validate_code_ref_paths(output, self.tmp)
        self.assertEqual(result, [])


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

    def test_apply_existing_outputs_latest_resolves_newest_dir(self) -> None:
        """apply_existing_outputs=latest resolves to most recently modified subdir."""
        intermediate_dir = self.root / "out" / "intermediate" / "map"
        older_dir = intermediate_dir / "run-older"
        newer_dir = intermediate_dir / "run-newer"
        older_dir.mkdir(parents=True, exist_ok=True)
        import time
        time.sleep(0.01)
        newer_dir.mkdir(parents=True, exist_ok=True)
        (newer_dir / "map_S1.json").write_text(
            json.dumps({
                "manual_resolution_items": [],
                "run_summary": {},
                "created_at": "2026-02-21T12:00:00Z",
                "mappings": {
                    "A1": {"status": "mapped", "code_refs": [], "assumptions": ""},
                    "A2": {"status": "unmapped", "code_refs": [], "assumptions": ""},
                },
            }),
            encoding="utf-8",
        )
        config = _map_test_config(
            self.root,
            design_spec_path=self.design_csv,
            outputs={
                "intermediate_map_dir": {"path": str(intermediate_dir), "no_overwrite": False},
                "agent_runs_dir": {"path": str(self.root / "out" / "agent_runs"), "no_overwrite": False},
            },
        )
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-latest",
            project_root=str(self.root),
            config_path=str(self.root / "config.yaml"),
            input_overrides={"design_spec_path": str(self.design_csv), "apply_existing_outputs": "latest"},
        )
        with patch("handlers.map.invoke_agent_with_schema_retry") as mock_invoke:
            result = run_map(config, ctx)
        mock_invoke.assert_not_called()
        self.assertEqual(result["status"], "completed")

    def test_apply_existing_outputs_latest_empty_returns_failed(self) -> None:
        """apply_existing_outputs=latest with no prior runs returns failed."""
        intermediate_dir = self.root / "out" / "intermediate" / "map"
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        config = _map_test_config(
            self.root,
            design_spec_path=self.design_csv,
            outputs={
                "intermediate_map_dir": {"path": str(intermediate_dir), "no_overwrite": False},
                "agent_runs_dir": {"path": str(self.root / "out" / "agent_runs"), "no_overwrite": False},
            },
        )
        ctx = RuntimeContext(
            command="map",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-latest-empty",
            project_root=str(self.root),
            config_path=str(self.root / "config.yaml"),
            input_overrides={"design_spec_path": str(self.design_csv), "apply_existing_outputs": "latest"},
        )
        result = run_map(config, ctx)
        self.assertEqual(result["status"], "failed")
        self.assertIn("no prior run directories", result["reason"])


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


class RunMapSubunitFilterAndBatchingTests(unittest.TestCase):
    """Tests for subunit_filter, max_specs_per_subunit, stats artifact, and per-subunit blocking."""

    def setUp(self) -> None:
        self.root = _TEST_DATA_DIR / "subunit_filter"
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "PROJECT_CONTEXT.md").write_text("# Test\n", encoding="utf-8")
        self.design_csv = self.root / "design_spec.csv"
        self.design_csv.write_text(
            "spec_id,subunit,title,mapped_code_symbols,map_status,map_assumptions,mapped_at\n"
            "A1,S1,Foo,,unmapped,,\n"
            "A2,S2,Bar,,unmapped,,\n"
            "A3,S3,Baz,,unmapped,,\n",
            encoding="utf-8",
        )
        (self.root / "out" / "backups" / "map").mkdir(parents=True, exist_ok=True)
        self.intermediate_dir = self.root / "out" / "intermediate" / "map"
        self.intermediate_dir.mkdir(parents=True, exist_ok=True)
        self.agent_runs_dir = self.root / "out" / "agent_runs"

    def tearDown(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def _base_config(self) -> dict[str, Any]:
        return _map_test_config(
            self.root,
            design_spec_path=self.design_csv,
            outputs={
                "intermediate_map_dir": {"path": str(self.intermediate_dir), "no_overwrite": False},
                "agent_runs_dir": {"path": str(self.agent_runs_dir), "no_overwrite": False},
            },
        )

    def _fake_invoke(self, spec_ids: list[str]) -> dict[str, Any]:
        """Return a stub output for given spec_ids."""
        return {
            "manual_resolution_items": [],
            "run_summary": {"status": "success"},
            "created_at": "2026-02-21T12:00:00Z",
            "mappings": {sid: {"status": "unmapped", "code_refs": [], "assumptions": ""} for sid in spec_ids},
        }

    def test_subunit_filter_processes_only_matching_subunits(self) -> None:
        """When subunit_filter is set, only those subunits are invoked."""
        config = self._base_config()
        invoked_csv: list[str] = []

        def fake_invoke(prompt_name: str, template_vars: dict, **kwargs: Any) -> dict:
            invoked_csv.append(template_vars.get("design_spec_rows_csv", ""))
            csv_content = template_vars.get("design_spec_rows_csv", "")
            spec_ids = [r.split(",")[0] for r in csv_content.strip().splitlines()[1:] if r.strip()]
            return self._fake_invoke(spec_ids)

        ctx = RuntimeContext(
            command="map", dry_run=False, verbose=False, command_only_validation=False,
            run_id="run-filter", project_root=str(self.root), config_path=str(self.root / "config.yaml"),
            input_overrides={"design_spec_path": str(self.design_csv), "subunit_filter": "S1"},
        )
        with patch("handlers.map.invoke_agent_with_schema_retry", side_effect=fake_invoke):
            result = run_map(config, ctx)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(invoked_csv), 1)
        self.assertIn("A1", invoked_csv[0])
        self.assertNotIn("A2", invoked_csv[0])

    def test_subunit_filter_no_match_returns_skipped(self) -> None:
        """When subunit_filter matches no subunit, result is skipped."""
        config = self._base_config()
        ctx = RuntimeContext(
            command="map", dry_run=False, verbose=False, command_only_validation=False,
            run_id="run-nofilt", project_root=str(self.root), config_path=str(self.root / "config.yaml"),
            input_overrides={"design_spec_path": str(self.design_csv), "subunit_filter": "NONEXISTENT"},
        )
        with patch("handlers.map.invoke_agent_with_schema_retry") as mock_invoke:
            result = run_map(config, ctx)
        mock_invoke.assert_not_called()
        self.assertEqual(result["status"], "skipped")
        self.assertIn("subunit_filter", result["reason"])

    def test_max_specs_per_subunit_splits_invocations(self) -> None:
        """max_specs_per_subunit splits large subunit into multiple agent invocations."""
        # Put 3 specs in same subunit
        self.design_csv.write_text(
            "spec_id,subunit,title,mapped_code_symbols,map_status,map_assumptions,mapped_at\n"
            "A1,S1,Foo,,unmapped,,\n"
            "A2,S1,Bar,,unmapped,,\n"
            "A3,S1,Baz,,unmapped,,\n",
            encoding="utf-8",
        )
        config = self._base_config()
        config["commands"]["map"]["max_specs_per_subunit"] = 2
        invocation_count: list[int] = []

        def fake_invoke(prompt_name: str, template_vars: dict, **kwargs: Any) -> dict:
            csv_content = template_vars.get("design_spec_rows_csv", "")
            spec_ids = [r.split(",")[0] for r in csv_content.strip().splitlines()[1:] if r.strip()]
            invocation_count.append(len(spec_ids))
            return self._fake_invoke(spec_ids)

        ctx = RuntimeContext(
            command="map", dry_run=False, verbose=False, command_only_validation=False,
            run_id="run-split", project_root=str(self.root), config_path=str(self.root / "config.yaml"),
            input_overrides={"design_spec_path": str(self.design_csv)},
        )
        with patch("handlers.map.invoke_agent_with_schema_retry", side_effect=fake_invoke):
            result = run_map(config, ctx)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(invocation_count), 2)
        self.assertLessEqual(max(invocation_count), 2)

    def test_stats_json_artifact_written(self) -> None:
        """After a successful map run, a stats JSON file is written to agent_runs/map/."""
        config = self._base_config()

        def fake_invoke(prompt_name: str, template_vars: dict, **kwargs: Any) -> dict:
            csv_content = template_vars.get("design_spec_rows_csv", "")
            spec_ids = [r.split(",")[0] for r in csv_content.strip().splitlines()[1:] if r.strip()]
            return self._fake_invoke(spec_ids)

        ctx = RuntimeContext(
            command="map", dry_run=False, verbose=False, command_only_validation=False,
            run_id="run-stats-123", project_root=str(self.root), config_path=str(self.root / "config.yaml"),
            input_overrides={"design_spec_path": str(self.design_csv)},
        )
        with patch("handlers.map.invoke_agent_with_schema_retry", side_effect=fake_invoke):
            result = run_map(config, ctx)

        self.assertIn(result["status"], ("completed", "partial"))
        stats_file = self.agent_runs_dir / "map" / "run-stats-123_stats.json"
        self.assertTrue(stats_file.exists(), f"Expected stats file: {stats_file}")
        stats = json.loads(stats_file.read_text(encoding="utf-8"))
        self.assertIn("total", stats)
        self.assertIn("mapped", stats)
        self.assertIn("run_id", stats)

    def test_partial_block_applies_clean_subunits(self) -> None:
        """When some subunits are blocked and some are clean, clean subunits are applied."""
        self.design_csv.write_text(
            "spec_id,subunit,title,mapped_code_symbols,map_status,map_assumptions,mapped_at\n"
            "A1,S1,Foo,,unmapped,,\n"
            "A2,S2,Bar,,unmapped,,\n",
            encoding="utf-8",
        )
        clean_output = {
            "manual_resolution_items": [],
            "run_summary": {"status": "success"},
            "created_at": "2026-02-21T12:00:00Z",
            "mappings": {"A1": {"status": "mapped", "code_refs": [], "assumptions": "clean"}},
        }
        blocked_output = {
            "manual_resolution_items": [
                {
                    "item_id": "MR-1", "title": "Ambiguous", "question": "Which?",
                    "options": [{"option_id": "a", "label": "A", "effect": "use A"}],
                    "required": True, "blocking_reason": "ambiguous",
                }
            ],
            "mappings": {},
            "run_summary": {"status": "blocked"},
            "created_at": "2026-02-21T12:00:00Z",
        }

        call_count = [0]

        def fake_invoke(prompt_name: str, template_vars: dict, **kwargs: Any) -> dict:
            csv_content = template_vars.get("design_spec_rows_csv", "")
            call_count[0] += 1
            if "A1" in csv_content:
                return clean_output
            return blocked_output

        config = self._base_config()
        ctx = RuntimeContext(
            command="map", dry_run=False, verbose=False, command_only_validation=False,
            run_id="run-partial-block", project_root=str(self.root), config_path=str(self.root / "config.yaml"),
            input_overrides={"design_spec_path": str(self.design_csv)},
        )
        with patch("handlers.map.invoke_agent_with_schema_retry", side_effect=fake_invoke):
            result = run_map(config, ctx)

        self.assertEqual(result["status"], "blocked")
        # Clean mappings were applied
        self.assertIn("clean_mappings_applied", result)
        self.assertGreater(result["clean_mappings_applied"], 0)
        # CSV updated for clean subunit
        content = self.design_csv.read_text(encoding="utf-8")
        self.assertIn("mapped", content)


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

    def test_codebase_content_empty_when_provider_local(self) -> None:
        """When provider is local, codebase_content is empty (model explores files directly)."""
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
        self.assertEqual(vars_.get("codebase_content", ""), "")

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
