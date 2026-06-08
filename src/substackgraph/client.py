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
