#!/bin/sh
# Start the server, optionally seeding the demo neighborhood on first boot so the site
# shows something immediately. Honors $PORT if the platform injects one.
set -e

DB_PATH="${SUBSTACKGRAPH_DB:-/data/cache.sqlite}"
DB_DIR=$(dirname "$DB_PATH")

# Fly (and most hosts) mount the persistent volume root-owned, masking the ownership
# baked into the image. When we start as root, make the cache dir writable by the
# unprivileged user, then re-exec this script as that user via gosu.
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DB_DIR"
  chown -R appuser:appuser "$DB_DIR"
  exec gosu appuser "$0" "$@"
fi

# --- running as appuser from here on ---
if [ "${LOAD_DEMO_ON_START:-0}" = "1" ]; then
  substackgraph load-demo || echo "load-demo skipped (cache may already be populated)"
fi

exec uvicorn substackgraph.web:app --host 0.0.0.0 --port "${PORT:-8000}"
