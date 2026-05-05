#!/usr/bin/env bash
set -euo pipefail

# Install OpenCode binary for the current platform.
# Reads version from .opencode-version at the repo root.
# Installs to ~/.opensec/bin/opencode by default.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="${OPENSEC_BIN_DIR:-$HOME/.opensec/bin}"

# Read pinned version
VERSION_FILE="$REPO_ROOT/.opencode-version"
if [[ ! -f "$VERSION_FILE" ]]; then
  echo "Error: .opencode-version not found at $VERSION_FILE"
  exit 1
fi
VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
echo "OpenCode version: $VERSION"

# Detect platform
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

case "$ARCH" in
  x86_64)  ARCH="x64" ;;
  aarch64) ARCH="arm64" ;;
  arm64)   ARCH="arm64" ;;
  *)
    echo "Error: unsupported architecture: $ARCH"
    exit 1
    ;;
esac

case "$OS" in
  darwin) EXT="zip" ;;
  linux)  EXT="tar.gz" ;;
  *)
    echo "Error: unsupported OS: $OS"
    exit 1
    ;;
esac

ASSET_NAME="opencode-${OS}-${ARCH}.${EXT}"
DOWNLOAD_URL="https://github.com/anomalyco/opencode/releases/download/v${VERSION}/${ASSET_NAME}"

# Check if already installed at correct version
if [[ -x "$INSTALL_DIR/opencode" ]]; then
  INSTALLED_VERSION="$("$INSTALL_DIR/opencode" --version 2>/dev/null || echo "unknown")"
  if echo "$INSTALLED_VERSION" | grep -q "$VERSION"; then
    echo "OpenCode $VERSION already installed at $INSTALL_DIR/opencode"
    exit 0
  fi
  echo "Updating OpenCode from $INSTALLED_VERSION to $VERSION"
fi

# Download
echo "Downloading $DOWNLOAD_URL"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

curl -fsSL "$DOWNLOAD_URL" -o "$TMPDIR/$ASSET_NAME"

# Extract
mkdir -p "$INSTALL_DIR"
case "$EXT" in
  zip)
    unzip -o "$TMPDIR/$ASSET_NAME" -d "$TMPDIR/extracted" > /dev/null
    ;;
  tar.gz)
    mkdir -p "$TMPDIR/extracted"
    tar -xzf "$TMPDIR/$ASSET_NAME" -C "$TMPDIR/extracted"
    ;;
esac

# Find and install the binary
BINARY="$(find "$TMPDIR/extracted" -name 'opencode' -type f | head -1)"
if [[ -z "$BINARY" ]]; then
  echo "Error: opencode binary not found in archive"
  exit 1
fi

cp "$BINARY" "$INSTALL_DIR/opencode"
chmod +x "$INSTALL_DIR/opencode"

# Strip macOS quarantine so Gatekeeper doesn't block the freshly-downloaded
# binary on first run. No-op on Linux and on macOS without the attribute.
if [[ "$OS" == "darwin" ]] && command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine "$INSTALL_DIR/opencode" 2>/dev/null || true
fi

# Verify
echo "Installed: $("$INSTALL_DIR/opencode" --version 2>/dev/null || echo "$INSTALL_DIR/opencode")"
echo "Location: $INSTALL_DIR/opencode"
