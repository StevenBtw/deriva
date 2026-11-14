# Get started

Install Deriva, connect a language model and derive your first ArchiMate model.

## Install

Deriva runs on your own machine: Deriva Studio in your browser, the pipeline and its embedded databases locally. Nothing is sent anywhere except the prompts to the LLM you choose.

### Requirements

- **uv**, the Python package manager (below). It downloads Python 3.14 for you.
- **Git**, to clone the repositories you analyse.
- **An LLM**: an API key for Azure OpenAI, OpenAI, Anthropic or Mistral, or a local model in Ollama or LM Studio.

### 1. Install uv

Windows (PowerShell):

```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

macOS and Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Install Deriva Studio

```bash
uv tool install --python 3.14 deriva-studio
deriva
```

`deriva` starts the studio and opens it in your browser at `http://127.0.0.1:8765`. It listens on this machine only; `--port` picks another port, `--no-browser` leaves the browser closed, and the API documentation is at `/docs`. Each start prints a launch link with a fresh token: the studio answers only a browser that opened that link (or a script that sends the token as an `X-Deriva-Token` header), so another website open in your browser cannot use it. To reach it from other machines, use `--host <address> --allow-remote --tls-cert <file> --tls-key <file>`; it does not start without TLS, because the launch link would cross the network readable.

To try Deriva without installing it:

```bash
uvx --python 3.14 deriva-studio
```

`--python 3.14` matters: Deriva needs Python 3.14, and without it uv may pick an older Python and refuse the install.

### 3. Add a model

On its first start the studio shows a banner until an LLM model is configured. Open **General**, add a model under **Models** and save; [Set Up an LLM](#set-up-an-llm) explains the fields. Structural steps run without a model, so **Structural steps only (without LLM)** in the Workspace gives a first look right away.

## Which package

| Package | Gives you | Commands |
|---------|-----------|----------|
| `deriva-studio` | the studio and the command line | `deriva`, `deriva-studio`, `deriva-cli` |
| `deriva-cli` | the command line only, for scripts, CI and servers | `deriva-cli` |
| `deriva-dev` | everything, plus benchmarking | `deriva`, `deriva-dev`, `deriva-cli` |

All three release together with the same version number.

## Where Deriva keeps its files

An installed Deriva keeps everything in one folder, `~/.deriva` (on Windows `%USERPROFILE%\.deriva`):

| In the home folder | Holds |
|--------------------|-------|
| `.env` | your settings and model configs; the studio writes it when you save the first model |
| `sql.db` | the step configurations with their versions, file types, name patterns and settings; created from the defaults on first start |
| `workspace/` | cloned repositories, the graphs, caches, runs, benchmark sessions and exports |

The environment variable `DERIVA_HOME` moves this folder, for example to keep projects apart or to try something in a sandbox. `deriva-cli status` shows which home folder is in use. Relative paths in `.env` are read from the home folder, so Deriva finds the same files from any working directory.

## Upgrade and uninstall

```bash
uv tool upgrade deriva-studio
uv tool uninstall deriva-studio
```

An upgrade keeps your work: the configuration database only gets the schema changes a new version needs, and your own step versions stay as they are. Uninstalling leaves the home folder in place; delete `~/.deriva` to remove your data too.

The packages share the `deriva` and `deriva-cli` commands, so install one of them. To switch, for example to get benchmarking, uninstall the other first; your home folder stays:

```bash
uv tool uninstall deriva-studio
uv tool install --python 3.14 deriva-dev
```

### Reproduce a release exactly

Every GitHub release has a `constraints.txt` with the exact version of every dependency. Download it from the release's assets into the current folder, then install against it:

```bash
uv tool install --python 3.14 deriva-dev==0.9.0 -c constraints.txt
```

### Next to other Python packages

Deriva's Python package is named `deriva`, like the client of ISI's DERIVA platform (`deriva-py`, on PyPI as `deriva`). The two cannot share one Python environment. Install Deriva as a tool, as above, or in a virtual environment of its own.

## From source

For development, or to follow the latest changes:

```bash
git clone https://github.com/StevenBtw/Deriva.git
cd Deriva
uv sync
cd studio && npm install && npm run build && cd ..
uv run deriva
```

`uv sync` installs all three packages from the checkout, with the development tools. The checkout is its own home folder: `.env` and `workspace/` sit in the repository root, and the configuration database in `deriva/adapters/database/sql.db`. Building the front end needs Node 22; build again after you pull changes to `studio/`. [CONTRIBUTING.md](contributing.md) has the details.

## Set up an LLM

Each model gets a block of `LLM_{NAME}_*` settings in `.env` in your home folder (the studio's **General** page writes them for you), and `LLM_DEFAULT_MODEL` picks the one Deriva uses. The default model is the name in lowercase with hyphens: `LLM_MISTRAL_SMALL_*` becomes `mistral-small`.

```bash
# .env: a cloud model
LLM_DEFAULT_MODEL=mistral-small
LLM_MISTRAL_SMALL_PROVIDER=mistral
LLM_MISTRAL_SMALL_MODEL=mistral-small-2603
LLM_MISTRAL_SMALL_KEY=your-mistral-api-key
```

Name a dated model version (`mistral-small-2603`) rather than a `-latest` alias, so a run says which model answered; each LLM call also records the model the provider reports. Some models need more settings:

```bash
# .env: models without a temperature, or with reasoning to switch off
LLM_ANTHROPIC_HAIKU_PROVIDER=anthropic
LLM_ANTHROPIC_HAIKU_MODEL=claude-haiku-5-5
LLM_ANTHROPIC_HAIKU_SAMPLING=false    # takes no temperature: Deriva leaves it out
LLM_ANTHROPIC_HAIKU_REASONING=none    # thinking off
LLM_OPENAI_LUNA_PROVIDER=openai
LLM_OPENAI_LUNA_MODEL=gpt-6-luna
LLM_OPENAI_LUNA_REASONING=none        # reasoning off, so the temperature applies
LLM_OPENAI_LUNA_TEMPERATURE=0         # this model's own temperature, over LLM_TEMPERATURE
```

`REASONING` is a level (`none`, `low`, `medium`, `high`) for OpenAI, Azure and Anthropic models. Without `SAMPLING`, an Anthropic model that refuses a temperature (such as Claude Haiku 5.5) gets none, and every other model takes one. A model with `SAMPLING=false` runs at its provider's default sampling, so its answers can vary more than those of a model at temperature 0. `TEMPERATURE` (0 to 2) sets one model's temperature; models without it use `LLM_TEMPERATURE`. Every LLM call records the temperature it sent (none with `SAMPLING=false`); top_p and seed are never sent, so the provider's defaults apply. `deriva-cli config model set <name> --provider <provider> --model <model id> --sampling false --reasoning none --temperature 0` writes these settings.

A local model needs no key:

```bash
# .env: a local model in Ollama
LLM_DEFAULT_MODEL=ollama-devstral
LLM_OLLAMA_DEVSTRAL_PROVIDER=ollama
LLM_OLLAMA_DEVSTRAL_MODEL=devstral-small-2
LLM_OLLAMA_DEVSTRAL_URL=http://localhost:11434/api/chat
LLM_OLLAMA_DEVSTRAL_CONTEXT=8192      # the server's context window, in tokens
```

Ollama gives each model a 4096-token window unless you start it with a larger one (`OLLAMA_CONTEXT_LENGTH=8192 ollama serve`), and it cuts a longer prompt without an error. Deriva cannot set the window through Ollama's OpenAI-compatible API, so start the server with the size you need and set `CONTEXT` to the same number (`deriva-cli config model set <name> ... --context 8192`). A call that fills the window is then logged as a warning. Very small local models (about 3B parameters) can fail the classification steps with `Exceeded maximum output retries`; use a larger model when they do.

| Provider | For |
|----------|-----|
| `azure` | Azure OpenAI |
| `openai` | OpenAI |
| `anthropic` | Anthropic |
| `mistral` | Mistral |
| `ollama` | Ollama, local |
| `lmstudio` | LM Studio, local |

To check a model config, press **Test** next to it on the studio's **General** page, or run `deriva-cli config model test <name>`: it makes one small call and says whether the key, the model id and the URL work, or what to fix.

Structured answers need no setting: Deriva passes each step's schema to the provider and checks the answer against it. Rate limits, retries and the response cache have defaults; [Configuration](configuration.md) has them, and the repository's [`.env.example`](https://github.com/StevenBtw/Deriva/blob/main/.env.example) lists every setting.

## Your first model

### Analyse your first repository

1. Open **Repositories** in the studio's menu and choose **+ Clone repository**. Enter the Git URL; a name and a branch are optional.
2. Open the **Workspace**, pick the repository and a scope, and press **Run**. **Structural steps only (without LLM)** gives a first look without any LLM calls.
3. Follow the run in the tabs at the bottom: **Live**, **Trace**, **Prompts** and **Errors**. The Workspace draws the repository, the intermediate graph and the output graph as lanes of one canvas: the intermediate graph grows step by step, and each derived element appears with links back to the nodes it came from. **Separate**, next to **Linked**, shows the two graphs apart instead.
4. **View model**, at the end of the canvas or on the right edge, opens the output graph as an ArchiMate diagram; click an element for its details.

### Export to Archi

Deriva writes the model in the Open Group ArchiMate exchange format. From the studio: open **Export config** (under **Model** in the menu), choose a file name and press **Save**; the page shows the full path in `workspace/output`, warns when the save replaces a file, and lists the exports already there. **Export XML** in the **View model** panel saves one too: the browser downloads it as `<repository>-<yyyymmdd-hhmmss>.xml`, and a copy under the same name stays in `workspace/output` on the machine that runs the studio. Or from the command line:

```bash
deriva-cli export -o workspace/output/model.xml --repo my-repo
```

In [Archi](https://www.archimatetool.com/), choose **File**, **Import**, **Open Exchange XML Model** and pick the file.
