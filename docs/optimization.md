# Optimization

Every LLM step in Deriva is driven by a configuration you can change: which candidates it sees, what the prompt says and how the model is called. This page explains how to improve those configurations so the model gets better and more consistent on any repository, not only on the one you test with.

To measure the effect of a change, see [Benchmarks](benchmarks.md).

## How steps are configured

The pipeline is a sequence of steps. Extraction steps build the graph from the repository; derivation steps turn the graph into the ArchiMate model in four phases: prep (graph algorithms), generate (one step per element type), relationship (one pass over all elements) and refine (cleanup and checks).

Each step is a row in Deriva's configuration database with these fields:

| Field | Purpose |
| --- | --- |
| Input query or sources | Which graph nodes (derivation) or files (extraction) the step works on |
| Instruction | The prompt text: what to decide and how to name the result |
| Example | An example of the expected output |
| Params | Step settings as JSON: thresholds, filters, switches |
| Temperature | The LLM temperature for this step |
| Batch size, max candidates | How many files go into one LLM call (extraction), and how many candidates a step considers (derivation) |
| Sequence, enabled | Where the step runs in the pipeline, and whether it runs at all |

All text that steers the LLM lives in these fields. The code only adds structure: the order of the prompt's sections, the candidate data and the required output format. So a configuration, together with Deriva's version, fully describes the rules a run gave the LLM; the request itself also holds the candidates of that run, which come from the repository.

### Look and change

```bash
deriva-cli config list derivation
deriva-cli config show derivation ApplicationService
deriva-cli config update derivation ApplicationService --instruction-file instruction.txt
deriva-cli config update derivation ApplicationService --params-file params.json
deriva-cli config update extraction BusinessConcept --batch-size 20 --temperature 0
deriva-cli config versions
```

Params are replaced as a whole, not merged. Start from the step's current params (shown on its configuration page in the studio), change what you need and save the complete JSON, or edit it in the studio directly.

`config update` never overwrites: it saves a new version and makes it the active one, and the earlier versions stay in the history (the studio shows them per step). To go back, update the step with the earlier text. Benchmark sessions record the versions they ran with (`deriva-cli config snapshot <session_id>`).

Change configurations through `config update` or the studio's configuration pages. Importing a configuration file replaces the whole database, version history included, and is only meant for restoring a backup.

## A tuning loop

1. **Find the step.** Run a benchmark and look at what varies (`benchmark analyze`, `benchmark deviations`) and at what is wrong in the model. Pick the one step that causes most of it.
2. **Measure the step alone.** `benchmark step <step>` repeats only that step on a fixed input, so you see its own variation without the rest of the pipeline.
3. **Make one small change** to that step's configuration.
4. **Measure again** the same way, close in time to the first measurement, on more than one repository.
5. **Keep it or go back.** Keep the change if the step improved and the model did not get worse elsewhere; otherwise restore the earlier version. Then start again with the next step.

Work on the pipeline in order. Extraction feeds derivation, so a missing or unstable node in the graph turns into a missing or unstable element later, and fixing it early fixes everything downstream.

## Keep configurations generic

**A configuration must work the same on any repository.** This is the most important rule. A prompt tuned to the repository you test with will look better on that repository and worse everywhere else.

Never put these in a configuration:

- names of entities, classes or concepts from a repository you tested on;
- specific file names;
- specific frameworks or technology stacks, unless the step is about recognizing technologies in general;
- the structure of one project.

Instead, use generic categories, standard terms and properties of the graph.

Too specific:

```text
Create services for: flight booking, seat reservation, loyalty points
Exclude files like: app.py, settings.py
```

Generic:

```text
Create services for: entity management, data validation, document generation
Exclude framework initialization and internal utilities
Skip candidates that no other part of the code depends on
```

A useful test: would this prompt behave the same on an unrelated system, say a hospital scheduler, a game server or a payroll tool? If the answer depends on the domain, the prompt is overfitted.

Keep at least one repository out of your tuning altogether and only measure on it at the end. If a change only helps the repositories you tuned on, it does not generalize.

## Let structure decide

Consistency comes from structure, not from asking the LLM more often. Before you change a prompt, ask whether the decision can be made without the LLM.

- **Filter candidates in the input query.** A derivation step only sees the graph nodes its query returns. Excluding a kind of node there is deterministic and costs nothing.
- **Use graph properties.** The prep phase gives the graph's nodes `pagerank`, `pagerank_percentile`, `louvain_community`, `kcore_level`, `is_articulation_point`, `in_degree` and `out_degree`. Nodes that are central and connected are more stable sources than isolated ones; filter on these properties instead of on names.
- **Use name patterns** for words that mark a candidate as technical or irrelevant (`deriva-cli config pattern add <step> exclude <category> <patterns>`). Patterns hold generic words such as helper or utils, never names from one repository.
- **Exclude directories** that never hold architecture, such as build output and vendored code (`deriva-cli config setting set excluded_directories '[...]'`).
- **Let the LLM classify, not invent.** Give it a closed set of candidates or labels to choose from, one kind of decision per call. Deriva builds identifiers from the code itself, so an LLM's wording never changes which element is which.

When a decision can be made from the graph, files or dependency metadata, make it there. Use the LLM for what only language can tell: what a documented term means, whether a component is an interface, which of a few labels fits.

## Write prompts that classify

When the LLM does decide, a few techniques make its answers stable.

### Give exact naming rules

"Use consistent names" is not enough. Say exactly how a name is formed, with generic examples:

```text
Naming:
1. Singular form ("Report", not "Reports")
2. Title Case for the name
3. Name services after what they do: "Data Validation", "Report Generation"
```

### Name the canonical form

Where synonyms are likely, name the form to use and the ones to avoid:

```text
Use "Configuration" (not: settings, config, preferences)
Use "Notification" (not: alert, message, notice)
```

### Show an example

The LLM follows an example closely. A short, well-formed example output in the step's Example field often does more than a paragraph of rules.

### Structure the prompt

Separate definition, rules and constraints into clearly marked sections:

```text
<definition>
An ApplicationService is behavior that the application exposes.
</definition>

<rules>
Name services after what they do, as a verb phrase.
</rules>

<constraints>
Return an empty list when no candidate fits.
</constraints>
```

### Allow "none"

Say explicitly that an empty answer is fine. Otherwise the LLM tends to fill the output with weak candidates. For business elements especially, no element is better than a technical one labelled as business.

### Ask for the answer, not the reasoning

For classification, direct instructions work better than asking the LLM to think step by step. Ask for the output you need.

### Keep the temperature low

Lower temperature reduces variation between runs. For classification steps, set it at or near 0 (`--temperature 0`).

## Cost and speed

- **Batch size** (extraction): more files or items per LLM call means fewer calls and less repeated instruction text. Large batches can lower quality for complex files; raise it for small, similar items.
- **Max candidates** (derivation): caps how many candidates a step considers. Combined with a graph filter, it keeps the most central candidates.
- **The cache:** answers are cached by prompt, so a run with unchanged prompts costs nothing. While tuning one step, keep the cache on for all others (`--nocache-configs <step>`).
- **Start with one run** to check that a change works at all, then measure with several.

## Consistency is not accuracy

A step can give the same wrong answer in every run. Consistency only says the model is reproducible. Check what the model says against what you know of the system: are the components the real parts of the system, do the services describe what it does, are business elements really business concepts? Fixing a wrong answer is an improvement even when the model gets smaller.
