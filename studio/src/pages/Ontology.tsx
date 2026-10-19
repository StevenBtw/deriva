import { useCallback, useEffect, useState } from "react";

import { configs, ontology } from "../api/client";
import type { IntermediateOntology, OntologyStep, OutputOntology, RelationshipRule, StepType } from "../api/types";

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

/** Load an ontology view and reload it after a step is switched; a failed load can be retried, a failed switch is a notice. */
function useOntology<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let live = true;
    load()
      .then((found) => {
        if (!live) return;
        setData(found);
        setError(null);
      })
      .catch((reason) => live && setError(message(reason)));
    return () => {
      live = false;
    };
  }, [load, reload]);

  const retry = useCallback(() => {
    setError(null);
    setReload((n) => n + 1);
  }, []);

  const toggle = useCallback(async (stepType: StepType, name: string, enabled: boolean) => {
    try {
      await configs.setEnabled(stepType, name, enabled);
      setNotice(null);
      setReload((n) => n + 1);
    } catch (reason) {
      setNotice(message(reason));
    }
  }, []);

  return { data, error, notice, retry, toggle, dismiss: useCallback(() => setNotice(null), []) };
}

/** A failed load (with Retry) or a failed switch (dismissable) above the page, which stays usable. */
function Problems({ error, notice, onRetry, onDismiss }: { error: string | null; notice: string | null; onRetry: () => void; onDismiss: () => void }) {
  return (
    <>
      {error && (
        <div className="banner warn" role="alert">
          {error}{" "}
          <button type="button" onClick={onRetry}>
            Retry
          </button>
        </div>
      )}
      {notice && (
        <div className="banner warn" role="alert">
          {notice}{" "}
          <button type="button" className="ghost" aria-label="Dismiss" onClick={onDismiss}>
            ×
          </button>
        </div>
      )}
    </>
  );
}

/** A step's switch with its version; its name too unless it is the type's own step (``owner``), as the output page shows it. */
function StepSwitch({ step, onToggle, owner }: { step: OntologyStep; onToggle: () => void; owner?: string }) {
  const version = step.version !== null ? `v${step.version}` : "";
  return (
    <span className="stepswitch" title={`${step.name} ${version}`.trim()}>
      <button type="button" className="toggle" role="switch" aria-checked={step.enabled} aria-label={`Enable ${step.name}`} onClick={onToggle} />
      {step.name === owner ? version : `${step.name} ${version}`}
    </span>
  );
}

const loadIntermediate = () => ontology.intermediate();
const loadOutput = () => ontology.output();

const GROUP_TITLE: Record<string, string> = { structure: "Structure", code: "Code", business: "Business", deployment: "Deployment", other: "Other" };

/** Short unique codes for the edge types (CONTAINS, CONFIGURES and CONSUMES become CONT, CONF and CONS). */
function edgeCodes(names: string[]): Record<string, string> {
  const codes: Record<string, string> = {};
  for (const name of names) {
    let length = Math.min(2, name.length);
    while (length < name.length && names.some((other) => other !== name && other.startsWith(name.slice(0, length)))) length += 1;
    codes[name] = name.slice(0, length);
  }
  return codes;
}

/** The graph extraction builds, as the output ontology shows the model: every node type per group with its count and the
 * steps that produce it, the edge types, and the edges between types as a matrix; a type opens its properties and sample. */
export function IntermediateOntologyPage() {
  const { data, error, notice, retry, toggle, dismiss } = useOntology<IntermediateOntology>(loadIntermediate);
  const [picked, setPicked] = useState<string | null>(null);
  const problems = <Problems error={error} notice={notice} onRetry={retry} onDismiss={dismiss} />;

  if (!data) return <div className="page pad">{error ? problems : <span className="muted">Loading the intermediate ontology…</span>}</div>;
  const selected = data.node_types.find((t) => t.name === picked) ?? data.node_types.find((t) => t.count > 0) ?? data.node_types[0];
  const groups = [...data.groups, ...(data.node_types.some((t) => !data.groups.includes(t.group)) ? ["other"] : [])];
  const codes = edgeCodes(data.edge_types.map((e) => e.name));
  // Who links to whom: rows are source types, columns target types, a cell the codes of the edge types between them
  const cells = new Map<string, string[]>();
  for (const e of data.edge_types) {
    for (const [source, target] of e.pairs) cells.set(`${source}→${target}`, [...(cells.get(`${source}→${target}`) ?? []), e.name]);
  }
  const sources = [...new Set(data.edge_types.flatMap((e) => e.pairs.map(([s]) => s)))].sort();
  const targets = [...new Set(data.edge_types.flatMap((e) => e.pairs.map(([, t]) => t)))].sort();

  return (
    <section className="page">
      <div className="pagehead">
        <h2>Intermediate ontology</h2>
        <span className="sub">The graph extraction builds; the switches turn a step on or off in its active version (as config enable/disable)</span>
      </div>
      {problems}
      <div className="pad cols" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(270px, 1fr))", alignItems: "start" }}>
        {groups.map((group) => (
          <div key={group} className="card">
            <div className="hd">
              <h3>{GROUP_TITLE[group] ?? group}</h3>
            </div>
            <table>
              <tbody>
                {data.node_types
                  .filter((t) => (data.groups.includes(t.group) ? t.group : "other") === group)
                  .map((t) => (
                    <tr key={t.name} className={`clickable${t.name === selected?.name ? " sel" : ""}`}>
                      <td>
                        <button type="button" className="linkbtn" aria-pressed={t.name === selected?.name} onClick={() => setPicked(t.name)}>
                          {t.name}
                        </button>
                        {/* Under the type, where a long step name has the card's width */}
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 10px", marginTop: 2 }}>
                          {t.producers.length ? (
                            t.producers.map((step) => <StepSwitch key={step.name} step={step} owner={t.name} onToggle={() => void toggle("extraction", step.name, !step.enabled)} />)
                          ) : (
                            <span className="faint">no step</span>
                          )}
                        </div>
                      </td>
                      <td className={t.count ? "" : "faint"} style={{ textAlign: "right" }}>
                        {t.count}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      <div className="pad cols" style={{ gridTemplateColumns: "300px 1fr", alignItems: "start" }}>
        <div className="card">
          <div className="hd">
            <h3>Edge types</h3>
          </div>
          <table>
            <tbody>
              {data.edge_types.map((e) => (
                <tr key={e.name}>
                  <td className="mono">{codes[e.name]}</td>
                  <td>{e.name}</td>
                  <td>{e.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.edge_types.length === 0 && <div className="empty">This graph has no edges yet.</div>}
          {data.other_steps.length > 0 && (
            <div className="bd">
              <div className="note">Steps that enrich existing nodes or write edges:</div>
              {data.other_steps.map((step) => (
                <StepSwitch key={step.name} step={step} onToggle={() => void toggle("extraction", step.name, !step.enabled)} />
              ))}
            </div>
          )}
        </div>
        {selected && (
          <div className="card">
            <div className="hd">
              <h3>{selected.name}</h3>
              <span className="note">{selected.count ? `${selected.count} nodes` : "no nodes in this graph"}</span>
            </div>
            <div className="bd kv" style={{ gridTemplateColumns: "110px 1fr" }}>
              <span className="muted">About</span>
              <span>{selected.description || "a label the metamodel does not name"}</span>
              <span className="muted">Properties</span>
              <span className="mono">{selected.properties.join(", ")}</span>
              <span className="muted">Produced by</span>
              <span>{selected.producers.map((step) => `${step.name} (${step.method ?? "?"})`).join(", ") || "no extraction step of its own"}</span>
              <span className="muted">Read by</span>
              <span>{selected.consumers.join(", ") || "no derivation step"}</span>
            </div>
            {selected.count > 0 && (
              <pre className="codebox" style={{ maxHeight: 320, overflow: "auto" }}>
                {JSON.stringify(selected.sample, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>
      {sources.length > 0 && (
        <div className="pad">
          <div className="card" style={{ overflow: "auto" }}>
            <div className="hd">
              <h3>Edges in this graph</h3>
              <span className="note">rows are sources; a cell lists the edge types from the row's type to the column's</span>
            </div>
            <table className="rules">
              <thead>
                <tr>
                  <th />
                  {/* Upright names keep the columns as narrow as their codes */}
                  {targets.map((t) => (
                    <th key={t} title={t} style={{ writingMode: "vertical-rl", transform: "rotate(180deg)", verticalAlign: "bottom", whiteSpace: "nowrap" }}>
                      {t}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sources.map((source) => (
                  <tr key={source}>
                    <th scope="row" title={source}>
                      {source}
                    </th>
                    {targets.map((target) => {
                      const kinds = cells.get(`${source}→${target}`) ?? [];
                      return (
                        <td key={target} className="mono" title={kinds.length ? `${source} → ${target}: ${kinds.join(", ")}` : undefined}>
                          {kinds.map((k) => codes[k]).join(" ")}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

const LETTER: Record<string, string> = { Access: "a", Composition: "c", Flow: "f", Aggregation: "g", Assignment: "i", Realization: "r", Serving: "v", Triggering: "t" };
const LAYERS = ["Business", "Application", "Technology"];

function ruleCell(rule?: RelationshipRule): { text: string; title: string } {
  if (!rule) return { text: "", title: "" };
  const text = rule.direct.map((r) => LETTER[r]?.toUpperCase() ?? "?").join("") + rule.derived.map((r) => LETTER[r] ?? "?").join("");
  const title = `${rule.source} → ${rule.target}: direct ${rule.direct.join(", ") || "none"}; derived ${rule.derived.join(", ") || "none"}`;
  return { text, title };
}

/** A matrix header: the layer's initial and the type (ApplicationService and TechnologyService stay apart); the title has the full name. */
function header(type: string): string {
  const match = /^(Business|Application|Technology)(.+)$/.exec(type);
  return match ? `${match[1][0]}·${match[2].slice(0, 10)}` : type.slice(0, 10);
}

/** ArchiMate as Deriva derives it: element types per layer with their derivation step, relationship types, and the rules matrix. */
export function OutputOntologyPage() {
  const { data, error, notice, retry, toggle, dismiss } = useOntology<OutputOntology>(loadOutput);
  const problems = <Problems error={error} notice={notice} onRetry={retry} onDismiss={dismiss} />;

  if (!data) return <div className="page pad">{error ? problems : <span className="muted">Loading the output ontology…</span>}</div>;
  const sources = [...new Set(data.rules.map((r) => r.source))];
  const targets = [...new Set(data.rules.map((r) => r.target))];
  const rule = (s: string, t: string) => data.rules.find((r) => r.source === s && r.target === t);

  return (
    <section className="page">
      <div className="pagehead">
        <h2>Output ontology</h2>
        <span className="sub">The ArchiMate types derivation may create; the switches turn a type's step on or off in its active version (as config enable/disable)</span>
      </div>
      {problems}
      <div className="pad cols" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
        {LAYERS.map((layer) => (
          <div key={layer} className="card">
            <div className="hd">
              <h3>{layer} layer</h3>
            </div>
            <table>
              <tbody>
                {data.element_types
                  .filter((t) => t.layer === layer)
                  .map((t) => (
                    <tr key={t.name}>
                      <td>{t.name}</td>
                      <td>{t.count}</td>
                      <td>
                        {t.step ? (
                          <span className="stepswitch">
                            <button
                              type="button"
                              className="toggle"
                              role="switch"
                              aria-checked={t.step.enabled}
                              aria-label={`Enable ${t.name}`}
                              onClick={() => void toggle("derivation", t.name, !t.step?.enabled)}
                            />
                            {t.step.version !== null ? `v${t.step.version}` : ""}
                          </span>
                        ) : (
                          <span className="faint">no step</span>
                        )}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      <div className="pad cols" style={{ gridTemplateColumns: "260px" }}>
        <div className="card">
          <div className="hd">
            <h3>Relationship types</h3>
          </div>
          <table>
            <tbody>
              {data.relationship_types.map((r) => (
                <tr key={r.name}>
                  <td>{r.name}</td>
                  <td>{r.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="note">Read-only: switching a relationship kind off changes derivation, so it is decided first.</div>
        </div>
      </div>
      {/* The matrix gets the page's full width: next to the relationship types its columns ran past the card at 1440px */}
      <div className="pad">
        <div className="card" style={{ overflow: "auto" }}>
          <div className="hd">
            <h3>Allowed relationships (ArchiMate 3.2)</h3>
            <span className="note">upper case = direct, lower case = derived; rows are sources</span>
          </div>
          <table className="rules">
            <thead>
              <tr>
                <th />
                {targets.map((t) => (
                  <th key={t} title={t}>
                    {header(t)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s}>
                  <th scope="row" title={s}>
                    {header(s)}
                  </th>
                  {targets.map((t) => {
                    const cell = ruleCell(rule(s, t));
                    return (
                      <td key={t} title={cell.title} className="mono">
                        {cell.text}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
