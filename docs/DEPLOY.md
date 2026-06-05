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

## Recommended: Fly.io with push-to-deploy (zero-ops)

After a **one-time** setup, every `git push` to the dev/default branch deploys to production
automatically via `.github/workflows/deploy-fly.yml` — no laptop, no per-change steps. The
SQLite cache lives on a persistent Fly volume, TLS is managed, and Cloudflare sits in front.

### One-time setup (~10 min, needs your accounts)

1. Install flyctl and sign in: `curl -L https://fly.io/install.sh | sh` then `fly auth login`.
2. Create the app (matches `app` in `fly.toml`; pick another name if taken):
   ```bash
   fly apps create substackgraph
   ```
3. Create the persistent volume for the cache (same name as `[mounts].source`):
   ```bash
   fly volumes create data --region iad --size 1   # 1 GB; match your fly.toml region
   ```
4. Create a deploy token and add it to GitHub as a repository secret named `FLY_API_TOKEN`:
   ```bash
   fly tokens create deploy -x 999999h
   ```
   Add it under **GitHub → repo → Settings → Secrets and variables → Actions → New secret**.
5. Point the domain through Cloudflare:
   ```bash
   fly certs add substackgraph.com
   ```
   Then in **Cloudflare → DNS** add a `CNAME` `substackgraph.com → substackgraph.fly.dev`
   (proxied / orange cloud), and set **SSL/TLS mode to Full (strict)**.

That's it. The first deploy runs on your next push (or trigger it now from the **Actions** tab
via *Run workflow*). After this, **shipping is just a commit/push — fully phone-driven.**

### What's automatic from here on

- Push → GitHub Actions builds the image on Fly's remote builder and deploys it.
- The volume persists the cache across deploys and machine restarts.
- The app scales to zero when idle (cost control); set `min_machines_running = 1` in
  `fly.toml` for an always-warm instance.
- Before the secret exists, the deploy workflow **no-ops cleanly** (stays green).

### Seeding real data

The site boots with the demo neighborhood. To show a real map, run a crawl once the host can
reach Substack and confirm the `substack-api` field names first (see `client.extract_identity`):

```bash
fly ssh console -C "substackgraph crawl --seed https://theairuntime.substack.com"
```

## Prebuilt image (no local build needed)

CI builds and publishes the image to GHCR on every push to the default/dev branch, so you
can pull and run it directly — no need to build from source on the server:

```bash
docker pull ghcr.io/ogkranthi/substackgraph:latest
docker run -d --name substackgraph -p 8000:8000 \
  -e LOAD_DEMO_ON_START=1 -v substackgraph-data:/data \
  ghcr.io/ogkranthi/substackgraph:latest
```

> First time only: the GHCR package starts **private**. Either `docker login ghcr.io` with a
> PAT, or flip the package to public under the repo's **Packages** settings for
> unauthenticated `docker pull`.

## Build from source instead

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
