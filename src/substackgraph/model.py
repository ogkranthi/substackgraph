"""Plain data structures shared across the pipeline. No behavior beyond construction."""

from __future__ import annotations

from dataclasses import dataclass, field


class PublicationNotFound(Exception):
    """Raised by the client when a publication handle 404s (e.g. a renamed handle)."""


class FetchError(Exception):
    """Raised by the client for any other failure reaching Substack."""


@dataclass
class RawNode:
    """A publication URL exactly as ingested, before any identity resolution.

    `meta` is the *entire* raw metadata dict so no field is lost to an early mapping
    decision; `status` is the cache status ("ok" | "http_404" | "error").
    """

    url: str
    meta: dict
    status: str


@dataclass(frozen=True)
class RawEdge:
    """A recommendation edge between two URLs, pre-resolution."""

    src_url: str
    dst_url: str
    kind: str = "recommendation"

    def __lt__(self, other: "RawEdge") -> bool:  # deterministic sorting
        return (self.src_url, self.dst_url) < (other.src_url, other.dst_url)


@dataclass
class IdentityTriad:
    """The identity-bearing fields pulled out of raw metadata, in one place.

    Field *names* on the raw dict are confirmed in client.extract_identity; everything
    downstream uses this normalized view instead of touching raw keys.
    """

    pub_id: int | None
    subdomain: str | None
    custom_domain: str | None
    author_id: int | None
    name: str | None
    aliases: list[str] = field(default_factory=list)


@dataclass
class CanonicalNode:
    """One real publication, after resolution: the canonical entity the map should show."""

    canonical_id: int
    member_urls: list[str]
    subdomain: str | None
    custom_domain: str | None
    author_ids: list[int]
    display_name: str | None
    aliases: list[str] = field(default_factory=list)
