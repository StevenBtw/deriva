"""Tests for services.derivation module."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from deriva.services import derivation


class TestNormalizeFunctions:
    """Tests for normalization helper functions."""

    def test_normalize_identifier_basic(self):
        """Should lowercase and replace separators."""
        assert derivation._normalize_identifier("MyComponent") == "mycomponent"
        assert derivation._normalize_identifier("my-component") == "my_component"
        assert derivation._normalize_identifier("my component") == "my_component"

    def test_normalize_identifier_mixed(self):
        """Should handle mixed separators."""
        assert derivation._normalize_identifier("My-Component Name") == "my_component_name"

    def test_normalize_relationship_type_valid(self):
        """Should return valid type unchanged."""
        assert derivation._normalize_relationship_type("Composition") == "Composition"
        assert derivation._normalize_relationship_type("Aggregation") == "Aggregation"

    def test_normalize_relationship_type_case_insensitive(self):
        """Should normalize case to match valid types."""
        assert derivation._normalize_relationship_type("composition") == "Composition"
        assert derivation._normalize_relationship_type("AGGREGATION") == "Aggregation"

    def test_normalize_relationship_type_unknown(self):
        """Should return unknown type as-is."""
        assert derivation._normalize_relationship_type("UnknownType") == "UnknownType"


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

    def test_parses_json_params(self):
        """Should parse JSON params from config."""
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 5
        cfg = MagicMock()
        cfg.step_name = "pagerank"
        cfg.params = '{"damping": 0.9}'

        with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "n1", "target": "n2"}]):
            with patch.object(derivation.enrich, "enrich_graph", return_value={"n1": {"pagerank": 0.5}}) as mock_enrich:
                derivation._run_prep_step(cfg, graph_manager)

        # Check that params were passed to enrich_graph
        call_args = mock_enrich.call_args
        assert call_args.kwargs.get("params", {}).get("pagerank", {}).get("damping") == 0.9

    def test_handles_invalid_json_params(self):
        """Should handle invalid JSON params gracefully."""
        graph_manager = MagicMock()
        graph_manager.batch_update_properties.return_value = 5
        cfg = MagicMock()
        cfg.step_name = "pagerank"
        cfg.params = "not valid json"

        with patch.object(derivation, "_get_graph_edges", return_value=[{"source": "n1", "target": "n2"}]):
            with patch.object(derivation.enrich, "enrich_graph", return_value={"n1": {"pagerank": 0.5}}):
                result = derivation._run_prep_step(cfg, graph_manager)

        # Should still run with empty params
        assert result["success"] is True


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

        # Should query for both phases
        phases_queried = [call.kwargs.get("phase") for call in mock_get.call_args_list]
        assert "prep" in phases_queried
        assert "generate" in phases_queried

    def test_runs_only_specified_phases(self):
        """Should only run specified phases."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.return_value = []
            derivation.run_derivation(
                engine=engine,
                graph_manager=graph_manager,
                archimate_manager=archimate_manager,
                phases=["prep"],
            )

        # Should only query prep phase
        phases_queried = [call.kwargs.get("phase") for call in mock_get.call_args_list]
        assert "prep" in phases_queried
        assert "generate" not in phases_queried

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
        assert result["stats"]["steps_completed"] == 0

    def test_returns_success_with_no_errors(self):
        """Should return success=True when no errors."""
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

        assert result["success"] is True
        assert result["errors"] == []

    def test_runs_prep_steps(self):
        """Should run configured prep steps."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        prep_cfg = MagicMock()
        prep_cfg.step_name = "pagerank"
        prep_cfg.params = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            # Order: prep phase, generate phase
            mock_get.side_effect = [[prep_cfg], []]
            with patch.object(derivation, "_run_prep_step", return_value={"success": True}):
                result = derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                )

        assert result["stats"]["steps_completed"] == 1

    def test_runs_generate_steps(self):
        """Should run configured generate steps."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        llm_query_fn = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "ApplicationComponent"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = "Generate"
        gen_cfg.example = "{}"
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            # Order: prep phase, generate phase
            mock_get.side_effect = [[], [gen_cfg]]
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.return_value = {"elements_created": 2, "created_elements": []}
                result = derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                    llm_query_fn=llm_query_fn,
                )

        assert result["stats"]["elements_created"] == 2
        assert result["stats"]["steps_completed"] == 1

    def test_handles_generate_step_error(self):
        """Should handle errors in generate step gracefully."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()

        gen_cfg = MagicMock()
        gen_cfg.step_name = "FailingStep"
        gen_cfg.element_type = "ApplicationComponent"
        gen_cfg.input_graph_query = "MATCH (n) RETURN n"
        gen_cfg.instruction = ""
        gen_cfg.example = ""
        gen_cfg.temperature = None
        gen_cfg.max_tokens = None

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            # Order: prep phase, generate phase
            mock_get.side_effect = [[], [gen_cfg]]
            with patch.object(derivation, "generate_element") as mock_gen:
                mock_gen.side_effect = Exception("LLM failed")
                result = derivation.run_derivation(
                    engine=engine,
                    graph_manager=graph_manager,
                    archimate_manager=archimate_manager,
                )

        assert result["success"] is False
        assert any("FailingStep" in e for e in result["errors"])
        assert result["stats"]["steps_skipped"] == 1

    def test_uses_run_logger(self):
        """Should log phases and steps when run_logger provided."""
        engine = MagicMock()
        graph_manager = MagicMock()
        archimate_manager = MagicMock()
        run_logger = MagicMock()

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            mock_get.return_value = []
            derivation.run_derivation(
                engine=engine,
                graph_manager=graph_manager,
                archimate_manager=archimate_manager,
                run_logger=run_logger,
            )

        run_logger.phase_start.assert_called_once()
        run_logger.phase_complete.assert_called_once()


class TestDeriveRelationships:
    """Tests for relationship derivation.

    Note: Relationship derivation now happens within each element module's
    generate() function, not in a separate phase. These tests verify the
    unified derivation approach works correctly.
    """

    def test_generate_element_returns_relationships_created(self):
        """Should return relationships_created in generate_element result."""
        from deriva.modules.derivation.base import GenerationResult

        # The GenerationResult should include relationship tracking
        result = GenerationResult(success=True)
        assert hasattr(result, "relationships_created")
        assert hasattr(result, "created_relationships")


