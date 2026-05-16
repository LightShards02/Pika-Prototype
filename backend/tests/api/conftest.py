"""Shared fixtures for backend/tests/api/."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


_FIXTURE_WS1 = Path(__file__).resolve().parent / "fixtures" / "ws1"


@pytest.fixture()
def isolated_api_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the workspace registry / api state at a fresh tmp dir per test."""
    state_dir = tmp_path / "api_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PIKA_API_STATE_DIR", str(state_dir))
    return state_dir


@pytest.fixture()
def workspace_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``PIKA_WORKSPACE_BASE_DIR`` at a per-test tmp directory.

    Tests that POST ``{"path": "..."}`` to ``/v1/workspaces`` will have the
    relative path resolved under this directory. The directory itself exists
    (unless a test explicitly removes it before posting, to exercise the
    base-bootstrap path).
    """
    base = tmp_path / "ws_base"
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("PIKA_WORKSPACE_BASE_DIR", str(base.resolve()))
    return base.resolve()


@pytest.fixture()
def ws1_dir(workspace_base: Path) -> Path:
    """Materialize a fresh copy of the ws1 fixture under the workspace base.

    Returned path is absolute (so tests can do ``ws1_dir / "out"``), but its
    parent is the configured ``PIKA_WORKSPACE_BASE_DIR``, so callers should
    POST ``ws1_dir.name`` when registering with the API.
    """
    dest = workspace_base / "ws1"
    shutil.copytree(_FIXTURE_WS1, dest)
    return dest.resolve()


@pytest.fixture()
def app_factory(isolated_api_state: Path, workspace_base: Path):
    """Return create_app callable, ensuring phase registry is reset between tests.

    Depends on ``workspace_base`` so ``PIKA_WORKSPACE_BASE_DIR`` is set before
    ``create_app()`` constructs the ``WorkspaceStore``.
    """
    from api.phase_registry import get_phase_registry
    from api.app import create_app

    # Reset the phase registry so re-registration during create_app() does not raise.
    get_phase_registry().clear()
    return create_app


@pytest.fixture()
def app(app_factory):
    return app_factory()


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
