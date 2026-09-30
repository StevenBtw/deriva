"""Tests for stability analysis functions.

Tests the stability analysis module which computes:
- Per-type stability breakdown across benchmark runs
- Phase-level stability reports (extraction/derivation)
- Stability pattern identification
- Aggregate metrics across repositories
"""

from __future__ import annotations

from deriva.modules.analysis.stability_analysis import (
    aggregate_stability_metrics,
    compute_phase_stability,
    compute_type_breakdown,
    extract_edge_type,
    extract_element_type,
    extract_node_type,
    extract_relationship_type,
    identify_stability_patterns,
)
from deriva.modules.analysis.types import PhaseStabilityReport, StabilityBreakdown


class TestExtractElementType:
    """Tests for element type extraction from identifiers."""

    def test_application_component_prefix(self):
        """Should recognize ac_ prefix as ApplicationComponent."""
        assert extract_element_type("ac_user_service") == "ApplicationComponent"

    def test_business_process_prefix(self):
        """Should recognize bp_ prefix as BusinessProcess."""
        assert extract_element_type("bp_order_process") == "BusinessProcess"

    def test_data_object_prefix(self):
        """Should recognize do_ prefix as DataObject."""
        assert extract_element_type("do_customer_record") == "DataObject"

    def test_case_insensitive(self):
        """Should handle uppercase prefixes."""
        assert extract_element_type("AC_UserService") == "ApplicationComponent"

    def test_unknown_prefix(self):
        """Should return Unknown for unrecognized prefixes."""
        assert extract_element_type("xyz_something") == "Unknown"

    def test_long_prefix_pattern(self):
        """Should recognize multi-part prefixes like app_comp_."""
        assert extract_element_type("app_comp_service") == "ApplicationComponent"

    def test_business_object_prefix(self):
        """Should recognize bo_ prefix as BusinessObject."""
        assert extract_element_type("bo_customer") == "BusinessObject"


class TestExtractNodeType:
    """Tests for node type extraction from graph node identifiers."""

    def test_graph_prefix_pattern(self):
        """Should extract type from Graph:Type:id pattern."""
        assert extract_node_type("Graph:BusinessConcept:xyz") == "BusinessConcept"

    def test_abbreviated_prefix(self):
        """Should recognize bc_ prefix as BusinessConcept."""
        assert extract_node_type("bc_user_management") == "BusinessConcept"

    def test_function_prefix(self):
        """Should recognize fn_ prefix as Function."""
        assert extract_node_type("fn_calculate_total") == "Function"

    def test_unknown_pattern(self):
        """Should return Unknown for unrecognized patterns."""
        assert extract_node_type("some_random_id") == "Unknown"


class TestExtractEdgeType:
    """Tests for edge type extraction from edge identifiers."""

    def test_contains_pattern(self):
        """Should extract CONTAINS from TYPE:source:target pattern."""
        assert extract_edge_type("CONTAINS:node1:node2") == "CONTAINS"

    def test_depends_on_pattern(self):
        """Should extract DEPENDS_ON from pattern."""
        assert extract_edge_type("DEPENDS_ON:a:b") == "DEPENDS_ON"

    def test_imports_pattern(self):
        """Should extract IMPORTS from pattern."""
        assert extract_edge_type("IMPORTS:module:other") == "IMPORTS"

    def test_type_in_id(self):
        """Should find edge type anywhere in ID."""
        assert extract_edge_type("edge_CONTAINS_123") == "CONTAINS"

    def test_unknown_edge(self):
        """Should return Unknown for unrecognized edge types."""
        assert extract_edge_type("some:random:edge") == "Unknown"


class TestExtractRelationshipType:
    """Tests for ArchiMate relationship type extraction."""

    def test_composition_pattern(self):
        """Should extract Composition relationship type."""
        assert extract_relationship_type("Composition:elem1:elem2") == "Composition"

    def test_serving_pattern(self):
        """Should extract Serving relationship type."""
        assert extract_relationship_type("Serving:service:consumer") == "Serving"

    def test_case_normalization(self):
        """Should normalize case for relationship types."""
        assert extract_relationship_type("COMPOSITION:a:b") == "Composition"

    def test_type_in_id(self):
        """Should find relationship type anywhere in ID."""
        assert extract_relationship_type("rel_composition_123") == "Composition"

    def test_unknown_relationship(self):
        """Should return Unknown for unrecognized types."""
        assert extract_relationship_type("random:a:b") == "Unknown"


class TestComputeTypeBreakdown:
    """Tests for per-type stability breakdown computation."""

    def test_empty_input(self):
        """Should return empty list for empty input."""
        result = compute_type_breakdown({}, extract_element_type, "derivation")
        assert result == []

    def test_all_stable_items(self):
        """Should identify items present in all runs as stable."""
        objects_by_run = {
            "run1": {"ac_service1", "ac_service2"},
            "run2": {"ac_service1", "ac_service2"},
            "run3": {"ac_service1", "ac_service2"},
        }
        result = compute_type_breakdown(objects_by_run, extract_element_type, "derivation")

        assert len(result) == 1  # One type: ApplicationComponent
        breakdown = result[0]
        assert breakdown.item_type == "ApplicationComponent"
        assert breakdown.stable_count == 2
        assert breakdown.unstable_count == 0
        assert breakdown.consistency_score == 1.0

    def test_mixed_stability(self):
        """Should correctly identify stable and unstable items."""
        objects_by_run = {
            "run1": {"ac_stable", "ac_unstable1"},
            "run2": {"ac_stable", "ac_unstable2"},
            "run3": {"ac_stable"},
        }
        result = compute_type_breakdown(objects_by_run, extract_element_type, "derivation")

        breakdown = result[0]
        assert breakdown.stable_count == 1  # ac_stable
        assert breakdown.unstable_count == 2  # ac_unstable1, ac_unstable2
        assert "ac_stable" in breakdown.stable_items
        assert "ac_unstable1" in breakdown.unstable_items
        assert "ac_unstable2" in breakdown.unstable_items

    def test_multiple_types(self):
        """Should create separate breakdowns for different types."""
        objects_by_run = {
            "run1": {"ac_component", "bp_process"},
            "run2": {"ac_component", "bp_process"},
        }
        result = compute_type_breakdown(objects_by_run, extract_element_type, "derivation")

        assert len(result) == 2
        types = {b.item_type for b in result}
        assert "ApplicationComponent" in types
        assert "BusinessProcess" in types

    def test_phase_attribute(self):
        """Should set correct phase attribute."""
        objects_by_run = {"run1": {"ac_x"}}
        result = compute_type_breakdown(objects_by_run, extract_element_type, "extraction")
        assert result[0].phase == "extraction"


class TestComputePhaseStability:
    """Tests for phase-level stability report computation."""

    def test_extraction_phase_only(self):
        """Should create extraction report when only extraction data provided."""
        nodes = {"run1": {"bc_concept1"}, "run2": {"bc_concept1"}}
        edges = {"run1": {"CONTAINS:a:b"}, "run2": {"CONTAINS:a:b"}}

        result = compute_phase_stability(
            nodes_by_run=nodes,
            edges_by_run=edges,
            elements_by_run=None,
            relationships_by_run=None,
            repository="test-repo",
            model="gpt-4",
        )

        assert "extraction" in result
        assert "derivation" not in result
        assert result["extraction"].repository == "test-repo"
        assert result["extraction"].model == "gpt-4"
        assert result["extraction"].total_runs == 2

    def test_derivation_phase_only(self):
        """Should create derivation report when only derivation data provided."""
        elements = {"run1": {"ac_service"}, "run2": {"ac_service"}}
        relationships = {"run1": {"Serving:a:b"}, "run2": {"Serving:a:b"}}

        result = compute_phase_stability(
            nodes_by_run=None,
            edges_by_run=None,
            elements_by_run=elements,
            relationships_by_run=relationships,
            repository="repo",
            model="claude",
        )

        assert "derivation" in result
        assert "extraction" not in result
        assert result["derivation"].phase == "derivation"

    def test_both_phases(self):
        """Should create reports for both phases when all data provided."""
        result = compute_phase_stability(
            nodes_by_run={"run1": {"node1"}},
            edges_by_run={"run1": {"edge1"}},
            elements_by_run={"run1": {"ac_elem"}},
            relationships_by_run={"run1": {"Serving:a:b"}},
            repository="repo",
            model="model",
        )

        assert "extraction" in result
        assert "derivation" in result

    def test_overall_consistency_calculation(self):
        """Should calculate overall consistency from type breakdowns."""
        # All items stable -> 100% consistency
        elements = {
            "run1": {"ac_a", "bp_b"},
            "run2": {"ac_a", "bp_b"},
        }

        result = compute_phase_stability(
            nodes_by_run=None,
            edges_by_run=None,
            elements_by_run=elements,
            relationships_by_run=None,
            repository="repo",
            model="model",
        )

        assert result["derivation"].overall_consistency == 1.0


class TestIdentifyStabilityPatterns:
    """Tests for stability pattern identification."""

    def test_highly_stable_types(self):
        """Should identify types with high consistency as highly stable."""
        breakdowns = [
            StabilityBreakdown(
                item_type="ApplicationComponent",
                phase="derivation",
                total_count=10,
                stable_count=10,
                unstable_count=0,
                consistency_score=1.0,
                stable_items=["ac_1", "ac_2"],
                unstable_items={},
            )
        ]

        result = identify_stability_patterns(breakdowns)

        assert any("ApplicationComponent" in t for t in result["highly_stable_types"])

    def test_unstable_types(self):
        """Should identify types with low consistency as unstable."""
        breakdowns = [
            StabilityBreakdown(
                item_type="DataObject",
                phase="derivation",
                total_count=10,
                stable_count=2,
                unstable_count=8,
                consistency_score=0.2,
                stable_items=["do_1"],
                unstable_items={"do_2": 1, "do_3": 1},
            )
        ]

        result = identify_stability_patterns(breakdowns, low_threshold=0.5)

        assert any("DataObject" in t for t in result["unstable_types"])

    def test_custom_thresholds(self):
        """Should respect custom thresholds."""
        breakdowns = [
            StabilityBreakdown(
                item_type="Test",
                phase="derivation",
                total_count=10,
                stable_count=8,
                unstable_count=2,
                consistency_score=0.8,
                stable_items=[],
                unstable_items={},
            )
        ]

        # With default threshold (0.9), this is not highly stable
        result = identify_stability_patterns(breakdowns)
        assert not any("Test" in t for t in result["highly_stable_types"])

        # With lower threshold (0.7), this is highly stable
        result = identify_stability_patterns(breakdowns, high_threshold=0.7)
        assert any("Test" in t for t in result["highly_stable_types"])


class TestAggregateStabilityMetrics:
    """Tests for aggregate metrics computation across repositories."""

    def test_empty_input(self):
        """Should handle empty input gracefully."""
        result = aggregate_stability_metrics({})

        assert result["avg_extraction_consistency"] == 0.0
        assert result["avg_derivation_consistency"] == 0.0
        assert result["best_element_types"] == []
        assert result["worst_element_types"] == []

    def test_single_repo_metrics(self):
        """Should compute metrics for single repository."""
        stability_reports = {
            "repo1": {
                "derivation": PhaseStabilityReport(
                    phase="derivation",
                    repository="repo1",
                    model="gpt-4",
                    total_runs=3,
                    overall_consistency=0.85,
                    node_breakdown=[],
                    edge_breakdown=[],
                    element_breakdown=[
                        StabilityBreakdown(
                            item_type="ApplicationComponent",
                            phase="derivation",
                            total_count=5,
                            stable_count=4,
                            unstable_count=1,
                            consistency_score=0.8,
                            stable_items=[],
                            unstable_items={},
                        )
                    ],
                    relationship_breakdown=[],
                )
            }
        }

        result = aggregate_stability_metrics(stability_reports)

        assert result["avg_derivation_consistency"] == 0.85
        assert len(result["best_element_types"]) == 1
        assert result["best_element_types"][0][0] == "ApplicationComponent"

    def test_multiple_repos_averaging(self):
        """Should average metrics across multiple repositories."""
        stability_reports = {
            "repo1": {
                "derivation": PhaseStabilityReport(
                    phase="derivation",
                    repository="repo1",
                    model="gpt-4",
                    total_runs=3,
                    overall_consistency=0.9,
                    node_breakdown=[],
                    edge_breakdown=[],
                    element_breakdown=[],
                    relationship_breakdown=[],
                )
            },
            "repo2": {
                "derivation": PhaseStabilityReport(
                    phase="derivation",
                    repository="repo2",
                    model="gpt-4",
                    total_runs=3,
                    overall_consistency=0.7,
                    node_breakdown=[],
                    edge_breakdown=[],
                    element_breakdown=[],
                    relationship_breakdown=[],
                )
            },
        }

        result = aggregate_stability_metrics(stability_reports)

        # Average of 0.9 and 0.7 = 0.8
        assert result["avg_derivation_consistency"] == 0.8

    def test_best_worst_element_types_sorting(self):
        """Should sort element types by consistency score."""
        stability_reports = {
            "repo1": {
                "derivation": PhaseStabilityReport(
                    phase="derivation",
                    repository="repo1",
                    model="gpt-4",
                    total_runs=3,
                    overall_consistency=0.8,
                    node_breakdown=[],
                    edge_breakdown=[],
                    element_breakdown=[
                        StabilityBreakdown(
                            item_type="HighType",
                            phase="derivation",
                            total_count=10,
                            stable_count=9,
                            unstable_count=1,
                            consistency_score=0.9,
                            stable_items=[],
                            unstable_items={},
                        ),
                        StabilityBreakdown(
                            item_type="LowType",
                            phase="derivation",
                            total_count=10,
                            stable_count=3,
                            unstable_count=7,
                            consistency_score=0.3,
                            stable_items=[],
                            unstable_items={},
                        ),
                    ],
                    relationship_breakdown=[],
                )
            }
        }

        result = aggregate_stability_metrics(stability_reports)

        # Best should be sorted descending (highest first)
        assert result["best_element_types"][0][0] == "HighType"
        assert result["best_element_types"][0][1] == 0.9

        # Worst should be the lowest
        assert result["worst_element_types"][0][0] == "LowType"


class TestAnswerStability:
    """Raw LLM answer stability: the same prompt answered identically in every run, per step.

    Reported next to output consistency, so voting or post-processing cannot hide LLM variance.
    """

    def test_counts_prompts_answered_identically_in_every_run(self):
        from deriva.modules.analysis import compute_answer_stability

        runs = {
            "r1": {("Naming", "k1"): ["a"], ("Naming", "k2"): ["b"], ("Concepts", "k3"): ["c"]},
            "r2": {("Naming", "k1"): ["a"], ("Naming", "k2"): ["x"], ("Concepts", "k3"): ["c"]},
            "r3": {("Naming", "k1"): ["a"], ("Naming", "k2"): ["b"], ("Concepts", "k3"): ["c"], ("Concepts", "k4"): ["d"]},
        }

        result = {s.step: (s.prompts, s.identical, s.score) for s in compute_answer_stability(runs)}

        # k4 was not asked in every run, so it does not count
        assert result == {"Concepts": (1, 1, 1.0), "Naming": (2, 1, 0.5)}

    def test_repeated_prompts_compare_as_multisets(self):
        from deriva.modules.analysis import compute_answer_stability

        runs = {"r1": {("S", "k"): ["a", "b"]}, "r2": {("S", "k"): ["b", "a"]}}

        (stability,) = compute_answer_stability(runs)

        assert (stability.prompts, stability.identical) == (1, 1)

    def test_fewer_than_two_runs_measure_nothing(self):
        from deriva.modules.analysis import compute_answer_stability

        assert compute_answer_stability({"r1": {("S", "k"): ["a"]}}) == []


class TestDecisionContent:
    """Answers are compared on their decisions: free text and scores are left out."""

    def test_free_text_and_scores_do_not_count(self):
        from deriva.modules.analysis import decision_content

        first = '{"items": [{"name": "Alpha", "kind": "entity", "description": "One wording", "confidence": 0.9}]}'
        second = '{"items":[{"confidence":0.7,"kind":"entity","name":"Alpha","description":"Another wording"}]}'

        assert decision_content(first) == decision_content(second)

    def test_documentation_does_not_count(self):
        from deriva.modules.analysis import decision_content

        assert decision_content('{"name": "Alpha", "documentation": "x"}') == decision_content('{"name": "Alpha", "documentation": "y"}')

    def test_a_different_decision_counts(self):
        from deriva.modules.analysis import decision_content

        assert decision_content('{"items": [{"name": "Alpha", "kind": "entity"}]}') != decision_content('{"items": [{"name": "Alpha", "kind": "process"}]}')

    def test_text_that_is_not_json_is_compared_as_is(self):
        from deriva.modules.analysis import decision_content

        assert decision_content("plain answer") == "plain answer"


class TestStepOutputConsistency:
    """One step repeated on a fixed input: are its outputs (and their properties) the same every run?"""

    def test_presence_counts_objects_in_every_run(self):
        from deriva.modules.analysis import compare_step_outputs

        runs = [
            {("Concept", "a"): {}, ("Concept", "b"): {}},
            {("Concept", "a"): {}},
            {("Concept", "a"): {}, ("Concept", "c"): {}},
        ]

        result = compare_step_outputs(runs)

        assert (result.present, result.total, result.counts) == (1, 3, [2, 1, 2])
        assert result.presence_score == 1 / 3

    def test_identical_needs_the_same_properties_in_every_run(self):
        from deriva.modules.analysis import compare_step_outputs

        runs = [
            {("Concept", "a"): {"kind": "entity", "score": 0.9}, ("Concept", "b"): {"kind": "actor"}},
            {("Concept", "a"): {"kind": "process", "score": 0.8}, ("Concept", "b"): {"kind": "actor"}},
        ]

        result = compare_step_outputs(runs)

        assert (result.present, result.identical) == (2, 1)
        assert result.exact_score == 0.5
        assert result.property_differences == {"kind": 1, "score": 1}

    def test_unscored_properties_are_reported_but_keep_an_object_exact(self):
        from deriva.modules.analysis import compare_step_outputs

        runs = [
            {("E", "a"): {"name": "A", "note": "one"}, ("E", "b"): {"name": "B"}},
            {("E", "a"): {"name": "A", "note": "two"}, ("E", "b"): {"name": "C"}},
        ]

        result = compare_step_outputs(runs, unscored=frozenset({"note"}))

        assert (result.identical, result.groups["E"].identical) == (1, 1)
        assert result.property_differences == {"name": 1, "note": 1}

    def test_a_property_missing_in_one_run_differs(self):
        from deriva.modules.analysis import compare_step_outputs

        result = compare_step_outputs([{("E", "a"): {"x": 1}}, {("E", "a"): {}}])

        assert result.property_differences == {"x": 1}

    def test_groups_are_scored_separately(self):
        from deriva.modules.analysis import compare_step_outputs

        runs = [{("Concept", "a"): {}, ("Edge", "e1"): {}}, {("Concept", "a"): {}}]

        result = compare_step_outputs(runs)

        assert (result.groups["Concept"].present, result.groups["Concept"].total) == (1, 1)
        assert (result.groups["Edge"].present, result.groups["Edge"].total) == (0, 1)

    def test_no_output_in_any_run_is_consistent(self):
        from deriva.modules.analysis import compare_step_outputs

        result = compare_step_outputs([{}, {}, {}])

        assert (result.presence_score, result.exact_score, result.counts) == (1.0, 1.0, [0, 0, 0])

    def test_to_dict_carries_scores_and_groups(self):
        from deriva.modules.analysis import compare_step_outputs

        data = compare_step_outputs([{("E", "a"): {}}, {("E", "a"): {}}]).to_dict()

        assert (data["presence_score"], data["exact_score"], data["groups"]["E"]["present"]) == (1.0, 1.0, 1)


class TestDecisionStability:
    """Per-item decisions of a classification step (one label per term): the same decision in every run?"""

    def test_items_with_the_same_decision_in_every_run(self):
        from deriva.modules.analysis import decision_stability

        runs = [{"a": "x", "b": "y", "c": None}, {"a": "x", "b": "z", "c": None}, {"a": "x", "b": "y"}]

        result = decision_stability(runs)

        # a is stable; b changes; c was skipped twice and missing from the third run's list
        assert (result.items, result.stable) == (3, 1)
        assert result.score == 1 / 3
        assert result.to_dict() == {"items": 3, "stable": 1, "score": 1 / 3}

    def test_a_decision_skipped_in_every_run_is_stable(self):
        from deriva.modules.analysis import decision_stability

        assert decision_stability([{"a": None}, {"a": None}]).stable == 1

    def test_no_items(self):
        from deriva.modules.analysis import decision_stability

        assert decision_stability([{}, {}]).score == 1.0
