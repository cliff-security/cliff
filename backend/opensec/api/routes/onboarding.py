"""Onboarding routes.

``POST /onboarding/repo`` persists the GitHub token, probes the repo via the
GitHub REST API for display metadata, and kicks off an initial assessment via
the DI'd engine seam. ``POST /onboarding/complete`` flips the
``onboarding.completed`` setting once the first assessment succeeds.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request as FastAPIRequest
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from opensec.api._background import schedule_assessment_run
from opensec.api._engine_dep import (
    AssessmentEngineProtocol,
    get_assessment_engine,
)
from opensec.assessment.posture.github_client import GithubClient, UnableToVerify
from opensec.db.connection import get_db
from opensec.db.dao.assessment import create_assessment, get_assessment
from opensec.db.repo_integration import (
    create_integration,
    list_integrations,
    update_integration,
)
from opensec.db.repo_setting import upsert_setting
from opensec.models import (
    AssessmentCreate,
    IntegrationConfigCreate,
    IntegrationConfigUpdate,
)

# ``upsert_setting`` is still used by ``/complete`` (``onboarding.completed``).

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class OnboardingRepoRequest(BaseModel):
    repo_url: str
    github_token: str


class VerifiedRepo(BaseModel):
    """Display-only metadata the SPA shows on the connect-success card."""

    repo_name: str
    visibility: str
    default_branch: str
    permissions: list[str] = []


class OnboardingRepoResponse(BaseModel):
    assessment_id: str
    repo_url: str
    verified: VerifiedRepo | None = None


def _parse_owner_repo(repo_url: str) -> tuple[str, str] | None:
    try:
        parsed = urlparse(repo_url)
    except ValueError:
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(parts) < 2:
        return None
    owner, name = parts[0], parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    return owner, name


GITHUB_ADAPTER_TYPE = "github"
GITHUB_PROVIDER_NAME = "GitHub"
# Canonical credential key name, matched by the GitHub registry entry
# (backend/opensec/integrations/registry/github.json) and read by the
# remediation executor's workspace setup + the connection tester. Writing
# under any other name silently breaks "open a PR" remediation.
GITHUB_TOKEN_KEY = "github_personal_access_token"


async def _upsert_github_integration(
    db,
    http_request: FastAPIRequest,
    token: str,
    repo_url: str,
    verified: VerifiedRepo | None,
) -> None:
    """Single source of truth for the onboarding PAT.

    Writes the GitHub integration row + credential through the same path the
    Integrations settings page uses, so "solve a finding" sees the PAT that
    onboarding just collected. Idempotent: reruns update the existing row
    instead of creating a duplicate.
    """
    integrations = await list_integrations(db)
    existing = next(
        (i for i in integrations if i.adapter_type == GITHUB_ADAPTER_TYPE), None
    )

    config = {
        "repo_url": repo_url,
        "default_branch": verified.default_branch if verified else None,
        "repo_name": verified.repo_name if verified else None,
    }

    if existing is None:
        integration = await create_integration(
            db,
            IntegrationConfigCreate(
                adapter_type=GITHUB_ADAPTER_TYPE,
                provider_name=GITHUB_PROVIDER_NAME,
                config=config,
                action_tier=2,
            ),
        )
    else:
        integration = await update_integration(
            db,
            existing.id,
            IntegrationConfigUpdate(enabled=True, config=config, action_tier=2),
        )
        assert integration is not None

    vault = getattr(http_request.app.state, "vault", None)
    if vault is None:
        # No vault in this deployment — the token is lost. Logged loudly so
        # operators know to set OPENSEC_CREDENTIAL_KEY. The Integrations row
        # still exists; they can re-enter the PAT from Settings.
        logger.warning(
            "credential vault not initialized; GitHub PAT from onboarding was not stored. "
            "Set OPENSEC_CREDENTIAL_KEY to enable durable credential storage."
        )
        return

    await vault.store(integration.id, GITHUB_TOKEN_KEY, token)


# Sentinel returned by _probe_repo_metadata for hard-fail cases. The route
# turns this into a 422 JSONResponse with the matching ``code`` so the SPA
# can branch on it (see frontend ConnectRepo missing_repo_scope handling).
class _ProbeError(BaseModel):
    code: str
    message: str


async def _probe_repo_metadata(
    repo_url: str, token: str
) -> VerifiedRepo | _ProbeError | None:
    """Call the GitHub REST API for display metadata.

    Three outcomes:
      * ``VerifiedRepo`` — the token can read **and** push to the repo.
      * ``_ProbeError`` — a hard failure the user must fix
        (bad URL, no access, read-only token). The route returns 422 with
        ``code`` so the SPA can branch on it.
      * ``None`` — a soft failure (network blip, 5xx, unparseable URL).
        Onboarding continues with ``verified=None`` — same as before.
    """
    parsed = _parse_owner_repo(repo_url)
    if parsed is None:
        return _ProbeError(
            code="invalid_repo_url",
            message="Repository URL must look like https://github.com/owner/name.",
        )
    owner, name = parsed
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            client = GithubClient(http, token=token)
            info = await client.get_repo_info(owner, name)
    except Exception:  # pragma: no cover — defensive; client already swallows most
        logger.exception("GitHub metadata probe raised for %s/%s", owner, name)
        return None

    if isinstance(info, UnableToVerify):
        # Distinguish auth/access failures (hard) from network/server (soft).
        # The frontend already renders a tailored UI for ``missing_repo_scope``
        # ([ConnectRepo.tsx]); ``repo_not_found`` reuses the generic callout.
        if info.reason in ("http_401", "http_403"):
            return _ProbeError(
                code="missing_repo_scope",
                message=(
                    "Token can't access this repository. It needs Contents "
                    "(write) and Pull requests (write)."
                ),
            )
        if info.reason == "http_404":
            return _ProbeError(
                code="repo_not_found",
                message="Repository not found. Check the URL and that your token can see it.",
            )
        # http_429 / http_5xx / network: keep the legacy degraded path so
        # transient GitHub blips don't strand a user mid-onboarding.
        return None

    raw_perms = info.get("permissions") or {}
    if not (isinstance(raw_perms, dict) and raw_perms.get("push") is True):
        # The token can read the repo (we got a 200) but can't push to it.
        # Without push, the remediation agent can't open a draft PR — this is
        # exactly the gap that lets onboarding succeed and PR creation later
        # fail. Hard-fail with the same code the SPA already handles.
        return _ProbeError(
            code="missing_repo_scope",
            message=(
                "Token has read but not write access. Contents (write) and "
                "Pull requests (write) are required."
            ),
        )

    visibility = "private" if info.get("private") else "public"
    perms = sorted(k for k, v in raw_perms.items() if v)
    return VerifiedRepo(
        repo_name=info.get("full_name") or f"{owner}/{name}",
        visibility=visibility,
        default_branch=info.get("default_branch") or "main",
        permissions=perms,
    )


class OnboardingCompleteRequest(BaseModel):
    assessment_id: str


class OnboardingCompleteResponse(BaseModel):
    onboarding_completed: bool


@router.post("/repo")
async def connect_repo(
    request: OnboardingRepoRequest,
    http_request: FastAPIRequest,
    db=Depends(get_db),
    engine: AssessmentEngineProtocol = Depends(get_assessment_engine),
):
    """Register a repo and kick off the initial assessment.

    Returns ``OnboardingRepoResponse`` on success. On hard probe failures
    returns a ``JSONResponse`` with ``{detail, code}`` at 422 — the SPA
    branches on ``code`` (e.g. ``missing_repo_scope``).
    """
    repo_url = request.repo_url.strip()
    if not repo_url:
        raise HTTPException(status_code=422, detail="repo_url must not be empty")

    probed = await _probe_repo_metadata(repo_url, request.github_token)

    # Hard failure — the user must fix the URL or token before we touch the
    # vault or schedule a scan. The SPA reads ``code`` from the top-level
    # body (see [api/onboarding.ts] postJson).
    if isinstance(probed, _ProbeError):
        return JSONResponse(
            status_code=422,
            content={"detail": probed.message, "code": probed.code},
        )

    verified = probed  # VerifiedRepo or None (soft network failure)

    # Store the PAT through the same path the Integrations settings page uses —
    # single source of truth. "Solve a finding" + posture-fix spawner both
    # read from this row later.
    await _upsert_github_integration(
        db, http_request, request.github_token, repo_url, verified
    )

    assessment = await create_assessment(db, AssessmentCreate(repo_url=repo_url))
    schedule_assessment_run(http_request.app, db, engine, assessment.id, repo_url)
    return OnboardingRepoResponse(
        assessment_id=assessment.id, repo_url=repo_url, verified=verified
    )


# ---------------------------------------------------------------------------
# Repo picker — phase A of onboarding
# ---------------------------------------------------------------------------


class ListReposRequest(BaseModel):
    github_token: str


class RepoOption(BaseModel):
    """One row in the onboarding repo picker.

    ``can_push`` mirrors GitHub's ``permissions.push`` so the SPA can disable
    rows for repos the token can't operate on, instead of letting the user
    pick one and surface the failure two screens later.
    """

    full_name: str
    html_url: str
    private: bool
    default_branch: str
    can_push: bool


class ListReposResponse(BaseModel):
    repos: list[RepoOption]


@router.post("/github/repos")
async def list_github_repos(
    request: ListReposRequest,
):
    """Return the repos a PAT can reach, for onboarding's picker step.

    The token is **not** persisted here — only on a successful call to
    ``POST /onboarding/repo``. Avoids dangling vault entries when the user
    abandons the flow at the picker.

    Auth/scope failures return 422 ``{code: "invalid_token"}``. Network and
    GitHub 5xx return 502 — onboarding's manual-URL fallback covers this.
    """
    token = request.github_token.strip()
    if not token:
        return JSONResponse(
            status_code=422,
            content={"detail": "github_token must not be empty", "code": "invalid_token"},
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            client = GithubClient(http, token=token)
            result = await client.list_user_repos()
    except Exception:  # pragma: no cover — client swallows most
        logger.exception("list_user_repos raised")
        raise HTTPException(status_code=502, detail="Could not reach GitHub.") from None

    if isinstance(result, UnableToVerify):
        if result.reason in ("http_401", "http_403", "http_404"):
            return JSONResponse(
                status_code=422,
                content={
                    "detail": "Token is invalid or lacks read access.",
                    "code": "invalid_token",
                },
            )
        # 429 / 5xx / network: surface as a 502 so the SPA can offer the
        # manual-URL fallback rather than treating it as a token problem.
        raise HTTPException(status_code=502, detail="GitHub is unavailable.")

    options: list[RepoOption] = []
    for repo in result:
        if not isinstance(repo, dict) or repo.get("archived"):
            continue
        perms = repo.get("permissions") or {}
        can_push = bool(perms.get("push")) if isinstance(perms, dict) else False
        options.append(
            RepoOption(
                full_name=repo.get("full_name") or "",
                html_url=repo.get("html_url") or "",
                private=bool(repo.get("private")),
                default_branch=repo.get("default_branch") or "main",
                can_push=can_push,
            )
        )

    # Push-capable first — those are the only ones the user can actually
    # remediate. GitHub already returns ``sort=updated`` desc within each
    # group, which we preserve via stable sort.
    options.sort(key=lambda r: 0 if r.can_push else 1)
    return ListReposResponse(repos=options)


@router.post("/complete", response_model=OnboardingCompleteResponse)
async def complete_onboarding(
    request: OnboardingCompleteRequest,
    db=Depends(get_db),
) -> OnboardingCompleteResponse:
    """Mark onboarding as complete once the first assessment finishes."""
    assessment = await get_assessment(db, request.assessment_id)
    if assessment is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if assessment.status != "complete":
        raise HTTPException(
            status_code=409,
            detail=f"Assessment is '{assessment.status}', not 'complete'",
        )

    await upsert_setting(db, "onboarding.completed", {"completed": True})
    return OnboardingCompleteResponse(onboarding_completed=True)
