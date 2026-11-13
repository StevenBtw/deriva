# Data and queries

Where Deriva keeps its graphs and models, how to check an extraction, and how to query the graph.

## Storage

- **Grafeo** (embedded graph database):
  - **Graph namespace**: the intermediate graph (directories, files, types, methods, dependencies, technologies, business concepts)
  - **Model namespace**: the output graph (ArchiMate elements and relationships)
- **DuckDB** (`sql.db` in your home folder; in a source checkout `deriva/adapters/database/sql.db`): step configurations with their versions, file types, name patterns and settings; created on first use from the shipped defaults

## Managing data

Each repository has its own graph database (`workspace/graphs/<repository>.grafeo`) with its graph and its model.

- **Repositories page**: **Clear model** (the graph stays; the next derivation builds the model again), **Clear graph and model** (the next extraction starts from nothing), **Update clone**, and **Delete** with or without its graph and model
- **Runs & storage page**: delete runs (one, the interrupted ones, or all past the latest N), clear the LLM cache (the next runs call the LLM again, and answers can differ from the cached ones), delete exported models, and delete a graph database whose repository is gone
- **CLI**: `deriva-cli clear graph|model --repo <name>`, `deriva-cli repo update <name>`, `deriva-cli repo delete <name> --with-data`, `deriva-cli repo register [name]` (records a git folder in the workspace that has no record)

These actions wait for a run to end.

## Checking an extraction

The Repositories page's **Coverage** section (and `deriva-cli coverage --repo <name>`, with `--json` for every file) compares a repository's checkout with its graph: how many files reached the graph, per extension which step reads them for types and methods and how many gave some, and the files that could not be read with the reason. An extraction is **incomplete** when files did not reach the graph, could not be read, or when not one source file gave a type or method; source files no step reads (shell scripts, say) are listed as notes. The run's **Errors** tab lists the errors of every step, also the files a completed step could not read, with a download of the whole list.

The model panel's **Quality** pill (and `deriva-cli quality --repo <name>`, with `--json`) judges a derived model from its structure. A model is **weak** when more than a quarter of its elements have no relationship, when more than that same share of its business elements at the enterprise level connect to nothing there, when nearly all relationships are Composition or Aggregation, when the Application or Technology layer is empty, or when elements have no file, type or method behind their sources (a component derived from a folder that holds no source file). The thresholds are the settings `quality_max_orphan_share` and `quality_max_structural_share` (`deriva-cli config setting set`). The verdict is a report; it changes nothing in the model.

## Querying the graph

In the Workspace's Separate view, each graph panel has a query bar that runs read-only queries against the embedded Grafeo database, in ISO GQL by default (the bar's settings switch it to Cypher). A few to start with:

```gql
-- All repositories
MATCH (r:Graph:Repository) RETURN r.repoName, r.url

-- The files of one repository, with their type
MATCH (repo:Graph:Repository)-[:`Graph:CONTAINS`]->{1,}(f:Graph:File)
WHERE repo.repoName = 'my-repo'
RETURN f.filePath, f.fileType

-- Type definitions
MATCH (td:Graph:TypeDefinition) RETURN td.typeName, td.category, td.filePath
```

Deriva itself queries in GQL too; `GRAFEO_QUERY_LANGUAGE=cypher` in `.env` switches its own queries to Cypher.
