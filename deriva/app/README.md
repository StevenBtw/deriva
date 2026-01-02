# Deriva App

Interactive Marimo notebook for configuring and running the Deriva pipeline.

## Purpose

The App provides a visual interface for managing repositories, configuring extraction/derivation steps, running the pipeline, and viewing results. It uses [Marimo](https://marimo.io) for reactive notebook functionality.

## Running the App

```bash
uv run app
```

Opens in browser at: <http://127.0.0.1:2718>

## UI Layout

| Column | Purpose |
|--------|---------|
| **0** | **Run Deriva** - Pipeline buttons, status display |
| **1** | **Configuration** - Runs, repositories, Neo4j, graph stats, ArchiMate model |
| **2** | **Extraction Settings** - File type registry, extraction step config |
| **3** | **Derivation Settings** - Derivation step config (prep/generate/refine phases) |

## Key Features

**Column 0: Run Deriva**

- Run full pipeline, extraction only, or derivation only
- View pipeline status with node/element counts
- Clear graph or model data

**Column 1: Configuration**

- Create and manage pipeline runs
- Clone and select repositories
- View graph statistics and ArchiMate model counts
- Export to Archi-compatible XML

**Column 2: Extraction Settings**

- Manage file type registry (add/edit extensions)
- Configure extraction steps (enable/disable, edit prompts)
- View undefined extensions discovered during extraction

**Column 3: Derivation Settings**

- Configure derivation steps by phase (prep, generate, refine)
- Edit LLM prompts and examples

## Architecture

The app uses `PipelineSession` from the services layer as its single interface to the backend:

```python
from deriva.services.session import PipelineSession

with PipelineSession() as session:
    session.run_extraction(repo_name="my-repo")
    session.run_derivation()
    session.export_model("output.archimate")
```

The app does **not** import adapters directly - all operations go through `PipelineSession`.

## Marimo Specifics

- Each variable can only be defined in ONE cell
- Access `.value` of UI elements in a separate cell from definition
- Underscore prefix (`_temp`) makes variables cell-local
- No callbacks - Marimo's reactivity handles UI updates automatically

## See Also

- [CONTRIBUTING.md](../../CONTRIBUTING.md) - Marimo editing guidelines and architecture
- [Marimo Docs](https://docs.marimo.io) - Framework documentation
