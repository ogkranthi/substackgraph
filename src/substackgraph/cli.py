"""Command-line entry point for substackgraph.

    substackgraph crawl --seed <url> [--hops 2]
    substackgraph render-naive
    substackgraph render-resolved
    substackgraph validate
    substackgraph reciprocity-gaps
    substackgraph bridge-nodes
    substackgraph warm-path --from <url> --to <url>
    substackgraph cluster-map
    substackgraph top-nodes [--metric degree]
    substackgraph overlap --pub <url>
    substackgraph voice-compat --pub-a <url> --pub-b <url>
    substackgraph blind-spots --cluster <id>
    substackgraph journey-match --pub <url>
    substackgraph rising-stars
    substackgraph surprise-matches --pub <url>
    substackgraph live-hooks --pub <url>
    substackgraph collab-brief --pub-a <url> --pub-b <url>
    substackgraph outreach-angles --pub-a <url> --pub-b <url>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from . import analytics, config
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


def _resolve_graph(db: str):
    """Load cache, run resolution, return (result, cache). Caller must close cache."""
    cache = Cache(db)
    nodes, edges = load_raw_graph(cache)
    result = resolve(nodes, edges, audit=AuditLog())
    return result, cache


def _pub_id_from_url(graph, url: str) -> int | None:
    """Resolve a publication URL to its canonical node ID in the graph."""
    nurl = normalize_url(url)
    for n, d in graph.nodes(data=True):
        member_urls = d.get("member_urls", [])
        if nurl in member_urls:
            return n
    # Fallback: subdomain token match
    host = urlsplit(nurl).netloc
    token = host.split(".")[0] if host.endswith(".substack.com") else host
    for n, d in graph.nodes(data=True):
        if d.get("label", "").lower().replace(" ", "") == token.lower():
            return n
    return None


# ---------------------------------------------------------------------------
# Episode 1 commands
# ---------------------------------------------------------------------------

def cmd_crawl(args: argparse.Namespace) -> int:
    config.ensure_dirs()
    cache = Cache(args.db)
    try:
        if getattr(args, "force", False):
            cache.conn.execute("DELETE FROM http_cache")
            cache.conn.commit()
            print("Cache cleared (--force).")
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


def cmd_validate(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    report = analytics.validate_graph(result.graph)
    if report["valid"]:
        print(f"PASS: {report['node_count']} nodes, {report['edge_count']} edges, "
              f"{report['isolated_nodes']} isolated. No issues found.")
    else:
        print(f"FAIL: {len(report['issues'])} issues found:")
        for issue in report["issues"]:
            print(f"  {issue}")
    return 0 if report["valid"] else 1


def cmd_load_demo(args: argparse.Namespace) -> int:
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
    try:
        import uvicorn
    except ImportError:
        print("The web extra is not installed. Run: pip install -e '.[web]'", file=sys.stderr)
        return 1
    uvicorn.run("substackgraph.web:app", host=args.host, port=args.port, reload=args.reload)
    return 0


# ---------------------------------------------------------------------------
# Episode 2 graph analytics commands
# ---------------------------------------------------------------------------

def cmd_reciprocity_gaps(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    gaps = analytics.reciprocity_gaps(result.graph)
    limit = getattr(args, "limit", 20)
    print(f"Reciprocity gaps ({len(gaps)} total, showing top {min(limit, len(gaps))}):\n")
    for g in gaps[:limit]:
        print(f"  {g['recommender_label']} → {g['target_label']}  "
              f"(target in-degree: {g['target_in_degree']})")
    return 0


def cmd_bridge_nodes(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    bridges = analytics.bridge_nodes(result.graph)
    if not bridges:
        print("No bridge nodes found (graph is already well-connected).")
        return 0
    print(f"Bridge nodes ({len(bridges)}):\n")
    for b in bridges:
        print(f"  {b['label']}  components_created={b['components_created']}  degree={b['degree']}")
    return 0


def cmd_warm_path(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    from_id = _pub_id_from_url(result.graph, args.from_url)
    to_id = _pub_id_from_url(result.graph, args.to)
    if from_id is None:
        print(f"Could not find publication: {args.from_url}", file=sys.stderr)
        return 1
    if to_id is None:
        print(f"Could not find publication: {args.to}", file=sys.stderr)
        return 1
    path = analytics.warm_path(result.graph, from_id, to_id)
    if path is None:
        print("No path found between these publications.")
        return 0
    print(f"Warm path ({len(path) - 1} hops):\n")
    for step in path:
        prefix = "→ " if step["step"] > 0 else "  "
        print(f"  {prefix}{step['label']}")
    return 0


def cmd_cluster_map(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    clusters = analytics.cluster_map(result.graph)
    print(f"Clusters ({len(clusters)}):\n")
    for c in clusters:
        print(f"  [{c['cluster_id']}] {c['label']}  (size: {c['size']})")
    return 0


def cmd_top_nodes(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    ranked = analytics.top_nodes(result.graph, metric=args.metric)
    limit = getattr(args, "limit", 20)
    print(f"Top nodes by {args.metric} ({len(ranked)} total, showing top {min(limit, len(ranked))}):\n")
    for i, r in enumerate(ranked[:limit], 1):
        print(f"  {i:3d}. {r['label']}  score={r['score']}  "
              f"in={r['in_degree']} out={r['out_degree']}")
    return 0


def cmd_overlap(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    pub_id = _pub_id_from_url(result.graph, args.pub)
    if pub_id is None:
        print(f"Could not find publication: {args.pub}", file=sys.stderr)
        return 1
    overlaps = analytics.audience_overlap(result.graph, pub_id)
    limit = getattr(args, "limit", 20)
    pub_label = result.graph.nodes[pub_id].get("label", str(pub_id))
    print(f"Audience overlap for {pub_label} (stub: graph distance proxy):\n")
    for o in overlaps[:limit]:
        print(f"  {o['label']}  overlap={o['overlap_score']}  distance={o['distance']}")
    return 0


def cmd_voice_compat(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    id_a = _pub_id_from_url(result.graph, args.pub_a)
    id_b = _pub_id_from_url(result.graph, args.pub_b)
    if id_a is None:
        print(f"Could not find publication: {args.pub_a}", file=sys.stderr)
        return 1
    if id_b is None:
        print(f"Could not find publication: {args.pub_b}", file=sys.stderr)
        return 1
    compat = analytics.voice_compatibility(result.graph, id_a, id_b)
    print(f"Voice compatibility (stub: keyword overlap):\n")
    print(f"  {compat['pub_a_label']} vs {compat['pub_b_label']}")
    print(f"  Score: {compat['score']}")
    print(f"  Shared keywords: {compat['shared_keywords']}")
    return 0


def cmd_blind_spots(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    report = analytics.blind_spots(result.graph, args.cluster)
    if "error" in report:
        print(f"Error: {report['error']}", file=sys.stderr)
        return 1
    print(f"Blind spots for cluster [{report['cluster_id']}] {report['cluster_label']}:\n")
    print(f"  Cluster topics: {', '.join(report['cluster_topics'][:15])}")
    print(f"  Potential gaps: {', '.join(report['potential_gaps'][:15])}")
    return 0


def cmd_journey_match(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    pub_id = _pub_id_from_url(result.graph, args.pub)
    if pub_id is None:
        print(f"Could not find publication: {args.pub}", file=sys.stderr)
        return 1
    match = analytics.journey_match(result.graph, pub_id)
    print(f"Journey match for {match['label']} (level: {match['level']}):\n")
    print(f"  Same-level peers:")
    for p in match["same_level_peers"]:
        print(f"    {p['label']}")
    return 0


def cmd_rising_stars(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    stars = analytics.rising_stars(result.graph)
    limit = getattr(args, "limit", 20)
    print(f"Rising stars ({len(stars)} total, showing top {min(limit, len(stars))}):\n")
    for s in stars[:limit]:
        print(f"  {s['label']}  centrality={s['in_degree_centrality']}  in_degree={s['in_degree']}")
    return 0


def cmd_surprise_matches(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    pub_id = _pub_id_from_url(result.graph, args.pub)
    if pub_id is None:
        print(f"Could not find publication: {args.pub}", file=sys.stderr)
        return 1
    matches = analytics.surprise_matches(result.graph, pub_id)
    pub_label = result.graph.nodes[pub_id].get("label", str(pub_id))
    print(f"Surprise matches for {pub_label} (stub: betweenness similarity):\n")
    for m in matches:
        print(f"  {m['label']}  similarity={m['structural_similarity']}  distance={m['distance']}")
    return 0


def cmd_live_hooks(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    pub_id = _pub_id_from_url(result.graph, args.pub)
    if pub_id is None:
        print(f"Could not find publication: {args.pub}", file=sys.stderr)
        return 1
    hooks = analytics.live_hooks(result.graph, pub_id)
    pub_label = result.graph.nodes[pub_id].get("label", str(pub_id))
    print(f"Live hooks for {pub_label} (stub: cluster proximity):\n")
    for h in hooks:
        print(f"  {h['label']}  cluster=[{h['cluster']}] {h['cluster_label'][:60]}")
    return 0


# ---------------------------------------------------------------------------
# Episode 3 stub commands
# ---------------------------------------------------------------------------

def cmd_collab_brief(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    id_a = _pub_id_from_url(result.graph, args.pub_a)
    id_b = _pub_id_from_url(result.graph, args.pub_b)
    if id_a is None:
        print(f"Could not find publication: {args.pub_a}", file=sys.stderr)
        return 1
    if id_b is None:
        print(f"Could not find publication: {args.pub_b}", file=sys.stderr)
        return 1
    brief = analytics.collab_brief(result.graph, id_a, id_b)
    print(brief["brief"])
    return 0


def cmd_outreach_angles(args: argparse.Namespace) -> int:
    result, cache = _resolve_graph(args.db)
    cache.close()
    id_a = _pub_id_from_url(result.graph, args.pub_a)
    id_b = _pub_id_from_url(result.graph, args.pub_b)
    if id_a is None:
        print(f"Could not find publication: {args.pub_a}", file=sys.stderr)
        return 1
    if id_b is None:
        print(f"Could not find publication: {args.pub_b}", file=sys.stderr)
        return 1
    result_data = analytics.outreach_angles(result.graph, id_a, id_b)
    print(f"Outreach angles: {result_data['pub_a']} → {result_data['pub_b']}\n")
    for i, angle in enumerate(result_data["angles"], 1):
        print(f"  {i}. [{angle['angle']}]")
        print(f"     {angle['pitch']}\n")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="substackgraph", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    # Episode 1 commands
    p_crawl = sub.add_parser("crawl", help="crawl the recommendation neighborhood (cache-first)")
    p_crawl.add_argument("--seed", required=True, help="seed publication URL")
    p_crawl.add_argument("--hops", type=int, default=2, help="crawl depth (default 2)")
    p_crawl.add_argument("--force", action="store_true", help="clear the cache before crawling")
    _add_db_arg(p_crawl)
    p_crawl.set_defaults(func=cmd_crawl)

    p_naive = sub.add_parser("render-naive", help="render the corrupted 'before' graph")
    _add_db_arg(p_naive)
    p_naive.set_defaults(func=cmd_render_naive)

    p_res = sub.add_parser("render-resolved", help="run the harness and render the resolved graph")
    _add_db_arg(p_res)
    p_res.set_defaults(func=cmd_render_resolved)

    p_val = sub.add_parser("validate", help="sanity-check the resolved graph")
    _add_db_arg(p_val)
    p_val.set_defaults(func=cmd_validate)

    p_demo = sub.add_parser("load-demo", help="load the bundled demo neighborhood into the cache")
    p_demo.add_argument("--path", default=str(DEMO_FIXTURE), help="fixture JSON path")
    _add_db_arg(p_demo)
    p_demo.set_defaults(func=cmd_load_demo)

    p_serve = sub.add_parser("serve", help="run the live web app")
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--reload", action="store_true", help="auto-reload (development)")
    p_serve.set_defaults(func=cmd_serve)

    # Episode 2 graph analytics commands
    p_rg = sub.add_parser("reciprocity-gaps", help="A->B edges with no B->A")
    p_rg.add_argument("--limit", type=int, default=20)
    _add_db_arg(p_rg)
    p_rg.set_defaults(func=cmd_reciprocity_gaps)

    p_bn = sub.add_parser("bridge-nodes", help="publications connecting two clusters")
    _add_db_arg(p_bn)
    p_bn.set_defaults(func=cmd_bridge_nodes)

    p_wp = sub.add_parser("warm-path", help="shortest route between two publications")
    p_wp.add_argument("--from", required=True, dest="from_url", help="source publication URL")
    p_wp.add_argument("--to", required=True, help="target publication URL")
    _add_db_arg(p_wp)
    p_wp.set_defaults(func=cmd_warm_path)

    p_cm = sub.add_parser("cluster-map", help="community detection with labels")
    _add_db_arg(p_cm)
    p_cm.set_defaults(func=cmd_cluster_map)

    p_tn = sub.add_parser("top-nodes", help="ranked list by centrality metric")
    p_tn.add_argument("--metric", default="degree",
                      choices=["degree", "in_degree", "out_degree", "betweenness"])
    p_tn.add_argument("--limit", type=int, default=20)
    _add_db_arg(p_tn)
    p_tn.set_defaults(func=cmd_top_nodes)

    p_ol = sub.add_parser("overlap", help="audience overlap scoring (stub)")
    p_ol.add_argument("--pub", required=True, help="publication URL")
    p_ol.add_argument("--limit", type=int, default=20)
    _add_db_arg(p_ol)
    p_ol.set_defaults(func=cmd_overlap)

    p_vc = sub.add_parser("voice-compat", help="voice compatibility scoring (stub)")
    p_vc.add_argument("--pub-a", required=True, help="first publication URL")
    p_vc.add_argument("--pub-b", required=True, help="second publication URL")
    _add_db_arg(p_vc)
    p_vc.set_defaults(func=cmd_voice_compat)

    p_bs = sub.add_parser("blind-spots", help="niche blind spot detection (stub)")
    p_bs.add_argument("--cluster", type=int, required=True, help="cluster ID")
    _add_db_arg(p_bs)
    p_bs.set_defaults(func=cmd_blind_spots)

    p_jm = sub.add_parser("journey-match", help="audience journey matching (stub)")
    p_jm.add_argument("--pub", required=True, help="publication URL")
    _add_db_arg(p_jm)
    p_jm.set_defaults(func=cmd_journey_match)

    p_rs = sub.add_parser("rising-stars", help="early velocity signal (stub)")
    p_rs.add_argument("--limit", type=int, default=20)
    _add_db_arg(p_rs)
    p_rs.set_defaults(func=cmd_rising_stars)

    p_sm = sub.add_parser("surprise-matches", help="counter-intuitive match finder (stub)")
    p_sm.add_argument("--pub", required=True, help="publication URL")
    _add_db_arg(p_sm)
    p_sm.set_defaults(func=cmd_surprise_matches)

    p_lh = sub.add_parser("live-hooks", help="timing/trigger detection (stub)")
    p_lh.add_argument("--pub", required=True, help="publication URL")
    _add_db_arg(p_lh)
    p_lh.set_defaults(func=cmd_live_hooks)

    # Episode 3 stub commands
    p_cb = sub.add_parser("collab-brief", help="collaboration brief generator (stub)")
    p_cb.add_argument("--pub-a", required=True, help="first publication URL")
    p_cb.add_argument("--pub-b", required=True, help="second publication URL")
    _add_db_arg(p_cb)
    p_cb.set_defaults(func=cmd_collab_brief)

    p_oa = sub.add_parser("outreach-angles", help="outreach angle suggestions (stub)")
    p_oa.add_argument("--pub-a", required=True, help="first publication URL")
    p_oa.add_argument("--pub-b", required=True, help="second publication URL")
    _add_db_arg(p_oa)
    p_oa.set_defaults(func=cmd_outreach_angles)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
