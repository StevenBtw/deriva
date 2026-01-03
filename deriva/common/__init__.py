"""
Common utilities and types shared across the Deriva pipeline.

This package provides:
- exceptions: Unified exception hierarchy
- types: TypedDicts and Protocols for consistent interfaces
- logging: JSON Lines based logging for pipeline runs
- time_utils: Timestamp generation and duration calculation
- json_utils: JSON parsing with error handling
- llm_utils: LLM response handling
- schema_utils: JSON Schema builders for structured output
- file_utils: File encoding utilities
- chunking: File chunking for large content handling
"""

from __future__ import annotations

from .exceptions import (
    APIError,
    BaseError,
    CacheError,
    CloneError,
    ConfigurationError,
    DeleteError,
    LLMError,
    MetadataError,
    ProviderError,
    RepositoryError,
    ServiceConnectionError,
    ValidationError,
)
from .file_utils import (
    read_file_with_encoding,
)
from .json_utils import (
    ParseResult,
    extract_json_from_response,
    parse_json_array,
)
from .llm_utils import (
    create_empty_llm_details,
    extract_llm_details,
)
from .schema_utils import (
    build_array_schema,
    build_object_schema,
)
from .chunking import (
    Chunk,
    chunk_by_delimiter,
    chunk_by_lines,
    chunk_content,
    estimate_tokens,
    get_model_token_limit,
    MODEL_TOKEN_LIMITS,
    should_chunk,
)
from .time_utils import (
    calculate_duration_ms,
    current_timestamp,
)
from .logging import (
    LogEntry,
    LogLevel,
    LogStatus,
    RunLogger,
    RunLoggerHandler,
    StepContext,
    get_logger_for_active_run,
    read_run_logs,
    setup_logging_bridge,
    teardown_logging_bridge,
)
from .types import (
    # Base types
    BaseResult,
    BatchExtractionFunction,
    BatchExtractionRegistry,
    BatchExtractionResult,
    DerivationConfig,
    # Derivation types
    DerivationData,
    DerivationFunction,
    DerivationRegistry,
    DerivationResult,
    # Extraction types
    ExtractionData,
    # Protocols
    ExtractionFunction,
    # Registry types
    ExtractionRegistry,
    ExtractionResult,
    FileExtractionResult,
    LLMDetails,
    ValidationConfig,
    ValidationData,
    ValidationFunction,
    # Validation types
    ValidationIssue,
    ValidationRegistry,
    ValidationResult,
)

__all__ = [
    # Exceptions
    "BaseError",
    "ConfigurationError",
    "APIError",
    "ProviderError",
    "ServiceConnectionError",
    "ValidationError",
    "CacheError",
    "RepositoryError",
    "CloneError",
    "DeleteError",
    "MetadataError",
    "LLMError",
    # Logging bridge
    "RunLoggerHandler",
    "setup_logging_bridge",
    "teardown_logging_bridge",
    # Types - Base
    "BaseResult",
    "LLMDetails",
    # Types - Extraction
    "ExtractionData",
    "ExtractionResult",
    "FileExtractionResult",
    "BatchExtractionResult",
    # Types - Derivation
    "DerivationData",
    "DerivationResult",
    "DerivationConfig",
    # Types - Validation
    "ValidationIssue",
    "ValidationData",
    "ValidationResult",
    "ValidationConfig",
    # Protocols
    "ExtractionFunction",
    "BatchExtractionFunction",
    "DerivationFunction",
    "ValidationFunction",
    # Registry types
    "ExtractionRegistry",
    "BatchExtractionRegistry",
    "DerivationRegistry",
    "ValidationRegistry",
    # Logging
    "LogLevel",
    "LogStatus",
    "LogEntry",
    "RunLogger",
    "StepContext",
    "get_logger_for_active_run",
    "read_run_logs",
    # File utils
    "read_file_with_encoding",
    # Time utils
    "current_timestamp",
    "calculate_duration_ms",
    # JSON utils
    "parse_json_array",
    "extract_json_from_response",
    "ParseResult",
    # LLM utils
    "create_empty_llm_details",
    "extract_llm_details",
    # Schema utils
    "build_array_schema",
    "build_object_schema",
    # Chunking utils
    "Chunk",
    "chunk_by_delimiter",
    "chunk_by_lines",
    "chunk_content",
    "estimate_tokens",
    "get_model_token_limit",
    "MODEL_TOKEN_LIMITS",
    "should_chunk",
]
