"""
Pydantic schemas for LLM structured output.

These models are used with PydanticAI to enforce structured output from LLMs.
They correspond to the extraction and derivation step outputs.

Usage:
    from deriva.adapters.llm.schemas import BusinessConceptResponse

    llm = LLMManager()
    result = llm.query(prompt, response_model=BusinessConceptResponse)
    for concept in result.concepts:
        print(concept.conceptName)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# =============================================================================
# Extraction Schemas
# =============================================================================


class BusinessConceptItem(BaseModel):
    """A single business concept extracted from documentation."""

    conceptName: str = Field(description="Name of the business concept")
    conceptType: Literal[
        "actor",
        "service",
        "process",
        "entity",
        "event",
        "rule",
        "goal",
        "channel",
        "product",
        "capability",
        "other",
    ] = Field(description="Type of business concept")
    description: str = Field(description="Brief description of the concept")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0"
    )


class BusinessConceptResponse(BaseModel):
    """Response containing extracted business concepts."""

    concepts: list[BusinessConceptItem] = Field(
        default_factory=list, description="List of extracted business concepts"
    )


class BusinessConceptMultiFileResult(BaseModel):
    """Result for a single file in multi-file extraction."""

    file_path: str = Field(
        description="Path of the file these concepts were extracted from"
    )
    concepts: list[BusinessConceptItem] = Field(
        default_factory=list, description="Concepts extracted from this file"
    )


class BusinessConceptMultiResponse(BaseModel):
    """Response containing extracted business concepts from multiple files."""

    results: list[BusinessConceptMultiFileResult] = Field(
        default_factory=list, description="Results per file"
    )


class TypeDefinitionItem(BaseModel):
    """A single type definition extracted from source code."""

    typeName: str = Field(
        description="Name of the type (class, interface, function, etc.)"
    )
    category: Literal[
        "class",
        "interface",
        "struct",
        "enum",
        "function",
        "alias",
        "module",
        "other",
    ] = Field(description="Category of the type definition")
    description: str = Field(description="Brief description of what this type does")
    interfaceType: Literal[
        "REST API",
        "GraphQL",
        "gRPC",
        "WebSocket",
        "CLI",
        "Internal API",
        "none",
    ] = Field(
        default="none",
        description="Type of interface this definition exposes, or 'none' if not an interface",
    )
    startLine: int = Field(
        ge=1, description="Line number where the type definition starts (1-indexed)"
    )
    endLine: int = Field(
        ge=1, description="Line number where the type definition ends (1-indexed)"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0"
    )


class TypeDefinitionResponse(BaseModel):
    """Response containing extracted type definitions."""

    types: list[TypeDefinitionItem] = Field(
        default_factory=list, description="List of extracted type definitions"
    )


class TechnologyItem(BaseModel):
    """A single technology extracted from code."""

    technologyName: str = Field(description="Name of the technology")
    technologyType: Literal[
        "service",
        "system_software",
        "infrastructure",
        "platform",
        "network",
        "security",
        "other",
    ] = Field(description="Category of technology")
    description: str = Field(
        description="Brief description of how the technology is used"
    )
    version: str | None = Field(
        default=None, description="Version of the technology if known"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0"
    )


class TechnologyResponse(BaseModel):
    """Response containing extracted technologies."""

    technologies: list[TechnologyItem] = Field(
        default_factory=list, description="List of extracted technologies"
    )


class ExternalDependencyItem(BaseModel):
    """A single external dependency extracted from code."""

    dependencyName: str = Field(description="Name of the external dependency")
    dependencyCategory: Literal[
        "library",
        "external_api",
        "external_service",
        "external_database",
        "other",
    ] = Field(description="Category of dependency")
    description: str = Field(description="Brief description of the dependency")
    version: str | None = Field(default=None, description="Version if known")
    ecosystem: str | None = Field(
        default=None, description="Package ecosystem (pypi, npm, maven, etc.)"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0"
    )


class ExternalDependencyResponse(BaseModel):
    """Response containing extracted external dependencies."""

    dependencies: list[ExternalDependencyItem] = Field(
        default_factory=list, description="List of extracted external dependencies"
    )


class TestItem(BaseModel):
    """A single test extracted from code."""

    testName: str = Field(description="Name of the test")
    testType: Literal[
        "unit",
        "integration",
        "e2e",
        "performance",
        "smoke",
        "regression",
        "other",
    ] = Field(description="Type of test")
    description: str = Field(description="Brief description of what the test verifies")
    testedElement: str | None = Field(
        default=None, description="What is being tested (class, function, feature)"
    )
    framework: str | None = Field(
        default=None, description="Test framework (pytest, jest, unittest)"
    )
    startLine: int = Field(
        ge=1, description="Line number where the test starts (1-indexed)"
    )
    endLine: int = Field(
        ge=1, description="Line number where the test ends (1-indexed)"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0"
    )


class TestResponse(BaseModel):
    """Response containing extracted tests."""

    tests: list[TestItem] = Field(
        default_factory=list, description="List of extracted tests"
    )


class MethodItem(BaseModel):
    """A single method extracted from code."""

    methodName: str = Field(description="Name of the method/function")
    returnType: str = Field(description="Return type of the method")
    visibility: Literal["public", "private", "protected", "internal"] = Field(
        default="public", description="Visibility modifier"
    )
    description: str = Field(description="Brief description of what the method does")
    parameters: str | None = Field(default=None, description="Parameter signature")
    isStatic: bool = Field(default=False, description="Whether it's a static method")
    isAsync: bool = Field(default=False, description="Whether it's an async method")
    startLine: int = Field(
        ge=1, description="Line number where the method starts (1-indexed)"
    )
    endLine: int = Field(
        ge=1, description="Line number where the method ends (1-indexed)"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0"
    )


class MethodResponse(BaseModel):
    """Response containing extracted methods."""

    methods: list[MethodItem] = Field(
        default_factory=list, description="List of extracted methods"
    )


class DirectoryClassificationItem(BaseModel):
    """Classification for a single directory."""

    directoryName: str = Field(description="Original directory name")
    classification: Literal["business", "technology", "skip"] = Field(
        description="Classification type"
    )
    conceptType: str = Field(
        description="Specific type (for business: actor/entity/process; for technology: infrastructure/framework/tool)"
    )
    description: str = Field(description="Brief description of what this represents")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0"
    )


class DirectoryClassificationResponse(BaseModel):
    """Response containing directory classifications."""

    classifications: list[DirectoryClassificationItem] = Field(
        default_factory=list, description="List of directory classifications"
    )


# =============================================================================
# Derivation Schemas
# =============================================================================


class DerivedElementItem(BaseModel):
    """A single ArchiMate element derived from extraction data."""

    name: str = Field(description="Name of the element")
    description: str = Field(description="Description of the element")
    documentation: str | None = Field(
        default=None, description="Additional documentation"
    )
    sourceNodes: list[str] = Field(
        default_factory=list,
        description="IDs of source nodes this element was derived from",
    )
    confidence: float = Field(
        ge=0.0, le=1.0, default=0.8, description="Confidence score"
    )


class DerivedElementResponse(BaseModel):
    """Response containing derived ArchiMate elements."""

    elements: list[DerivedElementItem] = Field(
        default_factory=list, description="List of derived elements"
    )


class DerivedRelationshipItem(BaseModel):
    """A single ArchiMate relationship derived from extraction data."""

    sourceName: str = Field(description="Name of the source element")
    targetName: str = Field(description="Name of the target element")
    relationshipType: Literal[
        "Composition",
        "Aggregation",
        "Assignment",
        "Realization",
        "Serving",
        "Access",
        "Flow",
        "Triggering",
    ] = Field(description="Type of ArchiMate relationship")
    description: str | None = Field(
        default=None, description="Description of the relationship"
    )


class DerivedRelationshipResponse(BaseModel):
    """Response containing derived ArchiMate relationships."""

    relationships: list[DerivedRelationshipItem] = Field(
        default_factory=list, description="List of derived relationships"
    )


# =============================================================================
# Schema Registry - Maps extraction types to Pydantic models
# =============================================================================

EXTRACTION_SCHEMAS: dict[str, type[BaseModel]] = {
    "BusinessConcept": BusinessConceptResponse,
    "BusinessConceptMulti": BusinessConceptMultiResponse,
    "TypeDefinition": TypeDefinitionResponse,
    "Technology": TechnologyResponse,
    "ExternalDependency": ExternalDependencyResponse,
    "Test": TestResponse,
    "Method": MethodResponse,
    "DirectoryClassification": DirectoryClassificationResponse,
}

DERIVATION_SCHEMAS: dict[str, type[BaseModel]] = {
    "elements": DerivedElementResponse,
    "relationships": DerivedRelationshipResponse,
}


def get_extraction_schema(node_type: str) -> type[BaseModel] | None:
    """Get the Pydantic schema for an extraction type."""
    return EXTRACTION_SCHEMAS.get(node_type)


def get_derivation_schema(schema_type: str) -> type[BaseModel] | None:
    """Get the Pydantic schema for a derivation type."""
    return DERIVATION_SCHEMAS.get(schema_type)


__all__ = [
    # Extraction schemas
    "BusinessConceptItem",
    "BusinessConceptResponse",
    "BusinessConceptMultiFileResult",
    "BusinessConceptMultiResponse",
    "TypeDefinitionItem",
    "TypeDefinitionResponse",
    "TechnologyItem",
    "TechnologyResponse",
    "ExternalDependencyItem",
    "ExternalDependencyResponse",
    "TestItem",
    "TestResponse",
    "MethodItem",
    "MethodResponse",
    "DirectoryClassificationItem",
    "DirectoryClassificationResponse",
    # Derivation schemas
    "DerivedElementItem",
    "DerivedElementResponse",
    "DerivedRelationshipItem",
    "DerivedRelationshipResponse",
    # Registry
    "EXTRACTION_SCHEMAS",
    "DERIVATION_SCHEMAS",
    "get_extraction_schema",
    "get_derivation_schema",
]
