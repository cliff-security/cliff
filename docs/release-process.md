# Releasing Cliff

This is the runbook for cutting a release of Cliff. It documents both
the per-release steps and the one-time GitHub UI configuration that
makes the release workflow safe.

## Per-release procedure

1. **Prepare a release PR**
   - Update [`VERSION`](../VERSION) to the new version (e.g. `0.1.0-alpha`).
   - Update [`CHANGELOG.md`](../CHANGELOG.md) — add a new
     `## [<version>] - YYYY-MM-DD` section with the changes.
   - Bump [`backend/pyproject.toml`](../backend/pyproject.toml) to the
     PEP 440 form (`0.1.0a0`, `0.1.0`, `0.2.0a1`, ...).
   - Bump [`frontend/package.json`](../frontend/package.json) to the
     same SemVer string as `VERSION`.
   - PR → merge to `main`.

2. **Dry-run locally**

   ```bash
   bash scripts/release-dryrun.sh
   ```

   Exits 0 only if the working tree is clean, `VERSION` matches the
   CHANGELOG, the multi-arch buildx works, and Trivy finds no fixable
   CRITICAL CVEs.

3. **Tag and push from `main`**

   ```bash
   git checkout main && git pull --ff-only
   git tag -a "v$(cat VERSION)" -m "v$(cat VERSION)"
   git push origin "v$(cat VERSION)"
   ```

   The tag must be **annotated** (`-a`). The workflow's `validate` job
   refuses lightweight tags.

4. **Approve in the GitHub Environment**
   - The tag push triggers `.github/workflows/release.yml`.
   - `validate` and `smoke-tests` run unattended (~5 min).
   - `build-and-publish` pauses on the **`release`** environment.
     Open the workflow run in the GitHub UI, click
     **Review deployments**, and approve.

5. **Verify the published image**

   ```bash
   VERSION=$(cat VERSION)
   docker buildx imagetools inspect "ghcr.io/galanko/cliff:${VERSION}"
   DIGEST=$(docker buildx imagetools inspect "ghcr.io/galanko/cliff:${VERSION}" --format '{{json .Manifest}}' | jq -r .digest)

   cosign verify "ghcr.io/galanko/cliff@${DIGEST}" \
     --certificate-identity-regexp 'https://github\.com/galanko/Cliff/\.github/workflows/release\.yml@.*' \
     --certificate-oidc-issuer https://token.actions.githubusercontent.com

   gh attestation verify "oci://ghcr.io/galanko/cliff@${DIGEST}" --owner galanko
   ```

6. **Spot-check the GitHub Release page** — `<repo>/releases/tag/v<version>`
   should be marked as pre-release (for `-alpha`/`-beta`/`-rc`) and
   carry the SBOM (`cliff-<version>.cdx.json`) plus
   `verification.txt`.

## One-time repo configuration

Done once by a repo admin; record any deviation here. None of these are
self-applying — GitHub doesn't expose the relevant APIs to a workflow
running with the default token.

### Environment: `release`

`Settings → Environments → New environment` named `release`:

- **Required reviewers:** `galanko` (this is the human gate before any
  push to `ghcr.io`).
- **Wait timer:** 0.
- **Deployment branches and tags:** `Selected branches and tags` → add a
  rule for the tag pattern `v*`.
- No environment secrets required — the workflow uses the default
  `GITHUB_TOKEN` for ghcr login and OIDC for keyless signing.

### Tag protection

`Settings → Tags → New rule`:

- **Pattern:** `v*`
- **Restrict tag creation/deletion** to repository administrators.

### Branch protection on `main`

`Settings → Branches → Branch protection rules → Add rule`:

- **Pattern:** `main`
- **Require a pull request before merging** ✓
  - **Require approvals:** 1
  - **Require review from Code Owners** ✓
- **Require status checks to pass:** `backend.yml` and `frontend.yml`
- **Require linear history** ✓
- **Require signed commits** ✓ (recommended)
- **Restrict pushes that create matching branches** to admins.

### Workflow permissions

`Settings → Actions → General → Workflow permissions`:

- **Default permissions:** `Read repository contents and packages
  permissions`.
- **Allow GitHub Actions to create and approve pull requests:** off.

### Package visibility

After the first successful release, GitHub creates the package as
private (default for packages from public repos). Make it public:

- `<repo> → Packages → cliff → Package settings`
- **Manage Actions access:** link to `galanko/Cliff` with role
  *Write*.
- **Danger Zone → Change visibility → Public**.

## Why each guardrail exists

- **Tag must be annotated** — lightweight tags are mutable; annotated
  tags carry a tagger identity and a signed-commit chain when commit
  signing is enforced on `main`.
- **Tag must be reachable from `main`** — releasing from any other
  branch would let a maintainer ship code that bypassed PR review.
- **Required reviewer on `release` environment** — a stolen session or
  accidental tag push cannot publish without an explicit second click.
- **SHA-pinned actions + Dependabot** — the canonical supply-chain
  hardening lever. Without it, a compromised upstream action tag can
  exfiltrate the OIDC token mid-build and sign a malicious image as
  the legitimate workflow.
- **Trivy CRITICAL gate** — we don't ship known-fixable CRITICAL CVEs.
  HIGH+CRITICAL are tracked via SARIF in the Security tab.
- **Non-root container user** — limits the blast radius if the running
  image is compromised, and is a permanent contract once early users
  have mounted volumes.

## Removing a release (last resort)

If a published image must be withdrawn (e.g. discovered post-publication
to leak a credential), do **not** delete the tag from git history —
mark the GitHub release as draft, mark the package version as deleted
in `<repo>/packages/<name>/versions`, and publish a security advisory
with the affected digest. Communicate via the SECURITY.md channel.
