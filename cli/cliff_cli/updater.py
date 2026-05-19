"""Safe in-place updater for the local Cliff install.

`cliffsec update` checks GitHub Releases for a newer version, downloads the
tarball, snapshots the current ``app/`` and ``bin/`` (rename, not copy — fast,
atomic on the same filesystem), extracts the new version, re-runs the
bundled ``install-opencode.sh`` / ``install-scanners.sh`` to rehydrate
``bin/``, runs the doctor checks, and either restarts the daemon or rolls
back on failure.

Data and config are never touched. ``data/``, ``config/``, and ``cli-venv/``
stay where they are.

A flock on ``$CLIFF_HOME/run/update.lock`` prevents concurrent updates.

Naming note: the v0.2.0 -> v0.2.1 release renamed the CLI binary from
``cliff`` to ``cliffsec`` and the release asset from ``cliff-<version>.tar.gz``
to ``cliffsec-<version>.tar.gz``. The v0.2.1 release ships both filenames
as one-time aliases so v0.2.0's updater (which still expects the old name)
can upgrade in place. From v0.2.1 onward this module fetches the
``cliffsec-`` name; v0.2.2 will drop the alias.
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
import time
from dataclasses import dataclass
from pathlib import Path

import click
import httpx
from packaging.version import InvalidVersion, Version

from cliff_cli.output import EXIT_AWAITING_HUMAN, EXIT_ERROR, EXIT_OK, emit_error

GITHUB_REPO = "cliff-security/cliff"
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


RENAME_CUTOVER = Version("0.2.1")


def _release_urls(tag: str) -> tuple[str, str]:
    """Build the tarball + sha256 sidecar URLs for a tag, mirroring install-local.sh.

    Releases from 0.2.1 onward ship ``cliffsec-<version>.tar.gz`` (with
    ``cliffsec.tar.gz`` as the ``latest`` redirect). Releases before 0.2.1
    used ``cliff-<version>.tar.gz`` — so when the user pins ``--version`` to
    a pre-rename tag (downgrade flow) we honour the old asset name. The
    0.2.1 release itself ships both names as a one-time alias, so either
    prefix resolves for that exact version.
    """
    version = _normalize(tag)
    base = f"https://github.com/{GITHUB_REPO}/releases/download/{tag}"
    parsed = _parse(version)
    prefix = "cliff" if parsed is not None and parsed < RENAME_CUTOVER else "cliffsec"
    tar = f"{base}/{prefix}-{version}.tar.gz"
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


REQUIRED_TARBALL_MEMBERS = (
    "VERSION",
    "scripts/install-opencode.sh",
    "scripts/install-scanners.sh",
)
MIN_FREE_BYTES = 500 * 1024 * 1024  # 500 MB pre-flight floor
SNAPSHOT_RETENTION = 3  # keep N recent snapshots after a successful update


def verify_tarball_shape(tarball: Path) -> None:
    """Open ``tarball`` and confirm it contains the files the updater needs.

    Run BEFORE touching the live install — if the tarball is malformed, we
    abort cleanly without ever moving the user's app/ aside. Raises
    ``RuntimeError`` with an actionable message if anything is wrong.
    """
    try:
        with tarfile.open(tarball, "r:gz") as tf:
            names = set(tf.getnames())
    except (tarfile.TarError, OSError) as exc:
        raise RuntimeError(f"tarball is unreadable: {exc}") from exc

    missing = [m for m in REQUIRED_TARBALL_MEMBERS if m not in names]
    if missing:
        raise RuntimeError(
            f"tarball is missing required entries: {missing}. "
            "This is not a valid Cliff release."
        )


def check_free_space(path: Path, min_bytes: int = MIN_FREE_BYTES) -> None:
    """Refuse to update if the filesystem hosting ``path`` has less than
    ``min_bytes`` free. Catches "I'm out of disk" before we move anything."""
    target = path if path.exists() else path.parent
    try:
        free = shutil.disk_usage(target).free
    except OSError as exc:
        raise RuntimeError(f"could not check free disk space at {target}: {exc}") from exc
    if free < min_bytes:
        raise RuntimeError(
            f"insufficient free space at {target}: "
            f"{free // (1024 * 1024)} MB available, {min_bytes // (1024 * 1024)} MB required"
        )


def robust_rmtree(path: Path) -> Path | None:
    """Remove ``path``. If anything is left behind, rename the residue out of
    the way and return the new path. Returns None on a clean removal.

    Used by rollback so that, even if a stray file resists deletion, the
    snapshot can be renamed back into place without colliding.
    """
    if not path.exists():
        return None
    with contextlib.suppress(OSError):
        shutil.rmtree(path)
    if not path.exists():
        return None
    # Couldn't fully remove — get it out of the way.
    residue = path.with_name(f"{path.name}.broken-{int(time.time())}")
    try:
        path.rename(residue)
    except OSError:
        return None
    return residue


def list_snapshots(cliff_home: Path, kind: str) -> list[Path]:
    """List snapshot directories like ``app.bak-...``, newest first by mtime."""
    pattern = f"{kind}.bak-*"
    snaps = [p for p in cliff_home.glob(pattern) if p.is_dir()]
    snaps.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return snaps


def prune_snapshots(cliff_home: Path, retain: int = SNAPSHOT_RETENTION) -> None:
    """Keep the ``retain`` newest snapshots per kind, remove the rest. Best-effort."""
    for kind in ("app", "bin"):
        for old in list_snapshots(cliff_home, kind)[retain:]:
            with contextlib.suppress(OSError):
                shutil.rmtree(old)


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


class UpdateLockBusy(RuntimeError):  # noqa: N818 — distinct exception type, not an Error
    """Another ``cliffsec update`` is currently holding the lock."""


@contextlib.contextmanager
def update_lock(lock_path: Path):
    """flock-based mutex on ``lock_path``. Raises ``UpdateLockBusy`` if another
    update is in progress."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise UpdateLockBusy("another `cliffsec update` is in progress") from exc
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


def _running_from_managed_venv(cliff_home: Path) -> bool:
    """True if the active CLI was installed by install-local.sh into cli-venv/."""
    cli_venv = cliff_home / "cli-venv"
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
    """Update Cliff to the latest release (or a pinned tag).

    Safe semantics: stops the daemon, snapshots the current install, extracts
    the new version, runs the bundled installers, and either restarts on
    success or rolls back on failure. ``data/``, ``config/``, and
    ``cli-venv/`` are preserved.
    """
    from cliff_cli import daemon as d  # local to honour CLIFF_HOME at call time

    current = _read_current_version(d.APP_DIR)
    if current is None:
        emit_error(
            f"Cliff is not installed (no VERSION at {d.APP_DIR / 'VERSION'}).",
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
            click.echo("Cliff is up to date.")
            ctx.exit(EXIT_OK)
        if check_only:
            click.echo(
                "An update is available. Run `cliffsec update` (or `cliffsec update --yes`)."
            )
            ctx.exit(EXIT_AWAITING_HUMAN)

        if not yes and not click.confirm(f"Update to {release.version}?"):
            click.echo("Aborted.")
            return

        # Lock so two updates can't race.
        try:
            with update_lock(d.RUN_DIR / "update.lock"):
                _do_update(client, ctx, d, release, current)
        except UpdateLockBusy as exc:
            emit_error(str(exc), code="update_in_progress", exit_code=EXIT_ERROR)
        except RuntimeError as exc:
            # Anything Phase-A raises that isn't lock-busy: live install
            # was not modified (Phase A runs before the snapshot).
            emit_error(
                f"Update aborted before changing the install: {exc}",
                code="update_aborted",
                hint="Live install untouched.",
                exit_code=EXIT_ERROR,
            )


def _do_update(
    client: httpx.Client,
    ctx: click.Context,
    d,  # cliff_cli.daemon module
    release: Release,
    current: str,
) -> None:
    """Two-phase update: validate first, then swap.

    Phase A (validate-before-touch) — never modifies the live install:
      1. Disk-space pre-flight.
      2. Stop daemon.
      3. Download tarball into a tempdir.
      4. Verify SHA-256 against the sidecar (if present).
      5. Verify the tarball contains the entries we need.

    Phase B (swap) — only runs if Phase A succeeded:
      6. Snapshot live install with a timestamped suffix (never clobbers).
      7. Extract.
      8. Re-run bundled installers.
      9. Doctor.
      10. Start daemon.

    On any Phase B failure, ``_rollback`` restores from the snapshot. The
    rollback survives partial rmtree by renaming residue aside.
    """
    # ----- Phase A: validate before we touch the live install ----------------
    click.echo("[1/9] checking disk space")
    check_free_space(d.CLIFF_HOME)

    click.echo("[2/9] stopping daemon")
    ctx.invoke(d.stop_cmd, timeout=10.0, force=False)

    # The tempdir context wraps the entire swap so the tarball stays on disk
    # for extraction.
    with tempfile.TemporaryDirectory() as tmpdir:
        tar_path = Path(tmpdir) / "cliffsec.tar.gz"

        click.echo(f"[3/9] downloading {release.tarball_url}")
        actual_sha = download_tarball(client, release, tar_path)

        expected_sha = fetch_expected_sha256(client, release)
        if expected_sha:
            if actual_sha.lower() != expected_sha.lower():
                emit_error(
                    "Tarball SHA-256 mismatch — refusing to install.",
                    code="checksum_mismatch",
                    hint=f"expected {expected_sha}, got {actual_sha}. Live install untouched.",
                    exit_code=EXIT_ERROR,
                )
            click.echo("[4/9] checksum verified")
        else:
            click.echo(
                "[4/9] checksum sidecar absent — skipping (HTTPS transport)",
                err=True,
            )

        click.echo("[5/9] verifying tarball contents")
        try:
            verify_tarball_shape(tar_path)
        except RuntimeError as exc:
            emit_error(
                f"{exc} Live install untouched.",
                code="bad_tarball",
                exit_code=EXIT_ERROR,
            )

        # ----- Phase B: live install touched here on out --------------------
        ts = time.strftime("%Y%m%d-%H%M%S")
        snap_app = d.CLIFF_HOME / f"app.bak-{current}-{ts}"
        snap_bin = d.CLIFF_HOME / f"bin.bak-{current}-{ts}"

        click.echo(f"[6/9] snapshotting -> {snap_app.name}, {snap_bin.name}")
        if d.APP_DIR.exists():
            d.APP_DIR.rename(snap_app)
        if d.BIN_DIR.exists():
            d.BIN_DIR.rename(snap_bin)

        rolled_back = False

        def _rollback(reason: str) -> None:
            nonlocal rolled_back
            rolled_back = True
            click.echo(f"  rolling back: {reason}", err=True)
            # Get the new (possibly partial) install out of the way. If
            # rmtree leaves residue, it gets renamed aside so the snapshot
            # rename-back has a clear target.
            for live in (d.APP_DIR, d.BIN_DIR):
                residue = robust_rmtree(live)
                if residue is not None:
                    click.echo(
                        f"  could not fully remove {live.name}; preserved as {residue.name}",
                        err=True,
                    )
            if snap_app.exists():
                snap_app.rename(d.APP_DIR)
            if snap_bin.exists():
                snap_bin.rename(d.BIN_DIR)
            with contextlib.suppress(SystemExit):
                ctx.invoke(d.start_cmd, detach=True, port=None, host=None)

        try:
            click.echo("[7/9] extracting tarball")
            d.APP_DIR.mkdir(parents=True, exist_ok=True)
            safe_extract(tar_path, d.APP_DIR)

            click.echo("[8/9] re-running bundled installers (opencode + scanners)")
            d.BIN_DIR.mkdir(parents=True, exist_ok=True)
            _run_bundled_installers(d)

            click.echo("[9/9] running doctor checks + starting daemon")
            checks = d._gather_doctor_checks()
            failing = [c["name"] for c in checks if not c["ok"] and not c["warn_only"]]
            if failing:
                raise RuntimeError(f"doctor failed: {failing}")

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

    # Success: keep the most recent snapshots, prune older ones.
    prune_snapshots(d.CLIFF_HOME, retain=SNAPSHOT_RETENTION)

    click.echo(f"\nUpdated {current} -> {release.version}.")
    if not _running_from_managed_venv(d.CLIFF_HOME):
        click.echo(
            "Note: the CLI itself was not updated (it's not running from "
            f"{d.CLIFF_HOME / 'cli-venv'}). If you installed via "
            "`pip install cliffsec`, upgrade the package separately.",
            err=True,
        )


def _run_bundled_installers(d) -> None:
    """Run install-opencode.sh and install-scanners.sh shipped inside the new tarball.

    These scripts download the pinned binaries from GitHub Releases and drop
    them into ``$CLIFF_HOME/bin/``. They tolerate being re-run.
    """
    scripts_dir = d.APP_DIR / "scripts"
    env = os.environ.copy()
    env["CLIFF_HOME"] = str(d.CLIFF_HOME)
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
