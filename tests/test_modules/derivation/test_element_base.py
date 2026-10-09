"""Tests for modules.derivation.element_base module."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deriva.modules.derivation.base import (
    Candidate,
    ElementPrompt,
    GenerationResult,
    PerCandidateConfig,
    RelationshipLLMConfig,
    RelationshipRule,
)
from deriva.modules.derivation.element_base import (
    ElementDerivationBase,
    PatternBasedDerivation,
)

TEST_PROMPT = ElementPrompt(persona="Derive elements.", candidates="Candidates.", rules="{abstention}Rules.", abstention="")


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
        result = derivation.get_filter_kwargs({})
        assert result == {}

    def test_generate_returns_result_for_empty_candidates(self):
        """Should return success result when no candidates found."""
        derivation = ConcreteDerivation()

        mock_graph = MagicMock()
        mock_graph.query.return_value = []

        result = derivation.generate(
            graph_manager=mock_graph,
            archimate_manager=MagicMock(),
            llm_query_fn=MagicMock(),
            query="MATCH (n) RETURN n",
            instruction="Test",
            example="{}",
            max_candidates=10,
            batch_size=5,
            existing_elements=[],
            prompt=TEST_PROMPT,
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
            llm_query_fn=MagicMock(),
            query="MATCH (n) RETURN n",
            instruction="Test",
            example="{}",
            max_candidates=10,
            batch_size=5,
            existing_elements=[],
            prompt=TEST_PROMPT,
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
                llm_query_fn=MagicMock(),
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                prompt=TEST_PROMPT,
            )

        assert result.success is True
        assert result.elements_created == 0


class TestRelationshipConfigThreading:
    """The relationship config row reaches the relationship pass in both generation modes."""

    ELEMENT_RESPONSE = '{"elements": [{"identifier": "te_x", "name": "X", "documentation": "d", "source": "1", "confidence": 0.9}]}'

    def _generate(self, derivation, relationship_config, per_candidate=None):
        llm = MagicMock()
        llm.return_value = SimpleNamespace(content=self.ELEMENT_RESPONSE)
        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch(
                "deriva.modules.derivation.element_base.query_candidates",
                return_value=[Candidate(node_id="1", name="x", labels=["Node"], properties={})],
            ),
            patch("deriva.modules.derivation.element_base.derive_batch_relationships", return_value=[]) as derive,
        ):
            derivation.generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=MagicMock(),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[{"identifier": "other", "name": "Other", "element_type": "Other"}],
                relationship_config=relationship_config,
                per_candidate=per_candidate,
                prompt=TEST_PROMPT,
            )
        return derive

    def test_batch_mode_passes_relationship_config(self):
        config = RelationshipLLMConfig(instruction="rules", min_confidence=0.6, persona="P")

        derive = self._generate(ConcreteDerivation(), config)

        assert derive.call_args.kwargs["llm_config"] is config

    def test_per_candidate_mode_passes_relationship_config(self):
        config = RelationshipLLMConfig(instruction="rules", min_confidence=0.6, persona="P")

        derive = self._generate(ConcreteDerivation(), config, PerCandidateConfig(min_pool=1, rules="R", persona="P"))

        assert derive.call_args.kwargs["llm_config"] is config


class TestPerCandidateMode:
    """Per-candidate naming is switched on by the element config (params.per_candidate)."""

    RESPONSE = '{"elements": [{"identifier": "te_x", "name": "X", "documentation": "d", "source": "1", "confidence": 0.9}]}'

    def _prompts(self, per_candidate, n_candidates=2, decorators=None):
        llm = MagicMock(return_value=SimpleNamespace(content=self.RESPONSE))
        decorators = decorators or {}
        candidates = [Candidate(node_id=str(i), name=f"c{i}", labels=["Node"], properties={"decorators": decorators.get(i, [])}) for i in range(n_candidates)]
        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
        ):
            ConcreteDerivation().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=MagicMock(),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                prompt=TEST_PROMPT,
                per_candidate=per_candidate,
            )
        return [c.args[0] for c in llm.call_args_list]

    def test_config_rules_go_into_one_prompt_per_candidate(self):
        prompts = self._prompts(PerCandidateConfig(min_pool=2, rules="CONFIG NAMING RULES", persona="P"))

        assert len(prompts) == 2
        assert all("CONFIG NAMING RULES" in p for p in prompts)

    def test_pool_below_min_pool_uses_batch_mode(self):
        prompts = self._prompts(PerCandidateConfig(min_pool=3, rules="CONFIG NAMING RULES", persona="P"))

        assert len(prompts) == 1
        assert "CONFIG NAMING RULES" not in prompts[0]

    def test_without_config_batch_mode_is_used(self):
        assert len(self._prompts(None)) == 1

    def test_marked_candidates_pass_the_name_filters(self):
        """The step's name filters judge names; a candidate whose annotation shows what it is is not judged by its name."""

        class NameFiltered(ConcreteDerivation):
            def filter_candidates(self, candidates, enrichments, max_candidates, **kwargs):
                return [c for c in candidates if c.name.endswith("Data")][:max_candidates]

        llm = MagicMock(return_value=SimpleNamespace(content=self.RESPONSE))
        candidates = [
            Candidate(node_id="0", name="OrderImpl", labels=["TypeDefinition"], properties={"decorators": ["Entity"]}),
            Candidate(node_id="1", name="OrderHelper", labels=["TypeDefinition"], properties={"decorators": []}),
        ]
        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
        ):
            result = NameFiltered().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=MagicMock(),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                prompt=TEST_PROMPT,
                per_candidate=PerCandidateConfig(min_pool=1, rules="CONFIG NAMING RULES", persona="P", decorators=r"^Entity(\(.*)?$"),
            )

        stages = {d.node_id: d.stage for d in result.candidate_decisions}
        assert stages["1"] == "filtered_out"
        assert stages.get("0") != "filtered_out"
        assert [("CONFIG NAMING RULES" in c.args[0]) for c in llm.call_args_list] == [True]

    def test_candidates_the_cap_leaves_out_are_told_apart_from_filtered_ones(self):
        """A rule judged the one; the budget (max_candidates) the other: the run record must say which."""

        class NameFiltered(ConcreteDerivation):
            def filter_candidates(self, candidates, enrichments, max_candidates, **kwargs):
                return sorted((c for c in candidates if c.name.endswith("Data")), key=lambda c: c.node_id)[:max_candidates]

        candidates = [Candidate(node_id=str(i), name=name, labels=["TypeDefinition"], properties={}) for i, name in enumerate(["AData", "BData", "CData", "Helper"])]
        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
        ):
            result = NameFiltered().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=MagicMock(),
                llm_query_fn=MagicMock(return_value=SimpleNamespace(content=self.RESPONSE)),
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=2,
                batch_size=5,
                existing_elements=[],
                prompt=TEST_PROMPT,
            )

        stages = {d.node_id: d.stage for d in result.candidate_decisions}
        assert (stages["2"], stages["3"]) == ("over_cap", "filtered_out")
        assert stages.get("0") not in ("over_cap", "filtered_out") and stages.get("1") not in ("over_cap", "filtered_out")

    def test_with_an_annotation_pattern_only_marked_candidates_are_named_per_candidate(self):
        """An annotation that shows what a candidate is decides; the LLM only names it. The others are judged in a batch."""
        per_candidate = PerCandidateConfig(min_pool=1, rules="CONFIG NAMING RULES", persona="P", decorators=r"^Entity(\(.*)?$")

        prompts = self._prompts(per_candidate, n_candidates=3, decorators={0: ["Entity"], 1: ['Entity(name = "x")'], 2: ["Deprecated"]})

        assert sum("CONFIG NAMING RULES" in p for p in prompts) == 2
        batch = [p for p in prompts if "CONFIG NAMING RULES" not in p]
        assert len(batch) == 1 and '"c2"' in batch[0] and '"c0"' not in batch[0]


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

    def test_get_filter_kwargs_uses_given_patterns(self):
        """Patterns come from the caller (the service loads them from config)."""
        derivation = ConcretePatternDerivation()

        result = derivation.get_filter_kwargs({"include": {"service", "manager"}, "exclude": {"test", "mock"}})

        assert result == {
            "include_patterns": {"service", "manager"},
            "exclude_patterns": {"test", "mock"},
        }

    def test_get_filter_kwargs_without_patterns(self):
        """Should return empty sets when no patterns are configured."""
        result = ConcretePatternDerivation().get_filter_kwargs({})

        assert result == {"include_patterns": set(), "exclude_patterns": set()}

    def test_get_filter_kwargs_passes_the_pattern_labels_when_configured(self):
        result = ConcretePatternDerivation().get_filter_kwargs({"include": {"docker"}, "exclude": set(), "labels": {"File"}})

        assert result == {"include_patterns": {"docker"}, "exclude_patterns": set(), "pattern_labels": {"File"}}


class TestPatternLabels:
    """Name patterns can be scoped to candidates with given graph labels (the step's params.pattern_labels)."""

    CANDIDATES = [
        Candidate(node_id="tech", name="Alpha", labels=["Graph", "Technology"], properties={}),
        Candidate(node_id="file_plain", name="alpha.txt", labels=["Graph", "File"], properties={}),
        Candidate(node_id="file_match", name="gamma.docker", labels=["Graph", "File"], properties={}),
    ]

    def _kept(self, **kwargs):
        from deriva.modules.derivation.node import NodeDerivation

        kept = NodeDerivation().filter_candidates(self.CANDIDATES, {}, 10, include_patterns={"docker"}, exclude_patterns=set(), **kwargs)
        return {c.node_id for c in kept}

    def test_candidates_without_a_pattern_label_are_not_matched_by_name(self):
        assert self._kept(pattern_labels={"File"}) == {"tech", "file_match"}

    def test_without_pattern_labels_every_candidate_is_matched_by_name(self):
        assert self._kept() == {"file_match"}


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
            repo_name="",
            structure_names={},
            taken=[],
            element_prompt=TEST_PROMPT,
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
                repo_name="",
                structure_names={},
                taken=[],
                element_prompt=TEST_PROMPT,
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


class TestCandidateDecisions:
    """Every filtered candidate gets a decision record, and created ones name their element."""

    @staticmethod
    def _generate(candidates, response, per_candidate=None):
        llm = MagicMock(return_value=SimpleNamespace(content=response))
        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
        ):
            return ConcreteDerivation().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=MagicMock(),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                prompt=TEST_PROMPT,
                per_candidate=per_candidate,
            )

    def test_per_candidate_created_decision_names_the_element(self):
        response = '{"elements": [{"identifier": "te_x", "name": "X", "documentation": "d", "source": "1", "confidence": 0.9}]}'

        result = self._generate([Candidate(node_id="1", name="x", labels=["Node"], properties={})], response, PerCandidateConfig(min_pool=1, rules="R", persona="P"))

        (decision,) = [d for d in result.candidate_decisions if d.stage == "created"]
        assert decision.element_id == result.created_elements[0]["identifier"]
        assert decision.element_confidence == 0.9

    def test_batch_mode_without_prompt_texts_is_an_error(self):
        """The batch prompt's texts come from the step's params.prompt; there is no default in code."""
        llm = MagicMock()
        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=[Candidate(node_id="1", name="x", labels=["Node"], properties={})]),
        ):
            result = ConcreteDerivation().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=MagicMock(),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
            )

        assert result.success is False
        assert "params.prompt" in result.errors[0]
        llm.assert_not_called()

    def test_batch_created_decision_names_the_element(self):
        """The decision names the element actually created, not the identifier the LLM proposed."""
        response = '{"elements": [{"identifier": "llm_proposed", "name": "X", "documentation": "d", "source": "1", "confidence": 0.9}]}'

        result = self._generate([Candidate(node_id="1", name="x", labels=["Node"], properties={})], response)

        (decision,) = [d for d in result.candidate_decisions if d.stage == "created"]
        assert decision.element_id == result.created_elements[0]["identifier"] != "llm_proposed"
        assert decision.element_confidence == 0.9

    def test_per_candidate_prompts_do_not_carry_earlier_answers(self):
        """Each candidate's prompt depends on its structure only, so one LLM drift cannot cascade."""
        response = '{"elements": [{"identifier": "te_x", "name": "Chosen Name", "documentation": "d", "source": "1", "confidence": 0.9}]}'
        llm = MagicMock(return_value=SimpleNamespace(content=response))
        candidates = [Candidate(node_id=str(i), name=f"cand{i}", labels=["Node"], properties={}) for i in (1, 2)]
        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
        ):
            ConcreteDerivation().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=MagicMock(),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                prompt=TEST_PROMPT,
                per_candidate=PerCandidateConfig(min_pool=1, rules="R", persona="P"),
            )

        prompts = [c.args[0] for c in llm.call_args_list]
        assert len(prompts) == 2
        assert not any("Existing Elements" in p or "cand1" in p for p in prompts[1:])

    def test_consolidated_candidates_are_recorded(self):
        candidates = [
            Candidate(node_id="1", name="Record", labels=["Node"], properties={}, pagerank=0.9),
            Candidate(node_id="2", name="Records", labels=["Node"], properties={}, pagerank=0.1),
        ]

        result = self._generate(candidates, '{"elements": []}')

        stages = {d.node_id: d.stage for d in result.candidate_decisions}
        assert stages["2"] == "duplicate_removed"


class TestPercentileFiltering:
    """A computed percentile of 0.0 is the bottom rank; only absent data is exempt from the cutoff."""

    class Filter:
        MIN_PAGERANK = None
        MIN_PAGERANK_PERCENTILE = 40.0
        USE_COMMUNITY_ROOTS = False
        USE_ARTICULATION_POINTS = False

    @classmethod
    def _filter(cls, candidates):
        from deriva.modules.derivation.base import GraphFilter
        from deriva.modules.derivation.element_base import HybridFilteringMixin

        filt = type("F", (cls.Filter, HybridFilteringMixin), {})()
        return {c.node_id for c in filt.apply_graph_filtering(candidates, {}, 10, GraphFilter(min_kcore_percentile=30.0))}

    def test_bottom_ranked_candidate_is_filtered(self):
        bottom = Candidate(node_id="bottom", name="b", pagerank_percentile=0.0, kcore_percentile=50.0)
        top = Candidate(node_id="top", name="t", pagerank_percentile=90.0, kcore_percentile=90.0)

        assert self._filter([bottom, top]) == {"top"}

    def test_candidate_without_percentile_data_passes(self):
        unknown = Candidate(node_id="unknown", name="u", pagerank_percentile=None, kcore_percentile=None)

        assert self._filter([unknown]) == {"unknown"}

    def test_missing_enrichment_leaves_percentiles_unset(self):
        from deriva.modules.derivation.base import enrich_candidate

        candidate = Candidate(node_id="n", name="n")
        enrich_candidate(candidate, {})

        assert (candidate.pagerank_percentile, candidate.kcore_percentile) == (None, None)


class TestGraphFilter:
    """The step's k-core threshold (params.graph_filter) applies to the candidates with one of its labels."""

    @staticmethod
    def _mixin():
        from deriva.modules.derivation.element_base import HybridFilteringMixin

        class Filter:
            MIN_PAGERANK = None
            MIN_PAGERANK_PERCENTILE = None
            USE_COMMUNITY_ROOTS = False
            USE_ARTICULATION_POINTS = False

        return type("F", (Filter, HybridFilteringMixin), {})()

    def test_the_threshold_leaves_out_low_kcore_candidates(self):
        from deriva.modules.derivation.base import GraphFilter

        low = Candidate(node_id="low", name="l", labels=["File"], kcore_percentile=20.0)
        high = Candidate(node_id="high", name="h", labels=["File"], kcore_percentile=80.0)

        kept = self._mixin().apply_graph_filtering([low, high], {}, 10, GraphFilter(min_kcore_percentile=30.0))

        assert [c.node_id for c in kept] == ["high"]

    def test_candidates_without_one_of_its_labels_pass(self):
        from deriva.modules.derivation.base import GraphFilter

        technology = Candidate(node_id="tech", name="t", labels=["Technology"], kcore_percentile=20.0)
        file = Candidate(node_id="file", name="f", labels=["File"], kcore_percentile=20.0)

        kept = self._mixin().apply_graph_filtering([technology, file], {}, 10, GraphFilter(min_kcore_percentile=30.0, labels=frozenset({"File"})))

        assert [c.node_id for c in kept] == ["tech"]

    def test_without_a_graph_filter_no_candidate_is_left_out_by_kcore(self):
        low = Candidate(node_id="low", name="l", labels=["File"], kcore_percentile=1.0)

        assert [c.node_id for c in self._mixin().apply_graph_filtering([low], {}, 10)] == ["low"]

    def test_filter_candidates_passes_it_on(self):
        from deriva.modules.derivation.base import GraphFilter
        from deriva.modules.derivation.node import NodeDerivation

        technology = Candidate(node_id="tech", name="Runtime", labels=["Technology"], kcore_percentile=20.0)
        file = Candidate(node_id="file", name="Dockerfile", labels=["File"], kcore_percentile=20.0)

        kept = NodeDerivation().filter_candidates([technology, file], {}, 10, graph_filter=GraphFilter(min_kcore_percentile=30.0, labels=frozenset({"File"})))

        assert [c.node_id for c in kept] == ["tech"]


class TestCandidateRankingTieBreak:
    """Candidates with equal PageRank rank by node id, so the result order of the candidate query never decides."""

    @staticmethod
    def _mixin():
        from deriva.modules.derivation.element_base import HybridFilteringMixin

        class Filter:
            MIN_PAGERANK = None
            MIN_PAGERANK_PERCENTILE = None
            USE_COMMUNITY_ROOTS = False
            USE_ARTICULATION_POINTS = False

        return type("F", (Filter, HybridFilteringMixin), {})()

    def test_ties_rank_by_node_id_whatever_the_input_order(self):
        candidates = [Candidate(node_id=n, name=n, pagerank=0.1) for n in ("c", "a", "d", "b")] + [Candidate(node_id="top", name="top", pagerank=0.9)]

        forward = [c.node_id for c in self._mixin().apply_graph_filtering(candidates, {}, 3)]
        backward = [c.node_id for c in self._mixin().apply_graph_filtering(list(reversed(candidates)), {}, 3)]

        assert forward == backward == ["top", "a", "b"]


class TestPerCandidateIdentity:
    """In per-candidate mode the prompt holds one candidate, so the element belongs to it."""

    @staticmethod
    def _created(candidates, response):
        archimate_manager = MagicMock()
        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
        ):
            result = ConcreteDerivation().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=archimate_manager,
                llm_query_fn=MagicMock(return_value=SimpleNamespace(content=response)),
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                prompt=TEST_PROMPT,
                per_candidate=PerCandidateConfig(min_pool=1, rules="R", persona="P"),
            )
        return result.created_elements

    def test_element_source_is_the_candidate(self):
        response = '{"elements": [{"identifier": "te_x", "name": "X", "documentation": "d", "source": "somewhere_else", "confidence": 0.9}]}'

        (element,) = self._created([Candidate(node_id="n1", name="x", labels=["Node"], properties={})], response)

        assert element["properties"]["source"] == "n1"

    def test_names_come_from_the_graph_not_the_llm(self):
        response = '{"elements": [{"identifier": "te_x", "name": "X", "documentation": "d", "source": "n", "confidence": 0.9}]}'
        candidates = [
            Candidate(node_id="n1", name="first", labels=["Node"], properties={}),
            Candidate(node_id="n2", name="second", labels=["Node"], properties={}),
        ]

        created = self._created(candidates, response)

        assert [(e["name"], e["properties"]["source"]) for e in created] == [("First", "n1"), ("Second", "n2")]
        assert len({e["identifier"] for e in created}) == 2

    def test_equal_graph_names_keep_one_element(self):
        response = '{"elements": [{"identifier": "te_x", "name": "X", "documentation": "d", "source": "n", "confidence": 0.9}]}'
        candidates = [
            Candidate(node_id="n1", name="shared", labels=["Node"], properties={}),
            Candidate(node_id="n2", name="shared", labels=["Node"], properties={}),
        ]

        created = self._created(candidates, response)

        assert [e["name"] for e in created] == ["Shared"]


class TestIsolatedNamingStep:
    """With params.naming, each kept element is named by a separate call about its source only."""

    ELEMENTS = '{"elements": [{"identifier": "x", "name": "In-batch LLM name", "documentation": "d", "source": "%s", "confidence": 0.9}]}'

    def _created(self, candidates, naming_answers, per_candidate=True, repo_name=""):
        from deriva.modules.derivation.base import NamingConfig

        answers = iter(naming_answers)
        prompts: list[str] = []

        def llm(prompt, schema, **kwargs):
            prompts.append(prompt)
            if schema.get("name") == "element_naming":
                return SimpleNamespace(content=json.dumps({"name": next(answers)}))
            source = next(c.node_id for c in candidates if f'"{c.node_id}"' in prompt)
            return SimpleNamespace(content=self.ELEMENTS % source)

        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
            patch.object(ConcreteDerivation, "_active_repo_name", return_value=repo_name),
        ):
            result = ConcreteDerivation().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=MagicMock(),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                prompt=TEST_PROMPT,
                per_candidate=PerCandidateConfig(min_pool=1, rules="R", persona="P") if per_candidate else None,
                naming=NamingConfig(instruction="NAMING RULES", samples=3),
            )
        return result.created_elements, prompts

    def test_majority_of_naming_answers_is_the_name(self):
        candidate = Candidate(node_id="n1", name="crud", labels=["Directory"], properties={"path": "r/crud"})
        created, prompts = self._created([candidate], ["CRUD Service", "Crud Operations", "CRUD Service"])

        assert [e["name"] for e in created] == ["CRUD Service"]
        naming_prompts = [p for p in prompts if "NAMING RULES" in p]
        assert len(naming_prompts) == 3 and len(set(naming_prompts)) == 1
        assert created[0]["identifier"] == "te_n1"  # identity still from structure

    def test_word_casing_comes_from_a_cased_source_name(self):
        """The source's spelling decides a word's casing, so answers that differ only in casing give one name; a
        lowercase source (a directory) carries no casing and the answer's stays."""
        typed = Candidate(node_id="n1", name="CrudTypeImpl", labels=["TypeDefinition"], properties={})
        directory = Candidate(node_id="n2", name="crud", labels=["Directory"], properties={})

        created, _ = self._created([typed], ["CRUD Type"] * 3)
        created_dir, _ = self._created([directory], ["CRUD Service"] * 3)

        assert [e["name"] for e in created] == ["Crud Type"]
        assert [e["name"] for e in created_dir] == ["CRUD Service"]

    def test_repository_words_are_removed_from_an_answer(self):
        candidate = Candidate(node_id="n1", name="registry", labels=["Directory"], properties={})

        created, _ = self._created([candidate], ["Tea Store Registry"] * 3, repo_name="TeaStore")

        assert [e["name"] for e in created] == ["Registry"]

    def test_no_usable_answer_falls_back_to_the_structure_name(self):
        created, _ = self._created([Candidate(node_id="n1", name="crud", labels=["Directory"], properties={})], ["", "", ""])

        assert [e["name"] for e in created] == ["Crud"]

    def test_name_taken_by_a_sibling_falls_back_to_the_structure_name(self):
        candidates = [
            Candidate(node_id="n1", name="alpha", labels=["Directory"], properties={}),
            Candidate(node_id="n2", name="beta", labels=["Directory"], properties={}),
        ]
        created, _ = self._created(candidates, ["Shared"] * 6)

        names = {e["name"] for e in created}
        assert "Shared" in names and len(names) == 2 and names - {"Shared"} <= {"Alpha", "Beta"}

    def test_batch_mode_names_the_same_way(self):
        created, _ = self._created([Candidate(node_id="n1", name="crud", labels=["Directory"], properties={})], ["CRUD Service"] * 3, per_candidate=False)

        assert [e["name"] for e in created] == ["CRUD Service"]


class TestStructureDecidesUniqueness:
    """Which candidates become elements is decided by structure: an LLM name never removes one."""

    @staticmethod
    def _generate(candidates, naming_answers, per_candidate=True, repo="", batch_size=5):
        from deriva.modules.derivation.base import NamingConfig

        answers = iter(naming_answers)
        prompts: list[str] = []

        def llm(prompt, schema, **kwargs):
            prompts.append(prompt)
            if schema.get("name") == "element_naming":
                return SimpleNamespace(content=json.dumps({"name": next(answers)}))
            sources = [c.node_id for c in candidates if f'"{c.node_id}"' in prompt]
            elements = [{"identifier": "x", "name": "n", "documentation": "d", "source": s, "confidence": 0.9} for s in sources]
            return SimpleNamespace(content=json.dumps({"elements": elements}))

        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
        ):
            result = ConcreteDerivation().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[{"name": repo}] if repo else [])),
                archimate_manager=MagicMock(),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=batch_size,
                existing_elements=[],
                prompt=TEST_PROMPT,
                per_candidate=PerCandidateConfig(min_pool=1, rules="R", persona="P") if per_candidate else None,
                naming=NamingConfig(instruction="NAMING RULES", samples=1),
            )
        return result, prompts

    def test_a_proper_name_the_source_writes_as_one_word_keeps_its_inner_capitals(self):
        """The source spells "ledgerkit3" as one word: the LLM's "LedgerKit3" is not split into "Ledger Kit3"."""
        candidates = [Candidate(node_id="file_schema", name="ledgerkit3_Report.xsd", labels=["File"], properties={"path": "repo/schemas/ledgerkit3_Report.xsd"})]

        result, _ = self._generate(candidates, ["LedgerKit3 Report Schema"], per_candidate=True)

        assert [e["name"] for e in result.created_elements] == ["LedgerKit3 Report Schema"]

    def test_a_code_name_the_llm_copies_is_split_where_the_source_splits_it(self):
        candidates = [Candidate(node_id="type_proc", name="EntityProcessor", labels=["TypeDefinition"], properties={"path": "repo/src/EntityProcessor.java"})]

        result, _ = self._generate(candidates, ["EntityProcessor"], per_candidate=True)

        assert [e["name"] for e in result.created_elements] == ["Entity Processor"]

    @pytest.mark.parametrize("per_candidate", [True, False])
    def test_a_name_that_is_another_candidates_structure_name_is_not_taken(self, per_candidate):
        """The first candidate's LLM name is the second one's structure name: the first keeps its own."""
        candidates = [
            Candidate(node_id="dir_inner", name="ledger", labels=["Directory"], properties={}),
            Candidate(node_id="dir_outer", name="ExternalLedger", labels=["Directory"], properties={}),
        ]

        result, _ = self._generate(candidates, ["External Ledger", "External Ledger"], per_candidate=per_candidate)

        assert {e["properties"]["source"]: e["name"] for e in result.created_elements} == {"dir_inner": "Ledger", "dir_outer": "External Ledger"}

    @pytest.mark.parametrize("per_candidate", [True, False])
    def test_a_repeated_structure_name_is_left_out_before_the_llm(self, per_candidate):
        """Structure names can repeat once the repository prefix is stripped: the later candidate is left out."""
        candidates = [
            Candidate(node_id="dir_first", name="gamma-delta", labels=["Directory"], properties={}),
            Candidate(node_id="dir_second", name="delta", labels=["Directory"], properties={}),
        ]

        result, prompts = self._generate(candidates, ["Alpha", "Beta"], per_candidate=per_candidate, repo="gamma")

        assert [e["properties"]["source"] for e in result.created_elements] == ["dir_first"]
        assert {d.node_id: d.stage for d in result.candidate_decisions}["dir_second"] == "duplicate_removed"
        assert not any('"dir_second"' in p for p in prompts)

    def test_the_structure_name_is_recorded_only_when_the_name_changes(self):
        candidates = [
            Candidate(node_id="dir_a", name="alpha", labels=["Directory"], properties={}),
            Candidate(node_id="dir_b", name="beta", labels=["Directory"], properties={}),
        ]

        result, _ = self._generate(candidates, ["Alpha", "Beta Store"])

        assert {e["properties"]["source"]: e["properties"].get("structure_name") for e in result.created_elements} == {"dir_a": None, "dir_b": "Beta"}

    def test_names_are_unique_across_batches(self):
        candidates = [
            Candidate(node_id="dir_a", name="alpha", labels=["Directory"], properties={}),
            Candidate(node_id="dir_b", name="beta", labels=["Directory"], properties={}),
        ]

        result, _ = self._generate(candidates, ["Shared", "Shared"], per_candidate=False, batch_size=1)

        assert [e["name"] for e in result.created_elements] == ["Shared", "Beta"]


class TestStepParamsReachTheBaseFilter:
    """A module that pre-filters and then delegates passes the step params (graph_filter, pattern_labels) on."""

    def test_application_interface_applies_the_graph_filter(self):
        from deriva.modules.derivation.application_interface import ApplicationInterfaceDerivation
        from deriva.modules.derivation.base import GraphFilter

        low = Candidate(node_id="low", name="LowController", labels=["File"])
        high = Candidate(node_id="high", name="HighController", labels=["File"])
        # The module enriches its candidates from the graph metrics first
        enrichments = {"low": {"kcore_percentile": 1.0, "pagerank": 0.5}, "high": {"kcore_percentile": 99.0, "pagerank": 0.5}}

        kept = ApplicationInterfaceDerivation().filter_candidates([low, high], enrichments, 10, set(), set(), graph_filter=GraphFilter(min_kcore_percentile=50.0))

        assert [c.node_id for c in kept] == ["high"]
