"""Handler for `agent implement` with unified planning and execution workflow."""

from __future__ import annotations

from handlers.implement.batching import (
    _build_batches,
    _build_briefs,
)
from handlers.implement.catalog import (
    _build_module_catalog,
    _select_workset,
)
from handlers.implement.config import (
    _get_impl_cfg,
    _resolve_min_confidence_threshold,
)
from handlers.implement.execution import _execute_batch
from handlers.implement.helpers import (
    _report_implement_phase,
)
from handlers.implement.impl import run_implement
from handlers.implement.validation import (
    _escalate_spec_issues,
    _validate_batch_plan_dependencies,
    _validate_brief_scoping,
    _validate_contract_field_consistency,
    _validate_dependency_context_edges,
    _validate_required_field_coverage,
    _validate_unified_plan,
)

__all__ = [
    "run_implement",
    "_build_batches",
    "_build_briefs",
    "_build_module_catalog",
    "_escalate_spec_issues",
    "_execute_batch",
    "_get_impl_cfg",
    "_report_implement_phase",
    "_resolve_min_confidence_threshold",
    "_select_workset",
    "_validate_batch_plan_dependencies",
    "_validate_brief_scoping",
    "_validate_contract_field_consistency",
    "_validate_dependency_context_edges",
    "_validate_required_field_coverage",
    "_validate_unified_plan",
]
