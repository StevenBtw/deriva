import { useCallback, useEffect, useMemo, useState } from "react";

import { configs, ontology } from "../api/client";
import type { IntermediateOntology, NodeType, OntologyStep, OutputOntology, RelationshipRule, StepType } from "../api/types";
import { useTheme } from "../theme/theme";
import { GraphWidget } from "../widgets/GraphWidget";
import { type SchemaColors, schemaGraph, typeEdges } from "./ontologySchema";

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
/** Each group's colour token: structure and code feed the application layer, business and deployment their own layers */
const GROUP_TOKEN: Record<string, string> = { structure: "--inter", code: "--app", business: "--biz", deployment: "--tech", other: "--muted" };
/** The tokens' values per theme, for a page whose stylesheet has not loaded */
const FALLBACK: Record<"dark" | "light", Record<string, string>> = {
  dark: { "--inter": "#b3a6ff", "--app": "#7fc4f5", "--biz": "#f2d264", "--tech": "#9bd88a", "--muted": "#9aa2b0", "--faint": "#8e96a3", "--line": "#353b46" },
  light: { "--inter": "#7d6be0", "--app": "#4fa3df", "--biz": "#e8c547", "--tech": "#6cbf5b", "--muted": "#5d6573", "--faint": "#646c79", "--line": "#d4d8df" },
};

/** anywidget-graph as a schema view: the page places the types, arrows show the direction, a selection lights its
 * neighbours; the edge types are named on the edges of a selected type only (all of them at once crowd the middle) */
const GRAPH_SETTINGS = { layout: "preset", edge_arrows: true, highlight_neighbors: true, show_query_input: false, show_settings: false };
const OVERVIEW_SETTINGS = { ...GRAPH_SETTINGS, show_edge_labels: false };
const SELECTED_SETTINGS = { ...GRAPH_SETTINGS, show_edge_labels: true };

type OntologyView = "graph" | "matrix" | "cards";
const VIEWS: [OntologyView, string][] = [
  ["graph", "Graph"],
  ["matrix", "Matrix"],
  ["cards", "Cards"],
];

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

/** Two hex colours mixed (``share`` of the second): the edges sit between the lines and the muted text of the theme. */
function mix(a: string, b: string, share: number): string {
  const parse = (hex: string) => (/^#[0-9a-f]{6}$/i.test(hex) ? [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) : null);
  const [x, y] = [parse(a), parse(b)];
  if (!x || !y) return a;
  return `#${x.map((v, i) => Math.round(v + (y[i] - v) * share).toString(16).padStart(2, "0")).join("")}`;
}

/** The schema's colours from the shown theme's tokens. */
function schemaColors(theme: "dark" | "light"): SchemaColors {
  const css = getComputedStyle(document.documentElement);
  const token = (name: string) => css.getPropertyValue(name).trim() || FALLBACK[theme][name];
  return {
    groups: Object.fromEntries(Object.entries(GROUP_TOKEN).map(([group, name]) => [group, token(name)])),
    empty: token("--faint"),
    edge: mix(token("--line"), token("--muted"), 0.45),
  };
}

const plural = (count: number, one: string, many = `${one}s`) => `${count.toLocaleString("en")} ${count === 1 ? one : many}`;

/** The graph extraction builds: its node types as a graph (sized by their nodes, coloured by group, edges with their
 * types and direction), as a matrix of the edges between types, or as cards with the steps' switches; a selected type
 * shows its steps, readers, edges, properties and a sample. Group, empty-type and edge-type filters hold for every view. */
export function IntermediateOntologyPage() {
  const { data, error, notice, retry, toggle, dismiss } = useOntology<IntermediateOntology>(loadIntermediate);
  const [picked, setPicked] = useState<string | null>(null);
  const [view, setView] = useState<OntologyView>("graph");
  const [hiddenGroups, setHiddenGroups] = useState<ReadonlySet<string>>(new Set());
  const [showEmpty, setShowEmpty] = useState(true);
  const [edgeType, setEdgeType] = useState<string | null>(null);
  const [, , shownTheme] = useTheme();
  // Read again when the theme changes (setTheme applies it before it announces the change)
  const colors = useMemo(() => schemaColors(shownTheme), [shownTheme]);
  const filter = useMemo(() => ({ hiddenGroups, showEmpty, edgeType }), [hiddenGroups, showEmpty, edgeType]);
  const schema = useMemo(() => (data ? schemaGraph(data, filter, colors) : { nodes: [], edges: [] }), [data, filter, colors]);
  const problems = <Problems error={error} notice={notice} onRetry={retry} onDismiss={dismiss} />;

  if (!data) return <div className="page pad">{error ? problems : <span className="muted">Loading the intermediate ontology…</span>}</div>;
  const selected = data.node_types.find((t) => t.name === picked) ?? null;
  const groups = [...data.groups, ...(data.node_types.some((t) => !data.groups.includes(t.group)) ? ["other"] : [])];
  const groupOf = (t: NodeType) => (data.groups.includes(t.group) ? t.group : "other");
  const visible = new Set(schema.nodes.map((n) => n.id));
  const switchStep = (step: OntologyStep) => void toggle("extraction", step.name, !step.enabled);
  const flipGroup = (group: string) =>
    setHiddenGroups((now) => {
      const next = new Set(now);
      if (next.has(group)) next.delete(group);
      else next.add(group);
      return next;
    });

  return (
    <section className="page">
      <div className="pagehead">
        <h2>Intermediate ontology</h2>
        <span className="sub">
          The graph extraction builds: {plural(data.node_types.length, "node type")}, {plural(data.edge_types.length, "edge type")}
        </span>
      </div>
      {problems}
      <div className="pad onto-layout">
        <div className="card onto-main">
          <div className="hd onto-toolbar">
            <div className="onto-groups" role="group" aria-label="Groups">
              {groups.map((group) => (
                <button
                  key={group}
                  type="button"
                  className={`pill groupchip${hiddenGroups.has(group) ? "" : " on"}`}
                  aria-pressed={!hiddenGroups.has(group)}
                  title={hiddenGroups.has(group) ? `Show the ${GROUP_TITLE[group] ?? group} types` : `Hide the ${GROUP_TITLE[group] ?? group} types`}
                  onClick={() => flipGroup(group)}
                >
                  <span className="dot" style={{ background: colors.groups[group] ?? colors.empty }} />
                  {GROUP_TITLE[group] ?? group} {data.node_types.filter((t) => groupOf(t) === group).length}
                </button>
              ))}
            </div>
            <label className="onto-check">
              <input type="checkbox" checked={showEmpty} onChange={(e) => setShowEmpty(e.target.checked)} />
              Types without nodes
            </label>
            <label className="onto-check">
              Edges
              <select value={edgeType ?? ""} onChange={(e) => setEdgeType(e.target.value || null)}>
                <option value="">All edge types</option>
                {data.edge_types.map((e) => (
                  <option key={e.name} value={e.name}>
                    {e.name} ({e.count.toLocaleString("en")})
                  </option>
                ))}
              </select>
            </label>
            <div className="seg" role="group" aria-label="Ontology view">
              {VIEWS.map(([name, label]) => (
                <button key={name} type="button" className={view === name ? "on" : ""} aria-pressed={view === name} onClick={() => setView(name)}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          {view === "graph" && (
            <div className="schema-graph">
              {schema.nodes.length ? (
                <GraphWidget database="graph" view={schema} dark={shownTheme === "dark"} height={560} settings={selected ? SELECTED_SETTINGS : OVERVIEW_SETTINGS} selected={picked} onSelect={setPicked} />
              ) : (
                <div className="empty">No type matches these filters.</div>
              )}
            </div>
          )}
          {view === "matrix" && <EdgeMatrix data={data} visible={visible} edgeType={edgeType} />}
          {view === "cards" && <TypeCards data={data} groups={groups.filter((g) => !hiddenGroups.has(g))} visible={visible} selected={picked} onPick={setPicked} onToggle={switchStep} />}
          <div className="onto-footer">
            {data.other_steps.length > 0 && (
              <span className="onto-enrich">
                <span className="muted">Enrich existing nodes</span>
                {data.other_steps.map((step) => (
                  <StepSwitch key={step.name} step={step} onToggle={() => switchStep(step)} />
                ))}
              </span>
            )}
            {view === "graph" && <span className="faint">Size is the node count; grey types have no nodes in this graph; arrows point from source to target</span>}
          </div>
        </div>
        <aside className="card onto-side">
          {selected ? (
            <TypeDetails data={data} type={selected} color={selected.count ? (colors.groups[groupOf(selected)] ?? colors.empty) : colors.empty} onPick={setPicked} onToggle={switchStep} />
          ) : (
            <Overview data={data} onPick={setPicked} />
          )}
        </aside>
      </div>
    </section>
  );
}

/** Nothing selected: what the graph holds, and its largest types to start from. */
function Overview({ data, onPick }: { data: IntermediateOntology; onPick: (name: string) => void }) {
  const filled = data.node_types.filter((t) => t.count > 0);
  const nodes = filled.reduce((sum, t) => sum + t.count, 0);
  const edges = data.edge_types.reduce((sum, e) => sum + e.count, 0);
  const largest = [...filled].sort((a, b) => b.count - a.count).slice(0, 6);
  return (
    <>
      <div className="hd">
        <h3>This graph</h3>
      </div>
      <div className="bd onto-overview">
        <p>
          {plural(nodes, "node")} of {plural(filled.length, "type")}, {plural(edges, "edge")} of {plural(data.edge_types.length, "type")}.
          {data.node_types.length > filled.length && ` ${plural(data.node_types.length - filled.length, "type has", "types have")} no nodes here.`}
        </p>
        {largest.length > 0 && <div className="note">Largest types</div>}
        <ul className="onto-largest">
          {largest.map((t) => (
            <li key={t.name}>
              <button type="button" className="linkbtn" onClick={() => onPick(t.name)}>
                {t.name}
              </button>
              <span className="muted">{t.count.toLocaleString("en")}</span>
            </li>
          ))}
        </ul>
        <p className="faint">Select a type in the graph or the cards to see the steps that make and read it, its edges and its properties.</p>
      </div>
    </>
  );
}

const ARROW = { in: "←", out: "→", self: "↻" };
const DIRECTION = { in: "from", out: "to", self: "to itself" };

/** A selected type: its description, the steps that produce it (with their switches), the derivation steps that read
 * it, its edges (the type at the other end opens), its properties and a sample node. */
function TypeDetails({ data, type, color, onPick, onToggle }: { data: IntermediateOntology; type: NodeType; color: string; onPick: (name: string | null) => void; onToggle: (step: OntologyStep) => void }) {
  const [sample, setSample] = useState(false);
  const edges = typeEdges(data, type.name);
  return (
    <>
      <div className="hd">
        <span className="dot" style={{ background: color }} />
        <h3>{type.name}</h3>
        <span className="note">{type.count ? plural(type.count, "node") : "no nodes in this graph"}</span>
        <button type="button" className="ghost onto-close" aria-label="Close the details" onClick={() => onPick(null)}>
          ×
        </button>
      </div>
      <div className="bd kv onto-kv">
        <span className="muted">About</span>
        <span>{type.description || "a label the metamodel does not name"}</span>
        <span className="muted">Group</span>
        <span>{GROUP_TITLE[type.group] ?? type.group}</span>
        <span className="muted">Produced by</span>
        <span className="onto-steps">
          {type.producers.length ? (
            type.producers.map((step) => (
              <span key={step.name} className="onto-step">
                <StepSwitch step={step} owner={type.name} onToggle={() => onToggle(step)} />
                {step.method && <span className="faint">{step.method}</span>}
              </span>
            ))
          ) : (
            <span className="faint">no extraction step of its own</span>
          )}
        </span>
        <span className="muted">Read by</span>
        <span className="onto-chips">{type.consumers.length ? type.consumers.map((c) => <span key={c} className="pill">{c}</span>) : <span className="faint">no derivation step</span>}</span>
      </div>
      <div className="bd onto-section">
        <div className="note">Edges ({edges.length})</div>
        {edges.length ? (
          <table className="onto-edges">
            <tbody>
              {edges.map((e) => (
                <tr key={`${e.direction}${e.edge}`}>
                  <td className="muted" title={DIRECTION[e.direction]}>
                    {ARROW[e.direction]}
                  </td>
                  <td className="mono">{e.edge}</td>
                  <td>
                    {e.direction === "self"
                      ? type.name
                      : e.others.map((other, i) => (
                          <span key={other}>
                            {i > 0 && ", "}
                            <button type="button" className="linkbtn" onClick={() => onPick(other)}>
                              {other}
                            </button>
                          </span>
                        ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="faint">No edges of this type in this graph.</div>
        )}
      </div>
      <div className="bd onto-section">
        <div className="note">Properties ({type.properties.length})</div>
        <div className="mono onto-props">{type.properties.join(", ") || "none"}</div>
      </div>
      {type.count > 0 && (
        <div className="bd onto-section">
          <button type="button" aria-expanded={sample} onClick={() => setSample((on) => !on)}>
            {sample ? "Hide the sample node" : "Show a sample node"}
          </button>
          {sample && (
            <pre className="codebox onto-sample">{JSON.stringify(type.sample, null, 2)}</pre>
          )}
        </div>
      )}
    </>
  );
}

/** The 0.8.4 cards: every type per group with its count and the switches of the steps that produced its nodes. */
function TypeCards({
  data,
  groups,
  visible,
  selected,
  onPick,
  onToggle,
}: {
  data: IntermediateOntology;
  groups: string[];
  visible: ReadonlySet<string>;
  selected: string | null;
  onPick: (name: string) => void;
  onToggle: (step: OntologyStep) => void;
}) {
  const groupOf = (t: NodeType) => (data.groups.includes(t.group) ? t.group : "other");
  return (
    <div className="bd cols onto-cards">
      {groups.map((group) => (
        <div key={group} className="card">
          <div className="hd">
            <h3>{GROUP_TITLE[group] ?? group}</h3>
          </div>
          <table>
            <tbody>
              {data.node_types
                .filter((t) => groupOf(t) === group && visible.has(t.name))
                .map((t) => (
                  <tr key={t.name} className={`clickable${t.name === selected ? " sel" : ""}`}>
                    <td>
                      <button type="button" className="linkbtn" aria-pressed={t.name === selected} onClick={() => onPick(t.name)}>
                        {t.name}
                      </button>
                      {/* Under the type, where a long step name has the card's width */}
                      <div className="onto-cardsteps">
                        {t.producers.length ? t.producers.map((step) => <StepSwitch key={step.name} step={step} owner={t.name} onToggle={() => onToggle(step)} />) : <span className="faint">no step</span>}
                      </div>
                    </td>
                    <td className={t.count ? "num" : "num faint"}>{t.count.toLocaleString("en")}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

/** The edge types with their codes and counts, and who links to whom: rows are source types, columns target types. */
function EdgeMatrix({ data, visible, edgeType }: { data: IntermediateOntology; visible: ReadonlySet<string>; edgeType: string | null }) {
  const codes = edgeCodes(data.edge_types.map((e) => e.name));
  const shown = data.edge_types.filter((e) => !edgeType || e.name === edgeType);
  const cells = new Map<string, string[]>();
  for (const e of shown) {
    for (const [source, target] of e.pairs) {
      if (visible.has(source) && visible.has(target)) cells.set(`${source}→${target}`, [...(cells.get(`${source}→${target}`) ?? []), e.name]);
    }
  }
  const ends = [...cells.keys()].map((key) => key.split("→"));
  const sources = [...new Set(ends.map(([s]) => s))].sort();
  const targets = [...new Set(ends.map(([, t]) => t))].sort();
  return (
    <div className="bd onto-matrix">
      <div className="card">
        <div className="hd">
          <h3>Edge types</h3>
        </div>
        <table>
          <tbody>
            {data.edge_types.map((e) => (
              <tr key={e.name} className={edgeType && e.name !== edgeType ? "faint" : ""}>
                <td className="mono">{codes[e.name]}</td>
                <td>{e.name}</td>
                <td className="num">{e.count.toLocaleString("en")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.edge_types.length === 0 && <div className="empty">This graph has no edges yet.</div>}
      </div>
      <div className="card" style={{ overflow: "auto" }}>
        <div className="hd">
          <h3>Edges in this graph</h3>
          <span className="note">rows are sources; a cell lists the edge types from the row's type to the column's</span>
        </div>
        {sources.length ? (
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
        ) : (
          <div className="empty">No edges between the types shown.</div>
        )}
      </div>
    </div>
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
