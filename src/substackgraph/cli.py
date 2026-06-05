"""Command-line entry point: crawl / render-naive / render-resolved.

    substackgraph crawl --seed <url> [--hops 2]   # cache-first, rate-limited ingestion
    substackgraph render-naive                     # the corrupted "before" map
    substackgraph render-resolved                  # run the harness → resolved "after" map
"""

from __future__ import annotations

import argparse
import sys

from . import config
from .auditlog import AuditLog
from .cache import Cache
from .client import SubstackClient
from .crawl import crawl, load_raw_graph
from .naive_graph import build_naive
from .ratelimit import RateLimiter
from .resolve import resolve


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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
