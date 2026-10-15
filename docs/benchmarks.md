# Benchmarks

An LLM does not always give the same answer twice, so two runs of Deriva on the same repository can produce slightly different models. Benchmarks repeat runs, show how consistent the model is across them, and point to the pipeline steps and prompts that cause the differences.

## Install benchmarking

Benchmarking is part of `deriva-dev`, one of Deriva's three packages (see [Architecture](architecture.md#packages)): it adds the benchmark commands and the studio's benchmark views to everything else. In a source checkout, `uv sync` installs all three packages, so benchmarking is always available. Where `deriva-dev` is missing, `deriva-cli benchmark` prints how to install it and exits, and the studio hides its benchmark views.

### Models

A benchmark runs with one or more of the LLM models configured in your `.env`, each a block of `LLM_{NAME}_*` settings (the guide explains how to set one up). The model's name is that `NAME` in lower case with hyphens: `LLM_MISTRAL_SMALL_*` is `mistral-small`. A model that takes no temperature (`SAMPLING=false`) runs at its provider's default sampling; compare its consistency with that in mind. List them with:

```bash
deriva-cli benchmark models
```

## What a benchmark measures

Deriva is built so that structure decides as much as possible: candidates, identifiers and many relationships come from the code itself, and the LLM classifies within a fixed set of choices. Variation that remains comes from those LLM answers. A benchmark measures it at three levels:

- **Consistency:** the share of elements and relationships that appear in every run. Elements are compared by identifier, which comes from the code, so the same element has the same identifier in every run.
- **Answer stability:** the share of prompts that the LLM answered identically in every run. This is the raw variation of the model, before Deriva's later steps filter or combine answers, so post-processing cannot hide it.
- **Decision stability:** for steps that classify many items per call, the share of items that got the same decision in every run. One changed label makes a whole answer differ, so this is the finer measure for those steps.

Each decision is one LLM call. Deriva does not ask the same question several times and vote, so the consistency a benchmark reports is the consistency you get in a normal run.

### Caching

Deriva caches LLM answers by prompt. A cached run gives back exactly the answers of an earlier run, which is how you check that a change to code or settings leaves the model identical. To measure variation, run without the cache (`--no-cache`), or leave the cache off only for the steps you are testing (`--nocache-configs`).

## Run a benchmark

A benchmark session runs every combination of repositories, models and repetitions:

```bash
deriva-cli benchmark run --repos my-repo --models my-model -n 3 --no-cache -v
```

The repositories must be cloned first (`deriva-cli repo clone <url>`). Several repositories in `--repos` are combined into one model per run. With `--per-repo`, each repository gets its own runs, which gives a consistency score per repository:

```bash
# 2 repositories x 1 model x 3 runs = 6 runs
deriva-cli benchmark run --repos repo-a,repo-b --models my-model -n 3 \
  --per-repo --no-cache
```

To compare models, pass several in `--models`; the analysis then also reports how much the models agree with each other.

### Test one change cheaply

After changing one step's configuration, run the benchmark with the cache on for everything except that step:

```bash
deriva-cli benchmark run --repos my-repo --models my-model -n 3 \
  --nocache-configs ApplicationService
```

Only the named steps call the LLM; the others answer from the cache.

## Measure one step

`benchmark step` repeats a single pipeline step on a fixed input and compares only what that step produces. Nothing before or after it varies, so a change to one step is measured without the noise of the rest of the pipeline.

```bash
deriva-cli benchmark step BusinessConcept --repos my-repo --model my-model -n 3 -v
deriva-cli benchmark step DataObject --repos my-repo --model my-model -n 3 -v
```

- The step can be an extraction step, a derivation step (an element type, `ConsolidatedRelationships` for the relationship pass, or a refine step), or `prep` for the graph algorithms of the preparation phase.
- The step's input (the result of every earlier step) is built once, with LLM answers from the cache, and saved in the session folder. Each run copies that input into its own work database, so the repository's own graph is not touched, and calls the LLM for the step without the cache.
- The output of a run is every node and edge the step added, changed or removed, with its properties. For derivation steps it also holds the model's elements (by identifier) and relationships (by type, source and target).
- **Presence** counts the objects produced in every run. **Exact** also requires the same properties, and the report names the properties that differ. Text that no later step relies on, such as an element's documentation or the LLM's own suggestion for its name, is reported but not scored in exact.
- The report gives the live LLM calls per run, the answer stability and, for classification steps, the decision stability per item. Element steps report per candidate how far it got (for example created, rejected or filtered out) and which element it became.

The step benchmark needs `GRAFEO_DB_DIR` to be set, because it copies the input to a file per run.

## Analyze the results

```bash
deriva-cli benchmark list                    # recent sessions
deriva-cli benchmark analyze <session_id>    # consistency, stability, model structure
deriva-cli benchmark deviations <session_id> # which steps vary most
```

`benchmark analyze` reports:

- consistency within each model: per repository, the elements and relationships created in every run, of all created (the runs of a session share one extraction, so its edges are compared across sessions, not within one);
- agreement between models, when the session used more than one;
- the structure of each exported model: relationships per element, elements without relationships, parts composed into more than one whole, and chains across layers;
- the elements and relationships that vary most.

It writes the full analysis, including answer stability per repository, to `analysis/summary.json` in the session folder (`-f markdown` for a report to read).

`benchmark deviations` groups the differences by step and sorts the steps by how much they vary, so you know where to start (see [Optimization](optimization.md)).

In the studio, `deriva-dev` adds benchmark views for starting sessions, comparing runs and following a difference back to the prompt and answer that caused it.

## Session files

Each session is a folder in `workspace/benchmarks/<session_id>/` of your Deriva home folder:

| File | Contents |
| --- | --- |
| `session_metadata.json` | The session's settings, runs and results |
| `session_inputs.json` | What the session ran on: the configuration versions and the environment |
| `timings.json` | Time per step and run |
| `models/<repo>_<model>_run<N>.xml` | The model of each run, in the Open Exchange format that Archi imports |
| `llm/<run>.jsonl` | Every LLM call of a run: step, prompts, answer, cache hit, tokens, latency, errors |
| `ocel/benchmark_events.json` | The session's event log in the OCEL 2.0 JSON format, for object-centric process mining tools |
| `ocel/benchmark_events.jsonl` | The same events as a stream, written during the session and read by `benchmark analyze` |
| `ocel/cases.csv`, `ocel/cases.xes` | A flat event log with one case per run, for case-centric tools |
| `analysis/summary.json` | The output of `benchmark analyze` |
| `step_results.json`, `steps/` | The results and fixed inputs of `benchmark step` |

`--no-export-models` leaves out the model files to save disk space.

### Share a session

```bash
deriva-cli benchmark export <session_id> -o session.zip
```

The zip holds the whole session folder, the full text of every configuration at the session's versions (`config_snapshot.json`), the environment (`environment.json`: Deriva version, library versions, platform and model settings without API keys) and `manifest.json` with the SHA-256 and size of every file. The environment is read when you export, so exporting the same session twice on the same install gives identical bytes, and a published result can be checked file by file.

### Process mining

```bash
deriva-cli benchmark ocel <session_id>[,<session_id>...] -o <folder>
```

This writes the event logs of one or more sessions to one folder, so the runs of several sessions or models sit side by side:

- `ocel.json`, in the OCEL 2.0 JSON format: every step, LLM call and run as an event, related to its session, run, repository, model and step, and to the graph nodes, edges, elements and relationships it created. Load it with `pm4py.read_ocel2_json`, or in any tool that reads OCEL 2.0.
- `cases.csv` and `cases.xes`, a flat log with one case per run: the activity (`Start run`, `Extract · <step>`, `Derive · <step>`, `LLM · <step> · <call kind>`, `Complete run`), its start and end time, the model as resource, and the event's details (duration, cache hit, tokens, latency, rate-limit wait). In Disco, import the CSV with `case_id` as case, `activity` as activity, `start_timestamp` and `timestamp` as timestamps and `resource` as resource.

In the studio, **Process mining logs** downloads the same files for the selected sessions.

## Measure well

- **Measure without the cache.** Cached runs repeat earlier answers and always look perfectly consistent.
- **Change one thing at a time,** and benchmark before and after it.
- **Run at least three times per repository.** Consistency over a few runs moves from session to session; compare sessions run close together and do not read much into small differences.
- **Use several repositories,** and keep one or two that you never tune on. A change that helps one repository can hurt another; the untouched repositories show whether it generalizes.
- **Start at the step.** Find the step that varies with `benchmark step`, fix it, then confirm the effect with a full run.
- **Consistency is not accuracy.** A step can give the same wrong answer every time. Check the model against what you know of the system, or against a model you trust.

## Command reference

### benchmark run

| Option | Meaning |
| --- | --- |
| `--repos` | Repositories, comma-separated (required) |
| `--models` | Model names, comma-separated (required) |
| `-n`, `--runs` | Runs per combination (default 3) |
| `--per-repo` | Run each repository on its own instead of combined |
| `--stages` | Stages to run: `extraction`, `derivation` (default both) |
| `--no-cache` | Call the LLM for every step |
| `--nocache-configs` | Call the LLM only for these steps, comma-separated |
| `--no-cache-extraction` | Extract again instead of reusing an earlier extraction (LLM answers still come from the cache unless `--no-cache`) |
| `--no-cache-extraction-llm` | Run only the LLM extraction steps again, keep the structural ones |
| `--only-extraction-step` | Run only this extraction step |
| `--only-derivation-step` | Run only this derivation step |
| `--no-defer-relationships` | Derive relationships after each element batch instead of in one pass after all elements (for comparison only) |
| `--no-export-models` | Do not write model files |
| `--no-clear` | Do not clear the graph between runs |
| `--bench-hash` | Keep each run's LLM cache separate |
| `-d`, `--description` | A description for the session |
| `-v`, `--verbose` / `-q`, `--quiet` | Detailed progress / no progress bar |

### Other commands

| Command | Does |
| --- | --- |
| `benchmark step <step> --repos <repos> --model <model> [-n N] [-v]` | Repeat one step on a fixed input |
| `benchmark list [-l N]` | List recent sessions |
| `benchmark analyze <session_id> [-o file] [-f json\|markdown]` | Analyze a session |
| `benchmark deviations <session_id> [-o file] [-s deviation_count\|consistency_score\|total_objects]` | Variation per step |
| `benchmark export <session_id> -o <zip>` | Bundle a session with its configurations, environment and checksums |
| `benchmark ocel <session_ids> -o <folder>` | Event logs of sessions for process mining (OCEL 2.0, CSV, XES) |
| `benchmark conventions <session_ids> [-o folder] [--run N]` | Check the run snapshots against ArchiMate modelling conventions: a review page per repository and a summary |
| `benchmark mark-failed <session_id>` | End a session whose process stopped without finishing (still `running`) as failed; its files stay |
| `benchmark models` | List the configured models |
