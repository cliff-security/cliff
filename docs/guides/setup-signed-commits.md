# Setting up commit signing

The `main` branch requires all commits to carry a verified signature. This guide walks through the one-time setup using either a GPG key or an SSH key.

## Option A: GPG signing (recommended for most contributors)

### 1. Generate a GPG key

```bash
gpg --full-generate-key
```

Choose:
- Key type: `RSA and RSA` (default) or `ECC (sign only)`
- Key size: `4096` (RSA) or `Curve 25519` (ECC)
- Expiry: `2y` (recommended — you can extend later)
- Enter your name and the email address associated with your GitHub account.

### 2. Find your key ID

```bash
gpg --list-secret-keys --keyid-format=long
```

Example output:
```
sec   rsa4096/3AA5C34371567BD2 2024-01-01 [SC]
      ...
uid   [ultimate] Your Name <you@example.com>
```

Copy the key ID after the `/` — here `3AA5C34371567BD2`.

### 3. Configure Git to use your key

```bash
git config --global user.signingkey 3AA5C34371567BD2
git config --global commit.gpgsign true
git config --global tag.gpgsign true
```

### 4. Export your public key and add it to GitHub

```bash
gpg --armor --export 3AA5C34371567BD2
```

Copy the entire block starting with `-----BEGIN PGP PUBLIC KEY BLOCK-----`.

In GitHub: **Settings → SSH and GPG keys → New GPG key** — paste and save.

### 5. (macOS) Store the passphrase in the keychain

Install `pinentry-mac` so Git can unlock the key without prompting every time:

```bash
brew install gnupg pinentry-mac
echo "pinentry-program $(which pinentry-mac)" >> ~/.gnupg/gpg-agent.conf
gpgconf --kill gpg-agent
```

---

## Option B: SSH signing (simpler, no separate key needed)

If you already use an SSH key for GitHub authentication, you can reuse it for commit signing.

### 1. Tell Git to use SSH for signing

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519.pub  # adjust path if needed
git config --global commit.gpgsign true
git config --global tag.gpgsign true
```

### 2. Add the key to GitHub as a signing key

In GitHub: **Settings → SSH and GPG keys → New SSH key** — choose key type **Signing Key**, paste your public key, and save.

> Note: if the same key is already present as an Authentication key, you must add it a second time as a Signing key.

---

## Verify your setup

Make a test commit and check its signature:

```bash
git commit --allow-empty -m "test: verify signing setup"
git log --show-signature -1
```

You should see output similar to:

```
gpg: Signature made ...
gpg: Good signature from "Your Name <you@example.com>"
```

or (SSH):

```
Good "git" signature for you@example.com with ED25519 key SHA256:...
```

Push to a feature branch and open a PR. GitHub will display a **Verified** badge next to the commit in the UI.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `error: gpg failed to sign the data` | Run `export GPG_TTY=$(tty)` and add it to your shell profile |
| Passphrase prompt on every commit (macOS) | Install `pinentry-mac` (see step 5 above) |
| Push rejected: "unsigned commit" | Your local branch has unsigned commits — see below |
| `invalid key` when uploading SSH key to GitHub | Use the `.pub` file, not the private key |

### Signing commits you've already made (before the rule was active)

If you have existing unsigned commits on a feature branch:

```bash
# Interactively sign the last N commits
git rebase --exec 'git commit --amend --no-edit -S' HEAD~N
```

Replace `N` with the number of commits to re-sign. Then force-push your feature branch (never `main`).

---

## Enforcement date

Branch protection requiring signed commits on `main` is active as of **2026-05-13**.

After this date, pushes to `main` (directly or via merged PR) will be rejected unless every commit in the push is signed by a key registered on the committer's GitHub account.
