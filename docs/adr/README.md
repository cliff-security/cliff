# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for Cliff.

ADRs document significant architectural decisions made during the project. Once accepted, they are immutable records of why a decision was made at a point in time. If a decision is reversed, a new ADR supersedes the old one.

## Index

| # | Title | Status |
|---|-------|--------|
| [0001](0001-opencode-engine-integration.md) | Use OpenCode as the AI engine (binary dependency) | Accepted |
| [0002](0002-fastapi-backend.md) | FastAPI for the backend | Accepted |
| [0003](0003-react-vite-tailwind-frontend.md) | React + TypeScript + Vite + Tailwind for the frontend | Accepted |
| [0004](0004-sqlite-persistence.md) | SQLite for persistence | Accepted |
| [0005](0005-single-docker-container.md) | Single Docker container deployment | Accepted |
| [0006](0006-mock-first-adapters.md) | Mock-first adapter integration strategy | Accepted |
| [0007](0007-domain-model.md) | Domain model design | Accepted |
| [0008](0008-sub-agent-architecture.md) | Sub-agent architecture | Accepted |
| [0009](0009-single-user-community-edition.md) | Single-user community edition | Accepted |
| [0010](0010-monorepo-structure.md) | Monorepo structure | Accepted |
| [0011](0011-stitch-design-system.md) | Stitch design system | Accepted |
| [0012](0012-runtime-settings-via-opencode-api.md) | Runtime settings via OpenCode API | Accepted |
| [0013](0013-runtime-model-source-of-truth.md) | Runtime model as source of truth | Accepted |
| [0014](0014-workspace-runtime-architecture.md) | Workspace runtime architecture — isolated context environments | Proposed |
| [0015](0015-mcp-native-integration-architecture.md) | MCP-native integration architecture | Accepted |
| [0016](0016-credential-vault.md) | Credential vault for encrypted secret storage | Accepted |
| [0017](0017-integration-audit-logging.md) | Integration audit logging | Accepted |
| [0018](0018-mcp-gateway.md) | MCP Gateway — build inline, informed by ecosystem | Accepted |
| [0019](0019-community-mcp-servers-over-custom-adapters.md) | Community MCP servers over custom adapters | Accepted |
| [0020](0020-two-plane-integration-architecture.md) | Two-plane integration architecture (operational + agentic) | Accepted |
| [0021](0021-agent-execution-model.md) | Agent execution model — direct invocation, advisory pipeline, filesystem checkpoints | Accepted |
| [0022](0022-app-level-agent-execution-and-conversational-shell.md) | App-level agent execution and conversational shell | Proposed |
| [0023](0023-async-chunked-finding-ingestion.md) | Async chunked finding ingestion with cost controls | Proposed |
| [0024](0024-repo-cloning-and-agentic-remediation.md) | Repository cloning and agentic remediation | Proposed |
| [0025](0025-assessment-engine-and-badge-lifecycle.md) | Assessment engine and badge lifecycle | Proposed |
| [0026](0026-tiered-scanner-execution.md) | Tiered scanner execution model — Docker default + subprocess fallback | Superseded by [0028](0028-subprocess-only-scanner-execution.md) |
| [0027](0027-unified-findings-model.md) | Unified findings model — one table, four types (dependency/code/secret/posture) | Proposed |
| [0028](0028-subprocess-only-scanner-execution.md) | Subprocess-only scanner execution with pinned binary checksums | Proposed |
| [0029](0029-warning-design-token.md) | Warning design token for Serene Sentinel | Proposed |
| [0030](0030-workspace-schema-unification.md) | Unified workspace schema with active-per-check unique index | Proposed |
| [0031](0031-provider-probe-endpoint.md) | Provider probe endpoint (`POST /api/settings/providers/test`) | Proposed |
| [0032](0032-assessment-v2-dashboard-payload.md) | Dashboard payload shape for security assessment v2 (`tools[]`, four-state posture, labeled criteria, `summary_seen_at`) | Proposed |
| [0033](0033-pre-alpha-destructive-migrations.md) | Pre-alpha destructive migrations — license that expires at v0.1 alpha tag | Accepted |
| [0034](0034-agent-cli-and-skill.md) | Agent CLI (`cliff`) and Claude Code skill (`/secure-repo`) | Proposed |
| [0035](0035-github-app-device-flow-onboarding.md) | GitHub App + Device Flow onboarding (replace PAT) | Proposed |

## Template

Use this template when creating a new ADR:

```markdown
# ADR-NNNN: Title

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Deprecated | Superseded by [ADR-NNNN](link)

## Context

What is the issue that we're seeing that is motivating this decision or change?

## Decision

What is the change that we're proposing and/or doing?

## Consequences

What becomes easier or more difficult to do because of this change?
```
