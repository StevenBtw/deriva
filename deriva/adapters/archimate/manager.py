"""ArchiMate Manager Service - Main interface for ArchiMate operations.

This module provides the ArchimateManager class which handles all ArchiMate model
operations using the shared grafeo connection with namespace isolation.

Usage:
    from deriva.adapters.archimate import ArchimateManager
    from deriva.adapters.archimate.models import Element, Relationship

    with ArchimateManager() as am:
        # Create elements
        element = Element(id="bo_1", name="Customer", type="BusinessObject")
        am.add_element(element)

        # Create relationships
        rel = Relationship(source_id="bo_1", target_id="bo_2", type="Association")
        am.add_relationship(rel)

        # Query elements
        elements = am.get_elements_by_type("BusinessObject")

        # Export to ArchiMate XML
        am.export_to_archimate("output.xml")
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

from deriva.adapters.grafeo import GrafeoConnection as Neo4jConnection

from .models import ArchiMateMetamodel, Element, Relationship
from .validation import ArchiMateValidator, ValidationError

logger = logging.getLogger(__name__)


class ArchimateManager:
    """Manage ArchiMate models in grafeo.

    This class provides a high-level interface for:
    - Creating and managing ArchiMate elements and relationships
    - Validating models against ArchiMate metamodel
    - Querying model structure
    - Exporting to ArchiMate XML format

    Uses the shared neo4j_manager service with "ArchiMate" namespace.
    """

    def __init__(self):
        """Initialize the ArchimateManager.

        Configuration is loaded from .env file.
        """
        load_dotenv()

        self.neo4j: Neo4jConnection | None = None
        # Try both env var names for backward compatibility
        self.namespace = os.getenv("ARCHIMATE_NAMESPACE") or os.getenv(
            "NEO4J_NAMESPACE_ARCHIMATE", "Model"
        )
        self.metamodel = ArchiMateMetamodel()
        self.validator = ArchiMateValidator(
            strict_mode=os.getenv("ARCHIMATE_VALIDATION_STRICT_MODE", "false").lower()
            == "true"
        )

        logger.info(f"Initialized ArchimateManager with namespace: {self.namespace}")

    def connect(self) -> None:
        """Establish connection to Neo4j via neo4j_manager."""
        if self.neo4j is not None:
            logger.warning("Connection already established")
            return

        try:
            # Create Neo4j connection with namespace
            self.neo4j = Neo4jConnection(namespace=self.namespace)
            self.neo4j.connect()

            logger.info(
                f"Successfully connected to Neo4j with namespace '{self.namespace}'"
            )

        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise ConnectionError(f"Could not connect to Neo4j: {e}")

    def disconnect(self) -> None:
        """Close the Neo4j connection."""
        if self.neo4j is not None:
            self.neo4j.disconnect()
            self.neo4j = None
            logger.info("Disconnected from Neo4j")

    def __enter__(self) -> ArchimateManager:
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(
        self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any
    ) -> None:
        """Context manager exit."""
        self.disconnect()

    def add_element(self, element: Element, validate: bool = True) -> str:
        """Add an ArchiMate element to the graph.

        Args:
            element: Element to add
            validate: If True, validate element before adding

        Returns:
            Element identifier

        Raises:
            ValidationError: If validation fails
            RuntimeError: If not connected to Neo4j
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        # Validate element
        if validate:
            is_valid, errors = self.validator.validate_element(element)
            if not is_valid:
                raise ValidationError(f"Element validation failed: {errors}")

        try:
            # Create Cypher query to add element node
            # Use two separate labels: namespace (Model) + element_type (TechnologyService)
            # This allows queries like MATCH (e:TechnologyService) to work
            # while still having namespace isolation via the Model label

            # Convert properties to JSON string (Neo4j can't store empty dicts)
            properties_json = (
                json.dumps(element.properties) if element.properties else None
            )

            # Extract source_identifier from properties for graph-based relationship derivation
            # The graph_relationships refine step needs this to link elements to source graph nodes
            source_identifier = (
                element.properties.get("source") if element.properties else None
            )

            query = f"""
                MERGE (e:`{self.namespace}`:`{element.element_type}` {{identifier: $identifier}})
                SET e.name = $name,
                    e.documentation = $documentation,
                    e.properties_json = $properties_json,
                    e.enabled = $enabled,
                    e.source_identifier = $source_identifier
                RETURN e.identifier as identifier
            """

            result = self.neo4j.execute_write(
                query,
                {
                    "identifier": element.identifier,
                    "name": element.name,
                    "documentation": element.documentation,
                    "properties_json": properties_json,
                    "enabled": element.enabled,
                    "source_identifier": source_identifier,
                },
            )

            if result:
                logger.debug(
                    f"Added element: {element.identifier} ({element.element_type})"
                )
                return result[0]["identifier"]
            else:
                raise RuntimeError("Failed to add element")

        except Exception as e:
            logger.error(f"Failed to add element {element.identifier}: {e}")
            raise

    def add_relationship(
        self, relationship: Relationship, validate: bool = True
    ) -> str:
        """Add an ArchiMate relationship to the graph.

        Args:
            relationship: Relationship to add
            validate: If True, validate relationship before adding

        Returns:
            Relationship identifier

        Raises:
            ValidationError: If validation fails
            RuntimeError: If not connected to Neo4j
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        # Validate relationship
        if validate:
            is_valid, errors = self.validator.validate_relationship(relationship)
            if not is_valid:
                raise ValidationError(f"Relationship validation failed: {errors}")

        try:
            # Create Cypher query to add relationship
            # Use namespaced relationship type (e.g., Model:Realization, Model:Serving)
            # This is consistent with Graph namespace which uses Graph:CONTAINS, Graph:CALLS, etc.
            # Nodes are matched by having the namespace label (Model)

            # Convert properties to JSON string
            properties_json = (
                json.dumps(relationship.properties) if relationship.properties else None
            )

            # Get namespaced relationship type (e.g., "Realization" -> "Model:Realization")
            rel_label = self.neo4j.get_label(relationship.relationship_type)

            query = f"""
                MATCH (source:`{self.namespace}` {{identifier: $source}})
                MATCH (target:`{self.namespace}` {{identifier: $target}})
                CREATE (source)-[r:`{rel_label}` {{
                    identifier: $identifier,
                    name: $name,
                    documentation: $documentation,
                    properties_json: $properties_json
                }}]->(target)
                RETURN r.identifier as identifier
            """

            result = self.neo4j.execute_write(
                query,
                {
                    "source": relationship.source,
                    "target": relationship.target,
                    "identifier": relationship.identifier,
                    "name": relationship.name,
                    "documentation": relationship.documentation,
                    "properties_json": properties_json,
                },
            )

            if result:
                logger.debug(
                    f"Added relationship: {relationship.source} -{relationship.relationship_type}-> {relationship.target}"
                )
                return result[0]["identifier"]
            else:
                raise RuntimeError(
                    f"Failed to add relationship. Make sure elements {relationship.source} and {relationship.target} exist."
                )

        except Exception as e:
            logger.error(f"Failed to add relationship {relationship.identifier}: {e}")
            raise

    def get_element(self, identifier: str) -> Element | None:
        """Get an element by identifier.

        Args:
            identifier: Element identifier

        Returns:
            Element or None if not found
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            # Find element by identifier - nodes have namespace label (Model) + type label
            query = f"""
                MATCH (e:`{self.namespace}` {{identifier: $identifier}})
                RETURN e.identifier as identifier,
                       e.name as name,
                       [lbl IN labels(e) WHERE lbl <> '{self.namespace}'][0] as element_type,
                       e.documentation as documentation,
                       e.properties_json as properties_json,
                       e.enabled as enabled
            """

            result = self.neo4j.execute_read(query, {"identifier": identifier})

            if result:
                data = result[0]
                # Element type is the non-namespace label
                element_type = (
                    data["element_type"] if data.get("element_type") else "Unknown"
                )
                # Parse JSON properties back to dict
                properties = (
                    json.loads(data["properties_json"])
                    if data.get("properties_json")
                    else {}
                )
                return Element(
                    name=data["name"],
                    element_type=element_type,
                    identifier=data["identifier"],
                    documentation=data.get("documentation"),
                    properties=properties,
                    enabled=data.get("enabled", True),
                )
            return None

        except Exception as e:
            logger.error(f"Failed to get element {identifier}: {e}")
            raise

    def get_elements(
        self, element_type: str | None = None, enabled_only: bool = False
    ) -> list[Element]:
        """Get all elements, optionally filtered by type and enabled status.

        Args:
            element_type: Optional element type filter
            enabled_only: If True, only return enabled elements (for export)

        Returns:
            List of elements
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            enabled_filter = "AND e.enabled = true" if enabled_only else ""

            if element_type:
                # Get elements by specific type label (namespace + type)
                query = f"""
                    MATCH (e:`{self.namespace}`:`{element_type}`)
                    WHERE true {enabled_filter}
                    RETURN e.identifier as identifier,
                           e.name as name,
                           e.documentation as documentation,
                           e.properties_json as properties_json,
                           e.enabled as enabled
                """
                result = self.neo4j.execute_read(query)
                # All elements have same type
                elements = []
                for data in result:
                    properties = (
                        json.loads(data["properties_json"])
                        if data.get("properties_json")
                        else {}
                    )
                    elements.append(
                        Element(
                            name=data["name"],
                            element_type=element_type,
                            identifier=data["identifier"],
                            documentation=data.get("documentation"),
                            properties=properties,
                            enabled=data.get("enabled", True),
                        )
                    )
            else:
                # Get all elements - match namespace label and extract type from other labels
                query = f"""
                    MATCH (e:`{self.namespace}`)
                    WHERE true {enabled_filter}
                    RETURN e.identifier as identifier,
                           e.name as name,
                           [lbl IN labels(e) WHERE lbl <> '{self.namespace}'][0] as element_type,
                           e.documentation as documentation,
                           e.properties_json as properties_json,
                           e.enabled as enabled
                """
                result = self.neo4j.execute_read(query)
                elements = []
                for data in result:
                    # Element type is the non-namespace label
                    etype = data.get("element_type") or "Unknown"
                    properties = (
                        json.loads(data["properties_json"])
                        if data.get("properties_json")
                        else {}
                    )
                    elements.append(
                        Element(
                            name=data["name"],
                            element_type=etype,
                            identifier=data["identifier"],
                            documentation=data.get("documentation"),
                            properties=properties,
                            enabled=data.get("enabled", True),
                        )
                    )

            return elements

        except Exception as e:
            logger.error(f"Failed to get elements: {e}")
            raise

    def get_relationships(
        self, source_id: str | None = None, target_id: str | None = None
    ) -> list[Relationship]:
        """Get relationships, optionally filtered by source and/or target.

        Args:
            source_id: Optional source element identifier
            target_id: Optional target element identifier

        Returns:
            List of relationships
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            ns = self.namespace

            # Build query - match relationships between Model namespace nodes
            # Relationship types are now plain (e.g., Realization, Serving)
            if source_id and target_id:
                query = f"""
                    MATCH (source:`{ns}` {{identifier: $source_id}})-[r]->(target:`{ns}` {{identifier: $target_id}})
                    RETURN source.identifier as source,
                           target.identifier as target,
                           r.identifier as identifier,
                           type(r) as rel_type,
                           r.name as name,
                           r.documentation as documentation,
                           r.properties_json as properties_json
                """
                params = {"source_id": source_id, "target_id": target_id}
            elif source_id:
                query = f"""
                    MATCH (source:`{ns}` {{identifier: $source_id}})-[r]->(target:`{ns}`)
                    RETURN source.identifier as source,
                           target.identifier as target,
                           r.identifier as identifier,
                           type(r) as rel_type,
                           r.name as name,
                           r.documentation as documentation,
                           r.properties_json as properties_json
                """
                params = {"source_id": source_id}
            elif target_id:
                query = f"""
                    MATCH (source:`{ns}`)-[r]->(target:`{ns}` {{identifier: $target_id}})
                    RETURN source.identifier as source,
                           target.identifier as target,
                           r.identifier as identifier,
                           type(r) as rel_type,
                           r.name as name,
                           r.documentation as documentation,
                           r.properties_json as properties_json
                """
                params = {"target_id": target_id}
            else:
                query = f"""
                    MATCH (source:`{ns}`)-[r]->(target:`{ns}`)
                    RETURN source.identifier as source,
                           target.identifier as target,
                           r.identifier as identifier,
                           type(r) as rel_type,
                           r.name as name,
                           r.documentation as documentation,
                           r.properties_json as properties_json
                """
                params = {}

            result = self.neo4j.execute_read(query, params)

            relationships = []
            for data in result:
                # Relationship type is stored with namespace prefix (e.g., "Model:Realization")
                # Strip the namespace prefix for the model object
                rel_type = data.get("rel_type") or "Unknown"
                if rel_type.startswith(f"{self.namespace}:"):
                    rel_type = rel_type[len(self.namespace) + 1 :]
                # Parse JSON properties back to dict
                properties = (
                    json.loads(data["properties_json"])
                    if data.get("properties_json")
                    else {}
                )
                relationships.append(
                    Relationship(
                        source=data["source"],
                        target=data["target"],
                        relationship_type=rel_type,
                        identifier=data["identifier"],
                        name=data.get("name"),
                        documentation=data.get("documentation"),
                        properties=properties,
                    )
                )

            return relationships

        except Exception as e:
            logger.error(f"Failed to get relationships: {e}")
            raise

    def clear_model(self) -> None:
        """Clear all ArchiMate elements and relationships from Neo4j."""
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            self.neo4j.clear_namespace()
            logger.info(f"Cleared all ArchiMate data from namespace '{self.namespace}'")

        except Exception as e:
            logger.error(f"Failed to clear model: {e}")
            raise

    def query(
        self, cypher_query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a custom Cypher query.

        Args:
            cypher_query: Cypher query string
            params: Optional query parameters

        Returns:
            Query results as list of dictionaries
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            return self.neo4j.execute(cypher_query, params)

        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise

    def disable_element(self, identifier: str, reason: str | None = None) -> bool:
        """Disable an element (soft delete for refine phase).

        Args:
            identifier: Element identifier to disable
            reason: Optional reason for disabling (stored in properties)

        Returns:
            True if element was disabled, False if not found
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            query = f"""
                MATCH (e:`{self.namespace}` {{identifier: $identifier}})
                SET e.enabled = false,
                    e.disabled_reason = $reason
                RETURN e.identifier as identifier
            """
            result = self.neo4j.execute_write(
                query, {"identifier": identifier, "reason": reason}
            )

            if result:
                logger.debug(f"Disabled element: {identifier} (reason: {reason})")
                return True
            return False

        except Exception as e:
            logger.error(f"Failed to disable element {identifier}: {e}")
            raise

    def disable_elements(
        self, identifiers: list[str], reason: str | None = None
    ) -> int:
        """Disable multiple elements (batch soft delete for refine phase).

        Args:
            identifiers: List of element identifiers to disable
            reason: Optional reason for disabling

        Returns:
            Number of elements disabled
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        if not identifiers:
            return 0

        try:
            query = f"""
                MATCH (e:`{self.namespace}`)
                WHERE e.identifier IN $identifiers
                SET e.enabled = false,
                    e.disabled_reason = $reason
                RETURN count(e) as count
            """
            result = self.neo4j.execute_write(
                query, {"identifiers": identifiers, "reason": reason}
            )

            count = result[0]["count"] if result else 0
            logger.info(f"Disabled {count} elements (reason: {reason})")
            return count

        except Exception as e:
            logger.error(f"Failed to disable elements: {e}")
            raise

    def delete_relationship(self, identifier: str) -> bool:
        """Delete a relationship by identifier.

        Args:
            identifier: Relationship identifier to delete

        Returns:
            True if relationship was deleted, False if not found
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            # Match relationships between Model namespace nodes
            query = f"""
                MATCH (:`{self.namespace}`)-[r]->(:`{self.namespace}`)
                WHERE r.identifier = $identifier
                DELETE r
                RETURN count(r) as count
            """
            result = self.neo4j.execute_write(query, {"identifier": identifier})

            if result and result[0]["count"] > 0:
                logger.debug(f"Deleted relationship: {identifier}")
                return True
            return False

        except Exception as e:
            logger.error(f"Failed to delete relationship {identifier}: {e}")
            raise

    def delete_relationships(self, identifiers: list[str]) -> int:
        """Delete multiple relationships by identifier.

        Args:
            identifiers: List of relationship identifiers to delete

        Returns:
            Number of relationships deleted
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        if not identifiers:
            return 0

        try:
            # Match relationships between Model namespace nodes
            query = f"""
                MATCH (:`{self.namespace}`)-[r]->(:`{self.namespace}`)
                WHERE r.identifier IN $identifiers
                DELETE r
                RETURN count(r) as count
            """
            result = self.neo4j.execute_write(query, {"identifiers": identifiers})

            count = result[0]["count"] if result else 0
            logger.info(f"Deleted {count} relationships")
            return count

        except Exception as e:
            logger.error(f"Failed to delete relationships: {e}")
            raise
