"""Tests for config_models module (configuration row models)."""

import pytest
from pydantic import ValidationError

from deriva.services.config_models import (
    BenchmarkModelConfigModel,
    ConfidenceThresholds,
    DerivationConfigModel,
    DerivationLimits,
    ExtractionConfigModel,
    FileTypeModel,
    LouvainConfig,
    PageRankConfig,
)


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
        with pytest.raises(ValidationError, match=r"node_type\n  Field required"):
            ExtractionConfigModel()

    def test_validates_temperature_range(self):
        """Should validate temperature range."""
        with pytest.raises(ValidationError, match=r"temperature\n  Input should be less than or equal to 2"):
            ExtractionConfigModel(node_type="Test", temperature=3.0)

    def test_accepts_every_method_a_step_can_be_added_with(self):
        """The model and ``config add`` know the same extraction methods."""
        from deriva.services.config import EXTRACTION_METHODS

        for method in EXTRACTION_METHODS:
            assert ExtractionConfigModel(node_type="Test", extraction_method=method).extraction_method == method

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
        with pytest.raises(ValidationError, match=r"phase\n  Input should be 'prep', 'generate', 'refine', 'relationship' or 'baseline'"):
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
        with pytest.raises(ValidationError, match=r"min_relationship\n  Input should be less than or equal to 1"):
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
        with pytest.raises(ValidationError, match=r"provider\n  Input should be 'azure'"):
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
