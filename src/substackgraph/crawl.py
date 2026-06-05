"""2-hop breadth-first crawl over recommendation edges. Cache-first and rate-limited:
the cache IS the crawl's only persistent output. Visit order is sorted so runs are
reproducible. The crawler intentionally does NO identity resolution — it preserves raw
URLs and edges so the naive renderer can later surface the corruption.
"""

from __future__ import annotations

from .cache import Cache
from .client import SubstackClient, normalize_url
from .model import RawEdge, RawNode
from .ratelimit import RateLimiter


def crawl(seed_url: str, hops: int, cache: Cache, rate_limiter: RateLimiter, client: SubstackClient) -> None:
    """Populate `cache` with `meta:` and `recs:` rows for the 2-hop neighborhood of the seed.

    Meta is fetched for every visited node (so it is resolvable). Recommendations are fetched
    for nodes within the hop budget (depth < hops) so edges span the requested number of hops.
    """
    seed = normalize_url(seed_url)
    frontier = {seed}
    visited: set[str] = set()

    for depth in range(hops + 1):
        next_frontier: set[str] = set()
        for url in sorted(frontier):
            if url in visited:
                continue
            visited.add(url)

            cache.cached_call(f"meta:{url}", url, lambda u=url: client.get_metadata(u), rate_limiter)

            if depth < hops:
                row = cache.cached_call(
                    f"recs:{url}", url, lambda u=url: client.get_recommendation_urls(u), rate_limiter
                )
                for neighbor in row.payload or []:
                    next_frontier.add(normalize_url(neighbor))

        frontier = next_frontier


def load_raw_graph(cache: Cache) -> tuple[list[RawNode], list[RawEdge]]:
    """Read the cache back into raw nodes and edges for the renderers / resolver."""
    nodes = [RawNode(row.url, row.payload or {}, row.status) for row in cache.iter_prefix("meta:")]
    edges: list[RawEdge] = []
    for row in cache.iter_prefix("recs:"):
        src = normalize_url(row.url)
        for dst in row.payload or []:
            edges.append(RawEdge(src, normalize_url(dst)))
    nodes.sort(key=lambda n: n.url)
    edges.sort()
    return nodes, edges
