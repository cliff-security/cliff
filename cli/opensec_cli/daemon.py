"""Daemon-management commands for the local OpenSec install.

These commands operate on the on-disk install at ``~/.opensec/`` (or
``$OPENSEC_HOME``) and never require a running daemon — they manage the
process itself. Unlike the agent commands in :mod:`opensec_cli.cli`, output
here is human-friendly by default; ``doctor`` exposes ``--json`` for agents
and CI.

Layout (created by ``scripts/install-local.sh``):

    ~/.opensec/
      app/                    # tarball contents
        backend/              # FastAPI app + uv-managed .venv/
        frontend/dist/        # prebuilt SPA
        scripts/
        .opencode-version
        .scanner-versions
        VERSION
      bin/                    # opencode, trivy, semgrep
      data/                   # opensec.db, workspaces/, logs/
      config/opensec.env      # runtime env vars (KEY=value lines)
      run/opensec.pid         # detached-mode pidfile
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import click

from opensec_cli.output import EXIT_ERROR, EXIT_OK, emit, emit_error
from opensec_cli.process_sweep import (
    OPENCODE_SINGLETON_PORT,
    WORKSPACE_PORT_RANGE,
    find_opensec_processes,
    find_port_squatters,
    kill_processes,
    verify_ports_free,
)

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

OPENSEC_HOME = Path(os.environ.get("OPENSEC_HOME", Path.home() / ".opensec"))
APP_DIR = OPENSEC_HOME / "app"
BACKEND_DIR = APP_DIR / "backend"
VENV_BIN = BACKEND_DIR / ".venv" / "bin"
BIN_DIR = OPENSEC_HOME / "bin"
DATA_DIR = OPENSEC_HOME / "data"
CONFIG_DIR = OPENSEC_HOME / "config"
RUN_DIR = OPENSEC_HOME / "run"
LOG_DIR = DATA_DIR / "logs"
ENV_FILE = CONFIG_DIR / "opensec.env"
PID_FILE = RUN_DIR / "opensec.pid"
STATIC_DIR = APP_DIR / "frontend" / "dist"
CLI_VENV_DIR = OPENSEC_HOME / "cli-venv"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pidfile() -> int | None:
    if not PID_FILE.is_file():
        return None
    try:
        pid = int(PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None
    if not _pid_alive(pid):
        # Stale pidfile — clean it up so callers don't trip on it.
        PID_FILE.unlink(missing_ok=True)
        return None
    return pid


def _port_free(port: int, host: str = DEFAULT_HOST) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
    except OSError:
        return False
    finally:
        s.close()
    return True


def _configured_app_port() -> int:
    """Read OPENSEC_APP_PORT from the env file, fall back to DEFAULT_PORT."""
    env = _read_env_file(ENV_FILE)
    raw = env.get("OPENSEC_APP_PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_PORT


def _opensec_ports() -> list[int]:
    """Every port we care about for the lifecycle: app + opencode singleton + workspace range."""
    return [_configured_app_port(), OPENCODE_SINGLETON_PORT, *WORKSPACE_PORT_RANGE]


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _build_env(host: str, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update(_read_env_file(ENV_FILE))
    env.setdefault("OPENSEC_DATA_DIR", str(DATA_DIR))
    env.setdefault("OPENSEC_STATIC_DIR", str(STATIC_DIR))
    env.setdefault("OPENSEC_BIN_DIR", str(BIN_DIR))
    env.setdefault("OPENSEC_SCANNER_BIN_DIR", str(BIN_DIR))
    env["OPENSEC_APP_HOST"] = host
    env["OPENSEC_APP_PORT"] = str(port)
    return env


def _wait_for_health(url: str, timeout: float, proc: subprocess.Popen[bytes]) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:  # noqa: S310 - localhost
                if 200 <= resp.status < 300:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# start / stop / restart / logs
# ---------------------------------------------------------------------------


@click.command(name="start")
@click.option(
    "--detach",
    "-d",
    is_flag=True,
    help="Run in background; logs go to ~/.opensec/data/logs/.",
)
@click.option("--port", default=None, type=int, help=f"Port to bind (default: {DEFAULT_PORT}).")
@click.option("--host", default=None, help=f"Host to bind (default: {DEFAULT_HOST}).")
def start_cmd(detach: bool, port: int | None, host: str | None) -> None:
    """Start the OpenSec server."""
    if not (VENV_BIN / "uvicorn").is_file():
        emit_error(
            f"OpenSec is not installed (no venv at {VENV_BIN}).",
            code="not_installed",
            hint=(
                "Run the installer: curl -fsSL "
                "https://github.com/galanko/opensec/releases/latest/download/install-local.sh | sh"
            ),
            exit_code=EXIT_ERROR,
        )

    existing = _read_pidfile()
    if existing:
        emit_error(
            f"OpenSec is already running (pid {existing}).",
            code="already_running",
            hint="Run `opensec stop` first, or `opensec restart` to bounce.",
        )

    _ensure_dirs()

    bind_host = host or _read_env_file(ENV_FILE).get("OPENSEC_APP_HOST", DEFAULT_HOST)
    bind_port = port or int(_read_env_file(ENV_FILE).get("OPENSEC_APP_PORT", DEFAULT_PORT))
    env = _build_env(bind_host, bind_port)

    if not _port_free(bind_port, bind_host):
        emit_error(
            f"Port {bind_port} is already in use on {bind_host}.",
            code="port_in_use",
            hint=f"Stop whatever is on port {bind_port}, or pick another with --port.",
        )

    args = [
        str(VENV_BIN / "uvicorn"),
        "opensec.main:app",
        "--host",
        bind_host,
        "--port",
        str(bind_port),
    ]

    if detach:
        log_path = LOG_DIR / f"opensec-{time.strftime('%Y%m%d')}.log"
        log_fd = open(log_path, "ab", buffering=0)  # noqa: SIM115 - kept open for child
        try:
            proc = subprocess.Popen(  # noqa: S603 - args are fully resolved paths
                args,
                cwd=str(BACKEND_DIR),
                env=env,
                stdout=log_fd,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            log_fd.close()
        PID_FILE.write_text(f"{proc.pid}\n")
        url = f"http://{bind_host}:{bind_port}/health"
        if not _wait_for_health(url, timeout=30.0, proc=proc):
            if proc.poll() is not None:
                PID_FILE.unlink(missing_ok=True)
                emit_error(
                    f"OpenSec exited (code {proc.returncode}) before /health became ready.",
                    code="start_failed",
                    hint=f"See {log_path}",
                )
            emit_error(
                f"Started detached (pid {proc.pid}) but /health did not respond within 30s.",
                code="health_timeout",
                hint=f"Check `opensec logs` and `opensec doctor`. Latest log: {log_path}",
            )
        click.echo(f"OpenSec started (pid {proc.pid}). Open http://{bind_host}:{bind_port}")
        return

    # Foreground: replace this process so signals propagate cleanly.
    os.chdir(BACKEND_DIR)
    os.execve(args[0], args, env)


@click.command(name="stop")
@click.option("--timeout", default=10.0, help="Seconds to wait before SIGKILL.")
@click.option(
    "--force",
    is_flag=True,
    help="Skip the SIGTERM grace window — SIGKILL immediately.",
)
def stop_cmd(timeout: float, force: bool) -> None:
    """Stop the running OpenSec server and reclaim any leaked child processes.

    Matching is owner-safe: a process is signalled only if its cmdline
    identifies it as ours (uvicorn for ``opensec.main:app`` or our installed
    ``$OPENSEC_HOME/bin/opencode`` binary). Anything else bound to a port we
    use is reported but never killed.
    """
    ports = _opensec_ports()

    # 1. Recorded parent: SIGTERM/SIGKILL via the pidfile path.
    pid = _read_pidfile()
    parent_killed: int | None = None
    if pid:
        sig = signal.SIGKILL if force else signal.SIGTERM
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            PID_FILE.unlink(missing_ok=True)
        else:
            deadline = time.time() + max(timeout, 0.0)
            while time.time() < deadline and _pid_alive(pid):
                time.sleep(0.2)
            if _pid_alive(pid):
                click.echo(
                    f"OpenSec did not stop within {timeout}s — sending SIGKILL.",
                    err=True,
                )
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
            PID_FILE.unlink(missing_ok=True)
            parent_killed = pid

    # 2. Sweep for OpenSec-owned orphans (parent or children still alive).
    ours = find_opensec_processes(OPENSEC_HOME)
    if parent_killed is not None:
        ours = [p for p in ours if p.pid != parent_killed]

    killed: list = []
    stuck: list = []
    if ours:
        for p in ours:
            ports_str = f" :{','.join(str(x) for x in p.ports)}" if p.ports else ""
            click.echo(f"  found stale {p.kind} pid={p.pid}{ports_str}")
        killed, stuck = kill_processes(ours, timeout=timeout, force=force)
        for p in killed:
            click.echo(f"  stopped {p.kind} pid={p.pid}")

    # 3. Report (do not signal) any port squatters.
    owned_pids = {p.pid for p in ours}
    if parent_killed is not None:
        owned_pids.add(parent_killed)
    squatters = find_port_squatters(ports, owned_pids)
    for s in squatters:
        click.echo(
            f"  port {s.port} held by pid {s.pid} (not OpenSec): {s.cmdline}",
            err=True,
        )

    # 4. Final state.
    if parent_killed is None and not ours:
        click.echo("OpenSec is not running.")
        return

    # 5. Final outcome.
    #    - PIDs still alive after our timeout: real failure, exit 1.
    #    - All our processes dead but ports still bound (kernel TIME_WAIT,
    #      socket teardown lag): not a failure, just a hint to wait briefly
    #      before `opensec start`.
    if stuck:
        emit_error(
            "Some OpenSec processes resisted shutdown.",
            code="stop_incomplete",
            hint=(
                f"PIDs still alive: {[p.pid for p in stuck]}. "
                "Try `opensec stop --force`."
            ),
            exit_code=EXIT_ERROR,
        )

    still_bound = verify_ports_free(ports)
    squatter_ports = {s.port for s in squatters}
    opensec_still_bound = [p for p in still_bound if p not in squatter_ports]
    if opensec_still_bound:
        click.echo(
            f"Note: ports {opensec_still_bound} still bound (likely TIME_WAIT). "
            "If the next `opensec start` fails with port_in_use, wait ~30s and retry.",
            err=True,
        )

    if parent_killed is not None:
        click.echo(f"OpenSec stopped (pid {parent_killed}).")
    else:
        click.echo("OpenSec stopped.")


@click.command(name="restart")
@click.option("--port", default=None, type=int, help=f"Port to bind (default: {DEFAULT_PORT}).")
@click.option("--host", default=None, help=f"Host to bind (default: {DEFAULT_HOST}).")
@click.option("--timeout", default=10.0, help="Seconds to wait before SIGKILL during stop.")
@click.option("--force", is_flag=True, help="During stop, skip SIGTERM and SIGKILL immediately.")
@click.pass_context
def restart_cmd(
    ctx: click.Context,
    port: int | None,
    host: str | None,
    timeout: float,
    force: bool,
) -> None:
    """Stop the server (and reclaim leaked children) and start it detached.

    Always runs the enhanced stop first — even with no PID file — to clean
    up orphans from a previous crash. With no flags, picks up the persistent
    port/host from ``~/.opensec/config/opensec.env``.
    """
    ctx.invoke(stop_cmd, timeout=timeout, force=force)
    ctx.invoke(start_cmd, detach=True, port=port, host=host)


@click.command(name="logs")
@click.option("--follow", "-f", is_flag=True, help="Tail the log.")
@click.option("--lines", "-n", default=100, type=int, help="Number of lines to show.")
def logs_cmd(follow: bool, lines: int) -> None:
    """Show the latest OpenSec server log."""
    if not LOG_DIR.is_dir():
        click.echo(f"No log directory: {LOG_DIR}", err=True)
        return
    log_files = sorted(LOG_DIR.glob("opensec-*.log"))
    if not log_files:
        click.echo("No logs found yet — run `opensec start --detach` first.", err=True)
        return
    latest = log_files[-1]
    args = ["tail"]
    if follow:
        args.append("-f")
    args.extend(["-n", str(lines), str(latest)])
    os.execvp("tail", args)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def _check(
    name: str,
    ok: bool,
    detail: str = "",
    *,
    expected: str = "",
    warn_only: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "detail": detail,
        "expected": expected,
        "warn_only": warn_only,
    }


def _run_version(args: list[str], timeout: float = 10.0) -> str:
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=timeout
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"error: {type(exc).__name__}"
    out = (r.stdout or r.stderr or "").strip().splitlines()
    return out[0] if out else ""


def _read_pinned_versions(path: Path) -> dict[str, str]:
    pinned: dict[str, str] = {}
    if not path.is_file():
        return pinned
    for raw in path.read_text().splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            pinned[parts[0]] = parts[1]
    return pinned


def _gather_doctor_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    # uv
    uv_bin = shutil.which("uv")
    checks.append(_check("uv", bool(uv_bin), uv_bin or "not found"))

    # venv + Python
    uvicorn_bin = VENV_BIN / "uvicorn"
    checks.append(_check("venv", uvicorn_bin.is_file(), str(uvicorn_bin)))
    py_bin = VENV_BIN / "python"
    if py_bin.is_file():
        ver = _run_version([str(py_bin), "--version"], timeout=5)
        ok = any(ver.startswith(f"Python 3.{n}") for n in (11, 12, 13))
        checks.append(_check("python", ok, ver))
    else:
        checks.append(_check("python", False, f"not found at {py_bin}"))

    # opencode binary version match
    opencode_bin = BIN_DIR / "opencode"
    expected_opencode = ""
    opencode_version_file = APP_DIR / ".opencode-version"
    if opencode_version_file.is_file():
        expected_opencode = opencode_version_file.read_text().strip()
    if opencode_bin.is_file():
        actual = _run_version([str(opencode_bin), "--version"], timeout=10)
        ok = (not expected_opencode) or expected_opencode in actual
        checks.append(_check("opencode", ok, actual or "?", expected=expected_opencode))
    else:
        checks.append(_check("opencode", False, f"not found at {opencode_bin}"))

    # trivy + semgrep against .scanner-versions
    pinned = _read_pinned_versions(APP_DIR / ".scanner-versions")
    for tool in ("trivy", "semgrep"):
        bin_path = BIN_DIR / tool
        expected = pinned.get(tool, "")
        if bin_path.is_file():
            actual = _run_version([str(bin_path), "--version"], timeout=15)
            ok = (not expected) or expected in actual
            checks.append(_check(tool, ok, actual or "?", expected=expected))
        else:
            checks.append(_check(tool, False, f"not found at {bin_path}"))

    # macOS Gatekeeper quarantine
    if sys.platform == "darwin":
        for tool in ("opencode", "trivy", "semgrep"):
            path = BIN_DIR / tool
            if not path.is_file():
                continue
            r = subprocess.run(  # noqa: S603, S607
                ["xattr", "-p", "com.apple.quarantine", str(path)],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            quarantined = r.returncode == 0 and bool(r.stdout.strip())
            checks.append(
                _check(
                    f"{tool}.quarantine",
                    not quarantined,
                    "clear" if not quarantined else f"quarantined ({r.stdout.strip()})",
                )
            )

    # git, gh
    for cmd in ("git", "gh"):
        path = shutil.which(cmd)
        checks.append(_check(cmd, bool(path), path or "not found"))

    # gh auth (warn-only — only needed for PR-creating remediations)
    if shutil.which("gh"):
        r = subprocess.run(  # noqa: S603, S607
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        first = ""
        for stream in (r.stdout, r.stderr):
            for line in stream.splitlines():
                if line.strip():
                    first = line.strip()
                    break
            if first:
                break
        checks.append(
            _check("gh.auth", r.returncode == 0, first or "unknown", warn_only=True)
        )

    # Ports — 8000 hard, the others warn-only
    for port in (DEFAULT_PORT, 4096, 4100, 4101, 4102):
        free = _port_free(port)
        warn_only = port != DEFAULT_PORT
        checks.append(
            _check(f"port.{port}", free, "free" if free else "in use", warn_only=warn_only)
        )

    # Data dir writable
    db_writable = DATA_DIR.is_dir() and os.access(DATA_DIR, os.W_OK)
    checks.append(_check("data_dir", db_writable, str(DATA_DIR)))

    # Migrations + API key from DB (warn-only when DB is absent — first run)
    db_path = DATA_DIR / "opensec.db"
    api_key_set = False
    if db_path.is_file():
        try:
            con = sqlite3.connect(str(db_path))
            try:
                cur = con.execute("SELECT COUNT(*) FROM _migrations")
                count = int(cur.fetchone()[0])
                checks.append(_check("migrations", count > 0, f"{count} applied"))
            except sqlite3.DatabaseError as exc:
                checks.append(_check("migrations", False, str(exc)))

            try:
                cur = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='credentials'"
                )
                if cur.fetchone():
                    cur = con.execute("SELECT COUNT(*) FROM credentials")
                    api_key_set = int(cur.fetchone()[0]) > 0
            except sqlite3.DatabaseError:
                pass
            con.close()
        except sqlite3.Error as exc:
            checks.append(_check("migrations", False, f"sqlite error: {exc}"))
    else:
        checks.append(
            _check("migrations", True, "no DB yet (created on first start)", warn_only=True)
        )

    checks.append(
        _check(
            "api_key",
            api_key_set,
            "configured"
            if api_key_set
            else "not set — paste in Settings UI after `opensec start`",
            warn_only=True,
        )
    )

    # OPENSEC_CREDENTIAL_KEY in env file
    env = _read_env_file(ENV_FILE)
    has_cred_key = bool(env.get("OPENSEC_CREDENTIAL_KEY"))
    checks.append(
        _check(
            "credential_key",
            has_cred_key,
            "set" if has_cred_key else f"missing in {ENV_FILE}",
        )
    )

    return checks


@click.command(name="doctor")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON envelope (for agents).")
def doctor_cmd(as_json: bool) -> None:
    """Diagnose the local install — does not start the daemon."""
    checks = _gather_doctor_checks()
    failing = [c for c in checks if not c["ok"] and not c["warn_only"]]
    warnings = [c for c in checks if not c["ok"] and c["warn_only"]]
    healthy = not failing

    if as_json:
        emit(
            {
                "healthy": healthy,
                "checks": checks,
                "failing": [c["name"] for c in failing],
                "warnings": [c["name"] for c in warnings],
            },
            exit_code=EXIT_OK if healthy else EXIT_ERROR,
        )

    for c in checks:
        if c["ok"]:
            sym = click.style("ok ", fg="green")
        elif c["warn_only"]:
            sym = click.style("warn", fg="yellow")
        else:
            sym = click.style("FAIL", fg="red")
        detail = c["detail"]
        if c["expected"] and not c["ok"]:
            detail = f"{detail}  (expected {c['expected']})"
        click.echo(f"  [{sym}] {c['name']:<24} {detail}")

    click.echo()
    if healthy:
        click.echo(click.style("OpenSec is ready.", fg="green"))
        if warnings:
            click.echo(
                click.style(
                    f"({len(warnings)} warning(s) — see entries marked 'warn' above.)",
                    fg="yellow",
                )
            )
    else:
        click.echo(
            click.style(
                f"{len(failing)} check(s) failing — fix the lines marked 'FAIL'.",
                fg="red",
            )
        )
        sys.exit(EXIT_ERROR)


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


@click.group(name="config")
def config_group() -> None:
    """Manage ~/.opensec/config/opensec.env."""


@config_group.command("path")
def config_path() -> None:
    """Print the env file path."""
    click.echo(str(ENV_FILE))


@config_group.command("get")
@click.argument("key")
def config_get(key: str) -> None:
    """Print one env var."""
    env = _read_env_file(ENV_FILE)
    click.echo(env.get(key, ""))


@config_group.command("set")
@click.argument("assignment")
def config_set(assignment: str) -> None:
    """Set KEY=VALUE in the env file (creates file if absent)."""
    if "=" not in assignment:
        emit_error("Use KEY=VALUE format.", code="bad_arg", exit_code=EXIT_ERROR)
    key, _, value = assignment.partition("=")
    key = key.strip()
    if not key:
        emit_error("Empty key.", code="bad_arg", exit_code=EXIT_ERROR)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if ENV_FILE.is_file():
        for raw in ENV_FILE.read_text().splitlines():
            stripped = raw.strip()
            if stripped.startswith("#") or "=" not in stripped:
                lines.append(raw)
                continue
            existing_key, _, _ = stripped.partition("=")
            if existing_key.strip() == key:
                continue
            lines.append(raw)
    lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n")
    os.chmod(ENV_FILE, 0o600)
    click.echo(f"Set {key} in {ENV_FILE}")


@config_group.command("edit")
def config_edit() -> None:
    """Open the env file in $EDITOR."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not ENV_FILE.is_file():
        ENV_FILE.write_text("# OpenSec environment overrides\n")
        os.chmod(ENV_FILE, 0o600)
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    parts = editor.split()
    os.execvp(parts[0], [*parts, str(ENV_FILE)])


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------


@click.command(name="uninstall")
@click.option("--keep-data", is_flag=True, help="Preserve ~/.opensec/data/ and ~/.opensec/config/.")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
@click.pass_context
def uninstall_cmd(ctx: click.Context, keep_data: bool, yes: bool) -> None:
    """Remove the local OpenSec install.

    Stops the daemon (and any leaked children) first, then removes the
    install directories. Port squatters are reported but never signalled.
    """
    # 1. Always try to stop first — orphans may exist even with no PID file.
    ctx.invoke(stop_cmd, timeout=10.0, force=yes)

    # 2. After stop, refuse to remove files if any of our processes are
    #    still alive on our ports. We never rm -rf over a live process.
    ours = find_opensec_processes(OPENSEC_HOME)
    if ours:
        emit_error(
            "OpenSec processes are still running after stop — refusing to remove files.",
            code="still_running",
            hint=f"PIDs: {[p.pid for p in ours]}. Try `opensec stop --force`.",
        )

    targets: list[Path] = [APP_DIR, BIN_DIR, RUN_DIR, CLI_VENV_DIR]
    if not keep_data:
        targets.extend([DATA_DIR, CONFIG_DIR])

    local_bin = Path.home() / ".local" / "bin" / "opensec"

    if not yes:
        click.echo("Will remove:")
        for t in targets:
            if t.exists():
                click.echo(f"  {t}")
        if local_bin.is_symlink() or local_bin.is_file():
            click.echo(f"  {local_bin}")
        if keep_data:
            click.echo("\nPreserved (--keep-data):")
            for t in (DATA_DIR, CONFIG_DIR):
                if t.exists():
                    click.echo(f"  {t}")
        if not click.confirm("\nProceed?"):
            click.echo("Aborted.")
            return

    for t in targets:
        if t.is_dir():
            shutil.rmtree(t, ignore_errors=True)
            click.echo(f"  removed {t}")

    if local_bin.is_symlink() or local_bin.is_file():
        try:
            local_bin.unlink()
            click.echo(f"  removed {local_bin}")
        except OSError:
            pass

    if OPENSEC_HOME.is_dir() and not any(OPENSEC_HOME.iterdir()):
        try:
            OPENSEC_HOME.rmdir()
            click.echo(f"  removed {OPENSEC_HOME}")
        except OSError:
            pass

    click.echo("\nOpenSec uninstalled.")
