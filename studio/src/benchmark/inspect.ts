import type { InspectorElement, InspectorView } from "../api/types";

/** Elements are the same across runs by source (type + source graph node) or by name (type + name). */
export type Identity = "source" | "name";
export type Filter = "all" | "diff" | "stable";
export type Status = { cls: string; text: string; diff: boolean };

/** One element of the inspector: its occurrences per run under the chosen identity, and the flip cause if any. */
export type Item = { key: string; type: string; layer: string; name: string; byRun: Record<string, InspectorElement>; cause?: string };

export function itemsOf(view: InspectorView, identity: Identity): Item[] {
  const items = new Map<string, Item>();
  for (const e of view.elements) {
    const key = identity === "source" ? e.by_source : e.by_name;
    const item = items.get(key) ?? { key, type: e.type, layer: e.layer, name: e.name, byRun: {} };
    item.byRun[e.run] ??= e;
    items.set(key, item);
  }
  for (const item of items.values()) {
    item.cause = Object.values(item.byRun)
      .map((e) => view.causes[e.by_source])
      .find(Boolean);
  }
  return [...items.values()].sort((a, b) => a.layer.localeCompare(b.layer) || a.type.localeCompare(b.type) || a.name.localeCompare(b.name));
}

/** Besides presence, what may differ between runs: the source (identity by name) or the name (identity by source). */
function variant(e: InspectorElement, identity: Identity): string {
  return identity === "name" ? e.source : e.name;
}

function variantLabel(identity: Identity): string {
  return identity === "name" ? "source" : "name";
}

export function statusUnion(item: Item, runs: string[], identity: Identity): Status {
  const present = runs.filter((r) => item.byRun[r]);
  if (present.length < runs.length) return { cls: "d-partial", text: `in ${present.join(", ")} (${present.length}/${runs.length})`, diff: true };
  const variants = new Set(present.map((r) => variant(item.byRun[r], identity)));
  if (variants.size > 1) {
    return { cls: "d-changed", text: `${variantLabel(identity)}: ${present.map((r) => `${variant(item.byRun[r], identity)} (${r})`).join(" · ")}`, diff: true };
  }
  return { cls: "", text: `${runs.length}/${runs.length}`, diff: false };
}

export function statusRun(item: Item, run: string, runs: string[], identity: Identity): Status {
  if (!item.byRun[run]) return { cls: "d-ghost", text: `not in ${run} (in ${runs.filter((r) => item.byRun[r]).join(", ")})`, diff: true };
  const others = runs.filter((r) => r !== run);
  const missing = others.filter((r) => !item.byRun[r]);
  if (missing.length) return { cls: "d-partial", text: `missing in ${missing.join(", ")}`, diff: true };
  const mine = variant(item.byRun[run], identity);
  const changed = others.filter((r) => variant(item.byRun[r], identity) !== mine);
  if (changed.length) {
    return { cls: "d-changed", text: `${variantLabel(identity)} ${mine} here, ${changed.map((r) => `${variant(item.byRun[r], identity)} in ${r}`).join(", ")}`, diff: true };
  }
  return { cls: "", text: "same in every run", diff: false };
}

/** The item on side ``a`` or ``b`` of a run-to-run comparison; null when neither run has it. */
export function statusPair(item: Item, side: "a" | "b", a: string, b: string, identity: Identity): Status | null {
  const [me, them] = side === "a" ? [a, b] : [b, a];
  const mine = item.byRun[me];
  const theirs = item.byRun[them];
  if (!mine && !theirs) return null;
  if (!mine) return { cls: "d-ghost", text: `only in ${them}`, diff: true };
  if (!theirs) return { cls: side === "a" ? "d-only-a" : "d-only-b", text: `only in ${me}`, diff: true };
  const here = variant(mine, identity);
  const there = variant(theirs, identity);
  if (here !== there) return { cls: "d-changed", text: `${variantLabel(identity)} ${here} (${them}: ${there})`, diff: true };
  return { cls: "", text: "", diff: false };
}

export function keep(status: Status | null, filter: Filter): status is Status {
  return !!status && (filter === "all" || (filter === "diff" ? status.diff : !status.diff));
}

/** An element and a relationship as anywidget-archimate draws them, with their comparison status and badge. */
export type DiagramElement = { id: string; name: string; type: string; layer: string; documentation: string; status: string; badge: string };
export type DiagramRelationship = { id: string; type: string; source: string; target: string; name: string; status: string };
export type DiagramView = { kind: "union" } | { kind: "run"; run: string };

const WIDGET_STATUS: Record<string, string> = { "": "stable", "d-partial": "partial", "d-changed": "changed", "d-ghost": "ghost", "d-only-a": "only_a", "d-only-b": "only_b" };

function shortBadge(item: Item, status: Status, runs: string[], identity: Identity, shown: DiagramView): string {
  if (!status.diff) return "";
  if (status.cls === "d-changed") return `${variantLabel(identity)} differs`;
  if (shown.kind === "union") return `${runs.filter((r) => item.byRun[r]).length}/${runs.length}`;
  if (status.cls === "d-ghost") return "not in this run";
  const missing = runs.filter((r) => r !== shown.run && !item.byRun[r]).length;
  return `missing in ${missing} run${missing === 1 ? "" : "s"}`;
}

/** The runs' models as one ArchiMate diagram (all runs, or one run with ghosts for what only other runs have). */
export function diagramOf(view: InspectorView, identity: Identity, shown: DiagramView, filter: Filter): { elements: DiagramElement[]; relationships: DiagramRelationship[] } {
  const runs = view.runs;
  const elements: DiagramElement[] = [];
  for (const item of itemsOf(view, identity)) {
    const status = shown.kind === "run" ? statusRun(item, shown.run, runs, identity) : statusUnion(item, runs, identity);
    if (!keep(status, filter)) continue;
    elements.push({
      id: item.key,
      name: (shown.kind === "run" && item.byRun[shown.run]?.name) || item.name,
      type: item.type,
      layer: item.layer,
      documentation: item.cause ?? "",
      status: WIDGET_STATUS[status.cls] ?? "stable",
      badge: shortBadge(item, status, runs, identity, shown),
    });
  }
  const shownIds = new Set(elements.map((e) => e.id));
  const grouped = new Map<string, { type: string; source: string; target: string; runs: Set<string> }>();
  for (const r of view.relationships) {
    const source = identity === "source" ? r.source_by_source : r.source_by_name;
    const target = identity === "source" ? r.target_by_source : r.target_by_name;
    const id = `${r.type}|${source}|${target}`;
    const entry = grouped.get(id) ?? { type: r.type, source, target, runs: new Set<string>() };
    entry.runs.add(r.run);
    grouped.set(id, entry);
  }
  const relationships: DiagramRelationship[] = [];
  for (const [id, r] of grouped) {
    if (!shownIds.has(r.source) || !shownIds.has(r.target)) continue;
    if (shown.kind === "run" && !r.runs.has(shown.run)) continue;
    relationships.push({ id, type: r.type, source: r.source, target: r.target, name: "", status: r.runs.size === runs.length ? "stable" : "partial" });
  }
  return { elements, relationships };
}
