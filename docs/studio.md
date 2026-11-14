# Studio

Deriva Studio is the local web interface: run the pipeline, follow it live and read the model.

The studio is Deriva's local web UI (`deriva`): a FastAPI backend over `PipelineSession` and a React front end.

| Area | Purpose |
|------|---------|
| **Workspace** | Run the pipeline (repository, scope, structural steps only), follow it live, see the repository, the intermediate graph and the output graph linked live in one canvas (or separately), open the ArchiMate model |
| **Repositories** | Clone, update (`git pull`), inspect and delete repositories; each repository's graph database with its counts, size and last runs, and Clear model or Clear graph and model |
| **General & file types** | System settings (excluded directories) and the file type registry |
| **Runs & storage** | Every run the studio kept (filter, delete, keep the latest N) and what the workspace keeps on disk: LLM cache, exported models, graph databases (one whose repository is gone can go), benchmark sessions |
| **Intermediate / Output ontology** | Every node type and element type with its count and the step that produces it, the edge and relationship types, and the matrix of what connects to what |
| **Extraction / Derivation config** | Step tables with versions; edit instructions and examples, save as a new version, switch steps on or off |

The graphs use [anywidget-graph](https://github.com/GrafeoDB/anywidget-graph) (its query bar runs read-only GQL or Cypher against the embedded databases) and the model uses [anywidget-archimate](https://github.com/StevenBtw/anywidget-archimate). While a CLI run holds the databases, the studio says so and shows what it can.

For front-end development, run `uv run deriva` and, in `studio/`, `npm run dev` (Vite forwards the API to port 8765, or to `DERIVA_STUDIO_API` for a studio on another port), then open the printed launch link with the dev server's address (`http://localhost:5173/api/auth?token=...`); `npm test`, `npm run lint` and `npm run typecheck` check it.
