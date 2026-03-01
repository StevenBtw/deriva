# Benchmark Implementation Plan

## Objective

Implement benchmark output structure per `.claude/BENCHMARK_OUTPUT.md` specification, then run a test benchmark to verify.

---

## Configuration Summary

| Setting | Value |
|---------|-------|
| **LLM Model** | `mistral-devstral2` (Mistral Devstral-2512) |
| **Repositories** | `deriva`, `bigdata` |
| **Runs per repo** | 1 |
| **Ground Truth** | `reference/reference_*.archimate` (filtered versions) |

---

## Current vs Desired Output Structure

### Current Structure (what Deriva produces now)

```
workspace/benchmarks/{session_id}/
├── summary.json                           # Session metadata
├── events.ocel.json                       # OCEL 2.0 event log at root
├── events.jsonl                           # JSONL streaming log at root
├── models/
│   ├── deriva_mistral-devstral2_1.xml    # Model naming: {repo}_{model}_{n}.xml
│   └── bigdata_mistral-devstral2_1.xml
├── cache/
│   └── mistral-devstral2/                 # Per-model subdirectory
│       ├── abc123def456.json              # Individual cache files by hash
│       └── ...
└── analysis/
    └── summary.json                       # Consistency analysis (JSON only)
```

### Desired Structure (per BENCHMARK_OUTPUT.md)

```
benchmark_session_<timestamp>/
├── session_metadata.json                  # Renamed from summary.json
├── models/
│   ├── deriva_devstral2_run1.xml         # Model naming: {repo}_{model}_run{n}.xml
│   └── bigdata_devstral2_run1.xml
├── cache/
│   └── llm_cache.json                     # Single consolidated cache file
├── ocel/
│   └── benchmark_events.json              # OCEL in subdirectory, renamed
└── results/
    ├── consistency_metrics.csv            # NEW: Per-run stability
    ├── ground_truth_comparison.csv        # NEW: Precision/recall/F1
    ├── quality_verification.csv           # NEW: Quality scores
    ├── inter_model_agreement.json         # Extracted from analysis
    └── execution_metrics.csv              # NEW: Timing/tokens
```

---

## Gap Analysis

| # | Item | Current | Desired | File to Modify | Lines | Effort |
|---|------|---------|---------|----------------|-------|--------|
| 1 | Model filename | `{repo}_{model}_{n}.xml` | `{repo}_{model}_run{n}.xml` | `benchmarking.py` | 1055 | Low |
| 2 | OCEL location | Root level | `ocel/` subdirectory | `benchmarking.py` | 1178-1184 | Low |
| 3 | OCEL filename | `events.ocel.json` | `benchmark_events.json` | `benchmarking.py` | 1179 | Low |
| 4 | Metadata file | `summary.json` | `session_metadata.json` | `benchmarking.py` | 1195 | Low |
| 5 | Cache structure | Per-model dirs | Single `llm_cache.json` | `benchmarking.py` | 1200-1234 | Medium |
| 6 | Results directory | `analysis/` | `results/` | `analysis.py` | 541-548 | Low |
| 7 | consistency_metrics.csv | Not exists | Required | `analysis.py` | New method | Medium |
| 8 | ground_truth_comparison.csv | Not exists | Required | `analysis.py` | New method | Medium |
| 9 | quality_verification.csv | Not exists | Required | `analysis.py` | New method | Medium |
| 10 | execution_metrics.csv | Not exists | Required | `analysis.py` | New method | Medium |

---

## Implementation Phases

### Phase 1: Directory Structure & Naming (P0 - Low Effort)

#### Task 1.1: Update Model File Naming

**File**: `h:\Deriva\deriva\deriva\services\benchmarking.py`
**Line**: 1055

```python
# CURRENT (line 1055):
filename = f"{safe_repo}_{safe_model}_{iteration}.xml"

# CHANGE TO:
filename = f"{safe_repo}_{safe_model}_run{iteration}.xml"
```

**Impact**: Model files will be named `bigdata_mistral-devstral2_run1.xml` instead of `bigdata_mistral-devstral2_1.xml`

---

#### Task 1.2: Move OCEL Files to `ocel/` Subdirectory

**File**: `h:\Deriva\deriva\deriva\services\benchmarking.py`
**Lines**: 1178-1184

```python
# CURRENT (lines 1178-1184):
# Export OCEL JSON
ocel_json_path = output_dir / "events.ocel.json"
self.ocel_log.export_json(ocel_json_path)

# Export JSONL for streaming
ocel_jsonl_path = output_dir / "events.jsonl"
self.ocel_log.export_jsonl(ocel_jsonl_path)

# CHANGE TO:
# Create ocel subdirectory
ocel_dir = output_dir / "ocel"
ocel_dir.mkdir(parents=True, exist_ok=True)

# Export OCEL JSON
ocel_json_path = ocel_dir / "benchmark_events.json"
self.ocel_log.export_json(ocel_json_path)

# Export JSONL for streaming
ocel_jsonl_path = ocel_dir / "benchmark_events.jsonl"
self.ocel_log.export_jsonl(ocel_jsonl_path)
```

**Impact**: OCEL files moved from root to `ocel/` subdirectory

---

#### Task 1.3: Rename summary.json to session_metadata.json

**File**: `h:\Deriva\deriva\deriva\services\benchmarking.py`
**Line**: 1195

```python
# CURRENT (line 1195):
with open(output_dir / "summary.json", "w") as f:

# CHANGE TO:
with open(output_dir / "session_metadata.json", "w") as f:
```

**Impact**: Session metadata file renamed

---

### Phase 2: Cache Consolidation (P1 - Medium Effort)

#### Task 2.1: Replace _copy_used_cache_entries() Method

**File**: `h:\Deriva\deriva\deriva\services\benchmarking.py`
**Lines**: 1200-1234

Replace the entire method with consolidation logic:

```python
def _copy_used_cache_entries(
    self,
    used_cache_keys: list[str],
    cache_dir: Path,
    model_name: str,
) -> int:
    """
    Consolidate used LLM cache entries into single llm_cache.json.

    Instead of copying individual hash-named files to per-model subdirectories,
    consolidates all entries into a single JSON file per BENCHMARK_OUTPUT.md spec.

    Args:
        used_cache_keys: List of cache keys (SHA256 hashes) used during the run
        cache_dir: Source cache directory where cache files are stored
        model_name: Name of the model (used for tagging entries)

    Returns:
        Number of cache entries in consolidated file
    """
    session_id = self.session_id or "unknown"
    cache_file = Path("workspace/benchmarks") / session_id / "cache" / "llm_cache.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    # Load existing consolidated cache or create new
    consolidated: dict[str, Any] = {}
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                consolidated = json.load(f)
        except json.JSONDecodeError:
            consolidated = {}

    # Add new entries from this run
    for cache_key in set(used_cache_keys):  # Deduplicate
        src = cache_dir / f"{cache_key}.json"
        if src.exists() and cache_key not in consolidated:
            try:
                with open(src) as f:
                    data = json.load(f)
                    # Extract fields per BENCHMARK_OUTPUT.md spec
                    consolidated[cache_key] = {
                        "prompt": data.get("request", {}).get("messages", [{}])[-1].get("content", ""),
                        "response": data.get("response", {}).get("content", ""),
                        "model": model_name,
                        "tokens_in": data.get("usage", {}).get("input_tokens", 0),
                        "tokens_out": data.get("usage", {}).get("output_tokens", 0),
                        "timestamp": data.get("created_at", ""),
                        "bench_hash": f"run{self._current_iteration}_{self._current_repo}_{model_name}",
                    }
            except (OSError, json.JSONDecodeError):
                pass  # Skip on read errors

    # Write consolidated cache
    with open(cache_file, "w") as f:
        json.dump(consolidated, f, indent=2)

    return len(consolidated)
```

**Note**: Need to track `_current_iteration` and `_current_repo` in the orchestrator class.

---

### Phase 3: CSV Export Implementation (P1 - Medium Effort)

#### Task 3.1: Add CSV Export Methods to BenchmarkAnalyzer

**File**: `h:\Deriva\deriva\deriva\services\analysis.py`
**Location**: After line 548 (after `export_all` method)

Add these 4 new methods:

```python
import csv
from pathlib import Path

def export_consistency_metrics_csv(self, path: Path) -> str:
    """
    Export consistency_metrics.csv with per-run element and relationship stability.

    Columns: repository, model, run, total_elements, stable_elements,
             element_stability, total_relationships, stable_relationships,
             relationship_stability
    """
    report = self.generate_report()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "repository", "model", "run",
            "total_elements", "stable_elements", "element_stability",
            "total_relationships", "stable_relationships", "relationship_stability"
        ])

        for repo, phases in report.stability_reports.items():
            derivation = phases.get("derivation")
            if derivation:
                # Aggregate element stats
                total_elem = sum(b.total for b in derivation.element_breakdown)
                stable_elem = sum(b.stable for b in derivation.element_breakdown)
                elem_stability = stable_elem / total_elem if total_elem > 0 else 0.0

                # Aggregate relationship stats
                total_rel = sum(b.total for b in derivation.relationship_breakdown)
                stable_rel = sum(b.stable for b in derivation.relationship_breakdown)
                rel_stability = stable_rel / total_rel if total_rel > 0 else 0.0

                writer.writerow([
                    repo, "all", "all",
                    total_elem, stable_elem, f"{elem_stability:.2%}",
                    total_rel, stable_rel, f"{rel_stability:.2%}"
                ])

    return str(path)


def export_ground_truth_comparison_csv(self, path: Path) -> str:
    """
    Export ground_truth_comparison.csv with precision/recall/F1 against reference models.

    Columns: repository, model, gt_elements, extracted_elements, matched,
             precision, recall, f1

    Uses reference models from reference/reference_{repo}.archimate
    """
    report = self.generate_report()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "repository", "model", "gt_elements", "extracted_elements",
            "matched", "precision", "recall", "f1"
        ])

        for repo, sem_report in report.semantic_reports.items():
            writer.writerow([
                repo, "all",
                sem_report.reference_element_count,
                sem_report.derived_element_count,
                len(sem_report.correctly_derived),
                f"{sem_report.precision:.3f}",
                f"{sem_report.recall:.3f}",
                f"{sem_report.f1_score:.3f}"
            ])

    return str(path)


def export_quality_verification_csv(self, path: Path) -> str:
    """
    Export quality_verification.csv with quality rubric scores.

    Columns: repository, model, validity_pct, type_correct_pct, name_quality_pct
    """
    report = self.generate_report()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "repository", "model", "validity_pct", "type_correct_pct", "name_quality_pct"
        ])

        for repo, sem_report in report.semantic_reports.items():
            # Validity: Elements traceable to source
            validity = sem_report.precision if sem_report else 0.0

            # Type correct: Elements with matching ArchiMate type
            type_correct = len([m for m in sem_report.correctly_derived
                               if m.match_type in ("exact", "fuzzy_name")]) / max(sem_report.derived_element_count, 1)

            # Name quality: Elements with meaningful names (fuzzy match quality)
            name_quality = sem_report.avg_similarity if hasattr(sem_report, 'avg_similarity') else 0.0

            writer.writerow([
                repo, "all",
                f"{validity:.1%}",
                f"{type_correct:.1%}",
                f"{name_quality:.1%}"
            ])

    return str(path)


def export_execution_metrics_csv(self, path: Path) -> str:
    """
    Export execution_metrics.csv with runtime performance data.

    Columns: repository, model, run, duration_sec, event_count,
             tokens_in, tokens_out, api_calls

    Extracts timing data from OCEL events.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Parse OCEL for timing data
    run_metrics: dict[str, dict] = {}

    for event in self.ocel_log.events:
        if event.activity == "StartRun":
            run_id = event.objects.get("BenchmarkRun", [""])[0]
            run_metrics[run_id] = {
                "start": event.timestamp,
                "repo": event.objects.get("Repository", [""])[0],
                "model": event.objects.get("Model", [""])[0],
                "events": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "api_calls": 0,
            }
        elif event.activity == "CompleteRun":
            run_id = event.objects.get("BenchmarkRun", [""])[0]
            if run_id in run_metrics:
                run_metrics[run_id]["end"] = event.timestamp
        elif event.activity == "LLMRequest":
            run_id = event.objects.get("BenchmarkRun", [""])[0]
            if run_id in run_metrics:
                run_metrics[run_id]["api_calls"] += 1
                run_metrics[run_id]["tokens_in"] += event.attributes.get("tokens_in", 0)
                run_metrics[run_id]["tokens_out"] += event.attributes.get("tokens_out", 0)

        # Count all events for this run
        for run_id in event.objects.get("BenchmarkRun", []):
            if run_id in run_metrics:
                run_metrics[run_id]["events"] += 1

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "repository", "model", "run", "duration_sec",
            "event_count", "tokens_in", "tokens_out", "api_calls"
        ])

        for run_id, metrics in run_metrics.items():
            # Parse run number from run_id (format: session:repo:model:n)
            parts = run_id.split(":")
            run_num = parts[-1] if len(parts) >= 4 else "1"

            # Calculate duration
            start = metrics.get("start")
            end = metrics.get("end", start)
            duration = (end - start).total_seconds() if start and end else 0.0

            writer.writerow([
                metrics["repo"], metrics["model"], run_num,
                f"{duration:.1f}",
                metrics["events"],
                metrics["tokens_in"],
                metrics["tokens_out"],
                metrics["api_calls"]
            ])

    return str(path)
```

---

#### Task 3.2: Update export_all() to Use results/ Directory

**File**: `h:\Deriva\deriva\deriva\services\analysis.py`
**Lines**: 531-548

```python
# CURRENT:
def export_all(self, output_dir: str | Path) -> dict[str, str]:
    """Export all formats to a directory."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths = {}
    paths["json"] = self.export_json(output_dir / "benchmark_analysis.json")
    paths["markdown"] = self.export_markdown(output_dir / "benchmark_analysis.md")

    return paths

# CHANGE TO:
def export_all(self, output_dir: str | Path) -> dict[str, str]:
    """Export all formats to results/ directory per BENCHMARK_OUTPUT.md spec."""
    output_dir = Path(output_dir)
    results_dir = output_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    paths = {}

    # JSON exports
    paths["inter_model_json"] = self.export_json(results_dir / "inter_model_agreement.json")
    paths["markdown"] = self.export_markdown(results_dir / "benchmark_analysis.md")

    # CSV exports (new)
    paths["consistency_csv"] = self.export_consistency_metrics_csv(
        results_dir / "consistency_metrics.csv"
    )
    paths["ground_truth_csv"] = self.export_ground_truth_comparison_csv(
        results_dir / "ground_truth_comparison.csv"
    )
    paths["quality_csv"] = self.export_quality_verification_csv(
        results_dir / "quality_verification.csv"
    )
    paths["execution_csv"] = self.export_execution_metrics_csv(
        results_dir / "execution_metrics.csv"
    )

    return paths
```

---

## Reference Model Configuration

The ground truth comparison will use:

| Repository | Reference Model Path |
|------------|---------------------|
| deriva | `reference/reference_deriva.archimate` (if exists) |
| bigdata | `reference/reference_bigdata.archimate` |

**Current reference files available:**
- `reference/reference_bigdata.archimate` (filtered)
- `reference/reference_lightblue.archimate` (filtered)
- `reference/reference_cloudbased.archimate` (filtered)
- `reference/full_reference_*.archimate` (full - NOT to be used)

**Note**: No `reference_deriva.archimate` exists. Ground truth comparison will show N/A or 0 for deriva repository.

---

## CLI Commands

### Step 1: Run Benchmark (Current Code - Baseline)

```bash
uv run deriva-cli benchmark run \
  --repos deriva,bigdata \
  --models mistral-devstral2 \
  -n 1 \
  --per-repo \
  -v \
  -d "Baseline test before BENCHMARK_OUTPUT.md changes"
```

**Expected output location**: `workspace/benchmarks/bench_YYYYMMDD_HHMMSS/`

### Step 2: Run Analysis

```bash
uv run deriva-cli benchmark analyze <session_id>
```

### Step 3: Run Comprehensive Analysis

```bash
uv run deriva-cli benchmark comprehensive-analysis <session_id> \
  -o workspace/benchmarks/<session_id>
```

### Step 4: Verify Output Structure

```bash
# Windows PowerShell
Get-ChildItem -Recurse workspace/benchmarks/<session_id> | Select-Object FullName

# Or simple dir
dir workspace\benchmarks\<session_id> /s
```

---

## Verification Checklist

After running baseline benchmark, check:

- [ ] `workspace/benchmarks/{session_id}/` directory created
- [ ] `summary.json` exists (will be renamed to `session_metadata.json`)
- [ ] `events.ocel.json` at root (will be moved to `ocel/`)
- [ ] `events.jsonl` at root (will be moved to `ocel/`)
- [ ] `models/` directory contains XML files
- [ ] Model filenames show current naming pattern

After implementing changes and re-running:

- [ ] `session_metadata.json` (renamed)
- [ ] `ocel/benchmark_events.json` (moved + renamed)
- [ ] `ocel/benchmark_events.jsonl` (moved + renamed)
- [ ] `cache/llm_cache.json` (consolidated)
- [ ] `results/consistency_metrics.csv` (new)
- [ ] `results/ground_truth_comparison.csv` (new)
- [ ] `results/quality_verification.csv` (new)
- [ ] `results/inter_model_agreement.json` (extracted)
- [ ] `results/execution_metrics.csv` (new)
- [ ] Model files named `{repo}_{model}_run{n}.xml`

---

## Implementation Order

1. **Run baseline benchmark** with current code
2. **Inspect output** to confirm current structure
3. **Implement Phase 1** (naming/directory changes)
4. **Implement Phase 2** (cache consolidation)
5. **Implement Phase 3** (CSV exports)
6. **Re-run benchmark** and verify output matches spec

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Breaking existing benchmark sessions | Keep backward compatibility by checking for old filenames |
| Missing reference models | Generate placeholder CSV rows with N/A values |
| OCEL parsing errors | Add try/except blocks with graceful fallbacks |
| Large cache files | Limit consolidated entries to current session only |

---

## Files Summary

| File | Changes |
|------|---------|
| `deriva/services/benchmarking.py` | Lines 1055, 1178-1184, 1195, 1200-1234 |
| `deriva/services/analysis.py` | Lines 531-548 + 4 new methods |

**Total estimated lines of code**: ~150 new/modified lines
