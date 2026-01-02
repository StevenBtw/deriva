"""ArchiMate Manager - Create, validate, and export ArchiMate models using Memgraph.

This package provides comprehensive ArchiMate modeling capabilities:
- Create and manage ArchiMate elements and relationships
- Validate models against ArchiMate metamodel
- Store models in Memgraph graph database
- Export to ArchiMate XML format (compatible with Archi tool)

Example:
    >>> from archimate_manager import ArchimateManager, Element, Relationship
    >>>
    >>> with ArchimateManager() as am:
    ...     # Create elements
    ...     e1 = Element("Auth Module", "ApplicationComponent")
    ...     e2 = Element("API Module", "ApplicationComponent")
    ...     am.add_element(e1)
    ...     am.add_element(e2)
    ...
    ...     # Create relationship
    ...     rel = Relationship(e1.identifier, e2.identifier, "Composition")
    ...     am.add_relationship(rel)
    ...
    ...     # Export to XML
    ...     from archimate_manager.xml_export import ArchiMateXMLExporter
    ...     exporter = ArchiMateXMLExporter()
    ...     elements = am.get_elements()
    ...     relationships = am.get_relationships()
    ...     exporter.export(elements, relationships, "model.xml")
"""

from __future__ import annotations

from .models import ArchiMateMetamodel, Element, Relationship
from .manager import ArchimateManager
from .validation import ArchiMateValidator, ValidationError
from .xml_export import ArchiMateXMLExporter

__all__ = [
    "Element",
    "Relationship",
    "ArchimateManager",
    "ArchiMateMetamodel",
    "ArchiMateValidator",
    "ValidationError",
    "ArchiMateXMLExporter",
]

__version__ = "2.0.0"
