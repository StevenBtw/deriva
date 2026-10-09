import { useCallback, useEffect, useState } from "react";

import { repositories } from "../api/client";
import type { Repository } from "../api/types";

export function Repositories() {
  const [list, setList] = useState<Repository[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [cloneOpen, setCloneOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [branch, setBranch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    repositories
      .list()
      .then((rows) => {
        setList(rows);
        setSelected((current) => current ?? rows[0]?.name ?? null);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(load, [load]);

  const repo = list.find((r) => r.name === selected) ?? null;

  const clone = async () => {
    setBusy(true);
    setError(null);
    try {
      await repositories.clone(url, name, branch);
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

  const remove = async () => {
    if (!repo) return;
    const warning = repo.is_dirty ? " It has uncommitted changes; they will be lost." : "";
    if (!window.confirm(`Delete the clone of ${repo.name} from the workspace?${warning}`)) return;
    try {
      await repositories.remove(repo.name, Boolean(repo.is_dirty));
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
              <input id="clone-name" value={name} onChange={(e) => setName(e.target.value)} style={{ width: 140 }} />
              <label className="note" htmlFor="clone-branch">
                Branch (optional)
              </label>
              <input id="clone-branch" value={branch} onChange={(e) => setBranch(e.target.value)} style={{ width: 120 }} />
              <button type="submit" className="go" disabled={busy || !url}>
                Clone
              </button>
            </form>
          )}
          {error && (
            <div className="bd error-text" role="alert">
              {error}
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
                <tr key={r.name} className={`clickable${r.name === selected ? " sel" : ""}`} onClick={() => setSelected(r.name)}>
                  <td>{r.name}</td>
                  <td className="mono">
                    {r.branch ?? ""} · {(r.last_commit ?? "").slice(0, 7)}
                  </td>
                  <td>{r.size_mb !== undefined ? `${r.size_mb.toFixed(1)} MB` : ""}</td>
                  <td className={r.is_dirty ? "warn" : "ok"}>{r.is_dirty ? "changed" : "clean"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.length === 0 && <div className="empty">No repositories cloned yet.</div>}
        </div>
        {repo && (
          <div className="card">
            <div className="hd">
              <h3>{repo.name}</h3>
              <span className={`pill ${repo.is_dirty ? "warn" : "ok"}`}>{repo.is_dirty ? "uncommitted changes" : "clean"}</span>
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
            <div className="bd row-actions">
              <button type="button" className="danger" style={{ marginLeft: "auto" }} onClick={() => void remove()}>
                Delete
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
