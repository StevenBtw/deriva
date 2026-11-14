# Troubleshooting

Common problems with an install or a run, and how to solve them.

## The studio shows a "not built yet" page

The front end is missing (source checkouts only; the installed studio ships its front end): build it ([from source](get-started.md#from-source)) and start the studio again (it looks for the front end when it starts).

## A banner says the databases are held

A command line run, for example a benchmark, has the databases open. The studio shows what it can and carries on when that run finishes.

## The wrong Python, or a broken install

An installed tool:

```bash
uv tool install --reinstall --python 3.14 deriva-studio
```

A source checkout:

```bash
uv run python --version  # 3.14 or newer
uv sync --reinstall
```

## The business concept step cannot download its models

On its first run with an LLM this step downloads its language models into `workspace/cache/nlp` in your home folder and checks them by SHA-256: three spaCy pipelines (English, German, French, about 63 MB) from GitHub and two translation models (German and French to English, about 220 MB) from argos-net.com, about 300 MB on disk. A run without an LLM skips the step and downloads nothing. Check that the machine can reach the model hosts and run the step again, or fetch the models ahead of time (for example before going offline):

```bash
deriva-cli nlp fetch
```

`DERIVA_NLP_MODELS_DIR` in `.env` moves the folder. Their licences are listed in `THIRD_PARTY_NOTICES.md`.
