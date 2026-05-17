# ADR-0001: Use OpenCode as the AI Engine (Binary Dependency)

**Date:** 2026-03-25
**Status:** Accepted (updated 2026-03-25 — changed from Git submodule to binary dependency)

## Context

Cliff needs an AI engine to power code analysis, remediation planning, and agent execution. Building an LLM orchestration layer from scratch would be a massive effort that distracts from the security product itself.

[OpenCode](https://github.com/anomalyco/opencode) is an active, MIT-licensed open-source coding agent. It provides:

- A headless HTTP server (`opencode serve`) with REST API and OpenAPI 3.1 spec
- Configurable primary agents and subagents with custom prompts and tool permissions
- Support for 75+ LLM providers (Anthropic, OpenAI, Google, AWS Bedrock, etc.)
- A TypeScript SDK for programmatic control
- Server-sent events for real-time streaming
- Session management, memory, and compaction

The server/client architecture means we can use OpenCode's engine without inheriting its terminal UI.

OpenCode compiles to a **standalone static binary** (`CGO_ENABLED=0`). No Go runtime is needed — only the binary itself.

## Decision

Use `anomalyco/opencode` as the AI runtime engine, integrated as a **pinned binary dependency**.

- OpenCode version is pinned in `.opencode-version` at the repo root
- A download script (`scripts/install-opencode.sh`) fetches the correct binary for the user's platform
- On first run, the FastAPI backend auto-downloads OpenCode if the binary is not found
- OpenCode runs as a managed subprocess inside the app, listening on an internal-only port (default 4096)
- FastAPI backend communicates with it via its REST API — the frontend never talks to OpenCode directly
- Custom cyber-security agents are defined in `.opencode/agents/`

### Version management

- `.opencode-version` contains the pinned version (e.g., `1.3.2`)
- In Docker: binary is downloaded during image build
- Local dev: auto-downloaded to `~/.cliff/bin/opencode` on first run, or manually via `brew install opencode` / `npm i -g opencode-ai`

## Consequences

- **Easier:** We get agent orchestration, model provider support, tool execution, and session management for free.
- **Easier:** No Go toolchain required anywhere — not for development, CI, or Docker builds.
- **Easier:** Version pinning + binary download is simpler than submodule management.
- **Harder:** We depend on an external project's API stability. Breaking changes in OpenCode require adaptation.
- **Harder:** Binary download adds a network dependency to first run. Mitigated by caching and manual install option.
- **Risk:** If OpenCode's architecture diverges from our needs, we may need to fork. The binary approach makes this harder than a source-level fork, but the REST API boundary keeps our code decoupled.
