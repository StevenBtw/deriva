# Deriva Changelog

Deriving ArchiMate models from code using knowledge graphs, heuristics and LLM's, a journey through architectural decisions, strategic purges and lot's (and lot's) of trial and error.

---

# v0.6.x - Deriva (December 2025 - January 2026)

## v0.6.4 - Benchmark with Deriva (this repo) runs stable and succesfull! (January 10 2026)

### Refine Module (NEW)

New post-derivation refinement phase with 5 quality assurance steps in `modules/derivation/refine/`:

- **Duplicate Elements**: Multi-tier detection (exact match → fuzzy match → LLM semantic check) with configurable auto-merge and survivor selection based on PageRank
- **Duplicate Relationships**: Exact duplicate removal and redundant relationship pair detection
- **Orphan Elements**: Identifies unconnected elements, proposes relationships from source graph patterns, optionally disables low-importance orphans
- **Structural Consistency**: Validates graph-to-model containment preservation (files in directories → components in systems)
- **Cross-Layer Coherence**: Checks ArchiMate layer connections (Business↔Application↔Technology) and flags floating elements

The refine phase runs after generation with config-driven step enablement. Each step returns detailed `RefineResult` with issues found/fixed counts.

### Graph Enrichment Stability Improvements

Major improvements for consistent results across different graph sizes and multi-repo setups:

- **Percentile Normalization**: New `normalize_to_percentiles()` functions convert absolute metrics (PageRank, k-core, degree) to 0-100 percentile ranks. A node at 90th percentile means "more important than 90% of nodes" regardless of graph size (50 or 5000 nodes)
- **Deterministic Louvain**: Fixed non-deterministic community detection by sorting nodes before algorithm execution. Same graph now produces identical community assignments every run
- **Graph Metadata**: New `GraphMetadata` dataclass captures graph statistics (total_nodes, density, max_kcore, num_communities). Returned with `EnrichmentResult` and propagated to refine steps via params
- **Per-Repository Isolation**: Added `repository_name` property extraction from node IDs and repo-aware edge filtering in `_get_graph_edges()`. Enables isolated enrichment per repo in multi-repo setups

New enrichment properties per node: `pagerank_percentile`, `kcore_percentile`, `in_degree_percentile`, `out_degree_percentile`

### General Improvements

Multiple minor improvements for different parts of the process:
- **Extraction Method Property**: Added extraction method (structural/ast/llm) property to the graph nodes
- **LLM Rate Limiting**: Extended the LLM manager (adapter) with rate limiting capabilities to gracefully deal with llm provider introduced rate limits
- **Status/Progress Bars**: Both the Marimo app and the cli now have visual indicators of progress during pipeline runs and benchmark runs (cli only)
- **Benchmark Output**: Added model output to the benchmark runs, with unique names ({repo}_{model}_{run#}.archimate)

### Full Test Pass

Removed and added a lot of tests, now fully caught up with all the changes. New test classes:

- `TestPercentileNormalization`, `TestGraphMetadata`, `TestPercentileEnrichments` for enrich module
- Comprehensive refine step tests for all 5 steps

Test coverage didn't jump because I deleted a lot of weak tests. Marimo (app) tests are still excluded.

### Graph Enrichment Module

New `modules/derivation/enrich.py` with graph algorithm pre-processing:
- **PageRank**: Node importance/centrality scoring
- **Louvain**: Community detection for natural component boundaries
- **K-core**: Core vs peripheral node classification
- **Articulation points**: Bridge node identification
- **Degree centrality**: In/out connectivity metrics

The enrichment runs before derivation, similar to how classification enriches files before extraction.

### Unified Element + Relationship Derivation

Major refactoring to generate elements and relationships in a single step:
- New `RelationshipRule` dataclass for valid relationships per element type
- LLM-based relationship derivation with `derive_batch_relationships()`
- All 13 element modules updated with `OUTBOUND_RULES` and `INBOUND_RULES`
- Removed obsolete relationship config infrastructure (database table, config class, JSON file)

Benchmark results on flask_invoice_generator: 15 elements, 15 relationships (Access, Serving, Composition, Flow, Realization, Aggregation, Assignment)

### Derivation Improvements

- Renamed `DerivationResult` to `GenerationResult`
- New `Candidate` dataclass with graph enrichment data
- Helper functions: `query_candidates()`, `get_enrichments()`, `batch_candidates()`
- Improved element building with `build_element()` and `parse_derivation_response()`

### Extraction Base Consolidation

Refactor of `modules/extraction/base.py`:
- Merged input_sources.py functionality into base.py
- Name normalization functions for packages, concepts, and technologies
- Canonical package names dictionary for consistent naming
- Singularization helper with irregular plurals support
- Removed `ast_extraction.py` and `input_sources.py`

---

## v0.6.3 - Database aAapter and Benchmark Improvements (January 9, 2026)

### Database Adapter Refactor

- Replaced SQL seed files with JSON data files for better portability
- New `db_tool.py` CLI for database export/import operations
- Added `data/` folder with per-table JSON files
- New exports: `export_database()`, `import_database()` in package API

### Benchmarking & Other Changes

- New `benchmarks.md` documentation
- Extended benchmarking service with additional metrics
- Graph manager: Added new query methods
- External dependency extractor: Major improvements
- Config service: New configuration functions

---

## v0.6.2 - New Derivation Modules & LLM Provider Expansion (January 7, 2026)

### New Derivation Modules

Major expansion with 6 new ArchiMate element modules:
- `ApplicationInterface`, `BusinessEvent`, `BusinessFunction` modules
- `Device`, `Node`, `SystemSoftware` technology layer modules
- Refactored existing modules to consistent style with improved prompts

### LLM Provider Expansion

- Added Mistral AI and LM Studio providers
- Fixed Claude response truncation and null response handling
- Fixed non-dict responses in external dependency extractor

### Extraction & Relationship Improvements

- Added `type` and `subtype` properties to File nodes
- Improved file classification logic
- Significant improvements to relationship derivation logic

### Bug Fixes & CI

- Fixed failing tests, type errors, and linting issues
- Aligned CI test coverage at 70%
- Updated documentation

---

## v0.6.1 - Extraction Refactor, Chunking, AST & Tests (January 3, 2026)

### Extraction Module Refactor

- Flattened `modules/extraction/` structure
- Added `common/chunking.py` with file chunking and overlap support
- New database scripts for chunking config and extraction method

### AST Parser & Claude Support

- Enhanced AST analysis for Python (classes, functions, imports)
- Added generic `tree-sitter` dependency for future multi-language support
- Added Claude Haiku model support

### Test Suite Expansion

Comprehensive test coverage across adapters, common utilities, extraction, derivation, and services. Enforced 70% minimum code coverage in CI.

---

## v0.6.0 - Rename to Deriva (January 1, 2026)

**AutoMate is now Deriva.**

The project has been renamed to reflect its broader scope. While initially focused on ArchiMate models, the architecture can derive other model types (C4, BPMN, UML, etc.) from source repositories.

Changes: renamed package directory, updated all imports, CLI commands, Docker containers, and documentation.

---

# v0.5.x - The Adapters/Modules/Services/Marimo+CLI Era (August 2025 - December 2025)

**Architectural paradigm:** Marimo notebook (`deriva/app/app.py`) with domain adapters and reusable modules.

**Process model:** Import -> Extraction -> Derivation -> Export

**Solution space:** 7 adapters (database, neo4j, repository, graph, archimate, llm, ast) + modular extraction/derivation functions + DuckDB config storage

---

## v0.5.11 - Improvements to the derivation module using graph techniques

- Flattened repo into single project layout
- Completed derivation module placeholders and stabilized graph-driven derivation
- Reached ~95% derivation consistency on small repo benchmark
- CLI now supports clearing Graph and Model namespaces

---

## v0.5.10 - Adapters Rename & Cleanup

- Renamed managers to adapters to clarify layering
- Consolidated operations and merged metamodel into models
- Added `.github/` scaffolding

---

## v0.5.9 - PipelineSession & Benchmarking

### PipelineSession

New unified API serving both CLI and Marimo:
- Context manager support for lifecycle management
- Query methods for reactive UI
- Orchestration for extraction, derivation, export
- Infrastructure control for Neo4j container management

### Benchmarking Service

Complete multi-model, multi-repository benchmarking framework:
- Test matrix: repos x models x runs
- OCEL integration for process mining analysis
- Post-run analysis with intra/inter-model consistency metrics

### OCEL 2.0 Module

Object-Centric Event Logging for process mining traceability, compliant with OCEL 2.0 standard.

### LLM Manager Refactor

- New protocol-based provider abstraction
- Implementations: Azure, OpenAI, Anthropic, Ollama providers
- Multi-model benchmarking support

### Architectural Boundaries

New per-directory ruff.toml files enforcing layer hierarchy (CLI/App -> services -> managers/modules -> common).

---

## v0.5.8 - Consistency Framework & Config Versioning

### Consistency Service

Framework for measuring LLM output stability:
- Stage-specific checks (extraction, derivation, validation)
- Deduplication and proper name property mapping
- Achieved 100% consistency through fixes

### Config Versioning System

- Versioned configuration updates preserving history
- Consistency run logging and history queries

### CLI Enhancements

New commands for config management, consistency checking, and history viewing.

### Validation Module Expansion

Comprehensive ArchiMate metamodel validation including relationship rules, naming conventions, orphan detection, and coverage checks.

---

## v0.5.7 - Operations Pattern & Neo4j Migration

### Graph Operations Rewritten

Complete rewrite from legacy DuckDB PGQ to Neo4j Cypher:
- Node/edge CRUD operations
- Graph traversal using Cypher patterns
- Subgraph extraction with depth limit

### ArchiMate Operations Directory

New operations following the graph manager pattern for elements, relationships, model operations, and queries.

### Code Quality

Fixed 60+ linter issues, updated type annotations, added documentation for the operations pattern.

---

## v0.5.6 - Code Quality & Standardization

### Standardized Pipeline Response Structure

Created unified `PipelineResult` TypedDict used by all pipeline stages with consistent fields for success, errors, warnings, stats, elements, and relationships.

### datetime.utcnow() Fixes

Fixed all deprecated `datetime.utcnow()` occurrences across extraction modules and LLM manager.

### LLM Cache Testing

New test file with 15 tests covering cache operations, statistics, and error handling.

---

## v0.5.5 - Complete Derivation Pipeline

### Derivation Service Rewrite

Two-phase approach:
1. **Element Derivation**: Config-driven via DuckDB with LLM-based derivation
2. **Relationship Derivation**: LLM derives relationships between created elements

### CLI Export Command

New `export` command for ArchiMate 3.0 Exchange Format, compatible with Archi modeling tool.

### Full Pipeline Working

Complete flow: extraction -> derivation -> validation -> export to `.archimate` file.

---

## v0.5.4 - Services Layer & CLI

### Services Layer Architecture

New `services/` layer for shared orchestration between Marimo and CLI:
- Config CRUD operations for DuckDB
- Extraction, derivation, validation pipeline orchestration
- Full pipeline orchestration with status tracking

### CLI Entry Point

Fully functional headless interface with configuration commands, pipeline execution, and various options.

### Workspace Consolidation

All workspace-related paths now use `workspace/` folder in project root.

---

## v0.5.3 - All Extraction Modules Complete

**Structural extraction (no LLM):** Repository, Directory, File modules

**LLM-based extraction:** BusinessConcept, TypeDefinition, Method, Technology, ExternalDependency, Test modules

### Process Changes

- Config-driven extraction with `input_sources` JSON column
- Module pattern standardization with shared base files and registry pattern

---

## v0.5.2 - Pipeline & Logging System

### 3-Level JSONL Logging System

- L1 (Phase): Neo4j operations, repo management, file classification
- L2 (Step): Config changes per step
- L3 (Detail): Full LLM details with tokens, cache status, retries

### Pipeline Orchestration

5 pipeline control buttons with step status tracking and proper execution order.

### LLM Manager Updates

Removed YAML config dependency, now uses `.env` configuration with multi-provider support.

---

## v0.5.1 - Foundation Complete

### Infrastructure

- Neo4j Docker setup with connection pooling
- DuckDB schema with configuration tables
- Repository workspace structure

### Manager Implementations

ArchimateManager, DatabaseManager, GraphManager, LLMManager, SourceManager, DerivationManager.

### UI Framework

4-column Marimo notebook layout for configuration, extraction, derivation, and status display.

---

## v0.5.0 - AutoMate V2 Merge

**Complete codebase replacement** merging parallel V2 development.

### Architecture Changes

- New structure: `managers/`, `modules/`, `layouts/`
- Single-file app: Marimo notebook with 4-column layout
- Config storage: DuckDB replaces JSON config files

### Process Model

Classification -> Extraction -> Derivation -> Validation -> Export

---

# v0.3.x - The UV/Extraction Functions Era

**Architectural paradigm:** UV package manager + extraction functions + layered steps

**Process model:** Clone -> Classify -> Extract (layered steps) -> Store in Neo4j

---

# v0.4.x - The FastAPI/Jinja2 Era (June-July 2025)

**Architectural paradigm:** FastAPI backend + Jinja2 templates + Run ID traceability

**Process model:** Repository Selection -> Run ID Definition -> Pipeline Execution

---

## v0.4.0 - FastAPI/Jinja2 Architecture

Web UI prototype with 8-week implementation roadmap. Introduced Run ID traceability linking all artifacts from cloned repos to final `.archimate` file.

---

## v0.3.5 - Pre-V2 Preparation

- Refactored derivation module
- Preparing codebase for V2 merge

---

## v0.3.4 - Business & Technology Extraction

- BusinessConcept extraction: First LLM-based extraction from documentation
- Technology extraction: Infrastructure component identification

---

## v0.3.3 - ArchiMate Model Generation

- Full ArchiMate model working: JSON to XML transformation
- Schema validation and file export with `.archimate` extension

---

## v0.3.2 - ArchiMate Layer Extraction

- Application layer extraction: First ArchiMate-aware step
- LLM prompt templates and ArchiMate schema

---

## v0.3.1 - Neo4j & Graph Operations

- Neo4j fully integrated with graph manager
- Graph operations layer for node/edge CRUD
- Docker compose for containerized Neo4j

---

## v0.3.0 - UV Rebuild & Extraction Functions

### The Second Purge

Complete reset for MVP focus - removed all previous extraction strategies, tests, and UI components.

### Post-Purge Changes

- UV package manager replacing pip
- Function-based extraction with file type detection system
- Layered extraction steps

---

# v0.2.x - The FastAPI/Streamlit/Services Era

**Architectural paradigm:** FastAPI backend + Streamlit UI + Service layer + Strategy pattern

**Process model:** Clone -> Extract (via strategies) -> Store in Neo4j

---

## v0.2.5 - Windows Support

PowerShell scripts and cross-platform compatibility improvements.

---

## v0.2.4 - Documentation & Polish

Python version pinned, documentation updates, `.gitignore` cleanup.

---

## v0.2.3 - Layered Strategy Implementation

- Layered extraction strategy implementing 7-step extraction flow
- ArchiMate metamodel and Pydantic models
- Utility modules for code analysis, config parsing, and module discovery

---

## v0.2.2 - Submodule Regret

Removed all 10 tree-sitter submodules. Decided to use Python's AST instead.

---

## v0.2.1 - Template Explosion

- 5 extraction strategy templates as Mermaid flowcharts
- Tree-sitter submodules for 10 languages
- Strategy pattern with base and specific implementations

---

## v0.2.0 - The Phoenix Rises

### The First Purge

Complete architectural reset - removed entire `src/` directory.

### Post-Purge Changes

- FastAPI backend with Streamlit UI
- Service layer for repository and extraction
- Mermaid metamodel parsing

---

# v0.1.x - The Initial Development Era

**Architectural paradigm:** Monolithic pipeline with JSON config files

**Process model:** Clone -> Chunk -> Extract -> Analyze -> Store

---

## v0.1.8 - Pre-Refactor Milestone

Split monolithic analysis into focused analyzers (business concepts, dependencies, methods, parameters, services, technologies, types).

---

## v0.1.7 - Memory & Metamodel

Persistent context storage, full metamodel, mermaid definitions.

---

## v0.1.6 - Pipeline Refactor

Config restructure with three-stage pipeline: Chunk -> Extract -> Analyze.

---

## v0.1.5 - Robustness

LLM retry mechanism with schema validation, response caching, and ArchiMate validation.

---

## v0.1.4 - Local Development

Docker compose local setup and dev scripts.

---

## v0.1.3 - Type System

Pydantic models and model validation tests.

---

## v0.1.2 - Housekeeping

Import fixes and `.gitignore` additions.

---

## v0.1.1 - Initial Fixes

Import warning fix.

---

## v0.1.0 - The Big Bang

Initial release with pipeline architecture, LLM client (OpenAI), Neo4j storage, Streamlit UI, ArchiMate schema validation, and Docker deployment.

---

# Version Boundary Summary

| Era | Dates | Key Event | Architecture |
|-----|-------|-----------|--------------|
| **0.1.x** | Feb 22-25 | Initial development | Monolithic pipeline + JSON configs |
| **0.2.x** | Feb 26-Apr 15 | First Purge | FastAPI/Streamlit/Services/Strategies |
| **0.3.x** | Apr 15-25 | Second Purge | UV/Extraction functions/File types |
| **0.4.x** | Jun-Jul | Web UI prototype | FastAPI/Jinja2 |
| **0.5.x** | Aug-Nov | Final development | Managers/Modules/Marimo/DuckDB |
| **0.6.x** | Dec-Jan | AutoMate renamed to Deriva | Focus on benchmark and optimization |

---

# Some highlights:

- **Rapid iteration**: v0.1.0 to v0.2.0 (First Purge) took only 4 days
- **The long gap**: 4 months between v0.3.x (Apr) and v0.5.x (Aug)
- **UI evolution**: Streamlit -> FastAPI+Jinja2 -> Gradio (planned) -> Marimo (final)
- **Graph DB constant**: Neo4j was the only technology that survived all purges
- **Config evolution**: JSON files -> YAML templates -> DuckDB tables
- **Python version ambition**: started targeting Python 3.8, now requires Python 3.14
- **Solo developer**: all commits by a single author across 10 months
- **Confidence scoring**: present from day 1, default 0.8 confidence on all elements
- **Deriva**: new name to underscore generalizability beyond ArchiMate

---

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) | Versioning: [SemVer](https://semver.org/spec/v2.0.0.html)
