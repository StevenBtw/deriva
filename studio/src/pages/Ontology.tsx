import { useCallback, useEffect, useState } from "react";

import { configs, ontology } from "../api/client";
import type { GraphView, IntermediateOntology, OntologyStep, OutputOntology, RelationshipRule, StepType } from "../api/types";
import { useTheme } from "../theme/theme";
import { GraphWidget } from "../widgets/GraphWidget";

function message(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

/** Load an ontology view and reload it after a step is switched. */
function useOntology<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    load()
      .then(setData)
      .catch((reason) => setError(message(reason)));
  }, [load, reload]);

  const toggle = useCallback(async (stepType: StepType, name: string, enabled: boolean) => {
    try {
      await configs.setEnabled(stepType, name, enabled);
      setReload((n) => n + 1);
    } catch (reason) {
      setError(message(reason));
    }
  }, []);

  return { data, error, toggle };
}

function StepSwitch({ step, onToggle }: { step: OntologyStep; onToggle: () => void }) {
  return (
    <span className="stepswitch">
      <button type="button" className="toggle" role="switch" aria-checked={step.enabled} aria-label={`Enable ${step.name}`} onClick={onToggle} />
      {step.name} {step.version !== null ? `v${step.version}` : ""}
    </span>
  );
}

const loadIntermediate = () => ontology.intermediate();
const loadOutput = () => ontology.output();

/** The graph extraction builds: node types with the steps that produce and read them, edge types, and the schema as a graph. */
export function IntermediateOntologyPage() {
  const { data, error, toggle } = useOntology<IntermediateOntology>(loadIntermediate);
  const [picked, setPicked] = useState<string | null>(null);
  const [, , shownTheme] = useTheme();

  if (error) return <div className="page pad error-text">{error}</div>;
  if (!data) return <div className="page pad muted">Loading the intermediate ontology…</div>;
  const selected = data.node_types.find((t) => t.name === picked) ?? data.node_types[0];
  const schema: GraphView = {
    nodes: data.node_types.map((t) => ({ id: t.name, label: t.name, count: t.count })),
    edges: data.edge_types.flatMap((e) => e.pairs.map(([source, target]) => ({ source, target, label: e.name }))),
  };

  return (
    <section className="page">
      <div className="pagehead">
        <h2>Intermediate ontology</h2>
        <span className="sub">The graph extraction builds; the switches turn a step on or off in its active version (as config enable/disable)</span>
      </div>
      <div className="pad cols" style={{ gridTemplateColumns: "1.2fr 1fr" }}>
        <div className="card">
          <div className="hd">
            <h3>Node types</h3>
          </div>
          <table>
            <thead>
              <tr>
                <th>Type</th>
                <th>Nodes</th>
                <th>Produced by</th>
                <th>Read by</th>
              </tr>
            </thead>
            <tbody>
              {data.node_types.map((t) => (
                <tr key={t.name} className={`clickable${t.name === selected?.name ? " sel" : ""}`}>
                  <td onClick={() => setPicked(t.name)}>{t.name}</td>
                  <td>{t.count}</td>
                  <td>
                    {t.producers.map((p) => (
                      <StepSwitch key={p.name} step={p} onToggle={() => void toggle("extraction", p.name, !p.enabled)} />
                    ))}
                  </td>
                  <td>{t.consumers.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="hd">
            <h3>Edge types</h3>
          </div>
          <table>
            <tbody>
              {data.edge_types.map((e) => (
                <tr key={e.name}>
                  <td>{e.name}</td>
                  <td>{e.count}</td>
                  <td className="faint">{e.pairs.map(([s, t]) => `${s} → ${t}`).join(" · ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.other_steps.length > 0 && (
            <div className="bd">
              <div className="note">Steps that enrich existing nodes:</div>
              {data.other_steps.map((s) => (
                <StepSwitch key={s.name} step={s} onToggle={() => void toggle("extraction", s.name, !s.enabled)} />
              ))}
            </div>
          )}
        </div>
        <div>
          <div className="card">
            <div className="hd">
              <h3>Schema</h3>
            </div>
            <GraphWidget database="graph" view={schema} dark={shownTheme === "dark"} height={320} />
          </div>
          {selected && (
            <div className="card">
              <div className="hd">
                <h3>{selected.name}</h3>
                <span className="note">{selected.count} nodes</span>
              </div>
              <div className="bd kv" style={{ gridTemplateColumns: "110px 1fr" }}>
                <span className="muted">Properties</span>
                <span className="mono">{selected.properties.join(", ")}</span>
                <span className="muted">Produced by</span>
                <span>{selected.producers.map((p) => `${p.name} (${p.method ?? "?"})`).join(", ") || "no extraction step of its own"}</span>
                <span className="muted">Read by</span>
                <span>{selected.consumers.join(", ") || "no derivation step"}</span>
              </div>
              <pre className="codebox">{JSON.stringify(selected.sample, null, 2)}</pre>
            </div>
          )}
        </div>
      </div>
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

/** ArchiMate as Deriva derives it: element types per layer with their derivation step, relationship types, and the rules matrix. */
export function OutputOntologyPage() {
  const { data, error, toggle } = useOntology<OutputOntology>(loadOutput);

  if (error) return <div className="page pad error-text">{error}</div>;
  if (!data) return <div className="page pad muted">Loading the output ontology…</div>;
  const sources = [...new Set(data.rules.map((r) => r.source))];
  const targets = [...new Set(data.rules.map((r) => r.target))];
  const rule = (s: string, t: string) => data.rules.find((r) => r.source === s && r.target === t);

  return (
    <section className="page">
      <div className="pagehead">
        <h2>Output ontology</h2>
        <span className="sub">The ArchiMate types derivation may create; the switches turn a type's step on or off in its active version (as config enable/disable)</span>
      </div>
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
      <div className="pad cols" style={{ gridTemplateColumns: "260px 1fr" }}>
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
                    {t.replace(/(Business|Application|Technology)/, "").slice(0, 6) || t.slice(0, 6)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s}>
                  <th>{s}</th>
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
