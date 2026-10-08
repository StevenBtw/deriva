import type {
  BenchmarkGroup,
  BenchmarkModel,
  BenchmarkRequest,
  BenchmarkSession,
  ConfigChange,
  ConfigRow,
  ConfigVersion,
  DryRunResult,
  FileType,
  Flip,
  GraphView,
  InspectorView,
  IntermediateOntology,
  LlmCall,
  LlmCallSummary,
  Model,
  ModelConfigInput,
  ModelConfigRow,
  OutputOntology,
  Repository,
  RunKind,
  RunSummary,
  SaveResult,
  ScanResult,
  Status,
  StepStability,
  StepType,
  Trace,
} from "./types";

/** An API answer other than 2xx; ``heldBy`` and ``busy`` explain a 503. */
export class ApiError extends Error {
  status: number;
  heldBy?: number | null;
  busy?: boolean;
  data: unknown;

  constructor(status: number, message: string, data: unknown) {
    super(message);
    this.status = status;
    this.data = data;
    const record = (data ?? {}) as { held_by?: number | null; busy?: boolean };
    this.heldBy = record.held_by;
    this.busy = record.busy;
  }
}

/** Reads that find the session busy (another request or a step holds it) are tried again a few times. */
const BUSY_RETRIES = 3;
const BUSY_DELAY_MS = 300;

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await requestOnce<T>(method, path, body);
    } catch (reason) {
      if (!(reason instanceof ApiError) || !reason.busy || method !== "GET" || attempt >= BUSY_RETRIES) throw reason;
      await new Promise((resolve) => setTimeout(resolve, BUSY_DELAY_MS * (attempt + 1)));
    }
  }
}

async function requestOnce<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    throw new ApiError(response.status, typeof detail === "string" ? detail : response.statusText || `HTTP ${response.status}`, data);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};

const seg = encodeURIComponent;

export const status = () => api.get<Status>("/api/status");

export const repositories = {
  list: () => api.get<Repository[]>("/api/repositories"),
  info: (name: string) => api.get<Repository>(`/api/repositories/${seg(name)}`),
  clone: (url: string, name?: string, branch?: string) => api.post<Repository & { success: boolean }>("/api/repositories", { url, name: name || null, branch: branch || null }),
  remove: (name: string, force = false) => api.del<{ success: boolean }>(`/api/repositories/${seg(name)}?force=${force}`),
};

export const settings = {
  get: (key: string) => api.get<{ key: string; value: string | null }>(`/api/settings/${seg(key)}`),
  set: (key: string, value: string) => api.put<{ key: string; value: string }>(`/api/settings/${seg(key)}`, { value }),
};

export const fileTypes = {
  list: () => api.get<{ file_types: FileType[]; stats: Record<string, number> }>("/api/filetypes"),
  add: (fileType: FileType) => api.post<FileType>("/api/filetypes", fileType),
  update: (extension: string, fileType: string, subtype: string) => api.put<FileType>(`/api/filetypes/${seg(extension)}`, { file_type: fileType, subtype }),
  remove: (extension: string) => api.del<{ extension: string; deleted: boolean }>(`/api/filetypes/${seg(extension)}`),
};

export const configs = {
  list: (stepType: StepType) => api.get<ConfigRow[]>(`/api/configs/${stepType}`),
  save: (stepType: StepType, name: string, change: ConfigChange) => api.put<SaveResult>(`/api/configs/${stepType}/${seg(name)}`, change),
  setEnabled: (stepType: StepType, name: string, enabled: boolean) => api.put<{ name: string; enabled: boolean }>(`/api/configs/${stepType}/${seg(name)}/enabled`, { enabled }),
  versions: (stepType: StepType, name: string) => api.get<ConfigVersion[]>(`/api/configs/${stepType}/${seg(name)}/versions`),
  scan: (texts: Record<string, string>) => api.post<ScanResult>("/api/configs/scan", { texts }),
  dryRun: (name: string, query?: string) => api.post<DryRunResult>(`/api/configs/derivation/${seg(name)}/dry-run`, query === undefined ? {} : { query }),
};

export const graph = {
  stats: () => api.get<{ total_nodes: number; by_type: Record<string, number> }>("/api/graph/stats"),
  view: (database: "graph" | "model", limit = 300) => api.get<GraphView>(`/grafeo/view/${database}?limit=${limit}`),
  clear: () => api.del<{ success: boolean }>("/api/graph"),
};

export const model = {
  get: () => api.get<Model>("/api/model"),
  stats: () => api.get<{ total_elements: number; total_relationships: number; by_type: Record<string, number> }>("/api/model/stats"),
  clear: () => api.del<{ success: boolean }>("/api/model"),
  exportXml: (path: string) => api.post<{ success: boolean; path?: string; error?: string }>("/api/model/export", { path }),
};

export const runs = {
  start: (kind: RunKind, repository: string | null, noLlm: boolean) => api.post<{ run_id: string }>("/api/runs", { kind, repository, no_llm: noLlm }),
  current: () => api.get<RunSummary | null>("/api/runs/current"),
  cancel: (runId: string) => api.post<{ run_id: string }>(`/api/runs/${seg(runId)}/cancel`),
  calls: (runId: string) => api.get<LlmCallSummary[]>(`/api/runs/${seg(runId)}/calls`),
  call: (runId: string, callId: string) => api.get<LlmCall>(`/api/runs/${seg(runId)}/calls/${seg(callId)}`),
  history: (limit = 10) => api.get<{ run_id: number; description: string; is_active?: boolean; started_at: string | null }[]>(`/api/runs/history?limit=${limit}`),
};

const ids = (sessions: string[]) => sessions.map(encodeURIComponent).join(",");

export const benchmarks = {
  list: (limit = 20) => api.get<BenchmarkSession[]>(`/api/benchmarks?limit=${limit}`),
  models: () => api.get<BenchmarkModel[]>("/api/benchmarks/models"),
  start: (request: BenchmarkRequest) => api.post<{ run_id: string }>("/api/benchmarks", request),
  results: (sessions: string[]) => api.get<BenchmarkGroup[]>(`/api/benchmarks/results?sessions=${ids(sessions)}`),
  steps: (sessions: string[]) => api.get<Record<string, StepStability[]>>(`/api/benchmarks/steps?sessions=${ids(sessions)}`),
  flips: (sessions: string[], repo: string) => api.get<Flip[]>(`/api/benchmarks/flips?sessions=${ids(sessions)}&repo=${encodeURIComponent(repo)}`),
  inspector: (sessions: string[], repo: string) => api.get<InspectorView>(`/api/benchmarks/inspector?sessions=${ids(sessions)}&repo=${encodeURIComponent(repo)}`),
  exportUrl: (session: string) => `/api/benchmarks/${encodeURIComponent(session)}/export`,
};

export const modelConfigs = {
  list: () => api.get<ModelConfigRow[]>("/api/models"),
  save: (name: string, config: ModelConfigInput) => api.put<{ name: string; saved: boolean }>(`/api/models/${seg(name)}`, config),
  remove: (name: string) => api.del<null>(`/api/models/${seg(name)}`),
};

export const ontology = {
  intermediate: () => api.get<IntermediateOntology>("/api/ontology/intermediate"),
  output: () => api.get<OutputOntology>("/api/ontology/output"),
};

export const trace = {
  element: (elementId: string, runId: string | null) => api.get<Trace>(`/api/trace/${seg(elementId)}${runId ? `?run_id=${seg(runId)}` : ""}`),
};

export const session = {
  current: () => api.get<{ repository: string | null }>("/api/session"),
  useRepository: (repository: string) => api.put<{ repository: string }>("/api/session/repository", { repository }),
};
