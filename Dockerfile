# substackgraph live web app. Runs anywhere that takes a container; put Cloudflare
# (Tunnel or proxy) in front for substackgraph.com. See docs/DEPLOY.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# gosu lets the entrypoint start as root (to fix mounted-volume ownership) and then
# drop to the unprivileged user to run the app.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[web]"

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Create the unprivileged user and give it the app dir. The /data volume is chowned
# at runtime by the entrypoint, because Fly/most hosts mount it root-owned over this.
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app

# Cache and any runtime artifacts live on the writable volume (the package install dir
# is read-only, so artifacts must not default under it). Both sit on /data.
ENV SUBSTACKGRAPH_DB=/data/cache.sqlite
ENV SUBSTACKGRAPH_ARTIFACTS=/data/artifacts
# Live crawling is OFF by default (ToS-sensitive); set to 1 only for trusted deploys.
ENV ALLOW_LIVE_CRAWL=0
VOLUME ["/data"]

# NOTE: container starts as root so the entrypoint can chown the mounted volume; it
# then drops to appuser via gosu before running anything. Do not add `USER appuser`.
EXPOSE 8000

# Liveness probe (no curl in slim images; use stdlib).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/healthz').status==200 else 1)"

# Honor $PORT if the platform injects one (Render/Railway/Fly), else default to 8000.
ENTRYPOINT ["docker-entrypoint.sh"]
