import type { GraphView, IntermediateOntology, WidgetEdge, WidgetNode } from "../api/types";

/** The schema graph's colours (from the theme's tokens): one per group, a faint one for types without nodes, the edges'. */
export type SchemaColors = { groups: Record<string, string>; empty: string; edge: string };
export type SchemaFilter = { hiddenGroups: ReadonlySet<string>; showEmpty: boolean; edgeType: string | null };
export type TypeEdge = { direction: "in" | "out" | "self"; edge: string; others: string[] };

const groupOf = (data: IntermediateOntology, group: string) => (data.groups.includes(group) ? group : "other");

/** Bigger for more nodes, on a log scale (two thousand methods next to one repository still both read). */
export const nodeSize = (count: number) => (count > 0 ? 5 + 3 * Math.log10(count + 1) : 3.5);
const edgeSize = (count: number) => 0.6 + 0.7 * Math.log10(count + 1);

/** The types' positions, the same every time for the same ontology: a force layout from a fixed start, each type
 * pulled towards its group's place on a circle, so the groups stay apart and a type sits near the types it links to. */
export function layoutSchema(data: IntermediateOntology): Map<string, { x: number; y: number }> {
  const groups = [...data.groups, "other"];
  const names = data.node_types.map((t) => t.name);
  const index = new Map(names.map((name, i) => [name, i]));
  const centre = data.node_types.map((t) => {
    // Clockwise from the top (the widget's y axis points up): structure, code, business, deployment
    const angle = Math.PI / 2 - (2 * Math.PI * groups.indexOf(groupOf(data, t.group))) / data.groups.length;
    return { x: Math.cos(angle), y: Math.sin(angle) };
  });
  const members = new Map<string, number>();
  const pos = data.node_types.map((t, i) => {
    const group = groupOf(data, t.group);
    const nth = members.get(group) ?? 0;
    members.set(group, nth + 1);
    const angle = nth * 2.4 + groups.indexOf(group);
    return { x: centre[i].x + 0.3 * Math.cos(angle), y: centre[i].y + 0.3 * Math.sin(angle) };
  });
  const links = [...new Set(data.edge_types.flatMap((e) => e.pairs.filter(([s, t]) => s !== t && index.has(s) && index.has(t)).map(([s, t]) => `${index.get(s)}:${index.get(t)}`)))].map((key) =>
    key.split(":").map(Number),
  );

  const k = 0.55, rounds = 400;
  for (let round = 0; round < rounds; round++) {
    const step = 0.1 * (1 - round / rounds) + 0.002;
    const move = pos.map(() => ({ x: 0, y: 0 }));
    for (let a = 0; a < pos.length; a++) {
      for (let b = a + 1; b < pos.length; b++) {
        const dx = pos[a].x - pos[b].x, dy = pos[a].y - pos[b].y;
        const d = Math.max(0.01, Math.hypot(dx, dy)), push = (k * k) / d;
        move[a].x += (dx / d) * push;
        move[a].y += (dy / d) * push;
        move[b].x -= (dx / d) * push;
        move[b].y -= (dy / d) * push;
      }
    }
    for (const [a, b] of links) {
      const dx = pos[a].x - pos[b].x, dy = pos[a].y - pos[b].y;
      // A spring (linear): a square pull draws every linked type into the middle and the groups lose their places
      const d = Math.max(0.01, Math.hypot(dx, dy)), pull = d * 0.35;
      move[a].x -= (dx / d) * pull;
      move[a].y -= (dy / d) * pull;
      move[b].x += (dx / d) * pull;
      move[b].y += (dy / d) * pull;
    }
    pos.forEach((p, i) => {
      move[i].x += (centre[i].x - p.x) * 0.6;
      move[i].y += (centre[i].y - p.y) * 0.6;
      const length = Math.hypot(move[i].x, move[i].y);
      const scale = length > step ? step / length : 1;
      p.x += move[i].x * scale;
      p.y += move[i].y * scale;
    });
  }
  return new Map(names.map((name, i) => [name, { x: Math.round(pos[i].x * 1000) / 10, y: Math.round(pos[i].y * 1000) / 10 }]));
}

/** The intermediate ontology as a graph for anywidget-graph (layout "preset"): a node per type, an edge per pair of
 * types with every edge type between them in its label; a filter hides groups, types without nodes, other edge types. */
export function schemaGraph(data: IntermediateOntology, filter: SchemaFilter, colors: SchemaColors): GraphView {
  const at = layoutSchema(data);
  const shown = data.node_types.filter((t) => !filter.hiddenGroups.has(groupOf(data, t.group)) && (filter.showEmpty || t.count > 0));
  const visible = new Set(shown.map((t) => t.name));
  const nodes: WidgetNode[] = shown.map((t) => ({
    id: t.name,
    label: t.name,
    group: groupOf(data, t.group),
    count: t.count,
    size: nodeSize(t.count),
    color: t.count > 0 ? (colors.groups[groupOf(data, t.group)] ?? colors.empty) : colors.empty,
    ...at.get(t.name),
  }));

  const pairs = new Map<string, { source: string; target: string; names: string[]; count: number }>();
  for (const e of data.edge_types) {
    if (filter.edgeType && e.name !== filter.edgeType) continue;
    for (const [source, target] of e.pairs) {
      if (!visible.has(source) || !visible.has(target)) continue;
      const key = `${source}→${target}`;
      const pair = pairs.get(key) ?? { source, target, names: [], count: 0 };
      pair.names.push(e.name);
      pair.count = Math.max(pair.count, e.count);
      pairs.set(key, pair);
    }
  }
  const edges: WidgetEdge[] = [...pairs.entries()].map(([id, p]) => ({ id, source: p.source, target: p.target, label: p.names.join(" · "), size: edgeSize(p.count), color: colors.edge }));
  return { nodes, edges };
}

const ORDER = { self: 0, in: 1, out: 2 };

/** A type's edges: per edge type and direction the types at the other end (out, in, or to itself). */
export function typeEdges(data: IntermediateOntology, name: string): TypeEdge[] {
  const found: TypeEdge[] = [];
  for (const e of [...data.edge_types].sort((a, b) => a.name.localeCompare(b.name))) {
    const ends = { self: new Set<string>(), in: new Set<string>(), out: new Set<string>() };
    for (const [source, target] of e.pairs) {
      if (source === name && target === name) ends.self.add(name);
      else if (source === name) ends.out.add(target);
      else if (target === name) ends.in.add(source);
    }
    for (const direction of Object.keys(ORDER) as TypeEdge["direction"][]) {
      if (ends[direction].size) found.push({ direction, edge: e.name, others: [...ends[direction]].sort() });
    }
  }
  return found;
}
