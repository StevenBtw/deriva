# Deriva Changelog

Deriving ArchiMate models from code using knowledge graphs, heuristics, and LLMs, a journey through architectural decisions, strategic purges, and lots (and lots) of trial and error.

---

# v0.8.x - Deriva Studio (October 2026 - )

Version 0.8.x makes the pipeline transparent and editable in a local web UI and prepares the final benchmark.

## v0.8.0 - Studio (Unreleased)

### Studio

- **Deriva Studio replaces the marimo app**: `uv run deriva-studio` starts a local web UI (FastAPI backend, React front end, own design) on http://127.0.0.1:8765, with the API documented at `/docs`. The marimo app, its `deriva-app` command and the marimo dependency are removed
- **Workspace**: pick a repository and a scope (everything, extraction, derivation, or structural steps only), start and cancel runs, and follow them live; the intermediate graph and the output graph sit side by side (anywidget-graph) and refresh after each step; the output model opens in anywidget-archimate, with XML export
- **Repositories, settings and file types**: clone, inspect and delete repositories; edit the excluded directories and the file type registry
- **Configuration**: extraction and derivation steps with their versions; instructions and examples are edited in a code editor and saved as a new version (earlier versions stay); steps can be switched on and off
- **One owner of the databases**: the studio keeps one session behind a lock; while a CLI run holds the config database the studio answers with the holder's process id instead of failing, and data views wait for a running step instead of reading at the same time
- **Read-only graph queries**: queries typed into the graph view run inside a grafeo transaction that is always rolled back, behind a write guard, so nothing can change the graphs from there
- `PipelineSession.save_extraction_config` and `save_derivation_config` accept an `example`

### Observability

- **Every LLM call is kept**: the LLM cache holds only the last answer per prompt, so runs overwrote each other there. Now each call's prompt, system prompt, answer, call kind, cache key, tokens, latency, cache hit and error are appended to a log per run: `workspace/benchmarks/<session>/llm/<run>.jsonl` for benchmark runs, `workspace/runs/<run>/llm.jsonl` for studio runs
- **LLM calls in the studio's live log**: each call appears as it lands, with its step, tokens, latency and cache state; prompt and answer unfold on click, and a Prompts tab lists the run's calls
- **Element trace**: clicking an element in the model shows its source graph nodes with their properties, its relationships, and the run's LLM calls that mention its sources (the deciding calls of its own step and the upstream calls), also at `GET /api/trace/{element}`
- **Benchmark export**: `deriva benchmark export <session> -o <zip>` (and `GET /api/benchmarks/{session}/export`) writes one zip with the session folder, the full config texts at the session's versions, the environment (Deriva commit, grafeo build, solvOR, Python, model configs without keys) and a manifest with the sha256 of every file; the same session always exports to identical bytes
- Model statistics count elements by their type (every element was counted as "Unknown")
- **Session inputs**: every benchmark session writes `session_inputs.json` into its folder when it starts: the config versions, LLM samples per step, the file type registry, derivation name patterns and system settings (these keep no version history, so they are captured as they are, with a sha256 per table), and the environment (git commit with dirty flag, a sha256 over the package source files, versions, model configs without keys). A session that fails still records what it ran on, and the export bundle carries it
- **Studio runs record their inputs**: each studio run writes `inputs.json` next to its call log, in the same format as a benchmark session's inputs (config versions, LLM samples, file types, name patterns, settings, environment) with the session's LLM provider, model and default generation settings; model records keep generation limits such as `max_tokens` (only names ending in key, token, secret or password count as secrets)
- **Trace an element of a benchmark run**: picking an element in the model inspector shows, per run of the selected sessions, whether it is in the model and under which name, its candidate stage, the refine rule that disabled it or the cause it is missing, and the calls of its own step with prompt and answer; built from the session files alone (`GET /api/benchmarks/trace`)
- **Answer stability with its counts**: the Steps tab shows the identical and total prompts next to each share, and says that one changed label in a batched classification makes the whole answer differ
- **Generation settings per call**: every logged LLM call records the provider, model, temperature and max tokens it ran with (after defaults); the studio's live log shows the temperature
- **Capped candidates are named**: a derivation candidate that passed the step's filters but fell beyond `max_candidates` gets the stage `over_cap` instead of `filtered_out`, so a binding cap shows in the run snapshot and in flip causes
- **Output stability**: BusinessConcept reports what each decision does (the concept type, or rejected for every reject label) next to the raw label; step benchmarks report this output stability next to the decision stability, so flips between two reject labels no longer count as instability
- **Refine disables are recorded**: run snapshots list the elements a refine step disabled with the reason (for example `no_cross_layer_anchor`), a created candidate whose element was disabled carries that reason, and flips name it ("disabled in refine (no_cross_layer_anchor)") instead of "candidate created"

### Benchmark mode

- **Start benchmarks from the studio**: end to end (separate one-run sessions, the measuring protocol) or derivation only on the current graphs, with the cache policy and runs per repository; samples per LLM call stay 1
- **Read sessions together**: pick one or more sessions and read their runs as one set: consistency per repository by name and by source (elements, relationships, concepts, technologies, with breakdowns per type, provenance and extraction route), and answer stability per step as a heatmap
- **Flips with their cause**: every element missing from a run gets the cause in that run (its candidate stage, no candidate, or a source node the run never extracted); with the runs' LLM call logs, the deciding calls are compared: the same prompt with a different answer points at the LLM, a different prompt points upstream
- **Model inspector**: the runs' models as layers: all runs (agreement), one run, or two side by side; everything, only differences or only stable elements; identity by source or by name; grouped by layer or by cause; shown as boxes or as an ArchiMate diagram whose elements carry their comparison status and a badge (2/3, missing in 1 run, name differs)
- **Export logs** downloads the selected session as one verified bundle

### Extraction quality

- **BusinessConcept candidates keep their tie group**: the evidence cut keeps the smallest prefix of ranked candidates holding the configured share of the evidence; candidates with equal evidence at the cut were split by key, so alphabetical order decided which ones the classifier saw. With the new param `evidence_keep_ties` the prefix runs to the end of that tie group (equal evidence, same decision); the step stats report `ties_added`. Config versions without the param keep the old behaviour, so they reproduce
- **Pipeline structure terms are no directory concepts**: directory classification skips directories named after the intermediate ontology's own node types (repository, directory, file, method, type definition, external dependency, business concept, technology), as it already skipped generic code-structure names
- **Domain-free prompt examples**: the element derivation prompts and the directory classification used an insurance running example (claims, policies, policyholders, premiums) and shop words in their naming examples. Every example now uses abstract placeholders (`<Concept>`, `<Party>`, `<Work Area>`, `<Amount>`) with the same rules and structure, so no prompt carries the vocabulary of a particular domain. Measured on an insurance and a non-insurance development repository: the insurance repository's model is unchanged in content, and no placeholder appears in any output
- **Proper names keep their spelling**: names chosen by the naming step were split at every inner capital, so a proper name such as a product written in camel case lost its spelling; a word the element's source writes as one word now stays whole, while code names the source itself splits (`EntityProcessor`) are still split
- **Licence and project metadata files are no BusinessConcept input**: licence, notice, copying, changelog, contributing, code of conduct and security files are registered as file type `meta`; their terms (warranty, liability, ...) are not domain concepts

### Definitions and editing

- **Model configs from the studio and the CLI**: the LLM model configs in `.env` can be listed, added, changed and deleted in General (and with `deriva config model list|set|delete`); API keys are shown masked and only ever written, the rest of `.env` (other keys, comments) stays as it is, and a model never touches another whose name extends it
- **Fuller config editor**: params (JSON object), the candidate query of derivation steps and the batch size are edited next to the instruction and example; the History tab lists every version with a line diff against the current text; changed texts are scanned for overfitting before they are saved (findings hold the save until confirmed; the scan runs where the local scanner exists); a dry run executes the candidate query read-only without the LLM
- **Ontology pages**: the intermediate ontology lists the graph's node types with their counts, the extraction steps that produce them (switchable), the derivation steps that read them, a sample node and the schema as a graph; the output ontology lists the 13 ArchiMate element types per layer with their derivation step (switchable) and counts, the relationship types with counts, and the allowed relationships per pair (direct and derived, ArchiMate 3.2)

# v0.7.x - Deriva (March 2026 - )

Version 0.7.x is all about stability, portability, user experience, documentation and clean architecture/code standards.

## v0.7.1 - Stability and Consistency (October 7 2026)

### Code Quality

- **Layer boundaries are enforced again**: the per-layer `ruff.toml` files now extend the project configuration. Before, those folders ran on ruff's defaults, so the architecture bans (TID251) and the project rules never applied there
- **CLI goes through services only**: `config query` and `config snapshot` open their read-only connection through the config service, and `benchmark deviations` takes its recommendations from the deviation service
- **Derivation modules no longer read the config database**: the service loads each step's include/exclude patterns and passes them to the element module (`generate()` takes `patterns` instead of a database connection)
- The remaining imports of adapter types in derivation and extraction modules are marked as a documented exception (see ARCHITECTURE.MD)
- Code in the layer folders reformatted to the project line length (180)
- ruff 0.16; Markdown files are excluded from ruff formatting, so documentation examples keep their hand formatting
- Removed dead code: the unused BusinessObject suffix collapse in duplicate detection, and the element scan that fed it; the graph adapter's index and constraint stubs (no-ops left from the Neo4j adapter, never called)
- **All prompt text in versioned config**: the texts that steer the LLM and were still written in code moved into the steps' config rows, byte-identical (cached runs on the benchmark repositories made no live LLM call and gave identical models; snapshot tests pin the assembled prompts):
  - the batch element prompt's persona, note on the candidates, rules and abstention rule, into each element step's `params.prompt`;
  - the opening line of the single-candidate element prompt, into `params.per_candidate.persona`;
  - the opening line of the relationship prompt, into the relationship row's `params.persona`;
  - the opening sentence and the task sentence of the TypeDefinition, Method, Test and ExternalDependency extraction prompts, into each step's `params.prompt`.

  Code keeps only headings, the serialized input and the output contract. A step whose config lacks one of these texts reports an error instead of using built-in text
- **Duplicate detection makes no LLM call**: its semantic check, an LLM prompt written in code without a config row, is removed. The pipeline never passed that step a model, so duplicates were already found from exact and fuzzy name matches only; results do not change (verified with cached runs on the benchmark repositories)
- **`config pattern` commands**: a derivation step's name patterns can be listed, added and removed from the CLI (`config pattern list|add|delete`); a category left without patterns is deactivated. The shipped SystemSoftware include patterns, a list of product names, are removed: that step keeps candidates that match no include pattern, so the list had no effect (verified: the same candidates on the benchmark repositories), and product names do not belong in configuration
- **grafeo 0.5.44**: the minimum grafeo version is now 0.5.44. Cached runs on the benchmark repositories make no live LLM call and give identical models, and derivation runs faster (up to four times on the largest repository). Graph files written by 0.5.43 open without re-extraction
- **solvOR 0.6.3**: the minimum solvOR version is 0.6.3, which Deriva now uses only for the joint-consistency optimization; its new MILP solver (presolve, warm branch and bound, a Rust LP kernel) makes the same decisions on Deriva's joint-consistency instances in milliseconds where 0.6.2 took up to minutes or did not finish
- **Graph writes through grafeo's upsert helpers**: nodes and edges are created or updated with grafeo's index-backed `upsert_nodes` / `upsert_edges` instead of a lookup and one property write at a time, and the per-edge-type cache of existing edges is gone
- **Properties stored natively**: nodes, edges, elements and relationships no longer keep a JSON copy of their properties next to them. Graph nodes store their properties (nested values included) directly, edges their own properties, elements and relationships one `properties` map; a re-added node holds exactly its last write, and properties without a value are not stored. Graphs written by earlier versions are extracted again on their next run. Exported models list element properties in sorted order
- **grafeo builds without Cypher are refused before a database opens**: Deriva sends every query as Cypher; it now checks grafeo's feature list (`grafeo.features()`) first, where a build without Cypher used to fail only at the first query, with an attribute error
- The id index lookups no longer filter out deleted nodes: grafeo's property index stopped returning them (a test pins that behaviour)
- **Refine steps no longer read the model's storage format**: orphan detection asks the ArchiMate manager for the orphan elements (sorted by identifier), and the Flow-to-Access fix retypes the relationship through the manager, which keeps its identifier, name, documentation and properties and validates the new type before removing the old relationship (it used to copy fields by hand into a raw query). An unused element-source helper is removed

### Benchmarking

- **Model quality next to consistency**: `benchmark analyze` reports the structure of every model a session exported: elements and relationships, relationships per element, elements in no relationship, parts composed into more than one whole, pairs linked by more than one relationship type, how many elements of a type are linked to the type a reader expects next to them (a business process to an application service, a data object to a business object, a component to a node), elements that repeat another of the same type and name (the pipeline should derive none), and precision and recall of the elements against the repository's reference model, counting only matches on name and type and each reference element once. Combined multi-repository sessions are read under their joined name. Consistency shows whether runs agree; these measures show whether the model is usable
- **Relationships are derived after the elements by default**: `benchmark run` now defers relationships to one pass after all elements, like the pipeline (`--no-defer-relationships` for the old mode). In the old mode, elements that a step classifies into roles got no relationships, so benchmark models had almost none
- **`benchmark step`**: repeats one extraction step on a fixed input and compares only what it produces. The input (every earlier step) is built once from the LLM cache and kept in the session folder; each run starts from a copy of it, in a separate work database, and calls the LLM for the step without the cache. The report gives presence and exact consistency per repository and per node or edge type, the properties that differ, live LLM calls and answer stability (`step_results.json`). `run_extraction` gained a `steps` filter for it
- **`benchmark step` measures derivation steps**: `prep` (the prep phase), an element step, `ConsolidatedRelationships` (the relationship pass) or a refine step, each on the whole extraction and every earlier derivation step built from the cache. A run's output adds the model's elements by identifier and its relationships by type and ends. `run_derivation` gained a `steps` filter for it
- **Decision stability for element steps**: `benchmark step` compares every candidate's decision (the stage it reached and the element it became) across runs, so keep decisions and role classifications report the share of candidates decided alike in every run
- **Element steps are scored on identity**: for an element step, `benchmark step` reports documentation, the LLM's own name for the element and its confidence but does not count them in exact consistency (no later step reads them for identity; the report names them). Element timestamps (`derived_at`) are left out like other timestamps
- **Decision stability in `benchmark step`**: a step that classifies items in batches reports its decision per item, and the step benchmark gives the share of items with the same decision in every run (reject labels included). One changed label makes a whole batch answer differ, so the answer stability of such a step says little on its own
- **Step reports**: an extraction step can return its own statistics (for business concepts: list sizes, labels, skipped terms, tool versions, decisions); they are written to the run log and the event log, and `run_extraction` returns them per repository and step
- **LLM answer stability in `benchmark analyze`**: per step, how many prompts got the same raw LLM decisions in every run (descriptions, documentation and confidence are left out, so a reworded description is not counted as a different answer; extraction and derivation runs compared separately), in the JSON and Markdown reports next to output consistency, so voting or post-processing cannot hide LLM variance
- **LLM samples per step recorded**: `session_metadata.json` lists the answers asked per decision for every LLM step (above 1 means majority voting), so every consistency number shows whether it came from single calls
- **Display names in the run snapshot**: business concept and technology names are recorded next to their ids (the ids have lost their word boundaries)
- **Extraction routes in the run snapshot**: each business concept and technology lists the routes that produced it (directory classification, document extraction, structural or LLM technology extraction; technology edges carry a `route` property), so stability can be measured per route
- **Fixed: `benchmark analyze` found no repositories**: the analyzer read `summary.json`, which the benchmark had renamed to `session_metadata.json`, so the per-repository analyses were empty
- **Keep rates and call kinds**: each run snapshot records every candidate decision (element type, source node, stage), and each LLM call event records its kind (the output schema: keep, naming, relationship or extraction), so LLM usage and keep rates can be analysed per step

### Consistency

- **Relationships from containment**: the relationship pass can decide ownership from structure: the nearest component whose directory holds an element's source composes a nested component or an interface, realizes a service and accesses a data object defined inside it, set per type pair in the relationship config (`params.containment`, each rule checked against the ArchiMate metamodel). Composition stays exclusive (a part belongs to one whole), components can now compose components, and these relationships are the same in every run. For an element that containment places under an owner, no other tier relates it to that owner, and the community, graph-neighbour, name-overlap and LLM tiers add no further composition, aggregation, assignment or realization to it; usage relationships to other elements (serving, flow, access through code edges) stay. Elements that containment cannot place (for example a service named after a business concept) are related as before. Before, word overlap between names composed one interface into several components, and a component next to a service got both an assignment and a realization
- **Technology relationships from structure**: a node made for a hosting role composes the system software of the technologies in that role, system software realizes the technology service of its kind, and a technology service serves the component whose directory holds a manifest, build or container file that configures one of its technologies (relationship config `params.membership` and `params.configuration`, checked against the metamodel). The chain from component to technology service, system software and node is now the same in every run, and system software has at most one node: a node made from a container file lists no technologies and no longer composes system software
- **Relationships without free LLM proposals**: the relationship config can switch off the LLM pass that proposed relationships freely (`params.llm_proposals`, true when absent), so every relationship comes from structure: containment, membership, configuration files, communities, graph neighbours, code edges and name overlap. The shipped configuration switches it off: the proposals changed between runs (they related generic actors to generic processes and functions by name), and no evidence in the repository backed them. Business elements that structure cannot relate are left without relationships
- **Fixed: Java and TypeScript imports did not resolve**: import resolution only knew Python file layouts, so every Java import became an external dependency named after its first segment (`com`, `org`, a project's own package root), the Java standard library was never recognised, and relative TypeScript and JavaScript imports stayed unresolved. A Java import now resolves to the repository file that declares the class (by its package path under any source root; a nested class or static member to its outer class's file; the nearest module when a class exists in several), the standard library by package prefix, a wildcard import of an own package to no dependency, and a relative script import to the file with any script extension or the directory's index file. On the Java benchmark repositories this recovers about 2,450 and 1,700 internal import edges and removes the false hub dependencies that skewed graph metrics and communities; the relationships derived from those hubs disappear
- **Dependencies between components from imports**: the relationship pass can relate elements by the imports between their files (relationship config `params.dependency`, checked against the metamodel). The shipped configuration lets a component serve the component whose files import its files. Each dependency is drawn between siblings: between the two components just below the deepest component that holds both ends, so a module that uses another module's part shows as a dependency between the two modules, and imports within a component or into its own parts add nothing. Deriva's own model now shows its layers (command line to services, services to modules, adapters and common code, modules to adapters and common code), and the benchmark repositories gain 2, 31 and 9 such lines, the same in every run
- **Annotations and decorators are kept in the graph**: type definitions and methods now store the annotations or decorators they carry (`decorators`), which extraction read but dropped. Derivation queries can select on them; the ApplicationInterface query's existing clause for decorated methods now matches, so a decorated web route becomes an interface (bigdata's web app index page). Prompts are unchanged
- **Components at the deployable-unit level**: a derivation step can select its directory candidates by deployable unit (step param `deployable_units`: the build, dependency and container file names that make a directory a unit, and the minimum number of units). When a repository has at least that many outermost units, those units are the candidates, before any ranking or cut; a repository with fewer keeps its candidates. The shipped ApplicationComponent configuration uses it with common build, dependency and container files and a minimum of two: on the multi-module benchmark repositories the components are now the modules and services (Gateway and the audit and integration hooks, which the centrality ranking had cut, are in; user interface folders and deep packages are out), and the components of single-unit repositories are unchanged
- **Elements made from a directory's concept lie in that directory**: a source node without a path of its own (a concept found in a directory name) now takes the path of the directory that represents it, or the deepest directory shared by several. Containment, configuration and dependency rules can then place such elements: lightblue's data and metadata management services are realized by the applications module they come from
- **Fixed: long file extensions were not recognised**: registered extensions longer than four letters (`.gradle`, `.properties`, `.coffee`, `.parquet`) were kept with the dotfile names and never matched a file's suffix, so Gradle build files and Java properties files were of unknown type. They now classify by suffix. The technology step reads Gradle builds again (on Cloudbased: Java, Eureka, Hibernate, Zuul and more, with the configuration-file relationships that follow); directory classification prompts list the corrected file types
- **A repository's own modules are no technologies**: a compose service named like one of the repository's own modules, or running an image tagged like one, is no technology candidate (Technology step param `own_modules`: the file types and subtypes whose directories are modules, here build, dependency and container files). The shipped configuration uses it; on Cloudbased the compose services of its own microservices no longer reach the classification, which had named them technologies in some runs
- **Data objects from persistence entities**: a derivation step can let an annotation decide (step param `per_candidate.decorators`, a pattern): a candidate carrying a matching annotation passes the name filters and the cut and is only named, never judged; the other candidates take the batch path as before. The shipped DataObject configuration selects types annotated as persistence entities (`Entity`, `Table`, `Document`, `Embeddable`, `MappedSuperclass`) and, in a repository that has them, no longer the name-suffix candidates (message and event classes). On Cloudbased the data objects are now its 34 domain entities (Process Model, Process Instance, Organization, User and more, each accessed by its component) instead of nine message classes; repositories without entities keep their data objects
- **A data object realizes the business object its type names**: the relationship pass can relate elements whose structural sources carry the same name (relationship config `params.same_name`, checked against the metamodel, with suffixes to remove such as an implementation suffix). The shipped configuration lets a data object realize the business object of the same name; on Cloudbased its entities now realize Organization, Process Model, Process Store, Rule, State, Subject and Transition, the first business-to-application links from structure
- **Business elements need an anchor in the application or technology layer**: the cross-layer refine step can disable the elements of a layer that have no relationship to another layer, directly or through relationships within their own layer (`cross_layer_coherence` param `disable_unanchored`, a list of layers; it only flagged them before). The shipped configuration applies it to the business layer: business elements that no derived relationship connects to the rest of the model leave it, together with the relationships between them. Most of them were generic terms from documentation (actors such as Actor, Person and Role, events such as Event Occurred) and the main source of run-to-run variance. On the benchmark repositories the business layer drops from 12, 10 and 76 elements to 0, 0 and 7 (the business objects that Cloudbased's entities realize); on a domain-driven repository the business processes and objects realized by its components stay. Valid business elements without a relationship leave too, until structure can relate them
- **The concept classifier can be told what the system is for**: BusinessConcept params `system_description_chars` (the prose opening of the README at the repository root, with headings, images, badges, HTML, tables and code blocks left out) and `context_sources` (the document of each context line) add both to the classification prompt; without them the prompt is unchanged. Tried with an instruction that judges terms by what the system's users work with: it found far more of a technical product's domain (a data platform's entities and projections, a modelling tool's models and derivation steps) and fewer terms from licenses and example domains, but it doubled the concepts and made them vary more between runs, so the shipped configuration does not use it
- **Business elements the code names stay**: the cross-layer refine step can keep an unanchored element whose source concept the code carries (`cross_layer_coherence` param `code_support`: how many distinct type definition or directory names must contain the concept's words in a row, for names of several words and for single words, where null means a single word never counts). The shipped configuration keeps names of several words that one code name carries and never single words: single words that many class names contain (actor, client, provider, role, manager) were mostly noise. On the benchmark repositories elements such as Generate Like, Process Rating, Business Concept and Extract Data come back; the kept elements have no relationships yet
- **Fixed: methods of Java, TypeScript, JavaScript and C# never reached the graph**: the Method step parsed only Python files with tree-sitter, although the parsers for the other languages exist, so on a Java repository there were no methods, no method annotations and no call edges. The step now parses the languages in its `languages` param (Python when absent); the shipped configuration lists all five. Graph metrics now count the methods of every language, as they already did for Python. The interface step's method clauses match decorator registrations only (`app.route(...)`, `router.get(...)`, `app.command(...)`), so a web route or command registered by a decorator still becomes an interface, while an annotated REST method of a controller class does not become an interface of its own: the controller file stays the interface
- **The repository itself is no technology it uses**: with the new param `skip_repository_name` (Technology and DirectoryClassification), an item named after the repository (a container image, a library, a compose service running such an image) is no technology candidate, and a technology answer for a directory named after the repository is skipped. A name counts in any spelling as one or more whole words (`acme/teastore-persistence` and the directory `big_data_kafka` name the repositories TeaStore and bigdata). The shipped configuration uses it: a repository's own images, client libraries and module directories no longer turn up as technologies in some runs
- **Nodes from the technologies a repository runs**: the Node step now also considers technologies classified as system software (databases, message brokers, caches found in manifests), not only platforms and infrastructure, and its role classification decides which of them need a host. Before, a database or broker got its node only when a directory carried its name, so nodes depended on directory classification; now Apache Kafka, MongoDB, MySQL, MariaDB, ActiveMQ and Ehcache get their message broker, database or cache server
- **Steadier element names**: the repository's name is removed from the start of an element name also when it is spread over several words ("Tea Store Registry" becomes "Registry" in the repository TeaStore), and the naming step takes a word's casing from the source when the source spells it with capitals (the type `CrudTypeImpl` gives "Crud Type" whether the answer says "CRUD Type" or "Crud Type"; a lowercase directory name carries no casing). Two names that varied between runs no longer do
- **No relationships from co-mention**: business actors are no longer assigned to every business process or function mentioned in the same document (on one benchmark repository about 390 of 470 relationships came from this)
- **LLM relationship proposals must fit a rule for their element types**: a proposal is kept only when its source type, target type and relationship type match a relationship rule; before, any relationship type that some rule of the element type allowed was accepted, between any pair
- **Application components are parts of the software**: the shipped ApplicationComponent configuration takes only directories with source code below them (configuration, schema and data folders were components), and one closed classification per batch keeps a directory as a component or leaves out build and task tooling, start and deployment scripts, container setup, data sets and documentation. A directory that holds nearly all of the source files of a selected directory above it (a source root such as `src` inside its module) is represented by that module: new step param `skip_nested` (`file_type`, `min_share`), applied after the candidates are ranked and cut, so no lower-ranked directory takes the freed place. Names still come from the naming call; the documentation comes from the template. Repeated runs on the benchmark repositories agree on every component, with half the LLM calls
- **Business elements only from business concepts**: the shipped BusinessActor, BusinessFunction, BusinessProcess and BusinessEvent configurations take only the business concepts that concept classification gave the matching label and that the documentation mentions, ranked by graph importance. One closed classification per batch keeps a concept as that element type or chooses none, which is the default for anything technical or generic; a repository without business elements of a type gets none. Each kept concept then gets one naming call that follows the ArchiMate naming convention of its type (a role or organization for an actor, a noun phrase for a function, verb and object for a process, object and past-tense verb for an event). Before, these steps also took methods and type definitions whose names matched a fixed word list, so the software's own operations became business functions and processes and functions became events under another name. The steps' name pattern lists are removed, and a concept that names a module which is already an application component is left out. New role param `naming_call` (needs one element per candidate and the step's `naming` params). Repeated runs of the four steps on the benchmark repositories agree on every element and every decision; process names agree on about 95% (the naming call varies the verb)
- **One technology service per kind**: the shipped TechnologyService configuration classifies each candidate technology into a closed list of service kinds (data storage, message queuing, caching, runtime, application hosting and more) in one call, and each kind found becomes one service named from the list, with the technologies that offer it as sources. Services were named per product before ("Node.js", "Java 8"), and names flipped in letter case between runs. Technologies that are a module of the application itself are left out. The step's name pattern lists are removed: its exclude list of standard library and tool names matched inside other names ("re" in "Eureka", "os" in "JBoss") and left out real system software, and its include list had no effect
- **Application interfaces by protocol, named from structure**: the LLM no longer names each interface. One closed classification per batch chooses the protocol a candidate is offered over (HTTP, web UI, command line, messaging, RPC) or none, which leaves out clients of other components, configuration classes and UI helpers. The name is built from structure: the application component that contains the candidate, its own name without the type word, and the protocol (for example `<Component> <Subject> HTTP API`). New role params `name_template`, `container_type` and `show_path`; on the benchmark repositories the step gives identical output in every run with 1 or 2 calls instead of one or two per candidate
- **Application service candidates from structure**: the shipped ApplicationService configuration takes types whose name ends in "Service" (it matched the word anywhere, so application bootstrap, constants and controller classes became services), and a concept that names a module which is already an application component is left out (one source, one element)
- **One application service per contract**: a candidate type that implements or extends another candidate type of the repository (an implementation class of a service interface, for example) is left out before the candidate list is ranked and cut, so the interface represents it. Before, the interface and each implementation became separate services that competed for one name. New step param `skip_subtypes`, used by the shipped ApplicationService configuration; a placeholder for an external base type never represents a candidate
- **Graph thresholds are step config and can be limited to some candidates**: the Node step's k-core threshold (the 30th percentile) was a constant in code and applied to every candidate, also to technologies chosen by their category. The percentile is computed over the whole graph, so an unrelated change elsewhere in the graph moved valid technologies below it and a hosting role disappeared. The threshold is now the step param `graph_filter` (`min_kcore_percentile`, optional `labels`); the shipped Node configuration applies it to file candidates only
- **Directory classification answers with decisions only**: the LLM chooses the classification and a type from fixed lists and no longer writes a description or a confidence. Directory concepts and technologies get the confidence set in the step's params (`confidence`); the confidence gate at 0.7 is gone (the instruction already sends uncertain directories to skip)
- **Business concepts from candidate terms**: the LLM no longer reads each document and writes concepts. A new NLP adapter finds candidate terms with spaCy (noun phrases and verb with object) in the documentation, in English, German and French; a pinned translation model gives every term an English form, which is its identity, and the adapter records where each term occurs. Terms with evidence (at least two mentions, or words that are part of a type definition or directory name) are ranked, and the list holds 80% of the evidence (with a budget cap as a guard). The LLM only classifies each term into a closed set of business labels (object, process, function, actor, role, event, service) or reject labels (technical, attribute, quality, generic, documentation), in batches whose membership depends only on the term. Names, ids, document references and the original wordings (`sourceTerms`) come from the candidates, never from the LLM, and the confidence comes from the step's params. Repeated runs of the step agree on about 95% of their output (was about 73%) with 1 to 16 LLM calls per repository instead of one or more per document; the share of valid business concepts in a hand check did not change (about a quarter). spaCy and CTranslate2 are new dependencies and the translation models are downloaded on the step's first run (see README); new step params `evidence_min_count`, `evidence_share`, `max_candidates`, `support_factor` (the score factor for terms named in the code), `missing_retries`, `confidence` and `nlp`, and the step's batch size is the number of terms per call
- **Business concept classification rejects the software's own operations**: the shipped instruction counts the data structures the software keeps and the operations it performs on them (also when named as a verb with an object, such as "update field") as technical, and chooses a business label only for what people in the organization would name in their own work without knowing how the software is built. In a hand check on the benchmark repositories, the technical share of the accepted concepts fell from about half to under a third, and no valid concept was rejected
- **Business concept terms left out of an answer are asked again**: the model sometimes leaves one or two of several hundred terms out of its classification answer, so those terms had no decision in that run. They are now asked again on their own, up to `missing_retries` times (one decision per term, no voting); the step reports the retry calls and the labels they recovered
- **Technologies from structure**: the LLM no longer reads each manifest and writes technologies. Structure finds the candidates in the step's input files: the platforms their types imply (a versioned table in the step's params: a build descriptor implies its language runtime, a compose file the container platform) and the items they declare (libraries without test scope, build plugins and profiles, compose services with their image and the names of their environment variables, container base images, environment variable names; values never reach a prompt). The LLM puts each item into one of the technology categories or none and names the system it runs or connects to, in batches whose membership depends only on the item; ids, categories, confidence and edges come from structure and those labels, and a technology that directory classification already found keeps its node. Repeated runs of the step on the benchmark repositories agree on about 99% of their output (was about 77%) with 1 to 4 LLM calls per repository instead of one per input file, and no longer produce the project itself or tools as technologies. New step params `platforms`, `confidence` and `missing_retries`; the per-file prompt, its schema, and the structural path with its fixed tables of container images and environment variables are removed
- **Translated phrases are no business concepts**: a candidate whose English name holds a stop word (new step param `stop_words`; the shipped list holds articles and forms of "be") is a clause or phrase that machine translation produced from a term, such as "actors are divided", and is left out of the classifier's list. It is left out after the evidence selection, so its evidence still counts and no other term moves in or out
- **Candidate support from structure only**: a concept that directory classification made (an LLM decision) no longer raises a term's evidence, so a changed answer upstream cannot change which terms reach the classifier
- **One classification per directory name**: directories with the same name (by canonical name key) reach the LLM as one entry listing all their paths, and all of them share the decision. Copies used to land in different prompts and could get different answers in one run, while they already shared one concept identity. The answer is matched back by name key, and the concept takes the directory's name, not the answer's spelling
- **Structure skips directories before the LLM**: the directory classification step's params list names to skip (`skip_names`), trees to skip with everything inside (`skip_trees`, such as test trees) and whether path steps without files and with one subdirectory are skipped (`skip_pass_through`). Those directories never reach the LLM (on one benchmark repository 234 of 625 directories, 8 prompts instead of 13)
- **Single LLM calls by default**: element naming asks once by default (it took the majority of three), and the shipped configuration uses one answer per decision for every step. Majority voting over samples made consistency look better than the single-call behaviour of the pipeline
- **One identity per concept and technology name**: business concept and technology ids come from one canonical name key (words split at spaces, separators and camel-case, parenthetical asides dropped, every word singular, joined and casefolded) in every step that creates them (document concepts, directory classification, structural and LLM technologies). Spelling variants such as "Claims Handling" and the directory `claims_handling` used to become separate nodes. Existing ids with separators change (new baseline)
- **Prompts built from structure only**: a prompt no longer contains what earlier LLM calls answered, so one drifting answer cannot change every later prompt. Per-candidate element prompts no longer list the names chosen for earlier candidates (duplicate names are still checked after the call); Technology prompts list the repository's dependencies sorted by name and no longer the technologies found by earlier calls (still used to deduplicate); relationship prompts sample existing elements by graph importance instead of LLM confidence
- Removed the per-document business concept extraction: its prompts, multi-file batching, structural seed concepts, voting and name normalization
- **Element names can no longer remove elements**: which candidates become elements is decided by structure before any LLM call. A candidate whose structure name repeats an earlier candidate's (for example once the repository prefix is stripped) is left out, and the naming step never gives an element another candidate's structure name or a name given earlier in the step (batch mode now checks across batches, not only within one). Before, a naming answer could take the name of a later candidate, which was then dropped as a duplicate: on one benchmark repository a top-level module disappeared in some runs because a package inside it was named after it. An element records its structure name (`structure_name`) only when the naming step changed its name
- **Application components derived one candidate at a time in every repository**: the shipped configuration uses per-candidate mode from the first candidate (`per_candidate.min_pool` 1, was 6), so the graph filter decides which directories become components everywhere; repositories with fewer than six candidates used to be judged in one batch, where a directory flipped between runs. Repeated runs of the step on the benchmark repositories now agree on every component and on about 96% of their names and structure (was 92 to 93% of components)
- **Technology nodes can become Nodes**: a derivation step's name patterns can be limited to candidates with given graph labels (new step param `pattern_labels`); the shipped Node configuration applies them to files only. Technologies selected by their category in the Node query used to be dropped unless their name contained a pattern such as "docker", so two of the benchmark repositories had no Node at all; they now get Nodes for their platforms and servers, and repeated runs agree on every Node
- **Nodes from technologies by hosting role**: a derivation step can classify candidates into a closed, versioned list of roles (new step param `roles`: the candidate labels, the instruction, the role names, an optional documentation template and `missing_retries`). One call per batch chooses a role or none for each candidate, and every chosen role becomes one element whose identity and name come from the role, with all its candidates recorded (`sources`). The shipped Node configuration classifies technologies into application server, database server, message broker, cache server, directory server, monitoring server and container host, so several application servers become one Application Server node instead of one node per product, and runtimes that need no host of their own are left out. Repeated runs of the Node step agree on every node and every classification, with one call per repository for the technologies
- **SystemSoftware by closed kind**: the role classification can also keep one element per candidate (`element_per: "candidate"`): each candidate keeps its own identity and name and stores its role. The shipped SystemSoftware configuration classifies technologies into database, message broker, runtime, application server, web server, cache, directory service, monitoring, service registry, data processing, container platform or none, instead of keeping candidates whose LLM confidence passes 0.5. Libraries such as HTTP clients or token libraries are left out in every run instead of flipping at the threshold, names are the technologies' own names (no naming call), and the step needs one or two calls per repository instead of five to thirteen
- **One structural source, one element**: a derivation step can leave out candidates whose directory is already the source of an element of given types (new step param `skip_when_directory_is`). The shipped SystemSoftware configuration uses it for application components: a module directory that directory classification also marked as a technology is no longer system software next to the component (the system software it runs comes from the manifests). Repeated runs of the SystemSoftware step on the benchmark repositories now agree on every element
- **Duplicate detection without domain vocabulary**: name comparison for duplicates no longer maps business words onto each other (client, buyer and account to customer; purchase and sale to order; generation to rendering) or singularizes a fixed list of business nouns; only generic architecture synonyms and abbreviations remain

### Fixes

- **Graph metrics computed natively in grafeo**: the prep phase runs PageRank, Louvain, k-core, articulation points and degree in grafeo, on the graph namespace, instead of exporting the edge list to solvor (solvor remains for the joint-consistency optimization). This changes results: Louvain now merges communities level by level (far fewer, larger communities), articulation points no longer fail on deep graphs, every graph node is scored (nodes without edges included), and PageRank is computed on the undirected graph with each connected pair once. Requires the grafeo 0.6.0 development build until 0.6.0 is released
- **Results no longer depend on the graph's result order**: candidates come in node id order (equal PageRank ranks by node id before the `max_candidates` cap), the graph readers return nodes in id order (a type name defined in several files used to resolve to whichever definition the graph returned first), and the graph metrics are computed in node id order. Verified with grafeo's shuffled result order: identical models and no new LLM calls on the benchmark repositories
- **Derivation steps read the graph metrics of their own run**: the element steps read PageRank, communities, k-core, articulation points and degree through a disk cache keyed only by the node and edge counts, so after a solver upgrade, a change of prep parameters or a graph with the same counts they could read values from an earlier run while the stored queries saw the new ones. The values are now read from the graph once per derivation run, and again after any prep step. The `benchmark run` options `--no-enrichment-cache` and `--nocache-enrichment-configs` are removed (there is no cache left to switch off), and so are the `use_enrichment_cache` / `nocache_enrichment_configs` arguments of `run_derivation` and `PipelineSession.run_benchmark`; the files under `workspace/cache/graph/enrichments` are no longer used and can be deleted
- **Retyping a relationship keeps everything written on it**: the Flow-to-Access fix rebuilt the relationship from its stored properties only, so a confidence and the consolidation mark that relationship consolidation writes on the edge were lost, and later refine steps read the default confidence instead
- **ApplicationInterface honours `graph_filter` and `pattern_labels`**: its candidate filter did not pass the step params on to the shared filter, so both had no effect on that step
- **`skip_nested` refuses an unknown file type**: a file type that is not registered counted no files and silently left nothing out; it is now an error when the step runs
- **Answer stability of combined sessions**: `benchmark analyze` dropped the derivation answers of a session that derives several repositories together, because their runs carry the joined repository name
- **`repo clone --overwrite` works on Windows**: replacing an existing clone failed with "Access is denied", because Git keeps its pack files read-only; the overwrite now removes the directory the way `repo delete` does
- **Name keys keep acronyms apart**: the shared name key made acronyms singular ("AWS" became "aw", "DNS" became "dn"), split an acronym plural into two words ("APIs" and "API" were two identities) and dropped "+" and "#" ("C++", "C#" and "C" were one technology). Acronyms now stay as written, an acronym plural meets its acronym, and a trailing "+" or "#" belongs to its word. A name written entirely in capitals with several words (a constant) is still made singular word by word. The benchmark repositories keep all their ids
- **Document text cleanup**: RTF paragraph marks now end a segment instead of joining paragraphs, and RTF Unicode escapes are decoded (their fallback character dropped), so umlauts and other non-ASCII letters survive. Tag removal only takes real tags, comments, declarations and template directives (a name or one of `! ? # @` after "<"), so text such as "a < b > c" stays, and a tag whose quoted attribute holds "<", ">" or a URL goes whole (tags are now removed before URLs)
- **Relationship prompts sample elements by graph importance**: when a type has more elements than the prompt shows, the sample was meant to take the elements whose source is most central in the graph, but it read a property elements do not carry and fell back to identifier order. It now reads the source's pagerank that every element stores
- **Role elements never share a name**: with a name template, two candidates could get the same planned name (a component, a subject and a role), and both became elements with that name. A candidate whose planned name repeats a name given before is now left out, as candidates with a repeated structure name already are
- **A represented candidate takes no place in the cut**: `skip_when_directory_is` left out candidates whose directory is already an element's source only after the candidates were ranked and cut, so they could take places from eligible candidates. They now leave before the cut (no change on the benchmark repositories)
- **Business events from concepts and methods together**: when the BusinessEvent query returned business concepts next to other candidates, all of them took the method path (name patterns, pagerank threshold), which could drop the concepts. Concepts now keep their query order and come first; only the other candidates take the method path. The shipped configuration returns concepts only, so its results do not change
- **Inheritance points at the repository's own types**: an inheritance edge whose base type is defined in another file used to point at a placeholder type (an unresolved external reference), so a class lost its link to the interface or base class it extends, and every step that reads type definitions saw the placeholder as one more type. Once every file is extracted, the edge now points at the repository's type of that name when exactly one exists; type arguments are not part of the name, and qualified names or names defined more than once keep the placeholder. On two of the benchmark repositories 433 of 649 and 97 of 266 inheritance edges now reach a real type (were 13 and 1)
- **One identity for the singular and the plural of a name**: the shared name key dropped "es" from every word ending in "-ses", "-zes" or "-ches" ("databases" became "database"), turned "-ies" into "-y" also for words ending in "-ie" ("cookies"), and cut the final "s" of singular words such as "alias" or "canvas". The singular and the plural of such words became two identities (business concepts, directory concepts, technologies). The rules now know singular words ending in "s", words ending in "-che" or "-ie", and more irregular plurals, so a singular stays as it is and its plural meets it. Ids of the affected names change; re-extract stored graphs
- **Excluded file types are never inputs, wherever they live**: a location rule (for example files under `docs/`) used to win over an excluded extension, and extension entries longer than four letters (such as `.archimate`) never matched as extensions. ArchiMate model files in documentation folders were therefore read as documentation. Excluded extensions now come first, at any length; `.bak` backups are excluded too
- **Directory classification sees each directory's files**: the query behind the classification matched no directory-to-file edges and read a file-type property that does not exist, so every directory reached the LLM with only its name and path. The prompt now carries the file counts per type and the languages, and directories come in path order
- **Directory classification votes as configured**: the step's `params` (`samples`, `min_votes`) never reached the classification, so it always asked once; the configured majority vote now runs
- **Voting fixes**: element naming votes treat spacing variants as one name ("HTTPServer" and "HTTP Server"); directories with the same name each get their REPRESENTS edge (one of them used to lose it); "series" and "species" are no longer singularized
- **One failed sample no longer fails the step**: with several samples, a failed first answer (for example a rate limit) made the whole file or batch fail; the other samples now still vote, and the step fails only when every sample failed
- **Candidate decisions name the created element**: in batch mode a created candidate's decision recorded the identifier the LLM proposed, which no element has; it now records the element's structural identifier (as the per-candidate mode already did)
- **Sampled extraction steps**: token usage in the step details sums all samples instead of the first; directories without a majority classification count as skipped; parallel sample threads are capped at 8
- **Config input validation**: step params must be a JSON object (`config update -p`, `config add`); arrays or scalars used to pass and fail later in the step. `config update --temperature` accepts 0 to 2
- **Switching graph databases checks the key first**: an invalid database key used to close the open database before failing, leaving the process without an active database
- **Extraction warns when no step matches**: a method-filtered extraction that selects no enabled step now returns a warning instead of a silent success
- **Rate limits slow the throttle even when a retry succeeds**: a 429 answered by a successful retry used to leave the adaptive request rate unchanged
- **Joint consistency solves each part of the model separately**: constraints and cycles never cross between unconnected parts of the model, so each part is its own small exact problem (same optimum). The single solve grew exponentially with the number of parts (8 parts: 5.5 s, 10 parts: minutes; one benchmark session spent 18 minutes in it); 500 parts now take 1 s. The step stays disabled until it is measured on the benchmark models
- **Faster directory extraction**: directories are walked once and excluded directories are never entered (the old walk descended into `node_modules` and re-walked each directory's subtree for its size); same nodes in the same order, 10 to 18 times faster on the benchmark repositories
- **Re-added graph edges replace their properties**: an edge re-added without properties kept its old ones
- **LLM extraction steps keep their edge properties**: edges written by the LLM-based extraction steps (business concepts, technologies, type definitions, methods, tests) lost their properties on the way to the graph; they are now stored. No step reads them yet, so models are unchanged
- `benchmark run --help` states that `--no-cache-extraction` and `--no-cache-extraction-llm` re-extract but still read LLM answers from the cache unless `--no-cache` is given

## v0.7.0 - Grafeo Migration (September 27, 2026)

Replaced Neo4j (Docker container) with grafeo, an embedded Rust graph database. Removes the external Docker dependency entirely and the graph database now runs in-process. (500-1000x speedup yah!)

### Infrastructure

- **Grafeo adapter**: New `deriva/adapters/grafeo/` with `GrafeoConnection`, a drop-in replacement for the old `Neo4jConnection`, using a shared `GrafeoDB` singleton with namespace isolation
- **No Docker required**: Graph database is embedded (in-memory by default, persistent via `GRAFEO_DB_DIR`)
- **One graph database per repository**: `GRAFEO_DB_DIR` holds a `<repository>.grafeo` file per repository (combined benchmark runs use the joined repository names, commands without `--repo` use `default.grafeo`). Benchmark runs are isolated per repository; `run`, `export`, `clear` and `status` accept `--repo`
- **Faster graph access**: property indexes on `id` and `identifier`; enrichment write-back and `graph_relationships` use index lookups and Python joins instead of unindexed Cypher joins
- **Observability**: real step durations in benchmark event logs, extraction events, LLM latency/rate-limit wait/requests/tokens per call, slow-query warnings (`GRAFEO_SLOW_QUERY_MS`) and a `timings.json` summary per benchmark session
- **Removed Neo4j**: Deleted `deriva/adapters/neo4j/` and all Neo4j driver dependencies
- **Dependency directories are excluded from extraction**: one `excluded_directories` system setting (default `.git`, `__pycache__`, `node_modules`, `bower_components`, `vendor`, `.venv`, `venv`, `site-packages`, matched as whole path segments) now applies to every repository walk, so third-party code no longer becomes Directory/File nodes or derivation candidates; it replaces five inconsistent hardcoded lists. New `config setting show|set` CLI command; the setting is part of the extraction fingerprint
- **TypeDefinition LLM fallback limited to code**: TypeDefinition input sources list programming-language subtypes only, so markup, stylesheets, templates and shell/batch scripts are no longer sent to the LLM
- **pydantic-ai 2**: the Mistral provider is now a declared extra (`pydantic-ai-slim[mistral]`); LLM agents are kept per thread so parallel calls do not share an HTTP client across event loops; token usage is read from pydantic-ai 2's `usage` property
- **LLM timeouts and retries**: `LLM_TIMEOUT` now bounds every LLM call (a stalled request used to hang the run), and timeouts, connection errors, rate limits and 5xx responses are retried up to `LLM_MAX_RETRIES` with exponential backoff (honouring Retry-After); other errors fail at once
- **grafeo and solvor from PyPI**: grafeo 0.5.43 and solvor 0.6.2 are regular PyPI dependencies again, no local builds needed
- **Security**: locked dependencies with known vulnerabilities upgraded (among others cryptography, pypdf, requests and urllib3); the CI dependency audit skips Deriva itself, which is not published on PyPI
- **Fixed: migrations could skip statements**: a comment line directly above a statement in a migration script hid that statement from the migration runner

### Derivation

- **Joint consistency refine step (experimental, disabled by default)**: `joint_consistency` selects relationships and duplicate-element merges together in one exact optimization (solvor MILP) under metamodel constraints: at most one relationship per ordered element pair, a single parent for single-parent relationship types, no cycles in acyclic relationship types, and no merge of two related elements. Stronger evidence tiers are optimized first. With `dry_run` (the default) it only writes a report
- **`config add derivation`**: new CLI command to add a derivation step (created disabled) with `--phase`, `--sequence` and `-p/--params`; `config update` gained `--temperature` and `--max-candidates`

### Benchmarking

- **Consistency snapshots**: every benchmark run writes a JSON file next to its exported model with each element (identifier, type, name, source node), each relationship (with origin and confidence) and the LLM-extracted graph nodes (business concepts with their types, technologies), so runs can be compared on names and on source nodes
- **`--no-cache` covers extraction**: with `--no-cache` the extraction steps also bypass the LLM cache, so a no-cache benchmark measures the whole pipeline

### Prompts in Versioned Config

- **Relationship prompt rules are config**: the ArchiMate conventions and rules of the LLM relationship pass, and its confidence cutoff, come from the `relationship` phase row `GlobalRelationships` (`instruction`, `params.min_confidence`). Disabling that row skips the LLM relationship pass (graph-derived relationships still run)
- **Per-candidate naming is config**: switched on per element type with `params.per_candidate` (`min_pool`, `rules`) instead of class constants
- **Extraction steps have versioned params**: `extraction_config.params` (JSON, added by a migration that runs automatically when a session connects), set with `config update extraction <step> -p/--params-file`. The Technology prompt headings and closing instruction live in `params.prompt`
- **Fixed: business concept names lost their word boundaries**: name normalization lowercased everything after the first letter (`RealTimeDataStreaming` became `Realtimedatastreaming`) and singularized words such as "analysis"; it now keeps the original casing and only singularizes real plurals
- **Fixed: derivation ran at the default temperature**: element steps kept their intended temperature in `params`, which was never read; the temperature now lives in the step's `temperature` column (new `config update --temperature`), and the relationship row's temperature applies to the consolidated relationship pass
- **Stable business concept extraction**: directory classification only classifies (business, technology or skip, plus a type); the concept or technology name comes from the directory name. Document concept extraction asks the same prompt several times and keeps only concepts found by a majority (`params.samples`, `params.min_votes` on the extraction step); samples run in parallel
- **Isolated element naming**: element names come from a separate naming call whose prompt depends only on the element's source node, its type and a configurable naming convention (`params.naming` on each element step); a majority of several answers wins, with the name from the code structure as fallback
- **Element names come from the code structure**: an element's name and identifier are derived from its source node (directory, file, type, concept or technology name), so the same source always yields the same element; the LLM decides whether to keep a candidate and writes its documentation (its proposed name is kept as `llm_name`)
- **Business concepts keep every type**: when files classify the same concept differently (for example entity in one document, actor in another), the concept node keeps all types (`conceptTypes`) instead of the last file's, so extraction results no longer depend on file order; derivation queries match on the set
- **Fixed: LLM-extracted technologies were silently dropped**: the enforced output schema names fields `technologyName`/`technologyType` while the Technology module read `techName`/`techCategory`; the module now matches the enforced schema
- **Technology extraction reads dependency manifests and build files**, and its instruction covers the runtime a manifest implies and the system a client library connects to
- **BusinessConcept system prompt is config**: the extraction instruction is the whole system prompt, sent verbatim
- Prompts are byte-identical to before the move (identical models)
- Removed unused relationship prompt builders: `build_relationship_prompt`, `build_element_relationship_prompt`, `build_per_element_relationship_prompt`, `derive_element_relationships`
- **LLM cache key covers every response-shaping input**: the key now includes the system prompt and the effective temperature and max_tokens, so changing any of them is never answered from a cache entry made with other settings (existing cache entries are invalidated once)

### Breaking Changes

- `Neo4jSettings` → `GrafeoSettings` (env prefix: `GRAFEO_`)
- `GRAFEO_DB_PATH` (single file) → `GRAFEO_DB_DIR` (directory, one database per repository); a set `GRAFEO_DB_PATH` now raises an error
- `NEO4J_GRAPH_NAMESPACE` → `GRAPH_NAMESPACE`, `NEO4J_NAMESPACE_ARCHIMATE` → `ARCHIMATE_NAMESPACE`
- `session.start_neo4j()` / `stop_neo4j()` → `start_graph_db()` / `stop_graph_db()`
- `get_enrichments_from_neo4j()` → `get_enrichments_from_graph()`

---

# v0.6.x - Deriva (December 2025 - March 2026)

Version 0.6.x is the first robust, end-to-end implementation of Deriva, but still very unstable. The goal for 0.6.x is to be fully feature complete, and have good performance in quality, efficiency, consistency and generalizability. 0.6.x will be the last version using neo4j, which will be replaced with grafeo for performance/stability reasons.

## v0.6.9 - Benchmarks, Relationships & Analysis (March 1, 2026)

I have been running a lot of benchmarks on flask_invoice_generator, full-stack-fastapi-template and taiga-back/taiga-front. Besides a lot of new config versions, I also added a few improvements to further reduce tokens per run and added some things to make my life easier while benchmarking and trying to get the % up without any overly canonical or repository specific prompts. Currently not breaking the 60% barrier, for relationships (the hardest one).

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

## v0.6.8 - Library Migration & Overall Cleanup (January 16, 2026)

Big migration replacing 6 custom implementations with off-the-shelf libraries, reducing the amount of code and improving maintainability.

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

---

## v0.6.7 - Gotta save some Tokens (January 15, 2026)

### Caching & Performance
- **Graph Cache**: New `cache.py` in graph adapter with hash-based cache for expensive graph queries
- **Common Cache Utils**: Shared `cache_utils.py` module unifying cache patterns across graph and LLM adapters

### Pipeline Phases
- **Derivation Prep Phase**: Renamed `enrich` phase to `prep` throughout codebase (modules, services, configs, CLI, tests)
- **Extraction Phases**: Added `--phase classify` and `--phase parse` options to extraction CLI for granular control

### Configuration Rationalization
- **Settings Principle**: New "Who Changes It" architecture - `.env` for ops/deployment (secrets, connections, provider settings), database for user tuning (algorithms, thresholds)
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

---

## v0.6.6 - ElementDerivationBase & Document Parsing (January 13, 2026)

### Derivation Module Refactoring

New `ElementDerivationBase` and `PatternBasedDerivation` base classes eliminate ~80% code duplication across all 13 element derivation modules. Common `generate()` flow, batch processing, and relationship derivation now centralized.

### Document Parsing

PDF (`pypdf`) and DOCX (`python-docx`) parsing moved from optional to core dependencies for token-limited text extraction.

### Other Changes

- **Structured Errors**: New `ErrorContext` dataclass and `create_error()` helper in `common/types.py`
- **Config Helpers**: Threshold/limit functions in `services/config.py` (`get_confidence_threshold()`, `get_derivation_limit()`, etc.)
- **Coverage**: Increased from 75% to 80%, new test modules for tree-sitter, document reader, types
- **Docs**: New `ARCHITECTURE.MD`, `OPTIMIZATION.md`, enhanced docstrings

---

## v0.6.5 - Tree-sitter & Graph-First Relationships (Unreleased)

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

---

## v0.6.4 - Benchmark with Deriva (this repo) runs stable and successful! (January 10, 2026)

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

Test coverage didn't jump because I deleted a lot of weak tests. Marimo (app) tests are still excluded.

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

---

## v0.6.3 - Database Adapter and Benchmark Improvements (January 9, 2026)

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

---

## v0.6.2 - New Derivation Modules & LLM Provider Expansion (January 7, 2026)

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

---

## v0.6.1 - Extraction Refactor, Chunking, AST & Tests (January 3, 2026)

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

---

## v0.6.0 - Rename to Deriva (January 1, 2026)

**AutoMate is now Deriva.**

The project has been renamed to reflect its broader scope. While initially focused on ArchiMate models, the architecture can derive other model types (C4, BPMN, UML, etc.) from source repositories.

Changes: renamed package directory, updated all imports, CLI commands, Docker containers, and documentation.

---

# v0.5.x - The Adapters/Modules/Services/Marimo+CLI Era (August 2025 - December 2025)

**Architectural paradigm:** Marimo notebook (`deriva/app/app.py`) with domain adapters and reusable modules.

**Process model:** Import -> Extraction -> Derivation -> Export

**Solution space:** 7 adapters (database, neo4j, repository, graph, archimate, llm, ast) + modular extraction/derivation functions + DuckDB config storage

---

## v0.5.11 - Improvements to the derivation module using graph techniques

- Flattened repo into single project layout
- Completed derivation module placeholders and stabilized graph-driven derivation
- Reached ~95% derivation consistency on small repo benchmark
- CLI now supports clearing Graph and Model namespaces

---

## v0.5.10 - Adapters Rename & Cleanup

- Renamed managers to adapters to clarify layering
- Consolidated operations and merged metamodel into models
- Added `.github/` scaffolding

---

## v0.5.9 - PipelineSession & Benchmarking

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

---

## v0.5.8 - Consistency Framework & Config Versioning

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

---

## v0.5.7 - Operations Pattern & Neo4j Migration

### Graph Operations Rewritten

Complete rewrite from legacy DuckDB PGQ to Neo4j Cypher:
- Node/edge CRUD operations
- Graph traversal using Cypher patterns
- Subgraph extraction with depth limit

### ArchiMate Operations Directory

New operations following the graph manager pattern for elements, relationships, model operations, and queries.

### Code Quality

Fixed 60+ linter issues, updated type annotations, added documentation for the operations pattern.

---

## v0.5.6 - Code Quality & Standardization

### Standardized Pipeline Response Structure

Created unified `PipelineResult` TypedDict used by all pipeline stages with consistent fields for success, errors, warnings, stats, elements, and relationships.

### datetime.utcnow() Fixes

Fixed all deprecated `datetime.utcnow()` occurrences across extraction modules and LLM manager.

### LLM Cache Testing

New test file with 15 tests covering cache operations, statistics, and error handling.

---

## v0.5.5 - Complete Derivation Pipeline

### Derivation Service Rewrite

Two-phase approach:
1. **Element Derivation**: Config-driven via DuckDB with LLM-based derivation
2. **Relationship Derivation**: LLM derives relationships between created elements

### CLI Export Command

New `export` command for ArchiMate 3.0 Exchange Format, compatible with Archi modeling tool.

### Full Pipeline Working

Complete flow: extraction -> derivation -> validation -> export to `.archimate` file.

---

## v0.5.4 - Services Layer & CLI

### Services Layer Architecture

New `services/` layer for shared orchestration between Marimo and CLI:
- Config CRUD operations for DuckDB
- Extraction, derivation, validation pipeline orchestration
- Full pipeline orchestration with status tracking

### CLI Entry Point

Fully functional headless interface with configuration commands, pipeline execution, and various options.

### Workspace Consolidation

All workspace-related paths now use `workspace/` folder in project root.

---

## v0.5.3 - All Extraction Modules Complete

**Structural extraction (no LLM):** Repository, Directory, File modules

**LLM-based extraction:** BusinessConcept, TypeDefinition, Method, Technology, ExternalDependency, Test modules

### Process Changes

- Config-driven extraction with `input_sources` JSON column
- Module pattern standardization with shared base files and registry pattern

---

## v0.5.2 - Pipeline & Logging System

### 3-Level JSONL Logging System

- L1 (Phase): Neo4j operations, repo management, file classification
- L2 (Step): Config changes per step
- L3 (Detail): Full LLM details with tokens, cache status, retries

### Pipeline Orchestration

5 pipeline control buttons with step status tracking and proper execution order.

### LLM Manager Updates

Removed YAML config dependency, now uses `.env` configuration with multi-provider support.

---

## v0.5.1 - Foundation Complete

### Infrastructure

- Neo4j Docker setup with connection pooling
- DuckDB schema with configuration tables
- Repository workspace structure

### Manager Implementations

ArchimateManager, DatabaseManager, GraphManager, LLMManager, SourceManager, DerivationManager.

### UI Framework

4-column Marimo notebook layout for configuration, extraction, derivation, and status display.

---

## v0.5.0 - AutoMate V2 Merge

**Complete codebase replacement** merging parallel V2 development.

### Architecture Changes

- New structure: `managers/`, `modules/`, `layouts/`
- Single-file app: Marimo notebook with 4-column layout
- Config storage: DuckDB replaces JSON config files

### Process Model

Classification -> Extraction -> Derivation -> Validation -> Export

---

# v0.4.x - The FastAPI/Jinja2 Era (June-July 2025)

**Architectural paradigm:** FastAPI backend + Jinja2 templates + Run ID traceability

**Process model:** Repository Selection -> Run ID Definition -> Pipeline Execution

---

## v0.4.0 - FastAPI/Jinja2 Architecture

Web UI prototype with 8-week implementation roadmap. Introduced Run ID traceability linking all artifacts from cloned repos to final `.archimate` file.

---

# v0.3.x - The UV/Extraction Functions Era

**Architectural paradigm:** UV package manager + extraction functions + layered steps

**Process model:** Clone -> Classify -> Extract (layered steps) -> Store in Neo4j

---
## v0.3.5 - Pre-V2 Preparation

- Refactored derivation module
- Preparing codebase for V2 merge

---

## v0.3.4 - Business & Technology Extraction

- BusinessConcept extraction: First LLM-based extraction from documentation
- Technology extraction: Infrastructure component identification

---

## v0.3.3 - ArchiMate Model Generation

- Full ArchiMate model working: JSON to XML transformation
- Schema validation and file export with `.archimate` extension

---

## v0.3.2 - ArchiMate Layer Extraction

- Application layer extraction: First ArchiMate-aware step
- LLM prompt templates and ArchiMate schema

---

## v0.3.1 - Neo4j & Graph Operations

- Neo4j fully integrated with graph manager
- Graph operations layer for node/edge CRUD
- Docker compose for containerized Neo4j

---

## v0.3.0 - UV Rebuild & Extraction Functions

### The Second Purge

Complete reset for MVP focus - removed all previous extraction strategies, tests, and UI components.

### Post-Purge Changes

- UV package manager replacing pip
- Function-based extraction with file type detection system
- Layered extraction steps

---

# v0.2.x - The FastAPI/Streamlit/Services Era

**Architectural paradigm:** FastAPI backend + Streamlit UI + Service layer + Strategy pattern

**Process model:** Clone -> Extract (via strategies) -> Store in Neo4j

---

## v0.2.5 - Windows Support

PowerShell scripts and cross-platform compatibility improvements.

---

## v0.2.4 - Documentation & Polish

Python version pinned, documentation updates, `.gitignore` cleanup.

---

## v0.2.3 - Layered Strategy Implementation

- Layered extraction strategy implementing 7-step extraction flow
- ArchiMate metamodel and Pydantic models
- Utility modules for code analysis, config parsing, and module discovery

---

## v0.2.2 - Submodule Regret

Removed all 10 tree-sitter submodules. Decided to use Python's AST instead.

---

## v0.2.1 - Template Explosion

- 5 extraction strategy templates as Mermaid flowcharts
- Tree-sitter submodules for 10 languages
- Strategy pattern with base and specific implementations

---

## v0.2.0 - The Phoenix Rises

### The First Purge

Complete architectural reset - removed entire `src/` directory.

### Post-Purge Changes

- FastAPI backend with Streamlit UI
- Service layer for repository and extraction
- Mermaid metamodel parsing

---

# v0.1.x - The Initial Development Era

**Architectural paradigm:** Monolithic pipeline with JSON config files

**Process model:** Clone -> Chunk -> Extract -> Analyze -> Store

---

## v0.1.8 - Pre-Refactor Milestone

Split monolithic analysis into focused analyzers (business concepts, dependencies, methods, parameters, services, technologies, types).

---

## v0.1.7 - Memory & Metamodel

Persistent context storage, full metamodel, mermaid definitions.

---

## v0.1.6 - Pipeline Refactor

Config restructure with three-stage pipeline: Chunk -> Extract -> Analyze.

---

## v0.1.5 - Robustness

LLM retry mechanism with schema validation, response caching, and ArchiMate validation.

---

## v0.1.4 - Local Development

Docker compose local setup and dev scripts.

---

## v0.1.3 - Type System

Pydantic models and model validation tests.

---

## v0.1.2 - Housekeeping

Import fixes and `.gitignore` additions.

---

## v0.1.1 - Initial Fixes

Import warning fix.

---

## v0.1.0 - The Big Bang

Initial release with pipeline architecture, LLM client (OpenAI), Neo4j storage, Streamlit UI, ArchiMate schema validation, and Docker deployment.

---

# Version Boundary Summary

| Era | Dates | Key Event | Architecture |
|-----|-------|-----------|--------------|
| **0.1.x** | Feb 22-25 '25 | Initial development | Monolithic pipeline + JSON configs |
| **0.2.x** | Feb 26-Apr 15 '25 | First Purge | FastAPI/Streamlit/Services/Strategies |
| **0.3.x** | Apr 15-25 '25 | Second Purge | UV/Extraction functions/File types |
| **0.4.x** | Jun-Jul '25 | Web UI prototype | FastAPI/Jinja2 |
| **0.5.x** | Aug-Nov '25 | Final development | Managers/Modules/Marimo/DuckDB |
| **0.6.x** | Dec '25-Jan '26| AutoMate renamed to Deriva | Focus on benchmark and optimization |
| **0.7.x** | Mar '26- | Grafeo migration | Embedded graph, prompts in versioned config, consistency |

---

# Some highlights:

- **Rapid iteration**: v0.1.0 to v0.2.0 (First Purge) took only 4 days
- **The long gap**: 4 months between v0.3.x (Apr) and v0.5.x (Aug)
- **UI evolution**: Streamlit -> FastAPI+Jinja2 -> Gradio (planned) -> Marimo (final)
- **Graph DB constant**: Neo4j was the only technology that survived all purges
- **Config evolution**: JSON files -> YAML templates -> DuckDB tables
- **Python version ambition**: started targeting Python 3.8, now requires Python 3.14
- **Solo developer**: all commits by a single author across 10 months
- **Confidence scoring**: present from day 1, default 0.8 confidence on all elements
- **Deriva**: new name to underscore generalizability beyond ArchiMate

---

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) | Versioning: [SemVer](https://semver.org/spec/v2.0.0.html)
