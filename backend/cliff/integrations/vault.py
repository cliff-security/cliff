"""Credential Vault — AES-256-GCM encrypted secret storage (ADR-0016).

Encryption key resolution priority:
1. System keyring (macOS Keychain, GNOME Keyring, Windows Credential Manager)
2. CLIFF_CREDENTIAL_KEY environment variable (base64-encoded 32 bytes)
3. File at ``<data_dir>/.credential-key`` — auto-generated on first run when
   keyring + env aren't available (the Docker path). Written 0600.
4. Raises CredentialKeyError — only when none of the above work AND the data
   directory isn't writable.

The file-based path means a fresh Docker run "just works" without the operator
having to set ``CLIFF_CREDENTIAL_KEY``. The key is generated once and lives
in the persistent data volume, so credentials survive container restarts. To
rotate the key, delete the file — but that invalidates every stored
credential, so it's a deliberate operator action.

Credentials are encrypted per-value with random 12-byte IVs and stored in the
``credential`` table. The vault never exposes plaintext via API — only internal
methods (workspace config generation) can decrypt.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cliff.db import repo_credential

if TYPE_CHECKING:
    from pathlib import Path

    import aiosqlite

logger = logging.getLogger(__name__)

_KEYRING_SERVICE = "cliff"
_KEYRING_USERNAME = "credential-vault-key"
_KEY_LENGTH = 32  # AES-256
_KEY_FILE_NAME = ".credential-key"


class CredentialKeyError(Exception):
    """Raised when no encryption key can be resolved."""


# ---------------------------------------------------------------------------
# Low-level crypto helpers
# ---------------------------------------------------------------------------


def _encrypt(key: bytes, plaintext: str) -> tuple[bytes, bytes]:
    """Encrypt *plaintext* with AES-256-GCM. Returns (ciphertext, iv)."""
    iv = os.urandom(12)  # 96-bit IV recommended for GCM
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    return ciphertext, iv


def _decrypt(key: bytes, ciphertext: bytes, iv: bytes) -> str:
    """Decrypt *ciphertext* with AES-256-GCM. Returns plaintext string."""
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(iv, ciphertext, None).decode("utf-8")


# ---------------------------------------------------------------------------
# Key resolution
# ---------------------------------------------------------------------------


def _try_keyring() -> bytes | None:
    """Attempt to load or generate a key from the system keyring."""
    try:
        import keyring as kr  # noqa: PLC0415
    except ImportError:
        return None

    try:
        stored = kr.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        if stored:
            return base64.b64decode(stored)
        # First run — generate and store a random key.
        new_key = os.urandom(_KEY_LENGTH)
        kr.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, base64.b64encode(new_key).decode())
        logger.info("Generated new credential vault key in system keyring")
        return new_key
    except Exception:
        logger.debug("System keyring unavailable", exc_info=True)
        return None


def _try_env_var() -> bytes | None:
    """Read a base64-encoded key from CLIFF_CREDENTIAL_KEY.

    Accepts BOTH URL-safe (``-``/``_``) and standard (``+``/``/``) base64
    alphabets. ``secrets.token_urlsafe(32)`` — the natural Python idiom — emits
    URL-safe output, but plain ``base64.b64decode`` silently strips ``-``/``_``
    chars (its default ``validate=False`` behaviour), yielding the wrong byte
    length and a misleading "must decode to 32 bytes" error. We try URL-safe
    first and fall back to strict standard base64 so operators get a precise
    error on real garbage instead of a length-mismatch red herring (B31).
    """
    raw = os.environ.get("CLIFF_CREDENTIAL_KEY", "").strip()
    if not raw:
        return None
    try:
        key = base64.urlsafe_b64decode(raw)
    except (ValueError, binascii.Error):
        try:
            key = base64.b64decode(raw, validate=True)
        except (ValueError, binascii.Error) as exc:
            msg = f"CLIFF_CREDENTIAL_KEY is not valid base64: {exc}"
            raise CredentialKeyError(msg) from exc
    if len(key) != _KEY_LENGTH:
        msg = f"CLIFF_CREDENTIAL_KEY must decode to {_KEY_LENGTH} bytes, got {len(key)}"
        raise CredentialKeyError(msg)
    return key


def _resolve_key_file_path() -> Path | None:
    """Return ``<data_dir>/.credential-key`` if the data dir is writable.

    Imported lazily so this module doesn't pull in app config at import time
    (and so tests can override the data dir via env vars before this fires).
    Returns ``None`` if the data dir can't be created — the caller falls
    through to the explicit error path.
    """
    try:
        from cliff.config import settings  # late import — see docstring

        data_dir = settings.resolve_data_dir()
    except Exception:  # pragma: no cover — defensive
        logger.debug("could not resolve data dir for credential key file", exc_info=True)
        return None
    return data_dir / _KEY_FILE_NAME


def _try_key_file() -> bytes | None:
    """Read or auto-generate ``<data_dir>/.credential-key``.

    On first run the file does not exist; we generate a 32-byte random key,
    write it with permissions ``0600``, and return it. On subsequent runs the
    file is read back and decoded. A short, non-secret marker line at the top
    explains the file's purpose so the next operator who finds it knows what
    they're looking at.
    """
    path = _resolve_key_file_path()
    if path is None:
        return None

    if path.exists():
        try:
            content = path.read_text().strip()
            # Strip any header lines we wrote (commented with ``#``); accept
            # the first non-comment, non-empty line as the base64 key.
            lines = [
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            if not lines:
                msg = f"credential key file {path} is empty"
                raise CredentialKeyError(msg)
            key = base64.b64decode(lines[0])
            if len(key) != _KEY_LENGTH:
                msg = (
                    f"credential key file {path} must decode to "
                    f"{_KEY_LENGTH} bytes, got {len(key)} — refusing to "
                    "auto-regenerate (would invalidate existing credentials). "
                    "Either restore a valid key or delete the file to start over."
                )
                raise CredentialKeyError(msg)
            return key
        except CredentialKeyError:
            raise
        except Exception as exc:
            logger.warning("could not read credential key file %s: %s", path, exc)
            return None

    # First run — generate and persist.
    new_key = os.urandom(_KEY_LENGTH)
    encoded = base64.b64encode(new_key).decode()
    body = (
        "# Cliff credential vault key — auto-generated on first run.\n"
        "# Do not edit, share, or commit this file. Deleting it invalidates\n"
        "# every credential stored in this Cliff instance.\n"
        "#\n"
        "# To rotate: stop Cliff, delete this file, restart, then re-enter\n"
        "# any integration credentials from Settings.\n"
        f"{encoded}\n"
    )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically via a temp file so a crash mid-write doesn't leave
        # a half-written key on disk.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(body)
        os.chmod(tmp, 0o600)
        tmp.replace(path)
        logger.info(
            "Generated new credential vault key at %s (0600). "
            "This file is now the source of truth for the credential vault.",
            path,
        )
        return new_key
    except OSError as exc:
        logger.warning("could not write credential key file %s: %s", path, exc)
        return None


def resolve_key() -> bytes:
    """Resolve encryption key via priority chain. Raises CredentialKeyError on failure.

    Priority order is deliberate: an explicit user-provided key (env var,
    written by the native installer to ``~/.cliff/config/cliff.env``)
    must beat any auto-discovered keyring entry. Otherwise:

    * The native installer would write a stable key to its env file but the
      daemon would generate a different one in the macOS Keychain on first
      start, then any credentials persisted under the keyring-generated key
      would be undecryptable after a restart that no longer hits Keychain
      (e.g. headless cron, CI, ssh session without a login keychain).
    * Docker users are unaffected: D-Bus / Keychain isn't available in the
      container so _try_keyring() returned None first either way.
    """
    key = _try_env_var()
    if key is not None:
        return key

    key = _try_keyring()
    if key is not None:
        return key

    key = _try_key_file()
    if key is not None:
        return key

    msg = (
        "No credential encryption key configured and could not auto-generate one. "
        "Set CLIFF_CREDENTIAL_KEY (base64-encoded 32 bytes), install the "
        "'keyring' package, or ensure the data directory is writable so Cliff "
        f"can persist a key at <data_dir>/{_KEY_FILE_NAME}."
    )
    raise CredentialKeyError(msg)


# ---------------------------------------------------------------------------
# CredentialVault
# ---------------------------------------------------------------------------


class CredentialVault:
    """Manages encrypted credential storage for integrations."""

    def __init__(self, db: aiosqlite.Connection, key: bytes | None = None) -> None:
        self._db = db
        self._key = key if key is not None else resolve_key()
        if len(self._key) != _KEY_LENGTH:
            msg = f"Encryption key must be {_KEY_LENGTH} bytes, got {len(self._key)}"
            raise CredentialKeyError(msg)

    async def store(self, integration_id: str, key_name: str, plaintext: str) -> str:
        """Encrypt and store a credential. Overwrites if (integration_id, key_name) exists.

        Returns the credential row ID.
        """
        ciphertext, iv = _encrypt(self._key, plaintext)

        existing = await repo_credential.get_credential(self._db, integration_id, key_name)
        if existing:
            await repo_credential.update_credential(
                self._db, integration_id, key_name, ciphertext, iv
            )
            return existing["id"]

        return await repo_credential.create_credential(
            self._db, integration_id, key_name, ciphertext, iv
        )

    async def retrieve(self, integration_id: str, key_name: str) -> str:
        """Decrypt and return a credential value. Raises KeyError if not found."""
        row = await repo_credential.get_credential(self._db, integration_id, key_name)
        if row is None:
            msg = f"No credential '{key_name}' for integration '{integration_id}'"
            raise KeyError(msg)
        return _decrypt(self._key, bytes(row["encrypted_value"]), bytes(row["iv"]))

    async def delete(self, integration_id: str, key_name: str) -> bool:
        """Delete a single credential. Returns True if it existed."""
        return await repo_credential.delete_credential(self._db, integration_id, key_name)

    async def delete_for_integration(self, integration_id: str) -> int:
        """Delete all credentials for an integration. Returns count deleted."""
        return await repo_credential.delete_credentials_for_integration(
            self._db, integration_id
        )

    async def list_keys(self, integration_id: str) -> list[dict]:
        """List credential metadata (key_name, created_at, rotated_at) — no values."""
        return await repo_credential.list_credential_keys(self._db, integration_id)

    async def has_credential(self, integration_id: str, key_name: str) -> bool:
        """Check whether a credential exists."""
        row = await repo_credential.get_credential(self._db, integration_id, key_name)
        return row is not None

    async def rotate(self, integration_id: str, key_name: str, new_plaintext: str) -> None:
        """Re-encrypt a credential with a new value. Raises KeyError if not found."""
        existing = await repo_credential.get_credential(self._db, integration_id, key_name)
        if existing is None:
            msg = f"No credential '{key_name}' for integration '{integration_id}'"
            raise KeyError(msg)
        ciphertext, iv = _encrypt(self._key, new_plaintext)
        await repo_credential.update_credential(
            self._db, integration_id, key_name, ciphertext, iv
        )

    async def get_credentials_for_workspace(self, integration_id: str) -> dict[str, str]:
        """Decrypt all credentials for an integration. Used for workspace config injection."""
        keys = await repo_credential.list_credential_keys(self._db, integration_id)
        result: dict[str, str] = {}
        for key_info in keys:
            result[key_info["key_name"]] = await self.retrieve(integration_id, key_info["key_name"])
        return result
