# Deriva
[![Build Status](https://github.com/StevenBtw/Deriva/actions/workflows/ci.yml/badge.svg)](https://github.com/StevenBtw/Deriva/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/StevenBtw/Deriva/graph/badge.svg?token=A3H2COO119)](https://codecov.io/gh/StevenBtw/Deriva)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-required-2496ED.svg?logo=docker)](https://www.docker.com/)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.x-008CC1.svg?logo=neo4j)](https://neo4j.com/)
[![Marimo](https://img.shields.io/badge/Marimo-notebook-orange.svg)](https://marimo.io/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://docs.astral.sh/uv/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://docs.astral.sh/ruff/)
[![Typing: ty](https://img.shields.io/badge/typing-ty-EFC621.svg)](https://docs.astral.sh/ty/)




**Automatically generate ArchiMate enterprise architecture models from software repositories.**

Deriva analyzes your code repositories and transforms them into ArchiMate models that can be opened in the [Archi modeling tool](https://www.archimatetool.com/). It uses a two-stage pipeline: Extraction → Derivation (with prep/generate/refine phases), with an intermediate graph representation stored in Neo4j.

## What Does Deriva Do?

1. **Clone** a Git repository
2. **Extract** a graph representation:
   - Classify files using heuristics and file type registry
   - Extract structural nodes (directories, files) and semantic nodes (TypeDefinitions, BusinessConcepts)
3. **Derive** ArchiMate elements (prep → generate → refine phases)
4. **Export** to `.archimate` XML file for use in Archi

## Quick Setup

### Prerequisites

- **Python 3.14+**
- **Docker** (for Neo4j)
- **uv** (Python package manager)

### 1. Install uv

```bash
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clone and Configure

```bash
git clone https://github.com/StevenBtw/Deriva.git
cd Deriva

# Create environment configuration
cp .env.example .env
# Edit .env with your settings (Neo4j, LLM API keys, etc.)
```

### 3. Create Python Environment

```bash
uv venv --python 3.14
```

Activate the virtual environment:

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# Windows Command Prompt
.venv\Scripts\activate.bat

# macOS/Linux
source .venv/bin/activate
```

### 4. Install Dependencies

```bash
uv sync
```

### 5. Start Neo4j

```bash
cd neo4j_manager
docker-compose up -d
```

Neo4j will be available at:

- **Browser UI**: http://localhost:7474 (no authentication)
- **Bolt Protocol**: `bolt://localhost:7687`

Verify Neo4j is running:

```bash
docker ps  # Should show deriva_neo4j container
```

### 6. Launch Deriva

```bash
cd ..  # Back to Deriva root
uv run marimo edit deriva/app/app.py
```

The marimo notebook opens in your browser at: http://127.0.0.1:2718

---

## First Time Setup

When you first open Deriva, you need to seed the configuration database.

### 1. Seed File Type Registry

Navigate to **Column 2: Manage Extraction** → **File Type Registry**

1. Click **"Seed from JSON"**
2. This loads default file type mappings from `extraction_config.json`
3. Categories include: Source, Config, Docs, Test, Build, Asset, Data, Exclude

### 2. Enable Extraction Steps

Navigate to **Column 2: Manage Extraction** → **Extraction Step Configuration**

Enable the extraction steps you need:

| Step | Purpose | Recommended |
|------|---------|-------------|
| Repository | Creates root node for the repo | Always |
| Directory | Creates directory structure nodes | Always |
| File | Creates file nodes with classification | Always |
| TypeDefinition | Extracts classes, functions, etc. | Yes |
| Technology | Detects frameworks and libraries | Optional |
| ExternalDependency | Maps external dependencies | Optional |

### 3. Configure LLM (Optional)

If using LLM-assisted extraction, configure your provider in `.env`:

```bash
LLM_PROVIDER=openai  # or azure, anthropic
LLM_OPENAI_API_KEY=your-key-here
LLM_OPENAI_MODEL=gpt-4
```

---

## Using Deriva

### Basic Workflow

#### 1. Clone a Repository

**Column 1: Configuration → Repositories**

1. Enter repository URL (e.g., `https://github.com/user/repo.git`)
2. Optionally specify a target name
3. Click **"Clone"**

#### 2. Run the Pipeline

**Column 0: Run Deriva**

- Click **"Run Deriva"** to run the full pipeline (extraction → derivation)
- Or use individual step buttons: **Extraction**, **Derivation**

Results display in a status callout showing nodes/elements created and any errors.

#### 3. View Results

**Column 1: Configuration**

- **Graph Statistics**: Node counts by type (Repository, Directory, File, etc.)
- **ArchiMate Model**: Element and relationship counts by type

#### 4. Export to Archi

**Column 1: Configuration → ArchiMate Model**

1. Set export path (default: `workspace/output/model.archimate`)
2. Click **"Export Model"**
3. Open the file with [Archi](https://www.archimatetool.com/)

**Via CLI:**
```bash
uv run python -m deriva.cli.cli export -o workspace/output/model.archimate
```

---

## Configuration

### Environment Variables (.env)

All configuration lives in `.env`. Key settings:

```bash
# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password

# LLM Provider (openai, azure, anthropic)
LLM_PROVIDER=openai
LLM_OPENAI_API_KEY=your-key
LLM_OPENAI_MODEL=gpt-4

# Namespaces
GRAPH_NAMESPACE=Graph
ARCHIMATE_NAMESPACE=Model
```

See `.env.example` for all available options.

### Managing File Types

If you encounter **undefined extensions** during extraction:

1. Navigate to **Column 2** → **Undefined Extensions**
2. Add them to the registry:
   - Extension (e.g., `.tsx`, `Dockerfile`)
   - Type (source, config, docs, test, build, asset, data, exclude)
   - Subtype (e.g., `typescript`, `docker`)

### Customizing Extraction Prompts

For LLM-assisted extraction steps:

1. Navigate to **Column 2** → **Extraction Step Configuration**
2. Expand a node type (e.g., TypeDefinition)
3. Edit: Input File Types, Input Graph Elements, Instruction, Example
4. Click **"Save Config"**

All prompts follow the **Input + Instruction + Example** pattern.

---

## UI Layout

Deriva uses a multi-column marimo notebook layout:

| Column | Purpose |
|--------|---------|
| **0** | **Run Deriva**: Pipeline execution buttons, status display |
| **1** | **Configuration**: Runs, repositories, Neo4j, graph stats, ArchiMate, LLM |
| **2** | **Extraction Settings**: File type registry, extraction step configuration |
| **3** | **Derivation Settings**: Derivation step configuration (prep/generate/refine phases) |

The UI is powered by `PipelineSession` from the services layer, providing a clean separation between presentation and business logic.

---

## Data Storage

- **Neo4j Graph Database**:
  - **Graph namespace**: Intermediate representation (Modules, Files, Dependencies)
  - **Model namespace**: ArchiMate elements and relationships
- **DuckDB** (`deriva.db`): File type registry, extraction configs, settings

### Clearing Data

**Column 0: Run Overview**

- **Clear Graph**: Removes all nodes/edges from Graph namespace
- **Clear Model**: Removes all ArchiMate elements and relationships

---

## Querying Neo4j Directly

Access the Neo4j browser at http://localhost:7474 and run Cypher queries:

```cypher
// See all repositories
MATCH (r:Graph:Repository) RETURN r

// See files in a repo
MATCH (repo:Graph:Repository)-[:Graph:CONTAINS*]->(f:Graph:File)
WHERE repo.name = 'my-repo'
RETURN f.name, f.file_type

// See type definitions
MATCH (td:Graph:TypeDefinition) RETURN td.name, td.type_category
```

---

## CLI (Headless Mode)

Deriva includes a full CLI for headless operation and automation:

```bash
# Help
uv run python -m deriva.cli.cli --help

# View configuration
uv run python -m deriva.cli.cli config list extraction
uv run python -m deriva.cli.cli config show extraction BusinessConcept
uv run python -m deriva.cli.cli status

# Run pipeline stages
uv run python -m deriva.cli.cli run extraction --repo flask_invoice_generator -v
uv run python -m deriva.cli.cli run derivation -v
uv run python -m deriva.cli.cli run derivation --phase generate -v  # Run specific phase
uv run python -m deriva.cli.cli run all --repo myrepo

# Export ArchiMate model
uv run python -m deriva.cli.cli export -o workspace/output/model.archimate
```

**CLI Options:**

| Option | Description |
|--------|-------------|
| `--repo NAME` | Process specific repository (default: all) |
| `--phase PHASE` | Run specific derivation phase: prep, generate, or refine |
| `-v, --verbose` | Print detailed progress |
| `--no-llm` | Skip LLM-based steps (structural extraction only) |
| `-o, --output PATH` | Output file path for export |

---

## Benchmarking

Deriva includes a multi-model benchmarking system for comparing LLM performance across different providers and models.

### Running Benchmarks

```bash
# List available benchmark models
uv run python -m deriva.cli.cli benchmark models

# Run a benchmark with specific models
uv run python -m deriva.cli.cli benchmark run \
  --repos flask_invoice_generator \
  --models azure-gpt4mini,ollama-llama \
  -n 3 \
  -d "Comparing Azure vs Ollama" \
  -v

# List benchmark sessions
uv run python -m deriva.cli.cli benchmark list

# Analyze a benchmark session
uv run python -m deriva.cli.cli benchmark analyze bench_20260101_150724
```

### Configuring Benchmark Models

Add models to `.env` using the pattern:

```bash
# Azure GPT-4o-mini
LLM_AZURE_GPT4MINI_PROVIDER=azure
LLM_AZURE_GPT4MINI_MODEL=gpt-4o-mini
LLM_AZURE_GPT4MINI_URL=https://your-resource.openai.azure.com/...
LLM_AZURE_GPT4MINI_KEY=your-api-key

# Ollama local model
LLM_OLLAMA_LLAMA_PROVIDER=ollama
LLM_OLLAMA_LLAMA_MODEL=llama3.2
LLM_OLLAMA_LLAMA_URL=http://localhost:11434/api/chat
```

### OCEL Event Logging

Benchmark runs are logged in **OCEL 2.0** (Object-Centric Event Log) format for process mining analysis:

- Events capture pipeline stages, LLM calls, and results
- Object types: `BenchmarkSession`, `BenchmarkRun`, `Repository`, `Model`
- Logs are saved to `workspace/benchmarks/{session_id}/events.ocel.json`

OCEL files can be analyzed with process mining tools like PM4Py, Celonis, or custom analysis scripts.

---

## Troubleshooting

### Neo4j Connection Issues

```bash
# Check if running
docker ps

# View logs
cd neo4j_manager && docker-compose logs

# Restart
docker-compose restart

# Clear all data (destructive!)
docker-compose down -v
```

### Port Conflicts

If ports 7687/7474 are in use, edit `neo4j_manager/docker-compose.yml`:

```yaml
ports:
  - "7688:7687"
  - "7475:7474"
```

Update `.env` accordingly:

```bash
NEO4J_URI=bolt://localhost:7688
```

### Marimo Issues

```bash
# Check Python version
python --version  # Should be 3.14+

# Reinstall dependencies
uv sync --reinstall

# Run without watch mode
uv run marimo edit deriva/app/app.py
```

---

## Contributing

For development setup, architecture details, and contribution guidelines, see [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

This means you can freely use, modify, and distribute this software, but if you run a modified version as a network service, you must make the source code available to users of that service.

See [LICENSE](LICENSE) for the full license text.

## Acknowledgments

- [Marimo](https://marimo.io) - Reactive Python notebooks
- [Neo4j](https://neo4j.com) - Graph database
- [ArchiMate](https://www.opengroup.org/archimate-forum) - Enterprise architecture standard
- [Archi](https://www.archimatetool.com) - Open source ArchiMate modeling tool

---

**Status**: Active Development
