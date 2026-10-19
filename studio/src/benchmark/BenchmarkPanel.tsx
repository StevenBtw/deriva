import { useEffect, useState } from "react";

import { benchmarks, repositories } from "../api/client";
import type { BenchmarkModel, BenchmarkRequest } from "../api/types";
import { SessionList } from "./SessionList";
import type { BenchmarkRunState } from "./useBenchmarkRun";

type Kind = "end_to_end" | "derivation";

type Props = {
  run: BenchmarkRunState;
  selected: string[];
  onToggleSession: (sessionId: string) => void;
  /** Deleted sessions leave the selection */
  onRemovedSessions: (sessionIds: string[]) => void;
  /** Bumped when a benchmark ended: the session list reads again */
  reload: number;
  onStart: (request: BenchmarkRequest) => void;
  onCancel: () => void;
  collapsed: boolean;
  onToggle: () => void;
};

/** The request a form describes: end to end runs separate one-run sessions; derivation only runs on the current graphs. */
function request(kind: Kind, repos: string[], model: string, runCount: number, useCache: boolean): BenchmarkRequest {
  const endToEnd = kind === "end_to_end";
  return {
    repositories: repos,
    model,
    runs: runCount,
    stages: endToEnd ? null : ["derivation"],
    use_cache: useCache,
    per_repo: true,
    separate_sessions: endToEnd,
    no_cache_extraction: endToEnd && !useCache,
  };
}

export function BenchmarkPanel({ run, selected, onToggleSession, onRemovedSessions, reload, onStart, onCancel, collapsed, onToggle }: Props) {
  const [repos, setRepos] = useState<string[]>([]);
  const [models, setModels] = useState<BenchmarkModel[]>([]);
  const [kind, setKind] = useState<Kind>("end_to_end");
  const [picked, setPicked] = useState<string[]>([]);
  const [runCount, setRunCount] = useState(3);
  const [model, setModel] = useState("");
  const [useCache, setUseCache] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    repositories
      .list()
      .then((list) => setRepos(list.map((r) => r.name)))
      .catch((reason: Error) => setLoadError(reason.message));
    benchmarks
      .models()
      .then((list) => {
        setModels(list);
        // The model Deriva uses (LLM_DEFAULT_MODEL) first, else the first configured one
        setModel((current) => current || (list.find((m) => m.default) ?? list[0])?.name || "");
      })
      .catch((reason: Error) => setLoadError(reason.message));
  }, []);

  const running = run.status === "running";
  const togglePick = (name: string) => setPicked((p) => (p.includes(name) ? p.filter((x) => x !== name) : [...p, name]));

  return (
    <aside className={`runpanel${collapsed ? " collapsed" : ""}`}>
      <div className="ph">
        <button type="button" className="ghost" aria-label={collapsed ? "Expand benchmark panel" : "Collapse benchmark panel"} onClick={onToggle} style={{ padding: "2px 6px" }}>
          {collapsed ? "»" : "«"}
        </button>
        <b>Benchmark configuration</b>
      </div>
      <div className="pb">
        <div className="fld">
          <label htmlFor="bench-kind">Type</label>
          <select id="bench-kind" value={kind} onChange={(e) => setKind(e.target.value as Kind)} disabled={running}>
            <option value="end_to_end">End to end (separate sessions)</option>
            <option value="derivation">Derivation only (current graphs)</option>
          </select>
        </div>
        <div className="fld">
          <label>Repositories</label>
          <div className="checks">
            {repos.map((name) => (
              <button key={name} type="button" className={`pill${picked.includes(name) ? " on" : ""}`} aria-pressed={picked.includes(name)} onClick={() => togglePick(name)} disabled={running}>
                {name}
              </button>
            ))}
          </div>
        </div>
        <div className="fld">
          <label htmlFor="bench-runs">Runs per repository</label>
          <input id="bench-runs" type="number" min={1} max={20} value={runCount} onChange={(e) => setRunCount(Math.min(20, Math.max(1, Math.trunc(Number(e.target.value)) || 1)))} disabled={running} />
        </div>
        <div className="fld">
          <label htmlFor="bench-model">Model</label>
          <select id="bench-model" value={model} onChange={(e) => setModel(e.target.value)} disabled={running}>
            {models.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name}
              </option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="bench-cache">Cache policy</label>
          <select id="bench-cache" value={useCache ? "cached" : "nocache"} onChange={(e) => setUseCache(e.target.value === "cached")} disabled={running}>
            <option value="nocache">No cache (measure consistency)</option>
            <option value="cached">Cached (verify a technical change)</option>
          </select>
        </div>
        <div className="fld">
          <label htmlFor="bench-samples">Samples per LLM call</label>
          <input id="bench-samples" type="text" value="1 (fixed)" disabled />
        </div>
        {running ? (
          <button type="button" className="danger" onClick={onCancel}>
            ■ Cancel
          </button>
        ) : (
          <button type="button" className="go" onClick={() => onStart(request(kind, picked, model, runCount, useCache))} disabled={!picked.length || !model}>
            ▶ Start benchmark
          </button>
        )}
        {run.error && <div className="error-text">{run.error}</div>}
        {loadError && <div className="error-text">{loadError}</div>}
        <SessionList selected={selected} onToggle={onToggleSession} onRemoved={onRemovedSessions} repositories={repos} models={models.map((m) => m.name)} reload={reload} />
        {selected.length === 1 && (
          <a className="util" href={benchmarks.exportUrl(selected[0])} download>
            ⤓ Export logs
          </a>
        )}
        {selected.length > 0 && (
          <a className="util" href={benchmarks.ocelUrl(selected)} download title="OCEL 2.0 and a case log (one case per run, CSV and XES) for PM4Py, ProM or Disco">
            ⤓ Process mining logs
          </a>
        )}
      </div>
    </aside>
  );
}
