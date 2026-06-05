"""Command-line entry point: crawl / render-naive / render-resolved.

    substackgraph crawl --seed <url> [--hops 2]   # cache-first, rate-limited ingestion
    substackgraph render-naive                     # the corrupted "before" map
    substackgraph render-resolved                  # run the harness → resolved "after" map
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config
from .auditlog import AuditLog
from .cache import Cache
from .client import SubstackClient, normalize_url
from .crawl import crawl, load_raw_graph
from .naive_graph import build_naive
from .ratelimit import RateLimiter
from .resolve import resolve

DEMO_FIXTURE = Path(__file__).resolve().parent / "data" / "demo_neighborhood.json"


def _add_db_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument("--db", default=str(config.DB_PATH), help="SQLite cache path")


def cmd_crawl(args: argparse.Namespace) -> int:
    config.ensure_dirs()
    cache = Cache(args.db)
    try:
        crawl(args.seed, args.hops, cache, RateLimiter(), SubstackClient())
        nodes, edges = load_raw_graph(cache)
        print(f"Crawled {len(nodes)} nodes / {len(edges)} edges into {args.db} (cache-first, ≤1 req/s).")
    finally:
        cache.close()
    return 0


def cmd_render_naive(args: argparse.Namespace) -> int:
    config.ensure_dirs()
    cache = Cache(args.db)
    try:
        nodes, edges = load_raw_graph(cache)
        graph, stats = build_naive(nodes, edges)
    finally:
        cache.close()
    out = config.GRAPHS_DIR / "naive.html"
    from .render import render_graph

    render_graph(graph, "substackgraph — naive (corrupted)", out)
    print(
        f"Naive map → {out}\n  nodes={stats.node_count} edges={stats.edge_count} "
        f"dropped_edges={stats.dropped_edges} self_loops={stats.self_loops}"
    )
    return 0


def cmd_render_resolved(args: argparse.Namespace) -> int:
    config.ensure_dirs()
    cache = Cache(args.db)
    audit = AuditLog(path=config.LOG_PATH)
    try:
        nodes, edges = load_raw_graph(cache)
        result = resolve(nodes, edges, audit=audit)
    finally:
        cache.close()
        audit.close()
    out = config.GRAPHS_DIR / "resolved.html"
    from .render import render_graph

    render_graph(result.graph, "substackgraph — resolved", out)
    actions: dict[str, int] = {}
    for rec in audit.records:
        actions[rec["action"]] = actions.get(rec["action"], 0) + 1
    print(
        f"Resolved map → {out}\n  canonical_nodes={len(result.nodes)} edges={len(result.edges)}\n"
        f"  decisions={dict(sorted(actions.items()))} → {config.LOG_PATH}"
    )
    return 0


def cmd_load_demo(args: argparse.Namespace) -> int:
    """Load the bundled demo neighborhood into the cache so the site has something to show
    before a real crawl runs."""
    config.ensure_dirs()
    data = json.loads(Path(args.path).read_text())
    cache = Cache(args.db)
    try:
        for url, entry in data["meta"].items():
            nurl = normalize_url(url)
            cache.put(f"meta:{nurl}", nurl, entry["status"], entry["meta"])
        for url, recs in data["recs"].items():
            nurl = normalize_url(url)
            cache.put(f"recs:{nurl}", nurl, "ok", [normalize_url(r) for r in recs])
    finally:
        cache.close()
    print(f"Loaded demo neighborhood from {args.path} into {args.db}.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the live web app (substackgraph.com)."""
    try:
        import uvicorn
    except ImportError:
        print("The web extra is not installed. Run: pip install -e '.[web]'", file=sys.stderr)
        return 1
    uvicorn.run("substackgraph.web:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="substackgraph", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_crawl = sub.add_parser("crawl", help="crawl the recommendation neighborhood (cache-first)")
    p_crawl.add_argument("--seed", required=True, help="seed publication URL")
    p_crawl.add_argument("--hops", type=int, default=2, help="crawl depth (default 2)")
    _add_db_arg(p_crawl)
    p_crawl.set_defaults(func=cmd_crawl)

    p_naive = sub.add_parser("render-naive", help="render the corrupted 'before' graph")
    _add_db_arg(p_naive)
    p_naive.set_defaults(func=cmd_render_naive)

    p_res = sub.add_parser("render-resolved", help="run the harness and render the resolved graph")
    _add_db_arg(p_res)
    p_res.set_defaults(func=cmd_render_resolved)

    p_demo = sub.add_parser("load-demo", help="load the bundled demo neighborhood into the cache")
    p_demo.add_argument("--path", default=str(DEMO_FIXTURE), help="fixture JSON path")
    _add_db_arg(p_demo)
    p_demo.set_defaults(func=cmd_load_demo)

    p_serve = sub.add_parser("serve", help="run the live web app")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true", help="auto-reload (development)")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
