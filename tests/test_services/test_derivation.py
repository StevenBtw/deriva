"""Tests for services.derivation module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from deriva.services import derivation


class TestLoadElementModule:
    """Tests for _load_element_module function."""

    def test_loads_application_component_module(self):
        """Should load ApplicationComponent module."""
        module = derivation._load_element_module("ApplicationComponent")
        assert module is not None
        assert hasattr(module, "generate")

    def test_loads_business_object_module(self):
        """Should load BusinessObject module."""
        module = derivation._load_element_module("BusinessObject")
        assert module is not None

    def test_caches_loaded_modules(self):
        """Should cache loaded modules."""
        # Clear cache first
        derivation._ELEMENT_MODULES.clear()

        module1 = derivation._load_element_module("Node")
        module2 = derivation._load_element_module("Node")

        assert module1 is module2

    def test_returns_none_for_unknown_type(self):
        """Should return None for unknown element type."""
        module = derivation._load_element_module("UnknownType")
        assert module is None


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

        with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "n1", "target": "n2"}]):
            with patch.object(derivation.enrich, "enrich_graph", return_value={"n1": {"pagerank": 0.5}}):
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
            with patch.object(derivation.enrich, "enrich_graph") as mock_enrich:
                mock_enrich.return_value = {"n1": {"pagerank": 0.5}}
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
            with patch.object(derivation.enrich, "enrich_graph", side_effect=Exception("Test error")):
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

        with patch.object(derivation, "_load_element_module") as mock_load:
            mock_module = MagicMock()
            mock_module.generate.return_value = GenerationResult(
                success=True,
                elements_created=3,
                relationships_created=5,
                created_elements=[{"id": "1"}],
                created_relationships=[{"id": "r1"}],
                errors=[],
            )
            mock_load.return_value = mock_module

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
        """Should return error when module not found."""
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
        assert "No generation module" in result["errors"][0]

    def test_handles_generation_exception(self):
        """Should handle exception during generation."""
        with patch.object(derivation, "_load_element_module") as mock_load:
            mock_module = MagicMock()
            mock_module.generate.side_effect = Exception("LLM failed")
            mock_load.return_value = mock_module

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


class TestLoadAllElementModules:
    """Tests for loading all element type modules."""

    def test_loads_business_process(self):
        """Should load BusinessProcess module."""
        module = derivation._load_element_module("BusinessProcess")
        assert module is not None
        assert hasattr(module, "generate")

    def test_loads_business_actor(self):
        """Should load BusinessActor module."""
        module = derivation._load_element_module("BusinessActor")
        assert module is not None

    def test_loads_business_event(self):
        """Should load BusinessEvent module."""
        module = derivation._load_element_module("BusinessEvent")
        assert module is not None

    def test_loads_business_function(self):
        """Should load BusinessFunction module."""
        module = derivation._load_element_module("BusinessFunction")
        assert module is not None

    def test_loads_application_service(self):
        """Should load ApplicationService module."""
        module = derivation._load_element_module("ApplicationService")
        assert module is not None

    def test_loads_application_interface(self):
        """Should load ApplicationInterface module."""
        module = derivation._load_element_module("ApplicationInterface")
        assert module is not None

    def test_loads_data_object(self):
        """Should load DataObject module."""
        module = derivation._load_element_module("DataObject")
        assert module is not None

    def test_loads_technology_service(self):
        """Should load TechnologyService module."""
        module = derivation._load_element_module("TechnologyService")
        assert module is not None

    def test_loads_device(self):
        """Should load Device module."""
        module = derivation._load_element_module("Device")
        assert module is not None

    def test_loads_system_software(self):
        """Should load SystemSoftware module."""
        module = derivation._load_element_module("SystemSoftware")
        assert module is not None


class TestRunDerivationWithConfigs:
    """Tests for run_derivation with actual mock configs."""

    def test_runs_prep_phase_with_configs(self):
        """Should execute prep step configs."""
        engine = MagicMock()
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 3
        archimate_manager = MagicMock()

        prep_cfg = MagicMock()
        prep_cfg.step_name = "pagerank"
        prep_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: ([prep_cfg] if phase == "prep" else [])
            with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "a", "target": "b"}]):
                with patch.object(derivation.enrich, "enrich_graph", return_value={"a": {"pagerank": 0.5}}):
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
            mock_get.side_effect = lambda engine, enabled_only, phase: ([gen_cfg] if phase == "generate" else [])
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
            mock_get.side_effect = lambda engine, enabled_only, phase: ([gen_cfg] if phase == "generate" else [])
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
            mock_get.side_effect = lambda engine, enabled_only, phase: ([gen_cfg] if phase == "generate" else [])
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
        assert "Error in gen_failing" in result["errors"][0]

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

        prep_cfg = MagicMock()
        prep_cfg.step_name = "pagerank"
        prep_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: ([prep_cfg] if phase == "prep" else [])
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
            mock_get.side_effect = lambda engine, enabled_only, phase: ([gen_cfg] if phase == "generate" else [])
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
            mock_get.side_effect = lambda engine, enabled_only, phase: ([gen_cfg1, gen_cfg2] if phase == "generate" else [])
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
            mock_get.side_effect = lambda engine, enabled_only, phase: ([gen_cfg] if phase == "generate" else [])
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

        prep_cfg = MagicMock()
        prep_cfg.step_name = "pagerank"
        prep_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: ([prep_cfg] if phase == "prep" else [])
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
            with patch.object(derivation.enrich, "enrich_graph", return_value={}):
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
            with patch.object(derivation.enrich, "enrich_graph", return_value={"n1": {"pagerank": 0.5}}):
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
            with patch.object(derivation.enrich, "enrich_graph") as mock_enrich:
                mock_enrich.return_value = {"n1": {"pagerank": 0.5}}
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
            with patch.object(derivation.enrich, "enrich_graph", return_value={"n1": {"community": 1}}):
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
            with patch.object(derivation.enrich, "enrich_graph", return_value={"n1": {"degree": 2}}):
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

        prep_cfg = MagicMock()
        prep_cfg.step_name = "pagerank"
        prep_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: ([prep_cfg] if phase == "prep" else [])
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

        prep_cfg1 = MagicMock()
        prep_cfg1.step_name = "pagerank"
        prep_cfg1.params = None

        prep_cfg2 = MagicMock()
        prep_cfg2.step_name = "louvain_communities"
        prep_cfg2.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: ([prep_cfg1, prep_cfg2] if phase == "prep" else [])
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
            mock_get.side_effect = lambda engine, enabled_only, phase: ([gen_cfg] if phase == "generate" else [])
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
            mock_get.side_effect = lambda engine, enabled_only, phase: ([gen_cfg] if phase == "generate" else [])
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
            mock_get.side_effect = lambda engine, enabled_only, phase: ([gen_cfg] if phase == "generate" else [])
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

        prep_cfg = MagicMock()
        prep_cfg.step_name = "pagerank"
        prep_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.side_effect = lambda engine, enabled_only, phase: ([prep_cfg] if phase == "prep" else [])
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
            mock_get.side_effect = lambda engine, enabled_only, phase: ([gen_cfg1, gen_cfg2] if phase == "generate" else [])
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
