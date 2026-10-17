"""ArchiMate XML Export - Export ArchiMate models to XML format.

This module provides functionality to export ArchiMate models to the
Open Group ArchiMate Exchange Format (XML), compatible with Archi tool.

Reference: https://www.opengroup.org/archimate-forum/archimate-exchange-format
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

from lxml import etree

from .models import Element, Relationship
from .views import View


class ArchiMateXMLExporter:
    """Export ArchiMate models to XML format."""

    # ArchiMate 3.0 namespace
    ARCHIMATE_NS = "http://www.opengroup.org/xsd/archimate/3.0/"
    DC_NS = "http://purl.org/dc/elements/1.1/"
    XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
    XML_NS = "http://www.w3.org/XML/1998/namespace"

    NSMAP = {None: ARCHIMATE_NS, "xsi": XSI_NS, "dc": DC_NS}

    SCHEMA_LOCATION = "http://www.opengroup.org/xsd/archimate/3.0/ http://www.opengroup.org/xsd/archimate/3.1/archimate3_Model.xsd"

    def __init__(self, pretty_print: bool = True, encoding: str = "UTF-8"):
        """
        Initialize XML exporter.

        Args:
            pretty_print: If True, format XML with indentation
            encoding: XML encoding (default UTF-8)
        """
        self.pretty_print = pretty_print
        self.encoding = encoding

    def export(
        self,
        elements: list[Element],
        relationships: list[Relationship],
        output_path: str,
        model_name: str = "ArchiMate Model",
        model_id: str = "model-001",
        properties: Mapping[str, Mapping[str, str]] | None = None,
        views: Sequence[View] | None = None,
        relationship_properties: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        """
        Export ArchiMate model to XML file.

        Args:
            elements: List of ArchiMate elements
            relationships: List of ArchiMate relationships
            output_path: Path to output XML file
            model_name: Name of the model
            model_id: Unique identifier for the model
            properties: Exported properties per element id (e.g. ``level``), declared as propertyDefinitions
            views: Diagrams to export (see ``views.build_views``)
            relationship_properties: Exported properties per relationship id, declared with the element ones
        """
        # Create root model element
        root = etree.Element(
            "model",
            nsmap=self.NSMAP,
            attrib={
                "identifier": model_id,
                f"{{{self.XSI_NS}}}schemaLocation": self.SCHEMA_LOCATION,
            },
        )

        # Add model name with xml:lang attribute
        name_elem = etree.SubElement(root, "name")
        name_elem.set(f"{{{self.XML_NS}}}lang", "en")
        name_elem.text = model_name

        # Add metadata
        self._add_metadata(root)

        properties = properties or {}
        relationship_properties = relationship_properties or {}
        keys = sorted({key for values in [*properties.values(), *relationship_properties.values()] for key, value in values.items() if value})
        definition_of = {key: f"propid-{key}" for key in keys}

        # Add elements section
        if elements:
            elements_section = etree.SubElement(root, "elements")
            for element in elements:
                self._add_element(elements_section, element, properties.get(element.identifier, {}), definition_of)

        # Add relationships section
        if relationships:
            rels_section = etree.SubElement(root, "relationships")
            for relationship in relationships:
                self._add_relationship(rels_section, relationship, relationship_properties.get(relationship.identifier, {}), definition_of)

        # The exchange format's order: elements, relationships, organizations, propertyDefinitions, views
        if keys:
            definitions = etree.SubElement(root, "propertyDefinitions")
            for key in keys:
                definition = etree.SubElement(definitions, "propertyDefinition", attrib={"identifier": definition_of[key], "type": "string"})
                etree.SubElement(definition, "name").text = key
        if views:
            self._add_views(root, views)

        # Write to file
        tree = etree.ElementTree(root)
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        tree.write(
            str(output_file),
            pretty_print=self.pretty_print,
            xml_declaration=True,
            encoding=self.encoding,
        )

    def _add_metadata(self, root: etree.Element) -> None:
        """Add metadata to model root."""
        metadata = etree.SubElement(root, "metadata")

        # Add schema info
        schema = etree.SubElement(metadata, "schema")
        schema.text = "Dublin Core"

        schemaversion = etree.SubElement(metadata, "schemaversion")
        schemaversion.text = "1.1"

        # Add Dublin Core elements
        title = etree.SubElement(metadata, f"{{{self.DC_NS}}}title")
        title.text = "Deriva Generated Model"

        creator = etree.SubElement(metadata, f"{{{self.DC_NS}}}creator")
        creator.text = "Deriva"

        date = etree.SubElement(metadata, f"{{{self.DC_NS}}}date")
        date.text = datetime.now().strftime("%Y-%m-%d")

        description = etree.SubElement(metadata, f"{{{self.DC_NS}}}description")
        description.text = "ArchiMate model generated by Deriva from source code analysis"

    def _add_element(
        self,
        parent: etree.Element,
        element: Element,
        properties: Mapping[str, str] | None = None,
        definition_of: Mapping[str, str] | None = None,
    ) -> None:
        """
        Add an element to the XML tree.

        Args:
            parent: Parent XML element
            element: ArchiMate element to add
            properties: The element's exported properties (key -> value)
            definition_of: propertyDefinition identifier per key
        """
        elem = etree.SubElement(
            parent,
            "element",
            attrib={
                "identifier": element.identifier,
                f"{{{self.XSI_NS}}}type": element.element_type,
            },
        )

        # Add name with xml:lang
        name_elem = etree.SubElement(elem, "name")
        name_elem.set(f"{{{self.XML_NS}}}lang", "en")
        name_elem.text = element.name

        # Add documentation if present
        if element.documentation:
            doc_elem = etree.SubElement(elem, "documentation")
            doc_elem.set(f"{{{self.XML_NS}}}lang", "en")
            doc_elem.text = element.documentation

        # Only the properties passed in are exported (each needs a model-level propertyDefinition);
        # internal metadata (source, derived_at) on the element is omitted.
        shown = sorted((key, value) for key, value in (properties or {}).items() if value and key in (definition_of or {}))
        if shown and definition_of:
            props = etree.SubElement(elem, "properties")
            for key, value in shown:
                prop = etree.SubElement(props, "property", attrib={"propertyDefinitionRef": definition_of[key]})
                value_elem = etree.SubElement(prop, "value")
                value_elem.set(f"{{{self.XML_NS}}}lang", "en")
                value_elem.text = value

    def _add_views(self, root: etree.Element, views: Sequence[View]) -> None:
        """Add the diagrams: element nodes with their bounds, relationship connections between them."""
        diagrams = etree.SubElement(etree.SubElement(root, "views"), "diagrams")
        for view in views:
            diagram = etree.SubElement(
                diagrams,
                "view",
                attrib={"identifier": view.identifier, f"{{{self.XSI_NS}}}type": "Diagram", "viewpoint": view.viewpoint},
            )
            name_elem = etree.SubElement(diagram, "name")
            name_elem.set(f"{{{self.XML_NS}}}lang", "en")
            name_elem.text = view.name
            for node in view.nodes:
                etree.SubElement(
                    diagram,
                    "node",
                    attrib={
                        "identifier": node.identifier,
                        "elementRef": node.element,
                        f"{{{self.XSI_NS}}}type": "Element",
                        "x": str(node.x),
                        "y": str(node.y),
                        "w": str(node.w),
                        "h": str(node.h),
                    },
                )
            for connection in view.connections:
                etree.SubElement(
                    diagram,
                    "connection",
                    attrib={
                        "identifier": connection.identifier,
                        "relationshipRef": connection.relationship,
                        f"{{{self.XSI_NS}}}type": "Relationship",
                        "source": connection.source,
                        "target": connection.target,
                    },
                )

    def _add_relationship(
        self,
        parent: etree.Element,
        relationship: Relationship,
        properties: Mapping[str, str] | None = None,
        definition_of: Mapping[str, str] | None = None,
    ) -> None:
        """
        Add a relationship to the XML tree.

        Args:
            parent: Parent XML element
            relationship: ArchiMate relationship to add
            properties: The relationship's exported properties (key -> value)
            definition_of: propertyDefinition identifier per key
        """
        rel = etree.SubElement(
            parent,
            "relationship",
            attrib={
                "identifier": relationship.identifier,
                f"{{{self.XSI_NS}}}type": relationship.relationship_type,
                "source": relationship.source,
                "target": relationship.target,
            },
        )

        # Add name if present
        if relationship.name:
            name_elem = etree.SubElement(rel, "name")
            name_elem.text = relationship.name

        # Add documentation if present
        if relationship.documentation:
            doc_elem = etree.SubElement(rel, "documentation")
            doc_elem.text = relationship.documentation

        # Only the properties passed in are exported (each needs a model-level propertyDefinition), after name and documentation
        shown = sorted((key, value) for key, value in (properties or {}).items() if value and key in (definition_of or {}))
        if shown and definition_of:
            props = etree.SubElement(rel, "properties")
            for key, value in shown:
                prop = etree.SubElement(props, "property", attrib={"propertyDefinitionRef": definition_of[key]})
                value_elem = etree.SubElement(prop, "value")
                value_elem.set(f"{{{self.XML_NS}}}lang", "en")
                value_elem.text = str(value)

    def export_to_string(
        self,
        elements: list[Element],
        relationships: list[Relationship],
        model_name: str = "ArchiMate Model",
        model_id: str = "model-001",
    ) -> str:
        """
        Export ArchiMate model to XML string.

        Args:
            elements: List of ArchiMate elements
            relationships: List of ArchiMate relationships
            model_name: Name of the model
            model_id: Unique identifier for the model

        Returns:
            XML string
        """
        # Create root model element
        root = etree.Element(
            "model",
            nsmap=self.NSMAP,
            attrib={"identifier": model_id, "version": "5.0.0"},
        )

        # Add model name
        name_elem = etree.SubElement(root, "name")
        name_elem.text = model_name

        # Add metadata
        self._add_metadata(root)

        # Add elements section
        if elements:
            elements_section = etree.SubElement(root, "elements")
            for element in elements:
                self._add_element(elements_section, element)

        # Add relationships section
        if relationships:
            rels_section = etree.SubElement(root, "relationships")
            for relationship in relationships:
                self._add_relationship(rels_section, relationship)

        # Return as string
        return etree.tostring(
            root,
            pretty_print=self.pretty_print,
            xml_declaration=True,
            encoding=self.encoding,
        ).decode(self.encoding)
