<div align="center">

<img src="docs/assets/cliff-wordmark.svg" alt="cliff" width="360" />

### Take care of security.

[![Version](https://img.shields.io/github/v/release/galanko/OpenSec?include_prereleases&label=version&color=6FE3B5&labelColor=0B101B)](https://github.com/galanko/OpenSec/releases)
[![Backend CI](https://img.shields.io/github/actions/workflow/status/galanko/OpenSec/backend.yml?branch=main&label=backend&color=6FE3B5&labelColor=0B101B)](https://github.com/galanko/OpenSec/actions/workflows/backend.yml)
[![Frontend CI](https://img.shields.io/github/actions/workflow/status/galanko/OpenSec/frontend.yml?branch=main&label=frontend&color=6FE3B5&labelColor=0B101B)](https://github.com/galanko/OpenSec/actions/workflows/frontend.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-6FE3B5?labelColor=0B101B)](LICENSE)
[![Status: alpha](https://img.shields.io/badge/status-alpha-F0BF7E?labelColor=0B101B)](ROADMAP.md)

<a href="https://github.com/galanko/OpenSec"><img src="docs/assets/cliff-badge-A.svg" alt="Cliff verified — Grade A" /></a>

</div>

---

The security industry was built for companies with security teams. The next ten years won't have those companies.

Cliff is the AI security teammate every team without a security team needs. Drop in a finding — CSV, Snyk, Trivy, your own scanner — and Cliff opens a workspace, enriches the context, finds the owner, drafts the plan, files the ticket, and validates the close. You steer; Cliff does the legwork.

Built on [OpenCode](https://github.com/anomalyco/opencode). Self-hosted, AGPL-3.0, runs natively on macOS and Linux or in a single Docker container.

> Alpha. Single-user. Expect rough edges — see [ROADMAP.md](ROADMAP.md).

## Who Cliff is for

- **OSS maintainers** with a backlog of Dependabot PRs they don't have time to read.
- **Founders at AI-native startups** answering a 200-question security questionnaire that landed Friday.
- **Solo security engineers** at growing companies, tired of being the bottleneck between detection and remediation.

If you don't have a security team — or you *are* the security team — Cliff is for you.

## Quick start

**macOS or Linux** — no Docker required, about two minutes:

<!-- install:start -->
```bash
curl -fsSL https://github.com/galanko/OpenSec/releases/latest/download/install-local.sh | sh
cliff start --detach
```
<!-- install:end -->

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and paste your Anthropic or OpenAI key in Settings.

The installer fetches `uv`, a managed Python 3.11, the OpenCode binary, and the Trivy and Semgrep scanners. Prereqs: `git`, `curl`, and the [GitHub CLI](https://github.com/cli/cli#installation). If something doesn't run, `cliff doctor` will say why.

**Docker** — single-container alternative, required on Windows. Prereqs: Docker 24+.

```bash
curl -fsSL https://github.com/galanko/OpenSec/releases/latest/download/install.sh | sh
```

Manual install, image verification, and platform notes are in [docs/install.md](docs/install.md).

## Use Cliff inside Claude Code

Already in [Claude Code](https://claude.com/claude-code)? You can skip the web UI. After running the installer above, register the plugin marketplace and install `secure-repo`:

```text
/plugin marketplace add galanko/OpenSec
/plugin install secure-repo@opensec
```

Then in any git repo, ask:

> *Hey Cliff, take care of this repo.*

Cliff scans the codebase, opens a workspace per finding, and walks you from plan to PR to merge to close. You approve the plan. You approve the merge. You mark closed. Cliff handles the rest.

## The badge

Cliff scores your repo continuously and issues a public badge for your README — A through F. Closed criticals, no committed secrets, posture checks passing: that's the work that earns it. The badge is a signal — to potential users, to the enterprise prospect who just sent you a security questionnaire, to yourself — that someone on this project takes care of the boring parts.

The badge in the hero above is the one Cliff issues for itself.

[Read the rubric →](docs/guides/badge.md)

## How Cliff works

| Step | Cliff | You |
|------|-------|-----|
| Triage | Reads the finding. Checks reachability. Writes the summary. | Skim the summary. |
| Owner | Finds the team that owns the affected code via CODEOWNERS, recent commits, blame. | Confirm or override. |
| Plan | Drafts the remediation plan with the mitigation, the fix, and the definition of done. | Approve, edit, or send it back. |
| Ticket | Files the ticket in Linear, Jira, or GitHub Issues with the plan attached. | — |
| PR | If a code fix exists, drafts the PR. Otherwise tracks the external work. | Review and merge. |
| Validate | Re-scans. Confirms closure. Recommends close or reopen. | Mark closed. |

Each step persists into both the chat timeline and a structured sidebar — the workspace remembers everything, so re-opening a finding three months later picks up where it left off.

## Architecture and docs

- [Architecture overview](docs/architecture/overview.md)
- [Connect a GitHub repo](docs/guides/setup-github-app.md) — one-click GitHub App + device flow
- [ADRs](docs/adr/) — every significant decision, with the trade-offs
- [Roadmap](ROADMAP.md)
- [Contributing](.github/CONTRIBUTING.md)
- [Security policy](SECURITY.md) · [License](LICENSE)

## About

Cliff is a product of [OpenSec](https://github.com/galanko) — a small team and a research vertical that publishes its bug bounty methodology and the tools to apply it. Cliff is the remediation copilot; OpenSec is the lab.

---

<div align="center">
  <sub>AGPL-3.0 · built by <a href="https://github.com/galanko">@galanko</a> · security should feel like shipping, not filing tickets.</sub>
</div>
