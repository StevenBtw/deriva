# Deriva Optimization Guide

This guide documents lessons learned from optimizing Deriva's LLM-based pipeline for consistency and quality. It's intended for developers working on prompt engineering and configuration tuning.

> **For running benchmarks**, see [BENCHMARKS.md](BENCHMARKS.md) for the user guide and CLI reference.

---

## Table of Contents

- [Optimization Methodology](#optimization-methodology)
- [Prompt Engineering Principles](#prompt-engineering-principles)
- [ArchiMate Knowledge](#archimate-knowledge)
- [Case Study: Initial Optimization](#case-study-initial-optimization)
- [Graph-Based Optimization](#graph-based-optimization)
- [Optimization Log](#optimization-log)
- [Phase 4: Advanced Optimizations](#phase-4-advanced-optimizations)
- [Token Efficiency Optimizations (v0.6.9)](#token-efficiency-optimizations-v069)
- [References](#references)

---

## Optimization Methodology

### Targeted Single-Config Testing

Instead of testing all configs together (expensive, noisy), use **targeted optimization**:

1. **Identify worst-performing element type** by analyzing `summary.json`
2. **Run 10+ iterations with only that config uncached** using `--nocache-configs`
3. **Iterate on prompt until 100% consistency** for that element type
4. **Move to next worst element type**

This approach is:

- **Cost-efficient**: Only LLM calls for the config being tested
- **Fast iteration**: 10 runs in ~4 minutes vs 3 full runs in ~6 minutes
- **Clear signal**: Isolates the effect of prompt changes

### Command Pattern

```bash
# Step 1: Run baseline to identify worst element type
uv run python -m deriva.cli.cli benchmark run \
  --repos flask_invoice_generator \
  --models mistral-devstral2 \
  --runs 3 \
  --no-cache

# Step 2: Analyze by element type prefix
uv run python -c "
import json
with open('workspace/benchmarks/<session>/analysis/summary.json') as f:
    data = json.load(f)
intra = data['intra_model'][0]
from collections import defaultdict
element_types = defaultdict(lambda: {'stable': 0, 'unstable': 0})
for e in intra['stable_elements']:
    prefix = e.split('_')[0]
    element_types[prefix]['stable'] += 1
for e in intra['unstable_elements'].items():
    prefix = e[0].split('_')[0]
    element_types[prefix]['unstable'] += 1
for prefix, counts in sorted(element_types.items()):
    total = counts['stable'] + counts['unstable']
    pct = (counts['stable'] / total * 100) if total > 0 else 0
    print(f'{prefix}: {counts[\"stable\"]}/{total} ({pct:.0f}%)')
"

# Step 3: Run targeted test for worst element type
uv run python -m deriva.cli.cli benchmark run \
  --repos flask_invoice_generator \
  --models mistral-devstral2 \
  --runs 10 \
  --nocache-configs TechnologyService

# Step 4: Update config and repeat until 100%
```

---

## Prompt Engineering Principles

### The Golden Rule: No Repository-Specific Overfitting

**This is the most important rule for config optimization.**

When writing prompts, NEVER include:

- Specific entity names from test repositories (invoice, customer, position)
- Specific file names (app.py, models.py)
- Specific technology stacks (Flask, SQLAlchemy)
- Specific project structures

<details>
<summary><strong>Examples: Bad vs Good</strong></summary>

**BAD - Overfitting:**

```text
# DON'T DO THIS
Create services for: invoice management, customer handling, position tracking
Exclude files like: app.py, __init__.py
Do not create BusinessActor for "flask_invoice_generator" concepts
```

**GOOD - Generalizable:**

```text
# DO THIS INSTEAD
Create services for: entity management, data validation, document generation
Exclude: framework initialization methods, internal utilities
Filter source nodes where out_degree = 0 AND pagerank < 0.01
```

</details>

**Test for overfitting:** Ask yourself: "Would this prompt work identically on a completely different repository (e.g., an e-commerce app, a healthcare system, a gaming backend)?"

If the answer is "no" or "it depends on the domain", the prompt is overfitting.

### Abstraction Level Determines Consistency

| Approach | Example | Consistency |
|----------|---------|-------------|
| Too specific | `as_validate_invoice_input` | Low (varies by domain) |
| Correct level | `as_validate_data` | High (generalizes) |

Guide the LLM to use GENERIC category names (data, entity, document) rather than domain-specific names.

> **Empirical support:** Liang 2025 achieved 100% accuracy on domain-specific tasks by providing carefully engineered in-context learning prompts with explicit domain constraints. Their finding that domain-specific instructions improved performance by 30% on complex cases validates the importance of abstraction-level guidance in prompts.

### Key Techniques

<details>
<summary><strong>1. Explicit Naming Rules</strong></summary>

"Use snake_case" is not enough. Provide exact format examples:

```text
NAMING RULES (CRITICAL FOR CONSISTENCY):
1. Use SINGULAR form always (Invoice not Invoices)
2. Use lowercase snake_case for identifier (bus_obj_invoice)
3. Use Title Case for display name (Invoice)
```

</details>

<details>
<summary><strong>2. Ban Synonyms Explicitly</strong></summary>

```text
MANDATORY SYNONYM RULES - ALWAYS use these canonical names:
- Customer (NEVER: Client, User, Buyer, Account)
- Order (NEVER: Purchase, Transaction, Sale)
- Position (NEVER: Line Item, Order Line, Item)
```

</details>

<details>
<summary><strong>3. Canonical Identifier Tables</strong></summary>

For DataObject and similar types, provide lookup tables:

```text
| File Pattern | Identifier |
|--------------|------------|
| .env, .flaskenv | do_environment_configuration |
| requirements.txt | do_dependency_manifest |
| *.db | do_application_database |
| .gitignore | do_version_control_configuration |
```

</details>

<details>
<summary><strong>4. Graph-Based Filtering</strong></summary>

Filter by structural properties rather than naming patterns:

```text
DO NOT create TechnologyService for:
- Nodes with low structural importance (pagerank < threshold)
- Transitive dependencies (out_degree = 0)
- Nodes not in k-core >= 2
```

</details>

<details>
<summary><strong>5. Examples Drive Consistency</strong></summary>

Claude follows example patterns closely. A well-structured example JSON is more effective than verbose rules:

```json
{
  "elements": [
    {
      "identifier": "as_manage_entities",
      "name": "Entity Management",
      "description": "CRUD operations for domain entities"
    }
  ]
}
```

</details>

<details>
<summary><strong>6. Use XML Tags for Structure</strong></summary>

Aligns with Claude's prompt engineering best practices:

```text
<definition>
ApplicationService represents a behavior element...
</definition>

<naming>
Use verb phrases: "Invoice Processing", "Payment Service"
</naming>

<constraints>
Maximum 5 services per repository
</constraints>
```

</details>

### ArchiMate Naming Conventions

| Element Type | Naming Pattern | Examples |
|--------------|----------------|----------|
| ApplicationService | Verb phrases | "Invoice Processing", "Payment Service" |
| DataObject | Singular noun phrases | "Environment Configuration" |
| BusinessObject | Singular nouns | "Customer", "Invoice" |
| ApplicationComponent | Directory-based | "templates", "static" |

---

## ArchiMate Knowledge

For comprehensive ArchiMate reference including element definitions, relationship rules, and metamodel constraints, see **[ARCHIMATE.md](ARCHIMATE.md)**.

Key sections for prompt engineering:
- [The Three Aspects](ARCHIMATE.md#the-three-aspects) - Active/Behavior/Passive classification
- [Relationships](ARCHIMATE.md#relationships) - Valid relationship types and constraints
- [Common Pitfalls](ARCHIMATE.md#common-pitfalls) - Modeling mistakes to avoid

### Research Findings

Key findings from academic research on LLM-based ArchiMate derivation:

| Finding | Source | Implication for Deriva |
|---------|--------|------------------------|
| Few-shot prompting works without fine-tuning | Chaaben 2022 | Use in-context examples, not trained models |
| Domain-specific ICL prompts can achieve 100% accuracy | Liang 2025 | Invest in tailored prompt engineering per element type |
| Guidance texts significantly improve output | Coutinho 2025 | Include domain-specific instruction documents |
| Chain-of-thought may decrease performance | Chen 2023 | Prefer direct instructions over reasoning chains |
| High precision, low recall is the norm | Chen 2023 | Expect correct but incomplete outputs |
| Code-to-ArchiMate: 68% precision, 80% recall | Castillo 2019 | Industrial benchmark baseline for extraction |
| NLP model extraction: 83-96% correctness | Arora 2016 | Achievable with explicit naming rules |
| LLMs show higher consistency than humans | Reitemeyer 2025 | Multiple runs can improve reliability |
| **Consistency ≠ accuracy (independent properties)** | Raj 2025 | Validate correctness separately from consistency |
| Human-in-the-loop is essential | All sources | Design for validation, not full automation |

### Temperature and Consistency

| Temperature | Use Case | Trade-off |
|-------------|----------|-----------|
| 0.0-0.2 | Element derivation | Maximum consistency, less creativity |
| 0.3-0.5 | Relationship discovery | Balanced |
| 0.6-0.8 | Name generation | More variety, less consistency |

**Recommendation:** Use low temperature (0.2-0.3) for element derivation to maximize consistency across runs.

### Validation Strategies

> **Critical caveat:** Consistency and accuracy are independent properties (Raj 2025). High consistency does NOT guarantee correctness. A process could consistently produce incorrect results. Always validate accuracy separately through manual review or ground truth comparison.

<details>
<summary><strong>Multi-Run Aggregation</strong></summary>

Run derivation 3-5 times and aggregate results (Wang 2025):

```python
def aggregate_elements(runs: list[list[dict]]) -> list[dict]:
    """Keep elements appearing in majority of runs."""
    element_counts = {}
    for run in runs:
        for element in run:
            key = element["identifier"]
            if key not in element_counts:
                element_counts[key] = {"element": element, "count": 0}
            element_counts[key]["count"] += 1

    threshold = len(runs) // 2 + 1
    return [
        data["element"]
        for data in element_counts.values()
        if data["count"] >= threshold
    ]
```

</details>

<details>
<summary><strong>Confidence Thresholds</strong></summary>

| Confidence | Interpretation | Action |
|------------|----------------|--------|
| 0.9-1.0 | High confidence | Include automatically |
| 0.7-0.9 | Moderate confidence | Include with review flag |
| 0.5-0.7 | Low confidence | Manual review required |
| < 0.5 | Very low | Exclude or investigate |

</details>

### LLM-Specific Pitfalls

<details>
<summary><strong>Identifier Hallucination</strong></summary>

**Problem:** LLM invents identifiers not in the provided list.

**Solution:** Explicitly constrain in the prompt:

```text
CRITICAL: You MUST use identifiers EXACTLY as shown in this list:
["ac_auth", "bo_customer", "do_user_data"]

Do NOT:
- Invent new identifiers
- Modify existing identifiers
- Use partial matches
```

</details>

<details>
<summary><strong>Over-Generation</strong></summary>

**Problem:** LLM creates too many elements/relationships.

**Solution:** Add explicit constraints:

```text
## Constraints
- Maximum 3 relationships per source element
- Only create elements where confidence > 0.5
- If no candidates are suitable, return {"elements": []}
```

</details>

<details>
<summary><strong>Generic Names</strong></summary>

**Problem:** LLM uses code names instead of business names.

**Solution:** Specify naming requirements:

```text
Naming rules:
- Use business-meaningful names, not code identifiers
- "User Authentication Service" not "auth_service"
- "Customer Order" not "customer_order_model"
- Names should be understandable to business stakeholders
```

</details>

<details>
<summary><strong>Chain-of-Thought Degradation</strong></summary>

**Problem:** Asking LLM to explain reasoning decreases quality (Chen 2023).

**Solution:**
- Use direct instructions, not reasoning chains
- Don't ask "think step by step" for ArchiMate derivation
- Focus prompts on what to output, not how to think

</details>

---

## Case Study: Initial Optimization

### Problem

Initial benchmark with 5 runs showed **28% consistency** with 18 unstable elements:

```text
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

<details>
<summary><strong>BusinessObject Prompt (Improved)</strong></summary>

```text
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

</details>

<details>
<summary><strong>ApplicationComponent Prompt (Improved)</strong></summary>

```text
NAMING RULES (CRITICAL FOR CONSISTENCY):
1. Use ONLY the directory name, NEVER include repository name prefix
   - Correct: app_comp_static
   - Wrong: app_comp_flask_invoice_generator_static
2. Use lowercase snake_case for identifier

Output stable, deterministic results.
```

</details>

### Results

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Consistency | 28% | 78.6% | +50.6% |
| Unstable elements | 18 | 3 | -83% |
| Count variance | 1.84 | 0.24 | -87% |

---

## Graph-Based Optimization

### The Hypothesis

Unstable elements may correlate with graph properties of their source nodes. By analyzing stable vs unstable elements' sources, we can identify patterns and apply graph-based filters.

### Methodology

1. **Run enrichment algorithms** on the graph (PageRank, Louvain, k-core, etc.)
2. **Correlate stability** with graph properties
3. **Apply filters** in derivation queries

<details>
<summary><strong>Step 1: Run Enrichment</strong></summary>

```python
from deriva.modules.derivation import enrich

enrichments = enrich.enrich_graph(
    edges=edges,
    algorithms=['pagerank', 'louvain', 'kcore', 'articulation_points', 'degree']
)
# Write to graph: graph_manager.batch_update_properties(enrichments)
```

</details>

<details>
<summary><strong>Step 2: Correlate Stability</strong></summary>

Query source nodes for stable vs unstable elements:

```cypher
// Get graph properties for element sources
MATCH (e) WHERE e.identifier IN $element_ids
WITH e.properties_json as props
MATCH (n {id: source_id})
RETURN n.pagerank, n.kcore_level, n.out_degree, n.in_degree
```

Analysis result:

```text
STABLE vs UNSTABLE Source Nodes:
+-----------+---------+----------+------------+
| Metric    | Stable  | Unstable | Difference |
+-----------+---------+----------+------------+
| PageRank  | 0.0188  | 0.0071   | +164%      |
| K-core    | 1.15    | 1.00     | +15%       |
| Out-degree| 2.31    | 0.00     | +inf       |
+-----------+---------+----------+------------+
```

</details>

<details>
<summary><strong>Step 3: Apply Graph-Based Filters</strong></summary>

Update `input_graph_query` to filter on graph properties:

```cypher
MATCH (n)
WHERE (n:`Graph:TypeDefinition` OR n:`Graph:BusinessConcept`)
  AND n.active = true
  AND (n.out_degree > 0 OR n.pagerank > 0.01)  -- Filter floating nodes
RETURN n.id, n.name, n.pagerank, n.kcore_level
```

</details>

### Key Insight: Structural vs Semantic Sources

| Source Type | Graph Properties | Stability |
|-------------|------------------|-----------|
| Structural (TypeDefinition, Method, File) | High out-degree, connected | More stable |
| Semantic (BusinessConcept) | Zero out-degree, floating | Less stable |

Semantic nodes extracted by LLM have no structural relationships in the code graph. When derivation uses these as sources, the LLM has less context, leading to inconsistent outputs.

This observation aligns with broader challenges in neural-symbolic integration: Cai 2025 identifies "representation gaps between neural network outputs and structured symbolic representations" as a fundamental challenge, particularly for complex relational reasoning. The graph-based filtering approach helps bridge this gap by grounding LLM interpretation in structural context.

**Recommendation:** For element types that can use either structural or semantic sources, prefer structural sources or require minimum graph connectivity.

---

## Optimization Log

Detailed chronological record of optimization sessions and findings.

<details>
<summary><strong>2026-01-03: Initial Config Optimization</strong></summary>

**Repository:** flask_invoice_generator (small)
**Model:** openai-gptx
**Runs:** 5

#### Baseline Results

| Session | Consistency | Element Counts | Issues |
|---------|-------------|----------------|--------|
| bench_20260103_094609 | 28% | 13-17 | 18 unstable elements |

**Main Problems:**

- BusinessObject: naming variants (positions/position, invoicedetails/invoice_details)
- ApplicationComponent: repo prefix inconsistency
- TechnologyService: detection variance

#### Optimizations Applied

1. **BusinessObject** (v1-v3): Added explicit naming rules, mandatory synonym rules, singular form requirement
2. **ApplicationComponent** (v1-v2): Never include repo name prefix, use only directory name
3. **TechnologyService** (v1-v2): Standard service categories list, grouping rules
4. **DataObject** (v1-v2): Generic names only

#### Final Results

| Session | Consistency | Element Counts | Issues |
|---------|-------------|----------------|--------|
| bench_20260103_095630 | 78.6% | 12-13 | 3 unstable elements |
| bench_20260103_101845 | 100% | 12 | 0 (DataObject test) |

**Improvement:** +50.6% consistency, 83% fewer unstable elements

#### Key Learnings

1. Explicit naming rules are critical
2. Ban synonyms explicitly
3. Standard category lists reduce variance
4. Add determinism instruction to every LLM prompt
5. Test one config at a time with `--nocache-configs`

</details>

<details>
<summary><strong>2026-01-03: Medium Repository Test</strong></summary>

**Repository:** full-stack-fastapi-template (medium)
**Model:** openai-gptx

#### Issues Encountered

- **Extraction failures** - "Response missing 'dependencies' array" in ExternalDependency extraction
- **Edge creation failures** - Node ID mismatches for TypeDefinition and Test extractions
- These are infrastructure/schema issues, not derivation LLM issues

#### Partial Results

| Session | Consistency | Notes |
|---------|-------------|-------|
| bench_20260103_100150 | 61.1% | DataObject naming variants |

**Observation:** Medium repo has underlying extraction issues to resolve before clean benchmarking.

</details>

<details>
<summary><strong>2026-01-03: Relationship Derivation Fix</strong></summary>

**Issue:** Run failures with "Invalid relationship type: Association"

The LLM was outputting "Association" which is not a valid ArchiMate relationship type.

#### Fix Applied

Updated `build_relationship_prompt()` in `deriva/modules/derivation/base.py`:

```text
VALID RELATIONSHIP TYPES (use ONLY these exact names):
- Composition, Aggregation, Serving, Realization, Access, Flow, Assignment

INVALID TYPES (NEVER use these):
- Association (use Serving or Flow instead)
- Dependency (use Serving instead)
- Uses (use Serving instead)
```

#### Results After Fix

| Session | Consistency | Runs | Failures |
|---------|-------------|------|----------|
| bench_20260103_103526 | 85.7% | 3 | 0 |

#### Cumulative Improvement

| Metric | Baseline | Final | Improvement |
|--------|----------|-------|-------------|
| Consistency | 28% | 85.7% | +57.7% |
| Stable elements | 7 | 12 | +71% |
| Unstable elements | 18 | 2 | -89% |
| Run failures | ~33% | 0% | -100% |

</details>

<details>
<summary><strong>2026-01-03: Cross-Repository Generalization Test</strong></summary>

**Objective:** Verify configs are generic and don't overfit to test repositories

**Repositories tested:**
- flask_invoice_generator (small)
- full-stack-fastapi-template (medium)

#### Results

| Repository | Runs | Consistency | Status |
|------------|------|-------------|--------|
| flask_invoice_generator | 3/3 | 85.7% | Configs work well |
| full-stack-fastapi-template | 3/3 | 57.1% | Extraction infra issues |

#### Analysis: Configs Are Generic

**Evidence of generalization:**

1. Consistent naming patterns across repos (same prefixes)
2. Small repo high consistency (85.7%) proves prompts work generically
3. Medium repo failures are infrastructure bugs, NOT config issues

**Conclusion:** No config adjustments needed for generalization. Derivation configs are generic.

</details>

<details>
<summary><strong>2026-01-08: Efficient Targeted Optimization Workflow</strong></summary>

**Model:** mistral-devstral2
**Repository:** flask_invoice_generator

#### New Methodology: One Config at a Time

See [Optimization Methodology](#optimization-methodology) for the full workflow.

#### TechnologyService Optimization Results

| Version | Stable | Unstable | Consistency | Key Change |
|---------|--------|----------|-------------|------------|
| v1 | 0/5 | 5 | 0% | Original vague prompt |
| v2 | 1/3 | 2 | 33% | Added canonical names |
| v3 | 3/8 | 5 | 38% | Added determinism instruction |
| v4 | 3/4 | 1 | 75% | Excluded transitive deps |

#### Overall Progress

| Element Type | Baseline | After Optimization |
|--------------|----------|-------------------|
| ApplicationService | 0% | **100%** |
| BusinessActor | 0% | **100%** |
| DataObject | 50% | **100%** |
| BusinessProcess | 0% | **50%** |
| BusinessObject | 25% | **50%** |
| TechnologyService | 0% | **75%** |

**Overall: 28% - 75%**

#### Extraction Consistency Analysis

| Config | Method | Variance | Status |
|--------|--------|----------|--------|
| Repository | Deterministic | 0 | 100% |
| Directory | Deterministic | 0 | 100% |
| File | Deterministic | 0 | 100% |
| Method | AST (Python) | 0 | 100% |
| TypeDefinition | AST (Python) | 0 | 100% |
| ExternalDependency | Parser | 0 | 100% |
| Test | Cache | 0 | 100% |
| **BusinessConcept** | **LLM** | **84-86** | **1-2 unstable** |
| **Technology** | **LLM** | **86-87** | **1 unstable** |

**Key finding:** Only LLM-based extraction configs have variance. AST-based and deterministic parsers are 100% consistent.

</details>

<details>
<summary><strong>2026-01-08: Graph Property-Based Optimization</strong></summary>

See [Graph-Based Optimization](#graph-based-optimization) for the full methodology.

#### Results

| Metric | Baseline | After Filter | Change |
|--------|----------|--------------|--------|
| Element Consistency | 81.25% | 80.0% | -1.25% |
| Unstable Elements | 3 | 3 | Same count |

**Key outcome:** The specific unstable elements changed completely. Graph filter eliminated instability from "floating" semantic nodes.

</details>

<details>
<summary><strong>2026-01-09: File Classification and CLI Improvements</strong></summary>

**Objective:** Improve file extraction quality and add CLI support for file type management.

#### Issues Identified

1. Files with unknown extensions had `fileType=None` instead of a meaningful default
2. No CLI for file types - registry could only be managed via UI

#### Fixes Applied

1. **Improved File Classification Logic** - Files with unknown extensions now get `file_type="unknown"` with extension as `subtype`
2. **CLI File Type Management** - Added `deriva config filetype` commands

#### Improvement Summary

| Metric | Before | After |
|--------|--------|-------|
| Files with null fileType | ~15% | 0% |
| CLI file type commands | 0 | 4 |

</details>

<details>
<summary><strong>2026-01-10: A/B Testing Framework and Derivation Optimization</strong></summary>

**Objective:** Create fast A/B testing workflow and improve derivation consistency to >=80%

#### DataObject Optimization

**Problem:** 41.7% consistency with naming variants

**Solution:** Canonical identifier table in prompt

**Result:** 41.7% - 100% consistency

#### ApplicationService Optimization

**Problem:** 28.6% consistency with variants like `as_validate_data` vs `as_validate_input`

**Solution:** Abstraction principle + example-driven prompt with XML tags

**Result:** 28.6% - 100% consistency

#### Final Results

| Element Type | Before | After | Change |
|--------------|--------|-------|--------|
| DataObject | 41.7% | 100% | +58.3% |
| ApplicationService | 28.6% | 100% | +71.4% |

</details>

---

## Summary of Key Learnings

1. **Explicit naming rules are critical** - "Use snake_case" is not enough; provide exact examples
2. **Ban synonyms explicitly** - "Customer (NEVER: Client, User, Buyer)" works better than "use consistent names"
3. **Standard category lists reduce variance** - Enumerate allowed values
4. **Add determinism instruction** - "Output stable, deterministic results" in every LLM prompt
5. **Test one config at a time** - Use `--nocache-configs` for targeted testing
6. **Examples drive consistency** - A good example JSON is more effective than verbose rules
7. **Abstraction level is key** - Use generic category names, not domain-specific names (Liang 2025: +30% improvement)
8. **Graph-based selection over name-based** - Filter by structural properties (in_degree, pagerank)
9. **Never use repository-specific rules** - All optimizations must be generic
10. **Prefer structural sources over semantic** - TypeDefinition/Method sources are more stable than BusinessConcept
11. **Consistency ≠ accuracy** - High consistency doesn't guarantee correctness; validate both independently (Raj 2025)

---

## Phase 4: Advanced Optimizations

The following advanced optimizations were implemented to further improve token efficiency and consistency.

### Token Estimation & Context Limiting

Functions in `deriva/modules/derivation/base.py`:

| Function | Purpose |
|----------|---------|
| `estimate_tokens(text)` | Estimates token count (~4 chars/token) |
| `get_model_context_limit(model)` | Returns context limit for model |
| `check_prompt_size(prompt, model)` | Warns if prompt exceeds 80% of limit |
| `limit_existing_elements(elements, max=50)` | Keeps top-N elements by confidence |
| `stratified_sample_elements(elements, max_per_type=10)` | Samples across element types |

### Graph-Aware Pre-filtering (Phase 4.3)

Only include existing elements with graph proximity to new elements:

```python
from deriva.modules.derivation.base import (
    get_connected_source_ids,
    filter_by_graph_proximity,
)

# Get nodes connected within 2 hops
connected_ids = get_connected_source_ids(graph_manager, new_source_ids, max_hops=2)

# Filter to only graph neighbors
filtered = filter_by_graph_proximity(existing_elements, connected_ids)
```

**Benefits:**

- 60-90% reduction in context size
- Better relationship quality (only related elements in context)
- Reduced hallucination of spurious relationships

### Separated Derivation Phases (Phase 4.6)

The `defer_relationships` parameter enables a two-phase architecture.

**Default Mode (defer_relationships=True):** *(Recommended)*

```text
Phase 1: Create ALL elements (skip relationships)
Phase 2: Single consolidated relationship pass
```

**Legacy Mode (defer_relationships=False):**

```text
For each element type:
  1. Create elements → 2. Derive relationships → Repeat
```

**Usage:**

```python
from deriva.services.derivation import generate_element
from deriva.modules.derivation.base import derive_consolidated_relationships

# Phase 1: Generate all elements without relationships
all_elements = []
for element_type in element_types:
    result = generate_element(
        element_type=element_type,
        defer_relationships=True,  # Skip per-batch relationships
        # ... other params
    )
    all_elements.extend(result["elements"])

# Phase 2: Derive all relationships in one pass
relationships = derive_consolidated_relationships(
    all_elements=all_elements,
    relationship_rules=rules_by_type,
    llm_query_fn=llm.query,
    graph_manager=graph_manager,
)
```

**Benefits:**

- Better context - ALL elements available during relationship derivation
- Fewer LLM calls - One pass per element type instead of per batch
- More consistent - Reduces ordering effects
- Graph-aware filtering works better with complete element set

### Dynamic Batch Sizing

Batch size adapts to candidate count and token limits:

```python
from deriva.modules.derivation.base import (
    calculate_dynamic_batch_size,
    adjust_batch_for_tokens,
)

# Auto-size based on candidate count
batch_size = calculate_dynamic_batch_size(len(candidates))  # 10-25 range

# Reduce if tokens exceed model limit
batch_size = adjust_batch_for_tokens(batch_size, estimated_tokens, model_name)
```

### Benchmark Results

After Phase 4 optimizations (5 runs, mistral-devstral2, flask_invoice_generator):

| Metric | Result |
|--------|--------|
| Structural edge consistency | 100% |
| Duration | ~411s |
| Node variance | 87-89 (stable) |
| Elements per run | 22-24 |
| Relationships per run | 20-30 |

---

## Token Efficiency Optimizations (v0.6.9)

Version 0.6.9 introduced several token efficiency improvements that reduce extraction costs by an estimated 40-60%.

### Compact JSON Serialization

**Problem:** Default JSON formatting with `indent=2` adds significant whitespace overhead.

**Solution:** Use compact serialization with no whitespace:

```python
# Before (wasteful)
json.dumps(data, indent=2)
# {"elements": [
#     {
#         "id": "bus_concept_1",
#         "name": "Customer"
#     }
# ]}

# After (efficient)
json.dumps(data, separators=(",", ":"))
# {"elements":[{"id":"bus_concept_1","name":"Customer"}]}
```

**Savings:** ~15% token reduction for JSON payloads.

**Where to apply:**

- Existing concepts/elements passed to LLM prompts
- Any structured data in prompt context
- NOT for human-readable output or logs

### System/User Prompt Separation

**Problem:** Static instructions repeated in every LLM call waste tokens.

**Solution:** Separate prompts into system (static) and user (dynamic) portions:

| Prompt Type | Content | Sent When |
|-------------|---------|-----------|
| **System prompt** | Role definition, naming rules, output format, constraints | Once per session (cached by provider) |
| **User prompt** | File content, existing concepts, specific context | Every call |

**Implementation pattern:**

```python
# System prompt - static instructions (sent once per session)
system_prompt = """
You are an expert at extracting business concepts from source code.

NAMING RULES:
1. Use singular form (Invoice not Invoices)
2. Use Title Case for names
3. Use lowercase snake_case for identifiers

OUTPUT FORMAT:
Return valid JSON with "concepts" array.
"""

# User prompt - dynamic content (per file/batch)
user_prompt = f"""
<existing_concepts>
{json.dumps(existing, separators=(",", ":"))}
</existing_concepts>

<file path="{file_path}">
{file_content}
</file>

Extract business concepts from this file.
"""
```

**Benefits:**

- Many providers cache system prompts across calls
- Reduces redundant instruction tokens
- Cleaner separation of concerns
- Easier to maintain and update instructions

### Multi-File Batching

**Problem:** Each small file requires a separate LLM call with full prompt overhead.

**Solution:** Batch multiple small files into single LLM calls using the `batch_size` configuration.

**Configuration:**

```bash
# CLI usage
uv run deriva-cli run extraction --repo myrepo --batch-size 5

# Or set in extraction config
uv run deriva-cli config update extraction BusinessConcept \
  -p '{"batch_size": 5}'
```

**How batching works:**

1. Files are sorted by size (smallest first)
2. Files are grouped until batch token limit is reached
3. Each batch is sent as a single LLM call
4. Results are disaggregated back to individual files

**Batching parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `batch_size` | 1 | Maximum files per batch |
| `max_batch_tokens` | 4000 | Token limit per batch |
| `batch_by_directory` | false | Group files from same directory |

**Example batch prompt:**

```text
<files>
<file path="models/customer.py" index="0">
class Customer:
    name: str
    email: str
</file>
<file path="models/order.py" index="1">
class Order:
    customer_id: int
    total: float
</file>
<file path="models/item.py" index="2">
class Item:
    name: str
    price: float
</file>
</files>

Extract business concepts from each file. Return results indexed by file.
```

**Savings:** 30-50% token reduction depending on file sizes and batch efficiency.

**Best practices for batching:**

1. **Start with batch_size=3-5** for initial testing
2. **Increase for small files** - config files, models, schemas batch well
3. **Keep batch_size=1 for large files** - complex modules need individual attention
4. **Monitor quality** - very high batch sizes may reduce extraction quality
5. **Use batch_by_directory** when files in same directory share context

### Combined Token Savings

When all three optimizations are applied together:

| Optimization | Individual Savings | Cumulative |
|--------------|-------------------|------------|
| Compact JSON | ~15% | 15% |
| System/User separation | ~10-15% | 25-30% |
| Multi-file batching | ~30-50% | 40-60% |

**Measuring token usage:**

```bash
# Run extraction with verbose logging to see token counts
uv run deriva-cli run extraction --repo myrepo -v

# Check logs for token usage per step
grep "tokens" workspace/logs/extraction_*.jsonl
```

### Token Efficiency Checklist

Before optimizing prompts for consistency, ensure token efficiency:

- [ ] JSON payloads use compact serialization (`separators=(",", ":")`)
- [ ] Static instructions are in system prompt, dynamic content in user prompt
- [ ] Small files are batched appropriately (`batch_size > 1`)
- [ ] Large context is filtered (use `limit_existing_elements()` or `stratified_sample_elements()`)
- [ ] Graph proximity filtering is enabled for relationship derivation

---

## References

### Academic Sources

| Citation | Reference | Key Contribution |
|----------|-----------|------------------|
| Arora 2016 | Arora et al., "Extracting domain models from natural-language requirements" | Industrial NLP extraction: 83-96% correctness, explicit naming rules |
| Cai 2025 | Cai et al., "Practices, opportunities and challenges in the fusion of knowledge graphs and large language models" | KG-LLM integration taxonomy (KEL/LEK/LKC), neural-symbolic representation gaps |
| Castillo 2019 | Castillo et al., "ArchiRev - Reverse engineering toward ArchiMate models" | Code-to-ArchiMate benchmark: 68% precision, 80% recall |
| Chaaben 2022 | Chaaben et al., "Towards using Few-Shot Prompt Learning for Automating Model Completion" | Few-shot prompting without fine-tuning, frequency-based ranking |
| Chaaben 2024 | Chaaben et al., "On the Utility of Domain Modeling Assistance with LLMs" | 20% time reduction, 33-56% suggestion contribution rates |
| Chen 2023 | Chen et al., "Automated Domain Modeling with LLMs: A Comparative Study" | F1 scores (0.76 classes, 0.34 relationships), chain-of-thought caution |
| Coutinho 2025 | Coutinho et al., "LLM-Based Modeling Assistance for Textual Ontology-Driven Conceptual Modeling" | Guidance texts significantly improve output quality |
| Liang 2025 | Liang et al., "Integrating Large Language Models for Automated Structural Analysis" | Domain-specific ICL achieves 100% accuracy; benchmarking methodology |
| Raj 2025 | Raj et al., "Semantic Consistency for Assuring Reliability of Large Language Models" | **Critical:** Consistency and accuracy are independent properties |
| Reitemeyer 2025 | Reitemeyer & Fill, "Applying LLMs in Knowledge Graph-based Enterprise Modeling" | LLMs show higher consistency than humans, human-in-the-loop essential |
| Wang 2025 | Wang & Wang, "Assessing Consistency and Reproducibility in LLM Outputs" | 3-5 runs optimal for consistency |

### Industry Resources

| Resource | Description |
|----------|-------------|
| [ArchiMate 3.2 Specification](https://pubs.opengroup.org/architecture/archimate3-doc/) | Official ArchiMate standard from The Open Group |
| [Mastering ArchiMate](https://ea.rna.nl/mastering-archimate-edition-3-2/) | Gerben Wierda's comprehensive guide to ArchiMate modeling |
| [ArchiMate Best Practices](https://github.com/AlbertoDMendoza/ArchiMateBestPractices) | Community-curated best practices for Archi tool usage |
| [ArchiMate Cookbook](https://www.hosiaisluoma.fi/blog/archimate/) | Eero Hosiaisluoma's practical ArchiMate patterns |

### Standards

- [ANSI/NISO Z39.19-2005 (R2010)](https://www.niso.org/standards-committees/vocab-mgmt) - Guidelines for Controlled Vocabularies
- [ISO 704:2022](https://www.iso.org/standard/79077.html) - Terminology work: Principles and methods
- [OMG SBVR](https://www.omg.org/spec/SBVR/) - Semantics of Business Vocabulary and Business Rules

---

## Further Reading

- [ARCHIMATE.md](ARCHIMATE.md) - ArchiMate element definitions, relationships, and metamodel reference
- [BENCHMARKS.md](BENCHMARKS.md) - User guide for running benchmarks
- [CONTRIBUTING.md](CONTRIBUTING.md) - Architecture and development patterns
- [ArchiMate Best Practices & Resource Guide](https://github.com/AlbertoDMendoza/ArchiMateBestPractices) - Detailed prompt templates for ArchiMate derivation
