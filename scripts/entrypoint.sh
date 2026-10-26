#!/bin/sh
set -eu
if [ "$(id -u)" = 0 ]; then
    PUID=${PUID:-1000}
    PGID=${PGID:-1000}
    case "$PUID:$PGID" in *[!0-9:]*) echo 'PUID/PGID doivent être numériques.' >&2; exit 1;; esac
    mkdir -p "$CONFIG_DIR"
    chown "$PUID:$PGID" "$CONFIG_DIR"
    chmod 700 "$CONFIG_DIR"
    # Only config is owned here; NEVER recursively chown the mounted media library.
    exec gosu "$PUID:$PGID" "$@"
fi
exec "$@"
