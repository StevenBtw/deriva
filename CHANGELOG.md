# Deriva Changelog

Deriving ArchiMate models from code using knowledge graphs, heuristics and LLM's, a journey through architectural decisions, strategic purges and lot's and lot's of trial and error.

---

# v0.6.x - Deriva (December 2025 - January 2026)

## v0.6.3 - (Unreleased)

---

## v0.6.2 - New Derivation Modules & LLM Provider Expansion (January 7, 2026)

### New Derivation Modules

Major expansion of derivation capabilities with 6 new ArchiMate element modules:

- Added `ApplicationInterface`, `BusinessEvent`, `BusinessFunction` modules
- Added `Device`, `Node`, `SystemSoftware` technology layer modules
- Refactored existing derivation modules to new consistent style with improved prompts and schemas
- New database scripts: `8_derivation_config_extension.sql`, `9_new_derivation_modules.sql`

### LLM Provider Expansion

- Added Mistral AI provider in `adapters/llm/providers.py`
- Added LM Studio provider for local LLM models like Nemotron A3B
- Fixed Claude response truncation bug in Anthropic provider
- Fixed LLM null/None response handling
- Fixed non-dict responses in external dependency extractor (strings, numbers)

### Extraction Improvements

- Added `type` and `subtype` properties to File nodes for richer classification
- Improved file classification logic with better pattern matching
- Added repository sync method, removed redundant code

### Relationship Derivation

- Significant improvements to relationship derivation logic

### Benchmarking

- Updated `BENCHMARKING.md` documentation
- Improved benchmark workflow and usability

### Bug Fixes

- Fixed failing tests, type errors, and linting issues
- Fixed derivation config issues
- Fixed extraction pipeline bugs

### CI & Code Quality

- Aligned CI test coverage with `pyproject.toml` at 70%
- Ruff formatting and style fixes
- Improved README badges
- Updated `CONTRIBUTING.md` documentation

---

## v0.6.1 - Extraction Refactor, Chunking, AST & Tests (January 3, 2026)

### Extraction Module Refactor

- Flattened `modules/extraction/` structure, removed `llm/` and `structural/` subdirs
- Added `common/chunking.py`, file chunking with overlap support
- New database scripts: `5_chunking_config.sql`, `6_extraction_method.sql`

### AST Parser Foundation

- Enhanced `adapters/ast/manager.py`, Python AST analysis (classes, functions, imports)
- Added generic `tree-sitter` dependency for future multi-language support (flash from the past)
- Updated `adapters/ast/models.py` with improved code element types

### Claude/Anthropic Provider Support

- Added Claude Haiku model support in `adapters/llm/providers.py`
- Updated `adapters/llm/models.py` with Anthropic model configurations

### Test Suite Expansion

Comprehensive test coverage across the codebase:

- **Adapters:** AST manager, repository manager, LLM cache/models/providers, ArchiMate validation, graph models
- **Common:** Chunking, exceptions, file utils, logging, OCEL, schema utils, time utils
- **Extraction:** Directory, file, input sources, LLM extractors, repository
- **Derivation:** Element generation, PageRank preparation
- **Services:** Benchmarking, config, derivation, extraction, pipeline, session
- **CLI:** Integration tests

### Code Quality

- Enforced 70% minimum code coverage in CI
- Fixed type warnings across codebase
- Consolidated `benchmark_analysis.py` into `benchmarking.py`
- Added `types-lxml>=2025.3.30` for lxml type stubs
- Created `@runtime_checkable` `HasToDict` Protocol
- Reduced `# type: ignore` from 8 to 2 (neo4j stubs limitations)

---

## v0.6.0 - Rename to Deriva (January 1, 2026)

**AutoMate is now Deriva.**

The project has been renamed from AutoMate to Deriva to reflect its broader scope. While the initial focus was on generating ArchiMate models from code, the underlying architecture can be extended to derive other model types (C4, BPMN, UML, etc.) from source repositories. The name "Deriva" captures this generalized purpose - deriving structured models from code.

Changes:
- Renamed `automate/` package directory to `deriva/`
- Updated all Python imports from `automate.*` to `deriva.*`
- Renamed CLI commands from `automate-cli`/`automate-app` to `deriva-cli`/`deriva-app`
- Updated Docker container names from `automate_neo4j` to `deriva_neo4j`
- Updated all documentation, configuration files, and GitHub workflows

---

# v0.5.x - The Adapters/Modules/Services/Marimo+CLI Era (August 2025 - December 2025)

**Architectural paradigm:** Single-file Marimo notebook (`app.py`) with domain adapters and reusable modules.

**Process model:** Import -> Extraction → Derivation → Export

**Solution space:** 7 adapters (database, neo4j, repository, graph, archimate, llm, ast) + modular extraction/derivation functions + DuckDB config storage

> **This changed because:** The previous extraction-focused architecture couldn't support the full pipeline without overbearing complexity. Needed proper separation of concerns and a more managable interactive UI for configuration.

---

## v0.5.11 - Improvements to the derivation module using graph techniques

Phase 11: src -> automate Refactor

- Flattened the repo into a single project layout and cleaned up stray scaffolding
- Completed derivation module placeholders and stabilized graph-driven derivation
- Reached ~95% derivation consistency on the small repo benchmark, by tweaking some more derivation configs
- CLI now supports clearing both Graph and Model (ArchiMate) namespaces
- Ruff/type-checking/pytest fixes across the refactor; integration tests pass

Commit trail (chronological):
- 4aa5af1 bumped to 0.5.11
- f92430a Moved all into one project, flat(ish) structure
- f368774 forgot gitignore
- 8f840cf ruff ty and pytest fixes
- 3a27fb3 some more type fixes
- d63fcba all tests pass, incl -m integration
- d0e34ba added clear graph/model(archimate) to cli

## v0.5.10 - Adapters Rename & Cleanup

Phase 10: Managers -> Adapters Refactor

- Renamed managers to adapters (including the tests directory) to clarify layering
- Consolidated operations and merged the metamodel into models for consistency
- Renamed `service.py` -> `manager.py` and cleaned imports/unused files
- Added `.github/` scaffolding alongside path and exception-handling fixes

Commit trail (chronological):
- 46cf7d4 all passss new exceptional exception handling
- 28b25e9 fixed path
- f71286c shuffeling some things around for consistency
- 6fbd51a merged metamodel into models
- a1a984a Consolidated operations in managers
- e96800d renamed service.py in managers to manager.py
- 18b6407 fixed some imports
- 7506313 added github folder
- be85f6b Renamed managers->adapters, simplified derivation
- c65c17a removed unused/old imports
- b514c41 removed
- 4666434 also renamed tests dir managers->adapters

---

## v0.5.9 - PipelineSession & Benchmarking

Phase 9: Unified API & Multi-Model Benchmarking

### PipelineSession (`services/session.py`)

New unified API that serves both CLI and Marimo:

- **Context manager support**, `with PipelineSession() as session: ...`
- **Lifecycle management**, `connect()`, `disconnect()`, manager initialization
- **Query methods**, `get_graph_stats()`, `get_archimate_elements()` for reactive UI
- **Orchestration methods**, `run_extraction()`, `run_derivation()`, `export_model()`
- **Infrastructure control**, Neo4j container management, data clearing

```python
# CLI usage
with PipelineSession() as session:
    result = session.run_extraction(repo_name="my-repo")
    session.export_model("output.archimate")

# Marimo usage (auto-connect for reactive cells)
session = PipelineSession(auto_connect=True)
stats = session.get_graph_stats()
```

### Benchmarking Service (`services/benchmarking.py`)

Complete multi-model, multi-repository benchmarking framework:

- **Test matrix**, repos × models × runs (e.g., 3×3×3 = 27 executions)
- **`BenchmarkConfig`**, repositories, models, runs_per_combination, stages
- **`BenchmarkOrchestrator`**, runs the test matrix with progress callbacks
- **OCEL integration**, all events logged for process mining analysis
- **Configurable stages**, classification, extraction, derivation, validation

### Benchmark Analysis (`services/benchmark_analysis.py`)

Post-run analysis of benchmark results:

- **`IntraModelMetrics`**, model stability across runs (count variance, name consistency)
- **`InterModelMetrics`**, model comparison (Jaccard similarity, unique elements)
- **`compute_intra_model_consistency()`**, measure how stable each model is
- **`compute_inter_model_consistency()`**, compare different models
- **`localize_inconsistencies()`**, identify WHERE outputs diverge

### OCEL 2.0 Module (`common/ocel.py`)

Object-Centric Event Logging for process mining traceability:

- **OCEL 2.0 compliant**, [ocel-standard.org](https://www.ocel-standard.org/)
- **Object types**, BenchmarkSession, BenchmarkRun, Repository, Model, File, GraphNode, Element
- **Event types**, StartBenchmark, CompleteBenchmark, StartRun, CompleteRun, ClassifyFile, ExtractNode, DeriveElement, ValidateElement
- **`OCELLog`**, log management with JSON export
- **`OCELEvent`**, event creation with object correlation

### LLM Manager Refactor (`managers/llm/`)

Complete restructure of LLM handling:

- **New `providers.py`**, protocol-based provider abstraction
  - `LLMProvider` protocol defining the interface
  - `ProviderConfig`, `CompletionResult` dataclasses
  - Implementations: `AzureOpenAIProvider`, `OpenAIProvider`, `AnthropicProvider`, `OllamaProvider`
- **Updated `models.py`**, `BenchmarkModelConfig` for multi-model benchmarking
- **Refactored `service.py`**, `load_benchmark_models()` for loading multiple configs

### ArchiMate Operations (`managers/archimate/operations/`)

New operations directory following the graph manager pattern:

- **`element_ops.py`**, element CRUD with semantic helpers
- **`relationship_ops.py`**, relationship operations
- **`model_ops.py`**, model-level operations (validate, export, clear)
- **`query_ops.py`**, model traversal and analysis

### App Refactor

- **Significant reduction**, `app.py` now uses PipelineSession
- **Cleaner architecture**, UI code now delegates to services layer

### Architectural Boundaries (Ruff TID251)

New per-directory `ruff.toml` files enforcing layer hierarchy:

```text
CLI/App → services ONLY (PipelineSession is the API)
Services → managers, modules, common
Managers → common only (NOT modules or services)
Modules  → common only (NOT managers or services)
Common   → stdlib and third-party only
```

### Bug Fixes

- **Node creation fix**, nodes don't need to be created before referencing in relationships

### Replaced Consistency with Benchmarking

The old `services/consistency.py` was replaced with the full benchmarking framework, providing more comprehensive multi-model analysis.

### Additional commit trail (chronological)

- 907dddc some updates, will port current version after
- eca38a8 Some housekeeping
- ea2a40f Consisten use of AutoMate
- c0294fb Moving some things around. new project structure
- e14209a First test setup in 0.5.X
- dc4f64e Added services and CLI
- a2710a4 uv run ruff check . --fix
- a44cc61 Updated CHANGELOG.md
- c05b599 The only constant is change
- 1fda614 Major improvements
- 7d99d5f refactor of notebook and llm manager
- 0f9bf18 replaced consistency.py with real benchmark
- 1720b38 bugfix, nodes dont need  to be created
- dd10e2a bumped to 0.5.9

> **This changed because:** Needed a unified API for CLI and Marimo, and the old consistency checking was too narrow. The new benchmarking framework enables systematic multi-model comparison with process mining traceability.

---

## v0.5.8 - Consistency Framework & Config Versioning

Phase 8: LLM Output Consistency & Reproducibility

### New Consistency Service (`services/consistency.py`)

Complete consistency checking framework for measuring LLM output stability:

- **Stage-specific checks**, support for `extraction`, `derivation`, `validation`, or `all` stages
- **`run_consistency_check()`**, main entry point with configurable runs, element types, stage
- **`_run_extraction_consistency()`**, extraction-specific checking with proper name property mapping
- **`_run_derivation_consistency()`**, derivation checking with graph input
- **`_run_single_extraction()`** / **`_run_single_derivation()`**, per-config execution
- **Deduplication**, case-insensitive deduplication within each run to prevent counting duplicates
- **`_get_node_name()`**, maps node types to their correct property names
- **`print_report()`**, formatted console output with stable/unstable element breakdown

### Config Versioning System (`services/config.py`)

New versioned configuration updates preserving history:

- **`create_derivation_config_version()`**, create new version, deactivate old
- **`create_extraction_config_version()`**, same for extraction configs
- **`get_active_config_versions()`**, get current versions for all config types
- **Consistency run logging**:
  - `log_consistency_run()` - Record results with config versions used
  - `get_consistency_history()` - Query past runs with filtering
  - `ensure_consistency_table()` - Auto-create `consistency_runs` table

### CLI Enhancements (`cli/cli.py`)

New commands for config management and consistency:

```bash
# Config versioning
automate config update derivation TechnologyService --instruction-file config.txt
automate config versions          # Show all active config versions

# Consistency checking
automate consistency run -r 5 --stage extraction --repo flask_invoice_generator -v
automate consistency run -r 3 --stage derivation -v
automate consistency history      # View past consistency runs
```

**New CLI arguments:**

- `--stage`, pipeline stage to check (`extraction`, `derivation`, `validation`, `all`)
- `--instruction-file`, read instruction from file
- `--example-file`, read example from file
- `--runs`, number of consistency runs (default: 3)

### Validation Module Expansion (`modules/validation/`)

Comprehensive ArchiMate metamodel validation:

- **`ARCHIMATE_RELATIONSHIP_RULES`**, defines valid (source_type, target_type) tuples per relationship
- **`DEFAULT_NAMING_RULES`**, naming convention patterns per element type
- **`validate_relationship()`**, check relationship validity against metamodel
- **`validate_element_naming()`**, regex-based naming convention validation
- **`validate_orphan_elements()`**, find elements with no relationships
- **`validate_coverage()`**, check extraction-to-derivation coverage
- **Quality metrics expansion** in `quality_metrics.py`

### Consistency Improvements (52% -> 100%)

Achieved 100% extraction and derivation consistency through:

1. **Empty name fix**, added `_get_node_name()` mapping each node type to correct property
2. **Casing fix**, updated ExternalDependency config with explicit casing rules (Flask not flask, Bootstrap not bootstrap)
3. **Deduplication**, added per-run deduplication to prevent counting same entity from multiple files

### Database Schema Changes

New `consistency_runs` table:

```sql
CREATE TABLE IF NOT EXISTS consistency_runs (
    id INTEGER PRIMARY KEY,
    repo_name VARCHAR,
    stage VARCHAR DEFAULT 'derivation',
    num_runs INTEGER,
    name_consistency FLOAT,
    identifier_consistency FLOAT,
    count_variance FLOAT,
    stable_elements INTEGER,
    total_elements INTEGER,
    config_versions JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

> **This changed because:** LLM outputs were inconsistent (~35-52%). Needed systematic way to measure, track, and improve consistency. Config versioning enables A/B testing of prompt changes.

---

## v0.5.7 - Operations Pattern & Neo4j Migration

Phase 7: Manager Architecture Refinement

### Graph Operations Rewritten for Neo4j/Cypher

Complete rewrite of `managers/graph/operations/` from legacy DuckDB PGQ to Neo4j Cypher:

- **`node_ops.py`**, node CRUD delegating to GraphManager
- **`edge_ops.py`**, edge operations with Cypher queries for `get_edges_from_node()`, `get_edges_to_node()`
- **`query_ops.py`**, graph traversal using Cypher patterns:
  - `find_files_in_repository()`, variable-length CONTAINS traversal
  - `find_dependencies()` / `find_dependents()`, DEPENDS_ON/USES relationship traversal
  - `traverse_path()`, allShortestPaths for path finding
  - `find_by_property()`, property-based node filtering
  - `get_subgraph()`, subgraph extraction with depth limit

### ArchiMate Operations Directory

New `managers/archimate/operations/` following the same pattern:

- **`element_ops.py`**, element CRUD with semantic helpers (`add_application_component()`, etc.)
- **`relationship_ops.py`**, relationship operations (`add_composition_relationship()`, `add_serving_relationship()`, etc.)
- **`model_ops.py`**, model-level operations:
  - `validate_model()`, full model validation against metamodel
  - `export_to_xml()` / `export_to_xml_string()`, ArchiMate Exchange Format export
  - `clear_model()`, model cleanup
  - `get_model_summary()`, statistics by element/relationship type
- **`query_ops.py`**, model traversal and analysis:
  - `find_connected_elements()`, element relationship traversal
  - `get_subgraph()`, ArchiMate subgraph extraction
  - `get_model_statistics()`, model metrics including orphan detection

### Linter & Type Fixes

Comprehensive cleanup of ruff and type checker issues:

- **E501 line too long (60)**, line length increased to 180, per-file-ignores for LLM prompts
- **E722 bare except (10)**, changed to specific exceptions (OSError, subprocess.CalledProcessError)
- **F401 unused imports (6)**, removed deprecated typing imports (Dict, List, Optional → native)
- **Type annotations**, updated return types to use `PipelineResult`, fixed `Callable` imports

### Documentation

- **CONTRIBUTING.md**, added "Operations Pattern" section documenting the `operations/` subdirectory structure

> **This changed because:** The graph operations were using legacy DuckDB PGQ SQL syntax that didn't work with the Neo4j backend. The ArchiMate manager needed the same clean operations abstraction that the graph manager has.

---

## v0.5.6 - Code Quality & Standardization

Phase 6: Unified Response Structure & Maintenance

### Standardized Pipeline Response Structure

Created unified `PipelineResult` TypedDict in `common/types.py` that all pipeline stages use:

```python
class PipelineResult(TypedDict, total=False):
    success: bool
    errors: List[str]
    warnings: List[str]
    stats: Dict[str, Any]
    elements: List[Dict[str, Any]]      # Always present
    relationships: List[Dict[str, Any]] # Always present
    stage: str                          # 'extraction', 'derivation', 'validation'
    timestamp: str
    duration_ms: int
    llm_details: LLMDetails
    issues: List[Dict[str, Any]]        # For validation
```

**Updated base modules:**

- `modules/extraction/extraction_base.py`, `create_extraction_result()` now returns `PipelineResult`
- `modules/derivation/derivation_base.py`, `create_derivation_result()` now returns `PipelineResult`
- `modules/validation/validation_base.py`, `create_validation_result()` and `aggregate_validation_results()` updated

**New helper in `common/utils.py`:**

- `create_pipeline_result()`, generic factory function for all stages
- `create_empty_llm_details()`, LLM details initialization

### Comprehensive datetime.utcnow() Fixes

Fixed all 15 deprecated `datetime.utcnow()` occurrences across 9 extraction modules:

- `directory.py`, `file.py`, `repository.py`
- `business_concept.py`, `type_definition.py`, `method.py`
- `technology.py`, `external_dependency.py`, `test.py`

All modules now use `current_timestamp()` helper from `extraction_base.py`.

Also fixed in LLM manager:

- `managers/llm/cache.py`
- `managers/llm/service.py`

### LLM Cache Testing

New test file `tests/test_managers/llm/test_cache.py` with 15 tests:

- Cache key generation (consistent hashing, different prompts/models/schemas)
- Memory and disk cache storage
- Cache clearing (memory, disk, all)
- Cache statistics
- Corrupted cache file handling

### Code Organization

- **Moved test file**, `src/managers/archimate/test_archimate_manager.py` → `tests/test_managers/archimate/`
- **Import organization**, moved import from inside function to module level in `managers/llm/service.py`
- **Test updates**, updated all tests to match new `PipelineResult` structure

### Test Status

- 106 tests passing
- 10 tests skipped (ArchiMate integration tests require Neo4j)
- All extraction, derivation, and validation module tests updated

> **This changed because:** Needed consistent response structure across all pipeline stages. The old structure had `data.nodes/edges` for extraction, `data.elements_created` for derivation, and `data.issues/passed/failed` for validation. Now all use `elements` and `relationships` at the top level for uniformity.

---

## v0.5.5 - Complete Derivation Pipeline

Phase 5: End-to-End ArchiMate Generation

### Derivation Service Rewrite

Complete rewrite of `services/derivation.py` with two-phase approach:

1. **Phase 1: Element Derivation**, processes all enabled derivation configs sequentially
   - Config-driven via DuckDB (element_type, input_graph_query, instruction, example)
   - LLM-based derivation using `DERIVATION_SCHEMA`
   - Tracks created elements for relationship phase

2. **Phase 2: Relationship Derivation**, LLM derives relationships between all created elements
   - Uses `RELATIONSHIP_SCHEMA` for structured output
   - ArchiMate relationship types: Composition, Aggregation, Serving, Realization, Assignment, Access
   - Validates source/target identifiers exist before creating

### New Schemas (`modules/derivation/derivation_base.py`)

```python
DERIVATION_SCHEMA = {
    "name": "derivation_output",
    "schema": {
        "properties": {
            "elements": [{
                "identifier": str,  # Required
                "name": str,        # Required
                "documentation": str,
                "source": str,
                "confidence": float
            }]
        }
    }
}

RELATIONSHIP_SCHEMA = {
    "name": "relationship_output",
    "schema": {
        "properties": {
            "relationships": [{
                "source": str,           # Required
                "target": str,           # Required
                "relationship_type": str, # Required
                "name": str,
                "confidence": float
            }]
        }
    }
}
```

### CLI Export Command

New `export` command in `cli/cli.py`:

```bash
# Export ArchiMate model to file
automate export -o workspace/output/model.archimate
automate export --output model.archimate --name "My Project Model" -v
```

- Fetches elements and relationships from Neo4j Model namespace
- Uses `ArchiMateXMLExporter` for ArchiMate 3.0 Exchange Format
- Compatible with Archi modeling tool

### Validation Module Fixes (`modules/validation/validation_base.py`)

- **Added `VALIDATION_SCHEMA`**, for LLM-based validation
- **Added severity aliases**, `SEVERITY_ERROR` (alias for critical), `SEVERITY_WARNING` (alias for major)
- **Fixed `create_issue()` API**, reordered parameters to match service usage
- **Fixed `build_validation_prompt()`**, made `instruction` parameter optional

### Deprecated datetime.utcnow() Fixes

Fixed Python deprecation warnings across all modules:

- `modules/derivation/derivation_base.py`, `datetime.now(timezone.utc)`
- `modules/validation/validation_base.py`, `datetime.now(timezone.utc)`
- `modules/extraction/extraction_base.py`, `datetime.now(timezone.utc)`

### Test Updates

- Fixed `test_validation_base.py` to match new `create_issue()` API
- Fixed `test_validation_base.py` to match new `build_validation_prompt()` signature
- All 69 tests passing

### Full Pipeline Now Working

```bash
# Start Neo4j
docker compose up -d

# Run extraction (Graph namespace)
automate run extraction --repo flask_invoice_generator -v

# Run derivation (Model namespace - elements + relationships)
automate run derivation -v

# Run validation
automate run validation -v

# Export to ArchiMate file
automate export -o workspace/output/model.archimate
```

> **This changed because:** The derivation service was incomplete - it only had element derivation stubs. Now it supports the full pipeline from Graph namespace to exportable ArchiMate model.

---

## v0.5.4 - Services Layer & CLI
*Phase 4: Shared Orchestration*

### Services Layer Architecture

New `services/` layer providing shared orchestration between Marimo (visual) and CLI (headless):

- **`services/config.py`**, config CRUD operations for DuckDB
  - `ExtractionConfig`, `DerivationConfig`, `ValidationConfig`, `FileType` dataclasses
  - Full CRUD: `get_*_configs()`, `get_*_config()`, `update_*_config()`
  - Convenience: `enable_step()`, `disable_step()`, `list_steps()`

- **`services/extraction.py`**, extraction pipeline orchestration
  - `run_extraction()` - Main entry point for extraction
  - Handles structural (Repository, Directory, File) and LLM-based extraction
  - Separates warnings from errors for skipped LLM steps

- **`services/derivation.py`**, derivation pipeline orchestration
  - `run_derivation()` - Graph→ArchiMate transformation
  - Processes enabled derivation configs in sequence

- **`services/validation.py`**, validation pipeline orchestration
  - `run_validation()` - Algorithmic and LLM-based validation
  - Aggregates issues by severity

- **`services/pipeline.py`**, full pipeline orchestration
  - `run_full_pipeline()` - Classification→Extraction→Derivation→Validation
  - `run_classification()` - Standalone classification stage
  - `get_pipeline_status()` - Current config status

### CLI Entry Point

New `cli/cli.py`, fully functional headless interface:

```bash
# Configuration commands
automate config list extraction      # List extraction configs
automate config show extraction BusinessConcept  # Show details
automate config enable derivation ApplicationComponent
automate status                      # Show pipeline status

# Pipeline execution
automate run extraction --no-llm -v --repo flask_invoice_generator
automate run derivation -v           # Requires LLM
automate run validation -v
automate run all --repo flask_invoice_generator
```

**CLI Options:**

- `--repo NAME`, process specific repository (default: all)
- `-v, --verbose`, print detailed progress
- `--no-llm`, skip LLM-based steps (structural extraction only)
- `--db PATH`, custom DuckDB path

### Workspace Consolidation

All workspace-related paths now use `workspace/` folder in project root:

| Component | Old Path | New Path |
|-----------|----------|----------|
| Repositories | `managers/repository/workspace/` | `workspace/` |
| LLM Cache | `managers/llm/cache/` | `workspace/cache/` |
| Pipeline Logs | `logs/` | `workspace/logs/` |

**Workspace structure:**
```
workspace/
├── cache/              # LLM response cache
├── logs/               # Pipeline run logs (JSONL)
├── flask_invoice_generator/  # Cloned repositories
├── workspace.yaml      # Repository state
└── *_metadata.json     # Repository metadata files
```

### Services/CLI Bug Fixes

- **Unicode encoding (Windows)**, replaced box-drawing characters (`─`) with ASCII dashes in CLI output for cp1252 compatibility
- **Extraction module calls**, fixed `extract_directories()` and `extract_files()` to receive `repo_path` string instead of pre-processed lists
- **GraphManager edge parameters**, fixed `add_edge()` calls to use correct parameter names (`src_id`, `dst_id`, `relationship`)
- **Node ID consistency**, pass `node_id` from extraction module to `add_node()` for proper ID matching in edges
- **Warnings vs Errors**, "LLM required" messages now classified as warnings, not errors (exit code 0 for structural-only extraction)

### Test Infrastructure

- **`conftest.py`**, root-level pytest config ensuring `src/` is on path
- **`.github/workflows/ci.yml`**, GitHub Actions with lint, typecheck, test jobs
- **69 tests passing** across modules (classification, extraction, derivation, validation)

### Documentation Updates

- **`CONTRIBUTING.md`**, updated with services layer architecture, component hierarchy, data flow diagrams
- **`.claude/active_context.md`**, rewritten with CLI + services plan

> **This changed because:** Both visual (Marimo) and headless (CLI) interfaces needed shared orchestration. Services layer enforces separation and enables scripting/automation use cases.

---

## v0.5.3 - All Extraction Modules Complete
*Phase 2-3: Extraction Pipeline*

### Extraction Modules Completed

**Structural extraction (no LLM):**

- `modules/extraction/repository.py`, repository node extraction
- `modules/extraction/directory.py`, directory node extraction
- `modules/extraction/file.py`, file node extraction with CONTAINS edges

**LLM-based extraction modules:**

- `modules/extraction/business_concept.py`, from docs files (.md, .txt, .rst, .adoc)
  - JSON schema for structured output (BUSINESS_CONCEPT_SCHEMA)
  - `build_extraction_prompt()`, `parse_llm_response()`, `extract_business_concepts_batch()`

- `modules/extraction/type_definition.py`, classes, interfaces, functions from source
  - Includes `startLine`, `endLine`, `codeSnippet` for Method extraction
  - Line-numbered file content for accurate LLM line references

- `modules/extraction/method.py`, methods from TypeDefinition.codeSnippet
  - **Key design**, uses codeSnippet from graph, no file I/O needed
  - Fields, methodName, returnType, visibility, parameters, isStatic, isAsync

- `modules/extraction/technology.py`, infrastructure components (ArchiMate Technology Layer)
  - Categories, service, system_software, infrastructure, platform, network, security
  - NOT for libraries (those go in ExternalDependency)

- `modules/extraction/external_dependency.py`, external dependencies
  - Categories, library, external_api, external_service, external_database
  - Captures, pypi/npm/maven packages, third-party APIs, external integrations

- `modules/extraction/test.py`, test definitions
  - Types, unit, integration, e2e, performance, smoke, regression
  - Includes, framework, testedElement, line numbers

### Process Changes

- **Config-driven extraction**, `input_sources` JSON column replaces `input_file_types` + `input_graph_elements`

  ```json
  {"files": [{"type": "source", "subtype": "*"}], "nodes": [{"label": "TypeDefinition", "property": "codeSnippet"}]}
  ```

- **Relationship chain**, File → CONTAINS → TypeDefinition → CONTAINS → Method
- **Config panel**, UI saves ALL fields (enabled, sequence, input_sources, instruction, example)

### Bug Fixes

- Fixed UTF-16 file encoding detection (requirements.txt in some repos)
- Created `modules/utils.py` with `read_file_with_encoding()` for BOM handling

### Module Pattern Standardization

Introduced consistent patterns across all pipeline modules:

- **`common/types.py`:** Shared TypedDicts (`BaseResult`, `ExtractionResult`, `DerivationResult`, `ValidationResult`) and function Protocols for type-safe registries
- **`*_base.py` files:** Each module folder now has a base file with shared utilities (`extraction_base.py`, `derivation_base.py`, `validation_base.py`)
- **Registry pattern:** `__init__.py` files export `DERIVATION_FUNCTIONS` / `VALIDATION_FUNCTIONS` dicts that map element types to handler functions
- **Generic dispatch:** `derive_elements()` and `validate()` entry points dispatch to element-specific functions via registry lookup

> **This changed because:** ...

---

## v0.5.2 - Pipeline & Logging System
*Phase 1: Pipeline Buttons & Orchestration*

### 3-Level JSONL Logging System

- **L1 (Phase)**, Neo4j start/stop, clear graph/ArchiMate, toggle cache, clone/delete repo, classify files, config saves
- **L2 (Step)**, each config change in extraction/derivation/validation saves
- **L3 (Detail)**, `detail_file_classified()`, `detail_file_unclassified()`, `detail_extraction()` with full LLM details
  - Tracks, prompt, response, tokens_in, tokens_out, cache_used, retries, concepts_extracted

### Pipeline Orchestration

- **5 pipeline control buttons**, Classification, Extraction, Derivation, Validation + Full Pipeline
- **Step status tracking**, Ready → Running → Completed/Error states
- **Execution order fix**, Classification cell returns `classification_done` flag
- All extraction cells depend on `classification_done` for proper ordering

### LLM Manager Updates

- Removed YAML config dependency, now uses `.env` configuration
- `LLMManager.__init__()` calls `load_dotenv()` and reads environment variables
- Supports: azure (LLM_AZURE_*), openai (LLM_OPENAI_*), anthropic (LLM_ANTHROPIC_*)
- Added `LLM_NOCACHE` and `LLM_TIMEOUT` configuration options

> **This changed because:** Needed traceability for debugging LLM calls and proper pipeline execution order. YAML config was inflexible compared to .env.

---

## v0.5.1 - Foundation Complete
*Phase 0: Infrastructure & Configuration*
*Commits: 6006bb0, fdfc601*

### Infrastructure

- Neo4j Docker setup with connection pooling
- DuckDB schema with configuration tables (`extraction_config`, `derivation_config`, `validation_config`)
- `.env` configuration consolidation
- Repository workspace structure

### Manager Implementations

- **ArchimateManager**, XML export, validation, element/relationship CRUD
- **DatabaseManager**, DuckDB schema, config tables, run tracking
- **GraphManager**, Neo4j operations, node/edge persistence
- **LLMManager**, multi-provider support (Azure, OpenAI, Anthropic), response caching
- **SourceManager**, repository analysis, file discovery
- **DerivationManager**, graph-to-ArchiMate mapping (placeholder)

### UI Framework (Marimo Notebook)

- 4-column layout in `app.py`
- Column 1, Configuration UI (runs, repo, graph, archimate, database status)
- Column 2, Extraction Settings UI (file types, steps, prompts, sequence)
- Column 3, Derivation Settings UI (metamodel, steps, prompts, validation config)
- Status bar with progress indicator (HTML-based, reactive)

### Modules Foundation

- `modules/classification.py`, classify_files, get_undefined_extensions, build_registry_update_list
- `modules/extraction/`, Repository, Directory, File extraction functions
- `modules/logging.py`, RunLogger class with JSONL output

> **This changed because:** ...

---

## v0.5.0 - AutoMate V2 Merge
*Developed: August-November 2025
*Commit: 6006bb0 | Lines: +25,657 / -13,353*

**Complete codebase replacement**, merged parallel V2 development into main repository.

### Architecture Changes

- **New structure:**
  - `managers/` - Domain-specific managers (archimate, database, derivation, graph, llm, source)
  - `modules/` - Reusable modules (connectors, llm, neo4j, extraction, classification, logging)
  - `layouts/` - Marimo notebook layouts
- **Single-file app**, `app.py`, Marimo notebook with 4-column layout
- **Config storage:** DuckDB replaces JSON config files

### Process Model

```
Classification → Extraction → Derivation → Validation → Export
     ↓              ↓             ↓            ↓          ↓
  File types    Graph nodes   ArchiMate    Schema    .archimate
  registry      in Neo4j      elements     checks    XML file
```

### Key Design Decisions

- **Single app.py**, all UI and orchestration in one Marimo notebook for easy debugging
- **Managers for I/O**, all external operations (DB, Neo4j, LLM, files) via manager classes
- **Modules for logic**, pure functions for extraction, classification, derivation
- **Config in DB**, DuckDB tables for extraction/derivation/validation config (editable from UI)

### Behind the Scenes

- **UI pivot**, original plan was Gradio, switched to Marimo for better notebook experience
- **Cache system**, SHA256 hashing of prompt+model+schema for cache keys, both memory and disk persistence
- **This merged 4 months of parallel V2 development** done outside this repo
- **Accidentally committed**, Neo4j debug logs (`managers/neo4j/logs/debug.log`), oops
- **Description simplified**, "AI-Assisted ArchiMate Model Generation" → "Derive Archimate models from unstructured data using LLMs"

> **This changed because:** The previous extraction-focused architecture couldn't support the full pipeline (derivation, validation, export). Needed proper separation of concerns and a more interactive UI for configuration.

---

# v0.3.x - The UV/Extraction Functions Era

**Architectural paradigm:** UV package manager + extraction functions + layered steps

**Process model:** Clone → Classify → Extract (layered steps) → Store in Neo4j

**Solution space:** Pure functions for extraction, YAML prompt templates, file type detection system

> **This changed because:** The v0.4.x FastAPI/Jinja2 approach was too coupled. Needed simpler extraction functions that could be tested independently.

---

# v0.4.x - The FastAPI/Jinja2 Era (June-July 2025)

**Architectural paradigm:** FastAPI backend + Jinja2 server-rendered templates + Run ID traceability

**Process model:** Repository Selection → Run ID Definition → Pipeline Execution (Extract → Derive → Export)

**Solution space:** Web UI for repository input, graph-based extraction, ArchiMate layer derivation

> **This changed because:** The v0.3.x extraction functions were too disconnected. Needed a proper web UI and pipeline orchestration.

---

## v0.4.0 - FastAPI/Jinja2 Architecture

### Technology Stack

| Technology | Purpose |
|------------|---------|
| FastAPI | REST API and orchestration |
| Jinja2 | Server-rendered HTML templates (43KB index.html) |
| Uvicorn | ASGI server |
| Neo4j | Graph database |
| UV | Package management |
| Python 3.13 | Core language |
| Docker Compose | Neo4j container |

### Key Features

**8-Week Implementation Roadmap:**
- Week 1: Project Setup (FastAPI, Neo4j, Jinja2 templates)
- Week 2: Core Services (Repository, Graph, Run ID system)
- Week 3-4: Extraction Pipeline (Discovery, LLM integration)
- Week 5-6: Derivation System (Business, Application, Technology layers)
- Week 7: ArchiMate Generation
- Week 8: Polish & Launch

**Flask Invoice Generator Test Target:**

```
Target: marcelemonds_flask_invoice_generator
Expected Elements:
- Application Component: Invoice Management System
- Application Service: Invoice Generation Service
- Data Object: Invoice (InvoiceDetails + Positions)
- Business Actor: Invoice Creator
- Technology Artifact: Flask Invoice Generator Application
```

**Run ID Traceability:**

Central concept linking all artifacts:
- Cloned repository paths
- Extracted file classifications
- Graph database entries
- Derived ArchiMate elements
- Final `.archimate` file

> **This changed because:** The FastAPI/Jinja2 approach proved the concept but was too tightly coupled. The learnings fed into v0.5.x's manager-based architecture.

---

## v0.3.5 - Pre-V2 Preparation
*Commits: 2b52689, 71b8b64*

- Refactored derivation module
- *Commit: "before another refactoring......"*, ominous ellipsis
- Preparing codebase for V2 merge

---

## v0.3.4 - Business & Technology Extraction
*Commits: 8aba989, e6551f4*

### Extraction Method Changes
- **BusinessConcept extraction:** First LLM-based extraction from documentation files
- **Technology extraction:** Infrastructure component identification
- Both use JSON schema for structured LLM output

> **This changed because:** Needed to extract semantic information beyond code structure, business domain concepts and technology stack.

---

## v0.3.3 - ArchiMate Model Generation
*Commits: ea6afa7, cc796f7, 9b94291*

- **Full ArchiMate model working:** JSON to XML transformation
- **Schema validation:** Both JSON structure and ArchiMate XML schema
- **File export:** Save models with `.archimate` extension (opens in Archi tool)

> **This changed because:** The goal was always to produce valid ArchiMate models, this was the first working end-to-end export.

---

## v0.3.2 - ArchiMate Layer Extraction
*Commits: b3f0c71, 11fe90b*

### Process Changes
- **Application layer extraction:** First ArchiMate-aware extraction step
- **LLM prompt templates:** `application_layer.yaml` for layer-specific prompts
- **ArchiMate schema:** Elements, relationships, validation rules

> **This changed because:** ...

---

## v0.3.1 - Neo4j & Graph Operations
*Commits: a0fd55f, b7200bb*

### Architecture Changes
- **Neo4j fully integrated**, graph manager with connection pooling
- **Graph operations layer**, node/edge CRUD, exclude file support
- **Cross-platform deployment**, scripts for bash, PowerShell, batch
- **Docker compose**, `compose.yaml` for containerized Neo4j

### Extraction Method Changes
- **Graph-based storage**, all extracted nodes stored in Neo4j
- **Relationship edges**, CONTAINS, DEPENDS_ON, etc.
- **Exclude patterns**, skip node_modules, .git, etc.

> **This changed because:** Needed persistent graph storage to build relationships between extracted elements and query the model.

---

## v0.3.0 - UV Rebuild & Extraction Functions
*Commits: 5fbca7a, 1a90e6d, d5889f6, 8a6a278, 321a344, 65e11e1, a552e14 (Apr 15-18, 2025)*

### The Second Purge
*Commit: 5fbca7a - "refactor for mvp on development"*
- **Deleted**, complete reset for MVP focus
- Removed: LICENSE, README, Docker configs, all extraction strategies, tests, UI components, API routes

### Architecture Changes (Post-Purge)
- **UV package manager**, replaced pip/requirements.txt with `uv.lock`
- **Layered extraction**, `step_1.py`, `step_2.py` approach
- **LLM model interfaces**, `model_interfaces/base.py`, `gpt_4_mini.py`
- **YAML prompt templates**, `module_discovery.yaml`, `custom.yaml`

### Extraction Method Changes
- **Function-based extraction**
  - `get_repo_files.py`, file discovery with type detection
  - `get_repo_metadata.py`, repository metadata extraction
  - `get_repo_modules.py`, module/package discovery
  - `get_repo_structure.py`, directory structure analysis
- **File type detection system**, separate detector per type
  - `source.py`, `test.py`, `config.py`, `build.py`
  - `docs.py`, `data.py`, `asset.py`, `exclude.py`

### Behind the Scenes

- **Planned Gradio UI architecture:**
  ```
  1. **UI Layer (Gradio)**
     - Repository URL input
     - Extraction control panel
     - Status feedback
  ```
- **"asef" commit**, test LLM scripts added (`scripts/testllm.py`, `scripts/llm_output.json`)
- **"intermed" commit**, checkpoint naming for work-in-progress

> **This changed because:** The strategy-based extraction was too complex. Needed simpler, testable functions. Also wanted to try UV for faster dependency management.

---

# v0.2.x - The FastAPI/Streamlit/Services Era

**Architectural paradigm:** FastAPI backend + Streamlit UI + Service layer + Strategy pattern

**Process model:** Clone → Extract (via strategies) → Store in Neo4j → (manual ArchiMate mapping)

**Solution space:** Multiple extraction strategies (simple, layered, bottom-up, top-down), tree-sitter for parsing

> **This changed because:** ...

---

## v0.2.5 - Windows Support
*Commit: 5272d70*

- **PowerShell scripts**, `start_local.ps1` for Windows users
- **Docker compose updates**, Windows path compatibility
- **Cross-platform shell scripts**, improved portability

---

## v0.2.4 - Documentation & Polish
*Commits: 3d3e844, 8c0f138, c290fd4, 9d30dcf, f1de740, 314727b*

- Python version pinned to 3.13.2
- *Commit: "little mermaid changes"*, mermaid diagram syntax updates
- *Commit body: "what is even a block-beta"*, questioning mermaid's design choices
- *Commit: "Okee, letsgo"*, enthusiastic .gitignore cleanup

---

## v0.2.3 - Layered Strategy Implementation
*Commits: 96755b5, 468aaaf (Feb 28, 2025)*

### Architecture Changes
- **Layered extraction strategy**, implementing 7-step extraction flow
- **ArchiMate metamodel**, mermaid, all ArchiMate layers (Business, Application, Technology, Physical, Strategy, Motivation, Implementation)
- **ArchiMate Pydantic models**, type definitions (auto-generated!)
  - Header comment, `"This file is auto-generated by parse_metamodel.py, do not edit directly"`
  - Generated classes for all 50+ ArchiMate element types

### Extraction Method Changes
- **Utility modules**
  - `code_analyzer.py`, Python AST-based analysis with `CodeElement` class and `PythonVisitor`
  - `config_analyzer.py`, configuration file parsing (JSON, YAML, TOML, INI)
  - `module_discovery.py`, project structure detection via file patterns
  - `test_analyzer.py`, test file identification and coverage analysis

### Layered Extraction Flow (from `layered.mmd`)

```
Repository Metadata → Module Discovery → File Discovery
        ↓                                      ↓
   Annotations ← Documentation First → Business Concepts
        ↓                                      ↓
Scripts/Configs → External Dependencies → Type Definitions
        ↓                                      ↓
Method Extraction → Parameter/Error/Variable → Service Discovery
        ↓                                      ↓
Relationship Mapping → Test Case Discovery → Final Confidence Scoring
```

> **This changed because:** Simple extraction wasn't enough, needed to understand code structure at multiple levels (files, modules, classes, functions).

---

## v0.2.2 - Submodule Regret
*Commit: 04a8301 (Feb 28, 2025)*

- **Removed all 10 tree-sitter submodules** added in previous commit
- Simple strategy confirmed working
- *Tree-sitter parsers lasted exactly one commit*

> **This changed because:** Submodules added too much complexity. Decided to use Python's AST instead of tree-sitter for parsing.

---

## v0.2.1 - Template Explosion
*Commit: d9a7f10 - "YOU GET A TEMPLATE, YOU GET A TEMPLATE!" (Feb 26, 2025)*

### Architecture Changes
- **5 extraction strategy templates**, Mermaid flowcharts for different approaches
  - `simple.mmd`, `layered.mmd`, `bottom_up.mmd`, `top_down.mmd`, `noredraw.mmd`
- **Tree-sitter submodules**, 10 language parsers (C, C++, C#, Go, Java, JavaScript, Python, Ruby, Rust, TypeScript)
- **Strategy pattern**, `strategies/base.py`, `simple.py`, `layered.py`, `bottom_up.py`, `top_down.py`
- **Tree-sitter installer script**, `scripts/install_tree_sitter_parsers.py`, cloned repos, built `languages.so`

### Process Changes
- **Neo4j interface**, graph storage backend
- **Graph service**, abstraction layer for graph operations

### The Tree-Sitter Experiment

```python
# From install_tree_sitter_parsers.py - the ambitious plan
language_repos = {
    "python": "https://github.com/tree-sitter/tree-sitter-python",
    "javascript": "https://github.com/tree-sitter/tree-sitter-javascript",
    # ... 8 more languages
}
# Built into: build/languages.so
```

*Note: Empty strategy files added, `bottom_up.py`, `layered.py`, `top_down.py`, optimistic placeholders that never got filled*

### Sample Test Repository

A complete test repository was created at `test/data/sample-repo/` with a realistic domain:

```python
@dataclass
class Order:
    """Represents a business order."""
    order_id: str
    customer_name: str
    items: List[str]
    total: float

class OrderProcessor:
    """Service for processing business orders."""
    def process_order(self, order: Order) -> bool:
        # Validate → Store → Notify pattern
```

This provided expected extraction targets: BusinessConcept (Order Processing), Service (OrderProcessor), TypeDefinition (Order), and Methods (process_order, _validate_order, _notify_success, _handle_error).

> **This changed because:** Wanted to support multiple extraction approaches for different use cases. Tree-sitter seemed like the right tool for multi-language parsing.

---

## v0.2.0 - The Phoenix Rises
*Commit: 62c5830 - "step 1 working"*

### The First Purge
*Commit: 32723c5 - "refactor"*
- **Deleted**, complete architectural reset
- Removed entire `src/` directory, all tests, scripts
- Added `buttom-up.md`, `top-down.md` (typo preserved: "buttom")

### Architecture Changes (Post-Purge)
- **FastAPI backend**, `src/api/` with routes and schemas
- **Streamlit UI**, `src/ui/` with component-based design
- **Service layer**, `src/services/repository/`, `src/services/extraction/`
- **Logging system**, color-coded output with configurable levels

### Process Changes
- **Mermaid metamodel parsing**, define graph structure in `.mmd` files
- **Repository service**, clone, analyze, track repositories

> **This changed because:** The original monolithic pipeline was hard to test and extend. Wanted proper separation: API, UI, Services.

---

# v0.1.x - The Initial Development Era

**Architectural paradigm:** Monolithic pipeline with JSON config files

**Process model:** Clone → Chunk → Extract → Analyze → Store

**Solution space:** Single pipeline, LLM-based analysis, Neo4j storage

> **This changed because:** ...

---

## v0.1.8 - Pre-Refactor Milestone
*Commit: 40505f4 - "commit before I refactor EVERYTHING"*

### Extraction Method Changes
- **Split monolithic analysis into focused analyzers:**
  - `business_concept_analysis.json`
  - `dependency_analysis.json`
  - `method_analysis.json`
  - `parameter_analysis.json`
  - `service_analysis.json`
  - `technology_analysis.json`
  - `type_analysis.json`
- **Metadata extraction:** Separate module for repo metadata

> **This changed because:** Single analysis prompt was too broad. Splitting by concept type improved LLM accuracy.

---

## v0.1.7 - Memory & Metamodel
*Commits: 21a36c2, 352aef0, 5ff481d, 599d8d9, 4144f95*

- **Persistent context**, storage for run state
- **Full metamodel**, code-to-graph transformation rules
- **Mermaid definitions**, graph structure in `.mmd` format
- **Docs refresh**, README updates across multiple commits

---

## v0.1.6 - Pipeline Refactor
*Commit: e692ef7*

### Architecture Changes
- **Config restructure**, `templates/prompts/` → `config/analyze/`
- **Chunking config**, `config/chunk/file_chunking.json`
- **Extraction config**, `config/extract/element_extraction.json`

### Process Changes
- **Chunk → Extract → Analyze**, three-stage pipeline
- **LLM chunking**, handle large files by splitting

> **This changed because:** ...

---

## v0.1.5 - Robustness
*Commits: 7bcf66c, 25a1f3f (Feb 22-23, 2025)*

### Process Changes
- **LLM retry mechanism**, `retry.py` with schema validation
- **Response caching**, `cache.py` for LLM response reuse
- **Schema validation**, `graph_schema.py` of validation logic
- **ArchiMate validator**, `archimate_schema.py`

### Retry Mechanism Details

```python
# RetryConfig from retry.py
max_attempts: int = 3
base_delay: float = 1.0      # seconds
exponential_base: float = 2.0  # backoff multiplier
max_delay: float = 10.0      # cap

# Key feature: prompts updated with validation errors
def _update_prompt_with_errors(original_prompt, error_context):
    # Appends: "Previous attempt had validation errors:..."
    # Includes: path, suggestion, expected values
```

### LLM Prompt Templates (from initial commit)

- **Chunk config**, `max_chunk_size: 1500`, `min_chunk_size: 500`, `overlap_size: 200`
- **Three prompt types**, `code_analysis.json`, `text_analysis.json`, `generic_analysis.json`
- **Output schema enforced**, nodes + relationships with strict types

> **This changed because:** LLM responses were inconsistent. Needed validation and retry to ensure usable output.

---

## v0.1.4 - Local Development
*Commit: 5f11272*

- **Docker compose local**, `docker-compose.local.yml`
- **Dev script**, `run_local.sh` for local workflow
- **Model improvements**, better Pydantic serialization

---

## v0.1.3 - Type System
*Commits: 5d05d65, 5f24e67*

- **Pydantic models**, analysis, base, repository types
- **Test suite**, model validation tests
- **Cleanup**, removed accidentally committed `.DS_Store`
- *Same commit message twice: "fixes and new types"*

---

## v0.1.2 - Housekeeping
*Commits: a656023, d06e7d7, ee10cdb, dcee2f4*

- Fixed import warning
- Added `.gitignore`
- *Commit: "gitnor"*, creative spelling of .gitignore
- *Commit: "ignore this"*, a questionable but memorable moment
- *Commit: "test"*, purpose unknown

---

## v0.1.1 - Initial Fixes
*Commit: a656023*

- Import warning fix (1 line change after 37k line commit)

---

## v0.1.0 - The Big Bang
*Commit: 27c8869 (Feb 22, 2025)*
*Lines: +36,986 (65 files)*

### Architecture
- **Pipeline**, `connect_repo` → `process_repo` → `graph_operations`
- **LLM client**, OpenAI integration (`src/common/llm/client.py`)
- **Storage**, Neo4j backend (`src/common/storage/neo4j.py`)
- **UI**, Streamlit app (`src/ui/app.py`)
- **Schemas**, ArchiMate XSD validation (3 schema files)
- **Deployment**, Docker (app + Neo4j containers)

### Original Graph Metamodel

```
Repository → Module → File → TypeDefinition → Method
                                    ↓
                              Parameter, Error, Variable → Value
                                    ↓
                         BusinessConcept, Service, Technology
```

### Original Dependencies (from pyproject.toml)

```toml
dependencies = [
    "gradio>=4.0.0",        # Gradio was the FIRST UI choice!
    "gitpython>=3.1.0",
    "pydantic>=2.0.0",
    "neo4j>=5.13.0",
    "openai>=1.0.0",        # OpenAI only, no multi-provider yet
    "jinja2>=3.0.0",
    "python-magic>=0.4.27",
]
# Target: Python 3.8 (tool.black target-version = ["py38"])
```

### Confidence Scoring from Day One

The `CodeElement` class in the code analyzer shows confidence was baked in from the start:

```python
class CodeElement:
    def __init__(self, name: str, element_type: str, file_path: str,
                 line_number: int, description: str = "", confidence: float = 0.8):
        # Default confidence of 0.8 for all elements
        self.relationships: List[Tuple[str, str, float]]  # (target, type, confidence)
```

### Strange Choices
- Committed `.DS_Store` files (Mac user on Windows project)
- Included `__pycache__/` and `.pyc` files (both Python 3.9 AND 3.13)
- Shipped ArchiMate HTML documentation
- 9 "Interoperability testing snippet" XML files (snippet-6.xml excluded, it's a transition view, not in scope)
- Committed with compiled bytecode from two different Python versions

> **This changed because:** First version, everything was new!

---

# Version Boundary Summary

| Era | Dates | Key Event | Architecture |
|-----|-------|-----------|--------------|
| **0.1.x** | Feb 22-25 | Initial development | Monolithic pipeline + JSON configs |
| **0.2.x** | Feb 26-Apr 15 | First Purge | FastAPI/Streamlit/Services/Strategies |
| **0.3.x** | Apr 15-25 | Second Purge | UV/Extraction functions/File types |
| **0.4.x** | Jun-Jul | Web UI prototype | FastAPI/Jinja2 |
| **0.5.x** | Aug-Nov | Final development | Managers/Modules/Marimo/DuckDB |

---

# Interesting Patterns

- **Rapid iteration**, v0.1.0 to v0.2.0 (First Purge) took only 4 days (Feb 22-26)
- **The long gap**, 4 months between v0.3.x (Apr) and v0.5.x (Aug), with v0.4.x prototype in between
- **UI evolution**, Streamlit → FastAPI+Jinja2 (v0.4.x) → Gradio (planned) → Marimo (final)
- **Graph DB constant**, Neo4j was the only technology that survived all purges
- **Config evolution**, JSON files → YAML templates → DuckDB tables
- **Dependency evolution**
  - v0.1.0: 9 dependencies (gradio, openai, neo4j...)
  - v0.5.x: 22 dependencies (marimo, duckdb, polars, networkx, altair...)
- **Python version ambition**, started targeting Python 3.8, now requires Python 3.14
- **Solo developer**, all 51 commits by a single author across 10 months
- **Confidence scoring**, present from day 1, default 0.8 confidence on all extracted elements
- **Test target consistency**, Flask Invoice Generator used from v0.4.x through v0.5.x

---

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) | Versioning: [SemVer](https://semver.org/spec/v2.0.0.html)
