import { useCallback, useEffect, useState } from "react";

import { benchmarks } from "../api/client";
import type { BenchmarkSession } from "../api/types";
import { size } from "../components/size";

const PAGE = 20;
const STATUSES = ["completed", "failed", "running"] as const;

type Props = {
  selected: string[];
  onToggle: (sessionId: string) => void;
  /** Sessions that were deleted (they leave the selection) */
  onRemoved: (sessionIds: string[]) => void;
  repositories: string[];
  models: string[];
  /** Bumped when a benchmark ended: the list reads again */
  reload: number;
};

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "2 repositories · mistral-small4 · 6 runs · 120.0 MB" */
function summary(s: BenchmarkSession): string {
  const parts = [
    s.repositories ? `${s.repositories.length} ${s.repositories.length === 1 ? "repository" : "repositories"}` : null,
    s.models?.length ? s.models.join(", ") : null,
    s.runs !== undefined ? plural(s.runs, "run") : null,
    s.bytes !== undefined ? size(s.bytes) : null,
  ];
  return parts.filter(Boolean).join(" · ");
}

/** The benchmark sessions, newest first and a page at a time, found by text, repository, model and status; the selected ones can be deleted (or marked failed while they still say running). */
export function SessionList({ selected, onToggle, onRemoved, repositories, models, reload }: Props) {
  const [rows, setRows] = useState<BenchmarkSession[]>([]);
  const [more, setMore] = useState(false);
  const [search, setSearch] = useState("");
  const [repository, setRepository] = useState("");
  const [model, setModel] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const page = useCallback(
    (offset: number) =>
      benchmarks.list(PAGE, { offset, search: search || null, repository: repository || null, model: model || null, status: status || null }).then((found) => {
        setRows((shown) => (offset === 0 ? found : [...shown, ...found]));
        setMore(found.length === PAGE);
      }),
    [search, repository, model, status],
  );

  useEffect(() => {
    page(0).catch((reason) => setError(message(reason)));
  }, [page, reload]);

  const chosen = rows.filter((r) => selected.includes(r.session_id));
  const running = chosen.filter((r) => r.status === "running");

  const act = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  };

  const remove = () =>
    act(async () => {
      const bytes = chosen.reduce((sum, r) => sum + (r.bytes ?? 0), 0);
      if (!window.confirm(`Delete ${plural(chosen.length, "benchmark session")} (${size(bytes)}) with ${chosen.length === 1 ? "its runs, metrics and folder" : "their runs, metrics and folders"}?`)) return;
      const gone: string[] = [];
      try {
        for (const s of chosen) {
          await benchmarks.remove(s.session_id);
          gone.push(s.session_id);
        }
      } finally {
        if (gone.length) {
          onRemoved(gone);
          await page(0);
        }
      }
    });

  const markFailed = () =>
    act(async () => {
      const names = running.map((r) => r.session_id).join(", ");
      if (!window.confirm(`Mark ${names} failed? Do this only when its process has stopped; its files stay.`)) return;
      for (const s of running) await benchmarks.markFailed(s.session_id);
      await page(0);
    });

  return (
    <div className="fld">
      <label htmlFor="session-search">Sessions</label>
      <input id="session-search" aria-label="Search sessions" placeholder="Search id or description" value={search} onChange={(e) => setSearch(e.target.value)} />
      <div style={{ display: "flex", gap: 4 }}>
        <select aria-label="Session repository" value={repository} onChange={(e) => setRepository(e.target.value)}>
          <option value="">every repository</option>
          {repositories.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
        <select aria-label="Session model" value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="">every model</option>
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        <select aria-label="Session status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">any status</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>
      <div className="runlist">
        {rows.length === 0 && <div className="faint">No benchmark sessions</div>}
        {rows.map((s) => (
          <button key={s.session_id} type="button" className={`runrow${selected.includes(s.session_id) ? " on" : ""}`} aria-pressed={selected.includes(s.session_id)} onClick={() => onToggle(s.session_id)}>
            <span>
              {s.session_id}
              <span className="faint" style={{ display: "block", fontSize: 11 }}>
                {s.started_at ? s.started_at.replace("T", " ").slice(0, 16) : ""}
                {s.description ? ` · ${s.description}` : ""}
              </span>
              <span className="faint" style={{ display: "block", fontSize: 11 }}>
                {summary(s)}
              </span>
            </span>
            <span className={s.status === "completed" ? "ok" : s.status === "failed" ? "bad" : "faint"}>{s.status}</span>
          </button>
        ))}
      </div>
      {more && (
        <button type="button" className="ghost" onClick={() => void act(() => page(rows.length))}>
          Show more
        </button>
      )}
      {error && (
        <div className="error-text" role="alert">
          {error}
        </div>
      )}
      {chosen.length > 0 && (
        <div style={{ display: "flex", gap: 6 }}>
          {running.length > 0 ? (
            <button type="button" disabled={busy} onClick={() => void markFailed()}>
              Mark failed
            </button>
          ) : (
            <button type="button" className="danger" disabled={busy} onClick={() => void remove()}>
              {`Delete ${plural(chosen.length, "session")}`}
            </button>
          )}
        </div>
      )}
      <div className="note">Pick several sessions to read them as one set of runs (end-to-end sessions hold one run each).</div>
    </div>
  );
}
