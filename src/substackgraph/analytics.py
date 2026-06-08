"""Graph analytics for Episode 2+. Pure graph math where possible; stubs marked TODO
for real LLM/embedding integration.

All functions take a networkx DiGraph (the resolved graph from resolve.py) and return
structured results suitable for CLI display.
"""

from __future__ import annotations

from collections import defaultdict

import networkx as nx


# ---------------------------------------------------------------------------
# E2-01: Reciprocity gap finder
# ---------------------------------------------------------------------------

def reciprocity_gaps(graph: nx.DiGraph) -> list[dict]:
    """A->B edges with no B->A, ranked by B's in-degree (proxy for audience size)."""
    gaps = []
    for u, v in graph.edges():
        if not graph.has_edge(v, u):
            gaps.append({
                "recommender": u,
                "recommender_label": graph.nodes[u].get("label", str(u)),
                "target": v,
                "target_label": graph.nodes[v].get("label", str(v)),
                "target_in_degree": graph.in_degree(v),
            })
    gaps.sort(key=lambda g: g["target_in_degree"], reverse=True)
    return gaps


# ---------------------------------------------------------------------------
# E2-02: Bridge node discovery
# ---------------------------------------------------------------------------

def bridge_nodes(graph: nx.DiGraph) -> list[dict]:
    """Publications connecting two or more communities (based on weakly connected components
    of the undirected projection minus the candidate node)."""
    results = []
    undirected = graph.to_undirected()
    for node in graph.nodes():
        test = undirected.copy()
        test.remove_node(node)
        components_after = nx.number_connected_components(test)
        if components_after > 1:
            results.append({
                "node": node,
                "label": graph.nodes[node].get("label", str(node)),
                "components_created": components_after,
                "degree": graph.degree(node),
            })
    results.sort(key=lambda r: r["components_created"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# E2-03: Warm path finder
# ---------------------------------------------------------------------------

def warm_path(graph: nx.DiGraph, from_id: int, to_id: int) -> list[dict] | None:
    """Shortest path between two nodes, returning the intermediaries."""
    undirected = graph.to_undirected()
    try:
        path = nx.shortest_path(undirected, from_id, to_id)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    return [
        {"node": n, "label": graph.nodes[n].get("label", str(n)), "step": i}
        for i, n in enumerate(path)
    ]


# ---------------------------------------------------------------------------
# E2-04: Cluster map + LLM labels
# ---------------------------------------------------------------------------

def cluster_map(graph: nx.DiGraph) -> list[dict]:
    """Community detection using greedy modularity on the undirected projection.
    Cluster labels are placeholder (top publication names). TODO: real LLM labeling."""
    undirected = graph.to_undirected()
    if undirected.number_of_nodes() == 0:
        return []
    communities = list(nx.community.greedy_modularity_communities(undirected))
    results = []
    for i, community in enumerate(communities):
        members = sorted(community)
        names = [graph.nodes[n].get("label", str(n)) for n in members]
        # Stub: label from top 3 names. TODO: LLM label generation
        label = " / ".join(names[:3])
        if len(names) > 3:
            label += f" (+{len(names) - 3} more)"
        results.append({
            "cluster_id": i,
            "label": label,
            "size": len(members),
            "members": members,
            "member_names": names,
        })
    results.sort(key=lambda r: r["size"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# E2-05: Degree centrality ranking
# ---------------------------------------------------------------------------

def top_nodes(graph: nx.DiGraph, metric: str = "degree") -> list[dict]:
    """Ranked list of nodes by centrality metric."""
    if metric == "degree":
        scores = nx.degree_centrality(graph)
    elif metric == "in_degree":
        scores = nx.in_degree_centrality(graph)
    elif metric == "out_degree":
        scores = nx.out_degree_centrality(graph)
    elif metric == "betweenness":
        scores = nx.betweenness_centrality(graph)
    else:
        scores = nx.degree_centrality(graph)
    ranked = [
        {
            "node": n,
            "label": graph.nodes[n].get("label", str(n)),
            "score": round(s, 4),
            "in_degree": graph.in_degree(n),
            "out_degree": graph.out_degree(n),
        }
        for n, s in scores.items()
    ]
    ranked.sort(key=lambda r: r["score"], reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# E2-06: Audience overlap scoring (stub — graph distance proxy)
# ---------------------------------------------------------------------------

def audience_overlap(graph: nx.DiGraph, pub_id: int) -> list[dict]:
    """Stub: uses graph distance as proxy for audience overlap. Closer = higher overlap.
    TODO: replace with embedding-based complementary overlap scoring."""
    undirected = graph.to_undirected()
    if pub_id not in undirected:
        return []
    try:
        distances = nx.single_source_shortest_path_length(undirected, pub_id)
    except nx.NodeNotFound:
        return []
    results = []
    for node, dist in distances.items():
        if node == pub_id:
            continue
        overlap_score = round(1.0 / (1.0 + dist), 4)
        results.append({
            "node": node,
            "label": graph.nodes[node].get("label", str(node)),
            "distance": dist,
            "overlap_score": overlap_score,
        })
    results.sort(key=lambda r: r["overlap_score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# E2-07: Voice compatibility scoring (stub — keyword overlap proxy)
# ---------------------------------------------------------------------------

def voice_compatibility(graph: nx.DiGraph, pub_a: int, pub_b: int,
                        cache=None) -> dict:
    """Stub: uses keyword overlap from publication names as proxy.
    TODO: fetch post titles from cache and use real LLM for tonal fit scoring."""
    label_a = graph.nodes.get(pub_a, {}).get("label", "")
    label_b = graph.nodes.get(pub_b, {}).get("label", "")
    words_a = set(label_a.lower().split())
    words_b = set(label_b.lower().split())
    union = words_a | words_b
    if not union:
        return {"score": 0.0, "method": "stub_keyword_overlap"}
    overlap = len(words_a & words_b) / len(union)
    return {
        "pub_a": pub_a,
        "pub_a_label": label_a,
        "pub_b": pub_b,
        "pub_b_label": label_b,
        "score": round(overlap, 4),
        "shared_keywords": sorted(words_a & words_b),
        "method": "stub_keyword_overlap",
    }


# ---------------------------------------------------------------------------
# E2-08: Recommendation quality scoring (stub — degree-based edge weight)
# ---------------------------------------------------------------------------

def recommendation_quality(graph: nx.DiGraph) -> list[dict]:
    """Stub: scores edge strength by out-degree of the recommending node (more selective
    recommenders = higher quality signal). TODO: LLM reads recommendation text for warmth.
    Returns edges with quality scores suitable for rendering as edge weights."""
    max_out = max((graph.out_degree(n) for n in graph.nodes()), default=1) or 1
    results = []
    for u, v in graph.edges():
        out_deg = graph.out_degree(u)
        quality = round(1.0 - (out_deg / max_out), 4)
        results.append({
            "src": u,
            "src_label": graph.nodes[u].get("label", str(u)),
            "dst": v,
            "dst_label": graph.nodes[v].get("label", str(v)),
            "quality_score": quality,
            "recommender_out_degree": out_deg,
        })
    results.sort(key=lambda r: r["quality_score"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# E2-09: Niche blind spot detection (stub — name-based topic inference)
# ---------------------------------------------------------------------------

def blind_spots(graph: nx.DiGraph, cluster_id: int) -> dict:
    """Stub: infers topics from publication names within a cluster and finds gaps
    by comparing to the full network. TODO: real LLM topic extraction."""
    clusters = cluster_map(graph)
    if cluster_id >= len(clusters):
        return {"error": f"cluster {cluster_id} not found", "clusters_available": len(clusters)}
    cluster = clusters[cluster_id]
    cluster_words = set()
    for name in cluster["member_names"]:
        cluster_words.update(w.lower() for w in name.split() if len(w) > 3)
    all_words = set()
    for n, d in graph.nodes(data=True):
        for w in d.get("label", "").split():
            if len(w) > 3:
                all_words.add(w.lower())
    missing = sorted(all_words - cluster_words)
    return {
        "cluster_id": cluster_id,
        "cluster_label": cluster["label"],
        "cluster_topics": sorted(cluster_words),
        "potential_gaps": missing[:20],
        "method": "stub_name_keywords",
    }


# ---------------------------------------------------------------------------
# E2-10: Audience journey matching (stub — name heuristic classifier)
# ---------------------------------------------------------------------------

def journey_match(graph: nx.DiGraph, pub_id: int) -> dict:
    """Stub: classifies beginner/intermediate/expert by name heuristics.
    TODO: real LLM classification from post content."""
    label = graph.nodes.get(pub_id, {}).get("label", "")
    lower = label.lower()
    beginner_signals = ["intro", "beginner", "101", "basics", "starter", "guide"]
    expert_signals = ["advanced", "deep", "research", "paper", "arxiv", "frontier"]
    level = "intermediate"
    if any(s in lower for s in beginner_signals):
        level = "beginner"
    elif any(s in lower for s in expert_signals):
        level = "expert"
    # Find peers at same level
    peers = []
    for n, d in graph.nodes(data=True):
        if n == pub_id:
            continue
        n_label = d.get("label", "").lower()
        n_level = "intermediate"
        if any(s in n_label for s in beginner_signals):
            n_level = "beginner"
        elif any(s in n_label for s in expert_signals):
            n_level = "expert"
        if n_level == level:
            peers.append({"node": n, "label": d.get("label", str(n))})
    return {
        "pub_id": pub_id,
        "label": label,
        "level": level,
        "same_level_peers": peers[:10],
        "method": "stub_name_heuristic",
    }


# ---------------------------------------------------------------------------
# E2-11: Early velocity signal (rising stars)
# ---------------------------------------------------------------------------

def rising_stars(graph: nx.DiGraph) -> list[dict]:
    """Flag publications with high in-degree centrality relative to estimated audience.
    TODO: replace with real subscriber data when available. Currently uses raw in-degree
    as a proxy, flagging those with above-median centrality."""
    in_cent = nx.in_degree_centrality(graph)
    if not in_cent:
        return []
    vals = sorted(in_cent.values())
    median = vals[len(vals) // 2]
    results = []
    for n, score in in_cent.items():
        if score > median and score > 0:
            results.append({
                "node": n,
                "label": graph.nodes[n].get("label", str(n)),
                "in_degree_centrality": round(score, 4),
                "in_degree": graph.in_degree(n),
                "method": "stub_degree_proxy",
            })
    results.sort(key=lambda r: r["in_degree_centrality"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# E2-12: Counter-intuitive match finder (surprise matches)
# ---------------------------------------------------------------------------

def surprise_matches(graph: nx.DiGraph, pub_id: int) -> list[dict]:
    """Find publications 2+ hops away that share structural graph patterns (same
    bridging role, same cluster boundary position). TODO: use embeddings for real
    similarity scoring."""
    undirected = graph.to_undirected()
    if pub_id not in undirected:
        return []
    betweenness = nx.betweenness_centrality(undirected)
    pub_bc = betweenness.get(pub_id, 0)
    try:
        distances = nx.single_source_shortest_path_length(undirected, pub_id)
    except nx.NodeNotFound:
        return []
    results = []
    for node, dist in distances.items():
        if dist < 2 or node == pub_id:
            continue
        node_bc = betweenness.get(node, 0)
        if pub_bc == 0 and node_bc == 0:
            continue
        bc_diff = abs(pub_bc - node_bc)
        similarity = round(1.0 / (1.0 + bc_diff * 100), 4)
        if similarity > 0.3:
            results.append({
                "node": node,
                "label": graph.nodes[node].get("label", str(node)),
                "distance": dist,
                "structural_similarity": similarity,
                "your_betweenness": round(pub_bc, 4),
                "their_betweenness": round(node_bc, 4),
                "method": "stub_betweenness_similarity",
            })
    results.sort(key=lambda r: r["structural_similarity"], reverse=True)
    return results[:10]


# ---------------------------------------------------------------------------
# E2-13: Timing/trigger detection (live hooks)
# ---------------------------------------------------------------------------

def live_hooks(graph: nx.DiGraph, pub_id: int) -> list[dict]:
    """Stub: detects publications in the same cluster that could be timely collaboration
    targets. TODO: fetch actual publication dates and detect 2-week overlap windows."""
    clusters = cluster_map(graph)
    pub_cluster = None
    for c in clusters:
        if pub_id in c["members"]:
            pub_cluster = c
            break
    if pub_cluster is None:
        return []
    results = []
    for member in pub_cluster["members"]:
        if member == pub_id:
            continue
        results.append({
            "node": member,
            "label": graph.nodes[member].get("label", str(member)),
            "cluster": pub_cluster["cluster_id"],
            "cluster_label": pub_cluster["label"],
            "hook": "same_cluster_member",
            "method": "stub_cluster_proximity",
        })
    return results[:10]


# ---------------------------------------------------------------------------
# E3-01: Collaboration brief generator (LLM-powered)
# ---------------------------------------------------------------------------

def _pub_description_from_cache(graph: nx.DiGraph, pub_id: int, cache=None) -> str:
    """Best-effort description from cached metadata. Returns empty string if unavailable."""
    if cache is None:
        return ""
    # Try to find cached metadata for this publication's URLs
    node_data = graph.nodes.get(pub_id, {})
    member_urls = node_data.get("member_urls", [])
    parts = []
    for url in member_urls:
        row = cache.get(f"meta:{url}")
        if row and row.status == "ok" and isinstance(row.payload, dict):
            meta = row.payload
            if meta.get("description"):
                parts.append(meta["description"])
            if meta.get("name") and meta["name"] not in parts:
                parts.append(meta["name"])
            break  # One good metadata hit is enough
    return " | ".join(parts) if parts else ""


def _shared_recommenders(graph: nx.DiGraph, pub_a: int, pub_b: int) -> list[str]:
    """Find publications that recommend both pub_a and pub_b."""
    preds_a = set(graph.predecessors(pub_a))
    preds_b = set(graph.predecessors(pub_b))
    shared = preds_a & preds_b
    return [graph.nodes[n].get("label", str(n)) for n in shared]


def collab_brief(graph: nx.DiGraph, pub_a: int, pub_b: int, cache=None) -> dict:
    """Generate a collaboration brief using LLM (or stub fallback)."""
    from . import llm

    label_a = graph.nodes.get(pub_a, {}).get("label", str(pub_a))
    label_b = graph.nodes.get(pub_b, {}).get("label", str(pub_b))
    clusters = cluster_map(graph)
    cluster_a = cluster_b = None
    for c in clusters:
        if pub_a in c["members"]:
            cluster_a = c["label"]
        if pub_b in c["members"]:
            cluster_b = c["label"]

    desc_a = _pub_description_from_cache(graph, pub_a, cache)
    desc_b = _pub_description_from_cache(graph, pub_b, cache)
    shared = _shared_recommenders(graph, pub_a, pub_b)

    # Compute overlap score
    overlaps = audience_overlap(graph, pub_a)
    overlap_score = 0.0
    for o in overlaps:
        if o["node"] == pub_b:
            overlap_score = o["overlap_score"]
            break

    result = llm.generate_collab_brief(
        pub_a_name=label_a,
        pub_b_name=label_b,
        pub_a_desc=desc_a,
        pub_b_desc=desc_b,
        cluster_a=cluster_a,
        cluster_b=cluster_b,
        shared_recommenders=shared,
        overlap_score=overlap_score,
    )
    result["pub_a"] = label_a
    result["pub_b"] = label_b
    result["cluster_a"] = cluster_a
    result["cluster_b"] = cluster_b
    return result


# ---------------------------------------------------------------------------
# E3-02: Outreach angle suggestions (LLM-powered)
# ---------------------------------------------------------------------------

def outreach_angles(graph: nx.DiGraph, pub_a: int, pub_b: int, cache=None) -> dict:
    """Generate 3 outreach angles using LLM (or stub fallback)."""
    from . import llm

    label_a = graph.nodes.get(pub_a, {}).get("label", str(pub_a))
    label_b = graph.nodes.get(pub_b, {}).get("label", str(pub_b))

    desc_a = _pub_description_from_cache(graph, pub_a, cache)
    desc_b = _pub_description_from_cache(graph, pub_b, cache)

    # Get warm path labels
    wp = warm_path(graph, pub_a, pub_b)
    wp_labels = [step["label"] for step in wp] if wp else []

    # Get voice compat score
    vc = voice_compatibility(graph, pub_a, pub_b)
    vc_score = vc.get("score", 0.0)

    result = llm.generate_outreach_angles(
        pub_a_name=label_a,
        pub_b_name=label_b,
        pub_a_desc=desc_a,
        pub_b_desc=desc_b,
        warm_path=wp_labels,
        voice_compat_score=vc_score,
    )
    result["pub_a"] = label_a
    result["pub_b"] = label_b
    return result


# ---------------------------------------------------------------------------
# Graph validation (E1-06)
# ---------------------------------------------------------------------------

def validate_graph(graph: nx.DiGraph) -> dict:
    """Sanity check the resolved graph: no URL-keyed nodes, no orphan edges, no self-loops."""
    issues = []
    # Check for URL-keyed nodes (should all be int canonical IDs)
    url_keyed = [n for n in graph.nodes() if isinstance(n, str) and n.startswith("http")]
    if url_keyed:
        issues.append({"type": "url_keyed_node", "count": len(url_keyed), "examples": url_keyed[:5]})
    # Check for self-loops
    self_loops = list(nx.selfloop_edges(graph))
    if self_loops:
        issues.append({"type": "self_loop", "count": len(self_loops), "examples": self_loops[:5]})
    # Check for orphan edges (edges to/from nodes not in the graph)
    for u, v in graph.edges():
        if u not in graph.nodes():
            issues.append({"type": "orphan_edge_src", "edge": (u, v)})
        if v not in graph.nodes():
            issues.append({"type": "orphan_edge_dst", "edge": (u, v)})
    # Check for isolated nodes (no edges at all)
    isolated = list(nx.isolates(graph))
    return {
        "valid": len(issues) == 0,
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "isolated_nodes": len(isolated),
        "issues": issues,
    }
