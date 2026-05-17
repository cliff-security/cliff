"""DAO modules for the EXEC-0002 tables (assessment, completion).

Keeps the new-tables CRUD separate from the legacy ``repo_*`` modules so Session B's
owns list is unambiguous. Style mirrors ``repo_finding.py``: module-level async
functions taking an ``aiosqlite.Connection``, ``_row_to_*`` helpers, JSON-encoded
columns serialized with ``json.dumps``/``json.loads``, UUID ids, UTC ISO timestamps.

PR-B (IMPL-0003-p2 Phase 2) deletes ``posture_check.py`` from this package —
posture rows now live in the unified ``finding`` table per ADR-0027.
"""
