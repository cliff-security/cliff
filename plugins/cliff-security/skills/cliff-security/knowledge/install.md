---
name: "install"
description: "Install or reinstall the Cliff daemon + `cliffsec` CLI on the user's machine."
version: "0.2.0"
---

# Install

Engage when:

- The user asks to "install Cliff", "set up Cliff", "get started".
- `cliffsec` is not on PATH (`command not found`).
- `cliffsec status` exits 3 (daemon unreachable) **and** there is no PID file at `~/.cliff/run/cliff.pid` (i.e. Cliff was never installed, not just stopped — for "Cliff was installed but crashed", route to `troubleshooting.md`).
- The user is on a fresh machine and the `cliffsec status` preflight in `secure-repo.md` failed at the very first step.

## Hard rules recap (from SKILL.md)

- Re-running the installer is a write action. Get explicit "yes" before running `curl … | sh`.
- Don't silence exit 4 anywhere downstream — if `cliffsec --version` reports a mismatch after install, the install didn't take; surface it.

## The install flow

### 1. Inspect the canonical one-liner from the pinned README

The README in `cliff-security/cliff` is the single source of truth for the install snippet. **Fetch it from an immutable ref — a released tag — never from `main`.** `main` is mutable, and the install snippet is later piped to a shell; pinning to a tag closes the TOCTOU window between "Claude reads the README" and "the user runs the install command".

This playbook is pinned to Cliff release **`v0.2.0`** (the latest released tag at the time this skill version was cut). Extract the snippet from that tag — for context only, not for direct execution:

```bash
CLIFF_REF="v0.2.0"
curl -fsSL "https://raw.githubusercontent.com/cliff-security/cliff/${CLIFF_REF}/README.md" \
  | awk '/<!-- install:start -->/{f=1;next}/<!-- install:end -->/{f=0}f'
```

The README snippet itself uses `/releases/latest/download/install-local.sh` and lets `CLIFF_VERSION` default to `latest`. **You will not run it verbatim** — the README is written for end users who want the bleeding edge; this skill is pinned to a tested release and must install exactly that release.

### 2. Run the pinned installer

Show the user this **pinned** install command (not the README's `latest`-redirect version):

```bash
CLIFF_REF="v0.2.0"
curl -fsSL "https://github.com/cliff-security/cliff/releases/download/${CLIFF_REF}/install-local.sh" \
  | CLIFF_VERSION="${CLIFF_REF}" sh
```

Both the install script URL and the `CLIFF_VERSION` env var are pinned to `v0.2.0`, so the binary the user ends up with matches what this skill was tested against — no silent drift to a later release.

Then say:

> "This will install Cliff `v0.2.0` (the version this skill was tested against). Both the install script and the binary it installs are pinned to tag `v0.2.0`. May I run it?"

Wait for an explicit "yes" / "go" / "do it". Only after approval, run the pinned command via Bash. The installer:

- Downloads the **`v0.2.0`** release tarball (pinned via `CLIFF_VERSION` above; the installer respects this env var).
- Creates `~/.cliff/` (config, data, run, logs, cli-venv, bin).
- Installs the `cliffsec` console-script into `~/.cliff/cli-venv/bin/` and symlinks it to `~/.local/bin/cliffsec`.
- Installs `opencode` and the scanner binaries (semgrep, trivy) under `~/.cliff/bin/`.
- Generates an encryption key (`CLIFF_CREDENTIAL_KEY`) and persists it in `~/.cliff/config/cliff.env`.

If the installer exits non-zero, **stop**. Surface the last 20 lines of its output to the user and route them to `troubleshooting.md` — don't keep retrying.

If the user wants a newer Cliff release than this skill is pinned to, ask them to (a) update the skill (`/plugin install cliff-security@cliff` re-pulls the latest), or (b) set `CLIFF_REF` to a newer tag explicitly — but flag that the skill hasn't been tested against newer releases, and a new tag may have moved release-asset names or install-snippet markers.

### 3. Verify the install came up

After the installer returns, run:

```bash
cliffsec --version
cliffsec doctor --json
cliffsec status
```

- `cliffsec --version` should print the version the installer advertised.
- `cliffsec doctor --json` should have empty `failing` (warnings are OK).
- `cliffsec status` should exit 0 (it's fine if `ready: false` at this point — that's the cue for onboarding).

If `cliffsec` is on disk but `~/.local/bin` isn't on PATH, the installer's last line will have printed a PATH-export snippet. Show it to the user and have them paste it into their shell rc — don't edit the rc on their behalf without an explicit ask.

### 4. Decide what's next

After verify:

- `cliffsec status` exit 0 + `ready: true` → install is complete and onboarding is already done (env-sourced provider key + a pre-existing GitHub Integration). Hand off to `secure-repo.md`.
- `cliffsec status` exit 0 + `ready: false` → install is complete but credentials are missing. Hand off to `onboarding.md`.
- Anything else → `troubleshooting.md`.

Tell the user explicitly which playbook you're moving to, e.g.: "Install complete. Cliff isn't fully configured yet — moving to onboarding to set up your GitHub PAT and AI provider key."

## What NOT to do

- Don't run the installer twice "to be safe" — it's idempotent but each run rewrites the venv + symlinks. One approved run is enough.
- Don't hardcode the install URL. Always re-extract from the README — the release-asset names have changed before (e.g. the `cliff-cli.tar.gz` → `cliffsec-cli.tar.gz` rename in v0.2.1) and a stale URL silently breaks the install.
- Don't `sudo` the installer. It writes to `$HOME`, not system paths.
- Don't edit the user's shell rc for them.
- Don't suggest `pipx install cliffsec` — Cliff isn't on PyPI yet, the installer is the only supported path.

## Token discipline

- Show the install snippet once. Don't repeat it across messages.
- Don't dump the full installer log unless something failed; just confirm it exited 0.
