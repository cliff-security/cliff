# Changelog

All notable changes to OpenSec are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.6-alpha] - 2026-05-05

Two themes in this release. First, the Dashboard and assessment surfaces
are rebuilt against the Claude Design v2 handoff so every number on
screen is real data the engine produces or the backend derives — the
fake time-to-close sparkline and abstract "open issues over time"
trend are gone, replaced by a hero grade, open-findings card, derived
Level-Up gates, and a transparent Last-Assessment panel. Second,
OpenSec now ships a native `curl | sh` installer for macOS and glibc
Linux alongside Docker, and the `opensec` CLI grows daemon-management
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
  `OPENSEC_CREDENTIAL_KEY`, and drops a single `opensec` launcher
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
- **"Secured by OpenSec" README badge brand-colored (PR #128).**
  Hoisted onto its own centered line and recolored to the indigo
  primary.

### Chores

- `actions/attest-sbom` 2.4.0 → 4.1.0 (PR #117).
- `astral-sh/setup-uv` 3.2.4 → 8.1.0 (PR #116).
- `actions/checkout` 4.3.1 → 6.0.2 (PR #115).

## [0.1.4-alpha] - 2026-04-30

Dogfooding `/secure-repo` against the OpenSec repo itself surfaced a
cluster of bugs across the CLI, scanner, posture checks, dashboard,
and skill — all fixed in this release. The full session log lives in
`docs/dogfooding/secure-repo-session-bugs.md`. Net effect: the CLI ↔
backend contract now actually works end to end, the scanner stops
inventing CVEs out of test fixtures, and posture rendering matches
the underlying state instead of approximating it.

### Fixed — CLI & API

- **`opensec fix` ↔ backend plan-schema mismatch.** CLI looked for
  `plan.steps` / `plan.summary`; backend writes `plan.plan_steps` and
  puts DoD at top-level `definition_of_done.items`. Predicate never
  fired, every fix ran to its 900 s timeout, and `TimeoutError` fell
  through as a raw Python traceback.
- **`poll()` retries on transient 404.** The sidebar row is created
  lazily by the first agent write; the first poll used to die with
  "Sidebar state not found".
- **`_with_client` catches `TimeoutError`** and emits a JSON `code:
  timeout` error per the documented exit-code contract.
- **`opensec approve` reads `pull_request.branch_name`** (was looking
  for the never-written `branch`).
- **CLI bumped to 0.1.1** for the schema fixes; `min_cli` stays at 0.1.0
  (changes are additive).

### Added — CLI

- **`opensec model get / set / list`** — view, change, and list LLM
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

- **Agent CLI (`opensec`)** — six commands (`status`, `scan`, `issues`,
  `fix`, `approve`, `close`) plus `selftest`. JSON-by-default output;
  exit codes encode workflow state (`0` ok · `2` awaiting human · `3`
  daemon down · `4` version mismatch · `5` clean repo). Published as a
  Python sdist release asset (`opensec-cli.tar.gz`); `scripts/install.sh`
  pip-installs it into `~/.opensec/cli-venv` and symlinks the entry
  point to `~/.local/bin/opensec`.
- **`/secure-repo` Claude Code plugin** — published via Anthropic's
  documented plugin marketplace mechanism (`.claude-plugin/marketplace.json`
  + `plugins/secure-repo/`). Users install explicitly with
  `/plugin marketplace add galanko/OpenSec` and
  `/plugin install secure-repo@opensec`. The plugin's skill drives the
  full loop: scan, plan, user-approves, executor, validator, PR, merge
  via `gh`, close. Hard rules: never auto-approve a plan, never
  auto-merge a PR.
- **`GET /api/version`** — version-handshake endpoint returning
  `{opensec, opencode, schema_version, min_cli}`. The CLI calls it once
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

- `scripts/install.sh` now installs only the `opensec` CLI to
  `~/.local/bin`; it never touches `~/.claude/`. The end-of-install
  banner prints the two `/plugin` commands the user runs themselves.
- `docs/adr/README.md` — index filled in for ADRs 0025–0034 (had been
  frozen at 0024).

## [0.1.1-alpha] - 2026-04-29

Polishes the install path before handing the alpha to external testers.
No app behavior or API changes.

### Added

- **One-line installer** (`scripts/install.sh`) — `curl -fsSL ...install.sh | sh`
  bootstraps `~/opensec/`, generates `OPENSEC_CREDENTIAL_KEY`, prompts
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
  `${OPENSEC_VERSION:-latest}` instead of hardcoding `0.1.0-alpha`.
  Existing users: set `OPENSEC_VERSION=0.1.0-alpha` in `.env` to pin.
- `docs/guides/docker-build.md` rewritten — was a "Phase 9 placeholder"
  stub, now documents the local-build path for contributors and points
  end users at [docs/install.md](docs/install.md).
- The release pipeline now uploads `install.sh`, `docker-compose.yml`,
  and `.env.example` as release assets, so
  `/releases/latest/download/install.sh` resolves the curl one-liner.

## [0.1.0-alpha] - 2026-04-28

First public alpha release of OpenSec — a self-hosted, single-container,
chat-led cybersecurity remediation copilot. The image is published to
`ghcr.io/galanko/opensec` and is signed via Sigstore keyless OIDC with
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

- **Image runs as non-root user** `opensec` (UID 10001) by default.
- **Image signing** — every published image is signed via Sigstore
  keyless OIDC. Verify with `cosign verify` (see
  [docs/verify-release.md](docs/verify-release.md)).
- **SLSA build provenance** — attached as an attestation. Verify with
  `gh attestation verify oci://ghcr.io/galanko/opensec:0.1.0-alpha
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
- Existing `opensec_data` volumes from pre-alpha dev builds are
  root-owned and will not be writable by the new non-root container.
  One-line migration:
  `docker run --rm --user 0 -v opensec_data:/data alpine chown -R 10001:10001 /data`.

[Unreleased]: https://github.com/galanko/OpenSec/compare/v0.1.2-alpha...HEAD
[0.1.2-alpha]: https://github.com/galanko/OpenSec/releases/tag/v0.1.2-alpha
[0.1.1-alpha]: https://github.com/galanko/OpenSec/releases/tag/v0.1.1-alpha
[0.1.0-alpha]: https://github.com/galanko/OpenSec/releases/tag/v0.1.0-alpha
