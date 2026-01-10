"""Shared fixtures and utilities for derivation module tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deriva.modules.derivation.base import Candidate


@pytest.fixture
def make_candidate():
    """Factory fixture for creating test candidates.

    Usage:
        def test_something(make_candidate):
            candidate = make_candidate("test_name", pagerank=0.8)
    """

    def _make(
        name: str = "test",
        pagerank: float = 0.5,
        node_id: str | None = None,
        louvain_community: str | None = None,
    ) -> Candidate:
        return Candidate(
            node_id=node_id or f"id_{name}",
            name=name,
            pagerank=pagerank,
            louvain_community=louvain_community,
        )

    return _make


@pytest.fixture
def mock_graph_manager():
    """Mock GraphManager that handles both enrichment and candidate queries.

    The generate() function makes two queries:
    1. get_enrichments_from_neo4j - returns node_id, pagerank, louvain_community, etc.
    2. query_candidates - returns id, name, labels, properties
    """
    manager = MagicMock()

    # Enrichment query results (first call)
    enrichment_results = [
        {
            "node_id": "node_1",
            "pagerank": 0.8,
            "louvain_community": "node_1",
            "kcore_level": 3,
            "is_articulation_point": False,
            "in_degree": 5,
            "out_degree": 3,
        },
        {
            "node_id": "node_2",
            "pagerank": 0.5,
            "louvain_community": "node_1",
            "kcore_level": 2,
            "is_articulation_point": False,
            "in_degree": 2,
            "out_degree": 1,
        },
    ]

    # Candidate query results (second call)
    candidate_results = [
        {
            "id": "node_1",
            "name": "TestComponent",
            "labels": ["Directory"],
            "properties": {"path": "/src/components"},
        },
        {
            "id": "node_2",
            "name": "AnotherComponent",
            "labels": ["Directory"],
            "properties": {"path": "/src/services"},
        },
    ]

    # Return different results for different queries
    manager.query.side_effect = [enrichment_results, candidate_results]
    return manager


@pytest.fixture
def mock_archimate_manager():
    """Mock ArchimateManager."""
    manager = MagicMock()
    manager.add_element.return_value = None
    manager.add_relationship.return_value = None
    return manager


@pytest.fixture
def mock_llm_query_fn():
    """Mock LLM query function returning valid derivation response.

    Returns elements with identifier and name as required by DERIVATION_SCHEMA.
    """

    def _create_mock(element_type: str = "ApplicationComponent"):
        mock_fn = MagicMock()
        mock_response = MagicMock()
        # Return valid derivation response with identifier and name
        mock_response.content = f"""{{
            "elements": [
                {{
                    "identifier": "test_{element_type.lower()}_1",
                    "name": "Test {element_type}",
                    "documentation": "Test documentation for {element_type}",
                    "source": "node_1",
                    "confidence": 0.85
                }}
            ]
        }}"""
        mock_fn.return_value = mock_response
        return mock_fn

    return _create_mock


@pytest.fixture
def mock_engine():
    """Mock DuckDB engine."""
    return MagicMock()
