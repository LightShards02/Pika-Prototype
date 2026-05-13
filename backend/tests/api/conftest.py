"""Shared fixtures for backend/tests/api/."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Generator

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
def ws1_dir(tmp_path: Path) -> Path:
    """Materialize a fresh copy of the ws1 fixture and return its path."""
    dest = tmp_path / "ws1"
    shutil.copytree(_FIXTURE_WS1, dest)
    return dest.resolve()


@pytest.fixture()
def app_factory(isolated_api_state: Path):
    """Return create_app callable, ensuring phase registry is reset between tests."""
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
