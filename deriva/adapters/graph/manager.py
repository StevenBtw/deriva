"""Graph Manager - Main interface for graph operations.

This module provides the GraphManager class which handles all graph database
operations using the shared grafeo connection with namespace isolation.

Usage:
    from deriva.adapters.graph import GraphManager
    from deriva.adapters.graph.models import RepositoryNode, FileNode

    with GraphManager() as gm:
        # Add nodes
        repo = RepositoryNode(id="repo_myapp", name="myapp", url="https://...")
        gm.add_node(repo)

        # Add relationships
        gm.add_edge("repo_myapp", "file_myapp_main_py", "CONTAINS")

        # Query with Cypher
        results = gm.execute("MATCH (r:Repository)-[:CONTAINS]->(f:File) RETURN f")

        # Get enrichment data
        enrichments = gm.get_enrichments(["file_myapp_main_py"])
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

from deriva.adapters.grafeo import GrafeoConnection

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

# Node ID prefixes that embed repository name
_NODE_ID_PREFIXES = frozenset(
    {
        "file",
        "dir",
        "method",
        "typedef",
        "concept",
        "tech",
        "test",
        "extdep",
        "service",
        "module",
    }
)


def _extract_repo_from_node_id(node_id: str) -> str | None:
    """Extract repository name from node ID.

    Supports two formats:
    - New format: prefix::reponame::identifier (preferred)
    - Legacy format: prefix_reponame_identifier (for backward compatibility)

    Examples:
        >>> _extract_repo_from_node_id("file::myapp::src/main.py")
        'myapp'
        >>> _extract_repo_from_node_id("file_myapp_src_main_py")
        'myapp'

    Args:
        node_id: The node ID string

    Returns:
        Repository name or None if not extractable
    """
    if not node_id:
        return None

    # New format: prefix::repo::identifier
    if "::" in node_id:
        parts = node_id.split("::", 2)
        if len(parts) >= 2 and parts[0] in _NODE_ID_PREFIXES:
            return parts[1]

    # Legacy format: prefix_repo_identifier
    parts = node_id.split("_", 2)
    if len(parts) >= 2 and parts[0] in _NODE_ID_PREFIXES:
        return parts[1]

    # Handle repo_ prefix specially (legacy format)
    if node_id.startswith("repo_"):
        return node_id[5:]  # Everything after "repo_"

    # Handle repo:: prefix (new format)
    if node_id.startswith("repo::"):
        remaining = node_id[6:]  # Everything after "repo::"
        # Return up to next :: or all if no more
        return remaining.split("::", 1)[0]

    return None


class GraphManager:
    """Manages graph database operations using grafeo (embedded).

    This class provides a high-level interface for:
    - Creating and managing property graphs
    - Adding nodes and edges (Repository, Directory, File, Method, TypeDefinition, etc.)
    - Querying graph structure with Cypher
    - Traversing relationships

    Uses the shared grafeo connection with "Graph" namespace.

    Example:
        from deriva.adapters.graph import GraphManager

        with GraphManager() as gm:
            # Add a node
            gm.add_node(RepositoryNode(id="repo_myapp", name="myapp", url="..."))

            # Query nodes
            results = gm.execute("MATCH (n:Repository) RETURN n")

            # Get node by ID
            node = gm.get_node("repo_myapp")
    """

    def __init__(self):
        """Initialize the GraphManager using .env configuration."""
        load_dotenv()
        self.db: GrafeoConnection | None = None
        self.namespace = os.getenv("GRAPH_NAMESPACE", "Graph")

        logger.info(f"Initializing GraphManager with namespace: {self.namespace}")

    def connect(self) -> None:
        """Establish connection to the graph database."""
        if self.db is not None:
            logger.warning("Connection already established")
            return

        try:
            self.db = GrafeoConnection(namespace=self.namespace)
            self.db.connect()

            logger.info(
                f"Successfully connected to grafeo with namespace '{self.namespace}'"
            )

        except Exception as e:
            logger.error(f"Failed to connect to grafeo: {e}")
            raise ConnectionError(f"Could not connect to grafeo: {e}")

    def disconnect(self) -> None:
        """Close the graph database connection."""
        if self.db is not None:
            self.db.disconnect()
            self.db = None
            logger.info("Disconnected from grafeo")

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
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

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
        # Graph can store: strings, numbers, booleans, and arrays of these
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

        # Extract and store repository_name for filtering in multi-repo setups
        if "repository_name" not in flat_props:
            repo_name = _extract_repo_from_node_id(node_id)
            if repo_name:
                flat_props["repository_name"] = repo_name

        try:
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

            # Use two separate labels: namespace (Graph) + type (Directory)
            # This allows queries like MATCH (d:Directory) to work
            # while still having namespace isolation via the Graph label
            query = f"""
                MERGE (n:`{self.namespace}`:`{node_label}` {{id: $id}})
                SET {", ".join(set_clauses)}
                RETURN n.id as id
            """

            result = self.db.execute_write(query, params)

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
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        # Generate edge ID if not provided
        if edge_id is None:
            edge_id = f"{src_id}_{relationship}_{dst_id}"

        properties = properties or {}

        # Convert properties to JSON string
        properties_json = json.dumps(properties) if properties else None

        try:
            # Use relationship type as the label (e.g., Graph:CONTAINS)
            edge_label = self.db.get_label(relationship)

            query = f"""
                MATCH (src) WHERE src.id = $src_id
                MATCH (dst) WHERE dst.id = $dst_id
                MERGE (src)-[r:`{edge_label}` {{id: $edge_id}}]->(dst)
                SET r.properties_json = $properties_json
                RETURN r.id as id
            """

            result = self.db.execute_write(
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
            # Log at debug level - edge failures are expected when targets don't exist yet
            logger.debug(f"Failed to add edge {edge_id}: {e}")
            raise

    def update_node_property(
        self, node_id: str, property_name: str, value: Any
    ) -> bool:
        """Update a single property on a node.

        Used by prep steps to write scores, flags, etc.

        Args:
            node_id: Node ID to update
            property_name: Property name to set
            value: Property value (must be graph-compatible: str, int, float, bool, list)

        Returns:
            True if updated, False if node not found
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        try:
            query = f"""
                MATCH (n {{id: $node_id}})
                SET n.{property_name} = $value
                RETURN n.id as id
            """

            result = self.db.execute_write(query, {"node_id": node_id, "value": value})

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
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        if not node_ids:
            return 0

        try:
            query = f"""
                MATCH (n)
                WHERE n.id IN $node_ids
                SET n.{property_name} = $value
                RETURN count(n) as updated
            """

            result = self.db.execute_write(
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

    def batch_update_properties(self, updates: dict[str, dict[str, Any]]) -> int:
        """Batch update multiple properties on multiple nodes.

        Used by enrichment to write algorithm results (pagerank, community, etc.)
        to graph nodes efficiently in a single transaction.

        Args:
            updates: Dict mapping node_id to property dict
                {
                    "node_123": {"pagerank": 0.05, "kcore_level": 3},
                    "node_456": {"pagerank": 0.02, "kcore_level": 2},
                }

        Returns:
            Number of nodes updated
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        if not updates:
            return 0

        try:
            # Use UNWIND for efficient batch update
            query = """
                UNWIND $updates AS update
                MATCH (n {id: update.node_id})
                SET n += update.properties
                RETURN count(n) as updated
            """

            # Convert to list format for UNWIND
            update_list = [
                {"node_id": node_id, "properties": props}
                for node_id, props in updates.items()
            ]

            result = self.db.execute_write(query, {"updates": update_list})

            if result:
                count = result[0]["updated"]
                logger.debug(f"Batch updated properties on {count} nodes")
                return count
            return 0

        except Exception as e:
            logger.error(f"Failed to batch update properties: {e}")
            raise

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Retrieve a node by ID.

        Args:
            node_id: Node ID to retrieve

        Returns:
            Node data as dictionary or None if not found
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        try:
            query = """
                MATCH (n)
                WHERE n.id = $node_id
                RETURN n.id as id,
                       n.label as label,
                       n.properties_json as properties_json
            """

            result = self.db.execute_read(query, {"node_id": node_id})

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

    def node_exists(self, node_id: str) -> bool:
        """Check if a node exists by ID.

        Args:
            node_id: Node ID to check

        Returns:
            True if node exists, False otherwise
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        try:
            query = """
                MATCH (n)
                WHERE n.id = $node_id
                RETURN count(n) > 0 as exists
            """
            result = self.db.execute_read(query, {"node_id": node_id})
            return result[0]["exists"] if result else False

        except Exception as e:
            logger.error(f"Failed to check node existence {node_id}: {e}")
            return False

    def get_nodes_by_type(self, node_type: str) -> list[dict[str, Any]]:
        """Retrieve all nodes of a specific type.

        Args:
            node_type: Node type/label to filter by

        Returns:
            List of node dictionaries
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        try:
            # Query by node type label directly
            # Nodes have two labels: namespace (Graph) + type (Repository, Directory, etc.)
            query = f"""
                MATCH (n:`{node_type}`)
                RETURN n.id as id,
                       n.label as label,
                       n.properties_json as properties_json
            """

            result = self.db.execute_read(query)

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
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        try:
            query = """
                MATCH (n {id: $node_id})
                DETACH DELETE n
                RETURN count(n) as deleted
            """

            result = self.db.execute_write(query, {"node_id": node_id})

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
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        try:
            return self.db.execute(cypher_query, params)

        except Exception as e:
            logger.error(f"Query failed: {e}")
            raise

    def clear_graph(self) -> None:
        """Clear all nodes and edges from the graph."""
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        try:
            self.db.clear_namespace()
            logger.info(f"Cleared all graph data from namespace '{self.namespace}'")

        except Exception as e:
            logger.error(f"Failed to clear graph: {e}")
            raise

    def clear_graph_for_repo(self, repo_name: str) -> int:
        """Clear all nodes and edges for a specific repository.

        Deletes only Graph-namespace nodes where repository_name matches.
        All node types (including Repository) get repository_name set
        by add_node(), so a single filter covers everything.

        Args:
            repo_name: Repository name to clear

        Returns:
            Number of nodes deleted
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        try:
            ns = self.namespace
            # Count first (grafeo can't RETURN after DETACH DELETE)
            count_query = f"""
                MATCH (n:`{ns}`)
                WHERE n.repository_name = $repo_name
                RETURN count(n) as cnt
            """
            count_result = self.db.execute_read(count_query, {"repo_name": repo_name})
            count = count_result[0]["cnt"] if count_result else 0

            if count > 0:
                delete_query = f"""
                    MATCH (n:`{ns}`)
                    WHERE n.repository_name = $repo_name
                    DETACH DELETE n
                """
                self.db.execute_write(delete_query, {"repo_name": repo_name})

            logger.info(
                "Cleared %d nodes for repo '%s' from namespace '%s'",
                count,
                repo_name,
                self.namespace,
            )
            return count

        except Exception as e:
            logger.error("Failed to clear graph for repo '%s': %s", repo_name, e)
            raise

    def clear_nodes_by_labels(self, repo_name: str, labels: list[str]) -> int:
        """Clear nodes with specific labels for a repository.

        Deletes nodes matching ANY of the given labels where repository_name matches.
        Edges connected to deleted nodes are also removed (DETACH DELETE).

        Args:
            repo_name: Repository name to clear
            labels: Node labels to clear (e.g., ["BusinessConcept", "Technology"])

        Returns:
            Number of nodes deleted
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        if not labels:
            return 0

        try:
            ns = self.namespace
            label_conditions = " OR ".join(f"n:`{ns}:{label}`" for label in labels)

            count_query = f"""
                MATCH (n:`{ns}`)
                WHERE n.repository_name = $repo_name AND ({label_conditions})
                RETURN count(n) as cnt
            """
            count_result = self.db.execute_read(count_query, {"repo_name": repo_name})
            count = count_result[0]["cnt"] if count_result else 0

            if count > 0:
                delete_query = f"""
                    MATCH (n:`{ns}`)
                    WHERE n.repository_name = $repo_name AND ({label_conditions})
                    DETACH DELETE n
                """
                self.db.execute_write(delete_query, {"repo_name": repo_name})

            logger.info(
                "Cleared %d nodes with labels %s for repo '%s'",
                count,
                labels,
                repo_name,
            )
            return count

        except Exception as e:
            logger.error(
                "Failed to clear nodes by labels for repo '%s': %s", repo_name, e
            )
            raise

    def has_extraction(self, repo_name: str) -> bool:
        """Check if extraction data exists for a repository.

        Looks for a Repository node with the given repository_name
        in the Graph namespace.

        Args:
            repo_name: Repository name to check

        Returns:
            True if extraction data exists
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        try:
            query = """
                MATCH (n:Repository)
                WHERE n.repository_name = $repo_name
                RETURN count(n) as cnt
            """
            result = self.db.execute_read(query, {"repo_name": repo_name})
            return (result[0]["cnt"] > 0) if result else False

        except Exception as e:
            logger.error("Failed to check extraction for '%s': %s", repo_name, e)
            return False

    def get_extraction_fingerprint(self, repo_name: str) -> str | None:
        """Get the stored extraction fingerprint for a repository.

        The fingerprint is a hash of extraction config versions and repo commit,
        stored on the Repository node after extraction completes.

        Args:
            repo_name: Repository name

        Returns:
            Fingerprint hash string, or None if not set
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        try:
            query = """
                MATCH (n:Repository)
                WHERE n.repository_name = $repo_name
                RETURN n.extraction_fingerprint as fingerprint
            """
            result = self.db.execute_read(query, {"repo_name": repo_name})
            if result and result[0].get("fingerprint"):
                return result[0]["fingerprint"]
            return None

        except Exception as e:
            logger.error("Failed to get fingerprint for '%s': %s", repo_name, e)
            return None

    def set_extraction_fingerprint(self, repo_name: str, fingerprint: str) -> bool:
        """Store an extraction fingerprint on the Repository node.

        Called after extraction completes to record what configs and
        repo state produced the current graph data.

        Args:
            repo_name: Repository name
            fingerprint: Hash string to store

        Returns:
            True if updated, False if Repository node not found
        """
        if self.db is None:
            raise RuntimeError("Not connected to grafeo. Call connect() first.")

        try:
            query = """
                MATCH (n:Repository)
                WHERE n.repository_name = $repo_name
                SET n.extraction_fingerprint = $fingerprint
                RETURN n.id as id
            """
            result = self.db.execute_write(
                query, {"repo_name": repo_name, "fingerprint": fingerprint}
            )
            if result:
                logger.info(
                    "Set extraction fingerprint for '%s': %s...",
                    repo_name,
                    fingerprint[:12],
                )
                return True
            return False

        except Exception as e:
            logger.error("Failed to set fingerprint for '%s': %s", repo_name, e)
            raise
