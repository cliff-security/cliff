---
name: "Cliff Security"
description: |
  Drive Cliff from inside Claude Code. Trigger when the user asks to (a) install Cliff, (b) onboard credentials (GitHub PAT or an AI provider key), (c) secure a repo end-to-end (scan → plan → approve → PR → merge → close), or (d) troubleshoot a broken install. The skill is action-dispatched: this file routes to one of four versioned playbooks under `knowledge/`. Uses the `cliffsec` CLI (bundled with the Cliff installer) and `gh` for PR review/merge and issue-filing. Hard rule: never auto-approve plans, auto-merge PRs, auto-submit issues, or run any write action without explicit user approval — those are user gates.
version: "0.2.0"
category: "security"
tags: [cliff, security, remediation, vibe-security, agent-cli]
---

# Cliff Security

You drive Cliff on the user's behalf. This skill is **action-dispatched**: pick the playbook that matches what the user asked for, then follow it. The skill itself stays short — playbooks live in `knowledge/`.

The CLI is agent-shaped: every command emits one JSON object on stdout and the exit code encodes state. Trust the exit code — it tells you what to do next.

## Pick the playbook

Read the matching file from `knowledge/` before acting. Do not improvise from memory.

| User intent (and how to detect it) | Playbook |
|---|---|
| "install Cliff", "set up Cliff", first run, `cliffsec` not on PATH, `cliffsec status` exits 3 with no PID file | `knowledge/install.md` |
| "connect GitHub", "add my API key", "onboard", `cliffsec status` returns `ready: false` with `blockers` like `no_llm_model_configured` or `no_github_integration` | `knowledge/onboarding.md` |
| "secure this repo", "vibe security", "scan with Cliff", "fix the findings", "drive Cliff on this repo" | `knowledge/secure-repo.md` |
| "troubleshoot", "doctor", "Cliff is broken", "the daemon won't start", any `cliffsec` exit 1 (generic error) in the main loop | `knowledge/troubleshooting.md` |

If the user's intent spans multiple actions ("install Cliff and secure this repo"), run them in order: **install → onboarding → secure-repo**. Each playbook ends with a one-line "now what" hint that names the next file.

If the user just says "use Cliff" with no further context, run `cliffsec status` first and let the exit code pick the playbook for you:

- Command not found / exit 3 → `install.md`
- Exit 0, `ready: false` → `onboarding.md`
- Exit 0, `ready: true` → `secure-repo.md`
- Exit 1 / 4 → `troubleshooting.md`

## Hard rules — apply to every playbook

These are non-negotiable and override any local guidance inside a playbook that contradicts them:

1. **Never auto-approve a plan.** Cliff exits 2 when a plan is awaiting a human gate. Show the plan summary + steps and wait for an explicit "approve" / "yes" / "go" before calling `cliffsec approve`.
2. **Never auto-merge a PR.** After `cliffsec approve` returns a `pr_url`, summarize the diff with `gh pr view --json title,body,files,additions,deletions` + `gh pr diff`, then wait for "merge" before calling `gh pr merge --squash`.
3. **Never run a write action without explicit approval.** Write actions include `cliffsec start`, `stop`, `restart`, `update`, `config set`, `xattr`, re-running the installer, creating an Integration, and storing an API key. Read-only diagnostics (`status`, `doctor`, `logs`, `--check`, `ps`, `curl GET …`) are fine to run unprompted.
4. **Never auto-submit a GitHub issue.** Always use `gh issue create --web` so the body opens in the user's browser for review.
5. **Never invent IDs.** Only pass IDs the CLI returned. If you don't have one, run `cliffsec issues` to get one.
6. **Don't silence exit 4 (version mismatch).** Stop and ask the user to re-run the installer. Do not try to work around it.
7. **Stop on validation failure.** If `cliffsec approve` exits 2 with `validation.verdict != "ok"`, do not call `close`. Surface the failure and stop.
8. **Never call `cliffsec uninstall` as a remedy.** It removes data and config. Only run it if the user explicitly asks to uninstall.

## Exit-code contract

Every `cliffsec` command emits one JSON object on stdout (or stderr on error) and exits with:

| Code | Meaning | What you do |
|---|---|---|
| 0 | Success, no human gate needed (incl. `fix` clearing a finding as **noise** — `cleared: true`) | Read `next` (+ `verdict`/`reason` for `fix`), continue |
| 2 | Awaiting human gate (plan to approve, `needs_review` triage verdict, or validation) | Surface details, wait for user |
| 3 | Daemon unreachable | Run `knowledge/install.md` |
| 4 | Version mismatch | Stop, ask user to upgrade |
| 5 | Scan completed with zero findings | Tell user the repo is clean, stop |
| 1 | Generic error | Enter `knowledge/troubleshooting.md`. Don't just print the hint — diagnose. |

## Integrity — version-pinned playbooks

This skill ships SKILL.md plus four playbooks under `knowledge/`. Every file carries a `version:` field in its YAML frontmatter. **Before relying on a playbook, confirm its `version:` equals this skill's `version` (`0.2.0`).** If they diverge, the user has a tampered or partial install — refuse to follow the playbook and tell them to re-run the installer.

The check is done at **playbook-read time**, not by an upfront shell command — the skill's on-disk location depends on how Claude Code installed it (marketplace plugins land outside the user's project, not at any `plugins/...` path you can hardcode), so there is no fixed path to grep. When you open a playbook with the Read tool, look at the YAML frontmatter at the top:

- `name:` should be one of `install`, `onboarding`, `secure-repo`, `troubleshooting`.
- `version:` MUST equal `"0.2.0"`.

If the version doesn't match, stop and tell the user "the `<name>` playbook reports version X but this skill is version 0.2.0 — reinstall the plugin (`/plugin install cliff-security@cliff`) and try again." Do **not** follow a mismatched playbook.

This is not a substitute for shipping the skill via a trusted source (the marketplace JSON in this repo); it's a fail-loud check that catches "user hand-edited one of the files" before that drift turns into wrong actions.

## Token discipline

- Always pass `--severity` and `--limit` on `cliffsec issues`. Don't list 100 findings when 10 will do.
- Don't ask the CLI for `--verbose` unless something failed and you need detail.
- Don't re-run `cliffsec status` between every step — once at the start is enough. Run it again only after an unexpected error.
- When showing a plan or PR diff, summarize. The user can read the diff themselves if they want — your value is the one-line risk read.
- Don't load a playbook you don't need. Read only the file that matches the current action.

## When in doubt

- The CLI returned a `next` field? Use it. The CLI knows what comes next.
- The user said "stop" or "let me look"? Stop. Don't keep the loop running.
- Unknown finding type? Just call `cliffsec fix <id>` and let the pipeline handle it. Don't pre-classify.
- An action straddles two playbooks (e.g. "install and secure")? Finish the first playbook to its end-of-flow state before opening the next.
