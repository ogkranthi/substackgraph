#!/bin/sh
# Optionally seed the cache with the demo neighborhood on first boot so the site shows
# something immediately, then start the server. Honors $PORT if the platform injects one.
set -e

if [ "${LOAD_DEMO_ON_START:-0}" = "1" ]; then
  substackgraph load-demo || echo "load-demo skipped (cache may already be populated)"
fi

exec uvicorn substackgraph.web:app --host 0.0.0.0 --port "${PORT:-8000}"
