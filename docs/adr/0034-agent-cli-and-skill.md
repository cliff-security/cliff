# ADR-0034: Agent CLI (`cliff`) and Claude Code skill (`/secure-repo`)

**Date:** 2026-04-30
**Status:** Proposed

## Context

Most early adopters of Cliff live in coding agents — Claude Code, Cursor, Cline — and run their day from a terminal. Asking them to leave the terminal, open a browser, and click through a UI to triage findings is friction we cannot afford. The agent IS the workflow surface.

The web UI stays. But we need a second surface that is shaped for agents:

1. **Token-efficient.** A 50-line JSON dump for "show me my findings" burns context the user could spend on actual code.
2. **Deterministic state.** The agent has to know "did this succeed", "is there a human gate", "is the daemon even up" without parsing prose.
3. **Coverable in one prompt.** The skill that drives the CLI must fit in the agent's working memory and not require re-reading docs every loop.
4. **Versioned.** When Cliff ships a new release, an old agent CLI must refuse to operate rather than silently pretend everything is fine.

Doing this with bare HTTP calls leaks too many concerns into the skill: ingest polling, SSE handshake, sidebar shape, version probe, finding-id lookup, error taxonomy. Every recipe is one more thing to drift.

## Decision

Ship two artifacts, version-locked to the Cliff daemon and bundled into the existing one-line installer.

### 1. The CLI: `cliff` (Python `click` + `httpx`)

Six commands. Each maps to a step of the user's mental model, not to an HTTP endpoint:

| Command | Purpose | Wraps |
|---|---|---|
| `cliff status` | Health + version handshake | `GET /health` + `GET /api/version` |
| `cliff scan <repo_url>` | Posture-assessment + ingest | `POST /api/assessment/run`, polls status, counts findings |
| `cliff issues` | Filtered finding list | `GET /api/findings?scope=current` |
| `cliff fix <id>` | Open workspace, run pipeline through planner, **stop at plan gate** | `POST /api/workspaces`, `POST .../sessions`, `POST .../pipeline/run-all`, polls `/sidebar` |
| `cliff approve <id>` | Resume pipeline through executor + validator | `POST .../plan/approve`, `POST .../pipeline/run-all`, polls `/sidebar` |
| `cliff close <id>` | Mark workspace closed (auto-resolves finding) | `PATCH /api/workspaces/{id}` |

Plus `cliff selftest` for our own e2e harness — it chains the same commands against a known repo so each release exercises the agent path.

**Output contract.** Every command emits one compact-JSON envelope on stdout:

```json
{"ok": true, "...": "...", "next": "approve ws-123"}
```

Errors emit the same shape on stderr with `ok: false` and an `error.code`/`error.message`/`error.hint`. No prose, no spinners, no progress bars.

**Exit-code contract** (the skill branches on this):

| Code | Meaning |
|---|---|
| 0 | Success, no human gate |
| 2 | Awaiting human gate (plan approval, validation failure) |
| 3 | Daemon unreachable |
| 4 | Version mismatch — CLI is older than `min_cli` |
| 5 | Scan completed with zero findings |
| 1 | Generic error |

**Version handshake.** A new endpoint `GET /api/version` returns `{cliff, opencode, schema_version, min_cli}`. The CLI calls it once per command (cheap, cached briefly) and refuses to operate if its baked-in version is older than `min_cli`. `schema_version` bumps when the contract surface changes incompatibly.

**Distribution — two separate consent surfaces.**

1. **CLI** — `scripts/install.sh` pip-installs the CLI tarball (`cliff-cli.tar.gz`) into `~/.cliff/cli-venv` and symlinks the entry point to `~/.local/bin/cliff`. This is a normal Unix binary going to a normal Unix location; the user already opted in by piping `install.sh` to `sh`, same as `rustup`, `nvm`, or `uv`.

2. **Skill (Claude Code plugin)** — published via the **official Claude Code plugin marketplace** mechanism. The repo root carries `.claude-plugin/marketplace.json`, and `plugins/secure-repo/` carries the plugin manifest + skill. The user installs explicitly from inside Claude Code:

   ```text
   /plugin marketplace add galanko/Cliff
   /plugin install secure-repo@cliff
   ```

   `install.sh` does **not** touch `~/.claude/`. The end-of-install banner prints the two `/plugin` commands as a hint, but never executes them.

**Why this split.** A reviewer flagged an earlier design that wrote `secure-repo-skill.md` straight into `~/.claude/skills/secure-repo/SKILL.md`. That was the wrong instinct: it silently mutates Claude's user-scoped config without explicit consent, and bypasses Anthropic's documented plugin/marketplace flow (see [Claude Code plugins reference](https://code.claude.com/docs/en/plugins-reference.md) and [marketplace docs](https://code.claude.com/docs/en/plugin-marketplaces.md)). Trust-from-first-second is a stated goal — every config mutation must be explicit, reversible, and originate from the user.

Both the CLI and the plugin manifest are version-locked to the daemon: the CLI sdist is published as a release asset; the plugin manifest is checked into the same repo and pulled by `/plugin marketplace add` at the user's request.

### 2. The skill: `/secure-repo`

A single `SKILL.md` (~4 KB) that teaches Claude Code the loop:

1. preflight (`cliff status`) — branch on exit code
2. install path — fetch the canonical install command from the README between `<!-- install:start -->` markers, surface it for user approval, run it
3. scan — resolve `.` to a repo URL via `gh repo view --json url -q .url`, then `cliff scan`
4. triage — `cliff issues --severity critical,high --limit 10`
5. fix loop — for each issue: `fix` → wait for human plan-approval → `approve` → `gh pr view`/`pr diff` → wait for human merge approval → `gh pr merge --squash` → `close`
6. report — one paragraph

The skill encodes hard rules: **never auto-approve a plan, never auto-merge a PR, stop on validation failure, stop on version mismatch, never invent IDs.**

### Decisions deliberately deferred

- **PyInstaller single-file binary.** Out of scope for v0.1. `pip install` from a tarball with a venv shim is enough for adopters who already have Python.
- **Scoped local-path scanning.** `cliff scan` requires a repo URL. The skill resolves `.` via `gh repo view`. Native local-path scanning lands when the assessment engine grows that mode.
- **Streaming `watch` command.** SSE streams are internal to `fix`/`approve`. The skill never needs raw events.
- **Merge verb.** `gh` already does this well. Keeping Cliff out of git auth is worth the extra command in the skill body.
- **Windows-native distribution.** macOS + Linux only for v0.1; Windows users run from WSL.

## Consequences

**Good**
- Adopters can use Cliff without ever opening the web UI.
- We get a deterministic, scriptable e2e harness (`cliff selftest`) that exercises the same code paths users hit, on every release candidate.
- The contract surface is small and explicit — six commands, six exit codes, one JSON envelope. Drift shows up as a failing test, not a silent regression.
- Version handshake gives us an off-ramp when the contract has to break: bump `min_cli`, old agents stop instead of silently corrupting state.

**Costs**
- One release artifact (`cliff-cli.tar.gz`) plus one in-repo plugin manifest (`.claude-plugin/marketplace.json` + `plugins/secure-repo/`). The plugin manifest tracks the same git tag as the daemon, so they're version-locked at the commit level.
- The user does two things instead of one: run the installer, and run two `/plugin` commands inside Claude Code. We accept the extra step in exchange for explicit consent.
- The skill is Claude-Code-shaped today. Porting to other agents (Cursor, Cline) means re-authoring the skill but reusing the CLI; we accept that trade.
- Older Cliff releases will not advertise `min_cli`, so the CLI's 404 fallback treats them as a hard mismatch. Users on stale daemons see exit 4 and a "re-run installer" hint — annoying but correct.

**Risks**
- The CLI couples to several routes (`/api/assessment`, `/api/findings`, `/api/workspaces`, `/api/sidebar`, `/api/pipeline/*`). A breaking change in any of these requires a coordinated `min_cli` bump. We track this with the OpenAPI snapshot test.
- A user who upgrades the daemon but not the CLI (e.g. installed the CLI manually outside the installer) will hit version mismatch. The hint tells them how to fix it; the cost is one extra command.

## References

- [Plan: agent-CLI + skill](../../.claude/plans/hey-man-i-thought-peppy-panda.md) — the design spec this ADR formalizes
- ADR-0014 — Workspace runtime architecture (the substrate the CLI drives)
- [`backend/cliff/api/routes/version.py`](../../backend/cliff/api/routes/version.py) — version handshake endpoint
- [`cli/`](../../cli) — CLI source
- [`.claude-plugin/marketplace.json`](../../.claude-plugin/marketplace.json) — marketplace manifest (registered via `/plugin marketplace add`)
- [`plugins/secure-repo/.claude-plugin/plugin.json`](../../plugins/secure-repo/.claude-plugin/plugin.json) — plugin manifest
- [`plugins/secure-repo/skills/secure-repo/SKILL.md`](../../plugins/secure-repo/skills/secure-repo/SKILL.md) — skill body
- Anthropic — [Claude Code plugins reference](https://code.claude.com/docs/en/plugins-reference.md)
- Anthropic — [Plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces.md)
