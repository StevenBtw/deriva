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
    PROVIDES,
    REFERENCES,
    TESTS,
    USES,
    BusinessConceptNode,
    DirectoryNode,
    ExternalDependencyNode,
    FileNode,
    MethodNode,
    ModuleNode,
    RepositoryNode,
    ServiceNode,
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
    "BusinessConceptNode",
    "TechnologyNode",
    "TypeDefinitionNode",
    "MethodNode",
    "TestNode",
    "ServiceNode",
    "ExternalDependencyNode",
    # Relationship types
    "CONTAINS",
    "DEPENDS_ON",
    "REFERENCES",
    "IMPLEMENTS",
    "DECLARES",
    "PROVIDES",
    "EXPOSES",
    "USES",
    "TESTS",
]
