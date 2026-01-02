# ArchiMate Adapter

Create, validate, and export ArchiMate enterprise architecture models using Neo4j.

## Purpose

The ArchiMate adapter stores derived ArchiMate elements and relationships in Neo4j (namespace: `ArchiMate`), validates them against the ArchiMate 3.1 metamodel, and exports to XML format compatible with the [Archi](https://www.archimatetool.com/) modeling tool.

## Key Exports

```python
from deriva.adapters.archimate import (
    ArchimateManager,      # Main service class
    Element,               # ArchiMate element dataclass
    Relationship,          # ArchiMate relationship dataclass
    ArchiMateMetamodel,    # Metamodel validation rules
    ArchiMateValidator,    # Validation logic
    ArchiMateXMLExporter,  # XML export
)
```

## Basic Usage

```python
from deriva.adapters.archimate import ArchimateManager, Element, Relationship

with ArchimateManager() as am:
    # Create elements
    component = Element(
        name="Authentication Module",
        element_type="ApplicationComponent",
        documentation="Handles user authentication"
    )
    am.add_element(component)

    # Create relationships
    rel = Relationship(
        source=component.identifier,
        target=other.identifier,
        relationship_type="Serving"
    )
    am.add_relationship(rel)

    # Query elements
    elements = am.get_elements(element_type="ApplicationComponent")

    # Export to Archi-compatible XML
    am.export_to_xml("model.archimate", model_name="My Model")
```

## Supported Types

**Element Types** (ArchiMate 3.1):

- Application Layer: `ApplicationComponent`, `ApplicationInterface`, `ApplicationService`, `DataObject`
- Business Layer: `BusinessObject`, `BusinessProcess`, `BusinessFunction`, `BusinessActor`
- Technology Layer: `Node`, `Device`, `SystemSoftware`, `TechnologyService`

**Relationship Types**:

- `Composition`, `Aggregation`, `Assignment`, `Realization`
- `Serving`, `Access`, `Flow`

## ArchimateManager Methods

| Method | Description |
|--------|-------------|
| `add_element(element)` | Add an ArchiMate element |
| `add_relationship(rel)` | Add a relationship between elements |
| `get_element(identifier)` | Get element by ID |
| `get_elements(element_type=None)` | Get all elements (optionally filtered) |
| `get_relationships(source_id=None)` | Get relationships |
| `clear_model()` | Clear all ArchiMate data |
| `export_to_xml(path, model_name)` | Export to Archi XML format |
| `query(cypher, params)` | Execute custom Cypher query |

## Data Isolation

Uses Neo4j with namespace `ArchiMate` for label prefixing (e.g., `ArchiMate:ApplicationComponent`), keeping ArchiMate data separate from the Graph namespace.

## See Also

- [CONTRIBUTING.md](../../../CONTRIBUTING.md) - Architecture and coding guidelines
- [Archi Tool](https://www.archimatetool.com/) - Open source ArchiMate modeling tool
