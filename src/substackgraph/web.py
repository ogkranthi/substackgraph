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

import logging
import os
import re
import threading
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from . import config
from .auditlog import AuditLog
from .cache import Cache
from .client import SubstackClient, normalize_url
from .crawl import crawl, load_raw_graph
from .naive_graph import build_naive
from .ratelimit import RateLimiter
from .render import graph_to_html  # noqa: F401 — kept for CLI render commands
from .resolve import resolve

ALLOW_LIVE_CRAWL = os.getenv("ALLOW_LIVE_CRAWL", "0") == "1"
BYPASS_GATE = os.getenv("BYPASS_GATE", "0") == "1"
DEFAULT_SEED = normalize_url(os.getenv("SUBSTACKGRAPH_SEED", "https://theairuntime.substack.com"))

logger = logging.getLogger("substackgraph.web")

app = FastAPI(title="substackgraph", description="Map and resolve the Substack recommendation network.")


# ---------------------------------------------------------------------------
# Subscriber gate — rate limiter (in-memory, per IP, 10 req/min)
# ---------------------------------------------------------------------------

_gate_hits: dict[str, list[float]] = {}
_gate_lock = threading.Lock()
_GATE_WINDOW = 60.0
_GATE_MAX = 10


def _gate_rate_ok(ip: str) -> bool:
    now = time.monotonic()
    with _gate_lock:
        times = _gate_hits.setdefault(ip, [])
        times[:] = [t for t in times if now - t < _GATE_WINDOW]
        if len(times) >= _GATE_MAX:
            return False
        times.append(now)
        return True


class _VerifyRequest(BaseModel):
    email: str


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.on_event("startup")
def _log_gate_status():
    if BYPASS_GATE:
        logger.info("Subscriber gate BYPASSED (BYPASS_GATE=1)")
    else:
        logger.info("Subscriber gate ENABLED — users must verify email")


@app.post("/api/verify-subscriber")
async def verify_subscriber(body: _VerifyRequest, request: Request):
    if BYPASS_GATE:
        return JSONResponse({"subscribed": True, "email": body.email, "method": "bypass"})

    ip = request.client.host if request.client else "unknown"
    if not _gate_rate_ok(ip):
        return JSONResponse({"error": "rate limit exceeded — try again in a minute"}, status_code=429)

    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        return JSONResponse({"error": "invalid email format"}, status_code=422)

    # TODO: Real subscriber verification needs Substack Pro API or a custom
    # subscribers CSV export. The public Substack API does not expose a
    # subscriber-check endpoint. For now, accept any valid-format email as a
    # fallback so the gate UX is testable end-to-end.
    return JSONResponse({"subscribed": True, "email": email, "method": "email_format_fallback"})


@app.middleware("http")
async def security_headers(request, call_next):
    """Baseline hardening for a public site. HSTS assumes TLS is terminated upstream."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


_crawl_lock = threading.Lock()
_crawling: set[str] = set()


def _open_cache() -> Cache:
    config.ensure_dirs()
    return Cache(config.DB_PATH)


def _handle_from_url(url: str) -> str:
    """Derive a human handle from a publication URL when no display name exists.

    The current dataset has null names everywhere, so the only legible label is the
    URL's leading host label: https://aiblewmymind.substack.com -> "aiblewmymind",
    https://www.creatoreconomy.so -> "creatoreconomy".
    """
    host = urlsplit(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return url
    return host.split(".")[0]


def _label_for(display_name, member_urls) -> str:
    if display_name:
        return str(display_name)
    if member_urls:
        return _handle_from_url(member_urls[0])
    return "(unknown)"


def _graph_metrics(graph):
    """Per-node influence (PageRank) and community id (greedy modularity).

    Both are cheap on a graph of this size and deterministic enough for a static
    snapshot. Community detection treats the recommendation graph as undirected
    (a recommendation in either direction means the two pubs share an audience),
    which is the right lens for "which niche cluster is this."
    """
    import networkx as nx

    clusters: dict = {}
    ranks: dict = {}
    n = graph.number_of_nodes()
    if n == 0:
        return clusters, ranks

    if graph.number_of_edges():
        try:
            ranks = nx.pagerank(graph, max_iter=200)
        except Exception:  # noqa: BLE001 — power iteration can fail to converge
            ranks = {node: 1.0 / n for node in graph.nodes()}
        try:
            from networkx.algorithms.community import greedy_modularity_communities
            communities = greedy_modularity_communities(graph.to_undirected())
            for i, com in enumerate(communities):
                for node in com:
                    clusters[node] = i
        except Exception:  # noqa: BLE001
            for i, com in enumerate(nx.weakly_connected_components(graph)):
                for node in com:
                    clusters[node] = i
    else:
        ranks = {node: 1.0 / n for node in graph.nodes()}
        clusters = {node: i for i, node in enumerate(graph.nodes())}

    # Ensure every node has a cluster id (isolated nodes dropped by modularity).
    for i, node in enumerate(graph.nodes()):
        clusters.setdefault(node, -1)
        ranks.setdefault(node, 0.0)
    return clusters, ranks


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz():
    return {"status": "ok", "live_crawl": ALLOW_LIVE_CRAWL, "bypass_gate": BYPASS_GATE, "default_seed": DEFAULT_SEED}


@app.get("/", response_class=HTMLResponse)
def index():
    page = _MAIN_PAGE.replace("__BYPASS_GATE__", "1" if BYPASS_GATE else "0")
    return HTMLResponse(page)


@app.get("/api/graph")
def api_graph(mode: str = Query("resolved", pattern="^(resolved|naive)$")):
    cache = _open_cache()
    try:
        nodes, edges = load_raw_graph(cache)
    finally:
        cache.close()

    if mode == "naive":
        g, stats = build_naive(nodes, edges)
        clusters, ranks = _graph_metrics(g)
        vn_nodes = []
        for node_id, data in g.nodes(data=True):
            members = data.get("member_urls", [])
            ids_seen = data.get("ids_seen", [])
            vn_nodes.append({
                "id": node_id,
                "label": _label_for(data.get("label"), members) if not members else _label_for(None, members),
                "value": max(1, g.in_degree(node_id)),
                "out": g.out_degree(node_id),
                "surfaces": len(members) or 1,
                "domains": members,
                "ids_seen": ids_seen,
                "cluster": clusters.get(node_id, -1),
                "rank": round(ranks.get(node_id, 0.0), 6),
                "group": "conflict" if len(ids_seen) > 1 else "naive",
            })
        vn_edges = [{"from": s, "to": d} for s, d in g.edges()]
        return JSONResponse({
            "nodes": vn_nodes,
            "edges": vn_edges,
            "meta": {
                "mode": "naive",
                "node_count": stats.node_count,
                "edge_count": stats.edge_count,
                "cluster_count": len({c for c in clusters.values() if c >= 0}),
                "dropped_edges": stats.dropped_edges,
                "self_loops": stats.self_loops,
            },
        })

    # resolved
    audit = AuditLog()
    result = resolve(nodes, edges, audit=audit)
    clusters, ranks = _graph_metrics(result.graph)
    vn_nodes = []
    for node in result.nodes:
        in_deg = result.graph.in_degree(node.canonical_id)
        out_deg = result.graph.out_degree(node.canonical_id)
        surfaces = len(node.member_urls)
        vn_nodes.append({
            "id": node.canonical_id,
            "label": _label_for(node.display_name, node.member_urls),
            "value": max(1, in_deg),
            "out": out_deg,
            "surfaces": surfaces,
            "domains": node.member_urls,
            "author_ids": node.author_ids,
            "subdomain": node.subdomain,
            "custom_domain": node.custom_domain,
            "cluster": clusters.get(node.canonical_id, -1),
            "rank": round(ranks.get(node.canonical_id, 0.0), 6),
            "group": "merged" if surfaces > 1 else ("hub" if in_deg >= 3 else "single"),
        })
    vn_edges = [{"from": s, "to": d} for s, d in result.edges]
    actions: dict[str, int] = {}
    for rec in audit.records:
        actions[rec["action"]] = actions.get(rec["action"], 0) + 1
    return JSONResponse({
        "nodes": vn_nodes,
        "edges": vn_edges,
        "meta": {
            "mode": "resolved",
            "node_count": len(result.nodes),
            "edge_count": len(result.edges),
            "cluster_count": len({c for c in clusters.values() if c >= 0}),
            "decisions": actions,
        },
    })


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
    return "User-agent: *\nDisallow: /crawl\n"


# ---------------------------------------------------------------------------
# Full-page SPA — vis-network force-directed graph + writer-centric views
# ---------------------------------------------------------------------------


_MAIN_PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>substackgraph — by The AI Runtime</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/vis-network@9/standalone/umd/vis-network.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
:root{
  --bg:#0a0a0a; --surface:#111111; --surface2:#1a1a1a; --surface3:#222222;
  --border:#2a2a2a; --border2:#333333;
  --text:#f0f0f0; --text2:#a0a0a0; --text3:#555555;
  --indigo:#ff6b35; --indigo2:#ff9a6c; --rose:#ef4444; --cyan:#22d3ee;
  --amber:#f59e0b; --blue:#3b82f6; --green:#22c55e;
  --header-h:56px;
  --mono:"JetBrains Mono",monospace;
}
html,body{height:100%;font-family:"Inter",-apple-system,"Segoe UI",Roboto,sans-serif;
  font-size:14px;background:var(--bg);color:var(--text);overflow:hidden;}

/* header */
#header{position:fixed;top:0;left:0;right:0;z-index:100;height:var(--header-h);
  background:rgba(10,10,10,.94);backdrop-filter:blur(16px);border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:12px;padding:0 16px;}
.logo{display:flex;align-items:center;gap:8px;font-size:15px;font-weight:600;letter-spacing:-.2px;
  color:var(--text);text-decoration:none;white-space:nowrap;flex-shrink:0;}
.logo-badge{font-size:11px;font-weight:400;color:var(--text3);background:var(--surface2);
  border:1px solid var(--border2);padding:2px 7px;border-radius:999px;}
.hbtn{display:inline-flex;align-items:center;gap:6px;padding:6px 11px;border-radius:8px;
  border:1px solid var(--border2);background:var(--surface2);color:var(--text2);
  font:500 13px "Inter",sans-serif;cursor:pointer;transition:all .15s;white-space:nowrap;}
.hbtn:hover{color:var(--text);border-color:var(--indigo);}
.hbtn.on{background:var(--indigo);color:#fff;border-color:var(--indigo);}

.toggle-wrap{display:flex;align-items:center;background:var(--bg);border:1px solid var(--border2);
  border-radius:9px;padding:3px;gap:2px;}
.toggle-btn{padding:5px 14px;border:none;border-radius:7px;font:500 13px "Inter",sans-serif;
  cursor:pointer;transition:all .18s;background:transparent;color:var(--text2);white-space:nowrap;}
.toggle-btn:hover:not(.active-resolved):not(.active-naive){background:var(--surface2);color:var(--text);}
.toggle-btn.active-resolved{background:var(--indigo);color:#fff;}
.toggle-btn.active-naive{background:var(--rose);color:#fff;}

#hstats{display:flex;align-items:center;gap:7px;margin-left:auto;flex-shrink:0;}
.hchip{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border:1px solid var(--border2);
  border-radius:999px;font-size:12px;color:var(--text2);background:var(--surface2);white-space:nowrap;}
.hchip b{color:var(--text);font-weight:600;}
.hchip .dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;}
.hc-nodes .dot{background:var(--indigo);} .hc-edges .dot{background:var(--cyan);}
.hc-avg .dot{background:var(--green);} .hc-top .dot{background:var(--amber);}

#stripe{position:fixed;top:var(--header-h);left:0;right:0;height:2px;z-index:99;
  background:var(--indigo);transition:background .3s;}

#gwrap{position:fixed;top:var(--header-h);left:0;right:0;bottom:0;}
#gc{width:100%;height:100%;background:var(--bg);}

/* loading + empty */
#loading{position:fixed;inset:0;z-index:200;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:16px;background:var(--bg);transition:opacity .4s;}
#loading.gone{opacity:0;pointer-events:none;}
.spinner{width:36px;height:36px;border:3px solid var(--border2);border-top-color:var(--indigo);
  border-radius:50%;animation:spin .75s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}
#loading p{color:var(--text2);font-size:13px;}
#empty{position:fixed;inset:var(--header-h) 0 0 0;z-index:50;display:none;flex-direction:column;
  align-items:center;justify-content:center;gap:13px;}
#empty.show{display:flex;}
#empty h2{font-size:20px;font-weight:600;}
#empty p{color:var(--text2);font-size:13px;max-width:440px;text-align:center;line-height:1.65;}
#empty code{background:var(--surface2);border:1px solid var(--border2);border-radius:8px;padding:10px 18px;
  font-family:var(--mono);font-size:12px;color:var(--cyan);display:block;}

/* search */
#swrap{position:fixed;top:calc(var(--header-h) + 12px);left:50%;transform:translateX(-50%);
  z-index:30;width:min(320px,86vw);}
#search{width:100%;background:rgba(10,10,10,.9);backdrop-filter:blur(10px);border:1px solid var(--border2);
  border-radius:9px;color:var(--text);font:13px "Inter",sans-serif;padding:9px 12px 9px 34px;outline:none;transition:border-color .18s;}
#search:focus{border-color:var(--indigo);}
#search::placeholder{color:var(--text3);}
.sicon{position:absolute;left:11px;top:50%;transform:translateY(-50%);color:var(--text3);pointer-events:none;}

/* color-mode + cluster legend (bottom-left) */
#controls{position:fixed;bottom:18px;left:18px;z-index:30;display:flex;flex-direction:column;gap:10px;align-items:flex-start;}
.ctl{background:rgba(10,10,10,.88);backdrop-filter:blur(10px);border:1px solid var(--border2);
  border-radius:10px;padding:10px 12px;}
.ctl .ct{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--text3);margin-bottom:7px;}
.seg{display:flex;background:var(--bg);border:1px solid var(--border2);border-radius:8px;padding:2px;gap:2px;}
.seg button{padding:4px 10px;border:none;border-radius:6px;background:transparent;color:var(--text2);
  font:500 12px "Inter",sans-serif;cursor:pointer;transition:all .15s;}
.seg button.on{background:var(--indigo);color:#fff;}
.leg{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text2);}
.ldot{width:10px;height:10px;border-radius:50%;flex-shrink:0;}
#legend-body{display:flex;flex-direction:column;gap:6px;}
.cl-row{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--text2);cursor:pointer;padding:1px 0;}
.cl-row:hover{color:var(--text);}
.cl-row.dim{opacity:.4;}
#legend-hint{font-size:11px;color:var(--text3);margin-top:3px;border-top:1px solid var(--border);
  padding-top:7px;line-height:1.6;}
kbd{background:var(--surface3);border:1px solid var(--border2);border-radius:4px;padding:0 4px;font-size:10px;font-family:inherit;}

/* mode note */
#modenote{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);z-index:30;
  background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);color:#fda4af;
  padding:7px 14px;border-radius:999px;font-size:12px;display:none;align-items:center;gap:7px;}
#modenote.show{display:flex;}

/* decision chips */
#decbar{position:fixed;bottom:18px;right:18px;z-index:30;display:flex;flex-direction:column;align-items:flex-end;gap:5px;}
.dc{display:flex;align-items:center;gap:6px;padding:4px 11px;background:rgba(10,10,10,.88);
  backdrop-filter:blur(10px);border:1px solid var(--border2);border-radius:999px;font-size:12px;color:var(--text2);}
.dc .dd{width:6px;height:6px;border-radius:50%;}
.dc-merge .dd{background:var(--green);} .dc-refuse .dd{background:var(--rose);}
.dc-alias .dd{background:var(--cyan);} .dc-drop .dd{background:var(--text3);}

/* generic side panel */
.side{position:fixed;top:var(--header-h);bottom:0;z-index:40;background:var(--surface2);
  overflow-y:auto;display:flex;flex-direction:column;transition:transform .22s cubic-bezier(.4,0,.2,1);}
.side::-webkit-scrollbar{width:4px;} .side::-webkit-scrollbar-thumb{background:var(--border2);border-radius:2px;}

/* left panel (board + decisions, tabbed) */
#board{left:0;width:320px;border-right:1px solid var(--border);transform:translateX(-100%);}
#board.open{transform:translateX(0);}
.tabs{display:flex;border-bottom:1px solid var(--border);flex-shrink:0;}
.tab{flex:1;padding:12px 8px;text-align:center;font:500 13px "Inter",sans-serif;cursor:pointer;
  color:var(--text2);background:transparent;border:none;border-bottom:2px solid transparent;transition:all .15s;}
.tab:hover{color:var(--text);}
.tab.on{color:var(--text);border-bottom-color:var(--indigo);}
.board-tools{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid var(--border);flex-shrink:0;}
.board-tools .sub{font-size:11px;color:var(--text3);}
.brow{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border);cursor:pointer;transition:background .12s;}
.brow:hover{background:var(--surface3);}
.brk{width:22px;text-align:center;font-size:12px;font-weight:600;color:var(--text3);flex-shrink:0;}
.brk.top{color:var(--amber);}
.brn{flex:1;min-width:0;}
.brn .h{font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.brn .m{font-size:11px;color:var(--text3);margin-top:1px;}
.cluster-pip{width:8px;height:8px;border-radius:50%;flex-shrink:0;}
.brbar{width:38px;height:5px;background:var(--border);border-radius:3px;overflow:hidden;flex-shrink:0;}
.brbar i{display:block;height:100%;background:var(--indigo);}
/* decision cards */
.dfilter{display:flex;flex-wrap:wrap;gap:5px;padding:10px 14px;border-bottom:1px solid var(--border);flex-shrink:0;}
.dfilter .fc{padding:3px 9px;border:1px solid var(--border2);border-radius:999px;font-size:11px;color:var(--text2);cursor:pointer;transition:all .12s;}
.dfilter .fc.on{background:var(--indigo);color:#fff;border-color:var(--indigo);}
.dcard{padding:10px 14px;border-bottom:1px solid var(--border);font-size:12px;}
.dcard .dh{display:flex;align-items:center;gap:7px;margin-bottom:5px;}
.dcard .da{font-weight:600;text-transform:uppercase;font-size:10px;letter-spacing:.05em;padding:2px 7px;border-radius:999px;}
.da-merge{background:rgba(34,197,94,.15);color:#34d399;} .da-refuse{background:rgba(239,68,68,.15);color:#fb7185;}
.da-alias{background:rgba(34,211,238,.15);color:#67e8f9;} .da-drop_404{background:rgba(74,85,104,.2);color:#94a3b8;}
.da-drop_self_loop{background:rgba(74,85,104,.2);color:#94a3b8;}
.dcard .dm{color:var(--text2);line-height:1.5;word-break:break-all;}
.dcard .ev{margin-top:5px;color:var(--text3);font-size:11px;}
.dcard .sc{margin-left:auto;color:var(--text3);font-size:11px;}

/* detail drawer (right) */
#panel{right:0;width:340px;border-left:1px solid var(--border);transform:translateX(100%);}
#panel.open{transform:translateX(0);}
.ph{padding:15px 16px 12px;border-bottom:1px solid var(--border);display:flex;align-items:flex-start;gap:11px;flex-shrink:0;}
.ph-icon{width:38px;height:38px;border-radius:9px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:18px;}
.ph-text{flex:1;min-width:0;}
.ph-title{font-size:15px;font-weight:600;line-height:1.3;word-break:break-all;}
.ph-sub{font-size:12px;color:var(--text2);margin-top:3px;word-break:break-all;}
.ph-close{background:none;border:none;cursor:pointer;color:var(--text3);font-size:18px;padding:2px 5px;border-radius:5px;transition:color .15s;flex-shrink:0;}
.ph-close:hover{color:var(--text);}
.pb{padding:14px 16px;flex:1;display:flex;flex-direction:column;gap:15px;}
.ps h3{font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--text3);margin-bottom:8px;display:flex;align-items:center;gap:6px;}
.ps h3 .cnt{color:var(--text2);background:var(--surface3);border-radius:999px;padding:0 6px;font-size:10px;}
.srow{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid var(--border);font-size:13px;}
.srow:last-child{border-bottom:none;} .srow .sl{color:var(--text2);} .srow .sv{font-weight:500;}
.metrics{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
.mc{background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:10px 12px;}
.mc .v{font-size:20px;font-weight:700;line-height:1;}
.mc .l{font-size:11px;color:var(--text2);margin-top:4px;}
.dlist{display:flex;flex-direction:column;gap:4px;}
.ditem{display:flex;align-items:center;gap:7px;padding:7px 9px;background:var(--surface);border:1px solid var(--border);
  border-radius:7px;font-size:12px;color:var(--text2);word-break:break-all;text-decoration:none;cursor:pointer;transition:border-color .15s,color .15s;}
.ditem:hover{border-color:var(--indigo);color:var(--text);}
.ditem svg{flex-shrink:0;color:var(--text3);}
.ditem .grow{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.opp{background:linear-gradient(180deg,rgba(255,107,53,.08),rgba(255,107,53,0));border:1px solid rgba(255,107,53,.25);border-radius:9px;padding:11px 12px;}
.opp .ot{font-size:12px;font-weight:600;color:var(--indigo2);margin-bottom:6px;}
.opp .od{font-size:11px;color:var(--text2);line-height:1.55;margin-bottom:8px;}
.tag{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;margin:0 4px 4px 0;background:var(--surface3);
  border:1px solid var(--border2);border-radius:999px;font-size:11px;color:var(--text2);cursor:pointer;transition:all .12s;}
.tag:hover{border-color:var(--indigo);color:var(--text);}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:500;margin-right:4px;}
.b-merged{background:rgba(245,158,11,.14);color:var(--amber);border:1px solid rgba(245,158,11,.28);}
.b-hub{background:rgba(255,107,53,.14);color:var(--indigo2);border:1px solid rgba(255,107,53,.28);}
.b-conflict{background:rgba(239,68,68,.14);color:var(--rose);border:1px solid rgba(239,68,68,.28);}
/* path finder */
.pf{background:var(--surface);border:1px solid var(--border2);border-radius:9px;padding:11px 12px;}
.pf .pt{font-size:12px;font-weight:600;color:var(--cyan);margin-bottom:7px;}
.pf input{width:100%;background:var(--bg);border:1px solid var(--border2);border-radius:7px;color:var(--text);
  font:13px "Inter",sans-serif;padding:7px 10px;outline:none;}
.pf input:focus{border-color:var(--cyan);}
.pf .presult{margin-top:8px;font-size:12px;color:var(--text2);line-height:1.6;}
.pf .chain{display:flex;flex-wrap:wrap;align-items:center;gap:4px;margin-top:6px;}
.pf .hop{padding:3px 8px;background:var(--surface3);border:1px solid var(--border2);border-radius:6px;font-size:11px;cursor:pointer;}
.pf .hop:hover{border-color:var(--cyan);color:var(--text);}
.pf .arr{color:var(--text3);}
.pact{display:flex;gap:8px;}
.pact button{flex:1;padding:8px;border-radius:8px;border:1px solid var(--border2);background:var(--surface);
  color:var(--text2);font:500 12px "Inter",sans-serif;cursor:pointer;transition:all .15s;}
.pact button:hover{border-color:var(--indigo);color:var(--text);}

/* subscriber gate */
#gate{position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.92);backdrop-filter:blur(20px);
  display:flex;align-items:center;justify-content:center;transition:opacity .4s;}
#gate.gone{opacity:0;pointer-events:none;}
.gate-box{max-width:420px;width:90%;background:#111111;border:1px solid #333333;border-radius:16px;padding:40px 32px;text-align:center;}
.gate-box .g-spark{font-size:36px;color:#ff6b35;margin-bottom:12px;}
.gate-box h2{font-size:22px;font-weight:700;color:#f0f0f0;margin-bottom:8px;}
.gate-box .g-sub{font-size:13px;color:#a0a0a0;line-height:1.6;margin-bottom:24px;}
.gate-box input{width:100%;background:#0a0a0a;border:1px solid #333333;border-radius:9px;color:#f0f0f0;
  font:14px "Inter",sans-serif;padding:12px 14px;outline:none;margin-bottom:12px;transition:border-color .18s;}
.gate-box input:focus{border-color:#ff6b35;}
.gate-box input::placeholder{color:#555555;}
.g-btn{width:100%;padding:12px;border:none;border-radius:9px;background:#ff6b35;color:#fff;
  font:600 14px "Inter",sans-serif;cursor:pointer;transition:background .15s;}
.g-btn:hover{background:#e55a2b;}
.g-btn:disabled{opacity:.5;cursor:not-allowed;}
.g-error{margin-top:14px;font-size:13px;color:#ef4444;display:none;}
.g-cta{display:none;margin-top:18px;text-align:center;}
.g-cta a{display:inline-block;padding:10px 20px;background:#ff6b35;color:#fff;border-radius:9px;
  font:600 13px "Inter",sans-serif;text-decoration:none;transition:background .15s;}
.g-cta a:hover{background:#e55a2b;}
.g-hint{margin-top:12px;font-size:11px;color:#555555;}

@media (max-width:680px){
  #hstats .hc-avg,#hstats .hc-top{display:none;}
  .logo-badge{display:none;}
  #panel,#board{width:100%;}
  #controls{display:none;}
}
</style>
</head>
<body>

<div id="gate">
  <div class="gate-box">
    <div class="g-spark">&#10022;</div>
    <h2>substackgraph is a subscriber-only tool</h2>
    <p class="g-sub">Built for readers of The AI Runtime &mdash; the newsletter for production AI engineers.</p>
    <input id="gate-email" type="email" placeholder="you@example.com" autocomplete="email">
    <button class="g-btn" id="gate-btn" onclick="verifyGate()">Verify Access</button>
    <div class="g-error" id="gate-error"></div>
    <div class="g-cta" id="gate-cta">
      <p style="font-size:13px;color:#a0a0a0;margin-bottom:10px">Not a subscriber yet?</p>
      <a href="https://theairuntime.substack.com" target="_blank" rel="noopener">Subscribe to The AI Runtime</a>
    </div>
    <p class="g-hint">Already subscribed? Enter your email above.</p>
  </div>
</div>

<header id="header">
  <a href="/" class="logo">
    <span style="color:#ff6b35;font-size:18px;line-height:1">&#10022;</span>
    substackgraph
  </a>
  <span style="font-size:11px;color:var(--text3);white-space:nowrap;flex-shrink:0">Substack recommendation graph &middot; by <a href="https://theairuntime.substack.com" target="_blank" rel="noopener" style="color:var(--indigo);text-decoration:none">The AI Runtime</a></span>

  <button class="hbtn" id="btn-board" onclick="openLeft('board')">&#9776; Leaderboard</button>
  <button class="hbtn" id="btn-dec" onclick="openLeft('dec')">&#9783; Decisions</button>

  <div class="toggle-wrap">
    <button class="toggle-btn active-resolved" id="btn-resolved" onclick="setMode('resolved')">&#10022; Resolved</button>
    <button class="toggle-btn" id="btn-naive" onclick="setMode('naive')">&#9888; Naive</button>
  </div>

  <div id="hstats">
    <div class="hchip hc-nodes" id="sc-nodes"><span class="dot"></span><b>&mdash;</b>&nbsp;pubs</div>
    <div class="hchip hc-edges" id="sc-edges"><span class="dot"></span><b>&mdash;</b>&nbsp;recs</div>
    <div class="hchip hc-avg" id="sc-avg"><span class="dot"></span><b>&mdash;</b>&nbsp;avg</div>
    <div class="hchip hc-top" id="sc-top"><span class="dot"></span><b>&mdash;</b></div>
  </div>
</header>

<div id="stripe"></div>
<div id="gwrap"><div id="gc"></div></div>

<div id="loading"><div class="spinner"></div><p id="loading-msg">Loading recommendation network&hellip;</p></div>

<div id="empty">
  <svg width="50" height="50" viewBox="0 0 52 52" fill="none" style="color:#555555">
    <circle cx="26" cy="26" r="24" stroke="currentColor" stroke-width="2"/>
    <path d="M18 26h16M26 18v16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
  </svg>
  <h2>No data yet</h2>
  <p>The cache is empty. Run a crawl with the CLI, then redeploy.</p>
  <code>substackgraph crawl --seed https://theairuntime.substack.com</code>
</div>

<div id="swrap">
  <svg class="sicon" width="14" height="14" viewBox="0 0 14 14" fill="none">
    <circle cx="6" cy="6" r="4.5" stroke="currentColor" stroke-width="1.5"/>
    <line x1="9.5" y1="9.5" x2="13" y2="13" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
  </svg>
  <input id="search" placeholder="Find a publication&hellip;" oninput="onSearch(this.value)" autocomplete="off" list="handles">
  <datalist id="handles"></datalist>
</div>

<div id="controls">
  <div class="ctl">
    <div class="ct">Color by</div>
    <div class="seg">
      <button id="cm-degree" class="on" onclick="setColorMode('degree')">Role</button>
      <button id="cm-cluster" onclick="setColorMode('cluster')">Cluster</button>
    </div>
    <div id="legend-body" style="margin-top:9px"></div>
    <div id="legend-hint"><kbd>/</kbd> search &nbsp; <kbd>r</kbd> fit &nbsp; <kbd>esc</kbd> close<br><kbd>1</kbd> resolved &nbsp; <kbd>2</kbd> naive &nbsp; <kbd>b</kbd> board &nbsp; <kbd>d</kbd> decisions</div>
  </div>
</div>

<div id="modenote"></div>
<div id="decbar"></div>

<!-- left panel: tabbed board + decisions -->
<div class="side" id="board">
  <div class="tabs">
    <button class="tab on" id="tab-board" onclick="switchTab('board')">Top publications</button>
    <button class="tab" id="tab-dec" onclick="switchTab('dec')">Decision log</button>
    <button class="ph-close" style="padding:0 12px" onclick="openLeft(null)">&#10005;</button>
  </div>
  <div id="view-board">
    <div class="board-tools">
      <div class="seg"><button id="bs-in" class="on" onclick="setBoardSort('in')">Inbound</button><button id="bs-inf" onclick="setBoardSort('inf')">Influence</button></div>
      <div class="sub" id="board-sub">by inbound recs</div>
    </div>
    <div id="board-list"></div>
  </div>
  <div id="view-dec" style="display:none">
    <div class="dfilter" id="dec-filter"></div>
    <div id="dec-list"></div>
  </div>
</div>

<!-- detail drawer -->
<div class="side" id="panel">
  <div class="ph">
    <div class="ph-icon" id="pi">&#128240;</div>
    <div class="ph-text"><div class="ph-title" id="pt">Publication</div><div class="ph-sub" id="ps"></div></div>
    <button class="ph-close" onclick="closePanel()">&#10005;</button>
  </div>
  <div class="pb" id="pb"></div>
</div>

<script>
var COLORS={
  hub:{background:'#3d1d0a',border:'#ff6b35',hover:{background:'#4d2510',border:'#ff9a6c'},highlight:{background:'#ff6b35',border:'#ffb899'}},
  merged:{background:'#78350f',border:'#f59e0b',hover:{background:'#92400e',border:'#fbbf24'},highlight:{background:'#b45309',border:'#fcd34d'}},
  single:{background:'#1a1a1a',border:'#ff6b35',hover:{background:'#222222',border:'#ff9a6c'},highlight:{background:'#333333',border:'#ff9a6c'}},
  conflict:{background:'#4c0519',border:'#ef4444',hover:{background:'#881337',border:'#fb7185'},highlight:{background:'#be123c',border:'#fda4af'}},
  naive:{background:'#1a1a1a',border:'#555555',hover:{background:'#222222',border:'#777777'},highlight:{background:'#333333',border:'#999999'}},
  seed:{background:'#ffffff',border:'#ff6b35',hover:{background:'#f0f0f0',border:'#ff9a6c'},highlight:{background:'#ffffff',border:'#ff9a6c'}}
};
var CLUSTER_PALETTE=['#ff6b35','#22d3ee','#f59e0b','#22c55e','#ef4444','#a855f7','#3b82f6','#ec4899','#84cc16','#ff9a6c','#14b8a6','#eab308'];
function clusterHex(c){return c<0?'#475569':CLUSTER_PALETTE[c%CLUSTER_PALETTE.length];}
function clusterColor(c){var h=clusterHex(c);return {background:h,border:'#fff',hover:{background:h,border:'#fff'},highlight:{background:h,border:'#fff'}};}

var VIS_OPTIONS={
  nodes:{shape:'dot',scaling:{min:9,max:46,label:{enabled:true,min:11,max:16,maxVisible:18,drawThreshold:5}},
    font:{color:'#f0f0f0',size:12,face:'Inter,sans-serif',strokeWidth:3,strokeColor:'#0a0a0a'},
    borderWidth:1.5,shadow:{enabled:true,color:'rgba(0,0,0,.5)',size:10,x:0,y:4}},
  edges:{color:{color:'#2a2a2a',hover:'#ff6b35',highlight:'#ff9a6c',opacity:.9},
    arrows:{to:{enabled:true,scaleFactor:.45,type:'arrow'}},width:1.2,selectionWidth:2.5,smooth:{type:'curvedCW',roundness:.08}},
  physics:{solver:'barnesHut',barnesHut:{gravitationalConstant:-14000,centralGravity:.3,springLength:130,springConstant:.035,damping:.1,avoidOverlap:.3},
    stabilization:{enabled:true,iterations:300,updateInterval:25,fit:true},minVelocity:.5},
  interaction:{hover:true,hoverConnectedEdges:true,tooltipDelay:80,zoomView:true,dragView:true,dragNodes:true,
    navigationButtons:false,keyboard:{enabled:true,speed:{x:10,y:10,zoom:.02}}},
  layout:{improvedLayout:true}
};

var network=null,dsNodes=null,dsEdges=null,curMode='resolved',curData=null;
var byId={},adjOut={},adjIn={},isolatedId=null;
var leftOpen=null,leftTab='board',boardSort='in',colorMode='degree',clusterFilter=null;
var decRecords=null,decFilter='all';

function setMode(m){
  if(m===curMode&&curData)return;
  curMode=m;
  document.getElementById('btn-resolved').className='toggle-btn'+(m==='resolved'?' active-resolved':'');
  document.getElementById('btn-naive').className='toggle-btn'+(m==='naive'?' active-naive':'');
  document.getElementById('stripe').style.background=m==='resolved'?'#ff6b35':'#ef4444';
  document.getElementById('search').value='';
  isolatedId=null;clusterFilter=null;decRecords=null;closePanel();loadGraph(m);
}

function loadGraph(m){
  showLoading(true,'Loading '+m+' graph…');
  fetch('/api/graph?mode='+m).then(function(r){return r.json();}).then(function(d){
    curData=d;
    if(!d.nodes||!d.nodes.length){showLoading(false);showEmpty(true);return;}
    showEmpty(false);
    buildIndex(d);
    renderNetwork(d,m);
    updateStats(d);
    updateDecBar(d);
    updateModeNote(d);
    buildBoard();
    buildLegend();
    buildHandles(d);
  }).catch(function(e){console.error(e);showLoading(false);});
}

function buildIndex(d){
  byId={};adjOut={};adjIn={};
  d.nodes.forEach(function(n){byId[n.id]=n;adjOut[n.id]=[];adjIn[n.id]=[];});
  d.edges.forEach(function(e){if(adjOut[e.from])adjOut[e.from].push(e.to);if(adjIn[e.to])adjIn[e.to].push(e.from);});
}
function buildHandles(d){
  var dl=document.getElementById('handles');
  dl.innerHTML=d.nodes.map(function(n){return '<option value="'+esc(n.label)+'">';}).join('');
}

function isSeed(n){return (n.domains||[]).some(function(d){return d.indexOf('theairuntime')>=0;});}
function nodeColor(n,m){
  if(colorMode==='cluster')return clusterColor(typeof n.cluster==='number'?n.cluster:-1);
  if(isSeed(n))return COLORS.seed;
  if(m==='naive')return (n.ids_seen&&n.ids_seen.length>1)?COLORS.conflict:COLORS.naive;
  if((n.surfaces||1)>1)return COLORS.merged;
  if((n.value||0)>=3)return COLORS.hub;
  return COLORS.single;
}
function tooltip(n,m){
  var lines=[],d0=(n.domains||[])[0]||'';
  lines.push('<span style="color:#a0a0a0">&#8595; '+(n.value||0)+' inbound &nbsp; &#8593; '+(n.out||0)+' outbound</span>');
  if(m==='resolved'&&(n.surfaces||1)>1)lines.push('<span style="color:#f59e0b">&#8853; '+n.surfaces+' surfaces merged</span>');
  if(m==='naive'&&n.ids_seen&&n.ids_seen.length>1)lines.push('<span style="color:#ef4444">&#9888; '+n.ids_seen.length+' pub IDs collapsed</span>');
  if(d0)lines.push('<span style="color:#555555;font-size:11px">'+esc(d0)+'</span>');
  return '<div style="font:12px Inter,sans-serif;padding:9px 11px;max-width:240px;background:#1a1a1a;border:1px solid #333333;border-radius:9px;color:#f0f0f0;line-height:1.6"><b style="color:#f0f0f0">'+esc(n.label)+'</b><br>'+lines.join('<br>')+'</div>';
}

function renderNetwork(d,m){
  var vn=d.nodes.map(function(n){var s=n.surfaces||1;
    return {id:n.id,label:s>1?n.label+'\n('+s+'×)':n.label,title:tooltip(n,m),value:Math.max(1,n.value||0),color:nodeColor(n,m),_raw:n};});
  var ve=d.edges.map(function(e,i){return {id:i,from:e.from,to:e.to};});
  if(network){network.destroy();network=null;}
  dsNodes=new vis.DataSet(vn);dsEdges=new vis.DataSet(ve);
  network=new vis.Network(document.getElementById('gc'),{nodes:dsNodes,edges:dsEdges},VIS_OPTIONS);
  network.on('stabilizationIterationsDone',function(){
    showLoading(false);network.setOptions({physics:{enabled:false}});
    network.fit({animation:{duration:700,easingFunction:'easeInOutQuad'}});
  });
  setTimeout(function(){showLoading(false);},10000);
  network.on('click',function(p){if(!p.nodes.length){closePanel();return;}openPanel(byId[p.nodes[0]],m);});
  network.on('doubleClick',function(p){if(p.nodes.length)network.focus(p.nodes[0],{scale:1.5,animation:{duration:450}});});
}

function recolor(){
  if(!dsNodes)return;
  dsNodes.update(dsNodes.get().map(function(n){return {id:n.id,color:nodeColor(n._raw,curMode)};}));
}

/* ── color mode + cluster legend ── */
function setColorMode(mode){
  colorMode=mode;clusterFilter=null;
  document.getElementById('cm-degree').className=mode==='degree'?'on':'';
  document.getElementById('cm-cluster').className=mode==='cluster'?'on':'';
  recolor();buildLegend();applyClusterFilter();
}
function buildLegend(){
  var el=document.getElementById('legend-body');
  if(colorMode==='degree'){
    if(curMode==='naive'){
      el.innerHTML='<div class="leg"><div class="ldot" style="background:#f43f5e"></div>Identity conflict</div>'
        +'<div class="leg"><div class="ldot" style="background:#555555"></div>Publication</div>';
    }else{
      el.innerHTML='<div class="leg"><div class="ldot" style="background:#ff6b35"></div>Hub (&ge;3 inbound)</div>'
        +'<div class="leg"><div class="ldot" style="background:#ff6b35"></div>Publication</div>'
        +'<div class="leg"><div class="ldot" style="background:#f59e0b"></div>Merged (multi-surface)</div>';
    }
  }else{
    var counts={};(curData?curData.nodes:[]).forEach(function(n){var c=(typeof n.cluster==='number')?n.cluster:-1;counts[c]=(counts[c]||0)+1;});
    var keys=Object.keys(counts).map(Number).sort(function(a,b){return counts[b]-counts[a];});
    var html='';
    keys.slice(0,10).forEach(function(c){
      var dim=(clusterFilter!==null&&clusterFilter!==c)?' dim':'';
      html+='<div class="cl-row'+dim+'" onclick="toggleCluster('+c+')"><div class="cluster-pip" style="background:'+clusterHex(c)+'"></div>Cluster '+(c<0?'—':(c+1))+' <span style="color:#555555">('+counts[c]+')</span></div>';
    });
    el.innerHTML=html||'<div class="leg" style="color:#555555">no clusters</div>';
  }
}
function toggleCluster(c){
  clusterFilter=(clusterFilter===c)?null:c;
  buildLegend();applyClusterFilter();
}
function applyClusterFilter(){
  if(!dsNodes)return;
  if(colorMode!=='cluster'||clusterFilter===null){
    dsNodes.update(dsNodes.get().map(function(n){return {id:n.id,hidden:false};}));
    dsEdges.update(dsEdges.get().map(function(e){return {id:e.id,hidden:false};}));
    return;
  }
  var keep=new Set();(curData.nodes||[]).forEach(function(n){if(((typeof n.cluster==='number')?n.cluster:-1)===clusterFilter)keep.add(n.id);});
  dsNodes.update(dsNodes.get().map(function(n){return {id:n.id,hidden:!keep.has(n.id)};}));
  dsEdges.update(dsEdges.get().map(function(e){return {id:e.id,hidden:!(keep.has(e.from)&&keep.has(e.to))};}));
  if(keep.size)network.fit({nodes:Array.from(keep),animation:{duration:450}});
}

/* ── detail drawer ── */
function openPanel(n,m){
  if(!n)return;
  var iconBg='rgba(255,107,53,.14)',iconCh='&#128240;';
  if(m==='resolved'&&(n.surfaces||1)>1){iconBg='rgba(245,158,11,.14)';iconCh='&#8853;';}
  else if(m==='naive'&&n.ids_seen&&n.ids_seen.length>1){iconBg='rgba(239,68,68,.14)';iconCh='&#9888;';}
  else if((n.value||0)>=3){iconBg='rgba(255,107,53,.2)';iconCh='&#9711;';}
  document.getElementById('pi').style.background=iconBg;
  document.getElementById('pi').innerHTML=iconCh;
  document.getElementById('pt').textContent=n.label||String(n.id);
  document.getElementById('ps').textContent=(n.domains||[])[0]||'';

  var inN=adjIn[n.id]||[],outN=adjOut[n.id]||[];
  var bal=outN.length-inN.length;
  var h='';

  var bb='';
  if(m==='resolved'&&(n.surfaces||1)>1)bb+='<span class="badge b-merged">&#8853; merged '+n.surfaces+'×</span>';
  if((n.value||0)>=3)bb+='<span class="badge b-hub">hub</span>';
  if(typeof n.cluster==='number'&&n.cluster>=0)bb+='<span class="badge" style="background:'+clusterHex(n.cluster)+'22;color:'+clusterHex(n.cluster)+';border:1px solid '+clusterHex(n.cluster)+'55">cluster '+(n.cluster+1)+'</span>';
  if(m==='naive'&&n.ids_seen&&n.ids_seen.length>1)bb+='<span class="badge b-conflict">&#9888; identity conflict</span>';
  if(bb)h+='<div>'+bb+'</div>';

  h+='<div class="metrics">';
  h+='<div class="mc"><div class="v" style="color:#ff9a6c">'+inN.length+'</div><div class="l">Recommendations received</div></div>';
  h+='<div class="mc"><div class="v" style="color:#22d3ee">'+outN.length+'</div><div class="l">Recommendations given</div></div>';
  h+='</div>';
  var balTxt=bal>0?('+'+bal+' net giver'):(bal<0?(bal+' net receiver'):'balanced');
  var balCol=bal>0?'#22d3ee':(bal<0?'#ff9a6c':'#a0a0a0');
  h+='<div class="srow"><span class="sl">Recommendation balance</span><span class="sv" style="color:'+balCol+'">'+balTxt+'</span></div>';
  if(typeof n.rank==='number')h+='<div class="srow"><span class="sl">Influence (PageRank)</span><span class="sv">'+(n.rank*1000).toFixed(1)+'&permil;</span></div>';

  /* intro-path finder */
  h+='<div class="pf"><div class="pt">&#128279; Find intro path</div>'
    +'<input id="pf-input" list="handles" placeholder="to a publication…" onkeydown="if(event.key===\'Enter\')runPath('+jid(n.id)+',this.value)">'
    +'<div class="presult" id="pf-result"></div></div>';

  /* opportunities (resolved) */
  if(m==='resolved'){
    var opp=computeOpportunities(n.id);
    if(opp.swaps.length||opp.asymOut.length||opp.asymIn.length){
      h+='<div class="opp"><div class="ot">&#9889; Recommendation opportunities</div>';
      if(opp.swaps.length){h+='<div class="od">Second-degree pubs — natural swap targets:</div><div>';
        opp.swaps.slice(0,8).forEach(function(id){h+='<span class="tag" onclick="focusNode('+jid(id)+')">'+esc(byId[id].label)+'</span>';});h+='</div>';}
      if(opp.asymOut.length){h+='<div class="od" style="margin-top:8px">You recommend, no rec back:</div><div>';
        opp.asymOut.slice(0,6).forEach(function(id){h+='<span class="tag" onclick="focusNode('+jid(id)+')">&#8599; '+esc(byId[id].label)+'</span>';});h+='</div>';}
      if(opp.asymIn.length){h+='<div class="od" style="margin-top:8px">Recommend you, you don\'t back:</div><div>';
        opp.asymIn.slice(0,6).forEach(function(id){h+='<span class="tag" onclick="focusNode('+jid(id)+')">&#8601; '+esc(byId[id].label)+'</span>';});h+='</div>';}
      h+='</div>';
    }
  }

  h+=neighborList('Recommended by',inN);
  h+=neighborList('Recommends',outN);

  var ds=n.domains||[];
  if(ds.length){
    h+='<div class="ps"><h3>Surfaces / URLs <span class="cnt">'+ds.length+'</span></h3><div class="dlist">';
    ds.forEach(function(u){var url=u.indexOf('http')===0?u:'https://'+u;
      h+='<a href="'+esc(url)+'" target="_blank" rel="noopener" class="ditem"><svg width="12" height="12" viewBox="0 0 12 12" fill="none"><circle cx="6" cy="6" r="5" stroke="currentColor" stroke-width="1.3"/><line x1="6" y1="1" x2="6" y2="11" stroke="currentColor" stroke-width="1.3"/><path d="M1.5 4.5h9M1.5 7.5h9" stroke="currentColor" stroke-width="1.3"/></svg><span class="grow">'+esc(u)+'</span></a>';});
    h+='</div></div>';
  }

  h+='<div class="pact"><button id="iso-btn" onclick="toggleIsolate('+jid(n.id)+')">'+(isolatedId===n.id?'Show full graph':'Isolate neighborhood')+'</button>'
    +'<button onclick="focusNode('+jid(n.id)+')">Center</button></div>';

  document.getElementById('pb').innerHTML=h;
  document.getElementById('panel').classList.add('open');
  if(network){var c=(network.getConnectedNodes(n.id)||[]).concat([n.id]);network.selectNodes(c,false);}
}

function neighborList(title,ids){
  if(!ids.length)return '';
  var h='<div class="ps"><h3>'+esc(title)+' <span class="cnt">'+ids.length+'</span></h3><div class="dlist">';
  ids.slice(0,20).forEach(function(id){var nn=byId[id];if(!nn)return;
    h+='<div class="ditem" onclick="focusNode('+jid(id)+')"><svg width="12" height="12" viewBox="0 0 12 12" fill="none"><circle cx="6" cy="6" r="2.4" fill="currentColor"/></svg><span class="grow">'+esc(nn.label)+'</span><span style="color:#555555;font-size:11px">&#8595;'+(nn.value||0)+'</span></div>';});
  if(ids.length>20)h+='<div style="font-size:11px;color:#555555;padding:4px 9px">+'+(ids.length-20)+' more</div>';
  h+='</div></div>';return h;
}

function computeOpportunities(id){
  var inN=adjIn[id]||[],outN=adjOut[id]||[];
  var direct=new Set(inN.concat(outN));direct.add(id);
  var swapCount={};
  inN.forEach(function(rec){(adjOut[rec]||[]).forEach(function(t){if(!direct.has(t))swapCount[t]=(swapCount[t]||0)+1;});});
  var swaps=Object.keys(swapCount).map(Number).sort(function(a,b){return swapCount[b]-swapCount[a]||(byId[b].value||0)-(byId[a].value||0);});
  var inSet=new Set(inN),outSet=new Set(outN);
  return {swaps:swaps,asymOut:outN.filter(function(t){return !inSet.has(t);}),asymIn:inN.filter(function(t){return !outSet.has(t);})};
}

/* undirected BFS shortest path (intro chain) */
function findPath(src,dst){
  if(src===dst)return [src];
  var seen=new Set([src]),q=[[src]];
  while(q.length){var p=q.shift(),last=p[p.length-1];
    var nbrs=(adjOut[last]||[]).concat(adjIn[last]||[]);
    for(var i=0;i<nbrs.length;i++){var nb=nbrs[i];
      if(nb===dst)return p.concat([dst]);
      if(!seen.has(nb)){seen.add(nb);q.push(p.concat([nb]));}}}
  return null;
}
function resolveHandle(name){
  name=(name||'').trim().toLowerCase();if(!name)return null;
  var exact=null,partial=null;
  for(var id in byId){var l=(byId[id].label||'').toLowerCase();
    if(l===name){exact=byId[id].id;break;}
    if(partial===null&&l.indexOf(name)>=0)partial=byId[id].id;}
  return exact!==null?exact:partial;
}
function runPath(srcId,targetName){
  var res=document.getElementById('pf-result');
  var dst=resolveHandle(targetName);
  if(dst===null){res.innerHTML='<span style="color:#fb7185">No publication matches that name.</span>';return;}
  if(dst===srcId){res.innerHTML='That\'s the same publication.';return;}
  var path=findPath(srcId,dst);
  if(!path){res.innerHTML='<span style="color:#fb7185">No connecting path in this network.</span>';return;}
  var hops=path.length-1;
  var chain='<div class="chain">';
  path.forEach(function(id,i){chain+='<span class="hop" onclick="focusNode('+jid(id)+')">'+esc(byId[id].label)+'</span>';if(i<path.length-1)chain+='<span class="arr">&#8594;</span>';});
  chain+='</div>';
  res.innerHTML='<b style="color:#67e8f9">'+hops+(hops===1?' hop':' hops')+'</b> away'+chain;
  network.selectNodes(path,false);
  network.fit({nodes:path,animation:{duration:600}});
}

function focusNode(id){if(!network)return;network.focus(id,{scale:1.4,animation:{duration:500,easingFunction:'easeInOutQuad'}});openPanel(byId[id],curMode);}

function toggleIsolate(id){
  if(!dsNodes)return;
  if(isolatedId===id){
    dsNodes.update(dsNodes.get().map(function(n){return {id:n.id,hidden:false};}));
    dsEdges.update(dsEdges.get().map(function(e){return {id:e.id,hidden:false};}));
    isolatedId=null;network.fit({animation:{duration:500}});
  }else{
    var keep=new Set((adjIn[id]||[]).concat(adjOut[id]||[]));keep.add(id);
    dsNodes.update(dsNodes.get().map(function(n){return {id:n.id,hidden:!keep.has(n.id)};}));
    dsEdges.update(dsEdges.get().map(function(e){return {id:e.id,hidden:!(keep.has(e.from)&&keep.has(e.to))};}));
    isolatedId=id;network.fit({nodes:Array.from(keep),animation:{duration:500}});
  }
  var b=document.getElementById('iso-btn');if(b)b.textContent=isolatedId===id?'Show full graph':'Isolate neighborhood';
}

function jid(id){return typeof id==='number'?id:('"'+String(id).replace(/"/g,'\\"')+'"');}
function closePanel(){document.getElementById('panel').classList.remove('open');if(network)network.unselectAll();}

/* ── left panel (board + decisions) ── */
function openLeft(which){
  if(which===null||(leftOpen&&leftTab===which)){
    leftOpen=null;document.getElementById('board').classList.remove('open');
    document.getElementById('btn-board').classList.remove('on');document.getElementById('btn-dec').classList.remove('on');
    return;
  }
  leftOpen=true;switchTab(which);
  document.getElementById('board').classList.add('open');
}
function switchTab(which){
  leftTab=which;
  document.getElementById('tab-board').className='tab'+(which==='board'?' on':'');
  document.getElementById('tab-dec').className='tab'+(which==='dec'?' on':'');
  document.getElementById('view-board').style.display=which==='board'?'':'none';
  document.getElementById('view-dec').style.display=which==='dec'?'':'none';
  document.getElementById('btn-board').classList.toggle('on',which==='board');
  document.getElementById('btn-dec').classList.toggle('on',which==='dec');
  if(which==='dec'&&!decRecords)loadDecisions();
}
function setBoardSort(s){boardSort=s;
  document.getElementById('bs-in').className=s==='in'?'on':'';
  document.getElementById('bs-inf').className=s==='inf'?'on':'';
  document.getElementById('board-sub').textContent=s==='in'?'by inbound recs':'by influence (PageRank)';
  buildBoard();}
function buildBoard(){
  if(!curData)return;
  var ranked=curData.nodes.slice().sort(function(a,b){
    return boardSort==='inf'?((b.rank||0)-(a.rank||0)):((b.value||0)-(a.value||0)||(b.out||0)-(a.out||0));});
  var max=boardSort==='inf'?(ranked.length?(ranked[0].rank||1):1):(ranked.length?(ranked[0].value||1):1);
  var h='';
  ranked.slice(0,60).forEach(function(n,i){
    var metric=boardSort==='inf'?(n.rank||0):(n.value||0);
    var pct=Math.round(100*metric/(max||1));
    var pip=(typeof n.cluster==='number'&&n.cluster>=0)?'<div class="cluster-pip" style="background:'+clusterHex(n.cluster)+'"></div>':'';
    h+='<div class="brow" onclick="focusNode('+jid(n.id)+');">';
    h+='<div class="brk'+(i<3?' top':'')+'">'+(i+1)+'</div>'+pip;
    h+='<div class="brn"><div class="h">'+esc(n.label)+'</div><div class="m">&#8595; '+(n.value||0)+' in &nbsp;&#8593; '+(n.out||0)+' out</div></div>';
    h+='<div class="brbar"><i style="width:'+pct+'%"></i></div></div>';
  });
  document.getElementById('board-list').innerHTML=h;
}

/* ── decision log ── */
function loadDecisions(){
  document.getElementById('dec-list').innerHTML='<div style="padding:16px;color:#555555;font-size:12px">Loading decision log…</div>';
  fetch('/api/decisions').then(function(r){return r.json();}).then(function(d){
    decRecords=d.decisions||[];buildDecFilter();renderDecisions();
  }).catch(function(){document.getElementById('dec-list').innerHTML='<div style="padding:16px;color:#fb7185;font-size:12px">Failed to load.</div>';});
}
function buildDecFilter(){
  var counts={all:decRecords.length};
  decRecords.forEach(function(r){counts[r.action]=(counts[r.action]||0)+1;});
  var order=['all','merge','refuse','alias','drop_404','drop_self_loop'];
  var labels={all:'all',merge:'merge',refuse:'refuse',alias:'alias',drop_404:'404 drop',drop_self_loop:'self-loop'};
  var h='';
  order.forEach(function(k){if(counts[k]===undefined)return;
    h+='<span class="fc'+(decFilter===k?' on':'')+'" onclick="setDecFilter(\''+k+'\')">'+labels[k]+' '+counts[k]+'</span>';});
  document.getElementById('dec-filter').innerHTML=h;
}
function setDecFilter(k){decFilter=k;buildDecFilter();renderDecisions();}
function renderDecisions(){
  var list=document.getElementById('dec-list');
  if(!decRecords.length){list.innerHTML='<div style="padding:16px;color:#555555;font-size:12px">No decisions recorded for this dataset. The resolver made no merges, refusals, or drops — so the resolved and naive maps are identical.</div>';return;}
  var recs=decFilter==='all'?decRecords:decRecords.filter(function(r){return r.action===decFilter;});
  var h='';
  recs.forEach(function(r){
    var ev=(r.evidence||[]).map(function(e){return e.signal+(e.value!==undefined?('='+JSON.stringify(e.value)):'');}).join(', ');
    var mem=(r.members||[]).map(function(m){var n=byId[m];return n?n.label:m;}).join(' · ');
    h+='<div class="dcard"><div class="dh"><span class="da da-'+r.action+'">'+r.action.replace(/_/g,' ')+'</span>';
    if(r.score!==undefined)h+='<span class="sc">score '+r.score+' / thr '+(r.threshold!==undefined?r.threshold:'—')+'</span>';
    h+='</div>';
    if(mem)h+='<div class="dm">'+esc(mem)+'</div>';
    if(r.target_url)h+='<div class="dm">target: '+esc(r.target_url)+'</div>';
    if(ev)h+='<div class="ev">'+esc(ev)+' &rarr; <b style="color:#a0a0a0">'+esc(r.outcome||'')+'</b></div>';
    h+='</div>';
  });
  list.innerHTML=h||'<div style="padding:16px;color:#555555;font-size:12px">None of this type.</div>';
}

/* ── search ── */
function onSearch(q){
  if(!dsNodes||!dsEdges)return;
  q=q.trim().toLowerCase();
  if(!q){applyClusterFilter();isolatedId=null;return;}
  var hits=new Set();
  dsNodes.get().forEach(function(n){var r=n._raw||{},txt=[r.label||''].concat(r.domains||[]).join(' ').toLowerCase();
    if(txt.indexOf(q)>=0)hits.add(n.id);});
  dsNodes.update(dsNodes.get().map(function(n){return {id:n.id,hidden:!hits.has(n.id)};}));
  dsEdges.update(dsEdges.get().map(function(e){return {id:e.id,hidden:!hits.has(e.from)||!hits.has(e.to)};}));
  if(hits.size)network.fit({nodes:Array.from(hits),animation:{duration:450}});
}

/* ── stats / decisions bar / mode note ── */
function updateStats(d){
  var m=d.meta||{},nc=m.node_count||0,ec=m.edge_count||0;
  setChip('sc-nodes',nc,'pubs');setChip('sc-edges',ec,'recs');
  setChip('sc-avg',nc?(ec/nc).toFixed(1):'0','avg/pub');
  var top=d.nodes.slice().sort(function(a,b){return (b.value||0)-(a.value||0);})[0];
  document.getElementById('sc-top').innerHTML='<span class="dot"></span>top: <b>'+(top?esc(top.label):'—')+'</b>';
}
function setChip(id,val,suf){document.getElementById(id).innerHTML='<span class="dot"></span><b>'+val+'</b>&nbsp;'+suf;}
function updateDecBar(d){
  var bar=document.getElementById('decbar');bar.innerHTML='';var m=d.meta||{};
  if(typeof m.cluster_count==='number'&&m.cluster_count>0)bar.innerHTML+='<div class="dc"><span class="dd" style="background:#a855f7"></span>'+m.cluster_count+' clusters</div>';
  if(curMode==='resolved'&&m.decisions){
    var labels={merge:['dc-merge','merged'],refuse:['dc-refuse','refused'],alias:['dc-alias','aliased'],drop_404:['dc-drop','404 dropped'],drop_self_loop:['dc-drop','self-loops removed']};
    Object.entries(m.decisions).forEach(function(kv){var info=labels[kv[0]]||['dc-drop',kv[0]];
      bar.innerHTML+='<div class="dc '+info[0]+'" onclick="openLeft(\'dec\')" style="cursor:pointer"><span class="dd"></span>'+kv[1]+' '+info[1]+'</div>';});
  }else if(curMode==='naive'){
    if(m.dropped_edges)bar.innerHTML+='<div class="dc dc-drop"><span class="dd"></span>'+m.dropped_edges+' edges dropped</div>';
    if(m.self_loops)bar.innerHTML+='<div class="dc dc-drop"><span class="dd"></span>'+m.self_loops+' self-loops</div>';
  }
}
function updateModeNote(d){
  var note=document.getElementById('modenote'),m=d.meta||{};
  var totalDec=m.decisions?Object.values(m.decisions).reduce(function(a,b){return a+b;},0):0;
  if(curMode==='resolved'&&totalDec===0){note.className='show';
    note.innerHTML='&#9432; No resolution decisions in this dataset yet — resolved and naive maps are currently identical.';}
  else{note.className='';}
}

function showLoading(v,msg){var el=document.getElementById('loading');el.style.display=v?'flex':'none';if(msg)document.getElementById('loading-msg').textContent=msg;}
function showEmpty(v){document.getElementById('empty').className=v?'show':'';}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

document.addEventListener('keydown',function(e){
  var tag=document.activeElement.tagName;
  if(e.key==='Escape'){closePanel();openLeft(null);var s=document.getElementById('search');s.value='';onSearch('');}
  if(e.key==='/'&&tag!=='INPUT'){e.preventDefault();document.getElementById('search').focus();}
  if(e.key==='r'&&tag!=='INPUT'&&network)network.fit({animation:{duration:600}});
  if(e.key==='b'&&tag!=='INPUT')openLeft('board');
  if(e.key==='d'&&tag!=='INPUT')openLeft('dec');
  if(e.key==='1'&&tag!=='INPUT')setMode('resolved');
  if(e.key==='2'&&tag!=='INPUT')setMode('naive');
});

/* ── subscriber gate ── */
var BYPASS_GATE=__BYPASS_GATE__;
function gateOk(){
  if(BYPASS_GATE)return true;
  try{return sessionStorage.getItem('sg_verified')==='1';}catch(e){return false;}
}
function dismissGate(){
  var g=document.getElementById('gate');g.classList.add('gone');
  setTimeout(function(){g.style.display='none';},400);
}
function verifyGate(){
  var email=(document.getElementById('gate-email').value||'').trim();
  var err=document.getElementById('gate-error');
  var cta=document.getElementById('gate-cta');
  var btn=document.getElementById('gate-btn');
  if(!email){err.textContent='Please enter your email.';err.style.display='block';return;}
  btn.disabled=true;btn.textContent='Checking\u2026';err.style.display='none';cta.style.display='none';
  fetch('/api/verify-subscriber',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:email})})
    .then(function(r){return r.json().then(function(d){return {ok:r.ok,data:d};});})
    .then(function(res){
      btn.disabled=false;btn.textContent='Verify Access';
      if(res.ok&&res.data.subscribed){
        try{sessionStorage.setItem('sg_verified','1');}catch(e){}
        dismissGate();setMode('resolved');
      }else if(res.data.error){
        err.textContent=res.data.error;err.style.display='block';
      }else{
        err.textContent='We could not verify your subscription.';err.style.display='block';
        cta.style.display='block';
      }
    }).catch(function(){btn.disabled=false;btn.textContent='Verify Access';err.textContent='Network error — please try again.';err.style.display='block';});
}
document.getElementById('gate-email').addEventListener('keydown',function(e){if(e.key==='Enter')verifyGate();});

if(gateOk()){dismissGate();setMode('resolved');}
</script>
</body>
</html>"""
