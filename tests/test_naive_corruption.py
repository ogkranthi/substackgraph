"""Proves the four failure modes are REAL in the naive graph (locks in the 'before')."""

from __future__ import annotations

from substackgraph.naive_graph import build_naive


def test_mode1_one_publication_splits_into_multiple_nodes(raw_graph):
    nodes, edges = raw_graph
    g, _ = build_naive(nodes, edges)
    # Publication id 101 (Import AI) is reached via subdomain, custom domain, and author profile.
    keys_with_101 = [n for n, d in g.nodes(data=True) if 101 in d.get("ids_seen", [])]
    assert len(keys_with_101) == 3


def test_mode2_two_publications_collapse_into_one_node(raw_graph):
    nodes, edges = raw_graph
    g, _ = build_naive(nodes, edges)
    # The author-id fallback merges two distinct publications (201, 202) into one node.
    collapsed = [n for n, d in g.nodes(data=True) if len(d.get("ids_seen", [])) > 1]
    assert collapsed, "expected at least one naive node carrying >1 distinct publication id"
    assert {201, 202} <= set(g.nodes[collapsed[0]]["ids_seen"])


def test_mode3_renamed_handle_drops_its_edge(raw_graph):
    nodes, edges = raw_graph
    _, stats = build_naive(nodes, edges)
    # The 404'd old handle has no node, so the edge pointing at it silently vanishes.
    assert stats.dropped_edges >= 1


def test_mode4_alias_self_recommendation_makes_a_self_loop(raw_graph):
    nodes, edges = raw_graph
    g, stats = build_naive(nodes, edges)
    assert stats.self_loops >= 1
    assert any(g.has_edge(n, n) for n in g.nodes)
