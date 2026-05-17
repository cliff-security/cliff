"""Tests for the Credential Vault (ADR-0016)."""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING

import pytest

from cliff.db.connection import close_db, init_db
from cliff.integrations.vault import (
    CredentialKeyError,
    CredentialVault,
    _decrypt,
    _encrypt,
    resolve_key,
)

if TYPE_CHECKING:
    import aiosqlite

# A deterministic 32-byte key for testing.
TEST_KEY = os.urandom(32)
TEST_KEY_B64 = base64.b64encode(TEST_KEY).decode()


@pytest.fixture
async def db():
    conn = await init_db(":memory:")
    yield conn
    await close_db()


@pytest.fixture
async def vault(db: aiosqlite.Connection):
    return CredentialVault(db, key=TEST_KEY)


@pytest.fixture
async def integration_id(db: aiosqlite.Connection) -> str:
    """Create a dummy integration_config row and return its ID."""
    iid = "int-test-001"
    await db.execute(
        """
        INSERT INTO integration_config (id, adapter_type, provider_name, enabled, updated_at)
        VALUES (?, 'finding_source', 'test_provider', 1, datetime('now'))
        """,
        (iid,),
    )
    await db.commit()
    return iid


# ---------------------------------------------------------------------------
# Low-level crypto
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_roundtrip():
    key = os.urandom(32)
    plaintext = "super-secret-api-key-12345"
    ct, iv = _encrypt(key, plaintext)
    assert _decrypt(key, ct, iv) == plaintext


def test_different_ivs_per_encryption():
    key = os.urandom(32)
    ct1, iv1 = _encrypt(key, "same-value")
    ct2, iv2 = _encrypt(key, "same-value")
    assert iv1 != iv2
    assert ct1 != ct2


def test_wrong_key_fails_decrypt():
    key1 = os.urandom(32)
    key2 = os.urandom(32)
    ct, iv = _encrypt(key1, "secret")
    with pytest.raises(Exception):  # InvalidTag from cryptography  # noqa: B017
        _decrypt(key2, ct, iv)


def test_tampered_ciphertext_fails():
    key = os.urandom(32)
    ct, iv = _encrypt(key, "secret")
    tampered = bytearray(ct)
    tampered[0] ^= 0xFF
    with pytest.raises(Exception):  # InvalidTag  # noqa: B017
        _decrypt(key, bytes(tampered), iv)


def test_empty_plaintext_handled():
    key = os.urandom(32)
    ct, iv = _encrypt(key, "")
    assert _decrypt(key, ct, iv) == ""


def test_unicode_plaintext_handled():
    key = os.urandom(32)
    plaintext = "p\u00e4ssw\u00f6rd-\U0001f512"
    ct, iv = _encrypt(key, plaintext)
    assert _decrypt(key, ct, iv) == plaintext


# ---------------------------------------------------------------------------
# Key resolution
# ---------------------------------------------------------------------------


def test_env_var_key_provider(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("cliff.integrations.vault._try_keyring", lambda: None)
    monkeypatch.setenv("CLIFF_CREDENTIAL_KEY", TEST_KEY_B64)
    key = resolve_key()
    assert key == TEST_KEY


def test_resolve_raises_when_every_path_fails(monkeypatch: pytest.MonkeyPatch):
    """All three providers must fail before ``resolve_key`` raises.

    The Docker path normally falls through to the file-based provider; this
    test forces that path to fail too (e.g. the data dir is read-only).
    """
    monkeypatch.delenv("CLIFF_CREDENTIAL_KEY", raising=False)
    monkeypatch.setattr("cliff.integrations.vault._try_keyring", lambda: None)
    monkeypatch.setattr("cliff.integrations.vault._try_key_file", lambda: None)
    with pytest.raises(CredentialKeyError):
        resolve_key()


def test_key_must_be_32_bytes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("cliff.integrations.vault._try_keyring", lambda: None)
    short_key = base64.b64encode(b"too-short").decode()
    monkeypatch.setenv("CLIFF_CREDENTIAL_KEY", short_key)
    with pytest.raises(CredentialKeyError, match="32 bytes"):
        resolve_key()


def test_env_var_accepts_urlsafe_base64(monkeypatch: pytest.MonkeyPatch):
    """B31: ``secrets.token_urlsafe(32)``-style keys must decode successfully.

    URL-safe base64 uses ``-``/``_`` in place of ``+``/``/``. The standard
    ``base64.b64decode`` silently strips those chars, yielding the wrong byte
    length and a misleading "must decode to 32 bytes" error. The fix accepts
    both encodings.
    """
    from cliff.integrations.vault import _try_env_var

    monkeypatch.setattr("cliff.integrations.vault._try_keyring", lambda: None)
    raw_bytes = os.urandom(32)
    urlsafe_key = base64.urlsafe_b64encode(raw_bytes).decode()
    # Sanity: a URL-safe encoding of 32 random bytes is overwhelmingly likely
    # to include at least one ``-`` or ``_`` distinct from standard base64.
    monkeypatch.setenv("CLIFF_CREDENTIAL_KEY", urlsafe_key)
    decoded = _try_env_var()
    assert decoded == raw_bytes


def test_env_var_accepts_standard_base64_regression(monkeypatch: pytest.MonkeyPatch):
    """B31 regression: the legacy standard-base64 path must still work."""
    from cliff.integrations.vault import _try_env_var

    monkeypatch.setattr("cliff.integrations.vault._try_keyring", lambda: None)
    raw_bytes = os.urandom(32)
    standard_key = base64.b64encode(raw_bytes).decode()
    monkeypatch.setenv("CLIFF_CREDENTIAL_KEY", standard_key)
    decoded = _try_env_var()
    assert decoded == raw_bytes


def test_env_var_raises_on_garbage(monkeypatch: pytest.MonkeyPatch):
    """B31: garbage input raises ``CredentialKeyError`` with a useful message
    (not silent corruption that gets reported as a length mismatch elsewhere).
    """
    from cliff.integrations.vault import _try_env_var

    monkeypatch.setattr("cliff.integrations.vault._try_keyring", lambda: None)
    monkeypatch.setenv("CLIFF_CREDENTIAL_KEY", "!!! not base64 at all !!!")
    with pytest.raises(CredentialKeyError, match="CLIFF_CREDENTIAL_KEY"):
        _try_env_var()


def test_file_provider_auto_generates_on_first_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """Docker-shaped path: no keyring, no env var, writable data dir → key
    is created at ``<data_dir>/.credential-key`` with mode 0600 and reused
    on subsequent calls.
    """
    monkeypatch.setattr("cliff.integrations.vault._try_keyring", lambda: None)
    monkeypatch.delenv("CLIFF_CREDENTIAL_KEY", raising=False)
    monkeypatch.setenv("CLIFF_DATA_DIR", str(tmp_path))
    # Re-import settings so the env var is picked up by ``resolve_data_dir``.
    from cliff.config import Settings

    fresh = Settings()
    monkeypatch.setattr("cliff.config.settings", fresh)

    key = resolve_key()
    assert len(key) == 32

    key_file = tmp_path / ".credential-key"
    assert key_file.exists()
    # Mode 0600 — owner read+write, no group/other access.
    mode = key_file.stat().st_mode & 0o777
    assert mode == 0o600

    # Subsequent resolves return the same key.
    key2 = resolve_key()
    assert key == key2


def test_file_provider_reads_existing_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """A pre-existing key file (from a prior run / volume mount) is reused."""
    monkeypatch.setattr("cliff.integrations.vault._try_keyring", lambda: None)
    monkeypatch.delenv("CLIFF_CREDENTIAL_KEY", raising=False)
    monkeypatch.setenv("CLIFF_DATA_DIR", str(tmp_path))
    from cliff.config import Settings

    fresh = Settings()
    monkeypatch.setattr("cliff.config.settings", fresh)

    # Pre-write a known key. Header lines (starting with ``#``) must be
    # stripped — the parser is comment-tolerant.
    key_file = tmp_path / ".credential-key"
    key_file.write_text(
        "# Cliff credential vault key — pre-existing\n"
        f"{TEST_KEY_B64}\n"
    )

    assert resolve_key() == TEST_KEY


def test_file_provider_refuses_to_silently_regenerate_corrupt_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    """A wrong-size key file must raise — overwriting it would invalidate
    every credential previously stored under the old key.
    """
    monkeypatch.setattr("cliff.integrations.vault._try_keyring", lambda: None)
    monkeypatch.delenv("CLIFF_CREDENTIAL_KEY", raising=False)
    monkeypatch.setenv("CLIFF_DATA_DIR", str(tmp_path))
    from cliff.config import Settings

    fresh = Settings()
    monkeypatch.setattr("cliff.config.settings", fresh)

    key_file = tmp_path / ".credential-key"
    key_file.write_text(base64.b64encode(b"too-short").decode())

    with pytest.raises(CredentialKeyError, match="refusing to auto-regenerate"):
        resolve_key()


# ---------------------------------------------------------------------------
# Vault CRUD
# ---------------------------------------------------------------------------


async def test_store_and_retrieve(vault: CredentialVault, integration_id: str):
    await vault.store(integration_id, "api_token", "ghp_abc123")
    result = await vault.retrieve(integration_id, "api_token")
    assert result == "ghp_abc123"


async def test_store_overwrites_existing(vault: CredentialVault, integration_id: str):
    cred_id_1 = await vault.store(integration_id, "api_token", "old-value")
    cred_id_2 = await vault.store(integration_id, "api_token", "new-value")
    assert cred_id_1 == cred_id_2  # Same row updated
    assert await vault.retrieve(integration_id, "api_token") == "new-value"


async def test_list_keys_no_values_exposed(vault: CredentialVault, integration_id: str):
    await vault.store(integration_id, "client_id", "id-123")
    await vault.store(integration_id, "client_secret", "secret-456")
    keys = await vault.list_keys(integration_id)
    key_names = {k["key_name"] for k in keys}
    assert key_names == {"client_id", "client_secret"}
    # Ensure no encrypted_value or plaintext leaks.
    for k in keys:
        assert "encrypted_value" not in k
        assert "id-123" not in str(k)
        assert "secret-456" not in str(k)


async def test_has_credential_true(vault: CredentialVault, integration_id: str):
    await vault.store(integration_id, "token", "value")
    assert await vault.has_credential(integration_id, "token") is True


async def test_has_credential_false(vault: CredentialVault, integration_id: str):
    assert await vault.has_credential(integration_id, "nonexistent") is False


async def test_delete_credential(vault: CredentialVault, integration_id: str):
    await vault.store(integration_id, "token", "value")
    assert await vault.delete(integration_id, "token") is True
    assert await vault.has_credential(integration_id, "token") is False


async def test_delete_returns_false_for_nonexistent(vault: CredentialVault, integration_id: str):
    assert await vault.delete(integration_id, "nope") is False


async def test_delete_for_integration(vault: CredentialVault, integration_id: str):
    await vault.store(integration_id, "key_a", "val_a")
    await vault.store(integration_id, "key_b", "val_b")
    count = await vault.delete_for_integration(integration_id)
    assert count == 2
    assert await vault.list_keys(integration_id) == []


async def test_rotate_updates_value_and_timestamp(
    vault: CredentialVault, integration_id: str, db: aiosqlite.Connection
):
    await vault.store(integration_id, "token", "old-secret")
    await vault.rotate(integration_id, "token", "new-secret")
    assert await vault.retrieve(integration_id, "token") == "new-secret"
    # Verify rotated_at was set.
    keys = await vault.list_keys(integration_id)
    assert keys[0]["rotated_at"] is not None


async def test_rotate_nonexistent_raises(vault: CredentialVault, integration_id: str):
    with pytest.raises(KeyError):
        await vault.rotate(integration_id, "nonexistent", "value")


async def test_retrieve_nonexistent_raises(vault: CredentialVault, integration_id: str):
    with pytest.raises(KeyError, match="No credential"):
        await vault.retrieve(integration_id, "nonexistent")


async def test_get_credentials_for_workspace(vault: CredentialVault, integration_id: str):
    await vault.store(integration_id, "client_id", "id-value")
    await vault.store(integration_id, "client_secret", "secret-value")
    creds = await vault.get_credentials_for_workspace(integration_id)
    assert creds == {"client_id": "id-value", "client_secret": "secret-value"}


async def test_unique_constraint_different_integrations(
    vault: CredentialVault, integration_id: str, db: aiosqlite.Connection
):
    """Same key_name under different integrations should not conflict."""
    iid2 = "int-test-002"
    await db.execute(
        """
        INSERT INTO integration_config (id, adapter_type, provider_name, enabled, updated_at)
        VALUES (?, 'ticketing', 'jira', 1, datetime('now'))
        """,
        (iid2,),
    )
    await db.commit()

    await vault.store(integration_id, "api_token", "value-a")
    await vault.store(iid2, "api_token", "value-b")
    assert await vault.retrieve(integration_id, "api_token") == "value-a"
    assert await vault.retrieve(iid2, "api_token") == "value-b"


async def test_cascade_delete_on_integration_delete(
    vault: CredentialVault, integration_id: str, db: aiosqlite.Connection
):
    """Deleting an integration_config row should cascade-delete its credentials."""
    await vault.store(integration_id, "token", "secret")
    assert await vault.has_credential(integration_id, "token") is True

    await db.execute("DELETE FROM integration_config WHERE id = ?", (integration_id,))
    await db.commit()

    # Credential should be gone due to ON DELETE CASCADE.
    assert await vault.has_credential(integration_id, "token") is False


async def test_vault_wrong_key_size(db: aiosqlite.Connection):
    with pytest.raises(CredentialKeyError, match="32 bytes"):
        CredentialVault(db, key=b"short")
