# Q01R-W2-B31 — Vault rejects URL-safe base64 keys silently, claiming key isn't set

**Severity:** P0
**Surface:** backend (`backend/opensec/integrations/vault.py`)

## What I observed
Set `OPENSEC_CREDENTIAL_KEY` to a key generated via `secrets.token_urlsafe(32)` — the natural Python idiom and what most operators reach for. Startup logs:
```
[WARNING] opensec.main: Credential vault not available — set OPENSEC_CREDENTIAL_KEY to enable
```
…even though the env var was clearly set (`docker exec env` confirmed). Every credential-protected route then returned `503 Service Unavailable` with body `{"detail":"Credential vault or audit logger unavailable."}`. Onboarding step 1 (`POST /api/integrations/github/connect`) was completely blocked.

## Root cause
`backend/opensec/integrations/vault.py:_try_env_var()` (line ~95) does:
```python
key = base64.b64decode(raw)
if len(key) != _KEY_LENGTH:
    raise CredentialKeyError(...)
```

Standard `base64.b64decode()` silently discards URL-safe chars (`-`, `_`) when `validate=False` (default). A `secrets.token_urlsafe(32)` value is 43 chars and contains them; after silent stripping, decoding yields the wrong length → `CredentialKeyError`. 

The exception is then caught in `backend/opensec/main.py:154` by a generic `except Exception` that emits the same misleading warning for ALL failure modes (not set, wrong format, can't decode, etc.), without `exc_info=True`.

## Two fixes (one per bug class)

### B31a (vault) — accept both standard and URL-safe base64
```python
def _try_env_var() -> bytes | None:
    raw = os.environ.get("OPENSEC_CREDENTIAL_KEY", "").strip()
    if not raw:
        return None
    try:
        key = base64.urlsafe_b64decode(raw)
    except Exception:
        try:
            key = base64.b64decode(raw, validate=True)
        except Exception as exc:
            raise CredentialKeyError(f"OPENSEC_CREDENTIAL_KEY is not valid base64: {exc}") from exc
    if len(key) != _KEY_LENGTH:
        raise CredentialKeyError(...)
    return key
```

### B31b (main.py) — surface the actual exception (Q01R-W2-B32)
```python
try:
    app.state.vault = CredentialVault(...)
    logger.info("Credential vault initialized")
except CredentialKeyError as exc:
    logger.warning("Credential vault not configured: %s", exc)
except Exception:
    logger.warning("Credential vault failed to initialize", exc_info=True)
```

## Workaround for the QA
Regenerated the key with `base64.b64encode(os.urandom(32))` (standard base64) — vault loads fine.

## Impact
Every fresh-Docker user who follows a Python-idiomatic key-generation pattern hits this. Documentation says only "base64-encoded 32 bytes" — doesn't disambiguate standard vs URL-safe. Combined with the misleading warning, debug time is significant.
