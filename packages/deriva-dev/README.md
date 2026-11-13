# Deriva (development and benchmarking)

**Everything in Deriva, plus benchmarking.**

`deriva-dev` installs Deriva Studio, the command line tool and the benchmarking system: repeated runs across repositories and LLMs, consistency and answer stability per step, the differences between runs traced back to the prompts and answers that caused them, and complete log bundles for each session.

```bash
uv tool install --python 3.14 deriva-dev
```

Running and analysing benchmarks: https://docs.deriva.dev/benchmarks/. To reproduce a published release exactly: https://docs.deriva.dev/get-started/#reproduce-a-release-exactly

- Install it as a tool or in its own environment: its Python package is named `deriva`, like ISI's `deriva-py`, and the two cannot share an environment.

Source and releases: https://github.com/StevenBtw/deriva

Deriva is part of a research project on AI-assisted domain modeling. License: AGPL-3.0-or-later.
