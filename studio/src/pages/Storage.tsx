import { useCallback, useEffect, useState } from "react";

import { runs as runsApi, storage as storageApi } from "../api/client";
import type { RunSummary, StorageOverview } from "../api/types";
import { size } from "../components/size";

const PAGE = 20;
const KINDS = ["all", "extraction", "derivation", "benchmark"] as const;

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function when(seconds: number): string {
  const date = new Date(seconds * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Every run the studio kept, a page at a time, by repository and kind; delete one, the interrupted ones, or all past the latest N. */
function Runs() {
  const [rows, setRows] = useState<RunSummary[]>([]);
  const [more, setMore] = useState(false);
  const [repository, setRepository] = useState("");
  const [kind, setKind] = useState("");
  const [keep, setKeep] = useState("20");
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const page = useCallback(
    (offset: number) =>
      runsApi.history(PAGE, { offset, repository: repository || null, kind: kind || null }).then((found) => {
        setRows((shown) => (offset === 0 ? found : [...shown, ...found]));
        setMore(found.length === PAGE);
      }),
    [repository, kind],
  );

  useEffect(() => {
    page(0).catch((reason) => setError(message(reason)));
  }, [page]);

  const guarded = async (action: () => Promise<void>) => {
    setError(null);
    setNote(null);
    try {
      await action();
    } catch (reason) {
      setError(message(reason));
    }
  };

  const remove = (row: RunSummary) =>
    guarded(async () => {
      if (!window.confirm(`Delete the run ${row.run_id} (${row.kind}${row.repository ? ` · ${row.repository}` : ""}, ${when(row.started_at)}) with its log and LLM calls?`)) return;
      await runsApi.remove(row.run_id);
      setRows((shown) => shown.filter((r) => r.run_id !== row.run_id));
    });

  const prune = (which: { keep: number } | { interrupted: true }, question: string) =>
    guarded(async () => {
      if (!window.confirm(question)) return;
      const { deleted } = await runsApi.prune(which);
      setNote(`Deleted ${plural(deleted.length, "run")}`);
      await page(0);
    });

  const kept = Number.parseInt(keep, 10);

  return (
    <div className="card">
      <div className="hd">
        <h3>Runs</h3>
        <span className="note">Each run keeps its live log, its LLM calls and its inputs; deleting a run removes them</span>
      </div>
      <div className="bd row-actions" style={{ flexWrap: "wrap" }}>
        <label className="note" htmlFor="runs-repository">
          Repository
        </label>
        <input id="runs-repository" value={repository} onChange={(e) => setRepository(e.target.value)} placeholder="all" style={{ width: 200 }} />
        <label className="note" htmlFor="runs-kind">
          Kind
        </label>
        <select id="runs-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">every kind</option>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
        <button
          type="button"
          style={{ marginLeft: "auto" }}
          onClick={() => void prune({ interrupted: true }, "Delete every interrupted run (its studio stopped before the run ended) with its log and LLM calls?")}
        >
          Delete interrupted runs
        </button>
        <label className="note" htmlFor="runs-keep">
          Keep the latest
        </label>
        <input id="runs-keep" type="number" min={0} value={keep} onChange={(e) => setKeep(e.target.value)} style={{ width: 64 }} />
        <button
          type="button"
          disabled={!Number.isInteger(kept) || kept < 0}
          onClick={() => void prune({ keep: kept }, `Keep the latest ${plural(kept, "run")} and delete every older run with its log and LLM calls?`)}
        >
          Delete older runs
        </button>
      </div>
      {error && (
        <div className="bd error-text" role="alert">
          {error}
        </div>
      )}
      {note && (
        <div className="bd ok" role="status">
          {note}
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Started</th>
            <th>Repository</th>
            <th>Kind</th>
            <th>Status</th>
            <th>Events</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.run_id}>
              <td className="mono">{row.run_id}</td>
              <td>{when(row.started_at)}</td>
              <td>{row.repository ?? ""}</td>
              <td>{row.kind}</td>
              <td className={row.status === "finished" ? "ok" : row.status === "running" ? "" : "warn"}>{row.status}</td>
              <td>{row.events}</td>
              <td>
                <button type="button" className="ghost" disabled={row.status === "running"} onClick={() => void remove(row)}>
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && <div className="empty">No runs kept.</div>}
      {more && (
        <div className="bd">
          <button type="button" onClick={() => void guarded(() => page(rows.length))}>
            Show more
          </button>
        </div>
      )}
    </div>
  );
}

const KIND_LABEL = { repository: "repository", shared: "shared graph", orphaned: "no repository" } as const;

/** What each area of the workspace takes on disk, with the actions that free it. */
function Disk() {
  const [data, setData] = useState<StorageOverview | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    storageApi
      .overview()
      .then(setData)
      .catch((reason) => setError(message(reason)));
  }, []);

  useEffect(load, [load]);

  const free = async (question: string, action: () => Promise<{ bytes: number }>) => {
    if (!window.confirm(question)) return;
    setError(null);
    setNote(null);
    try {
      const { bytes } = await action();
      setNote(`Freed ${size(bytes)}`);
      load();
    } catch (reason) {
      setError(message(reason));
    }
  };

  return (
    <div className="card">
      <div className="hd">
        <h3>Storage</h3>
        <span className="note">What the workspace keeps on disk</span>
      </div>
      {error && (
        <div className="bd error-text" role="alert">
          {error}
        </div>
      )}
      {note && (
        <div className="bd ok" role="status">
          {note}
        </div>
      )}
      {data && (
        <>
          <table>
            <thead>
              <tr>
                <th>Area</th>
                <th>Size</th>
                <th>Holds</th>
                <th />
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>LLM cache</td>
                <td>{size(data.llm_cache.bytes)}</td>
                <td>{plural(data.llm_cache.files, "file")}</td>
                <td>
                  <button
                    type="button"
                    disabled={data.llm_cache.files === 0}
                    onClick={() =>
                      void free(
                        `Clear the LLM cache (${size(data.llm_cache.bytes)})? Every later run then calls the LLM again for each prompt, which costs tokens, and an answer can differ from the cached one, so runs before and after compare less well.`,
                        storageApi.clearLlmCache,
                      )
                    }
                  >
                    Clear LLM cache
                  </button>
                </td>
              </tr>
              <tr>
                <td>Exported models</td>
                <td>{size(data.exports.bytes)}</td>
                <td>{plural(data.exports.files, "file")}</td>
                <td>
                  <button
                    type="button"
                    disabled={data.exports.files === 0}
                    onClick={() => void free(`Delete the ${plural(data.exports.files, "exported model")} (.xml) in workspace/output?`, storageApi.deleteExports)}
                  >
                    Delete exports
                  </button>
                </td>
              </tr>
              <tr>
                <td>Runs</td>
                <td>{size(data.runs.bytes)}</td>
                <td>{plural(data.runs.runs, "run")}</td>
                <td className="note">see Runs</td>
              </tr>
              <tr>
                <td>Benchmark sessions</td>
                <td>{size(data.benchmark_sessions.bytes)}</td>
                <td>{plural(data.benchmark_sessions.sessions, "session")}</td>
                <td className="note">in Benchmark mode</td>
              </tr>
            </tbody>
          </table>
          <div className="hd">
            <h3>Graph databases</h3>
            <span className="note">One per repository; a database whose repository was deleted can go here</span>
          </div>
          <table>
            <tbody>
              {data.graphs.map((g) => (
                <tr key={g.key}>
                  <td>{g.key}</td>
                  <td>{size(g.bytes)}</td>
                  <td className={g.kind === "orphaned" ? "warn" : ""}>
                    {KIND_LABEL[g.kind]}
                    {g.active ? " · open" : ""}
                  </td>
                  <td>
                    {g.kind !== "repository" && !g.active && (
                      <button
                        type="button"
                        className="ghost"
                        onClick={() => void free(`Delete the graph database ${g.key} (${size(g.bytes)}) with its graph and model?`, () => storageApi.deleteGraph(g.key))}
                      >
                        Delete
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

/** The workspace's runs and what it keeps on disk. */
export function Storage() {
  return (
    <section className="page">
      <div className="pagehead">
        <h2>Runs &amp; storage</h2>
        <span className="sub">The runs the studio kept and what the workspace holds on disk</span>
      </div>
      <div className="pad stack">
        <Disk />
        <Runs />
      </div>
    </section>
  );
}
