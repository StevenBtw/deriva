# Deriva CLI

Headless command-line interface for Deriva pipeline operations.

## Purpose

The CLI enables automation and scripting of Deriva operations without the studio. Useful for CI/CD pipelines, batch processing, and headless environments.

## Running the CLI

```bash
deriva --help
```

## Commands

### Config Management

```bash
# List extraction or derivation configs
deriva config list extraction
deriva config list derivation --enabled

# Show detailed config
deriva config show extraction BusinessConcept
deriva config show derivation ApplicationComponent

# Enable/disable steps
deriva config enable extraction TypeDefinition
deriva config disable derivation Technology

# Update config (creates new version)
deriva config update extraction BusinessConcept \
    --instruction "Extract business concepts..." \
    --example '{"concepts": [...]}'

# Update extraction batch size (files per LLM call)
deriva config update extraction BusinessConcept --batch-size 5

# LLM model configs in .env (keys shown masked; other lines kept)
deriva config model list
deriva config model set mistral-small --provider mistral --model mistral-small-latest --key <key>
deriva config model delete mistral-small
```

### Pipeline Execution

```bash
# Run extraction (all phases or specific phase)
deriva run extraction --repo my-repo -v
deriva run extraction --phase classify -v  # File classification only
deriva run extraction --phase parse -v     # Parse phase only

# Run derivation (all phases or specific phase)
deriva run derivation -v
deriva run derivation --phase generate -v

# Run full pipeline
deriva run all --repo my-repo -v
```

### Export

```bash
# Export ArchiMate model to XML
deriva export -o workspace/output/model.xml
```

### Status & Clear

```bash
# View pipeline status
deriva status

# Clear data
deriva clear graph
deriva clear model
```

### Benchmarking

```bash
# List available benchmark models
deriva benchmark models

# Run benchmark
deriva benchmark run \
    --repos flask_invoice_generator \
    --models azure-gpt4mini,ollama-llama \
    -n 3 -v

# Run benchmark without enrichment caching
deriva benchmark run --repos my-repo -n 3 --no-enrichment-cache

# Skip enrichment cache for specific configs
deriva benchmark run --repos my-repo -n 3 \
    --nocache-enrichment-configs ApplicationComponent,ApplicationService

# List sessions and analyze
deriva benchmark list
deriva benchmark analyze bench_20260101_150724

# Export a session as one zip (logs, LLM calls, models, config texts, environment, sha256 manifest)
deriva benchmark export bench_20260101_150724 -o workspace/exports/bench_20260101_150724.zip
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

Like the studio, the CLI uses `PipelineSession` as its single interface to the backend:

```python
from deriva.services.session import PipelineSession

with PipelineSession() as session:
    session.run_extraction(repo_name="my-repo")
```

The CLI does **not** import adapters directly.

## See Also

- [CONTRIBUTING.md](../../CONTRIBUTING.md) - Architecture and coding guidelines
