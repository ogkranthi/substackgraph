"""Tests for E3-01 (collab-brief) and E3-02 (outreach-angles).

These tests run WITHOUT an API key — they exercise the stub fallback path
to verify structure and contracts.
"""

from __future__ import annotations

import os

import networkx as nx
import pytest

from substackgraph import analytics
from substackgraph.llm import generate_collab_brief, generate_outreach_angles


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    """Ensure tests always use stub mode (no API key)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Reset the module-level state so stub mode is re-evaluated
    import substackgraph.llm as llm_mod
    llm_mod._client = None
    llm_mod._stub_mode = False


@pytest.fixture()
def sample_graph() -> nx.DiGraph:
    """Small directed graph with 4 nodes and edges for testing."""
    g = nx.DiGraph()
    g.add_node(1, label="The AI Runtime", member_urls=["https://theairuntime.substack.com"])
    g.add_node(2, label="ML Digest", member_urls=["https://mldigest.substack.com"])
    g.add_node(3, label="Data Weekly", member_urls=["https://dataweekly.substack.com"])
    g.add_node(4, label="AI Frontiers", member_urls=["https://aifrontiers.substack.com"])
    g.add_edge(1, 2)
    g.add_edge(2, 1)
    g.add_edge(1, 3)
    g.add_edge(3, 4)
    g.add_edge(4, 2)
    return g


# ---------------------------------------------------------------------------
# E3-01: collab_brief
# ---------------------------------------------------------------------------

class TestCollabBrief:
    def test_returns_nonempty_brief(self, sample_graph):
        result = analytics.collab_brief(sample_graph, 1, 2)
        assert "brief" in result
        assert isinstance(result["brief"], str)
        assert len(result["brief"]) > 0

    def test_method_is_stub_without_api_key(self, sample_graph):
        result = analytics.collab_brief(sample_graph, 1, 2)
        assert result["method"] == "stub_template"

    def test_pub_names_in_result(self, sample_graph):
        result = analytics.collab_brief(sample_graph, 1, 2)
        assert result["pub_a"] == "The AI Runtime"
        assert result["pub_b"] == "ML Digest"

    def test_cluster_info_present(self, sample_graph):
        result = analytics.collab_brief(sample_graph, 1, 2)
        assert "cluster_a" in result
        assert "cluster_b" in result

    def test_no_model_field_in_stub(self, sample_graph):
        result = analytics.collab_brief(sample_graph, 1, 2)
        assert "model" not in result


# ---------------------------------------------------------------------------
# E3-02: outreach_angles
# ---------------------------------------------------------------------------

class TestOutreachAngles:
    def test_returns_exactly_3_angles(self, sample_graph):
        result = analytics.outreach_angles(sample_graph, 1, 2)
        assert "angles" in result
        assert len(result["angles"]) == 3

    def test_each_angle_has_subject_and_body(self, sample_graph):
        result = analytics.outreach_angles(sample_graph, 1, 2)
        for angle in result["angles"]:
            assert "angle" in angle
            assert "subject" in angle
            assert "body" in angle
            assert len(angle["subject"]) > 0
            assert len(angle["body"]) > 0

    def test_method_is_stub_without_api_key(self, sample_graph):
        result = analytics.outreach_angles(sample_graph, 1, 2)
        assert result["method"] == "stub_template"

    def test_pub_names_in_result(self, sample_graph):
        result = analytics.outreach_angles(sample_graph, 1, 2)
        assert result["pub_a"] == "The AI Runtime"
        assert result["pub_b"] == "ML Digest"

    def test_no_model_field_in_stub(self, sample_graph):
        result = analytics.outreach_angles(sample_graph, 1, 2)
        assert "model" not in result


# ---------------------------------------------------------------------------
# Direct LLM module tests (stub path)
# ---------------------------------------------------------------------------

class TestLLMStubDirect:
    def test_generate_collab_brief_stub(self):
        result = generate_collab_brief(
            pub_a_name="Pub A",
            pub_b_name="Pub B",
            pub_a_desc="",
            pub_b_desc="",
            cluster_a="AI cluster",
            cluster_b="ML cluster",
            shared_recommenders=["Shared One"],
            overlap_score=0.5,
        )
        assert result["method"] == "stub_template"
        assert "Pub A" in result["brief"]
        assert "Pub B" in result["brief"]

    def test_generate_outreach_angles_stub(self):
        result = generate_outreach_angles(
            pub_a_name="Pub A",
            pub_b_name="Pub B",
            pub_a_desc="",
            pub_b_desc="",
            warm_path=["Pub A", "Connector", "Pub B"],
            voice_compat_score=0.7,
        )
        assert result["method"] == "stub_template"
        assert len(result["angles"]) == 3
