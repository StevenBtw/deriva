import type {
  BenchmarkGroup,
  BenchmarkModel,
  BenchmarkRequest,
  BenchmarkSession,
  ConfigChange,
  ConfigRow,
  ConfigVersion,
  Coverage,
  DryRunResult,
  ElementTrace,
  FileType,
  Flip,
  GraphView,
  InspectorView,
  IntermediateOntology,
  LinkedView,
  LlmCall,
  LlmCallSummary,
  Model,
  ModelConfigInput,
  ModelConfigRow,
  ModelTest,
  ModelLevel,
  ModelQuality,
  OutputOntology,
  Repository,
  RepositoryData,
  RunKind,
  RunSummary,
  SaveResult,
  ScanResult,
  Status,
  StorageOverview,
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
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      // A plain text body (an unhandled server error) is kept as the message
      if (response.ok) throw new ApiError(response.status, "The answer is not JSON", text);
      data = text;
    }
  }
  if (!response.ok) throw new ApiError(response.status, errorMessage(response, data), data);
  return data as T;
}

/** An error answer's message: FastAPI's detail (its text, or the fields a validation error names), the body text, or the status. */
function errorMessage(response: Response, data: unknown): string {
  if (typeof data === "string" && data.trim()) return data.trim().slice(0, 300);
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((item: { loc?: unknown[]; msg?: string }) => {
      const where = (item.loc ?? []).filter((part) => part !== "body").join(".");
      return where ? `${where}: ${item.msg ?? ""}` : (item.msg ?? "");
    });
    if (parts.some(Boolean)) return parts.filter(Boolean).join("; ");
  }
  return response.statusText || `HTTP ${response.status}`;
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
  /** What was cloned: its name, branch, commit and size */
  clone: (url: string, name?: string, branch?: string) =>
    api.post<Repository & { success: boolean }>("/api/repositories", { url, name: name || null, branch: branch || null }),
  /** ``withData`` also deletes the repository's graph database (graph and model) */
  remove: (name: string, force = false, withData = false) =>
    api.del<{ success: boolean; data_deleted?: boolean }>(`/api/repositories/${seg(name)}?force=${force}&with_data=${withData}`),
  data: (name: string) => api.get<RepositoryData>(`/api/repositories/${seg(name)}/data`),
  /** What of the checkout reached the graph, and whether the extraction is complete */
  coverage: (name: string) => api.get<Coverage>(`/api/repositories/${seg(name)}/coverage`),
  clearModel: (name: string) => api.del<{ success: boolean }>(`/api/repositories/${seg(name)}/model`),
  /** The graph and the model */
  clearData: (name: string) => api.del<{ success: boolean }>(`/api/repositories/${seg(name)}/graph`),
  /** Git folders in the workspace without a record */
  unregistered: () => api.get<string[]>("/api/repositories/unregistered"),
  /** Record such a folder: its name, branch, commit and size */
  register: (name: string) => api.post<Repository & { success: boolean }>(`/api/repositories/${seg(name)}/register`),
  /** git pull --ff-only; the graph changes with the next extraction */
  update: (name: string) => api.post<{ success: boolean; repository: Repository }>(`/api/repositories/${seg(name)}/update`),
};

export const storage = {
  overview: () => api.get<StorageOverview>("/api/storage"),
  /** Every cached LLM answer: the next runs call the LLM again */
  clearLlmCache: () => api.del<{ bytes: number; files: number }>("/api/storage/llm-cache"),
  /** The exported exchange files (*.xml) in workspace/output */
  deleteExports: () => api.del<{ bytes: number; files: number }>("/api/storage/exports"),
  /** A graph database without a repository */
  deleteGraph: (key: string) => api.del<{ key: string; bytes: number }>(`/api/storage/graphs/${seg(key)}`),
};

export const settings = {
  /** ``default`` is the value that applies while the setting is not set */
  get: (key: string) => api.get<{ key: string; value: string | null; default?: string | null }>(`/api/settings/${seg(key)}`),
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
  /** An earlier version's texts and settings as the step's new version */
  restore: (stepType: StepType, name: string, version: number) =>
    api.post<{ success: boolean; old_version: number; new_version: number; restored: number }>(`/api/configs/${stepType}/${seg(name)}/versions/${version}/restore`),
  scan: (texts: Record<string, string>) => api.post<ScanResult>("/api/configs/scan", { texts }),
  dryRun: (name: string, query?: string) => api.post<DryRunResult>(`/api/configs/derivation/${seg(name)}/dry-run`, query === undefined ? {} : { query }),
};

export const graph = {
  stats: () => api.get<{ total_nodes: number; by_type: Record<string, number> }>("/api/graph/stats"),
  // Without a limit the studio samples as many graph nodes as its graph_view_nodes setting says (300 until set)
  view: (database: "graph" | "model", limit?: number) => api.get<GraphView>(`/grafeo/view/${database}${limit === undefined ? "" : `?limit=${limit}`}`),
  linked: (limit?: number) => api.get<LinkedView>(`/grafeo/view/linked${limit === undefined ? "" : `?limit=${limit}`}`),
  clear: () => api.del<{ success: boolean }>("/api/graph"),
};

export const model = {
  get: (level: ModelLevel = "architect") => api.get<Model>(`/api/model?level=${level}`),
  stats: () => api.get<{ total_elements: number; total_relationships: number; by_type: Record<string, number> }>("/api/model/stats"),
  /** The verdict on the model from its structure (a report) */
  quality: () => api.get<ModelQuality>("/api/model/quality"),
  clear: () => api.del<{ success: boolean }>("/api/model"),
  /** The exchange file to save in the browser, with the name the studio gave it (repository and time) */
  download: async (): Promise<{ blob: Blob; name: string }> => {
    const response = await fetch("/api/model/download");
    if (!response.ok) {
      const text = await response.text();
      let data: unknown = text;
      try {
        data = JSON.parse(text);
      } catch {
        // A plain text body is the message
      }
      throw new ApiError(response.status, errorMessage(response, data), data);
    }
    const name = /filename="([^"]+)"/.exec(response.headers.get("content-disposition") ?? "")?.[1] ?? "model.xml";
    return { blob: await response.blob(), name };
  },
};

export const runs = {
  start: (kind: RunKind, repository: string | null, noLlm: boolean) => api.post<{ run_id: string }>("/api/runs", { kind, repository, no_llm: noLlm }),
  current: () => api.get<RunSummary | null>("/api/runs/current"),
  cancel: (runId: string) => api.post<{ run_id: string }>(`/api/runs/${seg(runId)}/cancel`),
  calls: (runId: string) => api.get<LlmCallSummary[]>(`/api/runs/${seg(runId)}/calls`),
  call: (runId: string, callId: string) => api.get<LlmCall>(`/api/runs/${seg(runId)}/calls/${seg(callId)}`),
  history: (limit = 10, filter: { offset?: number; repository?: string | null; kind?: string | null } = {}) => {
    const query = new URLSearchParams({ limit: String(limit), offset: String(filter.offset ?? 0) });
    if (filter.repository) query.set("repository", filter.repository);
    if (filter.kind) query.set("kind", filter.kind);
    return api.get<RunSummary[]>(`/api/runs/history?${query}`);
  },
  /** A run's folder: summary, events, call log and inputs */
  remove: (runId: string) => api.del<{ deleted: string }>(`/api/runs/${seg(runId)}`),
  /** Every run past the latest ``keep``, or the interrupted ones; the run in progress stays */
  prune: (which: { keep: number } | { interrupted: true }) => api.post<{ deleted: string[] }>("/api/runs/prune", which),
};

const ids = (sessions: string[]) => sessions.map(encodeURIComponent).join(",");

export const benchmarks = {
  list: (limit = 20, filter: { offset?: number; search?: string | null; repository?: string | null; model?: string | null; status?: string | null } = {}) => {
    const query = new URLSearchParams({ limit: String(limit), offset: String(filter.offset ?? 0) });
    for (const key of ["search", "repository", "model", "status"] as const) {
      const value = filter[key];
      if (value) query.set(key, value);
    }
    return api.get<BenchmarkSession[]>(`/api/benchmarks?${query}`);
  },
  /** A finished or failed session with its runs, metrics and folder */
  remove: (sessionId: string) => api.del<{ session_id: string; runs: number; bytes: number }>(`/api/benchmarks/${encodeURIComponent(sessionId)}`),
  /** A session whose process stopped while it still says running */
  markFailed: (sessionId: string) => api.post<{ session_id: string; runs_marked: number }>(`/api/benchmarks/${encodeURIComponent(sessionId)}/mark-failed`),
  models: () => api.get<BenchmarkModel[]>("/api/benchmarks/models"),
  start: (request: BenchmarkRequest) => api.post<{ run_id: string }>("/api/benchmarks", request),
  results: (sessions: string[]) => api.get<BenchmarkGroup[]>(`/api/benchmarks/results?sessions=${ids(sessions)}`),
  steps: (sessions: string[]) => api.get<Record<string, StepStability[]>>(`/api/benchmarks/steps?sessions=${ids(sessions)}`),
  flips: (sessions: string[], repo: string) => api.get<Flip[]>(`/api/benchmarks/flips?sessions=${ids(sessions)}&repo=${encodeURIComponent(repo)}`),
  inspector: (sessions: string[], repo: string, model?: string) =>
    api.get<InspectorView>(`/api/benchmarks/inspector?sessions=${ids(sessions)}&repo=${encodeURIComponent(repo)}${model ? `&model=${encodeURIComponent(model)}` : ""}`),
  trace: (sessions: string[], repo: string, type: string, source: string, model?: string) =>
    api.get<ElementTrace[]>(
      `/api/benchmarks/trace?sessions=${ids(sessions)}&repo=${encodeURIComponent(repo)}&type=${encodeURIComponent(type)}&source=${encodeURIComponent(source)}${model ? `&model=${encodeURIComponent(model)}` : ""}`,
    ),
  exportUrl: (session: string) => `/api/benchmarks/${encodeURIComponent(session)}/export`,
  ocelUrl: (sessions: string[]) => `/api/benchmarks/ocel?sessions=${ids(sessions)}`,
};

export const modelConfigs = {
  list: () => api.get<ModelConfigRow[]>("/api/models"),
  save: (name: string, config: ModelConfigInput) => api.put<{ name: string; saved: boolean }>(`/api/models/${seg(name)}`, config),
  remove: (name: string) => api.del<null>(`/api/models/${seg(name)}`),
  /** One small call with the config (no cache): does its key, model id and URL work */
  test: (name: string) => api.post<ModelTest>(`/api/models/${seg(name)}/test`),
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
