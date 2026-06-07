"""The substack-api adapter and the single place that touches raw metadata field names.

CLAUDE.md is explicit: confirm exact JSON field names against the live library / DevTools
before hard-coding them. So every raw-key access lives in `extract_identity` below, each
marked `# TODO confirm`. Correcting a field name is a one-file change; nothing else in the
codebase reads raw metadata keys directly.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from .model import IdentityTriad, PublicationNotFound


def normalize_url(raw: str) -> str:
    """Canonicalize a URL string for use as a stable key. Idempotent."""
    u = (raw or "").strip()
    if not u:
        return u
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    parts = urlsplit(u)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    return f"https://{host}{path}"


def subdomain_token(url: str) -> str | None:
    """Best-effort handle for a Substack URL: the subdomain for *.substack.com, else the host."""
    host = urlsplit(normalize_url(url)).netloc
    if not host:
        return None
    if host.endswith(".substack.com"):
        return host.split(".")[0]
    return host


def extract_identity(meta: dict) -> IdentityTriad:
    """Pull the identity-bearing fields out of a raw metadata dict.

    THE ONLY place raw field names are referenced. Uses `.get()` throughout so a missing
    or renamed field degrades to None rather than crashing the resolver.
    """
    # TODO confirm against live substack-api: these key names are the documented intent
    # (id / subdomain / custom_domain / author_id) but must be checked against a real payload.
    pub_id = meta.get("id")  # TODO confirm
    subdomain = meta.get("subdomain")  # TODO confirm
    custom_domain = meta.get("custom_domain")  # TODO confirm
    author_id = meta.get("author_id")  # TODO confirm (may be nested under authors[0].id)
    name = meta.get("name")  # TODO confirm
    aliases = meta.get("aliases") or []  # prior handles / redirecting domains, if exposed
    return IdentityTriad(
        pub_id=pub_id,
        subdomain=subdomain,
        custom_domain=custom_domain,
        author_id=author_id,
        name=name,
        aliases=list(aliases),
    )


class SubstackClient:
    """Thin wrapper over substack_api.Newsletter. Imported lazily so the package (and the
    fully-offline test suite) does not require the library or the network just to import.
    """

    def get_metadata(self, url: str) -> dict:
        nurl = normalize_url(url)
        meta: dict = {"url": nurl}
        try:
            # Use the library's publication search — same endpoint _resolve_publication_id
            # uses, but we capture the full match so we get id/subdomain/custom_domain/name.
            from substack_api.newsletter import (  # noqa: PLC0415
                DISCOVERY_HEADERS,
                SEARCH_URL,
                _match_publication,
            )
            import requests as _req  # noqa: PLC0415 — guaranteed via substack-api dep
            host = urlsplit(nurl).netloc
            r = _req.get(
                SEARCH_URL,
                headers=DISCOVERY_HEADERS,
                params={"query": host, "page": 0, "limit": 25,
                        "skipExplanation": "true", "sort": "relevance"},
                timeout=10,
            )
            r.raise_for_status()
            match = _match_publication(r.json(), host)
            if match:
                meta.update({
                    "id": match.get("id"),
                    "subdomain": match.get("subdomain"),
                    "custom_domain": match.get("custom_domain"),
                    "name": match.get("name"),
                    "author_id": match.get("author_id"),
                })
        except Exception:  # noqa: BLE001
            pass
        return meta

    def get_recommendation_urls(self, url: str) -> list[str]:
        newsletter = self._newsletter(url)
        recs = newsletter.get_recommendations() or []
        urls: list[str] = []
        for rec in recs:
            rec_url = getattr(rec, "url", None)
            if rec_url:
                urls.append(normalize_url(rec_url))
        return urls

    def _newsletter(self, url: str):
        try:
            from substack_api import Newsletter  # lazy: only needed for live crawls
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "substack-api is not installed. Run `pip install -e .` with Python 3.12+."
            ) from exc
        try:
            return Newsletter(normalize_url(url))
        except Exception as exc:  # noqa: BLE001 - surface 404s as the typed exception
            raise PublicationNotFound(url) from exc
