# substackgraph live web app. Runs anywhere that takes a container; put Cloudflare
# (Tunnel or proxy) in front for substackgraph.com. See docs/DEPLOY.md.
FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[web]"

# Cache lives on a writable volume so crawled neighborhoods survive restarts.
ENV SUBSTACKGRAPH_DB=/data/cache.sqlite
# Live crawling is OFF by default (ToS-sensitive); set to 1 only for trusted deploys.
ENV ALLOW_LIVE_CRAWL=0
VOLUME ["/data"]

EXPOSE 8000

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Honor $PORT if the platform injects one (Render/Railway/Fly), else default to 8000.
ENTRYPOINT ["docker-entrypoint.sh"]
