# =============================================================================
# OpenSec — Multi-stage Docker build
# Stage 1: Build frontend (Node)
# Stage 2: Production runtime (Python + OpenCode Go binary)
# =============================================================================

# Build-time args propagated through both stages so the resulting image
# can advertise its provenance via OCI labels.
ARG OPENSEC_VERSION=dev
ARG OPENSEC_REVISION=unknown
ARG OPENSEC_CREATED=unknown

# ---------------------------------------------------------------------------
# Stage 1: Frontend build
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend-builder

ARG OPENSEC_VERSION
ENV VITE_APP_VERSION=${OPENSEC_VERSION}

WORKDIR /build/frontend

# Install dependencies first (cache layer)
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts

# Copy frontend source and build
COPY frontend/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# Stage 2: Production runtime
# ---------------------------------------------------------------------------
FROM python:3.14-slim AS runtime

ARG OPENSEC_VERSION
ARG OPENSEC_REVISION
ARG OPENSEC_CREATED

# OCI image labels — populated by the release workflow at build time.
LABEL org.opencontainers.image.title="OpenSec" \
      org.opencontainers.image.description="Self-hosted cybersecurity remediation copilot" \
      org.opencontainers.image.source="https://github.com/galanko/OpenSec" \
      org.opencontainers.image.url="https://github.com/galanko/OpenSec" \
      org.opencontainers.image.documentation="https://github.com/galanko/OpenSec/blob/main/README.md" \
      org.opencontainers.image.vendor="galanko" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.version="${OPENSEC_VERSION}" \
      org.opencontainers.image.revision="${OPENSEC_REVISION}" \
      org.opencontainers.image.created="${OPENSEC_CREATED}"

# System dependencies: supervisor, curl, git for health checks, cloning, and OpenCode download
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        supervisor \
        curl \
        git \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# GitHub CLI — needed for PR creation by remediation agent
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends gh && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast Python dependency management
RUN pip install --no-cache-dir uv

# Create non-root runtime user. UID 10001 is fixed so bind-mount ownership
# is predictable across hosts.
RUN groupadd --system --gid 10001 opensec \
    && useradd --system --uid 10001 --gid 10001 \
        --home-dir /home/opensec --create-home \
        --shell /usr/sbin/nologin \
        opensec \
    && mkdir -p /data /app/bin /tmp/supervisor \
    && chown -R opensec:opensec /data /tmp/supervisor /home/opensec

WORKDIR /app

# Copy version file first (read at runtime; also referenced by install script)
COPY VERSION /app/VERSION
COPY .opencode-version ./

# Copy and run OpenCode install script (non-fatal if download fails)
COPY scripts/install-opencode.sh ./scripts/
ENV OPENSEC_BIN_DIR=/app/bin
RUN bash scripts/install-opencode.sh || echo "WARNING: OpenCode download failed — engine will be unavailable"

# PRD-0003 v0.2 — Trivy + Semgrep binaries for the assessment engine
# (ADR-0028 subprocess-only execution). Both land in /app/bin alongside
# OpenCode; OPENSEC_SCANNER_BIN_DIR points the runner at this directory.
ARG TRIVY_VERSION=0.70.0
RUN ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in \
        amd64) TRIVY_ARCH="64bit" ;; \
        arm64) TRIVY_ARCH="ARM64" ;; \
        *) echo "unsupported arch: $ARCH" && exit 1 ;; \
       esac \
    && curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz" \
         -o /tmp/trivy.tar.gz \
    && tar -xzf /tmp/trivy.tar.gz -C /app/bin trivy \
    && rm /tmp/trivy.tar.gz \
    && chmod +x /app/bin/trivy \
    && /app/bin/trivy --version
RUN pip install --no-cache-dir semgrep==1.70.0 \
    && ln -sf "$(which semgrep)" /app/bin/semgrep \
    && /app/bin/semgrep --version

# Install Python dependencies (cache layer)
COPY backend/pyproject.toml backend/uv.lock* ./backend/
RUN cd backend && uv sync --frozen --no-dev --no-install-project

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend from stage 1
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

# Copy OpenCode project config and agent definitions
COPY opencode.json ./
COPY .opencode/ ./.opencode/

# Copy supervisor and entrypoint configs
COPY docker/supervisord.conf /etc/supervisor/conf.d/opensec.conf
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Hand /app and the binaries directory to the runtime user. Done after all
# COPY/RUN steps so we don't have to re-chown on every layer.
RUN chown -R opensec:opensec /app

# ---------------------------------------------------------------------------
# Environment defaults
# ---------------------------------------------------------------------------
ENV OPENSEC_APP_HOST=0.0.0.0 \
    OPENSEC_APP_PORT=8000 \
    OPENSEC_OPENCODE_HOST=127.0.0.1 \
    OPENSEC_OPENCODE_PORT=4096 \
    OPENSEC_OPENCODE_BIN=/app/bin/opencode \
    OPENSEC_SCANNER_BIN_DIR=/app/bin \
    OPENSEC_DATA_DIR=/data \
    HOME=/home/opensec

# Persistent data volume
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Drop privileges. The entrypoint refuses to run as root.
USER opensec

ENTRYPOINT ["/app/entrypoint.sh"]
