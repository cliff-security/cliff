# ADR-0028: Subprocess-only scanner execution with pinned binary checksums

**Date:** 2026-04-19
**Status:** Accepted
**Supersedes:** [ADR-0026](0026-tiered-scanner-execution.md) (tiered Docker + subprocess model)
**Context PRD:** PRD-0003 (Security assessment v2)
**Relates to:** ADR-0005 (single Docker container), ADR-0027 (unified findings model)

---

## Context

ADR-0026 proposed a tiered scanner execution model: a Docker runner as the secure-by-default path, with a subprocess runner as fallback for hosts without Docker. Under review (architect pass, 2026-04-19), the Docker runner's security premise was found to hold only in a minority of Cliff's deployment paths, and the complexity cost to support both runners wasn't earning its keep.

### What ADR-0026 got wrong

**The Docker runner's isolation is conditional on how Cliff itself is deployed:**

- **Cliff running on bare metal (`scripts/dev.sh`, future binary distribution).** Cliff spawns scanner containers as peers. Scanner is isolated in a read-only ephemeral container. This is real isolation.
- **Cliff running inside its own Docker container (the ADR-0005 production path, which is *the* deployment path).** For Cliff to spawn scanner containers, it must have access to the host Docker socket (`-v /var/run/docker.sock:/var/run/docker.sock`). The moment that mount exists, any code inside the Cliff container has full host Docker API access — it can spawn privileged containers, mount the host filesystem, escalate to root. **A compromised scanner exploiting the socket mount is strictly worse than a compromised scanner running as a subprocess.** The Docker runner in the production path is a security regression dressed as security hardening.

**The "or" hedges were load-bearing.** ADR-0026 said "no network after image pull *or* we allow network for DB download" — the very kind of hedge that creates inconsistent behavior across deployments. Two paths means deciding-by-accident.

**Doubling test and deployment surface.** Two runners meant: two CI paths to keep green, two sets of docs, a detection layer, a config knob, runtime-fallback semantics when the "preferred" runner fails mid-session. Each of those is a place for bugs to hide and an obstacle for a single-user community edition.

### What the user (correctly) worried about

The CEO raised the real concern: "I don't want this supply chain attack on my PC and on my user's PC." The question is whether containerization meaningfully reduces that risk. For Cliff's actual deployment shape, it does not — and the container runner was creating the false impression that it did.

---

## Decision

### Subprocess-only execution

Cliff runs Trivy and Semgrep as subprocesses. No Docker runner. The `ScannerRunner` protocol from ADR-0026 remains as a seam, but only one implementation exists.

```python
class ScannerRunner(Protocol):
    async def run_trivy(self, target_dir: Path, *, timeout: int = 300) -> TrivyResult: ...
    async def run_semgrep(self, target_dir: Path, *, timeout: int = 300) -> SemgrepResult: ...
    def available_scanners(self) -> list[ScannerInfo]: ...
```

No auto-detection at startup. No runtime fallback. No `CLIFF_SCANNER_RUNNER` knob. One path.

### Supply chain defense, moved to the binary layer

Since isolation via Docker is off the table, the trust story moves to the binary itself:

1. **Pinned SHA256 checksums.** `.scanner-versions` holds the exact checksum of each scanner binary, not a Docker image digest:

   ```
   # .scanner-versions
   trivy_version=0.52.0
   trivy_url=https://github.com/aquasecurity/trivy/releases/download/v0.52.0/trivy_0.52.0_Linux-64bit.tar.gz
   trivy_sha256=<checksum>

   semgrep_version=1.70.0
   semgrep_url=https://github.com/semgrep/semgrep/releases/download/v1.70.0/...
   semgrep_sha256=<checksum>
   ```

2. **Official release artifacts only.** Binaries are downloaded from the scanner projects' GitHub releases. **Not from `pip`, `npm`, `brew`, `apt`, or a distro repo** — each of those adds a separate supply chain under someone else's control. GitHub releases + signed commits on `aquasec/trivy` and `semgrep/semgrep` is the shortest trusted path.

3. **Verification before first execution.** The install script (`scripts/install-scanners.sh`, mirroring `scripts/install-opencode.sh`) downloads the binary, computes SHA256, compares against `.scanner-versions`. On mismatch it aborts and refuses to install. The Docker image build (`docker/Dockerfile`) runs the same verification at build time and fails the build on mismatch.

4. **No auto-update.** Scanner binaries change only when Cliff cuts a release. The release process is the human review gate where new checksums are adopted. Today that process is Gal reviewing the diff; it formalizes later.

5. **Minimal subprocess environment.** The scanner subprocess receives an explicit env whitelist — `PATH`, `HOME`, `LANG`, and `TRIVY_CACHE_DIR`/`SEMGREP_RULES_CACHE_DIR` only. **The GitHub PAT is not in the scanner's environment.** A compromised scanner cannot exfiltrate credentials it never saw.

6. **Non-root.** Cliff runs as a non-root user and spawns scanners under that user. No `sudo`, no capability grants.

### What's explicitly NOT done

- **No sandboxing via seccomp / AppArmor / bwrap.** Possible future hardening, but each adds OS-specific code and failure modes. Not v1.
- **No air-gap mode.** Trivy fetches its vuln DB over network on each run (Trivy handles its own caching). Semgrep's rules are bundled in the binary. An `CLIFF_TRIVY_OFFLINE=1` mode is a reasonable follow-up if a user asks.
- **No scanner sidecar container pattern.** If a security-conscious user wants container isolation, they can fork and add it. The default path is simple and honest about its trust boundary.

### User overrides

| Env var | Purpose | Default |
|---------|---------|---------|
| `CLIFF_TRIVY_BINARY` | Path to an already-installed `trivy` binary (e.g., air-gapped) | Pinned binary baked into Cliff install |
| `CLIFF_SEMGREP_BINARY` | Path to an already-installed `semgrep` binary | Pinned binary baked into Cliff install |
| `CLIFF_SCANNER_CHECKSUM_VERIFY` | `strict` (default) fails on mismatch; `warn` logs and proceeds | `strict` |

`strict` is the default because silent drift on a security tool's binary is the exact class of issue we are trying to prevent.

---

## What changes vs ADR-0026

| Concern | ADR-0026 (superseded) | ADR-0028 (this) |
|---------|------------------------|------------------|
| Runners | Docker + subprocess, tiered with detection | Subprocess only |
| Isolation | Ephemeral read-only container | Cliff user process |
| Supply chain unit | Pinned image digests | Pinned binary checksums |
| Binary source | Docker Hub / Trivy registry | GitHub release artifacts |
| Docker in Docker | Required socket mount for production path (unacknowledged risk) | Not used |
| Config knobs | `CLIFF_SCANNER_RUNNER`, `CLIFF_TRIVY_IMAGE`, `CLIFF_SEMGREP_IMAGE` | `CLIFF_TRIVY_BINARY`, `CLIFF_SEMGREP_BINARY`, `CLIFF_SCANNER_CHECKSUM_VERIFY` |
| Env exposure to scanner | Full Cliff env | Minimal whitelist; no PAT |
| Code paths to maintain | Two runners + detection + fallback | One runner |

---

## Consequences

**Easier:**

- One runner, one CI path, one set of docs, one set of install steps.
- Deployment is just `docker run cliff` — no socket mount instructions, no explanation of trade-offs.
- Supply chain story is clearer to tell and audit: "we pin this binary, we download it from this URL, we verify this checksum, the release process updates those."
- Credential exposure is actually smaller than ADR-0026's subprocess fallback because the env whitelist closes a leak that the old ADR didn't call out.
- Removes the false-security footgun of mounting the Docker socket "for isolation."

**Harder:**

- No container-level isolation if a scanner binary is compromised. The attacker gets Cliff-user-level access: the cloned repo, the SQLite DB, and whatever outbound network Cliff has. This is bounded but non-zero. We accept the trade because the realistic alternative (mounted Docker socket inside the Cliff container) is worse.
- Adds a scanner install step to the Cliff install process. `scripts/install-scanners.sh` downloads + verifies both binaries; must run before first assessment. In Docker builds this happens at image build time.
- Binary pins must be refreshed per Cliff release. Adds one step to the release checklist: regenerate `.scanner-versions` against the new upstream versions and review the diff.

**Risks:**

| Risk | Mitigation |
|------|------------|
| Upstream scanner release gets compromised | Pinning is per-checksum, not per-version — a re-pushed compromised v0.52.0 would fail verification since the checksum would change. Release-time review of `.scanner-versions` diffs is the human gate |
| Scanner DB fetch over network during scan | Trivy's DB fetch is documented and expected; we do not block it. `CLIFF_TRIVY_OFFLINE=1` deferred until requested |
| User runs with `CHECKSUM_VERIFY=warn` and hits a real mismatch | Default is `strict`. `warn` is for controlled debugging only and is documented as such |
| Scanner binary crashes or hangs | Subprocess timeout (300s default), process killed on timeout, assessment reports scanner as failed/skipped, stale-close rule in ADR-0027 correctly refuses to close findings when the scanner didn't run successfully |

---

## Follow-ups

- `scripts/install-scanners.sh` — downloads + verifies Trivy and Semgrep against `.scanner-versions`. Called by `scripts/dev.sh` and `docker/Dockerfile`.
- IMPL-0003 Epic 1 is simplified: drop `docker_runner.py`, `detection.py`; `subprocess_runner.py` becomes the sole runner (rename to `runner.py`). No auto-detection code.
- IMPL-0003 `docker/Dockerfile` changes: install pinned Trivy + Semgrep binaries at build time with checksum verification. Remove socket-mount documentation from `docker-compose.yml`.
- Release checklist item: regenerate scanner checksums when upstream releases are adopted. To be documented alongside the first tagged Cliff release.
- Future hardening (not in v1): seccomp profile, outbound-network allowlist for the scanner subprocess, optional sandboxed execution via `bwrap`.
