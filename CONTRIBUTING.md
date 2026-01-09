# Contributing to Deriva

[![codecov](https://codecov.io/gh/StevenBtw/Deriva/graph/badge.svg?token=A3H2COO119)](https://codecov.io/gh/StevenBtw/Deriva)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://docs.astral.sh/uv/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://docs.astral.sh/ruff/)
[![Typing: ty](https://img.shields.io/badge/typing-ty-EFC621.svg)](https://docs.astral.sh/ty/)

Thanks for your interest in contributing to Deriva!

**Python 3.14+** is required. The project uses modern Python features and is developed with 3.14 in mind.

**Tooling:** We use [uv](https://docs.astral.sh/uv/) for package management, [Ruff](https://docs.astral.sh/ruff/) for linting/formatting, and [ty](https://docs.astral.sh/ty/) for type checking.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/StevenBtw/deriva.git
cd Deriva

# Copy environment template
cp .env.example .env
# Edit .env with your configuration (Neo4j, LLM keys, etc.)

# Install with dev dependencies
uv sync --all-extras

# Run the marimo notebook
uv run marimo edit deriva/app/app.py

# Run linter
uv run ruff check .

# Run type checker
uv run ty check .
```

## Architecture

Deriva follows a **layered architecture** with strict separation of concerns:

- **app/app.py (Marimo)**: Visual UI for configuration and pipeline execution
- **cli/cli.py**: Headless CLI for automation and scripting
- **Services**: Shared orchestration layer with `PipelineSession` as the unified API
- **Adapters**: Stateful services for I/O, persistence, connections
- **Modules**: Pure functions for business logic transformations

**Key Principle**: Both Marimo and CLI use `PipelineSession` from the services layer. This provides a unified API for lifecycle management, queries, and orchestration. Configuration lives in DuckDB (single source of truth). Data flows through pure transformations, with I/O isolated to adapters.

### Architectural Boundaries (Enforced by Ruff)

```
CLI      → services only (PipelineSession is the API)
App      → services only (PipelineSession is the API)
Services → adapters, modules, common
Adapters → common only (NOT modules or services)
Modules  → common only (NOT adapters or services)
Common   → stdlib and third-party only
```

These boundaries are enforced at lint time via Ruff's `TID251` rule with per-layer `ruff.toml` files.

<details>
<summary><strong>Architecture Overview</strong></summary>

### Component Hierarchy

```
src/
├── app/
│   ├── app.py               - Marimo Notebook: Visual UI + uses PipelineSession
│   └── layouts/             - Marimo UI layout components
├── cli/
│   └── cli.py               - Headless CLI + uses PipelineSession
│
├── services/ (Shared orchestration layer)
│   ├── session.py           - PipelineSession: unified API for CLI + Marimo
│   ├── config.py            - Config CRUD (read/write DuckDB settings)
│   ├── extraction.py        - Run extraction step
│   ├── derivation.py        - Run derivation step
│   ├── pipeline.py          - Orchestrate full pipeline
│   └── benchmarking.py      - Multi-model benchmarking and analysis
│
├── common/ (Shared utilities)
│   ├── types.py     - Shared TypedDicts, Protocols, ProgressReporter
│   ├── logging.py   - Pipeline logging (JSON Lines)
│   └── utils.py     - File encoding, helpers
│
├── adapters/ (Stateful I/O services)
│   ├── database/    - DuckDB configuration storage
│   ├── neo4j/       - Neo4j connection pool
│   ├── repository/  - Git operations
│   ├── graph/       - Graph CRUD (namespace: Graph)
│   ├── archimate/   - ArchiMate CRUD (namespace: Model)
│   └── llm/         - LLM provider abstraction (Azure, OpenAI, Anthropic, Ollama)
│
├── common/ (Shared utilities)
│   ├── types.py     - Shared TypedDicts and Protocols
│   ├── logging.py   - Pipeline logging (JSON Lines)
│   ├── chunking.py  - File chunking with overlap support
│   └── utils.py     - File encoding, helpers
│
└── modules/ (Pure business logic)
    └── analysis/
        ├── consistency.py    - Model consistency checks
        ├── deviation.py      - Deviation analysis
        └── types.py          - Shared analysis types
    └── extraction/
        ├── base.py           - Shared extraction utilities (ID generation, deduplication)
        ├── classification.py - File type classification
        ├── repository.py     - Repository node extraction
        ├── directory.py      - Directory node extraction
        ├── file.py           - File node extraction (with type/subtype)
        ├── type_definition.py - Classes/functions (AST for Python, LLM for others)
        ├── method.py         - Methods within type definitions
        ├── business_concept.py - Domain concepts (LLM)
        ├── technology.py     - Frameworks/libraries detection
        ├── external_dependency.py - External dependencies
        ├── test.py           - Test definitions
        ├── ast_extraction.py - Python AST parsing
        └── input_sources.py  - Input source filtering
    └── derivation/
        ├── base.py           - Shared utilities (prompts, parsing, graph filtering)
        ├── application_component.py - ApplicationComponent derivation
        ├── application_interface.py - ApplicationInterface derivation
        ├── application_service.py   - ApplicationService derivation
        ├── business_actor.py        - BusinessActor derivation
        ├── business_event.py        - BusinessEvent derivation
        ├── business_function.py     - BusinessFunction derivation
        ├── business_object.py       - BusinessObject derivation
        ├── business_process.py      - BusinessProcess derivation
        ├── data_object.py           - DataObject derivation
        ├── device.py                - Device derivation
        ├── node.py                  - Node derivation
        ├── system_software.py       - SystemSoftware derivation
        └── technology_service.py    - TechnologyService derivation
```

### Layer Responsibilities

```
┌─────────────────┐         ┌─────────────────┐
│     Marimo      │         │      CLI        │
│  (config + UI)  │         │   (headless)    │
└────────┬────────┘         └────────┬────────┘
         │                           │
         └───────────┬───────────────┘
                     │
              ┌──────▼──────┐
              │ PipelineSession │  ← unified API
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │  Services   │  ← orchestration functions
              └──────┬──────┘
                     │
         ┌───────────┼───────────┐
         │           │           │
  ┌──────▼──────┐ ┌──▼───┐ ┌─────▼─────┐
  │  Adapters   │ │Modules│ │  Common   │
  │    (I/O)    │ │(pure) │ │ (shared)  │
  └─────────────┘ └──────┘ └───────────┘
```

### Data Flow Pattern

```
User clicks "Run Pipeline" in app/app.py  OR  runs `deriva run` in CLI
    ↓
┌─────────────────────────────────────────────────────────────┐
│ PIPELINESESSION (unified API for CLI + Marimo)              │
├─────────────────────────────────────────────────────────────┤
│ with PipelineSession() as session:                          │
│     session.run_extraction(repo_name="my-repo")             │
│     session.run_derivation()                                │
│     session.export_model("output.archimate")                │
│                                                             │
│ # For reactive UI (Marimo):                                 │
│     stats = session.get_graph_stats()                       │
│     elements = session.get_archimate_elements()             │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ EXTRACTION (inside services.extraction)                     │
├─────────────────────────────────────────────────────────────┤
│ 1. Load config from DuckDB via services.config              │
│ 2. Get repos from RepositoryManager                         │
│ 3. Call modules.extraction.classification [PURE]            │
│ 4. Call modules.extraction.structural/* [PURE]              │
│ 5. Call modules.extraction.llm/* [PURE + LLM]               │
│ 6. Persist via GraphManager.add_node() [I/O]                │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ DERIVATION (inside services.derivation)                     │
├─────────────────────────────────────────────────────────────┤
│ Phases: enrich → generate → refine                          │
│ 1. Enrich: Graph enrichment (PageRank, communities, k-core) │
│ 2. Generate: Query candidates with enrichment data [I/O]    │
│ 3. Generate: Call modules.derivation.{element}.generate()   │
│ 4. Generate: Persist via ArchimateManager.add_element()     │
│ 5. Relationship: Derive relationships per-element or batch  │
└─────────────────────────────────────────────────────────────┘
    ↓
Export via ArchimateManager.export_to_xml() [I/O]
    ↓
Marimo: displays results in UI  |  CLI: prints summary to stdout
```

### Notebook Structure

| Column | Purpose |
|--------|---------|
| Column 0 | Run Deriva (pipeline buttons, status callouts) |
| Column 1 | Configuration (runs, repos, Neo4j, graph stats, ArchiMate, LLM) |
| Column 2 | Extraction Settings (file types, extraction step config) |
| Column 3 | Derivation Settings (14 element types across Business/Application/Technology layers) |

The app/app.py uses PipelineSession for all operations.

### Quick Reference

| Component | Purpose | Can Do | Cannot Do |
|-----------|---------|--------|-----------|
| **app/app.py** | Visual UI | Display UI, use PipelineSession | Import adapters/modules directly |
| **cli/cli.py** | Headless CLI | Parse args, use PipelineSession, print output | Import adapters/modules directly |
| **PipelineSession** | Unified API | Lifecycle, queries, orchestration | Business logic |
| **Services** | Orchestration | Load config, run pipeline steps, coordinate adapters | Direct I/O, pure business logic |
| **Adapters** | I/O & Persistence | Read .env, connect to services, CRUD | Import other adapters, pure logic |
| **Modules** | Business Logic | Pure transformations, return data/errors | I/O, import adapters, external state |

</details>

---

## Code Style

### Naming at a Glance

| Element | Convention | Example |
|---------|------------|---------|
| Files/modules | `snake_case` | `file_utils.py`, `manager.py` |
| Classes | `PascalCase` | `GraphManager`, `ExtractionResult` |
| Functions/methods | `snake_case` | `read_file_with_encoding()` |
| Variables | `snake_case` | `file_path`, `element_type` |
| Constants | `UPPER_SNAKE_CASE` | `DEFAULT_TIMEOUT`, `MAX_RETRIES` |
| Private | `_prefix` | `_internal_cache`, `_serialize_value()` |
| TypedDicts | `PascalCase` | `PipelineResult`, `LLMDetails` |
| Protocols | `PascalCase` + descriptive | `ExtractionFunction`, `Serializable` |

### Architectural Rules

- **Adapters**: Stateful, own schemas, provide CRUD, raise exceptions
- **Modules**: Pure functions, no I/O, return data/errors as dicts
- **app/app.py**: Orchestration only, no business logic
- **Single config source**: All configuration in `.env` (no YAML)

### File Structure

Every Python file follows this structure:

```python
"""Module-level docstring explaining what this module does."""

from __future__ import annotations  # Always include

# Standard library
import json
from pathlib import Path
from typing import Any, Protocol, TypedDict

# Third-party
from pydantic import BaseModel

# Local imports
from common.types import PipelineResult
from .models import RepositoryNode

# Module constants
DEFAULT_TIMEOUT = 30

# Public API
__all__ = ["process_file", "FileProcessor"]


# =============================================================================
# Section Header (for longer files)
# =============================================================================

class FileProcessor:
    """Class implementation..."""
    pass
```

### Module Organization

**Package style** (directory with multiple files) - use when a module has related files:

```text
adapters/graph/
├── __init__.py      # Re-exports: from .manager import GraphManager
├── manager.py       # Main class
├── models.py        # Data models
└── queries.py       # Complex queries (if needed)
```

**Flat style** (single file) - use for standalone utilities:

```text
common/
├── file_utils.py    # Just utility functions
├── time_utils.py
└── types.py
```

Rule of thumb: Start flat, graduate to a package when you need `models.py` or other supporting files.

### Import Rules

1. **Always start with** `from __future__ import annotations`
2. **Group imports**: stdlib → third-party → local (blank line between groups)
3. **Relative imports** for same-package: `from .models import Node`
4. **Absolute imports** for cross-package: `from common.types import Result`
5. **Multi-line imports** when 3+ items from same module

<details>
<summary><strong>Type Hints</strong></summary>

#### Modern Syntax (Python 3.10+)

```python
# Unions - use | not Optional or Union
def get_user(id: int) -> User | None:
    ...

# Collections - use lowercase builtins
items: list[str] = []
mapping: dict[str, int] = {}
```

#### TypedDict for Structured Data

Use TypedDict for JSON-like structures:

```python
class LLMDetails(TypedDict, total=False):
    """Tracks LLM call metadata for observability."""
    prompt: str
    response: str
    tokens_in: int
    tokens_out: int
    cache_used: bool
```

#### Protocol for Interfaces

Use Protocol for duck typing with type safety:

```python
class ExtractionFunction(Protocol):
    """Contract for extraction functions."""

    def __call__(
        self,
        file_path: str,
        file_content: str,
        repo_name: str,
        llm_query_fn: Callable,
        config: dict[str, Any]
    ) -> ExtractionResult:
        ...
```

#### Dataclass for Concrete Objects

Use dataclass for objects with behavior or identity:

```python
@dataclass
class RepositoryNode:
    """Represents a code repository in the knowledge graph."""
    name: str
    url: str
    created_at: datetime
    branch: str | None = None

    def generate_id(self) -> str:
        return f"Repository_{self.name}"
```

#### When to Use What

| Use | When |
|-----|------|
| `TypedDict` | Data shapes (JSON, API responses, result dicts) |
| `@dataclass` | Objects with identity/behavior (nodes, entities) |
| `BaseModel` | External data validation (API input, config files) |

</details>

<details>
<summary><strong>Docstrings</strong></summary>

**Core principle:** Explain the *why*, not the *what*. The code shows what happens; docstrings explain why it matters.

#### Module Docstrings

Brief. What is this module's job?

```python
"""JSON parsing utilities for Deriva.

Handles the messy reality of LLM output that's almost-but-not-quite valid JSON.
"""
```

#### Class Docstrings

What does this class represent? Why does it exist?

```python
class GraphManager:
    """
    High-level interface for Neo4j graph operations.

    Wraps Neo4j driver complexity and provides domain-specific operations
    like "add repository" rather than raw Cypher. Uses connection pooling
    internally so you can safely create instances per-request.
    """
```

#### Function Docstrings

Focus on behavior, edge cases, and non-obvious aspects:

```python
def read_file_with_encoding(file_path: Path) -> str | None:
    """
    Read a file with automatic encoding detection.

    Handles the encoding mess you find in real codebases: UTF-8 with/without
    BOM, UTF-16 variants, and falls back to Latin-1 for binary-ish text files.
    Returns None rather than raising - caller decides how to handle.

    Args:
        file_path: Path to the file

    Returns:
        File content as string, or None if reading fails
    """
```

#### When to Skip Docstrings

Trivial methods where the name says everything:

```python
def __enter__(self):
    self.connect()
    return self
```

</details>

<details>
<summary><strong>Comments</strong></summary>

Comments explain **why**, not **what**.

#### Good Comments

```python
# BOM markers indicate encoding - check before trying UTF-8
if raw.startswith(b'\xff\xfe'):
    return raw.decode('utf-16-le')

# Neo4j MERGE needs deterministic IDs to avoid duplicates
node_id = f"Repository_{repo_name}"

# LLMs sometimes return markdown-wrapped JSON
content = content.strip().removeprefix("```json").removesuffix("```")
```

#### Bad Comments

```python
# Increment counter  <- obvious from code
counter += 1

# Check if file exists  <- obvious from code
if file_path.exists():
```

#### Section Headers

Use for organizing longer files (100+ lines):

```python
# =============================================================================
# Graph Query Methods
# =============================================================================
```

</details>

<details>
<summary><strong>Error Handling</strong></summary>

#### Be Specific

```python
# Good - catch what you expect
try:
    data = json.loads(content)
except json.JSONDecodeError as e:
    return ParseResult(success=False, error=f"Invalid JSON: {e}")

# Bad - catches everything
try:
    data = json.loads(content)
except Exception:
    return None
```

#### Return vs Raise

- **Return None/Result** for expected failures (file not found, parse error)
- **Raise** for unexpected failures or contract violations

```python
def read_file(path: Path) -> str | None:
    """Returns None if file can't be read."""
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def connect(self) -> None:
    """Raises ConnectionError if connection fails."""
    try:
        self._driver = neo4j.GraphDatabase.driver(self._uri)
    except Exception as e:
        raise ConnectionError(f"Failed to connect: {e}") from e
```

</details>

<details>
<summary><strong>Python 3.14 Features</strong></summary>

Since we're on Python 3.14, use these modern features:

#### Deferred Annotations (PEP 649)

No need to quote forward references:

```python
from __future__ import annotations

class Node:
    parent: Node | None = None  # Works! No quotes needed
```

#### Exception Syntax (PEP 758)

Cleaner multi-exception handling:

```python
# New way (Python 3.14+)
except TimeoutError, ConnectionRefusedError:
    handle_network_error()
```

#### New UUID Functions

```python
from uuid import uuid7

# uuid7 is time-ordered AND random - better than uuid4
id = uuid7()
```

#### Path Improvements

```python
from pathlib import Path

src = Path("source.txt")
dst = Path("dest.txt")

# New methods
src.copy(dst)
src.move(dst)
```

#### New datetime Methods

```python
from datetime import date, time

# Parse directly on date/time classes
d = date.strptime("2024-01-15", "%Y-%m-%d")
```

</details>

<details>
<summary><strong>Formatting</strong></summary>

#### String Quotes

Use double quotes consistently:

```python
# Good
name = "Deriva"
data = {"key": "value"}

# Avoid
name = 'Deriva'
```

#### Line Length

180 characters max (configured in `pyproject.toml`). But prefer shorter when readable.

#### Checklist Before Committing

- [ ] `from __future__ import annotations` at top
- [ ] Imports organized: stdlib → third-party → local
- [ ] Type hints on all public functions
- [ ] Docstrings on all public classes and functions
- [ ] No `print()` statements (use logging)
- [ ] Double quotes for strings
- [ ] `__all__` defined for modules with public API
- [ ] `ruff check` passes

</details>

<details>
<summary><strong>Adapter Rules</strong></summary>

### Purpose

- Complex, stateful services that manage persistence and external systems
- Own their schemas, metamodels, and validation logic
- Provide CRUD operations for their domain
- Do **NOT** contain business logic (that's in modules)

### Lifecycle

- **Singleton pattern**: One instance per adapter per marimo session
- Initialized **once** in app.py, passed to cells that need them
- Maintain **persistent connections** for session lifetime
- Support **auto-reconnect** with retry logic (max 3 attempts, exponential backoff)
- Cleanup via `__del__` or `__exit__` methods

### Configuration

- **Read .env** in `__init__` using `python-dotenv`
- **Cache** config values (don't re-read on every operation)
- Provide **defaults** for optional settings

### Dependencies

- Can import **infrastructure adapters** (e.g., GraphManager ← Neo4jConnection)
- **Cannot** import other domain adapters (e.g., GraphManager ✗← ArchimateManager)
- **Cannot** import modules

### Error Handling

- **Raise exceptions** with clear messages
- Use **custom exception classes** (e.g., `GraphError`, `ArchimateError`)
- Retry transient errors (connection issues)
- Do **NOT** catch and silence errors

### Interface

- Export via `__init__.py` (e.g., `from .manager import GraphManager`)
- Consistent method naming: `add_*`, `get_*`, `update_*`, `delete_*`, `query_*`
- Return **data** (dicts, lists, dataclasses), not side effects
- Accept **parameters** from marimo (don't read global state)

### Adapter Structure

```text
adapters/{name}/
├── __init__.py           # Re-export manager class and models
├── manager.py            # Main manager class with all CRUD logic
└── models.py             # Data models with generate_id() methods
```

### ID Generation Pattern

Node/element models include a `generate_id()` method for consistent ID generation:

```python
@dataclass
class RepositoryNode:
    name: str
    url: str
    # ...

    def generate_id(self) -> str:
        """Generate a unique ID for this node."""
        return f"Repository_{self.name}"
```

The adapter's `add_node()` method auto-generates IDs when not provided:

```python
def add_node(self, node: GraphNode, node_id: str | None = None) -> str:
    if node_id is None:
        node_id = node.generate_id()
    # ... persist to database
```

</details>

<details>
<summary><strong>LLM Manager</strong></summary>

### Overview

The LLM adapter (`adapters/llm/`) provides a unified interface for multiple LLM providers with caching and structured output support.

**Supported Providers:**

- **Azure OpenAI** - Enterprise Azure deployments
- **OpenAI** - Direct OpenAI API
- **Anthropic** - Claude models
- **Ollama** - Local LLM inference (no API key required)

### Basic Usage

```python
from adapters.llm import LLMManager

llm = LLMManager()  # Reads provider config from .env
response = llm.query("What is Python?")

if response.response_type == "live":
    print(response.content)
elif response.response_type == "cached":
    print(f"From cache: {response.content}")
else:
    print(f"Error: {response.error}")
```

### Structured Output with Pydantic

Use `response_model` to get validated, type-safe responses:

```python
from pydantic import BaseModel, Field
from adapters.llm import LLMManager

class BusinessConcept(BaseModel):
    name: str = Field(description="Concept name")
    type: str = Field(description="actor, service, process, etc.")
    description: str = Field(description="Brief description")

llm = LLMManager()
result = llm.query(
    prompt="Extract the main business concept from: ...",
    response_model=BusinessConcept
)

# result is a validated BusinessConcept instance
print(result.name)  # Type-safe, IDE autocomplete works
```

### Provider Configuration

Set provider via `LLM_PROVIDER` in `.env`:

```bash
# Use local Ollama
LLM_PROVIDER=ollama
LLM_OLLAMA_MODEL=llama3.2
LLM_OLLAMA_API_URL=http://localhost:11434/api/chat

# Use Azure OpenAI
LLM_PROVIDER=azure
LLM_AZURE_API_URL=https://your-resource.openai.azure.com/...
LLM_AZURE_API_KEY=your-key
LLM_AZURE_MODEL=gpt-4o-mini
```

### Direct Provider Usage

For advanced use cases, create providers directly:

```python
from adapters.llm import create_provider, ProviderConfig

config = ProviderConfig(
    api_url="http://localhost:11434/api/chat",
    api_key=None,
    model="llama3.2"
)
provider = create_provider("ollama", config)

result = provider.complete(
    messages=[{"role": "user", "content": "Hello"}],
    temperature=0.7
)
print(result.content)
```

### Response Types

All queries return one of three Pydantic response types:

| Type             | When           | Key Fields                          |
|------------------|----------------|-------------------------------------|
| `LiveResponse`   | Fresh API call | `content`, `usage`, `finish_reason` |
| `CachedResponse` | From cache     | `content`, `cache_key`, `cached_at` |
| `FailedResponse` | Error occurred | `error`, `error_type`               |

### Caching

- Responses are cached to `workspace/cache/` by default
- Cache key = SHA256(prompt + model + schema)
- Disable with `LLM_NOCACHE=true` or `use_cache=False`
- Errors are also cached to prevent retry storms

</details>

<details>
<summary><strong>Module Rules</strong></summary>

### Purpose

- **Pure business logic** - data transformations only
- Abstracts complex operations from marimo cells
- Do **NOT** manage state, connections, or I/O

### Purity

- **Pure functions**: Same input → same output
- **No side effects**: Don't write to files, databases, network
- **No state**: No class variables, no module-level state
- Return **data** (dicts, lists, dataclasses), never `None`
- **No adapter imports** (receive adapter data via parameters)
- **No I/O operations** (marimo handles all I/O via adapters)

### Dependencies

- Can import **Python stdlib** (pathlib, json, re, typing, dataclasses, etc.)
- Can import **each other** (e.g., orchestration ← classification)
- Can use **external libs** if pure (e.g., polars for data transforms)
- **Cannot** import adapters
- **Cannot** import marimo
- **Cannot** import UI libraries

### Error Handling

- Return **error data** in results (e.g., `{'errors': [...]}`)
- Use **type hints** for clarity
- Do **NOT** raise exceptions (return errors as data)

### Result Structure

```python
{
    'success': bool,
    'data': {...},
    'errors': [str],
    'stats': {...}
}
```

</details>

<details>
<summary><strong>Module Pattern</strong></summary>

### Shared Types (`common/types.py`)

All pipeline modules use shared TypedDicts and Protocols for consistent interfaces:

```python
from common.types import (
    # Base result type - all modules return this structure
    BaseResult,       # success, errors, stats
    LLMDetails,       # prompt, response, tokens_in, tokens_out, cache_used

    # Extraction types
    ExtractionResult, # BaseResult + data: {nodes, edges} + llm_details
    BatchExtractionResult,

    # Derivation types
    DerivationResult, # BaseResult + data: {elements_created, issues} + llm_details
    DerivationConfig, # step_name, phase, input_graph_query, instruction, example

    # Function protocols for type safety
    ExtractionFunction,
    DerivationFunction,
)
```

### Base Files (`base.py`)

Each module folder has a `base.py` file with shared utilities:

| Module | Base File | Provides |
|--------|-----------|----------|
| `extraction/` | `base.py` | `generate_node_id()`, `parse_json_response()`, `create_extraction_result()` |
| `derivation/llm/` | `base.py` | `DERIVATION_SCHEMA`, `build_derivation_prompt()`, `parse_derivation_response()` |
| `derivation/graph/` | `base.py` | Graph algorithm utilities for refinement phase |

All base files also provide:

- `current_timestamp()` - UTC ISO format
- `create_empty_llm_details()` - Initialize LLM details dict
- `extract_llm_details_from_response()` - Parse LLM response metadata

### Lazy Module Loading (`services/derivation.py`)

Derivation modules are loaded lazily by element type:

```python
# services/derivation.py
def _load_element_module(element_type: str) -> Any:
    """Lazily load element generation module."""
    if element_type == "ApplicationComponent":
        from deriva.modules.derivation import application_component as module
    elif element_type == "BusinessObject":
        from deriva.modules.derivation import business_object as module
    # ... other element types
    return module

def generate_element(graph_manager, archimate_manager, llm_query_fn, element_type, ...):
    """Route to appropriate module based on element_type."""
    module = _load_element_module(element_type)
    return module.generate(graph_manager, archimate_manager, ...)
```

### Adding New Element Types

To add a new derivation element type (e.g., `Contract`):

1. Create `modules/derivation/contract.py` with a `generate()` function:

   ```python
   """Contract element derivation."""
   from __future__ import annotations

   from deriva.modules.derivation.base import (
       Candidate, GenerationResult, batch_candidates, build_derivation_prompt,
       build_element, get_enrichments, parse_derivation_response, query_candidates,
       DERIVATION_SCHEMA,
   )

   def generate(
       graph_manager, archimate_manager, engine, llm_query_fn,
       query: str, instruction: str, example: str,
       max_candidates: int, batch_size: int,
       temperature: float | None = None, max_tokens: int | None = None,
   ) -> GenerationResult:
       # 1. Get enrichments from DuckDB
       enrichments = get_enrichments(engine)
       # 2. Query candidates using the Cypher query
       candidates = query_candidates(graph_manager, query, enrichments)
       # 3. Filter/limit candidates
       candidates = candidates[:max_candidates]
       # 4. Batch and process with LLM
       # ... (see existing modules for full pattern)
       return GenerationResult(success=True, elements_created=count, ...)
   ```

2. Register in `services/derivation.py` `_load_element_module()`:

   ```python
   elif element_type == "Contract":
       from deriva.modules.derivation import contract as module
   ```

3. Add derivation config in `adapters/database/data/derivation_config.json`

</details>

<details>
<summary><strong>Module Reference</strong></summary>

### Core Modules

#### `extraction/classification.py`
**Goal:** Classify files by type based on the file type registry.

```python
def classify_files(
    file_paths: List[str],
    file_type_registry: List[Dict[str, str]]
) -> Dict[str, Any]:
    """
    Returns: {
        'classified': [...],   # Files with known types
        'undefined': [...],    # Files with unknown extensions
        'stats': {...},
        'errors': [...]
    }
    """
```

**Rules:**
- Classification priority: full filename → wildcard pattern → extension
- Never raises exceptions - returns errors in result dict
- Registry comes from DatabaseManager (passed as data, not manager)

#### `logging.py`
**Goal:** JSON Lines logging for pipeline runs with configurable verbosity.

```python
class LogLevel(int, Enum):
    PHASE = 1   # High-level: classification, extraction, derivation
    STEP = 2    # Steps: Repository, Directory, File, etc.
    DETAIL = 3  # Item-level: each file, node, edge

class PipelineLogger:
    def log(self, level: int, phase: str, status: str, ...) -> None
    def get_entries(self, min_level: int = 1) -> List[LogEntry]
```

**Rules:**
- Logs stored in `logs/run_{id}/log_{datetime}.jsonl`
- Use level 1 for phase start/end, level 2 for steps, level 3 for details
- Logger instance created in app.py, passed to extraction functions

#### `utils.py`
**Goal:** Shared utility functions for file handling and data processing.

```python
def read_file_with_encoding(file_path: Path) -> Optional[str]:
    """Auto-detect encoding (UTF-8, UTF-16, Latin-1 fallback)."""
```

**Rules:**
- Pure functions only - no state
- Used by extraction modules for file reading

---

### Extraction Modules (`modules/extraction/`)

Extraction is organized by method:

- **`structural/`** - File system based extraction (no LLM required)
- **`llm/`** - LLM-based semantic extraction
- **`ast/`** - AST-based extraction (future)

All extraction modules follow the same pattern:

```python
# Build a single node
def build_{node_type}_node(data: Dict) -> Dict[str, Any]

# Extract from files (structural) or via LLM (semantic)
def extract_{node_type}s(...) -> Dict[str, Any]:
    """
    Returns: {
        'nodes': [...],
        'edges': [...],
        'stats': {...},
        'errors': [...]
    }
    """
```

#### Structural Extraction (`structural/`)

| Module | Node Type | Input | Purpose |
|--------|-----------|-------|---------|
| `repository.py` | Repository | repo metadata | Root node for the repository |
| `directory.py` | Directory | file paths | Directory tree structure |
| `file.py` | File | file paths + classification | File nodes with type info |

#### LLM-Based Extraction (`llm/`)

| Module | Node Type | Input | Purpose |
|--------|-----------|-------|---------|
| `type_definition.py` | TypeDefinition | source files | Classes, functions, interfaces |
| `method.py` | Method | TypeDefinition nodes | Methods within type definitions |
| `business_concept.py` | BusinessConcept | source files | Domain concepts and entities |
| `technology.py` | Technology | config files | Frameworks, databases, infrastructure |
| `external_dependency.py` | ExternalDependency | dependency files | Libraries and external integrations |
| `test.py` | Test | test files | Test definitions and coverage |

**LLM Extraction Pattern:**

```python
# Each LLM module exports:
def build_extraction_prompt(files: List[Dict], config: Dict) -> str
def parse_llm_response(response: str) -> List[Dict]
{NODE_TYPE}_SCHEMA: Dict  # JSON schema for validation

# Batch extraction for multiple files
def extract_{type}s_batch(
    files: List[Dict],
    config: Dict,
    llm_response: str  # LLM called by app.py, not module
) -> Dict[str, Any]
```

**Rules for LLM modules:**
- Module builds prompt, app.py calls LLM, module parses response
- Never call LLM directly from module (purity)
- Include JSON schema for response validation
- Handle malformed LLM responses gracefully (return errors, don't raise)

#### `input_sources.py`
**Goal:** Parse and filter input source specifications for extraction steps.

```python
def parse_input_sources(config: Dict) -> Dict[str, List[str]]
def filter_files_by_input_sources(files: List, specs: List[str]) -> List
def has_file_sources(config: Dict) -> bool
def has_node_sources(config: Dict) -> bool
```

**Rules:**
- Supports file type specs (`source:python`, `config:*`) and node type specs (`TypeDefinition`, `File`)
- Used by extraction orchestration to determine inputs for each step

---

### Derivation Modules (`modules/derivation/`)

Derivation uses a hybrid approach combining graph algorithms with LLM:

- **enrich phase** - Graph enrichment (PageRank, Louvain communities, k-core analysis)
- **generate phase** - LLM-based element derivation using graph metrics for filtering
- **refine phase** - Cross-graph validation (duplicates, orphans, structural consistency)

**Goal:** Transform Graph nodes into ArchiMate elements across Business, Application, and Technology layers.

#### Base Module (`base.py`)

Provides shared utilities for all derivation modules:

```python
from deriva.modules.derivation import (
    Candidate,              # Dataclass for candidate nodes with enrichment data
    query_candidates,       # Execute Cypher and return enriched candidates
    batch_candidates,       # Split candidates into batches for LLM
    build_derivation_prompt,    # Build LLM prompt for elements
    build_relationship_prompt,  # Build LLM prompt for relationships
    parse_derivation_response,  # Parse LLM element response
    build_element,              # Build ArchiMate element from LLM output
    DERIVATION_SCHEMA,          # JSON schema for element derivation
    RELATIONSHIP_SCHEMA,        # JSON schema for relationship derivation
)
```

#### Element Modules

Each element type has its own module with a `generate()` function:

| Layer | Module | Element Type | Purpose |
|-------|--------|--------------|---------|
| **Business** | `business_actor.py` | BusinessActor | Roles, users, stakeholders |
| | `business_event.py` | BusinessEvent | Business events and triggers |
| | `business_function.py` | BusinessFunction | Business capabilities |
| | `business_object.py` | BusinessObject | Data entities, domain objects |
| | `business_process.py` | BusinessProcess | Activities, workflows |
| **Application** | `application_component.py` | ApplicationComponent | Software modules, packages |
| | `application_interface.py` | ApplicationInterface | APIs, interfaces |
| | `application_service.py` | ApplicationService | Endpoints, services |
| | `data_object.py` | DataObject | Files, data structures |
| **Technology** | `device.py` | Device | Hardware, containers |
| | `node.py` | Node | Compute infrastructure |
| | `system_software.py` | SystemSoftware | Operating systems, runtimes |
| | `technology_service.py` | TechnologyService | Infrastructure services |

#### Module Pattern

Each element module exports a `generate()` function:

```python
def generate(
    graph_manager: GraphManager,
    archimate_manager: ArchimateManager,
    engine: Any,  # DuckDB connection for enrichment
    llm_query_fn: Callable,
    query: str,           # Cypher query for candidates
    instruction: str,     # LLM derivation instructions
    example: str,         # Example output
    max_candidates: int,
    batch_size: int,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> GenerationResult:
    """Returns GenerationResult with success, elements_created, created_elements, errors."""
```

**Rules for derivation modules:**
- Query candidates using config's Cypher query
- Enrich candidates with graph metrics (PageRank, community, k-core)
- Filter and batch candidates before sending to LLM
- Persist elements via `archimate_manager.add_element()`
- Configuration comes from DuckDB (instruction, example, query, etc.)

</details>

<details>
<summary><strong>Configuration Pattern</strong></summary>

### Two Types of Configuration

Deriva has two configuration systems:

1. **Environment variables (`.env`)** - Runtime settings for adapters (connections, API keys, paths)
2. **Database configs (DuckDB)** - Pipeline behavior (extraction steps, derivation prompts, patterns)

### .env File (Adapter Configuration)

- **Single source of truth** for adapter configuration
- **Required** for all adapters to initialize
- Loaded via `python-dotenv` at adapter initialization
- Values **cached** by adapters on init (not re-read on every call)
- Must have `.env.example` as template
- **No YAML files** for configuration
- **Never commit** .env to git (keep in .gitignore)

### Environment Variables

- Naming: `{MANAGER}_{CATEGORY}_{SETTING}` (e.g., `NEO4J_POOL_SIZE`)
- Provide **sensible defaults** in code if env var missing
- Comma-separated for lists (e.g., `ARCHIMATE_ELEMENT_TYPES=Component,Service`)
- Boolean as string: `true`/`false` (case-insensitive)

### Pattern

```python
# adapters/some_adapter/manager.py
import os
from dotenv import load_dotenv

class SomeManager:
    def __init__(self):
        load_dotenv()
        self.setting = os.getenv('SOME_SETTING', 'default')
        # Read all config in __init__
        # Cache values as instance variables
```

### Database Configs (Pipeline Configuration)

Pipeline configs (extraction steps, derivation prompts) are stored in DuckDB with **version tracking**.

**How versioning works:**

- Each config has `id`, `version`, and `is_active` fields
- When you update a config via UI or CLI, a **new version** is created
- The old version is preserved with `is_active=false` for rollback
- Only one version per config type is active at a time

**Correct way to update configs:**

```bash
# Via CLI (creates new version)
uv run python -m deriva.cli.cli config update extraction BusinessConcept \
  -i "New instruction..."

# View version history
uv run python -m deriva.cli.cli config versions
```

**Never update configs by editing JSON and importing.** The `db_tool import` command is for **backup restoration only** - it overwrites the database including version history. This defeats the purpose of versioning and makes rollback impossible.

See [benchmarks.md](benchmarks.md) for the recommended config optimization workflow.

</details>

<details>
<summary><strong>Progress Tracking</strong></summary>

### Overview

The CLI provides visual progress tracking for pipeline and benchmark operations using the [Rich](https://rich.readthedocs.io/) library. This is implemented as an optional dependency with graceful fallback.

### Installation

```bash
# Install with progress support
uv sync --extra progress
```

### Features

- **Progress bars** with ETA, elapsed time, and completion counts
- **Spinner animations** for indeterminate operations
- **Phase/step hierarchy** for multi-stage pipelines (extraction → derivation)
- **Benchmark matrix display** showing current run context (repository, model, iteration)

### CLI Usage

```bash
# Default: progress bars shown (if Rich installed)
deriva run -r my-repo

# Quiet mode: disable progress display
deriva run -r my-repo -q

# Verbose mode: detailed text output (also disables progress bar)
deriva run -r my-repo -v

# Benchmark with progress
deriva benchmark run --repos my-repo --models my-model -n 3

# Benchmark quiet mode
deriva benchmark run --repos my-repo --models my-model -n 3 -q
```

### Architecture

Progress reporting uses a **callback protocol** defined in `common/types.py`:

```python
class ProgressReporter(Protocol):
    """UI-agnostic progress reporting protocol."""
    def start_phase(self, name: str, total_steps: int) -> None: ...
    def start_step(self, name: str, total_items: int | None = None) -> None: ...
    def update(self, current: int | None = None, message: str = "") -> None: ...
    def advance(self, amount: int = 1) -> None: ...
    def complete_step(self, message: str = "") -> None: ...
    def complete_phase(self, message: str = "") -> None: ...
    def log(self, message: str, level: str = "info") -> None: ...

class BenchmarkProgressReporter(Protocol):
    """Extended protocol for benchmark operations."""
    # Includes all ProgressReporter methods plus:
    def start_benchmark(self, session_id: str, total_runs: int, ...) -> None: ...
    def start_run(self, run_number: int, repository: str, model: str, ...) -> None: ...
    def complete_run(self, status: str, stats: dict | None = None) -> None: ...
    def complete_benchmark(self, runs_completed: int, runs_failed: int, ...) -> None: ...
```

### Implementation Layers

| Layer | File | Implementation |
|-------|------|----------------|
| **CLI** | `cli/progress.py` | Rich-based reporters with fallback to no-op |
| **Marimo** | `app/progress.py` | State-collecting reporter + `mo.status.spinner()` |
| **Services** | `extraction.py`, `derivation.py`, `benchmarking.py` | Accept optional `progress` parameter |

The services layer is UI-agnostic—it accepts any object implementing the protocol. This allows:

- CLI to use Rich progress bars with real-time updates
- Marimo to collect events and display summary after completion with spinner during execution
- Tests to use no-op reporters

### Adding Progress to New Services

```python
from deriva.common.types import ProgressReporter

def my_service_function(
    ...,
    progress: ProgressReporter | None = None,
) -> dict:
    if progress:
        progress.start_phase("my_operation", total_steps=3)

    # Step 1
    if progress:
        progress.start_step("Processing items", total_items=len(items))
    for item in items:
        process(item)
        if progress:
            progress.advance()
    if progress:
        progress.complete_step("Done")

    # ... more steps ...

    if progress:
        progress.complete_phase("Operation complete")
    return result
```

</details>

<details>
<summary><strong>Benchmarking System</strong></summary>

### Overview

The benchmarking system enables multi-model comparison for evaluating LLM performance on the ArchiMate derivation pipeline.

**Key Components:**
- `services/benchmarking.py` - `BenchmarkOrchestrator` for running benchmarks, `BenchmarkAnalyzer` for analysis
- OCEL 2.0 event logging for process mining analysis

### Architecture

```
BenchmarkConfig
    ↓
BenchmarkOrchestrator
    ├── Clears graph/model between runs
    ├── Switches LLM provider per run
    ├── Executes pipeline stages
    ├── Logs events in OCEL format
    └── Tracks runs in DuckDB
    ↓
BenchmarkAnalyzer
    ├── Intra-model consistency (stability)
    ├── Inter-model consistency (agreement)
    └── Inconsistency localization (hotspots)
```

### OCEL Event Logging

Benchmark runs are logged in **OCEL 2.0** (Object-Centric Event Log) format:

```python
# Event structure
{
    "ocel:eid": "unique-event-id",
    "ocel:activity": "StartBenchmark|EndRun|LLMCall|...",
    "ocel:timestamp": "2026-01-01T15:45:09.148583",
    "ocel:omap": ["bench_20260101_154509"],  # Related objects
    "ocel:vmap": {  # Event attributes
        "tokens_in": 1234,
        "tokens_out": 567,
        "cache_hit": false
    }
}
```

**Object Types:**
- `BenchmarkSession` - Top-level benchmark session
- `BenchmarkRun` - Individual run (repo × model × iteration)
- `Repository` - Target repository
- `Model` - LLM model configuration

### Adding New Metrics

To add a new consistency metric:

1. Add method to `BenchmarkAnalyzer` in `services/benchmarking.py`
2. Define result dataclass in the module
3. Integrate into `compute_full_analysis()`
4. Add database table in schema if persisting

### Configuration

Benchmark models are configured via environment variables:

```bash
LLM_{NAME}_PROVIDER=azure|openai|anthropic|ollama
LLM_{NAME}_MODEL=model-identifier
LLM_{NAME}_URL=api-endpoint  # Optional
LLM_{NAME}_KEY=api-key      # Optional
```

The friendly name for CLI usage is derived from `{NAME}` with underscores converted to hyphens and lowercased (e.g., `AZURE_GPT4` → `azure-gpt4`).

</details>

---

## Naming Conventions

Use consistent naming across all components:

- **snake_case** everywhere (variables, functions, files)
- **Verb-based** function names: `add_*`, `get_*`, `build_*`, `validate_*`
- **Predicate** functions: `is_*`, `has_*`, `can_*`
- **Short names** when obvious: `x`, `y`, `i`, `j`, `n`, `m`

<details>
<summary><strong>Naming Details</strong></summary>

### Variables & Functions

```python
# snake_case everywhere
parse_input, build_graph, max_iterations

# Short names when obvious
x, y, i, j, n, m          # coordinates, indices, counts
xs, ys, vals              # plurals for collections

# Verb-based functions
add_node(), build_graph(), get_neighbors()

# Predicate functions
is_valid(), can_place(), has_cycle()
```

### Manager Methods

| Prefix | Purpose | Example |
|--------|---------|---------|
| `add_*` | Create new entities | `add_node()`, `add_element()` |
| `get_*` | Retrieve entities | `get_node()`, `get_elements()` |
| `update_*` | Modify entities | `update_config()` |
| `delete_*` | Remove entities | `delete_repository()` |
| `query_*` | Complex queries | `query_by_type()` |
| `clear_*` | Reset/clear | `clear_graph()`, `clear_cache()` |
| `export_*` | Export data | `export_to_xml()` |

### Module Functions

| Prefix | Purpose | Example |
|--------|---------|---------|
| `build_*` | Construct data structures | `build_nodes()`, `build_edges()` |
| `classify_*` | Classification logic | `classify_files()` |
| `detect_*` | Detection/discovery | `detect_modules()`, `detect_patterns()` |
| `map_*` | Transform/map data | `map_modules_to_components()` |
| `validate_*` | Validation logic | `validate_nodes()`, `validate_edges()` |
| `run_*` | Pipeline steps | `run_classification_step()` |

### File Naming

- **Adapters**: `adapters/{name}/manager.py` with `__init__.py` export
- **Modules**: `modules/{name}.py` with clear purpose
- **Tests**: `tests/test_{name}.py` mirroring source structure

### Imports

```python
# stdlib first
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List

# third-party
from dotenv import load_dotenv
import polars as pl

# local
from modules.classification import classify_files
```

Group: stdlib, then third-party, then local. Blank line between groups.

</details>

---

## Marimo

Deriva uses [Marimo](https://marimo.io) as its reactive notebook framework. All UI and orchestration lives in `app/app.py`.

**Documentation**: [docs.marimo.io](https://docs.marimo.io) | **Examples**: [github.com/marimo-team/marimo/examples](https://github.com/marimo-team/marimo/tree/main/examples)

<details>
<summary><strong>Editing app/app.py - Critical Quirks</strong></summary>

### Cell Editing Format

When editing `app/app.py`, only modify the contents inside the `@app.cell` decorator. Marimo auto-generates function parameters and return statements:

```python
@app.cell
def _():
    # Your code here - marimo handles the rest
    return
```

### Reactivity Gotchas

| Quirk | Why It Matters |
|-------|----------------|
| **No variable redeclaration** | Each variable name can only be defined in ONE cell across the entire notebook |
| **`.value` access in separate cell** | You cannot access `button.value` in the same cell where `button` is defined |
| **Underscore prefix = cell-local** | Variables like `_temp` are local to that cell and won't trigger downstream updates |
| **Last expression auto-displays** | No need for `print()` or `display()` - the last expression renders automatically |
| **No `global` keyword** | Never use `global` - marimo's DAG handles state |
| **No callbacks** | Don't write callbacks - marimo's reactivity handles UI updates automatically |

### DAG Dependencies

Marimo builds a Directed Acyclic Graph from cell dependencies:
- Cell parameters declare dependencies (e.g., `def _(mo, data):` depends on `mo` and `data`)
- When a variable changes, all downstream cells automatically re-execute
- Circular dependencies will error - reorganize code to break cycles

### SQL Cells

When using `mo.sql()` for DuckDB queries:
- Don't add comments inside SQL cells
- Use f-strings for dynamic values: `mo.sql(f"SELECT * FROM t WHERE x > {slider.value}")`
- Configure output format in app init: `marimo.App(sql_output="polars")`

### Visualization

- **matplotlib**: use `plt.gca()` as last expression (not `plt.show()`)
- **plotly/altair**: return the figure/chart object directly
- Polars DataFrames render as interactive tables automatically

</details>

<details>
<summary><strong>PipelineSession Integration Pattern</strong></summary>

### Rules

1. **Create PipelineSession ONCE** in an early cell (singleton pattern)
2. Pass the **session** to cells via function parameters
3. Use **session methods** for all operations (queries and orchestration)
4. **Never** import adapters directly in app/app.py

### Usage in Marimo

```python
# Cell 1: Create session (runs once)
from services.session import PipelineSession
session = PipelineSession(auto_connect=True)

# Cell 2: Status display (reactive)
def _(session, mo):
    if session.is_connected():
        stats = session.get_graph_stats()
        mo.callout(mo.md(f"**Graph:** {stats['total_nodes']} nodes"), kind="success")
    else:
        mo.callout(mo.md("**Disconnected**"), kind="danger")

# Cell 3: Run extraction (button click)
def _(session, mo, run_button, selected_repo):
    if run_button.value:
        result = session.run_extraction(repo_name=selected_repo.value)
        mo.callout(mo.md(f"Created {result['stats']['nodes_created']} nodes"))

# Cell 4: Show elements table (reactive, updates after operations)
def _(session, mo):
    elements = session.get_archimate_elements()
    mo.ui.table(elements)
```

### PipelineSession API

| Method | Purpose |
|--------|---------|
| `connect()` / `disconnect()` | Lifecycle management |
| `is_connected()` | Connection status |
| `get_graph_stats()` | Node/edge counts for display |
| `get_graph_nodes(type)` | Get nodes for table display |
| `get_archimate_elements()` | Get elements for table display |
| `query_graph(cypher)` | Run arbitrary Graph queries |
| `query_model(cypher)` | Run arbitrary Model queries |
| `run_extraction(...)` | Run extraction pipeline |
| `run_derivation(...)` | Run derivation pipeline |
| `run_pipeline(...)` | Run full pipeline |
| `export_model(path, name)` | Export ArchiMate XML |
| `start_neo4j()` / `stop_neo4j()` | Container control |
| `clear_graph()` / `clear_model()` | Clear data |

</details>

<details>
<summary><strong>Validation & Troubleshooting</strong></summary>

### After Editing

```bash
marimo check src/app/app.py --fix
```

This catches and auto-resolves common formatting issues.

### Common Issues

| Issue | Solution |
|-------|----------|
| Circular dependencies | Reorganize code to remove cycles in DAG |
| UI element value access error | Move `.value` access to separate cell from definition |
| Visualization not showing | Ensure visualization object is the last expression |
| Variable redeclaration error | Use unique names or underscore prefix for cell-local |
| Cell not re-executing | Check that the variable is in the cell's function parameters |

</details>

---

## Testing

Tests are organized to mirror the source structure:

```
tests/
├── test_adapters/   # Adapter integration tests
│   ├── test_database.py
│   ├── test_graph.py
│   └── ...
├── test_modules/    # Module unit tests
│   ├── extraction/
│   ├── derivation/
│   └── ...
└── test_services/   # Service tests
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/test_modules/extraction/test_classification.py -v

# Run with coverage
uv run pytest --cov=.
```

### Module Tests (Pure Functions)

```python
# tests/test_modules/extraction/test_classification.py
def test_classify_files():
    files = [{'path': 'src/main.py', 'content': '...'}]
    registry = {'py': 'python'}

    result = classification.classify_files(files, registry)

    assert result[0]['type'] == 'python'
```

Module tests should be **unit tests only** - no external dependencies, mock data only.

### Adapter Tests (Integration)

```python
# tests/test_adapters/test_graph.py
def test_add_and_get_node():
    manager = GraphManager()
    node = {'id': 'test1', 'type': 'Repository'}

    manager.add_node(node)
    retrieved = manager.get_node('test1')

    assert retrieved['id'] == 'test1'
```

Manager tests may require external services (Neo4j, DuckDB) - use fixtures for setup/teardown.

---

## Anti-Patterns to Avoid

| Anti-Pattern | Why It's Bad | Do This Instead |
|--------------|--------------|-----------------|
| Importing adapters in app.py or cli.py | Violates architectural boundaries | Use PipelineSession from services |
| Business logic in app.py or cli.py | Hard to test, violates separation | Move logic to modules |
| Adapters importing adapters | Creates coupling | Coordinate via services |
| Modules with I/O | Breaks purity, hard to test | Pass data as parameters |
| Direct .env access in modules | Violates purity | Receive config as parameters |
| YAML configuration files | Multiple config sources | Use .env for all config |
| Manual state management in marimo | Fights reactivity | Let marimo handle state |
| Creating adapters in individual cells | Multiple instances, connection issues | Create PipelineSession once |

---

## Related Documentation

This project includes several specialized documentation files:

| Document | Description |
|----------|-------------|
| [README.md](README.md) | Main project overview, setup, and usage guide |
| [benchmarks.md](benchmarks.md) | Benchmarking & optimization guide for LLM consistency |
| [CHANGELOG.md](CHANGELOG.md) | Version history and release notes |
| [.github/SECURITY.md](.github/SECURITY.md) | Security policy and vulnerability reporting |
| [.github/SUPPORT.md](.github/SUPPORT.md) | How to get help and support |

### Component Documentation

| Component | README |
|-----------|--------|
| CLI | [deriva/cli/README.md](deriva/cli/README.md) |
| LLM Adapter | [deriva/adapters/llm/README.md](deriva/adapters/llm/README.md) |
| Graph Adapter | [deriva/adapters/graph/README.md](deriva/adapters/graph/README.md) |
| Database Adapter | [deriva/adapters/database/README.md](deriva/adapters/database/README.md) |
| Neo4j Adapter | [deriva/adapters/neo4j/README.md](deriva/adapters/neo4j/README.md) |
| ArchiMate Adapter | [deriva/adapters/archimate/README.md](deriva/adapters/archimate/README.md) |
| Repository Adapter | [deriva/adapters/repository/README.md](deriva/adapters/repository/README.md) |
| Marimo App | [deriva/app/README.md](deriva/app/README.md) |

---

## Philosophy

1. **Working > perfect** - ship it, iterate
2. **Readable > clever** - clarity over cleverness
3. **Simple > general** - solve today's problem
4. **Pure > stateful** - isolate side effects to adapters

```python
model.maximize(readability + maintainability)
model.add(complexity <= necessary)
```
