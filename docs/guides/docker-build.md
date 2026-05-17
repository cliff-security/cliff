# Docker build guide

> **For end users:** see [docs/install.md](../install.md). The published
> image at `ghcr.io/galanko/cliff` is what you want; this guide is for
> contributors building locally.

Cliff ships as a single multi-stage Docker container that bundles:

- FastAPI backend (Python 3.11)
- Built frontend (Vite static files)
- OpenCode server (Go binary, version pinned via `.opencode-version`)
- Bundled scanners — Trivy (CVE) and Semgrep (SAST)
- SQLite database (on a mounted volume)

Source of truth for the production build: the
[`release.yml`](../../.github/workflows/release.yml) workflow. This
guide covers the local-development build only.

## Local build

From the repo root:

```bash
docker build -f docker/Dockerfile -t cliff:dev .
```

Build args you can override:

| Arg                | Default                  | Used for                          |
|--------------------|--------------------------|-----------------------------------|
| `CLIFF_VERSION`  | `dev`                    | Stamped into `/app/VERSION`       |
| `CLIFF_REVISION` | `dev`                    | OCI label `org.opencontainers.image.revision` |
| `CLIFF_CREATED`  | `1970-01-01T00:00:00Z`   | OCI label `org.opencontainers.image.created`  |

Build single-arch (default — your host's architecture). Multi-arch
builds use `buildx` and QEMU emulation; the production workflow handles
that for you.

## Run a local build

The shipped `docker-compose.yml` pulls from GHCR. To run your local
build instead, drop a `docker-compose.override.yml` next to it:

```yaml
services:
  cliff:
    image: cliff:dev
    build:
      context: ..
      dockerfile: docker/Dockerfile
```

Compose merges overrides automatically:

```bash
cd docker
docker compose up --build
```

## Multi-arch build (advanced)

```bash
docker buildx create --name cliff-builder --use
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/Dockerfile \
  -t cliff:dev-multiarch \
  --load .
```

Note: `--load` only works for single-arch outputs; for multi-arch you
need `--push` to a registry. The release workflow does this against
GHCR automatically — see
[`release.yml`](../../.github/workflows/release.yml).

## Verify the build

```bash
# Image runs as cliff (UID 10001), not root
docker run --rm --entrypoint id cliff:dev -un  # → cliff

# Bundled VERSION matches the build arg
docker run --rm --entrypoint cat cliff:dev /app/VERSION

# Bundled scanners are present
docker run --rm --entrypoint /app/bin/trivy   cliff:dev --version
docker run --rm --entrypoint /usr/local/bin/semgrep cliff:dev --version
```

## Smoke test

The repo ships a Docker boot smoke test that mirrors what runs against
the released image in CI:

```bash
cd backend
CLIFF_TEST_IMAGE=cliff:dev uv run pytest -m docker tests/docker/ -v
```

This boots the image with stub credentials, polls `/health`, and
asserts the app reports `cliff=ok` within 90s. Catches regressions
where the image builds but doesn't start.

## Environment variables

See [docs/install.md](../install.md#configuration) for the full table.
Variables that matter to the build itself (not the runtime) are listed
above under **Build args**.
