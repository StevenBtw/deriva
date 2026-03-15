# Deriva
[![Research Project](https://img.shields.io/badge/Research-Project-blueviolet.svg)](#)
[![Build Status](https://github.com/StevenBtw/Deriva/actions/workflows/ci.yml/badge.svg)](https://github.com/StevenBtw/Deriva/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14+-blue.svg)](https://www.python.org/downloads/)
[![Grafeo](https://img.shields.io/badge/Grafeo-embedded-green.svg)](https://github.com/StevenBtw/grafeo)
[![Marimo](https://img.shields.io/badge/Marimo-notebook-orange.svg)](https://marimo.io/)

**Automatically generate ArchiMate enterprise architecture models from software repositories.**

Deriva analyzes code repositories and transforms them into [ArchiMate](https://www.opengroup.org/archimate-forum) models that can be opened in the [Archi modeling tool](https://www.archimatetool.com/).

![Deriva App](assets/app.png)

## How It Works

1. **Clone** a Git repository
2. **Extraction** - Build a graph representation:
   - **Classify phase**: Categorize files by type and subtype using registry
   - **Parse phase**: Extract semantic nodes (TypeDefinitions, Methods, BusinessConcepts, etc.)
   - Python files use fast AST parsing; other languages use LLM
3. **Derivation** - Generate ArchiMate elements using a hybrid approach:
   - **Prep phase**: Graph enrichment (PageRank, Louvain communities, k-core)
   - **Generate phase**: LLM-based element derivation with graph metrics
   - **Refine phase**: Relationship derivation and quality assurance
4. **Export** to `.xml` file (ArchiMate format)

## Quick Setup

### Prerequisites

- **Python 3.14+**
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
# Edit .env with your settings (LLM API keys, etc.)
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

### 5. Launch Deriva

```bash
cd ../../..  # Back to Deriva root
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
| TypeDefinition | Extracts classes, functions (AST for Python) | Yes |
| Method | Extracts methods from type definitions | Optional |
| Edge | Extracts relationships (IMPORTS, USES, CALLS, DECORATED_BY, REFERENCES) | Yes |
| Technology | Detects frameworks and libraries | Optional |
| ExternalDependency | Maps external dependencies | Optional |
| Test | Extracts test definitions | Optional |

### 3. Configure LLM (Optional)

If using LLM-assisted extraction, configure your provider in `.env`:

```bash
# Set default model to use
LLM_DEFAULT_MODEL=mistral-devstral

# Configure the model (naming: LLM_{NAME}_*)
LLM_MISTRAL_DEVSTRAL_PROVIDER=mistral
LLM_MISTRAL_DEVSTRAL_MODEL=devstral-2512
LLM_MISTRAL_DEVSTRAL_URL=https://api.mistral.ai/v1/chat/completions
LLM_MISTRAL_DEVSTRAL_KEY=your-key-here
LLM_MISTRAL_DEVSTRAL_STRUCTURED_OUTPUT=true
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

1. Set export path (default: `workspace/output/model.xml`)
2. Click **"Export Model"**
3. Open the file with [Archi](https://www.archimatetool.com/)

**Via CLI:**
```bash
deriva export -o workspace/output/model.xml
```

---

## Configuration

### Environment Variables (.env)

All configuration lives in `.env`. Key settings:

```bash
# Graph database (grafeo embedded)
GRAFEO_DB_PATH=          # Empty = in-memory, path = persistent file

# LLM Provider (mistral, openai, azure, anthropic, ollama, lmstudio)
LLM_MISTRAL_DEVSTRAL_PROVIDER=mistral
LLM_MISTRAL_DEVSTRAL_MODEL=devstral-2512
LLM_MISTRAL_DEVSTRAL_URL=https://api.mistral.ai/v1/chat/completions
LLM_MISTRAL_DEVSTRAL_KEY=your-mistral-api-key
LLM_MISTRAL_DEVSTRAL_STRUCTURED_OUTPUT=true

# Namespaces
GRAPH_NAMESPACE=Graph
ARCHIMATE_NAMESPACE=Model
```

See `.env.example` for all available options.

### Rate Limiting

The LLM adapter includes built-in rate limiting to prevent API throttling:

```bash
# Requests per minute (0 = use provider default: 60 RPM for cloud, unlimited for local)
LLM_RATE_LIMIT_RPM=0

# Minimum delay between requests in seconds
LLM_RATE_LIMIT_DELAY=0.0

# Max retries on rate limit (429) errors
LLM_RATE_LIMIT_RETRIES=3

# Adaptive throttling (reduces RPM when hitting rate limits)
LLM_THROTTLE_ENABLED=true
LLM_THROTTLE_MIN_FACTOR=0.25    # Minimum 25% of configured RPM
LLM_THROTTLE_RECOVERY_TIME=60   # Seconds before trying to increase RPM

# Circuit breaker (stops requests when provider is failing)
LLM_CIRCUIT_BREAKER_ENABLED=true
LLM_CIRCUIT_FAILURE_THRESHOLD=5   # Consecutive failures to open circuit
LLM_CIRCUIT_RECOVERY_TIME=30      # Seconds before testing recovery
```

Default rate limits by provider:

| Provider | Default RPM |
|----------|-------------|
| OpenAI | 30 |
| Anthropic | 30 |
| Mistral | 24 |
| Ollama | Unlimited |
| LM Studio | Unlimited |

The rate limiter automatically:

- Throttles requests to stay within limits
- Applies exponential backoff on rate limit errors (HTTP 429)
- Respects Retry-After headers from providers
- Adaptively reduces RPM when hitting rate limits (recovers over time)
- Opens circuit breaker after consecutive failures to prevent cascading errors

### Managing File Types

If you encounter **undefined extensions** during extraction:

**Via UI (Marimo):**

1. Navigate to **Column 2** → **Undefined Extensions**
2. Add them to the registry:
   - Extension (e.g., `.tsx`, `Dockerfile`)
   - Type (source, config, docs, test, build, asset, data, exclude)
   - Subtype (e.g., `typescript`, `docker`)

**Via CLI:**

```bash
# List all registered file types
deriva config filetype list

# Add a new file type
deriva config filetype add ".tsx" source typescript

# Delete a file type
deriva config filetype delete ".tsx"

# Show file type statistics by category
deriva config filetype stats
```

> **Note:** Files with unrecognized extensions are automatically classified as `file_type="unknown"` with their extension as the subtype. This ensures all files get proper classification even without explicit registry entries.

### Updating Configurations (Versioning)

Deriva uses a **versioning system** for configurations. When you update a config, a new version is created while preserving previous versions for rollback.

**Correct ways to update configs:**

1. **Via UI (Marimo)**: Navigate to the config section, edit, and click **"Save Config"**
2. **Via CLI**: Use the `config update` command

```bash
# Update extraction config instruction
deriva config update extraction BusinessConcept \
  -i "New instruction text..."

# Update extraction config with batch size for multi-file LLM calls
deriva config update extraction BusinessConcept \
  --batch-size 5

# Update derivation config from file
deriva config update derivation ApplicationComponent \
  --instruction-file prompts/app_component.txt

# View all versions
deriva config versions
```

**Do NOT use JSON import/export for config updates.** The `db_tool import` command is only for backup restoration or migration - it overwrites version history. See [BENCHMARKS.md](BENCHMARKS.md) for the optimization workflow.

### Customizing Extraction Prompts

For LLM-assisted extraction steps:

1. Navigate to **Column 2** → **Extraction Step Configuration**
2. Expand a node type (e.g., TypeDefinition)
3. Edit: Input File Types, Input Graph Elements, Instruction, Example
4. Click **"Save Config"** (this creates a new version)

All prompts follow the **Input + Instruction + Example** pattern.

---

## UI Layout

Deriva uses a multi-column marimo notebook layout:

| Column | Purpose |
|--------|---------|
| **0** | **Run Deriva**: Pipeline execution buttons, status display |
| **1** | **Configuration**: Runs, repositories, graph database, graph stats, ArchiMate, LLM |
| **2** | **Extraction Settings**: File type registry, extraction step configuration |
| **3** | **Derivation Settings**: Element type configuration (13 types across Business/Application/Technology layers), relationship derivation |

The UI is powered by `PipelineSession` from the services layer, providing a clean separation between presentation and business logic.

---

## Data Storage

- **Grafeo** (embedded graph database):
  - **Graph namespace**: Intermediate representation (Modules, Files, Dependencies)
  - **Model namespace**: ArchiMate elements and relationships
- **DuckDB** (`deriva/adapters/database/sql.db`): File type registry, extraction configs, settings

### Clearing Data

**Column 0: Run Overview**

- **Clear Graph**: Removes all nodes/edges from Graph namespace
- **Clear Model**: Removes all ArchiMate elements and relationships

---

## Querying the Graph

You can query the embedded grafeo graph database using Cypher via the CLI or Marimo notebook:

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
deriva --help

# View configuration
deriva config list extraction
deriva config show extraction BusinessConcept
deriva status

# Manage file types
deriva config filetype list
deriva config filetype add ".lock" dependency lock
deriva config filetype stats

# Run pipeline stages
deriva run extraction --repo flask_invoice_generator -v
deriva run derivation -v
deriva run derivation --phase generate -v  # Run specific phase (prep, generate, refine)
deriva run all --repo myrepo

# Export ArchiMate model
deriva export -o workspace/output/model.xml
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

Deriva includes a multi-model benchmarking system for comparing LLM performance across different providers and models. See [BENCHMARKS.md](BENCHMARKS.md) for the full guide and [OPTIMIZATION.md](OPTIMIZATION.md) for detailed case studies.

### Running Benchmarks

```bash
# List available benchmark models
deriva benchmark models

# Run a benchmark with specific models
deriva benchmark run \
  --repos flask_invoice_generator \
  --models openai-gptx,ollama-devstral \
  -n 3 \
  -d "Comparing gptx with devstral" \
  -v

# List benchmark sessions
deriva benchmark list

# Analyze a benchmark session
deriva benchmark analyze bench_20260101_150724
```

### Configuring Benchmark Models

Add models to `.env` using the pattern:

```bash
# Azure GPT-4o-mini
LLM_AZURE_GPT4MINI_PROVIDER=azure
LLM_AZURE_GPT4MINI_MODEL=gpt-4
LLM_AZURE_GPT4MINI_URL=https://your-resource.openai.azure.com/...
LLM_AZURE_GPT4MINI_KEY=your-api-key

# Ollama local model
LLM_OLLAMA_LLAMA_PROVIDER=ollama
LLM_OLLAMA_LLAMA_MODEL=devstral
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
- [Grafeo](https://github.com/StevenBtw/grafeo) - Embedded graph database
- [ArchiMate](https://www.opengroup.org/archimate-forum) - Enterprise architecture standard
- [Archi](https://www.archimatetool.com) - Open source ArchiMate modeling tool
- [Tree-sitter](https://tree-sitter.github.io/tree-sitter/) - Multi-language AST parsing

---

**Status**: Active Development
