import { useEffect, useState } from "react";

import { repositories, runs, session } from "../api/client";
import type { Repository, RunKind, RunSummary } from "../api/types";
import type { RunState } from "./useRun";

type Props = {
  run: RunState;
  onStart: (kind: RunKind, repository: string | null, noLlm: boolean) => void | Promise<void>;
  onCancel: () => void;
  collapsed: boolean;
  onToggle: () => void;
  onRepositoryChange?: (repository: string) => void;
  onSelectRun?: (run: RunSummary) => void;
};

/** "derivation · deriva", plus the status when the run did not simply finish. */
function runLabel(run: RunSummary): string {
  return [run.kind, run.repository, run.status === "finished" ? null : run.status].filter(Boolean).join(" · ");
}

/** Local time as YYYY-MM-DD HH:MM. */
function runTime(seconds: number): string {
  const d = new Date(seconds * 1000);
  const two = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`;
}

export function RunPanel({ run, onStart, onCancel, collapsed, onToggle, onRepositoryChange, onSelectRun }: Props) {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [repository, setRepository] = useState("");
  const [kind, setKind] = useState<RunKind>("all");
  const [noLlm, setNoLlm] = useState(false);
  const [history, setHistory] = useState<RunSummary[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Locked from the click on: while the start request runs the server may have started the run already
  const [starting, setStarting] = useState(false);
  const running = run.status === "running";
  const locked = running || starting;

  const begin = async (repositoryName: string | null) => {
    setStarting(true);
    try {
      await onStart(kind, repositoryName, noLlm);
    } finally {
      setStarting(false);
    }
  };

  useEffect(() => {
    // The session's repository first (it answers busy while a step runs), then the first one cloned.
    // A fresh session reads the shared "default" graph, which is no repository and cannot be chosen.
    Promise.all([repositories.list(), session.current().catch(() => ({ repository: null }))])
      .then(([list, current]) => {
        setRepos(list);
        setLoadError(null);
        const cloned = list.some((r) => r.name === current.repository) ? current.repository : null;
        setRepository((shown) => shown || cloned || list[0]?.name || "");
      })
      .catch((reason: Error) => {
        // While a run holds the databases the list may be unavailable: the run's repository is shown below
        if (!running) setLoadError(reason.message);
      });
    runs
      .history(8)
      .then(setHistory)
      .catch(() => setHistory([]));
  }, [run.status, running]);

  // Switching the session's repository waits for the run to end
  useEffect(() => {
    if (repository && !running) onRepositoryChange?.(repository);
  }, [repository, running, onRepositoryChange]);

  // A run in progress (also one this page attached to) shows its repository
  const shown = running && run.repository ? run.repository : repository;
  const options = shown && !repos.some((r) => r.name === shown) ? [...repos, { name: shown } as Repository] : repos;

  return (
    <aside className={`runpanel${collapsed ? " collapsed" : ""}`}>
      <div className="ph">
        <button type="button" className="ghost" aria-label={collapsed ? "Expand run panel" : "Collapse run panel"} onClick={onToggle} style={{ padding: "2px 6px" }}>
          {collapsed ? "»" : "«"}
        </button>
        <b>Run configuration</b>
      </div>
      <div className="pb">
        <div className="fld">
          <label htmlFor="run-repo">Repository</label>
          <select id="run-repo" value={shown} onChange={(e) => setRepository(e.target.value)} disabled={locked}>
            {options.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="run-scope">Scope</label>
          <select id="run-scope" value={kind} onChange={(e) => setKind(e.target.value as RunKind)} disabled={locked}>
            <option value="all">Everything (extraction + derivation)</option>
            <option value="extraction">Extraction only</option>
            <option value="derivation">Derivation only (current graph)</option>
          </select>
        </div>
        <label className="note" style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={noLlm} onChange={(e) => setNoLlm(e.target.checked)} disabled={locked} />
          Structural steps only (without LLM)
        </label>
        {running ? (
          <button type="button" className="danger" onClick={onCancel}>
            ■ Cancel
          </button>
        ) : (
          <button type="button" className="go" onClick={() => void begin(shown || null)} disabled={!shown || starting}>
            Run
          </button>
        )}
        {run.error && <div className="error-text">{run.error}</div>}
        {loadError && <div className="error-text">{loadError}</div>}
        <div className="fld">
          <label>Recent runs</label>
          <div className="runlist">
            {history.length === 0 && <div className="faint">No runs recorded yet</div>}
            {history.map((h) => (
              <button
                key={h.run_id}
                type="button"
                className={`runrow${run.runId === h.run_id ? " on" : ""}`}
                aria-pressed={run.runId === h.run_id}
                onClick={() => onSelectRun?.(h)}
                disabled={running && run.runId !== h.run_id}
              >
                <span>{runLabel(h)}</span>
                <span className="faint">{runTime(h.started_at)}</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}
