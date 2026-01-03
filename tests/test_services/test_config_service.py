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
        engine.execute.return_value.fetchall.return_value = [
            ("BusinessConcept", 1, True, '{"files": []}', "instruction1", "example1", "llm"),
            ("TypeDefinition", 2, True, '{"files": []}', "instruction2", "example2", "ast"),
        ]

        configs = get_extraction_configs(engine)

        assert len(configs) == 2
        assert configs[0].node_type == "BusinessConcept"
        assert configs[1].node_type == "TypeDefinition"
        assert configs[1].extraction_method == "ast"

    def test_filters_enabled_only(self):
        """Should filter to enabled configs when requested."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = [
            ("BusinessConcept", 1, True, None, None, None, "llm"),
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
            ("BusinessConcept", 1, True, None, None, None, None),
        ]

        configs = get_extraction_configs(engine)

        assert configs[0].extraction_method == "llm"


class TestGetExtractionConfig:
    """Tests for get_extraction_config function."""

    def test_returns_config_when_found(self):
        """Should return config when found."""
        engine = MagicMock()
        engine.execute.return_value.fetchone.return_value = (
            "BusinessConcept", 1, True, '{"files": []}', "instruction", "example", "llm"
        )

        config = get_extraction_config(engine, "BusinessConcept")

        assert config is not None
        assert config.node_type == "BusinessConcept"
        assert config.enabled is True

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
        engine.execute.return_value.fetchall.return_value = [
            ("PageRank", "prep", 1, True, False, "MATCH (n) RETURN n", None, None, None, '{"damping": 0.85}'),
            ("ApplicationComponent", "generate", 1, True, True, None, None, "instruction", "example", None),
        ]

        configs = get_derivation_configs(engine)

        assert len(configs) == 2
        assert configs[0].step_name == "PageRank"
        assert configs[0].phase == "prep"
        assert configs[0].llm is False
        assert configs[1].step_name == "ApplicationComponent"
        assert configs[1].llm is True

    def test_filters_by_phase(self):
        """Should filter by phase when specified."""
        engine = MagicMock()
        engine.execute.return_value.fetchall.return_value = [
            ("ApplicationComponent", "generate", 1, True, True, None, None, None, None, None),
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
        engine.execute.return_value.fetchone.return_value = (
            "ApplicationComponent", "generate", 1, True, True, "MATCH (n)", None, "instruction", "example", None
        )

        config = get_derivation_config(engine, "ApplicationComponent")

        assert config is not None
        assert config.step_name == "ApplicationComponent"
        assert config.phase == "generate"

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
        engine.execute.return_value.fetchone.return_value = (
            ".py", "source", "python", None, None, 0
        )

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
        engine.execute.return_value.fetchone.return_value = (
            ".md", "documentation", "markdown", "\n\n", 1000, 100
        )

        file_type = get_file_type(engine, ".md")

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
        engine.execute.return_value.fetchone.return_value = (
            ".py", "source", "python", None, None, 0
        )

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
