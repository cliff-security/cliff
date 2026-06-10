"""Repository identity — canonicalize git remote URLs to a stable key.

ADR-0053 §1: the app had no URL normalization, so ``…/a/b``, ``…/a/b.git`` and
``git@host:a/b`` were three different repos to the existing code (which used the
raw URL string as a de-facto key in ``assessment``/``workspace``/
``integration_config``). ``canonicalize_repo_url`` collapses the common
spellings to one ``https://<host>/<owner>/<repo>`` form used as
``repo.canonical_url``.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# scp-like git syntax: ``[user@]host:owner/repo`` (no scheme, a single colon
# before the path). Distinguished from a real URL by the absence of ``://``.
_SCP_LIKE = re.compile(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>.+)$")

_GIT_SUFFIX = ".git"


class InvalidRepoUrlError(ValueError):
    """The string could not be parsed as a usable repository URL."""


def canonicalize_repo_url(raw: str) -> str:
    """Return the canonical ``https://<host>/<owner>/<repo>`` key for *raw*.

    Normalizes scheme to https, lowercases the host, strips embedded
    credentials, a trailing ``.git``, and trailing slashes. The path case is
    preserved (some hosts are case-sensitive). Raises :class:`InvalidRepoUrlError`
    for empty input or a URL without both a host and an owner/repo path.
    """
    if not raw or not raw.strip():
        raise InvalidRepoUrlError("repo url must not be empty")
    s = raw.strip()

    # scp-like or bare host/path → give it an https scheme so urlparse works.
    if "://" not in s:
        scp = _SCP_LIKE.match(s)
        s = f"https://{scp.group('host')}/{scp.group('path')}" if scp else f"https://{s}"

    parsed = urlparse(s)
    host = (parsed.hostname or "").lower()
    if not host:
        raise InvalidRepoUrlError(f"repo url has no host: {raw!r}")

    path = parsed.path.strip("/")
    if path.endswith(_GIT_SUFFIX):
        path = path[: -len(_GIT_SUFFIX)]
    path = path.strip("/")
    if not path:
        raise InvalidRepoUrlError(f"repo url has no owner/repo path: {raw!r}")

    return f"https://{host}/{path}"
