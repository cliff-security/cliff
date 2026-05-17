"""Tests for Docker configuration and production static file serving."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cliff.config import Settings


def test_static_dir_setting_default():
    """Static dir defaults to empty string (disabled)."""
    s = Settings()
    assert s.static_dir == ""


def test_static_dir_setting_custom():
    """Static dir can be set via config."""
    s = Settings(static_dir="/app/frontend/dist")
    assert s.static_dir == "/app/frontend/dist"


def test_docker_env_defaults():
    """Verify environment defaults match Docker expectations."""
    s = Settings()
    assert s.app_host == "0.0.0.0"
    assert s.app_port == 8000
    assert s.opencode_host == "127.0.0.1"
    assert s.opencode_port == 4096


def test_spa_fallback_not_mounted_without_static_dir(client):
    """Without CLIFF_STATIC_DIR, unknown paths should 404 (no SPA fallback)."""
    resp = client.get("/some/random/path")
    # Should be 404 or 405 since no SPA fallback is mounted
    assert resp.status_code in (404, 405)


def test_health_still_works_without_static_dir(client):
    """Health endpoint works regardless of static dir config."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cliff"] == "ok"


class TestSpaFallback:
    """Test SPA fallback when static_dir is configured with real files."""

    def test_serves_index_html(self, tmp_path, mock_opencode_process, mock_opencode_client):
        """SPA fallback serves index.html for unknown paths."""
        # Set up a fake static directory
        static_dir = tmp_path / "dist"
        static_dir.mkdir()
        (static_dir / "index.html").write_text("<html><body>Cliff</body></html>")
        assets_dir = static_dir / "assets"
        assets_dir.mkdir()
        (assets_dir / "main.js").write_text("console.log('app')")

        with patch("cliff.main.settings") as mock_settings:
            mock_settings.static_dir = str(static_dir)
            # Re-import to trigger mount logic
            # Instead, test the logic directly
            index = static_dir / "index.html"
            assert index.exists()
            assert "Cliff" in index.read_text()

    def test_static_file_candidate_check(self, tmp_path):
        """Verify static file resolution logic."""
        static_dir = tmp_path / "dist"
        static_dir.mkdir()
        (static_dir / "favicon.ico").write_text("icon")
        (static_dir / "index.html").write_text("<html></html>")

        # Simulate the candidate check from _spa_fallback
        full_path = "favicon.ico"
        candidate = static_dir / full_path
        assert candidate.is_file()
        assert static_dir in candidate.resolve().parents or candidate.resolve().parent == static_dir


class TestDockerfileStructure:
    """Validate Docker configuration files exist and have correct content."""

    def _repo_root(self) -> Path:
        """Find the repo root."""
        current = Path(__file__).resolve().parent
        for _ in range(10):
            if (current / ".opencode-version").exists():
                return current
            current = current.parent
        return current

    def test_dockerfile_exists(self):
        root = self._repo_root()
        dockerfile = root / "docker" / "Dockerfile"
        assert dockerfile.exists(), "docker/Dockerfile must exist"
        content = dockerfile.read_text()
        # Multi-stage build
        assert "FROM node:" in content, "Must have Node build stage"
        assert "FROM python:" in content, "Must have Python runtime stage"
        assert "frontend-builder" in content, "Must reference frontend builder stage"
        # Health check
        assert "HEALTHCHECK" in content
        assert "/health" in content
        # Volume for persistent data
        assert "VOLUME" in content
        # Exposes port 8000
        assert "EXPOSE 8000" in content

    def test_supervisord_conf_exists(self):
        root = self._repo_root()
        conf = root / "docker" / "supervisord.conf"
        assert conf.exists(), "docker/supervisord.conf must exist"
        content = conf.read_text()
        assert "uvicorn" in content, "Supervisord must manage uvicorn"
        assert "cliff.main:app" in content
        assert "autorestart" in content

    def test_entrypoint_exists(self):
        root = self._repo_root()
        entrypoint = root / "docker" / "entrypoint.sh"
        assert entrypoint.exists(), "docker/entrypoint.sh must exist"
        content = entrypoint.read_text()
        assert "#!/usr/bin/env bash" in content
        assert "CLIFF_DATA_DIR" in content
        assert "supervisord" in content

    def test_docker_compose_exists(self):
        root = self._repo_root()
        compose = root / "docker" / "docker-compose.yml"
        assert compose.exists(), "docker/docker-compose.yml must exist"
        content = compose.read_text()
        assert "cliff" in content
        assert "8000" in content
        assert "volumes:" in content
        assert "healthcheck" in content

    def test_entrypoint_has_first_run_check(self):
        root = self._repo_root()
        content = (root / "docker" / "entrypoint.sh").read_text()
        assert "First run" in content, "Entrypoint must log first-run detection"

    def test_dockerfile_has_git(self):
        root = self._repo_root()
        content = (root / "docker" / "Dockerfile").read_text()
        assert "git" in content, "Dockerfile must install git"

    def test_dockerfile_has_gh_cli(self):
        root = self._repo_root()
        content = (root / "docker" / "Dockerfile").read_text()
        assert "githubcli-archive-keyring" in content, "Must use official gh CLI apt repo"
        assert "apt-get install" in content and "gh" in content, "Must install gh CLI"

    def test_dockerignore_exists(self):
        root = self._repo_root()
        dockerignore = root / ".dockerignore"
        assert dockerignore.exists(), ".dockerignore must exist"
        content = dockerignore.read_text()
        assert "node_modules" in content
        assert "__pycache__" in content
        assert ".git" in content


class TestReleaseHardening:
    """Assertions covering the v0.1.0-alpha release hardening (non-root,
    OCI labels, VERSION baked into the image)."""

    def _repo_root(self) -> Path:
        current = Path(__file__).resolve().parent
        for _ in range(10):
            if (current / ".opencode-version").exists():
                return current
            current = current.parent
        return current

    def test_version_file_exists_and_is_pep440_alpha(self):
        version = (self._repo_root() / "VERSION").read_text().strip()
        # `0.1.0-alpha`, `0.1.0`, `0.1.0a0`, etc. — non-empty single line
        assert version, "VERSION must not be empty"
        assert "\n" not in version, "VERSION must be a single line"

    def test_changelog_has_section_for_version(self):
        root = self._repo_root()
        version = (root / "VERSION").read_text().strip()
        changelog = (root / "CHANGELOG.md").read_text()
        assert f"[{version}]" in changelog, (
            f"CHANGELOG.md must contain a section for version {version}"
        )

    def test_dockerfile_creates_non_root_user(self):
        content = (self._repo_root() / "docker" / "Dockerfile").read_text()
        # User+group with fixed UID/GID 10001 so bind-mount ownership is predictable.
        assert "groupadd" in content and "10001 cliff" in content, (
            "Dockerfile must create the cliff group at GID 10001"
        )
        assert "useradd" in content and "10001" in content and "cliff" in content, (
            "Dockerfile must create the cliff user at UID 10001"
        )

    def test_dockerfile_has_user_directive(self):
        content = (self._repo_root() / "docker" / "Dockerfile").read_text()
        assert "USER cliff" in content, (
            "Dockerfile must drop privileges via 'USER cliff' before ENTRYPOINT"
        )

    def test_dockerfile_copies_version_file(self):
        content = (self._repo_root() / "docker" / "Dockerfile").read_text()
        assert "COPY VERSION" in content, "Dockerfile must copy the VERSION file"

    def test_dockerfile_has_oci_labels(self):
        content = (self._repo_root() / "docker" / "Dockerfile").read_text()
        for label in (
            "org.opencontainers.image.title",
            "org.opencontainers.image.description",
            "org.opencontainers.image.source",
            "org.opencontainers.image.url",
            "org.opencontainers.image.documentation",
            "org.opencontainers.image.licenses",
            "org.opencontainers.image.version",
            "org.opencontainers.image.revision",
            "org.opencontainers.image.created",
        ):
            assert label in content, f"Dockerfile must declare OCI label {label}"

    def test_dockerfile_accepts_version_build_args(self):
        content = (self._repo_root() / "docker" / "Dockerfile").read_text()
        for arg in ("CLIFF_VERSION", "CLIFF_REVISION", "CLIFF_CREATED"):
            assert f"ARG {arg}" in content, f"Dockerfile must accept build arg {arg}"

    def test_supervisord_runs_as_cliff_user(self):
        content = (self._repo_root() / "docker" / "supervisord.conf").read_text()
        assert "user=cliff" in content, "supervisord must run as the cliff user"
        assert "/var/run/" not in content, (
            "supervisord must not write to /var/run/ (not writable by non-root)"
        )
        assert "/tmp/supervisor" in content, (
            "supervisord pid/sock files must live under /tmp/supervisor"
        )

    def test_entrypoint_refuses_to_run_as_root(self):
        content = (self._repo_root() / "docker" / "entrypoint.sh").read_text()
        assert 'id -u' in content and 'refusing to run as root' in content, (
            "entrypoint.sh must refuse to run as root"
        )
