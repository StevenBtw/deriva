"""Graph Manager - Main interface for graph operations using Neo4j.

This module provides the GraphManager class which handles all graph database
operations using the shared Neo4j connection with namespace isolation.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

# Import Neo4j connection from the neo4j manager package
from deriva.adapters.neo4j import Neo4jConnection

from .models import (
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

# Type alias for all supported node types
GraphNode = (
    RepositoryNode
    | DirectoryNode
    | ModuleNode
    | FileNode
    | BusinessConceptNode
    | TechnologyNode
    | TypeDefinitionNode
    | MethodNode
    | TestNode
    | ServiceNode
    | ExternalDependencyNode
)

logger = logging.getLogger(__name__)


class GraphManager:
    """Manages graph database operations using Neo4j.

    This class provides a high-level interface for:
    - Creating and managing property graphs
    - Adding nodes and edges
    - Querying graph structure
    - Traversing relationships

    Uses the shared neo4j_manager service with "Graph" namespace.
    """

    def __init__(self):
        """Initialize the GraphManager using .env configuration."""
        load_dotenv()
        self.neo4j: Neo4jConnection | None = None
        self.namespace = os.getenv("NEO4J_GRAPH_NAMESPACE", "Graph")

        logger.info(f"Initializing GraphManager with namespace: {self.namespace}")

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

    def __enter__(self) -> GraphManager:
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(
        self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any
    ) -> None:
        """Context manager exit."""
        self.disconnect()

    def add_node(self, node: GraphNode, node_id: str | None = None) -> str:
        """Add a node to the graph.

        Args:
            node: Node object to add
            node_id: Optional custom node ID, auto-generated via node.generate_id() if not provided

        Returns:
            The node ID
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        # Generate node ID if not provided - use node's generate_id() method
        if node_id is None:
            node_id = node.generate_id()

        # Get node label (type)
        node_label = node.__class__.__name__.replace("Node", "")

        # Convert node to properties dict
        properties = node.to_dict()

        # Convert properties to JSON string for full data backup
        properties_json = json.dumps(properties) if properties else None

        # Extract scalar properties to store directly on node
        # Neo4j can store: strings, numbers, booleans, and arrays of these
        flat_props = {}
        for key, value in properties.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                flat_props[key] = value
            elif isinstance(value, list) and all(
                isinstance(v, (str, int, float, bool)) for v in value
            ):
                flat_props[key] = value

        # Add active flag for prep phase filtering (default true)
        flat_props["active"] = True

        try:
            # Use namespace-aware label
            label = self.neo4j.get_label(node_label)

            # Build SET clause for flat properties
            set_clauses = ["n.label = $label", "n.properties_json = $properties_json"]
            params = {
                "id": node_id,
                "label": node_label,
                "properties_json": properties_json,
            }

            for key, value in flat_props.items():
                param_name = f"prop_{key}"
                set_clauses.append(f"n.{key} = ${param_name}")
                params[param_name] = value

            query = f"""
                MERGE (n:`{label}` {{id: $id}})
                SET {", ".join(set_clauses)}
                RETURN n.id as id
            """

            result = self.neo4j.execute_write(query, params)

            if result:
                logger.debug(f"Added node: {node_id} ({node_label})")
                return result[0]["id"]
            else:
                raise RuntimeError("Failed to add node")

        except Exception as e:
            logger.error(f"Failed to add node {node_id}: {e}")
            raise

    def add_edge(
        self,
        src_id: str,
        dst_id: str,
        relationship: str,
        properties: dict[str, Any] | None = None,
        edge_id: str | None = None,
    ) -> str:
        """Add an edge between two nodes.

        Args:
            src_id: Source node ID
            dst_id: Destination node ID
            relationship: Relationship type (e.g., CONTAINS, DEPENDS_ON)
            properties: Optional edge properties
            edge_id: Optional custom edge ID

        Returns:
            The edge ID
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        # Generate edge ID if not provided
        if edge_id is None:
            edge_id = f"{src_id}_{relationship}_{dst_id}"

        properties = properties or {}

        # Convert properties to JSON string
        properties_json = json.dumps(properties) if properties else None

        try:
            # Use relationship type as the label (e.g., Graph:CONTAINS)
            edge_label = self.neo4j.get_label(relationship)

            query = f"""
                MATCH (src) WHERE src.id = $src_id
                MATCH (dst) WHERE dst.id = $dst_id
                MERGE (src)-[r:`{edge_label}` {{id: $edge_id}}]->(dst)
                SET r.properties_json = $properties_json
                RETURN r.id as id
            """

            result = self.neo4j.execute_write(
                query,
                {
                    "src_id": src_id,
                    "dst_id": dst_id,
                    "edge_id": edge_id,
                    "properties_json": properties_json,
                },
            )

            if result:
                logger.debug(f"Added edge: {src_id} -{relationship}-> {dst_id}")
                return result[0]["id"]
            else:
                raise RuntimeError(
                    f"Failed to add edge. Make sure nodes {src_id} and {dst_id} exist."
                )

        except Exception as e:
            logger.error(f"Failed to add edge {edge_id}: {e}")
            raise

    def update_node_property(
        self, node_id: str, property_name: str, value: Any
    ) -> bool:
        """Update a single property on a node.

        Used by prep steps to write scores, flags, etc.

        Args:
            node_id: Node ID to update
            property_name: Property name to set
            value: Property value (must be Neo4j-compatible: str, int, float, bool, list)

        Returns:
            True if updated, False if node not found
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            query = f"""
                MATCH (n {{id: $node_id}})
                SET n.{property_name} = $value
                RETURN n.id as id
            """

            result = self.neo4j.execute_write(
                query, {"node_id": node_id, "value": value}
            )

            if result:
                logger.debug(f"Updated {property_name}={value} on node {node_id}")
                return True
            return False

        except Exception as e:
            logger.error(f"Failed to update property on {node_id}: {e}")
            raise

    def update_nodes_property(
        self, node_ids: list[str], property_name: str, value: Any
    ) -> int:
        """Update a property on multiple nodes.

        Args:
            node_ids: List of node IDs to update
            property_name: Property name to set
            value: Property value

        Returns:
            Number of nodes updated
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        if not node_ids:
            return 0

        try:
            query = f"""
                MATCH (n)
                WHERE n.id IN $node_ids
                SET n.{property_name} = $value
                RETURN count(n) as updated
            """

            result = self.neo4j.execute_write(
                query, {"node_ids": node_ids, "value": value}
            )

            if result:
                count = result[0]["updated"]
                logger.debug(f"Updated {property_name}={value} on {count} nodes")
                return count
            return 0

        except Exception as e:
            logger.error(f"Failed to bulk update property: {e}")
            raise

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Retrieve a node by ID.

        Args:
            node_id: Node ID to retrieve

        Returns:
            Node data as dictionary or None if not found
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            query = """
                MATCH (n)
                WHERE n.id = $node_id
                RETURN n.id as id,
                       n.label as label,
                       n.properties_json as properties_json
            """

            result = self.neo4j.execute_read(query, {"node_id": node_id})

            if result:
                data = result[0]
                # Parse JSON properties back to dict
                properties = (
                    json.loads(data["properties_json"])
                    if data.get("properties_json")
                    else {}
                )
                return {
                    "id": data["id"],
                    "label": data["label"],
                    "properties": properties,
                }
            return None

        except Exception as e:
            logger.error(f"Failed to get node {node_id}: {e}")
            raise

    def get_nodes_by_type(self, node_type: str) -> list[dict[str, Any]]:
        """Retrieve all nodes of a specific type.

        Args:
            node_type: Node type/label to filter by

        Returns:
            List of node dictionaries
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            # Use namespace-aware label
            label = self.neo4j.get_label(node_type)

            query = f"""
                MATCH (n:`{label}`)
                RETURN n.id as id,
                       n.label as label,
                       n.properties_json as properties_json
            """

            result = self.neo4j.execute_read(query)

            nodes = []
            for data in result:
                # Parse JSON properties back to dict
                properties = (
                    json.loads(data["properties_json"])
                    if data.get("properties_json")
                    else {}
                )
                nodes.append(
                    {"id": data["id"], "label": data["label"], "properties": properties}
                )

            return nodes

        except Exception as e:
            logger.error(f"Failed to get nodes by type {node_type}: {e}")
            raise

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and its associated edges.

        Args:
            node_id: Node ID to delete

        Returns:
            True if deleted, False if not found
        """
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            query = """
                MATCH (n {id: $node_id})
                DETACH DELETE n
                RETURN count(n) as deleted
            """

            result = self.neo4j.execute_write(query, {"node_id": node_id})

            if result and result[0]["deleted"] > 0:
                logger.debug(f"Deleted node: {node_id}")
                return True
            return False

        except Exception as e:
            logger.error(f"Failed to delete node {node_id}: {e}")
            raise

    def query(
        self, cypher_query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a Cypher query.

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

    def clear_graph(self) -> None:
        """Clear all nodes and edges from the graph."""
        if self.neo4j is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            self.neo4j.clear_namespace()
            logger.info(f"Cleared all graph data from namespace '{self.namespace}'")

        except Exception as e:
            logger.error(f"Failed to clear graph: {e}")
            raise
