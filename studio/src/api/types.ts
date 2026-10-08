/** Shapes returned by the studio API (deriva/studio/routers). */

export type DbStatus = { state: "owned" | "held" | "not_connected"; held_by?: number | null; error?: string | null; busy?: boolean };

export type Status = { version: string; db: DbStatus };

export type Repository = {
  name: string;
  path?: string;
  url?: string;
  branch?: string;
  last_commit?: string;
  is_dirty?: boolean;
  size_mb?: number;
  cloned_at?: string;
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
  created_at: string | null;
};
export type ScanResult = { available: boolean; findings: { field: string; finding: string }[] };
export type DryRunResult = { count: number; rows: Record<string, unknown>[] };

export type SaveResult = { name: string; old_version: number | null; new_version: number | null };

export type WidgetNode = { id: string; label?: string; [key: string]: unknown };
export type WidgetEdge = { source: string; target: string; label?: string; [key: string]: unknown };
export type GraphView = { nodes: WidgetNode[]; edges: WidgetEdge[] };

export type ModelElement = { id: string; name: string; type: string; layer: string; documentation: string; source?: string | null };
export type ModelRelationship = { id: string; source: string; target: string; type: string; name: string };
export type Model = { elements: ModelElement[]; relationships: ModelRelationship[] };

export type RunKind = "all" | "extraction" | "derivation";
export type RunSummary = { run_id: string; kind: RunKind; repository: string | null; status: string; events: number; started_at: number; finished_at: number | null };
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

export type BenchmarkSession = { session_id: string; description: string | null; status: string; started_at: string | null; completed_at: string | null };
export type BenchmarkModel = { name: string; provider: string; model: string };
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
export type ModelConfigRow = { name: string; provider: string; model: string | null; url: string | null; key: string | null; key_env: string | null; structured_output: string | null };
/** A model config to save: null keeps a field, "" removes it (a blank key keeps the stored one). */
export type ModelConfigInput = { provider: string; model: string; url: string | null; key: string | null; key_env: string | null; structured_output: string | null };

export type OntologyStep = { name: string; enabled: boolean; version: number | null; method: string | null };
export type NodeType = { name: string; count: number; properties: string[]; sample: Record<string, unknown>; producers: OntologyStep[]; consumers: string[] };
export type EdgeType = { name: string; count: number; pairs: [string, string][] };
export type IntermediateOntology = { node_types: NodeType[]; edge_types: EdgeType[]; other_steps: OntologyStep[] };
export type OutputElementType = { name: string; layer: string; count: number; step: { enabled: boolean; version: number | null } | null };
export type RelationshipRule = { source: string; target: string; direct: string[]; derived: string[] };
export type OutputOntology = { element_types: OutputElementType[]; relationship_types: { name: string; count: number }[]; rules: RelationshipRule[] };
