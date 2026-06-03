# =============================================================================
# Cliff — Multi-stage Docker build
# Stage 1: Build frontend (Node)
# Stage 2: Production runtime (Python)
# =============================================================================

# Build-time args propagated through both stages so the resulting image
# can advertise its provenance via OCI labels.
ARG CLIFF_VERSION=dev
ARG CLIFF_REVISION=unknown
ARG CLIFF_CREATED=unknown

# ---------------------------------------------------------------------------
# Stage 1: Frontend build
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend-builder

ARG CLIFF_VERSION
ENV VITE_APP_VERSION=${CLIFF_VERSION}

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
FROM python:3.11-slim AS runtime

ARG CLIFF_VERSION
ARG CLIFF_REVISION
ARG CLIFF_CREATED

# OCI image labels — populated by the release workflow at build time.
LABEL org.opencontainers.image.title="Cliff" \
      org.opencontainers.image.description="Self-hosted cybersecurity remediation copilot" \
      org.opencontainers.image.source="https://github.com/cliff-security/cliff" \
      org.opencontainers.image.url="https://github.com/cliff-security/cliff" \
      org.opencontainers.image.documentation="https://github.com/cliff-security/cliff/blob/main/README.md" \
      org.opencontainers.image.vendor="cliff-security" \
      org.opencontainers.image.licenses="AGPL-3.0-only" \
      org.opencontainers.image.version="${CLIFF_VERSION}" \
      org.opencontainers.image.revision="${CLIFF_REVISION}" \
      org.opencontainers.image.created="${CLIFF_CREATED}"

# System dependencies: supervisor, curl, git for health checks and cloning
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
RUN groupadd --system --gid 10001 cliff \
    && useradd --system --uid 10001 --gid 10001 \
        --home-dir /home/cliff --create-home \
        --shell /usr/sbin/nologin \
        cliff \
    && mkdir -p /data /app/bin /tmp/supervisor \
    && chown -R cliff:cliff /data /tmp/supervisor /home/cliff

WORKDIR /app

# Copy version file first (read at runtime).
COPY VERSION /app/VERSION

# Ship the AGPL-3.0 LICENSE plus the NOTICE and third-party license
# inventory inside the image so that distribution carries the required
# attribution forward (AGPL §5(a); Apache-2.0 §4(d) for bundled scanners).
COPY LICENSE /app/LICENSE
COPY NOTICE /app/NOTICE
COPY THIRD-PARTY-LICENSES.md /app/THIRD-PARTY-LICENSES.md

ENV CLIFF_BIN_DIR=/app/bin

# PRD-0003 v0.2 — Trivy + Semgrep binaries for the assessment engine
# (ADR-0028 subprocess-only execution). Both land in /app/bin;
# CLIFF_SCANNER_BIN_DIR points the runner at this directory.
ARG TRIVY_VERSION=0.70.0
RUN ARCH="$(dpkg --print-architecture)" \
    && case "$ARCH" in \
        amd64) TRIVY_ARCH="64bit" ;; \
        arm64) TRIVY_ARCH="ARM64" ;; \
        *) echo "unsupported arch: $ARCH" && exit 1 ;; \
       esac \
    && curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz" \
         -o /tmp/trivy.tar.gz \
    && tar -xzf /tmp/trivy.tar.gz -C /app/bin trivy LICENSE \
    && mv /app/bin/LICENSE /app/bin/trivy.LICENSE \
    && rm /tmp/trivy.tar.gz \
    && chmod +x /app/bin/trivy \
    && /app/bin/trivy --version
ARG SEMGREP_VERSION=1.70.0
# Source the semgrep LICENSE from the GitHub repo at the matching
# version tag rather than from the installed wheel. The wheel-based
# lookup that used to live here (``importlib.metadata.distribution
# ('semgrep').files``) broke on linux/arm64 because pip picks the
# arch-specific ``musllinux_1_0_aarch64.manylinux2014_aarch64`` wheel
# there, and *that* wheel ships without any LICENSE in its dist-info —
# only the universal ``-none-any`` wheel used on linux/amd64 carried
# one. So no wheel-side lookup (RECORD-based or filesystem-based) can
# satisfy both arches. Fetching from
# ``raw.githubusercontent.com/semgrep/semgrep/v${SEMGREP_VERSION}``
# gives the same LICENSE on every platform and matches the pattern
# already used for the Trivy LICENSE above. Refs: v0.2.0 release run
# #26056147494, arm64 step 15/25.
RUN pip install --no-cache-dir "semgrep==${SEMGREP_VERSION}" \
    && ln -sf "$(which semgrep)" /app/bin/semgrep \
    && curl -fsSL "https://raw.githubusercontent.com/semgrep/semgrep/v${SEMGREP_VERSION}/LICENSE" \
         -o /app/bin/semgrep.LICENSE \
    && test -s /app/bin/semgrep.LICENSE \
    && /app/bin/semgrep --version

# Install Python dependencies (cache layer)
COPY backend/pyproject.toml backend/uv.lock* ./backend/
RUN cd backend && uv sync --frozen --no-dev --no-install-project

# Copy backend source
COPY backend/ ./backend/

# Copy built frontend from stage 1
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

# Copy supervisor and entrypoint configs
COPY docker/supervisord.conf /etc/supervisor/conf.d/cliff.conf
COPY docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Hand /app and the binaries directory to the runtime user. Done after all
# COPY/RUN steps so we don't have to re-chown on every layer.
RUN chown -R cliff:cliff /app

# ---------------------------------------------------------------------------
# Environment defaults
# ---------------------------------------------------------------------------
ENV CLIFF_APP_HOST=0.0.0.0 \
    CLIFF_APP_PORT=8000 \
    CLIFF_SCANNER_BIN_DIR=/app/bin \
    CLIFF_DATA_DIR=/data \
    CLIFF_OAUTH_CALLBACK_HOST=0.0.0.0 \
    HOME=/home/cliff

# Persistent data volume
VOLUME ["/data"]

# 8000 is the app; 3000 is the one-shot OpenRouter OAuth callback listener
# (only bound while a connect flow is in progress). Publish 3000 only if
# users will run the OAuth onboarding inside the container — otherwise
# the BYOK paths suffice.
EXPOSE 8000 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Drop privileges. The entrypoint refuses to run as root.
USER cliff

ENTRYPOINT ["/app/entrypoint.sh"]
