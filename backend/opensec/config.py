"""Application configuration via environment variables and defaults."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from pydantic_settings import BaseSettings


def _find_repo_root() -> Path:
    """Walk up from this file to find the repo root (contains .opencode-version)."""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / ".opencode-version").exists():
            return current
        current = current.parent
    return Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    # OpenSec
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # Demo mode — auto-seed sample findings on startup
    demo: bool = False

    # OpenCode engine (singleton)
    opencode_host: str = "127.0.0.1"
    opencode_port: int = 4096
    opencode_bin: str = ""  # Auto-resolved if empty

    # Credential vault
    credential_key: str = ""  # Base64-encoded 32-byte AES key (or set OPENSEC_CREDENTIAL_KEY)

    # Audit logging
    audit_retention_days: int = 90

    # Workspace process pool
    opencode_port_range_start: int = 4100
    opencode_port_range_end: int = 4199
    workspace_idle_timeout_seconds: int = 600

    # Assessment watchdog (migration 015 — failure surfacing). The watchdog
    # ticks every ``interval`` seconds and reaps any pending/running row
    # whose ``started_at`` is older than ``stale_threshold``. Threshold is
    # comfortably above the per-run hard timeout in
    # ``ASSESSMENT_RUN_TIMEOUT_S`` (10 min) so a healthy task always wins
    # the race against the watchdog.
    assessment_watchdog_interval_seconds: int = 60
    assessment_stale_threshold_seconds: int = 900

    # Paths
    repo_root: Path = _find_repo_root()
    data_dir: Path = Path(os.getenv("OPENSEC_DATA_DIR", ""))
    static_dir: str = ""  # Path to built frontend assets (set in Docker)

    # Scanner binaries (PRD-0003 v0.2 / ADR-0028). Trivy + Semgrep are invoked
    # as subprocesses; ``scanner_bin_dir`` points at the directory holding
    # both. Empty defaults to ``<home>/.opensec/bin/`` which the install
    # script populates; override with OPENSEC_SCANNER_BIN_DIR.
    scanner_bin_dir: str = ""

    # Playwright E2E test seam — retired pre-PR-B (the legacy seam targeted
    # the OSV/parser pipeline). Kept as a no-op placeholder so existing env
    # configs don't break loading; a v0.2-shape seam (mocked subprocess
    # transport) lands in a follow-up if/when the Playwright path returns.
    test_fixture_repo_dir: str = ""
    test_fixture_osv_dir: str = ""

    model_config = {"env_prefix": "OPENSEC_"}

    @property
    def opencode_url(self) -> str:
        return f"http://{self.opencode_host}:{self.opencode_port}"

    @property
    def opencode_binary_path(self) -> Path:
        if self.opencode_bin:
            return Path(self.opencode_bin)
        # Check common locations
        home_bin = Path.home() / ".opensec" / "bin" / "opencode"
        if home_bin.exists():
            return home_bin
        # Check PATH
        from shutil import which

        found = which("opencode")
        if found:
            return Path(found)
        return home_bin  # Default install location

    @property
    def opencode_version(self) -> str:
        version_file = self.repo_root / ".opencode-version"
        if version_file.exists():
            return version_file.read_text().strip()
        return "latest"

    @property
    def opensec_version(self) -> str:
        version_file = self.repo_root / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip()
        return "0.0.0"

    @property
    def opencode_model(self) -> str:
        """Read the configured model from opencode.json."""
        config_file = self.repo_root / "opencode.json"
        if config_file.exists():
            try:
                data = json.loads(config_file.read_text())
                return data.get("model", "")
            except (json.JSONDecodeError, OSError):
                pass
        return ""

    def write_opencode_config(self, model: str) -> None:
        """Update the model in opencode.json, preserving other fields."""
        config_file = self.repo_root / "opencode.json"
        data: dict = {}
        if config_file.exists():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                data = json.loads(config_file.read_text())
        data["model"] = model
        config_file.write_text(json.dumps(data, indent=2) + "\n")

    def resolve_data_dir(self) -> Path:
        d = self.data_dir if self.data_dir and str(self.data_dir) else self.repo_root / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def resolve_scanner_bin_dir(self) -> Path:
        """Directory holding the Trivy + Semgrep binaries.

        Defaults to ``<home>/.opensec/bin/`` (the install script's target).
        Override with ``OPENSEC_SCANNER_BIN_DIR``.
        """
        if self.scanner_bin_dir:
            return Path(self.scanner_bin_dir)
        return Path.home() / ".opensec" / "bin"


settings = Settings()
