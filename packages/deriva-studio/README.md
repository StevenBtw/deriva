# Deriva Studio

**From code repositories to ArchiMate models.**

Deriva reads a software repository, builds a graph of what is in it, and derives an [ArchiMate](https://www.opengroup.org/archimate-forum) enterprise architecture model you can open in [Archi](https://www.archimatetool.com/). Deriva Studio is its local web interface: run the pipeline, watch the intermediate graph and the output graph grow live with links from every derived element to its sources, read every prompt and answer, edit the versioned configuration, and export the model.

```bash
uv tool install --python 3.14 deriva-studio
deriva
```

Or try it without installing: `uvx --python 3.14 deriva-studio`.

- Includes the command line tool `deriva-cli`; benchmarking comes with [deriva-dev](https://pypi.org/project/deriva-dev/).
- Runs locally: the studio listens on this machine only, and nothing leaves it except the prompts to the LLM you configure (cloud or local).
- Keeps its files in `~/.deriva` (`DERIVA_HOME` moves it).
- Install it as a tool or in its own environment: its Python package is named `deriva`, like ISI's `deriva-py`, and the two cannot share an environment.

Documentation: https://docs.deriva.dev. Source and releases: https://github.com/StevenBtw/deriva

Deriva is part of a research project on AI-assisted domain modeling. License: AGPL-3.0-or-later.
