import type { GraphView, IntermediateOntology, WidgetEdge, WidgetNode } from "../api/types";

/** The schema graph's colours (from the theme's tokens): one per group, a faint one for types without nodes, the edges'. */
export type SchemaColors = { groups: Record<string, string>; empty: string; edge: string };
export type SchemaFilter = { hiddenGroups: ReadonlySet<string>; showEmpty: boolean; edgeType: string | null };
export type TypeEdge = { direction: "in" | "out" | "self"; edge: string; others: string[] };

const groupOf = (data: IntermediateOntology, group: string) => (data.groups.includes(group) ? group : "other");

/** Bigger for more nodes, on a log scale (two thousand methods next to one repository still both read). */
export const nodeSize = (count: number) => (count > 0 ? 5 + 3 * Math.log10(count + 1) : 3.5);
const edgeSize = (count: number) => 0.6 + 0.7 * Math.log10(count + 1);

// How the widget draws the graph: it fits the whole layout into the view (about this many pixels, inside its
// margin) and writes a type's label (12 px, about 7 px a character) to the right of its node
const VIEW = { width: 900, height: 560 };
const LABEL = { char: 7, height: 16, gap: 3 };

export type LabelBox = { name: string; x1: number; x2: number; y1: number; y2: number };

const extent = (values: number[]) => Math.max(...values) - Math.min(...values);

/** Layout units per pixel when the widget fits these positions into the view. */
function unitsPerPixel(points: { x: number; y: number }[]): number {
  return Math.max(extent(points.map((p) => p.x)) / VIEW.width, extent(points.map((p) => p.y)) / VIEW.height) || 0.01;
}

function boxAt(name: string, p: { x: number; y: number }, radius: number, perPx: number): LabelBox {
  const half = (LABEL.height / 2) * perPx;
  return { name, x1: p.x - radius * perPx, x2: p.x + (radius + LABEL.gap + LABEL.char * name.length) * perPx, y1: p.y - half, y2: p.y + half };
}

/** Each type's node and label as a box in layout units, as the widget draws them when it fits the layout into view. */
export function labelBoxes(at: Map<string, { x: number; y: number }>, data: IntermediateOntology): LabelBox[] {
  const perPx = unitsPerPixel([...at.values()]);
  return data.node_types.filter((t) => at.has(t.name)).map((t) => boxAt(t.name, at.get(t.name)!, nodeSize(t.count), perPx));
}

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
  separateLabels(names, data.node_types.map((t) => nodeSize(t.count)), pos);
  return new Map(names.map((name, i) => [name, { x: Math.round(pos[i].x * 1000) / 10, y: Math.round(pos[i].y * 1000) / 10 }]));
}

/** The force layout knows nothing of labels: two linked types of one group can sit closer than their labels are wide.
 * Push every pair whose node-and-label boxes overlap apart along the axis that needs the shorter move, half each,
 * in a fixed order, until none overlap (the same result every time). A pixel of margin stays between boxes, more
 * than the rounding of the returned positions moves them. */
function separateLabels(names: string[], radii: number[], pos: { x: number; y: number }[]): void {
  for (let round = 0; round < 200; round++) {
    const perPx = unitsPerPixel(pos);
    const margin = perPx; // a pixel between boxes
    const boxes = pos.map((p, i) => boxAt(names[i], p, radii[i], perPx));
    let moved = false;
    for (let a = 0; a < pos.length; a++) {
      for (let b = a + 1; b < pos.length; b++) {
        const across = Math.min(boxes[a].x2, boxes[b].x2) - Math.max(boxes[a].x1, boxes[b].x1);
        const along = Math.min(boxes[a].y2, boxes[b].y2) - Math.max(boxes[a].y1, boxes[b].y1);
        if (across <= -margin || along <= -margin) continue;
        moved = true;
        // The axis with less overlap (vertical on a tie); the first type moves up, or right, when the two are level
        if (along <= across) {
          const shift = (along + margin) / 2, up = pos[a].y >= pos[b].y ? 1 : -1;
          pos[a].y += up * shift;
          pos[b].y -= up * shift;
          boxes[a] = boxAt(names[a], pos[a], radii[a], perPx);
          boxes[b] = boxAt(names[b], pos[b], radii[b], perPx);
        } else {
          const shift = (across + margin) / 2, right = pos[a].x >= pos[b].x ? 1 : -1;
          pos[a].x += right * shift;
          pos[b].x -= right * shift;
          boxes[a] = boxAt(names[a], pos[a], radii[a], perPx);
          boxes[b] = boxAt(names[b], pos[b], radii[b], perPx);
        }
      }
    }
    if (!moved) return;
  }
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
