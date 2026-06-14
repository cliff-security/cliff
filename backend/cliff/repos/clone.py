"""Credential-less persistent clone for the per-repo store (ADR-0053 §4).

The existing ``assessment.clone`` injects the GitHub token into the remote URL
(``https://x-access-token:TOKEN@github.com/...``), which persists in
``.git/config`` — acceptable only because those clones are ephemeral. The
per-repo store keeps its clone for a long time and the deep dive reads it, so a
token in ``.git/config`` would be a standing leak.

Here the token is supplied to git transiently via ``GIT_ASKPASS`` (read from an
env var by a tiny helper script, never from argv), and the clone URL is plain.
Result: ``.git/config`` carries only ``https://host/owner/repo`` — no token,
not even the ``x-access-token`` username. "Practice what you preach."
"""

from __future__ import annotations

import asyncio
import os
import signal
import stat
import tempfile
from pathlib import Path

from cliff.assessment.clone import (
    CloneError,
    CloneTimeoutError,
    redact_token,
    validate_repo_url,
)

__all__ = [
    "CloneError",
    "CloneTimeoutError",
    "askpass_response",
    "clone_repo",
    "refresh_repo",
]

#: Env var the askpass helper reads the token from (never passed on argv).
TOKEN_ENV = "CLIFF_GIT_TOKEN"

#: git calls the askpass program once per credential prompt, passing the prompt
#: text as ``$1``. We answer the username with the fixed GitHub-App token user
#: and the password with the token from the environment.
_ASKPASS_SCRIPT = (
    "#!/bin/sh\n"
    'case "$1" in\n'
    '  *[Uu]sername*) printf "%s" "x-access-token" ;;\n'
    f'  *) printf "%s" "${TOKEN_ENV}" ;;\n'
    "esac\n"
)


def askpass_response(prompt: str, token: str) -> str:
    """Pure mirror of the askpass script's logic, for unit testing.

    A prompt mentioning "username" yields the fixed token-user; anything else
    (the password prompt) yields the token.
    """
    return "x-access-token" if "username" in prompt.lower() else token


def _clone_args(repo_url: str, target: Path, depth: int) -> list[str]:
    """The git clone argv. The token is NEVER here — only in the env."""
    return [
        "git",
        "-c",
        "credential.helper=",  # disable any helper that would cache the token
        "clone",
        "--depth",
        str(depth),
        "--single-branch",
        "--",
        repo_url,
        str(target),
    ]


def _git_env(token: str | None, askpass_path: Path | None) -> dict[str, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
    if token and askpass_path is not None:
        env["GIT_ASKPASS"] = str(askpass_path)
        env[TOKEN_ENV] = token
    return env


def _write_askpass() -> Path:
    fd, path = tempfile.mkstemp(prefix="cliff-askpass-", suffix=".sh")
    with os.fdopen(fd, "w") as f:
        f.write(_ASKPASS_SCRIPT)
    p = Path(path)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR)
    return p


async def _run_git(
    args: list[str], env: dict[str, str], *, timeout_s: float, token: str | None
) -> None:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=True,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        if proc.pid:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        await proc.wait()
        raise CloneTimeoutError(f"git timed out after {timeout_s}s") from None
    if proc.returncode != 0:
        msg = redact_token(stderr.decode("utf-8", errors="replace"), token)
        raise CloneError(f"git failed (exit {proc.returncode}): {msg.strip()}")


async def clone_repo(
    repo_url: str,
    *,
    target: Path,
    token: str | None,
    timeout_s: float = 120.0,
    depth: int = 1,
) -> None:
    """Clone *repo_url* into *target* without persisting the token.

    When a token is supplied the host is validated against the GitHub allowlist
    (we won't hand a token to an arbitrary host). The token reaches git only via
    ``GIT_ASKPASS`` + env, so the resulting ``.git/config`` stays credential-less.
    """
    has_token = bool(token)
    if has_token:
        validate_repo_url(repo_url, has_token=True)
    askpass_path = _write_askpass() if has_token else None
    try:
        await _run_git(
            _clone_args(repo_url, target, depth),
            _git_env(token, askpass_path),
            timeout_s=timeout_s,
            token=token,
        )
    finally:
        if askpass_path is not None:
            askpass_path.unlink(missing_ok=True)


async def refresh_repo(
    target: Path, *, token: str | None, timeout_s: float = 120.0
) -> None:
    """Fetch the latest remote tip and hard-reset the working tree to it.

    Used to bring a cached clone up to date instead of re-cloning (ADR-0053 §4).
    """
    has_token = bool(token)
    askpass_path = _write_askpass() if has_token else None
    env = _git_env(token, askpass_path)
    try:
        await _run_git(
            ["git", "-C", str(target), "-c", "credential.helper=", "fetch", "origin"],
            env,
            timeout_s=timeout_s,
            token=token,
        )
        await _run_git(
            ["git", "-C", str(target), "reset", "--hard", "FETCH_HEAD"],
            env,
            timeout_s=timeout_s,
            token=token,
        )
    finally:
        if askpass_path is not None:
            askpass_path.unlink(missing_ok=True)
