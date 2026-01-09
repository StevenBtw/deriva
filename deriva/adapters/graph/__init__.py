"""Graph Manager - Neo4j-based graph database for repository structure.

This module provides a property graph database using Neo4j
to store and query repository structure, dependencies, and relationships.
"""

from __future__ import annotations

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
from .manager import GraphManager

__version__ = "1.0.0"

__all__ = [
    "GraphManager",
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
