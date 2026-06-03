"""Unit tests for the owner-safe process sweeper.

All ``psutil`` interaction is mocked — these tests never touch real processes
or sockets (except the bind-probe in ``verify_ports_free``, which is checked
against an actual loopback listener for one case).
"""

from __future__ import annotations

import signal
import socket
from collections import namedtuple
from unittest.mock import MagicMock

import psutil
import pytest

from cliff_cli.process_sweep import (
    FoundProcess,
    PortSquatter,
    find_cliff_processes,
    find_port_squatters,
    kill_processes,
    verify_ports_free,
)

_UVICORN = [".venv/bin/uvicorn", "cliff.main:app", "--port", "8000"]

_LAddr = namedtuple("_LAddr", ["ip", "port"])
_Conn = namedtuple("_Conn", ["fd", "family", "type", "laddr", "raddr", "status", "pid"])


def _make_proc(
    pid: int,
    cmdline: list[str],
    *,
    exe: str = "",
    same_user: bool = True,
    raise_on: str | None = None,
):
    """Build a MagicMock standing in for ``psutil.Process``."""
    proc = MagicMock()
    proc.pid = pid

    def _cmdline():
        if raise_on == "cmdline":
            raise psutil.AccessDenied(pid)
        return cmdline

    def _exe():
        if raise_on == "exe":
            raise psutil.AccessDenied(pid)
        return exe

    def _uids():
        if raise_on == "uids":
            raise psutil.AccessDenied(pid)
        UIDs = namedtuple("UIDs", ["real", "effective", "saved"])
        return UIDs(real=1000 if same_user else 9999, effective=1000, saved=1000)

    proc.cmdline.side_effect = _cmdline
    proc.exe.side_effect = _exe
    proc.uids.side_effect = _uids
    return proc


@pytest.fixture(autouse=True)
def _stub_user_ids(monkeypatch):
    monkeypatch.setattr("cliff_cli.process_sweep.os.getuid", lambda: 1000)
    monkeypatch.setattr("cliff_cli.process_sweep.os.getpid", lambda: 99999)


def _patch_iter(monkeypatch, procs):
    monkeypatch.setattr(
        "cliff_cli.process_sweep.psutil.process_iter",
        lambda attrs=None: iter(procs),
    )


def _patch_conns(monkeypatch, conns):
    monkeypatch.setattr(
        "cliff_cli.process_sweep.psutil.net_connections",
        lambda kind="inet": list(conns),
    )


# ---------------------------------------------------------------------------
# find_cliff_processes — ownership rule (the critical safety contract)
#
# The agent substrate runs in-process now (ADR-0047), so the only Cliff-owned
# process is the uvicorn parent. There are no child binaries to reap.
# ---------------------------------------------------------------------------


def test_finds_parent_uvicorn(monkeypatch):
    proc = _make_proc(100, _UVICORN)
    _patch_iter(monkeypatch, [proc])
    _patch_conns(
        monkeypatch,
        [_Conn(0, 0, 0, _LAddr("127.0.0.1", 8000), None, psutil.CONN_LISTEN, 100)],
    )
    found = find_cliff_processes()
    assert len(found) == 1
    assert found[0].pid == 100
    assert found[0].kind == "uvicorn"
    assert 8000 in found[0].ports


def test_does_not_match_arbitrary_listener_on_known_port(monkeypatch):
    """The app port alone must not be sufficient — cmdline must prove ownership."""
    proc = _make_proc(104, ["nc", "-l", "8000"])
    _patch_iter(monkeypatch, [proc])
    _patch_conns(
        monkeypatch,
        [_Conn(0, 0, 0, _LAddr("127.0.0.1", 8000), None, psutil.CONN_LISTEN, 104)],
    )
    found = find_cliff_processes()
    assert found == []


def test_does_not_match_uvicorn_for_other_app(monkeypatch):
    proc = _make_proc(105, ["uvicorn", "other_app.main:app"])
    _patch_iter(monkeypatch, [proc])
    _patch_conns(monkeypatch, [])
    found = find_cliff_processes()
    assert found == []


def test_skips_processes_owned_by_other_users(monkeypatch):
    proc = _make_proc(106, _UVICORN, same_user=False)
    _patch_iter(monkeypatch, [proc])
    _patch_conns(monkeypatch, [])
    found = find_cliff_processes()
    assert found == []


def test_swallows_access_denied(monkeypatch):
    """Inaccessible process must not crash the sweep."""
    bad = _make_proc(107, [], raise_on="cmdline")
    good = _make_proc(108, _UVICORN)
    _patch_iter(monkeypatch, [bad, good])
    _patch_conns(monkeypatch, [])
    found = find_cliff_processes()
    assert [f.pid for f in found] == [108]


def test_skips_self_pid(monkeypatch):
    """The CLI must never match itself even if it happened to exec uvicorn."""
    proc = _make_proc(99999, ["uvicorn", "cliff.main:app"])
    _patch_iter(monkeypatch, [proc])
    _patch_conns(monkeypatch, [])
    found = find_cliff_processes()
    assert found == []


def test_swallows_net_connections_access_denied(monkeypatch):
    """psutil.net_connections raises AccessDenied on macOS w/o root — fallback
    to per-process scan handles it without crashing."""
    proc = _make_proc(109, _UVICORN)
    proc.net_connections.return_value = []

    def _raise(kind="inet"):
        raise psutil.AccessDenied(0)

    monkeypatch.setattr(
        "cliff_cli.process_sweep.psutil.process_iter",
        lambda attrs=None: iter([proc]),
    )
    monkeypatch.setattr("cliff_cli.process_sweep.psutil.net_connections", _raise)
    found = find_cliff_processes()
    assert len(found) == 1
    assert found[0].ports == ()


def test_macos_fallback_finds_owned_process_listening_port(monkeypatch):
    """When system net_connections is denied, per-process net_connections
    must take over so we still get the port -> pid mapping for owned procs.
    Regression test for the bug found during the macOS e2e smoke check."""
    fake_laddr = _LAddr("127.0.0.1", 8000)
    listening_conn = _Conn(0, 0, 0, fake_laddr, None, psutil.CONN_LISTEN, None)

    proc = _make_proc(120, _UVICORN)
    proc.net_connections.return_value = [listening_conn]

    def _denied(kind="inet"):
        raise psutil.AccessDenied(0)

    monkeypatch.setattr(
        "cliff_cli.process_sweep.psutil.process_iter",
        lambda attrs=None: iter([proc]),
    )
    monkeypatch.setattr("cliff_cli.process_sweep.psutil.net_connections", _denied)
    found = find_cliff_processes()
    assert len(found) == 1
    assert found[0].pid == 120
    # Critical: per-process fallback recovered the listening port.
    assert 8000 in found[0].ports


def test_macos_fallback_reports_squatter(monkeypatch):
    """End-to-end equivalent of the macOS gap caught during e2e verification:
    psutil.net_connections raises AccessDenied; squatter must still be
    reported via the per-process fallback."""
    fake_laddr = _LAddr("127.0.0.1", 8000)
    listening_conn = _Conn(0, 0, 0, fake_laddr, None, psutil.CONN_LISTEN, None)

    squatter_proc = _make_proc(200, ["python3", "-c", "import socket..."])
    squatter_proc.net_connections.return_value = [listening_conn]

    def _denied(kind="inet"):
        raise psutil.AccessDenied(0)

    monkeypatch.setattr(
        "cliff_cli.process_sweep.psutil.process_iter",
        lambda attrs=None: iter([squatter_proc]),
    )
    monkeypatch.setattr("cliff_cli.process_sweep.psutil.net_connections", _denied)
    monkeypatch.setattr(
        "cliff_cli.process_sweep.psutil.Process", lambda pid: squatter_proc
    )
    squatters = find_port_squatters([8000], owned_pids=set())
    assert len(squatters) == 1
    assert squatters[0].pid == 200
    assert squatters[0].port == 8000


# ---------------------------------------------------------------------------
# find_port_squatters — never signal, only report
# ---------------------------------------------------------------------------


def test_squatter_on_known_port_is_reported(monkeypatch):
    _patch_conns(
        monkeypatch,
        [_Conn(0, 0, 0, _LAddr("127.0.0.1", 8000), None, psutil.CONN_LISTEN, 200)],
    )

    def _proc_factory(pid):
        return _make_proc(pid, ["nc", "-l", "8000"])

    monkeypatch.setattr("cliff_cli.process_sweep.psutil.Process", _proc_factory)
    squatters = find_port_squatters([8000, 8765], owned_pids=set())
    assert squatters == [PortSquatter(pid=200, port=8000, cmdline="nc -l 8000")]


def test_squatter_excludes_owned_pids(monkeypatch):
    _patch_conns(
        monkeypatch,
        [_Conn(0, 0, 0, _LAddr("127.0.0.1", 8000), None, psutil.CONN_LISTEN, 201)],
    )
    squatters = find_port_squatters([8000], owned_pids={201})
    assert squatters == []


def test_squatter_handles_inaccessible_process(monkeypatch):
    _patch_conns(
        monkeypatch,
        [_Conn(0, 0, 0, _LAddr("127.0.0.1", 8000), None, psutil.CONN_LISTEN, 202)],
    )

    def _raise(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr("cliff_cli.process_sweep.psutil.Process", _raise)
    squatters = find_port_squatters([8000], owned_pids=set())
    assert len(squatters) == 1
    assert squatters[0].cmdline == "<inaccessible>"


# ---------------------------------------------------------------------------
# kill_processes
# ---------------------------------------------------------------------------


def test_kill_processes_sigterms_and_returns_killed(monkeypatch):
    procs = [FoundProcess(pid=300, kind="uvicorn", cmdline="uvicorn cliff.main:app")]
    sent: list[tuple[int, int]] = []

    def _kill(pid, sig):
        sent.append((pid, sig))

    pid_exists_state = {300: True}

    def _pid_exists(pid):
        # First call -> alive (so we enter the loop). Then dead.
        v = pid_exists_state[pid]
        pid_exists_state[pid] = False
        return v

    monkeypatch.setattr("cliff_cli.process_sweep.os.kill", _kill)
    monkeypatch.setattr("cliff_cli.process_sweep.psutil.pid_exists", _pid_exists)
    killed, alive = kill_processes(procs, timeout=2.0)
    assert sent == [(300, signal.SIGTERM)]
    assert [p.pid for p in killed] == [300]
    assert alive == []


def test_kill_processes_force_uses_sigkill(monkeypatch):
    procs = [FoundProcess(pid=301, kind="uvicorn", cmdline="...")]
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "cliff_cli.process_sweep.os.kill",
        lambda pid, sig: sent.append((pid, sig)),
    )
    monkeypatch.setattr("cliff_cli.process_sweep.psutil.pid_exists", lambda pid: False)
    killed, alive = kill_processes(procs, timeout=1.0, force=True)
    assert sent == [(301, signal.SIGKILL)]
    assert [p.pid for p in killed] == [301]
    assert alive == []


def test_kill_processes_escalates_to_sigkill_on_timeout(monkeypatch):
    procs = [FoundProcess(pid=302, kind="uvicorn", cmdline="...")]
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "cliff_cli.process_sweep.os.kill",
        lambda pid, sig: sent.append((pid, sig)),
    )
    # Stays alive through the SIGTERM grace, then dies after SIGKILL.
    state = {"alive": True}

    def _pid_exists(pid):
        return state["alive"]

    monkeypatch.setattr("cliff_cli.process_sweep.psutil.pid_exists", _pid_exists)
    monkeypatch.setattr("cliff_cli.process_sweep.time.sleep", lambda *_: None)

    # After SIGKILL is sent, simulate the kernel reaping.
    def _after_kill(pid, sig):
        sent.append((pid, sig))
        if sig == signal.SIGKILL:
            state["alive"] = False

    monkeypatch.setattr("cliff_cli.process_sweep.os.kill", _after_kill)
    killed, alive = kill_processes(procs, timeout=0.05)
    assert (302, signal.SIGTERM) in sent
    assert (302, signal.SIGKILL) in sent
    assert [p.pid for p in killed] == [302]
    assert alive == []


def test_kill_processes_swallows_process_lookup_error(monkeypatch):
    procs = [FoundProcess(pid=303, kind="uvicorn", cmdline="...")]

    def _kill(pid, sig):
        raise ProcessLookupError(pid)

    monkeypatch.setattr("cliff_cli.process_sweep.os.kill", _kill)
    monkeypatch.setattr("cliff_cli.process_sweep.psutil.pid_exists", lambda pid: False)
    killed, alive = kill_processes(procs, timeout=0.1)
    # Already gone counts as killed.
    assert [p.pid for p in killed] == [303]


def test_kill_processes_returns_still_alive_when_kill_fails(monkeypatch):
    procs = [FoundProcess(pid=304, kind="uvicorn", cmdline="...")]
    monkeypatch.setattr("cliff_cli.process_sweep.os.kill", lambda *_: None)
    monkeypatch.setattr("cliff_cli.process_sweep.psutil.pid_exists", lambda pid: True)
    monkeypatch.setattr("cliff_cli.process_sweep.time.sleep", lambda *_: None)
    killed, alive = kill_processes(procs, timeout=0.05)
    assert [p.pid for p in alive] == [304]
    assert killed == []


def test_kill_processes_empty_list_is_noop():
    killed, alive = kill_processes([], timeout=10.0)
    assert killed == [] and alive == []


# ---------------------------------------------------------------------------
# verify_ports_free
# ---------------------------------------------------------------------------


def test_verify_ports_free_reports_bound_subset():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen()
    bound_port = s.getsockname()[1]
    try:
        # The bound port plus a port we believe is free.
        result = verify_ports_free([bound_port, 1])
        assert bound_port in result
        # Port 1 is privileged on macOS/Linux for non-root — bind() fails
        # with EACCES, so it'll appear in the result too. We only assert
        # the specific port we definitely bound.
    finally:
        s.close()


def test_verify_ports_free_empty_when_all_free():
    # Use ephemeral port that we just released. Cannot guarantee it's free
    # the next instant — instead use port 0 semantics by binding/closing.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    free_port = s.getsockname()[1]
    s.close()
    # There's a tiny TOCTOU window but in practice this works.
    result = verify_ports_free([free_port])
    assert result == []
