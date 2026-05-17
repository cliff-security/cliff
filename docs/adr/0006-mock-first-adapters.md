# ADR-0006: Mock-First Adapter Integration Strategy

**Date:** 2026-03-25
**Status:** Accepted

## Context

Cliff needs to connect to external systems across four categories:

1. **Finding sources** (Tenable, Snyk, Dependabot, Wiz, etc.)
2. **Ownership/context sources** (CMDB, cloud tags, CODEOWNERS, etc.)
3. **Ticketing systems** (Jira, GitHub Issues, ServiceNow, etc.)
4. **Validation sources** (re-scanners, test runners, etc.)

Building real integrations before the product workflow is proven would be premature. The integration landscape is broad, and each vendor API has its own quirks.

## Decision

Adopt a **mock-first adapter strategy**:

- Define abstract adapter interfaces for each of the four categories
- Ship MVP with **fixture/mock providers** that return realistic static data
- Seeded demo data supports the entire golden-path user story without any external APIs
- Real adapters implement the same interface and are added incrementally after the workflow is proven

First real integrations (post-MVP): Tenable or Wiz for findings, Jira for ticketing.

## Consequences

- **Easier:** Full end-to-end development and demo without external API credentials.
- **Easier:** Adapter interface becomes the stable contract. Each real adapter is an independent module.
- **Easier:** Contributors can add new adapters without touching core product code.
- **Harder:** Mock data may not surface edge cases that real APIs expose. Mitigated by designing interfaces based on real API shapes.
