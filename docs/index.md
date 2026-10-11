# Deriva documentation

Deriva reads a code repository and builds an ArchiMate model of its architecture. These pages explain the model it builds, how to measure and tune it, and how Deriva itself is put together; installation and first steps are in the [guide](https://deriva.dev/guide/).

- [ArchiMate](archimate.md): the elements and relationships Deriva derives, and where it finds them in code
- [Benchmarking](benchmarks.md): repeat runs, measure consistency and find the steps that vary
- [Optimization](optimization.md): change prompts and step settings so the model improves on any repository
- [Architecture](architecture.md): the layers, the pipeline and where data is stored

Commands are shown as `deriva-cli ...`, as the PyPI packages install them. From a source checkout, put `uv run` in front of them.
