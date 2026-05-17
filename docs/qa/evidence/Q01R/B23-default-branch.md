# Q01R-B23 — Posture checks hardcoded to `main` branch (404/403 on master-branch repos)

**Severity**: P1
**Surface**: backend (assessment engine)

## What I observed
After connecting NodeGoat (default branch: `master`), Docker logs show during initial assessment:
- `GET https://api.github.com/repos/cliff-security/NodeGoat/branches/main/protection "HTTP/1.1 403 Forbidden"`
- `GET https://api.github.com/repos/cliff-security/NodeGoat/commits?sha=main&per_page=20 "HTTP/1.1 404 Not Found"`

The hardcoded `main` ref breaks any repo whose default branch isn't `main` — at minimum: `branch_protection` check (always shows as failed) and any commit-history-based check.

## Impact
- `branch_protection` posture check fails for `master`-branch repos with no signal that it's a wrong-branch query, not a missing protection
- Dashboard reports false "posture failing" badges
- Affects all NodeGoat / older GitHub repos (the explicit target of QA-0001)

## Suggested fix
Resolve the repo's default branch via `GET /repos/{owner}/{repo}` once after install, cache it, use it everywhere instead of hardcoding `main`. Backfill on existing assessments.

## Evidence
- See evidence/Q01R/B23-default-branch-logs.txt for the raw docker log lines.
