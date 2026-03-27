"""Batch construction and brief generation for implement workflow (unified planner)."""

from __future__ import annotations

from typing import Any

from core.constants import BatchKind
from core.graph_utils import tarjan_sccs, topologically_order_sccs
from core.implement_types import BatchBrief, BatchPlan, BatchPlanEntry, SpecDependency


def _build_spec_to_files(module_plans: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    """Build spec_id -> set[planned_file_path] from per-module plans."""
    spec_to_files: dict[str, set[str]] = {}
    for plan in module_plans.values():
        if not isinstance(plan, dict):
            continue
        for anchor in plan.get("planned_anchors", []):
            if not isinstance(anchor, dict):
                continue
            path = str(anchor.get("planned_file_path", "")).strip()
            if not path:
                continue
            for spec_id in anchor.get("spec_ids", []):
                sid = str(spec_id).strip()
                if sid:
                    spec_to_files.setdefault(sid, set()).add(path)
    return spec_to_files


def _build_spec_dependency_graph(
    spec_dependencies: list[dict[str, Any]],
) -> dict[str, set[str]]:
    """Build consumer_spec -> set[provider_specs] from spec_dependencies list."""
    graph: dict[str, set[str]] = {}
    for dep in spec_dependencies:
        if not isinstance(dep, dict):
            continue
        consumer = str(dep.get("consumer_spec_id", "")).strip()
        providers = dep.get("provider_spec_ids", [])
        if not consumer or not isinstance(providers, list):
            continue
        graph.setdefault(consumer, set())
        for p in providers:
            pid = str(p).strip()
            if pid:
                graph[consumer].add(pid)
                graph.setdefault(pid, set())
    return graph


def _merge_intra_module_dependencies(
    spec_dep_graph: dict[str, set[str]],
    module_plans: list[dict[str, Any]] | None,
) -> dict[str, set[str]]:
    """Merge intra-module dependencies from module plans into the spec graph."""
    if not module_plans:
        return spec_dep_graph

    merged: dict[str, set[str]] = {
        str(consumer): set(providers)
        for consumer, providers in spec_dep_graph.items()
    }
    for plan in module_plans:
        if not isinstance(plan, dict):
            continue
        for dep in plan.get("intra_module_dependencies", []):
            if not isinstance(dep, dict):
                continue
            consumer = str(dep.get("spec_id", "")).strip()
            providers = dep.get("depends_on", [])
            if not consumer or not isinstance(providers, list):
                continue
            merged.setdefault(consumer, set())
            for provider in providers:
                pid = str(provider).strip()
                if not pid:
                    continue
                merged[consumer].add(pid)
                merged.setdefault(pid, set())
    return merged


def _chunk_file_set(
    chunk_spec_ids: list[str],
    spec_to_files: dict[str, set[str]],
) -> set[str]:
    """Return union file set for one chunk using spec->files mapping."""
    files: set[str] = set()
    for spec_id in chunk_spec_ids:
        files |= spec_to_files.get(spec_id, set())
    return files


def _build_module_level_graph(
    modules: dict[str, list[str]],
    spec_dep_graph: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Derive module -> set[provider_modules] from spec-level dependency graph.

    A module M depends on module N when any spec in M depends on a spec in N (M != N).
    """
    spec_to_module: dict[str, str] = {}
    for module, specs in modules.items():
        for sid in specs:
            spec_to_module[sid] = module

    graph: dict[str, set[str]] = {module: set() for module in modules}
    for consumer_spec, provider_specs in spec_dep_graph.items():
        consumer_module = spec_to_module.get(consumer_spec)
        if not consumer_module:
            continue
        for provider_spec in provider_specs:
            provider_module = spec_to_module.get(provider_spec)
            if provider_module and provider_module != consumer_module:
                graph[consumer_module].add(provider_module)
    return graph


def _ordered_spec_groups_for_chunking(
    spec_ids: list[str],
    spec_dep_graph: dict[str, set[str]],
) -> list[list[str]]:
    """Return provider-first ordered spec groups, keeping spec SCCs atomic.

    For chunking, we need a deterministic order that avoids forward dependency
    references when possible and never splits a strongly connected spec cycle.
    """
    specs = sorted({str(s).strip() for s in spec_ids if str(s).strip()})
    if not specs:
        return []
    induced: dict[str, set[str]] = {sid: set() for sid in specs}
    for consumer in specs:
        for provider in spec_dep_graph.get(consumer, set()):
            if provider in induced and provider != consumer:
                induced[consumer].add(provider)
    sccs = tarjan_sccs(induced)
    scc_order = topologically_order_sccs(induced, sccs)
    return [sorted(sccs[idx]) for idx in scc_order]


def _chunk_spec_groups(
    spec_groups: list[list[str]],
    chunk_size: int,
    max_files: int | None = None,
    spec_to_files: dict[str, set[str]] | None = None,
) -> list[list[str]]:
    """Chunk ordered spec groups without splitting any group (SCC-safe)."""
    if chunk_size <= 0:
        flat = [sid for group in spec_groups for sid in group]
        return [flat] if flat else []

    use_file_limit = bool(max_files and max_files > 0 and spec_to_files)
    chunks: list[list[str]] = []
    current: list[str] = []
    current_files: set[str] = set()

    for group in spec_groups:
        group_items = [str(s).strip() for s in group if str(s).strip()]
        if not group_items:
            continue
        group_files: set[str] = set()
        if use_file_limit:
            for sid in group_items:
                group_files |= spec_to_files.get(sid, set()) if spec_to_files else set()

        if current:
            next_files = current_files | group_files
            exceeds_specs = len(current) + len(group_items) > chunk_size
            exceeds_files = bool(use_file_limit and len(next_files) > int(max_files or 0))
            if exceeds_specs or exceeds_files:
                chunks.append(current)
                current = []
                current_files = set()

        # Never split a dependency cycle group: if it exceeds budget alone, keep as-is.
        current.extend(group_items)
        current_files |= group_files

    if current:
        chunks.append(current)
    return chunks


def _build_batches(
    rows: list[dict[str, str]],
    spec_dependencies: list[dict[str, Any]],
    budgets: dict[str, int],
    anchor_plans: dict[str, dict[str, Any]] | None = None,
    module_plans: list[dict[str, Any]] | None = None,
) -> BatchPlan:
    """Build deterministic, graph-aware batch plan from spec dependencies and budgets.

    Uses the spec-to-spec dependency graph to derive module ordering, then chunks
    specs within each module by budget constraints.
    """
    anchor_plans = anchor_plans or {}
    modules = _module_specs_from_rows(rows)
    spec_dep_graph = _build_spec_dependency_graph(spec_dependencies)
    spec_dep_graph = _merge_intra_module_dependencies(spec_dep_graph, module_plans)
    module_graph = _build_module_level_graph(modules, spec_dep_graph)

    sccs = tarjan_sccs(module_graph)
    scc_order = topologically_order_sccs(module_graph, sccs)
    max_specs = max(1, int(budgets.get("max_specs_per_batch", 1)))
    max_files = max(0, int(budgets.get("max_files", 0)))

    spec_to_files = _build_spec_to_files(anchor_plans) if anchor_plans else {}
    use_file_chunking = bool(max_files and spec_to_files)

    batches: list[BatchPlanEntry] = []
    counter = 0
    spec_to_batch: dict[str, str] = {}
    for scc_idx in scc_order:
        members = sccs[scc_idx]
        all_specs: list[str] = sorted(set(s for m in members for s in modules.get(m, [])))
        ordered_groups = _ordered_spec_groups_for_chunking(all_specs, spec_dep_graph)
        chunks = _chunk_spec_groups(
            ordered_groups,
            max_specs,
            max_files=max_files if use_file_chunking else None,
            spec_to_files=spec_to_files if use_file_chunking else None,
        )

        planned_chunks: list[dict[str, Any]] = []
        for chunk in chunks:
            bid = f"B{counter}"
            counter += 1
            for sid in chunk:
                spec_to_batch[sid] = bid
            planned_chunks.append({"batch_id": bid, "spec_ids": chunk})

        if len(members) > 1:
            for planned in planned_chunks:
                bid = str(planned["batch_id"])
                chunk = [str(s) for s in planned.get("spec_ids", [])]
                deps = _deps_for_chunk(
                    set(chunk), spec_dep_graph, spec_to_batch,
                )
                deps.discard(bid)
                batches.append(
                    {
                        "batch_id": bid,
                        "kind": BatchKind.MODULE_IMPL,
                        "spec_ids": chunk,
                        "module_tags": sorted(members),
                        "depends_on_batches": sorted(deps),
                        "rationale": f"cyclic cohort {','.join(sorted(members))}",
                        "budgets_applied": budgets,
                    }
                )
            continue

        module = str(members[0])
        prev_batch = ""
        prev_chunk_files: set[str] = set()
        for planned in planned_chunks:
            bid = str(planned["batch_id"])
            chunk = [str(s) for s in planned.get("spec_ids", [])]
            deps = _deps_for_chunk(
                set(chunk), spec_dep_graph, spec_to_batch,
            )
            deps.discard(bid)
            chunk_files = _chunk_file_set(chunk, spec_to_files) if spec_to_files else set()
            if prev_batch and chunk_files and prev_chunk_files and (chunk_files & prev_chunk_files):
                deps.add(prev_batch)
            batches.append(
                {
                    "batch_id": bid,
                    "kind": BatchKind.MODULE_IMPL,
                    "spec_ids": chunk,
                    "module_tags": [module],
                    "depends_on_batches": sorted(deps),
                    "rationale": f"provider-first {module}",
                    "budgets_applied": budgets,
                }
            )
            prev_batch = bid
            prev_chunk_files = chunk_files

    if spec_to_files:
        batches = _add_file_overlap_edges(batches, spec_to_files)

    return {"batches": batches}


def _reachable_from(
    start: str,
    deps: dict[str, set[str]],
) -> set[str]:
    """BFS reachability from start node following deps edges (start -> its deps)."""
    visited: set[str] = set()
    queue = list(deps.get(start, set()))
    while queue:
        node = queue.pop()
        if node in visited:
            continue
        visited.add(node)
        queue.extend(deps.get(node, set()))
    return visited


def _compute_full_reachability(
    batch_ids: list[str],
    deps: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Compute transitive reachability for all nodes (node -> set of nodes it can reach)."""
    return {bid: _reachable_from(bid, deps) for bid in batch_ids}


def _add_file_overlap_edges(
    batches: list[dict[str, Any]],
    spec_to_files: dict[str, set[str]],
) -> list[dict[str, Any]]:
    """Serialize batch pairs that share files but have no existing dependency order.

    For each pair (Bi, Bj) with i < j that share at least one planned file path:
    - If neither batch is already transitively ordered relative to the other:
      add Bi -> Bj (Bj depends on Bi, runs after).
    - If any transitive order already exists (either direction): skip.
      The pair is already serialized through their spec-derived deps, so the later
      batch's workspace sync will naturally see the earlier batch's applied patches.

    This guarantees:
    - No cycles: an edge is only added when neither side can reach the other.
    - No batch merges: batch contents and sizes are never changed.
    - Minimal parallelism impact: only unordered file-sharing pairs are serialized.

    Pairs are processed in stable (i, j) index order for determinism. Reachability
    is updated incrementally so that edges added earlier are visible when later pairs
    are evaluated.
    """
    if not spec_to_files:
        return batches

    deps: dict[str, set[str]] = {
        b["batch_id"]: set(b.get("depends_on_batches", []))
        for b in batches
    }
    batch_ids = [b["batch_id"] for b in batches]
    reachability = _compute_full_reachability(batch_ids, deps)

    batch_files: dict[str, set[str]] = {
        b["batch_id"]: {
            f
            for sid in b.get("spec_ids", [])
            for f in spec_to_files.get(str(sid), set())
        }
        for b in batches
    }

    for i, bi_entry in enumerate(batches):
        bi = bi_entry["batch_id"]
        for bj_entry in batches[i + 1 :]:
            bj = bj_entry["batch_id"]
            if not (batch_files[bi] & batch_files[bj]):
                continue
            # Only add an edge when neither side already orders the other.
            # Adding Bj→Bi (deps[bj].add(bi)) is cycle-free iff Bi does not
            # already transitively depend on Bj (i.e. bi_reaches_bj is False).
            # Because bj_reaches_bi is also False here, both conditions hold.
            bi_reaches_bj = bj in reachability.get(bi, set())
            bj_reaches_bi = bi in reachability.get(bj, set())
            if bi_reaches_bj or bj_reaches_bi:
                continue
            # Neither side is ordered: add Bi -> Bj and propagate reachability.
            deps[bj].add(bi)
            new_reach = {bi} | reachability.get(bi, set())
            reachability[bj] |= new_reach
            for node in batch_ids:
                if bj in reachability.get(node, set()):
                    reachability[node] |= new_reach

    for b in batches:
        b["depends_on_batches"] = sorted(deps[b["batch_id"]])

    return batches


def _deps_for_chunk(
    chunk_spec_ids: set[str],
    spec_dep_graph: dict[str, set[str]],
    spec_to_batch: dict[str, str],
) -> set[str]:
    """Compute batch dependencies for a chunk using spec-level dependency graph.

    For each spec in the chunk, find its provider specs. If a provider spec
    is already assigned to a batch (not the current chunk), add that batch as a dep.
    """
    deps: set[str] = set()
    for spec_id in chunk_spec_ids:
        for provider_spec in spec_dep_graph.get(spec_id, set()):
            if provider_spec in chunk_spec_ids:
                continue
            provider_batch = spec_to_batch.get(provider_spec)
            if provider_batch:
                deps.add(provider_batch)
    return deps


def _module_specs_from_rows(rows: list[dict[str, str]]) -> dict[str, list[str]]:
    """Build deterministic module -> spec_id mapping from selected rows."""
    modules: dict[str, list[str]] = {}
    for row in rows:
        module = str(row.get("module_tag", "")).strip()
        spec_id = str(row.get("spec_id", "")).strip()
        if not module or not spec_id:
            continue
        modules.setdefault(module, []).append(spec_id)
    for module in modules:
        modules[module] = sorted(set(modules[module]))
    return modules


def _chunk_specs(
    spec_ids: list[str],
    chunk_size: int,
    max_files: int | None = None,
    spec_to_files: dict[str, set[str]] | None = None,
) -> list[list[str]]:
    """Split sorted spec IDs into chunks respecting max_specs and optionally max_files.

    When max_files and spec_to_files are provided, uses greedy bin-packing so each
    chunk's cumulative unique file count does not exceed max_files.
    """
    if chunk_size <= 0:
        return [spec_ids] if spec_ids else []
    if max_files is None or max_files <= 0 or spec_to_files is None:
        return [spec_ids[i : i + chunk_size] for i in range(0, len(spec_ids), chunk_size)] or [[]]

    chunks: list[list[str]] = []
    current: list[str] = []
    current_files: set[str] = set()
    for spec_id in spec_ids:
        files = spec_to_files.get(spec_id, set())
        new_files = current_files | files
        would_exceed_specs = len(current) >= chunk_size
        would_exceed_files = len(new_files) > max_files
        if current and (would_exceed_specs or would_exceed_files):
            chunks.append(current)
            current = []
            current_files = set()
        current.append(spec_id)
        current_files |= files
    if current:
        chunks.append(current)
    return chunks


def _build_briefs(
    rows: list[dict[str, str]],
    module_plans: dict[str, dict[str, Any]],
    spec_dependencies: list[dict[str, Any]],
    shared_contracts: list[dict[str, Any]],
    batch_plan: BatchPlan,
    impl: dict[str, Any],
    *,
    appendix_entries: list[Any] | None = None,
) -> list[BatchBrief]:
    """Build batch briefs from selected rows and unified planner artifacts."""
    by_spec = {row["spec_id"]: row for row in rows}

    spec_dep_graph = _build_spec_dependency_graph(spec_dependencies)

    briefs: list[dict[str, Any]] = []
    for batch in batch_plan.get("batches", []):
        if not isinstance(batch, dict):
            continue
        modules = [str(m) for m in batch.get("module_tags", [])]
        spec_ids = [str(s) for s in batch.get("spec_ids", [])]
        spec_id_set = set(spec_ids)
        constraints = {
            "forbidden_paths": impl["forbidden_paths"],
            "budgets_applied": impl["budgets"],
            "verification_commands": impl["verification_commands"],
            "traceability_rules": {"require_spec_ids_per_diff": True},
        }

        # Collect planned anchors for this batch's specs, narrowing spec_ids to batch scope
        planned_anchors: list[dict[str, Any]] = []
        for module in modules:
            plan = module_plans.get(module, {})
            if not isinstance(plan, dict):
                continue
            for anchor in plan.get("planned_anchors", []):
                if not isinstance(anchor, dict):
                    continue
                anchor_specs = {str(s).strip() for s in anchor.get("spec_ids", []) if str(s).strip()}
                batch_scoped = anchor_specs & spec_id_set
                if batch_scoped:
                    planned_anchors.append({**anchor, "spec_ids": sorted(batch_scoped)})

        # Collect shared contracts relevant to this batch, narrowing consumed_by_specs to batch scope
        relevant_contracts = []
        for contract in shared_contracts:
            if not isinstance(contract, dict):
                continue
            consumed = {str(s).strip() for s in contract.get("consumed_by_specs", []) if str(s).strip()}
            batch_scoped = consumed & spec_id_set
            if batch_scoped:
                relevant_contracts.append({**contract, "consumed_by_specs": sorted(batch_scoped)})

        # Collect spec dependency context for this batch
        dep_context: list[dict[str, Any]] = []
        for spec_id in spec_ids:
            providers = spec_dep_graph.get(spec_id, set())
            if providers:
                dep_context.append({
                    "consumer_spec_id": spec_id,
                    "provider_spec_ids": sorted(providers),
                })

        max_files = int(impl.get("budgets", {}).get("max_files", 0) or 0)
        if max_files > 0:
            unique_files = {
                str(a.get("planned_file_path", "")).strip()
                for a in planned_anchors
                if str(a.get("planned_file_path", "")).strip()
            }
            if len(unique_files) > max_files:
                raise ValueError(
                    f"Batch {batch.get('batch_id', '?')} brief exceeds max_files={max_files} "
                    f"(planned {len(unique_files)} unique files)"
                )

        batch_modules = set(modules)
        batch_appendix: list[dict[str, Any]] = []
        if appendix_entries:
            from dataclasses import asdict
            for entry in appendix_entries:
                if entry.module_tag is None or entry.module_tag in batch_modules:
                    batch_appendix.append(asdict(entry))

        briefs.append(
            {
                "batch_id": batch["batch_id"],
                "spec_rows": [by_spec[sid] for sid in spec_ids if sid in by_spec],
                "planned_anchors": planned_anchors,
                "shared_contracts": relevant_contracts,
                "spec_dependency_context": dep_context,
                "constraints": constraints,
                "appendix_entries": batch_appendix,
            }
        )
    return briefs
