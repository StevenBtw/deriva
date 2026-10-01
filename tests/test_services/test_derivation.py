"""Tests for services.derivation module."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deriva.modules.derivation.base import PerCandidateConfig, RelationshipLLMConfig
from deriva.modules.derivation.prep import EnrichmentResult
from deriva.services import derivation

# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def clean_instance_cache():
    """Fixture that clears and restores the instance cache for isolated testing."""
    original_cache = derivation._DERIVATION_INSTANCES.copy()
    derivation._DERIVATION_INSTANCES.clear()
    yield
    derivation._DERIVATION_INSTANCES.clear()
    derivation._DERIVATION_INSTANCES.update(original_cache)


# =============================================================================
# ELEMENT MODULE LOADING TESTS
# =============================================================================

# All known element types that should have generation modules
ELEMENT_TYPES_WITH_MODULES = [
    "ApplicationComponent",
    "ApplicationInterface",
    "ApplicationService",
    "BusinessActor",
    "BusinessEvent",
    "BusinessFunction",
    "BusinessObject",
    "BusinessProcess",
    "DataObject",
    "Device",
    "Node",
    "SystemSoftware",
    "TechnologyService",
]


class TestDerivationRegistry:
    """Tests for derivation registry and _get_derivation function."""

    @pytest.mark.parametrize("element_type", ELEMENT_TYPES_WITH_MODULES)
    def test_gets_derivation_instance(self, element_type):
        """Should get derivation instance with generate method."""
        instance = derivation._get_derivation(element_type)
        assert instance is not None, f"Derivation for {element_type} should exist"
        assert hasattr(instance, "generate"), f"Derivation for {element_type} should have generate method"

    def test_caches_derivation_instances(self, clean_instance_cache):
        """Should cache derivation instances."""
        instance1 = derivation._get_derivation("Node")
        instance2 = derivation._get_derivation("Node")

        assert instance1 is instance2
        assert "Node" in derivation._DERIVATION_INSTANCES

    def test_returns_none_for_unknown_type(self):
        """Should return None for unknown element type."""
        instance = derivation._get_derivation("UnknownType")
        assert instance is None


class TestGetGraphEdges:
    """Tests for _get_graph_edges function."""

    def test_returns_edges_from_query(self):
        """Should return edges from graph query."""
        graph_manager = MagicMock()
        graph_manager.query.return_value = [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ]

        edges = derivation._get_graph_edges(graph_manager)

        assert len(edges) == 2
        assert edges[0] == {"source": "n1", "target": "n2"}

    def test_returns_empty_list_when_no_edges(self):
        """Should return empty list when no edges."""
        graph_manager = MagicMock()
        graph_manager.query.return_value = []

        edges = derivation._get_graph_edges(graph_manager)

        assert edges == []


class TestRunPrepStep:
    """Tests for _run_prep_step function."""

    def test_runs_known_prep_step(self):
        """Should run known prep step."""
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 5
        cfg = MagicMock()
        cfg.step_name = "pagerank"
        cfg.params = None

        mock_result = EnrichmentResult(enrichments={"n1": {"pagerank": 0.5}})
        with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "n1", "target": "n2"}]):
            with patch.object(derivation.prep, "enrich_graph", return_value=mock_result):
                result = derivation._run_prep_step(cfg, graph_manager)

        assert result["success"] is True

    def test_unknown_prep_step_returns_error(self):
        """Should return error for unknown prep step."""
        graph_manager = MagicMock()
        cfg = MagicMock()
        cfg.step_name = "unknown_step"
        cfg.params = None

        result = derivation._run_prep_step(cfg, graph_manager)

        assert result["success"] is False
        assert "Unknown prep step" in result["errors"][0]

    def test_handles_empty_edges(self):
        """Should handle case when no edges found."""
        graph_manager = MagicMock()
        cfg = MagicMock()
        cfg.step_name = "pagerank"
        cfg.params = None

        with patch.object(derivation, "_get_graph_edges", return_value=[]):
            result = derivation._run_prep_step(cfg, graph_manager)

        assert result["success"] is True
        assert result["stats"]["nodes_updated"] == 0

    def test_parses_json_params(self):
        """Should parse JSON params from config."""
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 3
        cfg = MagicMock()
        cfg.step_name = "pagerank"
        cfg.params = '{"damping": 0.85}'

        with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "n1", "target": "n2"}]):
            with patch.object(derivation.prep, "enrich_graph") as mock_enrich:
                mock_enrich.return_value = EnrichmentResult(enrichments={"n1": {"pagerank": 0.5}})
                result = derivation._run_prep_step(cfg, graph_manager)

        assert result["success"] is True
        # Check that params were passed to enrich_graph
        call_args = mock_enrich.call_args
        assert "params" in call_args.kwargs or len(call_args.args) > 2

    def test_handles_enrichment_exception(self):
        """Should handle exception during enrichment."""
        graph_manager = MagicMock()
        cfg = MagicMock()
        cfg.step_name = "pagerank"
        cfg.params = None

        with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "n1", "target": "n2"}]):
            with patch.object(derivation.prep, "enrich_graph", side_effect=Exception("Test error")):
                result = derivation._run_prep_step(cfg, graph_manager)

        assert result["success"] is False
        assert "Enrichment failed" in result["errors"][0]


class TestRunDerivation:
    """Tests for run_derivation function."""

    def test_runs_all_phases_by_default(self):
        """Should run prep and generate phases by default."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.return_value = []
            derivation.run_derivation(
                engine=engine,
                graph_manager=graph_manager,
                archimate_manager=archimate_manager,
            )

        phases_queried = [call.kwargs.get("phase") for call in mock_get.call_args_list]
        assert "prep" in phases_queried
        assert "generate" in phases_queried

    def test_tracks_stats(self):
        """Should track elements and relationships created."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.return_value = []
            result = derivation.run_derivation(
                engine=engine,
                graph_manager=graph_manager,
                archimate_manager=archimate_manager,
            )

        assert "stats" in result
        assert result["stats"]["elements_created"] == 0
        assert result["stats"]["relationships_created"] == 0


class TestGenerateElement:
    """Tests for generate_element function."""

    def test_returns_generation_result_as_dict(self):
        """Should return dict with generation result data."""
        from deriva.modules.derivation.base import GenerationResult

        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        engine = MagicMock()

        with patch.object(derivation, "_get_derivation") as mock_get:
            mock_derivation = MagicMock()
            mock_derivation.generate.return_value = GenerationResult(
                success=True,
                elements_created=3,
                relationships_created=5,
                created_elements=[{"id": "1"}],
                created_relationships=[{"id": "r1"}],
                errors=[],
            )
            mock_get.return_value = mock_derivation

            result = derivation.generate_element(
                graph_manager=graph_manager,
                archimate_manager=archimate_manager,
                engine=engine,
                llm_query_fn=MagicMock(),
                element_type="ApplicationComponent",
                query="MATCH (n) RETURN n",
                instruction="test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
            )

        # Should return dict with result data
        assert result["success"] is True
        assert result["elements_created"] == 3
        assert result["relationships_created"] == 5

    def test_returns_error_for_unknown_element_type(self):
        """Should return error when derivation not found."""
        result = derivation.generate_element(
            graph_manager=MagicMock(),
            archimate_manager=MagicMock(),
            engine=MagicMock(),
            llm_query_fn=MagicMock(),
            element_type="UnknownType",
            query="MATCH (n) RETURN n",
            instruction="test",
            example="{}",
            max_candidates=10,
            batch_size=5,
        )

        assert result["success"] is False
        assert "No derivation class" in result["errors"][0]

    def test_handles_generation_exception(self):
        """Should handle exception during generation."""
        with patch.object(derivation, "_get_derivation") as mock_get:
            mock_derivation = MagicMock()
            mock_derivation.generate.side_effect = Exception("LLM failed")
            mock_get.return_value = mock_derivation

            result = derivation.generate_element(
                graph_manager=MagicMock(),
                archimate_manager=MagicMock(),
                engine=MagicMock(),
                llm_query_fn=MagicMock(),
                element_type="ApplicationComponent",
                query="MATCH (n) RETURN n",
                instruction="test",
                example="{}",
                max_candidates=10,
                batch_size=5,
            )

        assert result["success"] is False
        assert "Generation failed" in result["errors"][0]

    def _generate_with_patterns(self, **pattern_mock):
        from deriva.modules.derivation.base import GenerationResult

        engine = MagicMock()
        with (
            patch.object(derivation, "_get_derivation") as mock_get,
            patch.object(derivation.config, "get_derivation_patterns", **pattern_mock) as mock_patterns,
        ):
            mock_derivation = MagicMock()
            mock_derivation.generate.return_value = GenerationResult(success=True)
            mock_get.return_value = mock_derivation
            derivation.generate_element(
                graph_manager=MagicMock(),
                archimate_manager=MagicMock(),
                engine=engine,
                llm_query_fn=MagicMock(),
                element_type="ApplicationService",
                query="MATCH (n) RETURN n",
                instruction="test",
                example="{}",
                max_candidates=10,
                batch_size=5,
            )
        return engine, mock_patterns, mock_derivation.generate.call_args.kwargs

    def test_passes_the_step_patterns_to_the_module(self):
        """The service loads the patterns; the module never touches the config database."""
        patterns = {"include": {"service"}, "exclude": {"test"}}
        engine, mock_patterns, kwargs = self._generate_with_patterns(return_value=patterns)

        mock_patterns.assert_called_once_with(engine, "ApplicationService")
        assert kwargs["patterns"] == patterns
        assert "engine" not in kwargs

    def test_passes_no_patterns_when_none_are_configured(self):
        _, _, kwargs = self._generate_with_patterns(side_effect=ValueError("No patterns"))

        assert kwargs["patterns"] == {}

    def test_pattern_labels_travel_with_the_patterns(self):
        from deriva.modules.derivation.base import GenerationResult

        with (
            patch.object(derivation, "_get_derivation") as mock_get,
            patch.object(derivation.config, "get_derivation_patterns", return_value={"include": {"docker"}, "exclude": set()}),
        ):
            mock_get.return_value.generate.return_value = GenerationResult(success=True)
            derivation.generate_element(
                graph_manager=MagicMock(),
                archimate_manager=MagicMock(),
                engine=MagicMock(),
                llm_query_fn=MagicMock(),
                element_type="Node",
                query="MATCH (n) RETURN n",
                instruction="test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                pattern_labels=frozenset({"File"}),
            )

        assert mock_get.return_value.generate.call_args.kwargs["patterns"] == {"include": {"docker"}, "exclude": set(), "labels": {"File"}}


class TestEnrichmentAlgorithms:
    """Tests for ENRICHMENT_ALGORITHMS constant."""

    def test_contains_expected_algorithms(self):
        """Should contain expected enrichment algorithms."""
        assert "pagerank" in derivation.ENRICHMENT_ALGORITHMS
        assert "louvain_communities" in derivation.ENRICHMENT_ALGORITHMS
        assert "k_core_filter" in derivation.ENRICHMENT_ALGORITHMS


class TestRunDerivationSteps:
    """Only the named steps run (the step benchmark measures one derivation step at a time)."""

    @staticmethod
    def _gen_cfg(name):
        return MagicMock(
            step_name=name,
            element_type=name,
            input_graph_query="MATCH (n) RETURN n",
            instruction="I",
            example="{}",
            max_candidates=10,
            batch_size=5,
            temperature=None,
            max_tokens=None,
            params=None,
        )

    def _run(self, steps, prep=(), gen=(), model_elements=()):
        archimate_manager = MagicMock()
        archimate_manager.get_elements.return_value = list(model_elements)
        configs = {"prep": list(prep), "generate": list(gen)}
        created = {"success": True, "elements_created": 1, "created_elements": [{"identifier": "e1", "name": "E", "element_type": "X", "properties": {}}], "errors": []}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: configs.get(phase, [])),
            patch.object(derivation, "_run_prep_step", return_value={"stats": {}}) as prep_step,
            patch.object(derivation, "generate_element", return_value=created) as generate,
            patch.object(derivation, "derive_consolidated_relationships", return_value=[]) as relationships,
        ):
            derivation.run_derivation(engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=archimate_manager, llm_query_fn=MagicMock(), steps=steps)
        return prep_step, generate, relationships

    def test_only_the_named_steps_run(self):
        prep = [MagicMock(step_name="pagerank", params=None), MagicMock(step_name="k_core_filter", params=None)]
        gen = [self._gen_cfg("ApplicationComponent"), self._gen_cfg("BusinessObject")]

        prep_step, generate, relationships = self._run(["k_core_filter", "BusinessObject"], prep=prep, gen=gen)

        assert [c.args[0].step_name for c in prep_step.call_args_list] == ["k_core_filter"]
        assert [c.kwargs["element_type"] for c in generate.call_args_list] == ["BusinessObject"]
        # The consolidated relationship pass is a step of its own
        relationships.assert_not_called()

    def test_the_relationship_pass_runs_on_the_model_when_named(self):
        element = SimpleNamespace(identifier="e9", name="Ledger", element_type="BusinessObject", properties={})

        _, generate, relationships = self._run([derivation.RELATIONSHIP_STEP], gen=[self._gen_cfg("BusinessObject")], model_elements=[element])

        generate.assert_not_called()
        (call,) = relationships.call_args_list
        assert [e["identifier"] for e in call.kwargs["all_elements"]] == ["e9"]


class TestContainmentConfig:
    """The relationship row's params.containment: which type pairs containment decides, checked against the metamodel."""

    @staticmethod
    def _row(containment):
        params = {"min_confidence": 0.6, "persona": "P"}
        if containment is not None:
            params["containment"] = containment
        return SimpleNamespace(step_name="GlobalRelationships", instruction="rules", params=json.dumps(params))

    def test_without_a_row_or_the_key_there_is_no_containment(self):
        assert derivation._containment_rules([]) == []
        assert derivation._containment_rules([self._row(None)]) == []

    def test_rules_come_from_params(self):
        from deriva.modules.derivation.base import ContainmentRule

        row = self._row([{"container": "ApplicationComponent", "contained": "ApplicationInterface", "relationship": "Composition"}])

        assert derivation._containment_rules([row]) == [ContainmentRule(container="ApplicationComponent", contained="ApplicationInterface", relationship="Composition")]

    @pytest.mark.parametrize(
        "containment",
        [
            {"container": "ApplicationComponent"},
            [{"container": "ApplicationComponent", "contained": "DataObject"}],
            [{"container": "ApplicationComponent", "contained": "DataObject", "relationship": "Composition"}],
        ],
    )
    def test_invalid_settings_are_an_error(self, containment):
        with pytest.raises(ValueError, match="containment"):
            derivation._containment_rules([self._row(containment)])

    def test_the_relationship_pass_receives_the_rules(self):
        from deriva.modules.derivation.base import ContainmentRule

        row = self._row([{"container": "ApplicationComponent", "contained": "ApplicationService", "relationship": "Realization"}])
        element = SimpleNamespace(identifier="e9", name="Ledger", element_type="BusinessObject", properties={})
        archimate_manager = MagicMock()
        archimate_manager.get_elements.return_value = [element]
        configs = {"relationship": [row]}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: configs.get(phase, [])),
            patch.object(derivation, "derive_consolidated_relationships", return_value=[]) as relationships,
        ):
            derivation.run_derivation(
                engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=archimate_manager, llm_query_fn=MagicMock(), steps=[derivation.RELATIONSHIP_STEP]
            )

        assert relationships.call_args.kwargs["containment"] == [ContainmentRule(container="ApplicationComponent", contained="ApplicationService", relationship="Realization")]


class TestDependencyConfig:
    """The relationship row's params.dependency, checked against the metamodel."""

    @staticmethod
    def _row(**structure):
        params = {"min_confidence": 0.6, "persona": "P", **structure}
        return SimpleNamespace(step_name="GlobalRelationships", instruction="rules", params=json.dumps(params))

    def test_without_the_key_there_are_no_rules(self):
        assert derivation._dependency_rules([self._row()]) == []

    def test_dependency_rules_come_from_params(self):
        from deriva.modules.derivation.base import DependencyRule

        row = self._row(dependency=[{"provider": "ApplicationComponent", "consumer": "ApplicationComponent", "relationship": "Serving"}])

        assert derivation._dependency_rules([row]) == [DependencyRule(provider="ApplicationComponent", consumer="ApplicationComponent", relationship="Serving")]

    @pytest.mark.parametrize(
        "item",
        [
            {"provider": "ApplicationComponent", "consumer": "ApplicationComponent"},
            {"provider": "ApplicationComponent", "consumer": "ApplicationComponent", "relationship": "Access"},
        ],
    )
    def test_invalid_settings_are_an_error(self, item):
        with pytest.raises(ValueError, match="dependency"):
            derivation._dependency_rules([self._row(dependency=[item])])

    def test_the_relationship_pass_receives_the_rules(self):
        row = self._row(dependency=[{"provider": "ApplicationComponent", "consumer": "ApplicationComponent", "relationship": "Serving"}])
        element = SimpleNamespace(identifier="e9", name="Ledger", element_type="BusinessObject", properties={})
        archimate_manager = MagicMock()
        archimate_manager.get_elements.return_value = [element]
        configs = {"relationship": [row]}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: configs.get(phase, [])),
            patch.object(derivation, "derive_consolidated_relationships", return_value=[]) as relationships,
        ):
            derivation.run_derivation(
                engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=archimate_manager, llm_query_fn=MagicMock(), steps=[derivation.RELATIONSHIP_STEP]
            )

        assert [r.provider for r in relationships.call_args.kwargs["dependency"]] == ["ApplicationComponent"]


class TestTechnologyStructureConfig:
    """The relationship row's params.membership and params.configuration, checked against the metamodel."""

    @staticmethod
    def _row(**structure):
        params = {"min_confidence": 0.6, "persona": "P", **structure}
        return SimpleNamespace(step_name="GlobalRelationships", instruction="rules", params=json.dumps(params))

    def test_without_the_keys_there_are_no_rules(self):
        assert derivation._membership_rules([self._row()]) == []
        assert derivation._configuration_rules([]) == []

    def test_membership_rules_come_from_params(self):
        from deriva.modules.derivation.base import MembershipRule

        row = self._row(
            membership=[
                {"group": "Node", "member": "SystemSoftware", "relationship": "Composition", "from": "group"},
                {"group": "TechnologyService", "member": "SystemSoftware", "relationship": "Realization", "from": "member"},
            ]
        )

        assert derivation._membership_rules([row]) == [
            MembershipRule(group="Node", member="SystemSoftware", relationship="Composition", from_group=True),
            MembershipRule(group="TechnologyService", member="SystemSoftware", relationship="Realization", from_group=False),
        ]

    def test_configuration_rules_come_from_params(self):
        from deriva.modules.derivation.base import ConfigurationRule

        row = self._row(configuration=[{"provider": "TechnologyService", "consumer": "ApplicationComponent", "relationship": "Serving"}])

        assert derivation._configuration_rules([row]) == [ConfigurationRule(provider="TechnologyService", consumer="ApplicationComponent", relationship="Serving")]

    @pytest.mark.parametrize(
        "structure",
        [
            {"membership": [{"group": "Node", "member": "SystemSoftware", "relationship": "Composition", "from": "elsewhere"}]},
            {"membership": [{"group": "Node", "member": "SystemSoftware", "relationship": "Access", "from": "group"}]},
            {"configuration": [{"provider": "TechnologyService", "consumer": "ApplicationComponent"}]},
            {"configuration": [{"provider": "TechnologyService", "consumer": "ApplicationComponent", "relationship": "Composition"}]},
        ],
    )
    def test_invalid_settings_are_an_error(self, structure):
        key = next(iter(structure))
        with pytest.raises(ValueError, match=key):
            (derivation._membership_rules if key == "membership" else derivation._configuration_rules)([self._row(**structure)])

    def test_the_relationship_pass_receives_the_rules(self):
        row = self._row(
            membership=[{"group": "Node", "member": "SystemSoftware", "relationship": "Composition", "from": "group"}],
            configuration=[{"provider": "TechnologyService", "consumer": "ApplicationComponent", "relationship": "Serving"}],
        )
        element = SimpleNamespace(identifier="e9", name="Ledger", element_type="BusinessObject", properties={})
        archimate_manager = MagicMock()
        archimate_manager.get_elements.return_value = [element]
        configs = {"relationship": [row]}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: configs.get(phase, [])),
            patch.object(derivation, "derive_consolidated_relationships", return_value=[]) as relationships,
        ):
            derivation.run_derivation(
                engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=archimate_manager, llm_query_fn=MagicMock(), steps=[derivation.RELATIONSHIP_STEP]
            )

        kwargs = relationships.call_args.kwargs
        assert [r.group for r in kwargs["membership"]] == ["Node"]
        assert [r.provider for r in kwargs["configuration"]] == ["TechnologyService"]


class TestRunDerivationWithConfigs:
    """Tests for run_derivation with actual mock configs."""

    def test_runs_prep_phase_with_configs(self):
        """Should execute prep step configs."""
        engine = MagicMock()
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 3
        archimate_manager = MagicMock()

        enrich_cfg = MagicMock()
        enrich_cfg.step_name = "pagerank"
        enrich_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [enrich_cfg] if phase == "prep" else []
            with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "a", "target": "b"}]):
                with patch.object(derivation.prep, "enrich_graph", return_value=EnrichmentResult(enrichments={"a": {"pagerank": 0.5}})):
                    result = derivation.run_derivation(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        phases=["prep"],
                    )

        assert result["success"] is True
        assert result["stats"]["steps_completed"] == 1

    def test_runs_generate_phase_with_valid_config(self):
        """Should execute generate step with valid config."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_app_component"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Generate components"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "elements_created": 2,
                    "relationships_created": 1,
                    "created_elements": [{"id": "e1"}],
                    "errors": [],
                }
                result = derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    llm_query_fn=MagicMock(),
                    phases=["generate"],
                )

        assert result["success"] is True
        assert result["stats"]["elements_created"] == 2
        assert result["stats"]["relationships_created"] == 1

    def test_skips_generate_step_with_missing_params(self):
        """Should skip generate step when required params missing."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_incomplete"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = None  # Missing!
        gen_cfg.instruction = None  # Missing!
        gen_cfg.example = None  # Missing!
        gen_cfg.max_candidates = None  # Missing!
        gen_cfg.batch_size = None  # Missing!

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            result = derivation.run_derivation(
                engine=engine,
                graph_manager=graph_manager,
                archimate_manager=archimate_manager,
                llm_query_fn=MagicMock(),
                phases=["generate"],
            )

        assert result["success"] is False
        assert result["stats"]["steps_skipped"] == 1
        assert "Missing required config" in result["errors"][0]

    def test_handles_generate_exception(self):
        """Should handle exception during generate phase."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_failing"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Generate"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element", side_effect=Exception("LLM error")):
                result = derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    llm_query_fn=MagicMock(),
                    phases=["generate"],
                )

        assert result["success"] is False
        assert result["stats"]["steps_skipped"] == 1
        assert "gen_failing" in result["errors"][0]
        assert "LLM error" in result["errors"][0]

    def test_with_progress_reporter(self):
        """Should call progress reporter methods during execution."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        progress = MagicMock()

        with patch.object(derivation.config, "get_derivation_configs", return_value=[]):
            derivation.run_derivation(
                engine=engine,
                graph_manager=graph_manager,
                archimate_manager=archimate_manager,
                progress=progress,
            )

        progress.start_phase.assert_called_once()
        progress.complete_phase.assert_called_once()

    def test_with_run_logger(self):
        """Should call run_logger methods during execution."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        run_logger = MagicMock()

        with patch.object(derivation.config, "get_derivation_configs", return_value=[]):
            derivation.run_derivation(
                engine=engine,
                graph_manager=graph_manager,
                archimate_manager=archimate_manager,
                run_logger=run_logger,
            )

        run_logger.phase_start.assert_called_once()
        run_logger.phase_complete.assert_called_once()

    def test_verbose_output_for_prep_phase(self, capsys):
        """Should print verbose output during prep phase."""
        engine = MagicMock()
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 0
        archimate_manager = MagicMock()

        enrich_cfg = MagicMock()
        enrich_cfg.step_name = "pagerank"
        enrich_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [enrich_cfg] if phase == "prep" else []
            with patch.object(derivation, "_get_graph_edges", return_value=[]):
                derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    verbose=True,
                    phases=["prep"],
                )

        captured = capsys.readouterr()
        assert "Running 1 prep steps" in captured.out
        assert "Prep: pagerank" in captured.out

    def test_verbose_output_for_generate_phase(self, capsys):
        """Should print verbose output during generate phase."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_app"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Gen"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "elements_created": 2,
                    "relationships_created": 3,
                    "created_elements": [],
                    "errors": [],
                }
                derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    llm_query_fn=MagicMock(),
                    verbose=True,
                    phases=["generate"],
                )

        captured = capsys.readouterr()
        assert "Running 1 generate steps" in captured.out
        assert "Generate: gen_app" in captured.out
        assert "+ 3 relationships" in captured.out

    def test_verbose_no_generate_configs(self, capsys):
        """Should print message when no generate configs enabled."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        with patch.object(derivation.config, "get_derivation_configs", return_value=[]):
            derivation.run_derivation(
                engine=engine,
                graph_manager=graph_manager,
                archimate_manager=archimate_manager,
                verbose=True,
                phases=["generate"],
            )

        captured = capsys.readouterr()
        assert "No generate phase configs enabled" in captured.out

    def test_accumulates_created_elements_across_steps(self):
        """Should pass accumulated elements to subsequent steps."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        # Create two generate configs
        gen_cfg1 = MagicMock()
        gen_cfg1.step_name = "gen1"
        gen_cfg1.element_type = "ApplicationComponent"
        gen_cfg1.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg1.instruction = "Gen"
        gen_cfg1.example = "{}"
        gen_cfg1.max_candidates = 10
        gen_cfg1.batch_size = 5
        gen_cfg1.temperature = None
        gen_cfg1.max_tokens = None
        gen_cfg1.params = None

        gen_cfg2 = MagicMock()
        gen_cfg2.step_name = "gen2"
        gen_cfg2.element_type = "DataObject"
        gen_cfg2.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg2.instruction = "Gen"
        gen_cfg2.example = "{}"
        gen_cfg2.max_candidates = 10
        gen_cfg2.batch_size = 5
        gen_cfg2.temperature = None
        gen_cfg2.max_tokens = None
        gen_cfg2.params = None

        calls = []

        def track_generate(**kwargs):
            calls.append(kwargs.get("existing_elements", []).copy())
            created = [{"id": f"e{len(calls)}"}] if len(calls) == 1 else []
            return {
                "success": True,
                "elements_created": 1,
                "relationships_created": 0,
                "created_elements": created,
                "errors": [],
            }

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg1, gen_cfg2] if phase == "generate" else []
            with patch.object(derivation, "generate_element", side_effect=track_generate):
                derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    llm_query_fn=MagicMock(),
                    phases=["generate"],
                )

        # First call should have empty existing_elements
        assert calls[0] == []
        # Second call should have elements from first step
        assert len(calls[1]) == 1
        assert calls[1][0]["id"] == "e1"

    def test_run_logger_phase_error_on_failure(self):
        """Should call phase_error when errors occur."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        run_logger = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_bad"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = None  # Missing required param

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            derivation.run_derivation(
                engine=engine,
                graph_manager=graph_manager,
                archimate_manager=archimate_manager,
                llm_query_fn=MagicMock(),
                run_logger=run_logger,
                phases=["generate"],
            )

        run_logger.phase_error.assert_called_once()

    def test_progress_reporter_on_step_error(self):
        """Should log error via progress reporter when step fails."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        progress = MagicMock()

        enrich_cfg = MagicMock()
        enrich_cfg.step_name = "pagerank"
        enrich_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [enrich_cfg] if phase == "prep" else []
            with patch.object(derivation, "_run_prep_step", return_value={"success": False, "errors": ["Test error"]}):
                derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    progress=progress,
                    phases=["prep"],
                )

        progress.log.assert_called()
        assert "error" in str(progress.log.call_args)


class TestRunPrepStepEdgeCases:
    """Tests for edge cases in _run_prep_step function."""

    def test_returns_success_when_enrichment_returns_empty(self):
        """Should return success when enrichment returns empty results."""
        graph_manager = MagicMock()
        cfg = MagicMock()
        cfg.step_name = "pagerank"
        cfg.params = None

        with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "n1", "target": "n2"}]):
            with patch.object(derivation.prep, "enrich_graph", return_value=EnrichmentResult(enrichments={})):
                result = derivation._run_prep_step(cfg, graph_manager)

        assert result["success"] is True
        assert result["stats"]["nodes_updated"] == 0

    def test_handles_json_decode_error_in_params(self):
        """Should handle invalid JSON in params gracefully."""
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 3
        cfg = MagicMock()
        cfg.step_name = "pagerank"
        cfg.params = "not valid json {"

        with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "n1", "target": "n2"}]):
            with patch.object(derivation.prep, "enrich_graph", return_value=EnrichmentResult(enrichments={"n1": {"pagerank": 0.5}})):
                result = derivation._run_prep_step(cfg, graph_manager)

        # Should succeed despite invalid params (uses defaults)
        assert result["success"] is True

    def test_filters_description_from_params(self):
        """Should filter out 'description' key from params."""
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 3
        cfg = MagicMock()
        cfg.step_name = "pagerank"
        cfg.params = '{"damping": 0.85, "description": "PageRank algorithm"}'

        with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "n1", "target": "n2"}]):
            with patch.object(derivation.prep, "enrich_graph") as mock_enrich:
                mock_enrich.return_value = EnrichmentResult(enrichments={"n1": {"pagerank": 0.5}})
                derivation._run_prep_step(cfg, graph_manager)

        # Verify description was filtered out
        call_kwargs = mock_enrich.call_args.kwargs
        if "params" in call_kwargs and "pagerank" in call_kwargs["params"]:
            assert "description" not in call_kwargs["params"]["pagerank"]

    def test_runs_louvain_communities_algorithm(self):
        """Should run louvain_communities algorithm."""
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 5
        cfg = MagicMock()
        cfg.step_name = "louvain_communities"
        cfg.params = None

        with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "n1", "target": "n2"}]):
            with patch.object(derivation.prep, "enrich_graph", return_value=EnrichmentResult(enrichments={"n1": {"community": 1}})):
                result = derivation._run_prep_step(cfg, graph_manager)

        assert result["success"] is True
        assert result["stats"]["algorithm"] == "louvain"

    def test_runs_degree_centrality_algorithm(self):
        """Should run degree_centrality algorithm."""
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 3
        cfg = MagicMock()
        cfg.step_name = "degree_centrality"
        cfg.params = None

        with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "n1", "target": "n2"}]):
            with patch.object(derivation.prep, "enrich_graph", return_value=EnrichmentResult(enrichments={"n1": {"degree": 2}})):
                result = derivation._run_prep_step(cfg, graph_manager)

        assert result["success"] is True
        assert result["stats"]["algorithm"] == "degree"


class TestRunDerivationIter:
    """Tests for run_derivation_iter generator function."""

    def test_yields_progress_updates(self):
        """Should yield ProgressUpdate objects."""
        from deriva.common.types import ProgressUpdate

        engine = MagicMock()
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 0
        archimate_manager = MagicMock()

        enrich_cfg = MagicMock()
        enrich_cfg.step_name = "pagerank"
        enrich_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [enrich_cfg] if phase == "prep" else []
            with patch.object(derivation, "_get_graph_edges", return_value=[]):
                updates = list(
                    derivation.run_derivation_iter(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        phases=["prep"],
                    )
                )

        assert len(updates) >= 1
        assert all(isinstance(u, ProgressUpdate) for u in updates)

    def test_yields_error_when_no_configs_enabled(self):
        """Should yield error update when no configs are enabled."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        with patch.object(derivation.config, "get_derivation_configs", return_value=[]):
            updates = list(
                derivation.run_derivation_iter(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                )
            )

        assert len(updates) == 1
        assert updates[0].status == "error"
        assert "No derivation configs enabled" in updates[0].message

    def test_yields_step_complete_for_each_prep_step(self):
        """Should yield step complete for each prep step."""
        engine = MagicMock()
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 0
        archimate_manager = MagicMock()

        enrich_cfg1 = MagicMock()
        enrich_cfg1.step_name = "pagerank"
        enrich_cfg1.params = None

        enrich_cfg2 = MagicMock()
        enrich_cfg2.step_name = "louvain_communities"
        enrich_cfg2.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [enrich_cfg1, enrich_cfg2] if phase == "prep" else []
            with patch.object(derivation, "_get_graph_edges", return_value=[]):
                updates = list(
                    derivation.run_derivation_iter(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        phases=["prep"],
                    )
                )

        # Should have 2 prep step updates + 1 final completion
        step_updates = [u for u in updates if u.step]
        assert len(step_updates) == 2
        assert step_updates[0].step == "pagerank"
        assert step_updates[1].step == "louvain_communities"

    def test_yields_generate_step_with_element_counts(self):
        """Should yield generate step with element counts."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_app"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Gen"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "elements_created": 5,
                    "relationships_created": 3,
                    "created_elements": [],
                    "errors": [],
                }
                updates = list(
                    derivation.run_derivation_iter(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=MagicMock(),
                        phases=["generate"],
                    )
                )

        step_update = [u for u in updates if u.step == "gen_app"][0]
        assert "5 elements" in step_update.message
        assert "3 relationships" in step_update.message

    def test_yields_error_for_missing_config_params(self):
        """Should yield error when config has missing params."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_bad"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = None  # Missing
        gen_cfg.instruction = None  # Missing
        gen_cfg.example = None
        gen_cfg.max_candidates = None
        gen_cfg.batch_size = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            updates = list(
                derivation.run_derivation_iter(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    llm_query_fn=MagicMock(),
                    phases=["generate"],
                )
            )

        error_updates = [u for u in updates if u.status == "error"]
        assert len(error_updates) >= 1
        assert "Missing required config" in error_updates[0].message

    def test_yields_error_on_generate_exception(self):
        """Should yield error when generate raises exception."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_fail"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Gen"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element", side_effect=Exception("LLM crashed")):
                updates = list(
                    derivation.run_derivation_iter(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=MagicMock(),
                        phases=["generate"],
                    )
                )

        error_updates = [u for u in updates if u.status == "error"]
        assert len(error_updates) >= 1
        assert "Error in gen_fail" in error_updates[0].message

    def test_final_update_includes_stats(self):
        """Should include complete stats in final update."""
        engine = MagicMock()
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 0
        archimate_manager = MagicMock()

        enrich_cfg = MagicMock()
        enrich_cfg.step_name = "pagerank"
        enrich_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [enrich_cfg] if phase == "prep" else []
            with patch.object(derivation, "_get_graph_edges", return_value=[]):
                updates = list(
                    derivation.run_derivation_iter(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        phases=["prep"],
                    )
                )

        final_update = updates[-1]
        assert final_update.status == "complete"
        assert "stats" in final_update.stats
        assert final_update.stats["stats"]["steps_completed"] == 1

    def test_accumulates_elements_across_generate_steps(self):
        """Should accumulate elements and pass to subsequent steps."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg1 = MagicMock()
        gen_cfg1.step_name = "gen1"
        gen_cfg1.element_type = "ApplicationComponent"
        gen_cfg1.input_graph_query = "Q"
        gen_cfg1.instruction = "I"
        gen_cfg1.example = "{}"
        gen_cfg1.max_candidates = 10
        gen_cfg1.batch_size = 5
        gen_cfg1.temperature = None
        gen_cfg1.max_tokens = None
        gen_cfg1.params = None

        gen_cfg2 = MagicMock()
        gen_cfg2.step_name = "gen2"
        gen_cfg2.element_type = "DataObject"
        gen_cfg2.input_graph_query = "Q"
        gen_cfg2.instruction = "I"
        gen_cfg2.example = "{}"
        gen_cfg2.max_candidates = 10
        gen_cfg2.batch_size = 5
        gen_cfg2.temperature = None
        gen_cfg2.max_tokens = None
        gen_cfg2.params = None

        existing_elements_calls = []

        def track_generate(**kwargs):
            existing_elements_calls.append(kwargs.get("existing_elements", []).copy())
            created = [{"id": f"e{len(existing_elements_calls)}"}] if len(existing_elements_calls) == 1 else []
            return {
                "success": True,
                "elements_created": 1,
                "relationships_created": 0,
                "created_elements": created,
                "errors": [],
            }

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg1, gen_cfg2] if phase == "generate" else []
            with patch.object(derivation, "generate_element", side_effect=track_generate):
                list(
                    derivation.run_derivation_iter(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=MagicMock(),
                        phases=["generate"],
                    )
                )

        # First call gets empty list, second call gets elements from first
        assert existing_elements_calls[0] == []
        assert len(existing_elements_calls[1]) == 1


class TestCollectRelationshipRules:
    """Tests for _collect_relationship_rules function."""

    def test_returns_dict_of_rules(self):
        """Should return dict mapping element types to their rules."""
        rules = derivation._collect_relationship_rules()

        assert isinstance(rules, dict)

    def test_contains_rules_for_registered_types(self):
        """Should contain rules for element types with defined rules."""
        rules = derivation._collect_relationship_rules()

        # At least some types should have rules defined
        assert len(rules) > 0

    def test_rule_format_is_tuple_of_lists(self):
        """Each rule entry should be a tuple of (outbound, inbound) lists."""
        rules = derivation._collect_relationship_rules()

        for element_type, (outbound, inbound) in rules.items():
            assert isinstance(outbound, list), f"{element_type} outbound should be list"
            assert isinstance(inbound, list), f"{element_type} inbound should be list"


class TestGetElementProps:
    """Tests for _get_element_props function."""

    def test_returns_properties_for_matching_identifier(self):
        """Should return properties when identifier matches."""
        elements = [
            {"identifier": "elem1", "properties": {"pagerank": 0.5, "kcore": 3}},
            {"identifier": "elem2", "properties": {"pagerank": 0.3}},
        ]

        props = derivation._get_element_props(elements, "elem1")

        assert props == {"pagerank": 0.5, "kcore": 3}

    def test_returns_empty_dict_for_no_match(self):
        """Should return empty dict when identifier not found."""
        elements = [
            {"identifier": "elem1", "properties": {"pagerank": 0.5}},
        ]

        props = derivation._get_element_props(elements, "unknown")

        assert props == {}

    def test_returns_empty_dict_when_no_properties(self):
        """Should return empty dict when element has no properties field."""
        elements = [
            {"identifier": "elem1"},  # No properties field
        ]

        props = derivation._get_element_props(elements, "elem1")

        assert props == {}

    def test_returns_empty_dict_for_empty_list(self):
        """Should return empty dict for empty element list."""
        props = derivation._get_element_props([], "elem1")

        assert props == {}


class TestGetGraphEdgesWithRepoFilter:
    """Tests for _get_graph_edges with repository_name filter."""

    def test_filters_edges_by_repository(self):
        """Should filter edges by repository name when provided."""
        graph_manager = MagicMock()
        graph_manager.query.return_value = [
            {"source": "n1", "target": "n2"},
        ]

        edges = derivation._get_graph_edges(graph_manager, repository_name="my-repo")

        # Verify query was called with repo_name parameter
        call_args = graph_manager.query.call_args
        assert "repo_name" in call_args[1] or (len(call_args[0]) > 1 and "my-repo" in str(call_args[0][1]))
        assert len(edges) == 1

    def test_uses_different_query_for_repo_filter(self):
        """Should use different query when repository_name is provided."""
        graph_manager = MagicMock()
        graph_manager.query.return_value = []

        # Call without repo filter
        derivation._get_graph_edges(graph_manager)
        query_without_filter = graph_manager.query.call_args[0][0]

        # Call with repo filter
        derivation._get_graph_edges(graph_manager, repository_name="test-repo")
        query_with_filter = graph_manager.query.call_args[0][0]

        # Queries should be different
        assert "repository_name" in query_with_filter
        assert "repository_name" not in query_without_filter


class TestRunDerivationRefinePhase:
    """Tests for run_derivation refine phase."""

    def test_runs_refine_phase_when_specified(self):
        """Should run refine phase when included in phases list."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        refine_cfg = MagicMock()
        refine_cfg.step_name = "deduplicate"
        refine_cfg.params = None
        refine_cfg.llm = False

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [refine_cfg] if phase == "refine" else []
            with patch.object(derivation, "run_refine_step") as mock_refine:
                mock_result = MagicMock()
                mock_result.elements_disabled = 2
                mock_result.relationships_deleted = 1
                mock_result.issues_found = 3
                mock_result.errors = []
                mock_refine.return_value = mock_result

                result = derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    phases=["refine"],
                )

        assert result["success"] is True
        assert result["stats"]["elements_disabled"] == 2
        assert result["stats"]["relationships_deleted"] == 1
        assert result["stats"]["refine_issues_found"] == 3

    def test_refine_phase_parses_json_params(self):
        """Should parse JSON params for refine step."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        refine_cfg = MagicMock()
        refine_cfg.step_name = "threshold_filter"
        refine_cfg.params = '{"min_pagerank": 0.1}'
        refine_cfg.llm = False

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [refine_cfg] if phase == "refine" else []
            with patch.object(derivation, "run_refine_step") as mock_refine:
                mock_result = MagicMock()
                mock_result.elements_disabled = 0
                mock_result.relationships_deleted = 0
                mock_result.issues_found = 0
                mock_result.errors = []
                mock_refine.return_value = mock_result

                derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    phases=["refine"],
                )

        # Verify params were passed
        call_kwargs = mock_refine.call_args.kwargs
        assert "params" in call_kwargs
        assert call_kwargs["params"]["min_pagerank"] == 0.1

    def test_refine_phase_handles_exception(self):
        """Should handle exception in refine step."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        refine_cfg = MagicMock()
        refine_cfg.step_name = "failing_refine"
        refine_cfg.params = None
        refine_cfg.llm = False

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [refine_cfg] if phase == "refine" else []
            with patch.object(derivation, "run_refine_step", side_effect=Exception("Refine failed")):
                result = derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    phases=["refine"],
                )

        assert result["success"] is False
        assert "failing_refine" in result["errors"][0]

    def test_verbose_output_for_refine_phase(self, capsys):
        """Should print verbose output during refine phase."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        refine_cfg = MagicMock()
        refine_cfg.step_name = "deduplicate"
        refine_cfg.params = None
        refine_cfg.llm = False

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [refine_cfg] if phase == "refine" else []
            with patch.object(derivation, "run_refine_step") as mock_refine:
                mock_result = MagicMock()
                mock_result.elements_disabled = 0
                mock_result.relationships_deleted = 0
                mock_result.issues_found = 0
                mock_result.errors = []
                mock_refine.return_value = mock_result

                derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    verbose=True,
                    phases=["refine"],
                )

        captured = capsys.readouterr()
        assert "Running 1 refine steps" in captured.out
        assert "Refine: deduplicate" in captured.out


class TestRunDerivationDeferRelationships:
    """Tests for run_derivation with defer_relationships option."""

    def test_deferred_relationships_calls_consolidated_derivation(self):
        """Should call derive_consolidated_relationships when deferred."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_app"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Gen"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "elements_created": 2,
                    "relationships_created": 0,
                    "created_elements": [{"identifier": "e1"}, {"identifier": "e2"}],
                    "errors": [],
                }
                with patch.object(derivation, "derive_consolidated_relationships") as mock_rel:
                    mock_rel.return_value = []

                    derivation.run_derivation(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=MagicMock(),
                        defer_relationships=True,
                        phases=["generate"],
                    )

        # Should call consolidated relationship derivation
        mock_rel.assert_called_once()

    def test_deferred_relationships_creates_relationships(self):
        """Should create relationships from consolidated derivation."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_app"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Gen"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "elements_created": 2,
                    "relationships_created": 0,
                    "created_elements": [
                        {"identifier": "e1", "properties": {"source_pagerank": 0.5}},
                        {"identifier": "e2", "properties": {"source_pagerank": 0.3}},
                    ],
                    "errors": [],
                }
                with patch.object(derivation, "derive_consolidated_relationships") as mock_rel:
                    mock_rel.return_value = [{"source": "e1", "target": "e2", "relationship_type": "AccessRelationship", "confidence": 0.8}]

                    result = derivation.run_derivation(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=MagicMock(),
                        defer_relationships=True,
                        phases=["generate"],
                    )

        # Should have created relationship
        assert result["stats"]["relationships_created"] == 1
        archimate_manager.add_relationship.assert_called_once()

    def test_deferred_relationships_persist_derived_from(self):
        """Saved relationships keep their origin (derived_from) for tiering."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_app"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Gen"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "elements_created": 2,
                    "relationships_created": 0,
                    "created_elements": [
                        {"identifier": "e1", "properties": {"source_pagerank": 0.5}},
                        {"identifier": "e2", "properties": {"source_pagerank": 0.3}},
                    ],
                    "errors": [],
                }
                with patch.object(derivation, "derive_consolidated_relationships") as mock_rel:
                    mock_rel.return_value = [{"source": "e1", "target": "e2", "relationship_type": "Access", "confidence": 0.8, "derived_from": "graph_neighbor"}]

                    derivation.run_derivation(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=MagicMock(),
                        defer_relationships=True,
                        phases=["generate"],
                    )

        saved = archimate_manager.add_relationship.call_args[0][0]
        assert saved.properties["derived_from"] == "graph_neighbor"

    def test_deferred_relationships_get_their_own_step(self):
        """The relationship LLM step is logged as its own step, not under the last element type."""
        engine = MagicMock()
        run_logger = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_app"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Gen"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "elements_created": 2,
                    "relationships_created": 0,
                    "created_elements": [
                        {"identifier": "e1", "properties": {"source_pagerank": 0.5}},
                        {"identifier": "e2", "properties": {"source_pagerank": 0.3}},
                    ],
                    "errors": [],
                }
                with patch.object(derivation, "derive_consolidated_relationships") as mock_rel:
                    mock_rel.return_value = [{"source": "e1", "target": "e2", "relationship_type": "Access", "confidence": 0.8, "derived_from": "graph_neighbor"}]

                    derivation.run_derivation(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=MagicMock(),
                        defer_relationships=True,
                        phases=["generate"],
                        run_logger=run_logger,
                    )

        step_names = [c.args[0] for c in run_logger.step_start.call_args_list]
        assert step_names == ["gen_app", "ConsolidatedRelationships"]
        rel_ctx = run_logger.step_start.return_value
        assert rel_ctx.items_created == 1
        rel_ctx.complete.assert_called()

    def test_deferred_relationships_verbose_output(self, capsys):
        """Should print verbose output for consolidated relationships."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_app"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Gen"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "elements_created": 2,
                    "relationships_created": 0,
                    "created_elements": [{"identifier": "e1"}, {"identifier": "e2"}],
                    "errors": [],
                }
                with patch.object(derivation, "derive_consolidated_relationships") as mock_rel:
                    mock_rel.return_value = [{"source": "e1", "target": "e2", "relationship_type": "AccessRelationship"}]

                    derivation.run_derivation(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=MagicMock(),
                        defer_relationships=True,
                        verbose=True,
                        phases=["generate"],
                    )

        captured = capsys.readouterr()
        assert "Deriving relationships for 2 elements" in captured.out
        assert "1 consolidated relationships" in captured.out


class TestRunDerivationConfigVersions:
    """Tests for run_derivation with config_versions parameter."""

    def test_uses_versioned_configs_when_provided(self):
        """Should use versioned config lookup when config_versions provided."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        config_versions = {
            "derivation": {
                "pagerank": 2,
                "ApplicationComponent": 3,
            }
        }

        with patch.object(derivation.config, "get_derivation_configs_by_version") as mock_get_version:
            mock_get_version.return_value = []
            with patch.object(derivation.config, "get_derivation_configs") as mock_get:
                mock_get.return_value = []

                derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    config_versions=config_versions,
                )

        # Should use versioned lookup
        mock_get_version.assert_called()
        # Should NOT use regular lookup for config retrieval (only for calculation)
        # Actually, it uses versioned for both prep, gen, and refine when config_versions is provided


class TestRunDerivationIterRefinePhase:
    """Tests for run_derivation_iter with refine phase."""

    def test_yields_refine_step_updates(self):
        """Should yield progress updates for refine steps."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        refine_cfg = MagicMock()
        refine_cfg.step_name = "deduplicate"
        refine_cfg.params = None
        refine_cfg.llm = False

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [refine_cfg] if phase == "refine" else []
            with patch.object(derivation, "run_refine_step") as mock_refine:
                mock_result = MagicMock()
                mock_result.elements_disabled = 1
                mock_result.relationships_deleted = 0
                mock_result.issues_found = 2
                mock_result.errors = []
                mock_refine.return_value = mock_result

                updates = list(
                    derivation.run_derivation_iter(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        phases=["refine"],
                    )
                )

        step_updates = [u for u in updates if u.step == "deduplicate"]
        assert len(step_updates) == 1
        assert "2 issues" in step_updates[0].message
        assert "1 disabled" in step_updates[0].message

    def test_yields_error_for_refine_exception(self):
        """Should yield error update when refine step fails."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        refine_cfg = MagicMock()
        refine_cfg.step_name = "failing_refine"
        refine_cfg.params = None
        refine_cfg.llm = False

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [refine_cfg] if phase == "refine" else []
            with patch.object(derivation, "run_refine_step", side_effect=Exception("Refine error")):
                updates = list(
                    derivation.run_derivation_iter(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        phases=["refine"],
                    )
                )

        error_updates = [u for u in updates if u.status == "error"]
        assert len(error_updates) >= 1
        assert "failing_refine" in error_updates[0].message


class TestRunDerivationIterVerbose:
    """Tests for run_derivation_iter with verbose output."""

    def test_prints_verbose_for_prep_steps(self, capsys):
        """Should print verbose output for prep steps."""
        engine = MagicMock()
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 0
        archimate_manager = MagicMock()

        enrich_cfg = MagicMock()
        enrich_cfg.step_name = "pagerank"
        enrich_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [enrich_cfg] if phase == "prep" else []
            with patch.object(derivation, "_get_graph_edges", return_value=[]):
                list(
                    derivation.run_derivation_iter(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        verbose=True,
                        phases=["prep"],
                    )
                )

        captured = capsys.readouterr()
        assert "Prep: pagerank" in captured.out

    def test_prints_verbose_for_generate_steps(self, capsys):
        """Should print verbose output for generate steps."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_app"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Gen"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "elements_created": 0,
                    "relationships_created": 0,
                    "created_elements": [],
                    "errors": [],
                }
                list(
                    derivation.run_derivation_iter(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=MagicMock(),
                        verbose=True,
                        phases=["generate"],
                    )
                )

        captured = capsys.readouterr()
        assert "Generate: gen_app" in captured.out

    def test_prints_verbose_for_refine_steps(self, capsys):
        """Should print verbose output for refine steps."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        refine_cfg = MagicMock()
        refine_cfg.step_name = "deduplicate"
        refine_cfg.params = None
        refine_cfg.llm = False

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [refine_cfg] if phase == "refine" else []
            with patch.object(derivation, "run_refine_step") as mock_refine:
                mock_result = MagicMock()
                mock_result.elements_disabled = 0
                mock_result.relationships_deleted = 0
                mock_result.issues_found = 0
                mock_result.errors = []
                mock_refine.return_value = mock_result

                list(
                    derivation.run_derivation_iter(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        verbose=True,
                        phases=["refine"],
                    )
                )

        captured = capsys.readouterr()
        assert "Refine: deduplicate" in captured.out


class TestRunDerivationWithRunLoggerErrors:
    """Tests for run_derivation run_logger error handling."""

    def test_logs_step_error_for_prep_failures(self):
        """Should log step error when prep step fails."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        run_logger = MagicMock()
        step_ctx = MagicMock()
        run_logger.step_start.return_value = step_ctx

        enrich_cfg = MagicMock()
        enrich_cfg.step_name = "pagerank"
        enrich_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [enrich_cfg] if phase == "prep" else []
            with patch.object(derivation, "_run_prep_step", return_value={"success": False, "errors": ["Test prep error"]}):
                derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    run_logger=run_logger,
                    phases=["prep"],
                )

        # Should call step_ctx.error
        step_ctx.error.assert_called()

    def test_logs_step_complete_for_generate_success(self):
        """Should log step complete when generate succeeds."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        run_logger = MagicMock()
        step_ctx = MagicMock()
        run_logger.step_start.return_value = step_ctx

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_app"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Gen"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "elements_created": 2,
                    "relationships_created": 0,
                    "created_elements": [],
                    "created_relationships": [],
                    "errors": [],
                }
                derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    llm_query_fn=MagicMock(),
                    run_logger=run_logger,
                    phases=["generate"],
                )

        step_ctx.complete.assert_called()
        assert step_ctx.items_created == 2


class TestRunDerivationProgressReporter:
    """Additional tests for progress reporter integration."""

    def test_progress_start_step_for_generate(self):
        """Should call start_step for each generate step."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        progress = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "gen_app"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Gen"
        gen_cfg.example = "{}"
        gen_cfg.max_candidates = 10
        gen_cfg.batch_size = 5
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None
        gen_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [gen_cfg] if phase == "generate" else []
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.return_value = {
                    "success": True,
                    "elements_created": 2,
                    "relationships_created": 1,
                    "created_elements": [],
                    "errors": [],
                }
                derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    llm_query_fn=MagicMock(),
                    progress=progress,
                    phases=["generate"],
                )

        progress.start_step.assert_called_with("gen_app")
        # complete_step should include element and relationship counts
        complete_call = progress.complete_step.call_args
        assert "2 elements" in complete_call[0][0]
        assert "1 relationships" in complete_call[0][0]

    def test_progress_complete_phase_with_disabled_elements(self):
        """Should include disabled count in phase completion message."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        progress = MagicMock()

        refine_cfg = MagicMock()
        refine_cfg.step_name = "deduplicate"
        refine_cfg.params = None
        refine_cfg.llm = False

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: [refine_cfg] if phase == "refine" else []
            with patch.object(derivation, "run_refine_step") as mock_refine:
                mock_result = MagicMock()
                mock_result.elements_disabled = 5
                mock_result.relationships_deleted = 0
                mock_result.issues_found = 5
                mock_result.errors = []
                mock_refine.return_value = mock_result

                derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    progress=progress,
                    phases=["refine"],
                )

        complete_phase_call = progress.complete_phase.call_args
        assert "5 disabled" in complete_phase_call[0][0]


class TestRelationshipLLMConfig:
    """The enabled relationship-phase config row drives the LLM relationship pass."""

    @staticmethod
    def _row(instruction="rules", params='{"temperature": 0.0, "min_confidence": 0.6, "persona": "P"}', name="GlobalRelationships"):
        return SimpleNamespace(step_name=name, instruction=instruction, params=params)

    def test_no_enabled_row_skips_the_llm_pass(self):
        assert derivation._relationship_llm_config([]) is None

    def test_row_supplies_instruction_and_cutoff(self):
        assert derivation._relationship_llm_config([self._row()]) == RelationshipLLMConfig(instruction="rules", min_confidence=0.6, persona="P")

    def test_row_without_min_confidence_is_an_error(self):
        with pytest.raises(ValueError, match="min_confidence"):
            derivation._relationship_llm_config([self._row(params='{"temperature": 0.0}')])

    def test_llm_proposals_off_leaves_relationships_to_structure(self):
        row = self._row(params='{"min_confidence": 0.6, "persona": "P", "llm_proposals": false}')

        assert derivation._relationship_llm_config([row]) is None

    def test_llm_proposals_on_keeps_the_llm_pass(self):
        row = self._row(params='{"min_confidence": 0.6, "persona": "P", "llm_proposals": true}')

        assert derivation._relationship_llm_config([row]) == RelationshipLLMConfig(instruction="rules", min_confidence=0.6, persona="P")

    def test_llm_proposals_must_be_a_boolean(self):
        with pytest.raises(ValueError, match="llm_proposals"):
            derivation._relationship_llm_config([self._row(params='{"min_confidence": 0.6, "persona": "P", "llm_proposals": "no"}')])

    @pytest.mark.parametrize("runner", ["run_derivation", "run_derivation_iter"])
    def test_runs_that_never_derive_relationships_do_not_read_the_row(self, runner):
        """A prep-only run on an empty model must not fail on relationship rows it never uses."""
        archimate_manager = MagicMock()
        archimate_manager.get_elements.return_value = []
        broken = [self._row(name="A"), self._row(name="B")]  # two enabled rows is an error when read

        prep_rows = [SimpleNamespace(step_name="pagerank", params=None)]
        rows = {"relationship": broken, "prep": prep_rows}

        with (
            patch.object(derivation.config, "get_derivation_configs") as mock_get,
            patch.object(derivation, "_run_prep_step", return_value={}),
        ):
            mock_get.side_effect = lambda engine, enabled_only, phase: rows.get(phase, [])
            run = getattr(derivation, runner)(engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=archimate_manager, phases=["prep"])
            if runner == "run_derivation_iter":
                list(run)

    def test_row_without_instruction_is_an_error(self):
        with pytest.raises(ValueError, match="instruction"):
            derivation._relationship_llm_config([self._row(instruction="")])

    def test_two_enabled_rows_are_an_error(self):
        with pytest.raises(ValueError, match="Only one"):
            derivation._relationship_llm_config([self._row(), self._row(name="Other")])


def _run_derivation(**kwargs):
    return derivation.run_derivation(**kwargs)


def _run_derivation_iter(**kwargs):
    return list(derivation.run_derivation_iter(**kwargs))


class TestRelationshipConfigReachesTheRelationshipPass:
    """Both runners pass the relationship row to both relationship paths."""

    EXPECTED = RelationshipLLMConfig(instruction="rules", min_confidence=0.6, persona="P")

    @staticmethod
    def _configs(engine, enabled_only, phase):
        if phase == "generate":
            return [
                SimpleNamespace(
                    step_name="ApplicationComponent",
                    element_type="ApplicationComponent",
                    input_graph_query="MATCH (n) RETURN n",
                    instruction="Gen",
                    example="{}",
                    max_candidates=10,
                    batch_size=5,
                    temperature=None,
                    max_tokens=None,
                    params=None,
                )
            ]
        if phase == "relationship":
            return [SimpleNamespace(step_name="GlobalRelationships", instruction="rules", params='{"min_confidence": 0.6, "persona": "P"}')]
        return []

    def _run(self, runner, defer):
        generated = {"success": True, "elements_created": 1, "relationships_created": 0, "created_elements": [{"identifier": "e1"}], "errors": []}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=self._configs),
            patch.object(derivation, "generate_element", return_value=generated) as gen,
            patch.object(derivation, "derive_consolidated_relationships", return_value=[]) as consolidated,
        ):
            runner(
                engine=MagicMock(),
                graph_manager=MagicMock(),
                archimate_manager=MagicMock(),
                llm_query_fn=MagicMock(),
                defer_relationships=defer,
                phases=["generate"],
            )
        return gen, consolidated

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_deferred_path(self, runner):
        _, consolidated = self._run(runner, defer=True)

        assert consolidated.call_args.kwargs["llm_config"] == self.EXPECTED

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_per_element_path(self, runner):
        gen, _ = self._run(runner, defer=False)

        assert gen.call_args.kwargs["relationship_config"] == self.EXPECTED


class TestPerCandidateConfig:
    """Per-candidate naming mode comes from the element row's params.per_candidate."""

    def test_no_params_means_batch_mode(self):
        assert derivation._per_candidate_config(None) is None
        assert derivation._per_candidate_config('{"temperature": 0.0}') is None

    def test_params_supply_min_pool_and_rules(self):
        params = '{"temperature": 0.0, "per_candidate": {"min_pool": 6, "rules": "R", "persona": "P"}}'

        assert derivation._per_candidate_config(params) == PerCandidateConfig(min_pool=6, rules="R", persona="P")

    @pytest.mark.parametrize("value", ['{"min_pool": 6}', '{"rules": "R"}'])
    def test_incomplete_per_candidate_is_an_error(self, value):
        with pytest.raises(ValueError, match="per_candidate"):
            derivation._per_candidate_config(f'{{"per_candidate": {value}}}')

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_generate_element_receives_it(self, runner):
        cfg = SimpleNamespace(
            step_name="ApplicationComponent",
            element_type="ApplicationComponent",
            input_graph_query="MATCH (n) RETURN n",
            instruction="Gen",
            example="{}",
            max_candidates=10,
            batch_size=5,
            temperature=None,
            max_tokens=None,
            params='{"per_candidate": {"min_pool": 6, "rules": "R", "persona": "P"}}',
        )
        generated = {"success": True, "elements_created": 0, "relationships_created": 0, "created_elements": [], "errors": []}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: [cfg] if phase == "generate" else []),
            patch.object(derivation, "generate_element", return_value=generated) as gen,
        ):
            runner(
                engine=MagicMock(),
                graph_manager=MagicMock(),
                archimate_manager=MagicMock(),
                llm_query_fn=MagicMock(),
                defer_relationships=False,
                phases=["generate"],
            )

        assert gen.call_args.kwargs["per_candidate"] == PerCandidateConfig(min_pool=6, rules="R", persona="P")


class TestNamingConfig:
    """The isolated naming step comes from the element row's params.naming."""

    def test_no_naming_key_keeps_structure_names(self):
        assert derivation._naming_config(None) is None
        assert derivation._naming_config('{"temperature": 0.0}') is None

    def test_params_supply_instruction_and_samples(self):
        from deriva.modules.derivation.base import NamingConfig

        assert derivation._naming_config('{"naming": {"instruction": "N", "samples": 5}}') == NamingConfig(instruction="N", samples=5)
        assert derivation._naming_config('{"naming": {"instruction": "N"}}') == NamingConfig(instruction="N", samples=1)  # single call by default: no voting

    def test_naming_without_instruction_is_an_error(self):
        with pytest.raises(ValueError, match="naming"):
            derivation._naming_config('{"naming": {"samples": 3}}')

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_generate_element_receives_it(self, runner):
        from deriva.modules.derivation.base import NamingConfig

        cfg = SimpleNamespace(
            step_name="ApplicationComponent",
            element_type="ApplicationComponent",
            input_graph_query="MATCH (n) RETURN n",
            instruction="Gen",
            example="{}",
            max_candidates=10,
            batch_size=5,
            temperature=None,
            max_tokens=None,
            params='{"naming": {"instruction": "N", "samples": 3}}',
        )
        generated = {"success": True, "elements_created": 0, "relationships_created": 0, "created_elements": [], "errors": []}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: [cfg] if phase == "generate" else []),
            patch.object(derivation, "generate_element", return_value=generated) as gen,
        ):
            runner(engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=MagicMock(), llm_query_fn=MagicMock(), defer_relationships=False, phases=["generate"])

        assert gen.call_args.kwargs["naming"] == NamingConfig(instruction="N", samples=3)


class TestPatternLabelsConfig:
    """Which candidates the step's name patterns filter comes from the element row's params.pattern_labels."""

    def test_without_the_key_patterns_filter_every_candidate(self):
        assert derivation._pattern_labels(None) is None
        assert derivation._pattern_labels('{"temperature": 0.0}') is None

    def test_params_supply_the_labels(self):
        assert derivation._pattern_labels('{"pattern_labels": ["File"]}') == frozenset({"File"})

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_generate_element_receives_them(self, runner):
        cfg = SimpleNamespace(
            step_name="Node",
            element_type="Node",
            input_graph_query="MATCH (n) RETURN n",
            instruction="Gen",
            example="{}",
            max_candidates=10,
            batch_size=5,
            temperature=None,
            max_tokens=None,
            params='{"pattern_labels": ["File"]}',
        )
        generated = {"success": True, "elements_created": 0, "relationships_created": 0, "created_elements": [], "errors": []}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: [cfg] if phase == "generate" else []),
            patch.object(derivation, "generate_element", return_value=generated) as gen,
        ):
            runner(engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=MagicMock(), llm_query_fn=MagicMock(), defer_relationships=False, phases=["generate"])

        assert gen.call_args.kwargs["pattern_labels"] == frozenset({"File"})


class TestElementPromptConfig:
    """The batch element prompt's texts come from the element row's params.prompt."""

    TEXTS = {"persona": "P", "candidates": "C", "rules": "1.\n{abstention}3.", "abstention": "2.\n"}

    def test_without_the_key_there_are_no_texts(self):
        assert derivation._element_prompt(None) is None
        assert derivation._element_prompt('{"temperature": 0.0}') is None

    def test_params_supply_the_texts(self):
        from deriva.modules.derivation.base import ElementPrompt

        assert derivation._element_prompt(json.dumps({"prompt": self.TEXTS})) == ElementPrompt(**self.TEXTS)

    def test_incomplete_texts_are_an_error(self):
        with pytest.raises(ValueError, match="prompt"):
            derivation._element_prompt(json.dumps({"prompt": {"persona": "P"}}))

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_generate_element_receives_them(self, runner):
        cfg = SimpleNamespace(
            step_name="DataObject",
            element_type="DataObject",
            input_graph_query="MATCH (n) RETURN n",
            instruction="Gen",
            example="{}",
            max_candidates=10,
            batch_size=5,
            temperature=None,
            max_tokens=None,
            params=json.dumps({"prompt": self.TEXTS}),
        )
        generated = {"success": True, "elements_created": 0, "relationships_created": 0, "created_elements": [], "errors": []}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: [cfg] if phase == "generate" else []),
            patch.object(derivation, "generate_element", return_value=generated) as gen,
        ):
            runner(engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=MagicMock(), llm_query_fn=MagicMock(), defer_relationships=False, phases=["generate"])

        assert gen.call_args.kwargs["prompt"].persona == "P"


class TestSkipWhenDirectoryIs:
    """Element types whose sources take a directory's candidates out come from params.skip_when_directory_is."""

    def test_without_the_key_nothing_is_skipped(self):
        assert derivation._skip_when_directory_is(None) is None
        assert derivation._skip_when_directory_is('{"temperature": 0.0}') is None

    def test_params_supply_the_element_types(self):
        assert derivation._skip_when_directory_is('{"skip_when_directory_is": ["ApplicationComponent"]}') == frozenset({"ApplicationComponent"})

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_generate_element_receives_them(self, runner):
        cfg = SimpleNamespace(
            step_name="SystemSoftware",
            element_type="SystemSoftware",
            input_graph_query="MATCH (n) RETURN n",
            instruction="Gen",
            example="{}",
            max_candidates=10,
            batch_size=5,
            temperature=None,
            max_tokens=None,
            params='{"skip_when_directory_is": ["ApplicationComponent"]}',
        )
        generated = {"success": True, "elements_created": 0, "relationships_created": 0, "created_elements": [], "errors": []}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: [cfg] if phase == "generate" else []),
            patch.object(derivation, "generate_element", return_value=generated) as gen,
        ):
            runner(engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=MagicMock(), llm_query_fn=MagicMock(), defer_relationships=False, phases=["generate"])

        assert gen.call_args.kwargs["skip_when_directory_is"] == frozenset({"ApplicationComponent"})

    def test_generate_element_passes_them_to_the_module(self):
        from deriva.modules.derivation.base import GenerationResult

        with (
            patch.object(derivation, "_get_derivation") as mock_get,
            patch.object(derivation.config, "get_derivation_patterns", return_value={}),
        ):
            mock_get.return_value.generate.return_value = GenerationResult(success=True)
            derivation.generate_element(
                graph_manager=MagicMock(),
                archimate_manager=MagicMock(),
                engine=MagicMock(),
                llm_query_fn=MagicMock(),
                element_type="SystemSoftware",
                query="MATCH (n) RETURN n",
                instruction="test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                skip_when_directory_is=frozenset({"ApplicationComponent"}),
            )

        assert mock_get.return_value.generate.call_args.kwargs["skip_when_directory_is"] == frozenset({"ApplicationComponent"})


class TestSkipSubtypesConfig:
    """One element per contract: params.skip_subtypes leaves out candidate types that inherit from another candidate."""

    def test_without_the_key_no_candidate_is_left_out(self):
        assert derivation._skip_subtypes(None) is False
        assert derivation._skip_subtypes('{"temperature": 0.0}') is False

    def test_params_switch_it_on(self):
        assert derivation._skip_subtypes('{"skip_subtypes": true}') is True

    def test_a_non_boolean_value_is_an_error(self):
        with pytest.raises(ValueError, match="skip_subtypes"):
            derivation._skip_subtypes('{"skip_subtypes": "yes"}')

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_generate_element_receives_it(self, runner):
        cfg = SimpleNamespace(
            step_name="ApplicationService",
            element_type="ApplicationService",
            input_graph_query="MATCH (n) RETURN n",
            instruction="Gen",
            example="{}",
            max_candidates=10,
            batch_size=5,
            temperature=None,
            max_tokens=None,
            params='{"skip_subtypes": true}',
        )
        generated = {"success": True, "elements_created": 0, "relationships_created": 0, "created_elements": [], "errors": []}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: [cfg] if phase == "generate" else []),
            patch.object(derivation, "generate_element", return_value=generated) as gen,
        ):
            runner(engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=MagicMock(), llm_query_fn=MagicMock(), defer_relationships=False, phases=["generate"])

        assert gen.call_args.kwargs["skip_subtypes"] is True

    def test_generate_element_passes_it_to_the_module(self):
        from deriva.modules.derivation.base import GenerationResult

        with (
            patch.object(derivation, "_get_derivation") as mock_get,
            patch.object(derivation.config, "get_derivation_patterns", return_value={}),
        ):
            mock_get.return_value.generate.return_value = GenerationResult(success=True)
            derivation.generate_element(
                graph_manager=MagicMock(),
                archimate_manager=MagicMock(),
                engine=MagicMock(),
                llm_query_fn=MagicMock(),
                element_type="ApplicationService",
                query="MATCH (n) RETURN n",
                instruction="test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                skip_subtypes=True,
            )

        assert mock_get.return_value.generate.call_args.kwargs["skip_subtypes"] is True


class TestDeployableUnitsConfig:
    """Components at the deployable-unit level: params.deployable_units names the unit files and the minimum."""

    def test_without_the_key_there_is_no_unit_level(self):
        assert derivation._deployable_units(None) is None
        assert derivation._deployable_units('{"temperature": 0.0}') is None

    def test_params_set_the_files_and_the_minimum(self):
        from deriva.modules.derivation.base import UnitFilter

        units = derivation._deployable_units('{"deployable_units": {"file_names": ["pom.xml", "Dockerfile"], "min_units": 2}}')

        assert units == UnitFilter(file_names=frozenset({"pom.xml", "dockerfile"}), min_units=2)

    @pytest.mark.parametrize(
        "value",
        [
            True,
            {"min_units": 2},
            {"file_names": [], "min_units": 2},
            {"file_names": ["pom.xml", ""], "min_units": 2},
            {"file_names": ["pom.xml"]},
            {"file_names": ["pom.xml"], "min_units": 0},
            {"file_names": ["pom.xml"], "min_units": True},
        ],
    )
    def test_invalid_settings_are_an_error(self, value):
        with pytest.raises(ValueError, match="deployable_units"):
            derivation._deployable_units(json.dumps({"deployable_units": value}))

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_generate_element_receives_it(self, runner):
        from deriva.modules.derivation.base import UnitFilter

        cfg = SimpleNamespace(
            step_name="ApplicationComponent",
            element_type="ApplicationComponent",
            input_graph_query="MATCH (n) RETURN n",
            instruction="Gen",
            example="{}",
            max_candidates=10,
            batch_size=5,
            temperature=None,
            max_tokens=None,
            params='{"deployable_units": {"file_names": ["pom.xml"], "min_units": 2}}',
        )
        generated = {"success": True, "elements_created": 0, "relationships_created": 0, "created_elements": [], "errors": []}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: [cfg] if phase == "generate" else []),
            patch.object(derivation, "generate_element", return_value=generated) as gen,
        ):
            runner(engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=MagicMock(), llm_query_fn=MagicMock(), defer_relationships=False, phases=["generate"])

        assert gen.call_args.kwargs["deployable_units"] == UnitFilter(file_names=frozenset({"pom.xml"}), min_units=2)

    def test_generate_element_passes_it_to_the_module(self):
        from deriva.modules.derivation.base import GenerationResult, UnitFilter

        units = UnitFilter(file_names=frozenset({"pom.xml"}), min_units=2)
        with (
            patch.object(derivation, "_get_derivation") as mock_get,
            patch.object(derivation.config, "get_derivation_patterns", return_value={}),
        ):
            mock_get.return_value.generate.return_value = GenerationResult(success=True)
            derivation.generate_element(
                graph_manager=MagicMock(),
                archimate_manager=MagicMock(),
                engine=MagicMock(),
                llm_query_fn=MagicMock(),
                element_type="ApplicationComponent",
                query="MATCH (n) RETURN n",
                instruction="Gen",
                example="{}",
                max_candidates=10,
                batch_size=5,
                existing_elements=[],
                deployable_units=units,
            )

        assert mock_get.return_value.generate.call_args.kwargs["deployable_units"] == units


class TestSkipNestedConfig:
    """One module, one element: params.skip_nested names the file type and the share a nested directory must hold."""

    def test_without_the_key_no_candidate_is_left_out(self):
        assert derivation._skip_nested(None) is None
        assert derivation._skip_nested('{"temperature": 0.0}') is None
        assert derivation._skip_nested('{"skip_nested": null}') is None

    def test_a_share_of_one_is_valid(self):
        from deriva.modules.derivation.base import NestedFilter

        assert derivation._skip_nested('{"skip_nested": {"file_type": "source", "min_share": 1}}') == NestedFilter(file_type="source", min_share=1.0)

    def test_the_file_type_must_be_a_registered_one(self):
        registered = [SimpleNamespace(file_type="source"), SimpleNamespace(file_type="docs")]
        with patch.object(derivation.config, "get_file_types", return_value=registered):
            assert derivation._skip_nested('{"skip_nested": {"file_type": "source", "min_share": 0.9}}', engine=MagicMock()) is not None
            with pytest.raises(ValueError, match="skip_nested.*file type"):
                derivation._skip_nested('{"skip_nested": {"file_type": "sources", "min_share": 0.9}}', engine=MagicMock())

    def test_params_set_the_file_type_and_the_share(self):
        from deriva.modules.derivation.base import NestedFilter

        assert derivation._skip_nested('{"skip_nested": {"file_type": "source", "min_share": 0.9}}') == NestedFilter(file_type="source", min_share=0.9)

    @pytest.mark.parametrize(
        "value",
        [
            True,
            {"min_share": 0.9},
            {"file_type": "", "min_share": 0.9},
            {"file_type": "source"},
            {"file_type": "source", "min_share": "0.9"},
            {"file_type": "source", "min_share": True},
            {"file_type": "source", "min_share": 0},
            {"file_type": "source", "min_share": 1.5},
        ],
    )
    def test_invalid_settings_are_an_error(self, value):
        with pytest.raises(ValueError, match="skip_nested"):
            derivation._skip_nested(json.dumps({"skip_nested": value}))

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_generate_element_receives_it(self, runner):
        from deriva.modules.derivation.base import NestedFilter

        cfg = SimpleNamespace(
            step_name="ApplicationComponent",
            element_type="ApplicationComponent",
            input_graph_query="MATCH (n) RETURN n",
            instruction="Gen",
            example="{}",
            max_candidates=10,
            batch_size=5,
            temperature=None,
            max_tokens=None,
            params='{"skip_nested": {"file_type": "source", "min_share": 0.9}}',
        )
        generated = {"success": True, "elements_created": 0, "relationships_created": 0, "created_elements": [], "errors": []}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: [cfg] if phase == "generate" else []),
            patch.object(derivation.config, "get_file_types", return_value=[SimpleNamespace(file_type="source")]),
            patch.object(derivation, "generate_element", return_value=generated) as gen,
        ):
            runner(engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=MagicMock(), llm_query_fn=MagicMock(), defer_relationships=False, phases=["generate"])

        assert gen.call_args.kwargs["skip_nested"] == NestedFilter(file_type="source", min_share=0.9)

    def test_generate_element_passes_it_to_the_module(self):
        from deriva.modules.derivation.base import GenerationResult, NestedFilter

        nested = NestedFilter(file_type="source", min_share=0.9)
        with (
            patch.object(derivation, "_get_derivation") as mock_get,
            patch.object(derivation.config, "get_derivation_patterns", return_value={}),
        ):
            mock_get.return_value.generate.return_value = GenerationResult(success=True)
            derivation.generate_element(
                graph_manager=MagicMock(),
                archimate_manager=MagicMock(),
                engine=MagicMock(),
                llm_query_fn=MagicMock(),
                element_type="ApplicationComponent",
                query="MATCH (n) RETURN n",
                instruction="test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                skip_nested=nested,
            )

        assert mock_get.return_value.generate.call_args.kwargs["skip_nested"] == nested


class TestGraphFilterConfig:
    """The step's k-core threshold and the candidates it applies to come from params.graph_filter."""

    def test_without_the_key_there_is_no_threshold(self):
        assert derivation._graph_filter(None) is None
        assert derivation._graph_filter('{"temperature": 0.0}') is None

    def test_params_supply_the_threshold_and_labels(self):
        from deriva.modules.derivation.base import GraphFilter

        assert derivation._graph_filter('{"graph_filter": {"min_kcore_percentile": 30, "labels": ["File"]}}') == GraphFilter(min_kcore_percentile=30.0, labels=frozenset({"File"}))
        assert derivation._graph_filter('{"graph_filter": {"min_kcore_percentile": 30}}') == GraphFilter(min_kcore_percentile=30.0)

    @pytest.mark.parametrize("settings", ['{"labels": ["File"]}', '{"min_kcore_percentile": "high"}', '{"min_kcore_percentile": 30, "labels": "File"}'])
    def test_invalid_settings_are_an_error(self, settings):
        with pytest.raises(ValueError, match="graph_filter"):
            derivation._graph_filter(f'{{"graph_filter": {settings}}}')

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_generate_element_receives_it(self, runner):
        from deriva.modules.derivation.base import GraphFilter

        cfg = SimpleNamespace(
            step_name="Node",
            element_type="Node",
            input_graph_query="MATCH (n) RETURN n",
            instruction="Gen",
            example="{}",
            max_candidates=10,
            batch_size=5,
            temperature=None,
            max_tokens=None,
            params='{"graph_filter": {"min_kcore_percentile": 30, "labels": ["File"]}}',
        )
        generated = {"success": True, "elements_created": 0, "relationships_created": 0, "created_elements": [], "errors": []}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: [cfg] if phase == "generate" else []),
            patch.object(derivation, "generate_element", return_value=generated) as gen,
        ):
            runner(engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=MagicMock(), llm_query_fn=MagicMock(), defer_relationships=False, phases=["generate"])

        assert gen.call_args.kwargs["graph_filter"] == GraphFilter(min_kcore_percentile=30.0, labels=frozenset({"File"}))

    def test_generate_element_passes_it_to_the_module(self):
        from deriva.modules.derivation.base import GenerationResult, GraphFilter

        graph_filter = GraphFilter(min_kcore_percentile=30.0, labels=frozenset({"File"}))
        with (
            patch.object(derivation, "_get_derivation") as mock_get,
            patch.object(derivation.config, "get_derivation_patterns", return_value={}),
        ):
            mock_get.return_value.generate.return_value = GenerationResult(success=True)
            derivation.generate_element(
                graph_manager=MagicMock(),
                archimate_manager=MagicMock(),
                engine=MagicMock(),
                llm_query_fn=MagicMock(),
                element_type="Node",
                query="MATCH (n) RETURN n",
                instruction="test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                graph_filter=graph_filter,
            )

        assert mock_get.return_value.generate.call_args.kwargs["graph_filter"] == graph_filter


class TestRoleConfig:
    """Candidates classified into roles come from the element row's params.roles."""

    def test_without_the_key_there_is_no_role_path(self):
        assert derivation._role_config(None) is None
        assert derivation._role_config('{"temperature": 0.0}') is None

    def test_params_supply_labels_instruction_names_and_options(self):
        from deriva.modules.derivation.base import RoleConfig

        params = '{"roles": {"labels": ["Technology"], "instruction": "I", "names": {"a": "A"}, "documentation": "D {members}", "missing_retries": 2}}'

        assert derivation._role_config(params) == RoleConfig(labels=frozenset({"Technology"}), instruction="I", names={"a": "A"}, documentation="D {members}", missing_retries=2)

    def test_params_can_ask_for_one_element_per_candidate(self):
        params = '{"roles": {"labels": ["Technology"], "instruction": "I", "names": {"a": "A"}, "element_per": "candidate"}}'

        assert derivation._role_config(params).element_per == "candidate"

    def test_element_per_must_be_role_or_candidate(self):
        with pytest.raises(ValueError, match="element_per"):
            derivation._role_config('{"roles": {"labels": ["T"], "instruction": "I", "names": {"a": "A"}, "element_per": "group"}}')

    def test_params_can_name_candidates_from_a_template(self):
        params = json.dumps(
            {
                "roles": {
                    "labels": ["File"],
                    "instruction": "I",
                    "names": {"a": "A"},
                    "element_per": "candidate",
                    "name_template": "{container} {subject} {role}",
                    "container_type": "ApplicationComponent",
                    "show_path": True,
                }
            }
        )

        roles = derivation._role_config(params)

        assert (roles.name_template, roles.container_type, roles.show_path) == ("{container} {subject} {role}", "ApplicationComponent", True)

    def test_params_can_name_role_elements_with_the_naming_call(self):
        params = {"roles": {"labels": ["T"], "instruction": "I", "names": {"a": "A"}, "element_per": "candidate", "naming_call": True}, "naming": {"instruction": "N"}}

        assert derivation._role_config(json.dumps(params)).naming_call is True

    @pytest.mark.parametrize(
        "params",
        [
            {"roles": {"labels": ["T"], "instruction": "I", "names": {"a": "A"}, "element_per": "candidate", "naming_call": "yes"}, "naming": {"instruction": "N"}},
            {"roles": {"labels": ["T"], "instruction": "I", "names": {"a": "A"}, "element_per": "role", "naming_call": True}, "naming": {"instruction": "N"}},
            {"roles": {"labels": ["T"], "instruction": "I", "names": {"a": "A"}, "element_per": "candidate", "naming_call": True}},
        ],
    )
    def test_invalid_naming_call_settings_are_an_error(self, params):
        with pytest.raises(ValueError, match="naming"):
            derivation._role_config(json.dumps(params))

    @pytest.mark.parametrize(
        "extra",
        [
            {"element_per": "candidate", "name_template": 3},
            {"element_per": "candidate", "show_path": "yes"},
            {"element_per": "candidate", "container_type": ["ApplicationComponent"]},
            {"element_per": "role", "name_template": "{subject} {role}"},
        ],
    )
    def test_invalid_template_settings_are_an_error(self, extra):
        with pytest.raises(ValueError, match="roles"):
            derivation._role_config(json.dumps({"roles": {"labels": ["T"], "instruction": "I", "names": {"a": "A"}, **extra}}))

    @pytest.mark.parametrize("value", ['{"instruction": "I", "names": {"a": "A"}}', '{"labels": ["T"], "names": {"a": "A"}}', '{"labels": ["T"], "instruction": "I"}'])
    def test_incomplete_roles_are_an_error(self, value):
        with pytest.raises(ValueError, match="roles"):
            derivation._role_config(f'{{"roles": {value}}}')

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_generate_element_receives_them(self, runner):
        cfg = SimpleNamespace(
            step_name="Node",
            element_type="Node",
            input_graph_query="MATCH (n) RETURN n",
            instruction="Gen",
            example="{}",
            max_candidates=10,
            batch_size=5,
            temperature=None,
            max_tokens=None,
            params='{"roles": {"labels": ["Technology"], "instruction": "I", "names": {"a": "A"}}}',
        )
        generated = {"success": True, "elements_created": 0, "relationships_created": 0, "created_elements": [], "errors": []}
        with (
            patch.object(derivation.config, "get_derivation_configs", side_effect=lambda engine, enabled_only, phase: [cfg] if phase == "generate" else []),
            patch.object(derivation, "generate_element", return_value=generated) as gen,
        ):
            runner(engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=MagicMock(), llm_query_fn=MagicMock(), defer_relationships=False, phases=["generate"])

        assert gen.call_args.kwargs["roles"].names == {"a": "A"}

    def test_generate_element_passes_them_to_the_module(self):
        from deriva.modules.derivation.base import GenerationResult, RoleConfig

        roles = RoleConfig(labels=frozenset({"Technology"}), instruction="I", names={"a": "A"})
        with (
            patch.object(derivation, "_get_derivation") as mock_get,
            patch.object(derivation.config, "get_derivation_patterns", return_value={}),
        ):
            mock_get.return_value.generate.return_value = GenerationResult(success=True)
            derivation.generate_element(
                graph_manager=MagicMock(),
                archimate_manager=MagicMock(),
                engine=MagicMock(),
                llm_query_fn=MagicMock(),
                element_type="Node",
                query="MATCH (n) RETURN n",
                instruction="test",
                example="{}",
                max_candidates=10,
                batch_size=5,
                roles=roles,
            )

        assert mock_get.return_value.generate.call_args.kwargs["roles"] == roles


class TestRelationshipTemperature:
    """The relationship row's temperature column sets the consolidated relationship pass temperature."""

    def test_row_temperature_is_part_of_the_config(self):
        row = SimpleNamespace(step_name="GlobalRelationships", instruction="rules", params='{"min_confidence": 0.6, "persona": "P"}', temperature=0.0)

        assert derivation._relationship_llm_config([row]).temperature == 0.0

    @pytest.mark.parametrize("runner", [_run_derivation, _run_derivation_iter])
    def test_consolidated_pass_uses_it(self, runner):
        gen_cfg = SimpleNamespace(
            step_name="ApplicationComponent",
            element_type="ApplicationComponent",
            input_graph_query="MATCH (n) RETURN n",
            instruction="Gen",
            example="{}",
            max_candidates=10,
            batch_size=5,
            temperature=None,
            max_tokens=None,
            params=None,
        )
        rel = SimpleNamespace(step_name="GlobalRelationships", instruction="rules", params='{"min_confidence": 0.6, "persona": "P"}', temperature=0.0)
        generated = {"success": True, "elements_created": 1, "relationships_created": 0, "created_elements": [{"identifier": "e1"}], "errors": []}
        with (
            patch.object(
                derivation.config,
                "get_derivation_configs",
                side_effect=lambda engine, enabled_only, phase: {"generate": [gen_cfg], "relationship": [rel]}.get(phase, []),
            ),
            patch.object(derivation, "generate_element", return_value=generated),
            patch.object(derivation, "derive_consolidated_relationships", return_value=[]) as consolidated,
        ):
            runner(engine=MagicMock(), graph_manager=MagicMock(), archimate_manager=MagicMock(), llm_query_fn=MagicMock(), defer_relationships=True, phases=["generate"])

        assert consolidated.call_args.kwargs["temperature"] == 0.0
