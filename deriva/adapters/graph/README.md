# Graph Adapter

Property graph database for storing repository structure, code elements, and their relationships using Neo4j.

**Version:** 1.0.0

## Purpose

The Graph adapter stores extracted repository information in Neo4j (namespace: `Graph`). It maintains the intermediate representation between raw code and ArchiMate models, including files, directories, type definitions, business concepts, and their relationships.

## Key Exports

```python
from deriva.adapters.graph import (
    GraphManager,           # Main service class
    # Node types
    RepositoryNode,
    DirectoryNode,
    ModuleNode,
    FileNode,
    TypeDefinitionNode,
    MethodNode,
    BusinessConceptNode,
    TechnologyNode,
    ServiceNode,
    ExternalDependencyNode,
    TestNode,
    # Relationship constants
    CONTAINS, DEPENDS_ON, REFERENCES, IMPLEMENTS,
    DECLARES, PROVIDES, EXPOSES, USES, TESTS,
)
```

## Basic Usage

```python
from deriva.adapters.graph import GraphManager, RepositoryNode, FileNode, CONTAINS

with GraphManager() as gm:
    # Add a repository
    repo = RepositoryNode(name="my-app", url="https://github.com/user/my-app")
    gm.add_node(repo)

    # Add a file
    file = FileNode(
        name="main.py",
        path="src/main.py",
        repository_name="my-app",
        file_type="source",
        subtype="python"
    )
    gm.add_node(file)

    # Create relationship
    gm.add_edge(repo.generate_id(), file.generate_id(), CONTAINS)

    # Query nodes
    files = gm.get_nodes_by_type("File")
```

## File Structure

```text
deriva/adapters/graph/
├── __init__.py           # Package exports
├── manager.py            # GraphManager class
├── models.py             # Node types and relationship constants
└── metamodel.py          # Graph metamodel definitions
```

## Node Types

| Node | Purpose |
|------|---------|
| `RepositoryNode` | Root node for a code repository |
| `DirectoryNode` | Directory in the file tree |
| `ModuleNode` | Logical module grouping |
| `FileNode` | Source file with type classification |
| `TypeDefinitionNode` | Class, function, interface, enum |
| `MethodNode` | Method within a type definition |
| `BusinessConceptNode` | Domain concepts (actor, service, entity) |
| `TechnologyNode` | Frameworks, databases, infrastructure |
| `ServiceNode` | Services exposed by the system |
| `ExternalDependencyNode` | External libraries and APIs |
| `TestNode` | Test definitions |

## Relationship Types

| Constant | Purpose |
|----------|---------|
| `CONTAINS` | Hierarchical containment (repo→dir→file) |
| `DEPENDS_ON` | Dependencies between elements |
| `REFERENCES` | File references business concept |
| `IMPLEMENTS` | File implements technology |
| `DECLARES` | Type declares methods |
| `PROVIDES` | Provides a service |
| `EXPOSES` | Exposes an interface |
| `USES` | Uses external dependency |
| `TESTS` | Test tests code element |

## GraphManager Methods

| Method | Description |
|--------|-------------|
| `add_node(node, node_id=None)` | Add node (auto-generates ID if not provided) |
| `add_edge(src_id, dst_id, rel, props)` | Create relationship between nodes |
| `get_node(node_id)` | Retrieve node by ID |
| `get_nodes_by_type(node_type)` | Get all nodes of a type |
| `update_node_property(id, key, val)` | Update single property |
| `delete_node(node_id)` | Delete node and its edges |
| `clear_graph()` | Clear all graph data |
| `query(cypher, params)` | Execute custom Cypher query |

## Data Isolation

Uses Neo4j with namespace `Graph` for label prefixing (e.g., `Graph:Repository`, `Graph:File`), keeping extraction data separate from the ArchiMate namespace.

## See Also

- [CONTRIBUTING.md](../../../CONTRIBUTING.md) - Architecture and coding guidelines
