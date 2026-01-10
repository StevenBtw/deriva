"""Graph models for repository structure.

This module defines the node and relationship models for representing
repository structure in Neo4j.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "normalize_path",
    "RepositoryNode",
    "DirectoryNode",
    "ModuleNode",
    "FileNode",
    "BusinessConceptNode",
    "TechnologyNode",
    "TypeDefinitionNode",
    "MethodNode",
    "TestNode",
    "ServiceNode",
    "ExternalDependencyNode",
]


def normalize_path(path: str, repo_name: str | None = None) -> str:
    """Normalize a path for consistent storage.

    Args:
        path: Path string to normalize
        repo_name: Optional repository name for prefixing paths

    Returns:
        Normalized path string using forward slashes
    """
    try:
        # Convert to Path object to normalize separators
        normalized = str(Path(path)).replace("\\", "/")

        # Handle empty or invalid paths
        if not normalized or normalized == ".":
            return ""

        # Remove repo prefix if present
        if repo_name and normalized.startswith(f"{repo_name}/"):
            normalized = normalized[len(repo_name) + 1 :]

        # Remove any leading/trailing slashes
        normalized = normalized.strip("/")

        # Handle special case for root directory
        if not normalized:
            return repo_name if repo_name else ""

        # Add back repo prefix if provided
        return f"{repo_name}/{normalized}" if repo_name else normalized

    except Exception as e:
        # Log error but don't fail - return empty string
        logger.error("Failed to normalize path '%s': %s", path, e)
        return ""


@dataclass
class RepositoryNode:
    """Represents a repository in the graph."""

    name: str  # repoName in metamodel
    url: str
    created_at: datetime
    branch: str | None = None
    commit: str | None = None
    description: str | None = None
    confidence: float = 1.0
    extraction_method: str = "structural"  # structural, ast, or llm

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Repository_{self.name}"

    def to_dict(self) -> dict:
        """Convert to dictionary for Neo4j."""
        return {
            "repoName": self.name,  # Use metamodel field name
            "url": self.url,
            "branch": self.branch,
            "commit": self.commit,
            "description": self.description,
            "confidence": self.confidence,
            "extractionMethod": self.extraction_method,
            "type": "Repository",
        }


@dataclass
class DirectoryNode:
    """Represents a directory in the graph."""

    name: str
    path: str
    repository_name: str
    confidence: float = 1.0
    extraction_method: str = "structural"  # structural, ast, or llm

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        safe_path = self.path.replace("/", "_").replace("\\", "_")
        return f"Directory_{self.repository_name}_{safe_path}"

    def to_dict(self) -> dict:
        """Convert to dictionary for Neo4j."""
        return {
            "name": self.name,
            "path": normalize_path(self.path, self.repository_name),
            "confidence": self.confidence,
            "extractionMethod": self.extraction_method,
            "type": "Directory",
        }


@dataclass
class ModuleNode:
    """Represents a module in the graph."""

    name: str
    paths: list[str]  # List of paths this module contains
    repository_name: str
    description: str | None = None
    confidence: float = 1.0
    extraction_method: str = "llm"  # structural, ast, or llm

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Module_{self.repository_name}_{self.name}"

    def to_dict(self) -> dict:
        """Convert to dictionary for Neo4j."""
        return {
            "name": self.name,
            "paths": [normalize_path(p, self.repository_name) for p in self.paths],
            "description": self.description,
            "confidence": self.confidence,
            "extractionMethod": self.extraction_method,
            "type": "Module",
        }


@dataclass
class FileNode:
    """Represents a file in the graph."""

    name: str  # fileName in metamodel
    path: str  # filePath in metamodel
    repository_name: str
    file_type: str
    subtype: str | None = None
    size: int = 0
    confidence: float = 1.0
    complexity_score: float = 0.0
    extraction_method: str = "structural"  # structural, ast, or llm

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        safe_path = self.path.replace("/", "_").replace("\\", "_")
        return f"File_{self.repository_name}_{safe_path}"

    def to_dict(self) -> dict:
        """Convert to dictionary for Neo4j."""
        return {
            "fileName": self.name,  # Use metamodel field name
            "filePath": normalize_path(
                self.path, self.repository_name
            ),  # Use metamodel field name
            "fileType": self.file_type,  # Use metamodel field name
            "subtype": self.subtype,
            "size": self.size,
            "complexityScore": self.complexity_score,  # Use metamodel field name
            "confidence": self.confidence,
            "extractionMethod": self.extraction_method,
            "type": "File",
        }


@dataclass
class BusinessConceptNode:
    """Represents a business concept in the graph."""

    name: str
    concept_type: str  # Must be one of: actor, service, process, entity, event, rule, goal, channel, product, capability, other
    description: str
    origin_source: str  # Path to the file where the concept was found
    repository_name: str
    confidence: float = 1.0
    extraction_method: str = "llm"  # structural, ast, or llm

    def __post_init__(self):
        """Validate concept_type is one of the allowed values."""
        valid_types = [
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
        ]
        if self.concept_type not in valid_types:
            logger.warning(
                "Invalid concept_type '%s' for business concept '%s'. Using 'other' instead.",
                self.concept_type,
                self.name,
            )
            self.concept_type = "other"

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"BusinessConcept_{self.repository_name}_{self.name}_{self.concept_type}"

    def to_dict(self) -> dict:
        """Convert to dictionary for Neo4j."""
        return {
            "conceptName": self.name,
            "conceptType": self.concept_type,
            "description": self.description,
            "originSource": normalize_path(self.origin_source, self.repository_name),
            "confidence": self.confidence,
            "extractionMethod": self.extraction_method,
            "type": "BusinessConcept",
        }


@dataclass
class TechnologyNode:
    """Represents a technology infrastructure component in the graph.

    Maps to ArchiMate Technology Layer elements:
    - service: Technology services (auth, API gateway, message queue)
    - system_software: Databases, web servers, caches
    - infrastructure: Cloud platforms, container platforms
    - platform: Serverless, PaaS offerings
    - network: API protocols, communication patterns
    - security: Authentication mechanisms, IAM
    """

    name: str
    tech_category: (
        str  # service, system_software, infrastructure, platform, network, security
    )
    repository_name: str
    description: str | None = None
    version: str | None = None
    origin_source: str | None = None  # File where technology was discovered
    confidence: float = 1.0
    extraction_method: str = "llm"  # structural, ast, or llm

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Technology_{self.name}_{self.tech_category}"

    def to_dict(self) -> dict:
        """Convert to dictionary for Neo4j."""
        return {
            "techName": self.name,
            "techCategory": self.tech_category,
            "description": self.description,
            "version": self.version,
            "originSource": self.origin_source,
            "confidence": self.confidence,
            "extractionMethod": self.extraction_method,
            "type": "Technology",
        }


@dataclass
class TypeDefinitionNode:
    """Represents a type definition in the graph."""

    name: str
    type_category: str  # e.g., class, interface, struct, enum, function, alias, module
    file_path: str  # Path to the file where the type is defined
    repository_name: str
    description: str | None = None
    interface_type: str | None = None  # e.g., REST API, GraphQL, Internal API, gRPC
    start_line: int = 0  # Line number where type definition starts (1-indexed)
    end_line: int = 0  # Line number where type definition ends (1-indexed)
    code_snippet: str | None = None  # The actual code of the type definition
    confidence: float = 1.0
    extraction_method: str = "ast"  # structural, ast, or llm

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"TypeDefinition_{self.repository_name}_{self.name}_{self.type_category}"

    def to_dict(self) -> dict:
        """Convert to dictionary for Neo4j."""
        return {
            "typeName": self.name,
            "category": self.type_category,
            "description": self.description,
            "interfaceType": self.interface_type,
            "filePath": normalize_path(self.file_path, self.repository_name),
            "startLine": self.start_line,
            "endLine": self.end_line,
            "codeSnippet": self.code_snippet,
            "confidence": self.confidence,
            "extractionMethod": self.extraction_method,
            "type": "TypeDefinition",
        }


@dataclass
class MethodNode:
    """Represents a method in the graph."""

    name: str
    return_type: str  # e.g., void, int, String, None for Python
    visibility: str  # e.g., public, private, protected
    file_path: str  # Path to the file where the method is defined
    type_name: str  # Name of the type this method belongs to
    repository_name: str
    description: str | None = None  # Brief description of what the method does
    parameters: str | None = (
        None  # Parameter signature (e.g., "self, name: str, age: int")
    )
    is_static: bool = False  # Whether it's a static method
    is_async: bool = False  # Whether it's an async method
    start_line: int = 0  # Line number where method starts (relative to type, 1-indexed)
    end_line: int = 0  # Line number where method ends (relative to type, 1-indexed)
    confidence: float = 1.0
    extraction_method: str = "ast"  # structural, ast, or llm

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Method_{self.repository_name}_{self.type_name}_{self.name}"

    def to_dict(self) -> dict:
        """Convert to dictionary for Neo4j."""
        return {
            "methodName": self.name,
            "returnType": self.return_type,
            "visibility": self.visibility,
            "filePath": normalize_path(self.file_path, self.repository_name),
            "typeName": self.type_name,
            "description": self.description,
            "parameters": self.parameters,
            "isStatic": self.is_static,
            "isAsync": self.is_async,
            "startLine": self.start_line,
            "endLine": self.end_line,
            "confidence": self.confidence,
            "extractionMethod": self.extraction_method,
            "type": "Method",
        }


@dataclass
class TestNode:
    """Represents a test in the graph.

    Test types:
    - unit: Tests individual functions/methods in isolation
    - integration: Tests interaction between components
    - e2e: End-to-end tests of full user flows
    - performance: Load/stress/performance tests
    - smoke: Quick sanity checks
    - regression: Tests for previously fixed bugs
    """

    __test__ = False  # Prevent pytest from collecting this as a test class

    name: str
    test_type: str  # unit, integration, e2e, performance, smoke, regression, other
    file_path: str
    repository_name: str
    description: str | None = None
    tested_element: str | None = None  # What is being tested (class, function, feature)
    framework: str | None = None  # Test framework (pytest, jest, unittest)
    start_line: int = 0
    end_line: int = 0
    confidence: float = 1.0
    extraction_method: str = "llm"  # structural, ast, or llm

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Test_{self.repository_name}_{self.name}_{self.test_type}"

    def to_dict(self) -> dict:
        """Convert to dictionary for Neo4j."""
        return {
            "testName": self.name,
            "testType": self.test_type,
            "description": self.description,
            "testedElement": self.tested_element,
            "framework": self.framework,
            "filePath": normalize_path(self.file_path, self.repository_name),
            "startLine": self.start_line,
            "endLine": self.end_line,
            "confidence": self.confidence,
            "extractionMethod": self.extraction_method,
            "type": "Test",
        }


@dataclass
class ServiceNode:
    """Represents a service in the graph."""

    name: str
    description: str
    exposure_level: str  # e.g., public, internal, private
    repository_name: str
    file_path: str | None = None  # Path to the file where the service is defined
    confidence: float = 1.0
    extraction_method: str = "llm"  # structural, ast, or llm

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Service_{self.repository_name}_{self.name}"

    def to_dict(self) -> dict:
        """Convert to dictionary for Neo4j."""
        return {
            "serviceName": self.name,
            "description": self.description,
            "exposureLevel": self.exposure_level,
            "filePath": normalize_path(self.file_path, self.repository_name)
            if self.file_path
            else None,
            "confidence": self.confidence,
            "extractionMethod": self.extraction_method,
            "type": "Service",
        }


@dataclass
class ExternalDependencyNode:
    """Represents an external dependency in the graph.

    Categories:
    - library: Package dependencies (flask, react, lodash)
    - external_api: Third-party API integrations (Stripe, SendGrid)
    - external_service: External SaaS/systems (MongoDB Atlas)
    - external_database: External database services
    """

    name: str
    dependency_category: (
        str  # library, external_api, external_service, external_database
    )
    repository_name: str
    version: str | None = None
    ecosystem: str | None = None  # pypi, npm, maven, or provider name
    description: str | None = None
    origin_source: str | None = None  # File where dependency was discovered
    confidence: float = 1.0
    extraction_method: str = "llm"  # structural, ast, or llm

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        version_suffix = f"_{self.version}" if self.version else ""
        return f"ExternalDependency_{self.name}{version_suffix}"

    def to_dict(self) -> dict:
        """Convert to dictionary for Neo4j."""
        return {
            "dependencyName": self.name,
            "dependencyCategory": self.dependency_category,
            "version": self.version,
            "ecosystem": self.ecosystem,
            "description": self.description,
            "originSource": self.origin_source,
            "confidence": self.confidence,
            "extractionMethod": self.extraction_method,
            "type": "ExternalDependency",
        }


# Relationship types
CONTAINS = "CONTAINS"  # For repository->module, repository->directory, directory->file, module->file relationships
DEPENDS_ON = (
    "DEPENDS_ON"  # For module->module, file->file, service->service dependencies
)
REFERENCES = "REFERENCES"  # For file->businessconcept relationships
IMPLEMENTS = "IMPLEMENTS"  # For file->technology relationships
DECLARES = "DECLARES"  # For typedefinition->method relationships
PROVIDES = "PROVIDES"  # For typedefinition->service relationships
EXPOSES = "EXPOSES"  # For method->service relationships
USES = "USES"  # For file->externaldependency, service->externaldependency relationships
TESTS = "TESTS"  # For test->file, test->method, test->service relationships
