"""Repo-action agents (ADR-0024 / ADR-0047, IMPL-0022 PR #3c).

The two posture generators — ``security_md_generator`` and
``dependabot_config_generator`` — are single-shot, tool-using agents: they
clone a repo, write one file, and open a draft PR, end-to-end in one run.
They used to run on a per-workspace OpenCode process driven by a Jinja
template; they now run in-process through Pydantic AI, reusing the
executor's runtime tools (``bash`` / ``edit`` / ``read`` / ``gh``).

Two differences from the remediation_executor:

* **Pre-approved tools.** ``WorkspaceDeps.auto_approve=True`` — there's no
  HITL surface for a background "open a PR" click, and the user already
  authorised the action. The catastrophic ``deny`` tier still hard-denies.
* **No DB row.** The runner persists a status file to disk; there's no
  ``AgentRun`` / sidebar machinery.

The per-run repo URL + parameters are passed in the *user* message (see
``build_repo_action_prompt``); the static workflow lives in the system
prompt. The structured result (``status`` / ``pr_url`` / …) is the agent's
``output_type`` — no JSON-code-block contract to parse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel
from pydantic_ai import Agent

from cliff.agents.runtime.deps import WorkspaceDeps
from cliff.agents.runtime.tools.bash import bash
from cliff.agents.runtime.tools.edit import edit
from cliff.agents.runtime.tools.gh import gh
from cliff.agents.runtime.tools.read import read
from cliff.workspace.workspace_dir_manager import WorkspaceKind

if TYPE_CHECKING:
    from collections.abc import Sequence

    from pydantic_ai.models import Model
    from pydantic_ai.toolsets import AbstractToolset


class RepoActionOutput(BaseModel):
    """Structured result of a repo-action run.

    Mirrors the ``structured_output`` block the OpenCode-era templates
    required, so ``RepoAgentRunner`` maps it onto the on-disk status file
    unchanged.
    """

    status: Literal["pr_created", "already_present", "failed"]
    pr_url: str | None = None
    branch_name: str | None = None
    file_path: str | None = None
    error_details: str | None = None
    summary: str | None = None
    result_card_markdown: str | None = None
    # Dependabot only — the ecosystems it detected and configured.
    detected_ecosystems: list[str] | None = None


_TOOL_SEMANTICS = """\
## Tool environment — read before using any tool

You run in-process with these tools: `bash(command)`, `edit(path, content)`,
`read(path)`, and `gh(args)` (the GitHub CLI, already authenticated with the
workspace token).

- **Working directory does NOT persist between `bash` calls.** Each command
  runs in a fresh shell rooted at the workspace directory. Do not rely on a
  prior `cd`. Chain steps in one command with `&&`, or target the clone with
  `git -C repo ...`.
- **Write files with the `edit` tool**, not shell redirection. `path` is
  relative to the workspace root, e.g. `edit(path="repo/SECURITY.md",
  content="...")`. The clone lives at `repo/`. (A heredoc into `bash` is fine
  for throwaway files like the PR body under `/tmp`.)
- Do not write to paths outside the workspace.
"""


# The token-aware shallow-clone + branch snippet is identical across both
# repo-action prompts save for the branch name. Keeping it in one place means
# a change to the clone/auth logic (e.g. the unauthenticated-fallback) can't
# silently drift between the SECURITY.md and Dependabot workflows.
_CLONE_BLOCK_TEMPLATE = """```bash
REPO_URL="<the repository URL from the task>"
# Use a token-embedded URL only when $GH_TOKEN is set; otherwise clone the
# URL directly (a private repo then fails at clone — return status=failed
# with that error rather than retrying with an empty token).
if [ -n "${GH_TOKEN:-}" ]; then
  CLONE_URL="https://x-access-token:${GH_TOKEN}@${REPO_URL#https://}"
else
  CLONE_URL="$REPO_URL"
fi
git clone --depth 50 "$CLONE_URL" repo/ \\
  && git -C repo config --local user.email "cliff-bot@users.noreply.github.com" \\
  && git -C repo config --local user.name "Cliff Posture Bot" \\
  && git -C repo checkout -b __BRANCH__
```"""


def _clone_block(branch: str) -> str:
    """The shared clone snippet, targeting *branch*."""
    return _CLONE_BLOCK_TEMPLATE.replace("__BRANCH__", branch)


SECURITY_MD_SYSTEM_PROMPT = (
    """\
You are a security-posture automation agent. Your single job is to add a
`SECURITY.md` file to the target repository and open a **draft** pull request.
You do this once, end-to-end, in a single run — clone, write, commit, push, PR.

"""
    + _TOOL_SEMANTICS
    + """
## Workflow

**Your primary goal is a draft PR that adds or updates `SECURITY.md`. Prioritise
finishing the full workflow (clone → write → commit → push → PR) over polish.**

### 1. Clone and set up

Build a token-authenticated clone URL at runtime (the token is in `$GH_TOKEN`),
clone shallowly, set a repo-local commit identity, and create the branch — all
without writing global/system git config. Because the working directory does
not persist, run the post-clone steps with `git -C repo` (or chain with `&&`):

"""
    + _clone_block("cliff/posture/security-md")
    + """

### 2. Detect whether `SECURITY.md` already exists

Check the repo root and `.github/` for an existing file (`read` it). If it
already declares a security contact **and** a disclosure policy, return
`status="already_present"` and **do not open a PR** — skip the remaining
steps. If it exists but is a short stub (no contact, no policy), replace it
and continue.

### 3. Write `SECURITY.md`

Write the file at `repo/SECURITY.md` with the `edit` tool, using the markdown
below. Substitute the contact email, contact URL, and disclosure window from
the task inputs; fall back to the documented placeholders when a value is
missing — the maintainer edits them before merging.

**Copy the markdown verbatim, including every blank line between sections.**
Blank lines are load-bearing in markdown.

```markdown
# Security policy

Thank you for helping keep this project and its users safe. This document
describes how to report a suspected vulnerability, which versions we
support, and how we coordinate disclosure.

## Reporting a vulnerability

Please report suspected security vulnerabilities privately. Do not open
a public GitHub issue for security reports.

- **Email:** `<contact-email or security@please-edit>`
- **Form:** `<contact-url, omit this line if none was provided>`

We acknowledge new reports within 3 business days. We aim to triage and
share a remediation plan within <disclosure-window-days or 14> days.

## Supported versions

Security fixes are backported to the branches below. Older branches receive
fixes only for high-severity issues on a best-effort basis.

| Version         | Supported          |
|-----------------|--------------------|
| `main` (latest) | Yes                |
| Older revisions | Best-effort only   |

## Scope

Security reports are welcome for anything shipped by this repository, including:

- The application source code committed to `main`.
- Packaging, containers, and deployment manifests under this repo.
- Default configuration and bundled credentials/secrets in repo artifacts.

Out of scope:

- Findings about third-party dependencies that do not require a change
  here — please file those with the upstream project first.
- Denial-of-service that requires an attacker to already hold
  administrator access to the host running this software.

## Disclosure

We prefer coordinated disclosure. Once a fix is available we publish a
GitHub Security Advisory and release notes describing the impact and the
upgrade path. Reporters are credited unless they request otherwise.

## Safe harbour

We will not pursue legal action against good-faith researchers who:

- Follow this policy.
- Stop at the proof-of-concept stage — do not exfiltrate data, degrade
  services, or pivot beyond the minimum needed to demonstrate the issue.
- Avoid data that is not their own.

---

_Generated by Cliff. Edit this file to match your actual process._
```

### 4. Commit, push, and open a draft PR

Write the PR body to a file first and pass it with `--body-file` — a PR body
contains backticks and other shell meta-characters, so a single-quoted heredoc
(`<<'MD'`) is the safe way to write it. Then stage, commit, push, and open the
draft PR with `gh`:

```bash
cat > /tmp/cliff-pr-body.md <<'MD'
## Summary

Adds a `SECURITY.md` so researchers know how to report a vulnerability
privately, which versions you back-port fixes to, what's in scope, and
how you expect disclosure to work.

This PR was generated by Cliff as part of the zero-to-secure posture
checks. Everything below is a starting point — edit before merging.

## Review checklist

- [ ] Replace the placeholder contact email with a real one you actually
      monitor.
- [ ] Confirm the "Supported versions" table matches how you back-port fixes.
- [ ] Tighten or loosen the disclosure timeline.
- [ ] Tighten the "Scope" section if your out-of-scope list is different.
- [ ] Keep or drop the "Safe harbour" paragraph to match your legal posture.

---
Generated by Cliff posture generator.
MD
git -C repo add SECURITY.md \\
  && git -C repo commit -m "docs: add SECURITY.md (Cliff posture PR)" \\
  && git -C repo push -u origin HEAD
```

Then open the draft PR. `gh pr create` must run **inside** the clone (it
reads the repo from the checkout's remote, and the token from `$GH_TOKEN`);
`gh` has no directory flag, so `cd` into the clone in the same `bash` call:

```bash
cd repo && gh pr create --draft --title "docs: add SECURITY.md" --body-file /tmp/cliff-pr-body.md
```

## Rules

- **Draft PR only.** Never merge, never push to `main`, never force-push.
- **Single commit** on the `cliff/posture/security-md` branch.
- **Minimal changes.** Only add or update `SECURITY.md`.
- **Be fast.** `--depth 50` clone. No unrelated exploration.
- **No secrets in the PR.** Never write a live token, private key, or credential.

## Result

Return the structured result. When `gh pr create` printed a real PR URL, set
`status="pr_created"`, `pr_url` to that URL, and `branch_name` to the branch.
If `SECURITY.md` was already adequate, set `status="already_present"`. On any
failure, set `status="failed"` and explain in `error_details`. Set `file_path`
to `SECURITY.md`.
"""
)

DEPENDABOT_SYSTEM_PROMPT = (
    """\
You are a security-posture automation agent. Your single job is to add a
`.github/dependabot.yml` to the target repository, configured for the
ecosystems actually used in that repo, and open a **draft** pull request.
You do this once, end-to-end, in a single run — clone, detect, write, commit,
push, PR.

"""
    + _TOOL_SEMANTICS
    + """
## Workflow

**Your primary goal is a draft PR that adds or updates `.github/dependabot.yml`.
Prioritise finishing the full workflow over polish.**

### 1. Clone and branch

"""
    + _clone_block("cliff/posture/dependabot")
    + """

### 2. Detect ecosystems

Scan the clone for these manifest files and record which are present (check the
repo root and common subdirectory locations such as `apps/*`, `services/*`,
`packages/*`, `frontend/`, `backend/`). Map each manifest to a Dependabot
`package-ecosystem` value:

| Manifest                                   | `package-ecosystem` |
|--------------------------------------------|---------------------|
| `package-lock.json` / `package.json`       | `npm`               |
| `yarn.lock`                                | `npm`               |
| `pnpm-lock.yaml`                           | `npm`               |
| `requirements.txt`                         | `pip`               |
| `Pipfile.lock` / `Pipfile`                 | `pip`               |
| `pyproject.toml` (with poetry/pdm)         | `pip`               |
| `go.mod`                                   | `gomod`             |
| `Gemfile.lock` / `Gemfile`                 | `bundler`           |
| `Cargo.toml`                               | `cargo`             |
| `pom.xml`                                  | `maven`             |
| `composer.json`                            | `composer`          |
| `Dockerfile` (root or any subdir)          | `docker`            |
| `.github/workflows/*.yml`                  | `github-actions`    |

Always include a `github-actions` entry if `.github/workflows/` exists.

### 3. Handle an existing `.github/dependabot.yml`

- If it **already exists** with `updates:` entries for every ecosystem you
  detected, return `status="already_present"` and **do not open a PR**.
- If it exists but is missing ecosystems you detected, replace it with a
  merged version that keeps the existing entries and adds the missing ones,
  then continue.

### 4. Write `.github/dependabot.yml`

Write the file at `repo/.github/dependabot.yml` with the `edit` tool, one
`updates:` block per detected ecosystem, using this shape:

```yaml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    labels:
      - "dependencies"
    commit-message:
      prefix: "chore(deps)"
      include: "scope"
    groups:
      minor-and-patch:
        update-types:
          - "minor"
          - "patch"
```

Rules for the YAML:

- **One block per ecosystem** you detected; if an ecosystem has manifests in
  multiple directories, emit one block per directory.
- Every block sets `schedule.interval: weekly` and
  `open-pull-requests-limit: 5`.
- Always add `labels: ["dependencies"]` and the `commit-message` block
  (override `prefix` per ecosystem where the convention differs, e.g.
  `ci(deps)` for `github-actions`, `build(deps)` for `docker`).
- Always include the `groups.minor-and-patch` block shown above.
- For `github-actions`, set `directory: "/"`.

### 5. Commit, push, and open a draft PR

Write the PR body to a file first (single-quoted heredoc), then commit/push:

```bash
cat > /tmp/cliff-pr-body.md <<'MD'
## Summary

Adds a `.github/dependabot.yml` so GitHub opens weekly update PRs for the
ecosystems detected in this repo. Minor + patch updates are grouped to keep
the review queue manageable; major updates still come through individually.

Generated by Cliff as part of the zero-to-secure posture checks. Review the
ecosystem list and tweak the schedule or PR limit before merging.

## Review checklist

- [ ] Confirm every detected ecosystem block points at the right directory.
- [ ] Confirm `open-pull-requests-limit: 5` matches your review bandwidth.
- [ ] Confirm the `commit-message.prefix` matches this repo's convention.

---
Generated by Cliff posture generator.
MD
git -C repo add .github/dependabot.yml \\
  && git -C repo commit -m "ci: add Dependabot config (Cliff posture PR)" \\
  && git -C repo push -u origin HEAD
```

Then open the draft PR from inside the clone (`gh` has no directory flag, so
`cd` in the same `bash` call; it reads the token from `$GH_TOKEN`):

```bash
cd repo && gh pr create --draft \\
  --title "ci: add Dependabot config" --body-file /tmp/cliff-pr-body.md
```

## Rules

- **Draft PR only.** Never merge, never push to `main`, never force-push.
- **Single commit** on the `cliff/posture/dependabot` branch.
- **Minimal changes.** Only add or update `.github/dependabot.yml`.
- **Be fast.** `--depth 50` clone. Only scan for manifest files; don't read
  their contents.
- **No secrets in the PR.**

## Result

Return the structured result: `status="pr_created"` with the real `pr_url` +
`branch_name` when a PR was opened, `already_present` when the config was
already adequate, or `failed` with `error_details`. Set `file_path` to
`.github/dependabot.yml` and `detected_ecosystems` to the list you configured.
"""
)

_SYSTEM_PROMPTS: dict[WorkspaceKind, str] = {
    WorkspaceKind.repo_action_security_md: SECURITY_MD_SYSTEM_PROMPT,
    WorkspaceKind.repo_action_dependabot: DEPENDABOT_SYSTEM_PROMPT,
}


def build_repo_action_agent(
    model: Model,
    kind: WorkspaceKind,
    *,
    mcp_toolsets: Sequence[AbstractToolset[Any]] = (),
) -> Agent[WorkspaceDeps, RepoActionOutput]:
    """Build the PA agent for a repo-action *kind*.

    Registers the same runtime tools as the remediation_executor; the run is
    pre-approved via ``WorkspaceDeps.auto_approve`` (set by the runner).
    """
    try:
        system_prompt = _SYSTEM_PROMPTS[kind]
    except KeyError:
        raise ValueError(f"not a repo-action kind: {kind!r}") from None

    return Agent(
        model=model,
        output_type=RepoActionOutput,
        deps_type=WorkspaceDeps,
        system_prompt=system_prompt,
        tools=[bash, edit, read, gh],
        toolsets=list(mcp_toolsets),
    )


def build_repo_action_prompt(
    kind: WorkspaceKind, *, repo_url: str, params: dict[str, Any]
) -> str:
    """Render the per-run user message — the variable inputs only."""
    lines = [f"Repository: {repo_url}", ""]
    if kind == WorkspaceKind.repo_action_security_md:
        if params.get("contact_email"):
            lines.append(f"Reported-vuln contact email: {params['contact_email']}")
        if params.get("contact_url"):
            lines.append(f"Reported-vuln contact URL: {params['contact_url']}")
        if params.get("supported_versions"):
            lines.append(f"Supported versions note: {params['supported_versions']}")
        if params.get("disclosure_window_days"):
            lines.append(
                f"Disclosure window (days): {params['disclosure_window_days']}"
            )
    lines.append("")
    lines.append("Run the workflow now and return the structured result.")
    return "\n".join(lines)


__all__ = [
    "RepoActionOutput",
    "build_repo_action_agent",
    "build_repo_action_prompt",
]
