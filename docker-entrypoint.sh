#!/bin/sh
# Start the server. On first boot (empty DB):
#   - If SEED_URL is set: load demo as instant placeholder, then crawl the real
#     network in the background (≤1 req/s). Next page reload after the crawl
#     finishes (~2-10 min) shows real data. Subsequent restarts skip the crawl.
#   - Else if LOAD_DEMO_ON_START=1: load the hand-built demo neighborhood only.
# Honors $PORT if the platform injects one.
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

# Returns 0 if the DB has at least one cached row, 1 if empty or missing.
_db_has_data() {
  python3 - <<'EOF'
import os, sys, sqlite3
p = os.environ.get('SUBSTACKGRAPH_DB', '/data/cache.sqlite')
if not os.path.exists(p):
    sys.exit(1)
try:
    conn = sqlite3.connect(p)
    n = conn.execute('SELECT COUNT(*) FROM http_cache').fetchone()[0]
    conn.close()
    sys.exit(0 if n > 0 else 1)
except Exception:
    sys.exit(1)
EOF
}

if ! _db_has_data; then
  if [ -n "${SEED_URL:-}" ]; then
    echo "DB is empty — loading demo as placeholder, then crawling $SEED_URL in background..."
    substackgraph load-demo 2>/dev/null || true
    substackgraph crawl --seed "$SEED_URL" > /tmp/crawl.log 2>&1 &
    echo "Background crawl started (PID=$!, log at /tmp/crawl.log)"
  elif [ "${LOAD_DEMO_ON_START:-0}" = "1" ]; then
    substackgraph load-demo || echo "load-demo skipped (cache may already be populated)"
  fi
fi

exec uvicorn substackgraph.web:app --host 0.0.0.0 --port "${PORT:-8000}"
