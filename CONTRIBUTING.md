# Contributing to Cliff

Thank you for your interest in contributing. This document covers the essentials for getting changes reviewed and merged.

## Code of conduct

Be respectful and constructive. We follow the [Contributor Covenant](https://www.contributor-covenant.org/).

## Development setup

Prerequisites: Python 3.11+ with [`uv`](https://docs.astral.sh/uv/), Node.js 20+, and a clone of this repo.

```bash
# Install dependencies
cd backend && uv sync
cd ../frontend && npm install

# Start dev environment (backend on :8000, frontend on :5173)
cd .. && scripts/dev.sh
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173) and paste an Anthropic or OpenAI key in Settings.

## Branching and pull requests

- All changes must go through a pull request targeting `main`.
- Direct pushes to `main` are not permitted.
- Branch naming: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`, `refactor/<slug>`, `test/<slug>`.
- One PR per logical change. Keep commits focused.

## Commit signing (required)

**All commits merged to `main` must carry a verified GPG or SSH signature.**

The `main` branch has "Require signed commits" enabled. Unsigned commits will be rejected when you push.

Before your first contribution:

1. Set up commit signing — GitHub's [signing commits guide](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits) covers GPG, SSH, and S/MIME.
2. Upload your public key to your GitHub account under **Settings → SSH and GPG keys**.
3. Verify your setup: `git log --show-signature -1` should show `Good signature from …`.

## Sign-off / Developer Certificate of Origin (required)

Each commit must include a `Signed-off-by:` trailer certifying the [Developer Certificate of Origin 1.1](https://developercertificate.org/). The sign-off is your statement that you wrote the contribution (or otherwise have the right to submit it) and that you agree to license it under this project's terms.

Add the trailer automatically by committing with `-s`:

```bash
git commit -s -m "feat: add findings export to CSV"
```

The resulting commit message ends with `Signed-off-by: Your Name <you@example.com>`. Configure `user.name` and `user.email` in git so the trailer matches your GitHub identity.

Cliff is licensed under [`AGPL-3.0-only`](LICENSE). Inbound contributions are licensed `AGPL-3.0-only` to match — there is no separate CLA.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add findings export to CSV
fix: prevent workspace idle timeout race condition
docs: clarify adapter interface contract
refactor: simplify process pool retry logic
test: cover edge case in context builder
```

## Tests

Every PR must pass all tests before review:

```bash
# Unit tests (fast)
cd backend && uv run pytest -v -m 'not e2e'

# Lint
cd backend && uv run ruff check cliff/ tests/

# Frontend
cd frontend && npm test
```

## Review process

`@galanko` is the required code owner and must approve all PRs before merge. Please allow up to 3 business days for a first review pass.
