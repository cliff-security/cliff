"""AgentRunLog — append-only JSONL log for agent run history."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


class AgentRunLog:
    """Append-only JSONL log for agent run events within a workspace."""

    def __init__(self, log_path: Path) -> None:
        self._path = log_path

    def append(
        self,
        *,
        agent_type: str,
        status: str,
        started_at: str | None = None,
        completed_at: str | None = None,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append an agent run entry to the log.

        Each entry is a single JSON line with an auto-generated timestamp.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "agent_type": agent_type,
            "status": status,
        }
        if started_at is not None:
            entry["started_at"] = started_at
        if completed_at is not None:
            entry["completed_at"] = completed_at
        if summary is not None:
            entry["summary"] = summary
        if metadata is not None:
            entry["metadata"] = metadata

        with self._path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def read_all(self) -> list[dict[str, Any]]:
        """Read all entries from the log. Returns empty list if file is empty."""
        if not self._path.exists():
            return []

        entries: list[dict[str, Any]] = []
        for line in self._path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Skipping corrupted JSONL line in %s", self._path)
        return entries

    def read_latest(self, n: int = 10) -> list[dict[str, Any]]:
        """Read the N most recent entries."""
        all_entries = self.read_all()
        return all_entries[-n:]
