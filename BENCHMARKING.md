# Deriva Benchmarking & Optimization Guide

This guide explains how to systematically optimize Deriva's pipeline using benchmarking and config-deviation analysis.

## Overview

Deriva transforms code repositories into ArchiMate enterprise architecture models through a two-stage pipeline:

1. **Extraction** - Analyzes source code and creates graph nodes (classes, functions, modules, etc.)
2. **Derivation** - Uses LLM to derive ArchiMate elements from the extracted graph

Each stage is driven by **configurations** stored in the database. By benchmarking different config variants and analyzing deviations, you can systematically improve output quality.

## Understanding Configurations

### Extraction Configs

Extraction configs define how to extract specific node types from source code.

| Field | Description |
|-------|-------------|
| `node_type` | Type of node to extract (e.g., "Class", "Function", "Module") |
| `instruction` | LLM prompt explaining what to extract |
| `example` | Example output to guide the LLM |
| `input_sources` | Which files/patterns to analyze |
| `sequence` | Order of execution |
| `enabled` | Whether this step runs |

### Derivation Configs

Derivation configs define how to create ArchiMate elements from graph nodes.

| Field | Description |
|-------|-------------|
| `element_type` | ArchiMate type (e.g., "ApplicationComponent", "DataObject") |
| `instruction` | LLM prompt for derivation logic |
| `example` | Example transformation |
| `input_graph_query` | Cypher query to select input nodes |
| `sequence` | Order of execution |
| `enabled` | Whether this step runs |

### Viewing Configs

```bash
# List all extraction configs
uv run python -m deriva.cli.cli config list extraction

# List enabled derivation configs
uv run python -m deriva.cli.cli config list derivation --enabled

# Show detailed config
uv run python -m deriva.cli.cli config show derivation ApplicationComponent
```

> **Note:** All CLI commands use `uv run python -m deriva.cli.cli` as the entry point.

## The Cascading Effect: Why Early Stages Matter

Problems in extraction cascade through the entire pipeline:

```
Extraction (Graph Nodes)
    ↓
    └─ Poor class detection → Missing nodes in graph
                                  ↓
Derivation (ArchiMate Elements)
    ↓
    └─ Missing ApplicationComponents → Incomplete architecture model
                                            ↓
Export (ArchiMate XML)
    ↓
    └─ Gaps in enterprise architecture
```

**Key insight:** Optimizing early stages (extraction) has compound benefits. A 10% improvement in class detection can yield 20%+ improvement in final model quality.

### Identifying the Root Cause

When you see issues in your ArchiMate model:

1. **Check derivation first** - Is the LLM prompt producing incorrect elements?
2. **Then check extraction** - Are the input graph nodes correct?
3. **Finally check sources** - Is the code being parsed correctly?

Use `benchmark deviations` to identify which configs produce inconsistent results.

## Benchmarking Workflow

### 1. Run a Baseline Benchmark

First, establish a baseline with multiple runs to measure consistency:

```bash
# Clone test repository
uv run python -m deriva.cli.cli repo clone https://github.com/marcelemonds/flask_invoice_generator

# Run benchmark with --no-cache to get real variance data
# (cached runs will show 100% consistency)
uv run python -m deriva.cli.cli benchmark run \
  --repos flask_invoice_generator \
  --models azure-gpt4mini \
  --runs 5 \
  --no-cache \
  --verbose
```

> **Important:** Use `--no-cache` for initial benchmarks to measure actual LLM variance. Cached runs always produce identical outputs.

### 2. Analyze Results

Use `benchmark analyze` to see consistency metrics:

```bash
# Analyze overall consistency
uv run python -m deriva.cli.cli benchmark analyze bench_20260103_094609

# Output shows:
# Overall Consistency: 28.0%
# INTRA-MODEL CONSISTENCY (stability across runs)
#   azure-gpt4mini @ flask_invoice_generator: 28.0%
# INCONSISTENCY HOTSPOTS
#   [HIGH] model: azure-gpt4mini (28.0%)
```

The analysis produces `workspace/benchmarks/<session>/analysis/summary.json` with:

- `stable_elements`: Elements that appear in ALL runs
- `unstable_elements`: Elements that vary between runs
- `count_variance`: How much element counts differ

Low consistency (< 80%) indicates configs need optimization.

### 3. Update Config with Versioning

When you modify a config, Deriva creates a new version (for rollback):

```bash
# Update instruction inline
uv run python -m deriva.cli.cli config update derivation ApplicationComponent \
  -i "Identify software components that encapsulate business logic..."

# Or from file for longer instructions
uv run python -m deriva.cli.cli config update derivation ApplicationComponent \
  --instruction-file prompts/app_component.txt
```

### 4. Test the Changed Config Only

Use `--nocache-configs` to test your change while keeping other configs cached:

```bash
# Only ApplicationComponent skips cache, others use cached responses
uv run python -m deriva.cli.cli benchmark run \
  --repos flask_invoice_generator \
  --models azure-gpt4mini \
  --runs 5 \
  --nocache-configs ApplicationComponent
```

This is crucial for cost-efficient testing:

- Cached configs: $0 LLM cost
- Tested config: Full LLM cost only for that step

### 5. Compare Results

```bash
# Check if consistency improved
uv run python -m deriva.cli.cli benchmark analyze bench_20260103_130000

# Compare with baseline
# If consistency went from 28% → 78%, the change helped
```

## Optimizing a Single Config Efficiently

### Step-by-Step Process

1. **Identify the Problem Config**
   ```bash
   uv run python -m deriva.cli.cli benchmark analyze <session_id>
   # Look for configs with < 95% consistency in the analysis/summary.json
   ```

2. **Examine Current Config**
   ```bash
   uv run python -m deriva.cli.cli config show derivation ApplicationComponent
   ```

3. **Analyze Deviating Objects**

   Check `workspace/benchmarks/<session>/analysis/summary.json` for:
   - `unstable_elements`: Which specific elements vary between runs
   - Look for patterns like naming inconsistencies or synonym usage

4. **Improve the Prompt**

   Common improvements:

   - **Enforce naming conventions** (singular vs plural, snake_case vs camelCase)
   - **Ban synonyms explicitly** ("Customer" not "Client", "User", or "Buyer")
   - **Provide exact identifier format** (`bus_obj_customer`, not `BusinessObject_Customer`)
   - Add "Output stable, deterministic results" instruction

5. **Test with Minimal Cost**
   ```bash
   # Single run first to verify no errors
   uv run python -m deriva.cli.cli benchmark run \
     --repos flask_invoice_generator \
     --models azure-gpt4mini \
     --runs 1 \
     --nocache-configs ApplicationComponent

   # If successful, run 5x for consistency measurement
   uv run python -m deriva.cli.cli benchmark run \
     --repos flask_invoice_generator \
     --models azure-gpt4mini \
     --runs 5 \
     --nocache-configs ApplicationComponent
   ```

6. **Evaluate Improvement**
   ```bash
   uv run python -m deriva.cli.cli benchmark analyze <new_session_id>
   ```

7. **Iterate or Move On**
   - If consistency >= 80%: Move to next problematic config
   - If consistency < 80%: Try a different prompt approach

## Case Study: Improving Derivation Consistency

### Problem

Initial benchmark with 5 runs showed **28% consistency** with 18 unstable elements:

```
unstable_elements:
  bus_obj_positions: 3/5 runs      # plural vs singular
  bus_obj_invoicedetails: 4/5      # camelCase vs snake_case
  bus_obj_customer: 4/5            # vs "client" synonym
  app_comp_static: 2/5             # inconsistent naming
  app_comp_flask_invoice_generator_static: 3/5  # repo prefix included
```

### Root Cause Analysis

The original prompts were too vague:

- **BusinessObject**: "Derive BusinessObject elements from business concepts"
- **ApplicationComponent**: "Use directory name as component name, include repo for context"
- **TechnologyService**: "Group related dependencies into logical services"

### Solution: Explicit Naming Rules

Updated prompts with strict naming conventions:

**BusinessObject** (improved):
```
NAMING RULES (CRITICAL FOR CONSISTENCY):
1. Use SINGULAR form always (Invoice not Invoices)
2. Use lowercase snake_case for identifier (bus_obj_invoice)
3. Use Title Case for display name (Invoice)

MANDATORY SYNONYM RULES - ALWAYS use these canonical names:
- Customer (NEVER: Client, User, Buyer, Account)
- Order (NEVER: Purchase, Transaction, Sale)
- Position (NEVER: Line Item, Order Line, Item)

Output stable, deterministic results.
```

**ApplicationComponent** (improved):
```
NAMING RULES (CRITICAL FOR CONSISTENCY):
1. Use ONLY the directory name, NEVER include repository name prefix
   - Correct: app_comp_static
   - Wrong: app_comp_flask_invoice_generator_static
2. Use lowercase snake_case for identifier

Output stable, deterministic results.
```

### Results

After optimization: **78.6% consistency** with only 3 unstable elements:

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Consistency | 28% | 78.6% | +50.6% |
| Unstable elements | 18 | 3 | -83% |
| Count variance | 1.84 | 0.24 | -87% |

### Key Takeaways

1. **Explicit naming rules are critical** - LLMs will vary naming unless constrained
2. **Ban synonyms explicitly** - "Customer not Client" is more effective than "use consistent names"
3. **Provide exact format examples** - Show the exact identifier format you expect
4. **Add determinism instruction** - "Output stable, deterministic results" helps

## CLI Reference

### Benchmark Commands

```bash
# Run benchmark matrix
deriva benchmark run --repos <repos> --models <models> [options]
  --repos         Comma-separated repository names (required)
  --models        Comma-separated model config names (required)
  -n, --runs      Runs per combination (default: 3)
  --stages        Stages to run: extraction,derivation
  --no-cache      Disable all LLM caching
  --nocache-configs  Configs to skip cache for (comma-separated)
  -v, --verbose   Show detailed progress

# List benchmark sessions
deriva benchmark list

# Analyze consistency across runs
deriva benchmark analyze <session_id>

# Analyze config deviations
deriva benchmark deviations <session_id>
  -o, --output    Output file path
  -s, --sort-by   Sort by: deviation_count, consistency_score, total_objects

# List available models
deriva benchmark models
```

### Config Commands

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

## Cost Optimization Tips

1. **Use `--nocache-configs` liberally** - Only pay for configs you're testing
2. **Start with 1 run** - Verify no errors before 3x consistency runs
3. **Test on small repos first** - `flask_invoice_generator` is ideal
4. **Cache warms up** - First benchmark is expensive, subsequent are cheap
5. **Batch model comparisons** - Test multiple models in one benchmark if comparing

## Output Files

Benchmark results are stored in `workspace/benchmarks/<session_id>/`:

| File | Description |
|------|-------------|
| `summary.json` | Session configuration and stats |
| `events.ocel.json` | OCEL 2.0 event log for process mining |
| `events.jsonl` | Streaming event format |
| `analysis/summary.json` | Consistency analysis results |
| `config_deviations.json` | Per-config deviation report |

## Best Practices

1. **Always benchmark before and after changes** - Quantify improvement
2. **Fix high-deviation configs first** - Biggest impact on quality
3. **Document what worked** - Note successful prompt patterns
4. **Version control your prompts** - Deriva tracks versions, but backup important ones
5. **Test across repos** - A fix for one repo may break another
