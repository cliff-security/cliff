# Q01R-B24 — Auto-fix posture: frontend/backend contract mismatch + silent UI failure

**Severity**: P0
**Surface**: UI + backend

## What I observed
Dashboard "Level up to D" card displayed:
> Pass remaining posture checks [Auto-fixable]
> branch_protection, actions_pinned_to_sha, stale_collaborators
> [Auto-fix 2 of 5 →]

Clicked the "Auto-fix 2 of 5" button. UI did not change. No toast, no inline error, no progress indicator. Button text remained the same.

Docker logs showed:
```
POST /api/posture/fix/code_owners_exists HTTP/1.1" 422 Unprocessable Entity
POST /api/posture/fix/actions_pinned_to_sha HTTP/1.1" 422 Unprocessable Entity
```

OpenAPI schema for `POST /api/posture/fix/{check_name}`:
```
check_name enum: ["security_md", "dependabot_config"]
```

422 body:
```
{"detail":[{"type":"literal_error","loc":["path","check_name"],
 "msg":"Input should be 'security_md' or 'dependabot_config'",
 "input":"code_owners_exists"}]}
```

## Three bugs in one
1. **Backend whitelist**: only accepts `security_md` and `dependabot_config` — but UI offered `branch_protection`, `actions_pinned_to_sha`, `stale_collaborators`, `code_owners_exists`
2. **Frontend swallows the 422**: no toast, no inline error — user sees nothing, assumes nothing happened
3. **Dashboard promise is broken**: "Auto-fix 2 of 5" implies 2 are auto-fixable now, but neither of the checks the UI lists is actually accepted by the backend

## Impact
The single most prominent action on the post-onboarding dashboard ("Level up to D — One is one-click") is the broken auto-fix button. First-time users see a dead button as the very first thing they try.

## Suggested fix
Two-sided:
- Backend: extend the autofix enum to actually cover what the dashboard lists, OR mark un-fixable checks as non-autofixable so the dashboard doesn't show the button
- Frontend: never swallow 4xx silently — toast at minimum, ideally an inline error on the affected card
