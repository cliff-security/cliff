# ADR-0038 — Outbound URL validation policy for user/LLM-supplied URLs

* **Status**: Proposed
* **Date**: 2026-05-17
* **Related**: ADR-0037 (AI provider unified config), ADR-0009 (single-user
  community edition), the Q01-campaign architect health-check.

## Context

OpenSec issues outbound HTTP requests to URLs that originate **outside
the codebase** in three distinct places, each with a different trust
profile:

1. **`validators._safe_custom_chat_url`** — the user pastes a base URL
   for an OpenAI-compatible "custom" provider. Today: strict policy
   — rejects loopback / private / link-local / multicast / reserved /
   unspecified IPs (DNS-aware), reconstructs the URL via `urlunparse`
   to break the SSRF taint chain.
2. **`validators.safe_ollama_tags_url`** — the user pastes a base URL
   for an Ollama runtime (or omits and we default to
   `http://localhost:11434`). Loopback + RFC1918 stay **allowed**
   (the SSH-tunnel and remote-Ollama-on-LAN use cases depend on it);
   only obviously-malicious IP classes (link-local incl.
   `169.254.169.254` cloud metadata, multicast, reserved, unspecified)
   are rejected.
3. **`services.reference_verifier`** — the agent enricher emits
   references as free-text URLs. The list is LLM-controlled, so we
   apply the **strict** policy (same as `_safe_custom_chat_url`) —
   loopback + RFC1918 are rejected here.

Before the Q01 architect review these three sinks had three different
validation stances written ad-hoc — a CodeQL `py/full-ssrf` alert on
Ollama, an unguarded sink in `reference_verifier`, and a stored
Ollama `base_url` re-used by the picker's live `/models` route that
the validator never re-checked. Q01 fixed each sink (M1/M2/L2) and
this ADR codifies the policy so future outbound calls don't drift.

## Decision

Every outbound HTTP fetch whose URL is **not a compile-time string
constant inside the OpenSec codebase** MUST route through one of two
helpers, chosen by trust profile:

### Strict policy — `_ip_is_unsafe`

Use for URLs whose **source cannot be trusted to point at the public
internet**:

* User-supplied "custom" provider base URLs.
* LLM-produced URLs (reference verifier, future agent-emitted URL
  surfaces).

Rejects: loopback, RFC1918 private, link-local, multicast, reserved,
unspecified. DNS-aware (resolves hostnames before checking).

### Loose policy — `_ip_is_obviously_unsafe`

Use for URLs **explicitly designed to point at user-controlled
hosts** on a trusted network:

* Ollama base URLs (the runtime is loopback-by-default; SSH-tunnel and
  remote-Ollama-on-LAN are documented use cases).

Rejects only: link-local (incl. cloud metadata `169.254.169.254`),
multicast, reserved, unspecified. Loopback + RFC1918 stay allowed.

### Implementation requirement

Both helpers MUST:

1. Validate the URL scheme (`http`, `https` only).
2. Resolve hostnames via `getaddrinfo` and apply the IP check to
   every resolved address (closes the DNS-rebinding window).
3. Reconstruct the URL via `urlunparse` from validated parts so the
   SSRF taint flow is broken for static analysis.

Adding a new outbound sink without going through one of these
helpers SHOULD fail PR review. CodeQL's `py/full-ssrf` query is
already configured to flag the unguarded shape.

## Consequences

* New outbound surfaces require a one-line decision: "is the URL
  source trusted to point at the public internet?" — strict if no,
  loose if yes-but-on-a-local-network.
* The `_ip_is_obviously_unsafe` carve-out is intentionally narrow —
  only Ollama qualifies today. Any future addition needs justification
  in the call-site docstring.
* The single-user / self-hosted threat model means an attacker who
  controls the OpenSec process can already do anything; these
  validators protect against **adjacent** attacks: LLM prompt
  injection, BYOK form misconfiguration, future multi-user surfaces.

## Status / next

Implemented in Q01 (commits on `qa/q01-campaign-fixes` covering
M1/M2/M3/L2). This ADR exists to make the policy discoverable so the
next outbound surface added to the codebase picks the right helper.
