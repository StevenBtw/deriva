import { useCallback, useEffect, useState } from "react";

import { fileTypes, modelConfigs, settings } from "../api/client";
import type { FileType, ModelConfigRow } from "../api/types";

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function ExcludedDirectories() {
  const [dirs, setDirs] = useState<string[] | null>(null);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    settings
      .get("excluded_directories")
      .then(({ value }) => {
        try {
          setDirs(value ? (JSON.parse(value) as string[]) : []);
        } catch {
          setDirs([]);
          setNote("The stored value is not a JSON list; saving replaces it.");
        }
      })
      .catch((reason) => setNote(message(reason)));
  }, []);

  const add = () => {
    const name = draft.trim();
    if (name && dirs && !dirs.includes(name)) setDirs([...dirs, name]);
    setDraft("");
  };

  const save = async () => {
    try {
      await settings.set("excluded_directories", JSON.stringify(dirs ?? []));
      setNote("Saved");
    } catch (reason) {
      setNote(message(reason));
    }
  };

  return (
    <div className="card">
      <div className="hd">
        <h3>Settings</h3>
        <button type="button" className="primary" style={{ marginLeft: "auto" }} onClick={() => void save()} disabled={dirs === null}>
          Save settings
        </button>
      </div>
      <div className="bd kv" style={{ gridTemplateColumns: "160px 1fr" }}>
        <span className="muted">excluded_directories</span>
        <div className="chipsrow">
          {(dirs ?? []).map((d) => (
            <span key={d} className="pill">
              {d}{" "}
              <button type="button" className="ghost" style={{ padding: 0, border: 0 }} aria-label={`Remove ${d}`} onClick={() => setDirs((dirs ?? []).filter((x) => x !== d))}>
                ×
              </button>
            </span>
          ))}
          <input
            aria-label="Add excluded directory"
            placeholder="+ add"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                add();
              }
            }}
            style={{ width: 110, padding: "1px 6px" }}
          />
        </div>
      </div>
      {note && <div className="bd note">{note}</div>}
    </div>
  );
}

function FileTypes() {
  const [rows, setRows] = useState<FileType[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [edit, setEdit] = useState({ file_type: "", subtype: "" });
  const [fresh, setFresh] = useState<FileType>({ extension: "", file_type: "", subtype: "" });
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    fileTypes
      .list()
      .then((data) => {
        setRows(data.file_types);
        setStats(data.stats);
      })
      .catch((reason) => setError(message(reason)));
  }, []);

  useEffect(load, [load]);

  const run = async (action: () => Promise<unknown>, after?: () => void) => {
    setError(null);
    try {
      await action();
      after?.();
      load();
    } catch (reason) {
      setError(message(reason));
    }
  };

  const shown = rows.filter((r) => `${r.extension} ${r.file_type} ${r.subtype}`.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="card">
      <div className="hd">
        <h3>File type registry</h3>
        <span className="muted">
          {rows.length} extensions · {Object.entries(stats).map(([t, n]) => `${t} ${n}`).join(" · ")}
        </span>
        <input aria-label="Filter file types" placeholder="filter" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ marginLeft: "auto", width: 140 }} />
      </div>
      {error && (
        <div className="bd error-text" role="alert">
          {error}
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th>Extension</th>
            <th>Type</th>
            <th>Subtype</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <input aria-label="New extension" placeholder=".ext" value={fresh.extension} onChange={(e) => setFresh({ ...fresh, extension: e.target.value })} style={{ width: 90 }} />
            </td>
            <td>
              <input aria-label="New type" placeholder="source" value={fresh.file_type} onChange={(e) => setFresh({ ...fresh, file_type: e.target.value })} style={{ width: 100 }} />
            </td>
            <td>
              <input aria-label="New subtype" placeholder="language" value={fresh.subtype} onChange={(e) => setFresh({ ...fresh, subtype: e.target.value })} style={{ width: 110 }} />
            </td>
            <td>
              <button
                type="button"
                disabled={!fresh.extension || !fresh.file_type}
                onClick={() => void run(() => fileTypes.add(fresh), () => setFresh({ extension: "", file_type: "", subtype: "" }))}
              >
                Add
              </button>
            </td>
          </tr>
          {shown.map((r) => (
            <tr key={r.extension}>
              <td className="mono">{r.extension}</td>
              {editing === r.extension ? (
                <>
                  <td>
                    <input aria-label={`Type of ${r.extension}`} value={edit.file_type} onChange={(e) => setEdit({ ...edit, file_type: e.target.value })} style={{ width: 100 }} />
                  </td>
                  <td>
                    <input aria-label={`Subtype of ${r.extension}`} value={edit.subtype} onChange={(e) => setEdit({ ...edit, subtype: e.target.value })} style={{ width: 110 }} />
                  </td>
                  <td>
                    <button type="button" onClick={() => void run(() => fileTypes.update(r.extension, edit.file_type, edit.subtype), () => setEditing(null))}>
                      Save
                    </button>{" "}
                    <button type="button" className="ghost" onClick={() => setEditing(null)}>
                      Cancel
                    </button>
                  </td>
                </>
              ) : (
                <>
                  <td>{r.file_type}</td>
                  <td>{r.subtype}</td>
                  <td>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => {
                        setEditing(r.extension);
                        setEdit({ file_type: r.file_type, subtype: r.subtype });
                      }}
                    >
                      Edit
                    </button>{" "}
                    <button
                      type="button"
                      className="ghost danger"
                      onClick={() => {
                        if (window.confirm(`Delete the file type ${r.extension}?`)) void run(() => fileTypes.remove(r.extension));
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const PROVIDERS = ["anthropic", "azure", "lmstudio", "mistral", "ollama", "openai"];

type Draft = { isNew: boolean; name: string; provider: string; model: string; url: string; key: string; keyEnv: string };

function draftOf(row?: ModelConfigRow): Draft {
  return row
    ? { isNew: false, name: row.name, provider: row.provider, model: row.model ?? "", url: row.url ?? "", key: "", keyEnv: row.key_env ?? "" }
    : { isNew: true, name: "", provider: PROVIDERS[0], model: "", url: "", key: "", keyEnv: "" };
}

/** The model configs in .env: keys are shown masked and only ever sent, never read back. */
function Models() {
  const [rows, setRows] = useState<ModelConfigRow[] | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    modelConfigs
      .list()
      .then(setRows)
      .catch((reason) => setNote(message(reason)));
  }, [reload]);

  const save = async () => {
    if (!draft) return;
    try {
      await modelConfigs.save(draft.name, {
        provider: draft.provider,
        model: draft.model,
        url: draft.url,
        key: draft.key || null,
        key_env: draft.keyEnv || null,
        structured_output: null,
      });
      setNote(`Saved ${draft.name}`);
      setDraft(null);
      setReload((n) => n + 1);
    } catch (reason) {
      setNote(message(reason));
    }
  };

  const remove = async (name: string) => {
    if (!window.confirm(`Remove the model config ${name} from .env?`)) return;
    try {
      await modelConfigs.remove(name);
      setNote(`Deleted ${name}`);
      setReload((n) => n + 1);
    } catch (reason) {
      setNote(message(reason));
    }
  };

  const field = (key: keyof Draft, label: string, type = "text", placeholder?: string) => (
    <>
      <label className="muted" htmlFor={`model-${key}`}>
        {label}
      </label>
      <input
        id={`model-${key}`}
        type={type}
        value={String(draft?.[key] ?? "")}
        placeholder={placeholder}
        disabled={key === "name" && !draft?.isNew}
        onChange={(e) => setDraft((d) => (d ? { ...d, [key]: e.target.value } : d))}
      />
    </>
  );

  return (
    <div className="card models">
      <div className="hd">
        <h3>Models</h3>
        <span className="note">LLM model configs in .env; API keys are write-only</span>
        <button type="button" style={{ marginLeft: "auto" }} onClick={() => setDraft(draftOf())}>
          Add model
        </button>
      </div>
      <div className="bd">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Provider</th>
              <th>Model</th>
              <th>URL</th>
              <th>Key</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {(rows ?? []).map((row) => (
              <tr key={row.name}>
                <td>{row.name}</td>
                <td>{row.provider}</td>
                <td className="mono">{row.model}</td>
                <td className="mono">{row.url ?? ""}</td>
                <td className="mono">{row.key ?? (row.key_env ? `from $${row.key_env}` : "not set")}</td>
                <td>
                  <button type="button" onClick={() => setDraft(draftOf(row))}>
                    Edit
                  </button>{" "}
                  <button type="button" className="danger" onClick={() => void remove(row.name)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {draft && (
          <div className="kv" style={{ gridTemplateColumns: "120px 1fr", marginTop: 10 }}>
            {field("name", "Model name")}
            <label className="muted" htmlFor="model-provider">
              Provider
            </label>
            <select id="model-provider" value={draft.provider} onChange={(e) => setDraft({ ...draft, provider: e.target.value })}>
              {PROVIDERS.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
            {field("model", "Model id")}
            {field("url", "API URL")}
            {field("key", "API key", "password", draft.isNew ? "not set" : "unchanged")}
            {field("keyEnv", "Key variable", "text", "optional: name of a variable holding the key")}
            <span />
            <div>
              <button type="button" className="primary" onClick={() => void save()} disabled={!draft.name || !draft.model}>
                Save model
              </button>{" "}
              <button type="button" className="ghost" onClick={() => setDraft(null)}>
                Cancel
              </button>
            </div>
          </div>
        )}
        {note && <div className="note">{note}</div>}
      </div>
    </div>
  );
}

export function General() {
  return (
    <section className="page">
      <div className="pagehead">
        <h2>General &amp; file types</h2>
        <span className="sub">System settings, the file type registry and the LLM model configs</span>
      </div>
      <div className="pad cols" style={{ gridTemplateColumns: "1fr 1.3fr", alignItems: "start" }}>
        <div className="stack">
          <ExcludedDirectories />
          <Models />
        </div>
        <FileTypes />
      </div>
    </section>
  );
}
