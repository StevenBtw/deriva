"""
Technology extraction - Structural extraction from infrastructure config files.

This module extracts Technology nodes by:
1. Querying existing Technology nodes (from DirectoryClassification)
2. Parsing docker-compose.yml for services
3. Parsing .env files for configured infrastructure

No LLM required - purely deterministic extraction.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .base import (
    current_timestamp,
    generate_edge_id,
    strip_chunk_suffix,
)

# =============================================================================
# Technology Mapping Tables
# =============================================================================

# Map Docker base images to technology info
# Format: "image_pattern": ("TechName", "category", "description")
DOCKER_IMAGE_TO_TECHNOLOGY: dict[str, tuple[str, str, str]] = {
    "python": ("Python", "platform", "Python runtime"),
    "node": ("Node.js", "platform", "JavaScript runtime"),
    "golang": ("Go", "platform", "Go runtime"),
    "java": ("Java", "platform", "Java runtime"),
    "openjdk": ("Java", "platform", "Java runtime"),
    "postgres": ("PostgreSQL", "system_software", "Relational database"),
    "postgresql": ("PostgreSQL", "system_software", "Relational database"),
    "mysql": ("MySQL", "system_software", "Relational database"),
    "mariadb": ("MariaDB", "system_software", "Relational database"),
    "mongo": ("MongoDB", "system_software", "Document database"),
    "mongodb": ("MongoDB", "system_software", "Document database"),
    "redis": ("Redis", "system_software", "In-memory cache"),
    "elasticsearch": ("Elasticsearch", "system_software", "Search engine"),
    "opensearch": ("OpenSearch", "system_software", "Search engine"),
    "rabbitmq": ("RabbitMQ", "system_software", "Message broker"),
    "kafka": ("Kafka", "system_software", "Event streaming"),
    "nginx": ("Nginx", "system_software", "Web server"),
    "apache": ("Apache", "system_software", "Web server"),
    "neo4j": ("Neo4j", "system_software", "Graph database"),
    "memcached": ("Memcached", "system_software", "Memory cache"),
    "minio": ("MinIO", "system_software", "Object storage"),
    "vault": ("Vault", "security", "Secrets management"),
    "keycloak": ("Keycloak", "security", "Identity management"),
}

# Map .env variable patterns to technologies
# Format: "pattern": ("TechName", "category", "description")
ENV_PATTERNS: list[tuple[str, tuple[str, str, str]]] = [
    (r"NEO4J_", ("Neo4j", "system_software", "Graph database")),
    (
        r"POSTGRES_|POSTGRESQL_|PG_",
        ("PostgreSQL", "system_software", "Relational database"),
    ),
    (r"MYSQL_", ("MySQL", "system_software", "Relational database")),
    (r"MONGO_|MONGODB_", ("MongoDB", "system_software", "Document database")),
    (r"REDIS_", ("Redis", "system_software", "In-memory cache")),
    (r"ELASTICSEARCH_|ELASTIC_", ("Elasticsearch", "system_software", "Search engine")),
    (r"RABBITMQ_|AMQP_", ("RabbitMQ", "system_software", "Message broker")),
    (r"KAFKA_", ("Kafka", "system_software", "Event streaming")),
    (r"AWS_", ("AWS", "service", "Amazon Web Services")),
    (r"AZURE_", ("Azure", "service", "Microsoft Azure")),
    (r"GCP_|GOOGLE_CLOUD_", ("Google Cloud", "service", "Google Cloud Platform")),
    (r"OPENAI_", ("OpenAI", "service", "AI/ML API service")),
    (r"ANTHROPIC_", ("Anthropic", "service", "AI/ML API service")),
    (r"SENTRY_", ("Sentry", "service", "Error tracking")),
    (r"STRIPE_", ("Stripe", "service", "Payment processing")),
]


# =============================================================================
# Parsing Functions
# =============================================================================


def parse_docker_compose(file_content: str) -> list[dict[str, Any]]:
    """
    Parse docker-compose.yml to extract service technologies.

    Args:
        file_content: Content of docker-compose file

    Returns:
        List of technology dicts with name, category, description, version
    """
    technologies: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Find image: declarations
    image_pattern = re.compile(
        r"^\s*image:\s*['\"]?([^\s:'\"]+)(?::([^\s'\"]+))?", re.MULTILINE
    )

    for match in image_pattern.finditer(file_content):
        image_name = match.group(1).lower()
        version = match.group(2)

        # Strip registry prefix (e.g., docker.io/library/postgres -> postgres)
        if "/" in image_name:
            image_name = image_name.split("/")[-1]

        # Look up in mapping
        tech_info = DOCKER_IMAGE_TO_TECHNOLOGY.get(image_name)
        if tech_info:
            tech_name, category, description = tech_info

            if tech_name.lower() not in seen:
                seen.add(tech_name.lower())
                technologies.append(
                    {
                        "name": tech_name,
                        "category": category,
                        "description": description,
                        "version": version,
                        "source": "docker-compose",
                    }
                )

    return technologies


def parse_dockerfile(file_content: str) -> list[dict[str, Any]]:
    """
    Parse Dockerfile to extract base image technologies.

    Args:
        file_content: Content of Dockerfile

    Returns:
        List of technology dicts
    """
    technologies: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Parse FROM instructions
    from_pattern = re.compile(
        r"^FROM\s+([^\s:]+)(?::([^\s]+))?", re.MULTILINE | re.IGNORECASE
    )

    for match in from_pattern.finditer(file_content):
        image_name = match.group(1).lower()
        version = match.group(2)

        # Strip registry prefix
        if "/" in image_name:
            image_name = image_name.split("/")[-1]

        tech_info = DOCKER_IMAGE_TO_TECHNOLOGY.get(image_name)
        if tech_info:
            tech_name, category, description = tech_info

            if tech_name.lower() not in seen:
                seen.add(tech_name.lower())
                technologies.append(
                    {
                        "name": tech_name,
                        "category": category,
                        "description": description,
                        "version": version,
                        "source": "dockerfile",
                    }
                )

    return technologies


def parse_env_file(file_content: str) -> list[dict[str, Any]]:
    """
    Parse .env file to detect configured technologies.

    Args:
        file_content: Content of .env or .env.example file

    Returns:
        List of technology dicts
    """
    technologies: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pattern, tech_info in ENV_PATTERNS:
        if re.search(pattern, file_content, re.IGNORECASE):
            tech_name, category, description = tech_info

            if tech_name.lower() not in seen:
                seen.add(tech_name.lower())
                technologies.append(
                    {
                        "name": tech_name,
                        "category": category,
                        "description": description,
                        "version": None,
                        "source": "env",
                    }
                )

    return technologies


# =============================================================================
# Main Extraction Function
# =============================================================================


def extract_technologies_structural(
    existing_technologies: list[dict[str, Any]],
    files: list[dict[str, str]],
    repo_name: str,
) -> dict[str, Any]:
    """
    Extract Technology nodes from infrastructure config files.

    Uses existing Technology nodes (from DirectoryClassification) to:
    - Avoid creating duplicates
    - Create edges from files to existing technologies

    Args:
        existing_technologies: List of existing Technology nodes from graph
                               Each dict should have 'id', 'name', 'category'
        files: List of file dicts with 'path' and 'content'
        repo_name: Repository name

    Returns:
        Extraction result with nodes, edges, errors, stats
    """
    all_nodes: list[dict[str, Any]] = []
    all_edges: list[dict[str, Any]] = []

    # Build lookup of existing technologies by normalized name
    existing_by_name: dict[str, dict[str, Any]] = {}
    for tech in existing_technologies:
        name = (
            tech.get("name", "")
            .lower()
            .replace(" ", "")
            .replace("-", "")
            .replace("_", "")
        )
        existing_by_name[name] = tech

    # Track what we've already processed
    seen_technologies: set[str] = set(existing_by_name.keys())

    # Process each file
    for file_info in files:
        file_path = file_info.get("path", "")
        file_content = file_info.get("content", "")
        file_name = Path(file_path).name.lower()

        # Determine file type and parse
        parsed_techs: list[dict[str, Any]] = []

        if file_name == "dockerfile" or file_name.startswith("dockerfile."):
            parsed_techs = parse_dockerfile(file_content)
        elif "docker-compose" in file_name or file_name in (
            "compose.yml",
            "compose.yaml",
        ):
            parsed_techs = parse_docker_compose(file_content)
        elif file_name in (".env", ".env.example", ".env.local", ".env.development"):
            parsed_techs = parse_env_file(file_content)
        else:
            continue

        # Process parsed technologies
        for tech in parsed_techs:
            tech_name = tech["name"]
            normalized_name = (
                tech_name.lower().replace(" ", "").replace("-", "").replace("_", "")
            )

            # Build file node ID for edge
            original_path = strip_chunk_suffix(file_path)
            safe_path = original_path.replace("/", "_").replace("\\", "_")
            file_node_id = f"file::{repo_name}::{safe_path}"

            # Check if this technology already exists
            if normalized_name in existing_by_name:
                # Create edge to existing technology node
                existing_tech = existing_by_name[normalized_name]
                existing_id = existing_tech.get("id", "")

                if existing_id:
                    edge = {
                        "edge_id": generate_edge_id(
                            file_node_id, existing_id, "CONFIGURES"
                        ),
                        "from_node_id": file_node_id,
                        "to_node_id": existing_id,
                        "relationship_type": "CONFIGURES",
                        "properties": {
                            "source_type": tech.get("source", "config"),
                            "version": tech.get("version"),
                            "created_at": current_timestamp(),
                        },
                    }
                    all_edges.append(edge)
            elif normalized_name not in seen_technologies:
                # Create new technology node
                seen_technologies.add(normalized_name)

                tech_name_slug = tech_name.lower().replace(" ", "_").replace("-", "_")
                node_id = f"tech::{repo_name}::{tech_name_slug}"

                node = {
                    "node_id": node_id,
                    "label": "Technology",
                    "properties": {
                        "techName": tech_name,
                        "techCategory": tech["category"],
                        "description": tech["description"],
                        "version": tech.get("version"),
                        "originSource": file_path,
                        "confidence": 0.9,
                        "extracted_at": current_timestamp(),
                    },
                }
                all_nodes.append(node)

                # Create edge from file to new technology
                edge = {
                    "edge_id": generate_edge_id(file_node_id, node_id, "CONFIGURES"),
                    "from_node_id": file_node_id,
                    "to_node_id": node_id,
                    "relationship_type": "CONFIGURES",
                    "properties": {
                        "source_type": tech.get("source", "config"),
                        "version": tech.get("version"),
                        "created_at": current_timestamp(),
                    },
                }
                all_edges.append(edge)

    return {
        "success": True,
        "data": {"nodes": all_nodes, "edges": all_edges},
        "errors": [],
        "stats": {
            "total_nodes": len(all_nodes),
            "total_edges": len(all_edges),
            "node_types": {"Technology": len(all_nodes)},
            "existing_technologies": len(existing_technologies),
            "edges_to_existing": len(all_edges) - len(all_nodes),
        },
    }


# =============================================================================
# LLM-based Technology Extraction
# =============================================================================

TECHNOLOGY_SCHEMA = {
    "name": "technology_extraction",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "technologies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "techName": {"type": "string"},
                        "techCategory": {"type": "string"},
                        "description": {"type": "string"},
                        "version": {"type": ["string", "null"]},
                        "confidence": {"type": "number"},
                    },
                    "required": ["techName", "techCategory", "description"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["technologies"],
        "additionalProperties": False,
    },
}


def build_extraction_prompt(
    file_content: str,
    file_path: str,
    instruction: str,
    example: str,
    existing_dependencies: list[dict[str, str]] | None = None,
    existing_technologies: list[dict[str, str]] | None = None,
) -> str:
    """Build the LLM prompt for Technology extraction.

    Args:
        file_content: Content of the file to analyze
        file_path: Path to the file
        instruction: Extraction instruction from config
        example: Example output from config
        existing_dependencies: List of ExternalDependency nodes (to avoid overlap)
        existing_technologies: List of existing Technology nodes (to avoid duplicates)

    Returns:
        Formatted prompt string
    """
    prompt_parts = [
        instruction,
        "",
        f"File: {file_path}",
        "```",
        file_content[:15000],  # Limit content size
        "```",
        "",
    ]

    # Add existing dependencies context (so LLM knows what NOT to extract)
    if existing_dependencies:
        dep_names = [d.get("name", "") for d in existing_dependencies[:30]]
        prompt_parts.append(
            "ALREADY EXTRACTED as ExternalDependency (do NOT re-extract as Technology):"
        )
        prompt_parts.append(", ".join(dep_names))
        prompt_parts.append("")

    # Add existing technologies context (to avoid duplicates)
    if existing_technologies:
        tech_names = [t.get("name", "") for t in existing_technologies[:20]]
        prompt_parts.append("ALREADY EXTRACTED Technologies (do NOT duplicate):")
        prompt_parts.append(", ".join(tech_names))
        prompt_parts.append("")

    prompt_parts.extend(
        [
            "Example output format:",
            example,
            "",
            "Extract infrastructure technologies from this file. Return JSON matching the schema.",
        ]
    )

    return "\n".join(prompt_parts)


def parse_llm_response(response: Any) -> list[dict[str, Any]]:
    """Parse LLM response to extract technology data.

    Args:
        response: LLM response object

    Returns:
        List of technology dicts
    """
    # Handle different response formats
    if hasattr(response, "data"):
        data = response.data
    elif hasattr(response, "content"):
        import json

        try:
            data = json.loads(response.content)
        except json.JSONDecodeError:
            return []
    elif isinstance(response, dict):
        data = response
    else:
        return []

    # Extract technologies array
    if isinstance(data, dict):
        return data.get("technologies", [])
    return []


def build_technology_node(
    tech_data: dict[str, Any],
    file_path: str,
    repo_name: str,
) -> dict[str, Any]:
    """Build a Technology node dict from extracted data.

    Args:
        tech_data: Extracted technology data from LLM
        file_path: Source file path
        repo_name: Repository name

    Returns:
        Node dict with node_id, label, properties
    """
    tech_name = tech_data.get("techName", tech_data.get("name", ""))
    tech_name_slug = tech_name.lower().replace(" ", "_").replace("-", "_")
    node_id = f"tech::{repo_name}::{tech_name_slug}"

    return {
        "node_id": node_id,
        "label": "Technology",
        "properties": {
            "techName": tech_name,
            "techCategory": tech_data.get(
                "techCategory", tech_data.get("category", "service")
            ),
            "description": tech_data.get("description", ""),
            "version": tech_data.get("version"),
            "originSource": file_path,
            "confidence": tech_data.get("confidence", 0.8),
            "extracted_at": current_timestamp(),
        },
    }


def extract_technologies(
    file_path: str,
    file_content: str,
    repo_name: str,
    llm_query_fn: Any,
    config: dict[str, Any],
    existing_dependencies: list[dict[str, str]] | None = None,
    existing_technologies: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Extract Technology nodes from a single file using LLM.

    This function:
    1. Builds a prompt with the file content and context (existing deps/techs)
    2. Calls the LLM to extract infrastructure technologies
    3. Parses the response and builds nodes
    4. Creates CONFIGURES edges from File to Technology

    Args:
        file_path: Path to the file being analyzed
        file_content: Content of the file
        repo_name: Repository name
        llm_query_fn: Function to call LLM (signature: (prompt, schema) -> response)
        config: Extraction config with 'instruction' and 'example' keys
        existing_dependencies: ExternalDependency nodes (to avoid overlap)
        existing_technologies: Existing Technology nodes (to avoid duplicates)

    Returns:
        Dictionary with success, data (nodes, edges), errors, stats
    """
    errors: list[str] = []
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    try:
        # Build the prompt
        instruction = config.get("instruction", "")
        example = config.get("example", "{}")

        prompt = build_extraction_prompt(
            file_content=file_content,
            file_path=file_path,
            instruction=instruction,
            example=example,
            existing_dependencies=existing_dependencies,
            existing_technologies=existing_technologies,
        )

        # Call LLM
        response = llm_query_fn(prompt, TECHNOLOGY_SCHEMA)

        # Parse response
        technologies = parse_llm_response(response)

        # Build file node ID for edges
        original_path = strip_chunk_suffix(file_path)
        safe_path = original_path.replace("/", "_").replace("\\", "_")
        file_node_id = f"file::{repo_name}::{safe_path}"

        # Build existing tech lookup for deduplication
        existing_tech_names = set()
        if existing_technologies:
            for t in existing_technologies:
                name = (
                    t.get("name", "")
                    .lower()
                    .replace(" ", "")
                    .replace("-", "")
                    .replace("_", "")
                )
                existing_tech_names.add(name)

        # Build nodes and edges
        for tech_data in technologies:
            tech_name = tech_data.get("techName", "")

            # Skip if empty name
            if not tech_name or not tech_name.strip():
                continue

            normalized_name = (
                tech_name.lower().replace(" ", "").replace("-", "").replace("_", "")
            )

            # Skip if already exists
            if normalized_name in existing_tech_names:
                continue

            # Build node
            node = build_technology_node(tech_data, file_path, repo_name)
            nodes.append(node)
            existing_tech_names.add(normalized_name)

            # Build edge: File -> Technology (CONFIGURES)
            edge = {
                "edge_id": generate_edge_id(
                    file_node_id, node["node_id"], "CONFIGURES"
                ),
                "from_node_id": file_node_id,
                "to_node_id": node["node_id"],
                "relationship_type": "CONFIGURES",
                "properties": {
                    "created_at": current_timestamp(),
                },
            }
            edges.append(edge)

    except Exception as e:
        errors.append(
            f"Technology extraction failed for {file_path}: {type(e).__name__}: {e}"
        )

    return {
        "success": len(errors) == 0,
        "data": {"nodes": nodes, "edges": edges},
        "errors": errors,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
        },
    }


def extract_technologies_batch(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Batch extraction - not implemented, use single-file extraction."""
    return {
        "success": True,
        "data": {"nodes": [], "edges": []},
        "errors": [],
        "stats": {},
    }
