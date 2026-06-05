# Deploying the live site to substackgraph.com

The app is a real, dynamic FastAPI server (`substackgraph.web:app`). It reads the SQLite
cache and runs the identity-resolution harness on every request — the before/after toggle
and the decision-log API are live, not pre-baked.

Substack itself can't run this Python app, so the pattern is **the app runs in a container,
Cloudflare sits in front** of it for `substackgraph.com` (TLS + DNS). Two paths below; the
Tunnel path keeps everything "in Cloudflare" with no separate cloud account.

> **Scope / ToS note.** Live, on-demand crawling of Substack is **off by default**
> (`ALLOW_LIVE_CRAWL=0`). The public site serves neighborhoods that are already cached.
> Only enable on-demand crawling for trusted deployments, and keep the ≤1 req/sec limiter.

## Build & run the container

```bash
docker build -t substackgraph .
# Persist the cache on a host volume so crawled data survives restarts.
docker run -d --name substackgraph -p 8000:8000 -v substackgraph-data:/data substackgraph

# Seed something to display (demo neighborhood, or a real crawl):
docker exec substackgraph substackgraph load-demo
#   or, with live network + crawling allowed:
#   docker exec -e ALLOW_LIVE_CRAWL=1 substackgraph substackgraph crawl --seed https://theairuntime.substack.com
```

Verify locally: `curl localhost:8000/healthz` and open `http://localhost:8000/`.

## Path A — Cloudflare Tunnel (recommended; stays in Cloudflare)

Run the app anywhere (a small VPS, a home server, even the same box) and expose it on your
domain through Cloudflare with automatic TLS. No public inbound ports, no separate PaaS.

1. In the **Cloudflare dashboard → Zero Trust → Networks → Tunnels**, create a tunnel and
   copy its token.
2. Run `cloudflared` alongside the app (example with docker-compose):

   ```yaml
   services:
     app:
       build: .
       environment:
         - SUBSTACKGRAPH_DB=/data/cache.sqlite
       volumes:
         - substackgraph-data:/data
     cloudflared:
       image: cloudflare/cloudflared:latest
       command: tunnel run
       environment:
         - TUNNEL_TOKEN=${TUNNEL_TOKEN}
   volumes:
     substackgraph-data:
   ```

3. In the tunnel's **Public Hostname** config, map `substackgraph.com` (and `www`) to the
   service `http://app:8000`. Cloudflare creates the DNS records for you.
4. Done — `https://substackgraph.com` now serves the app, proxied (orange-cloud) through
   Cloudflare with TLS terminated at the edge.

## Path B — Container host + Cloudflare DNS

Deploy the image to a Python-friendly host (Render, Railway, Fly.io, or any VM), then point
Cloudflare at it.

1. Deploy the container; the platform gives you an origin hostname (e.g.
   `substackgraph.onrender.com`). These platforms inject `$PORT`, which the Dockerfile honors.
2. In **Cloudflare → DNS**, add a `CNAME` for `substackgraph.com` → the origin hostname
   (proxied / orange cloud). Add `www` the same way.
3. Set **SSL/TLS mode to Full (strict)** so the edge ↔ origin hop is also encrypted.
4. Add a mounted volume / disk for `/data` so the cache persists across deploys.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `SUBSTACKGRAPH_DB` | `artifacts/cache.sqlite` | SQLite cache path (point at a mounted volume) |
| `SUBSTACKGRAPH_SEED` | `https://theairuntime.substack.com` | seed shown on the landing page |
| `ALLOW_LIVE_CRAWL` | `0` | set `1` to allow on-demand crawls via `POST /crawl` |
| `PORT` | `8000` | injected by some hosts; the Dockerfile honors it |

## Routes

- `GET /` — landing page with the live resolved map embedded.
- `GET /graph?mode=resolved|naive` — the dynamic before/after map.
- `GET /api/graph` — canonical nodes + edges as JSON.
- `GET /api/decisions` — the replayable resolution decision log as JSON.
- `POST /crawl?seed=<url>` — enqueue a background crawl (only if `ALLOW_LIVE_CRAWL=1`).
- `GET /healthz` — health check.
