#!/usr/bin/env bash
set -euo pipefail

# Cliff container entrypoint
# Refuses to run as root, ensures data directory exists, then starts supervisord.

if [ "$(id -u)" = "0" ]; then
    echo "ERROR: refusing to run as root. The image runs as the 'cliff' user (UID 10001)." >&2
    echo "       If you mounted /data from a host directory, chown it to 10001:10001." >&2
    exit 1
fi

DATA_DIR="${CLIFF_DATA_DIR:-/data}"
VERSION="$(cat /app/VERSION 2>/dev/null || echo unknown)"

echo "=== Cliff ${VERSION} ==="
echo "  Data dir:    $DATA_DIR"
echo "  App port:    ${CLIFF_APP_PORT:-8000}"
echo "  Running as:  $(id -un) (uid=$(id -u))"
echo "==============="

# Ensure data directory exists (already chowned at build time for /data;
# bind-mounts are the user's responsibility — see error above).
mkdir -p "$DATA_DIR"

# First-run detection
if [ ! -f "$DATA_DIR/cliff.db" ]; then
    echo "  First run: no existing database found"
else
    echo "  Existing database: $DATA_DIR/cliff.db"
fi

# Start all services via supervisord
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/cliff.conf
