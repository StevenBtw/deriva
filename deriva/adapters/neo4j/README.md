# Neo4j Adapter

Shared Neo4j connection service with namespace isolation for multiple data domains.

**Version:** 1.0.0

## Purpose

The Neo4j adapter provides a centralized connection pool to Neo4j that multiple adapters (Graph, ArchiMate) share. Namespace prefixes isolate data while allowing cross-namespace queries when needed.

## Key Exports

```python
from deriva.adapters.neo4j import Neo4jConnection
```

## Basic Usage

```python
from deriva.adapters.neo4j import Neo4jConnection

# Create connection with namespace (context manager)
with Neo4jConnection(namespace="Graph") as conn:
    # Nodes automatically get "Graph:" prefix in labels
    conn.execute_write(
        "CREATE (n:Repository {name: $name})",
        {"name": "my-repo"}
    )

    # Query within namespace
    results = conn.execute_read(
        "MATCH (n:Repository) RETURN n.name as name"
    )

# Manual connection management
conn = Neo4jConnection(namespace="Graph")
conn.connect()
# ... do work ...
conn.disconnect()
```

## Multiple Namespaces

```python
# Graph adapter uses "Graph" namespace
with Neo4jConnection(namespace="Graph") as graph_conn:
    graph_conn.execute_write(
        "CREATE (n:Repository {id: $id})",
        {"id": "repo-1"}
    )

# ArchiMate adapter uses "ArchiMate" namespace
with Neo4jConnection(namespace="ArchiMate") as arch_conn:
    arch_conn.execute_write(
        "CREATE (n:ApplicationComponent {id: $id})",
        {"id": "comp-1"}
    )

# Data is isolated by namespace labels
```

## Configuration

Set via environment variables in `.env`:

```bash
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j
NEO4J_ENCRYPTED=false
NEO4J_MAX_CONNECTION_POOL_SIZE=50
NEO4J_MAX_CONNECTION_LIFETIME=3600
NEO4J_CONNECTION_ACQUISITION_TIMEOUT=60
NEO4J_LOG_LEVEL=INFO
NEO4J_LOG_QUERIES=false
```

## File Structure

```text
deriva/adapters/neo4j/
├── __init__.py           # Package exports
├── manager.py            # Neo4jConnection class
└── docker-compose.yml    # Neo4j container configuration
```

## Neo4jConnection Methods

### Connection Lifecycle

| Method | Description |
|--------|-------------|
| `connect()` | Establish connection to Neo4j |
| `disconnect()` | Close the Neo4j connection |
| `__enter__` / `__exit__` | Context manager support |

### Query Execution

| Method | Description |
|--------|-------------|
| `execute(query, params, database)` | Execute any Cypher query |
| `execute_write(query, params, database)` | Write transaction (CREATE, UPDATE, DELETE) |
| `execute_read(query, params, database)` | Read-only transaction (MATCH, RETURN) |

### Namespace Management

| Method | Description |
|--------|-------------|
| `get_label(base_label)` | Get namespaced label (e.g., `Graph:Repository`) |
| `clear_namespace()` | Delete all nodes/edges in namespace |

### Schema Management

| Method | Description |
|--------|-------------|
| `create_constraint(label, property_key, name)` | Create uniqueness constraint |
| `create_index(label, property_key, name)` | Create index on property |

### Docker Container Management

| Method | Description |
|--------|-------------|
| `start_container()` | Start Neo4j Docker container |
| `stop_container()` | Stop Neo4j Docker container |
| `get_container_status()` | Get container running status |
| `ensure_container_running()` | Start container if not running |

## Namespace Convention

| Adapter | Namespace | Example Labels |
|---------|-----------|----------------|
| Graph | `Graph` | `Graph:Repository`, `Graph:File` |
| ArchiMate | `ArchiMate` | `ArchiMate:ApplicationComponent` |

## Starting Neo4j

Using container management methods:

```python
conn = Neo4jConnection(namespace="Graph")
conn.ensure_container_running()  # Starts if not running
conn.connect()
```

Or manually via Docker:

```bash
cd deriva/adapters/neo4j
docker-compose up -d
```

Neo4j available at:

- Browser UI: <http://localhost:7474>
- Bolt: `bolt://localhost:7687`

## See Also

- [CONTRIBUTING.md](../../../CONTRIBUTING.md) - Architecture and coding guidelines
