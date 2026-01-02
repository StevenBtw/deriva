# Deriva CLI

Headless command-line interface for Deriva pipeline operations.

## Purpose

The CLI enables automation and scripting of Deriva operations without the Marimo UI. Useful for CI/CD pipelines, batch processing, and headless environments.

## Running the CLI

```bash
uv run cli --help
```

## Commands

### Config Management

```bash
# List extraction or derivation configs
uv run cli config list extraction
uv run cli config list derivation --enabled

# Show detailed config
uv run cli config show extraction BusinessConcept
uv run cli config show derivation ApplicationComponent

# Enable/disable steps
uv run cli config enable extraction TypeDefinition
uv run cli config disable derivation Technology

# Update config (creates new version)
uv run cli config update extraction BusinessConcept \
    --instruction "Extract business concepts..." \
    --example '{"concepts": [...]}'
```

### Pipeline Execution

```bash
# Run extraction
uv run cli run extraction --repo my-repo -v

# Run derivation (all phases or specific phase)
uv run cli run derivation -v
uv run cli run derivation --phase generate -v

# Run full pipeline
uv run cli run all --repo my-repo -v
```

### Export

```bash
# Export ArchiMate model to XML
uv run cli export -o workspace/output/model.archimate
```

### Status & Clear

```bash
# View pipeline status
uv run cli status

# Clear data
uv run cli clear graph
uv run cli clear model
```

### Benchmarking

```bash
# List available benchmark models
uv run cli benchmark models

# Run benchmark
uv run cli benchmark run \
    --repos flask_invoice_generator \
    --models azure-gpt4mini,ollama-llama \
    -n 3 -v

# List sessions and analyze
uv run cli benchmark list
uv run cli benchmark analyze bench_20260101_150724
```

## Common Options

| Option | Description |
|--------|-------------|
| `--repo NAME` | Process specific repository (default: all) |
| `--phase PHASE` | Derivation phase: prep, generate, or refine |
| `-v, --verbose` | Print detailed progress |
| `--no-llm` | Skip LLM-based steps |
| `-o, --output PATH` | Output file path |

## Architecture

Like the Marimo app, the CLI uses `PipelineSession` as its single interface to the backend:

```python
from deriva.services.session import PipelineSession

with PipelineSession() as session:
    session.run_extraction(repo_name="my-repo")
```

The CLI does **not** import adapters directly.

## See Also

- [CONTRIBUTING.md](../../CONTRIBUTING.md) - Architecture and coding guidelines
