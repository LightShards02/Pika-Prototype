"""Tests for implement execution patch collection safeguards."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.constants import ImplementStatus
from core.context import RuntimeContext
from handlers.implement.execution import (
    _apply_and_verify,
    _build_runtime_file_facts,
    _collect_and_copy_patches,
    _collect_spec_output,
    _execute_batch,
    _prepare_patch_files_for_apply,
)
from handlers.implement.helpers import _sha256
from handlers.implement.semantic_guard import (
    _cleanup_retry_diff_artifacts,
    _collect_output_diff_paths,
    build_batch_path_contract,
    default_verification_commands_for_batch,
    validate_implement_output_semantics,
)


def _new_file_diff(target: str, content: str) -> str:
    """Return a minimal unified diff that creates one file with one line."""
    return (
        f"diff --git a/{target} b/{target}\n"
        "new file mode 100644\n"
        "index 0000000..1111111\n"
        "--- /dev/null\n"
        f"+++ b/{target}\n"
        "@@ -0,0 +1 @@\n"
        f"+{content}\n"
    )


def _modify_file_diff(target: str, old: str, new: str) -> str:
    """Return a minimal unified diff that replaces one line in an existing file."""
    return (
        f"diff --git a/{target} b/{target}\n"
        f"--- a/{target}\n"
        f"+++ b/{target}\n"
        "@@ -1 +1 @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


class ImplementExecutionPatchCollectionTests(unittest.TestCase):
    """Regression tests for deterministic patch collection behavior."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-execution-"))
        self.patches_dir = self.tmp / "run" / "patches"
        self.patches_dir.mkdir(parents=True, exist_ok=True)
        self.paths = {"patches": self.patches_dir}
        self.constraints = {
            "forbidden_paths": [],
            "budgets_applied": {"max_files": 10, "max_lines_changed": 600},
        }

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_collect_and_copy_patches_deduplicates_identical_patch_payloads(self) -> None:
        """Identical patch artifacts referenced by multiple specs are copied/applied once."""
        shared = self.tmp / "artifacts" / "shared.diff"
        shared.parent.mkdir(parents=True, exist_ok=True)
        shared.write_text(_new_file_diff("DATA/infra/provider/adapter.py", "alpha"), encoding="utf-8")

        parsed = {
            "A1029": {
                "diffs": [
                    {
                        "diff_id": "A1029-provider-adapter",
                        "diff_path": str(shared.relative_to(self.tmp)),
                        "touched_files": ["DATA/infra/provider/adapter.py"],
                    }
                ]
            },
            "A1030": {
                "diffs": [
                    {
                        "diff_id": "A1030-provider-adapter",
                        "diff_path": str(shared.relative_to(self.tmp)),
                        "touched_files": ["DATA/infra/provider/adapter.py"],
                    }
                ]
            },
        }

        patch_paths, touched_files = _collect_and_copy_patches(
            self.tmp,
            self.paths,
            "B0",
            parsed,
            self.constraints,
        )

        self.assertEqual(len(patch_paths), 1)
        self.assertEqual(touched_files, ["DATA/infra/provider/adapter.py"])

    def test_collect_and_copy_patches_handles_same_diff_id_with_unique_suffix(self) -> None:
        """Distinct patch files with same diff_id are preserved without overwrite."""
        first = self.tmp / "artifacts" / "first.diff"
        second = self.tmp / "artifacts" / "second.diff"
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_text(_new_file_diff("DATA/infra/auth/a.py", "one"), encoding="utf-8")
        second.write_text(_new_file_diff("DATA/infra/auth/b.py", "two"), encoding="utf-8")

        parsed = {
            "A1040": {
                "diffs": [
                    {
                        "diff_id": "credential-repository",
                        "diff_path": str(first.relative_to(self.tmp)),
                        "touched_files": ["DATA/infra/auth/a.py"],
                    }
                ]
            },
            "A1041": {
                "diffs": [
                    {
                        "diff_id": "credential-repository",
                        "diff_path": str(second.relative_to(self.tmp)),
                        "touched_files": ["DATA/infra/auth/b.py"],
                    }
                ]
            },
        }

        patch_paths, _ = _collect_and_copy_patches(
            self.tmp,
            self.paths,
            "B0",
            parsed,
            self.constraints,
        )
        names = sorted(Path(path).name for path in patch_paths)

        self.assertEqual(
            names,
            ["B0_credential-repository.diff", "B0_credential-repository_2.diff"],
        )

    def test_collect_and_copy_patches_rejects_empty_diff_path(self) -> None:
        """Empty diff_path is rejected deterministically with ValueError."""
        parsed = {
            "A2001": {
                "diffs": [
                    {
                        "diff_id": "missing-diff-path",
                        "diff_path": "",
                        "touched_files": ["CORE/calc.py"],
                    }
                ]
            }
        }

        with self.assertRaisesRegex(ValueError, "Missing diff_path for A2001:missing-diff-path"):
            _collect_and_copy_patches(self.tmp, self.paths, "B0", parsed, self.constraints)

    def test_collect_and_copy_patches_rejects_non_file_diff_path(self) -> None:
        """Directory-valued diff_path is rejected before read/copy operations."""
        bad_dir = self.tmp / "artifacts" / "not-a-file"
        bad_dir.mkdir(parents=True, exist_ok=True)
        parsed = {
            "A2002": {
                "diffs": [
                    {
                        "diff_id": "directory-diff-path",
                        "diff_path": str(bad_dir.relative_to(self.tmp)),
                        "touched_files": ["CORE/calc.py"],
                    }
                ]
            }
        }

        with self.assertRaisesRegex(
            ValueError,
            "Missing diff_path for A2002:directory-diff-path",
        ):
            _collect_and_copy_patches(self.tmp, self.paths, "B0", parsed, self.constraints)


class ImplementExecutionHybridDiffPlanTests(unittest.TestCase):
    """Tests for hybrid implement output parsing (`diff_plan` + `diff_refs`)."""

    def test_collect_spec_output_resolves_diff_refs_from_diff_plan(self) -> None:
        output = {
            "run_summary": {"status": "success"},
            "diff_plan": [
                {
                    "diff_id": "D_B0_CALC",
                    "diff_path": "agent_artifacts/D_B0_CALC.diff",
                    "touched_files": ["CORE/src/nutrition/calculation_service.py"],
                    "verification_notes": "ok",
                    "owner_spec_id": "A1021",
                    "related_spec_ids": ["A1021", "A1022"],
                    "file_path": "CORE/src/nutrition/calculation_service.py",
                    "op": "create",
                }
            ],
            "A1021": {
                "summary": "A1021",
                "diff_refs": ["D_B0_CALC"],
                "mapped_classes_functions": [],
                "mapped_test_cases": [],
            },
            "A1022": {
                "summary": "A1022",
                "diff_refs": ["D_B0_CALC"],
                "mapped_classes_functions": [],
                "mapped_test_cases": [],
            },
        }

        parsed = _collect_spec_output(output)

        self.assertIn("A1021", parsed)
        self.assertIn("A1022", parsed)
        self.assertEqual(parsed["A1021"]["diffs"][0]["diff_id"], "D_B0_CALC")
        self.assertEqual(parsed["A1022"]["diffs"][0]["diff_id"], "D_B0_CALC")
        self.assertEqual(
            parsed["A1021"]["diffs"][0]["touched_files"],
            ["CORE/src/nutrition/calculation_service.py"],
        )

    def test_collect_spec_output_rejects_missing_diff_plan(self) -> None:
        output = {
            "run_summary": {"status": "success"},
            "A1041": {
                "summary": "A1041",
                "diff_refs": ["D1"],
                "mapped_classes_functions": [],
                "mapped_test_cases": [],
            },
        }

        with self.assertRaisesRegex(ValueError, "diff_plan must not be empty"):
            _collect_spec_output(output)

    def test_collect_spec_output_rejects_unknown_diff_ref(self) -> None:
        output = {
            "run_summary": {"status": "success"},
            "diff_plan": [
                {
                    "diff_id": "D1",
                    "diff_path": "agent_artifacts/D1.diff",
                    "touched_files": ["CORE/src/nutrition/calculation_service.py"],
                    "owner_spec_id": "A1021",
                    "related_spec_ids": ["A1021"],
                    "file_path": "CORE/src/nutrition/calculation_service.py",
                    "op": "create",
                }
            ],
            "A1021": {
                "summary": "A1021",
                "diff_refs": ["D_UNKNOWN"],
                "mapped_classes_functions": [],
                "mapped_test_cases": [],
            },
        }

        with self.assertRaisesRegex(ValueError, "references unknown diff_id"):
            _collect_spec_output(output)


class ImplementExecutionSemanticNormalizationTests(unittest.TestCase):
    """Regression tests for create-on-existing patch normalization."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-semantic-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "init"],
            cwd=str(self.repo),
            check=True,
            capture_output=True,
            text=True,
        )
        self.verification = self.tmp / "verification"
        self.verification.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prepare_patch_files_skips_idempotent_new_file_mode_for_existing_file(self) -> None:
        target = self.repo / "workspace" / "shared-contracts" / "login_request.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{\"a\":1}\n", encoding="utf-8")

        patch = self.tmp / "create_login_request.diff"
        patch.write_text(
            _new_file_diff("workspace/shared-contracts/login_request.json", "{\"a\":1}"),
            encoding="utf-8",
        )

        result = _prepare_patch_files_for_apply(
            self.repo,
            "B1",
            [str(patch)],
            self.verification,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["patch_files"], [])
        kinds = [r.get("kind") for r in result.get("records", [])]
        self.assertIn("patch_already_applied_skip", kinds)

    def test_prepare_patch_files_rewrites_new_file_mode_for_existing_file(self) -> None:
        target = self.repo / "workspace" / "shared-contracts" / "login_request.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{\"a\":1}\n", encoding="utf-8")

        patch = self.tmp / "rewrite_login_request.diff"
        patch.write_text(
            _new_file_diff("workspace/shared-contracts/login_request.json", "{\"a\":2}"),
            encoding="utf-8",
        )

        result = _prepare_patch_files_for_apply(
            self.repo,
            "B1",
            [str(patch)],
            self.verification,
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(result["patch_files"]), 1)
        rewritten = result["patch_files"][0]
        check = subprocess.run(
            ["git", "-C", str(self.repo), "apply", "--check", rewritten],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(check.returncode, 0, msg=check.stderr)
        apply_proc = subprocess.run(
            ["git", "-C", str(self.repo), "apply", rewritten],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(apply_proc.returncode, 0, msg=apply_proc.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "{\"a\":2}\n")
        kinds = [r.get("kind") for r in result.get("records", [])]
        self.assertIn("patch_create_to_modify_rewrite", kinds)

    def test_prepare_patch_files_normalizes_malformed_hunk_counts(self) -> None:
        patch = self.tmp / "bad_hunk_count.diff"
        patch.write_text(
            (
                "diff --git a/workspace/shared-contracts/login_request.json "
                "b/workspace/shared-contracts/login_request.json\n"
                "new file mode 100644\n"
                "index 0000000..1111111\n"
                "--- /dev/null\n"
                "+++ b/workspace/shared-contracts/login_request.json\n"
                "@@ -0,0 +1,2 @@\n"
                "+{\"a\":1}\n"
            ),
            encoding="utf-8",
        )

        result = _prepare_patch_files_for_apply(
            self.repo,
            "B1",
            [str(patch)],
            self.verification,
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(result["patch_files"]), 1)
        prepared_patch = result["patch_files"][0]
        kinds = [r.get("kind") for r in result.get("records", [])]
        self.assertIn("patch_hunk_header_normalized", kinds)

        check = subprocess.run(
            ["git", "-C", str(self.repo), "apply", "--check", prepared_patch],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(check.returncode, 0, msg=check.stderr)
        apply_proc = subprocess.run(
            ["git", "-C", str(self.repo), "apply", prepared_patch],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(apply_proc.returncode, 0, msg=apply_proc.stderr)
        created = self.repo / "workspace" / "shared-contracts" / "login_request.json"
        self.assertTrue(created.exists())
        self.assertEqual(created.read_text(encoding="utf-8"), "{\"a\":1}\n")

    def test_prepare_patch_files_adds_terminal_newline_to_patch_payload(self) -> None:
        patch = self.tmp / "missing_terminal_newline.diff"
        with patch.open("wb") as handle:
            handle.write(
                (
                    "--- /dev/null\n"
                    "+++ b/workspace/shared-contracts/login_request.json\n"
                    "@@ -0,0 +1,1 @@\n"
                    "+{\"a\":1}"
                ).encode("utf-8")
            )

        result = _prepare_patch_files_for_apply(
            self.repo,
            "B1",
            [str(patch)],
            self.verification,
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(result["patch_files"]), 1)
        prepared_patch = result["patch_files"][0]
        kinds = [r.get("kind") for r in result.get("records", [])]
        self.assertIn("patch_trailing_newline_added", kinds)

        prepared_bytes = Path(prepared_patch).read_bytes()
        self.assertTrue(prepared_bytes.endswith(b"\n"))

        check = subprocess.run(
            ["git", "-C", str(self.repo), "apply", "--check", prepared_patch],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(check.returncode, 0, msg=check.stderr)

    def test_prepare_patch_files_rewrites_implicit_create_patch_for_missing_target(self) -> None:
        patch = self.tmp / "implicit_create.diff"
        patch.write_text(
            (
                "diff --git a/CORE/tests/test_domain_policies.py b/CORE/tests/test_domain_policies.py\n"
                "--- a/CORE/tests/test_domain_policies.py\n"
                "+++ b/CORE/tests/test_domain_policies.py\n"
                "@@ -0,0 +1,2 @@\n"
                "+import pytest\n"
                "+\n"
            ),
            encoding="utf-8",
        )

        result = _prepare_patch_files_for_apply(
            self.repo,
            "B1",
            [str(patch)],
            self.verification,
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(result["patch_files"]), 1)
        prepared_patch = result["patch_files"][0]
        kinds = [r.get("kind") for r in result.get("records", [])]
        self.assertIn("patch_implicit_create_rewrite", kinds)

        check = subprocess.run(
            ["git", "-C", str(self.repo), "apply", "--check", prepared_patch],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(check.returncode, 0, msg=check.stderr)
        apply_proc = subprocess.run(
            ["git", "-C", str(self.repo), "apply", prepared_patch],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(apply_proc.returncode, 0, msg=apply_proc.stderr)
        created = self.repo / "CORE" / "tests" / "test_domain_policies.py"
        self.assertTrue(created.exists())
        self.assertEqual(created.read_text(encoding="utf-8"), "import pytest\n\n")

    def test_prepare_patch_files_splits_concatenated_hunk_markers(self) -> None:
        target = self.repo / "CORE" / "tests" / "test_domain_policies.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("assert old\n", encoding="utf-8")

        patch = self.tmp / "concatenated_hunk.diff"
        patch.write_text(
            (
                "diff --git a/CORE/tests/test_domain_policies.py b/CORE/tests/test_domain_policies.py\n"
                "--- a/CORE/tests/test_domain_policies.py\n"
                "+++ b/CORE/tests/test_domain_policies.py\n"
                "@@ -1,1 +1,2 @@\n"
                "-assert old+def test_new_policy():\n"
                "+    assert True\n"
            ),
            encoding="utf-8",
        )

        result = _prepare_patch_files_for_apply(
            self.repo,
            "B1",
            [str(patch)],
            self.verification,
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(result["patch_files"]), 1)
        prepared_patch = result["patch_files"][0]
        kinds = [r.get("kind") for r in result.get("records", [])]
        self.assertIn("patch_hunk_line_split", kinds)

        check = subprocess.run(
            ["git", "-C", str(self.repo), "apply", "--check", prepared_patch],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(check.returncode, 0, msg=check.stderr)
        apply_proc = subprocess.run(
            ["git", "-C", str(self.repo), "apply", prepared_patch],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(apply_proc.returncode, 0, msg=apply_proc.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "def test_new_policy():\n    assert True\n")

    def test_prepare_patch_files_rejects_binary_new_file_mode_rewrite(self) -> None:
        target = self.repo / "workspace" / "shared-contracts" / "login_request.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{\"a\":1}\n", encoding="utf-8")

        patch = self.tmp / "binary_create.diff"
        patch.write_text(
            (
                "diff --git a/workspace/shared-contracts/login_request.json "
                "b/workspace/shared-contracts/login_request.json\n"
                "new file mode 100644\n"
                "index 0000000..1111111\n"
                "GIT binary patch\n"
            ),
            encoding="utf-8",
        )

        result = _prepare_patch_files_for_apply(
            self.repo,
            "B1",
            [str(patch)],
            self.verification,
        )

        self.assertFalse(result["success"])
        kinds = [r.get("kind") for r in result.get("records", [])]
        self.assertIn("patch_semantic_conflict", kinds)


class ImplementExecutionHybridSemanticGuardTests(unittest.TestCase):
    """Tests for semantic guard behavior with hybrid diff_plan outputs."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-hybrid-semantic-"))
        (self.tmp / "CORE" / "src" / "nutrition").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_validate_implement_output_semantics_accepts_diff_refs_when_paths_allowed(self) -> None:
        contract = {
            "allowed_prefixes": ["CORE/"],
            "allowed_exact_paths": [],
            "forbidden_path_prefixes": [],
        }
        diff_path = self.tmp / "agent_artifacts" / "D1.diff"
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(
            "\n".join(
                [
                    "--- a/CORE/src/nutrition/calculation_service.py",
                    "+++ b/CORE/src/nutrition/calculation_service.py",
                    "@@ -0,0 +1,1 @@",
                    "+VALUE = 1",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        output = {
            "run_summary": {"status": "success"},
            "diff_plan": [
                {
                    "diff_id": "D1",
                    "diff_path": "agent_artifacts/D1.diff",
                    "touched_files": ["CORE/src/nutrition/calculation_service.py"],
                    "owner_spec_id": "A1021",
                    "related_spec_ids": ["A1021", "A1022"],
                    "file_path": "CORE/src/nutrition/calculation_service.py",
                    "op": "create",
                }
            ],
            "A1021": {
                "summary": "x",
                "diff_refs": ["D1"],
                "mapped_classes_functions": [
                    {
                        "kind": "class",
                        "qualified_name": "NutritionCalculationService",
                        "file_path": "CORE/src/nutrition/calculation_service.py",
                    }
                ],
                "mapped_test_cases": [],
            },
        }

        violations = validate_implement_output_semantics(output, contract, self.tmp)
        self.assertEqual(violations, [])

    def test_validate_implement_output_semantics_rejects_unknown_diff_ref(self) -> None:
        contract = {
            "allowed_prefixes": ["CORE/"],
            "allowed_exact_paths": [],
            "forbidden_path_prefixes": [],
        }
        output = {
            "run_summary": {"status": "success"},
            "diff_plan": [
                {
                    "diff_id": "D1",
                    "diff_path": "agent_artifacts/D1.diff",
                    "touched_files": ["CORE/src/nutrition/calculation_service.py"],
                    "owner_spec_id": "A1021",
                    "related_spec_ids": ["A1021"],
                    "file_path": "CORE/src/nutrition/calculation_service.py",
                    "op": "create",
                }
            ],
            "A1021": {
                "summary": "x",
                "diff_refs": ["D_UNKNOWN"],
                "mapped_classes_functions": [],
                "mapped_test_cases": [],
            },
        }

        violations = validate_implement_output_semantics(output, contract, self.tmp)
        self.assertTrue(any("unknown diff_id" in v for v in violations))

    def test_validate_implement_output_semantics_rejects_invalid_hunk_header(self) -> None:
        contract = {
            "allowed_prefixes": ["CORE/"],
            "allowed_exact_paths": [],
            "forbidden_path_prefixes": [],
        }
        diff_path = self.tmp / "agent_artifacts" / "D1.diff"
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(
            "\n".join(
                [
                    "--- a/CORE/src/nutrition/calculation_service.py",
                    "+++ b/CORE/src/nutrition/calculation_service.py",
                    "@@",
                    "+VALUE = 1",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        output = {
            "run_summary": {"status": "success"},
            "diff_plan": [
                {
                    "diff_id": "D1",
                    "diff_path": "agent_artifacts/D1.diff",
                    "touched_files": ["CORE/src/nutrition/calculation_service.py"],
                    "owner_spec_id": "A1021",
                    "related_spec_ids": ["A1021"],
                    "file_path": "CORE/src/nutrition/calculation_service.py",
                    "op": "modify",
                }
            ],
            "A1021": {
                "summary": "x",
                "diff_refs": ["D1"],
                "mapped_classes_functions": [],
                "mapped_test_cases": [],
            },
        }

        violations = validate_implement_output_semantics(output, contract, self.tmp)
        self.assertTrue(any("invalid patch" in v and "invalid hunk header" in v for v in violations))


class ImplementExecutionPatchApplySemanticGuardTests(unittest.TestCase):
    """Tests for git-apply semantic validation in implement output guard."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-apply-semantic-"))
        self.repo = self.tmp / "repo"
        target = self.repo / "src" / "CORE" / "tests"
        target.mkdir(parents=True, exist_ok=True)
        (target / "test_domain_logic.py").write_text("a\nb\n", encoding="utf-8")
        subprocess.run(
            ["git", "init"],
            cwd=str(self.repo),
            capture_output=True,
            text=True,
            check=True,
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_semantic_guard_rejects_non_applicable_patch(self) -> None:
        """Patch that cannot apply to current file context is rejected in semantic validation."""
        diff_path = self.repo / "agent_artifacts" / "D1.diff"
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(
            "\n".join(
                [
                    "--- a/CORE/tests/test_domain_logic.py",
                    "+++ b/CORE/tests/test_domain_logic.py",
                    "@@ -1,2 +1,2 @@",
                    " a",
                    "-c",
                    "+d",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        output = {
            "run_summary": {"status": "success"},
            "diff_plan": [
                {
                    "diff_id": "D1",
                    "diff_path": str(diff_path.relative_to(self.repo)),
                    "touched_files": ["CORE/tests/test_domain_logic.py"],
                    "owner_spec_id": "A1021",
                    "related_spec_ids": ["A1021"],
                    "file_path": "CORE/tests/test_domain_logic.py",
                    "op": "modify",
                }
            ],
            "A1021": {
                "summary": "x",
                "diff_refs": ["D1"],
                "mapped_classes_functions": [],
                "mapped_test_cases": [],
            },
        }
        contract = {
            "allowed_prefixes": ["CORE/"],
            "allowed_exact_paths": [],
            "forbidden_path_prefixes": [],
        }

        violations = validate_implement_output_semantics(
            output,
            contract,
            self.repo,
            codebase_prefix_rel="src",
        )
        self.assertTrue(any("git apply --check failed" in v for v in violations))

    def test_semantic_guard_accepts_patch_when_change_is_already_applied(self) -> None:
        """Patch already reflected in current files passes semantic validation."""
        diff_path = self.repo / "agent_artifacts" / "D1_applied.diff"
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(
            "\n".join(
                [
                    "--- a/CORE/tests/test_domain_logic.py",
                    "+++ b/CORE/tests/test_domain_logic.py",
                    "@@ -1,2 +1,2 @@",
                    " a",
                    "-b",
                    "+c",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        apply_proc = subprocess.run(
            ["git", "-C", str(self.repo), "apply", "--directory", "src", str(diff_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(apply_proc.returncode, 0, msg=apply_proc.stderr)

        output = {
            "run_summary": {"status": "success"},
            "diff_plan": [
                {
                    "diff_id": "D1",
                    "diff_path": str(diff_path.relative_to(self.repo)),
                    "touched_files": ["CORE/tests/test_domain_logic.py"],
                    "owner_spec_id": "A1021",
                    "related_spec_ids": ["A1021"],
                    "file_path": "CORE/tests/test_domain_logic.py",
                    "op": "modify",
                }
            ],
            "A1021": {
                "summary": "x",
                "diff_refs": ["D1"],
                "mapped_classes_functions": [],
                "mapped_test_cases": [],
            },
        }
        contract = {
            "allowed_prefixes": ["CORE/"],
            "allowed_exact_paths": [],
            "forbidden_path_prefixes": [],
        }

        violations = validate_implement_output_semantics(
            output,
            contract,
            self.repo,
            codebase_prefix_rel="src",
        )
        self.assertEqual(violations, [])

    def test_semantic_guard_accepts_whitespace_only_context_mismatch(self) -> None:
        """Whitespace-only context mismatches pass via --ignore-space-change fallback."""
        target = self.repo / "src" / "CORE" / "tests" / "test_whitespace.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_tab_indent():\n\treturn 1\n", encoding="utf-8")

        diff_path = self.repo / "agent_artifacts" / "D_ws.diff"
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(
            "\n".join(
                [
                    "--- a/CORE/tests/test_whitespace.py",
                    "+++ b/CORE/tests/test_whitespace.py",
                    "@@ -1,2 +1,3 @@",
                    " def test_tab_indent():",
                    "-    return 1",
                    "+\treturn 1",
                    "+    return 2",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        output = {
            "run_summary": {"status": "success"},
            "diff_plan": [
                {
                    "diff_id": "D_ws",
                    "diff_path": str(diff_path.relative_to(self.repo)),
                    "touched_files": ["CORE/tests/test_whitespace.py"],
                    "owner_spec_id": "A1021",
                    "related_spec_ids": ["A1021"],
                    "file_path": "CORE/tests/test_whitespace.py",
                    "op": "modify",
                }
            ],
            "A1021": {
                "summary": "x",
                "diff_refs": ["D_ws"],
                "mapped_classes_functions": [],
                "mapped_test_cases": [],
            },
        }
        contract = {
            "allowed_prefixes": ["CORE/"],
            "allowed_exact_paths": [],
            "forbidden_path_prefixes": [],
        }

        violations = validate_implement_output_semantics(
            output,
            contract,
            self.repo,
            codebase_prefix_rel="src",
        )
        self.assertEqual(violations, [])

    def test_semantic_guard_normalizes_blank_context_hunk_mismatch(self) -> None:
        """Whitespace-only context drift is normalized before semantic apply check."""
        target = self.repo / "src" / "SHARED" / "tests" / "test_contract_schemas.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "import json",
                    "from pathlib import Path",
                    "",
                    "",
                    "def _load_schema(file_name: str) -> dict:",
                    "    return {}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        diff_path = self.repo / "agent_artifacts" / "D1_blank_context.diff"
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        original_patch = "\n".join(
            [
                "--- a/SHARED/tests/test_contract_schemas.py",
                "+++ b/SHARED/tests/test_contract_schemas.py",
                "@@ -3,6 +3,7 @@",
                " import json",
                " from pathlib import Path",
                " ",
                " ",
                " ",
                "+from SHARED.contracts.auth_contracts import LoginRequestDTO",
                " def _load_schema(file_name: str) -> dict:",
                "",
            ]
        )
        diff_path.write_text(original_patch, encoding="utf-8")

        output = {
            "run_summary": {"status": "success"},
            "diff_plan": [
                {
                    "diff_id": "D1",
                    "diff_path": str(diff_path.relative_to(self.repo)),
                    "touched_files": ["SHARED/tests/test_contract_schemas.py"],
                    "owner_spec_id": "A1027",
                    "related_spec_ids": ["A1027"],
                    "file_path": "SHARED/tests/test_contract_schemas.py",
                    "op": "modify",
                }
            ],
            "A1027": {
                "summary": "x",
                "diff_refs": ["D1"],
                "mapped_classes_functions": [],
                "mapped_test_cases": [],
            },
        }
        contract = {
            "allowed_prefixes": ["SHARED/"],
            "allowed_exact_paths": [],
            "forbidden_path_prefixes": [],
        }

        violations = validate_implement_output_semantics(
            output,
            contract,
            self.repo,
            codebase_prefix_rel="src",
        )
        self.assertEqual(violations, [])

        normalized_patch = diff_path.read_text(encoding="utf-8")
        self.assertNotEqual(normalized_patch, original_patch)
        self.assertIn("+from SHARED.contracts.auth_contracts import LoginRequestDTO", normalized_patch)
        check = subprocess.run(
            ["git", "-C", str(self.repo), "apply", "--check", "--directory", "src", str(diff_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(check.returncode, 0, msg=check.stderr)

    def test_semantic_guard_accepts_applicable_patch(self) -> None:
        """Patch applicable under codebase prefix passes semantic validation."""
        diff_path = self.repo / "agent_artifacts" / "D1_valid.diff"
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_text(
            "\n".join(
                [
                    "--- a/CORE/tests/test_domain_logic.py",
                    "+++ b/CORE/tests/test_domain_logic.py",
                    "@@ -1,2 +1,2 @@",
                    " a",
                    "-b",
                    "+c",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        output = {
            "run_summary": {"status": "success"},
            "diff_plan": [
                {
                    "diff_id": "D1",
                    "diff_path": str(diff_path.relative_to(self.repo)),
                    "touched_files": ["CORE/tests/test_domain_logic.py"],
                    "owner_spec_id": "A1021",
                    "related_spec_ids": ["A1021"],
                    "file_path": "CORE/tests/test_domain_logic.py",
                    "op": "modify",
                }
            ],
            "A1021": {
                "summary": "x",
                "diff_refs": ["D1"],
                "mapped_classes_functions": [],
                "mapped_test_cases": [],
            },
        }
        contract = {
            "allowed_prefixes": ["CORE/"],
            "allowed_exact_paths": [],
            "forbidden_path_prefixes": [],
        }

        violations = validate_implement_output_semantics(
            output,
            contract,
            self.repo,
            codebase_prefix_rel="src",
        )
        self.assertEqual(violations, [])


class ImplementExecutionSemanticRetryHelpersTests(unittest.TestCase):
    """Tests for semantic retry helper utilities."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-semantic-retry-"))
        self.artifacts = self.tmp / "artifacts"
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_collect_output_diff_paths_deduplicates_across_locations(self) -> None:
        output = {
            "run_summary": {"status": "partial"},
            "diff_plan": [
                {"diff_id": "D1", "diff_path": "artifacts/a.diff"},
                {"diff_id": "D2", "diff_path": "artifacts/b.diff"},
                {"diff_id": "D3", "diff_path": "artifacts/a.diff"},
            ],
        }
        paths = _collect_output_diff_paths(output)
        self.assertEqual(paths, ["artifacts/a.diff", "artifacts/b.diff"])

    def test_cleanup_retry_diff_artifacts_removes_only_inside_artifacts_dir(self) -> None:
        inside = self.artifacts / "inside.diff"
        inside.write_text("x", encoding="utf-8")
        outside = self.tmp / "outside.diff"
        outside.write_text("x", encoding="utf-8")

        output = {
            "run_summary": {"status": "partial"},
            "diff_plan": [
                {"diff_id": "D1", "diff_path": str(inside)},
                {"diff_id": "D2", "diff_path": str(outside)},
            ],
        }
        removed = _cleanup_retry_diff_artifacts(
            output,
            {"agent_artifacts_dir": str(self.artifacts)},
        )
        self.assertEqual(removed, 1)
        self.assertFalse(inside.exists())
        self.assertTrue(outside.exists())


class ImplementExecutionLocalWorkspaceTests(unittest.TestCase):
    """Tests for local shared-workspace behavior in batch execution."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-local-workspace-"))
        self.codebase = self.tmp / "workspace_src"
        self.codebase.mkdir(parents=True, exist_ok=True)
        (self.codebase / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.shared_workspace = self.tmp / "shared_workspace"
        self.shared_workspace.mkdir(parents=True, exist_ok=True)
        self.schema_path = self.tmp / "schema.json"
        self.schema_path.write_text('{"type":"object"}', encoding="utf-8")
        self.paths = {
            "run": self.tmp / "run",
            "manual": self.tmp / "run" / "manual_resolution",
            "agent_outputs": self.tmp / "run" / "agent_outputs",
            "patches": self.tmp / "run" / "patches",
            "verification": self.tmp / "run" / "verification",
            "trace": self.tmp / "run" / "trace",
        }
        for path in self.paths.values():
            path.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_execute_batch_local_workspace_override_sets_prompt_codebase_dir(self) -> None:
        """Batch execution uses mirrored workspace path in prompt vars for local provider."""
        config = {
            "agent": {"provider": "local", "schema_validation_retries": 0},
            "project": {"name": "test", "root_dir": "."},

            "commands": {
                "implement": {
                    "inputs": {"codebase_dir": str(self.codebase)},
                    "outputs": {
                        "agent_artifacts_dir": {"path": str(self.tmp / "artifacts"), "no_overwrite": False},
                    },
                }
            },
            "outputs": {
                "agent_artifacts_dir": {"path": str(self.tmp / "artifacts"), "no_overwrite": False},
                "agent_runs_dir": {"path": str(self.tmp / "runs"), "no_overwrite": False},
            },
        }
        ctx = RuntimeContext(
            command="implement",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-local-batch-1",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
        )
        impl = {"prompt_name": "implement_from_specs"}
        brief = {
            "batch_id": "B0",
            "spec_rows": [{"spec_id": "A1", "module_tag": "CORE", "module_role": "domain"}],
            "constraints": {},
            "planned_anchors": [{"planned_file_path": "module.py"}],
            "shared_contracts": [],
        }

        captured: dict[str, object] = {}

        def fake_invoke(*args: object, **kwargs: object) -> dict[str, object]:
            captured["template_vars"] = kwargs.get("template_vars")
            captured["local_workspace_override"] = kwargs.get("local_workspace_override")
            return {
                "manual_resolution_items": [
                    {
                        "item_id": "MR-LOCAL-1",
                        "title": "Need clarification",
                        "question": "Which branch?",
                        "options": [{"option_id": "opt1", "label": "main", "effect": "Use main"}],
                        "required": True,
                        "blocking_reason": "Ambiguous branch",
                    }
                ]
            }

        with patch("handlers.implement.execution.invoke_with_semantic_retry", side_effect=fake_invoke):
            with patch("handlers.implement.execution.sync_local_agent_workspace") as mock_sync:
                result = _execute_batch(
                    config=config,
                    ctx=ctx,
                    impl=impl,
                    schema_path=self.schema_path,
                    root=self.tmp,
                    context_text="context",
                    paths=self.paths,
                    design_headers=["spec_id", "module_tag", "module_role"],
                    brief=brief,
                    completed_stages=["load"],
                    local_workspace_override=self.shared_workspace,
                )
                mock_sync.assert_called_once_with(self.codebase.resolve(), self.shared_workspace)

        self.assertEqual(result["status"], ImplementStatus.BLOCKED)
        self.assertEqual(captured["local_workspace_override"], self.shared_workspace)
        template_vars = captured.get("template_vars")
        self.assertIsInstance(template_vars, dict)
        assert isinstance(template_vars, dict)
        self.assertEqual(template_vars.get("codebase_dir"), str(self.shared_workspace.resolve()))
        artifacts_dir = Path(str(template_vars.get("agent_artifacts_dir", "")))
        self.assertEqual(artifacts_dir.name, "B0")
        self.assertEqual(artifacts_dir.parent.name, "run-local-batch-1")
        self.assertEqual(artifacts_dir.parent.parent.name, "implement")

    def test_execute_batch_retry_hook_resyncs_workspace_and_refreshes_prompt_state(self) -> None:
        """Semantic retry pre-attempt hook resyncs local workspace on retry attempts."""
        config = {
            "agent": {"provider": "local", "schema_validation_retries": 0},
            "project": {"name": "test", "root_dir": "."},

            "commands": {
                "implement": {
                    "inputs": {"codebase_dir": str(self.codebase)},
                    "outputs": {
                        "agent_artifacts_dir": {"path": str(self.tmp / "artifacts"), "no_overwrite": False},
                    },
                }
            },
            "outputs": {
                "agent_artifacts_dir": {"path": str(self.tmp / "artifacts"), "no_overwrite": False},
                "agent_runs_dir": {"path": str(self.tmp / "runs"), "no_overwrite": False},
            },
        }
        ctx = RuntimeContext(
            command="implement",
            dry_run=False,
            verbose=False,
            command_only_validation=False,
            run_id="run-local-batch-2",
            project_root=str(self.tmp),
            config_path=str(self.tmp / "config.yaml"),
        )
        impl = {"prompt_name": "implement_from_specs"}
        brief = {
            "batch_id": "B0",
            "spec_rows": [{"spec_id": "A1", "module_tag": "CORE", "module_role": "domain"}],
            "constraints": {},
            "planned_anchors": [{"planned_file_path": "CORE/module.py"}],
            "shared_contracts": [],
        }

        captured: dict[str, object] = {}

        def fake_invoke(*args: object, **kwargs: object) -> dict[str, object]:
            pre_attempt_hook = kwargs.get("pre_attempt_hook")
            template_vars = kwargs.get("template_vars")
            captured["template_vars"] = template_vars
            if callable(pre_attempt_hook) and isinstance(template_vars, dict):
                pre_attempt_hook(2, template_vars)
            return {
                "manual_resolution_items": [
                    {
                        "item_id": "MR-LOCAL-2",
                        "title": "Need clarification",
                        "question": "Which branch?",
                        "options": [{"option_id": "opt1", "label": "main", "effect": "Use main"}],
                        "required": True,
                        "blocking_reason": "Ambiguous branch",
                    }
                ]
            }

        with patch("handlers.implement.execution.invoke_with_semantic_retry", side_effect=fake_invoke):
            with patch("handlers.implement.execution.sync_local_agent_workspace") as mock_sync:
                result = _execute_batch(
                    config=config,
                    ctx=ctx,
                    impl=impl,
                    schema_path=self.schema_path,
                    root=self.tmp,
                    context_text="context",
                    paths=self.paths,
                    design_headers=["spec_id", "module_tag", "module_role"],
                    brief=brief,
                    completed_stages=["load"],
                    local_workspace_override=self.shared_workspace,
                )
                self.assertEqual(mock_sync.call_count, 2)

        self.assertEqual(result["status"], ImplementStatus.BLOCKED)
        template_vars = captured.get("template_vars")
        self.assertIsInstance(template_vars, dict)
        assert isinstance(template_vars, dict)
        self.assertIn("runtime_file_facts_json", template_vars)
        self.assertIn("directory_tree_snapshot", template_vars)


class ImplementExecutionBatchPathContractTests(unittest.TestCase):
    """Tests for per-batch allowed path contract construction."""

    def test_excludes_type_placement_prefix_when_shared_contracts_empty(self) -> None:
        brief = {
            "spec_rows": [{"spec_id": "A1", "module_tag": "CORE", "module_role": "domain"}],
            "planned_anchors": [{"planned_file_path": "CORE/domain/service.py"}],
            "shared_contracts": [],
        }
        contract = build_batch_path_contract(
            brief,
            "workspace/shared-contracts/",
            ["docs/"],
        )
        self.assertNotIn("workspace/shared-contracts/", contract["allowed_prefixes"])

    def test_includes_type_placement_prefix_when_shared_contracts_present(self) -> None:
        brief = {
            "spec_rows": [{"spec_id": "A1", "module_tag": "CORE", "module_role": "domain"}],
            "planned_anchors": [{"planned_file_path": "CORE/domain/service.py"}],
            "shared_contracts": [{"planned_file_path": "workspace/shared-contracts/request.json"}],
        }
        contract = build_batch_path_contract(
            brief,
            "workspace/shared-contracts/",
            ["docs/"],
        )
        self.assertIn("workspace/shared-contracts/", contract["allowed_prefixes"])


class ImplementExecutionRuntimeFactsTests(unittest.TestCase):
    """Tests for deterministic runtime file facts passed to implement prompt."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-runtime-facts-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_build_runtime_file_facts_includes_required_sha256_field(self) -> None:
        existing = self.tmp / "workspace" / "shared-contracts" / "nutrition_request.json"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text("{\"type\":\"object\"}\n", encoding="utf-8")
        expected_hash = _sha256(existing.read_bytes())

        brief = {
            "planned_anchors": [
                {"planned_file_path": "workspace/shared-contracts/nutrition_request.json"},
                {"planned_file_path": "workspace/shared-contracts/login_request.json"},
            ],
            "shared_contracts": [
                {"planned_file_path": "workspace/shared-contracts/nutrition_request.json"},
            ],
        }

        facts = _build_runtime_file_facts(self.tmp, brief)

        self.assertIn("workspace/shared-contracts/nutrition_request.json", facts)
        self.assertIn("workspace/shared-contracts/login_request.json", facts)
        for payload in facts.values():
            self.assertIn("sha256", payload)
            self.assertIsInstance(payload["sha256"], str)

        self.assertTrue(facts["workspace/shared-contracts/nutrition_request.json"]["exists"])
        self.assertEqual(
            facts["workspace/shared-contracts/nutrition_request.json"]["sha256"],
            expected_hash,
        )
        self.assertFalse(facts["workspace/shared-contracts/login_request.json"]["exists"])
        self.assertEqual(facts["workspace/shared-contracts/login_request.json"]["sha256"], "")


class ImplementExecutionVerificationFallbackTests(unittest.TestCase):
    """Tests for mandatory fallback verification commands."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-verify-fallback-"))
        (self.tmp / "CORE" / "tests").mkdir(parents=True, exist_ok=True)
        (self.tmp / "CORE" / "tests" / "test_dummy.py").write_text(
            "def test_dummy() -> None:\n    assert True\n",
            encoding="utf-8",
        )
        self.brief = {"spec_rows": [{"spec_id": "A1", "module_tag": "CORE", "module_role": "domain"}]}

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_uses_configured_verification_commands_when_present(self) -> None:
        commands = default_verification_commands_for_batch(
            self.tmp,
            self.brief,
            ["python -m pytest CORE/tests -q"],
        )
        self.assertEqual(commands, ["python -m pytest CORE/tests -q"])

    def test_uses_pytest_module_tests_as_default_when_available(self) -> None:
        commands = default_verification_commands_for_batch(
            self.tmp,
            self.brief,
            [],
        )
        self.assertEqual(commands, ["python -m pytest CORE/tests -q"])

    def test_falls_back_to_compileall_when_pytest_unavailable(self) -> None:
        class _Proc:
            returncode = 1

        with patch("handlers.implement.semantic_guard.subprocess.run", return_value=_Proc()):
            commands = default_verification_commands_for_batch(
                self.tmp,
                self.brief,
                [],
            )
        self.assertEqual(commands, ["python -m compileall CORE -q"])


class ImplementExecutionVerificationFallbackGitScopeTests(unittest.TestCase):
    """Tests for fallback command selection against git HEAD visibility."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-verify-fallback-git-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_ignores_untracked_tests_not_present_in_head(self) -> None:
        repo = self.tmp / "repo"
        project = repo / "dataset" / "nutrition"
        (project / "CORE").mkdir(parents=True, exist_ok=True)
        (project / "README.md").write_text("seed\n", encoding="utf-8")

        subprocess.run(
            ["git", "init"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["git", "add", "."],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test User",
                "commit",
                "-m",
                "seed",
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )

        # Untracked local tests should not influence detached-worktree verification targets.
        (project / "CORE" / "tests").mkdir(parents=True, exist_ok=True)
        (project / "CORE" / "tests" / "test_untracked.py").write_text(
            "def test_tmp() -> None:\n    assert True\n",
            encoding="utf-8",
        )

        brief = {"spec_rows": [{"module_tag": "CORE", "module_role": "domain"}], "planned_anchors": []}
        commands = default_verification_commands_for_batch(project, brief, [])

        self.assertEqual(commands, ["python -m compileall CORE -q"])

    def test_skips_pytest_target_when_head_has_no_test_modules(self) -> None:
        repo = self.tmp / "repo_empty_tests"
        project = repo / "dataset" / "nutrition"
        (project / "SHARED" / "tests").mkdir(parents=True, exist_ok=True)
        (project / "SHARED" / "tests" / "__init__.py").write_text("", encoding="utf-8")

        subprocess.run(
            ["git", "init"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["git", "add", "."],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test User",
                "commit",
                "-m",
                "seed",
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        )

        brief = {"spec_rows": [{"module_tag": "SHARED", "module_role": "contracts"}], "planned_anchors": []}
        commands = default_verification_commands_for_batch(project, brief, [])

        self.assertEqual(commands, ["python -m compileall SHARED -q"])


class ImplementExecutionWorktreeScopeTests(unittest.TestCase):
    """Regression tests for verification cwd scoping in subdirectory project roots."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-worktree-scope-"))
        self.repo = self.tmp / "repo"
        self.project_root = self.repo / "dataset" / "nutrition"
        (self.project_root / "CORE").mkdir(parents=True, exist_ok=True)
        (self.project_root / "CORE" / "project.marker").write_text("ok\n", encoding="utf-8")
        (self.project_root / "verify_cwd.py").write_text(
            (
                "import pathlib\n"
                "import sys\n\n"
                "marker = pathlib.Path('CORE/project.marker')\n"
                "sys.exit(0 if marker.exists() else 1)\n"
            ),
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "init"],
            cwd=str(self.repo),
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "add", "."],
            cwd=str(self.repo),
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test User",
                "commit",
                "-m",
                "init",
            ],
            cwd=str(self.repo),
            check=True,
            capture_output=True,
            text=True,
        )
        self.patch = self.tmp / "project_patch.diff"
        self.patch.write_text(_new_file_diff("CORE/generated_module.py", "VALUE = 1"), encoding="utf-8")
        self.verification = self.tmp / "verification"
        self.verification.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_apply_and_verify_uses_project_root_inside_worktree_for_subdir_project(self) -> None:
        """Verification commands run from worktree project root, not repository root."""
        result = _apply_and_verify(
            self.project_root,
            "B1",
            [str(self.patch)],
            ["python verify_cwd.py"],
            self.verification,
        )

        self.assertTrue(result["success"], msg=str(result["records"]))
        command_records = [r for r in result.get("records", []) if isinstance(r, dict) and "command" in r]
        self.assertEqual(len(command_records), 1)
        self.assertEqual(command_records[0].get("command"), "python verify_cwd.py")
        self.assertEqual(command_records[0].get("exit_code"), 0)
        self.assertTrue((self.project_root / "CORE" / "generated_module.py").exists())
        self.assertFalse((self.repo / "CORE" / "generated_module.py").exists())

    def test_apply_and_verify_rejects_mixed_prefixed_and_unprefixed_patch_paths(self) -> None:
        """Mixed patch path scopes are rejected deterministically as semantic conflicts."""
        mixed_patch = self.tmp / "mixed_scope_patch.diff"
        mixed_patch.write_text(
            (
                _new_file_diff("CORE/unprefixed_module.py", "VALUE = 1")
                + _new_file_diff("dataset/nutrition/CORE/prefixed_module.py", "VALUE = 2")
            ),
            encoding="utf-8",
        )

        result = _apply_and_verify(
            self.project_root,
            "B2",
            [str(mixed_patch)],
            ["python verify_cwd.py"],
            self.verification,
        )

        self.assertFalse(result["success"])
        kinds = [r.get("kind") for r in result.get("records", []) if isinstance(r, dict)]
        self.assertIn("patch_scope_conflict", kinds)

    def test_apply_and_verify_places_unprefixed_paths_under_codebase_dir_when_set(self) -> None:
        """Unprefixed patch paths are treated as codebase-relative when codebase_dir is nested."""
        codebase_dir = self.project_root / "src"
        codebase_dir.mkdir(parents=True, exist_ok=True)
        patch = self.tmp / "codebase_relative_patch.diff"
        patch.write_text(_new_file_diff("generated_module.py", "VALUE = 1"), encoding="utf-8")

        result = _apply_and_verify(
            self.project_root,
            "B4",
            [str(patch)],
            ["python verify_cwd.py"],
            self.verification,
            codebase_dir=codebase_dir,
        )

        self.assertTrue(result["success"], msg=str(result["records"]))
        self.assertTrue((self.project_root / "src" / "generated_module.py").exists())
        self.assertFalse((self.project_root / "generated_module.py").exists())

    def test_apply_and_verify_avoids_double_prefix_for_project_relative_paths_with_codebase_dir(self) -> None:
        """Project-relative paths keep normal project-root scope when codebase prefix is explicit."""
        codebase_dir = self.project_root / "src"
        codebase_dir.mkdir(parents=True, exist_ok=True)
        patch = self.tmp / "project_relative_patch.diff"
        patch.write_text(_new_file_diff("src/prefixed_module.py", "VALUE = 2"), encoding="utf-8")

        result = _apply_and_verify(
            self.project_root,
            "B5",
            [str(patch)],
            ["python verify_cwd.py"],
            self.verification,
            codebase_dir=codebase_dir,
        )

        self.assertTrue(result["success"], msg=str(result["records"]))
        self.assertTrue((self.project_root / "src" / "prefixed_module.py").exists())
        self.assertFalse((self.project_root / "src" / "src" / "prefixed_module.py").exists())

    def test_apply_and_verify_rejects_mixed_project_and_codebase_relative_paths(self) -> None:
        """Mixed project-relative and codebase-relative paths fail fast as ambiguous scope."""
        codebase_dir = self.project_root / "src"
        codebase_dir.mkdir(parents=True, exist_ok=True)
        mixed_patch = self.tmp / "mixed_codebase_scope_patch.diff"
        mixed_patch.write_text(
            (
                _new_file_diff("generated_module.py", "VALUE = 1")
                + _new_file_diff("src/prefixed_module.py", "VALUE = 2")
            ),
            encoding="utf-8",
        )

        result = _apply_and_verify(
            self.project_root,
            "B6",
            [str(mixed_patch)],
            ["python verify_cwd.py"],
            self.verification,
            codebase_dir=codebase_dir,
        )

        self.assertFalse(result["success"])
        kinds = [r.get("kind") for r in result.get("records", []) if isinstance(r, dict)]
        self.assertIn("patch_scope_conflict", kinds)

    def test_apply_and_verify_syncs_uncommitted_project_files_into_worktree(self) -> None:
        """Worktree verification uses synced project state, not only HEAD committed files."""
        local_only = self.project_root / "CORE" / "local_only.txt"
        local_only.write_text("old\n", encoding="utf-8")
        modify_patch = self.tmp / "modify_uncommitted.diff"
        modify_patch.write_text(
            _modify_file_diff("CORE/local_only.txt", "old", "new"),
            encoding="utf-8",
        )

        result = _apply_and_verify(
            self.project_root,
            "B3",
            [str(modify_patch)],
            ["python verify_cwd.py"],
            self.verification,
        )

        self.assertTrue(result["success"], msg=str(result["records"]))
        self.assertEqual(local_only.read_text(encoding="utf-8"), "new\n")

    def test_apply_and_verify_accepts_whitespace_only_context_mismatch_with_fallback(self) -> None:
        """Apply path retries with --ignore-space-change for whitespace-only context mismatches."""
        target = self.project_root / "src" / "CORE" / "tests" / "test_whitespace_apply.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_tab_indent():\n\treturn 1\n", encoding="utf-8")
        patch = self.tmp / "whitespace_context_patch.diff"
        patch.write_text(
            "\n".join(
                [
                    "--- a/src/CORE/tests/test_whitespace_apply.py",
                    "+++ b/src/CORE/tests/test_whitespace_apply.py",
                    "@@ -1,2 +1,3 @@",
                    " def test_tab_indent():",
                    "-    return 1",
                    "+\treturn 1",
                    "+    return 2",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = _apply_and_verify(
            self.project_root,
            "B8",
            [str(patch)],
            ["python verify_cwd.py"],
            self.verification,
            codebase_dir=self.project_root / "src",
        )

        self.assertTrue(result["success"], msg=str(result["records"]))
        updated = target.read_text(encoding="utf-8")
        self.assertIn("return 2", updated)

    def test_apply_and_verify_skips_patch_when_change_is_already_applied(self) -> None:
        """Already-applied patches are treated as idempotent no-ops."""
        target = self.project_root / "CORE" / "already_applied.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("old\n", encoding="utf-8")
        patch = self.tmp / "already_applied.diff"
        patch.write_text(
            _modify_file_diff("CORE/already_applied.txt", "old", "new"),
            encoding="utf-8",
        )

        preapply = subprocess.run(
            ["git", "-C", str(self.repo), "apply", "--directory", "dataset/nutrition", str(patch)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(preapply.returncode, 0, msg=preapply.stderr)

        result = _apply_and_verify(
            self.project_root,
            "B9",
            [str(patch)],
            ["python verify_cwd.py"],
            self.verification,
        )

        self.assertTrue(result["success"], msg=str(result["records"]))
        self.assertEqual(target.read_text(encoding="utf-8"), "new\n")
        kinds = [r.get("kind") for r in result.get("records", []) if isinstance(r, dict)]
        self.assertIn("patch_already_applied_skip", kinds)


class ImplementExecutionWorktreeBootstrapTests(unittest.TestCase):
    """Regression tests for detached worktree bootstrap in ignored subproject roots."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="implement-worktree-bootstrap-"))
        self.repo = self.tmp / "repo"
        self.project_root = self.repo / "dataset" / "nutrition"
        (self.project_root / "CORE").mkdir(parents=True, exist_ok=True)
        (self.project_root / "CORE" / "project.marker").write_text("ok\n", encoding="utf-8")
        (self.project_root / "verify_cwd.py").write_text(
            (
                "import pathlib\n"
                "import sys\n\n"
                "marker = pathlib.Path('CORE/project.marker')\n"
                "sys.exit(0 if marker.exists() else 1)\n"
            ),
            encoding="utf-8",
        )
        (self.repo / ".gitignore").write_text("dataset/\n", encoding="utf-8")
        (self.repo / "README.md").write_text("seed\n", encoding="utf-8")
        subprocess.run(
            ["git", "init"],
            cwd=str(self.repo),
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "add", ".gitignore", "README.md"],
            cwd=str(self.repo),
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test User",
                "commit",
                "-m",
                "init",
            ],
            cwd=str(self.repo),
            check=True,
            capture_output=True,
            text=True,
        )
        self.patch = self.tmp / "project_patch.diff"
        self.patch.write_text(_new_file_diff("CORE/generated_module.py", "VALUE = 1"), encoding="utf-8")
        self.verification = self.tmp / "verification"
        self.verification.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_apply_and_verify_bootstraps_missing_project_root_inside_worktree(self) -> None:
        """Ignored project subpaths are bootstrapped and synced into detached verification worktree."""
        result = _apply_and_verify(
            self.project_root,
            "B0",
            [str(self.patch)],
            ["python verify_cwd.py"],
            self.verification,
        )

        self.assertTrue(result["success"], msg=str(result["records"]))
        command_records = [r for r in result.get("records", []) if isinstance(r, dict) and "command" in r]
        self.assertEqual(len(command_records), 1)
        self.assertEqual(command_records[0].get("command"), "python verify_cwd.py")
        self.assertEqual(command_records[0].get("exit_code"), 0)
        kinds = [r.get("kind") for r in result.get("records", []) if isinstance(r, dict)]
        self.assertNotIn("worktree_project_root_bootstrap_failed", kinds)
        self.assertTrue((self.project_root / "CORE" / "generated_module.py").exists())


class TestContractSchemaConformanceCheck(unittest.TestCase):
    """Tests for _check_contract_schema_conformance and _schema_allows_null."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_schema(self, rel_path: str, schema: dict) -> Path:
        path = self.tmp / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(schema), encoding="utf-8")
        return path

    def _brief(self, contract_id: str, planned_path: str, fields: list[dict]) -> dict:
        return {
            "shared_contracts": [{
                "contract_id": contract_id,
                "planned_file_path": planned_path,
                "fields": fields,
            }]
        }

    def test_passes_all_required_and_nullable_consistent(self) -> None:
        """Schema with all properties in required and correct nullability passes."""
        from handlers.implement.execution import _check_contract_schema_conformance
        self._write_schema("shared/my_dto.json", {
            "properties": {
                "user_id": {"type": "string"},
                "display_name": {"type": ["string", "null"]},
            },
            "required": ["user_id", "display_name"],
        })
        brief = self._brief("my_dto", "shared/my_dto.json", [
            {"name": "user_id", "type_name": "string", "nullable": False},
            {"name": "display_name", "type_name": "string", "nullable": True},
        ])
        result = _check_contract_schema_conformance(brief, self.tmp)
        self.assertEqual(result["status"], "passed", result)
        self.assertIn("my_dto:conformant", result["checks"])

    def test_fails_when_field_not_in_required(self) -> None:
        """Schema property missing from required produces fields_not_in_required violation."""
        from handlers.implement.execution import _check_contract_schema_conformance
        self._write_schema("shared/my_dto.json", {
            "properties": {
                "user_id": {"type": "string"},
                "optional_name": {"type": "string"},
            },
            "required": ["user_id"],  # optional_name missing from required
        })
        brief = self._brief("my_dto", "shared/my_dto.json", [
            {"name": "user_id", "type_name": "string", "nullable": False},
            {"name": "optional_name", "type_name": "string", "nullable": False},
        ])
        result = _check_contract_schema_conformance(brief, self.tmp)
        self.assertEqual(result["status"], "failed")
        kinds = [v["kind"] for v in result["violations"]]
        self.assertIn("fields_not_in_required", kinds)

    def test_fails_when_nullable_true_but_no_null_type(self) -> None:
        """Field with nullable=true but schema using plain string type produces violation."""
        from handlers.implement.execution import _check_contract_schema_conformance
        self._write_schema("shared/my_dto.json", {
            "properties": {"display_name": {"type": "string"}},  # no null
            "required": ["display_name"],
        })
        brief = self._brief("my_dto", "shared/my_dto.json", [
            {"name": "display_name", "type_name": "string", "nullable": True},
        ])
        result = _check_contract_schema_conformance(brief, self.tmp)
        self.assertEqual(result["status"], "failed")
        kinds = [v["kind"] for v in result["violations"]]
        self.assertIn("nullable_true_but_no_null_type", kinds)

    def test_fails_when_nullable_false_but_allows_null(self) -> None:
        """Field with nullable=false but schema allowing null produces violation."""
        from handlers.implement.execution import _check_contract_schema_conformance
        self._write_schema("shared/my_dto.json", {
            "properties": {"user_id": {"type": ["string", "null"]}},
            "required": ["user_id"],
        })
        brief = self._brief("my_dto", "shared/my_dto.json", [
            {"name": "user_id", "type_name": "string", "nullable": False},
        ])
        result = _check_contract_schema_conformance(brief, self.tmp)
        self.assertEqual(result["status"], "failed")
        kinds = [v["kind"] for v in result["violations"]]
        self.assertIn("nullable_false_but_null_type", kinds)

    def test_skips_missing_file(self) -> None:
        """Contract whose planned_file_path does not exist is skipped, not failed."""
        from handlers.implement.execution import _check_contract_schema_conformance
        brief = self._brief("my_dto", "shared/nonexistent.json", [
            {"name": "user_id", "type_name": "string", "nullable": False},
        ])
        result = _check_contract_schema_conformance(brief, self.tmp)
        self.assertEqual(result["status"], "passed")
        self.assertIn("my_dto:file_not_found_skipped", result["checks"])

    def test_allows_null_via_anyof(self) -> None:
        """nullable=true field using anyOf with null type passes."""
        from handlers.implement.execution import _check_contract_schema_conformance
        self._write_schema("shared/my_dto.json", {
            "properties": {
                "display_name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            },
            "required": ["display_name"],
        })
        brief = self._brief("my_dto", "shared/my_dto.json", [
            {"name": "display_name", "type_name": "string", "nullable": True},
        ])
        result = _check_contract_schema_conformance(brief, self.tmp)
        self.assertEqual(result["status"], "passed", result)

    def test_schema_allows_null_variants(self) -> None:
        """_schema_allows_null recognises list types, anyOf, oneOf, and bare null."""
        from handlers.implement.execution import _schema_allows_null
        self.assertTrue(_schema_allows_null({"type": ["string", "null"]}))
        self.assertTrue(_schema_allows_null({"type": "null"}))
        self.assertTrue(_schema_allows_null({"anyOf": [{"type": "string"}, {"type": "null"}]}))
        self.assertTrue(_schema_allows_null({"oneOf": [{"type": "integer"}, {"type": "null"}]}))
        self.assertFalse(_schema_allows_null({"type": "string"}))
        self.assertFalse(_schema_allows_null({"anyOf": [{"type": "string"}, {"type": "boolean"}]}))


if __name__ == "__main__":
    unittest.main()
