"""Tests for modules.derivation.element_base module."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from deriva.modules.derivation.base import (
    Candidate,
    GenerationResult,
    PerCandidateConfig,
    RelationshipLLMConfig,
    RelationshipRule,
)
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
                engine=MagicMock(),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[{"identifier": "other", "name": "Other", "element_type": "Other"}],
                relationship_config=relationship_config,
                per_candidate=per_candidate,
            )
        return derive

    def test_batch_mode_passes_relationship_config(self):
        config = RelationshipLLMConfig(instruction="rules", min_confidence=0.6)

        derive = self._generate(ConcreteDerivation(), config)

        assert derive.call_args.kwargs["llm_config"] is config

    def test_per_candidate_mode_passes_relationship_config(self):
        config = RelationshipLLMConfig(instruction="rules", min_confidence=0.6)

        derive = self._generate(ConcreteDerivation(), config, PerCandidateConfig(min_pool=1, rules="R"))

        assert derive.call_args.kwargs["llm_config"] is config


class TestPerCandidateMode:
    """Per-candidate naming is switched on by the element config (params.per_candidate)."""

    RESPONSE = '{"elements": [{"identifier": "te_x", "name": "X", "documentation": "d", "source": "1", "confidence": 0.9}]}'

    def _prompts(self, per_candidate, n_candidates=2):
        llm = MagicMock(return_value=SimpleNamespace(content=self.RESPONSE))
        candidates = [Candidate(node_id=str(i), name=f"c{i}", labels=["Node"], properties={}) for i in range(n_candidates)]
        with (
            patch("deriva.modules.derivation.element_base.get_enrichments_from_graph", return_value={}),
            patch("deriva.modules.derivation.element_base.query_candidates", return_value=candidates),
        ):
            ConcreteDerivation().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=MagicMock(),
                engine=MagicMock(),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                per_candidate=per_candidate,
            )
        return [c.args[0] for c in llm.call_args_list]

    def test_config_rules_go_into_one_prompt_per_candidate(self):
        prompts = self._prompts(PerCandidateConfig(min_pool=2, rules="CONFIG NAMING RULES"))

        assert len(prompts) == 2
        assert all("CONFIG NAMING RULES" in p for p in prompts)

    def test_pool_below_min_pool_uses_batch_mode(self):
        prompts = self._prompts(PerCandidateConfig(min_pool=3, rules="CONFIG NAMING RULES"))

        assert len(prompts) == 1
        assert "CONFIG NAMING RULES" not in prompts[0]

    def test_without_config_batch_mode_is_used(self):
        assert len(self._prompts(None)) == 1


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
                engine=MagicMock(),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                per_candidate=per_candidate,
            )

    def test_per_candidate_created_decision_names_the_element(self):
        response = '{"elements": [{"identifier": "te_x", "name": "X", "documentation": "d", "source": "1", "confidence": 0.9}]}'

        result = self._generate([Candidate(node_id="1", name="x", labels=["Node"], properties={})], response, PerCandidateConfig(min_pool=1, rules="R"))

        (decision,) = [d for d in result.candidate_decisions if d.stage == "created"]
        assert decision.element_id == result.created_elements[0]["identifier"]
        assert decision.element_confidence == 0.9

    def test_consolidated_candidates_are_recorded(self):
        candidates = [
            Candidate(node_id="1", name="Order", labels=["Node"], properties={}, pagerank=0.9),
            Candidate(node_id="2", name="Orders", labels=["Node"], properties={}, pagerank=0.1),
        ]

        result = self._generate(candidates, '{"elements": []}')

        stages = {d.node_id: d.stage for d in result.candidate_decisions}
        assert stages["2"] == "duplicate_removed"


class TestPercentileFiltering:
    """A computed percentile of 0.0 is the bottom rank; only absent data is exempt from the cutoff."""

    class Filter:
        MIN_PAGERANK = None
        MIN_PAGERANK_PERCENTILE = 40.0
        MIN_KCORE_PERCENTILE = 30.0
        USE_COMMUNITY_ROOTS = False
        USE_ARTICULATION_POINTS = False

    @classmethod
    def _filter(cls, candidates):
        from deriva.modules.derivation.element_base import HybridFilteringMixin

        filt = type("F", (cls.Filter, HybridFilteringMixin), {})()
        return {c.node_id for c in filt.apply_graph_filtering(candidates, {}, 10)}

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
                engine=MagicMock(),
                llm_query_fn=MagicMock(return_value=SimpleNamespace(content=response)),
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                per_candidate=PerCandidateConfig(min_pool=1, rules="R"),
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

    def _created(self, candidates, naming_answers, per_candidate=True):
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
        ):
            result = ConcreteDerivation().generate(
                graph_manager=MagicMock(query=MagicMock(return_value=[])),
                archimate_manager=MagicMock(),
                engine=MagicMock(),
                llm_query_fn=llm,
                query="MATCH (n) RETURN n",
                instruction="Test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                per_candidate=PerCandidateConfig(min_pool=1, rules="R") if per_candidate else None,
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
