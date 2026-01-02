"""Neo4j Connection Service - Shared connection manager for Neo4j.

This module provides a connection service that can be used by multiple
managers (graph_manager, archimate_manager) with namespace isolation.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

if TYPE_CHECKING:
    from neo4j import Driver

try:
    from neo4j import GraphDatabase
except ModuleNotFoundError:
    GraphDatabase = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


class Neo4jConnection:
    """Manages Neo4j database connection with namespace support.

    This class provides a shared connection to Neo4j that multiple managers
    can use. Each manager gets its own namespace (label prefix) to ensure
    clean separation of data.

    Example:
        >>> conn = Neo4jConnection(namespace="Graph")
        >>> conn.connect()
        >>> conn.execute("CREATE (n:Repository {name: $name})", {"name": "test"})
        >>> conn.disconnect()
    """

    def __init__(self, namespace: str):
        """
        Initialize Neo4j connection using .env configuration.

        Args:
            namespace: Label prefix for this manager (e.g., "Graph", "ArchiMate")
        """
        load_dotenv()
        self.namespace = namespace
        self.config = self._load_config_from_env()
        self.driver: Driver | None = None

        logger.info(f"Initialized Neo4jConnection with namespace: {namespace}")

    def _load_config_from_env(self) -> dict[str, Any]:
        """Load configuration from environment variables.

        Returns:
            Configuration dictionary
        """
        return {
            "neo4j": {
                "uri": os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                "auth": {
                    "username": os.getenv("NEO4J_USERNAME", ""),
                    "password": os.getenv("NEO4J_PASSWORD", ""),
                },
                "database": os.getenv("NEO4J_DATABASE", "neo4j"),
                "encrypted": os.getenv("NEO4J_ENCRYPTED", "False").lower() == "true",
                "max_connection_lifetime": int(
                    os.getenv("NEO4J_MAX_CONNECTION_LIFETIME", "3600")
                ),
                "max_connection_pool_size": int(
                    os.getenv("NEO4J_MAX_CONNECTION_POOL_SIZE", "50")
                ),
                "connection_acquisition_timeout": int(
                    os.getenv("NEO4J_CONNECTION_ACQUISITION_TIMEOUT", "60")
                ),
            },
            "logging": {
                "level": os.getenv("NEO4J_LOG_LEVEL", "INFO"),
                "log_queries": os.getenv("NEO4J_LOG_QUERIES", "False").lower()
                == "true",
            },
        }

    def connect(self) -> None:
        """Establish connection to Neo4j."""
        if self.driver is not None:
            logger.warning("Connection already established")
            return

        if GraphDatabase is None:
            raise ModuleNotFoundError(
                "neo4j is not installed. Install it to use Neo4jConnection."
            )

        try:
            neo4j_config = self.config["neo4j"]

            # Create auth tuple (username, password) or None
            auth = None
            if neo4j_config["auth"]["username"] or neo4j_config["auth"]["password"]:
                auth = (
                    neo4j_config["auth"]["username"],
                    neo4j_config["auth"]["password"],
                )

            # Connect to Neo4j
            self.driver = GraphDatabase.driver(
                neo4j_config["uri"],
                auth=auth,
                max_connection_lifetime=neo4j_config.get(
                    "max_connection_lifetime", 3600
                ),
                max_connection_pool_size=neo4j_config.get(
                    "max_connection_pool_size", 50
                ),
                connection_acquisition_timeout=neo4j_config.get(
                    "connection_acquisition_timeout", 60
                ),
                encrypted=neo4j_config.get("encrypted", False),
            )

            # Test connection
            self.driver.verify_connectivity()
            logger.info(f"Successfully connected to Neo4j at {neo4j_config['uri']}")

        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            raise ConnectionError(f"Could not connect to Neo4j: {e}")

    def disconnect(self) -> None:
        """Close the Neo4j connection."""
        if self.driver is not None:
            self.driver.close()
            self.driver = None
            logger.info("Disconnected from Neo4j")

    def __enter__(self) -> Neo4jConnection:
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(
        self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any
    ) -> None:
        """Context manager exit."""
        self.disconnect()

    def execute(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        database: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute a Cypher query and return results.

        Args:
            query: Cypher query string
            parameters: Query parameters
            database: Database name (defaults to config database)

        Returns:
            List of result records as dictionaries
        """
        if self.driver is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        if database is None:
            database = self.config["neo4j"]["database"]

        if self.config["logging"].get("log_queries", False):
            logger.debug(f"Executing query: {query}")
            logger.debug(f"Parameters: {parameters}")

        try:
            params: dict[str, Any] = parameters if parameters is not None else {}
            with self.driver.session(database=database) as session:
                result = session.run(query, params)  # type: ignore[arg-type] # neo4j stubs require LiteralString
                records = [dict(record) for record in result]
                return records

        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Parameters: {parameters}")
            raise

    def execute_write(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        database: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute a write transaction (CREATE, UPDATE, DELETE).

        Args:
            query: Cypher query string
            parameters: Query parameters
            database: Database name (defaults to config database)

        Returns:
            List of result records as dictionaries
        """
        if self.driver is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        if database is None:
            database = self.config["neo4j"]["database"]

        if self.config["logging"].get("log_queries", False):
            logger.debug(f"Executing write query: {query}")
            logger.debug(f"Parameters: {parameters}")

        try:
            params: dict[str, Any] = parameters if parameters is not None else {}
            with self.driver.session(database=database) as session:
                result = session.execute_write(lambda tx: list(tx.run(query, params)))
                return [dict(record) for record in result]

        except Exception as e:
            logger.error(f"Write query execution failed: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Parameters: {parameters}")
            raise

    def execute_read(
        self,
        query: str,
        parameters: dict[str, Any] | None = None,
        database: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute a read transaction (MATCH, RETURN).

        Args:
            query: Cypher query string
            parameters: Query parameters
            database: Database name (defaults to config database)

        Returns:
            List of result records as dictionaries
        """
        if self.driver is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        if database is None:
            database = self.config["neo4j"]["database"]

        if self.config["logging"].get("log_queries", False):
            logger.debug(f"Executing read query: {query}")
            logger.debug(f"Parameters: {parameters}")

        try:
            params: dict[str, Any] = parameters if parameters is not None else {}
            with self.driver.session(database=database) as session:
                result = session.execute_read(lambda tx: list(tx.run(query, params)))
                return [dict(record) for record in result]

        except Exception as e:
            logger.error(f"Read query execution failed: {e}")
            logger.error(f"Query: {query}")
            logger.error(f"Parameters: {parameters}")
            raise

    def clear_namespace(self) -> None:
        """Clear all nodes and relationships for this namespace."""
        if self.driver is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        try:
            # Delete all relationships first
            self.execute_write(
                f"MATCH ()-[r:{self.namespace}Relationship]->() DELETE r"
            )

            # Delete all nodes
            self.execute_write(f"MATCH (n:{self.namespace}Element) DELETE n")

            # Also try generic namespace labels
            self.execute_write(
                "MATCH (n) WHERE any(label IN labels(n) WHERE label STARTS WITH $namespace) DETACH DELETE n",
                {"namespace": self.namespace},
            )

            logger.info(f"Cleared all data for namespace: {self.namespace}")

        except Exception as e:
            logger.error(f"Failed to clear namespace {self.namespace}: {e}")
            raise

    def get_label(self, base_label: str) -> str:
        """
        Get namespaced label.

        Args:
            base_label: Base label name (e.g., "Repository", "Element")

        Returns:
            Namespaced label (e.g., "Graph:Repository", "ArchiMate:Element")
        """
        return f"{self.namespace}:{base_label}"

    def create_constraint(
        self, label: str, property_key: str, constraint_name: str | None = None
    ) -> None:
        """
        Create a uniqueness constraint on a label property.

        Args:
            label: Node label (will be namespaced)
            property_key: Property to constrain
            constraint_name: Optional constraint name
        """
        if self.driver is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        namespaced_label = self.get_label(label)

        if constraint_name is None:
            constraint_name = (
                f"{namespaced_label.replace(':', '_')}_{property_key}_unique"
            )

        try:
            query = f"""
                CREATE CONSTRAINT {constraint_name} IF NOT EXISTS
                FOR (n:{namespaced_label})
                REQUIRE n.{property_key} IS UNIQUE
            """
            self.execute_write(query)
            logger.info(f"Created constraint: {constraint_name}")

        except Exception as e:
            logger.warning(f"Could not create constraint {constraint_name}: {e}")

    def create_index(
        self, label: str, property_key: str, index_name: str | None = None
    ) -> None:
        """
        Create an index on a label property.

        Args:
            label: Node label (will be namespaced)
            property_key: Property to index
            index_name: Optional index name
        """
        if self.driver is None:
            raise RuntimeError("Not connected to Neo4j. Call connect() first.")

        namespaced_label = self.get_label(label)

        if index_name is None:
            index_name = f"{namespaced_label.replace(':', '_')}_{property_key}_index"

        try:
            query = f"""
                CREATE INDEX {index_name} IF NOT EXISTS
                FOR (n:{namespaced_label})
                ON (n.{property_key})
            """
            self.execute_write(query)
            logger.info(f"Created index: {index_name}")

        except Exception as e:
            logger.warning(f"Could not create index {index_name}: {e}")

    def _get_compose_dir(self) -> Path:
        """Get the directory containing docker-compose.yml.

        Returns:
            Path to the directory containing docker-compose.yml
        """
        return Path(__file__).parent

    def start_container(self) -> dict[str, Any]:
        """Start the Neo4j Docker container using docker-compose.

        Returns:
            Dictionary with status information:
            {
                'success': bool,
                'message': str,
                'output': str (optional),
                'error': str (optional)
            }

        Raises:
            RuntimeError: If docker-compose command fails
        """
        compose_dir = self._get_compose_dir()

        try:
            logger.info("Starting Neo4j Docker container...")
            result = subprocess.run(
                ["docker-compose", "up", "-d"],
                cwd=compose_dir,
                capture_output=True,
                text=True,
                check=True,
            )

            logger.info("Neo4j Docker container started successfully")
            return {
                "success": True,
                "message": "Neo4j container started successfully",
                "output": result.stdout,
            }

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to start Neo4j container: {e.stderr}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
        except FileNotFoundError:
            error_msg = (
                "docker-compose command not found. Is Docker installed and in PATH?"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def stop_container(self) -> dict[str, Any]:
        """Stop the Neo4j Docker container using docker-compose.

        Returns:
            Dictionary with status information:
            {
                'success': bool,
                'message': str,
                'output': str (optional),
                'error': str (optional)
            }

        Raises:
            RuntimeError: If docker-compose command fails
        """
        compose_dir = self._get_compose_dir()

        try:
            logger.info("Stopping Neo4j Docker container...")
            result = subprocess.run(
                ["docker-compose", "down"],
                cwd=compose_dir,
                capture_output=True,
                text=True,
                check=True,
            )

            logger.info("Neo4j Docker container stopped successfully")
            return {
                "success": True,
                "message": "Neo4j container stopped successfully",
                "output": result.stdout,
            }

        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to stop Neo4j container: {e.stderr}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
        except FileNotFoundError:
            error_msg = (
                "docker-compose command not found. Is Docker installed and in PATH?"
            )
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def get_container_status(self) -> dict[str, Any]:
        """Get the status of the Neo4j Docker container.

        Returns:
            Dictionary with status information:
            {
                'running': bool,
                'container_name': str,
                'status': str,
                'ports': str (optional)
            }
        """
        try:
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "--filter",
                    "name=deriva_neo4j",
                    "--format",
                    "{{.Names}}\t{{.Status}}\t{{.Ports}}",
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            if result.stdout.strip():
                # Container is running
                parts = result.stdout.strip().split("\t")
                return {
                    "running": True,
                    "container_name": parts[0] if len(parts) > 0 else "deriva_neo4j",
                    "status": parts[1] if len(parts) > 1 else "Unknown",
                    "ports": parts[2] if len(parts) > 2 else "",
                }
            else:
                # Container is not running
                return {
                    "running": False,
                    "container_name": "deriva_neo4j",
                    "status": "Not running",
                    "ports": "",
                }

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get container status: {e.stderr}")
            return {
                "running": False,
                "container_name": "deriva_neo4j",
                "status": f"Error: {e.stderr}",
                "ports": "",
            }
        except FileNotFoundError:
            logger.error("docker command not found")
            return {
                "running": False,
                "container_name": "deriva_neo4j",
                "status": "Error: Docker not found",
                "ports": "",
            }

    def ensure_container_running(self) -> dict[str, Any]:
        """Ensure the Neo4j Docker container is running, starting it if necessary.

        Returns:
            Dictionary with status information:
            {
                'was_running': bool,
                'is_running': bool,
                'action_taken': str
            }
        """
        status = self.get_container_status()

        if status["running"]:
            logger.info("Neo4j container is already running")
            return {"was_running": True, "is_running": True, "action_taken": "none"}

        # Container not running, start it
        logger.info("Neo4j container not running, starting it...")
        start_result = self.start_container()

        if start_result["success"]:
            return {"was_running": False, "is_running": True, "action_taken": "started"}
        else:
            return {"was_running": False, "is_running": False, "action_taken": "failed"}
