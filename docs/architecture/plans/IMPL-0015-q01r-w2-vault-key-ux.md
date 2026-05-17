# IMPL-0015: Q01R Wave 2 — vault key UX + visible init errors

**Scope:** Wave 2 (Q01R-W2) bug fixes — vault key cluster
**Bugs:** B31 (P0), B32 (P1)
**Owner:** App Builder (V2) — `backend/opensec/integrations/vault.py` + `backend/opensec/main.py`
**Status:** Draft — needs CEO approval
**Date:** 2026-05-17

## Summary

Two bugs share the same broken code path:

- **B31 (P0)** — Vault rejects URL-safe base64 keys silently. `OPENSEC_CREDENTIAL_KEY` from the natural Python idiom `secrets.token_urlsafe(32)` triggers `CredentialKeyError` because `base64.b64decode` silently strips `-`/`_` chars, producing the wrong byte length.
- **B32 (P1)** — The bare `except Exception` in `main.py:154` swallows that error and emits a misleading warning ("set OPENSEC_CREDENTIAL_KEY") *even when the env var IS set*. Every credential-protected route then 503s. Diagnostic time: 10+ minutes per first-time user.

Both fixes are tiny and one PR. "Delete before adding" principle in spirit — we're not adding new code paths, we're fixing the two lines that obscure the real failure mode.

## Root causes (grounded in code)

| Bug | File:line | Current | Required |
|---|---|---|---|
| B31 | `backend/opensec/integrations/vault.py:97-103` `_try_env_var()` | `base64.b64decode(raw)` with default behavior silently discards `-`/`_` chars | Accept BOTH standard and URL-safe base64; raise `CredentialKeyError` with a specific message on actual decode failure (not silent corruption) |
| B32 | `backend/opensec/main.py:148-155` lifespan vault init | `except Exception: logger.warning("Credential vault not available — set OPENSEC_CREDENTIAL_KEY to enable")` — same message for "not set" and "set but bad" | Type-discriminate the except: `CredentialKeyError` → log the actual reason; other `Exception` → log with `exc_info=True` |

## Files touched

Backend (V2):
- `backend/opensec/integrations/vault.py` — `_try_env_var()`: try `urlsafe_b64decode` first, fall back to `b64decode(validate=True)`; on both fail raise `CredentialKeyError` with the original exception message
- `backend/opensec/main.py` — split the bare `except Exception` into `except CredentialKeyError` (log the reason) + `except Exception` (log with `exc_info=True`)

Tests (V2):
- `backend/tests/integrations/test_vault.py` (or wherever vault tests live — grep for it) — add three cases:
  1. URL-safe base64 key decodes successfully
  2. Standard base64 key still decodes successfully (regression)
  3. Garbage env var raises `CredentialKeyError` with a useful message (not silent)
- `backend/tests/test_main_lifespan.py` (or extend existing main lifespan test) — when `CredentialKeyError` is raised, the warning log contains the actual exception message (assert via `caplog`)

## Test plan (TDD-first)

Write first:
```python
# test_vault.py
def test_try_env_var_accepts_urlsafe_base64(monkeypatch):
    monkeypatch.setenv("OPENSEC_CREDENTIAL_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    assert len(_try_env_var()) == 32

def test_try_env_var_accepts_standard_base64(monkeypatch):
    monkeypatch.setenv("OPENSEC_CREDENTIAL_KEY", base64.b64encode(os.urandom(32)).decode())
    assert len(_try_env_var()) == 32

def test_try_env_var_raises_on_garbage(monkeypatch):
    monkeypatch.setenv("OPENSEC_CREDENTIAL_KEY", "this-is-not-a-base64-key-at-all-too-short")
    with pytest.raises(CredentialKeyError, match="OPENSEC_CREDENTIAL_KEY"):
        _try_env_var()
```

Then implement.

E2E (manual, captured by Wave 3 re-run):
- Run a fresh Docker with `OPENSEC_CREDENTIAL_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')` — vault initializes, `/api/integrations/github/connect` returns 200 (not 503)
- Same Docker with `OPENSEC_CREDENTIAL_KEY=garbage` — vault doesn't initialize but `docker logs` shows a specific "OPENSEC_CREDENTIAL_KEY is not valid base64" line, not "set OPENSEC_CREDENTIAL_KEY to enable"

## Risks

- **Trivial.** No behavior change for users who already use standard base64. URL-safe just newly works. Error messages get more specific.

## Rollout

Single PR, 2 commits:
1. `fix(q01r-w2): accept url-safe base64 for OPENSEC_CREDENTIAL_KEY (B31)`
2. `fix(q01r-w2): surface vault init exception with exc_info (B32)`

Target branch: `main`.
