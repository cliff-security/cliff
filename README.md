<div align="center">

<img src="docs/assets/cliff-wordmark.svg" alt="Cliff" width="200" />

**Take care of security.**

[![Version](https://img.shields.io/github/v/release/cliff-security/cliff?include_prereleases&label=version&color=6FE3B5&labelColor=0B101B)](https://github.com/cliff-security/cliff/releases)
[![Backend CI](https://img.shields.io/github/actions/workflow/status/cliff-security/cliff/backend.yml?branch=main&label=backend&color=6FE3B5&labelColor=0B101B)](https://github.com/cliff-security/cliff/actions/workflows/backend.yml)
[![Frontend CI](https://img.shields.io/github/actions/workflow/status/cliff-security/cliff/frontend.yml?branch=main&label=frontend&color=6FE3B5&labelColor=0B101B)](https://github.com/cliff-security/cliff/actions/workflows/frontend.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-6FE3B5?labelColor=0B101B)](LICENSE)
[![Status: beta](https://img.shields.io/badge/status-beta-F0BF7E?labelColor=0B101B)](ROADMAP.md)

<img src="docs/assets/cliff-badge-A.svg" alt="Cliff verified — Grade A" />

</div>

---

# Earn the trust

Modern software is assembled more than it's written. Your repo pulls in hundreds of open-source packages, and each of those pulls in more. When one ships a vulnerable or malicious release, every project downstream inherits it. That's a supply chain attack, and it's why security stopped being only a security team's job.

Cliff hands that job to everyone else. Point it at your repo and it scans, explains every finding in plain English, and prepares the fix — you approve each step. You don't need to know what a CVE is, which findings actually matter, or how to remediate them. That's Cliff's job.

[cliffsecurity.ai](https://cliffsecurity.ai) · self-hosted · runs natively on macOS and Linux, or in a single Docker container.

> Beta. Single-user. Expect rough edges — see [ROADMAP.md](ROADMAP.md).

<!--
  HERO PRODUCT SHOT — insert when the Cyberdeck UI ships:
  <p align="center">
    <img src="docs/assets/cliff-workspace.png" alt="Cliff workspace mid-remediation — chat thread on the left with agent run cards, sidebar state populating with summary, owner, plan, ticket, validation" width="900" />
  </p>
-->

## How Cliff works

Three steps, from install to a fix you can merge.

**1 · Point Cliff at your repo.** One command. Cliff runs entirely on your machine. Your code never leaves it.

**2 · Cliff scans and explains.** It runs Trivy, Semgrep, and a set of posture checks, then turns every result into a finding written in plain English. You get a grade, A through F, and the short list of what stands between your repo and an A.

**3 · Cliff remediates, with your approval.** For each finding, a pipeline of focused agents works it through: what the vulnerability is, whether your code actually reaches it, and a fix plan with a clear definition of done. Then Cliff stops. Nothing touches your code until you approve the plan. Once you do, Cliff opens a draft pull request — you review it like any other contribution. Nothing auto-merges.

Each finding moves along one track: `new → triaged → in progress → remediated → validated → closed`. You stay in control of every transition that matters.

## Who Cliff is for

Anyone responsible for software that didn't come with a security team.

A maintainer with a backlog of Dependabot PRs nobody has time to read. A founder whose product was built with AI and just got a 200-question security questionnaire. An engineer who became "the security person" by accident. If you want your project — and the people who depend on it — to be secure, and to be seen as secure, Cliff is for you. No security background required.

## Quick start

**macOS or Linux** — no Docker required, about two minutes:

<!-- install:start -->
```bash
curl -fsSL https://github.com/cliff-security/cliff/releases/latest/download/install-local.sh | sh
cliffsec start --detach
```
<!-- install:end -->

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) and paste your Anthropic or OpenAI key in Settings.

The installer fetches `uv`, a managed Python 3.11, the OpenCode binary, and the Trivy and Semgrep scanners. Prereqs: `git`, `curl`, and the [GitHub CLI](https://github.com/cli/cli#installation). If something doesn't run, `cliffsec doctor` will say why.

**Docker** — required on Windows, optional everywhere else. Prereqs: Docker 24+.

```bash
curl -fsSL https://github.com/cliff-security/cliff/releases/latest/download/install.sh | sh
```

Verify the image by checksum or build it yourself from this repo. See [`docker/`](docker/) for the Dockerfile and compose config.

## Use Cliff inside Claude Code

Already in [Claude Code](https://claude.com/claude-code)? Skip the web UI. After running the installer above, register the plugin marketplace and install `cliff-security`:

```text
/plugin marketplace add cliff-security/cliff
/plugin install cliff-security@cliff
```

Then, in any git repo, ask:

> *Hey Cliff, take care of this repo.*

Cliff scans the codebase, opens a workspace per finding, and walks you from plan to PR to merge to close. You approve the plan. You approve the merge. You mark closed. Cliff handles the rest.

## Road to A

Cliff grades your repo, A through F. An A is the highest standard Cliff measures: nothing critical outstanding, no secrets committed, and the posture basics in place. It's not a participation mark. It has to be earned.

When you reach it, Cliff gives you a summary card for your README — proof of the work, in a form anyone can verify. The public Cliff badge comes next. The point was never the badge itself. It's a standard of trust for open source: earned by doing the work, never bought.

The badge at the top of this README is the one Cliff issues for itself.

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
  <sub>AGPL-3.0 · security should feel like shipping, not filing tickets.</sub>
</div>
