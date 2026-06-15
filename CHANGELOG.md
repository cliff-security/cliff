# Changelog

All notable changes to Cliff are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.2] - 2026-06-15

Triage hardening for SAST/code findings — the Plan-gate bright line ("a
report must never carry a false positive") now holds for code findings the
way it already did for dependencies. Plus the `cliffsec` CLI release that
carries the triage-first `fix` flow to users.

### Fixed

- **Code/SAST triage no longer ships fake `real` verdicts.** The Quick-read
  synthesizer projected a confident `real` for code findings whenever the
  exposure analyzer's free-text reachability *looked* affirmative — including
  pure speculation like "likely reachable … needs verification to confirm"
  (the analyzer reasons from the file path, never opening the flagged line).
  On a SAST-heavy repo that shipped fake CRITICAL SQL-injection findings. Two
  fail-safes now guard the verdict: (1) reachability classification is
  hedge-aware — "likely / suggests / appears / needs verification" is treated
  as *undetermined*, never a confident reachable; (2) a `code` (and `secret`)
  finding can't be confidently cleared OR confirmed from the Quick read at all
  — it defers to `needs_review`, which auto-escalates to the file-reading Deep
  dive (ADR-0052), where the `file:line` is actually opened before any verdict.
- **Hedged negatives are no longer confidently cleared.** Reachability
  classification now checks hedging *before* the negative keywords, so
  "cannot confirm it is not reachable" / "appears unreachable but unverified"
  route to `needs_review` instead of a confident `unexploitable` — closing the
  same false-clear on the clearing side. A clean "no path found" still clears.
- **`secret` findings defer like code.** A leaked-secret finding has no CVE
  (the enricher always abstains), so the dependency projection would clear it
  as `false_positive` — false-clearing a real secret. Secrets now defer to
  `needs_review`. (`posture` keeps the projection — it's a deterministic Cliff
  check, real by definition.)
- **Triage never strands on a failed prerequisite.** When the enricher or
  exposure agent failed (e.g. a 150s timeout on a deploy-time migration file),
  triage aborted with no verdict — leaving the CLI to time out and exit 1. It
  now degrades to a `needs_review` verdict landed in the sidebar and chat
  card. Triage always produces a verdict; never a silent clear, never a crash.
  The degrade triggers on *any* non-`completed` prerequisite status (not just
  `failed`/`rate_limited`), and the degraded verdict is computed without stale
  output from a prior triage attempt in the same workspace.
- **Deep dive won't confirm an ungrounded path.** A `trace_path` result that
  claims `reached=yes` but cites no `file:line` hop is now routed to
  `needs_review` instead of proceeding to a confident `real` — the symmetric
  guard to the disproof challenge on the clearing side.
- **OpenAI BYOK save now works.** The validator probe was hardcoded to
  `gpt-5`, which is in OpenAI's reasoning-model family and rejects
  `max_tokens` with a 400. The non-classified-4xx catch-all rendered
  that as the misleading "Your account doesn't have access. Check
  billing setup at OpenAI." message, blocking every BYOK user from
  saving an OpenAI key regardless of account state, balance, or model
  permissions. Switched the probe to `gpt-4o-mini` — non-reasoning,
  universally available, cheapest probe target, consistent with the
  Anthropic probe's `claude-haiku-4-5`.

## [0.2.1] - 2026-05-25

The first patch on top of 0.2.0. Three release-shaped pieces of work —
the CLI binary rename to **`cliffsec`** (the PyPI distribution name
`cliff` is owned by openstack's CLI framework, so this unblocks a
future PyPI publish), the Claude Code plugin rename + restructure to
**`cliff-security`** with per-action playbooks, and a rework of the
GitHub App onboarding so the **device-flow user token *is* the
connection** (ADR-0048 revised). Plus 22 QA-driven bug fixes batched
from the Q02 and Q03 sessions.

**The product is still called Cliff** — only the user-facing CLI
command, the Claude Code plugin handle, and the PyPI distribution
name change. Configuration paths (`~/.cliff/`), env vars (`CLIFF_*`),
the `backend/cliff/` package, the Docker image, the GitHub repo, and
the GitHub App slug are all unchanged.

> **Upgrade:** the CLI binary is now `cliffsec`. Re-run
> `install-local.sh` (or `install.sh`) — the installer replaces
> `~/.local/bin/cliff` with `~/.local/bin/cliffsec` and recreates the
> CLI venv so no stale entry point survives. Users on 0.2.0 can also
> self-upgrade with `cliff update` — this release ships the tarball
> under both the new `cliffsec-0.2.1.tar.gz` name and a one-time
> `cliff-0.2.1.tar.gz` alias so the 0.2.0 updater's pinned URL
> resolves. Aliases are dropped in 0.2.2.
>
> Claude Code plugin users: the install command changes to
> `/plugin install cliff-security@cliff`. Run `/plugin uninstall
> secure-repo@cliff` first if you have the old plugin.

### Changed

- **Renamed the CLI binary from `cliff` to `cliffsec` (PR #218).**
  PyPI distribution name flipped from `cliff-cli` to `cliffsec`.
  Click `prog_name` is now `cliffsec`; all help text, error hints,
  command examples, the HTTP `User-Agent` header, and install-script
  banners reference the new name. `install.sh` and `install-local.sh`
  clean up the pre-rename `~/.local/bin/cliff` symlink during upgrade
  and wipe the CLI venv so the old `bin/cliff` entry-point doesn't
  linger.
- **Release assets renamed (PR #218).** The local-install tarball is
  now `cliffsec-${version}.tar.gz` (with `cliffsec.tar.gz` as the
  stable-name alias for the `latest` redirect); the CLI sdist is
  `cliffsec-cli.tar.gz`; the SBOM is `cliffsec-${version}.cdx.json`.
  The 0.2.1 release additionally ships `cliff-${version}.tar.gz`,
  `cliff.tar.gz`, and `cliff-cli.tar.gz` as one-time aliases so 0.2.0
  installers can still resolve their pinned download URLs. Aliases
  dropped in 0.2.2.
- **Renamed the Claude Code plugin from `secure-repo` to
  `cliff-security`, and reshaped it from a monolithic SKILL into an
  action-dispatched skill with versioned per-action playbooks
  (PR #219).** The plugin now covers four actions — `install`,
  `onboarding`, `secure-repo`, and `troubleshooting` — each backed by
  a dedicated playbook in
  `plugins/cliff-security/skills/cliff-security/knowledge/`. The
  top-level `SKILL.md` is a thin dispatcher that picks the right
  playbook based on user intent (or on `cliffsec status` exit code)
  and enforces the cross-cutting hard rules (no auto-approve, no
  auto-merge, no unapproved writes, no auto-submit issues). Each
  playbook carries a `version:` field in its frontmatter that must
  match the SKILL's `version` — a fail-loud integrity check against
  hand-edits or partial upgrades. Install command changes to
  `/plugin install cliff-security@cliff`.
- **GitHub App connection model: the device-flow user access token
  *is* the connection (PR #224, ADR-0048 revised).** The original
  ADR-0048 discovered an `installation_id` from the user token after
  device flow; Q03-B02 validation surfaced three defects in that
  design — `installation_id` was vestigial (clone/push authenticate
  with the user token), "one installation → auto-connect" could bind
  *any* installation the user could see (including an unrelated org,
  producing a false-green that 412'd at push time), and the install
  affordance was unreachable for users with one wrong installation.
  Device-flow success now transitions straight to `connected`; the
  `/user/installations` call, the `GET /installations` and
  `POST /installations/select` routes, and the discovery helpers are
  gone (**net −1500 lines**). The Integrations page surfaces an
  always-on **"Install or manage the Cliff GitHub App"** link. The
  honest per-repo gate (`check_repo_push_access` / the `/diagnose`
  push badge / the executor 412 preflight) is unchanged.

### Fixed

- **Q02 bug batch — 14 fixes from the QA session against `cliff-security/flask`
  (PR #220).** Side-panel state-refresh after `agent_run_completed`
  and `permission_request` SSE events (B16); OpenRouter polling
  defense-in-depth via throttled `/ai/status` check so the OAuth
  modal can't sit on "Waiting for you to authorize" forever (B06);
  Docker Compose publishes `3000:3000` so the recommended OpenRouter
  onboarding works without manual compose edits (B22); manual-recovery
  card no longer hard-codes `localhost:8000` (B03); first-scan banner
  on the Issues page for fresh installs (B24); error rendering uses
  `parseApiError` instead of the raw 400 envelope (B04); posture and
  vulnerability tile subtitles labeled (B07, B08); indefinite-article
  helper fixes "an C" → "a C" on grade letters (B09); auto-fix action
  labels surface what the N and M mean (B10); in-progress empty-state
  copy (B11); confidence tooltip (B14); `authorising` → `authorizing`
  (B22); `/history` page removed (closed findings already scroll into
  view at the bottom of `/issues`) and router redirects `/history →
  /issues` (B19, B20); Integrations catalog filters configured entries
  out of the "Available" grid so GitHub appears exactly once (B15);
  "Mark as fixed" surfaces a "We'll confirm this on the next
  assessment" line (B17).
- **Q03 bug batch — 8 fixes from the Maya Chen QA session against
  `cliff-security/litellm` (PR #223).** Share-report button now
  opens a completion-progress panel (criteria checklist + "N criteria
  to your badge" preview at non-A grades) instead of silently copying
  the URL (B11); a timed-out Semgrep used to render an identical
  green ✓ to a clean "0 findings" run, silently dropping SAST from
  the grade — timeout bumped 120s → 300s (override via
  `CLIFF_SEMGREP_TIMEOUT_S`) and skipped scanners render a distinct
  amber warning with the reason (B07); side panel could stall on
  "Thinking…" after an agent failed when SSE was unavailable —
  `useAgentRuns` invalidates `findings`+`sidebar` on terminal-status
  transition so the poll fallback unsticks the panel (B09); Dashboard
  hero hard-coded `quickWins: 0` while the LevelUp panel listed
  auto-fixable checks — both now derive from the same `level_up.gates`
  data so they can't disagree (B10); repo-picker redirects to
  `/dashboard` after selection instead of leaving the user on
  Settings (B06); doubled `python-diskcache: python-diskcache:`
  vulnerability-title prefix collapsed (B08); GitHub device-code
  expiry follows GitHub's `expired_token` poll result as the single
  authority instead of short-circuiting on the container's wall
  clock (B03); integration card no longer leaks a raw vault
  credential count — shows `repo · @login · Live` instead (B04).
- **Workspace footer silently swallowed the executor's 412
  push-access preflight error (PR #224).** "Approve & generate fix"
  appeared to do nothing when push access was missing. Added
  `FooterActionError` — an inline `role="alert"` with a "How to fix
  this" link — so the per-repo push gate is visible at the point of
  action.
- **`__version__` in `cli/cliff_cli/__init__.py` was stale (PR #218).**
  Pinned at `0.1.1` since the OpenSec→Cliff rename; bumped to `0.2.1`
  alongside this release so `cliffsec --version` reports correctly.

## [0.2.0] - 2026-05-18

The first non-alpha cut. The project is now **Cliff**, lives at
`github.com/cliff-security/cliff`, and ships with the production
GitHub App + Device Flow onboarding. The big themes of this release are
**identity** (rename + repo move), **trust** (real GitHub App, signed
images, ask-tier tool approvals, agent safety guardrails), and a long
list of QA-driven hardening fixes that take Cliff from "alpha that
works on the happy path" to "self-hosted tool you can sit down with on
a Monday morning and use without surprises."

> If you're upgrading from 0.1.7-alpha: pull the new image
> (`ghcr.io/cliff-security/cliff:0.2.0`) or re-run the installer. Your
> `~/.cliff/data` and `~/.cliff/config` directories are preserved; the
> installer is idempotent. PAT-based GitHub installs keep working —
> the new Device Flow path is additive.

### Changed

- **Renamed OpenSec → Cliff and moved to `cliff-security/cliff`
  (PRs #172, #182, #205).** Every user-visible surface — README,
  installer, CLI commands, env-var prefixes (`OPENSEC_*` → `CLIFF_*`),
  Python module (`opensec.*` → `cliff.*`), data dir (`~/.opensec/` →
  `~/.cliff/`) — was migrated. The GitHub redirect from the old
  `galanko/OpenSec` URL keeps existing clones working, and the
  installer transparently picks up the new release-asset names. CLI
  binary is now `cliff`; the old `opensec` binary is removed by
  re-running the installer.
- **OpenRouter default model swapped from `tencent/hy3-preview` to
  `anthropic/claude-haiku-4.5` (PR #212).** The Tencent preview was
  served by a single upstream provider (SiliconFlow) and serialised
  concurrent agent calls into a single queue, causing 600 s wall-clock
  timeouts when the user kicked off multiple remediations at once.
  Claude Haiku 4.5 is multi-provider (Anthropic, AWS Bedrock, Google
  Vertex through OpenRouter) and parallelises cleanly. Tencent Hy3
  stays in the picker for cost-sensitive single-finding flows.
- **Internal architecture docs (ADRs, IMPL plans, PRDs, QA evidence)
  split into a private `cliff-os` umbrella (PR #182).** The public
  repo now carries only end-user-facing docs (`README.md`,
  `ROADMAP.md`, `CONTRIBUTING.md`, `docs/guides/`, `docs/assets/`).
  Architecture decisions still happen — they live alongside the code
  in a private sibling repo per `CLAUDE.md`.

### Added

- **Production GitHub App + Device Flow onboarding (ADR-0035,
  IMPL-0010; PRs #168, #173, #174, #175, #176, #179, #180, #206).**
  Cliff now ships with a real public GitHub App
  ([github.com/apps/cliff-security](https://github.com/apps/cliff-security))
  and uses GitHub's Device Flow to authorise per-instance — the same
  pattern `gh auth login`, the Vercel CLI, and the npm CLI use. No
  PAT to copy and paste, no scope picker to reason about, no
  `client_secret` ever shipped to a self-hosted instance. The
  Integrations page renders a **Connect GitHub** button, an authorise
  modal with an 8-character device code and a 15-minute countdown,
  and a manual `installation_id` recovery field for non-default
  deployments. PAT flow continues to work for legacy installs.
- **Ask-tier tool-use approval for destructive agent actions
  (PR #165).** When the `remediation_executor` requests a "user"-tier
  tool (e.g. `rm -rf`, `git reset --hard`, `git push --force`), the
  agent pauses, the issue lands in a new `awaiting_permission` stage,
  and the side panel prompts the user to **Approve (A)** or **Deny
  (X)** the exact command before the agent proceeds. Auto-approved
  commands (routine `git`, `gh`, build runners) still flow through
  unattended.
- **Push-access preflight + diagnose surface (PRs #168, #180; #176).**
  Before the executor runs, Cliff probes whether the device-flow token
  can actually `git push --dry-run` to the target repo. On 403 from
  GitHub the API returns 412 with a deep-link to the App-permissions
  doc, and Settings → Integrations shows a red "Push blocked" badge
  with a one-click "How to fix" link — so a missing App permission
  surfaces before the agent burns 10 minutes on a doomed run.

### Fixed

- **Agent safety guardrails — no history rewrites on leaked-secret
  findings (PR #209).** The planner used to default to *"use BFG
  Repo-Cleaner to scrub the key from git history"* for
  `type='secret'` findings — a wrong instinct that doesn't un-leak
  the secret (it's already cloned/mirrored/cached), force-pushes a
  multi-thousand-file diff over the default branch, and destroys
  shared history. Real failure surfaced in QA: a NodeGoat PR came in
  at **+22,839 / -2,119 across 139 files** for a single `server.key`
  removal. The planner template now hard-bans BFG, `git filter-repo`,
  `git filter-branch`, and force-push-over-main for secret findings,
  pins the repo plan to `git rm` + `.gitignore` + commit + PR, and
  requires `plan_steps` to include an explicit "rotate the leaked
  credential with the owner" step so the user can't miss the real fix.
- **Agent safety guardrails — no scope creep on dependency bumps
  (PR #214).** The executor used to "be helpful" by mass-upgrading
  adjacent packages when an `npm install` for a single-package bump
  hit peer-dep conflicts. Real failure surfaced in QA: a remediation
  asked to bump `braces` to `^3.0.3` shipped a PR with **14
  packages** touched in `package.json` (mongodb 2→7, cypress 3→15,
  mocha 2→11, …) plus five downgrades to thread the needle — and
  claimed in its `changes_summary` that only `braces` was touched.
  New hard rule #7 in the executor template forbids editing any
  package in the manifest that isn't named in the plan; names the
  per-ecosystem "accept-the-conflict" escapes (`npm install
  --legacy-peer-deps`, `pnpm install --no-strict-peer-dependencies`,
  `cargo update -p`, `go get <name>@<version>`); and exits cleanly to
  `status="needs_approval"` if the conflict can't be resolved without
  scope expansion.
- **Pipeline fails fast on LLM errors and surfaces the failure in the
  UI (PR #210).** Three coupled bugs made out-of-credits errors look
  like "stuck" issues: the pipeline route only treated Python
  exceptions as failures (LLM errors were caught and returned as
  `status='failed'`, so the loop kept retrying — burning credits and
  producing 10+ duplicate `agent_run` rows per workspace); a failed
  pre-plan agent (enricher / owner / exposure / evidence) fell
  through the derivation rules and stayed pinned at `in_progress /
  planning` instead of surfacing as `failed`; and the Retry button
  for `failed` stage hard-coded the executor agent even when the
  failure happened pre-plan, so retry re-failed immediately. All
  three are fixed: out-of-credits → one failed run → issue lands in
  Review with the "Add credits" card and a working Retry.
- **Permission prompt no longer truncates destructive commands
  (PR #208).** The agent-permission card clipped `bash · git push -f
  origin <long-branch>` mid-branch-name with only a hover `title` for
  the full text — unsafe for destructive ops. Command now sits on its
  own full-width row below the title with `break-all` wrapping so the
  user always sees the entire string before deciding.
- **Permission prompt redesigned as a deliberate "pause" moment
  (PR #213).** Three-band editorial composition replaces the cramped
  inline row: amber eyebrow chip frames the moment as a pause, the
  command sits in a tonally-recessed code block with a 2-px amber
  rail down the left edge, and the Approve / Deny actions live at
  the foot right-aligned where the eye lands after reading.
- **Refine flow now visibly tracks the re-run (PR #207).** When the
  user refined the planner's output, the issue-derivation kept the
  stage pinned at `plan_ready` (because the old plan was still in
  the sidebar) and the "Reviewing the advisory…" drafting widget
  never appeared — so refining looked like clicking a button into the
  void. The derivation rule now lets a running planner win over an
  existing plan; the drafting widget renders immediately.
- **Timeout error label reports the real ceiling, not the input arg
  (PR #212).** Tool-agent runs that hit the 600-second wall-clock
  ceiling reported `"Agent timed out after 150s"` because the error
  formatter printed the caller-supplied `timeout` arg instead of the
  `effective_timeout` ceiling the run actually used.
- **"How to fix" link in the executor error card now resolves
  (PR #211).** The link pointed at `/docs/guides/setup-github-app.md`
  — a path the backend doesn't serve and a file extension browsers
  don't render. The doc has been restored to the public repo
  (rebranded Cliff, anchor heading aligned to the link constant) and
  all three call sites (backend 412 preflight, `PushAccessBadge`,
  `IssueSidePanel`) now point at the GitHub-rendered URL. The link is
  also gated on push/permission-shaped error text — non-perm errors
  no longer get a misleading CTA.
- **GitHub App config defaults to the production `cliff-security` app
  (PR #206).** Self-hosted installs ship with the real public
  client_id / slug so the **Connect GitHub** button works on first
  boot; operators can still override via `CLIFF_GITHUB_APP_CLIENT_ID`
  / `CLIFF_GITHUB_APP_SLUG`.
- **QA-driven hardening (PRs #157, #158, #159, #161, #162, #163,
  #167, #169, #170, #171, #173, #175).** Workspace-isolation guard,
  per-workspace npm cache, Spotlight-on-macOS guard, BYOK credential
  propagation into per-workspace OpenCode processes, vault accepts
  URL-safe base64, finding-status reconciliation on PR close, Issues
  UX reactivity polish, posture-severity model fixes — twelve PRs of
  the "found in QA, fixed before ship" pattern that pre-1.0 software
  needs to absorb before it stops embarrassing the maintainer.

### Legal

- **Legal-readiness paperwork (PR #181).** `NOTICE` file with
  attribution, third-party-licenses bundle generated at build time,
  Developer Certificate of Origin (DCO) on contributions, and
  install-time LICENSE preservation so the AGPL-3.0 text travels
  with every deployment.

## [0.1.7-alpha] - 2026-05-06

A stability and lifecycle release. The CLI gains owner-safe daemon
control and a real `cliff update` command, and the dashboard no
longer wedges on a stale "Assessment running" state when the previous
server died mid-scan.

### Added

- **`cliff update` and owner-safe daemon control (PR #141).** New
  `cliff update` command performs a safe in-place upgrade against
  GitHub Releases — snapshot via rename, checksummed download,
  re-run install scripts, doctor, and either restart or roll back;
  `data/` and `config/` are never touched. `--check`, `--yes`,
  `--force`, `--version <tag>` are all supported. `stop` /
  `restart` / `uninstall` now do owner-safe process discovery: a
  process is signalled only if its cmdline proves it's ours
  (uvicorn for `cliff.main:app`, or `argv[0]`/exe equals
  `$CLIFF_HOME/bin/opencode`). Orphan OpenCode processes on
  4096 / 4100–4199 are reclaimed; non-Cliff listeners are
  reported as squatters but never killed. `CLIFF_APP_PORT` is
  now honoured across the lifecycle, not just by `start`.

### Fixed

- **"Re-run assessment" button could stay greyed forever (PR #142).**
  If the server died mid-scan (update, crash, SIGKILL), the
  in-process `asyncio` worker died before its `except` block could
  flip the assessment row to `failed`, leaving it `pending` /
  `running` and the dashboard rendering a permanently-disabled
  "Assessment running" button. FastAPI lifespan now calls
  `reconcile_orphaned_assessments()` right after `init_db()`: any
  `pending` / `running` row at boot is provably orphaned (its
  worker died with the previous process) and is marked `failed`.
  `repo_url` is preserved so the existing fallthrough to
  `ReportCard` renders an enabled "Re-run assessment". Affected
  users on 0.1.6-alpha can unstick themselves before upgrading
  with:

  ```bash
  sqlite3 ~/.cliff/data/cliff.db \
    "UPDATE assessment SET status='failed', completed_at=COALESCE(completed_at, datetime('now')) WHERE status IN ('pending','running');"
  ```

## [0.1.6-alpha] - 2026-05-05

Two themes in this release. First, the Dashboard and assessment surfaces
are rebuilt against the Claude Design v2 handoff so every number on
screen is real data the engine produces or the backend derives — the
fake time-to-close sparkline and abstract "open issues over time"
trend are gone, replaced by a hero grade, open-findings card, derived
Level-Up gates, and a transparent Last-Assessment panel. Second,
Cliff now ships a native `curl | sh` installer for macOS and glibc
Linux alongside Docker, and the `cliff` CLI grows daemon-management
commands so first-run is two commands and a browser tab.

### Added

- **Dashboard + assessment redesign (PR #138).** Hero grade letter
  (168 px Manrope on a primary-container card), open-findings card
  with stacked severity bar and clickable per-severity rows, derived
  Level-Up panel with up to four gates (Ready / PR ready /
  In progress / Auto-fixable / Start) wired to the existing
  `POST /api/posture/fix/{check_name}` endpoint, and a
  Last-Assessment panel that shows scanner names, versions, scope,
  durations, and findings with a sandbox claim. New
  Assessment-running surface (stepped progress card with scanner
  credit pills) plus a Previous-assessment continuity card so data
  doesn't appear to vanish during a fresh scan. Migration `014`
  adds `commit_sha` / `branch` / `scanned_files` / `scanned_deps`
  to `assessment`; `AssessmentTool` gains `duration_ms` / `scope` /
  `ran`; `Posture-Checker` is versioned 1.0.0.
- **Native macOS + Linux installer alongside Docker (PR #139).**
  `curl -fsSL …/install-local.sh | sh` now bootstraps `uv` +
  Python 3.11, downloads the release tarball, installs the backend
  venv plus `opencode` / `trivy` / `semgrep`, generates
  `CLIFF_CREDENTIAL_KEY`, and drops a single `cliff` launcher
  into `~/.local/bin/`. The CLI gains `start` / `stop` / `restart` /
  `logs` / `doctor` / `config` / `uninstall`; `doctor` checks every
  dep + ports + DB + macOS quarantine without starting the daemon
  and supports `--json` for agents. Docker remains the secondary
  path for Windows and advanced users.

### Fixed

- **macOS Gatekeeper quarantine on freshly-downloaded binaries
  (PR #139).** `install-opencode.sh` and `install-scanners.sh` now
  strip the quarantine attribute so first-run doesn't bounce off
  Gatekeeper.
- **Semgrep wrapper survives copy (PR #139).** The Python launcher
  resolves `pysemgrep` via `__file__`, so the previous copy-based
  install broke it. Now installed into a `uv` venv with a thin
  shell wrapper.
- **Trivy 0.52.0 was deleted upstream (PR #139).** Bumped to 0.70.0
  to match the Dockerfile.

### Changed

- **Phase 2 dashboard payload extended additively (PR #138).** The
  wire contract gains `open_by_severity` / `level_up` /
  `last_assessment` / `grade_label` / `grade_caption`; the prior
  Phase 2 fields are still emitted (deprecated) so anything reading
  the old shape keeps working.

## [0.1.5-alpha] - 2026-05-04

PRD-0006 lands end to end: the Issues page, dashboard, and sidenav are
rebuilt against the v2 design handoff, the standalone Workspace page is
gone, and onboarding gains a real GitHub repo picker with scope
verification. The rest of the release is dogfooding-driven fixes —
posture findings render on the Workspace page, the executor + planner
no longer wedge on the failure modes from PR #111, and the Settings
search ranks providers above models.

### Added

- **Issues page Phase 2 (PR #129).** Stage-aware side panel with refine
  and reject actions, sub-grouping, Done-collapse, and the standalone
  Workspace route retired in favor of the panel. `finding.exception_reason`
  + reject endpoint on the API; `user_note` extension on the
  remediation planner.
- **Dashboard refresh Phase 2B (PR #130).** Hero grade, severity metric
  cards, history chart. Dashboard payload extended with the phase-2
  fields. `PostureCard` extracted as its own component.
- **Sidenav redesign (PR #134).** 224px named rail with logo block,
  workspace switcher, Issues count badge, and a labeled Settings
  footer per Claude Design's `IPSideNav`. New `useOpenIssuesCount`
  hook backs the sidenav badge.
- **Onboarding repo picker + scope verification (PR #133).** Real
  GitHub repo picker, provider probe before the AI-config step
  advances, and a workspace repo snapshot stored at install time so
  the rest of the app can show `owner/repo` (workspace switcher
  included).

### Fixed

- **Settings search ranks providers above models (PR #135).** Typing
  a provider name no longer buries the provider row underneath every
  model that mentions it.
- **Sidebar pinned to viewport (PR #136).** The Settings entry was
  scrolling out of view on short viewports; the rail is now fixed so
  the footer stays reachable.
- **Workspace renders posture details (PR #112).** Posture findings
  used to land on a blank Workspace page because the renderer only
  knew about CVE-shaped metadata. Now both shapes render.
- **Executor + planner harden against PR-#111 failure modes
  (PR #113).** Closes the regressions surfaced by the PR-111 incident
  so the agent loop doesn't wedge on the same shapes again.
- **Stale estimate cleared in change handlers, not in `useEffect`
  (PR #127).** The estimate field could keep showing a stale value
  after the user edited the dependent inputs; the clear now fires
  synchronously from the handler.

### Changed

- **README slimmed to what / quickstart / Claude Code (PR #126).**
  Removes the long architecture tour from the front page; the deep
  docs still live under `docs/`.
- **"Secured by Cliff" README badge brand-colored (PR #128).**
  Hoisted onto its own centered line and recolored to the indigo
  primary.

### Chores

- `actions/attest-sbom` 2.4.0 → 4.1.0 (PR #117).
- `astral-sh/setup-uv` 3.2.4 → 8.1.0 (PR #116).
- `actions/checkout` 4.3.1 → 6.0.2 (PR #115).

## [0.1.4-alpha] - 2026-04-30

Dogfooding `/secure-repo` against the Cliff repo itself surfaced a
cluster of bugs across the CLI, scanner, posture checks, dashboard,
and skill — all fixed in this release. The full session log lives in
`docs/dogfooding/secure-repo-session-bugs.md`. Net effect: the CLI ↔
backend contract now actually works end to end, the scanner stops
inventing CVEs out of test fixtures, and posture rendering matches
the underlying state instead of approximating it.

### Fixed — CLI & API

- **`cliff fix` ↔ backend plan-schema mismatch.** CLI looked for
  `plan.steps` / `plan.summary`; backend writes `plan.plan_steps` and
  puts DoD at top-level `definition_of_done.items`. Predicate never
  fired, every fix ran to its 900 s timeout, and `TimeoutError` fell
  through as a raw Python traceback.
- **`poll()` retries on transient 404.** The sidebar row is created
  lazily by the first agent write; the first poll used to die with
  "Sidebar state not found".
- **`_with_client` catches `TimeoutError`** and emits a JSON `code:
  timeout` error per the documented exit-code contract.
- **`cliff approve` reads `pull_request.branch_name`** (was looking
  for the never-written `branch`).
- **CLI bumped to 0.1.1** for the schema fixes; `min_cli` stays at 0.1.0
  (changes are additive).

### Added — CLI

- **`cliff model get / set / list`** — view, change, and list LLM
  models from the terminal. `model list` projects the provider catalog
  locally so the agent driving the CLI never sees the 3 MB blob.

### Fixed — assessment & posture

- **Trivy `--skip-dirs` / Semgrep `--exclude` honor `_fs.SKIP_DIRS`**
  with `**/<name>` glob patterns so test fixtures (`backend/tests/
  fixtures/lockfiles/...`) stop generating phantom CVEs. Self-scan
  dropped from 47 false-positive findings to 0.
- **`CriteriaSnapshot` is tri-state.** Each grade-counting field is
  `True` (verified pass) / `False` (verified fail) / `None` (unknown,
  e.g. no GitHub PAT to query). Frontend can render the third state
  as `?` instead of a misleading ✗. `met_count()` only counts `True`,
  so grading stays conservative.
- **`stale_collaborators` actually works now.** Old code read
  `last_active` off `/repos/.../collaborators` (a field GitHub doesn't
  return) and flagged every collaborator as stale. Now falls back to
  `/users/{login}/events` for per-user activity, with private-only
  contributors recorded as unverifiable instead of auto-flagged. Also
  added the missing `GithubClient.list_collaborators` method (the
  attribute lookup had been returning `None` since the check was
  written).
- **Advisory checks pass-when-clean.** `workflow_trigger_scope` and
  `broad_team_permissions` were perpetually `advisory`; now emit
  `pass` when nothing's flagged so the row leaves the Issues page.
- **`from_posture` honors scanner verdict for advisory.** A passing
  advisory check is persisted with `status='passed'` instead of always
  `status='new'`.
- **`PUT /api/settings/model`** accepts either `{model_full_id}` or
  the GET-shape `{provider, model_id}`.
- **`GET /api/settings/api-keys` surfaces env-sourced keys** with
  `source: "env"`, alongside DB-stored entries (`source: "db"`).

### Fixed — UI

- **Issues page surfaces posture findings.** `/api/findings?scope=current`
  used to filter out `type=posture`; the dashboard knew about failing
  checks but the Issues page didn't. Now includes them, with a
  category-aware `IssuePostureBadge` (Repo config / Code integrity /
  CI/CD / Access) and metadata that hides CVE-only fields.
- **Issues page count matches the dashboard.** Baseline-passing
  posture rows (`status='passed'` + no `pr_url`) are suppressed under
  `scope=current` — they were never actionable issues.
- **Dashboard grade ring shows the right fraction.** `ReportCard`
  was calling a legacy 5-bucket counter and rendering its result
  against `CRITERIA_TOTAL = 10` (so a grade-B repo could read "4 of 10"
  while the API said 9/10). Now uses the v0.2 labeled list.
- **CI workflows pinned to SHAs** (`backend.yml`, `cli.yml`,
  `frontend.yml`). `release.yml` was already pinned. `actions_pinned_to_sha`
  posture criterion now passes.

### Added — `/secure-repo` skill (v0.1.2)

- **Provider-key onboarding step.** Verifies an AI provider key
  (env or DB-sourced) and a GitHub Integration with a PAT in the
  encrypted vault before scanning. Without the integration, every
  GitHub-API posture check returns `unknown` and the grade caps at C
  — the skill makes that visible up front with curl recipes to
  provision either piece via API.
- **Re-assess step.** After the fix loop, the skill re-runs the scan,
  reads `/api/assessment/latest`, and reports the new grade. Calls
  out the GitHub-side criteria the daemon can't change (branch
  protection, secret scanning, stale collaborators).

## [0.1.2-alpha] - 2026-04-30

Adds an agent-shaped surface so Claude Code (and other coding agents)
can drive the full remediation loop without ever opening the web UI.
No app behavior or API changes for existing UI users.

### Added

- **Agent CLI (`cliff`)** — six commands (`status`, `scan`, `issues`,
  `fix`, `approve`, `close`) plus `selftest`. JSON-by-default output;
  exit codes encode workflow state (`0` ok · `2` awaiting human · `3`
  daemon down · `4` version mismatch · `5` clean repo). Published as a
  Python sdist release asset (`cliff-cli.tar.gz`); `scripts/install.sh`
  pip-installs it into `~/.cliff/cli-venv` and symlinks the entry
  point to `~/.local/bin/cliff`.
- **`/secure-repo` Claude Code plugin** — published via Anthropic's
  documented plugin marketplace mechanism (`.claude-plugin/marketplace.json`
  + `plugins/secure-repo/`). Users install explicitly with
  `/plugin marketplace add galanko/Cliff` and
  `/plugin install secure-repo@cliff`. The plugin's skill drives the
  full loop: scan, plan, user-approves, executor, validator, PR, merge
  via `gh`, close. Hard rules: never auto-approve a plan, never
  auto-merge a PR.
- **`GET /api/version`** — version-handshake endpoint returning
  `{cliff, opencode, schema_version, min_cli}`. The CLI calls it once
  per command and refuses to operate when its baked-in version is
  older than `min_cli`.
- **CLI CI** (`.github/workflows/cli.yml`) — lint, tests, sdist build
  on every PR touching `cli/**`.
- **[ADR-0034](docs/adr/0034-agent-cli-and-skill.md)** — design
  rationale for the agent CLI + plugin, including the trust-from-
  first-second decision to avoid silent `~/.claude/` mutation.
- **README** — new "Using Claude Code? Vibe-Security your repo."
  section walks the explicit two-step install (daemon installer +
  `/plugin` commands).

### Changed

- `scripts/install.sh` now installs only the `cliff` CLI to
  `~/.local/bin`; it never touches `~/.claude/`. The end-of-install
  banner prints the two `/plugin` commands the user runs themselves.
- `docs/adr/README.md` — index filled in for ADRs 0025–0034 (had been
  frozen at 0024).

## [0.1.1-alpha] - 2026-04-29

Polishes the install path before handing the alpha to external testers.
No app behavior or API changes.

### Added

- **One-line installer** (`scripts/install.sh`) — `curl -fsSL ...install.sh | sh`
  bootstraps `~/cliff/`, generates `CLIFF_CREDENTIAL_KEY`, prompts
  for an LLM API key, and runs `docker compose up -d` against the
  release image. Re-run any time to upgrade.
- **Docker boot smoke test** (`backend/tests/docker/test_docker_install.py`)
  using testcontainers — pulls the just-built image, boots it with stub
  credentials, and asserts `/health` reaches 200 within 90s. Wired into
  the release pipeline so a "builds-but-doesn't-start" regression
  blocks publish.
- **Platform-specific install notes** in [docs/install.md](docs/install.md)
  for Linux (SELinux, rootless), macOS Docker Desktop, and Windows WSL2.
- README troubleshooting table covering port conflicts, image pull
  failures, restart loops, and host bind-mount permissions.

### Changed

- `docker/docker-compose.yml` now resolves the image tag via
  `${CLIFF_VERSION:-latest}` instead of hardcoding `0.1.0-alpha`.
  Existing users: set `CLIFF_VERSION=0.1.0-alpha` in `.env` to pin.
- `docs/guides/docker-build.md` rewritten — was a "Phase 9 placeholder"
  stub, now documents the local-build path for contributors and points
  end users at [docs/install.md](docs/install.md).
- The release pipeline now uploads `install.sh`, `docker-compose.yml`,
  and `.env.example` as release assets, so
  `/releases/latest/download/install.sh` resolves the curl one-liner.

## [0.1.0-alpha] - 2026-04-28

First public alpha release of Cliff — a self-hosted, single-container,
chat-led cybersecurity remediation copilot. The image is published to
`ghcr.io/galanko/cliff` and is signed via Sigstore keyless OIDC with
SLSA build provenance and a CycloneDX SBOM attestation.

### Added

- **Findings queue** — import (CSV/JSON/Markdown), filter, sort, triage.
- **Chat-led workspace** — persistent chat per finding with structured
  sidebar state (summary, evidence, owner, plan, ticket, validation).
- **Five sub-agents** — Finding Enricher, Owner Resolver, Exposure
  Analyzer, Remediation Planner, Validation Checker. Each agent's output
  persists into both the chat timeline and the SidebarState.
- **Isolated per-workspace runtime** — every workspace gets its own
  directory, finding-specific context, and dedicated OpenCode process
  on a port from the 4100–4199 pool (ADR-0014).
- **History** — searchable, replayable record of every remediation
  session.
- **Single-container Docker image** — multi-stage build with frontend,
  backend, OpenCode, Trivy, Semgrep, and `gh` CLI bundled. Runs on
  `linux/amd64` and `linux/arm64`.
- **Mock-first adapters** — every integration ships with a working
  fixture; real integrations slot into the same interface.
- **Serene Sentinel design system** — calm, editorial, light-mode-first.
- **Security assessment v2** — dashboard payload (ADR-0032) with
  unified findings model from Trivy + Semgrep subprocess execution
  (ADR-0028).

### Security

- **Image runs as non-root user** `cliff` (UID 10001) by default.
- **Image signing** — every published image is signed via Sigstore
  keyless OIDC. Verify with `cosign verify` (see
  [docs/verify-release.md](docs/verify-release.md)).
- **SLSA build provenance** — attached as an attestation. Verify with
  `gh attestation verify oci://ghcr.io/galanko/cliff:0.1.0-alpha
  --owner galanko`.
- **CycloneDX SBOM** — attached both as a Sigstore attestation and as
  a release asset for download.
- **Trivy CVE gate at release** — CRITICAL severities block the
  release; HIGH+CRITICAL are uploaded as SARIF to the GitHub Security
  tab.
- **GitHub Environment gate** — every publish requires reviewer
  approval before any push to `ghcr.io`.
- **All third-party GitHub Actions are SHA-pinned** — Dependabot keeps
  them current.
- **Tag protection** on `v*` prevents accidental tag creation.

### Known limitations (alpha)

- Adapters: only CSV / JSON / Markdown imports and the demo fixture
  are wired today. Real adapters (Snyk, GitHub Advanced Security,
  Tenable, Wiz, ServiceNow) are post-MVP — see [ROADMAP.md](ROADMAP.md).
- Single-user only. No multi-tenant authentication.
- Existing `cliff_data` volumes from pre-alpha dev builds are
  root-owned and will not be writable by the new non-root container.
  One-line migration:
  `docker run --rm --user 0 -v cliff_data:/data alpine chown -R 10001:10001 /data`.

[Unreleased]: https://github.com/cliff-security/cliff/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/cliff-security/cliff/releases/tag/v0.2.1
[0.2.0]: https://github.com/cliff-security/cliff/releases/tag/v0.2.0
[0.1.2-alpha]: https://github.com/cliff-security/cliff/releases/tag/v0.1.2-alpha
[0.1.1-alpha]: https://github.com/cliff-security/cliff/releases/tag/v0.1.1-alpha
[0.1.0-alpha]: https://github.com/cliff-security/cliff/releases/tag/v0.1.0-alpha
