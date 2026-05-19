---
name: "troubleshooting"
description: "Diagnose a broken Cliff install, propose a fix gated on user approval, verify it took, and escalate real bugs as a pre-filled GitHub issue."
version: "0.2.0"
---

# Troubleshooting

Engage when:

- A `cliffsec` command in the main flow exits **1** (generic error).
- A command hangs longer than ~2 minutes with no output.
- The user says "troubleshoot", "it's broken", "something's wrong", "fix the daemon", "Cliff isn't working", or anything similar.
- `cliffsec status` exits 3 **but a PID file exists at `~/.cliff/run/cliff.pid`** — Cliff was installed but the daemon crashed or got orphaned. (No PID file → `install.md`, not here.)

Do **not** engage for exit 2 / 4 / 5 — those have their own paths in the other playbooks.

The flow is fixed: **gather → diagnose → propose → verify → escalate**. Don't improvise; follow the playbook.

## Hard rules recap (from SKILL.md)

- Read-only diagnostics (`doctor`, `logs`, `--check`, `ps`, `uname`) are fine to run unprompted.
- Every write action — `start`, `stop`, `restart`, `update`, `config set`, `xattr`, re-running the installer — needs an explicit "yes" first.
- Never call `cliffsec uninstall` as a remedy. It removes data and config.
- Never auto-submit a GitHub issue. Always `gh issue create --web`.

## A. Gather (read-only — no approval needed)

Run all of these once and **keep the output** for diagnosis and a possible issue draft:

```bash
cliffsec doctor --json
cliffsec logs --lines 100 || true
cliffsec --version
cliffsec update --check || true   # exit 0 = up to date, exit 2 = newer available
ps -ef | grep -E '(cliff|opencode|uvicorn)' | grep -v grep || true
uname -a
```

These are all safe; the user does not need to approve them. Capture stdout + stderr verbatim — you'll reuse it in Phase E.

## B. Diagnose (match signals against the table)

Cross-reference Phase A output against this table. The mapping is **fixed** — don't invent fixes that aren't here. If nothing matches, go straight to Phase E (escalate).

| Signal | Diagnosis | Proposed action |
|---|---|---|
| `status` exit 3, no PID file at `~/.cliff/run/cliff.pid` | Daemon was never started (or Cliff isn't installed) | `cliffsec start --detach` if installed, else route to `install.md` |
| `status` exit 3, PID file exists but the recorded process is gone | Crashed orphan, ports possibly leaked | `cliffsec stop` (sweeps owned children) then `cliffsec start --detach` |
| `doctor` shows `port.<configured-app-port>` failing | Port conflict | Pick a free port, then `cliffsec config set CLIFF_APP_PORT=<port>` and `cliffsec restart` |
| `doctor` shows `port.4096` or `port.4100..4102` failing AND status is daemon-down | OpenCode child leaked from a previous crash | `cliffsec stop` (the sweep reclaims orphans) then `cliffsec start --detach` |
| `doctor` shows `opencode` failing with "not found" | OpenCode binary missing or never installed | Re-run the install one-liner (see `install.md`) |
| `doctor` shows `opencode.quarantine` failing on macOS | Gatekeeper quarantined the binary | `xattr -dr com.apple.quarantine ~/.cliff/bin/opencode` (and `trivy` / `semgrep` if they show the same) |
| `doctor` shows `venv` failing | Backend venv corrupt or removed | Re-run the install one-liner |
| `doctor` shows `credential_key` missing | Encryption key not in env file | Re-run the install one-liner (it generates and persists the key) |
| `doctor` shows `migrations` failing with a SQLite error | DB schema state is bad | **Bug** — escalate (Phase E). Do not propose deleting the DB without explicit user request — it would lose findings + workspaces. |
| `update --check` exit 2 (newer release available) AND symptoms could plausibly be a known fix | Out-of-date install | Offer `cliffsec update` |
| Logs contain a Python traceback (`Traceback (most recent call last):` or `ERROR  ` lines on every request) | Real bug | Escalate (Phase E) |
| Doctor entirely clean, command still failing | No diagnosis from signals | Escalate (Phase E) |

## C. Propose + gate

For any write action you've identified, format the proposal as one block:

> **Diagnosis:** <one line — what doctor/logs showed>.
> **Proposed fix:** `<the exact command(s)>`.
> **What it changes:** <one line — e.g. "moves Cliff to port 8001 and restarts the daemon">.
> **May I proceed?**

Wait for an explicit "yes" / "go" / "do it". Anything ambiguous → ask again.

The list of writes that require approval (recheck before running):

- `cliffsec start`, `stop`, `restart`, `update`
- `cliffsec config set ...`
- `xattr ...` or any other shell command that mutates the system
- Re-running the installer

**Never** propose `cliffsec uninstall` as a remedy — that removes data and config. Only run it if the user explicitly asks to uninstall.

If the user declines, ask if they'd like to file an issue (Phase E) instead.

## D. Verify

After running the approved fix, re-verify before declaring success:

```bash
cliffsec doctor --json
cliffsec status   # if the fix involved start/restart
```

- Doctor clean and `status` ready → tell the user "fixed: <one line>" and stop.
- Doctor still failing on the same check → the fix didn't take. **Don't loop.** Go to Phase E.
- A new check is failing → **don't chain another guess.** Go to Phase E.

## E. Escalate — file a GitHub issue

Engage when: the table didn't match, the fix didn't work, doctor flagged something the table marks as a bug, or logs show a traceback.

Tell the user:

> "I can't fix this from here — it looks like a real bug in Cliff. Want me to draft a GitHub issue against `cliff-security/cliff` with the diagnostic context I collected? It'll open in your browser pre-filled, so you can review and edit before submitting."

If yes, build a single `gh` command that opens the GitHub compose page in the browser with the body pre-filled. **Always use `--web`.** Never auto-submit.

```bash
gh issue create --repo cliff-security/cliff --web \
  --title "[CLI] <one-line summary>" \
  --body "$(cat <<'EOF'
## What happened
<one-line summary of what the user was trying to do and what went wrong>

## Steps to reproduce
1. <command that failed>
2. <expected vs. actual>

## Environment
- Cliff CLI version: <cliffsec --version>
- Latest release: <cliffsec update --check result>
- OS: <uname -a>

## Doctor output
\`\`\`json
<cliffsec doctor --json output>
\`\`\`

## Recent daemon logs (last 100 lines, secrets redacted)
\`\`\`
<cliffsec logs --lines 100, with redaction applied>
\`\`\`

## What was already tried
- <each fix that was attempted in Phase C, with its outcome>

---
_Filed via Claude Code (`cliff-security` skill) — please add anything I missed before submitting._
EOF
)"
```

### Redaction — non-negotiable

Before pasting logs or doctor output into the body, scrub these patterns (replace value with `[REDACTED]`):

- Lines containing `KEY=`, `TOKEN=`, `SECRET=`, `PASSWORD=`, `Authorization:`, `Bearer `, `_TOKEN`, `_KEY`, `api_key`, `apikey`
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `CLIFF_CREDENTIAL_KEY` (these are in `~/.cliff/config/cliff.env`)
- Anything that looks like a JWT (`eyJ...`), a GitHub PAT (`ghp_...`, `gho_...`, `github_pat_...`), or a generic 40+ char hex string after `=`

If any line is ambiguous (might or might not be a secret), redact it. Better to over-redact than to leak. **Show the user the body as it will be submitted before running the `gh` command**, and offer to remove anything else they don't want public.

## Token discipline

- Don't dump the full doctor JSON to the chat — extract the failing checks only.
- Don't paste 100 log lines to the chat — extract the relevant traceback / error window only. The full logs go in the issue body, not the chat.
- Don't run all the Phase A commands again between attempts — once at the top is enough. If you re-run anything, only re-run the specific check you fixed (e.g. just `cliffsec doctor --json` after a restart).

## What NOT to do

- Don't try the same proposed fix twice. If it didn't take, escalate.
- Don't chain three unrelated fixes ("let me also try restarting") in one turn. One diagnosis, one fix, one verify.
- Don't propose deleting `~/.cliff/data/cliff.db`. Period. It contains the user's findings, workspaces, and audit log.
- Don't offer to edit the user's shell rc to fix a PATH problem.
