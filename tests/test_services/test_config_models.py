"""Tests for config_models module (pydantic-settings integration)."""

from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_settings import SettingsConfigDict

from deriva.services.config_models import (
    BenchmarkModelConfigModel,
    ConfidenceThresholds,
    DerivaSettings,
    DerivationConfigModel,
    DerivationLimits,
    ExtractionConfigModel,
    FileTypeModel,
    GrafeoSettings,
    LLMSettings,
    LouvainConfig,
    PageRankConfig,
)

# Type alias to help with BaseSettings._env_file parameter which isn't in the type signature
_GrafeoSettings: Any = GrafeoSettings
_LLMSettings: Any = LLMSettings
_DerivaSettings: Any = DerivaSettings


class TestGrafeoSettings:
    """Tests for GrafeoSettings."""

    def test_default_values(self):
        """Should have sensible defaults."""
        settings = _GrafeoSettings(_env_file=None)
        assert settings.db_path == ""
        assert settings.log_queries is False

    def test_loads_from_env(self, monkeypatch):
        """Should load values from environment."""
        monkeypatch.setenv("GRAFEO_DB_PATH", "/tmp/test.db")
        monkeypatch.setenv("GRAFEO_LOG_QUERIES", "true")
        settings = _GrafeoSettings(_env_file=None)
        assert settings.db_path == "/tmp/test.db"
        assert settings.log_queries is True


class TestLLMSettings:
    """Tests for LLMSettings."""

    def test_default_values(self):
        """Should have sensible defaults."""
        settings = _LLMSettings(_env_file=None)
        assert settings.temperature == 0.6
        assert settings.max_retries == 3
        assert settings.timeout == 60
        assert settings.nocache is False

    def test_temperature_validation(self, monkeypatch):
        """Should validate temperature range."""
        monkeypatch.setenv("LLM_TEMPERATURE", "1.5")
        settings = _LLMSettings(_env_file=None)
        assert settings.temperature == 1.5

    def test_loads_from_env(self, monkeypatch):
        """Should load values from environment."""
        monkeypatch.setenv("LLM_DEFAULT_MODEL", "test-model")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.3")
        settings = _LLMSettings(_env_file=None)
        assert settings.default_model == "test-model"
        assert settings.temperature == 0.3


class TestDerivaSettings:
    """Tests for DerivaSettings master class."""

    def test_default_values(self):
        """Should have sensible defaults."""
        settings = _DerivaSettings(_env_file=None)
        assert settings.repository_workspace_dir == "workspace/repositories"

    def test_nested_settings(self, monkeypatch):
        """Should provide access to nested settings.

        Nested settings properties create fresh instances that read .env,
        so we must clear the env var to isolate the test.
        """
        monkeypatch.delenv("GRAFEO_DB_PATH", raising=False)
        monkeypatch.setattr(GrafeoSettings, "model_config", SettingsConfigDict(env_prefix="GRAFEO_", env_file=None, extra="ignore"))
        settings = _DerivaSettings(_env_file=None)
        assert settings.grafeo.db_path == ""
        assert settings.llm.temperature == 0.6
        assert settings.graph.namespace == "Graph"


class TestExtractionConfigModel:
    """Tests for ExtractionConfigModel."""

    def test_valid_config(self):
        """Should create valid config."""
        config = ExtractionConfigModel(node_type="BusinessConcept")
        assert config.node_type == "BusinessConcept"
        assert config.enabled is True
        assert config.extraction_method == "llm"

    def test_requires_node_type(self):
        """Should require node_type."""
        with pytest.raises(ValidationError):
            ExtractionConfigModel()

    def test_validates_temperature_range(self):
        """Should validate temperature range."""
        with pytest.raises(ValidationError):
            ExtractionConfigModel(node_type="Test", temperature=3.0)

    def test_validates_extraction_method(self):
        """Should validate extraction_method."""
        config = ExtractionConfigModel(node_type="Test", extraction_method="ast")
        assert config.extraction_method == "ast"

        with pytest.raises(ValidationError):
            ExtractionConfigModel(node_type="Test", extraction_method="invalid")  # type: ignore[arg-type]


class TestDerivationConfigModel:
    """Tests for DerivationConfigModel."""

    def test_valid_config(self):
        """Should create valid config."""
        config = DerivationConfigModel(step_name="ApplicationService", phase="generate")
        assert config.step_name == "ApplicationService"
        assert config.phase == "generate"
        assert config.enabled is True

    def test_element_type_backward_compat(self):
        """Should provide element_type alias."""
        config = DerivationConfigModel(step_name="AppComp", phase="generate")
        assert config.element_type == "AppComp"

    def test_validates_phase(self):
        """Should validate phase values."""
        with pytest.raises(ValidationError):
            DerivationConfigModel(step_name="Test", phase="invalid_phase")  # type: ignore[arg-type]


class TestFileTypeModel:
    """Tests for FileTypeModel."""

    def test_valid_config(self):
        """Should create valid config."""
        ft = FileTypeModel(extension=".py", file_type="code", subtype="python")
        assert ft.extension == ".py"
        assert ft.chunk_overlap == 0

    def test_with_chunking(self):
        """Should accept chunking config."""
        ft = FileTypeModel(
            extension=".md",
            file_type="doc",
            subtype="markdown",
            chunk_delimiter="\n\n",
            chunk_max_tokens=1000,
            chunk_overlap=50,
        )
        assert ft.chunk_max_tokens == 1000
        assert ft.chunk_overlap == 50


class TestConfidenceThresholds:
    """Tests for ConfidenceThresholds."""

    def test_default_values(self):
        """Should have sensible defaults."""
        thresholds = ConfidenceThresholds()
        assert thresholds.min_relationship == 0.6
        assert thresholds.community_rel == 0.95
        assert thresholds.name_match == 0.95

    def test_validates_range(self):
        """Should validate threshold range."""
        with pytest.raises(ValidationError):
            ConfidenceThresholds(min_relationship=1.5)


class TestDerivationLimits:
    """Tests for DerivationLimits."""

    def test_default_values(self):
        """Should have sensible defaults."""
        limits = DerivationLimits()
        assert limits.max_relationships_per_derivation == 500
        assert limits.default_batch_size == 10


class TestPageRankConfig:
    """Tests for PageRankConfig."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = PageRankConfig()
        assert config.damping == 0.85
        assert config.max_iter == 100
        assert config.tol == 1e-6


class TestLouvainConfig:
    """Tests for LouvainConfig."""

    def test_default_values(self):
        """Should have sensible defaults."""
        config = LouvainConfig()
        assert config.resolution == 1.0


class TestBenchmarkModelConfigModel:
    """Tests for BenchmarkModelConfigModel."""

    def test_valid_config(self):
        """Should create valid config."""
        config = BenchmarkModelConfigModel(
            name="test-model",
            provider="openai",
            model="gpt-4",
        )
        assert config.name == "test-model"
        assert config.provider == "openai"

    def test_validates_provider(self):
        """Should validate provider."""
        with pytest.raises(ValidationError):
            BenchmarkModelConfigModel(
                name="test",
                provider="invalid_provider",  # type: ignore[arg-type]
                model="model",
            )

    def test_normalizes_provider_case(self):
        """Should normalize provider to lowercase."""
        config = BenchmarkModelConfigModel(
            name="test",
            provider="OpenAI",  # type: ignore[arg-type]  # Tests case normalization
            model="gpt-4",
        )
        assert config.provider == "openai"
