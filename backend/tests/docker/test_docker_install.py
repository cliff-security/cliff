"""Boot the Cliff Docker image and verify it serves /health.

This is the install-path smoke test. It exists so the release pipeline
catches "the image builds, but doesn't start" regressions before the
artifact is handed to humans.

Scope deliberately small:
  - Boot the container with stub credentials.
  - Wait for /health to return 200.
  - Assert the JSON shape and `cliff == "ok"`.

We do NOT assert `opencode == "ok"` because that requires the model
provider to authenticate against the stub key, which would re-introduce
the very flake we're trying to avoid.
"""

from __future__ import annotations

import base64
import contextlib
import os
import secrets
import time
from typing import TYPE_CHECKING

import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

if TYPE_CHECKING:
    from collections.abc import Iterator

IMAGE = os.environ.get("CLIFF_TEST_IMAGE", "cliff:dev")
HEALTH_TIMEOUT_S = 90  # Dockerfile start_period is 15s; pad for first-boot DB migration.


def _gen_credential_key() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode()


@pytest.fixture(scope="module")
def cliff_container() -> Iterator[DockerContainer]:
    container = (
        DockerContainer(IMAGE)
        .with_env("ANTHROPIC_API_KEY", "sk-ant-stub-for-tests")
        .with_env("CLIFF_CREDENTIAL_KEY", _gen_credential_key())
        .with_env("CLIFF_DATA_DIR", "/data")
        .with_exposed_ports(8000)
    )
    container.start()
    try:
        # supervisord/uvicorn print this once the FastAPI app finishes startup.
        # If it never appears the test will fall through to /health polling
        # and skip on timeout, so this just speeds up the happy path.
        with contextlib.suppress(Exception):
            wait_for_logs(container, "Application startup complete", timeout=60)
        yield container
    finally:
        container.stop()


def _health_url(container: DockerContainer) -> str:
    host = container.get_container_host_ip()
    port = container.get_exposed_port(8000)
    return f"http://{host}:{port}/health"


def test_image_boots_and_health_endpoint_responds(cliff_container: DockerContainer) -> None:
    url = _health_url(cliff_container)
    deadline = time.monotonic() + HEALTH_TIMEOUT_S
    last_error: Exception | None = None
    response: httpx.Response | None = None

    while time.monotonic() < deadline:
        try:
            response = httpx.get(url, timeout=5.0)
            if response.status_code == 200:
                break
        except httpx.HTTPError as exc:
            last_error = exc
        time.sleep(2)

    assert response is not None and response.status_code == 200, (
        f"/health never returned 200 within {HEALTH_TIMEOUT_S}s "
        f"(last error: {last_error!r})"
    )

    body = response.json()
    assert body["cliff"] == "ok", f"expected cliff=ok, got {body!r}"
    assert body["opencode_version"], f"expected non-empty opencode_version, got {body!r}"
    # opencode itself may report 'unavailable' under stub credentials —
    # that's fine. We only care the app shell came up.
    assert body["opencode"] in {"ok", "unavailable"}, body
