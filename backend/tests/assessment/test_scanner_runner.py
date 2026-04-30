"""Subprocess scanner runner tests (Epic 1).

The runner is the production seam between the assessment engine and the pinned
Trivy / Semgrep binaries. The two contracts the architect explicitly guards:

* env whitelist excludes every variable except PATH / HOME / LANG / cache dirs
  (ADR-0028). Most importantly, ``GITHUB_PAT`` must NOT propagate to the
  subprocess.
* timeouts kill the whole process group (the binary may have spawned children).

We don't run real Trivy/Semgrep here — these tests use throwaway shell scripts
and a tiny Python child to introspect the environment the subprocess sees.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from opensec.assessment.scanners.runner import (
    SCANNER_ENV_ALLOW,
    ScannerTimeoutError,
    SubprocessScannerRunner,
)


def _make_executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.fixture
def runner(tmp_path: Path) -> SubprocessScannerRunner:
    return SubprocessScannerRunner(bin_dir=tmp_path / "bin")


@pytest.mark.asyncio
async def test_subprocess_runner_env_whitelist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: SubprocessScannerRunner
) -> None:
    """ADR-0028 guard: GITHUB_PAT is in the parent env, but never reaches the child."""
    monkeypatch.setenv("GITHUB_PAT", "ghp_should_not_leak")
    monkeypatch.setenv("OPENSEC_DB_PATH", "/should/not/leak.db")
    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin:/bin"))

    out_file = tmp_path / "child_env.json"
    script = _make_executable(
        tmp_path / "dump_env.py",
        f"#!{sys.executable}\nimport json, os\n"
        f"open({str(out_file)!r}, 'w').write(json.dumps(dict(os.environ)))\n",
    )

    proc = await runner._run_subprocess([str(script)], timeout=10)
    assert proc.returncode == 0

    child_env = json.loads(out_file.read_text())
    assert "GITHUB_PAT" not in child_env, child_env
    assert "OPENSEC_DB_PATH" not in child_env

    # Whitelisted entries that exist in the parent should still be there.
    assert child_env.get("PATH"), "PATH must propagate so the child can locate libs"

    # The constraint is: nothing OpenSec controls (or that carries credentials)
    # leaks. macOS / glibc may inject loader vars (__CF_USER_TEXT_ENCODING,
    # LC_CTYPE) into every child process regardless of env=; those aren't ours.
    secret_like = {
        k for k in child_env if k.startswith(("OPENSEC_", "GITHUB", "ANTHROPIC", "OPENAI"))
    }
    assert not secret_like, f"secret-shaped env leaked into scanner: {secret_like}"
    extra_opensec_controlled = (set(child_env) - set(SCANNER_ENV_ALLOW)) - {
        "__CF_USER_TEXT_ENCODING",
        "LC_CTYPE",
    }
    assert not extra_opensec_controlled, (
        f"unexpected env beyond loader vars leaked: {extra_opensec_controlled}"
    )


@pytest.mark.asyncio
async def test_subprocess_runner_returns_stdout_and_exit(
    tmp_path: Path, runner: SubprocessScannerRunner
) -> None:
    script = _make_executable(
        tmp_path / "echo.sh",
        '#!/bin/sh\nprintf \'{"hello":"world"}\\n\'\n',
    )
    proc = await runner._run_subprocess([str(script)], timeout=5)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["hello"] == "world"


@pytest.mark.asyncio
async def test_subprocess_runner_timeout_raises(
    tmp_path: Path, runner: SubprocessScannerRunner
) -> None:
    script = _make_executable(
        tmp_path / "sleep.sh",
        "#!/bin/sh\nsleep 30\n",
    )
    with pytest.raises(ScannerTimeoutError):
        await runner._run_subprocess([str(script)], timeout=0.5)


@pytest.mark.asyncio
async def test_subprocess_runner_nonzero_exit_carries_stderr(
    tmp_path: Path, runner: SubprocessScannerRunner
) -> None:
    script = _make_executable(
        tmp_path / "fail.sh",
        '#!/bin/sh\necho "boom" 1>&2\nexit 7\n',
    )
    proc = await runner._run_subprocess([str(script)], timeout=5)
    assert proc.returncode == 7
    assert "boom" in proc.stderr


def test_available_scanners_reports_missing_when_no_binaries(tmp_path: Path) -> None:
    runner = SubprocessScannerRunner(bin_dir=tmp_path / "bin")
    infos = runner.available_scanners()
    names = {info.name for info in infos}
    assert names == {"trivy", "semgrep"}
    assert all(not info.available for info in infos)


def test_available_scanners_detects_present_binaries(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_executable(bin_dir / "trivy", "#!/bin/sh\necho 'Version: 0.52.0'\n")
    _make_executable(bin_dir / "semgrep", "#!/bin/sh\necho '1.70.0'\n")

    runner = SubprocessScannerRunner(bin_dir=bin_dir)
    infos = {info.name: info for info in runner.available_scanners()}
    assert infos["trivy"].available is True
    assert infos["semgrep"].available is True


@pytest.mark.asyncio
async def test_run_trivy_parses_fixture_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stand-in trivy script emits the captured Trivy JSON; the runner parses it."""
    fixture_path = (
        Path(__file__).resolve().parent.parent / "fixtures" / "scanners" / "trivy_output.json"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_executable(
        bin_dir / "trivy",
        f"#!/bin/sh\ncat {fixture_path}\n",
    )

    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
    runner = SubprocessScannerRunner(bin_dir=bin_dir)
    target = tmp_path / "repo"
    target.mkdir()

    result = await runner.run_trivy(target, timeout=10)
    assert result.version  # populated by the runner from the binary's --version
    assert any(v.vuln_id.startswith("CVE-") for v in result.vulnerabilities)


@pytest.mark.asyncio
async def test_run_semgrep_parses_fixture_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture_path = (
        Path(__file__).resolve().parent.parent / "fixtures" / "scanners" / "semgrep_output.json"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_executable(
        bin_dir / "semgrep",
        f"#!/bin/sh\ncat {fixture_path}\n",
    )

    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
    runner = SubprocessScannerRunner(bin_dir=bin_dir)
    target = tmp_path / "repo"
    target.mkdir()

    result = await runner.run_semgrep(target, timeout=10)
    assert result.findings, "fixture must have at least one finding"
    assert result.findings[0].path


# --- skip-dirs / exclude posture (ADR-0028 follow-up) -----------------------
#
# Trivy and Semgrep walk the target directory themselves, so the in-process
# `iter_repo_files` exclusion list has no effect on them. Without explicit
# CLI flags, both scanners report findings from `backend/tests/fixtures/` and
# similar test-data directories, surfacing hundreds of false positives on
# any repo that ships intentionally-vulnerable lockfiles for parser tests
# (including OpenSec itself).


@pytest.mark.asyncio
async def test_run_trivy_passes_skip_dirs_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Trivy must receive ``--skip-dirs <csv>`` so it doesn't walk fixture trees."""
    from opensec.assessment._fs import SKIP_DIRS

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_file = tmp_path / "trivy-argv.json"
    _make_executable(
        bin_dir / "trivy",
        (
            f"#!{sys.executable}\n"
            "import json, sys\n"
            f"argv_file = {str(argv_file)!r}\n"
            "if '--version' in sys.argv:\n"
            "    print('Version: 0.70.0')\n"
            "    sys.exit(0)\n"
            "open(argv_file, 'w').write(json.dumps(sys.argv))\n"
            "print('{}')\n"
        ),
    )

    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
    runner = SubprocessScannerRunner(bin_dir=bin_dir)
    target = tmp_path / "repo"
    target.mkdir()

    await runner.run_trivy(target, timeout=10)

    argv = json.loads(argv_file.read_text())
    assert "--skip-dirs" in argv, f"trivy was invoked without --skip-dirs: {argv}"
    csv = argv[argv.index("--skip-dirs") + 1]
    passed = set(csv.split(","))
    # Trivy uses doublestar globs against paths relative to the scan target,
    # so matching a directory at any depth needs ``**/<name>``. A bare
    # basename misses nested occurrences (the case that motivated this fix:
    # OpenSec's own ``backend/tests/fixtures``).
    expected = {f"**/{d}" for d in SKIP_DIRS}
    assert passed >= expected, f"--skip-dirs missing globs: {expected - passed}"
    # Spot-check the two that motivated this fix.
    assert "**/fixtures" in passed
    assert "**/test_fixtures" in passed


@pytest.mark.asyncio
async def test_run_semgrep_passes_exclude_for_each_skip_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Semgrep takes one ``--exclude <dir>`` per directory; every SKIP_DIR must appear."""
    from opensec.assessment._fs import SKIP_DIRS

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_file = tmp_path / "semgrep-argv.json"
    _make_executable(
        bin_dir / "semgrep",
        (
            f"#!{sys.executable}\n"
            "import json, sys\n"
            f"argv_file = {str(argv_file)!r}\n"
            "if '--version' in sys.argv:\n"
            "    print('1.70.0')\n"
            "    sys.exit(0)\n"
            "open(argv_file, 'w').write(json.dumps(sys.argv))\n"
            "print('{\"results\":[],\"errors\":[]}')\n"
        ),
    )

    monkeypatch.setenv("PATH", os.environ.get("PATH", "/usr/bin:/bin"))
    runner = SubprocessScannerRunner(bin_dir=bin_dir)
    target = tmp_path / "repo"
    target.mkdir()

    await runner.run_semgrep(target, timeout=10)

    argv = json.loads(argv_file.read_text())
    excludes = {argv[i + 1] for i, a in enumerate(argv) if a == "--exclude"}
    assert excludes >= SKIP_DIRS, (
        f"semgrep --exclude missing entries: {SKIP_DIRS - excludes}"
    )
