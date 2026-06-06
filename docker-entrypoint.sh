#!/bin/sh
# Start the server with optional first-boot crawl.
#
# SEED_URL + RECRAWL_MARKER control live crawling:
#   - If SEED_URL is set and the DB has no row matching RECRAWL_MARKER, the cache
#     is cleared and a fresh crawl runs in the background (≤1 req/s). The site
#     serves an empty placeholder during the crawl (~2-10 min), then real data.
#   - Once the crawl finishes, the marker is written; subsequent restarts skip it.
#   - To force a recrawl after code changes: bump RECRAWL_MARKER in fly.toml.
#   - Without SEED_URL, falls back to LOAD_DEMO_ON_START=1 for local dev.
#
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

if [ -n "${SEED_URL:-}" ]; then
  _marker="${RECRAWL_MARKER:-v1}"
  _marker_key="_crawl_marker:${_marker}"

  # Returns 0 if this exact marker is already stored (crawl already done).
  _crawl_done() {
    SUBSTACKGRAPH_DB="$DB_PATH" MARKER_KEY="$_marker_key" python3 - <<'PYEOF'
import os, sys, sqlite3
p = os.environ.get('SUBSTACKGRAPH_DB', '/data/cache.sqlite')
k = os.environ.get('MARKER_KEY', '')
if not os.path.exists(p):
    sys.exit(1)
try:
    conn = sqlite3.connect(p)
    row = conn.execute("SELECT 1 FROM http_cache WHERE cache_key=?", (k,)).fetchone()
    conn.close()
    sys.exit(0 if row else 1)
except Exception:
    sys.exit(1)
PYEOF
  }

  if _crawl_done; then
    echo "Crawl already done for marker=$_marker, skipping."
  else
    echo "Starting background crawl for $SEED_URL (marker=$_marker)..."
    {
      substackgraph crawl --seed "$SEED_URL" --force
      SUBSTACKGRAPH_DB="$DB_PATH" MARKER_KEY="$_marker_key" python3 - <<'PYEOF'
import os, sqlite3
from datetime import datetime, timezone
p = os.environ.get('SUBSTACKGRAPH_DB', '/data/cache.sqlite')
k = os.environ.get('MARKER_KEY', '')
conn = sqlite3.connect(p)
conn.execute(
    "INSERT OR REPLACE INTO http_cache (cache_key, url, fetched_at, status, payload_json) VALUES (?, '', ?, 'ok', 'true')",
    (k, datetime.now(timezone.utc).isoformat())
)
conn.commit()
conn.close()
print("Crawl marker written.")
PYEOF
    } > /tmp/crawl.log 2>&1 &
    echo "Background crawl started (PID=$!, log at /tmp/crawl.log)"
  fi

elif [ "${LOAD_DEMO_ON_START:-0}" = "1" ]; then
  substackgraph load-demo || echo "load-demo skipped (cache may already be populated)"
fi

exec uvicorn substackgraph.web:app --host 0.0.0.0 --port "${PORT:-8000}"
