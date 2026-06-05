"""The deliberately-corrupted graph (the "before"). It reproduces the four failure modes
not by injecting bugs but by doing what a careless first cut does: keying every node on a
surface string instead of its canonical publication id.

Naive key = custom_domain → subdomain → author:<id> → name. That single bad rule yields:
  1. one publication as 2-3 nodes (different surfaces resolve to different keys),
  2. two newsletters collapsing into one (the author-id fallback merges by shared author),
  3. renamed handles 404 → their edges are silently dropped (no node to attach to),
  4. self-loops where a publication recommends an alias of itself.
"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

from .model import RawEdge, RawNode


def naive_key(meta: dict) -> str:
    """What a first implementation reaches for, in order — none of which is the canonical id."""
    if meta.get("custom_domain"):
        return str(meta["custom_domain"])
    if meta.get("subdomain"):
        return str(meta["subdomain"])
    if meta.get("author_id") is not None:
        return f"author:{meta['author_id']}"  # the wrong fallback that collapses mode 2
    if meta.get("name"):
        return str(meta["name"])
    return "<unknown>"


@dataclass
class NaiveStats:
    node_count: int
    edge_count: int
    dropped_edges: int
    self_loops: int


def build_naive(raw_nodes: list[RawNode], raw_edges: list[RawEdge]) -> tuple[nx.DiGraph, NaiveStats]:
    g = nx.DiGraph()
    url_key: dict[str, str] = {}
    members: dict[str, set[str]] = {}
    ids_seen: dict[str, set[int]] = {}

    for node in raw_nodes:
        if node.status != "ok":
            continue
        key = naive_key(node.meta)
        url_key[node.url] = key
        members.setdefault(key, set()).add(node.url)
        if node.meta.get("id") is not None:
            ids_seen.setdefault(key, set()).add(int(node.meta["id"]))
        g.add_node(key)

    dropped = 0
    self_loops = 0
    for edge in raw_edges:
        sk = url_key.get(edge.src_url)
        dk = url_key.get(edge.dst_url)
        if sk is None or dk is None:
            dropped += 1  # mode 3: the dst 404'd, so the edge vanishes
            continue
        if sk == dk:
            self_loops += 1  # mode 4: a publication points at an alias of itself
        g.add_edge(sk, dk)

    for key in g.nodes:
        g.nodes[key]["label"] = key
        g.nodes[key]["member_urls"] = sorted(members.get(key, set()))
        g.nodes[key]["ids_seen"] = sorted(ids_seen.get(key, set()))

    stats = NaiveStats(
        node_count=g.number_of_nodes(),
        edge_count=g.number_of_edges(),
        dropped_edges=dropped,
        self_loops=self_loops,
    )
    return g, stats
