import { describe, expect, it } from "vitest";

import type { LinkedView, RunEvent } from "../api/types";
import {
  changedElements,
  edgeKey,
  INTERMEDIATE_COLORS,
  lanesChanged,
  LAYER_COLORS,
  linkedNote,
  newItems,
  ofTotal,
  pulseFrom,
  REJECTED_COLOR,
  removedItems,
  themeFromTokens,
  toWidgetIds,
  typeColors,
  withLaneLayouts,
  withLayerColors,
  withModelLane,
} from "./linkedView";

const lanes = [
  { id: "intermediate", title: "Intermediate graph" },
  { id: "output", title: "Output graph" },
];
const view = (nodes: string[], edges: [string, string, string?][]): LinkedView => ({
  lanes,
  nodes: nodes.map((id) => ({ id, deriva_id: `d-${id}` })),
  edges: edges.map(([source, target, label]) => ({ source, target, label })),
  missing_links: 0,
});
const progress = (data: RunEvent["data"], seq = 1): RunEvent => ({ seq, event: "progress", data });

describe("linked view diff", () => {
  it("sends only what the widget does not show yet, in order", () => {
    const shown = view(["1", "2"], [["1", "2", "CONTAINS"]]);
    const next = view(["1", "2", "3"], [
      ["1", "2", "CONTAINS"],
      ["3", "1", "DERIVED_FROM"],
    ]);
    expect(newItems(shown, next)).toEqual({ nodes: [{ id: "3", deriva_id: "d-3" }], edges: [{ source: "3", target: "1", label: "DERIVED_FROM" }] });
    expect(edgeKey({ source: "a", target: "b" })).toBe("a|b|");
  });

  it("maps Deriva ids to the widget's node ids", () => {
    expect(toWidgetIds(view(["1", "2"], []), ["d-2", "d-9"])).toEqual(["2"]);
  });

  it("lists the nodes and edges that left (a re-sample, or an element that left the model)", () => {
    const shown = view(["1", "2", "3"], [
      ["1", "2", "CONTAINS"],
      ["3", "model", "IN_MODEL"],
    ]);
    const next = view(["1", "3"], []);
    expect(removedItems(shown, next)).toEqual({
      nodes: ["2"],
      edges: [
        { source: "1", target: "2", label: "CONTAINS" },
        { source: "3", target: "model", label: "IN_MODEL" },
      ],
    });
    expect(removedItems(next, next)).toEqual({ nodes: [], edges: [] });
  });

  it("finds elements whose place in the model changed, in their new state", () => {
    const shown: LinkedView = { ...view([], []), nodes: [{ id: "1", enabled: true }, { id: "2" }, { id: "3", enabled: false }] };
    const next: LinkedView = { ...view([], []), nodes: [{ id: "1", enabled: false }, { id: "2" }, { id: "3", enabled: false }, { id: "4", enabled: false }] };
    expect(changedElements(shown, next)).toEqual([{ id: "1", enabled: false }]);
  });
});

describe("lane notes", () => {
  const nodes = [
    { id: "9", lane: "repository" },
    { id: "10", lane: "intermediate" },
    { id: "11", lane: "intermediate" },
    { id: "20", lane: "output", enabled: true },
    { id: "21", lane: "output", enabled: false },
  ];
  const edges = [
    { source: "9", target: "10", label: "CONTAINS" },
    { source: "20", target: "10", label: "DERIVED_FROM", cross: true },
    { source: "20", target: "model", label: "IN_MODEL", cross: true },
  ];

  it("counts a sampled intermediate graph against its totals, and the elements in the model", () => {
    const sampled: LinkedView = { lanes, nodes, edges, missing_links: 0, totals: { nodes: { Repository: 1, File: 2754, Method: 2 }, edges: { CONTAINS: 4922 } } };
    expect(linkedNote(sampled)).toBe("1 repository · 2 of 2,756 graph nodes · 1 of 4,922 edges · 2 elements, 1 in the model");
  });

  it("counts a graph shown whole without totals", () => {
    expect(linkedNote({ lanes, nodes: nodes.slice(0, 4), edges: [], missing_links: 0 })).toBe("1 repository · 2 graph nodes · 1 element");
  });

  it("says how much of a total is shown", () => {
    expect(ofTotal(300, 2757, "node", "nodes")).toBe("300 of 2,757 nodes");
    expect(ofTotal(44, 44, "node", "nodes")).toBe("44 nodes");
    expect(ofTotal(1, undefined, "edge", "edges")).toBe("1 edge");
  });
});

describe("pulse", () => {
  it("pulses the candidates of the running step until it completes", () => {
    const started = progress({ step: "ApplicationComponent", status: "processing", candidates: ["a", "b"] });
    expect(pulseFrom([started], "running")).toEqual(["a", "b"]);
    expect(pulseFrom([started, progress({ step: "ApplicationComponent", status: "complete" }, 2)], "running")).toEqual([]);
  });

  it("stops when the run is cancelled or fails during a step", () => {
    const started = progress({ step: "ApplicationComponent", status: "processing", candidates: ["a"] });
    expect(pulseFrom([started], "cancelled")).toEqual([]);
    expect(pulseFrom([started], "error")).toEqual([]);
  });
});

describe("layer colours", () => {
  it("colours output elements by ArchiMate layer and leaves graph nodes alone", () => {
    const nodes = withLayerColors([
      { id: "1", lane: "output", labels: ["BusinessProcess"] },
      { id: "2", lane: "output", labels: ["ApplicationComponent"] },
      { id: "3", lane: "output", labels: ["DataObject"] },
      { id: "4", lane: "output", labels: ["Node"] },
      { id: "5", lane: "intermediate", labels: ["File"] },
    ]);
    expect(nodes.map((n) => n.color)).toEqual([LAYER_COLORS.business, LAYER_COLORS.application, LAYER_COLORS.application, LAYER_COLORS.technology, undefined]);
    // The layer itself too, for the output lane's rows (business on top, technology at the bottom)
    expect(nodes.map((n) => n.layer)).toEqual(["business", "application", "application", "technology", undefined]);
  });

  it("greys out elements refine rejected", () => {
    const nodes = withLayerColors([
      { id: "1", lane: "output", labels: ["BusinessActor"], enabled: false },
      { id: "2", lane: "output", labels: ["BusinessActor"], enabled: true },
    ]);
    expect(nodes.map((n) => n.color)).toEqual([REJECTED_COLOR, LAYER_COLORS.business]);
    // They stay in the row of the layer they were derived for, only grey
    expect(nodes.map((n) => n.layer)).toEqual(["business", "business"]);
  });
});

describe("type colours", () => {
  const nodes = [
    { id: "1", lane: "intermediate", labels: ["Method"] },
    { id: "2", lane: "output", labels: ["BusinessObject"] },
    { id: "3", lane: "output", labels: ["Node"] },
  ];

  it("gives the intermediate types their palette for the theme and each element type its layer colour", () => {
    const dark = typeColors(nodes, true).nodes;
    const light = typeColors(nodes, false).nodes;
    expect(dark.Method).toBe(INTERMEDIATE_COLORS.dark.Method);
    expect(light.Method).toBe(INTERMEDIATE_COLORS.light.Method);
    expect(dark.BusinessObject).toBe(LAYER_COLORS.business);
    expect(light.Node).toBe(LAYER_COLORS.technology);
  });

  it("reads a graph node named like a layer as the intermediate type it is", () => {
    expect(typeColors([{ id: "1", lane: "intermediate", labels: ["Technology"] }], true).nodes.Technology).toBe(INTERMEDIATE_COLORS.dark.Technology);
  });

  it("gives every intermediate type a distinct colour, except the technology evidence pair", () => {
    for (const palette of [INTERMEDIATE_COLORS.dark, INTERMEDIATE_COLORS.light]) {
      expect(palette.Technology).toBe(palette.ExternalDependency);
      const rest = Object.entries(palette).filter(([type]) => type !== "ExternalDependency");
      expect(new Set(rest.map(([, color]) => color)).size).toBe(rest.length);
    }
  });
});

describe("theme", () => {
  it("reads the studio tokens", () => {
    const tokens: Record<string, string> = { "--bg": " #15171c", "--bg2": "#1c1f26", "--text": "#e7e9ee", "--muted": "#9aa2b0", "--line": "#353b46", "--accent": "#5bb8a9" };
    expect(themeFromTokens({ getPropertyValue: (name: string) => tokens[name] ?? "" })).toEqual({
      background: "#15171c",
      panel: "#1c1f26",
      text: "#e7e9ee",
      muted: "#9aa2b0",
      border: "#353b46",
      accent: "#5bb8a9",
    });
  });
});

describe("lanes", () => {
  const view: LinkedView = { lanes, nodes: [], edges: [], missing_links: 0 };

  it("ends with the model: a glyph in the ArchiMate layer colours that opens the model", () => {
    const model = withModelLane(view.lanes).at(-1);
    expect(model).toMatchObject({ id: "model", title: "Model", action: true, caption: "View model" });
    expect(model?.glyph).toEqual([LAYER_COLORS.business, LAYER_COLORS.application, LAYER_COLORS.technology]);
    expect(withModelLane(view.lanes).slice(0, -1)).toEqual(view.lanes);
  });

  it("spreads the intermediate graph with forces and stacks the output lane by layer, business on top", () => {
    const laid = withLaneLayouts([{ id: "repository", title: "Repository", arrange: "column" }, ...view.lanes]);
    const lane = (id: string) => laid.find((l) => l.id === id);
    expect(lane("intermediate")).toMatchObject({ layout: "force", relayout: 0.33, width: 1.6, labels: { count: 12 } });
    expect(lane("output")).toMatchObject({ rows: { field: "layer", order: ["business", "application", "technology"] }, relayout: 0.33, labels: { count: 16 } });
    expect(lane("output")?.width).toBeUndefined();
    expect(lane("repository")).toEqual({ id: "repository", title: "Repository", arrange: "column" });
  });

  it("notices changed lanes (a second repository renames the repository lane)", () => {
    expect(lanesChanged(view, { ...view, lanes: [{ id: "repository", title: "Repositories" }, ...lanes] })).toBe(true);
    expect(lanesChanged(view, { ...view })).toBe(false);
  });
});
