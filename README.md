<div align="center">

<img src="docs/assets/cliff-wordmark.svg" alt="Cliff" width="200" />

**Take care of security.**

[![Version](https://img.shields.io/github/v/release/cliff-security/cliff?include_prereleases&label=version&color=6FE3B5&labelColor=0B101B)](https://github.com/cliff-security/cliff/releases)
[![Backend CI](https://img.shields.io/github/actions/workflow/status/cliff-security/cliff/backend.yml?branch=main&label=backend&color=6FE3B5&labelColor=0B101B)](https://github.com/cliff-security/cliff/actions/workflows/backend.yml)
[![Frontend CI](https://img.shields.io/github/actions/workflow/status/cliff-security/cliff/frontend.yml?branch=main&label=frontend&color=6FE3B5&labelColor=0B101B)](https://github.com/cliff-security/cliff/actions/workflows/frontend.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-6FE3B5?labelColor=0B101B)](LICENSE)
[![Status: beta](https://img.shields.io/badge/status-beta-6FE3B5?labelColor=0B101B)](ROADMAP.md)

<img src="docs/assets/cliff-badge-A.svg" alt="Cliff verified — Grade A" />

</div>

---

## Earn the trust. Without speaking security.

The security industry was built for companies with security teams. The next ten years won't have those companies.

Cliff is the open-source security teammate your repo doesn't have. Point it at your code — it scans with bundled Trivy and Semgrep, explains every finding in plain English, and remediates with your approval at every step. Or pipe in findings from your existing scanner. The whole loop runs in a single chat thread — no dashboards to flip between, no per-CVE retracing.

Built on [OpenCode](https://github.com/anomalyco/opencode). Self-hosted, AGPL-3.0, BYOK. Runs natively on macOS and Linux, or in a single Docker container.

> Beta. Single-user. Pre-1.0 — we're still hardening edges; see [ROADMAP.md](ROADMAP.md).

<!--
  HERO PRODUCT SHOT — insert when the Cyberdeck UI ships:
  <p align="center">
    <img src="docs/assets/cliff-workspace.png" alt="Cliff workspace mid-remediation — chat thread on the left with agent run cards, sidebar state populating with summary, owner, plan, ticket, validation" width="900" />
  </p>
-->

## What Cliff does

Two findings. Same workflow.

### Case A — dismissed, with the reasoning on record

**Finding** · CVSS 7.5 · `braces` — transitive in `package-lock.json`

> *A library you depend on has a flaw that could crash your app.*

> **You:** is this even real?

```text
cliff is reasoning
✓ evidence        pulled CVE detail, mapped braces usage in lockfile
✓ reachability    matchBase() — the vulnerable function — is never called from your code
— exploitability  skipped, not reachable
→ verdict         dismiss. logged with reasoning, trust score unchanged.
```

> **Cliff:** Not for you. Dismissed, with the reasoning on record. Your trust score didn't move.

### Case B — remediated, with a draft PR awaiting your approval

**Finding** · CVSS 8.7 · `axios` — direct dep in `package.json`

> *A library you depend on could let attackers reach internal services.*

> **You:** is this real or noise?

```text
cliff is reasoning
✓ evidence        pulled CVE detail, mapped axios calls in source and lockfile
✓ reachability    called from your /webhook handler with a user-supplied URL
! exploitability  untrusted input flows directly into axios.get — confirmed exploitable
→ verdict         remediate. fix prepared, awaiting your approval.
```

> **Cliff:** Real exploit path. Remediating now — fix is on its way as PR #142. You approve, it ships.

Same loop for every finding. Cliff drives; you check the work.

## Who Cliff is for

- **OSS maintainers** with a backlog of Dependabot PRs they don't have time to read. *(V1 wedge.)*
- **Founder-engineers at AI-native startups** answering a 200-question security questionnaire that landed Friday.
- **Fractional security leads** serving a handful of small teams who need self-hosted, source-available tooling.

If you don't have a security team — or you *are* the security team — Cliff is for you.

## How Cliff works

Every finding moves through the same loop. Cliff drives; you check the work.

| Step | Cliff | You |
|------|-------|-----|
| Triage | Reads the finding. Checks reachability. Writes the summary. | Skim the summary. |
| Owner | Finds the team that owns the affected code via CODEOWNERS, recent commits, blame. | Confirm or override. |
| Plan | Drafts the remediation plan with the mitigation, the fix, and the definition of done. | Approve, edit, or send it back. |
| Ticket | Files the ticket in Linear, Jira, or GitHub Issues with the plan attached. | — |
| PR | If a code fix exists, drafts the PR. Otherwise tracks the external work. | Review and merge. |
| Validate | Rescans. Confirms closure. Recommends close or reopen. | Mark closed. |

Each step persists into both the chat timeline and a structured sidebar. Re-opening a finding three months later picks up where it left off — security work that compounds, instead of resetting every Monday.

## Quick start

**macOS or Linux** — no Docker required, about two minutes:

<!-- install:start -->
```bash
curl -fsSL https://github.com/cliff-security/cliff/releases/latest/download/install-local.sh | sh
cliff start --detach
```
<!-- install:end -->

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and paste your Anthropic or OpenAI key in Settings.

The installer fetches `uv`, a managed Python 3.11, the OpenCode binary, and the Trivy and Semgrep scanners. Prereqs: `git`, `curl`, and the [GitHub CLI](https://github.com/cli/cli#installation). If something doesn't run, `cliff doctor` will say why.

**Docker** — required on Windows, optional everywhere else. Prereqs: Docker 24+.

```bash
curl -fsSL https://github.com/cliff-security/cliff/releases/latest/download/install.sh | sh
```

Verify the image by checksum or build it yourself from this repo. See [`docker/`](docker/) for the Dockerfile and compose config.

## Use Cliff inside Claude Code

Already in [Claude Code](https://claude.com/claude-code)? Skip the web UI. After running the installer above, register the plugin marketplace and install `secure-repo`:

```text
/plugin marketplace add cliff-security/cliff
/plugin install secure-repo@cliff
```

Then, in any git repo, ask:

> *Hey Cliff, take care of this repo.*

Cliff scans the codebase, opens a workspace per finding, and walks you from plan to PR to merge to close. You approve the plan. You approve the merge. You mark closed. Cliff handles the rest.

## Road to A

What if your security posture were as legible as your build status?

Cliff scores your repo against a posture rubric and walks you to grade A:

- No critical issues
- High-severity backlog under control
- No secrets in code
- Posture checks passing
- Lockfile up to date

When the rubric clears, Cliff writes a completion summary you can paste in your README and share. The grade in the hero is the one Cliff issued for itself.

The live, continuously-scored Cliff badge — the kind that lives next to your build badge and updates on every commit — ships in v1.2, once enough maintainers have earned one that it actually means something. The point of a security badge is that it's credible, not that it exists.

## Who built this

Cliff is built by **Gal Ankonina**, a twelve-year security generalist. The stack spans **Unit 8200**, defensive engineering at a Fortune-50, security startups, and ongoing OSS bug-bounty research — Chrome VRP among the credits.

Cliff exists because the founder was the security person for his own projects and got tired of being it. The category had a thousand tools that told you you had a problem and almost none that helped you fix it.

The marketing site lives at [cliffsecurity.ai](https://cliffsecurity.ai).

## Project info

- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md) · [License](LICENSE)
- [Changelog](CHANGELOG.md) · [Known issues](KNOWN_ISSUES.md)

## Licensing

Cliff is licensed under [AGPL-3.0-only](LICENSE). Operating Cliff over a network for users other than yourself triggers AGPL §13 (corresponding-source disclosure); see [NOTICE](NOTICE) and [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).

Cliff bundles three third-party programs as subprocesses: [OpenCode](https://github.com/anomalyco/opencode) (MIT), [Trivy](https://github.com/aquasecurity/trivy) (Apache-2.0), and the [Semgrep CE](https://github.com/semgrep/semgrep) engine (LGPL-2.1). Their license texts ship alongside each binary in the install directory and are inventoried in [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).

The default scan invokes Semgrep's hosted **registry rule packs** `p/security-audit` and `p/owasp-top-ten`. Those rules are governed by the [Semgrep Rules License v1.0](https://semgrep.dev/legal/rules-license/) — source-available, separate from the LGPL-2.1 engine. They are free for **internal business use only**: not for SaaS, paid products, or products that compete with Semgrep. Teams considering a commercial deployment of Cliff should consult counsel before relying on these rule packs; [OpenGrep](https://github.com/opengrep/opengrep) is a license-clean drop-in alternative.

---

<div align="center">
  <sub>AGPL-3.0 · <a href="https://cliffsecurity.ai">cliffsecurity.ai</a> · take care of security.</sub>
</div>
