# PR #62 demo — test plan

Hands-on verification of the "from zero to secure" onboarding flow end-to-end.

## Prerequisites

Container already running on **http://localhost:18000** with the flag on.
- `CLIFF_V1_1_FROM_ZERO_TO_SECURE_ENABLED=true`
- Health: `curl -sf http://localhost:18000/health` returns `{"cliff":"ok",...}`
- Flag: `curl -sf http://localhost:18000/api/config/feature-flags` returns `{"v1_1_from_zero_to_secure_enabled":true}`

If you need to restart:

```bash
cd docker
CLIFF_APP_PORT=18000 CLIFF_V1_1_FROM_ZERO_TO_SECURE_ENABLED=true docker compose up -d
# and to stop:
docker compose down
```

You will need:
- A **public GitHub repo URL** you don't mind scanning. Good demo targets: `https://github.com/galanko/Cliff`, `https://github.com/expressjs/express`, `https://github.com/tj/node-tap`.
- (Optional) A **GitHub PAT** with `repo` scope if you want to test a private repo or raise rate limits. Public repos work without one.

---

## Scenario 1 — Happy path onboarding

Walks you through the full onboarding wizard and verifies the dashboard + completion card.

**Step 1 — Open the wizard.**
1. Visit http://localhost:18000/onboarding/welcome in your browser.
2. ✅ You should see the `Welcome` screen ("Ethos Security" branded card with a "Continue" CTA).
3. ❌ If you see the `/findings` page instead → flag didn't reach the container. Check `docker compose logs cliff | grep v1_1` or re-run with the env var.

**Step 2 — Connect the repo.**
1. Click Continue → you're on `/onboarding/connect`.
2. Paste a public GitHub URL (e.g. `https://github.com/expressjs/express`).
3. Leave the PAT field empty for public repos, or paste a valid PAT.
4. Click "Connect repo".
5. ✅ Should advance to `/onboarding/ai` without error toast.
6. ❌ If you see "repo_url and github_token are required" or a 422 → check the UI form binding.

**Step 3 — Configure AI.**
1. On `/onboarding/ai`, pick a model / paste an API key (or click "skip for now" if the UI allows).
2. Click "Start assessment".
3. ✅ Should advance to `/onboarding/start`.

**Step 4 — Watch the assessment run.**
1. You're now on `/onboarding/start`. The progress list polls `/api/assessment/status/:id` every second.
2. ✅ You should see step rows turn green as clone → lockfile parse → OSV lookup → posture checks complete.
3. Tail the container to watch it in real time:
   ```bash
   docker compose logs -f cliff | grep -E "clone|osv|posture|assessment"
   ```
4. ✅ When the run completes (~30–90s for a small repo), the UI redirects to `/dashboard`.
5. ❌ If it stays stuck at `running`, the assessment probably crashed. Check `docker compose logs cliff | grep -i error`.

**Step 5 — Dashboard.**
1. On `/dashboard`, verify:
   - A **grade ring** (A–F) is visible with criteria filled in.
   - The **posture-check list** shows pass/fail for all 5 checks (SECURITY.md, dependabot, branch protection, signed commits, pinned-actions).
   - The **findings table** on the right shows rows if the repo had vulnerabilities (sources labelled `cliff-assessment`).
2. Take a screenshot if anything looks off.

**Step 6 — Completion block (conditional on grade).**
1. If the repo got grade A with all criteria met, you'll see the **completion celebration** banner above the report card.
2. Click "Save .png" → browser should start a download of a 1200×630 PNG (`cliff-summary-<repo>-<date>.png`).
3. Open the PNG — it should render the card with your grade, repo name, and date.
4. ✅ Verify the file is non-trivial size (>10 KB).
5. Click "Copy text" / "Copy markdown" — should silently succeed (toast/confirm depending on the UI).

---

## Scenario 2 — Feature flag fail-closed

Verifies the backend gate actually blocks writes when the flag is off. **This is the defence-in-depth the review called out.**

**Step 1 — Stop and relaunch with the flag off.**
```bash
cd docker
docker compose down
CLIFF_APP_PORT=18000 docker compose up -d   # no flag override == default off
sleep 8
curl -sf http://localhost:18000/api/config/feature-flags
# expect: {"v1_1_from_zero_to_secure_enabled":false}
```

**Step 2 — Confirm the wizard is unreachable in the UI.**
1. Visit http://localhost:18000/onboarding/welcome.
2. ✅ Should redirect immediately to `/findings` (legacy home).
3. No blank-screen flash (retry:false was part of this PR).

**Step 3 — Try direct API calls — must return 404.**
```bash
curl -s -o /dev/null -w "repo:     %{http_code}\n" \
  -X POST http://localhost:18000/api/onboarding/repo \
  -H 'content-type: application/json' \
  -d '{"repo_url":"https://github.com/acme/x","github_token":"ghp_x"}'

curl -s -o /dev/null -w "complete: %{http_code}\n" \
  -X POST http://localhost:18000/api/onboarding/complete \
  -H 'content-type: application/json' \
  -d '{"assessment_id":"x"}'

curl -s -o /dev/null -w "run:      %{http_code}\n" \
  -X POST http://localhost:18000/api/assessment/run \
  -H 'content-type: application/json' \
  -d '{"repo_url":"https://github.com/acme/x"}'
```
4. ✅ All three must print `404`.
5. ❌ If any print `200` or `422` → the server-side gate is broken.

**Step 4 — Flip the flag back on and verify writes work.**
```bash
docker compose down
CLIFF_APP_PORT=18000 CLIFF_V1_1_FROM_ZERO_TO_SECURE_ENABLED=true docker compose up -d
sleep 8
curl -s -o /dev/null -w "run: %{http_code}\n" \
  -X POST http://localhost:18000/api/assessment/run \
  -H 'content-type: application/json' \
  -d '{"repo_url":"https://github.com/expressjs/express"}'
# expect: 200
```

---

## Scenario 3 — Security: token-aware host allowlist

Verifies a stolen GitHub PAT can't be exfiltrated via a non-GitHub clone URL.

**Step 1 — Set a token via the onboarding flow** (scenario 1 step 2 with a PAT).

**Step 2 — Try to start an assessment against a non-GitHub host.**
```bash
curl -s http://localhost:18000/api/assessment/run \
  -H 'content-type: application/json' \
  -d '{"repo_url":"https://evil.example.com/acme/x"}'
```
✅ Response body should include `"repo_url host 'evil.example.com' is not in the token-injection allowlist"` (the engine rejects before clone).
Check `docker compose logs cliff | tail -20` for the stack trace.

**Step 3 — Try a leading-dash host.**
```bash
curl -s http://localhost:18000/api/assessment/run \
  -H 'content-type: application/json' \
  -d '{"repo_url":"https://-upload-pack=evil/foo"}'
```
✅ Response should surface `"repo_url host may not begin with '-'"`.

---

## Scenario 4 — Findings resilience

Covers the Gap #3 fix: a malformed advisory in the middle of a run must not strand the assessment in `running`.

This is hard to trigger from outside without patched fixtures, but you can verify the behavior exists:

```bash
docker compose exec cliff grep -n "failed to persist" /app/backend/cliff/api/_background.py
```
✅ Expect two lines referencing the per-posture-check and per-finding logging. That's the resilience you'd want to see.

---

## Scenario 5 — PNG export cross-browser (manual)

If you have time, run the Playwright E2E locally across all three browsers:

```bash
cd frontend
npm run test:e2e   # or: npx playwright test
```

✅ 3 passes (chromium, firefox, webkit). The Firefox pass is the key one — it exercises the `skipFonts` fallback added in this PR for cross-origin Google Fonts CSS rules.

---

## Sign-off checklist

- [ ] Scenario 1 happy path completes through to dashboard
- [ ] Dashboard shows grade + posture checks + findings
- [ ] Completion card downloads a valid PNG (if grade A was reached)
- [ ] Scenario 2: all three POSTs return 404 when flag is off
- [ ] Scenario 2: wizard redirects to /findings with flag off
- [ ] Scenario 3: non-GitHub host rejected with token allowlist message
- [ ] Scenario 3: leading-dash host rejected
- [ ] No `ERROR` lines in `docker compose logs cliff` during a normal run
- [ ] Container stops cleanly (`docker compose down` → no orphans)

## Known gaps to flag for review

- The `CLIFF_CREDENTIAL_KEY` warning at startup is pre-existing; the onboarding flow stores the PAT in `app_setting` not the real vault (documented in the route comment; vault integration is a follow-up).
- If the repo has no lockfile the OSV phase returns zero findings — that's correct, not a bug, but the progress list currently doesn't explain it.
- The assessment does NOT fall back to a second grader if the GitHub API rate-limits without a PAT — posture checks return `advisory`, which the grader treats as pass. If you want stricter grading, supply a PAT.
