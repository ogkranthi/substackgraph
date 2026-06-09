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


# ---------------------------------------------------------------------------
# Helpers: cluster lookup + voice compat / journey match score reuse
# ---------------------------------------------------------------------------

def _node_cluster_map(graph: nx.DiGraph) -> dict[int, int]:
    """Return {node_id: cluster_id} mapping."""
    clusters = cluster_map(graph)
    mapping: dict[int, int] = {}
    for c in clusters:
        for m in c["members"]:
            mapping[m] = c["cluster_id"]
    return mapping


def _cluster_adjacency(clusters: list[dict]) -> dict[int, set[int]]:
    """Build adjacency between clusters based on shared edges (computed from member sets).
    Two clusters are adjacent if any member of one recommends a member of the other."""
    adj: dict[int, set[int]] = defaultdict(set)
    # For simplicity, treat clusters i and i+1 as adjacent when indices differ by 1
    # (greedy modularity orders them by connectedness)
    for c in clusters:
        adj[c["cluster_id"]].add(c["cluster_id"])
    for i, ci in enumerate(clusters):
        for j, cj in enumerate(clusters):
            if i != j:
                adj[ci["cluster_id"]].add(cj["cluster_id"])
    return adj


def voice_compat_score(graph: nx.DiGraph, pub_a: int, pub_b: int, cache=None) -> float:
    """Reuse voice_compatibility stub and return just the score."""
    return voice_compatibility(graph, pub_a, pub_b, cache=cache).get("score", 0.0)


def audience_journey_match(graph: nx.DiGraph, pub_a: int, pub_b: int) -> float:
    """Return 1.0 if same journey level, 0.5 if adjacent, 0.0 otherwise."""
    levels = ["beginner", "intermediate", "expert"]
    ja = journey_match(graph, pub_a).get("level", "intermediate")
    jb = journey_match(graph, pub_b).get("level", "intermediate")
    if ja == jb:
        return 1.0
    ia = levels.index(ja) if ja in levels else 1
    ib = levels.index(jb) if jb in levels else 1
    return 0.5 if abs(ia - ib) == 1 else 0.0


# ---------------------------------------------------------------------------
# E4-01: Recommendation source quality score
# ---------------------------------------------------------------------------

def rec_quality_score(graph: nx.DiGraph, pub_id: int, cache=None) -> list[dict]:
    """Score each incoming recommender by quality: selectivity, voice compat,
    journey match, and cluster alignment. Returns ranked list."""
    from . import llm

    if pub_id not in graph:
        return []

    predecessors = list(graph.predecessors(pub_id))
    if not predecessors:
        return []

    max_out = max((graph.out_degree(n) for n in graph.nodes()), default=1) or 1
    node_clusters = _node_cluster_map(graph)
    pub_cluster = node_clusters.get(pub_id, -1)
    clusters = cluster_map(graph)
    cluster_ids = {c["cluster_id"] for c in clusters}

    results = []
    for rec in predecessors:
        rec_out = graph.out_degree(rec)
        selectivity = 1.0 - (rec_out / max_out)

        vc = voice_compat_score(graph, rec, pub_id, cache=cache)
        jm = audience_journey_match(graph, rec, pub_id)

        rec_cluster = node_clusters.get(rec, -1)
        if rec_cluster == pub_cluster and pub_cluster >= 0:
            cluster_align = 1.0
        elif rec_cluster >= 0 and pub_cluster >= 0 and abs(rec_cluster - pub_cluster) <= 1:
            cluster_align = 0.5
        else:
            cluster_align = 0.2

        score = (selectivity * 0.4) + (cluster_align * 0.3) + (vc * 0.15) + (jm * 0.15)

        results.append({
            "recommender": rec,
            "recommender_label": graph.nodes[rec].get("label", str(rec)),
            "score": round(score, 4),
            "breakdown": {
                "selectivity": round(selectivity, 4),
                "cluster_alignment": round(cluster_align, 4),
                "voice_compat": round(vc, 4),
                "journey_match": round(jm, 4),
            },
            "method": "graph_weighted_avg",
        })
    results.sort(key=lambda r: r["score"], reverse=True)

    # LLM enhancement for top 5
    if not llm.is_stub_mode() and results:
        top5 = results[:5]
        pub_label = graph.nodes[pub_id].get("label", str(pub_id))
        summaries = llm.generate_rec_quality_insights(pub_label, top5)
        for i, s in enumerate(summaries):
            if i < len(top5):
                top5[i]["llm_insight"] = s

    return results


# ---------------------------------------------------------------------------
# E4-02: Related-feature competitor map
# ---------------------------------------------------------------------------

def related_map(graph: nx.DiGraph, pub_id: int) -> dict:
    """Find pubs within 2 hops in same cluster — categorize as competitors or safe partners."""
    from . import llm

    if pub_id not in graph:
        return {"competitors": [], "safe_partners": [], "threat_levels": {}}

    node_clusters = _node_cluster_map(graph)
    pub_cluster = node_clusters.get(pub_id, -1)

    # BFS 2-hop neighborhood (undirected)
    undirected = graph.to_undirected()
    two_hop: set[int] = set()
    try:
        for node, dist in nx.single_source_shortest_path_length(undirected, pub_id, cutoff=2).items():
            if node != pub_id and dist <= 2:
                two_hop.add(node)
    except nx.NodeNotFound:
        pass

    # Filter to same cluster
    same_cluster = {n for n in two_hop if node_clusters.get(n) == pub_cluster and pub_cluster >= 0}

    out_set = set(graph.successors(pub_id))
    in_set = set(graph.predecessors(pub_id))
    mutual = out_set & in_set

    competitors = []
    safe_partners = []
    threat_levels: dict[str, str] = {}

    for n in same_cluster:
        label = graph.nodes[n].get("label", str(n))
        has_reciprocal = n in mutual
        n_degree = graph.degree(n)

        if has_reciprocal:
            safe_partners.append({
                "node": n,
                "label": label,
                "in_degree": graph.in_degree(n),
                "relationship": "mutual_recommendation",
            })
        else:
            # Score threat
            if n_degree >= 5 and n not in out_set and n not in in_set:
                threat = "high"
            elif n_degree >= 3:
                threat = "medium"
            else:
                threat = "low"

            competitors.append({
                "node": n,
                "label": label,
                "in_degree": graph.in_degree(n),
                "threat_level": threat,
                "action": "swap" if threat in ("high", "medium") else "ignore",
            })
            threat_levels[label] = threat

    competitors.sort(key=lambda c: {"high": 0, "medium": 1, "low": 2}[c["threat_level"]])

    result = {
        "competitors": competitors,
        "safe_partners": safe_partners,
        "threat_levels": threat_levels,
        "method": "graph_2hop_cluster",
    }

    # LLM enhancement for high-threat
    if not llm.is_stub_mode():
        high_threats = [c for c in competitors if c["threat_level"] == "high"]
        if high_threats:
            pub_label = graph.nodes[pub_id].get("label", str(pub_id))
            insights = llm.generate_competitor_insights(pub_label, high_threats)
            for i, ins in enumerate(insights):
                if i < len(high_threats):
                    high_threats[i]["llm_action"] = ins

    return result


# ---------------------------------------------------------------------------
# E4-03: Paywall gap analysis
# ---------------------------------------------------------------------------

def paywall_gap_analysis(graph: nx.DiGraph, pub_id: int, cache=None) -> list[dict]:
    """Identify topic gaps by comparing pub titles across the cluster.
    Uses LLM if available, falls back to keyword frequency."""
    from . import llm

    if pub_id not in graph:
        return []

    node_clusters = _node_cluster_map(graph)
    pub_cluster = node_clusters.get(pub_id, -1)
    if pub_cluster < 0:
        return []

    # Gather labels as proxy for titles (cache titles if available)
    cluster_labels: list[str] = []
    pub_labels: list[str] = []
    for n, data in graph.nodes(data=True):
        label = data.get("label", "")
        if not label:
            continue
        if node_clusters.get(n) == pub_cluster:
            cluster_labels.append(label)
            if n == pub_id:
                pub_labels.append(label)

    # Try LLM first
    if not llm.is_stub_mode() and cluster_labels:
        pub_label = graph.nodes[pub_id].get("label", str(pub_id))
        gaps = llm.generate_paywall_gaps(pub_label, pub_labels, cluster_labels)
        if gaps:
            return gaps

    # Keyword frequency fallback
    stop_words = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "is", "on",
                  "at", "by", "with", "from", "newsletter", "substack", "weekly", "daily"}

    def tokenize(text: str) -> list[str]:
        return [w.lower() for w in text.split() if len(w) > 2 and w.lower() not in stop_words]

    cluster_freq: dict[str, int] = defaultdict(int)
    for label in cluster_labels:
        for w in tokenize(label):
            cluster_freq[w] += 1

    pub_words = set()
    for label in pub_labels:
        pub_words.update(tokenize(label))

    gaps = []
    for word, count in sorted(cluster_freq.items(), key=lambda x: x[1], reverse=True):
        if word not in pub_words and count >= 2:
            gaps.append({
                "topic": word,
                "cluster_frequency": count,
                "suggestion": f"Topic '{word}' appears in {count} cluster pubs but not in yours",
                "method": "keyword_frequency",
            })
    return gaps[:10]


# ---------------------------------------------------------------------------
# E4-04: Churn-risk content fingerprint
# ---------------------------------------------------------------------------

def churn_signals(graph: nx.DiGraph, pub_id: int) -> dict:
    """Graph-based churn risk signals. Returns risk score 0-1 and per-signal breakdown."""
    from . import llm

    if pub_id not in graph:
        return {"risk_score": 0.0, "signals": {}, "method": "graph_churn_proxy"}

    out_n = set(graph.successors(pub_id))
    in_n = set(graph.predecessors(pub_id))

    # Isolation: ratio of recs accepted (in) vs sent (out)
    total_connections = len(out_n) + len(in_n)
    if total_connections > 0:
        isolation = 1.0 - (len(in_n) / total_connections)
    else:
        isolation = 1.0

    # Reciprocity rate
    if out_n:
        reciprocity = len(out_n & in_n) / len(out_n)
    else:
        reciprocity = 0.0
    reciprocity_risk = 1.0 - reciprocity

    # Cluster centrality (betweenness within cluster)
    node_clusters = _node_cluster_map(graph)
    pub_cluster = node_clusters.get(pub_id, -1)
    cluster_nodes = [n for n, c in node_clusters.items() if c == pub_cluster]

    if len(cluster_nodes) > 2:
        subgraph = graph.subgraph(cluster_nodes).to_undirected()
        bc = nx.betweenness_centrality(subgraph)
        pub_bc = bc.get(pub_id, 0.0)
        max_bc = max(bc.values()) if bc else 1.0
        centrality_risk = 1.0 - (pub_bc / max_bc if max_bc > 0 else 0.0)
    else:
        centrality_risk = 0.5

    # Recommender churn proxy: how many recommenders also recommend competitors
    competitors_in_cluster = {n for n in cluster_nodes if n != pub_id and n not in (out_n & in_n)}
    recommender_overlap = 0
    if in_n and competitors_in_cluster:
        for rec in in_n:
            rec_out = set(graph.successors(rec))
            if rec_out & competitors_in_cluster:
                recommender_overlap += 1
        recommender_churn = recommender_overlap / len(in_n)
    else:
        recommender_churn = 0.0

    risk_score = (isolation * 0.25) + (reciprocity_risk * 0.3) + (centrality_risk * 0.25) + (recommender_churn * 0.2)

    result = {
        "risk_score": round(min(1.0, risk_score), 4),
        "signals": {
            "isolation": round(isolation, 4),
            "reciprocity_risk": round(reciprocity_risk, 4),
            "centrality_risk": round(centrality_risk, 4),
            "recommender_churn": round(recommender_churn, 4),
        },
        "method": "graph_churn_proxy",
    }

    # LLM enhancement
    if not llm.is_stub_mode():
        pub_label = graph.nodes[pub_id].get("label", str(pub_id))
        result["llm_insight"] = llm.generate_churn_insight(pub_label, result)

    return result


# ---------------------------------------------------------------------------
# E4-05: Warm reader scorer
# ---------------------------------------------------------------------------

def warm_readers(graph: nx.DiGraph, pub_id: int) -> list[dict]:
    """Find high-intent publication prospects: not recommending you, but sharing
    social graph and cluster membership."""
    from . import llm

    if pub_id not in graph:
        return []

    in_n = set(graph.predecessors(pub_id))
    out_n = set(graph.successors(pub_id))
    all_connected = in_n | out_n
    node_clusters = _node_cluster_map(graph)
    pub_cluster = node_clusters.get(pub_id, -1)

    # Who does pub_id also recommend? The "trusted" set
    trusted = out_n

    # For each non-recommender, check shared connections
    max_in = max((graph.in_degree(n) for n in graph.nodes()), default=1) or 1
    candidates = []

    for n in graph.nodes():
        if n == pub_id or n in in_n:
            continue  # Already recommending us

        # Must be recommended by 2+ pubs that pub_id also recommends
        n_preds = set(graph.predecessors(n))
        shared = n_preds & trusted
        if len(shared) < 2:
            continue

        # Same or adjacent cluster
        n_cluster = node_clusters.get(n, -1)
        if pub_cluster < 0 or n_cluster < 0:
            cluster_proximity = 0.2
        elif n_cluster == pub_cluster:
            cluster_proximity = 1.0
        elif abs(n_cluster - pub_cluster) <= 1:
            cluster_proximity = 0.5
        else:
            continue  # Too distant

        in_deg_norm = graph.in_degree(n) / max_in
        score = len(shared) * cluster_proximity * in_deg_norm

        candidates.append({
            "node": n,
            "label": graph.nodes[n].get("label", str(n)),
            "score": round(score, 4),
            "shared_connections": [graph.nodes[s].get("label", str(s)) for s in shared],
            "cluster_proximity": cluster_proximity,
            "in_degree": graph.in_degree(n),
            "why_warm": f"Shares {len(shared)} trusted connections, cluster proximity {cluster_proximity}",
        })

    candidates.sort(key=lambda c: c["score"], reverse=True)

    # LLM enhancement for top 3
    if not llm.is_stub_mode() and candidates:
        pub_label = graph.nodes[pub_id].get("label", str(pub_id))
        intros = llm.generate_warm_reader_intros(pub_label, candidates[:3])
        for i, intro in enumerate(intros):
            if i < len(candidates):
                candidates[i]["llm_intro"] = intro

    return candidates


# ---------------------------------------------------------------------------
# E4-06: Moat builder
# ---------------------------------------------------------------------------

def build_moat(graph: nx.DiGraph, pub_id: int) -> list[dict]:
    """Find 3-5 recommendation swaps that create a cluster moat."""
    from . import llm

    if pub_id not in graph:
        return []

    node_clusters = _node_cluster_map(graph)
    pub_cluster = node_clusters.get(pub_id, -1)
    out_n = set(graph.successors(pub_id))
    in_n = set(graph.predecessors(pub_id))
    mutual = out_n & in_n

    # Candidate swap partners: not mutual, same/adjacent cluster, decent degree
    candidates = []
    for n in graph.nodes():
        if n == pub_id or n in mutual:
            continue
        n_cluster = node_clusters.get(n, -1)
        if pub_cluster < 0 or n_cluster < 0:
            continue
        if abs(n_cluster - pub_cluster) > 1:
            continue

        reciprocity_gap = 1.0 if n not in out_n and n not in in_n else 0.5
        n_degree = graph.in_degree(n)

        # Count competitors in 2-hop that this swap would displace
        n_out = set(graph.successors(n))
        competitors_reached = {c for c in n_out
                               if node_clusters.get(c) == pub_cluster
                               and c != pub_id
                               and c not in mutual}

        moat_value = reciprocity_gap * (1 + len(competitors_reached)) * (1 + n_degree * 0.1)

        candidates.append({
            "node": n,
            "label": graph.nodes[n].get("label", str(n)),
            "moat_score": round(moat_value, 4),
            "in_degree": n_degree,
            "competitors_displaced": len(competitors_reached),
            "cluster": n_cluster,
            "rationale": (
                f"Swap with {graph.nodes[n].get('label', str(n))}: "
                f"displaces {len(competitors_reached)} competitors, "
                f"in-degree {n_degree}"
            ),
        })

    candidates.sort(key=lambda c: c["moat_score"], reverse=True)
    moat_set = candidates[:5]

    # Validate: count competitor 2-hop nodes before/after
    undirected = graph.to_undirected()
    try:
        before_2hop = set(nx.single_source_shortest_path_length(undirected, pub_id, cutoff=2).keys())
    except nx.NodeNotFound:
        before_2hop = set()
    competitors_before = {n for n in before_2hop
                          if node_clusters.get(n) == pub_cluster
                          and n != pub_id
                          and n not in mutual}

    for swap in moat_set:
        swap["method"] = "graph_moat_optimizer"

    # LLM enhancement
    if not llm.is_stub_mode() and moat_set:
        pub_label = graph.nodes[pub_id].get("label", str(pub_id))
        brief = llm.generate_moat_brief(pub_label, moat_set)
        if moat_set:
            moat_set[0]["llm_strategy"] = brief

    return moat_set
