# PRD-0002: From zero to secure — OSS security assessment and remediation

**Status:** Approved 2026-04-16 — CEO approved
**Author:** Product team
**Date:** 2026-04-12 (original) / 2026-04-15 (revision)
**Approver:** @galanko (CEO)
**Builds on:** PRD-0001 (MVP v1.0 — agentic remediation with PR creation)

---

## Revision note (2026-04-15)

The original PRD-0002 was titled "Earn the Badge" and bet on a public "Secured by Cliff" README badge as both the user's goal and Cliff's growth engine. After a brainstorm pass with the CEO, the badge has been **deferred to v1.2**. Rationale:

- The badge needs brand recognition to deliver consumer-side trust. Cliff has none yet.
- Static, self-declared security badges have a poor reputation history in OSS.
- Competing with the incumbent (OpenSSF Scorecard) is a weaker position than complementing it.
- Automatically adding a badge to a maintainer's README is the one place a security tool must be maximally above-board — a stronger brand is needed before this becomes an asset.

v1.1 keeps the hard technical bet (assessment engine, plain-language descriptions, posture checks, remediation) and replaces the public badge with a **private completion ceremony + shareable summary card**. The public README badge returns in v1.2 once the core product is validated with real maintainers and the criteria and brand are tightened.

The title, comparison table, Story 5, acceptance criteria, success metrics, and scope sections have been updated accordingly. Stories 1-4 and 6 are substantively unchanged.

---

## Problem statement

PRD-0001 built Cliff for a developer who already knows security — someone who has Snyk installed, understands CVEs, and just wants the remediation work done faster. That's a real pain point, but a narrow audience.

The bigger opportunity is the open-source maintainer who has *no security tooling at all*. They maintain a popular library or side project. They know they should "do something about security" but they don't know where to start, what tools to install, or what a CVE even means in practical terms. They have no Snyk, no Dependabot, no security scanner configured. They have a GitHub repo and good intentions.

Today, securing an open-source project requires: choosing a scanner, configuring it, interpreting its output (which is written for security engineers, not developers), figuring out fixes, and doing the remediation work. Most maintainers never start because step one is already overwhelming.

If we don't solve this, open-source projects — which power most of the world's software — remain systematically under-secured. And Cliff remains a tool for the small audience of security-aware developers instead of becoming the default way open-source gets secured.

## Strategic context

This PRD shifts Cliff's target from "security-savvy developer who already has findings" to "any open-source maintainer who wants their project secured." The product becomes the entry point — it finds the problems, explains them in plain language, fixes them, and celebrates when the repo meets a baseline security standard.

**Distribution strategy for v1.1:** word-of-mouth through the CEO's OSS network. Friends and personally-known maintainers install Cliff on real repos, remediate real vulnerabilities, and share their experience. A shareable completion card provides a lightweight viral artifact without the risk profile of a public README badge. The public badge returns in v1.2 after the core flow is validated.

**What changes from v1.0:**

| Area | v1.0 (PRD-0001) | v1.1 (this PRD) |
|---|---|---|
| Entry point | User imports Snyk JSON manually | Cliff runs its own assessment + imports from existing tools |
| Target user | Developer with Snyk findings | Any maintainer, including security-clueless |
| Finding descriptions | Technical CVE data | Plain-language explanation + technical details accessible |
| Posture awareness | None | Repo posture report card (display-only, not auto-remediated) |
| End state | PRs created for findings | PRs created + completion ceremony + shareable summary card |
| Onboarding | Empty state with import prompt | Guided 3-step wizard (repo, LLM, assessment) |
| Distribution | Word of mouth | Word of mouth + shareable summary card (public README badge deferred to v1.2) |

**What stays the same:** Self-hosted architecture, GitHub PAT for auth, single-workspace one-at-a-time remediation, 4-agent pipeline (enrich -> analyze -> plan -> remediate), chat-led collaborative model, draft PRs as the trust mechanism.

## User persona

**Primary: Open-source maintainer who is not a security expert**

Alex maintains a moderately popular Node.js library (2k stars, 50 contributors). They're a strong developer but security is not their domain. They've seen security badges on other repos and heard about supply chain attacks in the news. They want to "do the right thing" but don't know where to start. They've never configured a security scanner and find CVE descriptions incomprehensible.

What Alex cares about:
- "Is my project actually vulnerable? I genuinely don't know."
- "I don't speak security jargon. Tell me what's wrong in terms I understand."
- "Just fix it for me. I'll review the code, but I don't want to research the fix."
- "I want to feel like I actually did something meaningful for my users."

**Secondary: Security-aware developer (v1.0 persona)**

Still fully supported. They can skip the assessment and import their own Snyk/Trivy/Dependabot findings directly. The enhanced plain-language descriptions, posture checks, and completion ceremony are value-adds for them too.

## Value hypothesis

> If an open-source maintainer can install Cliff, connect their GitHub repo, have it automatically assess their security posture, explain problems in plain language, fix the vulnerabilities through collaborative AI agents, and reach a visible completion milestone they can share — they will secure their project when they otherwise would not have.

The completion ceremony is the reward. The plain-language descriptions remove the knowledge barrier. The agentic remediation removes the work barrier. The shareable summary gives the maintainer something concrete to celebrate publicly if they choose, without Cliff writing to their README unprompted.

---

## User stories

### Story 1: First-run onboarding

**As** an open-source maintainer installing Cliff for the first time, **I want** a guided setup experience that walks me through connecting my project and getting started, **so that** I can go from "just installed" to "assessment running" without reading documentation.

**Given** I've started Cliff for the first time (empty database, no configuration),
**When** the app loads,
**Then** I see a welcoming onboarding wizard — not an empty dashboard — that walks me through three steps: connect my GitHub repo, configure my AI model, and start the security assessment.

**The user should feel:** "This is friendly and professional. It's holding my hand without being condescending. I know exactly what to do."

**Onboarding flow:**

**Step 1 — Connect your project**
- GitHub repo URL field with placeholder text showing the expected format
- Personal access token field with a "How to create a token" help link that explains which scopes are needed (repo access for cloning + pushing + PR creation)
- "Test connection" button that validates: repo exists, token has correct permissions, can clone and push
- Success state shows repo name, visibility (public/private), and default branch
- Error states are specific and actionable: "Token doesn't have push access — you need the `repo` scope" (not "connection failed")

**Step 2 — Configure your AI**
- Model provider selection (OpenAI, Anthropic, local — whatever OpenCode supports)
- API key field
- "Test connection" button that validates the key works
- Brief explanation: "Cliff uses AI agents to understand vulnerabilities and write fixes. Your API key is stored locally and never sent to Cliff servers."
- Optional: model selection dropdown if the provider supports multiple models

**Step 3 — Start security assessment**
- Summary of what will happen: "We'll scan your repository for known vulnerabilities in dependencies and check your repo's security configuration. This usually takes 2-5 minutes."
- "Start assessment" button
- Transitions to the report card view (Story 2) with a progress indicator

**Acceptance criteria:**

- [ ] Onboarding wizard appears on first launch (no findings in DB, no repo configured)
- [ ] Wizard does NOT appear if the user has already completed setup (repo + LLM configured)
- [ ] User can skip the wizard and go directly to the app (for the v1.0 persona who wants manual import)
- [ ] Each step validates before allowing progression to the next
- [ ] "Test connection" buttons provide specific, actionable error messages (not generic "failed")
- [ ] GitHub token is stored in the existing credential vault
- [ ] LLM API key is stored securely
- [ ] Back button allows revisiting previous steps
- [ ] Progress indicator shows which step the user is on (1/3, 2/3, 3/3)
- [ ] Onboarding visuals follow the Serene Sentinel design system
- [ ] The entire onboarding flow is completable in under 3 minutes (assuming the user has their GitHub token and API key ready)

---

### Story 2: Security assessment and report card

**As** an open-source maintainer who just connected my repo, **I want** Cliff to assess my project's security posture automatically, **so that** I understand where I stand without needing to know what to look for.

**Given** I've completed the onboarding wizard and clicked "Start assessment,"
**When** the assessment runs,
**Then** I see a progress indicator as Cliff scans my repo, and when it finishes, I see a security report card — a visual dashboard showing my repo's security posture broken into two categories: vulnerabilities and repo posture.

**The user should feel:** "Now I know where I stand. I can see exactly what needs fixing, and it doesn't feel overwhelming because it's organized and clear."

**Assessment engine — what it checks:**

*Vulnerabilities (auto-remediated via agents):*
- Parse lockfiles (package-lock.json, yarn.lock, Pipfile.lock, go.sum, Gemfile.lock, etc.) and cross-reference against known CVE databases
- Detect outdated dependencies with known security advisories
- If the user has existing tool findings (Dependabot alerts, Snyk JSON, Trivy output), import and deduplicate against Cliff's own scan
- Each finding is normalized into Cliff's finding model with both technical data AND plain-language description (Story 3)

*Repo posture (displayed with fix guidance, not auto-remediated):*
- Branch protection: is the default branch protected? Are force pushes allowed? Is review required?
- Secrets in code: scan for committed API keys, tokens, passwords (using pattern matching, not full secret scanning — keep it simple for v1)
- CI/CD security: does the repo have a CI config? Are there obvious misconfigurations?
- SECURITY.md: does the repo have a security policy?
- Dependency management: is there a lockfile? Is Dependabot/Renovate configured?

**Report card display:**

- Overall security grade (A through F): A = 5/5 completion criteria met, B = 4/5, C = 3/5, D = 2/5, F = 0-1. Displayed prominently in Manrope 700 with a progress bar underneath
- Two sections: "Vulnerabilities" and "Repo posture"
- Vulnerability section: count by severity (critical/high/medium/low), with a prominent call-to-action: "Start fixing" that takes the user to the Findings page
- Posture section: checklist of checks with pass/fail/warning status and one-line fix instructions for each failing check (e.g., "Enable branch protection — Settings > Branches > Add rule")
- Completion progress: shows "X of 5 criteria met" with the list of remaining items (see Story 5 for the completion criteria)
- Independent-standard info line: a small, static info card at the bottom of the Dashboard that reads roughly "Want an independent second opinion? OpenSSF Scorecard is a free, third-party security assessment you can run on your repo." with a link to the Scorecard project. This is a one-sentence pointer — no API call, no live data, no dependency on whether the repo has a Scorecard result. Plants the positioning that Cliff is the coach and Scorecard is the independent judge, without any feature that can appear broken
- Import option: "Already using Snyk, Trivy, or Dependabot? Import additional findings" — links to the existing import flow

**Acceptance criteria:**

- [ ] Assessment starts automatically after onboarding step 3 (or can be triggered manually from a "Re-assess" button)
- [ ] Progress indicator shows assessment stages (scanning dependencies, checking posture, importing existing tools, generating report)
- [ ] Lockfile parsing supports at minimum: package-lock.json, yarn.lock, Pipfile.lock, requirements.txt, go.sum, Gemfile.lock, pom.xml, Cargo.lock
- [ ] CVE lookup uses a free, open data source (e.g., OSV.dev API, GitHub Advisory Database) — no paid scanner dependency
- [ ] Findings from the assessment are created in the Cliff findings table (same model as imported findings)
- [ ] Assessment deduplicates against any previously imported findings (no double-counting)
- [ ] Posture checks query the GitHub API via the configured PAT
- [ ] Report card renders within 3 seconds after assessment completes
- [ ] Report card is accessible from the main navigation (not just post-onboarding) — "Dashboard" or "Report card" nav item
- [ ] "Start fixing" CTA navigates to Findings page with findings sorted by severity
- [ ] Posture check items that pass show a green checkmark; failing items show an orange/red indicator with a fix instruction
- [ ] Completion progress section shows current status: "X of 5 criteria met" with clear indication of what's remaining
- [ ] Re-assess button allows running the assessment again (e.g., after fixing posture issues or merging PRs)
- [ ] Dashboard includes a small static info line pointing to OpenSSF Scorecard as an independent third-party standard, with an external link. No API call, no live score, no "no score available" state

---

### Story 3: Plain-language finding descriptions

**As** an open-source maintainer who doesn't speak security jargon, **I want** vulnerability descriptions that explain the problem in plain language alongside the technical details, **so that** I understand what's actually at risk without needing to Google every CVE.

**Given** the assessment (or import) has created findings,
**When** I view a finding in the queue or in a workspace,
**Then** I see a plain-language summary that explains what the vulnerability means in practical terms — what could go wrong, who could exploit it, and what the fix involves — with the technical CVE/package data accessible but not the primary view.

**The user should feel:** "I actually understand what this means. It's not a wall of jargon. I know why this matters and what I need to do."

**Example transformation:**

*Before (v1.0 — raw technical data):*
> CVE-2024-4068 in braces@3.0.2 — ReDoS vulnerability. CVSS 7.5. Affected versions: <3.0.3.

*After (v1.1 — plain language + technical):*
> **A pattern-matching library your project uses has a known security flaw** that could let an attacker slow down or crash your application by sending specially crafted input. This is a high-severity issue. The fix is straightforward: update `braces` from version 3.0.2 to 3.0.3.
>
> *Technical: CVE-2024-4068 | CVSS 7.5 (high) | braces 3.0.2 → 3.0.3 | ReDoS*

**How it works:**

The plain-language description is generated during finding normalization — either when Cliff's own assessment creates findings, or when the user imports findings from an external tool. The existing LLM normalizer (ADR-0022) is extended to produce a `plain_description` field alongside the existing structured fields. The prompt instructs the LLM to explain the vulnerability as if talking to a developer who has never read a CVE before: what's the risk in practical terms, how could it be exploited, and what does the fix look like.

**Acceptance criteria:**

- [ ] Every finding has both a `plain_description` (human-readable, 2-4 sentences) and the existing technical fields (CVE ID, package, version, CVSS, etc.)
- [ ] Plain-language descriptions are generated by the LLM normalizer during finding creation (assessment or import)
- [ ] The description explains: what the vulnerability is (in plain terms), what the practical risk is (what could happen), and what the fix involves (at a high level)
- [ ] Technical details (CVE ID, CVSS score, package name, affected/fixed versions) are displayed but secondary — accessible via an expandable section or smaller text below the plain description
- [ ] Finding cards on the Findings page show the plain-language summary as the primary text
- [ ] Workspace chat and sidebar use the plain-language description in context
- [ ] The enricher agent's output builds on (not replaces) the plain-language description — adding depth about exploitability and exposure specific to this repo
- [ ] Descriptions avoid unnecessary alarm ("your project is compromised!") and unnecessary reassurance ("this is probably fine") — they're factual and clear
- [ ] Works for all scanner formats: the LLM normalizer generates good plain-language descriptions regardless of whether the input is from Cliff's own scan, Snyk, Trivy, Dependabot, or any other format

---

### Story 4: Repo posture guidance

**As** an open-source maintainer, **I want** to see what security best practices my repo is missing and get clear instructions on how to fix them, **so that** I can improve my repo's security configuration — not just fix code vulnerabilities.

**Given** the security assessment has completed and identified posture issues,
**When** I view the report card's posture section,
**Then** I see a checklist of security practices with pass/fail status and actionable fix instructions for each failing item.

**The user should feel:** "These aren't scary demands — they're practical steps I can do right now. And I can see my progress as I check them off."

**Posture checks (v1.1 scope):**

| Check | What it verifies | Fix guidance |
|---|---|---|
| Branch protection | Default branch has protection rules enabled | "Go to Settings > Branches > Add rule for `main`. Enable 'Require pull request reviews' and 'Require status checks'" |
| Force push disabled | Force pushes to default branch are blocked | "In your branch protection rule, check 'Do not allow force pushes'" |
| Signed commits | Whether signed commits are encouraged (not required — display only) | "Consider requiring signed commits. See GitHub docs on commit signing" |
| No secrets in code | No obvious API keys, tokens, or passwords in tracked files | "Found potential secrets in: [file list]. Remove them and rotate the exposed credentials" |
| SECURITY.md exists | Repo has a security policy file | "Create a SECURITY.md with vulnerability reporting instructions. Cliff can generate a template for you" |
| Lockfile present | Dependency lockfile is committed | "Commit your lockfile (package-lock.json, yarn.lock, etc.) to ensure reproducible builds" |
| Dependabot/Renovate configured | Automated dependency updates are set up | "Create a `.github/dependabot.yml` to get automatic dependency update PRs. Cliff can generate this for you" |

**Interaction model:**

Posture checks are display-only in v1.1 — they show status and provide instructions, but Cliff does not auto-remediate them. The maintainer fixes these themselves via GitHub settings or by committing config files. For two items (SECURITY.md and dependabot.yml), Cliff offers to generate a template file and create a PR — these are simple enough for agents to handle reliably.

After fixing posture issues, the user clicks "Re-assess" to update the report card. Progress toward completion updates in real-time.

**Acceptance criteria:**

- [ ] All posture checks listed above run as part of the assessment
- [ ] Each check shows one of three states: pass (green), fail (red/orange), or info (gray — for advisory checks like signed commits)
- [ ] Failing checks include a one-line fix instruction and optionally a link to relevant GitHub docs
- [ ] For SECURITY.md and dependabot.yml: an "Cliff can create this" button triggers a simple agent that generates the file and creates a PR
- [ ] Posture check results are stored in the database (not just computed on-the-fly) so they persist across sessions
- [ ] "Re-assess" button re-runs posture checks and updates the report card
- [ ] Posture checks query the GitHub API — they check the actual repo state, not just local files
- [ ] If the GitHub API rate-limits or the PAT lacks permissions for a specific check, that check shows "unable to verify" rather than failing silently
- [ ] Posture items do NOT create findings in the queue — they live only on the report card. Vulnerability remediation (agents + PRs) is for code vulnerabilities only

---

### Story 5: Completion ceremony and shareable summary

**As** an open-source maintainer who has remediated my vulnerabilities and fixed my repo posture, **I want** Cliff to celebrate the completion and give me something concrete I can share, **so that** I feel rewarded for the work and can tell others what I just did — without Cliff modifying my README on my behalf.

**Given** I've been working through findings and posture issues,
**When** all completion criteria are met (no critical/high vulnerabilities remaining + baseline posture checks pass),
**Then** Cliff celebrates the achievement in-app and offers me a shareable summary card I can download or copy to share publicly.

**The user should feel:** "I earned this. The work was worth it. I have something I can point to — and I decide where, if anywhere, I share it."

**Completion criteria (same as v1.0 badge criteria — rename only):**

Completion is reached when ALL of the following are true:
1. Zero open critical-severity vulnerability findings
2. Zero open high-severity vulnerability findings
3. Branch protection is enabled on the default branch
4. No secrets detected in code
5. SECURITY.md exists

Medium and low severity findings do NOT block completion — they're tracked but not required for the baseline security standard. The criteria are intentionally achievable: we want maintainers to reach completion, not feel like it's out of reach.

**Completion ceremony:**

1. **Progress tracking** — Throughout the remediation process, the report card shows "X of 5 criteria met" with a visual progress bar and clear indication of remaining items
2. **Completion state** — When all criteria are met, the report card shows a celebration state: 3-second confetti animation (30-40 small particles in primary/tertiary colors, gentle fall), subtle background color shift to tertiary-fixed, and a completion badge preview scales up with a spring animation. No sound. Celebratory but fits the Serene Sentinel calm authority tone
3. **No auto-write to README.** Cliff will not create a PR that modifies the user's README in v1.1. This is a deliberate trust posture — a security tool must not silently touch repo content

**Shareable summary card:**

The ceremony produces a summary artifact the maintainer can choose to share. The card is generated locally and displayed in the app after the celebration animation.

- **Content:** Repo name, completion date, count of vulnerabilities remediated (by severity), posture checks passed, number of PRs merged via Cliff
- **Format:** A rendered PNG/SVG image sized for social sharing (roughly 1200×630), plus a matching plain-text version
- **Actions available to the user:**
  - "Download image" — saves the PNG/SVG locally
  - "Copy text summary" — copies a tweet-sized plain-text version to clipboard (e.g., "I secured `cool-lib` with Cliff — 12 vulns fixed, branch protection enabled, SECURITY.md added. cliff.dev")
  - "Copy markdown" — copies a markdown snippet the user can optionally paste into their own README manually (explicit user action — Cliff does not create the PR)
- **No public URL dependency.** The image is generated by Cliff locally. There is no verification server and no Cliff-hosted badge URL to fetch in v1.1

**Acceptance criteria:**

- [ ] Report card shows completion progress: "X of 5 criteria met" with visual indicator
- [ ] Each criterion shows its status individually (met/not met) so the user knows exactly what's remaining
- [ ] When all 5 criteria are met, the report card enters a "completion" state with prominent visual celebration (confetti + spring animation, ~3 seconds)
- [ ] Completion state displays the shareable summary card with repo name, date, and remediation stats
- [ ] "Download image" action saves the summary card as PNG or SVG locally
- [ ] "Copy text summary" action copies a short (tweet-sized) plain-text summary to the clipboard
- [ ] "Copy markdown" action copies a markdown snippet the user can paste into their README themselves
- [ ] Cliff does NOT create any PR that writes to the user's README in v1.1
- [ ] If the user hasn't reached completion yet, the completion section shows a preview of the celebration and the remaining criteria — motivating, not discouraging
- [ ] If findings are re-imported or a new assessment finds new critical/high vulns, the completion status reverts to "action needed" on the report card. Any shareable card the user already downloaded is theirs — Cliff does not try to track or invalidate it
- [ ] Summary card date format is ISO 8601 (YYYY-MM-DD)
- [ ] Summary card design follows the Serene Sentinel design system

---

### Story 6: Returning to check and re-assess

**As** an open-source maintainer who reached completion weeks ago, **I want** to re-run the security assessment to check for new vulnerabilities, **so that** my project remains secure over time.

**Given** I've previously completed the assessment and reached (or made progress toward) completion,
**When** I open Cliff and navigate to the report card,
**Then** I see my last assessment results with a "Re-assess" button and the date of the last assessment. Running a new assessment picks up new CVEs, new dependencies, and updated posture state.

**The user should feel:** "It's easy to keep this current. A quick re-assessment and I know where I stand."

**Acceptance criteria:**

- [ ] Report card shows the date of the last assessment prominently
- [ ] "Re-assess" button re-runs the full assessment (dependency scan + posture check)
- [ ] New findings from re-assessment are added to the queue; previously remediated findings are not re-created
- [ ] If a previously closed finding re-appears (e.g., a regression or new CVE for the same package), it's created as a new finding with a note referencing the original
- [ ] Re-assessment updates completion status: if new critical/high findings are found, status shows "action needed"
- [ ] If completion criteria are still met after re-assessment, the user can regenerate the shareable summary card with the new date
- [ ] Assessment history is stored — the user can see past assessment dates and finding counts (simple list, not a full analytics dashboard)

---

## Requirements

### Must-have (P0) — Core v1.1 flow cannot ship without these

- **Onboarding wizard** (Story 1) — Without this, the security-clueless user bounces on first launch
- **Security assessment engine** (Story 2) — Without this, users who don't have a scanner can't get findings
- **Plain-language descriptions** (Story 3) — Without this, the non-expert user can't understand what's wrong
- **Report card dashboard** (Story 2) — Without this, there's no visual representation of security posture
- **Posture checks** (Story 4) — Without this, the completion criteria can't be evaluated
- **Completion criteria tracking** (Story 5) — Without this, there's no goal to work toward
- **Completion ceremony + shareable summary card** (Story 5) — Without this, the maintainer has no reward or artifact to share

### Nice-to-have (P1) — Significantly improves experience

- **SECURITY.md generation** (Story 4) — Agent creates a template SECURITY.md via PR
- **Dependabot.yml generation** (Story 4) — Agent creates a Dependabot config via PR
- **Assessment history** (Story 6) — Track past assessments and show trends
- **Completion celebration animation** (Story 5) — Visual reward when completion is reached

### Future considerations (P2) — Design for but don't build in v1.1

- **Public README badge ("Secured by Cliff")** — Deferred from v1.1 after brainstorm (2026-04-15). Returns in v1.2 once core flow is validated, criteria are tightened, and the brand has traction. Includes the PR creation, badge SVG design, freshness semantics, and tamper-resistance considerations
- **Continuous monitoring** — GitHub Action that runs Cliff assessment on a schedule or on PR merge. A prerequisite for a meaningful public badge
- **Badge verification server** — SaaS endpoint that verifies a badge is legitimate (for when brand value makes faking worth preventing)
- **Multi-repo support** — Assess and badge multiple repos from a single Cliff instance
- **Organization-wide assessment** — Assess all repos in a GitHub org
- **Posture auto-remediation** — Agents that fix branch protection, remove secrets, etc. (v1.1 is display + guidance only)
- **OpenSSF Scorecard integration** — Full integration returns in v1.2+. Two layers to design together: (1) align Cliff's completion criteria with a subset of Scorecard checks so remediation improves both simultaneously; (2) run Scorecard ourselves (either by bundling the binary or via the continuous-monitoring GitHub Action) so we always have a live score to display rather than depending on public API coverage. The v1.1 decision is to ship neither of these — just a static info-line pointer so the positioning is planted

## Success metrics

| Metric | Target | How measured |
|---|---|---|
| Onboarding completion rate | >80% of users who start onboarding complete all 3 steps | Track step progression in assessment_history table |
| Assessment-to-findings | Assessment produces at least 1 finding for >90% of real-world repos | Test against 10+ popular open-source repos of varying quality |
| Plain-language clarity | >80% of plain-language descriptions are rated "clear and accurate" by a non-security reviewer | Manual review of 50 generated descriptions |
| Completion rate | >50% of users who start the process reach the completion criteria within a week | Track completion criteria progression over time |
| Time-to-completion | Median time from first assessment to completion is under 2 hours of active work | Timestamp difference: first assessment to completion state |
| Share action rate | >40% of users who reach completion use at least one of the share actions (download, copy text, copy markdown) | Track share action clicks |
| Return rate | >30% of completers re-assess within 90 days | Track re-assessment frequency |
| Qualitative validation | 3+ of the initial friend-network maintainers say "I would recommend this to a peer" | Follow-up interviews one week after completion |

## Scope

### In scope

- Onboarding wizard (3 steps: repo, LLM, assessment)
- Cliff's own dependency vulnerability scanner (lockfile parsing + OSV.dev/GitHub Advisory DB lookup)
- Repo posture checks via GitHub API (7 checks)
- Plain-language finding descriptions in the LLM normalizer
- Security report card page with vulnerability summary + posture checklist + completion progress
- Completion criteria tracking with visual progress
- Completion ceremony (celebration animation + shareable summary card)
- Shareable summary card with download, copy-text, and copy-markdown actions
- Re-assessment flow
- Static info-line on the Dashboard pointing to OpenSSF Scorecard as an independent third-party standard (no API call, no live data)
- All v1.0 capabilities remain fully functional (import, workspace, agents, remediation, PRs)

### Out of scope (and why)

- **Public "Secured by Cliff" README badge** — Deferred to v1.2. The brainstorm on 2026-04-15 concluded that v1.1's risk/reward favors ceremony + user-controlled share actions over a silent or one-click README modification. Returns once the core product is validated and the brand has enough recognition to make the badge meaningful
- **Full SAST/DAST scanning** — Cliff checks known CVEs in dependencies, not custom code vulnerabilities. Adding SAST is a separate product capability with different accuracy expectations. Future consideration
- **Posture auto-remediation** — Changing GitHub repo settings via API is risky (could lock out maintainers, break CI). Display + guidance for v1.1; auto-fix in a future version after trust is established
- **Badge verification server** — Tied to the public badge, which is itself deferred
- **Continuous monitoring / GitHub Action** — Excellent v1.2 feature and a prerequisite for a meaningful public badge. v1.1 is manual re-assessment
- **Live OpenSSF Scorecard integration** — Deferred to v1.2. The public `api.securityscorecards.dev` API only has results for repos that OpenSSF considers "critical" enough to scan automatically, and coverage for the small-to-medium OSS repos in our actual v1.1 user set is a coin flip. A feature that silently works 30-50% of the time feels broken. v1.2 will address this properly by either aligning our criteria to Scorecard checks or running Scorecard ourselves
- **Multi-repo support** — One repo per Cliff instance for v1.1. Multi-repo is a future product expansion
- **Secret scanning with rotation** — v1.1 does basic pattern matching for obvious secrets. Full secret scanning with automatic rotation is a separate product capability
- **License compliance** — Not a security posture issue in the strict sense. Potentially a future completion criterion
- **Automated batch remediation** — Still one workspace at a time. Batch mode is a separate future feature

## Dependencies

**Upstream (from PRD-0001, assumed complete or in progress):**

- Finding import + LLM normalizer (ADR-0022, ADR-0023) — extended with `plain_description` field
- Workspace runtime with isolated processes (ADR-0014)
- Agent pipeline: enrich -> analyze -> plan -> remediate (PRD-0001 Stories 4-6)
- PR creation from workspace (PRD-0001 Story 6)
- Credential vault for GitHub token (existing)
- Settings page with repo URL + PAT (PRD-0001 Story 3)

**New infrastructure needed:**

- CVE data source: OSV.dev API (primary) with GitHub Advisory Database as fallback — for the assessment engine
- Lockfile parsers: lightweight custom Python parsers per ecosystem (npm, pip, go, ruby, java, rust) — ~200-300 LOC each, stdlib only, no CLI tool dependencies
- New module: `backend/cliff/assessment/` with parsers, CVE lookup, and posture checker
- GitHub API client for posture checks (branch protection, repo settings) — extends existing PAT usage
- Report card data model — new tables/fields for assessment results, posture checks, completion status
- New "Dashboard" page in frontend — report card with letter grade, posture checklist, completion progress
- Shareable summary card renderer — local image generation (PNG/SVG) with repo name, date, and remediation stats

**Downstream (unblocked by v1.1):**

- Public "Secured by Cliff" README badge and PR flow (v1.2)
- GitHub Action for continuous monitoring (v1.2)
- Badge verification server (v1.3+)
- Multi-repo / org-wide assessment (v1.3+)
- Enterprise edition: team dashboards showing security status across all company OSS projects

## Resolved questions

- [x] **Public README badge for v1.1:** Deferred to v1.2. v1.1 ships a private completion ceremony + user-controlled shareable summary card. Rationale documented in the revision note above. *Decided by: CEO + Product (2026-04-15)*
- [x] **Scoring model:** Letter grade (A-F) with a visual progress bar toward completion. Grades map to completion criteria: A = 5/5 met (complete), B = 4/5, C = 3/5, D = 2/5, F = 0-1. Letter grades are intuitive for non-experts and more motivating than numeric scores. *Decided by: CEO + UX (2026-04-12)*
- [x] **CVE data source:** OSV.dev (Google) as primary, GitHub Advisory Database as secondary fallback. OSV has broad multi-ecosystem coverage, free API (~100 req/sec), single unified schema. GitHub Advisory DB fills gaps for Java/Maven and .NET. *Decided by: Engineering (2026-04-12)*
- [x] **Lockfile parser build vs. buy:** Build lightweight custom Python parsers per ecosystem (~200-300 LOC each). Lockfiles are simple structured formats (JSON, TOML, YAML, text). Custom parsers avoid deployment dependencies on npm/pip CLIs, subprocess overhead, and failure modes. Six ecosystems for v1.1: npm (package-lock.json), Python (Pipfile.lock/requirements.txt), Go (go.sum), Ruby (Gemfile.lock), Java (pom.xml), Rust (Cargo.lock). New module: `backend/cliff/assessment/parsers/`. *Decided by: Engineering (2026-04-12)*
- [x] **Report card as new page or enhanced findings page:** New "Dashboard" page in the main navigation. The report card is strategic ("how's my posture?") while Findings is tactical ("which vulns to fix?"). Separate pages respect the information hierarchy. Dashboard becomes the landing page after onboarding, with "Start fixing" CTA bridging to Findings. *Decided by: CEO + UX (2026-04-12)*
- [x] **Celebration UX:** 3-second confetti animation + subtle background color shift. ~30-40 small particles in primary (#4d44e3) and tertiary (#575e78) colors, gentle fall speed. Background tints briefly to tertiary-fixed. Completion badge preview scales up with a spring animation. No sound. Fits the Serene Sentinel "calm authority" tone — celebratory without being cheesy. *Decided by: UX (2026-04-12)*
- [x] **OpenSSF Scorecard relationship:** Position Cliff as the coach, Scorecard as the independent judge. v1.1 ships a single static info-line on the Dashboard pointing to Scorecard as a third-party standard the maintainer may want to know about — no API call, no live score, no broken-feature risk. A live Scorecard integration (aligned criteria + running Scorecard ourselves) is deferred to v1.2 because public-API coverage for our actual v1.1 user set (small-to-medium OSS repos) is a coin flip. No Scorecard outreach to the OpenSSF team in v1.1 — wait for traction first. *Decided by: CEO + Product (2026-04-15)*
- [x] **Shareable summary card format:** Locally generated PNG/SVG sized ~1200×630 for social sharing, plus a plain-text version for clipboard. Download, copy-text, and copy-markdown actions are available to the user. No Cliff-hosted URL, no verification server, no tracking. *Decided by: CEO + Product (2026-04-15)*

## Open questions

All resolved. No remaining blockers for CEO approval of the revised PRD.

---

_This PRD follows the Cliff product workflow. After CEO approval, it moves to the UX team for mockup updates via `/ux-designer`, then to `/architect` for implementation plan updates. Note that UX-0002 and IMPL-0002 were drafted against the original badge-centric PRD and will need revision passes to reflect the v1.1 scope change._
