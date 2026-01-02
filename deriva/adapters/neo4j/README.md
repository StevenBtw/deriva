# Neo4j Adapter

Shared Neo4j connection service with namespace isolation for multiple data domains.

## Purpose

The Neo4j adapter provides a centralized connection pool to Neo4j that multiple adapters (Graph, ArchiMate) share. Namespace prefixes isolate data while allowing cross-namespace queries when needed.

## Key Exports

```python
from deriva.adapters.neo4j import Neo4jConnection
```

## Basic Usage

```python
from deriva.adapters.neo4j import Neo4jConnection

# Create connection with namespace
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
NEO4J_LOG_QUERIES=false
```

## Neo4jConnection Methods

| Method | Description |
|--------|-------------|
| `connect()` / `disconnect()` | Connection lifecycle |
| `execute(query, params)` | Execute any Cypher query |
| `execute_write(query, params)` | Write transaction |
| `execute_read(query, params)` | Read-only transaction |
| `get_label(type_name)` | Get namespaced label (e.g., `Graph:Repository`) |
| `clear_namespace()` | Delete all nodes/edges in namespace |

## Namespace Convention

| Adapter | Namespace | Example Labels |
|---------|-----------|----------------|
| Graph | `Graph` | `Graph:Repository`, `Graph:File` |
| ArchiMate | `ArchiMate` | `ArchiMate:ApplicationComponent` |

## Starting Neo4j

```bash
cd neo4j_manager
docker-compose up -d
```

Neo4j available at:

- Browser UI: <http://localhost:7474>
- Bolt: `bolt://localhost:7687`

## See Also

- [CONTRIBUTING.md](../../../CONTRIBUTING.md) - Architecture and coding guidelines
