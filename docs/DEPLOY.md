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

After a **one-time** setup, every `git push` deploys automatically via
`.github/workflows/deploy-fly.yml` — no laptop, no per-change steps:

- push to the **dev branch** → deploys the **staging** app (`fly.staging.toml`)
- push to **`main`** → deploys **production** (`fly.toml`, → substackgraph.com)

So changes always get exercised on a real staging URL before they reach the public domain.
The SQLite cache lives on a persistent Fly volume per app, TLS is managed, Cloudflare sits in front.

### One-time setup — what *you* do (≈5 min, phone-friendly, no terminal)

The deploy workflow **auto-creates the Fly apps and cache volumes** on its first run, so you only
need to hand it credentials. All of this is doable from a browser on your phone:

1. **Fly.io account.** Sign up at [fly.io](https://fly.io) and add a payment card (Fly requires a
   card even within the free allowance — you won't be charged at this scale).
2. **Deploy token → GitHub secret.** In the Fly dashboard, create an **org deploy token**
   (Account → **Tokens**, or run `fly tokens create org -x 999999h` if you have the CLI). Copy it.
   In GitHub: **repo → Settings → Secrets and variables → Actions → New repository secret**,
   name it **`FLY_API_TOKEN`**, paste the token.
3. *(Optional)* set repository **Variables** (same page, Variables tab) if your defaults differ:
   `FLY_REGION` (default `iad`) and `FLY_ORG` (default `personal`).

That's the whole Fly side. On your next push the workflow creates `substackgraph` +
`substackgraph-staging`, their volumes, and deploys. You can also trigger it now from the
**Actions** tab → *Deploy to Fly.io* → *Run workflow*.

#### Manual alternative (if you prefer the CLI)

<details><summary>Create the apps + volumes yourself instead of letting CI do it</summary>

```bash
curl -L https://fly.io/install.sh | sh && fly auth login
fly apps create substackgraph
fly apps create substackgraph-staging
fly volumes create data -a substackgraph         --region iad --size 1
fly volumes create data -a substackgraph-staging --region iad --size 1
fly tokens create org -x 999999h   # add the output as the FLY_API_TOKEN secret
```
</details>

### Domain — what *you* do in Cloudflare (dashboard only)

After the **production** app's first deploy (it's live at `substackgraph.fly.dev`):

1. **DNS:** in Cloudflare → **DNS → Records**, add a `CNAME`:
   `substackgraph.com → substackgraph.fly.dev`, proxy **on** (orange cloud).
2. **Certificate:** in the **Fly dashboard → app `substackgraph` → Certificates → Add Certificate**,
   enter `substackgraph.com` (or run `fly certs add substackgraph.com`). Fly issues the cert.
3. **SSL mode:** Cloudflare → **SSL/TLS → Overview → Full (strict)**.
4. Then apply the **WAF + rate limiting** settings below (all in the Cloudflare dashboard).

That's everything. From here, shipping is just a push — fully phone-driven.

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

## Cloudflare WAF + rate limiting (edge defense)

The app sets security headers and runs as non-root, but the cheapest, strongest protection is at
Cloudflare's edge — requests are filtered before they ever reach Fly (saving compute *and* blocking
abuse). Configure once, in the Cloudflare dashboard for `substackgraph.com`:

### 1. Rate limiting rule (per-IP throttle)

**Security → WAF → Rate limiting rules → Create rule:**

- **Name:** `app-throttle`
- **If incoming requests match:** `(http.host eq "substackgraph.com")`
- **When rate exceeds:** `60` requests per `1 minute` (per client IP — the default characteristic)
- **Then:** *Block* for `60` seconds (use *Managed Challenge* instead if you expect shared-IP users)

Tighten a second rule for any future write/crawl endpoint, e.g. match
`(http.request.uri.path contains "/api/" and http.request.method eq "POST")` at `10/min`.

### 2. Managed WAF rules

**Security → WAF → Managed rules:** enable the **Cloudflare Managed Ruleset** (and the free
**OWASP Core Ruleset** if available on your plan). Action: *Managed Challenge*.

### 3. Baseline hardening

- **SSL/TLS → Overview:** mode **Full (strict)** (pairs with the `fly certs` cert).
- **SSL/TLS → Edge Certificates:** **Always Use HTTPS** on, **Min TLS 1.2**, **HSTS** on
  (the app also sends `Strict-Transport-Security`).
- **Security → Settings:** **Bot Fight Mode** on (free tier).
- **Network:** leave the orange cloud (proxy) **on** so Fly's origin IP is never exposed.

These are free-tier features. Result: edge TLS, DDoS protection, bot mitigation, and per-IP rate
limiting in front of a non-root container that only serves cached data — defense in depth.

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
