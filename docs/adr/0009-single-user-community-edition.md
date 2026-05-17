# ADR-0009: Single-User Community Edition

**Date:** 2026-03-25
**Status:** Accepted

## Context

Cliff must ship an MVP that is easy to adopt without enterprise sales cycles. The primary audience is individual security practitioners or small teams who want to try AI-assisted remediation.

Multi-user features (auth, RBAC, org management, shared workspaces) add significant complexity and delay the first usable release.

## Decision

The MVP is a **single-user self-hosted community edition**:

- No authentication layer
- No user model or accounts
- All data belongs to the single operator
- One local settings profile
- One local integration config set
- One local history store
- Free and open source (AGPL-3.0 license)

On first run, the app boots into a setup flow where the user configures their model provider and optionally loads demo data.

## Consequences

- **Easier:** Every API endpoint is simpler (no auth middleware, no tenant isolation).
- **Easier:** Fastest path to a working product that real users can try.
- **Easier:** Lower barrier to adoption — no need to set up auth providers.
- **Harder:** Future multi-user/enterprise edition requires adding an auth layer, user model, and data partitioning. Keep the data model future-proof by using workspace-scoped queries.
