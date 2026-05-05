# Install OpenSec — Docker

> **Looking for the native installer?** macOS and Linux users should prefer
> [docs/guides/install-local.md](guides/install-local.md) — no Docker
> required, runs as a single uvicorn process, ~2 minute first-run UX.
> This page documents the Docker path, which stays available as the
> alternative (and the only path on Windows).

OpenSec ships as a single, signed Docker image published to the GitHub
Container Registry. The image runs as the non-root user `opensec`
(UID 10001) and is multi-arch (`linux/amd64` and `linux/arm64`).

## Prerequisites

- Docker 24+ with the Docker Compose v2 plugin
- An LLM API key — `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
- (Optional) [`cosign`](https://github.com/sigstore/cosign) and
  [`gh`](https://cli.github.com/) for verifying the image — see
  [verify-release.md](verify-release.md)

Tested on:

- Linux (Ubuntu 22.04 / 24.04, Fedora 40, Debian 12)
- macOS 13+ with Docker Desktop (Apple Silicon and Intel)
- Windows 11 with WSL2 + Docker Desktop

## Quick install (recommended)

```bash
curl -fsSL https://github.com/galanko/OpenSec/releases/latest/download/install.sh | sh
```

This script:

1. Verifies Docker + Compose v2 are available and running.
2. Creates `~/opensec/` (override with `OPENSEC_HOME=...`).
3. Downloads the release `docker-compose.yml`.
4. Writes a `.env` with a freshly generated `OPENSEC_CREDENTIAL_KEY`.
5. Prompts for your `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY`).
6. Runs `docker compose up -d` and polls `/health` until ready.

Re-running the installer pulls the latest image, leaves your `.env` and
data volume intact, and recreates the container.

For unattended installs (CI, container provisioning):

```bash
curl -fsSL https://github.com/galanko/OpenSec/releases/latest/download/install.sh \
  | OPENSEC_NON_INTERACTIVE=1 ANTHROPIC_API_KEY=sk-ant-... sh
```

## Manual install — Docker Compose

If you prefer the explicit path (or want to read every byte before you
run it):

```bash
mkdir -p ~/opensec && cd ~/opensec

# Pin to a specific release; check the latest tag at
# https://github.com/galanko/OpenSec/releases
VERSION=0.1.0-alpha
curl -fsSL "https://github.com/galanko/OpenSec/releases/download/v${VERSION}/docker-compose.yml" \
  -o docker-compose.yml

# Generate a credential vault key (used for storing integration secrets)
echo "OPENSEC_CREDENTIAL_KEY=$(openssl rand -base64 32)" > .env
echo "ANTHROPIC_API_KEY=sk-ant-..."                       >> .env
echo "OPENSEC_VERSION=${VERSION}"                         >> .env

docker compose up -d
```

Then open <http://localhost:8000>.

## Manual install — `docker run`

```bash
docker run --rm -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e OPENSEC_CREDENTIAL_KEY="$(openssl rand -base64 32)" \
  -v opensec-data:/data \
  ghcr.io/galanko/opensec:latest
```

> **For production deployments, pin the image by digest, not tag.** Tag
> contents can change in principle (we never republish a released tag,
> but you should not have to trust that). Find the digest under the
> [release page](https://github.com/galanko/OpenSec/releases), or run:
>
> ```bash
> docker buildx imagetools inspect ghcr.io/galanko/opensec:0.1.0-alpha
> ```
>
> then use:
>
> ```bash
> docker run ... ghcr.io/galanko/opensec@sha256:<digest>
> ```

## Configuration

Create a `.env` file next to `docker-compose.yml`. The compose file picks
the values up automatically.

| Environment variable        | Required | Default | What it does                                                  |
|-----------------------------|----------|---------|---------------------------------------------------------------|
| `ANTHROPIC_API_KEY`         | one of   | —       | Claude API key.                                                |
| `OPENAI_API_KEY`            | these    | —       | OpenAI API key.                                                |
| `OPENSEC_VERSION`           | no       | `latest`| Image tag the compose file pulls (e.g. `0.1.0-alpha`).         |
| `OPENSEC_APP_PORT`          | no       | `8000`  | Host port mapped to the container's `8000`.                    |
| `OPENSEC_DATA_DIR`          | no       | `/data` | Where SQLite + workspace state live (inside the container).   |
| `OPENSEC_CREDENTIAL_KEY`    | no       | —       | Base64-encoded 32-byte AES key for the integration vault.      |
| `OPENSEC_DEMO`              | no       | `false` | Auto-seeds demo findings on first run.                         |

### Generating `OPENSEC_CREDENTIAL_KEY`

The vault uses an AES-256 key. Any 32 random bytes, base64-encoded:

```bash
# openssl (preinstalled on macOS, most Linux)
openssl rand -base64 32

# or with Python
python3 -c 'import os, base64; print(base64.b64encode(os.urandom(32)).decode())'
```

Without the key set, the credential vault stays read-only — you can use
OpenSec, but you can't store integration credentials.

## Persisting data

The compose file uses a named Docker volume (`opensec-data`) by default.
That's the simplest, most portable option and survives container
restarts and image upgrades.

If you want a host bind-mount instead (so files live in a known directory
on disk), make sure the host path is owned by UID 10001:

```bash
mkdir -p /srv/opensec-data
sudo chown -R 10001:10001 /srv/opensec-data
docker run ... -v /srv/opensec-data:/data ghcr.io/galanko/opensec:latest
```

## Platform notes

### Linux

- **SELinux (Fedora, RHEL, CentOS Stream):** add `:Z` to your bind-mount
  flag so the container can read/write — `-v /srv/opensec-data:/data:Z`.
- **Rootless Docker / Podman:** the image runs as UID 10001 inside the
  container; in rootless setups, host file ownership maps via subuid.
  The simplest path is to keep using a named volume and let the runtime
  handle it.
- **Adding your user to the `docker` group** removes the need for `sudo`:
  `sudo usermod -aG docker $USER` then log out and back in.

### macOS Docker Desktop

- Allocate **at least 4 GB RAM** to Docker Desktop (Settings → Resources).
  OpenCode + the FastAPI app + Trivy can spike under load.
- For host bind-mounts, the path must be inside an enabled "File sharing"
  directory (Settings → Resources → File sharing).
- Apple Silicon Macs pull the `linux/arm64` image automatically; no
  emulation required.

### Windows (WSL2)

- Run the installer **from inside your WSL2 distro**, not PowerShell:
  ```bash
  curl -fsSL https://github.com/galanko/OpenSec/releases/latest/download/install.sh | sh
  ```
- Make sure Docker Desktop's WSL integration is enabled for your distro
  (Docker Desktop → Settings → Resources → WSL integration).
- File paths: keep `OPENSEC_HOME` inside WSL (`~/opensec`) rather than
  `/mnt/c/...`. Bind-mounts crossing the Windows/WSL boundary are slow.

## Upgrading

The recommended path: re-run the installer.

```bash
curl -fsSL https://github.com/galanko/OpenSec/releases/latest/download/install.sh | sh
```

It pulls the new image and recreates the container. Your `.env` and
data volume are preserved.

Manually:

```bash
cd ~/opensec
docker compose pull
docker compose up -d
```

### Migrating from pre-alpha root-owned volumes

Earlier dev builds ran as root and left `/data` owned by `root:root`.
Migrate the volume in place once:

```bash
docker run --rm --user 0 -v opensec-data:/data alpine \
  chown -R 10001:10001 /data
```

## Verifying the image

The image is signed via Sigstore keyless OIDC and carries SLSA build
provenance + CycloneDX SBOM attestations. See
[verify-release.md](verify-release.md) for copy-paste commands.

## Troubleshooting

- **`docker compose: 'compose' is not a docker command`** — you have
  the legacy `docker-compose` binary, not the v2 plugin. Install
  `docker-compose-plugin` (Linux) or update Docker Desktop.
- **Container exits with `refusing to run as root`** — the entrypoint
  refuses UID 0 by design. Drop the `--user 0` flag. To migrate an
  old root-owned data volume, see "Upgrading" above.
- **`/health` never reaches 200** — supervisord boots uvicorn within
  ~5s and OpenCode within ~10s. If it doesn't, check
  `docker compose logs`. Most often the cause is a missing LLM API
  key (the app starts in degraded mode but `/health` still responds
  200 — if that's not happening, file an issue).
- **Port 8000 already in use** — set `OPENSEC_APP_PORT=8001` in
  `.env`, then `docker compose up -d` again.
- **SBOM scanner says the image references unknown components** — the
  CycloneDX SBOM lives at `ghcr.io/galanko/opensec:sha256-<digest>.sbom`
  via Sigstore. Most modern scanners pick it up automatically; if yours
  doesn't, download the SBOM from the GitHub release page.
