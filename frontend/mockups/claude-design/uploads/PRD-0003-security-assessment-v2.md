# PRD-0003: Security assessment v2 — best-of-breed scanning + deep posture

**Status:** Approved 2026-04-16 · rev. 2 amended 2026-04-25 (sequenced as v0.2, after PRD-0004 alpha)
**Author:** Product team
**Date:** 2026-04-16, revised 2026-04-25
**Approver:** @galanko (CEO)
**Builds on:** PRD-0002 (v1.1 — "From zero to secure")
**Sequenced after:** PRD-0004 (v0.1 alpha blockers) — PRD-0003 ships as v0.2
**Strategy:** docs/product/security-assessment-strategy.md
**Architecture:** ADR-0027 (unified findings model), ADR-0028 (subprocess-only scanner execution, supersedes ADR-0026)

---

## Revisions

### Rev. 2 — 2026-04-25

Carried forward without scope change. Four amendments fold in decisions that landed between approval and implementation:

1. **Sequencing.** PRD-0003 now ships as **v0.2**, after PRD-0004 (v0.1 alpha blockers). Rationale: get a real external alpha user to Grade A unattended on the existing assessment first, then expand the scanner surface.
2. **govulncheck dropped.** Trivy already covers Go via `go.sum`. The marginal precision did not justify another pinned binary and another supply-chain surface. Removed from Story 1, requirements, and dependencies.
3. **Scanner architecture aligned with ADR-0028.** Subprocess-only execution; binaries pinned by SHA256 checksum in `.scanner-versions`; installed at image build time via `scripts/install-scanners.sh`. The original Story 1 line "auto-installs binary if missing" is gone. The `ScannerAdapter` interface name is now `ScannerRunner` to match the ADR.
4. **Finding storage aligned with ADR-0027.** All findings (Trivy vulns, Trivy secrets, Semgrep code issues, failing posture checks) land in one `finding` table with a typed `type` column (`dependency` | `secret` | `code` | `posture`). PRD copy stays product-shaped; storage detail lives in ADR-0027.
5. **Surfaces ceded to PRD-0004.** PRD-0004 owns the visual design for: the "Run assessment" button (Story 1), Dashboard navigation entry + post-onboarding redirect (Story 2), and the four-state posture-row pattern (Story 3 — leading icon column, row tint, action slot variants by state). PRD-0003 keeps the *content* of the posture checks (which checks, what they verify, fix guidance); the *presentation* defers to PRD-0004's spec.
6. **Phase 1a/1b split is historical.** Per IMPL-0003, Trivy and Semgrep ship together in a single PR. The phased rollout language below is preserved for context but is no longer the delivery shape.

---

## Problem statement

PRD-0002 ships with a homebrew assessment engine: six custom Python lockfile parsers hitting OSV.dev, plus seven GitHub API posture checks. It works — Alex can connect a repo, get findings, remediate, and reach completion. But "works" isn't the same as "credible."

Three problems with the homebrew approach:

**1. Our scanning is shallow compared to what exists for free.** Trivy (34.5k GitHub stars, backed by Aqua Security) covers dependency vulnerabilities, secrets, IaC misconfigurations, and license compliance across every major ecosystem — in a single binary. Our six custom parsers cover dependency vulnerabilities in six ecosystems with none of the edge case handling that Trivy has accumulated over years. We're spending engineering time reinventing a commodity and producing worse results.

**2. Our posture checks are surface-level.** Seven GitHub API checks (branch protection, SECURITY.md, secrets in code, etc.) cover the basics. But the Axiom/xz-utils supply chain attack — where an APT group socially engineered a maintainer over months to gain commit access and release a backdoored version — showed that the real attack surface isn't code. It's the humans and processes around the code. Stale collaborators with write access, CI actions pinned to mutable tags instead of SHAs, no code owners file, no signed commits. These are the gaps that actually get exploited. No existing tool checks them because they're not "vulnerabilities" in the traditional sense. They're organizational hygiene — and they're where Cliff can be genuinely differentiated.

**3. We don't offer SAST or code-quality scanning.** Dependency vulnerabilities are one category. Code-level issues — SQL injection, XSS, insecure deserialization, hardcoded credentials — are another. Semgrep (14.3k stars, $100M raised) offers community rules for free that catch these. Our assessment currently has a blind spot for an entire class of security issues.

The market report (2026-04-15) validates this direction: "Scanning is commoditized. Trivy 34.5k★, Semgrep 14.3k★ — winner-take-most. Cliff should ingest, not compete." Our moat is remediation. Our assessment strategy should maximize finding coverage by standing on the shoulders of best-of-breed tools, then differentiate with posture checks that nobody else offers.

If we don't solve this, the "Secured by Cliff" completion criteria remains a shallow checkbox exercise that any security-aware reviewer will see through. The completion ceremony celebrates something that isn't actually comprehensive. And we leave the most dangerous attack vectors (human/process gaps) completely unchecked.

## Strategic context

This PRD evolves the assessment engine without changing the user-facing product model. Alex's experience stays the same: connect a repo, see a report card, remediate with agents, reach completion. What changes is under the hood — better scanners, deeper checks, more credible results.

**What changes from v1.1 (PRD-0002):**

| Area | v1.1 (PRD-0002) | v2 (this PRD) |
|---|---|---|
| Vulnerability scanning | Homebrew lockfile parsers + OSV.dev | Trivy + Semgrep, subprocess-only, pinned-binary execution per ADR-0028 |
| Secret detection | Regex pattern matching | Trivy secret scanner (industry-standard patterns) |
| SAST / code issues | None | Semgrep community rules (Phase 1b) |
| Posture checks | 7 GitHub API checks | 7 existing + 8 new deep checks (Phase 2a) |
| Posture focus | Repo configuration | Repo configuration + human attack surface + CI supply chain |
| Completion criteria | 5 checks | Expanded to include new posture checks (flat, no tiers) |
| Scanner architecture | Monolithic Python module | Single-implementation `ScannerRunner` protocol (per ADR-0028) — seam preserved for future scanners |
| Tool selection | N/A (homebrew only) | Auto-detect ecosystem → select tools automatically |

**What stays the same:** Onboarding wizard flow, plain-language descriptions, report card dashboard, completion ceremony + shareable summary, remediation agents, chat-led collaboration, import path for existing scanner results.

## User persona

**Same as PRD-0002: Alex, the open-source maintainer who is not a security expert.**

Alex's experience of the assessment itself doesn't change — they still connect a repo and get a report card. What changes is that the report card is now backed by industry-standard scanners (so Alex can trust the results) and covers attack vectors that no other tool surfaces (so the "secured" status actually means something).

**Secondary persona also unchanged:** the security-aware developer who can import their own scanner results. This PRD adds value for them too — the deeper posture checks surface issues they likely haven't thought about.

## Value hypothesis

> If Cliff replaces its homebrew scanning with best-of-breed tools (Trivy, Semgrep) and deepens posture checks to cover human attack surface and CI supply chain risks, the "secured" completion status becomes credible enough that maintainers trust it, security-aware reviewers respect it, and the foundation is set for a public badge that actually means something.

## User stories

### Story 1: Automatic scanner orchestration

**As** an open-source maintainer who just connected my repo, **I want** Cliff to automatically choose and run the best security scanners for my project's tech stack, **so that** I get comprehensive vulnerability coverage without needing to know what scanners exist or how to configure them.

**Given** I've completed the onboarding wizard and my repo is connected,
**When** the assessment runs,
**Then** Cliff detects my repo's ecosystems (e.g., npm + Python from the presence of `package-lock.json` and `requirements.txt`), selects the appropriate scanners (Trivy for dependency vulnerabilities and secrets, Semgrep for code issues when available), runs them against my repo clone, and normalizes all results into the same findings format I'm already used to from PRD-0002.

**The user should feel:** "I didn't have to choose anything. It just figured out what my project needs and checked it. These results look thorough — I trust this."

**How it works under the hood:**

Cliff ships with a `ScannerRunner` protocol (per ADR-0028). On assessment start, Cliff:

1. Scans the repo's file tree for ecosystem markers (lockfiles, config files, language-specific directories)
2. Runs Trivy (always) and Semgrep (when code files are detected)
3. Normalizes all scanner output into the unified `finding` table with a typed `type` column — `dependency` for vuln-scan results, `secret` for Trivy secret-scan hits, `code` for Semgrep, `posture` for failing/advisory checks (per ADR-0027)
4. Each new finding gets a `plain_description` from the LLM normalizer (PRD-0002 behavior, preserved)
5. UPSERT on `(source_type, source_id)` makes re-scans idempotent — user lifecycle state (status, owner, plain_description) survives every re-scan; scanner truth (title, severity, raw_payload) refreshes

**Scanners (per IMPL-0003 — shipping together, single PR):**

| Ecosystem marker | Scanner | What it finds | Finding type |
|---|---|---|---|
| Any lockfile (package-lock.json, go.sum, Gemfile.lock, etc.) | Trivy | Dependency vulnerabilities across all ecosystems | `dependency` |
| Any codebase | Trivy | Committed secrets (API keys, tokens, passwords) | `secret` |
| Dockerfile, docker-compose.yml | Trivy | Container misconfigurations | `dependency` (configuration class within Trivy) |
| Terraform, CloudFormation, Helm | Trivy | IaC misconfigurations | `dependency` (configuration class within Trivy) |
| .js, .ts, .py, .java, .go, .rb, .php files | Semgrep | Code-level vulnerabilities (SQLi, XSS, insecure deserialization, hardcoded creds) | `code` |

> **govulncheck removed in rev. 2 (2026-04-25).** Trivy already covers Go via `go.sum`. The marginal precision gain from govulncheck's call-graph analysis did not justify a third pinned binary and another supply-chain surface. Revisit if Go-repo users specifically request it.

> **Phase 1a / Phase 1b split is historical.** Originally proposed as a hedge; IMPL-0003 ships Trivy + Semgrep together. Future scanners (e.g., govulncheck) would be a separate PRD.

**The transition from homebrew:**

This PRD replaces the six custom lockfile parsers and OSV.dev / GHSA clients entirely. Trivy covers all ecosystems our parsers covered, plus many more (Rust, .NET, PHP, Swift, Dart). The homebrew parsers are removed, not kept as fallback — Trivy is strictly more capable.

The existing import path for Snyk / Dependabot / Trivy JSON files stays unchanged. Users who already run their own scanners can still bring their results.

**Acceptance criteria:**

- [ ] `ScannerRunner` protocol defined per ADR-0028 with: `run_trivy(target_dir, *, timeout) -> TrivyResult`, `run_semgrep(target_dir, *, timeout) -> SemgrepResult`, `available_scanners() -> list[ScannerInfo]`
- [ ] Trivy is invoked as a subprocess against the pinned binary at `bin/trivy`, runs `trivy fs --format json --scanners vuln,secret,misconfig`, parses JSON output
- [ ] Semgrep is invoked as a subprocess against the pinned binary at `bin/semgrep`, runs with the `p/security-audit` rule pack (focused security rules, not the full `p/default`)
- [ ] Ecosystem auto-detection: scans repo file tree, decides whether Semgrep runs (Trivy always runs)
- [ ] All scanner findings persist into the unified `finding` table with the correct `type` (`dependency` | `secret` | `code`) per ADR-0027
- [ ] Plain-language descriptions generated via LLM normalizer for all scanner findings (same quality as PRD-0002). UPSERT preserves prior `plain_description` on re-scan — the LLM is paid only when a finding is new
- [ ] Deduplication via UPSERT on `(source_type, source_id)`: re-scans of the same finding refresh scanner-truth fields and preserve user lifecycle state (status, owner, agent-generated text)
- [ ] Re-scan correctly closes findings that disappeared. Scope is per-`source_type`: a Trivy run does not touch externally-imported Snyk findings even though both are `type='dependency'`
- [ ] Assessment progress indicator shows scanner-specific stages with state ("Detecting…", "Scanning dependencies with Trivy…", "Scanning code with Semgrep…", "Checking repo posture…", "Generating descriptions…")
- [ ] Homebrew lockfile parsers and OSV.dev/GHSA clients removed from codebase when Trivy ships (no fallback period)
- [ ] Trivy and Semgrep binaries are baked into the Docker image at build time via `scripts/install-scanners.sh`, with SHA256 verification against `.scanner-versions`. Build fails on checksum mismatch (per ADR-0028). Strict checksum mode is the default at runtime; `CLIFF_SCANNER_CHECKSUM_VERIFY=warn` is an opt-in for air-gapped mirrors
- [ ] Scanner subprocesses receive a minimal env whitelist (`PATH`, `HOME`, `LANG`, scanner cache dirs only). The GitHub PAT is **not** in the scanner env (per ADR-0028)
- [ ] Assessment completes within 5 minutes for a repo with 500 dependencies
- [ ] Semgrep findings render with a visual indicator on the finding card: "Code issue — may require manual review" (distinct from dependency findings which agents can auto-fix)
- [ ] Semgrep findings are included in the report-card vulnerability count but do NOT block completion criteria until SAST remediation agents ship (separate future PRD)

---

> **Visual presentation of posture rows (Stories 2–4)** — the four-state row pattern (To do / Running / Done / Failed), leading-icon column, row tint, action-slot variants, and group progress rail are owned by **PRD-0004 Story 3**. PRD-0003 owns the *content* of each posture check (which checks exist, what they verify, why they matter, fix guidance). The visual spec lives in PRD-0004 and the UX spec produced from it.

### Story 2: Deep repo posture — CI supply chain

**As** an open-source maintainer, **I want** Cliff to check whether my CI/CD pipeline is vulnerable to supply chain attacks, **so that** I don't become the next xz-utils or tj-actions incident.

**Given** the assessment has run and my repo has GitHub Actions workflows,
**When** I view the posture section of the report card,
**Then** I see checks for CI supply chain risks that go beyond the basics: are my third-party actions pinned to commit SHAs (not mutable tags)? Am I using actions from trusted sources? Are there overly permissive workflow triggers?

**The user should feel:** "I had no idea my CI pipeline was a security risk. These checks caught something I never would have found myself."

**Posture checks — CI supply chain (new in this PRD):**

| Check | What it verifies | Why it matters | Fix guidance |
|---|---|---|---|
| Actions pinned to SHA | Third-party GitHub Actions reference a commit SHA, not a tag or branch | Tags are mutable — a compromised action maintainer can push malicious code to an existing tag (tj-actions/changed-files incident, March 2025) | "Pin `actions/checkout@v4` to `actions/checkout@b4ffde65f46336ab88eb53be808477a3936bae11`. Cliff can generate the pinned versions for you" |
| Trusted action sources | Actions come from verified publishers or well-known organizations (actions/*, github/*, etc.) | Unknown third-party actions with write permissions are supply chain risk | "Review these actions from unverified sources: [list]. Consider replacing with alternatives from verified publishers" |
| Workflow trigger scope | `pull_request_target` and `workflow_dispatch` triggers reviewed for injection risk | `pull_request_target` runs in the context of the base branch with write access — a common source of GitHub Actions exploits | "This workflow uses `pull_request_target` with `checkout` of PR code. This pattern is dangerous. See [GitHub security guide link]" |

**Acceptance criteria:**

- [ ] CI supply chain checks scan all `.github/workflows/*.yml` files
- [ ] SHA pinning check identifies all third-party actions using tag or branch references instead of commit SHAs
- [ ] SHA pinning check provides the correct pinned SHA for each unpinned action (looked up via GitHub API)
- [ ] Trusted source check flags actions not from GitHub-verified publishers
- [ ] Workflow trigger check identifies dangerous `pull_request_target` + `checkout` patterns
- [ ] Each failing check shows the specific file, line number, and action reference
- [ ] Fix guidance for SHA pinning includes an "Cliff can pin these for you" action that generates a PR with all actions pinned to their current SHAs
- [ ] All CI supply chain checks are completion criteria

---

### Story 3: Deep repo posture — collaborator hygiene

**As** an open-source maintainer, **I want** Cliff to flag risky collaborator access patterns, **so that** I reduce my exposure to compromised or disengaged accounts with write access to my repo.

**Given** the assessment has run,
**When** I view the posture section of the report card,
**Then** I see checks for collaborator access risks: stale collaborators who haven't contributed in months but still have write access, and overly broad team permissions that give more access than needed.

**The user should feel:** "I forgot these people still had write access. This is exactly the kind of thing that leads to supply chain attacks — and I never would have checked on my own."

**Posture checks — collaborator hygiene (new in this PRD):**

| Check | What it verifies | Why it matters | Fix guidance |
|---|---|---|---|
| Stale collaborators | No collaborators with write/admin access whose last contribution was >90 days ago | Inactive accounts with write access are a prime target for credential theft or social engineering (the xz-utils attacker cultivated trust with an existing maintainer over months) | "These collaborators haven't contributed in 90+ days but have write access: [list with last activity date]. Consider removing write access or reaching out to confirm they're still active" |
| Overly broad team permissions | Teams with write access have <20 members (heuristic) | Large teams with write access expand the attack surface — more credentials to compromise | "Team '[name]' has [N] members with write access. Consider creating a smaller team for direct contributors" |
| Default branch permissions | Repository default permission for org members is "read" not "write" | Overly permissive defaults give write access to people who don't need it | "Default org member permission is 'write'. Change to 'read' in repo settings and grant write access explicitly" |

**Acceptance criteria:**

- [ ] Stale collaborator check queries GitHub API for all collaborators with write/admin access and their last contribution date
- [ ] "Stale" threshold is 90 days with no commits, PRs, or reviews (configurable in settings for future flexibility)
- [ ] Overly broad team check queries teams with write access and their member counts
- [ ] Default permission check reads repo and org-level default permissions
- [ ] Each check handles API rate limiting gracefully (retry with backoff, show "unable to verify" if rate limited)
- [ ] If the PAT lacks permission to read collaborators (requires repo scope), the check shows "additional permissions needed" with specific instructions
- [ ] All collaborator hygiene checks are completion criteria

---

### Story 4: Deep repo posture — code integrity

**As** an open-source maintainer, **I want** Cliff to verify that my repo has code integrity protections in place, **so that** I can be confident that the code in my repo is what my contributors actually wrote.

**Given** the assessment has run,
**When** I view the posture section of the report card,
**Then** I see checks for code integrity: secret scanning enabled, code owners file exists, signed commits encouraged, and Dependabot or Renovate configured for automated dependency updates.

**The user should feel:** "These are the things I kept meaning to set up but never got around to. Now I can see exactly what's missing and how to fix it."

**Posture checks — code integrity (new in this PRD):**

| Check | What it verifies | Why it matters | Fix guidance |
|---|---|---|---|
| Secret scanning enabled | GitHub secret scanning is turned on for the repo | Catches accidentally committed tokens and keys before they're exploited | "Enable secret scanning: Settings > Code security and analysis > Secret scanning" |
| Code owners file | `CODEOWNERS` file exists in `.github/`, `docs/`, or repo root | Ensures PRs to sensitive paths require review from designated owners | "Create a CODEOWNERS file. Cliff can generate one based on your git blame history" |
| Signed commits | Whether the repo encourages or requires commit signing | Signed commits prove authorship — unsigned commits can be spoofed | "Consider requiring signed commits for the default branch. See GitHub docs on commit signing setup" |
| Dependabot/Renovate configured | Automated dependency update tool is set up | Keeps dependencies current, reducing the window of vulnerability exposure | "Create a `.github/dependabot.yml` config. Cliff can generate this for you" |

**Acceptance criteria:**

- [ ] Secret scanning check queries GitHub API for repo security settings
- [ ] Code owners check scans for `CODEOWNERS` in `.github/`, `docs/`, and repo root
- [ ] Signed commits check reads branch protection rules for commit signing requirements
- [ ] Dependabot check looks for `.github/dependabot.yml` or `renovate.json` / `.renovate.json`
- [ ] For CODEOWNERS and Dependabot: "Cliff can generate this" action triggers an agent that creates the file and opens a PR (same pattern as PRD-0002's SECURITY.md generator)
- [ ] All code integrity checks are completion criteria

---

### Story 5: Updated onboarding — zero-config scanner experience

**As** a first-time user, **I want** the onboarding wizard to set up scanning automatically without asking me to choose tools, **so that** I can go from "just installed" to "assessment running" without understanding what a scanner is.

**Given** I'm going through the onboarding wizard (same 3-step flow from PRD-0002),
**When** I reach Step 3 ("Start security assessment"),
**Then** I see a brief explanation of what Cliff will do — "We'll scan your repository using industry-standard security tools (Trivy, Semgrep) and check your repo's security configuration. This usually takes 2-5 minutes." — and the assessment runs automatically with a progress indicator showing which scanner is running.

**The user should feel:** "It mentioned real tools I might have heard of — Trivy, Semgrep. That gives me confidence this is thorough. And I didn't have to choose or configure anything."

**What changes from PRD-0002's onboarding:**

- Step 1 (Connect your project): unchanged
- Step 2 (Configure your AI): unchanged
- Step 3 (Start assessment): updated copy to reference the scanner tools by name (builds trust through transparency). Progress indicator now shows scanner-specific stages: "Detecting project type...", "Scanning dependencies with Trivy...", "Scanning code with Semgrep...", "Checking repo posture...", "Generating plain-language descriptions..."
- Post-onboarding redirect: the wizard hands off to **Dashboard**, not Findings. This was decided in PRD-0004 Story 2 and applies to v0.2 as well. PRD-0003 inherits the change rather than re-spec'ing it.

**Acceptance criteria:**

- [ ] Onboarding Step 3 copy updated to reference Trivy/Semgrep by name
- [ ] Assessment progress indicator shows scanner-specific stage names
- [ ] No scanner selection UI — tool choice is fully automatic
- [ ] If a scanner is not installed or fails, the assessment continues with remaining scanners and shows a note: "Some checks were skipped — [reason]"
- [ ] Assessment results include a "Scanned by" metadata line on the report card showing which tools were used (e.g., "Scanned by: Trivy 0.52, Semgrep 1.70")

---

### Story 6: Updated completion criteria

**As** an open-source maintainer working toward completing my security posture, **I want** the completion criteria to reflect the deeper checks so that "secured" actually means something comprehensive, **so that** I can be genuinely confident my repo meets a high security bar.

**Given** the expanded assessment has run (scanner orchestration + deep posture),
**When** I view the completion progress on the report card,
**Then** I see an updated set of completion criteria that includes the new posture checks alongside the original PRD-0002 criteria.

**The user should feel:** "This is thorough. When I complete all of these, my repo will genuinely be well-secured — not just checked off."

**Updated completion criteria (flat — all required):**

*Carried from PRD-0002:*
1. Zero open critical-severity vulnerability findings
2. Zero open high-severity vulnerability findings
3. Branch protection enabled on default branch
4. No secrets detected in code
5. SECURITY.md exists

*New in PRD-0003:*
6. CI actions pinned to commit SHAs (no mutable tag references)
7. No stale collaborators with write access (>90 days inactive)
8. Code owners file exists
9. Secret scanning enabled on repo
10. Dependabot or Renovate configured

**What's NOT a completion criterion (and why):**
- Signed commits: advisory only. Requiring this would block maintainers who haven't set up GPG keys, and the setup is nontrivial. Shown as "recommended" on the posture card.
- Overly broad team permissions: advisory only. The heuristic (team size) is too blunt for a hard requirement. Flagged for awareness.
- Workflow trigger scope: advisory only. Some repos legitimately use `pull_request_target` with proper safeguards. Flagged for review.
- SAST findings (Phase 1b): displayed but not blocking until SAST remediation agents ship.

**Grading impact:**

The letter grade (A-F) adjusts to the expanded criteria set: A = all 10 met, B = 8-9, C = 6-7, D = 4-5, F = 0-3. Same intuitive scale, wider coverage.

**Acceptance criteria:**

- [ ] Report card displays all 10 completion criteria with pass/fail status
- [ ] New criteria (6-10) appear in the posture section alongside the existing 5
- [ ] Letter grade recalculated against 10 criteria (A = 10/10, B = 8-9, etc.)
- [ ] Advisory checks (signed commits, broad permissions, trigger scope) shown with an "info" indicator, not pass/fail
- [ ] Completion ceremony fires when all 10 criteria are met (same celebration UX from PRD-0002)
- [ ] Shareable summary card updated to reflect the expanded criteria count
- [ ] "Run assessment" / "Re-run assessment" button re-runs all scanners + all posture checks. **Visual design is owned by PRD-0004 Story 1** (top-right of Dashboard, disabled-while-running, previous report card visible beneath the progress indicator). PRD-0003 inherits the surface and adds the new scanner stages

---

## Requirements

### Must-have (P0) — ship cannot go out without these

- **Trivy adapter + auto-detection** (Story 1, Phase 1a) — replaces homebrew parsers with better coverage
- **`ScannerRunner` protocol** (Story 1) — extensible seam for adding future tools (per ADR-0028)
- **CI supply chain checks** (Story 2) — the highest-value new posture checks, directly addresses supply chain attack risk
- **Stale collaborator check** (Story 3) — the human attack surface check that inspired this entire PRD
- **Code owners file check** (Story 4) — simple, high-impact, achievable
- **Secret scanning enabled check** (Story 4) — leverages GitHub's built-in capability
- **Dependabot/Renovate check** (Story 4) — automated dependency updates are table stakes
- **Updated completion criteria** (Story 6) — the whole point: "secured" means something comprehensive
- **Updated onboarding copy** (Story 5) — references real tools for trust

### Nice-to-have (P1) — improves experience significantly

- **Semgrep adapter** (Story 1) — SAST coverage, flagged as manual review. Was originally Phase 1b; now ships in the same PR as Trivy per IMPL-0003
- **CODEOWNERS generator agent** (Story 4) — generates file from git blame history
- **SHA pinning generator agent** (Story 2) — pins all actions to current SHAs in one PR
- **Dependabot.yml generator agent** (Story 4) — carried from PRD-0002, now more important
- **Signed commits advisory** (Story 4) — display + guidance, not blocking

### Future considerations (P2) — design for but don't build

- **SAST remediation agents** — auto-fix code-level vulnerabilities found by Semgrep. Separate PRD. Requires significant prompt engineering for each vulnerability class
- **GitHub org admin checks** — 2FA enforcement, SSO, audit logs. Not our ICP yet (individual maintainers)
- **User-level security posture** — passkey verification, credential hygiene. GitHub API doesn't expose this for individual users. Revisit if API evolves
- **Tiered completion levels** — if data shows completion rate dropping below 50%, consider Secured/Hardened/Fortified tiers. No users yet = no data = no tiers
- **OpenSSF Scorecard integration** — run Scorecard ourselves or align criteria. Deferred per PRD-0002 decision
- **Scanner marketplace** — let users enable/disable specific scanners. Over-engineering for now

## Success metrics

| Metric | Target | How measured |
|---|---|---|
| Finding coverage improvement | >2x findings vs homebrew engine on same repo | Compare Trivy results vs homebrew parser results on 5 test repos |
| Assessment time | <5 minutes for repos with 500 dependencies | Benchmark against test repos |
| Completion rate | >50% of users reach all 10 criteria within one week | Track completion criteria progression (same as PRD-0002 but against 10 criteria) |
| Posture check accuracy | Zero false positives in posture checks across 10 test repos | Manual validation against known repo states |
| New finding categories | >30% of findings come from sources homebrew didn't cover (secrets, misconfigs) | Count findings by source scanner |
| Scanner reliability | <1% assessment failures due to scanner errors | Track scanner adapter error rates |

## Scope

### In scope

- Trivy subprocess runner with vuln + secret + misconfig scanning, JSON output parsing
- Semgrep subprocess runner with `p/security-audit` rule pack
- `ScannerRunner` protocol (single implementation per ADR-0028; protocol seam preserved for future scanners)
- Unified `finding` table with typed `type` column (per ADR-0027) — replaces the deprecated `posture_check` table
- Pinned binary checksums in `.scanner-versions`; install via `scripts/install-scanners.sh` at image build / dev time
- 8 new posture checks (3 CI supply chain + 3 collaborator hygiene + 2 code integrity + Dependabot)
- Updated completion criteria (10 total, flat)
- Updated letter grade scale
- Onboarding copy referencing scanner tools
- Assessment progress with scanner-specific stages
- Removal of homebrew lockfile parsers and OSV.dev client
- Docker image updated to include Trivy binary
- CODEOWNERS generator agent
- SHA pinning generator agent
- Existing import path (Snyk, Dependabot JSON) unchanged

### Out of scope (and why)

- **SAST remediation agents** — Semgrep finds code issues, but auto-fixing them requires per-vulnerability-class prompt engineering. Separate PRD after remediation quality is proven
- **GitHub org admin features** — 2FA enforcement, SSO checks, audit log access. Our ICP is individual maintainers who don't have org admin access. Revisit when enterprise personas enter
- **User-level security checks** — passkey verification, credential hygiene beyond GitHub API. Data access limitations make this infeasible today
- **Scanner selection UI** — Alex doesn't choose scanners. Auto-detection only. Power users import their own results
- **Parallel scanner execution** — Run scanners sequentially for v1. Parallel is an optimization for later
- **Custom Semgrep rules** — Community rules only. Custom rule authoring is a power-user feature for later
- **Tiered completion levels** — No users, no data, no tiers. Revisit with real completion rate data

## Dependencies

**Upstream (from PRD-0002, assumed complete):**

- Assessment engine module (`backend/cliff/assessment/`)
- Finding normalization with `plain_description` via LLM normalizer (ADR-0022)
- Report card dashboard page with completion progress tracking
- Completion ceremony and shareable summary card
- Posture check display on report card (pass/fail/info states)
- GitHub PAT with repo scope configured in credential vault
- Docker build pipeline

**New infrastructure needed:**

- Trivy and Semgrep binaries: pinned by SHA256 in `.scanner-versions`, downloaded from each project's GitHub releases, installed via `scripts/install-scanners.sh` (used by both `scripts/dev.sh` and `docker/Dockerfile`). Strict checksum verification by default — see ADR-0028
- `ScannerRunner` protocol module: `backend/cliff/assessment/scanners/`
- Ecosystem auto-detection helper inside the engine (no separate module; gates whether Semgrep runs)
- Unified findings: schema migration to add `type`, `grade_impact`, `category`, `assessment_id` columns to `finding`; deprecate `posture_check` table; deterministic mapper module `backend/cliff/assessment/to_findings.py` per ADR-0027
- Updated posture check registry: extend `backend/cliff/assessment/posture/` with new check modules
- CODEOWNERS generator agent template
- SHA pinning generator agent template

**Downstream (unblocked by this PRD):**

- Public "Secured by Cliff" README badge (v1.2) — now backed by credible assessment
- SAST remediation agents (future PRD) — Semgrep findings exist, agents don't yet
- OpenSSF Scorecard alignment — criteria overlap now closer, integration more meaningful
- Enterprise posture features — org admin checks build on this foundation

## Resolved questions

- [x] **Trivy version pinning strategy:** Pin to a specific version. Trivy itself was targeted in a supply chain attack, so we must practice what we preach. *Originally:* pin in `.trivy-version`, auto-download script validates checksum, manual bumps required. *Superseded by ADR-0028 (2026-04-19):* pinning is per-SHA256-checksum (not per-tag) for both Trivy and Semgrep, in a unified `.scanner-versions` file. The release-time review of that file is the human gate. *Decided by: CEO (2026-04-16); evolved by ADR-0028 / rev. 2 (2026-04-25)*
- [x] **Semgrep rule set scope:** Use `p/security-audit` (focused, security-only rules). `p/default` (~500 rules) would overwhelm Alex with non-security findings. Start narrow, expand later if users ask for more. *Decided by: CEO (2026-04-16)*
- [x] **Stale collaborator threshold:** 90 days, not configurable. Keep it simple — no settings UI for this. If feedback from real users shows 90 days is too aggressive, revisit with data. *Decided by: CEO (2026-04-16)*
- [x] **CODEOWNERS generation accuracy:** Generated from git blame heuristic, but the PR must be reviewed and approved by the user before merge (same draft PR pattern as all Cliff-generated PRs). The user is the final authority on who owns what. *Decided by: CEO (2026-04-16)*
- [x] **Homebrew parser removal timing:** Remove immediately when Trivy adapter ships. No fallback period. Trivy is strictly more capable — keeping dead code adds maintenance burden and confusion. *Decided by: CEO (2026-04-16)*
- [x] **Sequencing relative to PRD-0004 (rev. 2):** PRD-0003 ships as **v0.2**, after PRD-0004 (v0.1 alpha blockers). Get an external alpha user to Grade A unattended on the existing assessment first, then expand the scanner surface. *Decided by: CEO (2026-04-25)*
- [x] **govulncheck (rev. 2):** Dropped. Trivy already covers Go via `go.sum`. Marginal precision gain did not justify a third pinned binary and another supply-chain surface. Revisit if Go-repo users specifically request it. *Decided by: CEO (2026-04-25)*
- [x] **Scanner execution model (rev. 2):** Subprocess-only, per ADR-0028 (which supersedes ADR-0026). No Docker-in-Docker scanner runner — the production deployment path would have required mounting `/var/run/docker.sock`, which is strictly worse than subprocess execution. Supply-chain defense moved to pinned SHA256 binary checksums + minimal env whitelist for the subprocess (no PAT). *Decided by: CEO (2026-04-19, formalized into PRD on 2026-04-25)*
- [x] **Finding storage model (rev. 2):** Unified `finding` table with typed `type` column (`dependency` | `secret` | `code` | `posture`), per ADR-0027. The `posture_check` table from PRD-0002 is deprecated. `(source_type, source_id)` UPSERT preserves user lifecycle state and expensive LLM-generated text on re-scans. *Decided by: CEO (2026-04-19, formalized into PRD on 2026-04-25)*

## Open questions

All resolved. No remaining blockers for v0.2 implementation planning.

---

_This PRD follows the Cliff product workflow. After the rev. 2 amendment (2026-04-25), the PRD is handed to **Claude design** for mockups (replacing the `/ux-designer` skill on this round), then to `/architect` to refresh IMPL-0003 against the agreed scope. Design hand-off uses a self-contained context bundle — see `docs/design/briefs/PRD-0003-claude-design-brief.md` (created alongside this revision)._
