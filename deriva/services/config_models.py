"""
Pydantic models for Deriva configuration.

Uses pydantic-settings for environment variable validation and type coercion.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# =============================================================================
# Environment Settings (from .env file)
# =============================================================================


class GrafeoSettings(BaseSettings):
    """Grafeo (embedded graph database) settings."""

    model_config = SettingsConfigDict(env_prefix="GRAFEO_", env_file=".env", extra="ignore")

    db_path: str = ""  # Empty = in-memory, path = persistent
    log_queries: bool = False


class LLMSettings(BaseSettings):
    """LLM configuration settings."""

    model_config = SettingsConfigDict(env_prefix="LLM_", env_file=".env", extra="ignore")

    default_model: str | None = None
    temperature: float = Field(default=0.6, ge=0.0, le=2.0)
    max_retries: int = Field(default=3, ge=0)
    timeout: int = Field(default=60, ge=1)
    max_tokens: int | None = None

    # Cache settings
    cache_dir: str = "workspace/cache/llm"
    cache_ttl: int = 0
    nocache: bool = False

    # Rate limiting
    rate_limit_rpm: int = 0
    rate_limit_delay: float = 0.0
    rate_limit_retries: int = 3

    # Token limits
    token_limit_default: int = 32000


class GraphSettings(BaseSettings):
    """Graph manager settings."""

    model_config = SettingsConfigDict(env_prefix="GRAPH_", env_file=".env", extra="ignore")

    namespace: str = "Graph"
    cache_dir: str = "workspace/cache/graph"
    log_level: str = "INFO"


class ArchimateSettings(BaseSettings):
    """ArchiMate manager settings."""

    model_config = SettingsConfigDict(env_prefix="ARCHIMATE_", env_file=".env", extra="ignore")

    namespace: str = "Model"
    version: str = "3.1"
    identifier_prefix: str = "id-"

    # Validation
    validation_strict_mode: bool = False
    validation_allow_custom_properties: bool = True

    # Export
    export_pretty_print: bool = True
    export_encoding: str = "UTF-8"
    export_xml_declaration: bool = True
    export_validate_on_export: bool = True
    export_include_metadata: bool = True


class AppSettings(BaseSettings):
    """Application-level settings."""

    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")

    env: str = "development"
    log_level: str = "INFO"
    log_dir: str = "logs"


class DerivaSettings(BaseSettings):
    """
    Master settings class that aggregates all settings.

    Usage:
        settings = DerivaSettings()
        print(settings.grafeo.db_path)
        print(settings.llm.temperature)
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Repository settings
    repository_workspace_dir: str = Field(default="workspace/repositories", alias="REPOSITORY_WORKSPACE_DIR")
    output_dir: str = Field(default="workspace/output/model.xml", alias="OUTPUT_DIR")

    # Nested settings are loaded separately
    @property
    def grafeo(self) -> GrafeoSettings:
        return GrafeoSettings()

    @property
    def llm(self) -> LLMSettings:
        return LLMSettings()

    @property
    def graph(self) -> GraphSettings:
        return GraphSettings()

    @property
    def archimate(self) -> ArchimateSettings:
        return ArchimateSettings()

    @property
    def app(self) -> AppSettings:
        return AppSettings()


# =============================================================================
# Pipeline Configuration Models (from DuckDB)
# =============================================================================


class ExtractionConfigModel(BaseModel):
    """Extraction step configuration with validation."""

    node_type: str = Field(..., min_length=1, description="The node type to extract (e.g., 'BusinessConcept')")
    sequence: int = Field(default=0, ge=0, description="Execution order")
    enabled: bool = Field(default=True, description="Whether this extraction step is enabled")
    input_sources: str | None = Field(default=None, description="JSON string of input sources")
    instruction: str | None = Field(default=None, description="LLM instruction prompt")
    example: str | None = Field(default=None, description="Example output for LLM")
    extraction_method: Literal["llm", "ast", "structural"] = Field(default="llm", description="Extraction method to use")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="LLM temperature override")
    max_tokens: int | None = Field(default=None, ge=1, description="LLM max_tokens override")


class DerivationConfigModel(BaseModel):
    """Unified derivation step configuration with validation."""

    step_name: str = Field(..., min_length=1, description="The derivation step name")
    phase: Literal["prep", "generate", "refine", "relationship"] = Field(..., description="Derivation phase")
    sequence: int = Field(default=0, ge=0, description="Execution order within phase")
    enabled: bool = Field(default=True, description="Whether this derivation step is enabled")
    llm: bool = Field(default=False, description="True = uses LLM, False = pure graph algorithm")
    input_graph_query: str | None = Field(default=None, description="Cypher query for graph input")
    input_model_query: str | None = Field(default=None, description="Cypher query for model input")
    instruction: str | None = Field(default=None, description="LLM instruction prompt")
    example: str | None = Field(default=None, description="Example output for LLM")
    params: str | None = Field(default=None, description="JSON parameters for graph algorithms")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="LLM temperature override")
    max_tokens: int | None = Field(default=None, ge=1, description="LLM max_tokens override")
    max_candidates: int | None = Field(default=None, ge=1, description="Max candidates to send to LLM")
    batch_size: int | None = Field(default=None, ge=1, description="Batch size for LLM processing")

    @property
    def element_type(self) -> str:
        """Backward compatibility: element_type maps to step_name."""
        return self.step_name


class FileTypeModel(BaseModel):
    """File type registry entry with validation."""

    extension: str = Field(..., min_length=1, description="File extension (e.g., '.py')")
    file_type: str = Field(..., min_length=1, description="File type category (e.g., 'code')")
    subtype: str = Field(..., min_length=1, description="File subtype (e.g., 'python')")
    chunk_delimiter: str | None = Field(default=None, description="Delimiter for chunking")
    chunk_max_tokens: int | None = Field(default=None, ge=1, description="Max tokens per chunk")
    chunk_overlap: int = Field(default=0, ge=0, description="Token overlap between chunks")


# =============================================================================
# Threshold and Limit Models
# =============================================================================


class ConfidenceThresholds(BaseModel):
    """Confidence threshold configuration."""

    min_relationship: float = Field(default=0.6, ge=0.0, le=1.0, description="Minimum confidence for relationships")
    community_rel: float = Field(default=0.95, ge=0.0, le=1.0, description="Confidence for community-based relationships")
    name_match: float = Field(default=0.95, ge=0.0, le=1.0, description="Confidence for name-based matches")
    file_match: float = Field(default=0.85, ge=0.0, le=1.0, description="Confidence for file-based matches")
    fuzzy_match: float = Field(default=0.85, ge=0.0, le=1.0, description="Threshold for fuzzy string matching")
    semantic: float = Field(default=0.95, ge=0.0, le=1.0, description="Confidence for semantic similarity matches")
    pagerank_min: float = Field(default=0.001, ge=0.0, description="Minimum PageRank to consider")


class DerivationLimits(BaseModel):
    """Derivation processing limits."""

    max_relationships_per_derivation: int = Field(default=500, ge=1, description="Max relationships per derivation step")
    default_batch_size: int = Field(default=10, ge=1, description="Default batch size for LLM processing")
    default_max_candidates: int = Field(default=30, ge=1, description="Default max candidates for LLM derivation")
    high_pagerank_non_roots: int = Field(default=10, ge=1, description="For ApplicationComponent filtering")


class PageRankConfig(BaseModel):
    """PageRank algorithm configuration."""

    damping: float = Field(default=0.85, ge=0.0, le=1.0, description="Damping factor")
    max_iter: int = Field(default=100, ge=1, description="Maximum iterations")
    tol: float = Field(default=1e-6, gt=0.0, description="Convergence tolerance")


class LouvainConfig(BaseModel):
    """Louvain algorithm configuration."""

    resolution: float = Field(default=1.0, gt=0.0, description="Resolution parameter")


# =============================================================================
# Benchmark Model Configuration
# =============================================================================


class BenchmarkModelConfigModel(BaseModel):
    """Benchmark model configuration with validation."""

    name: str = Field(..., min_length=1, description="Model identifier")
    provider: Literal["azure", "openai", "anthropic", "ollama", "mistral", "lmstudio"] = Field(..., description="LLM provider")
    model: str = Field(..., min_length=1, description="Model name")
    api_url: str | None = Field(default=None, description="API endpoint URL")
    api_key: str | None = Field(default=None, description="API key (direct)")
    api_key_env: str | None = Field(default=None, description="Env var name for API key")
    structured_output: bool = Field(default=False, description="Enable structured output at API level")

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, v: str) -> str:
        """Normalize provider to lowercase before Literal validation."""
        if isinstance(v, str):
            return v.lower()
        return v
