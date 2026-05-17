# ADR-0016: Credential Vault for Encrypted Secret Storage

**Date:** 2026-03-31
**Status:** Accepted

## Context

Cliff integrations require credentials to authenticate with external systems: API keys, OAuth tokens, client secrets, personal access tokens. These credentials protect access to systems that guard entire organizations — Wiz, CrowdStrike, Jira, GitHub. Mishandling them would be catastrophic for user trust.

Today, `IntegrationConfig.config` stores credentials as a JSON blob in SQLite with no encryption. This was acceptable for MVP with mock adapters (ADR-0006), but real integrations demand production-grade secret management.

The threat model for a self-hosted security tool is distinct from cloud SaaS:

- The SQLite database file sits on the user's machine (or Docker volume). Anyone with file access can read plaintext secrets.
- Backup and migration flows could inadvertently expose credentials.
- Debug logging or error messages could leak credential values.
- The AI engine (OpenCode/LLM) must never see raw credentials in its context window.

We considered several approaches:

1. **External secrets manager (HashiCorp Vault, AWS Secrets Manager)** — Enterprise-grade but adds a heavy dependency for a self-hosted single-user tool. Overkill for community edition.
2. **System keyring only (GNOME Keyring, macOS Keychain)** — OS-native encryption but not available in all environments (Docker containers, headless servers).
3. **Application-level encryption in SQLite** — AES-256-GCM encryption before storing in the database. Key from system keyring, env var, or user passphrase. Works everywhere.
4. **SQLCipher (full database encryption)** — Encrypts the entire SQLite database. Protects all data, not just credentials. But adds a compiled dependency and encrypts data that doesn't need encryption (findings, chat history).

## Decision

Implement an application-level Credential Vault that encrypts individual credential values using AES-256-GCM before storing them in a dedicated `credential` table in SQLite.

Key design choices:

1. **Per-credential encryption.** Each credential gets its own random initialization vector (IV). Compromise of one encrypted blob doesn't help decrypt others.

2. **Key derivation priority chain:**
   - **System keyring** (GNOME Keyring, macOS Keychain, Windows Credential Manager) — preferred for desktop installs. Key stored in OS-managed secure storage.
   - **`CLIFF_CREDENTIAL_KEY` environment variable** — preferred for Docker/server deployments. Set once in `docker-compose.yml` or systemd unit.
   - **User passphrase with PBKDF2** — fallback. Prompted on first integration setup. Derived key cached in memory for the session.

3. **Credential injection at transport layer.** When a workspace starts, the MCP Gateway decrypts credentials and writes them into the workspace's `opencode.json` environment variables. The LLM context never contains raw credentials. Workspace directories are ephemeral and file-permission restricted.

4. **No credential export.** Credentials cannot be retrieved, viewed, or exported after initial entry. Only "test connection" and "update" operations are supported.

5. **No credential values in logs.** Audit events log `parameters_hash` (SHA-256 of parameters), never raw values. Error messages are sanitized to strip auth headers and tokens.

6. **Database schema:**
   ```sql
   CREATE TABLE credential (
       id TEXT PRIMARY KEY,
       integration_id TEXT NOT NULL REFERENCES integration_config(id),
       key_name TEXT NOT NULL,
       encrypted_value BLOB NOT NULL,
       iv BLOB NOT NULL,
       created_at TEXT NOT NULL,
       rotated_at TEXT,
       UNIQUE(integration_id, key_name)
   );
   ```

7. **Token lifetime awareness.** Different vendors have different token lifetimes (Wiz ~24h, CrowdStrike ~30min). The vault supports a TTL-aware caching layer for OAuth tokens with automatic refresh before expiry.

## Consequences

- **Easier:** Credentials are encrypted at rest in all deployment scenarios (desktop, Docker, server). No external infrastructure dependency.
- **Easier:** The priority chain means the vault works out-of-the-box in any environment without configuration. System keyring for desktop, env var for Docker, passphrase as fallback.
- **Easier:** Credential injection at config-generation time means zero changes to OpenCode — it just reads environment variables from its config file.
- **Harder:** If the encryption key is lost (keyring reset, env var deleted, passphrase forgotten), all encrypted credentials become irrecoverable. Users must re-enter them. We accept this trade-off — recoverability of the key would weaken the security model.
- **Harder:** Credentials in workspace `opencode.json` are in plaintext (OpenCode doesn't support vault integration). Mitigated by ephemeral directories, restricted file permissions, and regeneration on every process start.
- **Harder:** Multi-user edition (future) will need per-user credential namespacing. The current single-tenant design is intentionally simple (ADR-0009). We'll add namespacing when we build multi-user support.
