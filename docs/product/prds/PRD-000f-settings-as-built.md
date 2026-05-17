# PRD-000f: Settings page (as-built)

**Status:** Approved (as-built)
**Author:** Product team (bootstrap)
**Date:** 2026-04-09
**Approver:** @galanko (CEO)

---

## Problem statement

Administrators need to configure which AI model powers the copilot and manage API keys — without this, the product doesn't function. Settings is the operational control plane for the single-user MVP.

## User persona

**Admin / self-hosted operator** — deploying Cliff on their own infrastructure. Needs to set up their AI provider (OpenAI, Anthropic, etc.) and API key to get started.

## User stories

### Story 1: Configure AI provider

**As an** admin, **I want to** select which AI provider and model to use, **so that** the copilot uses my preferred LLM.

**Given** I navigate to Settings,
**When** I search/select a provider and model,
**Then** new workspaces use the selected model. Existing workspaces keep their original model.

**The user should feel:** In control — "I choose the brain behind the copilot."

### Story 2: Manage API keys

**As an** admin, **I want to** add or update my API key, **so that** the copilot can authenticate with the AI provider.

**Given** I'm on the Settings page,
**When** I enter my API key and save,
**Then** the key is stored and used for all future requests. Environment variable fallback exists.

**The user should feel:** Secure — "My key is handled safely."

## What exists today

- Provider selection with search
- Model selection within a provider
- API key add/update/remove
- Environment variable fallback for keys
- About section with version info

## Known gaps

- [ ] No key validation on save (only fails at agent execution time)
- [ ] No usage/cost tracking
- [ ] No multi-provider per-workspace configuration

## Scope boundaries

**In scope for MVP:** Single provider, single model, single API key.
**Out of scope:** Multi-provider, per-workspace model config, cost tracking, rate limiting.

---

_As-built PRD — documents what exists as of 2026-04-09. Not a future spec._
