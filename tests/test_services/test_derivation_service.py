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
            with patch.object(derivation.config, "get_relationship_configs", return_value=[]):
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
            with patch.object(derivation.config, "get_relationship_configs", return_value=[]):
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
            with patch.object(derivation.config, "get_relationship_configs", return_value=[]):
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
    """Tests for _derive_relationships function."""

    def test_returns_zero_without_llm(self):
        """Should return zero relationships without LLM function."""
        elements = [{"identifier": "elem1"}, {"identifier": "elem2"}]
        archimate_manager = MagicMock()

        result = derivation._derive_relationships(elements, archimate_manager, None)

        assert result["relationships_created"] == 0
        assert "LLM not configured" in result["errors"]

    def test_handles_llm_error(self):
        """Should handle LLM errors gracefully."""
        elements = [{"identifier": "elem1"}, {"identifier": "elem2"}]
        archimate_manager = MagicMock()
        llm_query_fn = MagicMock(side_effect=Exception("API error"))

        result = derivation._derive_relationships(elements, archimate_manager, llm_query_fn)

        assert result["relationships_created"] == 0
        assert any("LLM error" in e for e in result["errors"])

    def test_creates_valid_relationships(self):
        """Should create relationships from valid LLM response."""
        elements = [
            {"identifier": "comp1", "name": "Component 1"},
            {"identifier": "comp2", "name": "Component 2"},
        ]
        archimate_manager = MagicMock()

        mock_response = MagicMock()
        mock_response.content = json.dumps({"relationships": [{"source": "comp1", "target": "comp2", "relationship_type": "Composition"}]})
        llm_query_fn = MagicMock(return_value=mock_response)

        result = derivation._derive_relationships(elements, archimate_manager, llm_query_fn)

        assert result["relationships_created"] == 1
        archimate_manager.add_relationship.assert_called_once()

    def test_handles_missing_source(self):
        """Should handle relationship with missing source."""
        elements = [{"identifier": "comp1"}, {"identifier": "comp2"}]
        archimate_manager = MagicMock()

        mock_response = MagicMock()
        mock_response.content = json.dumps({"relationships": [{"source": "unknown", "target": "comp2", "relationship_type": "Composition"}]})
        llm_query_fn = MagicMock(return_value=mock_response)

        result = derivation._derive_relationships(elements, archimate_manager, llm_query_fn)

        assert result["relationships_created"] == 0
        assert any("source not found" in e for e in result["errors"])

    def test_handles_missing_target(self):
        """Should handle relationship with missing target."""
        elements = [{"identifier": "comp1"}, {"identifier": "comp2"}]
        archimate_manager = MagicMock()

        mock_response = MagicMock()
        mock_response.content = json.dumps({"relationships": [{"source": "comp1", "target": "unknown", "relationship_type": "Composition"}]})
        llm_query_fn = MagicMock(return_value=mock_response)

        result = derivation._derive_relationships(elements, archimate_manager, llm_query_fn)

        assert result["relationships_created"] == 0
        assert any("target not found" in e for e in result["errors"])

    def test_fuzzy_matches_identifiers(self):
        """Should fuzzy match identifiers with normalization."""
        elements = [
            {"identifier": "My-Component"},
            {"identifier": "Other Component"},
        ]
        archimate_manager = MagicMock()

        mock_response = MagicMock()
        mock_response.content = json.dumps({"relationships": [{"source": "my_component", "target": "other_component", "relationship_type": "Composition"}]})
        llm_query_fn = MagicMock(return_value=mock_response)

        result = derivation._derive_relationships(elements, archimate_manager, llm_query_fn)

        assert result["relationships_created"] == 1

    def test_handles_add_relationship_error(self):
        """Should handle errors when adding relationship."""
        elements = [{"identifier": "comp1"}, {"identifier": "comp2"}]
        archimate_manager = MagicMock()
        archimate_manager.add_relationship.side_effect = Exception("DB error")

        mock_response = MagicMock()
        mock_response.content = json.dumps({"relationships": [{"source": "comp1", "target": "comp2", "relationship_type": "Composition"}]})
        llm_query_fn = MagicMock(return_value=mock_response)

        result = derivation._derive_relationships(elements, archimate_manager, llm_query_fn)

        assert result["relationships_created"] == 0
        assert any("Failed to persist" in e for e in result["errors"])


class TestDeriveElementRelationships:
    """Tests for _derive_element_relationships function (per-element relationship derivation)."""

    def test_returns_zero_without_llm(self):
        """Should return zero relationships without LLM function."""
        source_elements = [{"identifier": "ac:comp1", "element_type": "ApplicationComponent"}]
        target_elements = [{"identifier": "as:svc1", "element_type": "ApplicationService"}]
        archimate_manager = MagicMock()

        result = derivation._derive_element_relationships(
            source_element_type="ApplicationComponent",
            source_elements=source_elements,
            target_elements=target_elements,
            archimate_manager=archimate_manager,
            llm_query_fn=None,
            instruction="Derive relationships",
        )

        assert result["relationships_created"] == 0
        assert "LLM not configured" in result["errors"]

    def test_returns_zero_for_empty_source_elements(self):
        """Should return zero when no source elements provided."""
        archimate_manager = MagicMock()
        llm_query_fn = MagicMock()

        result = derivation._derive_element_relationships(
            source_element_type="ApplicationComponent",
            source_elements=[],
            target_elements=[],
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            instruction="Derive relationships",
        )

        assert result["relationships_created"] == 0
        assert result["errors"] == []

    def test_handles_llm_error(self):
        """Should handle LLM errors gracefully."""
        source_elements = [{"identifier": "ac:comp1", "element_type": "ApplicationComponent"}]
        target_elements = source_elements
        archimate_manager = MagicMock()
        llm_query_fn = MagicMock(side_effect=Exception("API error"))

        result = derivation._derive_element_relationships(
            source_element_type="ApplicationComponent",
            source_elements=source_elements,
            target_elements=target_elements,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            instruction="Derive relationships",
        )

        assert result["relationships_created"] == 0
        assert any("LLM error" in e for e in result["errors"])

    def test_creates_valid_relationships_with_metamodel_validation(self):
        """Should create relationships that pass metamodel validation."""
        source_elements = [
            {"identifier": "ac:comp1", "name": "Component 1", "element_type": "ApplicationComponent"},
        ]
        target_elements = source_elements + [
            {"identifier": "as:svc1", "name": "Service 1", "element_type": "ApplicationService"},
        ]
        archimate_manager = MagicMock()

        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "relationships": [{
                "source": "ac:comp1",
                "target": "as:svc1",
                "relationship_type": "Assignment",
                "confidence": 0.9
            }]
        })
        llm_query_fn = MagicMock(return_value=mock_response)

        result = derivation._derive_element_relationships(
            source_element_type="ApplicationComponent",
            source_elements=source_elements,
            target_elements=target_elements,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            instruction="Derive relationships",
        )

        assert result["relationships_created"] == 1
        archimate_manager.add_relationship.assert_called_once()

    def test_rejects_invalid_relationship_type_for_source(self):
        """Should reject relationships that violate configured relationship types."""
        source_elements = [
            {"identifier": "ac:comp1", "name": "Component 1", "element_type": "ApplicationComponent"},
        ]
        target_elements = source_elements + [
            {"identifier": "bp:proc1", "name": "Process 1", "element_type": "BusinessProcess"},
        ]
        archimate_manager = MagicMock()

        # Try to create Composition but only Serving is allowed
        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "relationships": [{
                "source": "ac:comp1",
                "target": "bp:proc1",
                "relationship_type": "Composition"
            }]
        })
        llm_query_fn = MagicMock(return_value=mock_response)

        result = derivation._derive_element_relationships(
            source_element_type="ApplicationComponent",
            source_elements=source_elements,
            target_elements=target_elements,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            instruction="Derive relationships",
            valid_relationship_types=["Serving", "Assignment"],  # Composition not allowed
        )

        # Should be rejected - Composition not in valid_relationship_types
        assert result["relationships_created"] == 0
        assert any("Invalid relationship type" in e for e in result["errors"])

    def test_rejects_source_not_in_source_elements(self):
        """Should reject relationships where source is not from source_elements list."""
        source_elements = [
            {"identifier": "ac:comp1", "name": "Component 1", "element_type": "ApplicationComponent"},
        ]
        target_elements = source_elements + [
            {"identifier": "ac:comp2", "name": "Component 2", "element_type": "ApplicationComponent"},
        ]
        archimate_manager = MagicMock()

        mock_response = MagicMock()
        mock_response.content = json.dumps({
            "relationships": [
                # Source is comp2, but source_elements only contains comp1
                {"source": "ac:comp2", "target": "ac:comp1", "relationship_type": "Composition"}
            ]
        })
        llm_query_fn = MagicMock(return_value=mock_response)

        result = derivation._derive_element_relationships(
            source_element_type="ApplicationComponent",
            source_elements=source_elements,
            target_elements=target_elements,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            instruction="Derive relationships",
        )

        assert result["relationships_created"] == 0
        assert any("source not in" in e.lower() for e in result["errors"])

    def test_passes_temperature_and_max_tokens_to_llm(self):
        """Should pass temperature and max_tokens overrides to LLM."""
        source_elements = [
            {"identifier": "ac:comp1", "element_type": "ApplicationComponent"},
        ]
        target_elements = source_elements
        archimate_manager = MagicMock()

        mock_response = MagicMock()
        mock_response.content = json.dumps({"relationships": []})
        llm_query_fn = MagicMock(return_value=mock_response)

        derivation._derive_element_relationships(
            source_element_type="ApplicationComponent",
            source_elements=source_elements,
            target_elements=target_elements,
            archimate_manager=archimate_manager,
            llm_query_fn=llm_query_fn,
            instruction="Derive relationships",
            temperature=0.5,
            max_tokens=2000,
        )

        # Verify temperature and max_tokens were passed
        call_args = llm_query_fn.call_args
        assert call_args.kwargs.get("temperature") == 0.5
        assert call_args.kwargs.get("max_tokens") == 2000


class TestPerElementRelationshipInRunDerivation:
    """Tests for per-element relationship derivation in run_derivation."""

    def test_uses_per_element_relationships_when_configs_exist(self):
        """Should use per-element relationship derivation when relationship configs exist."""
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

        rel_cfg = MagicMock()
        rel_cfg.step_name = "ApplicationComponent_relationships"
        rel_cfg.element_type = "ApplicationComponent"
        rel_cfg.instruction = "Derive relationships"
        rel_cfg.example = "{}"
        rel_cfg.temperature = 0.3
        rel_cfg.max_tokens = 1000
        rel_cfg.sequence = 1
        rel_cfg.target_element_types = None  # None means all types
        rel_cfg.valid_relationship_types = ["Serving", "Assignment"]

        with patch.object(derivation.config, "get_derivation_configs") as mock_get:
            with patch.object(derivation.config, "get_relationship_configs", return_value=[rel_cfg]):
                # Returns: prep configs, generate configs
                mock_get.side_effect = [[], [gen_cfg]]
                with patch.object(derivation, "generate_element") as mock_gen:
                    mock_gen.return_value = {
                        "elements_created": 1,
                        "created_elements": [
                            {"identifier": "ac:comp1", "element_type": "ApplicationComponent"}
                        ]
                    }
                    with patch.object(derivation, "_derive_element_relationships") as mock_derive:
                        mock_derive.return_value = {
                            "relationships_created": 2,
                            "relationship_ids": ["r1", "r2"],
                            "errors": []
                        }
                        result = derivation.run_derivation(
                            engine=engine,
                            graph_manager=graph_manager,
                            archimate_manager=archimate_manager,
                            llm_query_fn=llm_query_fn,
                        )

        # Should have called _derive_element_relationships
        mock_derive.assert_called_once()
        assert result["stats"]["relationships_created"] == 2

    def test_falls_back_to_single_pass_when_no_relationship_configs(self):
        """Should fall back to single-pass when no relationship phase configs exist."""
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
            with patch.object(derivation.config, "get_relationship_configs", return_value=[]):
                # Returns: prep configs, generate configs
                mock_get.side_effect = [[], [gen_cfg]]
                with patch.object(derivation, "generate_element") as mock_gen:
                    mock_gen.return_value = {
                        "elements_created": 2,
                        "created_elements": [
                            {"identifier": "ac:comp1", "element_type": "ApplicationComponent"},
                            {"identifier": "ac:comp2", "element_type": "ApplicationComponent"},
                        ],
                    }
                    # No relationship derivation since no relationship configs
                    result = derivation.run_derivation(
                        engine=engine,
                        graph_manager=graph_manager,
                        archimate_manager=archimate_manager,
                        llm_query_fn=llm_query_fn,
                    )

        # Should not derive relationships when no relationship configs exist
        assert result["stats"]["relationships_created"] == 0
        assert result["stats"]["elements_created"] == 2
