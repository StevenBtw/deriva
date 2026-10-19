import { useCallback, useEffect, useState } from "react";

import { repositories } from "../api/client";
import type { Coverage, Repository, RepositoryData, RunSummary } from "../api/types";
import { downloadText } from "../components/download";
import { size } from "../components/size";

const count = (n: number) => n.toLocaleString("en-US");


/** "2026-10-18 22:41 · all · finished", or a dash when the repository has no such run */
function runLine(run: RunSummary | null): string {
  if (!run) return "none yet";
  const when = new Date(run.started_at * 1000);
  const pad = (n: number) => String(n).padStart(2, "0");
  const date = `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())} ${pad(when.getHours())}:${pad(when.getMinutes())}`;
  return `${date} · ${run.kind} · ${run.status}`;
}

/** "ef815ce improved classification" from git's "<full hash> <subject>" */
function shortCommit(commit: string | undefined): string {
  if (!commit) return "the latest commit";
  const [hash, ...subject] = commit.split(" ");
  return [hash.slice(0, 7), ...subject].join(" ");
}

/** The folder name a clone of the URL gets (its last path segment without .git) */
function nameFrom(url: string): string {
  const last = url.trim().replace(/\/+$/, "").split(/[/:]/).pop() ?? "";
  return last.replace(/\.git$/, "");
}

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

// The extensions with the most files; the CLI's coverage --json has every one
const EXTENSIONS_SHOWN = 8;

/** What of the checkout reached the graph: the verdict with its reasons, notes, the largest extensions, and the
 * files that did not make it as a download. */
function CoverageSection({ name, coverage, note }: { name: string; coverage: Coverage | null; note: string | null }) {
  if (!coverage) return <div className="bd note">{note ?? "Checking…"}</div>;
  const lost = [...coverage.missing.map((path) => `not in the graph: ${path}`), ...coverage.unreadable.map((u) => `could not be read: ${u.path}: ${u.reason}`)];
  return (
    <div className="bd">
      <div className={coverage.complete ? "ok" : "warn"}>{`${coverage.complete ? "Complete" : "Incomplete"}: ${count(coverage.in_graph)} of ${count(coverage.files)} files in the graph`}</div>
      {coverage.reasons.map((reason) => (
        <div key={reason} className="warn">
          {reason}
        </div>
      ))}
      {coverage.notes.map((text) => (
        <div key={text} className="note">
          {text}
        </div>
      ))}
      {lost.length > 0 && (
        <div className="row-actions">
          <button type="button" onClick={() => downloadText(lost, `${name}-coverage.txt`)}>
            {`Download the list (${lost.length})`}
          </button>
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th>Extension</th>
            <th>Files</th>
            <th>Read by</th>
            <th>Gave symbols</th>
          </tr>
        </thead>
        <tbody>
          {coverage.extensions.slice(0, EXTENSIONS_SHOWN).map((row) => (
            <tr key={row.extension}>
              <td className="mono">{row.extension}</td>
              <td>{row.in_graph === row.files ? count(row.files) : `${count(row.in_graph)} of ${count(row.files)}`}</td>
              <td>{row.reader ?? "none"}</td>
              <td>{row.reader ? count(row.with_symbols) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Repositories() {
  const [list, setList] = useState<Repository[]>([]);
  // Git folders in the workspace without a record (a lost record, a checkout put there by hand)
  const [unregistered, setUnregistered] = useState<string[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [branch, setBranch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // What the last clone or delete did (the detail card it was about may be gone)
  const [pageNote, setPageNote] = useState<string | null>(null);
  const [data, setData] = useState<RepositoryData | null>(null);
  const [dataNote, setDataNote] = useState<string | null>(null);
  // Per repository name: a slow answer for the last selection never shows under the next one
  const [coverage, setCoverage] = useState<{ name: string; report: Coverage | null; note: string | null } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [withData, setWithData] = useState(false);
  const [acting, setActing] = useState(false);

  const load = useCallback(() => {
    repositories
      .list()
      .then((rows) => {
        setList(rows);
        setSelected((current) => current ?? rows[0]?.name ?? null);
      })
      .catch((reason: Error) => setError(reason.message));
    repositories
      .unregistered()
      .then(setUnregistered)
      .catch(() => setUnregistered([]));
  }, []);

  useEffect(load, [load]);

  // What the selected repository's graph database holds; another repository's counts wait for a run to end
  const loadData = useCallback((name: string) => {
    repositories
      .data(name)
      .then((rows) => {
        setData(rows);
        setDataNote(null);
      })
      .catch((reason) => {
        setData(null);
        setDataNote(message(reason));
      });
    repositories
      .coverage(name)
      .then((report) => setCoverage({ name, report, note: null }))
      .catch((reason) => setCoverage({ name, report: null, note: message(reason) }));
  }, []);

  useEffect(() => {
    if (selected) loadData(selected);
  }, [selected, loadData]);

  // A new selection starts without the last one's notice and delete option
  const choose = (name: string) => {
    if (name === selected) return;
    setNotice(null);
    setDataNote(null);
    setWithData(false);
    setSelected(name);
  };

  const repo = list.find((r) => r.name === selected) ?? null;
  const shown = data && data.repository === selected ? data : null;

  const act = async (action: () => Promise<unknown>, done: string, reloadList = false) => {
    if (!repo) return;
    setActing(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      setNotice(done);
      loadData(repo.name);
      if (reloadList) load();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setActing(false);
    }
  };

  const clearModel = () => {
    if (!repo || !shown) return;
    const what = `${count(shown.model.elements)} elements and ${count(shown.model.relationships)} relationships`;
    if (!window.confirm(`Clear the model of ${repo.name} (${what})? The graph stays; the next derivation builds the model again.`)) return;
    void act(() => repositories.clearModel(repo.name), "Model cleared");
  };

  const clearData = () => {
    if (!repo || !shown) return;
    const what = `${count(shown.graph.nodes)} graph nodes and ${count(shown.model.elements)} model elements`;
    if (!window.confirm(`Clear the graph and the model of ${repo.name} (${what})? The next extraction starts from nothing.`)) return;
    void act(() => repositories.clearData(repo.name), "Graph and model cleared");
  };

  const update = async () => {
    if (!repo) return;
    setActing(true);
    setError(null);
    setNotice(null);
    try {
      const result = await repositories.update(repo.name);
      const commit = shortCommit(result.repository.last_commit);
      setNotice(result.repository.last_commit === repo.last_commit ? `Already up to date at ${commit}` : `Updated to ${commit}; run extraction to read it`);
      load();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setActing(false);
    }
  };

  const clone = async () => {
    setBusy(true);
    setError(null);
    setPageNote(null);
    try {
      const cloned = await repositories.clone(url, name, branch);
      const size = cloned.size_mb !== undefined ? `, ${cloned.size_mb.toFixed(1)} MB` : "";
      setPageNote(`Cloned ${cloned.name}: branch ${cloned.branch ?? "default"} at ${shortCommit(cloned.last_commit)}${size}. Run it from the Workspace.`);
      setCloneOpen(false);
      setUrl("");
      setName("");
      setBranch("");
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const register = async (folder: string) => {
    setError(null);
    setPageNote(null);
    try {
      const registered = await repositories.register(folder);
      setPageNote(`Registered ${registered.name}: branch ${registered.branch ?? "default"} at ${shortCommit(registered.last_commit)}. Run it from the Workspace.`);
      load();
    } catch (reason) {
      setError(message(reason));
    }
  };

  // A stale record goes without touching files: its folder is gone, or holds no clone
  const removeRecord = async () => {
    if (!repo?.stale) return;
    const also = withData ? " Its graph and model are deleted too." : "";
    if (!window.confirm(`Remove the record of ${repo.name}? Its folder ${repo.stale.replace(/^its folder /, "")}; no files are deleted.${also}`)) return;
    try {
      const result = await repositories.remove(repo.name, false, withData);
      setPageNote(result.data_deleted ? `Removed the record of ${repo.name} with its graph and model.` : `Removed the record of ${repo.name}.`);
      setSelected(null);
      load();
    } catch (reason) {
      setError(message(reason));
    }
  };

  const remove = async () => {
    if (!repo) return;
    if (repo.stale) return removeRecord();
    const warning = repo.is_dirty ? " It has uncommitted changes; they will be lost." : "";
    const also = withData ? " and its graph and model" : "";
    if (!window.confirm(`Delete the clone of ${repo.name}${also} from the workspace?${warning}`)) return;
    try {
      const result = await repositories.remove(repo.name, Boolean(repo.is_dirty), withData);
      setPageNote(
        result.data_deleted
          ? `Deleted ${repo.name} with its graph and model.`
          : `Deleted the clone of ${repo.name}. Its graph and model stay; Runs & storage can delete them.`,
      );
      setSelected(null);
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  return (
    <section className="page">
      <div className="pagehead">
        <h2>Repositories</h2>
        <span className="sub">Cloned sources in the workspace</span>
        <div className="actions">
          <button type="button" className="primary" onClick={() => setCloneOpen((o) => !o)}>
            + Clone repository
          </button>
        </div>
      </div>
      <div className="pad cols" style={{ gridTemplateColumns: "1.6fr 1fr" }}>
        <div className="card">
          {cloneOpen && (
            <form
              className="hd"
              style={{ gap: 6, flexWrap: "wrap" }}
              onSubmit={(e) => {
                e.preventDefault();
                void clone();
              }}
            >
              <label className="note" htmlFor="clone-url">
                Git URL
              </label>
              <input id="clone-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/org/repo.git" style={{ flex: 1, minWidth: 220 }} required />
              <label className="note" htmlFor="clone-name">
                Name (optional)
              </label>
              <input id="clone-name" value={name} onChange={(e) => setName(e.target.value)} placeholder={nameFrom(url)} style={{ width: 140 }} />
              <label className="note" htmlFor="clone-branch">
                Branch (optional)
              </label>
              <input id="clone-branch" value={branch} onChange={(e) => setBranch(e.target.value)} style={{ width: 120 }} />
              <button type="submit" className="go" disabled={busy || !url}>
                Clone
              </button>
            </form>
          )}
          {busy && (
            <div className="bd note" role="status">
              {`Cloning ${url}… a large repository takes longer`}
            </div>
          )}
          {error && (
            <div className="bd error-text" role="alert">
              {error}
            </div>
          )}
          {pageNote && !busy && (
            <div className="bd ok" role="status">
              {pageNote}
            </div>
          )}
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Branch · commit</th>
                <th>Size</th>
                <th>State</th>
              </tr>
            </thead>
            <tbody>
              {list.map((r) => (
                <tr
                  key={r.name}
                  className={`clickable${r.name === selected ? " sel" : ""}`}
                  // A tab stop per row: Enter or Space selects it, as a click does
                  tabIndex={0}
                  onClick={() => choose(r.name)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      choose(r.name);
                    }
                  }}
                >
                  <td>{r.name}</td>
                  <td className="mono">
                    {r.branch ?? ""} · {(r.last_commit ?? "").slice(0, 7)}
                  </td>
                  <td>{r.size_mb !== undefined ? `${r.size_mb.toFixed(1)} MB` : ""}</td>
                  {r.stale ? (
                    <td className="warn" title={r.stale}>
                      stale
                    </td>
                  ) : (
                    <td className={r.is_dirty ? "warn" : "ok"}>{r.is_dirty ? "changed" : "clean"}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {list.length === 0 && <div className="empty">No repositories cloned yet.</div>}
          {unregistered.length > 0 && (
            <div className="bd row-actions" style={{ flexWrap: "wrap" }}>
              <span className="note">Git folders in the workspace without a record:</span>
              {unregistered.map((folder) => (
                <button type="button" key={folder} aria-label={`Register ${folder}`} title="Record this folder so it can be run" onClick={() => void register(folder)}>
                  Register {folder}
                </button>
              ))}
            </div>
          )}
        </div>
        {repo && (
          <div className="card">
            <div className="hd">
              <h3>{repo.name}</h3>
              {repo.stale ? (
                <span className="pill warn">{`stale: ${repo.stale}`}</span>
              ) : (
                <span className={`pill ${repo.is_dirty ? "warn" : "ok"}`}>{repo.is_dirty ? "uncommitted changes" : "clean"}</span>
              )}
            </div>
            <div className="bd kv" style={{ gridTemplateColumns: "100px 1fr" }}>
              <span className="muted">Path</span>
              <span className="mono">{repo.path}</span>
              <span className="muted">Remote</span>
              <span className="mono">{repo.url}</span>
              <span className="muted">Branch</span>
              <span>{repo.branch}</span>
              <span className="muted">Last commit</span>
              <span className="mono">{repo.last_commit}</span>
              <span className="muted">Cloned</span>
              <span>{repo.cloned_at?.slice(0, 16) ?? ""}</span>
            </div>
            <div className="hd">
              <h3>Graph database</h3>
            </div>
            {shown ? (
              <div className="bd kv" style={{ gridTemplateColumns: "100px 1fr" }}>
                <span className="muted">Graph</span>
                <span>
                  {count(shown.graph.nodes)} nodes · {count(shown.graph.edges)} edges
                </span>
                <span className="muted">Model</span>
                <span>
                  {count(shown.model.elements)} elements · {count(shown.model.relationships)} relationships
                </span>
                <span className="muted">On disk</span>
                <span>{size(shown.database_bytes)}</span>
                <span className="muted">Extraction</span>
                <span>{runLine(shown.last_runs.extraction)}</span>
                <span className="muted">Derivation</span>
                <span>{runLine(shown.last_runs.derivation)}</span>
              </div>
            ) : (
              <div className="bd note">{dataNote ?? "Counting…"}</div>
            )}
            <div className="hd">
              <h3>Coverage</h3>
            </div>
            <CoverageSection name={repo.name} coverage={coverage?.name === repo.name ? coverage.report : null} note={coverage?.name === repo.name ? coverage.note : null} />
            {notice && (
              <div className="bd ok" role="status">
                {notice}
              </div>
            )}
            <div className="bd row-actions" style={{ flexWrap: "wrap" }}>
              <button type="button" disabled={acting || Boolean(repo.stale)} onClick={() => void update()}>
                Update clone
              </button>
              <button type="button" disabled={acting || !shown} onClick={clearModel}>
                Clear model
              </button>
              <button type="button" disabled={acting || !shown} onClick={clearData}>
                Clear graph and model
              </button>
              <label className="note" style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
                <input type="checkbox" checked={withData} onChange={(e) => setWithData(e.target.checked)} />
                also delete its graph and model
              </label>
              <button type="button" className="danger" disabled={acting} onClick={() => void remove()}>
                Delete
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
