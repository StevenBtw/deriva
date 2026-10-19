/** Shapes returned by the studio API (deriva/studio/routers). */

export type DbStatus = {
  state: "owned" | "held" | "not_connected";
  held_by?: number | null;
  error?: string | null;
  busy?: boolean;
  /** The last status poll got no answer: ``state`` is the last one known */
  unanswered?: boolean;
};

/** `features` lists optional parts of the install; `environment` is the machine the server runs on. Both are absent on older servers. */
export type Status = { version: string; db: DbStatus; features?: { benchmark?: boolean }; environment?: { os?: string; python?: string } };

export type Repository = {
  name: string;
  path?: string;
  url?: string;
  branch?: string;
  last_commit?: string;
  is_dirty?: boolean;
  size_mb?: number;
  cloned_at?: string;
  /** Why the record no longer matches the workspace (its folder is gone, or is no git checkout) */
  stale?: string | null;
};

/** The verdict on a model from its structure; ``unsupported`` are elements with no file, type or method behind their sources. */
export type ModelQuality = {
  elements: number;
  relationships: number;
  orphans: { id: string; name: string; type: string }[];
  orphan_share: number;
  structural_share: number;
  relationship_types: Record<string, number>;
  layers: Record<string, number>;
  unsupported: { id: string; name: string; type: string; sources: string[] }[];
  verdict: "ok" | "weak";
  reasons: string[];
};

/** One extension's files: how many reached the graph, which step reads them for types and methods, how many gave some. */
export type CoverageRow = {
  extension: string;
  files: number;
  in_graph: number;
  file_type: string | null;
  subtype: string | null;
  reader: "parser" | "llm" | null;
  with_symbols: number;
  unreadable: number;
};

/** What of a repository's checkout reached its graph; incomplete with the reasons, notes for what is worth knowing. */
export type Coverage = {
  files: number;
  in_graph: number;
  extensions: CoverageRow[];
  missing: string[];
  unreadable: { path: string; reason: string }[];
  nodes: Record<string, number>;
  complete: boolean;
  reasons: string[];
  notes: string[];
};

/** What a repository's graph database holds, with its last extraction and derivation run (a full run counts for both). */
export type RepositoryData = {
  repository: string;
  graph: { nodes: number; edges: number };
  model: { elements: number; relationships: number };
  database_bytes: number;
  last_runs: { extraction: RunSummary | null; derivation: RunSummary | null };
};

/** What the workspace keeps on disk; a graph database is a repository's, the shared one, or orphaned (its repository is gone). */
export type StorageOverview = {
  graphs: { key: string; bytes: number; kind: "repository" | "shared" | "orphaned"; active: boolean }[];
  llm_cache: { bytes: number; files: number };
  exports: { bytes: number; files: number };
  benchmark_sessions: { bytes: number; sessions: number };
  runs: { runs: number; bytes: number };
};

export type FileType = { extension: string; file_type: string; subtype: string };

export type StepType = "extraction" | "derivation";

export type ConfigRow = {
  name: string;
  sequence: number;
  enabled: boolean;
  instruction: string | null;
  example: string | null;
  version: number | null;
  [key: string]: unknown;
};

export type ConfigChange = { instruction?: string; example?: string; enabled?: boolean; params?: string; input_graph_query?: string; batch_size?: number };
export type ConfigVersion = {
  version: number;
  is_active: boolean;
  enabled: boolean;
  sequence: number;
  instruction: string | null;
  example: string | null;
  params: string | null;
  batch_size: number | null;
  input_graph_query?: string | null;
  input_model_query?: string | null;
  max_candidates?: number | null;
  temperature?: number | null;
  max_tokens?: number | null;
  llm?: boolean | null;
  extraction_method?: string | null;
  created_at: string | null;
};
export type ScanResult = { available: boolean; findings: { field: string; finding: string }[] };
export type DryRunResult = { count: number; rows: Record<string, unknown>[] };

export type SaveResult = { name: string; old_version: number | null; new_version: number | null };

export type WidgetNode = { id: string; label?: string; [key: string]: unknown };
export type WidgetEdge = { source: string; target: string; label?: string; [key: string]: unknown };
/** Counts of the whole graph per node type and edge type, when a view shows a sample of it (anywidget-graph's `totals`). */
export type Totals = { nodes?: Record<string, number>; edges?: Record<string, number> };
export type GraphView = { nodes: WidgetNode[]; edges: WidgetEdge[]; totals?: Totals };
/** A lane of the linked view; everything after `title` is an anywidget-graph lane option. */
export type Lane = {
  id: string;
  title: string;
  width?: number;
  arrange?: "column";
  action?: boolean;
  glyph?: string[];
  caption?: string;
  layout?: "force";
  // Rows top to bottom by a node field's value (`order`); other values go to a row below them
  rows?: { field: string; order: string[] };
  // Lay the lane out again when one batch adds or removes more than this share of its nodes
  relayout?: number;
  // Label the lane's `count` largest nodes at the default zoom, where the label has room
  labels?: { count: number };
};
/** anywidget-graph's `type_colors`: one colour per node type (and edge type) for the nodes and the legend. */
export type TypeColors = { nodes?: Record<string, string>; edges?: Record<string, string> };
export type LinkedView = { lanes: Lane[]; nodes: WidgetNode[]; edges: WidgetEdge[]; missing_links: number; totals?: Totals };

export type ModelElement = { id: string; name: string; type: string; layer: string; documentation: string; source?: string | null };
export type ModelRelationship = { id: string; source: string; target: string; type: string; name: string };
/** The export levels: the derived model (architect) and, with it, the members of its elements (detail). */
/** The studio's model levels: enterprise, solution, detail (the solution level with the members); "architect" is the whole model of earlier studios. */
export type ModelLevel = "enterprise" | "solution" | "detail" | "architect";
/** A generated view: its ArchiMate viewpoint, its level (enterprise, solution or detail; "architect" in earlier models), the elements and the relationships it shows. */
export type ModelView = { name: string; viewpoint: string; level: ModelLevel; elements: string[]; relationships?: string[] };
export type Model = { elements: ModelElement[]; relationships: ModelRelationship[]; views?: ModelView[] };

export type RunKind = "all" | "extraction" | "derivation";
/** A run of the studio; ``events_kept`` false: a run from before the studio kept live logs, its events cannot be replayed. */
export type RunSummary = {
  run_id: string;
  kind: RunKind | "benchmark";
  repository: string | null;
  status: string;
  events: number;
  started_at: number;
  finished_at: number | null;
  events_kept?: boolean;
};
export type RunEventName = "started" | "progress" | "llm" | "finished" | "cancelled" | "error";
export type RunEvent = {
  seq: number;
  event: RunEventName;
  data: {
    phase?: string;
    step?: string;
    status?: string;
    current?: number;
    total?: number;
    message?: string;
    stats?: Record<string, unknown>;
    candidates?: string[];
    kind?: string;
    repository?: string | null;
    ts?: number;
    call_id?: string;
    seq?: number;
    schema?: string | null;
    cache_hit?: boolean | null;
    latency_ms?: number | null;
    tokens_in?: number | null;
    tokens_out?: number | null;
    temperature?: number | null;
    error?: string | null;
    sessions?: string[];
  };
};

/** One LLM call of a run as listed (no prompt or answer). */
export type LlmCallSummary = {
  call_id: string;
  seq: number;
  step: string | null;
  schema: string | null;
  cache_hit: boolean | null;
  latency_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  /** The temperature the call ran with (absent in logs written before it was recorded). */
  temperature?: number | null;
  error: string | null;
};
/** Where a model element comes from: its source graph nodes, relationships and the LLM calls that mention its sources. */
export type TraceSource = { id: string; type: string | null; name: string | null; properties: Record<string, unknown> };
export type TraceRelationship = {
  identifier: string;
  direction: "in" | "out";
  type: string;
  other: { identifier: string | null; name: string | null; type: string | null };
  derived_from: string | null;
};
export type TraceCall = LlmCallSummary & { role: "decision" | "upstream"; matched: string };
export type Trace = {
  element: { identifier: string; name: string; element_type: string; documentation?: string; properties: Record<string, unknown> };
  sources: TraceSource[];
  relationships: TraceRelationship[];
  calls: TraceCall[];
};
/** One LLM call with its prompt and answer, as kept in the run's call log. */
export type LlmCall = LlmCallSummary & { run_id: string; ts?: number; prompt: string; system_prompt: string | null; response: string | null; cache_key?: string | null };

export type BenchmarkSession = {
  session_id: string;
  description: string | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  /** From its runs (the studio lists them; older answers may leave them out) */
  repositories?: string[];
  models?: string[];
  runs?: number;
  stages?: string[];
  /** Bytes its folder takes */
  bytes?: number;
};
export type BenchmarkModel = { name: string; provider: string; model: string; default?: boolean };
export type BenchmarkRequest = {
  repositories: string[];
  model: string;
  runs: number;
  stages: ("extraction" | "derivation")[] | null;
  use_cache: boolean;
  per_repo: boolean;
  separate_sessions: boolean;
  no_cache_extraction: boolean;
  description?: string;
};
export type ConsistencyRow = { key: string; common: number; union: number; score: number };
export type BenchmarkGroup = {
  repository: string;
  model: string;
  runs: string[];
  counts: { label: string; elements: number; relationships: number }[];
  rows: ConsistencyRow[];
};
export type StepStability = { step: string; prompts: number; identical: number; score: number };
export type Flip = {
  type: string;
  source: string;
  names: Record<string, string>;
  present: string[];
  missing: Record<string, string>;
  also_from: Record<string, string>;
  llm: string | null;
  cause: string;
  /** The model whose runs were compared (flips are found per model) */
  model?: string;
};
/** One run's answer to "why is this element (not) in the model": from the run's snapshot and call log. */
export type RunTraceCall = {
  call_id: string | null;
  step: string | null;
  schema: string | null;
  cache_key: string | null;
  cache_hit: boolean | null;
  model: string | null;
  temperature: number | null;
  prompt: string | null;
  response: string | null;
  error: string | null;
};
export type ElementTrace = { run: string; present: boolean; name: string | null; stage: string | null; refine: string | null; cause: string | null; calls: RunTraceCall[] };
export type InspectorElement = { run: string; identifier: string; name: string; type: string; layer: string; source: string; by_source: string; by_name: string };
export type InspectorRelationship = {
  run: string;
  type: string;
  source_by_source: string;
  target_by_source: string;
  source_by_name: string;
  target_by_name: string;
  derived_from: string | null;
};
export type InspectorView = { repository: string; runs: string[]; elements: InspectorElement[]; relationships: InspectorRelationship[]; causes: Record<string, string> };

/** A model config from .env; ``key`` is masked (``sk-...4f2a``) or null. */
/** One small call with a model config: what answered and how fast, or what to fix (``detail`` is the provider's own message) */
export type ModelTest = {
  ok: boolean;
  model: string;
  provider: string;
  model_id: string;
  served_model?: string | null;
  latency_ms?: number | null;
  answer?: string;
  error?: string;
  detail?: string;
};
export type ModelConfigRow = { name: string; provider: string; model: string | null; url: string | null; key: string | null; key_env: string | null };
/** A model config to save: null keeps a field, "" removes it (a blank key keeps the stored one). */
export type ModelConfigInput = { provider: string; model: string; url: string | null; key: string | null; key_env: string | null };

export type OntologyStep = { name: string; enabled: boolean; version: number | null; method: string | null };
export type NodeType = {
  name: string;
  /** structure, code, business, deployment (or other for a label the metamodel does not name) */
  group: string;
  description: string;
  count: number;
  /** The sample's properties, or the metamodel's for a type the graph has no nodes of */
  properties: string[];
  sample: Record<string, unknown>;
  producers: OntologyStep[];
  consumers: string[];
};
export type EdgeType = { name: string; count: number; pairs: [string, string][] };
export type IntermediateOntology = { groups: string[]; node_types: NodeType[]; edge_types: EdgeType[]; other_steps: OntologyStep[] };
export type OutputElementType = { name: string; layer: string; count: number; step: { enabled: boolean; version: number | null } | null };
export type RelationshipRule = { source: string; target: string; direct: string[]; derived: string[] };
export type OutputOntology = { element_types: OutputElementType[]; relationship_types: { name: string; count: number }[]; rules: RelationshipRule[] };
