"""The crawl must ground every neighbor's identity from the recommendations payload,
so the resolver has real publication ids to merge on — the fix for the live graph where
metadata came back null and the decision log was empty."""

from __future__ import annotations

from substackgraph.auditlog import AuditLog
from substackgraph.cache import Cache
from substackgraph.client import normalize_url
from substackgraph.crawl import crawl, load_raw_graph
from substackgraph.resolve import resolve


class FakeClient:
    """Stands in for SubstackClient: serves a tiny network from in-memory tables.

    `theairuntime` recommends `alpha` (reachable at both a custom domain and its subdomain,
    same pub id → a merge) and `beta`. `alpha` and `gamma` share an author (→ a refuse).
    """

    RECS = {
        "https://theairuntime.substack.com": [
            {"url": "https://alpha.com", "id": 100, "subdomain": "alpha",
             "custom_domain": "alpha.com", "name": "Alpha", "author_id": 1},
            {"url": "https://beta.substack.com", "id": 200, "subdomain": "beta",
             "custom_domain": None, "name": "Beta", "author_id": 2},
        ],
        "https://alpha.com": [
            # alpha's own subdomain surface — same id 100 → must collapse into one node
            {"url": "https://alpha.substack.com", "id": 100, "subdomain": "alpha",
             "custom_domain": "alpha.com", "name": "Alpha", "author_id": 1},
            {"url": "https://gamma.substack.com", "id": 300, "subdomain": "gamma",
             "custom_domain": None, "name": "Gamma", "author_id": 1},  # shared author → refuse
        ],
    }

    def get_metadata(self, url: str) -> dict:
        return {"url": normalize_url(url), "id": 1, "subdomain": "theairuntime",
                "custom_domain": None, "name": "The AI Runtime", "author_id": 99}

    def get_recommendations_meta(self, url: str) -> list[dict]:
        return self.RECS.get(normalize_url(url), [])


class _NoLimit:
    def acquire(self) -> None:  # offline: never sleep
        pass


def test_crawl_grounds_neighbor_identity_and_resolver_fires(tmp_path):
    cache = Cache(tmp_path / "c.sqlite")
    crawl("https://theairuntime.substack.com", 2, cache, _NoLimit(), FakeClient())

    nodes, edges = load_raw_graph(cache)
    by_url = {n.url: n for n in nodes}

    # Every neighbor was grounded from the recommendations payload (no null identity).
    assert by_url["https://alpha.com"].meta.get("id") == 100
    assert by_url["https://beta.substack.com"].meta.get("name") == "Beta"
    assert by_url["https://gamma.substack.com"].meta.get("id") == 300

    audit = AuditLog()
    result = resolve(nodes, edges, audit=audit)
    actions = {}
    for rec in audit.records:
        actions[rec["action"]] = actions.get(rec["action"], 0) + 1

    # alpha's two surfaces (custom domain + subdomain, id 100) collapse to one node.
    alpha = [n for n in result.nodes if n.custom_domain == "alpha.com" or n.subdomain == "alpha"]
    assert len(alpha) == 1
    assert len(alpha[0].member_urls) == 2
    assert actions.get("merge", 0) >= 1          # the surface collapse was logged
    assert actions.get("refuse", 0) >= 1          # alpha vs gamma share an author → refused
    cache.close()


def test_crawl_is_cache_first_on_rerun(tmp_path):
    """A second crawl must hit the cache, not the client (the cache-first SLO)."""
    cache = Cache(tmp_path / "c.sqlite")
    crawl("https://theairuntime.substack.com", 2, cache, _NoLimit(), FakeClient())

    class ExplodingClient(FakeClient):
        def get_metadata(self, url):
            raise AssertionError("network touched on re-run")

        def get_recommendations_meta(self, url):
            raise AssertionError("network touched on re-run")

    crawl("https://theairuntime.substack.com", 2, cache, _NoLimit(), ExplodingClient())
    cache.close()
