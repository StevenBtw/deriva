# CLI

Run the same pipeline without the studio, from a terminal, a script or a CI job.

`deriva` starts the studio; `deriva-cli` runs the same pipeline without it, for scripts and automation. From a source checkout, put `uv run` in front of both.

```bash
deriva-cli repo clone https://github.com/user/my-repo.git
deriva-cli repo list
deriva-cli run all --repo my-repo -v
deriva-cli run extraction --repo my-repo --no-llm
deriva-cli status
deriva-cli coverage --repo my-repo
deriva-cli quality --repo my-repo
deriva-cli export -o workspace/output/model.xml --repo my-repo
deriva-cli --help
```

| Option | Does |
|--------|------|
| `--repo NAME` | Runs one repository (default: all) |
| `--phase PHASE` | Runs one phase of `run extraction` (classify or parse) or `run derivation` (prep, generate or refine); `run all` ignores it |
| `--only-step STEP` | Runs a single step of `run extraction` or `run derivation`; with `run all`, one extraction step and then the whole derivation |
| `--no-llm` | Makes no LLM call: extraction runs its parsers, derivation only its prep phase (graph metrics), and the model is kept |
| `-v` | Prints detailed progress |
| `-o PATH` | Where `export` writes the model |

Configuration from the command line:

```bash
# View configuration
deriva-cli config list extraction
deriva-cli config show extraction BusinessConcept

# Add a derivation step (created disabled, then enable it); a refine step
# must also be implemented and registered in code under the same name
deriva-cli config add derivation my_refine_step --phase refine --sequence 4 --params '{"dry_run": true}'
deriva-cli config enable derivation my_refine_step
# Every supported ArchiMate element type has a generate step; the types without a step of their own
# (Contract or Product, for example) ship disabled: enable one to derive that type too
deriva-cli config enable derivation Contract

# Manage file types
deriva-cli config filetype list
deriva-cli config filetype add ".lock" dependency lock
deriva-cli config filetype stats

# System settings (e.g. directories skipped during extraction)
deriva-cli config setting show excluded_directories

# Derivation name patterns (include and exclude, per step and category)
deriva-cli config pattern list SystemSoftware
```
