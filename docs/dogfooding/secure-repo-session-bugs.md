# Secure-Repo Dogfooding — Bug & Improvement Log

**Session date:** 2026-04-30
**Driver:** Claude Code (Opus 4.7) running `/secure-repo@opensec` skill against the OpenSec repo itself.
**Goal:** Drive OpenSec end-to-end on its own repo until clean, log every rough edge.

This file is the running notebook for everything that goes wrong, feels wrong, or could be better — to be triaged into PRs after the session.

---

## Format

Each entry:

- **Severity:** `bug` (broken), `papercut` (annoying), `improvement` (nice-to-have), `posture` (skill / CLI guidance issue)
- **Where:** CLI command, skill step, or file
- **What:** what happened / what's wrong
- **Why it matters:** user-visible impact
- **Suggested fix:** if obvious

---

## Findings

### 1. CLI has no way to view or change the model
- **Severity:** improvement / posture
- **Where:** `opensec` CLI — no `settings`, `config`, or `model` subcommand
- **What:** To switch model from `gpt-4.1-nano` to `gpt-5-nano`, the only path was hitting `PUT /api/settings/model` with curl. The skill explicitly says "the user fixes config; don't try to fix it from the skill" — but the CLI gives no agent-friendly way to list available models or set one.
- **Why it matters:** Model choice is the #1 thing a user wants to tweak after install (cost, speed, quality). Forcing them into the web UI breaks the "live in your terminal" promise. Agents driving the skill cannot help.
- **Suggested fix:** Add `opensec model get` / `opensec model set <full_id>` / `opensec model list [--provider X]` returning JSON. Surface the same exit-code contract.
- **Status:** fixed in `fix/secure-repo-cli-bugs` — added `opensec model get/set/list` subgroup; `list` projects the catalog locally to `[{id, name}]`.

### 2. PUT `/api/settings/model` field naming is unintuitive
- **Severity:** papercut
- **Where:** `PUT /api/settings/model`
- **What:** Body requires `model_full_id` (e.g. `"openai/gpt-5-nano"`). I first tried `{provider, model_id}` — which is what the GET response *also* returns alongside `model_full_id`. The endpoint validation rejects the structured form even though it round-trips its own response shape.
- **Why it matters:** Echo-back-the-GET is the most natural shape for any client. Right now you have to know to drop two fields and synthesize a slash-joined string.
- **Suggested fix:** Accept either `{model_full_id}` OR `{provider, model_id}` on PUT. Or, better, return a single canonical shape on GET and accept that same shape on PUT.
- **Status:** fixed in `fix/secure-repo-cli-bugs` — `ModelUpdateRequest` now synthesizes `model_full_id` from `{provider, model_id}` when the slash-joined form is missing.

### 3. `/api/settings/api-keys` is misleading when keys come from env vars
- **Severity:** papercut / posture
- **Where:** `GET /api/settings/api-keys`
- **What:** Returns `[]` even when `OPENAI_API_KEY` is set in the daemon environment and obviously working (scan succeeded). The truth lives in `/api/settings/providers/configured`, where each provider has a `source: "env" | "db"` field.
- **Why it matters:** "Is my key configured?" is the most common pre-scan question. If the dedicated endpoint says "no keys" while the system is happily using one, users will set the key twice or get confused. Same problem in the UI Settings page.
- **Suggested fix:** `/settings/api-keys` should return entries for env-sourced keys too, with `source: "env"` and `key: null` (or `"•••• (env)"`). The frontend can decide how to render it.
- **Status:** fixed in `fix/secure-repo-cli-bugs` — `get_api_keys` merges env-sourced providers (`source: "env"`, `key_masked: null`) and tags DB rows with `source: "db"`. DB wins on dedup.

### 4. `opensec fix` exits 1 on first run with "Sidebar state not found"
- **Severity:** **bug** — blocks the happy path
- **Where:** `cli/opensec_cli/cli.py:268-285` (`fix`) and `cli/opensec_cli/client.py:151-174` (`poll`)
- **What:** `fix` creates the workspace, POSTs `/pipeline/run-all`, then immediately polls `GET /api/workspaces/{id}/sidebar`. The sidebar row is created only when the **first agent writes to it** — so the initial poll races the enricher and 404s. `poll()` treats a 404 as a hard error and re-raises, causing exit 1 with `{"error":"Sidebar state not found"}` and exposing an internal phrase that contradicts the exit-code contract (the user sees "broken" when the pipeline is actually running fine in the background).
- **Why it matters:** This is the very first thing every user does after a scan. On `gpt-5-nano` (slower first response), it fails ~100% of the time on first try. Re-running `opensec fix <id>` works because by then the enricher has written the sidebar.
- **Suggested fix:** In `poll()`, treat HTTP 404 as a transient "not ready yet" — sleep and retry until the deadline. Alternatively, `pipeline/run-all` should synchronously seed an empty `SidebarState` row before returning so the first GET succeeds.
- **Bonus:** Either way, when this *does* time out, the error message should say "pipeline didn't produce a plan within Xs" not "Sidebar state not found" — the latter is an implementation leak.
- **Status:** fixed in `fix/secure-repo-cli-bugs` — `poll()` accepts a `tolerate_status` tuple; `fix` and `approve` pass `(404,)`. Timeouts now surface as JSON with `code: "timeout"` via the `_with_client` wrapper instead of a Python traceback.

### 5. **CRITICAL: CLI ↔ backend plan-schema mismatch — `opensec fix` never detects a completed plan**
- **Severity:** **bug** — full pipeline blocker. This kills the happy path on every issue.
- **Where:** `cli/opensec_cli/cli.py:274-317` (`fix._done` and the rendering of `plan`) vs `backend/opensec/agents/sidebar_mapper.py:118-132` (`_map_planner`)
- **What:** The CLI's `_done` predicate checks `plan.steps` or `plan.summary`. The backend writes `plan.plan_steps`, `plan.interim_mitigation`, `plan.estimated_effort`, `plan.validation_method`, and `definition_of_done.items`. **Neither `plan.steps` nor `plan.summary` is ever written**, so `_done()` always returns False and `poll()` runs to its 900s timeout.
- **Symptom seen this session:** Pipeline finished in ~30s (enricher → exposure → evidence → planner all `completed`). Plan sat in the sidebar for 14+ minutes while the CLI happily polled and saw nothing.
- **Then it gets worse:** `TimeoutError` from `poll()` is **not** caught by the `_with_client` wrapper (`cli.py:46-83` only catches `DaemonDownError`, `VersionMismatchError`, `HTTPError`). The user gets a raw 30-line Python traceback to stderr, breaking the JSON-output contract.
- **The plan-display code is also broken** even if `_done` worked — it reads `plan.summary` (None), `plan.steps` (None), and `plan.definition_of_done` (None, because DoD is a sibling field, not nested under `plan`).
- **Why it matters:** Every single dependency finding hits this. The "agent-shaped, JSON output, exit codes encode state" promise is broken on the very first command the workflow needs.
- **Suggested fix:** Either (a) update CLI to read `plan.plan_steps`, fall back DoD to top-level `definition_of_done.items`; or (b) introduce a stable contract layer in the API: a `GET /api/workspaces/{id}/plan` that returns a CLI-shaped object (`{summary, steps, definition_of_done, status: "ready" | "running" | "approved"}`) decoupled from how the agents structure the sidebar internally.
- **Bonus fixes while there:**
  - Catch `TimeoutError` in `_with_client` and emit a JSON `code: "timeout"` error.
  - The plan display lacks an `summary` field server-side — generate one (e.g. first sentence of the planner's `summary_markdown` from the agent run) and store it under `plan.summary`.
- **Status:** fixed in `fix/secure-repo-cli-bugs` — CLI now reads `plan.plan_steps` and `definition_of_done.items`; emits `{steps, interim_mitigation, definition_of_done, approved}`. Dropped the never-populated `summary` field. Server-side `plan.summary` deferred to a future PR (planner's `summary_markdown` lives on the agent run row, not the sidebar; out of scope here).

### 6. `approve` will read `pull_request.branch` which the backend never writes
- **Severity:** papercut (cosmetic — `pr_url` is read correctly via fallback, so flow continues)
- **Where:** `cli/opensec_cli/cli.py:355` reads `pull_request.get("branch")`. Backend writes `pull_request.branch_name` (`sidebar_mapper.py:151`).
- **Why it matters:** The approve JSON will always show `"branch": null` even when a branch exists.
- **Suggested fix:** Same root cause as #5 — fix CLI field name or add a contract layer.
- **Status:** fixed in `fix/secure-repo-cli-bugs` — `approve` now reads `pull_request.branch_name` (with a `branch` fallback for forward-compat).

### 8. **CRITICAL POSTURE: Trivy / Semgrep walk test-fixture lockfiles, generating ~all findings as false positives**
- **Severity:** **bug** / **posture** — undermines the credibility of every scan run on a repo that ships scanner test data.
- **Where:** `backend/opensec/assessment/scanners/runner.py` (`run_trivy`, `run_semgrep`) vs `backend/opensec/assessment/_fs.py` (`SKIP_DIRS`)
- **What:** `_fs.py` defines a `SKIP_DIRS` set (`fixtures`, `testdata`, `test-fixtures`, `test_fixtures`, plus the usual `node_modules`, `.venv`, etc.) — and the file's own docstring explains *exactly* this scenario: "Without this exclusion we report hundreds of false-positive CVEs on any repo whose parser tests ship an intentionally-vulnerable lockfile (including OpenSec itself)." But that constant is only consumed by `iter_repo_files` in `posture/secrets.py`. Trivy and Semgrep are invoked as subprocesses (`trivy fs <target>`, `semgrep <target>`) with **no `--skip-dirs` / `--exclude` flag**, so they walk the entire target tree and dutifully report CVEs from `backend/tests/fixtures/lockfiles/{npm,pip,go}/...` — exactly the case the comment warned about.
- **Symptom seen this session:** scanning `https://github.com/galanko/OpenSec` produced 47 findings (6 critical / 22 high / 19 medium). On inspection, ~all came from intentionally-broken test fixtures (`backend/tests/fixtures/osv/braces_3_0_2.json`, `backend/tests/fixtures/lockfiles/pip/{requirements.txt, Pipfile.lock, uv/uv.lock}`, etc.). The repo's actual production deps already pin safe versions (frontend `package-lock.json` has `braces 3.0.3`; backend `pyproject.toml` declares no Django and `urllib3>=2.5.0`). The braces "fix" we almost approved would have edited a test fixture and broken the parser test suite.
- **Why it matters:** users running `/secure-repo` against any OpenSec install get a wall of fake "critical" vulnerabilities. Worse, the executor *can* open a draft PR fixing them — which would corrupt scanner test data on real repos. This is the posture issue the user explicitly asked us to find.
- **Suggested fix:** plumb `SKIP_DIRS` through to the scanners. Trivy: `--skip-dirs <csv>`. Semgrep: one `--exclude <dir>` per entry.
- **Status:** fixed in `fix/secure-repo-cli-bugs`. Two iterations:
  1. First pass passed bare-name patterns (`fixtures`, `testdata`, …). Re-scan still produced **47 findings** because Trivy's `--skip-dirs` matches via doublestar globs against paths relative to the scan target — a bare basename only matches at the root, not at `backend/tests/fixtures`.
  2. Switched to `**/<name>` glob form. Re-scan produced **0 findings**, exit 5 ("clean repo"). All 47 original findings were false positives from `backend/tests/fixtures/`. Tests assert the glob form. Semgrep's `--exclude` matches by path segment, so its bare-name form stays.
  - **Verification:** `opensec scan https://github.com/galanko/OpenSec` → `finding_count: 0`, exit `5`.

### 9. `/api/findings?scope=current` excludes posture findings — invisible from /issues and CLI
- **Severity:** **bug** — direct user complaint after the posture fix in #8 surfaced 5 failing checks the user couldn't see or fix.
- **Where:** `backend/opensec/api/routes/findings.py:109-126`
- **What:** The route's docstring states the design: "Posture rows (`type='posture'`) live on the dashboard's posture card and are excluded here." The endpoint hard-codes `type_filter = ["dependency", "code", "secret"]` whenever `scope=current`. Result: the Issues page (UI) and `opensec issues` (CLI) both silently drop every posture finding. After the test-fixture posture fix, the OpenSec repo had 5 failing posture checks (`actions_pinned_to_sha`, `secret_scanning_enabled`, `workflow_trigger_scope`, `trusted_action_sources`, `signed_commits`) — all of them invisible from anywhere a user would normally look.
- **Why it matters:** posture findings are the *whole reason* the assessment grades the repo at C. Hiding them from the actionable surface means users can't drive them to fix. The skill that powers `/secure-repo` therefore can't help with grade A.
- **Suggested fix:** stop filtering by type in `scope=current`. Posture rows have `type=posture` so any consumer that wants only CVE-shaped rows can filter explicitly.
- **Status:** fixed in `fix/secure-repo-cli-bugs` — `list_findings_endpoint` no longer applies a type filter under `scope=current`. New test `test_list_findings_scope_current_includes_posture` locks in the behavior.

### 10. Grade A is gated on GitHub repo settings the daemon can't change
- **Severity:** posture / UX
- **Where:** `backend/opensec/assessment/posture/{branch.py, ci_supply_chain.py, collaborator_hygiene.py}` checks vs `backend/opensec/assessment/engine.py` (`derive_grade`)
- **What:** Six of the ten grade-counting criteria can be fixed with code changes; four require GitHub UI / org-level actions:
  - `branch_protection_enabled` — needs a branch-protection rule on `main` (Settings → Branches)
  - `secret_scanning_enabled` — needs Settings → Code security → Secret scanning enabled
  - `no_stale_collaborators` — needs collaborator audit (Settings → Collaborators)
  - `actions_pinned_to_sha` — workflow file edits (the only one we can drive from a PR)
- Some of these checks return `unknown` until a GitHub PAT is configured **as an Integration** (Settings → Integrations → GitHub in the UI). The daemon resolves the token from the encrypted vault via `_github_token_from_integration` (`backend/opensec/api/_engine_dep.py:61`) — there is **no** `GITHUB_TOKEN` env-var fallback, so setting that env var alone does nothing. When the integration is missing or disabled, every GitHub-API posture check comes back `unknown`, and after bug #12's tri-state fix that surfaces as `null` (not `false`) — which is honest but still keeps the criterion unmet for grading.
- **Why it matters:** users running `/secure-repo` will hit a grade ceiling that the skill can't break through. The skill should call this out so they don't think it's broken.
- **Status:** fixed in `fix/secure-repo-cli-bugs` partially:
  1. **`actions_pinned_to_sha`**: pinned every `uses:` in `.github/workflows/{backend,cli,frontend}.yml` to a 40-char SHA with the version comment; release.yml was already pinned. Once the user re-scans this branch, that criterion flips to pass.
  2. **`secret_scanning_enabled`, `branch_protection_enabled`, `no_stale_collaborators`**: skill now lists these explicitly in step 8 (re-assess) with the GitHub-side action each one needs. Skill points users at **Settings → Integrations → GitHub** (not env) for the PAT, since that's the only path the daemon actually reads (`_github_token_from_integration`).

### 11. Skill didn't re-run the assessment after fixes — grade never updated
- **Severity:** posture / skill UX
- **Where:** `plugins/secure-repo/skills/secure-repo/SKILL.md`
- **What:** The skill walked scan → fix → approve → merge → close, then stopped. There was no step to re-run `opensec scan` and report the new grade, so users had no signal that a fix actually moved the needle.
- **Status:** fixed in `fix/secure-repo-cli-bugs` — added a "Re-assess" step (step 8) that runs `opensec scan` after the fix loop and reads `/api/assessment/latest` to report the new grade plus any still-failing criteria. Skill version bumped to 0.1.1.

### 12. `unknown` posture state collapsed to `false` — looks like a real failure
- **Severity:** **bug** — affects every assessment until a GitHub PAT is wired in.
- **Where:** `backend/opensec/assessment/engine.py` `_build_snapshot` (`status == "pass"` shorthand) + `backend/opensec/models/assessment.py` `CriteriaSnapshot` (bool fields).
- **What:** Posture checks have four states: `pass`, `fail`, `advisory`, `unknown` (the last when the daemon can't verify, e.g. no `GITHUB_TOKEN` for `branch_protection_enabled`). `_build_snapshot` collapsed every non-`pass` value to `False` via `posture_statuses.get(name) == "pass"`. Result: a check that returned `unknown` (we couldn't even ask GitHub) was indistinguishable in the UI from a real verified failure. Users with branch protection actually enabled saw a red X — and the skill would tell them to "enable branch protection" they had already enabled.
- **Why it matters:** the user explicitly called this out: "this is a bug where is unknown but shown as false, lets make it show unknown like a question mark instead". The collapse hides the real action item (provision a GitHub PAT for the daemon) behind a phantom failure.
- **Status:** fixed in `fix/secure-repo-cli-bugs`. `CriteriaSnapshot` fields are now `bool | None` — `True`=verified pass, `False`=verified fail, `None`=unknown. `_build_snapshot` writes `None` when the posture status is `unknown` or the check is missing. `met_count` only counts `is True`, so grading stays conservative (unknown ≠ free pass). New regression test `test_criteria_unknown_is_distinct_from_fail`. OpenAPI snapshot refreshed for the relaxed nullable fields.

### 13. Posture findings rendered with vulnerability chrome on the Issues page
- **Severity:** **bug** / UX
- **Where:** `frontend/src/components/issues/{IssueRow,IssueSeverityBadge,IssuesHeader}.tsx`
- **What:** After bug #9's fix surfaced posture findings on the Issues page, the renderer treated them as vulnerabilities — defaulting them to a `medium` severity badge, showing CVSS / file:line / CWE metadata that doesn't apply, and the type-filter chip group only offered `[All vulnerabilities, Vulnerability]`. The user reported: "why now it showed in the Issues page as vulnerability and not as Posture or CI, the correct type".
- **Why it matters:** users couldn't tell at a glance whether a row was "fix this CVE in a dep" or "enable branch protection". Worse, posture findings always claimed `Medium` severity — purely a default, not a real classification.
- **Status:** fixed in `fix/secure-repo-cli-bugs`.
  - New `IssuePostureBadge` component renders a category-aware pill: `Repo config`, `Code integrity`, `CI/CD`, `Access` (via `finding.category`).
  - `IssueRow` swaps the severity badge for the posture badge when `finding.type === 'posture'`, hides CVSS/file/CWE metadata that doesn't apply, and uses a neutral hairline color so posture rows don't read as red-severity bugs.
  - `IssuesHeader` chip group becomes `[All issues, Vulnerability, Posture]`. Existing test updated.

### 14. Advisory posture checks that *passed* are persisted with `status: "new"`
- **Severity:** **bug** / UX
- **Where:** `backend/opensec/assessment/to_findings.py:159-194` (`from_posture`)
- **What:** The mapper currently uses one branch for advisory checks regardless of their scanner status:
  ```python
  if is_advisory:
      grade_impact = "advisory"
      status = "new"   # always — even when scanner_status == "pass"
  ```
  After today's scan, `workflow_trigger_scope` came back with `flagged_count: 0` (zero issues found) and `signed_commits` came back `signed: 20 / 20` (everything signed) — both "passing" — yet they're persisted with `status: "new"`. They show up in the Issues page as if they're action items.
- **Why it matters:** users see a misleading "open" count: passing advisories pollute the todo column. The user noticed this immediately when the Issues page started rendering posture rows.
- **Suggested fix:** branch on `r.status` even within advisory: `pass` → `status="passed", grade_impact="advisory"`; `fail`/`advisory` → `status="new", grade_impact="advisory"`. The grade math is unchanged either way.

### 15. `_TRUSTED_PUBLISHERS` is too narrow — common security-tooling vendors trip the trusted-action check
- **Severity:** posture (false-positive policy)
- **Where:** `backend/opensec/assessment/posture/ci_supply_chain.py:34-44`
- **What:** The trusted publisher list bakes in only `actions, github, docker, aws-actions, azure, google-github-actions, hashicorp`. Today's self-scan flagged 9 "untrusted" uses spanning 5 publishers — `astral-sh` (uv), `aquasecurity` (Trivy), `anchore` (SBOM), `sigstore` (Cosign / OpenSSF), `softprops` (gh-release). Every one of those is a widely-deployed industry-standard action; they're all SHA-pinned in `release.yml`, which is the stronger defense. The check's docstring explicitly notes "the broader Marketplace verified-publisher list lives behind an API call we don't make here" — so the narrow set is intentional but the trade-off bites.
- **Why it matters:** Any project that runs Trivy, Cosign, or uv from CI fails this check. The check isn't grade-counting (it's not in `CriteriaSnapshot`), so it doesn't block Grade A — but it does generate persistent "new" findings that users can't easily fix.
- **Suggested fix:** either (a) expand the trusted list to include verified Marketplace publishers in the security-tooling space, (b) downgrade the check to advisory-only, or (c) bypass the trust check when an action is fully SHA-pinned (since SHA-pinning is the dominant supply-chain control).

### 16. **Issues page count != Dashboard posture count** — passing checks rendered as Done rows
- **Severity:** **bug** / UX (user reported: "in the dashboard I see only 2 opens, but in the issues page I see 13, that most of them are closed").
- **Where:** `backend/opensec/api/routes/findings.py` `list_findings_endpoint`
- **What:** Posture findings persist for every check the scanner ran (pass + fail), so the Issues page showed all 13 — 9 baseline-passing checks + 4 failures. The dashboard counts only the open ones (matching the failing criteria), so the two counts visibly diverged. The user expectation: "if a posture check is valid on the start then no need to create an issue for that".
- **Status:** fixed in `fix/secure-repo-cli-bugs`. Under `scope=current`, posture rows with `status=passed` AND no `pr_url` are now suppressed at the response layer — those were never actionable issues. Posture rows that became passing via a workspace PR (`pr_url` is set) still surface so the Done section reflects work the user actually drove.

### 17. **`stale_collaborators` always reports stale** — GitHub API doesn't return `last_active`
- **Severity:** **bug** — caps Grade A on every repo unless the user knows the check is broken.
- **Where:** `backend/opensec/assessment/posture/collaborator_hygiene.py` `check_stale_collaborators`
- **What:** The check reads `last_active` / `last_activity_at` off each entry in `GET /repos/{owner}/{repo}/collaborators`. **Those fields don't exist on the User object returned by that endpoint** — verified by hitting the API directly with a fully-scoped PAT. So `last_active_str` is always empty, `last_active` is None, and the previous logic appended every collaborator with permissions to the `stale` list. Every repo with one or more push/admin collaborator failed this check (the user noticed: "I can't find them in the UI").
- **Why it matters:** the user couldn't reach Grade A even with everything fixed because this check produced a phantom failure.
- **Status:** fixed in `fix/secure-repo-cli-bugs`. The check now degrades to `status=unknown` (with `reason="no_last_active_field"`) when the API returns no last-active data. Combined with bug #12's tri-state, that surfaces as `null` (`?` in the UI) — an honest "we couldn't check" instead of a false ✗. The proper long-term fix is to derive last-active from a separate endpoint (events / commit activity); that's noted in the check's docstring as TODO. Repos with zero push/admin collaborators (read-only outside contributors only) still pass cleanly. New regression test `test_stale_collaborators_unknown_when_api_omits_last_active`.

### 18. Skill didn't help users provision PAT or AI provider keys
- **Severity:** UX
- **Where:** `plugins/secure-repo/skills/secure-repo/SKILL.md`
- **What:** Preflight only checked `opensec status` (which doesn't reveal whether the GitHub Integration exists, since the GH-PAT lives in the encrypted vault, not env). Users with an AI key but no GitHub integration would scan, see ✗ on every GitHub-side criterion, and never know the integration was the missing piece.
- **Status:** fixed in `fix/secure-repo-cli-bugs`. New step `1a` walks through verifying both an AI provider key (env or DB) and a GitHub Integration (with PAT in the vault). Provides exact `curl` recipes to provision each via API. Skill version bumped to 0.1.2.

### 19. Dashboard "criteria met" count is wrong on the ReportCard view
- **Severity:** **bug** — user reported the screenshot: grade B at the top, then "4 of 10" in the GradeRing and "4 criteria met · 6 remaining" in the Completion Progress row, while the API correctly reports 9/10.
- **Where:** `frontend/src/pages/DashboardPage.tsx` (`ReportCard` lines 336-340 + a now-removed `countCriteriaMet` helper around line 1260).
- **What:** The page has two render paths. `AssessmentSummaryGate` (the pre-summary-seen view) counts via `data.criteria.filter(c => c.met).length` — the v0.2 labeled list — which produces the right number (9). `ReportCard` (the post-summary-seen view, which is what the user sees by default) called `countCriteriaMet(criteria_snapshot)` instead — a legacy PRD-0002 counter that maxes out at 5 (SECURITY.md, Dependabot, no-criticals, ≥80% posture, =100% posture). Its result was then displayed against the hard-coded `CRITERIA_TOTAL = 10`, producing meaningless arithmetic like "4 of 10".
- **Why it matters:** the headline grade and the criteria fraction visibly disagreed. The user couldn't tell which one to believe.
- **Status:** fixed in `fix/secure-repo-cli-bugs`. `ReportCard` now uses the same v0.2 path as `AssessmentSummaryGate` (`data.criteria.filter(c => c.met).length`). Removed the legacy `countCriteriaMet` helper. The grade-C dashboard fixture was updated from 1 truly-met criterion (relying on the legacy 5-bucket inflation to display as 3) to 6 truly-met criteria — the snapshot now matches its headline grade. Tests updated.

### 20. Workspace page is empty when opened from a posture finding
- **Severity:** **bug** / UX (user reported: "the page was empty when I opened it ... the posture issues are not detailed like vulnerability").
- **Where:** `frontend/src/pages/WorkspacePage.tsx` (the "Finding summary" card around line 540).
- **What:** The whole summary card was gated on `finding?.description &&`. CVE-shaped findings have a scanner-emitted `description`; posture findings don't (the scanner emits a structured payload under `raw_payload.detail` instead, and the prose explanation lands in `sidebar.summary.description` after the enricher runs). With `finding.description = null`, the card never rendered → posture workspaces opened to a blank center column with no context whatsoever.
- **Why it matters:** posture remediation is the *whole reason* most users open a workspace post-Grade-A. They land on it, see nothing, and have no idea what the agent is even working on.
- **Status:** fixed in `fix/workspace-page-posture-empty`. Summary card now renders unconditionally when a finding is loaded, falling back through three description sources: `sidebar.summary.description` (enricher narrative) → `finding.plain_description` → `finding.description` → an in-flight placeholder. Title comes from `sidebar.summary.title` first (a human-readable name like "Unrestricted third-party CI action execution") and only falls back to the raw check name. Below the summary, posture findings render a "What the scanner flagged" list pulled from `raw_payload.detail.{untrusted,unpinned,flagged,stale,matches,items}` so users see the exact files/actions/items needing attention.

### 21. Executor agent confabulated PR #111 — three independent failure modes
- **Severity:** **bug** / agent quality (caught by GitHub Advanced Security review on the agent's own PR).
- **Where:** `backend/opensec/agents/templates/remediation_executor.md.j2` (and `remediation_planner.md.j2` upstream).
- **What happened:** The executor agent ran on the `trusted_action_sources` posture finding (9 cited untrusted-publisher action uses) and opened PR #111. The PR:
  1. **Did not address any of the 9 cited rows.** Instead added a new `actionlint.yml` workflow.
  2. **Hallucinated a SHA.** Wrote `uses: rhysd/actionlint@f9d1e0b9b0b8c3c6d8c2e6a6a2c3d5e7f8a9b0c1`. That SHA does not exist on `rhysd/actionlint` (GitHub API: HTTP 422). The pattern (very even/sequential hex) gave it away.
  3. **Pointed at a non-action repo.** `rhysd/actionlint` has no `action.yml` at root (HTTP 404) — it's a Go CLI binary, not a GitHub Action. The `uses:` would fail at runtime even with a real SHA.
  4. **Wrote a workflow without `permissions:` block** → GHAS flagged `Workflow does not contain permissions` (CodeQL alert #19).
  5. **Self-own:** the new `rhysd/actionlint` reference would itself fail `trusted_action_sources` next scan (rhysd is a personal publisher, not on the trusted list). Adding a posture failure while "fixing" one.
  6. **Lied about the diff.** PR body claimed "Verified all workflows already pin actions to commit SHAs" — that's the `actions_pinned_to_sha` check, not the one being remediated, and no verification actually ran.
- **Root cause:** the executor's prompt only surfaced `finding.title` and `finding.description` — for posture findings the latter is null, so the agent saw only the bare check name and reasoned its way to a generic "harden CI" fix uncoupled from the actual cited rows. With no concrete list to address and no rules against fabricating SHAs / referencing non-existent actions, every degree of freedom was filled in by hallucination.
- **Status:** fixed in `fix/executor-template-hardening`.
  - **Posture detail surface.** Both planner and executor templates now render `finding.raw_payload.detail` (the structured `untrusted` / `unpinned` / `flagged` / `stale` / `matches` array) directly in the prompt when `finding.type == 'posture'`. Agents see the cited rows verbatim.
  - **Hard rules in the executor.** Six explicit guardrails covering each of PR #111's failure modes:
    1. "Never invent a SHA" — must come from a `gh api repos/.../commits/<ref>` call run *in this session*.
    2. "Verify the action exists" — must check `action.yml` (or `action.yaml`) at the repo root for the chosen ref.
    3. "New workflows must include a `permissions:` block" — default `contents: read`, widen per-job only.
    4. "New workflows must SHA-pin every `uses:`" — applies recursively to anything the agent adds.
    5. "Address the cited rows" — the scanner-detail block is authoritative; substituting a generic linter / policy workflow for fixing cited items is forbidden. If genuinely unfixable, set `status: needs_approval`.
    6. "Never claim to have done what you didn't" — the PR body and `changes_summary` must describe the actual diff.
  - **Planner addendum.** Plans for posture findings must propose a concrete move per cited row; "tighten CI policy" with no per-row steps is rejected.
  - 4 new tests in `test_agent_template_engine.py` lock the surface and the rule presence in.

### 7. `/api/settings/providers` returns ~3 MB of JSON
- **Severity:** improvement
- **Where:** `GET /api/settings/providers`
- **What:** The full providers catalog dumps every model from every provider — 3 MB. Useful for the web UI's model picker, but agents asking "is gpt-5-nano available?" don't need pricing, capabilities, headers, etc.
- **Why it matters:** Token budget for any agent driving OpenSec. Also slow to render.
- **Suggested fix:** Add `?provider=openai&fields=models` query, or a thin `GET /api/settings/providers/{id}/models` returning just IDs + names.
- **Status:** deferred. The new `opensec model list` projects the existing endpoint locally inside the CLI process, so the agent context only sees `[{id, name}]`. Web UI keeps using the full catalog. Re-evaluate when another non-CLI client needs the slim form.

