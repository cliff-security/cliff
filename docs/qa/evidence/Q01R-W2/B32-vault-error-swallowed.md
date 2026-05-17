# Q01R-W2-B32 — Vault init error swallowed with misleading message

**Severity:** P1
**Surface:** backend (`backend/opensec/main.py:148-155`)

## What I observed
When `CredentialVault(...)` raises (e.g. due to B31's URL-safe base64 issue), the lifespan code catches `Exception` and logs:
```
[WARNING] opensec.main: Credential vault not available — set OPENSEC_CREDENTIAL_KEY to enable
```
…regardless of the actual cause. The message implies the env var isn't set, even when it IS set but the value is invalid. `exc_info=True` is not used — the original exception is lost.

## Fix
```python
try:
    app.state.vault = CredentialVault(db_connection._db)
    logger.info("Credential vault initialized")
except CredentialKeyError as exc:
    logger.warning("Credential vault not configured: %s", exc)
except Exception:
    logger.warning("Credential vault failed to initialize", exc_info=True)
```

## Impact
Doubles the debug time on B31 (and any other vault-init regression). The single misleading log line is what made me waste 10 minutes thinking my env var wasn't reaching the container.
