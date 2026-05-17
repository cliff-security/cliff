"""Output envelope and exit codes for the agent CLI.

Every command returns a single JSON object on stdout and exits with a
state-meaningful code. Errors go to stderr as the same envelope shape with
``ok: false``.

Exit codes are part of the contract — agents branch on them:

  0  — command succeeded; no human gate needed
  1  — generic / unexpected error
  2  — awaiting a human gate (plan approval, validation failure, ...)
  3  — daemon unreachable (install / start Cliff)
  4  — version mismatch (CLI is too old or too new for this server)
  5  — scan completed with zero findings (clean repo)
"""

from __future__ import annotations

import json
import sys
from typing import Any

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_AWAITING_HUMAN = 2
EXIT_DAEMON_DOWN = 3
EXIT_VERSION_MISMATCH = 4
EXIT_NO_FINDINGS = 5


def emit(payload: dict[str, Any], *, exit_code: int = EXIT_OK) -> None:
    """Write the JSON envelope to stdout and exit.

    Always emits compact JSON (no pretty-printing) — agents parse, humans use
    `--human` if they want pretty output.
    """
    payload = {"ok": exit_code == EXIT_OK, **payload}
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    sys.exit(exit_code)


def emit_error(
    message: str,
    *,
    code: str = "error",
    hint: str | None = None,
    exit_code: int = EXIT_ERROR,
    extra: dict[str, Any] | None = None,
) -> None:
    """Write an error envelope to stderr and exit non-zero."""
    payload: dict[str, Any] = {
        "ok": False,
        "error": {"code": code, "message": message},
    }
    if hint:
        payload["error"]["hint"] = hint
    if extra:
        payload.update(extra)
    sys.stderr.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stderr.flush()
    sys.exit(exit_code)
