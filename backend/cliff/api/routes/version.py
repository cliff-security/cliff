"""Version handshake for the agent CLI.

The agent-facing `cliff` CLI calls `GET /api/version` on every command (with
a 60s cache) so it can:

  1. show the running daemon version to the user, and
  2. refuse to operate if its own build is older than `min_cli` —
     i.e. the contract has moved and the user needs to upgrade their CLI.

The plain `/health` endpoint stays for liveness probes; this one is the
contract surface for tooling.
"""

from __future__ import annotations

from fastapi import APIRouter

from cliff.config import settings
from cliff.engine.models import VersionInfo

router = APIRouter()

# Bump when the CLI/server contract changes in a way an older CLI cannot
# tolerate. `min_cli` is what the running daemon will accept; the CLI binary
# bakes its own version at build time and compares.
_MIN_CLI = "0.1.0"
_SCHEMA = "1"


@router.get("/version", response_model=VersionInfo)
async def get_version() -> VersionInfo:
    return VersionInfo(
        cliff=settings.cliff_version,
        opencode=settings.opencode_version,
        schema_version=_SCHEMA,
        min_cli=_MIN_CLI,
    )
