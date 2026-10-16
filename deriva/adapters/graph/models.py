"""Graph models for repository structure.

This module defines the node and relationship models for representing
repository structure in the graph database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "normalize_path",
    "repo_relative",
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
    "DeployableUnitNode",
    "DataEntityNode",
    "DataDomainNode",
    "EnvironmentNode",
    "DeploymentNode",
    "LifecycleNode",
    "LifecycleEventNode",
    "RoleNode",
    "SoftwareNode",
    "INCLUDES",
]


def normalize_path(path: str, repo_name: str | None = None) -> str:
    """Normalize a path for consistent storage.

    Args:
        path: Repository-relative path string to normalize (a top folder named like the repository is kept)
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


def repo_relative(path: str, repo_name: str) -> str:
    """The repository-relative path of a stored path (the inverse of ``normalize_path`` with a repository name)."""
    path = str(path or "").replace("\\", "/")
    return path[len(repo_name) + 1 :] if path.startswith(f"{repo_name}/") else path


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
        """Convert to dictionary for graph storage."""
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
        """Convert to dictionary for graph storage."""
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
        """Convert to dictionary for graph storage."""
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
        """Convert to dictionary for graph storage."""
        return {
            "fileName": self.name,  # Use metamodel field name
            "filePath": normalize_path(self.path, self.repository_name),  # Use metamodel field name
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
    # Every type any file gave this concept (default: [concept_type])
    concept_types: list[str] | None = None
    # The document wordings behind the concept, as "term (language)"
    source_terms: list[str] | None = None

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
        """Convert to dictionary for graph storage."""
        return {
            "conceptName": self.name,
            "conceptType": self.concept_type,
            "conceptTypes": sorted(self.concept_types or [self.concept_type]),
            "sourceTerms": sorted(self.source_terms or []),
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
    tech_category: str  # service, system_software, infrastructure, platform, network, security
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
        """Convert to dictionary for graph storage."""
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
    decorators: list[str] = field(default_factory=list)  # Annotations or decorators, as written (e.g. RestController)

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"TypeDefinition_{self.repository_name}_{self.name}_{self.type_category}"

    def to_dict(self) -> dict:
        """Convert to dictionary for graph storage."""
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
            "decorators": list(self.decorators),
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
    parameters: str | None = None  # Parameter signature (e.g., "self, name: str, age: int")
    is_static: bool = False  # Whether it's a static method
    is_async: bool = False  # Whether it's an async method
    start_line: int = 0  # Line number where method starts (relative to type, 1-indexed)
    end_line: int = 0  # Line number where method ends (relative to type, 1-indexed)
    confidence: float = 1.0
    extraction_method: str = "ast"  # structural, ast, or llm
    decorators: list[str] = field(default_factory=list)  # Annotations or decorators, as written (e.g. GetMapping("orders"))

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Method_{self.repository_name}_{self.type_name}_{self.name}"

    def to_dict(self) -> dict:
        """Convert to dictionary for graph storage."""
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
            "decorators": list(self.decorators),
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
        """Convert to dictionary for graph storage."""
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
        """Convert to dictionary for graph storage."""
        return {
            "serviceName": self.name,
            "description": self.description,
            "exposureLevel": self.exposure_level,
            "filePath": normalize_path(self.file_path, self.repository_name) if self.file_path else None,
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

    Properties:
    - declared: True if dependency was found in a manifest file (requirements.txt, package.json)
    - used: True if dependency is imported in code
    """

    name: str
    dependency_category: str  # library, external_api, external_service, external_database
    repository_name: str
    version: str | None = None
    ecosystem: str | None = None  # pypi, npm, maven, or provider name
    description: str | None = None
    origin_source: str | None = None  # File where dependency was discovered
    confidence: float = 1.0
    extraction_method: str = "llm"  # structural, ast, or llm
    declared: bool = True  # True if found in manifest file
    used: bool = False  # True if imported in code

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        version_suffix = f"_{self.version}" if self.version else ""
        return f"ExternalDependency_{self.name}{version_suffix}"

    def to_dict(self) -> dict:
        """Convert to dictionary for graph storage."""
        return {
            "dependencyName": self.name,
            "dependencyCategory": self.dependency_category,
            "version": self.version,
            "ecosystem": self.ecosystem,
            "description": self.description,
            "originSource": self.origin_source,
            "confidence": self.confidence,
            "extractionMethod": self.extraction_method,
            "declared": self.declared,
            "used": self.used,
            "type": "ExternalDependency",
        }


@dataclass
class DeployableUnitNode:
    """A deployable unit: what runs on its own (a container, a declared entry point, a mainframe application).

    Its members (files, and for mainframe units programs and screens) hang below it by ``INCLUDES``
    edges; the structural evidence and the naming evidence (manifest name and description, the
    documentation lines that name it, the mainframe module) are properties.
    """

    name: str
    path: str
    unit_kind: str  # container, script, start, bin, war, spring-boot, application, online, batch, module, repository
    repository_name: str
    evidence: list[str] = field(default_factory=list)
    entry: str | None = None
    manifest_name: str | None = None
    manifest_description: str | None = None
    module: str | None = None
    readme_lines: list[str] = field(default_factory=list)
    readme_title: str | None = None
    web_entries: list[str] = field(default_factory=list)  # Files that serve pages (Web UI signals)
    product: str = ""
    name_candidates: list[str] = field(default_factory=list)  # The closed set its component is named from
    name_sources: list[str] = field(default_factory=list)  # Where each candidate comes from (readme, docs, manifest, ...)
    member_count: int = 0

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"DeployableUnit_{self.path}_{self.entry or self.unit_kind}"

    def to_dict(self) -> dict:
        """Convert to dictionary for graph storage."""
        return {
            "name": self.name,
            "path": self.path,
            "unitKind": self.unit_kind,
            "evidence": list(self.evidence),
            "entry": self.entry,
            "manifestName": self.manifest_name,
            "manifestDescription": self.manifest_description,
            "module": self.module,
            "readmeLines": list(self.readme_lines),
            "readmeTitle": self.readme_title,
            "webEntries": list(self.web_entries),
            "product": self.product,
            "nameCandidates": list(self.name_candidates),
            "nameSources": list(self.name_sources),
            "memberCount": self.member_count,
            # Unit ids carry no prefix the graph manager reads the repository from
            "repository_name": self.repository_name,
            "type": "DeployableUnit",
        }


@dataclass
class DataEntityNode:
    """A data entity: one persistent concept of the code (an aggregate root, an ORM entity, a shared
    record, a table), merging the same concept's types across units; its types hang below it by
    ``INCLUDES`` edges."""

    name: str
    signal: str  # aggregate root, orm entity, shared record, table
    repository_name: str
    name_candidates: list[str] = field(default_factory=list)
    name_sources: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"DataEntity_{self.repository_name}_{self.name}"

    def to_dict(self) -> dict:
        """Convert to dictionary for graph storage."""
        return {
            "name": self.name,
            "signal": self.signal,
            "nameCandidates": list(self.name_candidates),
            "nameSources": list(self.name_sources),
            "paths": list(self.paths),
            "typeCount": len(self.paths),
            "repository_name": self.repository_name,
            "type": "DataEntity",
        }


@dataclass
class DataDomainNode:
    """An information domain: a group of data entities (and the parts and value objects of an aggregate),
    named by closed choice; its members hang below it by ``INCLUDES`` edges."""

    name: str  # The anchor's name
    kind: str  # aggregate, naming, ownership, context, single
    repository_name: str
    name_candidates: list[str] = field(default_factory=list)
    business_object: str | None = None  # The BusinessObject it realizes (None: no BusinessObject)
    exception: bool = False  # A technical-word domain admitted by evidence

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"DataDomain_{self.repository_name}_{self.name}"

    def to_dict(self) -> dict:
        """Convert to dictionary for graph storage."""
        return {
            "name": self.name,
            "kind": self.kind,
            "nameCandidates": list(self.name_candidates),
            "nameSources": ["structure"] * len(self.name_candidates),
            "businessObject": self.business_object,
            "exception": self.exception,
            "repository_name": self.repository_name,
            "type": "DataDomain",
        }


@dataclass
class LifecycleNode:
    """A business process from structure: the lifecycle of a business domain's status, its states in order; it
    ``TRIGGERS`` its first event."""

    name: str
    domain: str
    entity: str
    attribute: str
    repository_name: str
    states: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    sites: list[str] = field(default_factory=list)  # Files that set its states
    name_candidates: list[str] = field(default_factory=list)
    flow: str = ""  # The documented flow it follows ("path#heading")
    transitions: list[str] = field(default_factory=list)  # "FROM>TO": the transitions code or the flow shows

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Lifecycle_{self.repository_name}_{self.entity}_{self.attribute}"

    def to_dict(self) -> dict:
        """Convert to dictionary for graph storage."""
        return {
            "name": self.name,
            "domain": self.domain,
            "entity": self.entity,
            "attribute": self.attribute,
            "states": list(self.states),
            "events": list(self.events),
            "sites": list(self.sites),
            "nameCandidates": list(self.name_candidates),
            "nameSources": ["structure"] * len(self.name_candidates),
            "flow": self.flow,
            "transitions": list(self.transitions),
            "repository_name": self.repository_name,
            "type": "Lifecycle",
        }


@dataclass
class LifecycleEventNode:
    """A business event: a state where the lifecycle passes to another unit (or its start); it ``TRIGGERS`` the next."""

    name: str
    lifecycle: str
    state: str
    repository_name: str

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"LifecycleEvent_{self.lifecycle}_{self.state}"

    def to_dict(self) -> dict:
        """Convert to dictionary for graph storage."""
        return {"name": self.name, "lifecycle": self.lifecycle, "state": self.state, "repository_name": self.repository_name, "type": "LifecycleEvent"}


@dataclass
class RoleNode:
    """An actor or role from structure (an authorization role, a person a Web UI component's README names); it is
    ``ASSIGNED`` to the lifecycles it works on."""

    name: str
    kind: str  # role or actor
    source: str
    repository_name: str

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Role_{self.repository_name}_{self.name}"

    def to_dict(self) -> dict:
        """Convert to dictionary for graph storage."""
        return {"name": self.name, "kind": self.kind, "source": self.source, "repository_name": self.repository_name, "type": "Role"}


@dataclass
class EnvironmentNode:
    """A deployment environment (Docker Compose, Kubernetes, a cloud, a mainframe): the repository's
    primary one; it ``RUNS`` its deployed services and ``HOSTS`` the system software that runs in it."""

    name: str
    kind: str  # compose, kubernetes, cloud, mainframe
    repository_name: str
    file: str = ""  # The compose file, the folder of the manifests or of the templates
    others: list[str] = field(default_factory=list)  # The other environments, "kind file" (reported, not modelled)

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Environment_{self.repository_name}_{self.kind}"

    def to_dict(self) -> dict:
        """Convert to dictionary for graph storage."""
        return {
            "name": self.name,
            "kind": self.kind,
            "file": self.file,
            "others": list(self.others),
            "repository_name": self.repository_name,
            "type": "Environment",
        }


@dataclass
class DeploymentNode:
    """A service an environment runs; it ``DEPLOYS`` its deployable unit (none for a ready-made image)."""

    name: str
    environment: str  # The environment kind
    repository_name: str
    image: str = ""
    variables: dict[str, str] = field(default_factory=dict)  # The service's environment variables
    ports: list[int] = field(default_factory=list)

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Deployment_{self.repository_name}_{self.environment}_{self.name}"

    def to_dict(self) -> dict:
        """Convert to dictionary for graph storage."""
        return {
            "name": self.name,
            "environment": self.environment,
            "image": self.image,
            "variables": dict(self.variables),
            "ports": list(self.ports),
            "repository_name": self.repository_name,
            "type": "Deployment",
        }


@dataclass
class SoftwareNode:
    """A system software from the closed list (or a fallback image off it), with its evidence; it
    ``SERVES`` the deployable units that demonstrably use it."""

    name: str
    kind: str  # The list entry's kind (database, runtime, ...), "fallback" off the list
    listed: bool
    repository_name: str
    in_environment: bool = False
    evidence: list[str] = field(default_factory=list)

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Software_{self.repository_name}_{self.name}"

    def to_dict(self) -> dict:
        """Convert to dictionary for graph storage."""
        return {
            "name": self.name,
            "kind": self.kind,
            "listed": self.listed,
            "inEnvironment": self.in_environment,
            "evidence": list(self.evidence),
            "repository_name": self.repository_name,
            "type": "Software",
        }


# Relationship types
INCLUDES = "INCLUDES"  # For deployableunit->file (and ->program/screen type) membership
CONTAINS = "CONTAINS"  # For repository->module, repository->directory, directory->file, module->file relationships
DEPENDS_ON = "DEPENDS_ON"  # For module->module, file->file, service->service dependencies
REFERENCES = "REFERENCES"  # For file->businessconcept relationships
IMPLEMENTS = "IMPLEMENTS"  # For file->technology relationships
DECLARES = "DECLARES"  # For typedefinition->method relationships
PROVIDES = "PROVIDES"  # For typedefinition->service relationships
EXPOSES = "EXPOSES"  # For method->service relationships
USES = "USES"  # For file->externaldependency, service->externaldependency relationships
TESTS = "TESTS"  # For test->file, test->method, test->service relationships
INHERITS = "INHERITS"  # For class inheritance (typedefinition->typedefinition)
CALLS = "CALLS"  # For method parameter type dependencies (method->typedefinition)
