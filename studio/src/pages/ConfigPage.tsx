import { useCallback, useEffect, useRef, useState } from "react";

import { configs } from "../api/client";
import type { ConfigChange, ConfigRow, ConfigVersion, DryRunResult, ScanResult, StepType } from "../api/types";
import { CodeEditor } from "../components/CodeEditor";
import { lineDiff } from "../components/diff";

type Props = { stepType: StepType; title: string };
type Tab = "instruction" | "example" | "params" | "query" | "history";
type Status = { kind: "ok" | "error"; text: string } | null;

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

type EditorProps = {
  stepType: StepType;
  row: ConfigRow;
  status: Status;
  onStatus: (status: Status) => void;
  onDirty: (dirty: boolean) => void;
  onSaved: () => void;
};

type Draft = { instruction: string; example: string; params: string; query: string; batchSize: string };

function draftOf(row: ConfigRow): Draft {
  return {
    instruction: row.instruction ?? "",
    example: row.example ?? "",
    params: typeof row.params === "string" ? row.params : "",
    query: typeof row.input_graph_query === "string" ? row.input_graph_query : "",
    batchSize: row.batch_size == null ? "" : String(row.batch_size),
  };
}

/** What the draft changes against the stored row, as the API takes it. */
function changesOf(row: ConfigRow, d: Draft, stepType: StepType): ConfigChange {
  const stored = draftOf(row);
  const changes: ConfigChange = {};
  if (d.instruction !== stored.instruction) changes.instruction = d.instruction;
  if (d.example !== stored.example) changes.example = d.example;
  if (d.params !== stored.params) changes.params = d.params;
  if (stepType === "derivation" && d.query !== stored.query) changes.input_graph_query = d.query;
  if (d.batchSize !== stored.batchSize && d.batchSize !== "") changes.batch_size = Number(d.batchSize);
  return changes;
}

function paramsError(params: string): string | null {
  try {
    const value: unknown = JSON.parse(params);
    return value !== null && typeof value === "object" && !Array.isArray(value) ? null : "params must be a JSON object";
  } catch (reason) {
    return `params must be valid JSON: ${message(reason)}`;
  }
}

function History({ stepType, name, draft }: { stepType: StepType; name: string; draft: Draft }) {
  const [versions, setVersions] = useState<ConfigVersion[] | null>(null);
  const [picked, setPicked] = useState<ConfigVersion | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    configs
      .versions(stepType, name)
      .then(setVersions)
      .catch((reason) => setFailed(message(reason)));
  }, [stepType, name]);

  if (failed) return <div className="error-text">{failed}</div>;
  if (!versions) return <div className="muted">Loading versions…</div>;
  const fields: [keyof Draft, string, string | null | undefined][] = picked
    ? [
        ["instruction", "Instruction", picked.instruction],
        ["example", "Example", picked.example],
        ["params", "Params", picked.params],
        ["query", "Candidate query", picked.input_graph_query],
      ]
    : [];

  return (
    <div className="history">
      <div className="runlist">
        {versions.map((v) => (
          <button key={v.version} type="button" className={`runrow${picked?.version === v.version ? " on" : ""}`} onClick={() => setPicked(v)}>
            <span>
              v{v.version}
              {v.is_active ? " · active" : ""}
              {v.enabled ? "" : " · off"}
            </span>
            <span className="faint">{v.created_at?.slice(0, 16).replace("T", " ") ?? ""}</span>
          </button>
        ))}
      </div>
      {picked && <div className="note">Changes from the current text back to v{picked.version} (- current, + v{picked.version})</div>}
      {fields.map(([key, label, old]) => {
        const lines = lineDiff(draft[key], old ?? "");
        if (lines.every((l) => l.op === " ")) return null;
        return (
          <div key={key} className="diff">
            <div className="diff-head">{label}</div>
            {lines.map((line, i) => (
              <div key={i} className={`diff-line diff-${line.op === "-" ? "del" : line.op === "+" ? "add" : "same"}`}>
                {`${line.op} ${line.text}`}
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function DryRun({ name, query }: { name: string; query?: string }) {
  const [result, setResult] = useState<DryRunResult | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  const run = () => {
    setFailed(null);
    configs
      .dryRun(name, query)
      .then(setResult)
      .catch((reason) => setFailed(message(reason)));
  };

  return (
    <div className="dryrun">
      <button type="button" onClick={run}>
        ▷ Dry run (no LLM)
      </button>
      {failed && <span className="error-text"> {failed}</span>}
      {result && (
        <div>
          <div className="note">
            {result.count} candidates{result.count > result.rows.length ? `, first ${result.rows.length} shown` : ""}
          </div>
          {result.rows.map((row, i) => (
            <div key={i} className="logline">
              {JSON.stringify(row)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** The selected step's texts, params, query and batch size; remounted per step and version, so a new selection starts from the stored values. */
function StepEditor({ stepType, row, status, onStatus, onDirty, onSaved }: EditorProps) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(row));
  const [tab, setTab] = useState<Tab>("instruction");
  const [findings, setFindings] = useState<ScanResult["findings"] | null>(null);

  const changes = changesOf(row, draft, stepType);
  const dirty = Object.keys(changes).length > 0;
  const tabs: [Tab, string][] = [
    ["instruction", "Instruction"],
    ["example", "Example"],
    ["params", "Params"],
    ...(stepType === "derivation" ? ([["query", "Candidate query"]] as [Tab, string][]) : []),
    ["history", "History"],
  ];

  const update = (key: keyof Draft, value: string) => {
    const next = { ...draft, [key]: value };
    setDraft(next);
    setFindings(null);
    onDirty(Object.keys(changesOf(row, next, stepType)).length > 0);
  };

  const store = async () => {
    try {
      const result = await configs.save(stepType, row.name, changes);
      onStatus({ kind: "ok", text: `Saved as v${result.new_version}` });
      setFindings(null);
      onDirty(false);
      onSaved();
    } catch (reason) {
      onStatus({ kind: "error", text: message(reason) });
    }
  };

  const save = async () => {
    if (!dirty) return;
    if (changes.params !== undefined && changes.params !== "") {
      const problem = paramsError(changes.params);
      if (problem) {
        onStatus({ kind: "error", text: problem });
        return;
      }
    }
    const texts = Object.fromEntries(
      (["instruction", "example", "params"] as const).filter((k) => typeof changes[k] === "string").map((k) => [k, changes[k] as string]),
    );
    if (Object.keys(texts).length) {
      try {
        const scan = await configs.scan(texts);
        if (!scan.available) onStatus({ kind: "ok", text: "Overfit scan unavailable here (no local scanner); saving without it" });
        if (scan.findings.length) {
          setFindings(scan.findings);
          return;
        }
      } catch (reason) {
        onStatus({ kind: "error", text: `Overfit scan failed: ${message(reason)}` });
        return;
      }
    }
    await store();
  };

  return (
    <div className="card">
      <div className="hd">
        <h3>{row.name}</h3>
        <span className="pill on">{row.version !== null ? `v${row.version} active` : "disabled"}</span>
        {dirty && <span className="pill warn">unsaved changes</span>}
        <label className="note" style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
          Batch size
          <input type="number" min={1} style={{ width: 64 }} aria-label="Batch size" value={draft.batchSize} onChange={(e) => update("batchSize", e.target.value)} />
        </label>
      </div>
      <div className="bd">
        <div className="subtabs" role="tablist">
          {tabs.map(([t, label]) => (
            <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>
              {label}
            </button>
          ))}
        </div>
        {tab === "instruction" && <CodeEditor label="Instruction" value={draft.instruction} onChange={(v) => update("instruction", v)} />}
        {tab === "example" && <CodeEditor label="Example" language="json" value={draft.example} onChange={(v) => update("example", v)} />}
        {tab === "params" && <CodeEditor label="Params" language="json" value={draft.params} onChange={(v) => update("params", v)} />}
        {tab === "query" && (
          <>
            <CodeEditor label="Candidate query" value={draft.query} onChange={(v) => update("query", v)} />
            <DryRun name={row.name} query={changes.input_graph_query} />
          </>
        )}
        {tab === "history" && <History stepType={stepType} name={row.name} draft={draft} />}
        {findings && (
          <div className="findings" role="alert">
            <b>Overfit scan: {findings.length} finding{findings.length === 1 ? "" : "s"}</b>
            {findings.map((f, i) => (
              <div key={i} className="logline warn">
                {f.field}: {f.finding}
              </div>
            ))}
            <button type="button" className="danger" onClick={() => void store()}>
              Save anyway
            </button>
          </div>
        )}
        <div className="row-actions">
          {status && <span className={status.kind === "ok" ? "ok" : "error-text"}>{status.text}</span>}
          <span className="note">Changed texts are scanned for overfitting before they are saved (rule 5).</span>
          <button type="button" className="primary" style={{ marginLeft: "auto" }} onClick={() => void save()} disabled={!dirty}>
            Save as new version
          </button>
        </div>
      </div>
    </div>
  );
}

/** Steps of one type: the table on the left, the selected step's prompt text on the right; saves create a new version. */
export function ConfigPage({ stepType, title }: Props) {
  const [rows, setRows] = useState<ConfigRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>(null);
  const dirty = useRef(false);

  const load = useCallback(() => {
    configs
      .list(stepType)
      .then((list) => {
        setRows(list);
        setSelected((current) => current ?? list[0]?.name ?? null);
      })
      .catch((reason) => setStatus({ kind: "error", text: message(reason) }));
  }, [stepType]);

  useEffect(load, [load]);

  const row = rows.find((r) => r.name === selected) ?? null;

  const choose = (name: string) => {
    if (name === selected) return;
    if (dirty.current && !window.confirm("Discard the unsaved changes to this step?")) return;
    dirty.current = false;
    setStatus(null);
    setSelected(name);
  };

  const toggle = async (target: ConfigRow) => {
    try {
      await configs.setEnabled(stepType, target.name, !target.enabled);
      load();
    } catch (reason) {
      setStatus({ kind: "error", text: message(reason) });
    }
  };

  return (
    <section className="page">
      <div className="pagehead">
        <h2>{title}</h2>
        <span className="sub">Saving creates a new version; earlier versions stay in the history</span>
      </div>
      <div className="pad cols" style={{ gridTemplateColumns: "340px 1fr" }}>
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Step</th>
                <th>v</th>
                <th>On</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.name} className={`clickable${r.name === selected ? " sel" : ""}`}>
                  <td onClick={() => choose(r.name)}>{r.sequence}</td>
                  <td onClick={() => choose(r.name)}>{r.name}</td>
                  <td onClick={() => choose(r.name)}>{r.version !== null ? `v${r.version}` : "off"}</td>
                  <td>
                    <button type="button" className="toggle" role="switch" aria-checked={r.enabled} aria-label={`Enable ${r.name}`} onClick={() => void toggle(r)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {row && (
          <StepEditor
            key={`${row.name}:${row.version}`}
            stepType={stepType}
            row={row}
            status={status}
            onStatus={setStatus}
            onDirty={(value) => {
              dirty.current = value;
            }}
            onSaved={load}
          />
        )}
      </div>
    </section>
  );
}
