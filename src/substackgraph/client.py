"""The substack-api adapter and the single place that touches raw metadata field names.

CLAUDE.md is explicit: confirm exact JSON field names against the live library / DevTools
before hard-coding them. So every raw-key access lives in `extract_identity` below,
verified against a real _preloads payload (2026-06-08). Correcting a field name is a
one-file change; nothing else in the codebase reads raw metadata keys directly.
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
    Field names confirmed against live _preloads.pub payload (2026-06-08).
    """
    pub_id = meta.get("id")
    subdomain = meta.get("subdomain")
    custom_domain = meta.get("custom_domain")
    author_id = meta.get("author_id")
    name = meta.get("name")
    aliases = meta.get("aliases") or []
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
            import json as _json  # noqa: PLC0415
            import re as _re  # noqa: PLC0415
            import requests as _req  # noqa: PLC0415
            r = _req.get(nurl, timeout=10,
                         headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
            if r.status_code == 404:
                raise PublicationNotFound(nurl)
            r.raise_for_status()
            # Extract _preloads JSON from the page — contains pub metadata.
            m = _re.search(r'window\._preloads\s*=\s*JSON\.parse\("(.+?)"\)', r.text)
            if m:
                decoded = m.group(1).encode().decode("unicode_escape")
                preloads = _json.loads(decoded)
                pub = preloads.get("pub", {})
                if pub:
                    meta.update({
                        "id": pub.get("id"),
                        "subdomain": pub.get("subdomain"),
                        "custom_domain": pub.get("custom_domain"),
                        "name": pub.get("name"),
                        "author_id": pub.get("author_id"),
                    })
        except PublicationNotFound:
            raise
        except Exception:  # noqa: BLE001
            pass
        return meta

    def get_recommendation_urls(self, url: str) -> list[str]:
        return [rec["url"] for rec in self.get_recommendations_meta(url) if rec.get("url")]

    def get_recommendations_meta(self, url: str) -> list[dict]:
        """Recommendations for `url` WITH the identity-bearing fields from the payload.

        The `/api/v1/recommendations/from/{id}` response carries a full
        `recommendedPublication` object per edge (id / subdomain / custom_domain / name /
        author_id). The library's own `get_recommendations()` discards everything but the
        URL; we keep it, so a single recommendations request grounds the identity of every
        neighbor — no per-node search call, fewer requests, and the resolver gets real
        publication ids to merge on. Field names are isolated here on purpose (CLAUDE.md).
        """
        nurl = normalize_url(url)
        newsletter = self._newsletter(nurl)
        try:
            pub_id = newsletter._resolve_publication_id()  # discovery search → pub id
        except Exception:  # noqa: BLE001 — no id means no recommendations to read
            return []
        if not pub_id:
            return []

        import requests as _req  # noqa: PLC0415 — guaranteed via substack-api dep
        from substack_api.newsletter import HEADERS  # noqa: PLC0415

        endpoint = f"{nurl}/api/v1/recommendations/from/{pub_id}"
        resp = _req.get(endpoint, headers=HEADERS, timeout=30)
        resp.raise_for_status()

        out: list[dict] = []
        for rec in resp.json() or []:
            pub = rec.get("recommendedPublication", {}) or {}
            subdomain = pub.get("subdomain")
            custom_domain = pub.get("custom_domain")
            if custom_domain:
                target = custom_domain if "://" in str(custom_domain) else f"https://{custom_domain}"
            elif subdomain:
                target = f"https://{subdomain}.substack.com"
            else:
                continue
            author = pub.get("author_id")
            if author is None:
                authors = pub.get("authors") or []  # author_id is sometimes nested
                if authors and isinstance(authors[0], dict):
                    author = authors[0].get("id")
            out.append({
                "url": normalize_url(target),
                "id": pub.get("id"),
                "subdomain": subdomain,
                "custom_domain": custom_domain,
                "name": pub.get("name"),
                "author_id": author,
            })
        return out

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
