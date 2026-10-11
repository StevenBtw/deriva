# Deriva CLI

**From code repositories to ArchiMate models, from the command line.**

Deriva reads a software repository, builds a graph of what is in it, and derives an [ArchiMate](https://www.opengroup.org/archimate-forum) enterprise architecture model you can open in [Archi](https://www.archimatetool.com/). `deriva-cli` runs the whole pipeline without a browser, for scripts, CI jobs and servers.

```bash
uv tool install --python 3.14 deriva-cli

deriva-cli repo clone https://github.com/user/my-repo.git
deriva-cli run all --repo my-repo -v
deriva-cli export -o model.xml --repo my-repo
deriva-cli status
```

- Configuration from the command line: `deriva-cli config list derivation`, `deriva-cli config show extraction BusinessConcept`; every change is a new version, earlier versions stay.
- Models are configured in `.env` in the home folder `~/.deriva` (`DERIVA_HOME` moves it).
- For the local web interface install [deriva-studio](https://pypi.org/project/deriva-studio/); for benchmarking, [deriva-dev](https://pypi.org/project/deriva-dev/).
- Install it as a tool or in its own environment: its Python package is named `deriva`, like ISI's `deriva-py`, and the two cannot share an environment.

Documentation: https://docs.deriva.dev. Source and releases: https://github.com/StevenBtw/deriva

Deriva is part of a research project on AI-assisted domain modeling. License: AGPL-3.0-or-later.
