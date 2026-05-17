"""Unit tests for the daemon-management module helpers.

These don't start a real daemon — they exercise the small pure helpers in
:mod:`cliff_cli.daemon`. Process-level behaviour (start/stop/restart) is
covered end-to-end by ``tests/install/smoke.sh``.
"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Re-import the daemon module with CLIFF_HOME pointed at a tmpdir.

    The module reads CLIFF_HOME at import time, so we have to reload it
    after monkeypatching the env var.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CLIFF_HOME", str(home))
    import importlib

    import cliff_cli.daemon as daemon_mod

    importlib.reload(daemon_mod)
    return home, daemon_mod


# ---------------------------------------------------------------------------
# env file parsing
# ---------------------------------------------------------------------------


def test_read_env_file_basic(fake_home):
    home, daemon = fake_home
    env_file = home / "config" / "cliff.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text(
        "# comment\n"
        "FOO=bar\n"
        "\n"
        "  TRIMMED  =  spaced  \n"
        'QUOTED="quoted value"\n'
        "SINGLE='also quoted'\n"
        "BARE_EQ=\n"
    )
    out = daemon._read_env_file(env_file)
    assert out == {
        "FOO": "bar",
        "TRIMMED": "spaced",
        "QUOTED": "quoted value",
        "SINGLE": "also quoted",
        "BARE_EQ": "",
    }


def test_read_env_file_missing_returns_empty(tmp_path):
    from cliff_cli.daemon import _read_env_file

    assert _read_env_file(tmp_path / "nope.env") == {}


# ---------------------------------------------------------------------------
# pid handling
# ---------------------------------------------------------------------------


def test_pid_alive_for_self():
    from cliff_cli.daemon import _pid_alive

    assert _pid_alive(os.getpid()) is True


def test_pid_alive_for_unused_pid():
    from cliff_cli.daemon import _pid_alive

    # PID 999999 is well above any sensible system limit on test runners.
    assert _pid_alive(999_999) is False


def test_read_pidfile_strips_stale(fake_home):
    home, daemon = fake_home
    daemon.RUN_DIR.mkdir(parents=True)
    daemon.PID_FILE.write_text("999999\n")
    assert daemon._read_pidfile() is None
    # Side-effect: stale pidfile is unlinked so future reads see a fresh state.
    assert not daemon.PID_FILE.exists()


def test_read_pidfile_returns_live_pid(fake_home):
    home, daemon = fake_home
    daemon.RUN_DIR.mkdir(parents=True)
    daemon.PID_FILE.write_text(f"{os.getpid()}\n")
    assert daemon._read_pidfile() == os.getpid()


# ---------------------------------------------------------------------------
# port probe
# ---------------------------------------------------------------------------


def test_port_free_then_in_use():
    from cliff_cli.daemon import _port_free

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.listen(1)
    try:
        assert _port_free(port) is False
    finally:
        s.close()
    # Once released, the same port should be reported free again. We may
    # need a tiny wait on macOS due to TIME_WAIT, so loop a couple of times.
    for _ in range(5):
        if _port_free(port):
            break
    else:
        pytest.fail(f"port {port} stayed marked in-use after socket close")


# ---------------------------------------------------------------------------
# config commands
# ---------------------------------------------------------------------------


def test_config_set_and_get_roundtrip(fake_home, monkeypatch):
    home, daemon = fake_home
    # Re-import cli so it picks up the reloaded daemon module.
    import importlib

    import cliff_cli.cli as cli_mod

    importlib.reload(cli_mod)

    runner = CliRunner()
    res = runner.invoke(cli_mod.main, ["config", "set", "MY_KEY=my-value"])
    assert res.exit_code == 0, res.output
    res = runner.invoke(cli_mod.main, ["config", "get", "MY_KEY"])
    assert res.exit_code == 0
    assert res.output.strip() == "my-value"

    # Overwrite — `config set` should replace, not append.
    runner.invoke(cli_mod.main, ["config", "set", "MY_KEY=second"])
    res = runner.invoke(cli_mod.main, ["config", "get", "MY_KEY"])
    assert res.output.strip() == "second"

    # File permissions should be 0600 (the env file holds CLIFF_CREDENTIAL_KEY).
    mode = oct(daemon.ENV_FILE.stat().st_mode & 0o777)
    assert mode == "0o600"


# ---------------------------------------------------------------------------
# stop / restart / uninstall — owner-safe lifecycle
# ---------------------------------------------------------------------------


@pytest.fixture
def stop_env(fake_home, monkeypatch):
    """Daemon module + canned process_sweep stubs for stop/restart/uninstall tests.

    Returns a dict with mutable state so tests can adjust the stubs:
      - owned: list[FoundProcess] returned by find_cliff_processes
      - squatters: list[PortSquatter] returned by find_port_squatters
      - bound_ports: list[int] returned by verify_ports_free
      - kills: tuple[killed, alive] returned by kill_processes
      - kill_calls: list of (pids, force) tuples recorded for assertions
      - sigs: list of (pid, sig) tuples recorded by os.kill in the parent path
      - alive_pids: set of pids that _pid_alive should report as alive
    """
    home, daemon = fake_home
    from cliff_cli.process_sweep import FoundProcess, PortSquatter

    state = {
        "owned": [],
        "squatters": [],
        "bound_ports": [],
        "kills": ([], []),
        "kill_calls": [],
        "sigs": [],
        "alive_pids": set(),
    }

    monkeypatch.setattr(daemon, "find_cliff_processes", lambda home_: list(state["owned"]))
    monkeypatch.setattr(
        daemon,
        "find_port_squatters",
        lambda ports, owned_pids: list(state["squatters"]),
    )
    monkeypatch.setattr(daemon, "verify_ports_free", lambda ports: list(state["bound_ports"]))

    def _kill_processes(procs, timeout=10.0, force=False):
        state["kill_calls"].append(([p.pid for p in procs], force))
        return state["kills"]

    monkeypatch.setattr(daemon, "kill_processes", _kill_processes)

    def _os_kill(pid, sig):
        state["sigs"].append((pid, sig))
        # SIGTERM/SIGKILL on a "dead" pid raises ProcessLookupError.
        if pid not in state["alive_pids"]:
            raise ProcessLookupError(pid)
        if sig == 9:  # SIGKILL flips it dead
            state["alive_pids"].discard(pid)

    monkeypatch.setattr(daemon.os, "kill", _os_kill)

    def _pid_alive(pid):
        return pid in state["alive_pids"]

    monkeypatch.setattr(daemon, "_pid_alive", _pid_alive)
    monkeypatch.setattr(daemon.time, "sleep", lambda *_: None)

    return home, daemon, state, FoundProcess, PortSquatter


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def test_stop_says_not_running_when_no_pidfile_and_no_owned(stop_env):
    home, daemon, state, *_ = stop_env
    runner = CliRunner()
    res = runner.invoke(daemon.stop_cmd)
    assert res.exit_code == 0
    assert res.output.strip() == "Cliff is not running."
    # Crucially: no signals sent.
    assert state["sigs"] == []
    assert state["kill_calls"] == []


def test_stop_kills_recorded_parent_via_pidfile(stop_env, tmp_path):
    home, daemon, state, *_ = stop_env
    daemon.RUN_DIR.mkdir(parents=True, exist_ok=True)
    daemon.PID_FILE.write_text("4242\n")
    state["alive_pids"] = {4242}
    runner = CliRunner()
    res = runner.invoke(daemon.stop_cmd, ["--force"])
    assert res.exit_code == 0
    # --force => SIGKILL (signal.SIGKILL == 9 on POSIX)
    assert (4242, 9) in state["sigs"]
    assert not daemon.PID_FILE.exists()


def test_stop_kills_owned_orphan_when_no_pidfile(stop_env):
    home, daemon, state, FoundProcess, _ = stop_env  # noqa: N806
    state["owned"] = [
        FoundProcess(pid=5000, kind="opencode", cmdline="opencode serve", ports=(4096,))
    ]
    state["kills"] = (state["owned"], [])
    runner = CliRunner()
    res = runner.invoke(daemon.stop_cmd)
    assert res.exit_code == 0
    assert state["kill_calls"] == [([5000], False)]
    assert "found stale opencode pid=5000" in res.output


def test_stop_with_force_passes_force_to_killer(stop_env):
    home, daemon, state, FoundProcess, _ = stop_env  # noqa: N806
    state["owned"] = [FoundProcess(pid=5001, kind="opencode", cmdline="...")]
    state["kills"] = (state["owned"], [])
    runner = CliRunner()
    res = runner.invoke(daemon.stop_cmd, ["--force"])
    assert res.exit_code == 0
    assert state["kill_calls"] == [([5001], True)]


def test_stop_reports_squatter_but_does_not_signal_it(stop_env):
    home, daemon, state, _, PortSquatter = stop_env  # noqa: N806
    # No owned processes; just an unrelated listener on 4096.
    state["squatters"] = [PortSquatter(pid=9000, port=4096, cmdline="nc -l 4096")]
    runner = CliRunner()
    res = runner.invoke(daemon.stop_cmd)
    # No owned procs found => still says "not running" and never signals.
    assert res.exit_code == 0
    assert state["sigs"] == []
    assert state["kill_calls"] == []
    assert "Cliff is not running." in res.output
    # Squatter is reported on stderr (or mixed_output for CliRunner).
    assert "9000" in res.output and "not Cliff" in res.output


def test_stop_uses_configured_port_from_env_file(stop_env):
    """CLIFF_APP_PORT in env file must be picked up by the sweep."""
    home, daemon, state, *_ = stop_env
    daemon.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    daemon.ENV_FILE.write_text("CLIFF_APP_PORT=8765\n")
    captured: dict = {}

    def _fps(ports, owned_pids):
        captured["ports"] = list(ports)
        return []

    import cliff_cli.daemon as d
    d.find_port_squatters = _fps  # noqa: SLF001 — direct attr write for the test
    runner = CliRunner()
    runner.invoke(d.stop_cmd)
    assert 8765 in captured["ports"]
    # And the workspace range / opencode singleton are still there.
    assert 4096 in captured["ports"]
    assert 4150 in captured["ports"]


def test_stop_errors_when_processes_resist_shutdown(stop_env):
    home, daemon, state, FoundProcess, _ = stop_env  # noqa: N806
    state["owned"] = [FoundProcess(pid=5010, kind="opencode", cmdline="...")]
    state["kills"] = ([], state["owned"])  # nothing killed, all stuck
    state["bound_ports"] = [4096]
    runner = CliRunner()
    res = runner.invoke(daemon.stop_cmd)
    assert res.exit_code == 1
    assert "stop_incomplete" in res.output


def test_stop_succeeds_when_pids_dead_but_ports_linger(stop_env):
    """Kernel TIME_WAIT after our processes die: warn, don't fail."""
    home, daemon, state, FoundProcess, _ = stop_env  # noqa: N806
    state["owned"] = [FoundProcess(pid=5020, kind="opencode", cmdline="...")]
    state["kills"] = (state["owned"], [])  # all dead
    state["bound_ports"] = [4096]  # but kernel hasn't released yet
    runner = CliRunner()
    res = runner.invoke(daemon.stop_cmd)
    assert res.exit_code == 0, res.output
    assert "TIME_WAIT" in res.output


def test_stop_succeeds_when_remaining_bound_ports_are_squatter_held(stop_env):
    """Ports still bound by squatters must NOT count against stop."""
    home, daemon, state, FoundProcess, PortSquatter = stop_env  # noqa: N806
    state["owned"] = [FoundProcess(pid=5011, kind="opencode", cmdline="...")]
    state["kills"] = (state["owned"], [])
    state["squatters"] = [PortSquatter(pid=9001, port=4096, cmdline="nc -l 4096")]
    state["bound_ports"] = [4096]  # only the squatter
    runner = CliRunner()
    res = runner.invoke(daemon.stop_cmd)
    assert res.exit_code == 0
    assert "stop_incomplete" not in res.output


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------


def test_restart_invokes_stop_then_start(stop_env, monkeypatch):
    home, daemon, state, *_ = stop_env
    calls: list[tuple[str, dict]] = []

    def _fake_stop(timeout, force):
        calls.append(("stop", {"timeout": timeout, "force": force}))

    def _fake_start(detach, port, host):
        calls.append(("start", {"detach": detach, "port": port, "host": host}))

    monkeypatch.setattr(daemon.stop_cmd, "callback", _fake_stop)
    monkeypatch.setattr(daemon.start_cmd, "callback", _fake_start)
    runner = CliRunner()
    res = runner.invoke(daemon.restart_cmd, ["--port", "8765", "--force"])
    assert res.exit_code == 0
    assert [c[0] for c in calls] == ["stop", "start"]
    assert calls[0][1]["force"] is True
    assert calls[1][1]["port"] == 8765
    assert calls[1][1]["detach"] is True


def test_restart_runs_stop_even_with_no_pidfile(stop_env, monkeypatch):
    """Stop must always run during restart so orphans get swept."""
    home, daemon, state, *_ = stop_env
    stop_called = {"n": 0}

    def _fake_stop(timeout, force):
        stop_called["n"] += 1

    def _fake_start(detach, port, host):
        pass

    monkeypatch.setattr(daemon.stop_cmd, "callback", _fake_stop)
    monkeypatch.setattr(daemon.start_cmd, "callback", _fake_start)
    runner = CliRunner()
    runner.invoke(daemon.restart_cmd)
    assert stop_called["n"] == 1


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------


def test_uninstall_invokes_stop_then_removes_paths(stop_env, monkeypatch):
    home, daemon, state, *_ = stop_env
    daemon.APP_DIR.mkdir(parents=True)
    daemon.BIN_DIR.mkdir(parents=True)
    daemon.RUN_DIR.mkdir(parents=True, exist_ok=True)
    daemon.DATA_DIR.mkdir(parents=True, exist_ok=True)
    daemon.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    daemon.CLI_VENV_DIR.mkdir(parents=True)

    stop_called = {"n": 0}

    def _bump(timeout, force):
        stop_called["n"] += 1

    monkeypatch.setattr(daemon.stop_cmd, "callback", _bump)

    runner = CliRunner()
    res = runner.invoke(daemon.uninstall_cmd, ["--yes"])
    assert res.exit_code == 0
    assert stop_called["n"] == 1
    assert not daemon.APP_DIR.exists()
    assert not daemon.BIN_DIR.exists()
    assert not daemon.DATA_DIR.exists()
    assert not daemon.CONFIG_DIR.exists()
    assert not daemon.CLI_VENV_DIR.exists()


def test_uninstall_keep_data_preserves_data_and_config(stop_env, monkeypatch):
    home, daemon, state, *_ = stop_env
    daemon.APP_DIR.mkdir(parents=True)
    daemon.BIN_DIR.mkdir(parents=True)
    daemon.DATA_DIR.mkdir(parents=True, exist_ok=True)
    daemon.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    daemon.CLI_VENV_DIR.mkdir(parents=True)
    monkeypatch.setattr(daemon.stop_cmd, "callback", lambda timeout, force: None)

    runner = CliRunner()
    res = runner.invoke(daemon.uninstall_cmd, ["--yes", "--keep-data"])
    assert res.exit_code == 0
    assert not daemon.APP_DIR.exists()
    assert not daemon.CLI_VENV_DIR.exists()
    assert daemon.DATA_DIR.exists()
    assert daemon.CONFIG_DIR.exists()


def test_uninstall_aborts_if_processes_still_running_after_stop(stop_env, monkeypatch):
    home, daemon, state, FoundProcess, _ = stop_env  # noqa: N806
    daemon.APP_DIR.mkdir(parents=True)
    monkeypatch.setattr(daemon.stop_cmd, "callback", lambda timeout, force: None)
    state["owned"] = [FoundProcess(pid=7000, kind="opencode", cmdline="...")]

    runner = CliRunner()
    res = runner.invoke(daemon.uninstall_cmd, ["--yes"])
    assert res.exit_code == 1
    assert "still running" in res.output.lower()
    # Must not have removed any files.
    assert daemon.APP_DIR.exists()


def test_uninstall_without_yes_and_declined_removes_nothing(stop_env, monkeypatch):
    home, daemon, state, *_ = stop_env
    daemon.APP_DIR.mkdir(parents=True)
    monkeypatch.setattr(daemon.stop_cmd, "callback", lambda timeout, force: None)
    runner = CliRunner()
    res = runner.invoke(daemon.uninstall_cmd, input="n\n")
    assert res.exit_code == 0
    assert "Aborted." in res.output
    assert daemon.APP_DIR.exists()


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def test_doctor_json_envelope_on_empty_home(fake_home):
    home, daemon = fake_home
    import importlib

    import cliff_cli.cli as cli_mod

    importlib.reload(cli_mod)

    runner = CliRunner()
    res = runner.invoke(cli_mod.main, ["doctor", "--json"])
    # Empty home -> failing checks -> non-zero exit.
    assert res.exit_code != 0
    payload = json.loads(res.output.strip().splitlines()[-1])
    assert payload["healthy"] is False
    assert "venv" in payload["failing"]
    # The shape is stable: every check is named.
    names = {c["name"] for c in payload["checks"]}
    expected = {"uv", "venv", "python", "opencode", "trivy", "semgrep", "credential_key"}
    assert expected.issubset(names)
