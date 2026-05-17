"""Auto-mark and gate docker install smoke tests.

These tests boot the published Cliff image, so they require:
  1. A docker daemon reachable from the test runner.
  2. The image to be available locally (set via CLIFF_TEST_IMAGE,
     default `cliff:dev`).

Both gates skip the tests rather than failing them, so the suite stays
green on machines without Docker.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest


def _docker_daemon_reachable() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _image_present(ref: str) -> bool:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", ref],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


_TEST_IMAGE = os.environ.get("CLIFF_TEST_IMAGE", "cliff:dev")
_daemon_ok = _docker_daemon_reachable()
_image_ok = _daemon_ok and _image_present(_TEST_IMAGE)

_skip_no_daemon = pytest.mark.skipif(
    not _daemon_ok,
    reason="Docker daemon not reachable",
)
_skip_no_image = pytest.mark.skipif(
    not _image_ok,
    reason=(
        f"Cliff image '{_TEST_IMAGE}' not found locally. "
        "Build it first (`docker build -f docker/Dockerfile -t cliff:dev .`) "
        "or set CLIFF_TEST_IMAGE to an existing image."
    ),
)


def pytest_collection_modifyitems(items):
    for item in items:
        if "/tests/docker/" in str(item.fspath):
            item.add_marker(pytest.mark.docker)
            item.add_marker(_skip_no_daemon)
            item.add_marker(_skip_no_image)
