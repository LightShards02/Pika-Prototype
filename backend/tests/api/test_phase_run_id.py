"""Unit tests for api.jobs.generate_phase_run_id strict monotonicity."""

from __future__ import annotations

from datetime import datetime

import pytest

from api import jobs
from api.jobs import generate_phase_run_id


@pytest.fixture(autouse=True)
def _reset_counter():
    jobs._last_second = None
    jobs._counter = 0
    yield
    jobs._last_second = None
    jobs._counter = 0


def test_generate_phase_run_id_unique_and_strictly_increasing() -> None:
    ids = [generate_phase_run_id() for _ in range(50)]
    assert len(set(ids)) == len(ids)
    for prev, curr in zip(ids, ids[1:]):
        assert curr > prev


def test_generate_phase_run_id_strictly_increasing_with_frozen_now() -> None:
    frozen = datetime(2026, 5, 6, 12, 0, 0).astimezone()
    ids = [generate_phase_run_id(now=frozen) for _ in range(5)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 5
    for value in ids:
        assert value.startswith("20260506-")
    suffixes = [int(v.rsplit("-", 1)[-1], 16) for v in ids]
    assert suffixes == [0, 1, 2, 3, 4]


def test_generate_phase_run_id_resets_counter_on_new_second() -> None:
    t1 = datetime(2026, 5, 6, 12, 0, 0).astimezone()
    t2 = datetime(2026, 5, 6, 12, 0, 1).astimezone()
    a = generate_phase_run_id(now=t1)
    b = generate_phase_run_id(now=t1)
    c = generate_phase_run_id(now=t2)
    assert a.endswith("-0000")
    assert b.endswith("-0001")
    assert c.endswith("-0000")


def test_generate_phase_run_id_raises_when_counter_exhausted() -> None:
    frozen = datetime(2026, 5, 6, 12, 0, 0).astimezone()
    jobs._last_second = frozen.strftime("%Y%m%d-%H%M%S")
    jobs._counter = 0xFFFF
    with pytest.raises(RuntimeError, match="counter exhausted"):
        generate_phase_run_id(now=frozen)
