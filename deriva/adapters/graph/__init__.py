"""Graph Manager - Grafeo-based graph database for repository structure.

This module provides a property graph database using grafeo (embedded)
to store and query repository structure, dependencies, and relationships.
"""

from __future__ import annotations

from .cache import QueryCache
from .manager import STORAGE_FORMAT, SYSTEM_PROPERTIES, GraphManager
from .models import (
    CONTAINS,
    DECLARES,
    DEPENDS_ON,
    EXPOSES,
    IMPLEMENTS,
    INCLUDES,
    PROVIDES,
    REFERENCES,
    TESTS,
    USES,
    BusinessConceptNode,
    DataDomainNode,
    DataEntityNode,
    DeployableUnitNode,
    DeploymentNode,
    DirectoryNode,
    EnvironmentNode,
    ExternalDependencyNode,
    FileNode,
    LifecycleEventNode,
    LifecycleNode,
    MethodNode,
    ModuleNode,
    RepositoryNode,
    RoleNode,
    ServiceNode,
    SoftwareNode,
    TechnologyNode,
    TestNode,
    TypeDefinitionNode,
)

__version__ = "1.0.0"

__all__ = [
    # Manager
    "GraphManager",
    "STORAGE_FORMAT",
    "SYSTEM_PROPERTIES",
    # Cache
    "QueryCache",
    # Node types
    "RepositoryNode",
    "DirectoryNode",
    "ModuleNode",
    "FileNode",
    "LifecycleEventNode",
    "LifecycleNode",
    "RoleNode",
    "BusinessConceptNode",
    "TechnologyNode",
    "TypeDefinitionNode",
    "MethodNode",
    "TestNode",
    "ServiceNode",
    "ExternalDependencyNode",
    "DataDomainNode",
    "DataEntityNode",
    "DeploymentNode",
    "EnvironmentNode",
    "SoftwareNode",
    "DeployableUnitNode",
    # Relationship types
    "CONTAINS",
    "INCLUDES",
    "DEPENDS_ON",
    "REFERENCES",
    "IMPLEMENTS",
    "DECLARES",
    "PROVIDES",
    "EXPOSES",
    "USES",
    "TESTS",
]
