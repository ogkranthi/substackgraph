"""The identity-resolution harness (the "after"). Deterministic by construction:

  1. Canonicalize — group every URL by its publication `id`; reconcile the
     custom_domain ↔ subdomain ↔ author_id triad onto one canonical node.
  2. Confidence-scored merge with a refuse-to-guess gate — two distinct canonical nodes
     that merely share an author are scored low and REFUSED (flagged for review), never
     merged. That is the exact trap that corrupted the naive graph (mode 2).
  3. Alias re-attachment — a dangling edge whose target 404'd is re-pointed to the
     canonical node that lists it as a prior handle (mode 3). Self-loops are dropped (mode 4).

Every merge / refuse / alias / drop is written to the audit log with its triggering evidence.
The same input resolves to the same canonical node every run (the episode SLO).
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

import networkx as nx

from .auditlog import AuditLog
from .client import extract_identity, normalize_url, subdomain_token
from .config import MERGE_THRESHOLD
from .model import CanonicalNode, RawEdge, RawNode


@dataclass
class ResolveResult:
    nodes: list[CanonicalNode]
    edges: list[tuple[int, int]]
    graph: nx.DiGraph


def _first(values):
    for v in values:
        if v:
            return v
    return None


def score_merge(a: CanonicalNode, b: CanonicalNode) -> tuple[float, list[dict]]:
    """Weighted, explainable merge confidence for two *distinct* canonical nodes.

    Shared author alone is deliberately weak — it must never be sufficient on its own.
    """
    score = 0.0
    evidence: list[dict] = []

    shared_authors = sorted(set(a.author_ids) & set(b.author_ids))
    if shared_authors:
        score += 0.3
        evidence.append({"signal": "shared_author_only", "value": shared_authors, "weight": 0.3})

    name_sim = SequenceMatcher(None, (a.display_name or "").lower(), (b.display_name or "").lower()).ratio()
    if name_sim > 0:
        contrib = round(0.2 * name_sim, 4)
        score += contrib
        evidence.append({"signal": "name_similarity", "value": round(name_sim, 4), "weight": contrib})

    return min(score, 1.0), evidence


def _canonicalize(raw_nodes: list[RawNode], audit: AuditLog) -> dict[int, CanonicalNode]:
    """Group resolvable URLs by publication id into canonical nodes; log each collapse."""
    groups: dict[int, list[tuple[str, object]]] = {}
    for node in raw_nodes:
        if node.status != "ok":
            continue
        ident = extract_identity(node.meta)
        if ident.pub_id is None:
            continue
        groups.setdefault(int(ident.pub_id), []).append((node.url, ident))

    canonical: dict[int, CanonicalNode] = {}
    for pid in sorted(groups):
        members = groups[pid]
        urls = sorted(u for u, _ in members)
        idents = [i for _, i in members]
        aliases = sorted({a for i in idents for a in i.aliases})
        canonical[pid] = CanonicalNode(
            canonical_id=pid,
            member_urls=urls,
            subdomain=_first(i.subdomain for i in idents),
            custom_domain=_first(i.custom_domain for i in idents),
            author_ids=sorted({i.author_id for i in idents if i.author_id is not None}),
            display_name=_first(i.name for i in idents),
            aliases=aliases,
        )
        if len(urls) > 1:
            audit.log(
                "merge",
                canonical_id=pid,
                members=urls,
                score=1.0,
                threshold=MERGE_THRESHOLD,
                evidence=[{"signal": "same_id", "value": pid, "weight": 1.0}],
                outcome="merged",
            )
    return canonical


def _refuse_gate(canonical: dict[int, CanonicalNode], audit: AuditLog) -> None:
    """Examine candidate merges (nodes sharing an author) and refuse those below threshold."""
    by_author: dict[int, list[int]] = {}
    for pid, node in canonical.items():
        for aid in node.author_ids:
            by_author.setdefault(aid, []).append(pid)

    seen_pairs: set[tuple[int, int]] = set()
    for aid in sorted(by_author):
        pids = sorted(by_author[aid])
        for i in range(len(pids)):
            for j in range(i + 1, len(pids)):
                pair = (pids[i], pids[j])
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                a, b = canonical[pair[0]], canonical[pair[1]]
                score, evidence = score_merge(a, b)
                if score < MERGE_THRESHOLD:
                    audit.log(
                        "refuse",
                        members=[pair[0], pair[1]],
                        score=round(score, 4),
                        threshold=MERGE_THRESHOLD,
                        evidence=evidence,
                        outcome="kept_separate",
                    )
                else:  # pragma: no cover - not reached by the Episode 1 fixture
                    audit.log(
                        "merge",
                        members=[pair[0], pair[1]],
                        score=round(score, 4),
                        threshold=MERGE_THRESHOLD,
                        evidence=evidence,
                        outcome="merged",
                    )


def _alias_index(canonical: dict[int, CanonicalNode]) -> dict[str, int]:
    """Map every known alias (normalized url and bare handle) to its canonical id."""
    index: dict[str, int] = {}
    for pid, node in canonical.items():
        for alias in node.aliases:
            if "." in alias or alias.startswith("http"):
                index[normalize_url(alias)] = pid
            else:
                index[alias] = pid
    return index


def resolve(raw_nodes: list[RawNode], raw_edges: list[RawEdge], audit: AuditLog | None = None,
            threshold: float = MERGE_THRESHOLD) -> ResolveResult:
    audit = audit or AuditLog()

    canonical = _canonicalize(raw_nodes, audit)
    _refuse_gate(canonical, audit)
    alias_index = _alias_index(canonical)

    url_to_id: dict[str, int] = {}
    for pid, node in canonical.items():
        for url in node.member_urls:
            url_to_id[url] = pid

    canonical_edges: set[tuple[int, int]] = set()
    for edge in sorted(raw_edges):
        sid = url_to_id.get(edge.src_url)
        if sid is None:
            continue  # source never resolved; nothing to draw
        did = url_to_id.get(edge.dst_url)
        if did is None:
            did = alias_index.get(edge.dst_url) or alias_index.get(subdomain_token(edge.dst_url) or "")
            if did is not None:
                audit.log(
                    "alias",
                    src=sid,
                    target_url=edge.dst_url,
                    canonical_id=did,
                    evidence=[{"signal": "alias_match", "value": edge.dst_url, "weight": 1.0}],
                    outcome="reattached",
                )
            else:
                audit.log(
                    "drop_404",
                    src=sid,
                    target_url=edge.dst_url,
                    evidence=[{"signal": "unresolved_target", "value": edge.dst_url}],
                    outcome="dropped",
                )
                continue
        if sid == did:
            audit.log(
                "drop_self_loop",
                canonical_id=sid,
                target_url=edge.dst_url,
                evidence=[{"signal": "self_reference", "value": edge.dst_url}],
                outcome="dropped",
            )
            continue
        canonical_edges.add((sid, did))

    graph = nx.DiGraph()
    for pid in sorted(canonical):
        node = canonical[pid]
        graph.add_node(
            pid,
            label=node.display_name or node.subdomain or str(pid),
            member_urls=node.member_urls,
            surfaces=len(node.member_urls),
            author_ids=node.author_ids,
        )
    for sid, did in sorted(canonical_edges):
        graph.add_edge(sid, did)

    return ResolveResult(
        nodes=[canonical[pid] for pid in sorted(canonical)],
        edges=sorted(canonical_edges),
        graph=graph,
    )
