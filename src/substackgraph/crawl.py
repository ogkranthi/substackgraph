"""2-hop breadth-first crawl over recommendation edges. Cache-first and rate-limited:
the cache IS the crawl's only persistent output. Visit order is sorted so runs are
reproducible. The crawler intentionally does NO identity resolution — it preserves raw
URLs and edges so the naive renderer can later surface the corruption.
"""

from __future__ import annotations

from .cache import Cache
from .client import SubstackClient, normalize_url
from .model import PublicationNotFound, RawEdge, RawNode
from .ratelimit import RateLimiter

_META_KEYS = ("id", "subdomain", "custom_domain", "name", "author_id")


def crawl(seed_url: str, hops: int, cache: Cache, rate_limiter: RateLimiter, client: SubstackClient) -> None:
    """Populate `cache` with `meta:` and `recs:` rows for the 2-hop neighborhood of the seed.

    Meta is fetched for every visited node (so it is resolvable). Recommendations are fetched
    for nodes within the hop budget (depth < hops) so edges span the requested number of hops.
    The recommendations payload also carries each neighbor's identity, so we write it through
    to that neighbor's `meta:` row — grounding the neighbor without a separate search request.
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
                for neighbor in _fetch_recs(url, cache, rate_limiter, client):
                    next_frontier.add(neighbor)

        frontier = next_frontier


def _fetch_recs(url: str, cache: Cache, rate_limiter: RateLimiter, client: SubstackClient) -> list[str]:
    """Cache-first recommendations fetch. Stores the `recs:` URL list (unchanged format) and
    writes identity through to each neighbor's `meta:` row from the same payload."""
    key = f"recs:{url}"
    existing = cache.get(key)
    if existing is not None:
        return [normalize_url(u) for u in (existing.payload or [])]

    rate_limiter.acquire()
    try:
        rich = client.get_recommendations_meta(url)
    except PublicationNotFound:
        cache.put(key, url, "http_404", None)
        return []
    except Exception:  # noqa: BLE001 — record the failure, don't crash the crawl
        cache.put(key, url, "error", None)
        return []

    rec_urls: list[str] = []
    for obj in rich:
        ru = normalize_url(obj.get("url") or "")
        if not ru:
            continue
        rec_urls.append(ru)
        # Ground the neighbor from the recommendations payload (no extra request). Don't
        # clobber an existing meta row (e.g. the seed's own searched metadata).
        has_identity = any(obj.get(k) is not None for k in _META_KEYS)
        if has_identity and cache.get(f"meta:{ru}") is None:
            cache.put(f"meta:{ru}", ru, "ok", {"url": ru, **{k: obj.get(k) for k in _META_KEYS}})

    cache.put(key, url, "ok", rec_urls)
    return rec_urls


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
