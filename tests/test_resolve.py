"""Proves the harness fixes each mode and logs the triggering evidence (the 'after')."""

from __future__ import annotations

from substackgraph.auditlog import AuditLog
from substackgraph.resolve import resolve


def _by_id(result):
    return {n.canonical_id: n for n in result.nodes}


def test_mode1_three_surfaces_collapse_to_one_canonical_node(raw_graph):
    nodes, edges = raw_graph
    audit = AuditLog()
    result = resolve(nodes, edges, audit=audit)
    node = _by_id(result)[101]
    assert len(node.member_urls) == 3
    merges = [r for r in audit.records if r["action"] == "merge" and r.get("canonical_id") == 101]
    assert merges and merges[0]["evidence"][0]["signal"] == "same_id"


def test_mode2_shared_author_pubs_are_kept_separate_and_flagged(raw_graph):
    nodes, edges = raw_graph
    audit = AuditLog()
    result = resolve(nodes, edges, audit=audit)
    ids = _by_id(result)
    assert 201 in ids and 202 in ids  # NOT merged
    refusals = [r for r in audit.records if r["action"] == "refuse" and r["members"] == [201, 202]]
    assert refusals, "expected a refuse-to-merge record for the shared-author pair"
    assert refusals[0]["score"] < refusals[0]["threshold"]


def test_mode3_renamed_handle_edge_is_reattached_via_alias(raw_graph):
    nodes, edges = raw_graph
    audit = AuditLog()
    result = resolve(nodes, edges, audit=audit)
    assert (1, 301) in result.edges  # seed → New Handle, recovered from the 404'd old handle
    aliases = [r for r in audit.records if r["action"] == "alias" and r["canonical_id"] == 301]
    assert aliases


def test_mode4_self_loop_is_dropped(raw_graph):
    nodes, edges = raw_graph
    audit = AuditLog()
    result = resolve(nodes, edges, audit=audit)
    assert all(src != dst for src, dst in result.edges)
    drops = [r for r in audit.records if r["action"] == "drop_self_loop" and r.get("canonical_id") == 401]
    assert drops
