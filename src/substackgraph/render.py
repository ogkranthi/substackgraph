"""Shared pyvis renderer. Both the naive and resolved graphs draw through this so the only
difference in the before/after image is the data, never the rendering. pyvis is imported
lazily so importing this module (and the offline test suite) needs no JS/render dependency.
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx


def _build_network(graph: nx.DiGraph, title: str):
    """Construct a pyvis Network from a graph. Uses a remote CDN for vis-network assets so
    the output is a single self-contained file with no local `lib/` dump — important for
    serving over the web."""
    from pyvis.network import Network

    net = Network(
        height="800px", width="100%", directed=True, heading=title, cdn_resources="remote"
    )
    net.barnes_hut()  # force-directed layout

    for node, data in graph.nodes(data=True):
        label = str(data.get("label", node))
        surfaces = data.get("surfaces")
        if surfaces and surfaces > 1:
            label = f"{label}\n({surfaces} surfaces → 1)"
        members = data.get("member_urls", [])
        title_text = "\n".join(str(m) for m in members) if members else str(node)
        net.add_node(str(node), label=label, title=title_text)

    for src, dst in graph.edges():
        net.add_edge(str(src), str(dst))

    return net


def graph_to_html(graph: nx.DiGraph, title: str) -> str:
    """Render a graph to a self-contained HTML string (for serving dynamically)."""
    return _build_network(graph, title).generate_html(notebook=False)


def render_graph(graph: nx.DiGraph, title: str, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(graph_to_html(graph, title), encoding="utf-8")
    return out
