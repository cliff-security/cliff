"""Unit tests for the in-place updater.

Heavy mocking: httpx for the GitHub API + tarball download, subprocess for
the bundled installer scripts, daemon.stop_cmd / start_cmd as no-ops, and
``_gather_doctor_checks`` as a stub returning success or a synthesized failure.
"""

from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner

from opensec_cli import updater
from opensec_cli.updater import (
    _release_urls,
    is_newer,
    safe_extract,
    update_lock,
)

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "latest,current,expected",
    [
        ("v0.1.7-alpha", "0.1.6-alpha", True),
        ("0.1.7", "0.1.7", False),
        ("0.1.6", "0.1.7", False),
        ("v0.1.7", "v0.1.7", False),
        ("0.2.0", "0.1.99", True),
    ],
)
def test_is_newer(latest, current, expected):
    assert is_newer(latest, current) is expected


def test_release_urls_uses_versioned_asset_name():
    tar, sha = _release_urls("v0.1.7-alpha")
    assert tar.endswith("/v0.1.7-alpha/opensec-0.1.7-alpha.tar.gz")
    assert sha == tar + ".sha256"


# ---------------------------------------------------------------------------
# safe_extract
# ---------------------------------------------------------------------------


def _build_tarball(members: dict[str, bytes], path: Path) -> None:
    with tarfile.open(path, "w:gz") as tf:
        for name, content in members.items():
            data = io.BytesIO(content)
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, data)


def test_safe_extract_extracts_clean_tarball(tmp_path):
    src = tmp_path / "good.tar.gz"
    _build_tarball({"app/VERSION": b"0.1.7\n", "app/scripts/x.sh": b"#!/bin/sh\n"}, src)
    dest = tmp_path / "dest"
    dest.mkdir()
    safe_extract(src, dest)
    assert (dest / "app" / "VERSION").read_text() == "0.1.7\n"


def test_safe_extract_rejects_path_traversal(tmp_path):
    src = tmp_path / "evil.tar.gz"
    _build_tarball({"../escape.txt": b"oops"}, src)
    dest = tmp_path / "dest"
    dest.mkdir()
    with pytest.raises(RuntimeError, match="unsafe"):
        safe_extract(src, dest)


# ---------------------------------------------------------------------------
# update_lock
# ---------------------------------------------------------------------------


def test_update_lock_blocks_concurrent_holder(tmp_path):
    lock = tmp_path / "u.lock"
    with update_lock(lock), pytest.raises(RuntimeError, match="in progress"), update_lock(lock):
        pass


# ---------------------------------------------------------------------------
# update_cmd — CLI surface
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a fake OPENSEC_HOME with a pre-existing 'installed' app/."""
    home = tmp_path / "home"
    (home / "app").mkdir(parents=True)
    (home / "app" / "VERSION").write_text("0.1.6-alpha\n")
    (home / "app" / "scripts").mkdir()
    (home / "bin").mkdir()
    (home / "run").mkdir()
    monkeypatch.setenv("OPENSEC_HOME", str(home))

    import importlib

    import opensec_cli.daemon as d
    import opensec_cli.updater as u

    importlib.reload(d)
    importlib.reload(u)

    return home, d, u


def _stub_lifecycle(monkeypatch, daemon, *, doctor_passes=True):
    """No-op out the daemon-side things the updater calls into."""
    monkeypatch.setattr(daemon.stop_cmd, "callback", lambda timeout, force: None)
    monkeypatch.setattr(daemon.start_cmd, "callback", lambda detach, port, host: None)
    if doctor_passes:
        monkeypatch.setattr(
            daemon,
            "_gather_doctor_checks",
            lambda: [{"name": "ok", "ok": True, "warn_only": False}],
        )
    else:
        monkeypatch.setattr(
            daemon,
            "_gather_doctor_checks",
            lambda: [{"name": "venv", "ok": False, "warn_only": False, "detail": "missing"}],
        )


def test_check_only_prints_versions_and_exits_2_when_newer(fake_install, httpx_mock):
    home, d, u = fake_install
    httpx_mock.add_response(
        url=updater.GITHUB_API_LATEST,
        json={"tag_name": "v0.1.7-alpha"},
    )
    res = CliRunner().invoke(u.update_cmd, ["--check"])
    assert res.exit_code == 2, res.output
    assert "current=0.1.6-alpha latest=0.1.7-alpha" in res.output


def test_check_only_when_up_to_date_exits_0(fake_install, httpx_mock):
    home, d, u = fake_install
    httpx_mock.add_response(
        url=updater.GITHUB_API_LATEST,
        json={"tag_name": "v0.1.6-alpha"},
    )
    res = CliRunner().invoke(u.update_cmd, ["--check"])
    assert res.exit_code == 0, res.output
    assert "up to date" in res.output


def test_update_aborts_when_user_declines(fake_install, httpx_mock):
    home, d, u = fake_install
    httpx_mock.add_response(
        url=updater.GITHUB_API_LATEST,
        json={"tag_name": "v0.1.7-alpha"},
    )
    res = CliRunner().invoke(u.update_cmd, input="n\n")
    assert res.exit_code == 0
    assert "Aborted." in res.output
    # Old version still in place.
    assert (home / "app" / "VERSION").read_text().strip() == "0.1.6-alpha"


def test_update_happy_path_replaces_install(fake_install, httpx_mock, monkeypatch, tmp_path):
    home, d, u = fake_install
    _stub_lifecycle(monkeypatch, d, doctor_passes=True)

    # GitHub API resolves the tag.
    httpx_mock.add_response(
        url=updater.GITHUB_API_LATEST,
        json={"tag_name": "v0.1.7-alpha"},
    )
    # Tarball: a minimal app/ payload with a VERSION + stub installer scripts.
    tar_url = _release_urls("v0.1.7-alpha")[0]
    sha_url = tar_url + ".sha256"
    tar_path = tmp_path / "fake.tar.gz"
    _build_tarball(
        {
            "VERSION": b"0.1.7-alpha\n",
            "scripts/install-opencode.sh": b"#!/bin/sh\nexit 0\n",
            "scripts/install-scanners.sh": b"#!/bin/sh\nexit 0\n",
        },
        tar_path,
    )
    tar_bytes = tar_path.read_bytes()
    import hashlib
    expected_sha = hashlib.sha256(tar_bytes).hexdigest()
    httpx_mock.add_response(url=tar_url, content=tar_bytes)
    httpx_mock.add_response(url=sha_url, text=f"{expected_sha}  opensec-0.1.7-alpha.tar.gz\n")

    # Stub the bundled installers — they're shell scripts but we can't rely on
    # the test box having `sh` paths set up the way the real installers want.
    # The updater shells out via subprocess.run; intercept that.
    sh_calls: list[list[str]] = []

    def _run(cmd, *args, **kwargs):
        sh_calls.append(list(cmd))
        class _R:
            returncode = 0
            stdout = ""
            stderr = ""
        return _R()

    monkeypatch.setattr(u.subprocess, "run", _run)

    res = CliRunner().invoke(u.update_cmd, ["--yes"])
    assert res.exit_code == 0, res.output
    assert (home / "app" / "VERSION").read_text().strip() == "0.1.7-alpha"
    assert "Updated 0.1.6-alpha -> 0.1.7-alpha" in res.output
    # Both bundled installers were run.
    assert any("install-opencode.sh" in " ".join(c) for c in sh_calls)
    assert any("install-scanners.sh" in " ".join(c) for c in sh_calls)
    # Snapshots were cleaned up.
    assert not (home / "app.bak-0.1.6-alpha").exists()
    assert not (home / "bin.bak-0.1.6-alpha").exists()


def test_update_rolls_back_on_doctor_failure(
    fake_install, httpx_mock, monkeypatch, tmp_path
):
    home, d, u = fake_install
    _stub_lifecycle(monkeypatch, d, doctor_passes=False)

    httpx_mock.add_response(
        url=updater.GITHUB_API_LATEST,
        json={"tag_name": "v0.1.7-alpha"},
    )
    tar_url = _release_urls("v0.1.7-alpha")[0]
    sha_url = tar_url + ".sha256"
    tar_path = tmp_path / "fake.tar.gz"
    _build_tarball(
        {
            "VERSION": b"0.1.7-alpha\n",
            "scripts/install-opencode.sh": b"#!/bin/sh\nexit 0\n",
            "scripts/install-scanners.sh": b"#!/bin/sh\nexit 0\n",
        },
        tar_path,
    )
    tar_bytes = tar_path.read_bytes()
    httpx_mock.add_response(url=tar_url, content=tar_bytes)
    httpx_mock.add_response(url=sha_url, status_code=404)

    monkeypatch.setattr(
        u.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    res = CliRunner().invoke(u.update_cmd, ["--yes"])
    assert res.exit_code == 1, res.output
    assert "rolled back" in res.output.lower()
    # Old VERSION restored from snapshot.
    assert (home / "app" / "VERSION").read_text().strip() == "0.1.6-alpha"
    # Snapshots cleaned up after rollback.
    assert not (home / "app.bak-0.1.6-alpha").exists()


def test_update_with_pinned_version_uses_tag_endpoint(fake_install, httpx_mock):
    home, d, u = fake_install
    httpx_mock.add_response(
        url=updater.GITHUB_API_TAG.format(tag="v0.1.5-alpha"),
        json={"tag_name": "v0.1.5-alpha"},
    )
    res = CliRunner().invoke(u.update_cmd, ["--check", "--version", "v0.1.5-alpha"])
    # current=0.1.6, requested=0.1.5 — not newer, exits 0 with "up to date".
    assert res.exit_code == 0
    assert "current=0.1.6-alpha latest=0.1.5-alpha" in res.output


def test_update_force_reinstalls_same_version(
    fake_install, httpx_mock, monkeypatch, tmp_path
):
    home, d, u = fake_install
    _stub_lifecycle(monkeypatch, d, doctor_passes=True)
    httpx_mock.add_response(
        url=updater.GITHUB_API_LATEST,
        json={"tag_name": "v0.1.6-alpha"},  # same as installed
    )
    tar_url = _release_urls("v0.1.6-alpha")[0]
    sha_url = tar_url + ".sha256"
    tar_path = tmp_path / "fake.tar.gz"
    _build_tarball({"VERSION": b"0.1.6-alpha\n",
                    "scripts/install-opencode.sh": b"#!/bin/sh\n",
                    "scripts/install-scanners.sh": b"#!/bin/sh\n"}, tar_path)
    httpx_mock.add_response(url=tar_url, content=tar_path.read_bytes())
    httpx_mock.add_response(url=sha_url, status_code=404)
    monkeypatch.setattr(
        u.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    res = CliRunner().invoke(u.update_cmd, ["--yes", "--force"])
    assert res.exit_code == 0, res.output
    assert "Updated 0.1.6-alpha -> 0.1.6-alpha" in res.output


def test_update_errors_when_not_installed(tmp_path, monkeypatch):
    """No VERSION file -> not_installed error."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("OPENSEC_HOME", str(home))
    import importlib

    import opensec_cli.daemon as d
    import opensec_cli.updater as u

    importlib.reload(d)
    importlib.reload(u)

    res = CliRunner().invoke(u.update_cmd, ["--check"])
    assert res.exit_code == 1
    assert "not_installed" in res.output


def test_update_errors_when_github_unreachable(fake_install, httpx_mock):
    home, d, u = fake_install
    httpx_mock.add_exception(httpx.ConnectError("offline"))
    res = CliRunner().invoke(u.update_cmd, ["--check"])
    assert res.exit_code == 1
    assert "github_unreachable" in res.output


# ---------------------------------------------------------------------------
# Safety paths — Path B: validate before swap, robust rollback,
#                        timestamped non-clobbering snapshots.
# ---------------------------------------------------------------------------


def test_verify_tarball_shape_accepts_valid_tarball(tmp_path):
    src = tmp_path / "ok.tar.gz"
    _build_tarball(
        {
            "VERSION": b"0.1.7\n",
            "scripts/install-opencode.sh": b"#!/bin/sh\n",
            "scripts/install-scanners.sh": b"#!/bin/sh\n",
        },
        src,
    )
    updater.verify_tarball_shape(src)  # no raise


def test_verify_tarball_shape_rejects_missing_entries(tmp_path):
    src = tmp_path / "bad.tar.gz"
    _build_tarball({"VERSION": b"0.1.7\n"}, src)  # no scripts/
    with pytest.raises(RuntimeError, match="missing required entries"):
        updater.verify_tarball_shape(src)


def test_check_free_space_raises_when_low(monkeypatch, tmp_path):
    fake_usage = type("U", (), {"free": 100 * 1024 * 1024})  # 100MB
    monkeypatch.setattr(updater.shutil, "disk_usage", lambda p: fake_usage())
    with pytest.raises(RuntimeError, match="insufficient free space"):
        updater.check_free_space(tmp_path)


def test_check_free_space_passes_when_sufficient(monkeypatch, tmp_path):
    fake_usage = type("U", (), {"free": 10 * 1024 * 1024 * 1024})  # 10GB
    monkeypatch.setattr(updater.shutil, "disk_usage", lambda p: fake_usage())
    updater.check_free_space(tmp_path)  # no raise


def test_robust_rmtree_clean_removal(tmp_path):
    target = tmp_path / "doomed"
    target.mkdir()
    (target / "f.txt").write_text("hi")
    residue = updater.robust_rmtree(target)
    assert residue is None
    assert not target.exists()


def test_robust_rmtree_handles_residue(tmp_path, monkeypatch):
    target = tmp_path / "doomed"
    target.mkdir()
    (target / "f.txt").write_text("hi")

    real_rmtree = updater.shutil.rmtree

    def _flaky_rmtree(path, *args, **kwargs):
        # Fail to actually remove — simulate a permission error mid-tree.
        raise OSError("simulated rmtree failure")

    monkeypatch.setattr(updater.shutil, "rmtree", _flaky_rmtree)
    residue = updater.robust_rmtree(target)
    monkeypatch.setattr(updater.shutil, "rmtree", real_rmtree)

    assert residue is not None
    assert residue.exists()
    assert not target.exists()
    assert residue.name.startswith("doomed.broken-")


def test_update_aborts_on_low_disk_without_touching_install(
    fake_install, httpx_mock, monkeypatch
):
    """Disk-space pre-flight runs BEFORE any rename — install must be intact."""
    home, d, u = fake_install
    monkeypatch.setattr(d.stop_cmd, "callback", lambda timeout, force: None)
    httpx_mock.add_response(
        url=updater.GITHUB_API_LATEST,
        json={"tag_name": "v0.1.7-alpha"},
    )
    fake_usage = type("U", (), {"free": 10 * 1024 * 1024})  # 10 MB — way below 500
    monkeypatch.setattr(u.shutil, "disk_usage", lambda p: fake_usage())
    res = CliRunner().invoke(u.update_cmd, ["--yes"])
    assert res.exit_code == 1
    assert "update_aborted" in res.output
    assert "insufficient free space" in res.output
    # The live install MUST be untouched.
    assert (home / "app" / "VERSION").read_text().strip() == "0.1.6-alpha"
    assert not list(home.glob("app.bak-*"))


def test_update_aborts_on_bad_checksum_without_touching_install(
    fake_install, httpx_mock, monkeypatch, tmp_path
):
    home, d, u = fake_install
    _stub_lifecycle(monkeypatch, d, doctor_passes=True)
    httpx_mock.add_response(
        url=updater.GITHUB_API_LATEST,
        json={"tag_name": "v0.1.7-alpha"},
    )
    tar_url = _release_urls("v0.1.7-alpha")[0]
    sha_url = tar_url + ".sha256"
    tar_path = tmp_path / "fake.tar.gz"
    _build_tarball(
        {
            "VERSION": b"0.1.7-alpha\n",
            "scripts/install-opencode.sh": b"#!/bin/sh\n",
            "scripts/install-scanners.sh": b"#!/bin/sh\n",
        },
        tar_path,
    )
    httpx_mock.add_response(url=tar_url, content=tar_path.read_bytes())
    # Sidecar advertises the WRONG digest -> checksum mismatch.
    httpx_mock.add_response(url=sha_url, text="0" * 64 + "  opensec-0.1.7-alpha.tar.gz\n")

    res = CliRunner().invoke(u.update_cmd, ["--yes"])
    assert res.exit_code == 1
    assert "checksum_mismatch" in res.output
    # Live install untouched, no snapshot created.
    assert (home / "app" / "VERSION").read_text().strip() == "0.1.6-alpha"
    assert not list(home.glob("app.bak-*"))


def test_update_aborts_on_malformed_tarball_without_touching_install(
    fake_install, httpx_mock, monkeypatch, tmp_path
):
    home, d, u = fake_install
    _stub_lifecycle(monkeypatch, d, doctor_passes=True)
    httpx_mock.add_response(
        url=updater.GITHUB_API_LATEST,
        json={"tag_name": "v0.1.7-alpha"},
    )
    tar_url = _release_urls("v0.1.7-alpha")[0]
    sha_url = tar_url + ".sha256"
    # Tarball missing the required scripts/ entries.
    tar_path = tmp_path / "bad.tar.gz"
    _build_tarball({"VERSION": b"0.1.7-alpha\n"}, tar_path)
    httpx_mock.add_response(url=tar_url, content=tar_path.read_bytes())
    httpx_mock.add_response(url=sha_url, status_code=404)

    res = CliRunner().invoke(u.update_cmd, ["--yes"])
    assert res.exit_code == 1
    assert "bad_tarball" in res.output
    assert (home / "app" / "VERSION").read_text().strip() == "0.1.6-alpha"
    assert not list(home.glob("app.bak-*"))


def test_two_failed_updates_keep_both_snapshots(
    fake_install, httpx_mock, monkeypatch, tmp_path
):
    """Snapshot names are timestamped, so consecutive failures preserve every lifeboat."""
    home, d, u = fake_install
    _stub_lifecycle(monkeypatch, d, doctor_passes=False)

    def _setup_one_failed_run(version: str):
        httpx_mock.add_response(
            url=updater.GITHUB_API_LATEST, json={"tag_name": f"v{version}"}
        )
        tar_url = _release_urls(f"v{version}")[0]
        sha_url = tar_url + ".sha256"
        tarball = tmp_path / f"{version}.tar.gz"
        _build_tarball(
            {
                "VERSION": f"{version}\n".encode(),
                "scripts/install-opencode.sh": b"#!/bin/sh\n",
                "scripts/install-scanners.sh": b"#!/bin/sh\n",
            },
            tarball,
        )
        httpx_mock.add_response(url=tar_url, content=tarball.read_bytes())
        httpx_mock.add_response(url=sha_url, status_code=404)

    monkeypatch.setattr(
        u.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    _setup_one_failed_run("0.1.7-alpha")
    res = CliRunner().invoke(u.update_cmd, ["--yes"])
    assert res.exit_code == 1
    # After the first failed update + rollback, the snapshot was renamed back
    # into place — so no app.bak-* should remain. But the test asserts our
    # write protects what *would* be overwritten on a second attempt.
    # Force a second failure by making the second snapshot collide if names
    # weren't timestamped.
    time.sleep(1.1)  # ensure a fresh timestamp slot

    # Pre-create a fake old snapshot to verify it's preserved.
    fake_old = home / "app.bak-0.1.6-alpha-19990101-000000"
    fake_old.mkdir()
    (fake_old / "marker").write_text("DO_NOT_DELETE")

    _setup_one_failed_run("0.1.8-alpha")
    res2 = CliRunner().invoke(u.update_cmd, ["--yes"])
    assert res2.exit_code == 1
    # The fake old snapshot must still exist — we never clobber.
    assert fake_old.exists()
    assert (fake_old / "marker").read_text() == "DO_NOT_DELETE"


def test_rollback_survives_partial_rmtree(
    fake_install, httpx_mock, monkeypatch, tmp_path
):
    """If rmtree of the new app/ leaves residue, rollback renames it aside
    so the snapshot rename-back still succeeds and the user is on the old version."""
    home, d, u = fake_install
    # Doctor will fail -> triggers rollback path.
    _stub_lifecycle(monkeypatch, d, doctor_passes=False)
    httpx_mock.add_response(
        url=updater.GITHUB_API_LATEST, json={"tag_name": "v0.1.7-alpha"}
    )
    tar_url = _release_urls("v0.1.7-alpha")[0]
    sha_url = tar_url + ".sha256"
    tarball = tmp_path / "t.tar.gz"
    _build_tarball(
        {
            "VERSION": b"0.1.7-alpha\n",
            "scripts/install-opencode.sh": b"#!/bin/sh\n",
            "scripts/install-scanners.sh": b"#!/bin/sh\n",
        },
        tarball,
    )
    httpx_mock.add_response(url=tar_url, content=tarball.read_bytes())
    httpx_mock.add_response(url=sha_url, status_code=404)
    monkeypatch.setattr(
        u.subprocess,
        "run",
        lambda *a, **k: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    # Force shutil.rmtree to fail the FIRST time (the rollback's removal of
    # the new APP_DIR), succeed otherwise — robust_rmtree should rename the
    # residue aside instead of giving up.
    real_rmtree = u.shutil.rmtree
    failed_once = {"n": 0}

    def _flaky_rmtree(path, *args, **kwargs):
        if failed_once["n"] == 0 and Path(path) == d.APP_DIR:
            failed_once["n"] += 1
            raise OSError("simulated permissions error")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(u.shutil, "rmtree", _flaky_rmtree)

    res = CliRunner().invoke(u.update_cmd, ["--yes"])
    assert res.exit_code == 1, res.output
    # Old version was restored from snapshot.
    assert (home / "app" / "VERSION").read_text().strip() == "0.1.6-alpha"
    # Residue from the failed rmtree was preserved (not silently lost).
    residues = list(home.glob("app.broken-*"))
    assert residues, "expected app.broken-<ts> sidecar from robust_rmtree"
