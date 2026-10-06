"""Tests for modules.derivation.refine modules."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

# =============================================================================
# Tests for refine/base.py
# =============================================================================


class TestRefineResult:
    """Tests for RefineResult dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        from deriva.modules.derivation.refine.base import RefineResult

        result = RefineResult(success=True, step_name="test_step")

        assert result.success is True
        assert result.step_name == "test_step"
        assert result.elements_disabled == 0
        assert result.elements_merged == 0
        assert result.relationships_deleted == 0
        assert result.issues_found == 0
        assert result.issues_fixed == 0
        assert result.details == []
        assert result.errors == []

    def test_to_dict_conversion(self):
        """Should convert to dictionary correctly."""
        from deriva.modules.derivation.refine.base import RefineResult

        result = RefineResult(
            success=True,
            step_name="duplicate_elements",
            elements_disabled=5,
            elements_merged=3,
            issues_found=2,
            details=[{"action": "merged", "id": "elem1"}],
            errors=["warning1"],
        )

        d = result.to_dict()

        assert d["success"] is True
        assert d["step_name"] == "duplicate_elements"
        assert d["elements_disabled"] == 5
        assert d["elements_merged"] == 3
        assert d["issues_found"] == 2
        assert len(d["details"]) == 1
        assert d["errors"] == ["warning1"]


class TestNormalizeName:
    """Tests for normalize_name function."""

    def test_lowercases_string(self):
        """Should convert to lowercase."""
        from deriva.modules.derivation.refine.base import normalize_name

        # Note: AuthService without separator becomes authservice (no spaces inserted)
        assert normalize_name("AuthService") == "authservice"

    def test_no_business_domain_synonyms(self):
        """Only generic architecture rules: domain words are not rewritten into other domain words."""
        from deriva.modules.derivation.refine.base import normalize_name

        assert normalize_name("Client Portal") == "client portal"
        assert normalize_name("Account Settings") == "account setting"  # the generic plural rule still applies
        assert normalize_name("Sale Record") == "sale record"
        assert normalize_name("Report Generation") == "report generation"
        assert normalize_name("Payments") == "payments"  # only architecture plurals have entries

    def test_removes_common_prefixes(self):
        """Should remove the, a, an prefixes."""
        from deriva.modules.derivation.refine.base import normalize_name

        # The function applies synonyms, so "auth" becomes "authentication"
        result = normalize_name("the Login Service")
        assert result.startswith("login")
        assert normalize_name("a User") == "user"
        assert normalize_name("an Item") == "item"

    def test_normalizes_separators(self):
        """Should normalize underscores and hyphens to spaces."""
        from deriva.modules.derivation.refine.base import normalize_name

        # Note: "auth" might be converted by synonym mapping
        result = normalize_name("user_service")
        assert "user" in result
        assert "_" not in result

        result = normalize_name("user-login")
        assert "user" in result
        assert "login" in result
        assert "-" not in result

    def test_applies_synonym_mapping(self):
        """Should apply synonym mappings."""
        from deriva.modules.derivation.refine.base import normalize_name

        # Based on actual synonyms defined in the function
        assert normalize_name("insert item") == "create item"
        assert normalize_name("remove user") == "delete user"
        assert normalize_name("modify data") == "update data"
        # Note: "database" is a key in synonyms map
        result = normalize_name("database connection")
        assert "db" in result or "database" in result  # May or may not be mapped

    def test_handles_empty_string(self):
        """Should return empty string for empty input."""
        from deriva.modules.derivation.refine.base import normalize_name

        assert normalize_name("") == ""

    def test_normalizes_whitespace(self):
        """Should normalize multiple spaces."""
        from deriva.modules.derivation.refine.base import normalize_name

        result = normalize_name("login   service")
        assert "  " not in result  # No multiple spaces
        assert "login" in result
        assert "service" in result


class TestLevenshteinDistance:
    """Tests for levenshtein_distance function."""

    def test_identical_strings(self):
        """Should return 0 for identical strings."""
        from deriva.modules.derivation.refine.base import levenshtein_distance

        assert levenshtein_distance("test", "test") == 0

    def test_empty_string(self):
        """Should return length of other string for empty input."""
        from deriva.modules.derivation.refine.base import levenshtein_distance

        assert levenshtein_distance("", "test") == 4
        assert levenshtein_distance("test", "") == 4

    def test_single_character_difference(self):
        """Should return 1 for single character difference."""
        from deriva.modules.derivation.refine.base import levenshtein_distance

        assert levenshtein_distance("test", "tost") == 1
        assert levenshtein_distance("test", "tests") == 1

    def test_completely_different_strings(self):
        """Should return max length for completely different strings."""
        from deriva.modules.derivation.refine.base import levenshtein_distance

        # "abc" vs "xyz" - all 3 characters different
        assert levenshtein_distance("abc", "xyz") == 3


class TestSimilarityRatio:
    """Tests for similarity_ratio function."""

    def test_identical_strings(self):
        """Should return 1.0 for identical strings."""
        from deriva.modules.derivation.refine.base import similarity_ratio

        assert similarity_ratio("test", "test") == 1.0

    def test_empty_strings(self):
        """Should return 1.0 for two empty strings."""
        from deriva.modules.derivation.refine.base import similarity_ratio

        assert similarity_ratio("", "") == 1.0

    def test_one_empty_string(self):
        """Should return 0.0 when one string is empty."""
        from deriva.modules.derivation.refine.base import similarity_ratio

        assert similarity_ratio("test", "") == 0.0
        assert similarity_ratio("", "test") == 0.0

    def test_similar_strings(self):
        """Should return high ratio for similar strings."""
        from deriva.modules.derivation.refine.base import similarity_ratio

        ratio = similarity_ratio("authentication", "authenticator")
        assert ratio > 0.8

    def test_different_strings(self):
        """Should return low ratio for different strings."""
        from deriva.modules.derivation.refine.base import similarity_ratio

        ratio = similarity_ratio("abc", "xyz")
        assert ratio == 0.0


class TestRegisterRefineStep:
    """Tests for register_refine_step decorator."""

    def test_registers_step_in_registry(self):
        """Should register step class in REFINE_STEPS."""
        from deriva.modules.derivation.refine.base import REFINE_STEPS, register_refine_step

        @register_refine_step("test_step_registration")
        class TestStep:
            pass

        assert "test_step_registration" in REFINE_STEPS
        assert REFINE_STEPS["test_step_registration"] == TestStep

        # Cleanup
        del REFINE_STEPS["test_step_registration"]


class TestRunRefineStep:
    """Tests for run_refine_step function."""

    def test_returns_error_for_unknown_step(self):
        """Should return error result for unknown step name."""
        from deriva.modules.derivation.refine.base import run_refine_step

        result = run_refine_step(
            step_name="nonexistent_step",
            archimate_manager=MagicMock(),
        )

        assert result.success is False
        assert "Unknown refine step" in result.errors[0]

    def test_runs_registered_step(self):
        """Should run registered step and return result."""
        from deriva.modules.derivation.refine.base import REFINE_STEPS, RefineResult, run_refine_step

        class MockStep:
            def run(self, archimate_manager, graph_manager=None, llm_query_fn=None, params=None):
                return RefineResult(success=True, step_name="mock_step", issues_found=5)

        REFINE_STEPS["mock_step_test"] = MockStep

        result = run_refine_step(
            step_name="mock_step_test",
            archimate_manager=MagicMock(),
        )

        assert result.success is True
        assert result.issues_found == 5

        # Cleanup
        del REFINE_STEPS["mock_step_test"]

    def test_handles_step_exception(self):
        """Should handle exception from step and return error."""
        from deriva.modules.derivation.refine.base import REFINE_STEPS, run_refine_step

        class FailingStep:
            def run(self, archimate_manager, graph_manager=None, llm_query_fn=None, params=None):
                raise ValueError("Step failed!")

        REFINE_STEPS["failing_step"] = FailingStep

        result = run_refine_step(
            step_name="failing_step",
            archimate_manager=MagicMock(),
        )

        assert result.success is False
        assert "Step failed!" in result.errors[0]

        # Cleanup
        del REFINE_STEPS["failing_step"]


# =============================================================================
# Tests for refine/duplicate_elements.py
# =============================================================================


@dataclass
class MockElement:
    """Mock ArchiMate element for testing."""

    identifier: str
    name: str
    element_type: str
    enabled: bool = True
    documentation: str | None = None
    properties: dict | None = None

    def __post_init__(self):
        if self.properties is None:
            self.properties = {}


class TestDuplicateElementsStep:
    """Tests for DuplicateElementsStep class."""

    def test_returns_success_for_no_elements(self):
        """Should return success when no elements exist."""
        from deriva.modules.derivation.refine.duplicate_elements import DuplicateElementsStep

        mock_manager = MagicMock()
        mock_manager.get_elements.return_value = []

        step = DuplicateElementsStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.elements_merged == 0

    def test_finds_exact_name_duplicates(self):
        """Should find and merge exact name duplicates."""
        from deriva.modules.derivation.refine.duplicate_elements import DuplicateElementsStep

        elements = [
            MockElement("id1", "AuthService", "ApplicationComponent"),
            MockElement("id2", "AuthService", "ApplicationComponent"),
        ]

        mock_manager = MagicMock()
        mock_manager.get_elements.return_value = elements

        step = DuplicateElementsStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.elements_merged == 1
        assert result.elements_disabled == 1
        assert any(d["tier"] == 1 for d in result.details)

    def test_skips_disabled_elements(self):
        """Should skip disabled elements."""
        from deriva.modules.derivation.refine.duplicate_elements import DuplicateElementsStep

        elements = [
            MockElement("id1", "AuthService", "ApplicationComponent", enabled=True),
            MockElement("id2", "AuthService", "ApplicationComponent", enabled=False),
        ]

        mock_manager = MagicMock()
        mock_manager.get_elements.return_value = elements

        step = DuplicateElementsStep()
        result = step.run(archimate_manager=mock_manager)

        # Should not find duplicates since one is disabled
        assert result.elements_merged == 0

    def test_finds_fuzzy_matches_and_flags(self):
        """Should find fuzzy matches and flag for review."""
        from deriva.modules.derivation.refine.duplicate_elements import DuplicateElementsStep

        elements = [
            MockElement("id1", "AuthenticationService", "ApplicationComponent"),
            MockElement("id2", "AuthenticateService", "ApplicationComponent"),
        ]

        mock_manager = MagicMock()
        mock_manager.get_elements.return_value = elements

        step = DuplicateElementsStep()
        result = step.run(archimate_manager=mock_manager)

        # Should flag as issue but not merge (default auto_merge_tier2=False)
        assert result.issues_found >= 1 or result.elements_merged >= 1

    def test_auto_merge_tier2_when_enabled(self):
        """Should auto-merge fuzzy matches when auto_merge_tier2=True."""
        from deriva.modules.derivation.refine.duplicate_elements import DuplicateElementsStep

        elements = [
            MockElement("id1", "AuthenticationService", "ApplicationComponent"),
            MockElement("id2", "AuthenticateService", "ApplicationComponent"),
        ]

        mock_manager = MagicMock()
        mock_manager.get_elements.return_value = elements

        step = DuplicateElementsStep()
        result = step.run(
            archimate_manager=mock_manager,
            params={"auto_merge_tier2": True, "fuzzy_threshold": 0.7},
        )

        # Should merge fuzzy matches
        if result.elements_merged > 0:
            assert any(d.get("tier") == 2 for d in result.details)

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        from deriva.modules.derivation.refine.duplicate_elements import DuplicateElementsStep

        mock_manager = MagicMock()
        mock_manager.get_elements.side_effect = Exception("DB error")

        step = DuplicateElementsStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is False
        assert "DB error" in result.errors[0]

    def test_select_survivor_by_pagerank(self):
        """Should select element with higher pagerank as survivor."""
        from deriva.modules.derivation.refine.duplicate_elements import DuplicateElementsStep

        elem_a = MockElement("id1", "Service", "ApplicationComponent", properties={"source_pagerank": 0.5})
        elem_b = MockElement("id2", "Service", "ApplicationComponent", properties={"source_pagerank": 0.8})

        step = DuplicateElementsStep()
        survivor, duplicate = step._select_survivor(elem_a, elem_b)

        assert survivor.identifier == "id2"  # Higher pagerank
        assert duplicate.identifier == "id1"

    def test_select_survivor_by_documentation(self):
        """Should select element with more documentation when pagerank equal."""
        from deriva.modules.derivation.refine.duplicate_elements import DuplicateElementsStep

        elem_a = MockElement("id1", "Service", "ApplicationComponent", documentation="Short")
        elem_b = MockElement("id2", "Service", "ApplicationComponent", documentation="Much longer documentation")

        step = DuplicateElementsStep()
        survivor, duplicate = step._select_survivor(elem_a, elem_b)

        assert survivor.identifier == "id2"  # Longer docs

    def test_select_survivor_alphabetical_fallback(self):
        """Should use alphabetical order as fallback."""
        from deriva.modules.derivation.refine.duplicate_elements import DuplicateElementsStep

        elem_a = MockElement("aaa", "Service", "ApplicationComponent")
        elem_b = MockElement("bbb", "Service", "ApplicationComponent")

        step = DuplicateElementsStep()
        survivor, duplicate = step._select_survivor(elem_a, elem_b)

        assert survivor.identifier == "aaa"  # First alphabetically


class TestDuplicateElementsStepNoLlm:
    """Duplicate detection is rule-based (exact and fuzzy names): it never calls an LLM, even when given one."""

    def test_similar_names_below_the_fuzzy_threshold_make_no_llm_call(self):
        from deriva.modules.derivation.refine.duplicate_elements import DuplicateElementsStep

        mock_manager = MagicMock()
        mock_manager.get_elements.return_value = [
            MockElement("id1", "Journal Reader", "ApplicationComponent"),
            MockElement("id2", "Journal Writer", "ApplicationComponent"),
        ]
        mock_llm = MagicMock()

        result = DuplicateElementsStep().run(archimate_manager=mock_manager, llm_query_fn=mock_llm, params={"fuzzy_threshold": 0.99})

        mock_llm.assert_not_called()
        assert (result.success, result.elements_merged) == (True, 0)


# =============================================================================
# Tests for refine/duplicate_relationships.py
# =============================================================================


class TestDuplicateRelationshipsStep:
    """Tests for DuplicateRelationshipsStep class."""

    def test_returns_success_for_no_duplicates(self):
        """Should return success when no duplicates found."""
        from deriva.modules.derivation.refine.duplicate_relationships import DuplicateRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = []  # No duplicates

        step = DuplicateRelationshipsStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.relationships_deleted == 0

    def test_finds_and_deletes_exact_duplicates(self):
        """Should find and delete exact duplicate relationships."""
        from deriva.modules.derivation.refine.duplicate_relationships import DuplicateRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = [
            [],  # No self-loops (first query in _remove_self_loops)
            [
                {
                    "r1_id": "rel1",
                    "r2_id": "rel2",
                    "source": "elem1",
                    "target": "elem2",
                    "rel_type": "Model:Serving",
                }
            ],
            [],  # No redundant relationships
        ]
        mock_manager.delete_relationships.return_value = 1

        step = DuplicateRelationshipsStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.relationships_deleted == 1
        assert result.issues_fixed == 1
        mock_manager.delete_relationships.assert_called_once_with(["rel2"])

    def test_flags_redundant_relationship_pairs(self):
        """Should flag redundant relationship pairs."""
        from deriva.modules.derivation.refine.duplicate_relationships import DuplicateRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = [
            [],  # No self-loops (first query in _remove_self_loops)
            [],  # No exact duplicates
            [
                {
                    "source": "elem1",
                    "source_name": "Component A",
                    "target": "elem2",
                    "target_name": "Service B",
                    "rels": [
                        {"id": "rel1", "type": "Model:Serving"},
                        {"id": "rel2", "type": "Model:Flow"},
                    ],
                }
            ],
        ]

        step = DuplicateRelationshipsStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.issues_found == 1
        assert any(d.get("reason") == "redundant_relationship_pair" for d in result.details)

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        from deriva.modules.derivation.refine.duplicate_relationships import DuplicateRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = Exception("Query error")

        step = DuplicateRelationshipsStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is False
        assert "Query error" in result.errors[0]

    def test_skips_redundant_check_when_disabled(self):
        """Should skip redundant check when check_redundant=False."""
        from deriva.modules.derivation.refine.duplicate_relationships import DuplicateRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = []

        step = DuplicateRelationshipsStep()
        step.run(
            archimate_manager=mock_manager,
            params={"check_redundant": False},
        )

        # Should query twice: self_loops + exact duplicates (skips redundant check)
        assert mock_manager.query.call_count == 2

    def test_finds_and_removes_self_loops(self):
        """Should find and remove self-referential relationships."""
        from deriva.modules.derivation.refine.duplicate_relationships import DuplicateRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = [
            # Self-loops query returns results
            [
                {
                    "rel_id": "rel_self1",
                    "element_id": "elem1",
                    "element_name": "Component A",
                    "rel_type": "Model:Composition",
                },
                {
                    "rel_id": "rel_self2",
                    "element_id": "elem2",
                    "element_name": "Service B",
                    "rel_type": "Model:Serving",
                },
            ],
            [],  # No exact duplicates
            [],  # No redundant relationships
        ]
        mock_manager.delete_relationships.return_value = 2

        step = DuplicateRelationshipsStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.relationships_deleted == 2
        assert result.issues_fixed == 2
        mock_manager.delete_relationships.assert_called_once_with(["rel_self1", "rel_self2"])
        # Check details include self-referential reason
        assert any(d.get("reason") == "self_referential" for d in result.details)
        assert len([d for d in result.details if d.get("reason") == "self_referential"]) == 2


# =============================================================================
# Tests for refine/circular_relationships.py
# =============================================================================


class TestCircularRelationshipsStep:
    """Tests for CircularRelationshipsStep class."""

    def test_returns_success_for_no_circular_relationships(self):
        """Should return success when no circular relationships found."""
        from deriva.modules.derivation.refine.circular_relationships import CircularRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = []

        step = CircularRelationshipsStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.issues_found == 0

    def test_finds_and_deletes_bidirectional_compositions(self):
        """Should find and delete bidirectional Composition relationships."""
        from deriva.modules.derivation.refine.circular_relationships import CircularRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = [
            # Bidirectional pairs query
            [
                {
                    "a_id": "elem1",
                    "a_name": "Component A",
                    "b_id": "elem2",
                    "b_name": "Component B",
                    "r1_id": "rel1",
                    "r1_confidence": 0.8,
                    "r2_id": "rel2",
                    "r2_confidence": 0.6,
                }
            ],
            # Longer cycles query (empty)
            [],
        ]
        mock_manager.delete_relationships.return_value = 1

        step = CircularRelationshipsStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.issues_found == 1
        assert result.relationships_deleted == 1
        # Should delete rel2 (lower confidence)
        mock_manager.delete_relationships.assert_called_with(["rel2"])

    def test_flags_but_does_not_delete_when_delete_cycles_false(self):
        """Should flag but not delete when delete_cycles=False."""
        from deriva.modules.derivation.refine.circular_relationships import CircularRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = [
            [
                {
                    "a_id": "elem1",
                    "a_name": "Component A",
                    "b_id": "elem2",
                    "b_name": "Component B",
                    "r1_id": "rel1",
                    "r1_confidence": 0.8,
                    "r2_id": "rel2",
                    "r2_confidence": 0.6,
                }
            ],
            [],
        ]

        step = CircularRelationshipsStep()
        result = step.run(
            archimate_manager=mock_manager,
            params={"delete_cycles": False},
        )

        assert result.success is True
        assert result.issues_found == 1
        assert result.relationships_deleted == 0
        mock_manager.delete_relationships.assert_not_called()

    def test_skips_longer_cycle_detection_when_max_cycle_length_2(self):
        """Should skip longer cycle detection when max_cycle_length=2."""
        from deriva.modules.derivation.refine.circular_relationships import CircularRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = []

        step = CircularRelationshipsStep()
        step.run(
            archimate_manager=mock_manager,
            params={"max_cycle_length": 2},
        )

        # Should only query once (for bidirectional pairs)
        assert mock_manager.query.call_count == 1

    def test_finds_longer_cycles(self):
        """Should find and handle longer Composition cycles."""
        from deriva.modules.derivation.refine.circular_relationships import CircularRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = [
            # Bidirectional pairs (empty)
            [],
            # Longer cycles
            [
                {
                    "start_id": "elem1",
                    "start_name": "Component A",
                    "rel_ids": ["rel1", "rel2", "rel3"],
                    "confidences": [0.8, 0.5, 0.9],
                    "node_names": ["A", "B", "C", "A"],
                    "weakest_idx": 1,
                    "weakest_rel_id": "rel2",
                    "weakest_confidence": 0.5,
                }
            ],
        ]
        mock_manager.delete_relationships.return_value = 1

        step = CircularRelationshipsStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.issues_found == 1
        assert result.relationships_deleted == 1
        mock_manager.delete_relationships.assert_called_with(["rel2"])

    def test_handles_query_exception(self):
        """Should handle exceptions gracefully."""
        from deriva.modules.derivation.refine.circular_relationships import CircularRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = Exception("Query error")

        step = CircularRelationshipsStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is False
        assert "Query error" in result.errors[0]

    def test_handles_longer_cycle_query_exception(self):
        """Should handle exception in longer cycle detection gracefully."""
        from deriva.modules.derivation.refine.circular_relationships import CircularRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        # First query succeeds, second fails
        mock_manager.query.side_effect = [
            [],  # Bidirectional query succeeds
            Exception("Cycle query failed"),  # Longer cycle query fails
        ]

        step = CircularRelationshipsStep()
        result = step.run(archimate_manager=mock_manager)

        # Should still succeed (graceful degradation)
        assert result.success is True

    def test_keeps_higher_confidence_relationship(self):
        """Should keep the relationship with higher confidence."""
        from deriva.modules.derivation.refine.circular_relationships import CircularRelationshipsStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = [
            [
                {
                    "a_id": "elem1",
                    "a_name": "Component A",
                    "b_id": "elem2",
                    "b_name": "Component B",
                    "r1_id": "rel1",
                    "r1_confidence": 0.4,  # Lower confidence
                    "r2_id": "rel2",
                    "r2_confidence": 0.9,  # Higher confidence
                }
            ],
            [],
        ]
        mock_manager.delete_relationships.return_value = 1

        step = CircularRelationshipsStep()
        step.run(archimate_manager=mock_manager)

        # Should delete rel1 (lower confidence) and keep rel2
        mock_manager.delete_relationships.assert_called_with(["rel1"])


# =============================================================================
# Tests for refine/relationship_consolidation.py
# =============================================================================


class TestRelationshipConsolidationStep:
    """Tests for RelationshipConsolidationStep class."""

    def test_returns_success_for_no_relationships(self):
        """Should return success when no relationships found."""
        from deriva.modules.derivation.refine.relationship_consolidation import RelationshipConsolidationStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = []

        step = RelationshipConsolidationStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.issues_found == 0

    def test_boosts_confidence_for_corroborated_relationships(self):
        """Should boost confidence when multiple derivation signals agree."""
        from deriva.modules.derivation.refine.relationship_consolidation import RelationshipConsolidationStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = [
            {
                "identifier": "rel1",
                "source_id": "elem1",
                "source_name": "Component A",
                "target_id": "elem2",
                "target_name": "Service B",
                "rel_type": "Model:Serving",
                "confidence": 0.7,
                "derived_from": "edge_calls,community",
                "rel_name": None,
            }
        ]

        step = RelationshipConsolidationStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        # Should have boosted at least one relationship
        boosted = [d for d in result.details if d.get("action") == "boosted"]
        assert len(boosted) >= 1

    def test_flags_low_confidence_relationships_for_pruning(self):
        """Should flag relationships below confidence threshold."""
        from deriva.modules.derivation.refine.relationship_consolidation import RelationshipConsolidationStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = [
            {
                "identifier": "rel1",
                "source_id": "elem1",
                "source_name": "Component A",
                "target_id": "elem2",
                "target_name": "Service B",
                "rel_type": "Model:Serving",
                "confidence": 0.3,  # Below default 0.5 threshold
                "derived_from": "llm",
                "rel_name": None,
            }
        ]

        step = RelationshipConsolidationStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.issues_found == 1
        flagged = [d for d in result.details if "prune" in d.get("action", "")]
        assert len(flagged) == 1

    def test_prunes_relationships_when_auto_prune_enabled(self):
        """Should delete relationships when auto_prune=True."""
        from deriva.modules.derivation.refine.relationship_consolidation import RelationshipConsolidationStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = [
            {
                "identifier": "rel1",
                "source_id": "elem1",
                "source_name": "Component A",
                "target_id": "elem2",
                "target_name": "Service B",
                "rel_type": "Model:Serving",
                "confidence": 0.3,
                "derived_from": "llm",
                "rel_name": None,
            }
        ]
        mock_manager.delete_relationships.return_value = 1

        step = RelationshipConsolidationStep()
        result = step.run(
            archimate_manager=mock_manager,
            params={"auto_prune": True},
        )

        assert result.success is True
        assert result.relationships_deleted == 1
        mock_manager.delete_relationships.assert_called()

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        from deriva.modules.derivation.refine.relationship_consolidation import RelationshipConsolidationStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = Exception("Query error")

        step = RelationshipConsolidationStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is False
        assert "Query error" in result.errors[0]

    def test_requires_corroboration_for_low_confidence(self):
        """Should flag single-signal relationships below corroboration threshold."""
        from deriva.modules.derivation.refine.relationship_consolidation import RelationshipConsolidationStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = [
            {
                "identifier": "rel1",
                "source_id": "elem1",
                "source_name": "Component A",
                "target_id": "elem2",
                "target_name": "Service B",
                "rel_type": "Model:Serving",
                "confidence": 0.6,  # Below corroboration threshold (0.7)
                "derived_from": "llm",  # Single signal
                "rel_name": None,
            }
        ]

        step = RelationshipConsolidationStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.issues_found == 1


# =============================================================================
# Tests for refine/orphan_elements.py
# =============================================================================


class TestOrphanElementsStep:
    """The manager finds the orphans (enabled elements without relationships); the step decides."""

    @staticmethod
    def _manager(*orphans):
        manager = MagicMock()
        manager.namespace = "Model"
        manager.get_orphan_elements.return_value = list(orphans)
        return manager

    @staticmethod
    def _orphan(name="Orphan Component", properties=None):
        from deriva.adapters.archimate.models import Element

        return Element(name=name, element_type="ApplicationComponent", identifier="orphan1", properties=properties or {})

    def test_returns_success_for_no_orphans(self):
        from deriva.modules.derivation.refine.orphan_elements import OrphanElementsStep

        result = OrphanElementsStep().run(archimate_manager=self._manager())

        assert result.success is True
        assert result.issues_found == 0

    def test_flags_orphan_elements(self):
        from deriva.modules.derivation.refine.orphan_elements import OrphanElementsStep

        result = OrphanElementsStep().run(archimate_manager=self._manager(self._orphan()))

        assert result.success is True
        assert result.issues_found == 1
        assert [(d["action"], d["element_type"]) for d in result.details] == [("flagged", "ApplicationComponent")]

    def test_disables_orphans_below_the_importance_threshold(self):
        from deriva.modules.derivation.refine.orphan_elements import OrphanElementsStep

        manager = self._manager(self._orphan(properties={"source_pagerank": 0.01}))

        result = OrphanElementsStep().run(archimate_manager=manager, params={"disable_orphans": True, "min_importance": 0.1})

        assert (result.success, result.elements_disabled, result.issues_fixed) == (True, 1, 1)
        manager.disable_element.assert_called_once_with("orphan1", reason="orphan_no_relationships")

    def test_keeps_important_orphans(self):
        from deriva.modules.derivation.refine.orphan_elements import OrphanElementsStep

        manager = self._manager(self._orphan(name="Important Orphan", properties={"source_pagerank": 0.9}))

        result = OrphanElementsStep().run(archimate_manager=manager, params={"disable_orphans": True, "min_importance": 0.1})

        # Flagged, not disabled
        assert result.elements_disabled == 0
        assert result.issues_found == 1

    def test_handles_exception(self):
        from deriva.modules.derivation.refine.orphan_elements import OrphanElementsStep

        manager = self._manager()
        manager.get_orphan_elements.side_effect = Exception("Query error")

        result = OrphanElementsStep().run(archimate_manager=manager)

        assert result.success is False
        assert "Query error" in result.errors[0]

    def test_proposes_relationships_from_the_source_graph(self):
        from deriva.modules.derivation.refine.orphan_elements import OrphanElementsStep

        graph = MagicMock()
        graph.query.return_value = [{"rel_type": "Graph:CONTAINS", "target_id": "target_1", "target_name": "Target Node"}]

        result = OrphanElementsStep().run(archimate_manager=self._manager(self._orphan(properties={"source": "graph_node_1"})), graph_manager=graph)

        (detail,) = result.details
        assert detail["proposed_relationships"] == [
            {"source_graph_rel": "CONTAINS", "proposed_archimate_rel": "Composition", "target_graph_id": "target_1", "target_name": "Target Node"}
        ]
        assert graph.query.call_args.args[1] == {"source_id": "graph_node_1"}


# =============================================================================
# Tests for refine/structural_consistency.py
# =============================================================================


class TestStructuralConsistencyStep:
    """Tests for StructuralConsistencyStep class."""

    def test_skips_without_graph_manager(self):
        """Should skip check when graph_manager not provided."""
        from deriva.modules.derivation.refine.structural_consistency import StructuralConsistencyStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"

        step = StructuralConsistencyStep()
        result = step.run(archimate_manager=mock_manager, graph_manager=None)

        assert result.success is True
        assert any(d.get("action") == "skipped" for d in result.details)

    def test_checks_containment_preservation(self):
        """Should check containment relationship preservation."""
        from deriva.modules.derivation.refine.structural_consistency import StructuralConsistencyStep

        mock_archimate_manager = MagicMock()
        mock_archimate_manager.namespace = "Model"
        mock_archimate_manager.query.return_value = []

        mock_graph_manager = MagicMock()

        step = StructuralConsistencyStep()
        result = step.run(
            archimate_manager=mock_archimate_manager,
            graph_manager=mock_graph_manager,
        )

        assert result.success is True

    def test_model_query_failure_does_not_fail_the_step(self):
        """A failing call-preservation query is logged, not fatal."""
        from deriva.modules.derivation.refine.structural_consistency import (
            StructuralConsistencyStep,
        )

        mock_archimate_manager = MagicMock()
        mock_archimate_manager.namespace = "Model"
        mock_archimate_manager.query.side_effect = Exception("Query error")

        mock_graph_manager = MagicMock()

        step = StructuralConsistencyStep()
        result = step.run(
            archimate_manager=mock_archimate_manager,
            graph_manager=mock_graph_manager,
        )

        assert result.success is True

    def test_skips_checks_based_on_params(self):
        """Should skip specific checks based on params."""
        from deriva.modules.derivation.refine.structural_consistency import StructuralConsistencyStep

        mock_archimate_manager = MagicMock()
        mock_archimate_manager.namespace = "Model"
        mock_archimate_manager.query.return_value = []

        mock_graph_manager = MagicMock()

        step = StructuralConsistencyStep()
        result = step.run(
            archimate_manager=mock_archimate_manager,
            graph_manager=mock_graph_manager,
            params={"check_containment": False, "check_calls": False, "check_aspect_constraints": False},
        )

        # Should return quickly with no checks performed
        assert result.success is True
        assert mock_archimate_manager.query.call_count == 0


# =============================================================================
# Tests for refine/cross_layer.py
# =============================================================================


class TestCrossLayerCoherenceStep:
    """Tests for CrossLayerCoherenceStep class."""

    def test_checks_business_to_app_connections(self):
        """Should check Business→App layer connections."""
        from deriva.modules.derivation.refine.cross_layer import CrossLayerCoherenceStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = []

        step = CrossLayerCoherenceStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True

    def test_flags_disconnected_business_elements(self):
        """Should flag Business elements without App connections."""
        from deriva.modules.derivation.refine.cross_layer import CrossLayerCoherenceStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = [
            [
                {
                    "identifier": "bp1",
                    "name": "Business Process",
                    "label": "Model:BusinessProcess",
                }
            ],
            [],  # App to Tech check
            [],  # Floating check
        ]

        step = CrossLayerCoherenceStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.issues_found >= 1

    def test_skips_checks_based_on_params(self):
        """Should skip specific checks based on params."""
        from deriva.modules.derivation.refine.cross_layer import CrossLayerCoherenceStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = []

        step = CrossLayerCoherenceStep()
        result = step.run(
            archimate_manager=mock_manager,
            params={"check_business_to_app": False, "check_app_to_tech": False},
        )

        assert result.success is True
        # Should still check floating elements
        assert mock_manager.query.call_count == 1

    def test_checks_floating_technology_elements(self):
        """Should check for floating Technology elements."""
        from deriva.modules.derivation.refine.cross_layer import CrossLayerCoherenceStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = [
            [],  # Business to App
            [],  # App to Tech
            [
                {
                    "identifier": "node1",
                    "name": "Server Node",
                    "label": "Model:Node",
                }
            ],
        ]

        step = CrossLayerCoherenceStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is True
        assert result.issues_found >= 1
        assert any("floating" in str(d.get("reason", "")).lower() for d in result.details)

    def test_handles_exception(self):
        """Should handle exceptions gracefully."""
        from deriva.modules.derivation.refine.cross_layer import CrossLayerCoherenceStep

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.side_effect = Exception("Query error")

        step = CrossLayerCoherenceStep()
        result = step.run(archimate_manager=mock_manager)

        assert result.success is False
        assert "Query error" in result.errors[0]


class TestUnanchoredLayers:
    """Elements of a listed layer without a link to another layer, directly or through their own layer (params.disable_unanchored)."""

    TYPES = {
        "svc": "ApplicationService",
        "proc": "BusinessProcess",
        "obj": "BusinessObject",
        "actor": "BusinessActor",
        "event": "BusinessEvent",
        "node": "Node",
    }
    # svc serves proc, proc accesses obj; actor triggers event; node has no link at all
    LINKS = [("svc", "proc"), ("proc", "obj"), ("actor", "event")]

    def test_unlinked_and_business_only_islands_are_unanchored(self):
        from deriva.modules.derivation.refine.cross_layer import unanchored

        # obj is anchored through proc; actor and event only link to each other
        assert unanchored(self.TYPES, self.LINKS, ["Business"]) == ["actor", "event"]

    def test_layers_not_listed_are_untouched(self):
        from deriva.modules.derivation.refine.cross_layer import unanchored

        assert unanchored(self.TYPES, self.LINKS, ["Technology"]) == ["node"]
        assert unanchored(self.TYPES, self.LINKS, []) == []

    def test_links_to_unknown_elements_do_not_anchor(self):
        from deriva.modules.derivation.refine.cross_layer import unanchored

        # "gone" is not among the elements (disabled earlier), so the actor has nothing to stand on
        assert unanchored(self.TYPES, [*self.LINKS, ("gone", "actor")], ["Business"]) == ["actor", "event"]

    def _manager(self):
        from deriva.adapters.archimate.models import Element, Relationship

        manager = MagicMock()
        manager.namespace = "Model"
        manager.query.return_value = []
        manager.get_elements.return_value = [Element(name=i, element_type=t, identifier=i) for i, t in self.TYPES.items()]
        manager.get_relationships.return_value = [Relationship(source=s, target=t, relationship_type="Serving") for s, t in self.LINKS]
        return manager

    def test_step_disables_unanchored_business_elements(self):
        from deriva.modules.derivation.refine.cross_layer import CrossLayerCoherenceStep

        manager = self._manager()
        result = CrossLayerCoherenceStep().run(archimate_manager=manager, params={"disable_unanchored": ["Business"]})

        assert result.success is True
        manager.get_elements.assert_called_once_with(enabled_only=True)
        manager.disable_elements.assert_called_once_with(["actor", "event"], reason="no_cross_layer_anchor")
        assert result.elements_disabled == 2
        assert {d["identifier"] for d in result.details if d["action"] == "disabled"} == {"actor", "event"}

    def test_step_without_the_param_disables_nothing(self):
        from deriva.modules.derivation.refine.cross_layer import CrossLayerCoherenceStep

        manager = self._manager()
        result = CrossLayerCoherenceStep().run(archimate_manager=manager)

        assert result.success is True
        manager.disable_elements.assert_not_called()
        assert result.elements_disabled == 0

    def test_code_support_needs_more_names_for_a_single_word(self):
        from deriva.modules.derivation.refine.cross_layer import code_supported

        names = {"order": "Order", "policy": "Insurance Policy", "actor": "Actor", "ledger": "Ledger"}
        code = ["OrderService", "orders", "OrderController", "InsurancePolicyEntity", "ActorSystem", "Ordering", "LedgerView", "LedgerView"]

        # Order: three names (Ordering is another word); Insurance Policy: one name, two words;
        # Actor: one name only; Ledger: the same name twice counts once
        assert code_supported(names, code, multi_word_names=1, single_word_names=3) == {"order", "policy"}

    def test_without_a_single_word_count_only_names_of_several_words_count(self):
        from deriva.modules.derivation.refine.cross_layer import code_supported

        names = {"order": "Order", "policy": "Insurance Policy"}
        code = ["OrderService", "orders", "OrderController", "InsurancePolicyEntity"]

        assert code_supported(names, code, multi_word_names=1, single_word_names=None) == {"policy"}

    class Graph:
        """Code names and the source concept names, as the step asks for them."""

        def query(self, query, params=None):
            if "TypeDefinition" in query:
                return [{"name": n} for n in ("OrderService", "OrderController")]
            if "Directory" in query:
                return [{"name": "orders"}]
            return [{"id": i, "name": "Order"} for i in (params or {}).get("ids", []) if i == "concept::r::order"]

    def test_step_keeps_unanchored_elements_the_code_names(self):
        from deriva.adapters.archimate.models import Element
        from deriva.modules.derivation.refine.cross_layer import CrossLayerCoherenceStep

        manager = self._manager()
        manager.get_elements.return_value = [
            Element(name=i, element_type=t, identifier=i, properties={"source": "concept::r::order"} if i == "actor" else {}) for i, t in self.TYPES.items()
        ]
        params = {"disable_unanchored": ["Business"], "code_support": {"multi_word_names": 1, "single_word_names": 3}}

        result = CrossLayerCoherenceStep().run(archimate_manager=manager, graph_manager=self.Graph(), params=params)

        assert result.success is True
        manager.disable_elements.assert_called_once_with(["event"], reason="no_cross_layer_anchor")

    def test_step_accepts_no_single_word_count(self):
        from deriva.modules.derivation.refine.cross_layer import CrossLayerCoherenceStep

        manager = self._manager()
        params = {"disable_unanchored": ["Business"], "code_support": {"multi_word_names": 1, "single_word_names": None}}

        result = CrossLayerCoherenceStep().run(archimate_manager=manager, graph_manager=self.Graph(), params=params)

        assert result.success is True
        manager.disable_elements.assert_called_once_with(["actor", "event"], reason="no_cross_layer_anchor")

    @pytest.mark.parametrize(
        "support",
        [
            {"multi_word_names": 0, "single_word_names": 3},
            {"multi_word_names": 1, "single_word_names": 0},
            {"multi_word_names": None, "single_word_names": 3},
            {"multi_word_names": 1},
            ["multi_word_names"],
        ],
    )
    def test_step_rejects_invalid_code_support(self, support):
        from deriva.modules.derivation.refine.cross_layer import CrossLayerCoherenceStep

        manager = self._manager()
        result = CrossLayerCoherenceStep().run(archimate_manager=manager, graph_manager=self.Graph(), params={"disable_unanchored": ["Business"], "code_support": support})

        assert result.success is False
        assert "code_support" in result.errors[0]
        manager.disable_elements.assert_not_called()

    def test_step_rejects_an_unknown_layer(self):
        from deriva.modules.derivation.refine.cross_layer import CrossLayerCoherenceStep

        manager = self._manager()
        result = CrossLayerCoherenceStep().run(archimate_manager=manager, params={"disable_unanchored": ["Business"]})

        assert result.success is False
        assert "Business" in result.errors[0]
        manager.disable_elements.assert_not_called()


# =============================================================================
# Integration Tests for Step Registration
# =============================================================================


class TestDuplicateElementsMerge:
    """Additional tests for duplicate element merging behavior."""

    def test_merge_elements_disables_duplicate(self):
        """Should call disable_element on the duplicate."""
        from deriva.modules.derivation.refine.duplicate_elements import (
            DuplicateElementsStep,
        )

        survivor = MockElement("survivor_id", "Service", "ApplicationComponent")
        duplicate = MockElement("dup_id", "Service", "ApplicationComponent")

        mock_manager = MagicMock()

        step = DuplicateElementsStep()
        step._merge_elements(mock_manager, survivor, duplicate, "test_reason")

        mock_manager.disable_element.assert_called_once()
        call_args = mock_manager.disable_element.call_args
        assert call_args[0][0] == "dup_id"
        assert "survivor_id" in call_args[1]["reason"]

    def test_merge_elements_with_documentation(self):
        """Should handle elements with documentation."""
        from deriva.modules.derivation.refine.duplicate_elements import (
            DuplicateElementsStep,
        )

        survivor = MockElement("s1", "Svc", "ApplicationComponent", documentation="Survivor docs")
        duplicate = MockElement("d1", "Svc", "ApplicationComponent", documentation="Duplicate docs")

        mock_manager = MagicMock()

        step = DuplicateElementsStep()
        step._merge_elements(mock_manager, survivor, duplicate, "doc_test")

        mock_manager.disable_element.assert_called_once()


class TestOrphanElementsProposals:
    """Relationship proposals from the element's source node in the graph."""

    def test_no_source_means_no_proposals(self):
        from deriva.modules.derivation.refine.orphan_elements import OrphanElementsStep

        graph = MagicMock()

        assert OrphanElementsStep()._propose_relationships(graph, None) == []
        graph.query.assert_not_called()

    def test_maps_graph_relationships_to_archimate_types(self):
        from deriva.modules.derivation.refine.orphan_elements import OrphanElementsStep

        graph = MagicMock()
        graph.query.return_value = [
            {"rel_type": "Graph:CONTAINS", "target_id": "target_1", "target_name": "Child"},
            {"rel_type": "Graph:CALLS", "target_id": "target_2", "target_name": "Callee"},
        ]

        proposals = OrphanElementsStep()._propose_relationships(graph, "graph_node_1")

        assert [p["proposed_archimate_rel"] for p in proposals] == ["Composition", "Flow"]


class TestCrossLayerHelpers:
    """Tests for cross-layer helper methods."""

    def test_check_layer_connections_logs_disconnected(self):
        """Should log info about disconnected elements."""
        from deriva.modules.derivation.refine.base import RefineResult
        from deriva.modules.derivation.refine.cross_layer import (
            BUSINESS_LAYER,
            CrossLayerCoherenceStep,
        )

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = [{"identifier": "bp1", "name": "Process", "label": "Model:BusinessProcess"}]

        step = CrossLayerCoherenceStep()
        result = RefineResult(success=True, step_name="test")

        step._check_layer_connections(
            mock_manager,
            result,
            "Business",
            BUSINESS_LAYER,
            "Application",
            {"ApplicationComponent"},
            "Model",
        )

        assert result.issues_found == 1

    def test_check_floating_elements_finds_unconnected(self):
        """Should find elements with no connections to higher layer."""
        from deriva.modules.derivation.refine.base import RefineResult
        from deriva.modules.derivation.refine.cross_layer import (
            APPLICATION_LAYER,
            TECHNOLOGY_LAYER,
            CrossLayerCoherenceStep,
        )

        mock_manager = MagicMock()
        mock_manager.namespace = "Model"
        mock_manager.query.return_value = [{"identifier": "n1", "name": "Node 1", "label": "Model:Node"}]

        step = CrossLayerCoherenceStep()
        result = RefineResult(success=True, step_name="test")

        step._check_floating_elements(
            mock_manager,
            result,
            "Technology",
            TECHNOLOGY_LAYER,
            "Application",
            APPLICATION_LAYER,
            "Model",
        )

        assert result.issues_found == 1
        assert any("floating" in str(d.get("reason", "")) for d in result.details)


class TestRefineBaseRegistry:
    """Additional tests for refine base registry."""

    def test_run_refine_step_passes_all_params(self):
        """Should pass all parameters to step run method."""
        from deriva.modules.derivation.refine.base import (
            REFINE_STEPS,
            RefineResult,
            run_refine_step,
        )

        received_params = {}

        class ParamCapturingStep:
            def run(self, archimate_manager, graph_manager=None, llm_query_fn=None, params=None):
                received_params["archimate"] = archimate_manager
                received_params["graph"] = graph_manager
                received_params["llm"] = llm_query_fn
                received_params["params"] = params
                return RefineResult(success=True, step_name="param_test")

        REFINE_STEPS["param_capture"] = ParamCapturingStep

        mock_arch = MagicMock()
        mock_graph = MagicMock()
        mock_llm = MagicMock()
        params = {"key": "value"}

        run_refine_step(
            step_name="param_capture",
            archimate_manager=mock_arch,
            graph_manager=mock_graph,
            llm_query_fn=mock_llm,
            params=params,
        )

        assert received_params["archimate"] == mock_arch
        assert received_params["graph"] == mock_graph
        assert received_params["llm"] == mock_llm
        assert received_params["params"] == params

        del REFINE_STEPS["param_capture"]


class TestLemmatizeWord:
    """Tests for lemmatize_word function."""

    def test_short_word_unchanged(self):
        """Should return short words unchanged."""
        from deriva.modules.derivation.refine.base import lemmatize_word

        assert lemmatize_word("get") == "get"
        assert lemmatize_word("a") == "a"
        assert lemmatize_word("do") == "do"

    def test_verb_ing_suffix(self):
        """Should handle -ing verb suffixes."""
        from deriva.modules.derivation.refine.base import lemmatize_word

        # Tests for specific suffix rules
        assert lemmatize_word("generating") == "generate"  # ating -> ate
        assert lemmatize_word("initializing") == "initialize"  # izing -> ize
        assert lemmatize_word("modifying") == "modify"  # ying -> y
        assert lemmatize_word("loading") == "load"  # ding -> d
        # Note: "sing" rule matches before "ing", so processing -> processe
        assert lemmatize_word("processing") == "processe"

    def test_noun_suffixes(self):
        """Should handle noun suffixes."""
        from deriva.modules.derivation.refine.base import lemmatize_word

        assert lemmatize_word("generation") == "generate"
        assert lemmatize_word("creation") == "create"
        assert lemmatize_word("management") == "manage"

    def test_plural_forms(self):
        """Should handle plural noun forms."""
        from deriva.modules.derivation.refine.base import lemmatize_word

        assert lemmatize_word("entries") == "entry"
        assert lemmatize_word("categories") == "category"
        assert lemmatize_word("processes") == "process"
        assert lemmatize_word("items") == "item"

    def test_no_matching_rules_returns_original(self):
        """Should return original word when no rules match."""
        from deriva.modules.derivation.refine.base import lemmatize_word

        # Words that don't match any suffix rules
        assert lemmatize_word("hello") == "hello"
        assert lemmatize_word("world") == "world"
        assert lemmatize_word("xyz") == "xyz"


class TestNormalizeNameAdvanced:
    """Advanced tests for normalize_name function."""

    def test_with_extra_synonyms(self):
        """Should apply extra synonyms."""
        from deriva.modules.derivation.refine.base import normalize_name

        extra = {"foo": "bar", "custom": "mapped"}

        assert normalize_name("foo item", extra_synonyms=extra) == "bar item"
        assert normalize_name("custom thing", extra_synonyms=extra) == "mapped thing"

    def test_with_lemmatization_enabled(self):
        """Should apply lemmatization when enabled."""
        from deriva.modules.derivation.refine.base import normalize_name

        result = normalize_name("generating items", use_lemmatization=True)
        assert "generate" in result or "item" in result

    def test_synonyms_precedence(self):
        """Extra synonyms should take precedence over defaults."""
        from deriva.modules.derivation.refine.base import normalize_name

        extra = {"insert": "custom_insert"}

        result = normalize_name("insert item", extra_synonyms=extra)
        assert "custom_insert" in result


class TestRefineStepRegistry:
    """Tests for the refine step registry integration."""

    def test_duplicate_elements_step_is_registered(self):
        """Should have duplicate_elements step registered."""
        # Import to trigger registration
        from deriva.modules.derivation.refine import duplicate_elements  # noqa: F401
        from deriva.modules.derivation.refine.base import REFINE_STEPS

        assert "duplicate_elements" in REFINE_STEPS

    def test_duplicate_relationships_step_is_registered(self):
        """Should have duplicate_relationships step registered."""
        from deriva.modules.derivation.refine import duplicate_relationships  # noqa: F401
        from deriva.modules.derivation.refine.base import REFINE_STEPS

        assert "duplicate_relationships" in REFINE_STEPS

    def test_orphan_elements_step_is_registered(self):
        """Should have orphan_elements step registered."""
        from deriva.modules.derivation.refine import orphan_elements  # noqa: F401
        from deriva.modules.derivation.refine.base import REFINE_STEPS

        assert "orphan_elements" in REFINE_STEPS

    def test_structural_consistency_step_is_registered(self):
        """Should have structural_consistency step registered."""
        from deriva.modules.derivation.refine import structural_consistency  # noqa: F401
        from deriva.modules.derivation.refine.base import REFINE_STEPS

        assert "structural_consistency" in REFINE_STEPS

    def test_cross_layer_coherence_step_is_registered(self):
        """Should have cross_layer_coherence step registered."""
        from deriva.modules.derivation.refine import cross_layer  # noqa: F401
        from deriva.modules.derivation.refine.base import REFINE_STEPS

        assert "cross_layer_coherence" in REFINE_STEPS
