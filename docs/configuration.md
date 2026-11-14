# Configuration

Settings, file types, limits, name patterns and versioned step configuration.

## Environment Variables (.env)

Runtime settings (the graph folder, models and providers, LLM rate limits) live in `.env` in your [home folder](get-started.md#where-deriva-keeps-its-files); a variable set in the environment wins over the file. File types, name patterns, system settings and the versioned step configuration are in Deriva's configuration database, changed with the commands below. Key `.env` settings:

```bash
# Graph database (grafeo embedded)
GRAFEO_DB_DIR=workspace/graphs  # Default: one <repo>.grafeo database per repository in the home folder; empty = in-memory

# LLM Provider (mistral, openai, azure, anthropic, ollama, lmstudio)
LLM_MISTRAL_SMALL_PROVIDER=mistral
LLM_MISTRAL_SMALL_MODEL=mistral-small-2603
LLM_MISTRAL_SMALL_KEY=your-mistral-api-key

# Namespaces
GRAPH_NAMESPACE=Graph
ARCHIMATE_NAMESPACE=Model

# NLP translation models for business concepts (default shown)
DERIVA_NLP_MODELS_DIR=workspace/cache/nlp
```

See `.env.example` for all available options.

## Rate Limiting

The LLM adapter includes built-in rate limiting to prevent API throttling:

```bash
# Requests per minute (0 = use provider default: 60 RPM for cloud, unlimited for local)
LLM_RATE_LIMIT_RPM=0

# Minimum delay between requests in seconds
LLM_RATE_LIMIT_DELAY=0.0

# Max retries on rate limit (429) errors
LLM_RATE_LIMIT_RETRIES=3

# Adaptive throttling (reduces RPM when hitting rate limits)
LLM_THROTTLE_ENABLED=true
LLM_THROTTLE_MIN_FACTOR=0.25    # Minimum 25% of configured RPM
LLM_THROTTLE_RECOVERY_TIME=60   # Seconds before trying to increase RPM

# Circuit breaker (stops requests when provider is failing)
LLM_CIRCUIT_BREAKER_ENABLED=true
LLM_CIRCUIT_FAILURE_THRESHOLD=5   # Consecutive failures to open circuit
LLM_CIRCUIT_RECOVERY_TIME=30      # Seconds before testing recovery
```

Default rate limits by provider:

| Provider | Default RPM |
|----------|-------------|
| Azure OpenAI | 60 |
| OpenAI | 60 |
| Anthropic | 60 |
| Mistral | 60 |
| Ollama | Unlimited |
| LM Studio | Unlimited |

The rate limiter automatically:

- Throttles requests to stay within limits
- Applies exponential backoff on rate limit errors (HTTP 429)
- Respects Retry-After headers from providers
- Adaptively reduces RPM when hitting rate limits (recovers over time)
- Opens circuit breaker after consecutive failures to prevent cascading errors

## Managing File Types

If you encounter **undefined extensions** during extraction:

**Via the studio:**

1. Open **General & file types** in the menu
2. Add them to the registry:
   - Extension (e.g., `.tsx`, `Dockerfile`)
   - Type (source, config, docs, test, build, asset, data, exclude)
   - Subtype (e.g., `typescript`, `docker`)

**Via CLI:**

```bash
# List all registered file types
deriva-cli config filetype list

# Add a new file type
deriva-cli config filetype add ".tsx" source typescript

# Delete a file type
deriva-cli config filetype delete ".tsx"

# Show file type statistics by category
deriva-cli config filetype stats
```

> **Note:** Files with unrecognized extensions are automatically classified as `file_type="unknown"` with their extension as the subtype. This ensures all files get proper classification even without explicit registry entries.

**Excluded directories:** dependency and tool directories are skipped by every repository walk (no Directory or File nodes, no LLM calls), matched as whole path segments. The list is the `excluded_directories` system setting (JSON list); by default `.git`, `__pycache__`, `node_modules`, `bower_components`, `vendor`, `.venv`, `venv` and `site-packages`. Changing it triggers re-extraction.

```bash
deriva-cli config setting show excluded_directories
deriva-cli config setting set excluded_directories '[".git", "node_modules", "third_party"]'
```

**Limits for untrusted repositories:** extraction does not read a file larger than `max_read_bytes` (default 50 MB; it is reported, and the run goes on), and a run makes at most `max_llm_calls_per_run` LLM calls (default 2000; a call's own retries after a provider error are not counted, so failing providers can see up to `LLM_MAX_RETRIES` more requests per call), after which every further call of that run fails with a message naming the setting. A type's code snippet keeps at most `max_snippet_line_chars` characters of each line (default 2000), so a minified or generated one-line file cannot fill the disk. Raise them for a very large repository.

```bash
deriva-cli config setting set max_llm_calls_per_run 5000
```

**LLM answers per decision:** the steps that vote (directory classification and element naming) ask the same question `samples` times and keep the majority answer; every step ships with 1. The `llm_samples` setting (1 to 20, also on the studio's **General** page) replaces that for all of them while it is set, and `config setting unset llm_samples` gives each step its own value again. Answers can differ even at temperature 0 or with the provider's default sampling, and a higher temperature generally adds variation; more answers cost that many more calls. Benchmark sessions record the value, so measure consistency with 1.

```bash
deriva-cli config setting set llm_samples 3
deriva-cli config setting unset llm_samples
```

**Derivation name patterns:** some derivation steps use include and exclude patterns on the names of their code candidates; business concepts are already classified and skip them. Most of these steps reject a name that contains an exclude pattern and keep one that contains an include pattern, and a name that matches neither follows the step's default (rejected by most steps, kept by BusinessFunction, ApplicationInterface, SystemSoftware and TechnologyService). BusinessObject (type definitions) and BusinessEvent (methods) use the patterns to rank candidates instead, and fill their remaining slots with names that did not match. A step that uses the default candidate filter (ApplicationComponent, ApplicationInterface, BusinessFunction, DataObject, Device, Node, SystemSoftware, TechnologyService) can limit the patterns to candidates with given graph labels with its `pattern_labels` param, and set a k-core threshold with `graph_filter`. Patterns are stored per step, type and category.

```bash
deriva-cli config pattern list Node
deriva-cli config pattern add Node include deployment helm
deriva-cli config pattern delete Node include --category deployment helm   # a category left empty is deactivated
```

**Full derivation runs start from an empty model:** a derivation run skips every candidate the model already has, so a run on top of an earlier model derives less than a run from scratch. A full run (`run derivation` or `run all` without `--phase` or `--only-step`, and the studio's run scopes) therefore clears the model first, as benchmarks do. Runs of one phase or one step keep the model. The `derivation_clear_model` system setting (default `true`) switches this off; with benchmarking installed, the studio shows it as a switch in **General**.

```bash
deriva-cli config setting set derivation_clear_model false
```

## Updating Configurations (Versioning)

Deriva uses a **versioning system** for configurations. When you update a config, a new version is created while preserving previous versions for rollback.

**Correct ways to update configs:**

1. **Via the studio**: see [Change a prompt](how-tos.md#change-a-prompt)
2. **Via CLI**: Use the `config update` command

```bash
# Update extraction config instruction
deriva-cli config update extraction BusinessConcept \
  -i "New instruction text..."

# Update extraction config with batch size for multi-file LLM calls
deriva-cli config update extraction BusinessConcept \
  --batch-size 5

# Update derivation config from file
deriva-cli config update derivation ApplicationComponent \
  --instruction-file prompts/app_component.txt

# View all versions
deriva-cli config versions

# Start a release from version 1 (removes the version history; keep a backup)
deriva-cli config reset-versions --yes
```

**Do NOT use JSON import/export for config updates.** The `db_tool import` command is only for backup restoration or migration - it overwrites version history. See [docs/benchmarks.md](benchmarks.md) for the optimization workflow.
