import { Fragment, useCallback, useEffect, useState } from "react";

import { fileTypes, modelConfigs, settings } from "../api/client";
import type { FileType, ModelConfigRow, ModelTest } from "../api/types";

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

/** A JSON list of directory names, or null for anything else (a stored ``{}`` must not reach the chips). */
function directoryList(text: string): string[] | null {
  try {
    const value: unknown = JSON.parse(text);
    return Array.isArray(value) && value.every((d) => typeof d === "string")
      ? value
      : null;
  } catch {
    return null;
  }
}

function ExcludedDirectories() {
  const [dirs, setDirs] = useState<string[] | null>(null);
  const [draft, setDraft] = useState("");
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    settings
      .get("excluded_directories")
      .then(({ value, default: fallback }) => {
        if (value == null) {
          // Not set: the built-in list applies, so the editor starts from it (saving keeps those directories out)
          setDirs(fallback ? (directoryList(fallback) ?? []) : []);
          return;
        }
        const list = directoryList(value);
        setDirs(list ?? []);
        if (list === null)
          setNote(
            "The stored value is not a JSON list of names; saving replaces it.",
          );
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
        <button
          type="button"
          className="primary"
          style={{ marginLeft: "auto" }}
          onClick={() => void save()}
          disabled={dirs === null}
        >
          Save settings
        </button>
      </div>
      <div className="bd kv" style={{ gridTemplateColumns: "160px 1fr" }}>
        <span className="muted">excluded_directories</span>
        <div className="chipsrow">
          {(dirs ?? []).map((d) => (
            <span key={d} className="pill">
              {d}{" "}
              <button
                type="button"
                className="ghost"
                style={{ padding: 0, border: 0 }}
                aria-label={`Remove ${d}`}
                onClick={() => setDirs((dirs ?? []).filter((x) => x !== d))}
              >
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
  const [fresh, setFresh] = useState<FileType>({
    extension: "",
    file_type: "",
    subtype: "",
  });
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

  const shown = rows.filter((r) =>
    `${r.extension} ${r.file_type} ${r.subtype}`
      .toLowerCase()
      .includes(filter.toLowerCase()),
  );

  return (
    <div className="card">
      <div className="hd">
        <h3>File type registry</h3>
        <span className="muted">
          {rows.length} extensions ·{" "}
          {Object.entries(stats)
            .map(([t, n]) => `${t} ${n}`)
            .join(" · ")}
        </span>
        <input
          aria-label="Filter file types"
          placeholder="filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          style={{ marginLeft: "auto", width: 140 }}
        />
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
              <input
                aria-label="New extension"
                placeholder=".ext"
                value={fresh.extension}
                onChange={(e) =>
                  setFresh({ ...fresh, extension: e.target.value })
                }
                style={{ width: 90 }}
              />
            </td>
            <td>
              <input
                aria-label="New type"
                placeholder="source"
                value={fresh.file_type}
                onChange={(e) =>
                  setFresh({ ...fresh, file_type: e.target.value })
                }
                style={{ width: 100 }}
              />
            </td>
            <td>
              <input
                aria-label="New subtype"
                placeholder="language"
                value={fresh.subtype}
                onChange={(e) =>
                  setFresh({ ...fresh, subtype: e.target.value })
                }
                style={{ width: 110 }}
              />
            </td>
            <td>
              <button
                type="button"
                disabled={!fresh.extension || !fresh.file_type}
                onClick={() =>
                  void run(
                    () => fileTypes.add(fresh),
                    () =>
                      setFresh({ extension: "", file_type: "", subtype: "" }),
                  )
                }
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
                    <input
                      aria-label={`Type of ${r.extension}`}
                      value={edit.file_type}
                      onChange={(e) =>
                        setEdit({ ...edit, file_type: e.target.value })
                      }
                      style={{ width: 100 }}
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`Subtype of ${r.extension}`}
                      value={edit.subtype}
                      onChange={(e) =>
                        setEdit({ ...edit, subtype: e.target.value })
                      }
                      style={{ width: 110 }}
                    />
                  </td>
                  <td>
                    <button
                      type="button"
                      onClick={() =>
                        void run(
                          () =>
                            fileTypes.update(
                              r.extension,
                              edit.file_type,
                              edit.subtype,
                            ),
                          () => setEditing(null),
                        )
                      }
                    >
                      Save
                    </button>{" "}
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setEditing(null)}
                    >
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
                        if (
                          window.confirm(`Delete the file type ${r.extension}?`)
                        )
                          void run(() => fileTypes.remove(r.extension));
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

const PROVIDERS = [
  "anthropic",
  "azure",
  "lmstudio",
  "mistral",
  "ollama",
  "openai",
];

type Draft = {
  isNew: boolean;
  name: string;
  provider: string;
  model: string;
  url: string;
  key: string;
  keyEnv: string;
};

function draftOf(row?: ModelConfigRow): Draft {
  return row
    ? {
        isNew: false,
        name: row.name,
        provider: row.provider,
        model: row.model ?? "",
        url: row.url ?? "",
        key: "",
        keyEnv: row.key_env ?? "",
      }
    : {
        isNew: true,
        name: "",
        provider: PROVIDERS[0],
        model: "",
        url: "",
        key: "",
        keyEnv: "",
      };
}

/** The model configs in .env: keys are shown masked and only ever sent, never read back. */
/** How a model test went: what answered and how fast, or what to fix (the provider's message on hover). */
function TestResult({ result }: { result: ModelTest | "testing" }) {
  if (result === "testing")
    return <span className="note">Testing: one small call to the model…</span>;
  if (result.ok) {
    const seconds = ((result.latency_ms ?? 0) / 1000).toFixed(1);
    return (
      <span className="ok">{`Works: ${result.served_model || result.model_id} answered in ${seconds} s`}</span>
    );
  }
  return (
    <span className="error-text" title={result.detail ?? undefined}>
      {result.error}
    </span>
  );
}

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
        // An emptied field removes the variable ("" removes, null would keep it)
        key_env: draft.keyEnv,
      });
      setNote(`Saved ${draft.name}. Press Test to check its key and model id.`);
      setDraft(null);
      setReload((n) => n + 1);
    } catch (reason) {
      setNote(message(reason));
    }
  };

  // One small call per press; the answer stays under the model's row
  const [tests, setTests] = useState<Record<string, ModelTest | "testing">>({});
  const test = async (name: string) => {
    setTests((t) => ({ ...t, [name]: "testing" }));
    try {
      const result = await modelConfigs.test(name);
      setTests((t) => ({ ...t, [name]: result }));
    } catch (reason) {
      setTests((t) => ({
        ...t,
        [name]: {
          ok: false,
          model: name,
          provider: "",
          model_id: "",
          error: message(reason),
        },
      }));
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

  const field = (
    key: keyof Draft,
    label: string,
    type = "text",
    placeholder?: string,
  ) => (
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
        onChange={(e) =>
          setDraft((d) => (d ? { ...d, [key]: e.target.value } : d))
        }
      />
    </>
  );

  return (
    <div className="card models">
      <div className="hd">
        <h3>Models</h3>
        <span className="note">
          LLM model configs in .env; API keys are write-only
        </span>
        <button
          type="button"
          style={{ marginLeft: "auto" }}
          onClick={() => setDraft(draftOf())}
        >
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
              <Fragment key={row.name}>
                <tr>
                  <td>{row.name}</td>
                  <td>{row.provider}</td>
                  <td className="mono">{row.model}</td>
                  <td className="mono">{row.url ?? ""}</td>
                  <td className="mono">
                    {row.key ??
                      (row.key_env ? `from $${row.key_env}` : "not set")}
                  </td>
                  <td>
                    <button
                      type="button"
                      disabled={tests[row.name] === "testing"}
                      onClick={() => void test(row.name)}
                    >
                      Test
                    </button>{" "}
                    <button
                      type="button"
                      onClick={() => setDraft(draftOf(row))}
                    >
                      Edit
                    </button>{" "}
                    <button
                      type="button"
                      className="danger"
                      onClick={() => void remove(row.name)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
                {tests[row.name] && (
                  <tr>
                    <td colSpan={6}>
                      <TestResult result={tests[row.name]} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        {draft && (
          <div
            className="kv"
            style={{ gridTemplateColumns: "120px 1fr", marginTop: 10 }}
          >
            {field("name", "Model name")}
            <label className="muted" htmlFor="model-provider">
              Provider
            </label>
            <select
              id="model-provider"
              value={draft.provider}
              onChange={(e) => setDraft({ ...draft, provider: e.target.value })}
            >
              {PROVIDERS.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
            {field("model", "Model id")}
            {field("url", "API URL")}
            {field(
              "key",
              "API key",
              "password",
              draft.isNew ? "not set" : "unchanged",
            )}
            {field(
              "keyEnv",
              "Key variable",
              "text",
              "optional: name of a variable holding the key",
            )}
            <span />
            <div>
              <button
                type="button"
                className="primary"
                onClick={() => void save()}
                disabled={!draft.name || !draft.model}
              >
                Save model
              </button>{" "}
              <button
                type="button"
                className="ghost"
                onClick={() => setDraft(null)}
              >
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

const GRAPH_VIEW_NODES = "graph_view_nodes";

/** How many graph nodes the Workspace and Benchmark graph views sample (the model is always shown whole). */
function GraphViews() {
  const [draft, setDraft] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    settings
      .get(GRAPH_VIEW_NODES)
      .then(({ value, default: fallback }) =>
        setDraft(value ?? fallback ?? "300"),
      )
      .catch((reason) => setNote(message(reason)));
  }, []);

  const save = async () => {
    if (draft === null) return;
    try {
      const { value } = await settings.set(GRAPH_VIEW_NODES, draft.trim());
      setNote(
        `Saved: the graph views now sample ${Number(value).toLocaleString("en")} nodes (reopen a graph to see it).`,
      );
    } catch (reason) {
      setNote(message(reason));
    }
  };

  return (
    <div className="card">
      <div className="hd">
        <h3>Graph views</h3>
      </div>
      <div className="bd">
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <label htmlFor="graph-view-nodes">Nodes in the graph views</label>
          <input
            id="graph-view-nodes"
            type="number"
            min={50}
            max={5000}
            step={50}
            value={draft ?? ""}
            disabled={draft === null}
            style={{ width: 100 }}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void save()}
          />
          <button
            type="button"
            aria-label="Save the node count"
            disabled={draft === null}
            onClick={() => void save()}
          >
            Save
          </button>
        </div>
        <div className="note">
          The Workspace and Benchmark graphs show this many nodes of the graph
          (50 to 5,000; the model is always shown whole). More nodes show more
          of the graph and draw slower. A display setting: it changes no run.
        </div>
      </div>
      {note && <div className="bd note">{note}</div>}
    </div>
  );
}

const LLM_SAMPLES = "llm_samples";

/** Answers per LLM decision for the steps that vote; unset, each step keeps its own samples param. */
function LlmSamples() {
  const [draft, setDraft] = useState<string | null>(null);
  const [isSet, setIsSet] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    settings
      .get(LLM_SAMPLES)
      .then(({ value }) => {
        setIsSet(value !== null);
        setDraft(value ?? "1");
      })
      .catch((reason) => setNote(message(reason)));
  }, []);

  const save = async () => {
    if (draft === null) return;
    try {
      const { value } = await settings.set(LLM_SAMPLES, draft.trim());
      setIsSet(true);
      setNote(
        `Saved: every step that votes now asks ${value} times per decision (from the next run).`,
      );
    } catch (reason) {
      setNote(message(reason));
    }
  };

  const unset = async () => {
    try {
      await settings.unset(LLM_SAMPLES);
      setIsSet(false);
      setDraft("1");
      setNote(
        "Each step asks as many times as its own config says again (from the next run).",
      );
    } catch (reason) {
      setNote(message(reason));
    }
  };

  return (
    <div className="card">
      <div className="hd">
        <h3>LLM answers</h3>
      </div>
      <div className="bd">
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <label htmlFor="llm-samples">LLM answers per decision</label>
          <input
            id="llm-samples"
            type="number"
            min={1}
            max={20}
            step={1}
            value={draft ?? ""}
            disabled={draft === null}
            style={{ width: 70 }}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void save()}
          />
          <button
            type="button"
            aria-label="Save the answers per decision"
            disabled={draft === null}
            onClick={() => void save()}
          >
            Save
          </button>
          <button
            type="button"
            className="ghost"
            aria-label="Use each step's own setting"
            disabled={!isSet}
            onClick={() => void unset()}
          >
            Use each step&apos;s own
          </button>
        </div>
        <div className="note">
          {isSet
            ? "Set for every step that votes. "
            : "Not set: each step asks as many times as its own config says (1 by default). "}
          Steps that vote (directory classification, element naming) ask the
          same question this many times and keep the majority answer: steadier
          answers for everyday runs, at that many times the calls. Answers
          differ only when the model samples (a temperature above 0). Benchmark
          sessions record the value; measure consistency with 1.
        </div>
      </div>
      {note && <div className="bd note">{note}</div>}
    </div>
  );
}

const CLEAR_MODEL = "derivation_clear_model";

/** Whether full derivation runs start from an empty model (the default, as benchmarks do); a switch for deriva-dev. */
function DerivationRuns() {
  const [on, setOn] = useState<boolean | null>(null);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    settings
      .get(CLEAR_MODEL)
      .then(({ value }) =>
        setOn(
          value === null ||
            !["false", "0", "no", "off"].includes(value.trim().toLowerCase()),
        ),
      )
      .catch((reason) => setNote(message(reason)));
  }, []);

  const change = async (next: boolean) => {
    setOn(next);
    try {
      await settings.set(CLEAR_MODEL, next ? "true" : "false");
      setNote(null);
    } catch (reason) {
      setOn(!next);
      setNote(message(reason));
    }
  };

  return (
    <div className="card">
      <div className="hd">
        <h3>Derivation runs</h3>
      </div>
      <div className="bd">
        <label className="check">
          <input
            type="checkbox"
            checked={on ?? true}
            disabled={on === null}
            onChange={(e) => void change(e.target.checked)}
          />
          Full derivation runs start from an empty model
        </label>
        <div className="note">
          As benchmarks do. Switched off, a run builds on the model of an
          earlier run and skips every candidate that model already has, so it
          derives less. Runs of one phase or one step always keep the model.
        </div>
      </div>
      {note && <div className="bd note">{note}</div>}
    </div>
  );
}

export function General({ benchmark = true }: { benchmark?: boolean }) {
  return (
    <section className="page">
      <div className="pagehead">
        <h2>General &amp; file types</h2>
        <span className="sub">
          System settings, the file type registry and the LLM model configs
        </span>
      </div>
      <div
        className="pad cols"
        style={{ gridTemplateColumns: "1fr 1.3fr", alignItems: "start" }}
      >
        <div className="stack">
          <ExcludedDirectories />
          <GraphViews />
          <LlmSamples />
          {benchmark && <DerivationRuns />}
          <Models />
        </div>
        <FileTypes />
      </div>
    </section>
  );
}
