# How-tos

Everyday tasks in Deriva Studio: change what a step asks the LLM, and where to go next.

## Change a prompt

1. Open **Extraction config** or **Derivation config** in the menu.
2. Pick a step (for example BusinessConcept) and edit its instruction or example; extraction steps also have their input sources and params. Every LLM step follows the same pattern: input, instruction, example.
3. Press **Save as new version**. Earlier versions stay in the history (**Use this version** there brings one back as a new version), and each step can be switched on or off.

Run the repository again to see the effect.

## Going further

- [Architecture](architecture.md): how Deriva is put together, and where its data lives.
- [ArchiMate](archimate.md): the elements and relationships Deriva derives, and where it finds them in code.
- [Benchmarking](benchmarks.md) and [Optimization](optimization.md): measure how consistent runs are, and improve the model.
- [Contribute](contributing.md): the development setup.
- [Issues](https://github.com/StevenBtw/Deriva/issues): questions, bugs and ideas.
