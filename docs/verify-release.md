# Verifying an Cliff release

Every Cliff image published to `ghcr.io/galanko/cliff` carries
three independent attestations, all rooted in Sigstore's transparency
log:

1. **A keyless code-signing signature** — proves the image was built
   and signed by the `release.yml` workflow on `galanko/Cliff` from
   a tag matching `v*`.
2. **A SLSA build provenance attestation** — proves *what* built the
   image (the workflow run, the runner, the inputs).
3. **A CycloneDX SBOM attestation** — proves the bill of materials
   shipped with the image is the one Sigstore signed.

You don't need anything but `cosign` and `gh` to verify them.

## TL;DR

Pin to the digest from the [release page](https://github.com/galanko/Cliff/releases),
then:

```bash
DIGEST=sha256:...     # from the release page or `docker buildx imagetools inspect`

# 1. Signature
cosign verify ghcr.io/galanko/cliff@${DIGEST} \
  --certificate-identity-regexp 'https://github\.com/galanko/Cliff/\.github/workflows/release\.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# 2. Build provenance
gh attestation verify oci://ghcr.io/galanko/cliff@${DIGEST} \
  --owner galanko

# 3. SBOM
cosign verify-attestation --type cyclonedx \
  --certificate-identity-regexp 'https://github\.com/galanko/Cliff/\.github/workflows/release\.yml@.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/galanko/cliff@${DIGEST}
```

If all three commands exit 0, the image is exactly what `galanko/Cliff`'s
`release.yml` produced and signed.

## What each verification proves

### `cosign verify` — image authenticity

Confirms two things:

1. The image digest you specified was signed by **someone holding a
   GitHub OIDC identity token issued to a workflow named
   `.github/workflows/release.yml` in `galanko/Cliff`**. Nobody else's
   identity (including any PAT, any other repo, any local dev signing
   key) will satisfy that regex.
2. The signature is recorded in the Sigstore transparency log
   (Rekor). If we ever rotated the key or the signing identity, the
   change would be auditable.

You should fail closed if this command does not exit 0.

### `gh attestation verify` — build provenance (SLSA v1)

Goes one level deeper than the signature: confirms *which workflow
run*, *on which commit*, *with which inputs* produced the image.
Output includes:

```
✓ Verification succeeded!
  ↪ predicate type:  https://slsa.dev/provenance/v1
  ↪ source repo:     galanko/Cliff
  ↪ source ref:      refs/tags/v0.1.0-alpha
  ↪ workflow:        .github/workflows/release.yml
```

This is what you cite if you ever need to prove which exact commit a
running container came from.

### `cosign verify-attestation` — SBOM authenticity

The SBOM attached to the image is signed by the same workflow.
Re-run scanners (Trivy, Grype, etc.) against it without trusting
that whoever handed you the SBOM didn't tamper with it.

## Compatibility notes

- `cosign` v2.0+ is required. We never use legacy tag-based signatures.
- `gh attestation verify` was added in GitHub CLI v2.49 (April 2024).
- All three commands work against multi-arch manifests — verification
  applies to the manifest digest, not the per-platform image digest.

## What we *don't* claim

- We don't claim the underlying base images (`python:3.11-slim`,
  `node:20-slim`) are themselves free of CVEs. We do gate releases on
  Trivy CRITICAL, and the GitHub Security tab tracks all HIGH+CRITICAL
  findings against the published digest.
- We don't sign or attest dev builds (anything not pushed by
  `release.yml`). If you need to verify a dev image, build it yourself.

## Reporting a verification failure

If any of the commands above fails on a tagged release, don't pull the
image. Email security reports to `galank@gmail.com` with `[Cliff
Security]` in the subject — see [SECURITY.md](../SECURITY.md).
