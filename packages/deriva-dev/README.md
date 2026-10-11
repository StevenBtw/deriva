# Deriva (development and benchmarking)

**Everything in Deriva, plus benchmarking.**

`deriva-dev` installs Deriva Studio, the command line tool and the benchmarking system: repeated runs across repositories and LLMs, consistency and answer stability per step, the differences between runs traced back to the prompts and answers that caused them, and complete log bundles for each session.

```bash
uv tool install --python 3.14 deriva-dev
deriva                      # the studio, with its Benchmark mode
deriva-cli benchmark run --repos my-repo --models my-model -n 3 -v
deriva-cli benchmark analyze <session>
```

To reproduce a published release exactly, install it with the `constraints.txt` from its GitHub release:

```bash
uv tool install --python 3.14 deriva-dev==0.8.0 -c constraints.txt
```

- Keeps its files in `~/.deriva` (`DERIVA_HOME` moves it).
- Install it as a tool or in its own environment: its Python package is named `deriva`, like ISI's `deriva-py`, and the two cannot share an environment.

Documentation: https://docs.deriva.dev. Source and releases: https://github.com/StevenBtw/deriva

Deriva is part of a research project on AI-assisted domain modeling. License: AGPL-3.0-or-later.
