# Changelog

All notable changes to Deriva, which derives ArchiMate models from code with knowledge graphs, heuristics and LLMs: a record of architectural decisions, resets, and a lot of trial and error.

## [0.9.0] - Unreleased

Hardening release: Deriva is safe to run on untrusted repositories, the bugs found since 0.8.10 are fixed, and the default configuration covers more kinds of repositories (Go, TypeScript, .NET, gRPC). Some changes alter derived models; use 0.8.10 for its exact output. Changes to the shipped configuration reach a new database; an existing one keeps its versions until they are updated.

### Security

- **Links stay inside the repository**: every repository walk and file read skips symlinks and Windows junctions, so a link to a file outside the clone (`.env` with provider keys, SSH keys) is never read, stored or sent to an LLM. Clones check symlinks out as plain files.
- **Git runs locked down**: clones, pulls and remote checks allow only the https, http, ssh and git protocols (submodules too), git gets no provider variables or API keys, and a clone stops after `DERIVA_GIT_TIMEOUT` seconds (default 1800). Submodules are cloned unless `repo clone --no-submodules` or `submodules: false` is given; a `file://` URL works from the command line only.
- **Cloning refuses two more git attacks**: no bundle a server advertises is fetched (`transfer.bundleURI=false`), and a git older than the July 2025 submodule fixes clones without submodules, checked before the clone. On such a git, repositories with submodules lose that content until git is updated.
- **The studio answers only its own launch**: each start prints a launch link with a fresh token that sets an HttpOnly, SameSite=Strict cookie, which every server path requires (scripts send `X-Deriva-Token`). A local studio answers only to its local host names, and a state-changing request from another site is refused.
- **A remote studio needs TLS**: `--allow-remote` requires `--tls-cert` and `--tls-key` and serves HTTPS with a Secure cookie. Bound to `0.0.0.0`, the launch link names the machine.
- **Another site's cookie cannot take the studio down**: a same-host cookie with an illegal name no longer makes every request fail.
- **The model diagram renders names as text**: anywidget-archimate 0.5.1 renders element names, documentation and properties as text, so a hostile name cannot run script in the studio. It also draws elements without a type, has every ArchiMate 3.2 notation icon and scrolls a long filter panel.
- **The graph views render names as text**: anywidget-graph 0.5.2 renders node names, keys and values as text. Its query box connects on the first query, draws at most 300 nodes of a typed query (the best connected) and explains a result with nothing to draw.
- **The query view runs only read-only procedures**: a procedure outside grafeo's read-only list is refused however its name is written, and so is `LOAD CSV`. grafeo's load procedures read local files, even in a rolled-back query.
- **The query bar cannot end its transaction**: grafeo 0.6.1 refuses `COMMIT`, `ROLLBACK` and `START TRANSACTION` inside the always rolled-back transaction of a typed query. Before, a GQL `COMMIT` kept the query's writes.
- **Limits on reading and on LLM calls**: extraction skips files above `max_read_bytes` (default 50 MB, reported per file), and a run makes at most `max_llm_calls_per_run` LLM calls (default 2000). Both are system settings.
- **Hostile documents are bounded**: a `.docx` that unpacks to more than 100 MB is skipped, and a PDF is read up to 2000 pages, 20 million characters and 100 MB of unpacked page content (pypdf 7.0 caps each stream). A document cut or refused at a limit says so in the log.
- **Snippet lines are capped**: a type's snippet keeps at most `max_snippet_line_chars` characters per line (default 2000), so a minified one-line file can no longer fill the disk with snippets. Files are split once for all their types, and title separators no longer take quadratic time on long runs of spaces.
- **Metadata extraction takes a folder name only**: like every other repository command.

### Extraction

- **TypeScript is parsed as TypeScript**: `.ts` files use the TypeScript grammar and `.tsx` the TSX grammar, so abstract classes, interfaces, type aliases, enums, decorators, typed parameters, return types and exported arrow functions are kept. `.tsx`, `.mts`, `.cts`, `.jsx`, `.mjs` and `.cjs` are source files, also in existing databases. *Changes models of TypeScript and React repositories.*
- **Go is parsed**: tree-sitter reads Go types, methods with their receiver (also across the files of a package), imports and calls instead of the LLM, and an import of the repository's own module reaches its files through go.mod (Method v2). *Changes models of Go repositories.*
- **go.mod dependencies are declared**: the require lines of each go.mod are declared dependencies, so an import of a required module or one of its packages is that dependency. One id rule names a dependency from a manifest or an import, so a name with a dot or slash is no longer two nodes.
- **Script imports name their package**: a JavaScript or TypeScript sub-path import is its package (`aws-cdk-lib/aws-s3` is `aws-cdk-lib`) and `node:` imports are the standard library. Aliases from tsconfig, jsconfig, vite, webpack or vue configs reach the repository file they lead to.
- **C# imports reach files**: a `using` of a namespace the repository declares links to that namespace's files whose types the file names, instead of counting as an external package. *Changes models of C# repositories.*
- **.NET solutions have structure**: a `.csproj` is a build manifest, and one with the web or worker SDK or an executable output is a deployable unit. Folders that repeat one layout across features are one module each. *Changes models of .NET repositories.*
- **.NET Framework web projects are web units**: a project whose ProjectTypeGuids mark a web application or web site is an entry point, also with OutputType Library. *Changes models of .NET repositories.*
- **.NET Aspire app hosts are environments**: each project an app host adds deploys its unit, listed technology resources are system software serving the projects that reference them, and the host is a Container Platform node (Deployment v2, `aspire`). *Changes models of repositories with an Aspire app host.*
- **System software is named after what an image runs**: an image off the technology list becomes the system its Technology label names, or the listed technology inside that name ("Apache Kafka" is Kafka); an image labelled none is no software. The labels stay on the repository node (`imageLabels`) for a Deployment rerun. *Changes models of repositories that run such images.*
- **Tooling is no part of the product**: one closed LLM call per repository labels each deployable unit as product or tooling (build, orchestration, deployment, seeding, load, tests, monitoring), and a tooling unit gives no component, function or artifact. The unit at the repository root is never asked. *Changes models.*
- **Unit names read like the product's**: the README's first heading is the product title only when it is the only top-level heading or shares a word with the repository or manifest name, and a `.csproj` unit takes its AssemblyName. Glued names (`shopapi`) are split and identifier-style titles are cased like folder names. *Changes models.*
- **Units are found by their manifest name**: a deployment that names a unit's manifest deploys that unit, and a Kubernetes image named like one of the repository's modules is no technology. *Changes models.*
- **Test code and event-sourced roots are no data entities**: a type below a folder named with a test word is test code, and a type named like an event-sourced root marker is the marker; a root another type extends stays a root. *Changes models.*
- **Fewer generic words as business behaviour**: the concept classifier (BusinessConcept v2) rejects general activity words, software method vocabulary and work on the project itself, and asks whether a term would mean the same in another business. Over three runs on eleven repositories about half as many such words are kept and labels vary less; models change only through the steps that read concepts.
- **Enum states in any naming style**: an enum's constants are its states in any case (C# `Submitted = 1` too), its constructor arguments and attributes are left out, and Kotlin's `enum class` counts.
- **Status types join their domain (experimental, BusinessLayer `status_members`, off by default)**: a status type named after a member plus a status word, declared in a member's file or kept in a member's folder joins that member's business domain, so its lifecycle is found.
- **Process names from what happens to the object (experimental, BusinessLayer `verb_names`, off by default)**: a lifecycle offers `<Verb> <Object>` for each past-participle state ("Approved" gives "Approve") and `Manage <Object>` as name candidates.
- **`.markdown` is documentation**: such files are read and split like `.md`; existing databases get the file type through a migration.
- **Step warnings reach the run**: what a step reports as a warning (directories not classified, no documents, a switch it could not apply) is in the run's warnings, also in the studio.

### Derivation

- **The metamodel holds the ArchiMate core**: all 35 core element types of ArchiMate 3.2 with their full direct and derived relationship table, matching Archi cell by cell (strategy, motivation, physical, Grouping and Location stay out). Derived models do not change.
- **Every core type has a step (experimental, off by default)**: the 18 core types without a step get a disabled one that keeps or rejects broad graph candidates per batch and draws the type's direct relationships. Switch one on in the Output ontology page or with `config enable`; these first versions are rough.
- **The LLM's role is measured**: against a run whose LLM answers are all empty, the LLM changes the model in five decisions: it adds the actors the documentation names, groups components into applications, gives entry points their interface role, names a service's object among structural candidates, and leaves tooling units out. Where an image is off the closed list of technologies, its label also names the software it runs. Identities and relationships come from structure: the same LLM answers give the same model.
- **Known variance between runs**: the grouping into applications can leave a component out of its application, which moves it and its relationships in or out of the enterprise level, and a service's object can differ where several candidates fit a component about equally, which renames the service under the same identifier. The solution level depends on neither and was identical in three uncached runs of each measured repository.
- **gRPC services are interfaces**: a source file that registers a gRPC server (Go, Python, C#, Java, Node) is an RPC interface of its unit with the registered services as members, without an LLM call (ApplicationInterface v4, `roles.registrations`). `.proto` files are a schema file type, also in existing databases. *Changes models of gRPC repositories.*
- **Service names are chosen from structure**: with `component_services.verb_choice` the LLM picks a service's object among structural candidates ranked by how much of the component each covers, and the verb stays structural. A choice equal to a sibling's structural name falls back to the service's own. *Changes models.*
- **Service names are shorter**: a word the stem already holds is written once and the verb stays ("Order History Order Management" becomes "Order History Management"); leading stem words that spell the repository's name do not count. *Changes models.*
- **Technology functions are named by what they do**: a technology function takes its realizer kind's activity from a closed table (TechnologyFunction v3), such as "Store and Query Data" or "Route Messages", with the realizer in brackets when two would share a name. *Changes models.*
- **Actors are judged by their evidence**: each documentation actor candidate comes with the sentence that names it (`documentation_actors.evidence_chars`), and generic words for people (`documentation_actors.generic_actors`) are no candidates. Actors such as People, User or a demo login no longer appear, and actors agree between runs on more repositories. *Changes models.*
- **Documentation is read as prose**: grouping, actors and component documentation skip fenced code, an underscore inside a word keeps it one word, and the root README's line names a component only as a whole word.
- **Grouping without documentation makes no call**: when the grouping prompt would show neither an introduction nor a README title, structure decides (`application_grouping.without_documentation`, "title" as shipped), so the grouping no longer varies there.
- **Combined runs decide per repository**: application grouping and documentation actors are decided per repository, so one repository's system component no longer switches grouping off for the others.
- **Combined runs keep their repositories apart**: element identifiers in a multi-repository run carry the repository (`ac_shop__frontend`), so two repositories' parts of one name stay two elements; single-repository identifiers are unchanged. An element that would replace one from another source is logged.
- **Libraries serve their users**: a library module serves the modules and units that import it (Serving) instead of being aggregated by them. Relationship recall and precision rise by 6 to 15 points on the development references with shared libraries. *Changes models.*
- **The enterprise view connects the business layer**: a system serves the actors its services serve and accesses the business objects its data objects realize, the second through potential derivation rule PDR 5 for this view only. *Changes models.*
- **Aggregate roots by marker interface**: a class implementing `IAggregateRoot` is a data entity; an interface extending it is not. *Changes models.*
- **Relationship identifiers come from the relationship**: an identifier is a hash of type, ends and origin, so it is the same in every run and the last tie-break of joint selection is deterministic. Exported models are unchanged.
- **Joint selection keeps one relationship per pair under two merges**: two merges that join both ends of two relationships no longer leave both on one pair. Without merge candidates (every run so far) the model is unchanged.
- **The quality report names floating business elements**: business elements that connect to nothing at the enterprise level make a model weak above the orphan share, and the reason names them. Other layers, roles and a level with one element may stand alone.

### Studio

- **Choose what to derive**: the Output ontology page selects the part of ArchiMate to derive by layer, aspect and type. A type's switch covers every step that makes it, and a selected type says when it needs one that is off.
- **Run limits on the General page**: it sets the largest file extraction reads and the LLM calls a run may make, or restores their defaults.
- **Views load on demand**: each page and the config editor are their own chunk, so the first load drops from about 1 MB to under 300 kB of JavaScript. A page shows a loading line meanwhile and says so when it fails to load.

### CLI

- **`deriva-cli nlp fetch`**: downloads the BusinessConcept step's pinned language models (about 300 MB on disk) for a machine that runs offline later. The README states sizes and hosts, and `THIRD_PARTY_NOTICES.md` lists each model with its SHA-256 and licence.

### Benchmark

- **Consistency per level**: `benchmark analyze` reports consistency by id for the solution level (direct relationships), the enterprise level and the whole model, also in `analysis/summary.json` (`consistency_levels`).
- **The gate's consistency budget**: `benchmark gate` requires consistency by id of 90% for elements and 80% for relationships, each on its own, instead of 95% for both.
- **The gate shows naming apart**: `benchmark gate` adds element recall and precision by name alone and a per-type table of reference, found, found by name and derived elements; the verdict is unchanged.
- **Empty sets are n/a everywhere**: with nothing to compare (fewer than two runs, or nothing in any run), every consistency measure reports n/a and leaves it out of averages. Before, some counted it as 100% and some as 0%.
- **Event-log relationship ids are unambiguous**: an edge or relationship in the run log is `Type|source|target`, as the old `Type_source_target` could give two pairs one id. Older logs keep their types; their structural stability is n/a.

### Configuration

- **GQL is the query language**: every graph query runs in ISO GQL by default and `GRAFEO_QUERY_LANGUAGE=cypher` switches back; a grafeo build without the chosen language is refused before a database opens. Every query gives the same rows in both languages on the development repositories, and derived models do not change.
- **One setting for the answers per decision**: `llm_samples` (1 to 20, on the General page or with `config setting set llm_samples 3`) overrides every voting step's `samples` until `config setting unset`. Sessions record it; above 1 the answers are combined by majority, so measure consistency with 1.
- **`config add --llm`**: a new derivation step can be added as an LLM step (still disabled until `config enable`); without the flag it stays structural.
- **`.env.example` starts local and repeatable**: the default model is a local Ollama model at temperature 0, provider keys are commented out (a placeholder was sent as a key), and the example models and token limits are current.
- **The shipped file types name no repository's documents**: three exclusions of one benchmark repository's reference-model documents left the seed; a database that has them keeps them. Every session records its file types in `session_inputs.json`.

### Fixes

- **A second extraction gives the same graph**: the import step treats only declared manifest packages as external, as a first run does. Before, a repeated `run extraction` or `run all` turned the repository's own imports into external ones (114 import edges lost on Deriva's own repository); benchmarks were not affected.
- **Running without a model**: `run all` with no LLM model runs as `--no-llm` does instead of failing in the LLM steps, and the missing-model message names what to set. The summary reads "PIPELINE FAILED" when the run failed.
- **The LLM cache keeps providers apart**: the cache key holds the provider and its base URL, so one model id served by two providers never shares answers. Existing entries are not reused: the first run after the upgrade calls the LLM again.
- **Sampling caches each answer**: a voting step numbers its answers and caches each one, so a cached run votes over the answers the run got; a single call keeps its cache key. Before, every sample read one cached answer.
- **A missing checkout leaves the graph alone**: a repository whose folder is gone or lists no file runs no extraction step and fails with a message naming the folder. Before, the later steps swept their output and the graph kept only what the first steps rebuilt.
- **Architecture models are never an input**: an `.xml` file in the ArchiMate exchange format is excluded like a `.archimate` file, so a model shipped with a repository never feeds the model derived from it. Such files change type, and so does the classification prompt of their folder.
- **A library repository is modelled**: a repository whose only units are examples or tests keeps its own module as its component, and test or example code is recognised by its own folder and manifest name or an exact test-word folder above it. *Changes models of such repositories.*
- **Compose builds from the repository root find their unit**: a service with `context: .` and a `dockerfile` in a subfolder deploys the unit in that folder, and its image name is no longer system software. *Changes models of such repositories.*
- **Combined runs strip the first repository's name**: the repository whose name is stripped from element names is the first by name, not whichever a query returned first.
- **Answer stability with `--bench-hash`**: answer stability keys a prompt by everything the call sent except its benchmark run, so `--bench-hash` sessions no longer report 0 of 0 prompts.
- **Analysis counts what it says**: the two-level tables pool a model's runs over sessions (one row per model), and structure-named application services no longer count as LLM-dependent in the origin split.
- **Studio run consistency by source**: relationships are keyed by the type and source of both ends, so a component's and its function's relationships no longer collapse into one. The studio's numbers now equal `benchmark analyze`'s.
- **The graph widget finds the schema**: the studio answers the schema request at `/grafeo/db/<name>/schema` too, and query results come in grafeo-server's shape, so the widget's query box connects and draws them.
- **Local clones are named after their folder**: `repo clone file:///.../name/.git` clones into `name`, and a working tree's URL without `.git` is accepted.
- **The run summary counts honestly**: extraction reports "Nodes written" followed by the graph's distinct nodes, as `deriva-cli status` counts them.
- **Repository errors are said once**: `repo delete` and `repo info` print one error for an unknown repository.
- **One-line command summaries**: every command's summary in `--help` is one line.
- **The live log names the phase it closes**: "✓ derivation (30/30)".
- **Runs from outside the studio are named**: the Repositories page says "run outside the studio" when a repository holds a graph or model the studio did not record.
- **No polling during a run**: the run panel stops reloading repositories and the session while a run holds them.
- **Refine says what changed**: "Refine: 4 flagged, 2 disabled, 1 merged", or that nothing changed.
- **Cache hits in the LLM call list**: a cached call shows "cache hit" instead of zero tokens and latency.
- **The LLM cache shows what it holds**: the Runs & storage page gives the number of cached answers and their size, not the size of the lmdb map file (2 GB on disk, mostly unused). A cache file lmdb cannot read is measured by its files.
- **Coverage names each file type**: the coverage table on the Repositories page and in `deriva-cli coverage` lists each extension's file types with their files ("test 236, source 220"), and its "Parsed by" column stays empty for documentation and assets instead of saying `none`. An extension with source files that no step reads says `none`.
- **An open page notices a stopped studio**: while the studio does not answer, the page says so and asks again less and less often (up to once a minute), instead of every 10 seconds without end. An expired launch token stops the polling and shows the launch-link page.
- **One warning per missing model**: a model that cannot be loaded is reported once per reason, not again inside a run.

### Dependencies

- **grafeo 0.6.1** (requires `>=0.6.1`): models are identical and derivation's graph queries take about a third less time; a run as a whole takes about the same. Graph files written by 0.6.1 still open in 0.6.0.
- **Every runtime requirement has an upper bound**: each requirement of the three packages is pinned or bounded below its next breaking release (`pydantic>=2.14.3,<3`, `grafeo>=0.6.1,<0.7`), so an installed tool, which resolves without the lockfile, does not pick up a breaking release. A test checks every published wheel.
- **Dependencies at their latest**: pydantic 2.14.3, pypdf 7.0, typer 0.28, ruff 0.17.4 and ty 0.0.99; the business concept translation stack moves to CTranslate2 4.8.5 and sentencepiece 0.2.3.

### Development

- **Version 0.9.0 for all three packages**: deriva-cli, deriva-studio and deriva-dev move together (the studio and dev packages pin the release beside them), and the studio front end reports 0.9.0.
- **ty checks the whole repository**: CI and the pre-commit hook run `ty check .`, tests included.

## [0.8.10] - 2026-10-26

Reproducible benchmark input release: the shipped configuration carries every input exclusion the final benchmark used, so a fresh install reads the same files as the benchmark did. The pipeline code is unchanged from 0.8.9.

### Configuration

- **Reference-model documents are excluded on a fresh install**: the shipped file types exclude the documents that describe a benchmark's reference model, both where extraction and where the B1 baseline look for them. Every step still ships at version 1.

## [0.8.9] - 2026-10-26

Reference scoring release: a reference written in ArchiMate 2 names is read with its ArchiMate 3 types, and final derivable labels set the scope. The pipeline is unchanged from 0.8.8.

### Benchmark

- **Reference models in ArchiMate 2 names are scored**: Archi files with ArchiMate 2 names (InfrastructureService, CommunicationPath, UsedBy and the like) are read as their ArchiMate 3 types, so their technology services count and their relationships can match. The scoring calls `parse_archi_xml(path, archimate3=True)`; without the flag the parser keeps the file's own types.
- **Final derivable labels set the golden scope**: the gate scores a golden model on the elements labelled derivable as soon as that file is final, even while the accepted names are still a template. The row then says the matches are provisional (`matches_provisional`).

## [0.8.8] - 2026-10-26

ArchiMate metamodel conformance release: only relationships an ArchiMate 3.2 figure draws are direct, the enterprise level is a viewpoint derived through the valid derivation rules, and the application and technology layers gain functions, artifacts and technology services from structure. Most naming calls are gone, the remaining LLM calls are closed choices asked once, and every step ships at version 1. Derived models change.

### Extraction

- **Serverless functions and static frontends are units**: an `(event, context)` handler and an `index.html` outside every unit are deployable units, a package with several project scripts is one unit, and a front-end module built into a unit's folder gives that unit its web UI. A unit offers one application interface, named after its main channel (`roles.one_per_unit`). *Changes models.*
- **Build modules are classed by who uses them**: a module two or more units use is a shared library, and a component only when it carries behaviour (`min_behaviour`). A development-only package gives no component, and feature packages (each with a route handler and a data entity) split a unit (`feature_markers`). *Changes models.*
- **The primary environment runs the repository's units**: it is the one that runs the repository's own units (`primary_runs_units`), preferring Compose's default file names (`compose_defaults`). A unit that only a variant file deploys is no component, and `.devcontainer` is excluded. *Changes models.*
- **Declared persistent classes are entities**: a class with an entity annotation, an aggregate root or an ORM base is an entity whatever its name; aggregates are scoped to the root's folder and join tables are no entities. An ORM entity records its table (`table_attributes`), so a query naming that table reaches it. *Changes models.*
- **Dockerfiles give import roots**: a folder a Dockerfile copies onto `PYTHONPATH`, `NODE_PATH` or `CLASSPATH` resolves bare imports that nothing else resolves.
- **Units take their project's own name**: a Maven unit takes the project's `<name>` (never a license's, nor one with an unresolved `${...}`), an aggregator its folder's name and a static frontend the name of the module that ships it. `Impl` is dropped from entity names. *Changes models.*

### Derivation

- **Direct relationships follow the metamodel figures**: a relationship is direct only where an ArchiMate 3.2 figure draws it (layer, cross-layer and same-type figures), else derived. Storing a relationship checks the relationship table, so no step can write one the metamodel does not allow. *Changes models.*
- **Five more element types are derived**: ApplicationFunction, Artifact (until now only the export's detail level), BusinessRole, BusinessService and TechnologyFunction. The views, the convention checks and the B1 baseline's output types include them. *Changes models.*
- **Structure decides most elements**: components and their names (`naming.source_order`), services (`<object> <verb>`, `service_verbs`), one data object per entity, one application function per unit, library or feature package, one artifact per deployable, one platform node per environment and business roles all come from structure, without an LLM call. *Changes models.*
- **The technology layer gains functions and services**: the platform node and each service the closed kind table names get a technology function and a technology service ("Container Hosting", "Relational Database") that serves the application functions of the units it runs. A runtime is assigned to the artifacts it runs, and service software a unit embeds is realized by the unit's artifact. *Changes models.*
- **Relationships rest on structure**: none come from names in code (`named_in_code` is empty), libraries are aggregated by their users, and an application function accesses the data objects of the entities its own files declare. A service name two components share is qualified by its component. *Changes models.*
- **The enterprise viewpoint is derived**: its relationships come from a versioned pattern table (`enterprise_patterns`), each drawn only where ArchiMate's valid derivation rules derive it from the direct relationships below, with its chain recorded (`derivedFrom`, `derivationRules`). Edge technology services stay at the solution level. *Changes models.*
- **Documentation steps ask once**: one closed LLM call per repository groups the top-level components into the applications the README names (`ApplicationGrouping`), and one chooses which documented business actors each application serves (`DocumentationActors`). Majority voting over three answers made no choice more stable, so every closed choice is asked once.
- **Fewer business elements come from data**: no business function per data domain, and no business process or event from a status lifecycle (a process needs a human actor). *Changes models.*

### Export

- **Schema locations follow the standard's examples**: `xsi:schemaLocation` names the diagram schema (the export carries views) and the Dublin Core schema of the metadata.

### Benchmark

- **Derived reference relationships count as found**: a reference relationship counts when the valid derivation rules derive it from a chain of the model's direct relationships (only drawn ones count for external systems). Behaviour matches within its layer, and elements derived from a reference's lineage map one to one.
- **The B1 baseline reads what extraction reads**: it leaves out the files the file-type registry excludes, and takes build and source files in turn within its character budget.
- **Session reports show samples and the joint selection**: samples and re-asks per LLM step (`llm_samples`, `llm_reasks`; a re-asked decision is stable only when every run answered it alike), the joint selection's variables and constraints per run and model, and an "all LLMs" row for answer and decision stability.

### Configuration

- **Every step starts at version 1**: `config reset-versions --yes` makes each active row version 1 and removes the history (it stays in the older releases), so the shipped defaults match the active configuration again. `config update derivation <step> --llm/--no-llm` sets whether a step calls the LLM.

### Fixes

- **A re-ask reaches the model**: an answer without JSON where a schema was asked for is no longer cached, and one already in the cache counts as a miss. A step that asks again gets a new answer instead of the same unusable one.

## [0.8.7] - 2026-10-24

Database upgrade release: grafeo 0.6.0 for the graphs and DuckDB 2.0 for the configs, both new major releases. Models are the same, derivation is faster, and installs no longer need a pre-release.

### Dependencies

- **grafeo 0.6.0** (requires `>=0.6.0`, the stable release instead of the 0.6.0b1 preview): models are identical, and derivation's graph queries take less than half the time (50 times faster than on Neo4j). Graph files are upgraded on their first open, after which Deriva 0.8.6 or older cannot open them.
- **DuckDB 2.0** (requires `>=2`) for the config database: an existing database keeps its storage format, so an earlier Deriva (on DuckDB 1.5) still opens it and every config, version and setting reads as before.
- **Other dependencies at their latest**: among them anthropic 2.2, pydantic-ai 2.60, openai 3.37, FastAPI 0.162 and httpx2 2.16, and Vite 8.3.5 for the studio's build.

### Development

- **No pre-release requirements**: a test reads the built wheels and fails when a runtime requirement names a pre-release. uv does not install one for a dependency and fell back to the empty 0.0.1 placeholder of the package.

## [0.8.6] - 2026-10-20

Trace and dimming fix release: two fixes found while taking the 0.8.5 screenshots.

### Fixes

- **Trace works after a benchmark**: with a benchmark as the run shown in the workspace, the Trace tab shows the selected element's sources and relationships instead of "Unknown run". It lists no LLM calls, since a benchmark keeps them in its session; a run the studio does not know is still refused.

### Dependencies

- **anywidget-graph 0.4.6** (deriva-studio requires `>=0.4.6`): a selection dims the other types and edges of the ontology graph so they stay visible on a light canvas too.

## [0.8.5] - 2026-10-20

Ontology graph and honest counters release: the intermediate ontology is a graph again (anywidget-graph 0.4.5), the graph views' size is a setting, and the run summary, the step counter, the ontology's readers and the benchmark inspector report what is there.

### Studio

- **The intermediate ontology is a graph again**: every node type is a node sized by its count and coloured by its group, and edge types are arrows (a loop for a type to itself), placed the same way every time. Selecting a type lights its neighbours and opens its description, producing and reading steps, edges, properties and a sample node; group, empty-type and edge-type filters hold in the Graph, Matrix and Cards views.
- **Graph view size is a setting**: the General page sets how many nodes the Workspace and Benchmark graph views sample (50 to 5,000, 300 until set; the model is always shown whole). On the CLI, `config setting set graph_view_nodes <count>`.

### Fixes

- **The derivation summary counts the model**: the line that closes a derivation says how many elements and relationships the model holds, as the Repositories page counts them. It added up only the generate and relationship steps, so refine relationships were missing (40 where the model had 46).
- **Ontology pages find every step that reads a type**: a candidate query that tests a node's labels (`"BusinessConcept" IN labels(n)`) counts as reading that type, as `n:Graph:BusinessConcept` does.
- **The step counter includes the deferred relationship pass**: the live log no longer counts past the step total (25/24).
- **Benchmark inspector groups say what differs**: an element whose name differs between runs, or that some runs lack, goes under "name differs" or "not in every run" instead of "other". The header says what the elements are matched by ("3 of 51 elements differ, matched by source").

### Dependencies

- **anywidget-graph 0.4.5** (deriva-studio requires `>=0.4.5`): arrows, self-loops, neighbour highlight and the `preset` layout for the ontology graph.

## [0.8.4] - 2026-10-19

Studio management and field fix release: the studio manages what a workspace keeps (repositories, graph databases, runs, benchmark sessions, storage), and a test on a large repository led to fixes in cloning, long paths and cut LLM answers. Two read-only reports are new: extraction coverage and model quality.

### Security

- **Credentials in URLs stay out of output**: the user and token part of a URL (`https://user:token@host/...`) is removed from git's errors, the URL checks' messages, the stored repository records and the CLI's output. Git still gets the URL as given.

### Studio

- **The Repositories page manages each graph database**: it shows what each repository's database holds and its last runs, with **Clear model**, **Clear graph and model** and **Update clone** (`git pull --ff-only`, refused with uncommitted changes), and **Delete** can take the graph and model along. The actions wait for a run to end; on the CLI, `repo update <name>` and `repo delete <name> --with-data`.
- **Export downloads the model**: **Export XML** saves the exchange file in the browser as `<repository>-<yyyymmdd-hhmmss>.xml`. The copy in `workspace/output` keeps that name, so exports no longer overwrite one another in `model.xml`.
- **The Runs & storage page lists every run**: a page at a time, by repository and kind, and deletes a run with its live log, LLM calls and inputs, every interrupted run, or every run past the latest N. The run in progress always stays (`GET /api/runs/history`, `DELETE /api/runs/{id}`, `POST /api/runs/prune`).
- **The Runs & storage page shows storage**: disk use per area (LLM cache, exports, runs, benchmark sessions) and per graph database, with **Clear LLM cache**, **Delete exports** and **Delete** for a graph database without a repository. The actions wait for a run to end (`GET /api/storage` and its `DELETE` routes).
- **Benchmark sessions are searchable and deletable** (deriva-dev): the session list finds every session by text, repository, model and status, a page at a time, and deletes the selected ones or marks them failed. On the CLI, `benchmark delete <ids>` and `benchmark prune --keep N | --failed` (asks first unless `--yes`); running sessions always stay.
- **A config version can be restored**: **Use this version** in a step's History tab makes an earlier version's texts, queries, params and generation settings the step's new version, after the overfit scan; its place in the phase and its switch stay. On the CLI, `config restore <type> <name> <version>`.
- **The intermediate ontology looks like the output ontology**: every node type of the graph metamodel is listed in group cards with its count and the switches of the steps that produced it, also types without nodes. Edge types get short codes and show as a matrix; a type opens its description, properties, producing and reading steps and a sample.
- **Clone and delete say what happened**: the Repositories page reports clone progress and result (branch, commit, size), suggests the folder name a URL gives, and says what a delete removed and kept. Git's errors become a sentence a user can act on, with git's own line kept, and git no longer waits for a username on the studio's terminal.
- **A model config can be tested**: **Test** next to each model config (and `deriva-cli config model test <name>`) makes one small uncached call and says which model answered and how fast. A failure names what to fix: a refused key, a key without access, an unknown model id, a rate limit, an unreachable server or a timeout.
- **Extraction coverage is reported**: the Repositories page's Coverage section and `deriva-cli coverage --repo <name>` (`--json`) compare a checkout with its graph per extension and reading step, and list the files that could not be read with the reason. It only reads, and marks an extraction incomplete when files are missing or unreadable or no source file gave a type or method.
- **Every error of a run is listed**: the Errors tab also shows the errors of steps that completed, the first 50 with a download of the whole list. Read errors name the repository path and the system's reason instead of the absolute path.
- **Models get a quality verdict**: the model panel's Quality pill and `deriva-cli quality --repo <name>` (`--json`) call a model weak when over a quarter of its elements have no relationship, over 80% of its relationships are Composition or Aggregation, the Application or Technology layer is empty, or elements have no file, type or method behind them. The thresholds are `quality_max_orphan_share` and `quality_max_structural_share`, and the verdict changes nothing in the model (`GET /api/model/quality`).

### Fixes

- **Joint selection works outside a source checkout**: a relative `report_path` is now under the Deriva home folder and its folder is created, so an installed tool applies its merges, redirects and drops again. A report that cannot be written is logged without stopping the selection.
- **Unknown `--repo` names are refused**: `run`, `status`, `export`, `clear` and `graph tag-steps` list the known repositories and exit 1 instead of creating an empty graph database for the typo. `default` and the joined names of existing combined runs stay valid.
- **Cancelling a studio run stops the running step**: the session refuses every further LLM call of the run (`RunCancelled`), so a long step ends at its next call and the run ends as `cancelled`. A call already under way still finishes.
- **Stopping the studio during a run no longer hangs**: the first Ctrl+C or SIGTERM cancels the run and ends the open event streams, which the server used to wait for.
- **Interrupted runs stay in the history**: a run whose studio process ended first is listed as `interrupted`, with its kind, repository and times from its kept events. Its live log replays and ends with a note that the studio stopped.
- **Runs without an LLM count skipped steps**: with `--no-llm` an LLM-only extraction step counts under `Steps skipped` with its warning instead of "had errors", and keeps what an earlier run wrote. The `--no-llm` help says what runs: the extraction parsers and derivation's prep phase, so no elements.
- **`status` names its graph**: without `--repo` that is the shared `default` graph, with a hint to pass `--repo`.
- **Models that refuse a temperature get none**: a model config without `SAMPLING` follows the model as pydantic-ai knows it, so an Anthropic model without temperature (Claude Haiku 5.5) no longer warns on every call. An explicit `SAMPLING` still wins.
- **Local context windows are a setting**: a model config takes its context size (`LLM_{NAME}_CONTEXT`, `config model set --context N`), and a call that fills it is logged as a warning. Ollama cuts a longer prompt without an error (4096 tokens unless started with `OLLAMA_CONTEXT_LENGTH`).
- **Studio config and ontology pages read better**: the derivation config list heads each phase, a step without LLM calls opens on its params with no empty text editors, and the allowed-relationships matrix fits from 1280 pixels wide with abbreviated row labels.
- **The graph widget needs no CDN**: deriva-studio requires anywidget-graph 0.4.4, which bundles its graph libraries. With 0.4.3 the graphs failed with "Failed to fetch dynamically imported module" wherever esm.sh or cdn.jsdelivr.net could not be reached.
- **Azure's v1 API works**: a model URL on an Azure `/openai/v1/` endpoint goes through the OpenAI-compatible client without an `api_version`, which that API refuses. Other Azure URLs keep the versioned client.
- **"DB not connected" only when it is so**: when the studio does not answer a status request (a long step, a restart), the top bar says the studio is not answering and keeps the last known database state on hover.
- **Cloning no longer blocks the studio**: a clone holds no session, so other pages keep answering; a run still cannot start while a clone runs.
- **Failed clones leave nothing behind**: a clone goes into a staging folder and becomes the repository's folder only when it worked, so a retry with the same name works. A git folder without a record can be registered instead of cloned again (**Register**, `deriva-cli repo register [name]`).
- **Clones clean up on Windows**: removing a staging folder or a deleted clone uses Windows' extended path form, so files deeper than 260 characters no longer stop it. A git that Windows cannot start (`0xC0000142`) is reported as such, with what to try and without the repository URL.
- **Stale repository records show as stale**: a record whose folder is gone or is no git checkout shows the reason, Update is off for it, and Delete removes only the record, never files.
- **Deep paths on Windows are read**: extraction walks and reads the repository in Windows' extended path form (`\\?\C:\...`), so files deeper than 260 characters no longer fail with `WinError 3` or get skipped where long paths are off. Graph paths stay relative.
- **Opening a repository creates no graph database**: the counts for a repository without one are zero, and no empty database is made.
- **The LLM-not-configured message says what to set**: it names the variable (the config's `KEY_ENV` reference or its own `LLM_{NAME}_KEY`, never a value) and the `.env` this install reads, in the CLI, a derivation's error and the studio's run.
- **Answers cut at the output limit fail as cut**: a structured answer that reached the step's `max_tokens` fails as `IncompleteToolCall` (not cached, not retried as transient) instead of a shorter re-asked answer that could leave part of a batch unanswered. Directory classification then halves the batch until each answer fits, and reports directories whose answer alone does not fit as not classified.
- **Cut answers whose retries failed fail as cut too**: a run that holds a cut response fails as `IncompleteToolCall` also when pydantic-ai's retries raised "Exceeded maximum output retries", so directory classification splits that batch as well.
- **TLS drops are retried**: an `SSL EOF` or a connection reset is retried as a transient error, now pinned by tests.
- **Code parsers read classes correctly**: JavaScript and TypeScript no longer give an extra unnamed class per class (41 nameless TypeDefinition nodes in one graph) or an exported class twice, and read `extends`, class expression names and generator functions. Python class decorators and `type X = ...` aliases and C# return types are read; derived models stayed identical on three development repositories.

### Dependencies

- **Python and npm dependencies at their latest**: among them pydantic-ai-slim 2.57, httpx2 2.14, FastAPI 0.149, uvicorn 0.54, anywidget 0.11, pydantic 2.14 and ty 0.0.89, and the studio's npm packages within their ranges. Types follow the newer `ty` (`@contextmanager` functions return `Generator`).

### Development

- **Tests check the result**: 170 tests whose only checks were weak now assert exact values, calls and messages, and a rate limiter test no longer sleeps a minute, so the Python suite runs in about half the time. The tighter tests found the code parser bugs listed under Fixes.
- **TypeScript 7 type-checks the studio**: `npm run typecheck` (part of `npm run build`) runs on the native compiler. TypeScript 6 stays for `typescript-eslint`, which needs the TypeScript 6 API.

## [0.8.3] - 2026-10-18

Abstraction levels release: the model has two abstraction levels, enterprise and solution, built from structure without LLM calls, and the benchmark gate judges a change per level. Derived models change.

### Extraction

- **Build modules come from structure**: a new structural step `BuildModule` finds the folders with a build manifest and code of their own (`manifests`, `code_subtypes`), their nesting, and a parent system where an aggregator manifest lists at least two of them (Maven modules, npm, yarn or pnpm workspaces, uv workspace members, Gradle includes). A module that is the folder of exactly one unit is one structure with it.

### Derivation

- **Modules and libraries are components**: ApplicationComponent also takes the build modules and systems, named from structure after their manifest or folder, with a kind noun (`kind_nouns`) or path words where a name is taken. Modules for infrastructure as code (`iac_dependencies`), with only test dependencies (`test_dependencies`) or with a test word in their name (`test_words`) stay in the graph with their reason (`excluded`) but become no component. *Changes models.*
- **Libraries serve the modules that import them**: a module serves the module whose files import its files (a new `graph_links` rule). *Changes models.*
- **One model holds two levels**: every element and relationship carries its levels, enterprise (business layer, services, top-level components, the platform node) or solution (units, modules, libraries, interfaces, data objects, system software), from a versioned table per type (`roles` places one role on its own levels). A relationship is on the levels both ends share, else it is a cross-level link.
- **Components form a hierarchy**: roll-up Compositions follow system, units, modules and libraries, and only the hierarchy composes one component into another. The top-level component realizes the services of the units below it, so the enterprise level stands on its own. *Changes models.*
- **Every deployment is a service node**: a compose service, a cloud or Kubernetes workload or a ready-made image becomes a solution-level Node that serves the component of the unit it deploys. The environment Node composes them. *Changes models.*
- **Relationships are lifted to the enterprise level**: a Serving, Access, Flow or Triggering relationship below that level implies one between the nearest enterprise elements above its ends, and an Access to a data object reaches the business object it realizes. Each lift lists its sources (`liftedFrom`) and is on the enterprise level only. *Changes models.*
- **Nothing changes the model after the joint selection**: the hierarchy's relationships, removals and lifts come from a new step before it (`abstraction_hierarchy`), and `abstraction_levels` after it only writes the level tags. A refine step after the joint selection that adds or removes anything is an error of the run.
- **Data access goes through services**: GlobalRelationships v35 drops the two rules that let a component access a data object directly; a service of the component had the same access in 36 of 46 cases. Solution relationship precision rose on 5 of 6 development repositories, with recall unchanged. *Changes models.*

### Export

- **The exchange file carries levels**: an element's `level` property is its set of levels (`enterprise`, `solution`, `enterprise solution`; `detail` for members) instead of `architect`, relationships carry one too (`cross-level` without a shared level), and relationship ids come from the ends, type and level, so they are the same in every run. The files validate against the Open Group 3.1 schema and import into Archi.
- **Each level has its own views**: five enterprise views, four solution views and three detail views (Application Interfaces lists each interface's endpoints, pages or jobs), each showing only its level's elements and relationships. A cross-level link is in no view, and an empty view is left out.

### Studio

- **The studio shows each level**: enterprise, solution or detail, each with its own relationships and views as in the exchange file. A view draws only the relationships it holds.

### Benchmark

- **`benchmark gate` judges a change**: `deriva-cli benchmark gate --baseline <sessions> [--candidate <sessions>]` reports element and relationship recall, precision and consistency by id per repository and level against a development reference or a golden model's derivable subset. A level passes when one measure rises at least 1 point on two thirds of the repositories, none drops more than 2 points and consistency stays at 95% or more (`HELD` with too few gains); the change passes when no level fails and one passes.
- **Golden matches can name structure**: an accepted match can list `structure_refs` (`path:<folder or file>` or a structural id) next to names, so an unmatched golden element is found by the element derived from that structure. `benchmark analyze` and `benchmark gate` share this matching.
- **References carry levels**: a development reference tags its elements and relationships with `levels`, and the reference evaluation scores one level or all (`level`).
- **Run snapshots carry levels**: elements and relationships carry `levels` (and `cross_level`), and consistency by id is measured per level.
- **Chosen names keep their candidates**: an element named by a closed-set choice keeps its candidates in order (`name_candidates`) in the model and each run snapshot, with whether a call made the choice (`name_choice`).
- **Sessions record their commit**: `session_metadata.json` records the code commit a session started on and whether the working tree had changes (`code`: `commit`, `dirty`).
- **Event logs are complete and in order**: a refine step names the relationships it adds in the OCEL and case logs, and step durations are kept to the microsecond, so tools that order by start time no longer swap short steps.

### Configuration

- **Step order is versioned**: `config update derivation <step> --sequence N` moves a step within its phase as a new config version, and `config sequence` versions every step it moves.

### Fixes

- **Data entities are found when every service declares its own ORM base**: since 0.8.2 such repositories got no data entities and none of the elements built on them; a base class now resolves through its nearest definition. *Changes models.*
- **Images that name their service in the tag deploy it**: a deployment whose image carries the service in its tag or last name segment deploys the unit of that exact name or folder. *Changes models.*
- **Two cloud services of one name stay two**: they are no longer merged into one deployment. *Changes models.*
- **Names from documentation lists lose their separator**: a bold term, table cell or link label used as a component name no longer keeps the colon before its description ("Order Desk:"). *Changes models.*
- **The studio run history is current**: a run that has just ended is listed at once, a run of an earlier studio process replays its live log from `events.jsonl` instead of a 404, and a run without LLM calls lists none instead of failing.
- **The benchmark form starts on the default model**: it selects `LLM_DEFAULT_MODEL` instead of the first configured model.
- **Extraction reads a moved workspace**: it reads `REPOSITORY_WORKSPACE_DIR` as `repo list` does; with another folder it found no repositories.
- **CLI messages are clearer**: `run all` lists its errors, a config database held by the studio or another run gives one line instead of a traceback, `config update extraction --sequence` is refused, and the hints after `benchmark run` and an empty `repo list` name `deriva-cli`.

## [0.8.2] - 2026-10-17

Pre-benchmark refinement release: most of the model now comes from structure. New structural extraction steps find deployable units, data entities and domains, deployments, cooperation lines and lifecycles, and the LLM mainly chooses among structural candidates. Derived models change.

### Extraction

- **Deployable units are found**: a new structural step `DeployableUnit` finds what runs on its own (a folder with a container file and its own code, a manifest entry point, a mainframe application split into online and batch). A repository without any is one unit.
- **Data entities come from structure**: a new step `DataEntity` finds aggregate roots, ORM entities, shared mainframe records and DDL tables, and leaves out ids, value objects, DTOs, configuration and technical records with their reason. With `table_mentions` a table links to the code files that query it.
- **Entities are grouped into information domains**: a new step `DataDomain` groups an aggregate with its parts, an entity with its owner and a lookup with the domain that uses it.
- **Deployments come from structure**: a new step `Deployment` reads compose files, Kubernetes manifests, cloud templates and Dockerfiles; the primary environment (the cloud, else the root compose file, else Kubernetes) runs the services that deploy units, and a unit's runtime comes from its Dockerfile's `FROM` chain. Secret-looking variables and URL passwords are not stored.
- **System software comes from a closed list** (`technologies`): images, runtimes, managed services, manifest dependencies and content markers are matched to a versioned list where each alias names one technology. Mainframe subsystems make a mainframe environment.
- **AWS CDK apps are read without synth**: tree-sitter TypeScript reads them statically through a versioned construct table (`cdk_constructs`), from literal values and literal loops only.
- **Managed services name their engine** (`cloud_qualifiers`): for example `Amazon RDS for PostgreSQL`; an engine found through drivers merges into its managed service.
- **Cooperation comes from structure**: a new step `Cooperation` finds `CONSUMES` and `SENDS_TO` lines between units from endpoint URLs, message destinations, service catalogs, gateway routes and code edges. The provider's interface serves the consumer, and messages are a Flow.
- **The business layer comes from structure**: a new step `BusinessLayer` finds lifecycles (a status attribute with its states and transitions), the events that hand them on and the roles that act in them. They give a BusinessProcess per lifecycle, a BusinessEvent per hand-off and a BusinessActor per role.
- **Extraction steps can be re-run**: every node and edge carries the step and config version that wrote it, and after a clean run a step removes what it no longer produces. `graph tag-steps` tags an existing graph, and `--only-step` lists the later steps that may read its output.
- **SQL tables are read without an LLM**: from `CREATE TABLE` statements in `.sql` and `.ddl` files.

### Derivation

- **One component per deployable unit**: instead of one per module, package or folder. *Changes models.*
- **One interface per unit and channel**: REST API, Web UI, Commands, Messaging API, RPC API or Batch Jobs, with the endpoints, screens or jobs as its `members`. Page files give a Web UI interface without an LLM call. *Changes models.*
- **Services are grouped per component** (`component_services.group_by: "unit"`): members that extend one base type form one service and the others group by the data domain they reach, at most `max_per_component` per component and none for a pure front end. *Changes models.*
- **Business functions span components**: a business domain that the services of two or more cooperating components access becomes a business function. *Changes models.*
- **Names are chosen from a closed set**: component, service and function names come from structural and documentation candidates, and one call chooses only when there are several. Component names agree in 97% of runs (was 81%) with 10 naming calls per run instead of 36.
- **Relationships follow the units**: the relationship rules find a node's component through the units' members.
- **Name matching reads structure**: the name tier compares `structure_name`, never an LLM name (relationship consistency 89.7% to 95.2%).
- **One data object and one business object per domain**: a DataObject per domain and a BusinessObject per domain with a business anchor, which the data object realizes. Element and relationship consistency rose from 93.1% and 94.3% to 97.0% and 98.9%, with 346 LLM calls per session instead of 611. *Changes models.*
- **Nodes and system software need no LLM**: they come from the environment and the listed software, and TechnologyService and Device are switched off. The technology layer is identical in every run. *Changes models.*
- **Business functions can come from a process catalog**: `BusinessFunctionModel` classifies documentation against APQC PCF (notice in `THIRD_PARTY_NOTICES.md`); disabled by default.
- **The joint decision is the last refine step**: the MILP decides relationships and merges in a canonical order, with evidence tiers from a versioned table. Its solve report is in every run snapshot.
- **No confidence gates**: no step filters on an LLM-reported confidence, and `circular_relationships` and `relationship_consolidation` are removed. *Changes models.*

### Export

- **One file holds two levels**: the architect level (the derived model) and a detail level with the members of its elements (entities, endpoints, programs, deployed artifacts), for which the metamodel gains Artifact. Every element carries a `level`.
- **Views are generated**: Layered, Application Cooperation, Information Structure, Implementation and Deployment, and Business Process Cooperation, laid out deterministically. The files validate against the ArchiMate 3.1 exchange schema and open in Archi.

### Studio

- **The model panel switches level and view**: between the architect and detail levels and the generated views.
- **Issues can be reported from the studio**: a Report issue button fills in the environment, next to a GitHub link.

### Benchmark

- **Runs are checked against modelling conventions**: `benchmark conventions <session...>` checks run snapshots against ArchiMate modelling conventions and writes a review page per repository and model, and a summary.
- **Runs are compared with reference models**: `benchmark reference <session>` reports recall and precision per element type, layer and relationship kind against JSON or Archi references, with split elements, chain completeness, accepted names and a derivable subset.
- **Extraction can repeat per run**: `benchmark run --extract-per-run` repeats the whole pipeline in every run, on a graph of its own and with the run's own model.
- **Each call records what it sent**: temperature, top_p, seed, reasoning level and the model that answered. A model config can set its own temperature (`LLM_{NAME}_TEMPERATURE`).
- **`benchmark analyze` reports more**: consistency by source identity and by type and name (share and mean Jaccard) per layer, answer and decision stability with Krippendorff's alpha per decision type, answers outside their candidates, and the share of differences from extraction or derivation. `--also` gives agreement across sessions.
- **Baseline B1 generates the whole model in one go**: `benchmark run --baseline b1` asks the LLM for the model from raw repository material, validated against the ArchiMate rules and repaired at most twice (config row `BaselineB1`).

### Configuration

- **Extraction steps can be added**: `config add extraction <node type> --sequence N` adds a disabled extraction step.

### Fixes

- **Nested and dynamic imports are extracted**: Python imports inside functions and blocks, and JavaScript `require()` and dynamic `import()`.
- **Calls resolve like the language does**: the caller's own file first, then the files it imports, then its module root, always in the caller's language (`call_languages` for cross-language calls). A bare call means the caller's own method only in Java and C#.
- **Python relative and aliased imports resolve**: `from . import x` and `import y as z`.
- **A top folder named like the repository is kept**: it is no longer dropped from stored paths.
- **Smaller fixes**: LLM config values are stripped of padding inside quotes, `config query` no longer claims to be safe during a benchmark, and the studio layout has small fixes.

## [0.8.1] - 2026-10-12

Cleanup release: a smaller install, a studio without the notebook stack, and stricter LLM configuration.

### CLI

- **CLI output is complete and quiet**: the derivation summary counts the elements refine disabled, and no pydantic-ai banner prints on start.

### Fixes

- **LLM configuration is cleaned**: keys, URLs and model names are stripped of padding and quotes, permanent client errors are not retried, and API keys are redacted from error text.

### Dependencies

- **The install is smaller**: `pydantic-ai-slim` with only the providers Deriva builds, and unused dependencies removed; deriva-cli installs 86 packages instead of 146.
- **The studio installs no notebook stack**: anywidget-graph 0.4.3 and anywidget-archimate 0.3.1 no longer install marimo, and the model view keeps its zoom.

### Development

- **Ruff checks library boundaries**: `TID251` also checks third-party imports, and the Ollama warm-up uses httpx.

## [0.8.0] - 2026-10-11

Studio release: Deriva Studio, a local FastAPI and React web UI, replaces the marimo app, with a benchmark mode, a log of every LLM call and three packages on PyPI. Derived models change.

### Security

- **Cache files cannot run code**: pickled cache rows are refused (diskcache CVE-2025-69872).
- **The studio API checks its input**: plain labels, bounded limits, exports only into `workspace/output`, and no listening beyond this machine without `--allow-remote`. The CI token is read-only.
- **Secrets stay out of exports**: exports and session inputs hold no secrets, and `.env` writes are atomic and refuse line breaks.

### Extraction

- **Mainframe sources are parsed**: COBOL programs and copybooks, JCL and BMS maps, by structural parsers.
- **Business concepts are cleaner**: ties at the evidence cut are kept as groups (`evidence_keep_ties`), pipeline terms and licence files are no concepts, prompt examples name no domain, and proper names keep their spelling.

### Derivation

- **Business concepts the code names stay in the model**: they are kept and connected (`named_in_code`, `code_support.single_word_names`). *Changes models.*
- **Roles come from structure** (`roles.structural`): an annotation or a kind gives a candidate its role without an LLM call.
- **Application services are capabilities** (`component_services`): identity and relationships come from structure, and one call writes the name and a sentence.
- **Relationships come from graph links** (`graph_links`, `listed_members`): drawn without an LLM call.
- **Full runs start from an empty model**: `derivation_clear_model` switches it off; runs of one phase or step keep the model.

### Studio

- **Deriva Studio replaces the marimo app**: `uv run deriva` starts a local web UI (FastAPI, React) on http://127.0.0.1:8765 with the API documented at `/docs`. The marimo app and `deriva-app` are removed.
- **The workspace runs and shows the pipeline**: pick a repository and a scope, then start, follow and cancel runs on one live canvas (anywidget-graph) where the repository, the intermediate graph and the output graph grow step by step, each element linked to its sources. The model (anywidget-archimate) follows, with XML export.
- **Large graphs stay readable**: samples keep every node type in proportion, most connected first (8 to 13 times as many edges as a random pick), with layer rows, lane labels and colours checked for colour-blind readers. Elements refine rejected show in grey.
- **Configuration is edited in the studio**: a step's instruction, example, params, candidate query and batch size are saved as a new version, with a history diff, an overfit scan before saving and a read-only dry run.
- **Both ontologies have pages**: the graph's node types with counts, producing and reading steps and the schema, and the 13 ArchiMate element types with their steps and the allowed relationships per pair.
- **Repositories, settings, file types and model configs are managed in the studio**: model configs also with `config model list|set|delete`; keys are masked and only written.
- **The studio has a visual identity**: the inverted isoline logo and the "Tide" colours (SVGs in `assets/brand/`).
- **One session owns the databases**: one session behind a lock; typed graph queries run in a transaction that is always rolled back, behind a write guard.
- **The studio guides a first run**: first-run hints, a theme switch that reaches every view, and runs that survive a reload.
- **Every LLM call is kept**: a log per run holds prompt, answer, kind, tokens, latency, cache state, error and generation settings, shown in the live log, the Prompts tab and the element trace (`GET /api/trace/{element}`).

### CLI

- **`repo clone` fetches submodules**: a clone includes the repository's submodules.

### Benchmark

- **Benchmarks start from the studio**: end to end or derivation only, with single calls.
- **Sessions are read together**: consistency per repository by name and by source, and answer stability per step as a heatmap.
- **Flips show their cause**: the candidate stage, no candidate or a missing source node, with the deciding calls showing whether the LLM or something upstream changed.
- **The model inspector compares runs**: all runs, one run or two side by side, as boxes or as an ArchiMate diagram with comparison badges.
- **Elements trace across runs and sessions export**: an element is followed across runs, and a session is exported as one verified bundle.
- **Every run records its inputs**: benchmark sessions and studio runs record their config versions, samples per step, file types, name patterns, settings and environment (`session_inputs.json`, `inputs.json`).
- **Sessions export reproducibly**: `benchmark export <session> -o <zip>` writes a zip with the config texts, the environment and a sha256 manifest.
- **Runs write process mining logs**: OCEL 2.0 and a case log (`cases.csv`, `cases.xes`); `benchmark ocel` exports several sessions as one log.
- **Run snapshots record more**: refine disables with their reason, capped candidates (`over_cap`) and BusinessConcept output stability. The event log names every node, edge, element and relationship a step created.

### Configuration

- **Fresh installs work out of the box**: the configuration ships as seed data, and the database is created on first use.
- **One home folder and one settings layer**: `~/.deriva` (moved with `DERIVA_HOME`) and pydantic-settings, where the environment wins over `.env`.
- **Newer models are configurable**: a model config can take no temperature (`LLM_{NAME}_SAMPLING`) and set a reasoning level (`LLM_{NAME}_REASONING`). Each call records the model that answered, as a retired id can be served by another model.

### Fixes

- **A first start works end to end**: graphs persist in the home folder by default, the first saved model becomes the default, and a model's own key and URL reach the provider.
- **Structure-only runs make no LLM call**: with `--no-llm` or **Structural steps only**.
- **`benchmark analyze` compares like with like**: it compares the runs of one repository with one model (a two-repository session read 2.7%), and a single run reads "not measured".
- **Smaller fixes**: `benchmark mark-failed`, `config model set` on duplicated keys, long paths on Windows, `run` without `-v`, runs and benchmarks that end cleanly, JSON answers that quote a code fence, half-made configuration databases, and studio keyboard access, live regions and contrast.

### Dependencies

- **grafeo 0.6.0b1 from PyPI**: graph files of earlier versions are extracted again. spaCy pipelines are downloaded on first use, pinned by version and SHA-256.
- **deriva-py cannot share an environment**: ISI's deriva-py (`deriva` on PyPI) cannot share a Python environment with Deriva (known limitation).

### Development

- **Three packages on PyPI**: `deriva-studio` (studio and CLI), `deriva-cli` (CLI only) and `deriva-dev` (both, plus benchmarking), installed with `uv tool install --python 3.14 deriva-studio`.
- **Releases are checked and attested**: version checks, wheel smoke tests, trusted publishing with PEP 740 attestations and a `constraints.txt` per release. CI installs the packages as tools on Linux, Windows and macOS.
- **Documentation is published at docs.deriva.dev**: its sources moved to `docs/`.

## [0.7.1] - 2026-10-07

Stability and consistency release: every prompt text is versioned config, extraction and derivation take their candidates, identities and most relationships from structure with closed LLM classifications, and `benchmark step` measures one step at a time. Most changes alter derived models, and graphs written by earlier versions are extracted again on their next run.

### Extraction

- **Business concepts come from candidate terms**: a new NLP adapter finds candidate terms in the documentation with spaCy (English, German and French, each translated to an English identity), and the LLM only classifies each term into a closed set of business or reject labels, in batches that depend only on the term. Repeated runs agree on about 95% of the output (was about 73%) with 1 to 16 LLM calls per repository; spaCy and CTranslate2 are new dependencies, and the translation models download on the step's first run. *Changes models.*
- **Per-document business concept extraction is removed**: its prompts, multi-file batching, structural seed concepts, voting and name normalization are gone.
- **Business concept classification rejects the software's own operations**: the shipped instruction labels the data structures the software keeps and the operations on them (also as a verb with an object) as technical. In a hand check the technical share of accepted concepts fell from about half to under a third, with no valid concept rejected. *Changes models.*
- **Business concept terms left out of an answer are asked again**: each missing term is asked on its own, up to `missing_retries` times (one decision per term, no voting), and the step reports the retries.
- **Translated phrases are no business concepts**: a candidate whose English name holds a stop word (`stop_words`: articles and forms of "be") is left out after the evidence selection, so no other term moves in or out.
- **Candidate support comes from structure only**: a concept that directory classification made no longer raises a term's evidence, so an upstream LLM answer cannot change which terms reach the classifier.
- **The concept classifier can be told what the system is for**: BusinessConcept params `system_description_chars` and `context_sources` add the README's prose opening and each context line's document to the prompt. The shipped configuration leaves them off: they doubled the concepts and made them vary more between runs.
- **Technologies come from structure**: the platforms that file types imply (a versioned `platforms` table) and the items the input files declare are the candidates, and the LLM only puts each item in a technology category or none, in batches that depend only on the item. Repeated runs agree on about 99% of the output (was about 77%) with 1 to 4 calls per repository, and the project itself and its tools are no longer technologies. *Changes models.*
- **A repository's own modules are no technologies**: a compose service named like one of the repository's own modules, or running an image tagged like one, is no candidate (Technology param `own_modules`). *Changes models.*
- **The repository itself is no technology it uses**: with `skip_repository_name` (Technology and DirectoryClassification), an image, library, compose service or directory named after the repository, in any spelling, is no technology. *Changes models.*
- **Directory classification answers with decisions only**: the LLM picks a classification and a type from fixed lists and writes no description or confidence. The confidence comes from the step's `confidence` param, and the 0.7 confidence gate is gone.
- **One classification per directory name**: directories with the same name key reach the LLM as one entry listing all their paths and share its decision, and the concept takes the directory's name, not the answer's spelling.
- **Structure skips directories before the LLM**: `skip_names`, `skip_trees` and `skip_pass_through` keep directories away from the classification (on one benchmark repository 234 of 625 directories, 8 prompts instead of 13).
- **One identity per concept and technology name**: every step that creates business concepts or technologies takes the id from one canonical name key, so spelling variants such as "Claims Handling" and `claims_handling` are one node. Existing ids with separators change. *Changes models.*
- **Annotations and decorators are kept in the graph**: type definitions and methods store the annotations or decorators they carry (`decorators`), so the ApplicationInterface query's clause for decorated methods matches and a decorated web route becomes an interface. *Changes models.*
- **Properties are stored natively**: graph nodes, edges, elements and relationships store their properties directly instead of a JSON copy, and properties without a value are not stored. Graphs written by earlier versions are extracted again on their next run, and exported models list element properties in sorted order.
- **Directory extraction is faster**: directories are walked once and excluded ones are never entered, giving the same nodes in the same order 10 to 18 times faster on the benchmark repositories.

### Derivation

- **Relationships from containment**: the relationship pass can decide ownership from structure (`params.containment`, checked against the metamodel): the nearest component whose directory holds an element's source composes a nested component or interface, realizes a service and accesses a data object inside it. Composition stays exclusive, components can compose components, and other tiers add no further structural relationship to an element placed this way. *Changes models.*
- **Technology relationships from structure**: a hosting node composes the system software of its role, system software realizes the technology service of its kind, and a technology service serves the component whose files configure it (`params.membership`, `params.configuration`). The chain from component to node is the same in every run. *Changes models.*
- **Relationships without free LLM proposals**: `params.llm_proposals` can switch off the LLM pass that proposed relationships freely, and the shipped configuration does, so every relationship comes from structure. Business elements that structure cannot relate are left without relationships. *Changes models.*
- **Dependencies between components from imports**: with `params.dependency` a component serves the component whose files import its files, drawn between the siblings below the deepest component that holds both ends. Deriva's own model now shows its layers, and the benchmark repositories gain 2, 31 and 9 such lines, the same in every run. *Changes models.*
- **Components at the deployable-unit level**: with step param `deployable_units`, a repository with at least the minimum number of outermost units (build, dependency or container files) takes those units as component candidates. The shipped ApplicationComponent configuration uses a minimum of two; single-unit repositories keep their components. *Changes models.*
- **Application components are parts of the software**: the shipped ApplicationComponent configuration takes only directories with source code below them, and one closed classification per batch leaves out tooling, scripts, container setup, data sets and documentation. A source root that holds nearly all files of the directory above it is represented by that module (`skip_nested`), and repeated runs agree on every component with half the LLM calls. *Changes models.*
- **Application components are derived one candidate at a time**: `per_candidate.min_pool` is 1 (was 6), so small repositories are no longer judged in one batch where a directory flipped between runs. Repeated runs agree on every component and on about 96% of names and structure (was 92 to 93%). *Changes models.*
- **Elements made from a directory's concept lie in that directory**: a source node without a path of its own takes the path of the directory that represents it, so containment, configuration and dependency rules can place such elements. *Changes models.*
- **Data objects from persistence entities**: with `per_candidate.decorators` a candidate with a matching annotation passes the filters and is only named; the shipped DataObject configuration selects persistence-entity annotations (`Entity`, `Table`, `Document`, `Embeddable`, `MappedSuperclass`). In a repository with annotated entities the data objects are its domain entities instead of message classes. *Changes models.*
- **A data object realizes the business object its type names**: `params.same_name` relates elements whose structural sources share a name, and the shipped configuration lets a data object realize the business object of that name, the first business-to-application links from structure. *Changes models.*
- **Business elements need an anchor in the application or technology layer**: `cross_layer_coherence` param `disable_unanchored` disables the elements of a layer with no relationship to another layer, and the shipped configuration applies it to the business layer. On the benchmark repositories the business layer drops from 12, 10 and 76 elements to 0, 0 and 7, removing the main source of run-to-run variance. *Changes models.*
- **Business elements the code names stay**: `cross_layer_coherence` param `code_support` keeps an unanchored element whose concept a type or directory name carries; the shipped configuration counts names of several words, never single words. The kept elements have no relationships yet. *Changes models.*
- **Business elements only from business concepts**: the shipped BusinessActor, BusinessFunction, BusinessProcess and BusinessEvent configurations take only the concepts classified with their label and mentioned in the documentation; one closed classification per batch keeps or rejects each, then a naming call (`naming_call`) follows the type's ArchiMate naming convention. Methods and types matched by word lists no longer become business elements, the name pattern lists are removed, and repeated runs agree on every element (process names on about 95%). *Changes models.*
- **Nodes from the technologies a repository runs**: the Node step also considers technologies classified as system software (databases, message brokers, caches), and its role classification decides which need a host, so a node no longer depends on a directory carrying its name. *Changes models.*
- **Technology nodes can become Nodes**: step param `pattern_labels` limits name patterns to candidates with given labels, and the shipped Node configuration applies them to files only, so repositories that had no Node get Nodes for their platforms and servers. *Changes models.*
- **Nodes by hosting role**: step param `roles` classifies candidates into a closed, versioned list of roles, and each chosen role becomes one element named after it with all its candidates as `sources`. The shipped Node configuration uses application server, database server, message broker, cache server, directory server, monitoring server and container host, and repeated runs agree on every node with one call per repository. *Changes models.*
- **SystemSoftware by closed kind**: with `element_per: "candidate"` each candidate keeps its identity and name and stores its role, and the shipped SystemSoftware configuration classifies technologies into a closed list of kinds instead of keeping those with an LLM confidence above 0.5. Libraries are left out in every run, and the step needs one or two calls per repository instead of five to thirteen. *Changes models.*
- **One structural source, one element**: step param `skip_when_directory_is` leaves out candidates whose directory already is an element's source; the shipped SystemSoftware configuration uses it for application components, and repeated runs agree on every element. *Changes models.*
- **One technology service per kind**: the shipped TechnologyService configuration classifies candidate technologies into a closed list of service kinds in one call, and each kind found is one service named from the list. Its name pattern lists are removed (the exclude list matched inside other names). *Changes models.*
- **Application interfaces by protocol, named from structure**: one closed classification per batch chooses the protocol (HTTP, web UI, command line, messaging, RPC) or none, and the name is built from the component, the candidate and the protocol (`name_template`, `container_type`, `show_path`). The step gives identical output in every run with 1 or 2 calls instead of one or two per candidate. *Changes models.*
- **Application service candidates from structure**: the shipped ApplicationService configuration takes types whose name ends in "Service" (it matched the word anywhere), and a concept that names a module that is already a component is left out. *Changes models.*
- **One application service per contract**: with `skip_subtypes` a candidate that implements or extends another candidate is left out before ranking, so the interface represents its implementations. *Changes models.*
- **Graph thresholds are step config**: the Node step's k-core threshold (the 30th percentile) is step param `graph_filter` (`min_kcore_percentile`, optional `labels`) instead of a constant, and the shipped Node configuration applies it to file candidates only. *Changes models.*
- **Element names can no longer remove elements**: structure decides which candidates become elements before any LLM call, and the naming step never gives an element another candidate's structure name or a name given earlier in the step. An element records its `structure_name` only when naming changed its name. *Changes models.*
- **Steadier element names**: the repository's name is removed from the start of a name also when spread over several words, and naming takes a word's casing from the source where the source uses capitals. *Changes models.*
- **Prompts are built from structure only**: no prompt holds what earlier LLM calls answered; per-candidate prompts list no earlier names, Technology prompts list dependencies by name, and relationship prompts sample elements by graph importance. *Changes models.*
- **No relationships from co-mention**: business actors are no longer assigned to every business process or function mentioned in the same document (on one benchmark repository about 390 of 470 relationships came from this). *Changes models.*
- **LLM relationship proposals must fit a rule**: a proposal is kept only when its source type, target type and relationship type match one relationship rule. *Changes models.*
- **Duplicate detection makes no LLM call**: its semantic check, a prompt in code without a config row, is removed. The pipeline never passed it a model, so results do not change.
- **Duplicate detection uses no domain vocabulary**: names are no longer mapped onto business words or singularized by a fixed noun list; only generic architecture synonyms and abbreviations remain. *Changes models.*
- **Graph metrics are computed in grafeo**: the prep phase runs PageRank, Louvain, k-core, articulation points and degree natively on the graph namespace instead of in solvor. Louvain gives far fewer, larger communities, every node is scored and PageRank is undirected; this requires the grafeo 0.6.0 development build until 0.6.0 is released. *Changes models.*
- **Joint consistency solves each part of the model separately**: constraints never cross unconnected parts, so each part is a small exact problem with the same optimum, and 500 parts take 1 s where 10 took minutes. The step stays disabled until it is measured.

### Benchmark

- **Model quality next to consistency**: `benchmark analyze` reports the structure of every exported model (relationships per element, orphans, parts composed more than once, expected type links, duplicates) and element precision and recall against the repository's reference model. Combined sessions are read under their joined name.
- **Relationships are derived after the elements by default**: `benchmark run` defers relationships to one pass after all elements, as the pipeline does. `--no-defer-relationships` keeps the old mode, in which role-classified elements got no relationships.
- **`benchmark step` repeats one extraction step**: the input is built once from the LLM cache, and each run calls the LLM for the step without the cache, in its own work database. The report gives presence and exact consistency per node and edge type, the properties that differ, live calls and answer stability (`step_results.json`).
- **`benchmark step` measures derivation steps**: `prep`, an element step, `ConsolidatedRelationships` or a refine step, each on a cached extraction and the earlier derivation steps. A run's output is its elements by identifier and its relationships by type and ends.
- **Decision stability for element steps**: `benchmark step` compares every candidate's decision (the stage it reached and the element it became) across runs, so keep and role decisions report the share decided alike.
- **Element steps are scored on identity**: documentation, the LLM's own name and its confidence are reported but not counted in exact consistency, as no later step reads them for identity; `derived_at` is left out like other timestamps.
- **Decision stability for batch classification steps**: a step that classifies items in batches reports its decision per item, and `benchmark step` gives the share of items decided alike in every run. One changed label changes a whole batch answer, so answer stability alone says little for such steps.
- **Step reports**: an extraction step can return its own statistics (for business concepts: list sizes, labels, skipped terms, tool versions, decisions), written to the run log and the event log.
- **LLM answer stability in `benchmark analyze`**: per step, the share of prompts that got the same raw decisions in every run (descriptions, documentation and confidence left out), next to output consistency, so voting or post-processing cannot hide LLM variance.
- **LLM samples per step are recorded**: `session_metadata.json` lists the answers asked per decision for every LLM step (above 1 means majority voting).
- **Display names in the run snapshot**: business concept and technology names are recorded next to their ids.
- **Extraction routes in the run snapshot**: each business concept and technology lists the routes that produced it (technology edges carry `route`), so stability can be measured per route.
- **Keep rates and call kinds**: each run snapshot records every candidate decision (element type, source node, stage), and each LLM call event records its kind (keep, naming, relationship or extraction).

### Configuration

- **All prompt text is versioned config**: the persona, candidate note, rules and abstention rule of the batch element prompt (`params.prompt`), the openings of the single-candidate and relationship prompts (`params.per_candidate.persona`, `params.persona`) and the opening and task sentences of the TypeDefinition, Method, Test and ExternalDependency prompts (`params.prompt`) moved from code into config rows, byte-identical. A step whose config lacks one of these texts reports an error instead of using built-in text.
- **`config pattern list|add|delete`**: a derivation step's name patterns are managed from the CLI, and a category left without patterns is deactivated. The shipped SystemSoftware include patterns, a list of product names without effect, are removed.
- **Single LLM calls by default**: element naming asks once (it took the majority of three), and the shipped configuration uses one answer per decision for every step.

### Fixes

- **Java and TypeScript imports resolve**: a Java import reaches the repository file that declares the class, the Java standard library is recognised, and a relative script import reaches its file or the directory's index file. On the Java benchmark repositories this recovers about 2,450 and 1,700 internal import edges and removes false hub dependencies. *Changes models.*
- **Methods of Java, TypeScript, JavaScript and C# reach the graph**: the Method step parses the languages in its `languages` param (the shipped configuration lists all five), where it parsed only Python. The interface step's method clauses match decorator registrations only, so a controller file stays the interface. *Changes models.*
- **Long file extensions are recognised**: extensions longer than four letters (`.gradle`, `.properties`, `.coffee`, `.parquet`) classify by suffix, so the Technology step reads Gradle builds again. *Changes models.*
- **Excluded file types are never inputs**: excluded extensions win over location rules at any length, so ArchiMate model files in documentation folders are no longer read as documentation; `.bak` backups are excluded too. *Changes models.*
- **Directory classification sees each directory's files**: the prompt carries the file counts per type and the languages (its query matched no edges and read a missing property), and directories come in path order. *Changes models.*
- **Directory classification votes as configured**: the step's `samples` and `min_votes` reach the classification, which always asked once.
- **Inheritance points at the repository's own types**: once every file is extracted, an inheritance edge to a base type defined in another file reaches the repository's type of that name when exactly one exists. On two benchmark repositories 433 of 649 and 97 of 266 edges now reach a real type (were 13 and 1). *Changes models.*
- **Name keys keep acronyms apart**: acronyms stay as written ("AWS" was "aw"), an acronym plural meets its acronym, and a trailing "+" or "#" belongs to its word ("C++", "C#" and "C" were one technology).
- **The singular and the plural of a name are one identity**: the name key knows singular words ending in "s", words ending in "-che" or "-ie" and more irregular plurals. Ids of the affected names change; re-extract stored graphs. *Changes models.*
- **Results no longer depend on the graph's result order**: candidates, graph readers and graph metrics all go in node id order, verified with grafeo's shuffled result order (identical models, no new LLM calls).
- **Derivation steps read the graph metrics of their own run**: the metrics are read from the graph once per derivation run and after any prep step, not from a disk cache keyed by node and edge counts. `--no-enrichment-cache`, `--nocache-enrichment-configs` and their `run_derivation` and `PipelineSession.run_benchmark` arguments are removed, and `workspace/cache/graph/enrichments` can be deleted.
- **Retyping a relationship keeps everything written on it**: the Flow-to-Access fix lost the confidence and the consolidation mark, so later refine steps read the default confidence.
- **ApplicationInterface honours `graph_filter` and `pattern_labels`**: its candidate filter did not pass the step params on, so both had no effect there.
- **`skip_nested` refuses an unknown file type**: an unregistered file type is an error when the step runs, instead of silently leaving nothing out.
- **Relationship prompts sample elements by graph importance**: the sample reads the source's pagerank that every element stores; it read a missing property and fell back to identifier order.
- **Role elements never share a name**: a candidate whose planned name repeats an earlier one is left out.
- **A represented candidate takes no place in the cut**: `skip_when_directory_is` applies before ranking and the cut (no change on the benchmark repositories).
- **Business events from concepts and methods together**: concepts keep their query order and come first, and only the other candidates take the method path. The shipped configuration returns concepts only.
- **Document text cleanup**: RTF paragraph marks end a segment and RTF Unicode escapes are decoded, and tag removal takes only real tags, so text such as "a < b > c" stays.
- **Voting fixes**: element naming treats spacing variants as one name, directories with the same name each get their REPRESENTS edge, and "series" and "species" are no longer singularized.
- **One failed sample no longer fails the step**: with several samples the others still vote, and the step fails only when every sample failed.
- **Candidate decisions name the created element**: in batch mode a decision records the element's structural identifier, not the one the LLM proposed.
- **Sampled extraction steps**: token usage sums all samples, directories without a majority count as skipped, and parallel sample threads are capped at 8.
- **Config input validation**: step params must be a JSON object (`config update -p`, `config add`), and `config update --temperature` accepts 0 to 2.
- **Switching graph databases checks the key first**: an invalid key no longer closes the open database before failing.
- **Extraction warns when no step matches**: a method-filtered extraction that selects no enabled step returns a warning.
- **Rate limits slow the throttle even when a retry succeeds**: a 429 answered by a successful retry left the adaptive rate unchanged.
- **Re-added graph edges replace their properties**: an edge re-added without properties kept its old ones.
- **LLM extraction steps keep their edge properties**: edges written by the LLM-based extraction steps are stored with their properties; no step reads them yet.
- **`benchmark analyze` finds repositories again**: it read `summary.json`, which the benchmark had renamed to `session_metadata.json`.
- **Answer stability of combined sessions**: `benchmark analyze` keeps the derivation answers of a session that derives several repositories together.
- **`repo clone --overwrite` works on Windows**: Git's read-only pack files made the overwrite fail with "Access is denied"; it now removes the directory as `repo delete` does.
- **`benchmark run --help` is accurate on caching**: it states that `--no-cache-extraction` and `--no-cache-extraction-llm` still read LLM answers from the cache unless `--no-cache` is given.
- **grafeo builds without Cypher are refused before a database opens**: Deriva checks `grafeo.features()` first, where such a build failed at the first query with an attribute error.

### Dependencies

- **grafeo 0.5.44** (requires `>=0.5.44`): cached runs on the benchmark repositories give identical models, and derivation runs up to four times faster on the largest one. Graph files written by 0.5.43 open without re-extraction.
- **solvOR 0.6.3** (requires `>=0.6.3`): now used only for the joint-consistency optimization, where its new MILP solver makes the same decisions in milliseconds where 0.6.2 took up to minutes.

### Development

- **Layer boundaries are enforced again**: the per-layer `ruff.toml` files extend the project configuration, so the architecture bans (TID251) and project rules apply in those folders.
- **The CLI goes through services only**: `config query` and `config snapshot` open their connection through the config service, and `benchmark deviations` takes its recommendations from the deviation service.
- **Derivation modules no longer read the config database**: the service passes each step's patterns to the element module (`generate()` takes `patterns`).
- **Remaining adapter-type imports are a documented exception**: the imports of adapter types left in derivation and extraction modules are marked as such.
- **Layer folders are reformatted**: their code follows the project line length (180).
- **ruff 0.16**: Markdown files are excluded from formatting, so documentation examples keep their hand formatting.
- **Dead code is removed**: the unused BusinessObject suffix collapse in duplicate detection with its element scan, and the graph adapter's index and constraint stubs left from Neo4j.
- **Graph writes use grafeo's upsert helpers**: nodes and edges go through the index-backed `upsert_nodes` and `upsert_edges`, and the per-edge-type cache of existing edges is gone.
- **Id index lookups no longer filter deleted nodes**: grafeo's property index stopped returning them, and a test pins that.
- **Refine steps no longer read the model's storage format**: orphan detection and the Flow-to-Access fix go through the ArchiMate manager, which keeps a retyped relationship's identifier and properties and validates the new type.

## [0.7.0] - 2026-09-27

Grafeo migration release: grafeo, an embedded graph database that runs in-process, replaces Neo4j and its Docker container, 500 to 1000 times faster. Settings and API names that named Neo4j are renamed, which breaks existing `.env` files and scripts (see Configuration and Development). Element names and identities come from structure, so derived models change.

### Security

- **Vulnerable locked dependencies are upgraded**: among them cryptography, pypdf, requests and urllib3. The CI dependency audit skips Deriva itself, which is not on PyPI.

### Extraction

- **Dependency directories are excluded from extraction**: one `excluded_directories` system setting (`.git`, `__pycache__`, `node_modules`, `bower_components`, `vendor`, `.venv`, `venv`, `site-packages`, as whole path segments) applies to every repository walk, replaces five hardcoded lists and is edited with `config setting show|set`. Third-party code no longer becomes Directory or File nodes or derivation candidates. *Changes models.*
- **The TypeDefinition LLM fallback reads code only**: its input sources list programming-language subtypes, so markup, stylesheets, templates and shell scripts no longer reach the LLM. *Changes models.*
- **Directory classification only classifies**: it answers business, technology or skip plus a type, and the concept or technology name comes from the directory name. Document concept extraction keeps only the concepts a majority of samples found (`params.samples`, `params.min_votes`), with samples in parallel. *Changes models.*
- **Business concepts keep every type**: a concept that files classify differently keeps all its types (`conceptTypes`) instead of the last file's, so results no longer depend on file order; derivation queries match on the set. *Changes models.*
- **Technology extraction reads dependency manifests and build files**: its instruction covers the runtime a manifest implies and the system a client library connects to. *Changes models.*

### Derivation

- **Element names come from the code structure**: an element's name and identifier come from its source node, so the same source always gives the same element. The LLM decides whether to keep a candidate and writes its documentation (its proposed name is kept as `llm_name`). *Changes models.*
- **Element naming is isolated**: names come from a separate naming call whose prompt depends only on the source node, its type and a configurable convention (`params.naming`); a majority of several answers wins, with the structure name as fallback. *Changes models.*
- **Joint consistency refine step (experimental, off by default)**: `joint_consistency` selects relationships and duplicate merges together in one exact solvor MILP under metamodel constraints (one relationship per ordered pair, single parents, no cycles where acyclic, no merge of related elements). With `dry_run` (the default) it only writes a report.
- **Graph access is faster**: property indexes on `id` and `identifier`, and enrichment write-back and `graph_relationships` use index lookups and Python joins instead of unindexed Cypher joins.

### CLI

- **One graph database per repository**: `GRAFEO_DB_DIR` holds a `<repository>.grafeo` file per repository (joined names for combined runs, `default.grafeo` without `--repo`), and `run`, `export`, `clear` and `status` accept `--repo`. Benchmark runs are isolated per repository.

### Benchmark

- **Consistency snapshots**: every benchmark run writes a JSON file next to its model with each element, relationship and LLM-extracted graph node, so runs can be compared on names and on source nodes.
- **`--no-cache` covers extraction**: the extraction steps also bypass the LLM cache, so a no-cache benchmark measures the whole pipeline.
- **Runs are observable**: benchmark event logs carry real step durations and extraction events, each LLM call its latency, rate-limit wait and tokens, slow queries warn (`GRAFEO_SLOW_QUERY_MS`), and each session writes `timings.json`.

### Configuration

- **No Docker required**: the graph database is embedded, in memory by default and persistent with `GRAFEO_DB_DIR`.
- **`GRAFEO_DB_DIR` replaces `GRAFEO_DB_PATH`**: the setting is a directory with one database per repository, and a set `GRAFEO_DB_PATH` raises an error.
- **`GrafeoSettings` replaces `Neo4jSettings`**: the environment prefix is `GRAFEO_`.
- **Namespace settings drop Neo4j**: `NEO4J_GRAPH_NAMESPACE` is `GRAPH_NAMESPACE` and `NEO4J_NAMESPACE_ARCHIMATE` is `ARCHIMATE_NAMESPACE`.
- **Relationship prompt rules are config**: the ArchiMate conventions, rules and confidence cutoff of the LLM relationship pass come from the `relationship` phase row `GlobalRelationships` (`instruction`, `params.min_confidence`). Disabling the row skips the LLM pass; graph-derived relationships still run.
- **Per-candidate naming is config**: it is switched on per element type with `params.per_candidate` (`min_pool`, `rules`) instead of class constants.
- **Extraction steps have versioned params**: `extraction_config.params` (added by an automatic migration) is set with `config update extraction <step> -p/--params-file`, and the Technology prompt headings and closing instruction live in `params.prompt`.
- **The BusinessConcept system prompt is config**: the extraction instruction is sent verbatim as the whole system prompt.
- **Moved prompts are byte-identical**: the prompts that moved into config give identical models.
- **`config add derivation`**: adds a disabled derivation step with `--phase`, `--sequence` and `-p/--params`; `config update` gains `--temperature` and `--max-candidates`.

### Fixes

- **Business concept names keep their word boundaries**: normalization lowercased everything after the first letter (`RealTimeDataStreaming` became `Realtimedatastreaming`) and singularized words such as "analysis". It keeps the casing and singularizes only real plurals. *Changes models.*
- **Derivation runs at its configured temperature**: the temperature lives in the step's `temperature` column (`config update --temperature`), as the value in `params` was never read, and the relationship row's temperature applies to the consolidated relationship pass. *Changes models.*
- **LLM-extracted technologies are kept**: the Technology module read `techName` and `techCategory` while the enforced schema names `technologyName` and `technologyType`, so they were silently dropped. *Changes models.*
- **LLM timeouts and retries**: `LLM_TIMEOUT` bounds every call (a stalled request hung the run), and timeouts, connection errors, rate limits and 5xx responses are retried up to `LLM_MAX_RETRIES` with exponential backoff and Retry-After. Other errors fail at once.
- **The LLM cache key covers every response-shaping input**: the system prompt and the effective temperature and max_tokens are part of the key. Existing cache entries are invalidated once.
- **Migrations run every statement**: a comment line directly above a statement hid it from the migration runner.

### Dependencies

- **Neo4j is removed**: `deriva/adapters/neo4j/` and all Neo4j driver dependencies are deleted.
- **grafeo 0.5.43 and solvor 0.6.2 from PyPI**: both are regular PyPI dependencies again, with no local builds.
- **pydantic-ai 2**: the Mistral provider is a declared extra (`pydantic-ai-slim[mistral]`), LLM agents are kept per thread so parallel calls share no HTTP client across event loops, and token usage is read from the `usage` property.

### Development

- **Grafeo adapter**: `deriva/adapters/grafeo/` with `GrafeoConnection` replaces `Neo4jConnection`, on a shared `GrafeoDB` singleton with namespace isolation.
- **Session methods drop Neo4j**: `session.start_neo4j()` and `stop_neo4j()` are `start_graph_db()` and `stop_graph_db()`.
- **Enrichment reads drop Neo4j**: `get_enrichments_from_neo4j()` is `get_enrichments_from_graph()`.
- **Unused relationship prompt builders are removed**: `build_relationship_prompt`, `build_element_relationship_prompt`, `build_per_element_relationship_prompt` and `derive_element_relationships`.

## [0.6.9] - 2026-03-01

Benchmarks, relationships and analysis release: many benchmark runs on three open-source web applications led to new config versions, fewer tokens per run and tools for benchmarking without repository-specific prompts. Relationship consistency stayed below 60%.

### CLI

- **Single Step Execution**: New `--only-step` option for `run` command to run a single extraction/derivation step (disables all others)
- **Benchmark Step Isolation**: New `--only-extraction-step` and `--only-derivation-step` options for benchmark runs
- **Enrichment Cache Control**: New `--nocache-enrichment-configs` option for selective cache bypass during benchmarks
- **Sequence Reordering**: New `config sequence` command to reorder derivation step execution (e.g., bottom-up: Technology → Application → Business)
- **Read-Only Config Access**: New `config query` command for safe config access during benchmark runs (non-blocking)
- **Batch Size in CLI**: Added `--batch-size` option to `config update` for extraction batching

### Extraction

- **Edge Extraction Module**: New `edges.py` for Tree-sitter based relationship extraction. Extracts IMPORTS, USES, CALLS, DECORATED_BY, and REFERENCES edges in a single efficient parse per file. Language-specific filter constants for Python, JavaScript, Java, and C#. Fixed type node ID format mismatch that caused REFERENCES edge creation failures
- **Directory Classification Step**: New extraction step after directories to create technology and business concept nodes (with batched LLM calls), guiding subsequent LLM extraction
- **Structural Technology Extraction**: New extraction method for Technology nodes from infrastructure files (docker-compose.yml, Dockerfile, .env) without LLM
- **Token Efficiency**: Compact JSON serialization (~15% savings), system/user prompt separation, and multi-file batching (`--batch-size N`). Estimated 40-60% total reduction
- **Error Context**: Error messages now include step context (e.g., `[Extraction - TypeDefinition] error...`) for easier debugging

### Derivation

- **HybridDerivation Base**: All 13 modules use hybrid filtering combining pattern-based AND graph-based candidate selection
- **Edge-Aware Relationships**: New Tier 1.5 derivation using CALLS, IMPORTS, USES edges with high confidence (0.90-0.95)
- **Pre-Generation Dedup**: Fuzzy matching against existing elements before LLM calls
- **Business Layer**: BusinessProcess detects orchestrator methods (3+ CALLS), BusinessEvent detects webhooks/signals, BusinessActor detects auth decorators
- **Relationship Consolidation**: Refine step boosts confidence on multi-signal agreement, prunes low-confidence without corroboration
- **Self-Loop Prevention**: Fixed self-referential relationships in graph_relationships with query filters and cleanup
- **Enrichment Cache**: Aligned with LLM cache patterns, CLI control via `--no-enrichment-cache`

### Adapters

- **Pydantic Structured Output**: New `schemas.py` with Pydantic models for all extraction types. LLM manager auto-resolves JSON schemas to models, enforcing structure via PydanticAI
- **Rate Limiting**: Adaptive throttling (auto-reduces RPM on 429s), circuit breaker pattern, Retry-After header respect, error classification, and model-specific rate limits via env vars
- **Graph Metadata**: Element properties now include all graph metrics (kcore, articulation points, degree); propagated to relationships
- **Graph Labels**: Split Neo4j labels into namespace (Graph/Model) and node type, enabling cleaner queries and consistent naming across extraction and derivation
- **Database Locking**: Non-blocking during benchmarks/pipeline runs, versions used for isolation

## [0.6.8] - 2026-01-16

Library migration and cleanup release: six custom implementations replaced with off-the-shelf libraries, with less code to maintain.

### LLM Adapter Rewrite
- **PydanticAI Integration**: Replaced custom REST provider implementations with `pydantic-ai` library
- **Model Registry**: New `model_registry.py` maps Deriva config to PydanticAI model identifiers with URL normalization for Azure/LM Studio
- **Code Reduction**: Same (or better) LLM adapter with way less code, deleted entire `providers.py`
- **Native Structured Output**: PydanticAI handles validation and retry automatically

### Configuration
- **Pydantic Settings**: New `config_models.py` with type-safe environment validation using `pydantic-settings`
- **Standard API Keys**: Added PydanticAI standard env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`, `AZURE_OPENAI_*`)

### Caching
- **diskcache Integration**: Replaced custom SQLite-based caching with `diskcache` library
- **Simplified Cache Utils**: Rewrote `cache_utils.py` to wrap diskcache with `BaseDiskCache` class
- **Preserved Features**: Kept `hash_inputs()`, `bench_hash` isolation, and `export_to_json()` functionality
- **LLM & Graph Caches**: Updated both adapters to use new base cache class

### Retry Logic
- **backoff Library**: Replaced custom retry implementation with `backoff` library
- **New retry.py**: Centralized retry decorator with exponential backoff and jitter
- **Simplified Rate Limiter**: Token bucket rate limiting now separate from retry logic

### CLI Refactor

- **Typer Framework**: Replaced argparse-based CLI with `typer`
- **Command Modules**: Split CLI into `deriva/cli/commands/` with separate files for `benchmark.py`, `config.py`, `repo.py`, `run.py`
- **Modern CLI Features**: Auto-completion, better help generation, type hints via `Annotated`
- **Subcommand Groups**: `config`, `repo`, `benchmark` as typer subapps

### Logging

- **structlog Integration**: Rewrote `logging.py` with `structlog` for structured logging
- **Preserved API**: Same RunLogger, StepContext, and JSONL output format
- **OCEL Unchanged**: OCEL module kept intact for benchmark process mining

### Tests & Quality
- **CLI Tests Rewritten**: Updated all 51 CLI tests to use typer's `CliRunner`
- **Tree-sitter Test Consolidation**: Merged per-language test files into single `test_languages.py`
- **Coverage Threshold**: Updated CI coverage threshold to 80%

## [0.6.7] - 2026-01-15

Token savings release.

### Caching & Performance
- **Graph Cache**: New `cache.py` in graph adapter with hash-based cache for expensive graph queries
- **Common Cache Utils**: Shared `cache_utils.py` module unifying cache patterns across graph and LLM adapters

### Pipeline Phases
- **Derivation Prep Phase**: Renamed `enrich` phase to `prep` throughout codebase (modules, services, configs, CLI, tests)
- **Extraction Phases**: Added `--phase classify` and `--phase parse` options to extraction CLI for granular control

### Configuration Rationalization
- **Settings Principle**: New "Who Changes It" architecture: `.env` for ops/deployment (secrets, connections, provider settings), database for user tuning (algorithms, thresholds)
- **Algorithm Settings in DB**: PageRank damping/iterations/tolerance, Louvain resolution, confidence thresholds, batch sizes now in `system_settings` table
- **LLM Settings in .env**: Rate limits, timeouts, backoff config remain in environment (provider-specific operational settings)

### Benchmarking
- **Rich Progress Bars**: Fixed phase tracking in CLI benchmark runs with proper Rich progress display
- **Per-Repo Flag**: New `--per-repo` flag for running multiple repositories without combining results
- **XML Export**: Changed default export format from `.archimate` to `.xml` for broader compatibility

### Documentation
- **MD Files Review**: Comprehensive pass on all markdown files for accuracy and consistent style
- **Config Pattern Docs**: Updated CONTRIBUTING.md with configuration ownership table and rationale

### Fixed
- **Graph bugs**: Fixed Neo4j relationship syntax in structural_consistency.py and fixed bug in duplicate_elements.py
- **bench-hash Cache Fix**: Fixed cache hit detection in manager.py

### Updated
- **Smarter retries**: Added retry-after header parsing to rate_limiter.py and updated providers.py to pass headers to rate limiter
- **Muted Neo4j**: Suppressed Neo4j notifications during benchmark runs, with toggle in .env

## [0.6.6] - 2026-01-13

ElementDerivationBase and document parsing release.

### Derivation Module Refactoring

New `ElementDerivationBase` and `PatternBasedDerivation` base classes eliminate ~80% code duplication across all 13 element derivation modules. Common `generate()` flow, batch processing, and relationship derivation now centralized.

### Document Parsing

PDF (`pypdf`) and DOCX (`python-docx`) parsing moved from optional to core dependencies for token-limited text extraction.

### Other Changes

- **Structured Errors**: New `ErrorContext` dataclass and `create_error()` helper in `common/types.py`
- **Config Helpers**: Threshold/limit functions in `services/config.py` (`get_confidence_threshold()`, `get_derivation_limit()`, etc.)
- **Coverage**: Increased from 75% to 80%, new test modules for tree-sitter, document reader, types
- **Docs**: New `ARCHITECTURE.MD`, `OPTIMIZATION.md`, enhanced docstrings

## [0.6.5] - 2026-01

Tree-sitter and graph-first relationships release.

### Tree-sitter Adapter

Replaced Python's `ast` with tree-sitter for multi-language code analysis. Supports Python, JavaScript/TypeScript, Java, and C# via unified `TreeSitterManager` with per-language extractors in `adapters/treesitter/languages/`.

### Graph-First Relationship Derivation

Deterministic graph techniques for relationship consistency:

- Community-based (Louvain, 0.95 confidence) and neighbor-based (0.90 confidence) derivation
- Name/file matching with semantic word overlap
- Hybrid approach: deterministic first, then LLM with deduplication
- Edge-to-relationship mapping (CONTAINS→Composition, IMPLEMENTS→Realization, etc.)
- ArchiMate 3.2 metamodel validation for source/target combinations

### Benchmarks & Fixes

- OCEL phase tracking, structured output logging, token optimization
- Bug fixes: chunking logic, TypeDefinitionNode constructor, test fixes

## [0.6.4] - 2026-01-10

Stable benchmark release: the benchmark on Deriva's own repository runs stable end to end.

### Refine Module (NEW)

New post-derivation refinement phase with 5 quality assurance steps in `modules/derivation/refine/`:

- **Duplicate Elements**: Multi-tier detection (exact match → fuzzy match → LLM semantic check) with configurable auto-merge and survivor selection based on PageRank
- **Duplicate Relationships**: Exact duplicate removal and redundant relationship pair detection
- **Orphan Elements**: Identifies unconnected elements, proposes relationships from source graph patterns, optionally disables low-importance orphans
- **Structural Consistency**: Validates graph-to-model containment preservation (files in directories → components in systems)
- **Cross-Layer Coherence**: Checks ArchiMate layer connections (Business↔Application↔Technology) and flags floating elements

The refine phase runs after generation with config-driven step enablement. Each step returns detailed `RefineResult` with issues found/fixed counts.

### Graph Enrichment Stability Improvements

Major improvements for consistent results across different graph sizes and multi-repo setups:

- **Percentile Normalization**: New `normalize_to_percentiles()` functions convert absolute metrics (PageRank, k-core, degree) to 0-100 percentile ranks. A node at 90th percentile means "more important than 90% of nodes" regardless of graph size (50 or 5000 nodes)
- **Deterministic Louvain**: Fixed non-deterministic community detection by sorting nodes before algorithm execution. Same graph now produces identical community assignments every run
- **Graph Metadata**: New `GraphMetadata` dataclass captures graph statistics (total_nodes, density, max_kcore, num_communities). Returned with `EnrichmentResult` and propagated to refine steps via params
- **Per-Repository Isolation**: Added `repository_name` property extraction from node IDs and repo-aware edge filtering in `_get_graph_edges()`. Enables isolated enrichment per repo in multi-repo setups

New enrichment properties per node: `pagerank_percentile`, `kcore_percentile`, `in_degree_percentile`, `out_degree_percentile`

### General Improvements

Multiple minor improvements for different parts of the process:
- **Extraction Method Property**: Added extraction method (structural/ast/llm) property to the graph nodes
- **LLM Rate Limiting**: Extended the LLM manager (adapter) with rate limiting capabilities to gracefully deal with llm provider introduced rate limits
- **Status/Progress Bars**: Both the Marimo app and the cli now have visual indicators of progress during pipeline runs and benchmark runs (cli only)
- **Benchmark Output**: Added model output to the benchmark runs, with unique names ({repo}_{model}_{run#}.archimate)

### Full Test Pass

Removed and added a lot of tests, now fully caught up with all the changes. New test classes:

- `TestPercentileNormalization`, `TestGraphMetadata`, `TestPercentileEnrichments` for enrich module
- Comprehensive refine step tests for all 5 steps

Test coverage did not rise because many weak tests were deleted. Marimo (app) tests are still excluded.

### Graph Enrichment Module

New `modules/derivation/enrich.py` with graph algorithm pre-processing:
- **PageRank**: Node importance/centrality scoring
- **Louvain**: Community detection for natural component boundaries
- **K-core**: Core vs peripheral node classification
- **Articulation points**: Bridge node identification
- **Degree centrality**: In/out connectivity metrics

The enrichment runs before derivation, similar to how classification enriches files before extraction.

### Unified Element + Relationship Derivation

Major refactoring to generate elements and relationships in a single step:
- New `RelationshipRule` dataclass for valid relationships per element type
- LLM-based relationship derivation with `derive_batch_relationships()`
- All 13 element modules updated with `OUTBOUND_RULES` and `INBOUND_RULES`
- Removed obsolete relationship config infrastructure (database table, config class, JSON file)

Benchmark results on flask_invoice_generator: 15 elements, 15 relationships (Access, Serving, Composition, Flow, Realization, Aggregation, Assignment)

### Derivation Improvements

- Renamed `DerivationResult` to `GenerationResult`
- New `Candidate` dataclass with graph enrichment data
- Helper functions: `query_candidates()`, `get_enrichments()`, `batch_candidates()`
- Improved element building with `build_element()` and `parse_derivation_response()`

### Extraction Base Consolidation

Refactor of `modules/extraction/base.py`:
- Merged input_sources.py functionality into base.py
- Name normalization functions for packages, concepts, and technologies
- Canonical package names dictionary for consistent naming
- Singularization helper with irregular plurals support
- Removed `ast_extraction.py` and `input_sources.py`

## [0.6.3] - 2026-01-09

Database adapter and benchmark release.

### Database Adapter Refactor

- Replaced SQL seed files with JSON data files for better portability
- New `db_tool.py` CLI for database export/import operations
- Added `data/` folder with per-table JSON files
- New exports: `export_database()`, `import_database()` in package API

### Benchmarking & Other Changes

- New `benchmarks.md` documentation
- Extended benchmarking service with additional metrics
- Graph manager: Added new query methods
- External dependency extractor: Major improvements
- Config service: New configuration functions

## [0.6.2] - 2026-01-07

New derivation modules and LLM providers release.

### New Derivation Modules

Major expansion with 6 new ArchiMate element modules:
- `ApplicationInterface`, `BusinessEvent`, `BusinessFunction` modules
- `Device`, `Node`, `SystemSoftware` technology layer modules
- Refactored existing modules to consistent style with improved prompts

### LLM Provider Expansion

- Added Mistral AI and LM Studio providers
- Fixed Claude response truncation and null response handling
- Fixed non-dict responses in external dependency extractor

### Extraction & Relationship Improvements

- Added `type` and `subtype` properties to File nodes
- Improved file classification logic
- Significant improvements to relationship derivation logic

### Bug Fixes & CI

- Fixed failing tests, type errors, and linting issues
- Aligned CI test coverage at 70%
- Updated documentation

## [0.6.1] - 2026-01-03

Extraction refactor release: chunking, AST parsing and tests.

### Extraction Module Refactor

- Flattened `modules/extraction/` structure
- Added `common/chunking.py` with file chunking and overlap support
- New database scripts for chunking config and extraction method

### AST Parser & Claude Support

- Enhanced AST analysis for Python (classes, functions, imports)
- Added generic `tree-sitter` dependency for future multi-language support
- Added Claude Haiku model support

### Test Suite Expansion

Comprehensive test coverage across adapters, common utilities, extraction, derivation, and services. Enforced 70% minimum code coverage in CI.

## [0.6.0] - 2026-01-01

Rename release: AutoMate is now Deriva.

The project has been renamed to reflect its broader scope. While initially focused on ArchiMate models, the architecture can derive other model types (C4, BPMN, UML, etc.) from source repositories.

Changes: renamed package directory, updated all imports, CLI commands, Docker containers, and documentation.

## [0.5.11] - 2025-08 to 2025-12

Graph techniques in derivation release.

- Flattened repo into single project layout
- Completed derivation module placeholders and stabilized graph-driven derivation
- Reached ~95% derivation consistency on small repo benchmark
- CLI now supports clearing Graph and Model namespaces

## [0.5.10] - 2025-08 to 2025-12

Adapters rename and cleanup release.

- Renamed managers to adapters to clarify layering
- Consolidated operations and merged metamodel into models
- Added `.github/` scaffolding

## [0.5.9] - 2025-08 to 2025-12

PipelineSession and benchmarking release.

### PipelineSession

New unified API serving both CLI and Marimo:
- Context manager support for lifecycle management
- Query methods for reactive UI
- Orchestration for extraction, derivation, export
- Infrastructure control for Neo4j container management

### Benchmarking Service

Complete multi-model, multi-repository benchmarking framework:
- Test matrix: repos x models x runs
- OCEL integration for process mining analysis
- Post-run analysis with intra/inter-model consistency metrics

### OCEL 2.0 Module

Object-Centric Event Logging for process mining traceability, compliant with OCEL 2.0 standard.

### LLM Manager Refactor

- New protocol-based provider abstraction
- Implementations: Azure, OpenAI, Anthropic, Ollama providers
- Multi-model benchmarking support

### Architectural Boundaries

New per-directory ruff.toml files enforcing layer hierarchy (CLI/App -> services -> managers/modules -> common).

## [0.5.8] - 2025-08 to 2025-12

Consistency framework and config versioning release.

### Consistency Service

Framework for measuring LLM output stability:
- Stage-specific checks (extraction, derivation, validation)
- Deduplication and proper name property mapping
- Achieved 100% consistency through fixes

### Config Versioning System

- Versioned configuration updates preserving history
- Consistency run logging and history queries

### CLI Enhancements

New commands for config management, consistency checking, and history viewing.

### Validation Module Expansion

Comprehensive ArchiMate metamodel validation including relationship rules, naming conventions, orphan detection, and coverage checks.

## [0.5.7] - 2025-08 to 2025-12

Operations pattern and Neo4j migration release.

### Graph Operations Rewritten

Complete rewrite from legacy DuckDB PGQ to Neo4j Cypher:
- Node/edge CRUD operations
- Graph traversal using Cypher patterns
- Subgraph extraction with depth limit

### ArchiMate Operations Directory

New operations following the graph manager pattern for elements, relationships, model operations, and queries.

### Code Quality

Fixed 60+ linter issues, updated type annotations, added documentation for the operations pattern.

## [0.5.6] - 2025-08 to 2025-12

Code quality and standardization release.

### Standardized Pipeline Response Structure

Created unified `PipelineResult` TypedDict used by all pipeline stages with consistent fields for success, errors, warnings, stats, elements, and relationships.

### datetime.utcnow() Fixes

Fixed all deprecated `datetime.utcnow()` occurrences across extraction modules and LLM manager.

### LLM Cache Testing

New test file with 15 tests covering cache operations, statistics, and error handling.

## [0.5.5] - 2025-08 to 2025-12

Complete derivation pipeline release.

### Derivation Service Rewrite

Two-phase approach:
1. **Element Derivation**: Config-driven via DuckDB with LLM-based derivation
2. **Relationship Derivation**: LLM derives relationships between created elements

### CLI Export Command

New `export` command for ArchiMate 3.0 Exchange Format, compatible with Archi modeling tool.

### Full Pipeline Working

Complete flow: extraction -> derivation -> validation -> export to `.archimate` file.

## [0.5.4] - 2025-08 to 2025-12

Services layer and CLI release.

### Services Layer Architecture

New `services/` layer for shared orchestration between Marimo and CLI:
- Config CRUD operations for DuckDB
- Extraction, derivation, validation pipeline orchestration
- Full pipeline orchestration with status tracking

### CLI Entry Point

Fully functional headless interface with configuration commands, pipeline execution, and various options.

### Workspace Consolidation

All workspace-related paths now use `workspace/` folder in project root.

## [0.5.3] - 2025-08 to 2025-12

Complete extraction modules release.

**Structural extraction (no LLM):** Repository, Directory, File modules

**LLM-based extraction:** BusinessConcept, TypeDefinition, Method, Technology, ExternalDependency, Test modules

### Process Changes

- Config-driven extraction with `input_sources` JSON column
- Module pattern standardization with shared base files and registry pattern

## [0.5.2] - 2025-08 to 2025-12

Pipeline and logging release.

### 3-Level JSONL Logging System

- L1 (Phase): Neo4j operations, repo management, file classification
- L2 (Step): Config changes per step
- L3 (Detail): Full LLM details with tokens, cache status, retries

### Pipeline Orchestration

5 pipeline control buttons with step status tracking and proper execution order.

### LLM Manager Updates

Removed YAML config dependency, now uses `.env` configuration with multi-provider support.

## [0.5.1] - 2025-08 to 2025-12

Foundation release.

### Infrastructure

- Neo4j Docker setup with connection pooling
- DuckDB schema with configuration tables
- Repository workspace structure

### Manager Implementations

ArchimateManager, DatabaseManager, GraphManager, LLMManager, SourceManager, DerivationManager.

### UI Framework

4-column Marimo notebook layout for configuration, extraction, derivation, and status display.

## [0.5.0] - 2025-08 to 2025-12

AutoMate V2 merge release.

**Complete codebase replacement** merging parallel V2 development.

### Architecture Changes

- New structure: `managers/`, `modules/`, `layouts/`
- Single-file app: Marimo notebook with 4-column layout
- Config storage: DuckDB replaces JSON config files

### Process Model

Classification -> Extraction -> Derivation -> Validation -> Export

## [0.4.0] - 2025-06 to 2025-07

FastAPI and Jinja2 release: a web UI prototype with an 8-week implementation roadmap, and Run ID traceability linking every artifact from the cloned repository to the final `.archimate` file.

## [0.3.5] - 2025-04

Pre-V2 preparation release.

- Refactored derivation module
- Preparing codebase for V2 merge

## [0.3.4] - 2025-04

Business and technology extraction release.

- BusinessConcept extraction: First LLM-based extraction from documentation
- Technology extraction: Infrastructure component identification

## [0.3.3] - 2025-04

ArchiMate model generation release.

- Full ArchiMate model working: JSON to XML transformation
- Schema validation and file export with `.archimate` extension

## [0.3.2] - 2025-04

ArchiMate layer extraction release.

- Application layer extraction: First ArchiMate-aware step
- LLM prompt templates and ArchiMate schema

## [0.3.1] - 2025-04

Neo4j and graph operations release.

- Neo4j fully integrated with graph manager
- Graph operations layer for node/edge CRUD
- Docker compose for containerized Neo4j

## [0.3.0] - 2025-04

UV rebuild release: a second complete reset for MVP focus, with function-based extraction.

### Reset

Complete reset for MVP focus: removed all previous extraction strategies, tests and UI components.

### Changes

- UV package manager replacing pip
- Function-based extraction with file type detection system
- Layered extraction steps

## [0.2.5] - 2025-02 to 2025-04

Windows support release: PowerShell scripts and cross-platform compatibility improvements.

## [0.2.4] - 2025-02 to 2025-04

Documentation release: Python version pinned, documentation updates, `.gitignore` cleanup.

## [0.2.3] - 2025-02 to 2025-04

Layered strategy release.

- Layered extraction strategy implementing 7-step extraction flow
- ArchiMate metamodel and Pydantic models
- Utility modules for code analysis, config parsing, and module discovery

## [0.2.2] - 2025-02 to 2025-04

Submodule removal release: all 10 tree-sitter submodules removed in favour of Python's AST.

## [0.2.1] - 2025-02 to 2025-04

Extraction templates release.

- 5 extraction strategy templates as Mermaid flowcharts
- Tree-sitter submodules for 10 languages
- Strategy pattern with base and specific implementations

## [0.2.0] - 2025-02 to 2025-04

Rewrite release: the first complete reset, with a FastAPI backend and a Streamlit UI.

### Reset

Complete architectural reset: removed the entire `src/` directory.

### Changes

- FastAPI backend with Streamlit UI
- Service layer for repository and extraction
- Mermaid metamodel parsing

## [0.1.8] - 2025-02

Pre-refactor release: the monolithic analysis split into focused analyzers (business concepts, dependencies, methods, parameters, services, technologies, types).

## [0.1.7] - 2025-02

Memory and metamodel release: persistent context storage, the full metamodel and Mermaid definitions.

## [0.1.6] - 2025-02

Pipeline refactor release: a config restructure with a three-stage pipeline (Chunk, Extract, Analyze).

## [0.1.5] - 2025-02

Robustness release: LLM retries with schema validation, response caching and ArchiMate validation.

## [0.1.4] - 2025-02

Local development release: a Docker Compose setup and dev scripts.

## [0.1.3] - 2025-02

Type system release: Pydantic models and model validation tests.

## [0.1.2] - 2025-02

Housekeeping release: import fixes and `.gitignore` additions.

## [0.1.1] - 2025-02

Initial fixes release: an import warning fixed.

## [0.1.0] - 2025-02

Initial release: pipeline architecture, LLM client (OpenAI), Neo4j storage, Streamlit UI, ArchiMate schema validation and Docker deployment.

## Release series

| Series | Dates | Summary |
| --- | --- | --- |
| 0.9.x | 2026-10 onward | Hardening: safe on untrusted repositories, bugs found since 0.8.10 fixed, defaults for more kinds of repositories |
| 0.8.x | 2026-10 | Deriva Studio: the pipeline transparent and editable in a local web UI (FastAPI, React), and the final benchmark prepared |
| 0.7.x | 2026-03 to 2026-10 | grafeo replaces Neo4j as an embedded graph; stability, portability, prompts in versioned config and consistency |
| 0.6.x | 2025-12 to 2026-03 | AutoMate renamed to Deriva; the first end-to-end implementation, with benchmarks and optimization; the last series on Neo4j |
| 0.5.x | 2025-08 to 2025-12 | A Marimo notebook with domain adapters, reusable extraction and derivation modules and DuckDB config storage (Import, Extraction, Derivation, Export) |
| 0.4.x | 2025-06 to 2025-07 | A FastAPI backend with Jinja2 templates and Run ID traceability (Repository Selection, Run ID Definition, Pipeline Execution) |
| 0.3.x | 2025-04 | The second reset: UV, extraction functions, file types and layered steps stored in Neo4j (Clone, Classify, Extract, Store) |
| 0.2.x | 2025-02 to 2025-04 | The first reset: a FastAPI backend, a Streamlit UI, a service layer and extraction strategies (Clone, Extract, Store in Neo4j) |
| 0.1.x | 2025-02 | A monolithic pipeline with JSON config files (Clone, Chunk, Extract, Analyze, Store) |

- From 0.1.0 to the first reset (0.2.0) took four days.
- Four months passed between 0.3.x (April 2025) and 0.5.x (August 2025).
- The UI went from Streamlit to FastAPI with Jinja2, Gradio, Marimo, and FastAPI with React.
- Configuration went from JSON files to YAML templates to DuckDB tables.
- The name Deriva reflects that the approach generalizes beyond ArchiMate.

---

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
