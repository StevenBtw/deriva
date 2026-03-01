# Deriva Architecture

This document provides a high-level overview of Deriva's architecture, layer responsibilities, and enforced boundaries.

## System Overview

Deriva transforms code repositories into ArchiMate enterprise architecture models through a multi-stage pipeline:

```text
Repository --> Extraction --> Graph --> Derivation --> ArchiMate Model --> Export
```

## Architecture Diagram

```text
+-----------------------------------------------------------------------------+
|                              PRESENTATION LAYER                              |
|  +-----------------------------+    +-------------------------------------+ |
|  |         CLI (cli/)          |    |        Marimo App (app/)            | |
|  |  - Command parsing          |    |  - Interactive notebook UI          | |
|  |  - Progress display         |    |  - Reactive components              | |
|  |  - Benchmark orchestration  |    |  - Configuration forms              | |
|  +--------------+--------------+    +------------------+------------------+ |
|                 |                                      |                    |
|                 +------------------+-------------------+                    |
|                                    v                                        |
+-----------------------------------------------------------------------------+
|                              SERVICES LAYER                                  |
|  +-------------------------------------------------------------------------+|
|  |                        PipelineSession (services/)                       ||
|  |  - Unified API for CLI and App                                          ||
|  |  - Connection lifecycle management                                       ||
|  |  - Pipeline orchestration (extraction, derivation, export)              ||
|  |  - Configuration management                                              ||
|  |  - Benchmarking service                                                  ||
|  +----------------------------------+--------------------------------------+|
|                                     |                                        |
|                    +----------------+----------------+                       |
|                    v                v                v                       |
+-----------------------------------------------------------------------------+
|                    ADAPTERS LAYER              MODULES LAYER                 |
|  +-------------------------------+  +-----------------------------------+   |
|  |   External System Adapters    |  |       Business Logic Modules      |   |
|  |  +---------+ +-------------+  |  |  +-------------+ +-------------+  |   |
|  |  | Grafeo  | |  Database   |  |  |  |  Extraction | |  Derivation |  |   |
|  |  | (grafeo)| |  (database) |  |  |  |             | |             |  |   |
|  |  +---------+ +-------------+  |  |  |  - Business | |  - Prep     |  |   |
|  |  +---------+ +-------------+  |  |  |  - TypeDef  | |  - Generate |  |   |
|  |  |  Graph  | |  ArchiMate  |  |  |  |  - Method   | |  - Refine   |  |   |
|  |  |  (graph)| |  (archimate)|  |  |  |  - Tech     | |             |  |   |
|  |  +---------+ +-------------+  |  |  +-------------+ +-------------+  |   |
|  |  +---------+ +-------------+  |  |                                   |   |
|  |  |   LLM   | | Repository  |  |  |  13 Element Types:                |   |
|  |  |  (llm)  | | (repository)|  |  |  - ApplicationComponent/Interface |   |
|  |  +---------+ +-------------+  |  |  - ApplicationService, DataObject |   |
|  |  +-------------------------+  |  |  - BusinessActor/Event/Function  |   |
|  |  |     TreeSitter          |  |  |  - BusinessObject/Process         |   |
|  |  |    (treesitter)         |  |  |  - Device, Node, SystemSoftware   |   |
|  |  |  Multi-language AST     |  |  |  - TechnologyService              |   |
|  |  +-------------------------+  |  +-----------------------------------+   |
|  +-------------------------------+                                          |
|                    |                              |                          |
|                    +--------------+---------------+                          |
|                                   v                                          |
+-----------------------------------------------------------------------------+
|                              COMMON LAYER                                    |
|  +-------------------------------------------------------------------------+|
|  |                           common/                                        ||
|  |  - Shared utilities (file_utils, time_utils, json_utils)                ||
|  |  - Type definitions and exceptions                                       ||
|  |  - Chunking for large files                                              ||
|  |  - OCEL event logging                                                    ||
|  |  - Document readers (PDF, DOCX)                                          ||
|  +-------------------------------------------------------------------------+|
+-----------------------------------------------------------------------------+
```

## Layer Responsibilities

### Presentation Layer (CLI / App)

| Component | Purpose |
|-----------|---------|
| `cli/` | Headless command-line interface for automation and scripting |
| `app/` | Interactive Marimo notebook for visual configuration and monitoring |

Both components use `PipelineSession` as the sole interface to the backend.

### Services Layer

The orchestration layer providing a unified API:

- **PipelineSession**: Main entry point for all operations
- **Config Service**: Manages extraction/derivation configurations with versioning
- **Benchmarking Service**: Multi-model comparison and consistency analysis
- **OCEL Integration**: Event logging for process mining

### Adapters Layer

External system integrations:

| Adapter | Purpose |
|---------|---------|
| `grafeo/` | Embedded graph database with namespace isolation |
| `database/` | DuckDB for configuration and metadata storage |
| `graph/` | Graph operations (nodes, edges) in "Graph" namespace |
| `archimate/` | ArchiMate model operations in "Model" namespace |
| `llm/` | Multi-provider LLM abstraction with caching |
| `repository/` | Git operations and file system access |
| `treesitter/` | Multi-language AST parsing (Python, JS, Java, C#) |

### Modules Layer

Business logic organized by pipeline stage:

| Module | Purpose |
|--------|---------|
| `extraction/` | Extracts nodes from source code (structural + semantic, includes classification) |
| `derivation/` | Derives ArchiMate elements from graph nodes |
| `analysis/` | Consistency analysis, deviation detection, stability metrics |

### Common Layer

Shared utilities with no internal dependencies:

- File, time, JSON utilities
- Type definitions and exceptions
- Chunking for large file processing
- OCEL event logging
- Document readers (PDF, DOCX)

## Enforced Architectural Boundaries

Deriva uses **per-directory ruff.toml files** to enforce layer separation at lint time. Violations are caught during `ruff check`.

### Dependency Rules

```text
+------------------------------------------------------------------+
|  CLI / App                                                        |
|  - Can import: services                                           |
|  - CANNOT import: adapters, modules, common                       |
+------------------------------------------------------------------+
|  Services                                                         |
|  - Can import: adapters, modules, common                          |
|  - CANNOT import: cli, app                                        |
+------------------------------------------------------------------+
|  Adapters                                                         |
|  - Can import: common                                             |
|  - CANNOT import: modules, services, cli, app                     |
+------------------------------------------------------------------+
|  Modules                                                          |
|  - Can import: common                                             |
|  - CANNOT import: adapters, services, cli, app                    |
+------------------------------------------------------------------+
|  Common                                                           |
|  - Can import: stdlib, third-party only                           |
|  - CANNOT import: adapters, modules, services, cli, app           |
+------------------------------------------------------------------+
```

### Enforcement via ruff.toml

Each layer has a `ruff.toml` file enforcing boundaries:

**deriva/cli/ruff.toml:**

```toml
[lint.flake8-tidy-imports.banned-api]
"deriva.adapters" = { msg = "Architecture violation: CLI should only import from services" }
"deriva.modules" = { msg = "Architecture violation: CLI should only import from services" }
"deriva.common" = { msg = "Architecture violation: CLI should only import from services" }
```

**deriva/adapters/ruff.toml:**

```toml
[lint.flake8-tidy-imports.banned-api]
"deriva.modules" = { msg = "Architecture violation: adapters cannot import from modules" }
"deriva.services" = { msg = "Architecture violation: adapters cannot import from services" }
```

**deriva/modules/ruff.toml:**

```toml
[lint.flake8-tidy-imports.banned-api]
"deriva.adapters" = { msg = "Architecture violation: modules cannot import from adapters" }
"deriva.services" = { msg = "Architecture violation: modules cannot import from services" }
```

**deriva/common/ruff.toml:**

```toml
[lint.flake8-tidy-imports.banned-api]
"deriva.adapters" = { msg = "Architecture violation: common cannot import from adapters" }
"deriva.modules" = { msg = "Architecture violation: common cannot import from modules" }
"deriva.services" = { msg = "Architecture violation: common cannot import from services" }
```

## Data Flow

### Pipeline Stages

```text
1. CLONE         Repository cloned to workspace/repositories/
                              |
2. EXTRACT       +------------+------------+
                 |    Graph Namespace       |
                 |  Repository -> Directory |
                 |  -> File -> TypeDef      |
                 |  -> Method -> Technology |
                 +------------+------------+
                              |
3. DERIVE        +------------+------------+
   (Prep)        |  PageRank, Louvain,     |
                 |  K-core enrichment       |
                 +------------+------------+
                              |
   (Generate)    +------------+------------+
                 |    Model Namespace       |
                 |  ArchiMate Elements      |
                 |  (13 element types)      |
                 +------------+------------+
                              |
   (Refine)      +------------+------------+
                 |  Relationships +         |
                 |  Quality Assurance       |
                 +------------+------------+
                              |
4. EXPORT        +--------> .xml file (Open Exchange ArchiMate format)
```

### Data Storage

| Store | Purpose | Location |
|-------|---------|----------|
| Grafeo (Graph) | Intermediate representation | Embedded (in-memory or `GRAFEO_DB_PATH`) |
| Grafeo (Model) | ArchiMate elements/relationships | Embedded (shared instance) |
| DuckDB | Configuration, metadata | `deriva/adapters/database/sql.db` |
| Workspace | Repositories, benchmarks, exports | `workspace/` |

## Key Design Decisions

1. **Services as API Layer**: CLI and App only interact with the backend through `PipelineSession`, ensuring consistent behavior and single point of change.

2. **Namespace Isolation**: Grafeo uses label prefixes (`Graph:`, `Model:`) to separate extraction data from ArchiMate model data in a single embedded database.

3. **Configuration Versioning**: All config changes create new versions, enabling rollback and A/B testing during optimization.

4. **Multi-Language AST**: Tree-sitter enables deterministic code analysis across Python, JavaScript, Java, and C# without LLM costs.

5. **Graph-First Derivation**: PageRank, Louvain communities, and k-core metrics guide LLM derivation, improving consistency and reducing hallucination.

## See Also

- [README.md](README.md) - Quick start and usage guide
- [CONTRIBUTING.md](CONTRIBUTING.md) - Development setup and coding guidelines
- [BENCHMARKS.md](BENCHMARKS.md) - LLM benchmarking and optimization workflow
