# Native install (macOS + Linux)

The native installer is the recommended path for new users. No Docker, no
sudo, no system Python required. Docker stays available as the secondary
path — see [docs/install.md](../install.md) for that.

## TL;DR

```bash
curl -fsSL https://github.com/galanko/OpenSec/releases/latest/download/install-local.sh | sh
opensec start --detach
```

Open http://127.0.0.1:8000 and paste your Anthropic or OpenAI key in
Settings. That's it.

## Prerequisites

- macOS 13+ (Intel or Apple Silicon), or **glibc** Linux. Alpine/musl is not
  supported — use Docker instead.

  Continuously tested in CI on every push: macOS, Ubuntu 22.04, Ubuntu 24.04,
  Debian 12, Fedora latest, Rocky Linux 9, and Arch.
- `git`, `curl`, and the GitHub CLI `gh` on `PATH`. The remediation agents
  shell out to `gh pr create`, so it is a hard requirement, not optional.
  - macOS: `brew install gh`
  - Debian/Ubuntu: see [install instructions](https://github.com/cli/cli/blob/trunk/docs/install_linux.md)
  - Fedora/RHEL: `sudo dnf install gh`

The installer handles everything else automatically: it downloads `uv`,
installs a managed Python 3.11, downloads the pinned OpenCode binary, and
installs Trivy + Semgrep into `~/.opensec/bin/`.

## What gets installed where

```
~/.opensec/
  app/                    # backend source + frontend/dist + .venv
  bin/                    # opencode, trivy, semgrep
  data/                   # opensec.db, workspaces/, logs/
  config/opensec.env      # OPENSEC_CREDENTIAL_KEY + your overrides
  cli-venv/               # the `opensec` CLI
~/.local/bin/opensec      # symlink — make sure ~/.local/bin is in your PATH
```

Re-running the installer upgrades `app/`, `bin/`, and `cli-venv/` in place
without touching `data/` or `config/`.

## Daily commands

```bash
opensec start [--detach]   # foreground, or background with pidfile + logs
opensec stop               # SIGTERM (graceful), then SIGKILL after --timeout
opensec restart            # stop + start --detach
opensec status             # health probe + version handshake
opensec logs [-f]          # tail the latest detached log
opensec doctor             # diagnose dependencies, ports, DB, API key
opensec doctor --json      # same, agent-readable
opensec config get|set|edit|path
opensec uninstall [--keep-data]
```

The agent-facing commands (`opensec scan`, `issues`, `fix`, `approve`,
`close`, `model`) target a running daemon and behave the same as in the
Docker install — same JSON envelope, same exit codes.

## First-run troubleshooting

`opensec doctor` is the first thing to try. It checks every dependency
without starting the daemon, so a port conflict or missing `gh` shows up
in seconds.

Common failures:

| `doctor` says                     | Fix                                                                 |
|-----------------------------------|---------------------------------------------------------------------|
| `gh: not found`                   | Install the GitHub CLI (see prereqs above).                         |
| `port.8000: in use`               | Another process holds it. Either stop it, or `opensec start --port 8765`. |
| `port.4096: in use`               | The OpenCode singleton port is taken. Same fix.                     |
| `opencode.quarantine: quarantined`| macOS Gatekeeper blocked the binary. Re-run the installer; v0.1.6+ scripts strip the attribute automatically. |
| `credential_key: missing`         | The vault key wasn't generated. Re-run the installer.               |
| `api_key: not set`                | Open Settings in the web UI and paste your key. (Warn-only.)        |

## Pinning to a specific version

```bash
curl -fsSL https://github.com/galanko/OpenSec/releases/latest/download/install-local.sh \
  | OPENSEC_VERSION=0.1.6 sh
```

## Uninstalling

```bash
opensec stop
opensec uninstall          # removes everything under ~/.opensec/ and the launcher
opensec uninstall --keep-data   # keeps ~/.opensec/data/ and ~/.opensec/config/
```

## Why no `opensec update`?

For v1, the update path is intentionally manual: `opensec stop`, re-run
`install-local.sh`, `opensec start`. The installer is idempotent and
preserves your data. Auto-update with DB-backup-on-upgrade ships in v1.1
once we've seen real schema migrations under user load.

## Internals

- The installer reads pinned versions from `.opencode-version` and
  `.scanner-versions` shipped inside the release tarball. Bumps to either
  ride a normal OpenSec release.
- Backend lives in a uv-managed venv at `~/.opensec/app/backend/.venv/`.
  The CLI lives in a separate venv at `~/.opensec/cli-venv/` so the two
  can be upgraded independently.
- `OPENSEC_HOME` overrides `~/.opensec/` if you need a different prefix.
