"""The live web app for substackgraph.com.

Dynamic, not static: every request reads the SQLite cache and runs the identity-resolution
harness on the fly (resolution is deterministic and cheap), then renders the force-directed
map. The before/after is a live toggle, and the decision log is exposed as an API — the
observability surface is the product.

Crawling is the one expensive, ToS-sensitive step. It is OFF by default in production: the
public site serves whatever neighborhoods are already cached. Set ALLOW_LIVE_CRAWL=1 to allow
on-demand crawls (rate-limited, background) for trusted deployments.
"""

from __future__ import annotations

import os
import threading

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from . import config
from .auditlog import AuditLog
from .cache import Cache
from .client import SubstackClient, normalize_url
from .crawl import crawl, load_raw_graph
from .naive_graph import build_naive
from .ratelimit import RateLimiter
from .render import graph_to_html
from .resolve import resolve

ALLOW_LIVE_CRAWL = os.getenv("ALLOW_LIVE_CRAWL", "0") == "1"
DEFAULT_SEED = normalize_url(os.getenv("SUBSTACKGRAPH_SEED", "https://theairuntime.substack.com"))

app = FastAPI(title="substackgraph", description="Map and resolve the Substack recommendation network.")


@app.middleware("http")
async def security_headers(request, call_next):
    """Baseline hardening for a public site. HSTS assumes TLS is terminated upstream
    (Cloudflare). Frames are same-origin only — the landing page embeds /graph itself."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

# Guards on-demand crawls so a flood of seeds can't spawn unbounded threads.
_crawl_lock = threading.Lock()
_crawling: set[str] = set()


def _open_cache() -> Cache:
    config.ensure_dirs()
    return Cache(config.DB_PATH)


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; font:16px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; background:#0c0d10; color:#e6e6e6; }}
  header {{ padding:20px 28px; border-bottom:1px solid #23252b; }}
  header h1 {{ margin:0; font-size:20px; letter-spacing:.2px; }}
  header p {{ margin:6px 0 0; color:#9aa0ab; font-size:14px; }}
  nav {{ padding:12px 28px; display:flex; gap:14px; flex-wrap:wrap; border-bottom:1px solid #23252b; }}
  nav a {{ color:#7db1ff; text-decoration:none; font-size:14px; }}
  nav a:hover {{ text-decoration:underline; }}
  main {{ padding:24px 28px; }}
  iframe {{ width:100%; height:780px; border:1px solid #23252b; border-radius:8px; background:#111; }}
  .pill {{ display:inline-block; padding:2px 8px; border:1px solid #2c2f37; border-radius:999px; font-size:12px; color:#9aa0ab; }}
  code {{ background:#15171c; padding:1px 5px; border-radius:4px; }}
</style></head>
<body>
<header>
  <h1>substackgraph <span class="pill">Episode 1 · The Grounding Break</span></h1>
  <p>Crawl the Substack recommendation network, resolve publications to canonical entities, and see the difference.</p>
</header>
<nav>
  <a href="/">Home</a>
  <a href="/graph?mode=resolved">Resolved map</a>
  <a href="/graph?mode=naive">Naive (corrupted) map</a>
  <a href="/api/decisions">Decision log (JSON)</a>
  <a href="/api/graph">Graph data (JSON)</a>
</nav>
<main>{body}</main>
</body></html>"""


@app.get("/healthz")
def healthz():
    return {"status": "ok", "live_crawl": ALLOW_LIVE_CRAWL, "default_seed": DEFAULT_SEED}


@app.get("/", response_class=HTMLResponse)
def index():
    cache = _open_cache()
    try:
        nodes, edges = load_raw_graph(cache)
    finally:
        cache.close()

    if not nodes:
        body = (
            "<p>No neighborhood is cached yet. Populate one with the CLI:</p>"
            "<p><code>substackgraph crawl --seed https://theairuntime.substack.com</code></p>"
            "<p>or load the bundled demo neighborhood: <code>substackgraph load-demo</code></p>"
        )
        return HTMLResponse(_page("substackgraph", body))

    audit = AuditLog()
    result = resolve(nodes, edges, audit=audit)
    actions: dict[str, int] = {}
    for rec in audit.records:
        actions[rec["action"]] = actions.get(rec["action"], 0) + 1
    summary = ", ".join(f"{k}: {v}" for k, v in sorted(actions.items())) or "none"
    body = (
        f"<p><span class='pill'>{len(result.nodes)} canonical publications</span> "
        f"<span class='pill'>{len(result.edges)} edges</span> "
        f"<span class='pill'>decisions — {summary}</span></p>"
        "<iframe src='/graph?mode=resolved' title='Resolved recommendation map'></iframe>"
        "<p style='color:#9aa0ab;font-size:14px'>Toggle to the "
        "<a href='/graph?mode=naive'>naive map</a> to see the same data before resolution.</p>"
    )
    return HTMLResponse(_page("substackgraph", body))


@app.get("/graph", response_class=HTMLResponse)
def graph(mode: str = Query("resolved", pattern="^(resolved|naive)$")):
    cache = _open_cache()
    try:
        nodes, edges = load_raw_graph(cache)
    finally:
        cache.close()

    if not nodes:
        return HTMLResponse("<p>No data cached yet. Run a crawl first.</p>", status_code=404)

    if mode == "naive":
        g, _ = build_naive(nodes, edges)
        return HTMLResponse(graph_to_html(g, "substackgraph — naive (corrupted)"))
    result = resolve(nodes, edges, audit=AuditLog())
    return HTMLResponse(graph_to_html(result.graph, "substackgraph — resolved"))


@app.get("/api/graph")
def api_graph():
    cache = _open_cache()
    try:
        nodes, edges = load_raw_graph(cache)
    finally:
        cache.close()
    result = resolve(nodes, edges, audit=AuditLog())
    return JSONResponse(
        {
            "nodes": [
                {
                    "id": n.canonical_id,
                    "name": n.display_name,
                    "surfaces": n.member_urls,
                    "author_ids": n.author_ids,
                }
                for n in result.nodes
            ],
            "edges": [{"src": s, "dst": d} for s, d in result.edges],
        }
    )


@app.get("/api/decisions")
def api_decisions():
    cache = _open_cache()
    try:
        nodes, edges = load_raw_graph(cache)
    finally:
        cache.close()
    audit = AuditLog()
    resolve(nodes, edges, audit=audit)
    return JSONResponse({"count": len(audit.records), "decisions": audit.records})


def _run_crawl(seed: str) -> None:
    try:
        cache = _open_cache()
        try:
            crawl(seed, 2, cache, RateLimiter(), SubstackClient())
        finally:
            cache.close()
    finally:
        with _crawl_lock:
            _crawling.discard(seed)


@app.post("/crawl")
def trigger_crawl(seed: str = Query(...)):
    if not ALLOW_LIVE_CRAWL:
        return JSONResponse(
            {"error": "live crawling is disabled (set ALLOW_LIVE_CRAWL=1 to enable)"}, status_code=403
        )
    nseed = normalize_url(seed)
    with _crawl_lock:
        if nseed in _crawling:
            return JSONResponse({"status": "already_crawling", "seed": nseed}, status_code=202)
        _crawling.add(nseed)
    threading.Thread(target=_run_crawl, args=(nseed,), daemon=True).start()
    return JSONResponse({"status": "crawling", "seed": nseed}, status_code=202)


@app.get("/api/status")
def api_status():
    """Debug endpoint: DB row counts and last crawl log lines."""
    import sqlite3
    from pathlib import Path

    db = str(config.DB_PATH)
    rows: dict = {}
    try:
        conn = sqlite3.connect(db)
        total = conn.execute("SELECT COUNT(*) FROM http_cache").fetchone()[0]
        by_status = dict(conn.execute(
            "SELECT status, COUNT(*) FROM http_cache GROUP BY status"
        ).fetchall())
        marker = conn.execute(
            "SELECT payload_json FROM http_cache WHERE cache_key LIKE '_crawl_marker:%'"
        ).fetchone()
        conn.close()
        rows = {"total": total, "by_status": by_status, "crawl_marker": marker[0] if marker else None}
    except Exception as e:
        rows = {"error": str(e)}

    log_tail: list[str] = []
    log_path = Path("/tmp/crawl.log")
    if log_path.exists():
        lines = log_path.read_text().splitlines()
        log_tail = lines[-30:]

    return JSONResponse({
        "db_path": db,
        "db": rows,
        "crawl_log_tail": log_tail,
        "allow_live_crawl": ALLOW_LIVE_CRAWL,
        "seed_url": DEFAULT_SEED,
    })


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    # Research/visualization site; keep crawler endpoints out of search indexes.
    return "User-agent: *\nDisallow: /crawl\n"
