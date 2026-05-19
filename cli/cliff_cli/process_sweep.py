"""Owner-safe process discovery and cleanup for the Cliff CLI.

Used by ``cliffsec stop`` / ``restart`` / ``uninstall`` to find leaked Cliff
processes (parent uvicorn + child OpenCode binaries) when the parent died
abruptly and left orphans holding ports.

Hard ownership rule: a process is Cliff-owned **iff** its cmdline matches
one of two patterns:

1. The parent uvicorn — argv contains the literal token ``uvicorn`` and the
   target ``cliff.main:app``.
2. Our installed opencode binary — ``argv[0]`` (or the executable path) is
   exactly ``$CLIFF_HOME/bin/opencode``.

Port presence is *never* sufficient to declare a process ours. A process
sitting on port 4096 with an unrelated cmdline is a "squatter": reported,
never signalled. This is the safety contract: we never kill someone else's
process just because it happens to be on a port we'd like.
"""

from __future__ import annotations

import os
import signal
import socket
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import psutil

OPENCODE_SINGLETON_PORT = 4096
WORKSPACE_PORT_RANGE = range(4100, 4200)


@dataclass(frozen=True)
class FoundProcess:
    """An Cliff process the user is allowed to signal."""

    pid: int
    kind: Literal["uvicorn", "opencode"]
    cmdline: str
    ports: tuple[int, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PortSquatter:
    """A non-Cliff process bound to one of our ports. Report only — never signal."""

    pid: int
    port: int
    cmdline: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _listening_ports_by_pid() -> dict[int, list[int]]:
    """Map PID -> list of TCP ports it is LISTENing on.

    Two paths:
      1. Fast path: ``psutil.net_connections(kind="inet")`` — single syscall,
         covers every process. On Linux as a regular user this works.
      2. Fallback: ``psutil.net_connections`` raises AccessDenied on macOS for
         non-root users (it needs ``sudo`` or a privileged helper). In that
         case we iterate processes individually and call ``proc.net_connections``,
         which works without root for processes the user owns.

    Either way, returns an empty map if nothing can be inspected. Safety is
    not affected by this map being incomplete — kill decisions never depend
    on port info, only on cmdline ownership.
    """
    out: dict[int, list[int]] = {}
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, PermissionError):
        # macOS fallback: per-process scan.
        for proc in psutil.process_iter(["pid"]):
            try:
                proc_conns = proc.net_connections(kind="inet")
            except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
                continue
            for c in proc_conns:
                if c.status != psutil.CONN_LISTEN:
                    continue
                if c.laddr is None:
                    continue
                port = getattr(c.laddr, "port", None)
                if port is None:
                    continue
                out.setdefault(proc.pid, []).append(port)
        return out

    for c in conns:
        if c.status != psutil.CONN_LISTEN or c.pid is None:
            continue
        if c.laddr is None:
            continue
        port = getattr(c.laddr, "port", None)
        if port is None:
            continue
        out.setdefault(c.pid, []).append(port)
    return out


def _classify(
    proc: psutil.Process,
    cliff_opencode_bin: Path,
) -> Literal["uvicorn", "opencode"] | None:
    """Return 'uvicorn' / 'opencode' if proc matches our ownership rules, else None."""
    try:
        cmdline = proc.cmdline()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return None
    if not cmdline:
        return None

    # Rule 1: parent uvicorn for our app.
    has_uvicorn = any("uvicorn" in arg for arg in cmdline)
    has_app = any("cliff.main:app" in arg for arg in cmdline)
    if has_uvicorn and has_app:
        return "uvicorn"

    # Rule 2: our opencode binary at the exact installed path.
    target = str(cliff_opencode_bin)
    if cmdline[0] == target:
        return "opencode"
    try:
        exe = proc.exe()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        exe = ""
    if exe == target:
        return "opencode"

    return None


def _is_same_user(proc: psutil.Process) -> bool:
    """True if proc is owned by the current user. Defensive: AccessDenied -> False."""
    try:
        return proc.uids().real == os.getuid()
    except (psutil.AccessDenied, psutil.NoSuchProcess, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_cliff_processes(cliff_home: Path) -> list[FoundProcess]:
    """Find every Cliff-owned process running as the current user.

    Skips processes we can't inspect (AccessDenied, NoSuchProcess) and never
    matches by port alone — see module docstring for the ownership rules.
    """
    opencode_bin = cliff_home / "bin" / "opencode"
    ports_by_pid = _listening_ports_by_pid()
    found: list[FoundProcess] = []
    self_pid = os.getpid()

    for proc in psutil.process_iter(["pid"]):
        try:
            if proc.pid == self_pid:
                continue
            if not _is_same_user(proc):
                continue
            kind = _classify(proc, opencode_bin)
            if kind is None:
                continue
            cmdline_str = " ".join(proc.cmdline())
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        ports = tuple(sorted(ports_by_pid.get(proc.pid, [])))
        found.append(
            FoundProcess(
                pid=proc.pid,
                kind=kind,
                cmdline=_truncate(cmdline_str),
                ports=ports,
            )
        )
    return found


def find_port_squatters(
    ports: Iterable[int],
    owned_pids: set[int],
) -> list[PortSquatter]:
    """Return processes bound to one of ``ports`` that are NOT in ``owned_pids``.

    These are reported so the user knows why a port stayed bound, but we
    never signal them — they aren't ours.
    """
    target_ports = set(ports)
    ports_by_pid = _listening_ports_by_pid()
    squatters: list[PortSquatter] = []
    seen: set[tuple[int, int]] = set()
    for pid, plist in ports_by_pid.items():
        if pid in owned_pids:
            continue
        for port in plist:
            if port not in target_ports:
                continue
            key = (pid, port)
            if key in seen:
                continue
            seen.add(key)
            try:
                proc = psutil.Process(pid)
                cmdline = " ".join(proc.cmdline())
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                cmdline = "<inaccessible>"
            squatters.append(PortSquatter(pid=pid, port=port, cmdline=_truncate(cmdline)))
    squatters.sort(key=lambda s: (s.port, s.pid))
    return squatters


def kill_processes(
    procs: list[FoundProcess],
    timeout: float = 10.0,
    *,
    force: bool = False,
) -> tuple[list[FoundProcess], list[FoundProcess]]:
    """SIGTERM (or SIGKILL if force=True), wait up to ``timeout``, SIGKILL stragglers.

    Returns ``(killed, still_alive)``. Already-dead processes count as killed.
    ``ProcessLookupError`` is swallowed silently — the process exited between
    discovery and signal.
    """
    if not procs:
        return [], []

    sig = signal.SIGKILL if force else signal.SIGTERM
    for p in procs:
        try:
            os.kill(p.pid, sig)
        except ProcessLookupError:
            continue
        except PermissionError:
            # Should not happen — we filtered to same-user processes — but
            # be defensive: leave it for the still_alive bucket.
            continue

    deadline = time.time() + max(timeout, 0.0)
    pending = list(procs)
    killed: list[FoundProcess] = []

    while pending and time.time() < deadline:
        next_pending: list[FoundProcess] = []
        for p in pending:
            if not psutil.pid_exists(p.pid):
                killed.append(p)
            else:
                next_pending.append(p)
        if not next_pending:
            return killed, []
        pending = next_pending
        time.sleep(0.1)

    if not force:
        # Escalate to SIGKILL on stragglers.
        for p in pending:
            try:
                os.kill(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                continue
        # Brief wait for the kernel to reap.
        time.sleep(0.2)

    still_alive: list[FoundProcess] = []
    for p in pending:
        if psutil.pid_exists(p.pid):
            still_alive.append(p)
        else:
            killed.append(p)

    return killed, still_alive


def verify_ports_free(
    ports: Iterable[int],
    host: str = "127.0.0.1",
) -> list[int]:
    """Return the subset of ``ports`` that are still bound on ``host``.

    A bind() probe with SO_REUSEADDR — same approach as daemon._port_free.
    Empty list = all clear.
    """
    bound: list[int] = []
    for port in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            bound.append(port)
        finally:
            s.close()
    return bound
