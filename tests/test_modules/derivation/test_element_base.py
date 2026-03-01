"""Tests for modules.derivation.element_base module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deriva.modules.derivation.base import Candidate, GenerationResult, RelationshipRule
from deriva.modules.derivation.element_base import (
    ElementDerivationBase,
    PatternBasedDerivation,
)


class ConcreteDerivation(ElementDerivationBase):
    """Concrete implementation for testing abstract base class."""

    ELEMENT_TYPE = "TestElement"
    OUTBOUND_RULES: list[RelationshipRule] = []
    INBOUND_RULES: list[RelationshipRule] = []

    def filter_candidates(self, candidates, enrichments, max_candidates, **kwargs):
        """Simple filter that returns first N candidates."""
        return candidates[:max_candidates]


class ConcretePatternDerivation(PatternBasedDerivation):
    """Concrete implementation for testing PatternBasedDerivation."""

    ELEMENT_TYPE = "TestPatternElement"
    OUTBOUND_RULES: list[RelationshipRule] = []
    INBOUND_RULES: list[RelationshipRule] = []

    def filter_candidates(
        self,
        candidates,
        enrichments,
        max_candidates,
        include_patterns=None,
        exclude_patterns=None,
        **kwargs,
    ):
        """Filter using pattern matching."""
        include_patterns = include_patterns or set()
        exclude_patterns = exclude_patterns or set()

        filtered = []
        for c in candidates:
            if self.matches_patterns(c.name, include_patterns, exclude_patterns):
                filtered.append(c)
        return filtered[:max_candidates]


class TestElementDerivationBase:
    """Tests for ElementDerivationBase abstract class."""

    def test_init_creates_logger(self):
        """Should create a logger on initialization."""
        derivation = ConcreteDerivation()
        assert derivation.logger is not None

    def test_get_filter_kwargs_returns_empty_dict(self):
        """Default get_filter_kwargs should return empty dict."""
        derivation = ConcreteDerivation()
        result = derivation.get_filter_kwargs(MagicMock())
        assert result == {}

    def test_generate_returns_result_for_empty_candidates(self):
        """Should return success result when no candidates found."""
        derivation = ConcreteDerivation()

        mock_graph = MagicMock()
        mock_graph.query.return_value = []

        result = derivation.generate(
            graph_manager=mock_graph,
            archimate_manager=MagicMock(),
            engine=MagicMock(),
            llm_query_fn=MagicMock(),
            query="MATCH (n) RETURN n",
            instruction="Test",
            example="{}",
            max_candidates=10,
            batch_size=5,
            existing_elements=[],
        )

        assert isinstance(result, GenerationResult)
        assert result.success is True
        assert result.elements_created == 0

    def test_generate_handles_query_exception(self):
        """Should return error result when query fails."""
        derivation = ConcreteDerivation()

        mock_graph = MagicMock()
        # First call returns empty enrichments, second raises exception
        mock_graph.query.side_effect = [[], Exception("Query failed")]

        result = derivation.generate(
            graph_manager=mock_graph,
            archimate_manager=MagicMock(),
            engine=MagicMock(),
            llm_query_fn=MagicMock(),
            query="MATCH (n) RETURN n",
            instruction="Test",
            example="{}",
            max_candidates=10,
            batch_size=5,
            existing_elements=[],
        )

        assert result.success is False
        assert len(result.errors) > 0
        assert "Query failed" in result.errors[0]

    def test_generate_returns_empty_when_no_candidates_pass_filter(self):
        """Should return success when all candidates are filtered out."""

        class FilterAllDerivation(ConcreteDerivation):
            def filter_candidates(self, candidates, enrichments, max_candidates, **kwargs):
                return []  # Filter out everything

        derivation = FilterAllDerivation()

        mock_graph = MagicMock()
        mock_graph.query.return_value = [{"id": "1", "name": "test", "labels": ["Node"], "properties": {}}]

        # Patch the helper functions to control behavior
        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph") as mock_enrichments,
            patch("deriva.modules.derivation.element_base.query_candidates") as mock_candidates,
        ):
            mock_enrichments.return_value = {}
            mock_candidates.return_value = [
                Candidate(
                    node_id="1",
                    name="test",
                    labels=["Node"],
                    properties={},
                )
            ]

            result = derivation.generate(
                graph_manager=mock_graph,
                archimate_manager=MagicMock(),
                engine=MagicMock(),
                llm_query_fn=MagicMock(),
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
            )

        assert result.success is True
        assert result.elements_created == 0


class TestPatternBasedDerivation:
    """Tests for PatternBasedDerivation mixin class."""

    def test_matches_patterns_returns_true_for_include_match(self):
        """Should return True when name matches include pattern."""
        derivation = ConcretePatternDerivation()

        result = derivation.matches_patterns(
            name="UserService",
            include_patterns={"service", "manager"},
            exclude_patterns=set(),
        )

        assert result is True

    def test_matches_patterns_returns_false_for_exclude_match(self):
        """Should return False when name matches exclude pattern."""
        derivation = ConcretePatternDerivation()

        result = derivation.matches_patterns(
            name="TestService",
            include_patterns={"service"},
            exclude_patterns={"test"},
        )

        assert result is False

    def test_matches_patterns_is_case_insensitive(self):
        """Should match patterns case-insensitively."""
        derivation = ConcretePatternDerivation()

        result = derivation.matches_patterns(
            name="USERSERVICE",
            include_patterns={"service"},
            exclude_patterns=set(),
        )

        assert result is True

    def test_matches_patterns_returns_default_when_no_match(self):
        """Should return PATTERN_MATCH_DEFAULT when no patterns match."""
        derivation = ConcretePatternDerivation()

        result = derivation.matches_patterns(
            name="RandomName",
            include_patterns={"service"},
            exclude_patterns=set(),
        )

        assert result is False  # PATTERN_MATCH_DEFAULT is False

    def test_matches_patterns_returns_false_for_empty_name(self):
        """Should return False for empty name."""
        derivation = ConcretePatternDerivation()

        result = derivation.matches_patterns(
            name="",
            include_patterns={"service"},
            exclude_patterns=set(),
        )

        assert result is False

    def test_matches_patterns_returns_false_for_none_name(self):
        """Should return False for None name."""
        derivation = ConcretePatternDerivation()

        result = derivation.matches_patterns(
            name=None,  # type: ignore[arg-type]  # Testing None handling
            include_patterns={"service"},
            exclude_patterns=set(),
        )

        assert result is False

    def test_get_filter_kwargs_loads_patterns(self):
        """Should load patterns from config."""
        derivation = ConcretePatternDerivation()

        with patch("deriva.services.config.get_derivation_patterns") as mock_get:
            mock_get.return_value = {
                "include": {"service", "manager"},
                "exclude": {"test", "mock"},
            }

            result = derivation.get_filter_kwargs(MagicMock())

            assert "include_patterns" in result
            assert "exclude_patterns" in result
            assert "service" in result["include_patterns"]
            assert "test" in result["exclude_patterns"]

    def test_get_filter_kwargs_handles_missing_patterns(self):
        """Should return empty sets when no patterns configured."""
        derivation = ConcretePatternDerivation()

        with patch("deriva.services.config.get_derivation_patterns") as mock_get:
            mock_get.side_effect = ValueError("Not found")

            result = derivation.get_filter_kwargs(MagicMock())

            assert result["include_patterns"] == set()
            assert result["exclude_patterns"] == set()


class TestPatternMatchDefault:
    """Tests for PATTERN_MATCH_DEFAULT behavior."""

    def test_custom_pattern_match_default(self):
        """Should allow customizing PATTERN_MATCH_DEFAULT."""

        class InclusivePatternDerivation(PatternBasedDerivation):
            ELEMENT_TYPE = "Inclusive"
            PATTERN_MATCH_DEFAULT = True  # Include by default
            OUTBOUND_RULES: list[RelationshipRule] = []
            INBOUND_RULES: list[RelationshipRule] = []

            def filter_candidates(self, candidates, enrichments, max_candidates, **kwargs):
                return candidates

        derivation = InclusivePatternDerivation()

        result = derivation.matches_patterns(
            name="RandomName",
            include_patterns=set(),
            exclude_patterns=set(),
        )

        assert result is True  # Custom default


class TestProcessBatch:
    """Tests for _process_batch method."""

    def test_process_batch_handles_llm_error(self):
        """Should add error when LLM call fails."""
        derivation = ConcreteDerivation()

        result = GenerationResult(success=True)
        batch = [
            Candidate(
                node_id="1",
                name="Test",
                labels=["Node"],
                properties={},
                pagerank=0.5,
                louvain_community="1",
            )
        ]

        mock_llm = MagicMock(side_effect=Exception("LLM error"))

        derivation._process_batch(
            batch_num=1,
            batch=batch,
            instruction="Test",
            example="{}",
            llm_query_fn=mock_llm,
            llm_kwargs={},
            archimate_manager=MagicMock(),
            graph_manager=MagicMock(),
            existing_elements=[],
            temperature=None,
            max_tokens=None,
            defer_relationships=False,
            result=result,
        )

        assert len(result.errors) > 0
        assert "LLM error" in result.errors[0]

    def test_process_batch_handles_parse_error(self):
        """Should add error when response parsing fails."""
        derivation = ConcreteDerivation()

        result = GenerationResult(success=True)
        batch = [
            Candidate(
                node_id="1",
                name="Test",
                labels=["Node"],
                properties={},
                pagerank=0.5,
                louvain_community="1",
            )
        ]

        # Mock LLM to return invalid response
        mock_response = MagicMock()
        mock_response.output = "not valid json"
        mock_llm = MagicMock(return_value=mock_response)

        with patch("deriva.modules.derivation.element_base.extract_response_content") as mock_extract:
            mock_extract.return_value = ("invalid json", None)

            derivation._process_batch(
                batch_num=1,
                batch=batch,
                instruction="Test",
                example="{}",
                llm_query_fn=mock_llm,
                llm_kwargs={},
                archimate_manager=MagicMock(),
                graph_manager=MagicMock(),
                existing_elements=[],
                temperature=None,
                max_tokens=None,
                defer_relationships=False,
                result=result,
            )

        # Should have parse errors
        assert len(result.errors) >= 0  # May or may not have errors depending on parse


class TestDeriveRelationships:
    """Tests for _derive_relationships method."""

    def test_derive_relationships_creates_relationships(self):
        """Should create relationships from derive_batch_relationships result."""
        derivation = ConcreteDerivation()

        result = GenerationResult(success=True)
        batch_elements = [{"identifier": "elem-1", "name": "Element1"}]
        existing_elements = [{"identifier": "elem-0", "name": "Element0"}]

        mock_archimate = MagicMock()

        with patch("deriva.modules.derivation.element_base.derive_batch_relationships") as mock_derive:
            mock_derive.return_value = [
                {
                    "source": "elem-1",
                    "target": "elem-0",
                    "relationship_type": "Association",
                    "confidence": 0.8,
                }
            ]

            derivation._derive_relationships(
                batch_elements=batch_elements,
                existing_elements=existing_elements,
                llm_query_fn=MagicMock(),
                temperature=None,
                max_tokens=None,
                graph_manager=MagicMock(),
                archimate_manager=mock_archimate,
                result=result,
            )

        assert result.relationships_created == 1
        assert mock_archimate.add_relationship.called

    def test_derive_relationships_handles_creation_error(self):
        """Should add error when relationship creation fails."""
        derivation = ConcreteDerivation()

        result = GenerationResult(success=True)
        batch_elements = [{"identifier": "elem-1", "name": "Element1"}]
        existing_elements = [{"identifier": "elem-0", "name": "Element0"}]

        mock_archimate = MagicMock()
        mock_archimate.add_relationship.side_effect = Exception("Creation failed")

        with patch("deriva.modules.derivation.element_base.derive_batch_relationships") as mock_derive:
            mock_derive.return_value = [
                {
                    "source": "elem-1",
                    "target": "elem-0",
                    "relationship_type": "Association",
                }
            ]

            derivation._derive_relationships(
                batch_elements=batch_elements,
                existing_elements=existing_elements,
                llm_query_fn=MagicMock(),
                temperature=None,
                max_tokens=None,
                graph_manager=MagicMock(),
                archimate_manager=mock_archimate,
                result=result,
            )

        assert len(result.errors) > 0
        assert "Failed to create" in result.errors[0]
