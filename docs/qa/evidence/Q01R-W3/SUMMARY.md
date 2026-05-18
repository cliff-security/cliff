# Q01R-W3 evidence — summary

| File | What it documents |
|---|---|
| `../../QA-0001-Q01R-Wave3-rerun.md` | Full Wave 3 walkthrough, verification matrix, headline result |
| `B36-stream-no-refetch.md` | Side-panel activity feed doesn't update without F5 (reactivity regression in same class as B22) |
| `B37-preflight-false-positive.md` | `check_repo_push_access` returns can_push=true via user-perms fallback; actual git push then fails |

## TL;DR

All four Wave 2 PRs (#173 vault, #174 GitHub App recovery, #175 preflight teeth, #176 push-access badge) ship their UI contracts correctly. PR-C's `executor_failed` stage rendered exactly per spec on a real failure — a major win.

But the end-to-end "real PR on cliff-security/NodeGoat via UI alone" still doesn't complete, for the deferred-work reason IMPL-0017 anticipated: the user OAuth token can call `/repos/{}/{}` (push=true) but not `/repos/{}/{}/installation` (401) — preflight's fallback path passes, then the actual git push fails on token scope.

Wave 4 should ship **IMPL-0019 (installation tokens)** for the structural fix and/or **a runtime push-probe** as the tactical unblocker. B36 (reactivity) is a one-PR follow-up in parallel.
