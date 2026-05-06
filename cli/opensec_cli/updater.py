"""Safe in-place updater for the local OpenSec install.

`opensec update` checks GitHub Releases for a newer version, downloads the
tarball, snapshots the current ``app/`` and ``bin/`` (rename, not copy — fast,
atomic on the same filesystem), extracts the new version, re-runs the
bundled ``install-opencode.sh`` / ``install-scanners.sh`` to rehydrate
``bin/``, runs the doctor checks, and either restarts the daemon or rolls
back on failure.

Data and config are never touched. ``data/``, ``config/``, and ``cli-venv/``
stay where they are.

A flock on ``$OPENSEC_HOME/run/update.lock`` prevents concurrent updates.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

import click
import httpx
from packaging.version import InvalidVersion, Version

from opensec_cli.output import EXIT_AWAITING_HUMAN, EXIT_ERROR, EXIT_OK, emit_error

GITHUB_REPO = "galanko/opensec"
GITHUB_API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_API_TAG = f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{{tag}}"

DOWNLOAD_TIMEOUT_S = 120.0
API_TIMEOUT_S = 10.0
MAX_TARBALL_BYTES = 200 * 1024 * 1024  # 200 MB cap


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------


def _normalize(tag: str) -> str:
    """Strip a leading 'v' so 'v0.1.6-alpha' compares the same as '0.1.6-alpha'."""
    return tag.lstrip("v").strip()


def _parse(version: str) -> Version | None:
    try:
        return Version(_normalize(version))
    except InvalidVersion:
        return None


def is_newer(latest: str, current: str) -> bool:
    """True if ``latest`` > ``current`` per PEP 440. Falls back to string inequality
    if either is unparseable (the conservative default — assume update needed)."""
    lp = _parse(latest)
    cp = _parse(current)
    if lp is None or cp is None:
        return _normalize(latest) != _normalize(current)
    return lp > cp


# ---------------------------------------------------------------------------
# Release metadata
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Release:
    tag: str  # e.g. "v0.1.7-alpha"
    version: str  # e.g. "0.1.7-alpha"
    tarball_url: str
    sha256_url: str  # `${tarball_url}.sha256`


def _release_urls(tag: str) -> tuple[str, str]:
    """Build the tarball + sha256 sidecar URLs for a tag, mirroring install-local.sh.

    install-local.sh names the asset ``opensec-<version>.tar.gz`` for tagged
    releases and ``opensec.tar.gz`` for the ``latest`` redirect. We always
    pin to a tag here, so we use the versioned asset name.
    """
    version = _normalize(tag)
    base = f"https://github.com/{GITHUB_REPO}/releases/download/{tag}"
    tar = f"{base}/opensec-{version}.tar.gz"
    return tar, tar + ".sha256"


def fetch_latest_release(client: httpx.Client) -> Release:
    """GET /releases/latest. Raises httpx.HTTPError on transport failure."""
    resp = client.get(GITHUB_API_LATEST, timeout=API_TIMEOUT_S, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()
    tag = data["tag_name"]
    tar_url, sha_url = _release_urls(tag)
    return Release(tag=tag, version=_normalize(tag), tarball_url=tar_url, sha256_url=sha_url)


def fetch_release_by_tag(client: httpx.Client, tag: str) -> Release:
    resp = client.get(
        GITHUB_API_TAG.format(tag=tag), timeout=API_TIMEOUT_S, follow_redirects=True
    )
    resp.raise_for_status()
    data = resp.json()
    real_tag = data["tag_name"]
    tar_url, sha_url = _release_urls(real_tag)
    return Release(
        tag=real_tag, version=_normalize(real_tag), tarball_url=tar_url, sha256_url=sha_url
    )


# ---------------------------------------------------------------------------
# Tarball download + extract
# ---------------------------------------------------------------------------


def download_tarball(client: httpx.Client, release: Release, dest: Path) -> str:
    """Stream the tarball to ``dest`` and return the SHA-256 hex digest of the bytes.

    Aborts with ``RuntimeError`` if the download exceeds MAX_TARBALL_BYTES.
    """
    h = hashlib.sha256()
    written = 0
    with client.stream(
        "GET", release.tarball_url, timeout=DOWNLOAD_TIMEOUT_S, follow_redirects=True
    ) as r:
        r.raise_for_status()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes(chunk_size=64 * 1024):
                if not chunk:
                    continue
                written += len(chunk)
                if written > MAX_TARBALL_BYTES:
                    raise RuntimeError(
                        f"tarball exceeds {MAX_TARBALL_BYTES} bytes — refusing to download"
                    )
                h.update(chunk)
                f.write(chunk)
    return h.hexdigest()


def fetch_expected_sha256(client: httpx.Client, release: Release) -> str | None:
    """Best-effort fetch of the ``.sha256`` sidecar. Returns hex digest or None.

    Older releases may not have the sidecar — we treat that as a soft warn.
    """
    try:
        resp = client.get(release.sha256_url, timeout=API_TIMEOUT_S, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    # File format: "<hex>  <filename>" (shasum/sha256sum convention) or just "<hex>".
    return resp.text.strip().split()[0] if resp.text.strip() else None


def safe_extract(tarball: Path, dest: Path) -> None:
    """Extract ``tarball`` into ``dest``, rejecting any member that escapes ``dest``.

    Mitigates CVE-2007-4559 path-traversal style attacks. Caller must ensure
    ``dest`` exists and is empty.
    """
    dest = dest.resolve()
    with tarfile.open(tarball, "r:gz") as tf:
        for member in tf.getmembers():
            target = (dest / member.name).resolve()
            if not str(target).startswith(str(dest) + os.sep) and target != dest:
                raise RuntimeError(f"unsafe tarball member: {member.name!r}")
            if member.issym() or member.islnk():
                # Symlinks: ensure link target also stays inside dest.
                link_target = (dest / member.name).parent / member.linkname
                if not str(link_target.resolve()).startswith(str(dest)):
                    raise RuntimeError(f"unsafe symlink target: {member.name!r}")
        tf.extractall(dest, filter="data")  # noqa: S202 — every member checked above


# ---------------------------------------------------------------------------
# Lock file
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def update_lock(lock_path: Path):
    """flock-based mutex on ``lock_path``. Raises RuntimeError if another
    update is in progress."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another `opensec update` is in progress") from exc
        os.write(fd, f"{os.getpid()}\n".encode())
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        with contextlib.suppress(OSError):
            lock_path.unlink()


# ---------------------------------------------------------------------------
# Click command
# ---------------------------------------------------------------------------


def _read_current_version(app_dir: Path) -> str | None:
    version_file = app_dir / "VERSION"
    if not version_file.is_file():
        return None
    return version_file.read_text().strip() or None


def _running_from_managed_venv(opensec_home: Path) -> bool:
    """True if the active CLI was installed by install-local.sh into cli-venv/."""
    cli_venv = opensec_home / "cli-venv"
    try:
        return Path(sys.executable).resolve().is_relative_to(cli_venv.resolve())
    except (ValueError, OSError):
        return False


@click.command(name="update")
@click.option("--check", "check_only", is_flag=True, help="Only print versions; don't install.")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
@click.option(
    "--force",
    is_flag=True,
    help="Reinstall even if already on the latest version (recovers a corrupted install).",
)
@click.option("--version", "version_pin", default=None, help="Pin to a specific release tag.")
@click.pass_context
def update_cmd(
    ctx: click.Context,
    check_only: bool,
    yes: bool,
    force: bool,
    version_pin: str | None,
) -> None:
    """Update OpenSec to the latest release (or a pinned tag).

    Safe semantics: stops the daemon, snapshots the current install, extracts
    the new version, runs the bundled installers, and either restarts on
    success or rolls back on failure. ``data/``, ``config/``, and
    ``cli-venv/`` are preserved.
    """
    from opensec_cli import daemon as d  # local to honour OPENSEC_HOME at call time

    current = _read_current_version(d.APP_DIR)
    if current is None:
        emit_error(
            f"OpenSec is not installed (no VERSION at {d.APP_DIR / 'VERSION'}).",
            code="not_installed",
            hint=(
                "Run the installer: curl -fsSL "
                f"https://github.com/{GITHUB_REPO}/releases/latest/download/install-local.sh | sh"
            ),
            exit_code=EXIT_ERROR,
        )

    with httpx.Client() as client:
        try:
            release = (
                fetch_release_by_tag(client, version_pin)
                if version_pin
                else fetch_latest_release(client)
            )
        except httpx.HTTPError as exc:
            emit_error(
                f"Could not reach GitHub Releases: {exc}",
                code="github_unreachable",
                exit_code=EXIT_ERROR,
            )

        click.echo(f"current={current} latest={release.version}")

        needs_update = force or is_newer(release.version, current)
        if not needs_update:
            click.echo("OpenSec is up to date.")
            ctx.exit(EXIT_OK)
        if check_only:
            click.echo(
                "An update is available. Run `opensec update` (or `opensec update --yes`)."
            )
            ctx.exit(EXIT_AWAITING_HUMAN)

        if not yes and not click.confirm(f"Update to {release.version}?"):
            click.echo("Aborted.")
            return

        # Lock so two updates can't race.
        try:
            with update_lock(d.RUN_DIR / "update.lock"):
                _do_update(client, ctx, d, release, current)
        except RuntimeError as exc:
            emit_error(str(exc), code="update_in_progress", exit_code=EXIT_ERROR)


def _do_update(
    client: httpx.Client,
    ctx: click.Context,
    d,  # opensec_cli.daemon module
    release: Release,
    current: str,
) -> None:
    """The actual stop/snapshot/download/extract/restart sequence.

    Split out for testability. ``d`` is the daemon module; we hold a
    reference because ``OPENSEC_HOME`` is read at import time.
    """
    click.echo("[1/8] stopping daemon")
    ctx.invoke(d.stop_cmd, timeout=10.0, force=False)

    snap_app = d.OPENSEC_HOME / f"app.bak-{current}"
    snap_bin = d.OPENSEC_HOME / f"bin.bak-{current}"
    # Defensive: clear any leftover snapshots from a previous failed update.
    for path in (snap_app, snap_bin):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    click.echo(f"[2/8] snapshotting current install -> {snap_app.name}, {snap_bin.name}")
    if d.APP_DIR.exists():
        d.APP_DIR.rename(snap_app)
    if d.BIN_DIR.exists():
        d.BIN_DIR.rename(snap_bin)

    rolled_back = False

    def _rollback(reason: str) -> None:
        nonlocal rolled_back
        rolled_back = True
        click.echo(f"  rolling back: {reason}", err=True)
        if d.APP_DIR.exists():
            shutil.rmtree(d.APP_DIR, ignore_errors=True)
        if d.BIN_DIR.exists():
            shutil.rmtree(d.BIN_DIR, ignore_errors=True)
        if snap_app.exists():
            snap_app.rename(d.APP_DIR)
        if snap_bin.exists():
            snap_bin.rename(d.BIN_DIR)
        # Bring the daemon back on the previous version.
        with contextlib.suppress(SystemExit):
            ctx.invoke(d.start_cmd, detach=True, port=None, host=None)

    try:
        click.echo(f"[3/8] downloading {release.tarball_url}")
        with tempfile.TemporaryDirectory() as tmpdir:
            tar_path = Path(tmpdir) / "opensec.tar.gz"
            actual_sha = download_tarball(client, release, tar_path)
            expected_sha = fetch_expected_sha256(client, release)
            if expected_sha:
                if actual_sha.lower() != expected_sha.lower():
                    raise RuntimeError(
                        f"tarball SHA-256 mismatch: expected {expected_sha}, got {actual_sha}"
                    )
                click.echo("[4/8] checksum verified")
            else:
                click.echo(
                    "[4/8] checksum sidecar absent — skipping (HTTPS transport)",
                    err=True,
                )

            click.echo("[5/8] extracting tarball")
            d.APP_DIR.mkdir(parents=True, exist_ok=True)
            safe_extract(tar_path, d.APP_DIR)

        click.echo("[6/8] re-running bundled installers (opencode + scanners)")
        d.BIN_DIR.mkdir(parents=True, exist_ok=True)
        _run_bundled_installers(d)

        click.echo("[7/8] running doctor checks")
        checks = d._gather_doctor_checks()
        failing = [c["name"] for c in checks if not c["ok"] and not c["warn_only"]]
        if failing:
            raise RuntimeError(f"doctor failed: {failing}")

        click.echo("[8/8] starting daemon")
        ctx.invoke(d.start_cmd, detach=True, port=None, host=None)

    except Exception as exc:
        _rollback(str(exc))
        emit_error(
            f"Update failed and was rolled back to {current}.",
            code="update_failed",
            hint=str(exc),
            exit_code=EXIT_ERROR,
        )

    if rolled_back:
        return

    # Success: clean up snapshots.
    for path in (snap_app, snap_bin):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    click.echo(f"\nUpdated {current} -> {release.version}.")
    if not _running_from_managed_venv(d.OPENSEC_HOME):
        click.echo(
            "Note: the CLI itself was not updated (it's not running from "
            f"{d.OPENSEC_HOME / 'cli-venv'}). If you installed via "
            "`pip install opensec-cli`, upgrade the package separately.",
            err=True,
        )


def _run_bundled_installers(d) -> None:
    """Run install-opencode.sh and install-scanners.sh shipped inside the new tarball.

    These scripts download the pinned binaries from GitHub Releases and drop
    them into ``$OPENSEC_HOME/bin/``. They tolerate being re-run.
    """
    scripts_dir = d.APP_DIR / "scripts"
    env = os.environ.copy()
    env["OPENSEC_HOME"] = str(d.OPENSEC_HOME)
    env["BIN_DIR"] = str(d.BIN_DIR)
    for script_name in ("install-opencode.sh", "install-scanners.sh"):
        script = scripts_dir / script_name
        if not script.is_file():
            raise RuntimeError(f"bundled installer missing: {script}")
        result = subprocess.run(  # noqa: S603 — fully resolved path
            ["sh", str(script)],
            env=env,
            cwd=str(d.APP_DIR),
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
        if result.returncode != 0:
            tail = "\n".join(
                (result.stderr or result.stdout or "").strip().splitlines()[-10:]
            )
            raise RuntimeError(f"{script_name} failed (rc={result.returncode}): {tail}")
