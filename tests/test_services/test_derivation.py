"""Tests for services.derivation module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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


class TestEnrichmentAlgorithms:
    """Tests for ENRICHMENT_ALGORITHMS constant."""

    def test_contains_expected_algorithms(self):
        """Should contain expected enrichment algorithms."""
        assert "pagerank" in derivation.ENRICHMENT_ALGORITHMS
        assert "louvain_communities" in derivation.ENRICHMENT_ALGORITHMS
        assert "k_core_filter" in derivation.ENRICHMENT_ALGORITHMS


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
