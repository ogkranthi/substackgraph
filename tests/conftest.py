"""Loads the JSON fixture into a temporary SQLite cache so the whole suite runs offline.
The cache is the single source of truth, exactly as a real crawl would leave it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from substackgraph.cache import Cache
from substackgraph.client import normalize_url
from substackgraph.crawl import load_raw_graph

FIXTURE = Path(__file__).parent / "fixtures" / "recommendations.json"


@pytest.fixture
def cache(tmp_path) -> Cache:
    data = json.loads(FIXTURE.read_text())
    c = Cache(tmp_path / "cache.sqlite")
    for url, entry in data["meta"].items():
        nurl = normalize_url(url)
        c.put(f"meta:{nurl}", nurl, entry["status"], entry["meta"])
    for url, recs in data["recs"].items():
        nurl = normalize_url(url)
        c.put(f"recs:{nurl}", nurl, "ok", [normalize_url(r) for r in recs])
    yield c
    c.close()


@pytest.fixture
def raw_graph(cache):
    return load_raw_graph(cache)
