"""The episode SLO, executable: the same input resolves to the same canonical node every
run, independent of input ordering."""

from __future__ import annotations

import random
from dataclasses import asdict

from substackgraph.auditlog import AuditLog
from substackgraph.resolve import resolve


def _serialize(result):
    return [asdict(n) for n in result.nodes], result.edges


def test_repeated_runs_are_identical(raw_graph):
    nodes, edges = raw_graph
    a1 = AuditLog()
    a2 = AuditLog()
    r1 = resolve(nodes, edges, audit=a1)
    r2 = resolve(nodes, edges, audit=a2)
    assert _serialize(r1) == _serialize(r2)
    # Decisions match once run-specific noise (timestamp, run id) is stripped.
    assert a1.replayable() == a2.replayable()


def test_input_order_does_not_change_output(raw_graph):
    nodes, edges = raw_graph
    baseline = _serialize(resolve(nodes, edges, audit=AuditLog()))

    shuffled_nodes = nodes[:]
    shuffled_edges = edges[:]
    random.Random(1234).shuffle(shuffled_nodes)
    random.Random(5678).shuffle(shuffled_edges)
    shuffled = _serialize(resolve(shuffled_nodes, shuffled_edges, audit=AuditLog()))

    assert baseline == shuffled
