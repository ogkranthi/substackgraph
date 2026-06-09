"""Tests for E4 — Writer Growth Intelligence features.

All tests run WITHOUT an API key — they exercise the stub/fallback paths
to verify structure and contracts.
"""

from __future__ import annotations

import networkx as nx
import pytest

from substackgraph import analytics


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    """Ensure tests always use stub mode (no API key)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    import substackgraph.llm as llm_mod
    llm_mod._api_key = None
    llm_mod._stub_mode = False
    monkeypatch.setattr("substackgraph.llm._get_api_key", lambda: None)


@pytest.fixture()
def sample_graph() -> nx.DiGraph:
    """Directed graph with 6 nodes for testing growth intelligence features.

    Structure:
      1 -> 2 (mutual)
      2 -> 1 (mutual)
      1 -> 3
      3 -> 4
      4 -> 2
      3 -> 1 (3 recommends 1)
      5 -> 1 (5 recommends 1)
      5 -> 3
      6 -> 3
      6 -> 4
      4 -> 5
    """
    g = nx.DiGraph()
    g.add_node(1, label="The AI Runtime", member_urls=["https://theairuntime.substack.com"])
    g.add_node(2, label="ML Digest", member_urls=["https://mldigest.substack.com"])
    g.add_node(3, label="Data Weekly", member_urls=["https://dataweekly.substack.com"])
    g.add_node(4, label="AI Frontiers", member_urls=["https://aifrontiers.substack.com"])
    g.add_node(5, label="Deep Learning Daily", member_urls=["https://deeplearningdaily.substack.com"])
    g.add_node(6, label="Neural Notes", member_urls=["https://neuralnotes.substack.com"])
    g.add_edge(1, 2)
    g.add_edge(2, 1)
    g.add_edge(1, 3)
    g.add_edge(3, 4)
    g.add_edge(4, 2)
    g.add_edge(3, 1)
    g.add_edge(5, 1)
    g.add_edge(5, 3)
    g.add_edge(6, 3)
    g.add_edge(6, 4)
    g.add_edge(4, 5)
    return g


# ---------------------------------------------------------------------------
# E4-01: rec_quality_score
# ---------------------------------------------------------------------------

class TestRecQualityScore:
    def test_returns_list(self, sample_graph):
        result = analytics.rec_quality_score(sample_graph, 1)
        assert isinstance(result, list)

    def test_each_item_has_score_0_to_1(self, sample_graph):
        result = analytics.rec_quality_score(sample_graph, 1)
        assert len(result) > 0
        for item in result:
            assert 0.0 <= item["score"] <= 1.0

    def test_each_item_has_recommender_name(self, sample_graph):
        result = analytics.rec_quality_score(sample_graph, 1)
        for item in result:
            assert "recommender_label" in item
            assert isinstance(item["recommender_label"], str)

    def test_each_item_has_breakdown_dict(self, sample_graph):
        result = analytics.rec_quality_score(sample_graph, 1)
        for item in result:
            assert "breakdown" in item
            bd = item["breakdown"]
            assert "selectivity" in bd
            assert "cluster_alignment" in bd
            assert "voice_compat" in bd
            assert "journey_match" in bd

    def test_results_are_sorted_by_score(self, sample_graph):
        result = analytics.rec_quality_score(sample_graph, 1)
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_nonexistent_node_returns_empty(self, sample_graph):
        assert analytics.rec_quality_score(sample_graph, 999) == []


# ---------------------------------------------------------------------------
# E4-02: related_map
# ---------------------------------------------------------------------------

class TestRelatedMap:
    def test_returns_categorized_dict(self, sample_graph):
        result = analytics.related_map(sample_graph, 1)
        assert "competitors" in result
        assert "safe_partners" in result
        assert "threat_levels" in result

    def test_competitors_have_threat_levels(self, sample_graph):
        result = analytics.related_map(sample_graph, 1)
        for c in result["competitors"]:
            assert c["threat_level"] in ("high", "medium", "low")

    def test_safe_partners_have_relationship(self, sample_graph):
        result = analytics.related_map(sample_graph, 1)
        for p in result["safe_partners"]:
            assert "relationship" in p

    def test_nonexistent_node_returns_empty(self, sample_graph):
        result = analytics.related_map(sample_graph, 999)
        assert result["competitors"] == []
        assert result["safe_partners"] == []


# ---------------------------------------------------------------------------
# E4-03: paywall_gap_analysis
# ---------------------------------------------------------------------------

class TestPaywallGapAnalysis:
    def test_returns_list(self, sample_graph):
        result = analytics.paywall_gap_analysis(sample_graph, 1)
        assert isinstance(result, list)

    def test_each_gap_has_topic_and_suggestion(self, sample_graph):
        result = analytics.paywall_gap_analysis(sample_graph, 1)
        for gap in result:
            assert "topic" in gap
            assert "suggestion" in gap

    def test_method_is_keyword_frequency_in_stub(self, sample_graph):
        result = analytics.paywall_gap_analysis(sample_graph, 1)
        for gap in result:
            assert gap.get("method") == "keyword_frequency"

    def test_nonexistent_node_returns_empty(self, sample_graph):
        assert analytics.paywall_gap_analysis(sample_graph, 999) == []


# ---------------------------------------------------------------------------
# E4-04: churn_signals
# ---------------------------------------------------------------------------

class TestChurnSignals:
    def test_returns_dict_with_risk_score(self, sample_graph):
        result = analytics.churn_signals(sample_graph, 1)
        assert "risk_score" in result
        assert 0.0 <= result["risk_score"] <= 1.0

    def test_has_per_signal_breakdown(self, sample_graph):
        result = analytics.churn_signals(sample_graph, 1)
        assert "signals" in result
        signals = result["signals"]
        assert "isolation" in signals
        assert "reciprocity_risk" in signals
        assert "centrality_risk" in signals
        assert "recommender_churn" in signals

    def test_method_field(self, sample_graph):
        result = analytics.churn_signals(sample_graph, 1)
        assert result["method"] == "graph_churn_proxy"

    def test_nonexistent_node_returns_zero_risk(self, sample_graph):
        result = analytics.churn_signals(sample_graph, 999)
        assert result["risk_score"] == 0.0


# ---------------------------------------------------------------------------
# E4-05: warm_readers
# ---------------------------------------------------------------------------

class TestWarmReaders:
    def test_returns_list(self, sample_graph):
        result = analytics.warm_readers(sample_graph, 1)
        assert isinstance(result, list)

    def test_each_item_has_score(self, sample_graph):
        result = analytics.warm_readers(sample_graph, 1)
        for item in result:
            assert "score" in item
            assert isinstance(item["score"], float)

    def test_each_item_has_shared_connections(self, sample_graph):
        result = analytics.warm_readers(sample_graph, 1)
        for item in result:
            assert "shared_connections" in item
            assert isinstance(item["shared_connections"], list)

    def test_results_are_sorted_by_score(self, sample_graph):
        result = analytics.warm_readers(sample_graph, 1)
        scores = [r["score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_nonexistent_node_returns_empty(self, sample_graph):
        assert analytics.warm_readers(sample_graph, 999) == []


# ---------------------------------------------------------------------------
# E4-06: build_moat
# ---------------------------------------------------------------------------

class TestBuildMoat:
    def test_returns_list(self, sample_graph):
        result = analytics.build_moat(sample_graph, 1)
        assert isinstance(result, list)

    def test_returns_at_most_5_swaps(self, sample_graph):
        result = analytics.build_moat(sample_graph, 1)
        assert len(result) <= 5

    def test_each_swap_has_moat_score(self, sample_graph):
        result = analytics.build_moat(sample_graph, 1)
        for swap in result:
            assert "moat_score" in swap
            assert isinstance(swap["moat_score"], float)

    def test_each_swap_has_required_fields(self, sample_graph):
        result = analytics.build_moat(sample_graph, 1)
        for swap in result:
            assert "label" in swap
            assert "competitors_displaced" in swap
            assert "rationale" in swap
            assert "method" in swap

    def test_nonexistent_node_returns_empty(self, sample_graph):
        assert analytics.build_moat(sample_graph, 999) == []
