# IMPL-0019: Q01R Wave 3 — push-access runtime probe (tactical fix for B37)

**Scope:** Wave 3 (Q01R-W3) — make `check_repo_push_access` return ground truth at the git-protocol layer.
**Bug:** B37 (P0 for the "real PR via UI alone" goal)
**Owner:** App Builder (V2) — `backend/cliff/integrations/github_app/client.py`
**Status:** Draft — needs CEO approval
**Date:** 2026-05-18

## Note on numbering

The Wave 3 rerun doc (PR #177) and IMPL-0017's Risks section both referenced **IMPL-0019 = installation tokens** as the structural fix. After triage, the architect verdict is: **runtime probe first (this plan, IMPL-0019), installation tokens later (will become IMPL-0021)**. The runtime probe is cheaper to ship and gives ground truth that installation tokens alone don't (an installation token's *declared* permissions and what `git push` *actually* does over HTTPS are still two different things). The probe remains useful even after installation tokens land.

## Summary

PR-C's `check_repo_push_access` has 17 return paths. Multiple of them return `can_push=True` based on indirect signals (user's permissions on the repo, App's declared permissions on the installation, etc.) without ever verifying that the stored token can actually push a commit. Wave 3 QA hit the worst case: user-perms fallback said `push=true`; actual `git push` failed silently inside the executor; UI surfaced the failure correctly via PR-C's `executor_failed` stage, but no PR landed on cliff-security/NodeGoat.

**Simplest correct fix: a runtime probe.** Before returning `can_push=True`, run `git push --dry-run <https-with-token-url> HEAD:refs/heads/cliff-push-probe` against the configured repo. The `--dry-run` flag tells git to perform the full ref-negotiation handshake with the remote (which is where the server enforces push permission) but to skip the pack upload. If the negotiation succeeds, the token can push. If it returns `403`, `permission denied`, `unauthorized`, or any non-zero exit, return `can_push=False` with a precise reason. ~30 lines + 3 tests.

This is the cheaper of the two mitigations IMPL-0017's Risks block named:

> If user token can't call [/installation], fall back to: mint an installation token using the App private key (deferred — needs IMPL-0019 ADR work) OR add a runtime probe (push a scratch ref, revert).

We pick the probe. `git push --dry-run` is the non-destructive form: it never writes to the remote because git skips the object transfer when `--dry-run` is set. The probe ref `cliff-push-probe` is a fixed name; we never actually create the ref, so there's nothing to clean up. **Earlier drafts of this plan mistakenly referenced `git ls-remote --push` — that flag does not exist; `git ls-remote` is read-only and uses the fetch-side authentication path, which doesn't tell us anything about push permission. Use `git push --dry-run` only.**

## Root cause (grounded in code)

`backend/cliff/integrations/github_app/client.py:317-541` — `check_repo_push_access`:

- L386 — `/repos/{}/{}` returns `permissions.push=true` for user → `can_push=True`. But this tells us nothing about whether THIS token can push via git protocol.
- L489-541 — five distinct fallback paths that return `can_push=True, reason=""` when subsidiary API calls fail (network blips, 403 on `/installation`, unparseable JSON, etc.).
- None of these paths verify the token at the wire level.

## Files touched

Backend (V2):

- `backend/cliff/integrations/github_app/client.py` — add a `_probe_git_push(token, repo_url) -> ProbeResult` helper that runs:

  ```
  git push --dry-run https://x-access-token:{token}@github.com/{owner}/{repo}.git HEAD:refs/heads/cliff-push-probe
  ```

  via `asyncio.create_subprocess_exec` with a configurable timeout (default 5 s, read from `settings.push_probe_timeout_seconds` — add this to `backend/cliff/config.py` so operators can tune via `CLIFF_PUSH_PROBE_TIMEOUT_SECONDS`). Returns a small result object with `ok: bool` and a classified `reason` string derived from stderr: `"credentials rejected"` on auth failure (403, "permission denied", "unauthorized"), `"repository not found"` on 404, `"timeout"` on hang, `"git binary not available"` on FileNotFoundError, `"probe ok"` on exit 0. Wrap `check_repo_push_access`'s currently-permissive return paths (those that say `can_push=True, reason=""`) so they invoke the probe and downgrade to `can_push=False, reason="git push probe failed: <classified-reason>"` if it fails. Stderr is parsed for classification but NEVER echoed verbatim into the response (it can contain the remote URL with the embedded token).
- `backend/tests/test_github_app_client.py` — three new tests: probe succeeds → can_push=True; probe fails with auth error → can_push=False with reason mentioning credentials; probe times out → can_push=False with reason mentioning timeout.

Frontend (V2): **none.** The Settings push-access badge (PR-D) and the executor's preflight both consume `check_repo_push_access` — both surfaces inherit the new ground truth for free.

Tests for cache behavior (existing in `test_routes_github_diagnose.py`): verify cache key still respects the (token, repo) pair so a token rotation invalidates correctly.

## Test plan (TDD-first)

Write first:

```python
# test_github_app_client.py
async def test_check_runs_probe_when_user_perms_say_push_true(monkeypatch):
    # mock httpx: /repos/{}/{} returns permissions.push=true
    # mock subprocess: git push --dry-run returns exit 0
    result = await check_repo_push_access(...)
    assert result.can_push is True
    assert "verified" in result.reason.lower()

async def test_probe_failure_downgrades_to_can_push_false(monkeypatch):
    # mock subprocess: returns exit 128 with "remote: Permission to ... denied"
    result = await check_repo_push_access(...)
    assert result.can_push is False
    assert "credentials" in result.reason.lower() or "permission" in result.reason.lower()

async def test_probe_timeout_returns_can_push_false_with_specific_reason(monkeypatch):
    # mock subprocess: hangs past the timeout
    result = await check_repo_push_access(...)
    assert result.can_push is False
    assert "timeout" in result.reason.lower()
```

Then implement. Run lint + existing test suite — must stay green.

E2E (Wave 4 QA, manual):

- Settings → Integrations: badge state matches actual push outcome (green only if real push works).
- Drive a Critical through Approve & generate fix: if probe fails, preflight returns 412 within ~5 s with "git push probe failed: <reason>" message in `error_details`. UI surfaces `executor_failed` (B35a/B35b path).

## Risks

- **Probe makes a network call to GitHub on every preflight + every Settings page load.** The existing 5-min cache in PR-D's diagnose endpoint absorbs the Settings load; the executor preflight is fine because it's a once-per-execute. No new rate-limit pressure on GitHub.
- **Default 5 s timeout might be too short for slow corporate networks.** Configurable via `CLIFF_PUSH_PROBE_TIMEOUT_SECONDS`.
- **The probe leaks the token to the local git process.** Already happens — `git clone` and `git push` in the executor use the same pattern. No new exposure. Stderr classification strips the URL before any value reaches the response.
- **`git` binary may not be present in some deployment environments.** It IS present in our Docker image (we already use it for clone). Fail closed (`can_push=False, reason="git binary not available"`) if subprocess spawn fails.

## ADR

Amends `docs/adr/0037-github-app-write-permissions.md` (second amendment block, dated 2026-05-18). Acknowledges the runtime probe as the tactical fix and IMPL-0021 (installation tokens) as the future structural fix.

## Rollout

Single PR, 2 commits:

1. `feat(q01r-w3-probe): runtime git push --dry-run probe for push access verification (B37)`
2. `chore(q01r-w3): apply post-review polish` (only if `/simplify` + `engineering:code-review` finds high-confidence cuts)

Target branch: `main`.
