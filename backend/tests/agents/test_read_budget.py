"""Read/grep budget — bounds cumulative tool output so a large real repo can't
overflow the model context window (ADR-0052; the 200K crash from the first live run)."""

from __future__ import annotations

from types import SimpleNamespace

from cliff.agents.runtime.deps import ReadBudget, WorkspaceDeps
from cliff.agents.runtime.tools.grep import grep
from cliff.agents.runtime.tools.read import read


def test_read_budget_take():
    b = ReadBudget(10)
    assert b.take(7) is True
    assert b.remaining == 3
    assert b.take(5) is True  # allowed (was > 0), may overshoot
    assert b.remaining == -2
    assert b.take(1) is False  # now exhausted


def _ctx(tmp_path, budget):
    deps = WorkspaceDeps(
        workspace_id="t", workspace_dir=str(tmp_path), finding={}, read_budget=budget
    )
    return SimpleNamespace(deps=deps)


async def test_read_stops_once_budget_spent(tmp_path):
    (tmp_path / "f.txt").write_text("x" * 100)
    ctx = _ctx(tmp_path, ReadBudget(50))
    first = await read(ctx, "f.txt")
    assert first.startswith("x")  # first read goes through (budget was > 0)
    second = await read(ctx, "f.txt")
    assert "budget exhausted" in second  # budget now spent → refused


async def test_no_budget_is_unlimited(tmp_path):
    (tmp_path / "f.txt").write_text("y" * 100)
    ctx = _ctx(tmp_path, None)  # the executor's case — unchanged behaviour
    for _ in range(5):
        out = await read(ctx, "f.txt")
        assert out.startswith("y")


async def test_grep_respects_budget(tmp_path):
    (tmp_path / "a.py").write_text("needle here\n")
    ctx = _ctx(tmp_path, ReadBudget(5))
    first = await grep(ctx, "needle")
    assert "a.py" in first  # first grep returns matches
    second = await grep(ctx, "needle")
    assert "budget exhausted" in second
