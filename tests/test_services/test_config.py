"""Tests for services.config module."""

from __future__ import annotations

from unittest.mock import MagicMock

from deriva.services.config import (
    DerivationConfig,
    ExtractionConfig,
    FileType,
    add_file_type,
    delete_file_type,
    disable_step,
    enable_step,
    get_derivation_config,
    get_derivation_configs,
    get_extraction_config,
    get_extraction_configs,
    get_file_type,
    get_file_types,
    get_setting,
    set_setting,
    update_derivation_config,
    update_extraction_config,
    update_file_type,
)


class TestExtractionConfig:
    """Tests for ExtractionConfig class."""

    def test_basic_creation(self):
        """Should create ExtractionConfig with all fields."""
        config = ExtractionConfig(
            node_type="BusinessConcept",
            sequence=1,
            enabled=True,
            input_sources='{"files": []}',
            instruction="Extract business concepts",
            example='{"concepts": []}',
            extraction_method="llm",
        )

        assert config.node_type == "BusinessConcept"
        assert config.sequence == 1
        assert config.enabled is True
        assert config.input_sources == '{"files": []}'
        assert config.instruction == "Extract business concepts"
        assert config.extraction_method == "llm"

    def test_default_extraction_method(self):
        """Should default to llm extraction method."""
        config = ExtractionConfig(
            node_type="TypeDefinition",
            sequence=2,
            enabled=True,
            input_sources=None,
            instruction=None,
            example=None,
        )

        assert config.extraction_method == "llm"


class TestDerivationConfig:
    """Tests for DerivationConfig class."""

    def test_basic_creation(self):
        """Should create DerivationConfig with all fields."""
        config = DerivationConfig(
            step_name="ApplicationComponent",
            phase="generate",
            sequence=1,
            enabled=True,
            llm=True,
            input_graph_query="MATCH (n) RETURN n",
            input_model_query=None,
            instruction="Generate ArchiMate elements",
            example='{"elements": []}',
            params=None,
        )

        assert config.step_name == "ApplicationComponent"
        assert config.phase == "generate"
        assert config.sequence == 1
        assert config.enabled is True
        assert config.llm is True
        assert config.input_graph_query == "MATCH (n) RETURN n"

    def test_element_type_backward_compatibility(self):
        """Should map element_type to step_name for backward compatibility."""
        config = DerivationConfig(
            step_name="ApplicationComponent",
            phase="generate",
            sequence=1,
            enabled=True,
            llm=True,
            input_graph_query=None,
            input_model_query=None,
            instruction=None,
            example=None,
            params=None,
        )

        assert config.element_type == "ApplicationComponent"


class TestFileType:
    """Tests for FileType class."""

    def test_basic_creation(self):
        """Should create FileType with required fields."""
        file_type = FileType(
            extension=".py",
            file_type="source",
            subtype="python",
        )

        assert file_type.extension == ".py"
        assert file_type.file_type == "source"
        assert file_type.subtype == "python"
        assert file_type.chunk_delimiter is None
        assert file_type.chunk_max_tokens is None
        assert file_type.chunk_overlap == 0

    def test_with_chunking_config(self):
        """Should create FileType with chunking configuration."""
        file_type = FileType(
            extension=".md",
            file_type="documentation",
            subtype="markdown",
            chunk_delimiter="\n\n",
            chunk_max_tokens=1000,
            chunk_overlap=100,
        )

        assert file_type.chunk_delimiter == "\n\n"
        assert file_type.chunk_max_tokens == 1000
        assert file_type.chunk_overlap == 100


class TestGetExtractionConfigs:
    """Tests for get_extraction_configs function."""

    def test_returns_all_configs(self):
        """Should return all active extraction configs."""
        engine = MagicMock()
        # Columns: node_type, sequence, enabled, input_sources, instruction, example,
        #          extraction_method, temperature, max_tokens, batch_size
        engine.execute.return_value.fetchall.return_value = [
            ("BusinessConcept", 1, True, '{"files": []}', "instruction1", "example1", "llm", None, None, 1),
            ("TypeDefinition", 2, True, '{"files": []}', "instruction2", "example2", "ast", 0.5, 2000, 5),
        ]

        configs = get_extraction_configs(engine)

        assert len(configs) == 2
        assert configs[0].node_type == "BusinessConcept"
        assert configs[0].temperature is None
        assert configs[0].max_tokens is None
        assert configs[0].batch_size == 1
        assert configs[1].node_type == "TypeDefinition"
        assert configs[1].extraction_method == "ast"
        assert configs[1].temperature == 0.5
        assert configs[1].max_tokens == 2000
        assert configs[1].batch_size == 5

    def test_filters_enabled_only(self):
        """Should filter to enabled configs when requested."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = [
            ("BusinessConcept", 1, True, None, None, None, "llm", None, None, 1),
        ]

        configs = get_extraction_configs(engine, enabled_only=True)

        assert len(configs) == 1
        # Verify query includes enabled filter
        call_args = engine.execute.call_args[0][0]
        assert "enabled = TRUE" in call_args

    def test_handles_empty_result(self):
        """Should handle empty result."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        configs = get_extraction_configs(engine)

        assert configs == []

    def test_defaults_extraction_method_to_llm(self):
        """Should default extraction_method to llm when None."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = [
            ("BusinessConcept", 1, True, None, None, None, None, None, None, None),
        ]

        configs = get_extraction_configs(engine)

        assert configs[0].extraction_method == "llm"
        assert configs[0].batch_size == 1  # Default when None


class TestGetExtractionConfig:
    """Tests for get_extraction_config function."""

    def test_returns_config_when_found(self):
        """Should return config when found."""
        engine = MagicMock()
        # Columns: node_type, sequence, enabled, input_sources, instruction, example,
        #          extraction_method, temperature, max_tokens, batch_size
        engine.execute.return_value.fetchone.return_value = ("BusinessConcept", 1, True, '{"files": []}', "instruction", "example", "llm", 0.7, 4096, 3)

        config = get_extraction_config(engine, "BusinessConcept")

        assert config is not None
        assert config.node_type == "BusinessConcept"
        assert config.enabled is True
        assert config.temperature == 0.7
        assert config.max_tokens == 4096
        assert config.batch_size == 3

    def test_returns_none_when_not_found(self):
        """Should return None when config not found."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = None

        config = get_extraction_config(engine, "UnknownType")

        assert config is None


class TestUpdateExtractionConfig:
    """Tests for update_extraction_config function."""

    def test_updates_enabled_field(self):
        """Should update enabled field."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_extraction_config(engine, "BusinessConcept", enabled=False)

        assert result is True
        call_args = engine.execute.call_args[0][0]
        assert "enabled = ?" in call_args

    def test_updates_multiple_fields(self):
        """Should update multiple fields at once."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_extraction_config(
            engine,
            "BusinessConcept",
            enabled=True,
            sequence=5,
            instruction="New instruction",
        )

        assert result is True
        call_args = engine.execute.call_args[0][0]
        assert "enabled = ?" in call_args
        assert "sequence = ?" in call_args
        assert "instruction = ?" in call_args

    def test_returns_false_when_no_updates(self):
        """Should return False when no fields to update."""
        engine = MagicMock()

        result = update_extraction_config(engine, "BusinessConcept")

        assert result is False


class TestGetDerivationConfigs:
    """Tests for get_derivation_configs function."""

    def test_returns_all_configs(self):
        """Should return all active derivation configs."""
        engine = MagicMock()
        # Columns: step_name, phase, sequence, enabled, llm, input_graph_query, input_model_query,
        #          instruction, example, params, temperature, max_tokens, max_candidates, batch_size
        engine.execute.return_value.fetchall.return_value = [
            ("PageRank", "prep", 1, True, False, "MATCH (n) RETURN n", None, None, None, '{"damping": 0.85}', None, None, None, None),
            ("ApplicationComponent", "generate", 1, True, True, None, None, "instruction", "example", None, 0.5, 2000, 30, 10),
        ]

        configs = get_derivation_configs(engine)

        assert len(configs) == 2
        assert configs[0].step_name == "PageRank"
        assert configs[0].phase == "prep"
        assert configs[0].llm is False
        assert configs[0].temperature is None
        assert configs[0].max_tokens is None
        assert configs[0].max_candidates is None
        assert configs[0].batch_size is None
        assert configs[1].step_name == "ApplicationComponent"
        assert configs[1].llm is True
        assert configs[1].temperature == 0.5
        assert configs[1].max_tokens == 2000
        assert configs[1].max_candidates == 30
        assert configs[1].batch_size == 10

    def test_filters_by_phase(self):
        """Should filter by phase when specified."""
        engine = MagicMock()
        # Columns: step_name, phase, sequence, enabled, llm, input_graph_query, input_model_query,
        #          instruction, example, params, temperature, max_tokens, max_candidates, batch_size
        engine.execute.return_value.fetchall.return_value = [
            ("ApplicationComponent", "generate", 1, True, True, None, None, None, None, None, None, None, 30, 10),
        ]

        configs = get_derivation_configs(engine, phase="generate")

        assert len(configs) == 1
        # Verify query includes phase filter
        call_args = engine.execute.call_args[0][0]
        assert "phase = ?" in call_args

    def test_filters_by_llm_only(self):
        """Should filter by LLM type when specified."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        get_derivation_configs(engine, llm_only=True)

        call_args = engine.execute.call_args[0][0]
        assert "llm = ?" in call_args

    def test_filters_enabled_only(self):
        """Should filter to enabled configs."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        get_derivation_configs(engine, enabled_only=True)

        call_args = engine.execute.call_args[0][0]
        assert "enabled = TRUE" in call_args


class TestGetDerivationConfig:
    """Tests for get_derivation_config function."""

    def test_returns_config_when_found(self):
        """Should return config when found."""
        engine = MagicMock()
        # Columns: step_name, phase, sequence, enabled, llm, input_graph_query, input_model_query,
        #          instruction, example, params, temperature, max_tokens, max_candidates, batch_size
        engine.execute.return_value.fetchone.return_value = (
            "ApplicationComponent",
            "generate",
            1,
            True,
            True,
            "MATCH (n)",
            None,
            "instruction",
            "example",
            None,
            0.8,
            3000,
            30,
            10,
        )

        config = get_derivation_config(engine, "ApplicationComponent")

        assert config is not None
        assert config.step_name == "ApplicationComponent"
        assert config.phase == "generate"
        assert config.temperature == 0.8
        assert config.max_tokens == 3000
        assert config.max_candidates == 30
        assert config.batch_size == 10

    def test_returns_none_when_not_found(self):
        """Should return None when config not found."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = None

        config = get_derivation_config(engine, "UnknownStep")

        assert config is None


class TestUpdateDerivationConfig:
    """Tests for update_derivation_config function."""

    def test_updates_enabled_field(self):
        """Should update enabled field."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_derivation_config(engine, "ApplicationComponent", enabled=False)

        assert result is True

    def test_updates_multiple_fields(self):
        """Should update multiple fields."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_derivation_config(
            engine,
            "ApplicationComponent",
            enabled=True,
            sequence=10,
            instruction="New instruction",
        )

        assert result is True


class TestGetFileTypes:
    """Tests for get_file_types function."""

    def test_returns_all_file_types(self):
        """Should return all file types."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = [
            (".py", "source", "python", None, None, 0),
            (".md", "documentation", "markdown", "\n\n", 1000, 100),
        ]

        file_types = get_file_types(engine)

        assert len(file_types) == 2
        assert file_types[0].extension == ".py"
        assert file_types[0].file_type == "source"
        assert file_types[1].extension == ".md"
        assert file_types[1].chunk_max_tokens == 1000

    def test_handles_empty_result(self):
        """Should handle empty result."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        file_types = get_file_types(engine)

        assert file_types == []


class TestGetFileType:
    """Tests for get_file_type function."""

    def test_returns_file_type_when_found(self):
        """Should return file type when found."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (".py", "source", "python", None, None, 0)

        file_type = get_file_type(engine, ".py")

        assert file_type is not None
        assert file_type.extension == ".py"
        assert file_type.file_type == "source"
        assert file_type.subtype == "python"

    def test_returns_none_when_not_found(self):
        """Should return None when file type not found."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = None

        file_type = get_file_type(engine, ".xyz")

        assert file_type is None

    def test_handles_chunking_config(self):
        """Should include chunking configuration."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (".md", "documentation", "markdown", "\n\n", 1000, 100)

        file_type = get_file_type(engine, ".md")

        assert file_type is not None
        assert file_type.chunk_delimiter == "\n\n"
        assert file_type.chunk_max_tokens == 1000
        assert file_type.chunk_overlap == 100


class TestAddFileType:
    """Tests for add_file_type function."""

    def test_adds_new_file_type(self):
        """Should add new file type when not exists."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = None  # Not exists

        result = add_file_type(engine, ".rs", "source", "rust")

        assert result is True
        # Verify INSERT was called
        insert_call = engine.execute.call_args_list[-1]
        assert "INSERT" in insert_call[0][0]

    def test_returns_false_when_exists(self):
        """Should return False when file type already exists."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (".py", "source", "python", None, None, 0)

        result = add_file_type(engine, ".py", "source", "python")

        assert result is False


class TestUpdateFileType:
    """Tests for update_file_type function."""

    def test_updates_existing_file_type(self):
        """Should update existing file type."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_file_type(engine, ".py", "source", "python3")

        assert result is True

    def test_returns_true_without_rowcount(self):
        """Should return True when rowcount not available."""
        engine = MagicMock()
        del engine.execute.return_value.rowcount

        result = update_file_type(engine, ".py", "source", "python")

        assert result is True


class TestDeleteFileType:
    """Tests for delete_file_type function."""

    def test_deletes_file_type(self):
        """Should delete file type."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = delete_file_type(engine, ".py")

        assert result is True
        call_args = engine.execute.call_args[0][0]
        assert "DELETE" in call_args

    def test_returns_false_when_not_found(self):
        """Should return False when file type not found."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 0

        result = delete_file_type(engine, ".xyz")

        assert result is False


class TestGetSetting:
    """Tests for get_setting function."""

    def test_returns_setting_when_found(self):
        """Should return setting value when found."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = ("my_value",)

        value = get_setting(engine, "my_key")

        assert value == "my_value"

    def test_returns_default_when_not_found(self):
        """Should return default when setting not found."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = None

        value = get_setting(engine, "missing_key", default="default_value")

        assert value == "default_value"

    def test_returns_none_when_not_found_no_default(self):
        """Should return None when not found and no default."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = None

        value = get_setting(engine, "missing_key")

        assert value is None


class TestSetSetting:
    """Tests for set_setting function."""

    def test_updates_existing_setting(self):
        """Should update existing setting."""
        engine = MagicMock()
        # First call returns existing value, subsequent calls for update
        engine.execute.return_value.fetchone.return_value = ("old_value",)

        set_setting(engine, "my_key", "new_value")

        # Should have called UPDATE
        calls = engine.execute.call_args_list
        update_call = [c for c in calls if "UPDATE" in str(c)]
        assert len(update_call) > 0

    def test_inserts_new_setting(self):
        """Should insert new setting when not exists."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = None

        set_setting(engine, "new_key", "new_value")

        # Should have called INSERT
        calls = engine.execute.call_args_list
        insert_call = [c for c in calls if "INSERT" in str(c)]
        assert len(insert_call) > 0


class TestEnableStep:
    """Tests for enable_step function."""

    def test_enables_extraction_step(self):
        """Should enable extraction step."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = enable_step(engine, "extraction", "BusinessConcept")

        assert result is True

    def test_enables_derivation_step(self):
        """Should enable derivation step."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = enable_step(engine, "derivation", "ApplicationComponent")

        assert result is True

    def test_returns_false_for_unknown_step_type(self):
        """Should return False for unknown step type."""
        engine = MagicMock()

        result = enable_step(engine, "unknown", "SomeStep")

        assert result is False


class TestDisableStep:
    """Tests for disable_step function."""

    def test_disables_extraction_step(self):
        """Should disable extraction step."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = disable_step(engine, "extraction", "BusinessConcept")

        assert result is True

    def test_disables_derivation_step(self):
        """Should disable derivation step."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = disable_step(engine, "derivation", "ApplicationComponent")

        assert result is True

    def test_returns_false_for_unknown_step_type(self):
        """Should return False for unknown step type."""
        engine = MagicMock()

        result = disable_step(engine, "unknown", "SomeStep")

        assert result is False


class TestUpdateExtractionConfigExtended:
    """Additional tests for update_extraction_config edge cases."""

    def test_updates_example_field(self):
        """Should update example field."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_extraction_config(
            engine,
            "BusinessConcept",
            example='{"concepts": [{"name": "User"}]}',
        )

        assert result is True
        call_args = engine.execute.call_args[0][0]
        assert "example = ?" in call_args

    def test_updates_input_sources_field(self):
        """Should update input_sources field."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_extraction_config(
            engine,
            "BusinessConcept",
            input_sources='{"files": [{"type": "source"}]}',
        )

        assert result is True
        call_args = engine.execute.call_args[0][0]
        assert "input_sources = ?" in call_args

    def test_returns_true_without_rowcount(self):
        """Should return True when rowcount not available."""
        engine = MagicMock()
        del engine.execute.return_value.rowcount

        result = update_extraction_config(engine, "BusinessConcept", enabled=True)

        assert result is True


class TestUpdateDerivationConfigExtended:
    """Additional tests for update_derivation_config edge cases."""

    def test_updates_input_graph_query(self):
        """Should update input_graph_query field."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_derivation_config(
            engine,
            "ApplicationComponent",
            input_graph_query="MATCH (n:TypeDefinition) RETURN n",
        )

        assert result is True
        call_args = engine.execute.call_args[0][0]
        assert "input_graph_query = ?" in call_args

    def test_updates_params_field(self):
        """Should update params field."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_derivation_config(
            engine,
            "PageRank",
            params='{"damping": 0.9, "max_iterations": 50}',
        )

        assert result is True
        call_args = engine.execute.call_args[0][0]
        assert "params = ?" in call_args

    def test_updates_example_field(self):
        """Should update example field."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_derivation_config(
            engine,
            "ApplicationComponent",
            example='{"elements": []}',
        )

        assert result is True

    def test_returns_false_when_no_updates(self):
        """Should return False when no fields to update."""
        engine = MagicMock()

        result = update_derivation_config(engine, "ApplicationComponent")

        assert result is False


class TestListSteps:
    """Tests for list_steps function."""

    def test_returns_extraction_step_info(self):
        """Should return extraction step info with correct fields."""
        from unittest.mock import patch

        from deriva.services.config import list_steps

        engine = MagicMock()
        mock_config = ExtractionConfig(
            node_type="BusinessConcept",
            sequence=1,
            enabled=True,
            input_sources=None,
            instruction="Test instruction",
            example=None,
        )

        with patch(
            "deriva.services.config.get_extraction_configs",
            return_value=[mock_config],
        ):
            result = list_steps(engine, "extraction")

            assert len(result) == 1
            assert result[0]["name"] == "BusinessConcept"
            assert result[0]["sequence"] == 1
            assert result[0]["enabled"] is True
            assert result[0]["has_instruction"] is True

    def test_returns_derivation_step_info(self):
        """Should return derivation step info with correct fields."""
        from unittest.mock import patch

        from deriva.services.config import list_steps

        engine = MagicMock()
        mock_config = DerivationConfig(
            step_name="ApplicationComponent",
            phase="generate",
            sequence=1,
            enabled=True,
            llm=True,
            input_graph_query="MATCH (n) RETURN n",
            input_model_query=None,
            instruction=None,
            example=None,
            params=None,
        )

        with patch(
            "deriva.services.config.get_derivation_configs",
            return_value=[mock_config],
        ):
            result = list_steps(engine, "derivation")

            assert len(result) == 1
            assert result[0]["name"] == "ApplicationComponent"
            assert result[0]["phase"] == "generate"
            assert result[0]["sequence"] == 1
            assert result[0]["enabled"] is True
            assert result[0]["llm"] is True
            assert result[0]["has_query"] is True

    def test_returns_empty_for_invalid_step_type(self):
        """Should return empty list for invalid step type."""
        from deriva.services.config import list_steps

        engine = MagicMock()
        result = list_steps(engine, "invalid_type")

        assert result == []

    def test_respects_enabled_only_parameter(self):
        """Should pass enabled_only parameter to underlying function."""
        from unittest.mock import patch

        from deriva.services.config import list_steps

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_extraction_configs",
            return_value=[],
        ) as mock_fn:
            list_steps(engine, "extraction", enabled_only=True)
            mock_fn.assert_called_once()
            assert mock_fn.call_args[1].get("enabled_only") is True

    def test_passes_phase_for_derivation(self):
        """Should pass phase parameter for derivation steps."""
        from unittest.mock import patch

        from deriva.services.config import list_steps

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_derivation_configs",
            return_value=[],
        ) as mock_fn:
            list_steps(engine, "derivation", phase="prep")
            mock_fn.assert_called_once()
            assert mock_fn.call_args[1].get("phase") == "prep"


class TestGetSettings:
    """Tests for get_settings function."""

    def test_returns_cached_settings(self):
        """Should return cached DerivaSettings instance."""
        from deriva.services.config import get_settings

        # Clear cache for testing
        get_settings.cache_clear()

        settings = get_settings()
        assert settings is not None
        # Should return same instance on subsequent calls
        settings2 = get_settings()
        assert settings is settings2


class TestUpdateExtractionConfigTemperatureAndTokens:
    """Tests for update_extraction_config with temperature and max_tokens."""

    def test_updates_temperature_field(self):
        """Should update temperature field."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_extraction_config(engine, "BusinessConcept", temperature=0.7)

        assert result is True
        call_args = engine.execute.call_args[0][0]
        assert "temperature = ?" in call_args

    def test_updates_max_tokens_field(self):
        """Should update max_tokens field."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_extraction_config(engine, "BusinessConcept", max_tokens=4096)

        assert result is True
        call_args = engine.execute.call_args[0][0]
        assert "max_tokens = ?" in call_args


class TestUpdateDerivationConfigTemperatureAndTokens:
    """Tests for update_derivation_config with temperature and max_tokens."""

    def test_updates_input_model_query(self):
        """Should update input_model_query field."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_derivation_config(
            engine,
            "ApplicationComponent",
            input_model_query="MATCH (n:Model) RETURN n",
        )

        assert result is True
        call_args = engine.execute.call_args[0][0]
        assert "input_model_query = ?" in call_args

    def test_updates_temperature_field(self):
        """Should update temperature field."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_derivation_config(
            engine,
            "ApplicationComponent",
            temperature=0.5,
        )

        assert result is True
        call_args = engine.execute.call_args[0][0]
        assert "temperature = ?" in call_args

    def test_updates_max_tokens_field(self):
        """Should update max_tokens field."""
        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_derivation_config(
            engine,
            "ApplicationComponent",
            max_tokens=8192,
        )

        assert result is True
        call_args = engine.execute.call_args[0][0]
        assert "max_tokens = ?" in call_args


class TestCreateDerivationConfigVersion:
    """Tests for create_derivation_config_version function."""

    def test_creates_new_version(self):
        """Should create new version with incremented version number."""
        from deriva.services.config import create_derivation_config_version

        engine = MagicMock()
        # Current config: (id, version, phase, sequence, enabled, llm, graph_query, model_query, instruction, example, params, temperature, max_tokens)
        engine.execute.return_value.fetchone.side_effect = [
            (1, 1, "generate", 1, True, True, "MATCH (n)", None, "instruction", "example", None, 0.7, 4096),  # Current config
            (2,),  # Next ID
        ]

        result = create_derivation_config_version(
            engine,
            "ApplicationComponent",
            instruction="New instruction",
        )

        assert result["success"] is True
        assert result["step_name"] == "ApplicationComponent"
        assert result["old_version"] == 1
        assert result["new_version"] == 2

    def test_returns_error_when_not_found(self):
        """Should return error when config not found."""
        from deriva.services.config import create_derivation_config_version

        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = None

        result = create_derivation_config_version(engine, "UnknownStep")

        assert result["success"] is False
        assert "Config not found" in result["error"]

    def test_preserves_existing_values(self):
        """Should preserve existing values when not specified."""
        from deriva.services.config import create_derivation_config_version

        engine = MagicMock()
        engine.execute.return_value.fetchone.side_effect = [
            (1, 1, "generate", 5, True, True, "OLD_QUERY", "OLD_MODEL", "old_instruction", "old_example", '{"key": "value"}', 0.5, 2000),
            (2,),
        ]

        result = create_derivation_config_version(
            engine,
            "ApplicationComponent",
            enabled=False,  # Only change enabled
        )

        assert result["success"] is True
        # Verify INSERT preserves old values
        insert_call = [c for c in engine.execute.call_args_list if "INSERT INTO derivation_config" in str(c)]
        assert len(insert_call) > 0


class TestCreateExtractionConfigVersion:
    """Tests for create_extraction_config_version function."""

    def test_creates_new_version(self):
        """Should create new version with incremented version number."""
        from deriva.services.config import create_extraction_config_version

        engine = MagicMock()
        # Current config: (id, version, sequence, enabled, input_sources, instruction, example, temperature, max_tokens, batch_size, extraction_method)
        engine.execute.return_value.fetchone.side_effect = [
            (1, 1, 1, True, '{"files": []}', "instruction", "example", 0.7, 4096, 1, "llm"),
            (2,),  # Next ID
        ]

        result = create_extraction_config_version(
            engine,
            "BusinessConcept",
            instruction="New instruction",
        )

        assert result["success"] is True
        assert result["node_type"] == "BusinessConcept"
        assert result["old_version"] == 1
        assert result["new_version"] == 2

    def test_returns_error_when_not_found(self):
        """Should return error when config not found."""
        from deriva.services.config import create_extraction_config_version

        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = None

        result = create_extraction_config_version(engine, "UnknownType")

        assert result["success"] is False
        assert "Config not found" in result["error"]


class TestGetActiveConfigVersions:
    """Tests for get_active_config_versions function."""

    def test_returns_all_active_versions(self):
        """Should return all active config versions."""
        from deriva.services.config import get_active_config_versions

        engine = MagicMock()
        # Mock two separate fetchall calls
        engine.execute.return_value.fetchall.side_effect = [
            [("BusinessConcept", 3), ("TypeDefinition", 1)],  # Extraction
            [("ApplicationComponent", 2), ("PageRank", 1)],  # Derivation
        ]

        result = get_active_config_versions(engine)

        assert result["extraction"]["BusinessConcept"] == 3
        assert result["extraction"]["TypeDefinition"] == 1
        assert result["derivation"]["ApplicationComponent"] == 2
        assert result["derivation"]["PageRank"] == 1


class TestLogConsistencyRun:
    """Tests for log_consistency_run function."""

    def test_logs_run_and_returns_id(self):
        """Should log run and return new ID."""
        from deriva.services.config import log_consistency_run

        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (1,)  # Next ID

        result = log_consistency_run(
            engine,
            repo_name="test_repo",
            num_runs=5,
            results={
                "name_consistency": 0.95,
                "identifier_consistency": 0.92,
                "count_variance": 0.05,
                "stable_count": 10,
                "total_unique": 12,
            },
            config_versions={"extraction": {"BusinessConcept": 1}},
        )

        assert result == 1
        # Verify table creation
        create_calls = [c for c in engine.execute.call_args_list if "CREATE TABLE" in str(c)]
        assert len(create_calls) > 0


class TestGetConsistencyHistory:
    """Tests for get_consistency_history function."""

    def test_returns_history_records(self):
        """Should return history records."""
        from deriva.services.config import get_consistency_history

        engine = MagicMock()
        # First call checks table existence, second gets data
        engine.execute.return_value.fetchall.side_effect = [
            [("consistency_runs",)],  # Table exists
            [
                (1, "test_repo", 5, 0.95, 0.92, 0.05, 10, 12, '{"extraction": {}}', "2024-01-01 00:00:00"),
            ],
        ]

        result = get_consistency_history(engine, repo_name="test_repo")

        assert len(result) == 1
        assert result[0]["repo_name"] == "test_repo"
        assert result[0]["name_consistency"] == 0.95

    def test_returns_empty_when_table_not_exists(self):
        """Should return empty list when table doesn't exist."""
        from deriva.services.config import get_consistency_history

        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        result = get_consistency_history(engine)

        assert result == []


class TestGetDerivationPatterns:
    """Tests for get_derivation_patterns function."""

    def test_returns_patterns(self):
        """Should return patterns grouped by type."""
        from deriva.services.config import get_derivation_patterns

        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = [
            ("include", '["get", "post", "put"]'),
            ("exclude", '["_", "private"]'),
        ]

        result = get_derivation_patterns(engine, "ApplicationService")

        assert "get" in result["include"]
        assert "post" in result["include"]
        assert "_" in result["exclude"]

    def test_raises_when_not_found(self):
        """Should raise ValueError when no patterns found."""
        import pytest

        from deriva.services.config import get_derivation_patterns

        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = []

        with pytest.raises(ValueError, match="No patterns found"):
            get_derivation_patterns(engine, "UnknownStep")


class TestGetIncludePatterns:
    """Tests for get_include_patterns function."""

    def test_returns_include_patterns_only(self):
        """Should return only include patterns."""
        from unittest.mock import patch

        from deriva.services.config import get_include_patterns

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_derivation_patterns",
            return_value={"include": {"get", "post"}, "exclude": set()},
        ):
            result = get_include_patterns(engine, "ApplicationService")

        assert "get" in result
        assert "post" in result


class TestGetExcludePatterns:
    """Tests for get_exclude_patterns function."""

    def test_returns_exclude_patterns_only(self):
        """Should return only exclude patterns."""
        from unittest.mock import patch

        from deriva.services.config import get_exclude_patterns

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_derivation_patterns",
            return_value={"include": set(), "exclude": {"_", "private"}},
        ):
            result = get_exclude_patterns(engine, "ApplicationService")

        assert "_" in result
        assert "private" in result


class TestUpdateDerivationPatterns:
    """Tests for update_derivation_patterns function."""

    def test_updates_existing_patterns(self):
        """Should update existing patterns."""
        from deriva.services.config import update_derivation_patterns

        engine = MagicMock()
        engine.execute.return_value.rowcount = 1

        result = update_derivation_patterns(
            engine,
            "ApplicationService",
            "include",
            "http_methods",
            ["get", "post", "put", "delete"],
        )

        assert result is True

    def test_inserts_when_not_exists(self):
        """Should insert new patterns when not exists."""
        from deriva.services.config import update_derivation_patterns

        engine = MagicMock()
        engine.execute.return_value.rowcount = 0
        engine.execute.return_value.fetchone.return_value = (1,)

        result = update_derivation_patterns(
            engine,
            "NewStep",
            "include",
            "new_category",
            ["pattern1", "pattern2"],
        )

        assert result is True


class TestThresholdHelpers:
    """Tests for threshold helper functions."""

    def test_get_confidence_threshold_from_settings(self):
        """Should get threshold from system_settings."""
        from unittest.mock import patch

        from deriva.services.config import get_confidence_threshold

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_setting",
            return_value="0.75",
        ):
            result = get_confidence_threshold(engine, "min_relationship")

        assert result == 0.75

    def test_get_confidence_threshold_uses_default(self):
        """Should use default when setting not found."""
        from unittest.mock import patch

        from deriva.services.config import get_confidence_threshold

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_setting",
            return_value=None,
        ):
            result = get_confidence_threshold(engine, "min_relationship")

        assert result == 0.6  # Default value

    def test_get_confidence_threshold_handles_invalid_value(self):
        """Should handle invalid value and use default."""
        from unittest.mock import patch

        from deriva.services.config import get_confidence_threshold

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_setting",
            return_value="not_a_number",
        ):
            result = get_confidence_threshold(engine, "min_relationship")

        assert result == 0.6  # Default value

    def test_get_derivation_limit_from_settings(self):
        """Should get limit from system_settings."""
        from unittest.mock import patch

        from deriva.services.config import get_derivation_limit

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_setting",
            return_value="50",
        ):
            result = get_derivation_limit(engine, "default_batch_size")

        assert result == 50

    def test_get_derivation_limit_uses_default(self):
        """Should use default when setting not found."""
        from unittest.mock import patch

        from deriva.services.config import get_derivation_limit

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_setting",
            return_value=None,
        ):
            result = get_derivation_limit(engine, "default_batch_size")

        assert result == 10  # Default value


class TestSpecificThresholdHelpers:
    """Tests for specific threshold helper functions."""

    def test_get_min_relationship_confidence(self):
        """Should get min relationship confidence."""
        from unittest.mock import patch

        from deriva.services.config import get_min_relationship_confidence

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_confidence_threshold",
            return_value=0.65,
        ):
            result = get_min_relationship_confidence(engine)

        assert result == 0.65

    def test_get_community_rel_confidence(self):
        """Should get community relationship confidence."""
        from unittest.mock import patch

        from deriva.services.config import get_community_rel_confidence

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_confidence_threshold",
            return_value=0.95,
        ):
            result = get_community_rel_confidence(engine)

        assert result == 0.95

    def test_get_name_match_confidence(self):
        """Should get name match confidence."""
        from unittest.mock import patch

        from deriva.services.config import get_name_match_confidence

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_confidence_threshold",
            return_value=0.95,
        ):
            result = get_name_match_confidence(engine)

        assert result == 0.95

    def test_get_file_match_confidence(self):
        """Should get file match confidence."""
        from unittest.mock import patch

        from deriva.services.config import get_file_match_confidence

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_confidence_threshold",
            return_value=0.85,
        ):
            result = get_file_match_confidence(engine)

        assert result == 0.85

    def test_get_fuzzy_match_threshold(self):
        """Should get fuzzy match threshold."""
        from unittest.mock import patch

        from deriva.services.config import get_fuzzy_match_threshold

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_confidence_threshold",
            return_value=0.85,
        ):
            result = get_fuzzy_match_threshold(engine)

        assert result == 0.85

    def test_get_semantic_confidence(self):
        """Should get semantic confidence."""
        from unittest.mock import patch

        from deriva.services.config import get_semantic_confidence

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_confidence_threshold",
            return_value=0.95,
        ):
            result = get_semantic_confidence(engine)

        assert result == 0.95

    def test_get_pagerank_min(self):
        """Should get pagerank minimum threshold."""
        from unittest.mock import patch

        from deriva.services.config import get_pagerank_min

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_confidence_threshold",
            return_value=0.001,
        ):
            result = get_pagerank_min(engine)

        assert result == 0.001


class TestSpecificLimitHelpers:
    """Tests for specific limit helper functions."""

    def test_get_max_batch_size(self):
        """Should get max batch size."""
        from unittest.mock import patch

        from deriva.services.config import get_max_batch_size

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_derivation_limit",
            return_value=10,
        ):
            result = get_max_batch_size(engine)

        assert result == 10

    def test_get_max_candidates(self):
        """Should get max candidates."""
        from unittest.mock import patch

        from deriva.services.config import get_max_candidates

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_derivation_limit",
            return_value=30,
        ):
            result = get_max_candidates(engine)

        assert result == 30

    def test_get_max_relationships_per_derivation(self):
        """Should get max relationships per derivation."""
        from unittest.mock import patch

        from deriva.services.config import get_max_relationships_per_derivation

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_derivation_limit",
            return_value=500,
        ):
            result = get_max_relationships_per_derivation(engine)

        assert result == 500


class TestAlgorithmSettingsHelpers:
    """Tests for algorithm settings helper functions."""

    def test_get_algorithm_setting_from_settings(self):
        """Should get algorithm setting from system_settings."""
        from unittest.mock import patch

        from deriva.services.config import get_algorithm_setting

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_setting",
            return_value="0.9",
        ):
            result = get_algorithm_setting(engine, "algorithm_pagerank_damping")

        assert result == "0.9"

    def test_get_algorithm_setting_uses_default(self):
        """Should use default when setting not found."""
        from unittest.mock import patch

        from deriva.services.config import get_algorithm_setting

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_setting",
            return_value=None,
        ):
            result = get_algorithm_setting(engine, "algorithm_pagerank_damping")

        assert result == "0.85"  # Default value

    def test_get_algorithm_setting_float(self):
        """Should get algorithm setting as float."""
        from unittest.mock import patch

        from deriva.services.config import get_algorithm_setting_float

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_algorithm_setting",
            return_value="0.85",
        ):
            result = get_algorithm_setting_float(engine, "algorithm_pagerank_damping")

        assert result == 0.85

    def test_get_algorithm_setting_float_handles_invalid(self):
        """Should handle invalid float value."""
        from unittest.mock import patch

        from deriva.services.config import get_algorithm_setting_float

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_algorithm_setting",
            return_value="not_a_number",
        ):
            result = get_algorithm_setting_float(engine, "key", default=0.5)

        assert result == 0.5

    def test_get_algorithm_setting_int(self):
        """Should get algorithm setting as int."""
        from unittest.mock import patch

        from deriva.services.config import get_algorithm_setting_int

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_algorithm_setting",
            return_value="100",
        ):
            result = get_algorithm_setting_int(engine, "algorithm_pagerank_max_iter")

        assert result == 100

    def test_get_algorithm_setting_int_handles_invalid(self):
        """Should handle invalid int value."""
        from unittest.mock import patch

        from deriva.services.config import get_algorithm_setting_int

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_algorithm_setting",
            return_value="not_a_number",
        ):
            result = get_algorithm_setting_int(engine, "key", default=50)

        assert result == 50

    def test_get_pagerank_config(self):
        """Should get pagerank configuration."""
        from unittest.mock import patch

        from deriva.services.config import get_pagerank_config

        engine = MagicMock()

        with (
            patch(
                "deriva.services.config.get_algorithm_setting_float",
                side_effect=[0.85, 1e-6],
            ),
            patch(
                "deriva.services.config.get_algorithm_setting_int",
                return_value=100,
            ),
        ):
            result = get_pagerank_config(engine)

        assert result["damping"] == 0.85
        assert result["max_iter"] == 100
        assert result["tol"] == 1e-6

    def test_get_louvain_config(self):
        """Should get louvain configuration."""
        from unittest.mock import patch

        from deriva.services.config import get_louvain_config

        engine = MagicMock()

        with patch(
            "deriva.services.config.get_algorithm_setting_float",
            return_value=1.0,
        ):
            result = get_louvain_config(engine)

        assert result["resolution"] == 1.0
