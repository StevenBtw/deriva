# Deriva CLI

Headless command-line interface for Deriva pipeline operations.

## Purpose

The CLI enables automation and scripting of Deriva operations without the studio. Useful for CI/CD pipelines, batch processing, and headless environments.

## Running the CLI

```bash
deriva-cli --help
```

## Commands

### Config Management

```bash
# List extraction or derivation configs
deriva-cli config list extraction
deriva-cli config list derivation --enabled

# Show detailed config
deriva-cli config show extraction BusinessConcept
deriva-cli config show derivation ApplicationComponent

# Enable/disable steps
deriva-cli config enable extraction TypeDefinition
deriva-cli config disable derivation Technology

# Update config (creates new version)
deriva-cli config update extraction BusinessConcept \
    --instruction "Extract business concepts..." \
    --example '{"concepts": [...]}'

# Update extraction batch size (files per LLM call)
deriva-cli config update extraction BusinessConcept --batch-size 5

# LLM model configs in .env (keys shown masked; other lines kept)
deriva-cli config model list
deriva-cli config model set mistral-small --provider mistral --model mistral-small-latest --key  # asks for the key (hidden)
deriva-cli config model delete mistral-small
```

### Pipeline Execution

```bash
# Run extraction (all phases or specific phase)
deriva-cli run extraction --repo my-repo -v
deriva-cli run extraction --phase classify -v  # File classification only
deriva-cli run extraction --phase parse -v     # Parse phase only

# Run derivation (all phases or specific phase)
deriva-cli run derivation -v
deriva-cli run derivation --phase generate -v

# Run full pipeline
deriva-cli run all --repo my-repo -v
```

### Export

```bash
# Export ArchiMate model to XML
deriva-cli export -o workspace/output/model.xml
```

### Status & Clear

```bash
# View pipeline status
deriva-cli status

# Clear data
deriva-cli clear graph
deriva-cli clear model
```

### Benchmarking

```bash
# List available benchmark models
deriva-cli benchmark models

# Run benchmark
deriva-cli benchmark run \
    --repos my-repo \
    --models azure-gpt4mini,ollama-llama \
    -n 3 -v

# Run benchmark without the LLM cache
deriva-cli benchmark run --repos my-repo --models azure-gpt4mini -n 3 --no-cache

# Skip the LLM cache for specific configs
deriva-cli benchmark run --repos my-repo --models azure-gpt4mini -n 3 \
    --nocache-configs ApplicationComponent,ApplicationService

# List sessions and analyze
deriva-cli benchmark list
deriva-cli benchmark analyze bench_20260101_150724

# Export a session as one zip (logs, LLM calls, models, config texts, environment, sha256 manifest)
deriva-cli benchmark export bench_20260101_150724 -o workspace/exports/bench_20260101_150724.zip
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
