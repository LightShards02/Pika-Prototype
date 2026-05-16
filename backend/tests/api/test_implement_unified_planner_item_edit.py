"""POST /resolutions/items/{i}/edit on a blocked implement.unified-planner run."""

from __future__ import annotations

from pathlib import Path

from tests.api._implement_helpers import (
    blocking_planner_output,
    enable_implement,
    write_planner_inputs,
)
from tests.api._refine_helpers import wait_for_status


def _start_blocked_planner_run(client, ws1_dir: Path, monkeypatch) -> tuple[str, list[dict]]:
    enable_implement(ws1_dir)
    design_rel, codebase_rel = write_planner_inputs(ws1_dir)

    from handlers.implement.phases import unified_planner as phase_mod
    monkeypatch.setattr(phase_mod, "invoke_with_semantic_retry", lambda **_kw: blocking_planner_output())

    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    resp = client.post(
        "/v1/phases/implement.unified-planner/runs",
        json={
            "workspace_id": ws["id"],
            "inputs": {"design_spec_path": design_rel, "codebase_dir": codebase_rel},
        },
    )
    phase_run_id = resp.json()["phase_run_id"]
    wait_for_status(client, phase_run_id, "blocked")
    items = client.get(f"/v1/phase-runs/{phase_run_id}/resolutions").json()["items"]
    return phase_run_id, items


def test_edit_invokes_spec_editor_on_blocked_planner_item(client, ws1_dir: Path, monkeypatch) -> None:
    fake_output = {
        "edit_type": "field",
        "field": "requirement",
        "new_text": "rewritten requirement text",
    }
    import handlers.resolve as resolve_mod
    monkeypatch.setattr(resolve_mod, "invoke_spec_editor", lambda *_a, **_kw: fake_output)
    monkeypatch.setattr(resolve_mod, "_invoke_spec_editor", lambda *_a, **_kw: fake_output)

    phase_run_id, items = _start_blocked_planner_run(client, ws1_dir, monkeypatch)
    assert len(items) >= 1

    resp = client.post(
        f"/v1/phase-runs/{phase_run_id}/resolutions/items/0/edit",
        json={"user_guide": "tighten the wording"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["editor_output"] == fake_output
    assert body["item_index"] == 0
    assert body["phase_run_id"] == phase_run_id


def test_edit_returns_404_for_out_of_range_index_on_planner(client, ws1_dir: Path, monkeypatch) -> None:
    phase_run_id, _items = _start_blocked_planner_run(client, ws1_dir, monkeypatch)

    resp = client.post(
        f"/v1/phase-runs/{phase_run_id}/resolutions/items/999/edit",
        json={"user_guide": "out of range"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "item_index_out_of_range"


def test_edit_passes_memory_to_spec_editor(client, ws1_dir: Path, monkeypatch) -> None:
    """When workspace memory contains lessons, /edit invokes spec_editor with
    rendered {memory} in template_vars (via the agent invoker downstream)."""
    captured: dict[str, object] = {}

    def fake_invoke(item, config, ctx, phase_run_dir, *, user_guide):
        captured["memory_context"] = ctx.memory_context
        return {"edit_type": "field", "field": "requirement", "new_text": "ok"}

    import handlers.resolve as resolve_mod
    monkeypatch.setattr(resolve_mod, "invoke_spec_editor", fake_invoke)
    monkeypatch.setattr(resolve_mod, "_invoke_spec_editor", fake_invoke)

    phase_run_id, items = _start_blocked_planner_run(client, ws1_dir, monkeypatch)
    assert len(items) >= 1

    ws = client.post("/v1/workspaces", json={"path": ws1_dir.name}).json()
    client.put(
        f"/v1/workspaces/{ws['id']}/memory/lessons",
        content="# Lessons\n\n- never use mocks in integration tests\n",
        headers={"Content-Type": "text/plain"},
    )

    resp = client.post(
        f"/v1/phase-runs/{phase_run_id}/resolutions/items/0/edit",
        json={"user_guide": "tighten"},
    )
    assert resp.status_code == 200, resp.text
    memory_ctx = captured.get("memory_context")
    assert isinstance(memory_ctx, dict), f"expected dict, got {memory_ctx!r}"
    assert "never use mocks" in memory_ctx.get("lessons", "")
