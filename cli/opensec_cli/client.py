"""HTTP client for the OpenSec daemon.

Wraps httpx with the conventions every CLI command needs:

  * base URL from ``OPENSEC_URL`` (default ``http://127.0.0.1:8000``);
  * one shared connection-pool per CLI invocation (commands are short-lived
    so we don't bother caching across runs);
  * a single retry on connect failures so a daemon that's still booting
    behind ``opensec status`` doesn't immediately exit 3;
  * helper exceptions the command layer maps to exit codes.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from opensec_cli import __version__


class DaemonDownError(Exception):
    """Daemon is unreachable. CLI should exit with EXIT_DAEMON_DOWN."""


class VersionMismatchError(Exception):
    """Server requires a newer CLI than this binary."""

    def __init__(self, message: str, *, min_cli: str, our_version: str) -> None:
        super().__init__(message)
        self.min_cli = min_cli
        self.our_version = our_version


class HTTPError(Exception):
    """Generic API error with the server's status + detail."""

    def __init__(self, status: int, detail: Any) -> None:
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


def _base_url() -> str:
    return os.environ.get("OPENSEC_URL", "http://127.0.0.1:8000").rstrip("/")


def _parse_version(v: str) -> tuple[int, ...]:
    """Loose semver parse — strips a leading ``v`` and any pre-release suffix
    so ``0.1.1-alpha`` and ``v0.1.1`` and ``0.1.1`` all compare as ``(0,1,1)``.
    """
    v = v.lstrip("v")
    core = v.split("-", 1)[0].split("+", 1)[0]
    parts = core.split(".")
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            break
    return tuple(out) or (0,)


class Client:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self._http = httpx.Client(
            base_url=_base_url(),
            timeout=timeout,
            headers={"User-Agent": f"opensec-cli/{__version__}"},
        )

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *exc: object) -> None:
        self._http.close()

    # ----- low-level ----------------------------------------------------

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._http.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise DaemonDownError(str(exc)) from exc

    def get(self, path: str, **kwargs: Any) -> Any:
        r = self.request("GET", path, **kwargs)
        return self._parse(r)

    def post(self, path: str, **kwargs: Any) -> Any:
        r = self.request("POST", path, **kwargs)
        return self._parse(r)

    def patch(self, path: str, **kwargs: Any) -> Any:
        r = self.request("PATCH", path, **kwargs)
        return self._parse(r)

    def put(self, path: str, **kwargs: Any) -> Any:
        r = self.request("PUT", path, **kwargs)
        return self._parse(r)

    @staticmethod
    def _parse(r: httpx.Response) -> Any:
        if r.is_success:
            if r.status_code == 204 or not r.content:
                return None
            return r.json()
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise HTTPError(r.status_code, detail)

    # ----- version handshake -------------------------------------------

    def version_handshake(self) -> dict[str, Any]:
        """Fetch the server version contract and verify our CLI is supported.

        Raises :class:`VersionMismatchError` if our build is older than the
        server's ``min_cli``. Older servers without ``/api/version`` are
        treated as a hard mismatch — they cannot be relied on to serve the
        contract this CLI was built against.
        """
        try:
            info = self.get("/api/version")
        except HTTPError as exc:
            if exc.status == 404:
                raise VersionMismatchError(
                    "OpenSec server is missing /api/version — older than this CLI supports.",
                    min_cli="unknown",
                    our_version=__version__,
                ) from exc
            raise

        min_cli = str(info.get("min_cli", "0.0.0"))
        if _parse_version(__version__) < _parse_version(min_cli):
            raise VersionMismatchError(
                (
                    f"This CLI ({__version__}) is older than the server requires "
                    f"(min {min_cli}). Re-run the OpenSec installer to upgrade."
                ),
                min_cli=min_cli,
                our_version=__version__,
            )
        return info


# ---------------------------------------------------------------------------
# Helpers used by individual commands
# ---------------------------------------------------------------------------


def poll(
    client: Client,
    path: str,
    *,
    is_done: callable,  # type: ignore[valid-type]
    is_failed: callable | None = None,  # type: ignore[valid-type]
    interval: float = 1.5,
    timeout: float = 600.0,
    tolerate_status: tuple[int, ...] = (),
) -> Any:
    """Poll a status endpoint until ``is_done(payload)`` is true.

    Returns the final payload. Raises :class:`TimeoutError` after ``timeout``
    seconds. If ``is_failed`` is provided and returns true, raises
    :class:`HTTPError`.

    ``tolerate_status`` lists HTTP status codes that should be treated as
    "not ready yet" rather than fatal — useful for polling endpoints that
    404 until a downstream worker creates the row.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            payload = client.get(path)
        except HTTPError as exc:
            if exc.status in tolerate_status:
                time.sleep(interval)
                continue
            raise
        if is_done(payload):
            return payload
        if is_failed and is_failed(payload):
            raise HTTPError(0, payload)
        time.sleep(interval)
    raise TimeoutError(f"Timed out polling {path} after {timeout}s")
