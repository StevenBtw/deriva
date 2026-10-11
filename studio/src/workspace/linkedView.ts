import type { GraphView, Lane, LinkedView, RunEvent, WidgetEdge, WidgetNode } from "../api/types";

export type AppendItems = { nodes: WidgetNode[]; edges: WidgetEdge[] };
export type HostTheme = { background: string; panel: string; text: string; muted: string; border: string; accent: string };

/** The key the widget merges edges by: source, target and label. */
export function edgeKey(edge: WidgetEdge): string {
  return JSON.stringify([edge.source, edge.target, edge.label ?? ""]);
}

/** The nodes and edges of `next` that `shown` lacks, in their order in `next`: one append batch. */
export function newItems(shown: LinkedView, next: LinkedView): AppendItems {
  const nodeIds = new Set(shown.nodes.map((node) => node.id));
  const edgeKeys = new Set(shown.edges.map(edgeKey));
  return { nodes: next.nodes.filter((node) => !nodeIds.has(node.id)), edges: next.edges.filter((edge) => !edgeKeys.has(edgeKey(edge))) };
}

/** The nodes (ids) and edges `shown` has and `next` lacks (a re-sample, an element leaving the model): one batch's `remove`. */
export function removedItems(shown: LinkedView, next: LinkedView): { nodes: string[]; edges: WidgetEdge[] } {
  const nodeIds = new Set(next.nodes.map((node) => node.id));
  const edgeKeys = new Set(next.edges.map(edgeKey));
  return {
    nodes: shown.nodes.filter((node) => !nodeIds.has(node.id)).map((node) => node.id),
    edges: shown.edges.filter((edge) => !edgeKeys.has(edgeKey(edge))).map(({ source, target, label }) => ({ source, target, label })),
  };
}

/** Whether an element is part of the exported model (refine did not disable it). */
export function inModel(node: WidgetNode): boolean {
  return node.enabled !== false;
}

/** The nodes of `next` whose place in the model changed since `shown` (refine rejected or restored them), in their new state. */
export function changedElements(shown: LinkedView, next: LinkedView): WidgetNode[] {
  const before = new Map(shown.nodes.map((node) => [node.id, inModel(node)]));
  return next.nodes.filter((node) => before.has(node.id) && before.get(node.id) !== inModel(node));
}

/** Whether the lanes differ (a second repository renames the repository lane): the studio reloads instead of appending. */
export function lanesChanged(shown: LinkedView, next: LinkedView): boolean {
  return JSON.stringify(shown.lanes) !== JSON.stringify(next.lanes);
}

/** The widget node ids of the graph nodes with these Deriva ids (the ones the view shows). */
export function toWidgetIds(view: LinkedView, derivaIds: string[]): string[] {
  const wanted = new Set(derivaIds);
  return view.nodes.filter((node) => typeof node.deriva_id === "string" && wanted.has(node.deriva_id)).map((node) => node.id);
}

/** The candidates (Deriva ids) of the derivation step that is running: its last `processing` event, until that step completes. */
export function pulseFrom(events: RunEvent[], status: string): string[] {
  if (status !== "running") return [];
  for (let i = events.length - 1; i >= 0; i--) {
    const { event, data } = events[i];
    if (event !== "progress") continue;
    if (data.status === "complete" || data.status === "error") return [];
    if (data.status === "processing" && data.candidates) return data.candidates;
  }
  return [];
}

/** The studio's theme tokens as the widget's host theme. */
export function themeFromTokens(style: Pick<CSSStyleDeclaration, "getPropertyValue">): HostTheme {
  const token = (name: string) => style.getPropertyValue(name).trim();
  return { background: token("--bg"), panel: token("--bg2"), text: token("--text"), muted: token("--muted"), border: token("--line"), accent: token("--accent") };
}

/** ArchiMate layer colours in mid tones that read on the dark and the light ground (a theme switch keeps them). */
export const LAYER_COLORS = { business: "#e8c547", application: "#5fb0e8", technology: "#7cc96b" } as const;

const TECHNOLOGY_TYPES = new Set(["Node", "Device", "SystemSoftware", "TechnologyService"]);

function layerOf(type: string): keyof typeof LAYER_COLORS | null {
  if (type.startsWith("Business")) return "business";
  if (type.startsWith("Application") || type === "DataObject") return "application";
  if (TECHNOLOGY_TYPES.has(type) || type.startsWith("Technology")) return "technology";
  return null;
}

/**
 * The intermediate graph's node types per theme (checked with the dataviz palette validator, all pairs, against --bg):
 * code in violet and structure in grey, the container darker than what it contains; business evidence in amber and
 * technology evidence in green-teal, next to the layers they feed. Other types keep the widget's palette.
 */
export const INTERMEDIATE_COLORS = {
  dark: { TypeDefinition: "#5d52b4", Method: "#8b87d8", Directory: "#5d646f", File: "#999fa8", BusinessConcept: "#bb881a", Technology: "#308e63", ExternalDependency: "#308e63" },
  light: { TypeDefinition: "#5343ac", Method: "#7f79d1", Directory: "#474d58", File: "#81868f", BusinessConcept: "#d9a02c", Technology: "#308e63", ExternalDependency: "#308e63" },
} as const;

/**
 * anywidget-graph's `type_colors` (one colour per type for nodes and legend): the intermediate palette for the theme,
 * and each element type (output-lane nodes) in its layer colour.
 */
export function typeColors(nodes: WidgetNode[], dark: boolean): { nodes: Record<string, string> } {
  const colors: Record<string, string> = { ...INTERMEDIATE_COLORS[dark ? "dark" : "light"] };
  for (const node of nodes) {
    const type = Array.isArray(node.labels) ? String(node.labels[0] ?? "") : "";
    const layer = node.lane === "output" ? layerOf(type) : null;
    if (layer) colors[type] = LAYER_COLORS[layer];
  }
  return { nodes: colors };
}

/** Elements refine rejected: a mid grey that reads on both grounds, next to the layer colours of the elements in the model. */
export const REJECTED_COLOR = "#8a8f98";

/**
 * Output-lane nodes with their ArchiMate layer (their row) and its colour; rejected elements keep their row, in grey.
 * Graph nodes keep the widget's colours by type.
 */
export function withLayerColors(nodes: WidgetNode[]): WidgetNode[] {
  return nodes.map((node) => {
    if (node.lane !== "output") return node;
    const type = Array.isArray(node.labels) ? String(node.labels[0] ?? "") : "";
    const layer = layerOf(type);
    const placed = layer ? { ...node, layer } : node;
    if (!inModel(node)) return { ...placed, color: REJECTED_COLOR };
    return layer ? { ...placed, color: LAYER_COLORS[layer] } : placed;
  });
}

const formatCount = (n: number) => n.toLocaleString("en-US");
const countOf = (n: number, one: string, many: string) => `${formatCount(n)} ${n === 1 ? one : many}`;
const sumOf = (counts?: Record<string, number>) => (counts ? Object.values(counts).reduce((a, b) => a + b, 0) : undefined);

/** "300 of 2,757 nodes" when a view shows part of a total, else "44 nodes". */
export function ofTotal(shown: number, total: number | undefined, one: string, many: string): string {
  return total !== undefined && total > shown ? `${formatCount(shown)} of ${formatCount(total)} ${many}` : countOf(shown, one, many);
}

/** The counts of a separate graph pane: nodes and edges, against the totals of a sampled graph. */
export function viewNote(view: GraphView): string {
  return `${ofTotal(view.nodes.length, sumOf(view.totals?.nodes), "node", "nodes")} · ${ofTotal(view.edges.length, sumOf(view.totals?.edges), "edge", "edges")}`;
}

/** The counts of the linked view: repositories, the (sampled) intermediate graph and its edges, the elements and how many are in the model. */
export function linkedNote(view: LinkedView): string {
  const inLane = (lane: string) => view.nodes.filter((node) => node.lane === lane);
  const repositories = inLane("repository").length;
  const output = inLane("output");
  const onGraph = new Set(view.nodes.filter((node) => node.lane !== "output").map((node) => node.id));
  const graphEdges = view.edges.filter((edge) => !edge.cross && onGraph.has(edge.source) && onGraph.has(edge.target)).length;
  // Repositories are always shown whole, so the intermediate graph's total is the graph's total without them
  const totalNodes = sumOf(view.totals?.nodes);
  const totalEdges = sumOf(view.totals?.edges);
  const parts = [countOf(repositories, "repository", "repositories"), ofTotal(inLane("intermediate").length, totalNodes === undefined ? undefined : totalNodes - repositories, "graph node", "graph nodes")];
  if (graphEdges || totalEdges !== undefined) parts.push(ofTotal(graphEdges, totalEdges, "edge", "edges"));
  const valid = output.filter(inModel).length;
  const elements = countOf(output.length, "element", "elements");
  parts.push(valid === output.length ? elements : `${elements}, ${valid} in the model`);
  return parts.join(" · ");
}

// A lane re-laid as a whole when one batch adds or removes more than this share of its nodes (a re-sample, the first fill)
const RELAYOUT_SHARE = 0.33;

/**
 * How the two graphs are drawn (anywidget-graph lane options): the intermediate graph spread by forces in a wider lane;
 * the output graph in rows by ArchiMate layer (the `layer` withLayerColors sets), business on top, then application and
 * technology; rejected elements stay in their layer's row, in grey.
 * Each lane labels its largest nodes at the default zoom where the label has room (the hubs, the most related elements).
 */
export function withLaneLayouts(lanes: Lane[]): Lane[] {
  return lanes.map((lane) => {
    if (lane.id === "intermediate") return { ...lane, layout: "force", relayout: RELAYOUT_SHARE, width: 1.6, labels: { count: 12 } };
    if (lane.id === "output") {
      return { ...lane, rows: { field: "layer", order: ["business", "application", "technology"] }, relayout: RELAYOUT_SHARE, labels: { count: 16 } };
    }
    return lane;
  });
}

/** The lanes followed by the model: a glyph in the ArchiMate layer colours; a click on it opens the model panel. */
export function withModelLane(lanes: Lane[]): Lane[] {
  return [...lanes, { id: "model", title: "Model", action: true, width: 0.25, glyph: [LAYER_COLORS.business, LAYER_COLORS.application, LAYER_COLORS.technology], caption: "View model" }];
}
