# Deriva Benchmarking Guide

This guide explains how to run benchmarks and analyze LLM consistency in Deriva's pipeline.

> **For developers** optimizing prompts and configurations, see [OPTIMIZATION.md](OPTIMIZATION.md) for detailed case studies, lessons learned, and the optimization log.

## Overview

Deriva transforms code repositories into ArchiMate models through a two-stage pipeline:

1. **Extraction** - Analyzes source code and creates graph nodes (classes, functions, modules, etc.)
2. **Derivation** - Uses LLM to derive ArchiMate elements from the extracted graph

Each stage is driven by **configurations** stored in the database. By benchmarking different config variants and analyzing deviations, you can systematically improve output quality.

---

## Understanding Configurations

<details>
<summary><strong>Extraction Configs</strong></summary>

Extraction configs define how to extract specific node types from source code.

| Field | Description |
|-------|-------------|
| `node_type` | Type of node to extract (e.g., "Class", "Function", "Module") |
| `instruction` | LLM prompt explaining what to extract |
| `example` | Example output to guide the LLM |
| `input_sources` | Which files/patterns to analyze |
| `sequence` | Order of execution |
| `enabled` | Whether this step runs |

</details>

<details>
<summary><strong>Derivation Configs</strong></summary>

Derivation configs define how to create ArchiMate elements from graph nodes.

| Field | Description |
|-------|-------------|
| `element_type` | ArchiMate type (e.g., "ApplicationComponent", "DataObject") |
| `instruction` | LLM prompt for derivation logic |
| `example` | Example transformation |
| `input_graph_query` | Cypher query to select input nodes |
| `sequence` | Order of execution |
| `enabled` | Whether this step runs |

</details>

<details>
<summary><strong>Viewing Configs via CLI</strong></summary>

```bash
# List all extraction configs
deriva config list extraction

# List enabled derivation configs
deriva config list derivation --enabled

# Show detailed config
deriva config show derivation ApplicationComponent
```

</details>

---

## The Cascading Effect

Problems in extraction cascade through the entire pipeline:

```
Extraction (Graph Nodes)
    └─ Poor class detection → Missing nodes in graph
                                  ↓
Derivation (ArchiMate Elements)
    └─ Missing ApplicationComponents → Incomplete architecture model
                                            ↓
Export (ArchiMate XML)
    └─ Gaps in enterprise architecture
```

**Key insight:** Optimizing early stages (extraction) has compound benefits. A 10% improvement in class detection can yield 20%+ improvement in final model quality.

---

## Default Benchmark Models

Deriva uses three models by default for multi-model benchmarking:

| Model Name | Provider | Description |
|------------|----------|-------------|
| `anthropic-haiku` | Anthropic API | Claude Haiku 4.5 - fast, cost-effective |
| `openai-gpt41mini` | OpenAI API | GPT-4.1-mini - balanced performance |
| `mistral-devstral2` | Mistral API | Devstral-2512 - code-focused |

These are configured in `.env` under the **BENCHMARK MODELS** section.

---

## Benchmarking Workflow

### 1. Run a Baseline Benchmark

Establish a baseline with multiple runs to measure consistency:

```bash
# Clone test repository
deriva repo clone https://github.com/marcelemonds/flask_invoice_generator

# Run benchmark with --no-cache to get real variance data
deriva benchmark run \
  --repos flask_invoice_generator \
  --models openai-gptx \
  --runs 5 \
  --no-cache \
  --verbose
```

> **Important:** Use `--no-cache` for initial benchmarks to measure actual LLM variance. Cached runs always produce identical outputs.

#### Per-Repository Mode

By default, multiple repos are combined into one model. Use `--per-repo` to benchmark each repository individually:

```bash
# Per-repo mode: each repo gets its own benchmark runs
deriva benchmark run \
  --repos repo1,repo2 \
  --models gpt4 \
  -n 3 \
  --per-repo
# Creates 6 runs: 2 repos × 1 model × 3 iterations
```

**When to use per-repo mode:**

- Comparing model performance across different codebases
- Testing prompts that may work better for certain repo structures
- Getting independent consistency scores per repository

### 2. Analyze Results

```bash
deriva benchmark analyze bench_20260103_094609
```

The analysis produces `workspace/benchmarks/<session>/analysis/summary.json` with:

- `stable_elements`: Elements that appear in ALL runs
- `unstable_elements`: Elements that vary between runs
- `count_variance`: How much element counts differ

**Low consistency (< 80%) indicates configs need optimization.**

### 3. Update Config with Versioning

When you modify a config, Deriva creates a new version for rollback:

```bash
# Update instruction inline
deriva config update derivation ApplicationComponent \
  -i "Identify software components that encapsulate business logic..."

# Or from file for longer instructions
deriva config update derivation ApplicationComponent \
  --instruction-file prompts/app_component.txt
```

> **Warning:** Do NOT update configs by editing JSON files and using `db_tool import`. This overwrites the database including version history. Always use `config update` via CLI or the UI.

### 4. Test the Changed Config Only

Use `--nocache-configs` to test your change while keeping other configs cached:

```bash
deriva benchmark run \
  --repos flask_invoice_generator \
  --models openai-gptx \
  --runs 5 \
  --nocache-configs ApplicationComponent
```

This is cost-efficient: cached configs cost $0, only the tested config incurs LLM costs.

### 5. Compare Results

```bash
deriva benchmark analyze bench_20260103_130000
```

If consistency improved (e.g., 28% → 78%), the change helped.

### Measure One Pipeline Step

`benchmark step` repeats a single pipeline step on a fixed input and compares only what that step produces. Nothing before or after it varies, so a change to one step is measured without the noise of the rest of the pipeline.

```bash
deriva benchmark step BusinessConcept --repos my-repo --model openai-gptx -n 3 -v
deriva benchmark step DataObject --repos my-repo --model openai-gptx -n 3 -v
```

- The step is an extraction step, a derivation step (an element type, `ConsolidatedRelationships` for the relationship pass, or a refine step), or `prep` for the whole prep phase (graph algorithms). Steps follow the pipeline order: extraction, prep, element steps, the relationship pass, refine.
- The step's input (every earlier step) is built once, with LLM answers from the cache (a prompt the cache does not have calls the LLM), and saved in the session folder (`steps/<repo>_input.grafeo`, graph and model).
- Each run copies that input into a separate work database (the repository's own graph is not touched) and calls the LLM for the step without the cache.
- The output of a run is every node and edge the step added, changed or removed, with its properties (timestamps left out). For derivation steps it also holds the model's elements (by identifier, disabled ones included) and relationships (by type, source and target, since relationship identifiers differ per run).
- **Presence** counts the objects produced in every run. **Exact** also requires the same properties, and the report names the properties that differ.
- For an element step, documentation, the LLM's own name for the element (`llm_name`) and its confidence are reported but not scored in exact: no later step reads them for identity. The report lists them as "Reported, not scored in exact".
- The report also gives the live LLM calls per run and the step's answer stability. Results are written to `step_results.json`.
- A step that classifies items in batches (BusinessConcept) also reports **decision stability**: the share of items with the same decision in every run. One changed label makes a whole batch answer differ, so this is the finer measure for such steps. Element steps report it per candidate: the stage the candidate reached (for example created, rejected, filtered out) and the element it became.
- It needs `GRAFEO_DB_DIR` (the input is copied per run as a file).

---

## CLI Reference

<details>
<summary><strong>Benchmark Commands</strong></summary>

```bash
# Run benchmark matrix
deriva benchmark run --repos <repos> --models <models> [options]
  --repos                       Comma-separated repository names (required)
  --models                      Comma-separated model config names (required)
  -n, --runs                    Runs per combination (default: 3)
  --stages                      Stages to run: extraction,derivation
  --no-cache                    Disable all LLM caching
  --nocache-configs             Configs to skip cache for (comma-separated)
  --no-enrichment-cache         Disable enrichment caching
  --nocache-enrichment-configs  Enrichment configs to skip cache for (comma-separated)
  --no-export-models            Disable exporting ArchiMate model files
  --per-repo                    Run each repo separatetely (default: combine all)
  -v, --verbose                 Show detailed text progress
  -q, --quiet                   Disable progress bar display

# Repeat one pipeline step (extraction, derivation or prep) on a fixed input and compare its outputs
deriva benchmark step <step> --repos <repos> --model <model> [options]
  --repos                       Comma-separated repository names (required)
  --model                       Model config name (required)
  -n, --runs                    Runs per repository (default: 3)
  -v, --verbose                 Show detailed text progress

# List benchmark sessions
deriva benchmark list

# Analyze consistency across runs, and the structure of every exported model
# (relationships per element, orphans, composition into more than one whole,
# cross-layer chains, precision and recall against the reference model)
deriva benchmark analyze <session_id>

# Analyze config deviations
deriva benchmark deviations <session_id>
  -o, --output    Output file path
  -s, --sort-by   Sort by: deviation_count, consistency_score, total_objects

# List available models
deriva benchmark models
```

</details>

<details>
<summary><strong>Config Commands</strong></summary>

```bash
# List configs
deriva config list extraction
deriva config list derivation --enabled

# Show config details
deriva config show <step_type> <name>

# Enable/disable configs
deriva config enable <step_type> <name>
deriva config disable <step_type> <name>

# Update config (creates new version)
deriva config update <step_type> <name> [options]
  -i, --instruction      New instruction text
  -e, --example          New example text
  --instruction-file     Read instruction from file
  --example-file         Read example from file
  -q, --query            New graph query (derivation only)
  -s, --sources          New input sources (extraction only)

# Show active versions
deriva config versions
```

</details>

<details>
<summary><strong>File Type Commands</strong></summary>

```bash
# List all registered file types
deriva config filetype list

# Add a new file type
deriva config filetype add <extension> <file_type> <subtype>

# Examples
deriva config filetype add ".tsx" source typescript
deriva config filetype add ".lock" dependency lock

# Delete a file type
deriva config filetype delete <extension>

# Show statistics
deriva config filetype stats
```

</details>

---

## Progress Tracking

Benchmark operations display visual progress bars when `rich` is installed:

```bash
uv sync --extra progress
```

Use `-q/--quiet` to disable progress display, or `-v/--verbose` for detailed text output.

---

## Cost Optimization Tips

1. **Use `--nocache-configs` liberally** - Only pay for configs you're testing
2. **Start with 1 run** - Verify no errors before running 5x for consistency
3. **Test on small repos first** - `flask_invoice_generator` is ideal
4. **Cache warms up** - First benchmark is expensive, subsequent are cheap
5. **Batch model comparisons** - Test multiple models in one benchmark

---

## Output Files

Benchmark results are stored in `workspace/benchmarks/<session_id>/`:

| File | Description |
|------|-------------|
| `summary.json` | Session configuration and stats |
| `events.ocel.json` | OCEL 2.0 event log for process mining |
| `events.jsonl` | Streaming event format |
| `analysis/summary.json` | Consistency analysis results |
| `config_deviations.json` | Per-config deviation report |
| `models/*.archimate` | ArchiMate model files per run |

Use `--no-export-models` to disable model export and save disk space.

---

## Advanced Derivation Options

### Separated Phases Mode (defer_relationships)

Deriva supports a two-phase derivation architecture via the `defer_relationships` parameter:

| Mode               | Behavior                                                         | Use Case                              |
|--------------------|------------------------------------------------------------------|---------------------------------------|
| Legacy (`False`)   | Derive relationships after each element batch                    | Debugging, comparison (`--no-defer-relationships`) |
| Default (`True`)   | Create all elements first, then derive relationships in one pass | Recommended for all use cases         |

`deriva benchmark run` uses the deferred mode by default, like the pipeline itself. In the legacy mode, elements that a step classifies into roles get no relationships at all.

**Benefits of deferred mode:**

- All elements available as context during relationship derivation
- Fewer LLM calls (one pass per element type vs per batch)
- Reduced ordering effects improve consistency
- Graph-aware filtering more effective with complete element set

See [OPTIMIZATION.md](OPTIMIZATION.md#separated-derivation-phases-phase-46) for implementation details.

---

## Best Practices

1. **Always benchmark before and after changes** - Quantify improvement
2. **Fix high-deviation configs first** - Biggest impact on quality
3. **Document what worked** - Note successful prompt patterns
4. **Version control your prompts** - Deriva tracks versions, but backup important ones
5. **Test across repos** - A fix for one repo may break another

---

## Further Reading

- [OPTIMIZATION.md](OPTIMIZATION.md) - Detailed case studies, prompt engineering findings, and optimization log
- [CONTRIBUTING.md](CONTRIBUTING.md) - Architecture and development patterns
