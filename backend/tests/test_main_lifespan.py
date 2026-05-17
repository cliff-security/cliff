"""Tests for the credential-vault init slice of ``cliff.main`` (B32).

The full app lifespan spins up DB, OpenCode processes, etc., so we test the
small ``_init_vault`` helper in isolation: it must

1. Set ``app.state.vault`` to a constructed ``CredentialVault`` on success.
2. On ``CredentialKeyError``, leave ``app.state.vault = None`` and log the
   actual exception message at WARNING (not the generic "set
   CLIFF_CREDENTIAL_KEY" line that hides the real reason).
3. On any other ``Exception``, leave ``app.state.vault = None`` and log
   with ``exc_info=True`` so the traceback reaches the operator.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from cliff.integrations.vault import CredentialKeyError

if TYPE_CHECKING:
    import pytest


def test_init_vault_success_sets_state(monkeypatch: pytest.MonkeyPatch):
    from cliff import main

    fake_vault = MagicMock(name="CredentialVault")
    monkeypatch.setattr(main, "CredentialVault", lambda db: fake_vault)

    app = SimpleNamespace(state=SimpleNamespace(vault=None))
    main._init_vault(app, db=MagicMock(name="db"))
    assert app.state.vault is fake_vault


def test_init_vault_credential_key_error_logs_actual_reason(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """B32: when ``CredentialKeyError`` is raised the warning must contain the
    actual exception message — not the generic "set CLIFF_CREDENTIAL_KEY"
    line that masks key-format problems.
    """
    from cliff import main

    def _raise(_db: object) -> object:
        msg = "CLIFF_CREDENTIAL_KEY is not valid base64: bad padding"
        raise CredentialKeyError(msg)

    monkeypatch.setattr(main, "CredentialVault", _raise)

    app = SimpleNamespace(state=SimpleNamespace(vault=None))
    with caplog.at_level(logging.WARNING, logger="cliff.main"):
        main._init_vault(app, db=MagicMock(name="db"))

    assert app.state.vault is None
    combined = " ".join(rec.getMessage() for rec in caplog.records)
    # The actual error message must reach the operator.
    assert "CLIFF_CREDENTIAL_KEY is not valid base64: bad padding" in combined


def test_init_vault_unexpected_error_logs_with_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """B32: non-CredentialKeyError must be logged with traceback (exc_info=True)
    so operators see what went wrong instead of a silent swallow.
    """
    from cliff import main

    def _raise(_db: object) -> object:
        msg = "unexpected database failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(main, "CredentialVault", _raise)

    app = SimpleNamespace(state=SimpleNamespace(vault=None))
    with caplog.at_level(logging.WARNING, logger="cliff.main"):
        main._init_vault(app, db=MagicMock(name="db"))

    assert app.state.vault is None
    # The traceback is attached when ``exc_info=True`` is passed to logger.
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning_records, "expected at least one WARNING log record"
    assert any(r.exc_info is not None for r in warning_records), (
        "expected the unexpected-error warning to attach exc_info for a traceback"
    )
