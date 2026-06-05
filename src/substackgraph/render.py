"""Shared pyvis renderer. Both the naive and resolved graphs draw through this so the only
difference in the before/after image is the data, never the rendering. pyvis is imported
lazily so importing this module (and the offline test suite) needs no JS/render dependency.
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx


def render_graph(graph: nx.DiGraph, title: str, out_path: str | Path) -> Path:
    from pyvis.network import Network

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    net = Network(height="800px", width="100%", directed=True, heading=title)
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

    net.write_html(str(out), notebook=False, open_browser=False)
    return out
