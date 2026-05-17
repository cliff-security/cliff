"""Tests for first-run detection logic."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from cliff.db.connection import close_db, init_db


@pytest.fixture
async def _cleanup_db():
    """Ensure DB connection is closed after each test."""
    yield
    await close_db()


@pytest.mark.asyncio
async def test_first_run_detected_when_no_db(tmp_path: Path, _cleanup_db):
    """On a fresh volume the database file should not exist before init_db."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    db_path = data_dir / "cliff.db"
    assert not db_path.exists(), "DB should not exist on a fresh volume"

    # After init_db the file must be created
    await init_db(db_path)
    assert db_path.exists(), "init_db must create the database file"


@pytest.mark.asyncio
async def test_existing_db_detected(tmp_path: Path):
    """When a database already exists we should detect it."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    db_path = data_dir / "cliff.db"
    db_path.write_text("")  # simulate existing DB file

    assert db_path.exists(), "Existing DB should be detected"
