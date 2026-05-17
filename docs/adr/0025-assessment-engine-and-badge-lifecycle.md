# ADR-0025: Assessment engine and badge lifecycle

**Status:** Proposed
**Date:** 2026-04-14
**Context PRD:** PRD-0002 (Earn the badge)
**UX Spec:** UX-0002 (Earn the badge)
**Supersedes:** None
**Relates to:** ADR-0014 (workspace runtime), ADR-0022 (app-level agent execution), ADR-0024 (repo cloning)

## Context

PRD-0002 requires Cliff to produce its own vulnerability findings (instead of relying on imported scanner output), plain-language descriptions for non-expert users, a repo posture checklist, and a "Secured by Cliff" badge earned when a small set of criteria are met. The decision points are:

1. Build the assessment (lockfile parsing + CVE lookup + posture) as a deterministic backend service **or** as agents?
2. Model badge state as a dedicated state machine **or** as a derived view?
3. Introduce a new architecture for the three PR-creating agents (SECURITY.md, dependabot.yml, badge on README) **or** reuse the existing ephemeral-workspace + single-shot-agent pattern?
4. Ship all eight lockfile parsers in v1.1 **or** phase them?

## Decision

### 1. The assessment engine is deterministic Python, not agents

Lockfile parsing, OSV.dev lookups, and GitHub API posture checks are mechanical. Making them agents would add LLM cost, non-determinism, and latency for zero benefit. The only place LLMs participate in the assessment pipeline is the existing `finding-normalizer` agent (ADR-0022), which we extend to emit a `plain_description` field alongside the structured fields it already produces.

New module layout:

```
backend/cliff/assessment/
    __init__.py
    engine.py            # orchestrates parse -> CVE lookup -> posture -> normalize
    osv_client.py        # OSV.dev HTTP client
    ghsa_client.py       # GitHub Advisory DB fallback
    parsers/
        __init__.py      # parser registry: ecosystem -> parser fn
        npm.py           # package-lock.json
        pip.py           # Pipfile.lock + requirements.txt
        golang.py        # go.sum
        # ruby/java/rust/yarn added in a follow-up
    posture/
        __init__.py
        github_api.py    # thin PyGithub wrapper used by all checks
        branch.py        # branch protection + force push
        secrets.py       # regex-based secret scan over tracked files
        files.py         # SECURITY.md + lockfile + dependabot existence
```

### 2. Badge state is derived, not persisted

The badge is earned when all five criteria hold right now:

- Zero open critical vulnerability findings
- Zero open high vulnerability findings
- Branch protection enabled on default branch
- No secrets detected on the latest posture check
- `SECURITY.md` exists

We compute this at read-time in the assessment endpoint. We only persist **events** that are otherwise unrecoverable:

| Table | Purpose |
|---|---|
| `assessments(id, started_at, completed_at, status, summary_json)` | One row per assessment run — feeds the history list |
| `posture_checks(assessment_id, check_name, status, detail_json)` | Per-check results within one assessment |
| `badges(id, earned_at, revoked_at, last_verified_at, readme_pr_number)` | Lifecycle events only — single row for v1.1 (single repo) |

Critically, there is no `findings.badge_blocking` column or `repo.grade` column. Those are joined/computed. If the facts move, the grade moves with them, no migrator needed.

### 3. The three PR agents reuse the existing workspace pattern

SECURITY.md generation, dependabot.yml generation, and badge installation on README are all "single-shot template agent in an ephemeral workspace that creates a PR" — the same pattern already in production for `remediation_executor` (ADR-0024). The only extension is a new workspace kind.

Today every workspace is scoped to exactly one finding. We introduce a second kind — **repo workspaces** — scoped to the repo itself. Concretely:

```
data/workspaces/<workspace_id>/          # existing, one per finding
data/workspaces/repo-<action>-<ts>/       # new: ephemeral, cleaned up after PR
```

The `WorkspaceDirManager` and `WorkspaceProcessPool` already handle the directory-and-port plumbing; only a `WorkspaceKind = finding | repo_action` discriminator is added. No new process manager, no new engine integration.

Three new agent templates go in `backend/cliff/agents/`:

- `security_md_generator.md.j2`
- `dependabot_config_generator.md.j2`
- `badge_installer.md.j2`

Each is a small prompt that expects: repo path, repo URL, default branch, one action parameter. Output contract mirrors `remediation_executor`: `pr_url`, `pr_number`, `branch_name` in the sidebar.

### 4. Ship three parsers in v1.1, expand later

Build npm, pip, and go parsers for v1.1. These three cover the majority of the open-source long tail based on GitHub ecosystem data. Ruby, Java, Rust, and yarn parsers each add ~200–300 LOC and can land as independent follow-ups without schema change. Shipping three parsers gets Alex (the PRD persona) to a badge faster; shipping eight delays everyone.

The `parsers/__init__.py` registry makes adding a parser a one-line change, so there is no architectural cost to phasing.

## Consequences

**Positive**

- Assessment is fast (< 10s for a repo with ~1000 deps), deterministic, cacheable, and testable with pure unit tests. No LLM spend per assessment.
- Badge state can never drift from the underlying facts — no "my badge still says earned but I have new critical findings" bug class.
- The three "Cliff can create this" actions reuse the single most-tested path in the app. No new agent-runner code, no new process management.
- Phasing parsers lets us ship IMPL-0002 in a predictable window. Each additional parser is a follow-up PR with its own fixture-based test.

**Negative / accepted**

- OSV.dev becomes a runtime dependency. We mitigate with a GHSA fallback and an "unable to verify — please retry" result per finding when both are down. An entire assessment never fails — it degrades.
- Secrets scanning is regex-based (PRD explicit) and will miss things real secret scanners catch. We accept this for v1.1; the posture check reports "no obvious secrets detected" rather than "no secrets", which sets expectations correctly.
- Posture checks hit the GitHub API synchronously. At realistic repo sizes this is 4–6 REST calls, well inside the 5000/hour PAT limit. If we hit the limit, checks individually return "unable to verify" (per PRD) rather than failing the whole assessment.

**Open**

- Whether the `badges` table graduates from a single row to a multi-row history in v1.2 (for the multi-repo future) is deferred. v1.1 assumes single-repo per ADR-0009.

## Alternatives considered

1. **Assessment as an "assessment agent"** — rejected. LLM cost and nondeterminism are wrong for work that's a pure function of inputs.
2. **Badge as a first-class state machine** — rejected. Derived state has no drift bugs; the badge question is "do the facts currently qualify?", not "what's the badge's current mood?".
3. **Use OSS secret-scanning tools (trufflehog, gitleaks)** — rejected for v1.1. Adds a subprocess dependency and complicates Docker packaging. Regex patterns for the ~10 highest-impact key formats (AWS, GitHub, Stripe, Google API, generic PEM) cover the obvious mistakes the PRD targets.
4. **Ship all 8 parsers in v1.1** — rejected. Each parser carries maintenance. Three cover the critical path; four through eight ship as they become needed.
