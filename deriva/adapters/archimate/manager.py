"""ArchiMate Manager Service - Main interface for ArchiMate operations using Neo4j.

This module provides the ArchimateManager class which handles all ArchiMate model
operations using the shared neo4j_manager service with namespace isolation.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

from deriva.adapters.neo4j import Neo4jConnection

from .models import ArchiMateMetamodel, Element, Relationship
from .validation import ArchiMateValidator, ValidationError

logger = logging.getLogger(__name__)


class ArchimateManager:
    """Manage ArchiMate models in Neo4j.

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
            # Use element_type as the label (e.g., Model:ApplicationComponent)
            # Note: Convert empty dict to null for Neo4j compatibility
            label = self.neo4j.get_label(element.element_type)

            # Convert properties to JSON string (Neo4j can't store empty dicts)
            properties_json = (
                json.dumps(element.properties) if element.properties else None
            )

            query = f"""
                MERGE (e:`{label}` {{identifier: $identifier}})
                SET e.name = $name,
                    e.documentation = $documentation,
                    e.properties_json = $properties_json
                RETURN e.identifier as identifier
            """

            result = self.neo4j.execute_write(
                query,
                {
                    "identifier": element.identifier,
                    "name": element.name,
                    "documentation": element.documentation,
                    "properties_json": properties_json,
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
            # Use relationship_type as the label (e.g., Model:Serving)
            rel_label = self.neo4j.get_label(relationship.relationship_type)

            # Convert properties to JSON string
            properties_json = (
                json.dumps(relationship.properties) if relationship.properties else None
            )

            query = f"""
                MATCH (source {{identifier: $source}})
                WHERE any(lbl IN labels(source) WHERE lbl STARTS WITH '{self.namespace}:')
                MATCH (target {{identifier: $target}})
                WHERE any(lbl IN labels(target) WHERE lbl STARTS WITH '{self.namespace}:')
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
            # Find element by identifier across all type-specific labels
            query = f"""
                MATCH (e {{identifier: $identifier}})
                WHERE any(lbl IN labels(e) WHERE lbl STARTS WITH '{self.namespace}:')
                RETURN e.identifier as identifier,
                       e.name as name,
                       [lbl IN labels(e) WHERE lbl STARTS WITH '{self.namespace}:'][0] as label,
                       e.documentation as documentation,
                       e.properties_json as properties_json
            """

            result = self.neo4j.execute_read(query, {"identifier": identifier})

            if result:
                data = result[0]
                # Extract element type from label (e.g., "Model:ApplicationComponent" -> "ApplicationComponent")
                label = data["label"]
                element_type = label.split(":")[-1] if label else "Unknown"
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
                )
            return None

        except Exception as e:
            logger.error(f"Failed to get element {identifier}: {e}")
            raise

    def get_elements(self, element_type: str | None = None) -> list[Element]:
        """Get all elements, optionally filtered by type.

        Args:
            element_type: Optional element type filter

        Returns:
            List of elements
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            if element_type:
                # Get elements by specific type label
                label = self.neo4j.get_label(element_type)
                query = f"""
                    MATCH (e:`{label}`)
                    RETURN e.identifier as identifier,
                           e.name as name,
                           e.documentation as documentation,
                           e.properties_json as properties_json
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
                        )
                    )
            else:
                # Get all elements across all type labels
                query = f"""
                    MATCH (e)
                    WHERE any(lbl IN labels(e) WHERE lbl STARTS WITH '{self.namespace}:' AND lbl <> '{self.namespace}:Relationship')
                    RETURN e.identifier as identifier,
                           e.name as name,
                           [lbl IN labels(e) WHERE lbl STARTS WITH '{self.namespace}:'][0] as label,
                           e.documentation as documentation,
                           e.properties_json as properties_json
                """
                result = self.neo4j.execute_read(query)
                elements = []
                for data in result:
                    # Extract element type from label
                    label = data["label"]
                    etype = label.split(":")[-1] if label else "Unknown"
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

            # Build query - match any relationship type in namespace
            # Extract relationship type from type(r)
            if source_id and target_id:
                query = f"""
                    MATCH (source {{identifier: $source_id}})-[r]->(target {{identifier: $target_id}})
                    WHERE any(lbl IN labels(source) WHERE lbl STARTS WITH '{ns}:')
                    AND any(lbl IN labels(target) WHERE lbl STARTS WITH '{ns}:')
                    AND type(r) STARTS WITH '{ns}:'
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
                    MATCH (source {{identifier: $source_id}})-[r]->(target)
                    WHERE any(lbl IN labels(source) WHERE lbl STARTS WITH '{ns}:')
                    AND any(lbl IN labels(target) WHERE lbl STARTS WITH '{ns}:')
                    AND type(r) STARTS WITH '{ns}:'
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
                    MATCH (source)-[r]->(target {{identifier: $target_id}})
                    WHERE any(lbl IN labels(source) WHERE lbl STARTS WITH '{ns}:')
                    AND any(lbl IN labels(target) WHERE lbl STARTS WITH '{ns}:')
                    AND type(r) STARTS WITH '{ns}:'
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
                    MATCH (source)-[r]->(target)
                    WHERE any(lbl IN labels(source) WHERE lbl STARTS WITH '{ns}:')
                    AND any(lbl IN labels(target) WHERE lbl STARTS WITH '{ns}:')
                    AND type(r) STARTS WITH '{ns}:'
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
                # Extract relationship type from label (e.g., "Model:Serving" -> "Serving")
                rel_type = (
                    data["rel_type"].split(":")[-1]
                    if data.get("rel_type")
                    else "Unknown"
                )
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
