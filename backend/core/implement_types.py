"""TypedDict definitions for implement workflow data structures."""

from __future__ import annotations

from typing import Any, TypedDict


class ModuleCatalogEntry(TypedDict, total=False):
    """Entry in the module catalog."""

    module_tag: str
    module_role: str
    root_dirs: list[str]
    languages: list[str]


class ModuleCatalog(TypedDict, total=False):
    """Module catalog structure."""

    modules: list[ModuleCatalogEntry]


class SpecDependency(TypedDict, total=False):
    """Cross-module spec-to-spec dependency edge.

    consumer_spec_id depends on all provider_spec_ids being implemented first.
    """

    consumer_spec_id: str
    provider_spec_ids: list[str]
    rationale: str


class SharedContract(TypedDict, total=False):
    """Shared contract (DTO/interface/type) declaration from unified planner.

    Describes a canonical type provided by explicit spec IDs and consumed
    by specs across multiple modules.
    """

    contract_id: str
    provider_spec_ids: list[str]
    planned_file_path: str
    consumed_by_specs: list[str]
    description: str
    fields: list[dict[str, Any]]


class UnifiedPlan(TypedDict, total=False):
    """Top-level unified planner output (success branch).

    Contains per-module file plans, cross-module spec dependencies,
    and shared contract declarations.
    """

    module_plans: list[dict[str, Any]]
    spec_dependencies: list[SpecDependency]
    shared_contracts: list[SharedContract]


class BatchPlanEntry(TypedDict, total=False):
    """Single batch in the batch plan."""

    batch_id: str
    kind: str
    module_tags: list[str]
    spec_ids: list[str]
    depends_on_batches: list[str]


class BatchPlan(TypedDict, total=False):
    """Batch plan structure."""

    batches: list[BatchPlanEntry]


class BatchBrief(TypedDict, total=False):
    """Batch brief for implementer agent.

    Contains everything the implementer needs for one batch: the spec rows,
    the planned anchors for those specs, relevant shared contracts, and
    cross-module dependency context.
    """

    batch_id: str
    spec_rows: list[dict[str, Any]]
    planned_anchors: list[dict[str, Any]]
    shared_contracts: list[dict[str, Any]]
    spec_dependency_context: list[SpecDependency]
    constraints: dict[str, Any]
