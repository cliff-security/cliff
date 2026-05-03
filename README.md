<div align="center">

<img src="frontend/public/favicon.svg" alt="OpenSec" width="80" />

# OpenSec

**Your security team, in chat.**

[![Version](https://img.shields.io/github/v/release/galanko/OpenSec?include_prereleases&label=version&color=4d44e3)](https://github.com/galanko/OpenSec/releases)
[![Backend CI](https://github.com/galanko/OpenSec/actions/workflows/backend.yml/badge.svg?branch=main)](https://github.com/galanko/OpenSec/actions/workflows/backend.yml)
[![Frontend CI](https://github.com/galanko/OpenSec/actions/workflows/frontend.yml/badge.svg?branch=main)](https://github.com/galanko/OpenSec/actions/workflows/frontend.yml)
[![Secured by OpenSec](https://img.shields.io/badge/secured_by-opensec-2b3437.svg)](https://github.com/galanko/OpenSec)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-4d44e3.svg)](LICENSE)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-f59e0b.svg)](ROADMAP.md)

</div>

## What is OpenSec?

OpenSec is a self-hosted, open-source AI copilot for vulnerability remediation. Drop in a finding (CSV, Snyk, Trivy, your own scanner) and you get a chat-led workspace where AI sub-agents enrich context, identify owners, plan the fix, draft tickets, and validate closure. You steer; the agents do the legwork.

Built on [OpenCode](https://github.com/anomalyco/opencode). Runs in a single Docker container. AGPL-3.0.

> Alpha. Single-user. Expect rough edges — see [ROADMAP.md](ROADMAP.md).

## Quick start

Prereqs: Docker 24+ and an LLM API key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`).

<!-- install:start -->
```bash
curl -fsSL https://github.com/galanko/OpenSec/releases/latest/download/install.sh | sh
```
<!-- install:end -->

Then open [http://localhost:8000](http://localhost:8000).

The installer drops a compose file in `~/opensec`, prompts for your API key, and waits for `/health`. Re-run any time to upgrade. Manual install, image verification, and platform notes: [docs/install.md](docs/install.md).

## Using with Claude Code

Live in [Claude Code](https://claude.com/claude-code)? Skip the web UI. After running the installer above, register the plugin marketplace and install `secure-repo` from inside Claude Code:

```text
/plugin marketplace add galanko/OpenSec
/plugin install secure-repo@opensec
```

Then in any git repo, ask:

> *"Secure this repo with OpenSec."*

Claude scans the repo, opens a workspace per finding, and walks you through plan → PR → merge → close. You approve the plan, approve the merge, mark closed — everything else is automated.

## Learn more

- [Architecture overview](docs/architecture/overview.md)
- [ADRs](docs/adr/) — every significant decision
- [Roadmap](ROADMAP.md)
- [Contributing](.github/CONTRIBUTING.md)
- [Security policy](SECURITY.md) · [License](LICENSE)

---

<div align="center">
  <sub>Built by <a href="https://github.com/galanko">@galanko</a> — because security should feel like shipping, not filing tickets.</sub>
</div>
