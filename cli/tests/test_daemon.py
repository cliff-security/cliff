"""Unit tests for the daemon-management module helpers.

These don't start a real daemon — they exercise the small pure helpers in
:mod:`opensec_cli.daemon`. Process-level behaviour (start/stop/restart) is
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
    """Re-import the daemon module with OPENSEC_HOME pointed at a tmpdir.

    The module reads OPENSEC_HOME at import time, so we have to reload it
    after monkeypatching the env var.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("OPENSEC_HOME", str(home))
    import importlib

    import opensec_cli.daemon as daemon_mod

    importlib.reload(daemon_mod)
    return home, daemon_mod


# ---------------------------------------------------------------------------
# env file parsing
# ---------------------------------------------------------------------------


def test_read_env_file_basic(fake_home):
    home, daemon = fake_home
    env_file = home / "config" / "opensec.env"
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
    from opensec_cli.daemon import _read_env_file

    assert _read_env_file(tmp_path / "nope.env") == {}


# ---------------------------------------------------------------------------
# pid handling
# ---------------------------------------------------------------------------


def test_pid_alive_for_self():
    from opensec_cli.daemon import _pid_alive

    assert _pid_alive(os.getpid()) is True


def test_pid_alive_for_unused_pid():
    from opensec_cli.daemon import _pid_alive

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
    from opensec_cli.daemon import _port_free

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

    import opensec_cli.cli as cli_mod

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

    # File permissions should be 0600 (the env file holds OPENSEC_CREDENTIAL_KEY).
    mode = oct(daemon.ENV_FILE.stat().st_mode & 0o777)
    assert mode == "0o600"


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def test_doctor_json_envelope_on_empty_home(fake_home):
    home, daemon = fake_home
    import importlib

    import opensec_cli.cli as cli_mod

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
