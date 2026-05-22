"""Thin async HTTP client for GitHub's three device-flow endpoints (IMPL-0010).

Stateless. The caller supplies the ``client_id`` (public). Base URLs are
overridable so tests use ``httpx.MockTransport`` and don't touch the real
network. The wrapper does **no** retry / backoff — that's the orchestrator's
job (Phase 3).

Reference:
https://docs.github.com/en/apps/creating-github-apps/writing-code-with-the-rest-api/using-the-device-flow-to-generate-a-user-access-token-for-a-github-app
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

import httpx

DEVICE_CODE_PATH = "/login/device/code"
TOKEN_PATH = "/login/oauth/access_token"  # noqa: S105 — URL path, not a credential
USER_PATH = "/user"
REPO_PATH_TEMPLATE = "/repos/{owner}/{repo}"
REPO_INSTALLATION_PATH_TEMPLATE = "/repos/{owner}/{repo}/installation"
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
INSTALL_URL_TEMPLATE = "https://github.com/apps/{slug}/installations/new"


def build_install_url(slug: str, *, state: str | None = None) -> str:
    """The github.com App-install URL for *slug*.

    With *state* it carries the CSRF token the ``/setup`` callback
    validates (the device-flow ``/connect`` contract). Without it, it's
    the plain always-available "install or manage the App" link the
    Settings UI renders (ADR-0048). ``quote(safe="")`` defends both the
    slug (env-supplied) and the state against a stray ``/`` or ``?``.
    """
    base = INSTALL_URL_TEMPLATE.format(slug=quote(slug, safe=""))
    if state is None:
        return base
    return f"{base}?state={quote(state, safe='')}"


class GitHubDeviceFlowError(RuntimeError):
    """Unexpected response from GitHub during the device flow."""


class GitHubDeviceFlowTransientError(GitHubDeviceFlowError):
    """Subset of :class:`GitHubDeviceFlowError` for recoverable failures
    (HTTP 429 / 5xx). The orchestrator retries on next poll tick rather
    than marking the row terminal."""


# Errors the orchestrator should treat as transient — retry on next
# tick rather than marking the row terminal. Defined here next to the
# raising classes so the contract lives in one place; the orchestrator
# just imports and uses the tuple.
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    httpx.TimeoutException,
    httpx.NetworkError,  # superclass of ConnectError, ReadError, WriteError
    httpx.RemoteProtocolError,
    GitHubDeviceFlowTransientError,
)


@dataclass(frozen=True)
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


PollKind = Literal[
    "success",
    "authorization_pending",
    "slow_down",
    "expired_token",
    "access_denied",
]


@dataclass(frozen=True)
class PollTokenResult:
    kind: PollKind
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
    interval: int | None = None  # populated only on slow_down


@dataclass(frozen=True)
class UserInfo:
    login: str
    id: int


# Cap exception/log payloads at this many characters of body text.
# Anything longer than ~200 chars is almost certainly a server error
# page that adds noise without information; verbose echo also lets a
# misbehaving GitHub API surprise us by reflecting our request fields
# (e.g. refresh_token) back into our logs / DB. SR-4 in PR #145 review.
_ERROR_BODY_MAX_CHARS = 200


def _safe_error_summary(resp: httpx.Response) -> str:
    """Build a short, log-safe error summary from a non-2xx response.

    Prefers the standard OAuth error JSON shape (``{"error":"...",
    "error_description":"..."}``) and falls back to a truncated text body.
    Never returns more than ``_ERROR_BODY_MAX_CHARS`` characters.
    """
    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError):
        body = None
    if isinstance(body, dict):
        err = body.get("error") or body.get("message")
        desc = body.get("error_description")
        if err and desc:
            summary = f"{err}: {desc}"
        elif err:
            summary = str(err)
        else:
            summary = ""
        if summary:
            return summary[:_ERROR_BODY_MAX_CHARS]
    text = (resp.text or "").strip()
    return text[:_ERROR_BODY_MAX_CHARS]


class GitHubDeviceFlowClient:
    """Async wrapper around GitHub's device-flow endpoints.

    The transport can be overridden (httpx.MockTransport in tests). When
    ``transport`` is provided, the client owns its own ``AsyncClient`` and
    closes it on ``aclose()``. In production we hand-build an AsyncClient
    on each call so the orchestrator's lifetime isn't tied to ours - the
    flow is short-lived.
    """

    def __init__(
        self,
        *,
        client_id: str,
        api_base_url: str = "https://api.github.com",
        oauth_base_url: str = "https://github.com",
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._client_id = client_id
        self._api_base = api_base_url.rstrip("/")
        self._oauth_base = oauth_base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    def _async_client(self) -> httpx.AsyncClient:
        kwargs: dict = {"timeout": self._timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        return httpx.AsyncClient(**kwargs)

    async def request_device_code(self) -> DeviceCodeResponse:
        """POST /login/device/code — returns the device + user codes."""
        url = f"{self._oauth_base}{DEVICE_CODE_PATH}"
        async with self._async_client() as client:
            resp = await client.post(
                url,
                data={"client_id": self._client_id},
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            raise GitHubDeviceFlowError(
                f"device_code request failed: HTTP {resp.status_code} "
                f"{_safe_error_summary(resp)}"
            )
        body = resp.json()
        try:
            return DeviceCodeResponse(
                device_code=body["device_code"],
                user_code=body["user_code"],
                verification_uri=body["verification_uri"],
                expires_in=int(body["expires_in"]),
                interval=int(body["interval"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubDeviceFlowError(
                f"device_code response missing fields: {body}"
            ) from exc

    async def poll_token(self, *, device_code: str) -> PollTokenResult:
        """POST /login/oauth/access_token — one polling attempt."""
        url = f"{self._oauth_base}{TOKEN_PATH}"
        async with self._async_client() as client:
            resp = await client.post(
                url,
                data={
                    "client_id": self._client_id,
                    "device_code": device_code,
                    "grant_type": DEVICE_CODE_GRANT,
                },
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                raise GitHubDeviceFlowTransientError(
                    f"token poll transient: HTTP {resp.status_code} "
                    f"{_safe_error_summary(resp)}"
                )
            raise GitHubDeviceFlowError(
                f"token poll failed: HTTP {resp.status_code} "
                f"{_safe_error_summary(resp)}"
            )
        body = resp.json()

        if "access_token" in body:
            return PollTokenResult(
                kind="success",
                access_token=body["access_token"],
                refresh_token=body.get("refresh_token"),
                expires_in=body.get("expires_in"),
            )

        error = body.get("error")
        if error == "authorization_pending":
            return PollTokenResult(kind="authorization_pending")
        if error == "slow_down":
            return PollTokenResult(
                kind="slow_down", interval=body.get("interval")
            )
        if error == "expired_token":
            return PollTokenResult(kind="expired_token")
        if error == "access_denied":
            return PollTokenResult(kind="access_denied")
        raise GitHubDeviceFlowError(
            f"unexpected token poll error: {error or body!r}"
        )

    async def refresh_access_token(self, *, refresh_token: str) -> PollTokenResult:
        """POST /login/oauth/access_token with grant_type=refresh_token.

        Returned shape mirrors :meth:`poll_token` so callers can treat
        ``kind=='success'`` uniformly. Anything other than success raises -
        the orchestrator marks the integration ``needs_reconnect`` from
        the exception in Phase 5.
        """
        url = f"{self._oauth_base}{TOKEN_PATH}"
        async with self._async_client() as client:
            resp = await client.post(
                url,
                data={
                    "client_id": self._client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            raise GitHubDeviceFlowError(
                f"refresh failed: HTTP {resp.status_code} "
                f"{_safe_error_summary(resp)}"
            )
        body = resp.json()
        if "access_token" in body:
            return PollTokenResult(
                kind="success",
                access_token=body["access_token"],
                refresh_token=body.get("refresh_token"),
                expires_in=body.get("expires_in"),
            )
        raise GitHubDeviceFlowError(
            f"refresh response missing access_token: {body!r}"
        )

    async def fetch_user(self, *, access_token: str) -> UserInfo:
        """GET /user — used to record the github_login post-connect."""
        url = f"{self._api_base}{USER_PATH}"
        async with self._async_client() as client:
            resp = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if resp.status_code != 200:
            raise GitHubDeviceFlowError(
                f"GET /user failed: HTTP {resp.status_code} "
                f"{_safe_error_summary(resp)}"
            )
        body = resp.json()
        try:
            return UserInfo(login=body["login"], id=int(body["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubDeviceFlowError(
                f"GET /user response missing fields: {body!r}"
            ) from exc


# ---------------------------------------------------------------------------
# Repo push-access preflight (Q01R / B30 / ADR-0037 / IMPL-0014)
#
# A GitHub App user-to-server token carries the INTERSECTION of (App declared
# permissions) and (user repo permissions). If the App only declares
# Contents:read the token cannot push regardless of the user's real perms —
# which is exactly what B30 surfaces: executor "succeeds", produces a local
# branch, can't push, no PR appears.
#
# The fix per ADR-0037 is to (a) update the App to declare Contents:write +
# Pull requests:write on GitHub.com, and (b) preflight every executor run
# with a real GET /repos/{owner}/{repo} call so we fail fast with a useful
# error if the App was misconfigured. This module owns (b).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoPushAccess:
    """Effective push capability of an OAuth user token on a given repo.

    Populated from ``GET /repos/{owner}/{repo}``. The ``permissions.push``
    field on that response reflects the *authenticated principal's*
    effective perms for the repo — which for a user-to-server token is the
    intersection of (App declared perms) and (user repo perms). That's
    precisely the signal B30 needs.
    """

    can_push: bool
    reason: str = ""


# Default timeout for the runtime ``git push --dry-run`` probe
# (Q01R-W3 / IMPL-0019). The caller passes ``probe_timeout_seconds``
# explicitly; this default is used only when the caller doesn't override
# it AND the settings import fails. ``settings.push_probe_timeout_seconds``
# is the operator-facing knob.
_DEFAULT_PROBE_TIMEOUT_SECONDS = 5.0

# Canonical success reason for a probe that returned exit-0. Surfaces in
# the diagnose response body and in the executor preflight's success log
# line so operators can confirm push access was verified at the wire
# (not just inferred from API signals).
_PROBE_REASON_VERIFIED = "verified by runtime probe"

# Short bootstrap timeout: ``git init`` and ``git commit --allow-empty``
# touch only the local filesystem. Anything past a few seconds means
# something is seriously wrong (slow disk, fsync stall) — fail closed
# rather than hang the preflight indefinitely.
_BOOTSTRAP_TIMEOUT_SECONDS = 5.0


# Reason strings for probe failures. Kept as a small constant table so
# (a) tests can grep for the exact bucket without false positives on
# user-perms or install-perms messages, and (b) the strings stay free of
# the token / remote URL / raw stderr. Operators see these in the diagnose
# response body and in the executor's 412 error_details.
_PROBE_REASON_CREDENTIALS = (
    "git push probe failed: credentials rejected. The stored token cannot "
    "push to this repo at the git protocol layer — reconnect GitHub or "
    "update the Cliff GitHub App's installation permissions to declare "
    "Contents:write."
)
_PROBE_REASON_NOT_FOUND = (
    "git push probe failed: repository not found at the git protocol "
    "layer. The Cliff GitHub App may not be installed on this repo, or "
    "the repo was renamed/deleted since the integration was configured."
)
_PROBE_REASON_TIMEOUT = (
    "git push probe failed: timeout after {seconds}s. The network path to "
    "github.com may be slow — raise CLIFF_PUSH_PROBE_TIMEOUT_SECONDS if "
    "this is expected for your environment."
)
_PROBE_REASON_GIT_MISSING = (
    "git push probe failed: git binary not available on this Cliff host."
)
_PROBE_REASON_GENERIC = (
    "git push probe failed: git protocol handshake rejected the token. "
    "Reconnect GitHub or have the org admin approve the App's updated "
    "permissions."
)


def _classify_probe_stderr(stderr: bytes) -> str:
    """Map ``git`` stderr into one of a few well-known reason buckets.

    We never echo raw stderr — it may contain the remote URL with the
    token embedded (``https://x-access-token:<token>@github.com/...``)
    and it certainly contains noise that's useless to a user. Instead we
    classify into a handful of buckets the UI can reason about.
    """
    text = stderr.decode("utf-8", errors="replace").lower()
    if "permission" in text or "403" in text or "denied" in text:
        return _PROBE_REASON_CREDENTIALS
    if (
        "not found" in text
        or "could not read" in text
        or "repository" in text
        or "404" in text
    ):
        return _PROBE_REASON_NOT_FOUND
    return _PROBE_REASON_GENERIC


async def _run_git(
    *args: str,
    cwd: str,
    timeout_seconds: float,
) -> tuple[int | None, bytes, bool]:
    """Spawn ``git <args>`` with ``cwd`` set, wait up to ``timeout_seconds``.

    Returns ``(returncode, stderr, timed_out)``. ``returncode`` is
    ``None`` only when ``timed_out`` is True. ``FileNotFoundError`` on
    spawn (``git`` missing from PATH) is propagated to the caller — the
    probe wants to bucket it as ``git binary not available``.

    Stdout is discarded (the probe never reads it). Stderr is captured
    for classification — the caller MUST strip / bucket it before any
    value reaches a response body (the HTTPS URL contains the token).
    """
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(BaseException):
            await proc.wait()
        return None, b"", True
    return proc.returncode, stderr or b"", False


async def _probe_git_push(
    *,
    token: str,
    owner: str,
    repo: str,
    timeout_seconds: float,
    git_host: str = "github.com",
) -> RepoPushAccess:
    """Run ``git push --dry-run <https-with-token-url> HEAD:refs/heads/cliff-push-probe``
    against the repo from an ephemeral temp git repo.

    ``git push --dry-run`` performs the full ref-negotiation handshake
    (which is where the server enforces push permission) but skips the
    pack upload. It's the cheapest wire-level probe that observes the
    same server-side decision the executor's real ``git push`` will hit.

    An earlier revision of this code used ``git ls-remote --push`` — that
    flag does NOT exist; ``ls-remote`` is read-only and authenticates on
    the fetch path, so it cannot distinguish ``Contents:read`` from
    ``Contents:write``. Do NOT regress to it.

    Why the temp-repo bootstrap (``git init`` + ``git commit --allow-empty``):
    ``git push HEAD:refs/heads/<name>`` requires a local HEAD pointing at
    a commit. The API server's cwd is not a git repo, so without a
    bootstrap step ``git push`` would fail with ``fatal: not a git
    repository`` before reaching the network. The classifier would then
    bucket that local error as a credentials failure, incorrectly
    downgrading ``can_push``. The bootstrap is fast (touch-only, no
    objects of consequence) and the temp dir is cleaned up in a
    ``finally`` regardless of probe outcome.

    Returns ``can_push=True, reason="verified by runtime probe"`` on
    exit-code 0. Anything else → ``can_push=False`` with a bucketed
    reason. Stderr is parsed for classification but NEVER echoed —
    it may contain the remote URL with the embedded token.

    Token exposure: same surface as the executor's ``git clone`` —
    ``/proc/<pid>/cmdline`` for the duration of the probe. No NEW
    exposure. We do NOT log the URL or the token anywhere.
    """
    remote_url = (
        f"https://x-access-token:{token}@{git_host}/{owner}/{repo}.git"
    )
    refspec = "HEAD:refs/heads/cliff-push-probe"

    tmp_dir = tempfile.mkdtemp(prefix="cliff-push-probe-")
    try:
        # Step 1: bootstrap an empty repo so HEAD exists. ``-q`` keeps
        # stderr quiet on success so we don't pollute the classifier on
        # the off-chance it's invoked on a bootstrap error.
        try:
            rc, _err, timed_out = await _run_git(
                "init",
                "-q",
                cwd=tmp_dir,
                timeout_seconds=_BOOTSTRAP_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            return RepoPushAccess(
                can_push=False, reason=_PROBE_REASON_GIT_MISSING
            )
        except OSError:
            return RepoPushAccess(
                can_push=False, reason=_PROBE_REASON_GENERIC
            )
        if timed_out or rc != 0:
            # Local disk / config problem — fail closed but do NOT
            # claim "credentials": the network was never reached.
            return RepoPushAccess(
                can_push=False, reason=_PROBE_REASON_GENERIC
            )

        # Step 2: create an empty commit so HEAD points at an object.
        # Inline ``-c user.email`` / ``-c user.name`` so the commit
        # succeeds even on a clean container without ``git config
        # --global`` set.
        try:
            rc, _err, timed_out = await _run_git(
                "-c",
                "user.email=probe@cliff.local",
                "-c",
                "user.name=Cliff Probe",
                "commit",
                "--allow-empty",
                "-q",
                "-m",
                "probe",
                cwd=tmp_dir,
                timeout_seconds=_BOOTSTRAP_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            return RepoPushAccess(
                can_push=False, reason=_PROBE_REASON_GIT_MISSING
            )
        except OSError:
            return RepoPushAccess(
                can_push=False, reason=_PROBE_REASON_GENERIC
            )
        if timed_out or rc != 0:
            return RepoPushAccess(
                can_push=False, reason=_PROBE_REASON_GENERIC
            )

        # Step 3: the actual probe. Negotiates push perms with GitHub
        # but skips the pack upload.
        try:
            rc, stderr, timed_out = await _run_git(
                "push",
                "--dry-run",
                remote_url,
                refspec,
                cwd=tmp_dir,
                timeout_seconds=timeout_seconds,
            )
        except FileNotFoundError:
            return RepoPushAccess(
                can_push=False, reason=_PROBE_REASON_GIT_MISSING
            )
        except OSError:
            # Any other spawn failure — fail closed. Don't echo the
            # exception message (it may contain the remote URL).
            return RepoPushAccess(
                can_push=False, reason=_PROBE_REASON_GENERIC
            )

        if timed_out:
            return RepoPushAccess(
                can_push=False,
                reason=_PROBE_REASON_TIMEOUT.format(
                    seconds=timeout_seconds
                ),
            )
        if rc == 0:
            return RepoPushAccess(
                can_push=True, reason=_PROBE_REASON_VERIFIED
            )
        return RepoPushAccess(
            can_push=False, reason=_classify_probe_stderr(stderr)
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def check_repo_push_access(
    *,
    token: str,
    owner: str,
    repo: str,
    api_base_url: str = "https://api.github.com",
    transport: httpx.BaseTransport | None = None,
    timeout: float = 10.0,
    probe_timeout_seconds: float | None = None,
) -> RepoPushAccess:
    """Verify that ``token`` can push to ``owner/repo`` before triggering work.

    Two-step preflight:

    1. ``GET /repos/{owner}/{repo}`` — the user-OAuth-token's effective
       repo permissions (intersection of App declared perms × user repo
       perms). A ``push=false`` here is definitive.
    2. ``GET /repos/{owner}/{repo}/installation`` — the GitHub App
       installation's declared permissions on this repo. When the user
       perms say push=true we still need to confirm the *installation*
       has ``contents:write`` (Q01R-W2 / B35a). The intersection
       semantics mean an installation with ``contents:read`` blocks the
       push even if the user owns the repo. Step 2 closes that gap.

    On a definitive negative (404 / 401 / 403 / 200 with push=false /
    install perms missing write) we return ``can_push=False`` with a
    UI-safe reason pointing at the actual remediation. On a *transient*
    failure (network error, 429, 5xx) on the user-perms step we
    ``can_push=True`` with a reason annotating that the check was
    skipped. Step 2 failures fall back to step 1's verdict so the
    preflight stays useful for tokens that can't call the App-only
    endpoint (e.g. a stock user OAuth token may receive 403/404 on
    ``/installation`` — that's expected and not a regression).
    """
    base = api_base_url.rstrip("/")
    kwargs: dict = {"timeout": timeout}
    if transport is not None:
        kwargs["transport"] = transport

    # Resolve the probe timeout. Explicit override wins (tests). Otherwise
    # pick up the operator-tunable setting. Import locally so importing
    # this module doesn't drag the full settings tree in at import time.
    if probe_timeout_seconds is None:
        try:
            from cliff.config import settings as _settings

            probe_timeout_seconds = _settings.push_probe_timeout_seconds
        except Exception:
            probe_timeout_seconds = _DEFAULT_PROBE_TIMEOUT_SECONDS

    async def _verify_with_probe() -> RepoPushAccess:
        """Run the runtime probe and return its verdict. The 6
        previously-permissive return paths below funnel through here —
        the probe is the wire-level ground truth that the API-derived
        signals (user perms, install perms) sometimes misreport
        (Q01R-W3 / B37 / IMPL-0019).
        """
        return await _probe_git_push(
            token=token,
            owner=owner,
            repo=repo,
            timeout_seconds=probe_timeout_seconds,
        )

    async with httpx.AsyncClient(**kwargs) as client:
        user_perms_url = (
            f"{base}{REPO_PATH_TEMPLATE.format(owner=owner, repo=repo)}"
        )
        try:
            resp = await client.get(
                user_perms_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        except httpx.HTTPError as exc:
            # Network / timeout / DNS — fail OPEN. The executor will hit
            # GitHub itself; if push is truly broken it'll surface there.
            return RepoPushAccess(
                can_push=True,
                reason=(
                    f"Skipped push preflight: could not reach GitHub "
                    f"({exc.__class__.__name__})."
                ),
            )

        # Transient HTTP failures (rate limit, server error) — also fail
        # OPEN. GitHub returns 429 with rate-limit headers; treating
        # that as "no push access" would silently block every executor
        # run during a spike. The executor will retry GitHub itself and
        # either succeed or surface a real 4xx.
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            return RepoPushAccess(
                can_push=True,
                reason=(
                    f"Skipped push preflight: GitHub returned HTTP "
                    f"{resp.status_code} (transient)."
                ),
            )

        if resp.status_code == 404:
            return RepoPushAccess(
                can_push=False,
                reason=(
                    f"Repo {owner}/{repo} is not visible to this GitHub "
                    "token. The Cliff GitHub App may not be installed "
                    "on this organization, or the installation was "
                    "removed."
                ),
            )
        if resp.status_code == 401:
            return RepoPushAccess(
                can_push=False,
                reason=(
                    "GitHub rejected the auth token (HTTP 401). The "
                    "token has likely expired or been revoked — "
                    "reconnect GitHub from Settings → Integrations."
                ),
            )
        if resp.status_code == 403:
            return RepoPushAccess(
                can_push=False,
                reason=(
                    "GitHub denied access to this repo (HTTP 403). "
                    "Check that the Cliff GitHub App is installed on "
                    "this org/repo and declares Contents:write + Pull "
                    "requests:write permissions."
                ),
            )
        if resp.status_code != 200:
            return RepoPushAccess(
                can_push=False,
                reason=(
                    f"Unexpected response from GitHub when checking "
                    f"push access (HTTP {resp.status_code})."
                ),
            )

        try:
            body = resp.json()
        except ValueError:
            return RepoPushAccess(
                can_push=False,
                reason=(
                    "GitHub returned an unparseable response for the repo."
                ),
            )

        perms = body.get("permissions") if isinstance(body, dict) else None
        if not isinstance(perms, dict):
            return RepoPushAccess(
                can_push=False,
                reason=(
                    "GitHub did not return a permissions block for this "
                    "repo. Update the Cliff GitHub App to declare "
                    "Contents:write and Pull requests:write."
                ),
            )

        user_can_push = bool(perms.get("push"))
        if not user_can_push:
            return RepoPushAccess(
                can_push=False,
                reason=(
                    f"GitHub reports this token has no push permission "
                    f"on {owner}/{repo}. The Cliff GitHub App likely "
                    "declares Contents:read only — update it to "
                    "Contents:write + Pull requests:write so the "
                    "device-flow token can create a PR."
                ),
            )

        # User-perms say push=true. Cross-check the App installation's
        # declared permissions — the effective git-push capability is
        # the intersection of (user × App installation), and we've seen
        # B30/B35a where user perms read green but the install still
        # carries Contents:read because the org admin hasn't approved
        # the App's newer requested permissions yet. The executor would
        # then waste ~4 minutes only to fail at git-push time.
        install_url = (
            f"{base}{REPO_INSTALLATION_PATH_TEMPLATE.format(owner=owner, repo=repo)}"
        )
        try:
            install_resp = await client.get(
                install_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        except httpx.HTTPError:
            # Network blip on the install lookup → fall back to the
            # user-perms verdict (push=true here). Don't degrade the
            # preflight just because one of the two endpoints was
            # transiently unreachable. Q01R-W3: STILL run the runtime
            # probe — this fallback path was B37's worst case (signals
            # said green, git push failed).
            return await _verify_with_probe()

        # The ``/installation`` endpoint is documented as App-JWT-only
        # in some places and accessible to user-to-server tokens in
        # others; in practice GitHub returns 403/404 for user OAuth
        # tokens that don't have install visibility. Treat any non-200
        # as "fall back to user-perms verdict" rather than escalating
        # into a hard block.
        if install_resp.status_code != 200:
            return await _verify_with_probe()

        try:
            install_body = install_resp.json()
        except ValueError:
            return await _verify_with_probe()

        install_perms = (
            install_body.get("permissions")
            if isinstance(install_body, dict)
            else None
        )
        if not isinstance(install_perms, dict):
            # No permissions block on the response — can't make a
            # confident negative judgement, fall back to the user-perms
            # verdict. Q01R-W3: runtime probe is the ground truth.
            return await _verify_with_probe()

        # The ``/installation`` permissions block is keyed by App-scope
        # names (``contents``, ``metadata``, ``pull_requests``, …) with
        # ``read``/``write``/``admin`` values. If ``contents`` is
        # missing entirely the response shape probably isn't an install
        # perms doc at all (some endpoints / shims return a repo-perms
        # block under the same field name) — fall back rather than
        # mislabel.
        if "contents" not in install_perms:
            return await _verify_with_probe()

        contents_perm = install_perms.get("contents")
        if contents_perm != "write":
            return RepoPushAccess(
                can_push=False,
                reason=(
                    f"The Cliff GitHub App's installation on "
                    f"{owner}/{repo} declares Contents:"
                    f"{contents_perm or 'none'}, not Contents:write. An "
                    "org admin needs to approve the App's updated "
                    "permissions before pushes can succeed — open the "
                    "App in GitHub's org settings and click "
                    "“Review request” to approve the new permissions."
                ),
            )

        # All API-derived signals point to "can push". Confirm with the
        # runtime probe before returning True — Q01R-W3 / B37: signals can
        # lie at the wire-protocol layer (App declared write but installation
        # still scoped Contents:read, etc.).
        return await _verify_with_probe()
