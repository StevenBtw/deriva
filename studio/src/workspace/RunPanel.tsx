import { useEffect, useState } from "react";

import { repositories, runs } from "../api/client";
import type { Repository, RunKind } from "../api/types";
import type { RunState } from "./useRun";

type Props = {
  run: RunState;
  onStart: (kind: RunKind, repository: string | null, noLlm: boolean) => void;
  onCancel: () => void;
  collapsed: boolean;
  onToggle: () => void;
  onRepositoryChange?: (repository: string) => void;
};

type HistoryRow = { run_id: number; description: string; started_at: string | null };

export function RunPanel({ run, onStart, onCancel, collapsed, onToggle, onRepositoryChange }: Props) {
  const [repos, setRepos] = useState<Repository[]>([]);
  const [repository, setRepository] = useState("");
  const [kind, setKind] = useState<RunKind>("all");
  const [noLlm, setNoLlm] = useState(false);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    repositories
      .list()
      .then((list) => {
        setRepos(list);
        setRepository((current) => current || list[0]?.name || "");
      })
      .catch((reason: Error) => setLoadError(reason.message));
    runs
      .history(8)
      .then(setHistory)
      .catch(() => setHistory([]));
  }, [run.status]);

  useEffect(() => {
    if (repository) onRepositoryChange?.(repository);
  }, [repository, onRepositoryChange]);

  const running = run.status === "running";

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
          <select id="run-repo" value={repository} onChange={(e) => setRepository(e.target.value)} disabled={running}>
            {repos.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name}
              </option>
            ))}
          </select>
        </div>
        <div className="fld">
          <label htmlFor="run-scope">Scope</label>
          <select id="run-scope" value={kind} onChange={(e) => setKind(e.target.value as RunKind)} disabled={running}>
            <option value="all">Everything (extraction + derivation)</option>
            <option value="extraction">Extraction only</option>
            <option value="derivation">Derivation only (current graph)</option>
          </select>
        </div>
        <label className="note" style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={noLlm} onChange={(e) => setNoLlm(e.target.checked)} disabled={running} />
          Structural steps only (without LLM)
        </label>
        {running ? (
          <button type="button" className="danger" onClick={onCancel}>
            ■ Cancel
          </button>
        ) : (
          <button type="button" className="go" onClick={() => onStart(kind, repository || null, noLlm)} disabled={!repository}>
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
              <div key={h.run_id}>
                <span>{h.description || `run ${h.run_id}`}</span>
                <span className="faint">{h.started_at?.slice(0, 16) ?? ""}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}
