"""Graph algorithms for implement batch planning."""

from __future__ import annotations

import heapq
from typing import Any


def tarjan_sccs(graph: dict[str, set[str]]) -> list[list[str]]:
    """Compute strongly connected components using deterministic Tarjan traversal."""
    index = 0
    indices: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def strong_connect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlink[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in sorted(graph.get(node, set())):
            if neighbor not in indices:
                strong_connect(neighbor)
                lowlink[node] = min(lowlink[node], lowlink[neighbor])
            elif neighbor in on_stack:
                lowlink[node] = min(lowlink[node], indices[neighbor])

        if lowlink[node] != indices[node]:
            return
        component: list[str] = []
        while stack:
            popped = stack.pop()
            on_stack.discard(popped)
            component.append(popped)
            if popped == node:
                break
        components.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            strong_connect(node)
    return components


def topologically_order_sccs(graph: dict[str, set[str]], sccs: list[list[str]]) -> list[int]:
    """Topologically sort SCCs by provider->consumer edges with deterministic tie-breaks."""
    module_to_scc = {module: idx for idx, component in enumerate(sccs) for module in component}
    edges: dict[int, set[int]] = {idx: set() for idx in range(len(sccs))}
    indegree: dict[int, int] = {idx: 0 for idx in range(len(sccs))}

    for consumer, providers in graph.items():
        consumer_idx = module_to_scc.get(consumer)
        if consumer_idx is None:
            continue
        for provider in providers:
            provider_idx = module_to_scc.get(provider)
            if provider_idx is None or provider_idx == consumer_idx:
                continue
            if consumer_idx not in edges[provider_idx]:
                edges[provider_idx].add(consumer_idx)
                indegree[consumer_idx] += 1

    order: list[int] = []
    keys = {idx: ",".join(sccs[idx]) for idx in range(len(sccs))}
    heap = [(keys[idx], idx) for idx in range(len(sccs)) if indegree[idx] == 0]
    heapq.heapify(heap)
    while heap:
        _, current = heapq.heappop(heap)
        order.append(current)
        for nxt in sorted(edges[current], key=lambda idx: keys[idx]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(heap, (keys[nxt], nxt))

    if len(order) == len(sccs):
        return order
    return sorted(range(len(sccs)), key=lambda idx: ",".join(sccs[idx]))
