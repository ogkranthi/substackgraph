# substackgraph live web app. Runs anywhere that takes a container; put Cloudflare
# (Tunnel or proxy) in front for substackgraph.com. See docs/DEPLOY.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[web]"

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Run as an unprivileged user; give it ownership of the cache volume and app dir.
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app

# Cache lives on a writable volume so crawled neighborhoods survive restarts.
ENV SUBSTACKGRAPH_DB=/data/cache.sqlite
# Live crawling is OFF by default (ToS-sensitive); set to 1 only for trusted deploys.
ENV ALLOW_LIVE_CRAWL=0
VOLUME ["/data"]

USER appuser
EXPOSE 8000

# Liveness probe (no curl in slim images; use stdlib).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz').status==200 else 1)"

# Honor $PORT if the platform injects one (Render/Railway/Fly), else default to 8000.
ENTRYPOINT ["docker-entrypoint.sh"]
