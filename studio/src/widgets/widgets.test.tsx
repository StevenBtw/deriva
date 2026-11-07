import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ArchimateWidget } from "./ArchimateWidget";
import { GraphWidget } from "./GraphWidget";
import { LinkedGraphWidget } from "./LinkedGraphWidget";
import type { WidgetModel } from "./host";

function capturingLoader() {
  const models: WidgetModel[] = [];
  const loader = vi.fn(async () => ({
    default: {
      render: ({ model }: { model: WidgetModel }) => {
        models.push(model);
      },
    },
  }));
  return { loader, models };
}

describe("GraphWidget", () => {
  it("points anywidget-graph at the studio's grafeo endpoints in server mode", async () => {
    const { loader, models } = capturingLoader();

    render(<GraphWidget database="model" view={{ nodes: [{ id: "1", label: "Core" }], edges: [] }} dark loader={loader} />);

    await waitFor(() => expect(models).toHaveLength(1));
    const model = models[0];
    expect(loader).toHaveBeenCalledWith("/widgets/anywidget-graph/index.js");
    expect(model.get("database_backend")).toBe("grafeo");
    expect(model.get("grafeo_connection_mode")).toBe("server");
    expect(model.get("grafeo_server_url")).toBe(`${window.location.origin}/grafeo`);
    expect(model.get("connection_database")).toBe("model");
    expect(model.get("nodes")).toEqual([{ id: "1", label: "Core" }]);
    expect(model.get("dark_mode")).toBe(true);
    expect(model.get("fill")).toBe(true);
    // The shim has no Python defaults: a trait the studio leaves out reads as undefined (labels would stay off)
    expect(model.get("show_labels")).toBe(true);
    // A typed query draws at most as many nodes as the view (anywidget-graph 0.5.2 and later)
    expect(model.get("max_query_nodes")).toBe(300);
  });

  it("updates nodes and edges when the view changes", async () => {
    const { loader, models } = capturingLoader();
    const { rerender } = render(<GraphWidget database="graph" view={{ nodes: [], edges: [] }} dark={false} loader={loader} />);
    await waitFor(() => expect(models).toHaveLength(1));

    rerender(<GraphWidget database="graph" view={{ nodes: [{ id: "a" }], edges: [{ source: "a", target: "a" }] }} dark={false} loader={loader} />);

    await waitFor(() => expect(models[0].get("nodes")).toEqual([{ id: "a" }]));
    expect(models[0].get("edges")).toEqual([{ source: "a", target: "a" }]);
  });

  it("passes the totals of a sampled graph and the colours per type", async () => {
    const { loader, models } = capturingLoader();
    const totals = { nodes: { File: 40 }, edges: { CONTAINS: 39 } };
    const typeColors = { nodes: { File: "#999fa8" } };

    render(<GraphWidget database="graph" view={{ nodes: [], edges: [], totals }} typeColors={typeColors} dark={false} loader={loader} />);

    await waitFor(() => expect(models).toHaveLength(1));
    expect(models[0].get("totals")).toEqual(totals);
    expect(models[0].get("type_colors")).toEqual(typeColors);
  });

  it("hands its settings to the widget at mount and again when they change", async () => {
    const { loader, models } = capturingLoader();
    const view = { nodes: [], edges: [] };
    const { rerender } = render(<GraphWidget database="graph" view={view} dark={false} loader={loader} settings={{ layout: "preset", edge_arrows: true, show_query_input: false }} />);
    await waitFor(() => expect(models).toHaveLength(1));
    expect(models[0].get("layout")).toBe("preset");
    expect(models[0].get("edge_arrows")).toBe(true);
    expect(models[0].get("show_query_input")).toBe(false);

    rerender(<GraphWidget database="graph" view={view} dark={false} loader={loader} settings={{ layout: "preset", edge_arrows: false, show_query_input: false }} />);

    await waitFor(() => expect(models[0].get("edge_arrows")).toBe(false));
  });

  it("reports the node a viewer selects, and nothing when the selection is cleared", async () => {
    const { loader, models } = capturingLoader();
    const onSelect = vi.fn();
    render(<GraphWidget database="graph" view={{ nodes: [{ id: "File" }], edges: [] }} dark={false} loader={loader} onSelect={onSelect} />);
    await waitFor(() => expect(models).toHaveLength(1));

    models[0].set("selected_node", { id: "File", label: "File" });
    models[0].set("selected_node", null);

    expect(onSelect.mock.calls).toEqual([["File"], [null]]);
  });

  it("clears a query's note when the view changes (another repository)", async () => {
    const { loader, models } = capturingLoader();
    const { rerender } = render(<GraphWidget database="graph" view={{ nodes: [{ id: "a" }], edges: [] }} dark={false} loader={loader} />);
    await waitFor(() => expect(models).toHaveLength(1));
    models[0].set("query_note", "The query returned 9,161 nodes; the 300 best connected are drawn (max_query_nodes).");

    rerender(<GraphWidget database="graph" view={{ nodes: [{ id: "b" }], edges: [] }} dark={false} loader={loader} />);

    await waitFor(() => expect(models[0].get("nodes")).toEqual([{ id: "b" }]));
    expect(models[0].get("query_note")).toBe("");
  });

  it("reports what it draws: the host's view, then a query's result", async () => {
    const { loader, models } = capturingLoader();
    const onDrawn = vi.fn();
    render(<GraphWidget database="graph" view={{ nodes: [{ id: "a" }], edges: [] }} dark={false} loader={loader} onDrawn={onDrawn} />);
    await waitFor(() => expect(models).toHaveLength(1));
    await waitFor(() => expect(onDrawn).toHaveBeenLastCalledWith({ nodes: 1, edges: 0 }));

    // The query box sets the widget's own nodes and edges to the result
    models[0].set({ nodes: [{ id: "a" }, { id: "b" }, { id: "c" }], edges: [{ source: "a", target: "b" }] });

    expect(onDrawn).toHaveBeenLastCalledWith({ nodes: 3, edges: 1 });
  });

  it("selects the node the host picks, as a click would", async () => {
    const { loader, models } = capturingLoader();
    const view = { nodes: [{ id: "File" }, { id: "Method" }], edges: [] };
    const { rerender } = render(<GraphWidget database="graph" view={view} dark={false} loader={loader} selected="File" />);
    await waitFor(() => expect(models).toHaveLength(1));
    expect(models[0].get("selected_nodes")).toEqual(["File"]);
    expect(models[0].get("selected_node")).toEqual({ id: "File" });

    rerender(<GraphWidget database="graph" view={view} dark={false} loader={loader} selected={null} />);

    await waitFor(() => expect(models[0].get("selected_nodes")).toEqual([]));
    expect(models[0].get("selected_node")).toBeNull();
  });

  it("shows a message when the widget cannot be loaded", async () => {
    const loader = vi.fn(async () => {
      throw new Error("Failed to fetch https://esm.sh/graphology");
    });

    render(<GraphWidget database="graph" view={{ nodes: [], edges: [] }} dark={false} loader={loader} />);

    expect(await screen.findByText(/Widget could not be loaded/)).toHaveTextContent("esm.sh");
  });
});

describe("useWidget", () => {
  const writing = (text: string) => async () => ({ default: { render: ({ el }: { el: HTMLElement }) => void (el.textContent = text) } });

  it("keeps a mount that finishes late out of the widget that replaced it", async () => {
    let finish: () => void = () => {};
    const late = () => new Promise<unknown>((resolve) => (finish = () => resolve(writing("old widget")())));
    const { container, rerender } = render(<ArchimateWidget elements={[]} relationships={[]} dark={false} loader={late} />);

    rerender(<ArchimateWidget elements={[]} relationships={[]} dark={false} loader={writing("new widget")} />);
    await waitFor(() => expect(container).toHaveTextContent("new widget"));
    finish();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(container).not.toHaveTextContent("old widget");
  });

  it("drops an old load error once another load starts", async () => {
    const failing = vi.fn(async () => {
      throw new Error("Failed to fetch the widget");
    });
    const { rerender } = render(<ArchimateWidget elements={[]} relationships={[]} dark={false} loader={failing} />);
    expect(await screen.findByText(/Widget could not be loaded/)).toBeInTheDocument();

    rerender(<ArchimateWidget elements={[]} relationships={[]} dark={false} loader={() => new Promise(() => {})} />);

    expect(screen.queryByText(/Widget could not be loaded/)).not.toBeInTheDocument();
  });
});

describe("ArchimateWidget", () => {
  it("follows a new height", async () => {
    const { loader, models } = capturingLoader();
    const { rerender } = render(<ArchimateWidget elements={[]} relationships={[]} dark={false} height={300} loader={loader} />);
    await waitFor(() => expect(models).toHaveLength(1));

    rerender(<ArchimateWidget elements={[]} relationships={[]} dark={false} height={480} loader={loader} />);

    await waitFor(() => expect(models[0].get("height")).toBe(480));
  });

  it("passes the model and reports selected elements", async () => {
    const { loader, models } = capturingLoader();
    const onSelect = vi.fn();
    const elements = [{ id: "n1", name: "Application Server", type: "Node", layer: "Technology", documentation: "" }];

    render(<ArchimateWidget elements={elements} relationships={[]} dark onSelect={onSelect} loader={loader} />);

    await waitFor(() => expect(models).toHaveLength(1));
    expect(models[0].get("elements")).toEqual(elements);
    models[0].set("selected_element", { id: "n1", name: "Application Server" });
    models[0].save_changes();
    expect(onSelect).toHaveBeenCalledWith({ id: "n1", name: "Application Server" });
  });
});

describe("LinkedGraphWidget", () => {
  const view = {
    lanes: [
      { id: "intermediate", title: "Intermediate graph" },
      { id: "output", title: "Output graph" },
    ],
    nodes: [{ id: "1", lane: "intermediate" }],
    edges: [],
    missing_links: 0,
  };

  function featuredLoader(features: string[] | null) {
    const models: WidgetModel[] = [];
    const loader = vi.fn(async () => ({
      default: {
        render: ({ model }: { model: WidgetModel }) => {
          if (features) model.set("_features", features);
          models.push(model);
        },
      },
    }));
    return { loader, models };
  }

  it("mounts one widget with lanes, the studio theme and no query bar", async () => {
    const { loader, models } = featuredLoader(["lanes", "append", "pulse", "theme"]);
    render(<LinkedGraphWidget view={view} batch={null} pulse={[]} dark loader={loader} />);
    await waitFor(() => expect(models).toHaveLength(1));
    expect(models[0].get("lanes")).toEqual(view.lanes);
    expect(models[0].get("nodes")).toEqual(view.nodes);
    expect(models[0].get("theme")).toHaveProperty("accent");
    expect(models[0].get("show_query_input")).toBe(false);
    expect(models[0].get("show_labels")).toBe(true);
  });

  it("sends append batches and pulse ids, and a theme change without reloading nodes", async () => {
    const { loader, models } = featuredLoader(["lanes", "append", "pulse", "theme"]);
    const { rerender } = render(<LinkedGraphWidget view={view} batch={null} pulse={[]} dark loader={loader} />);
    await waitFor(() => expect(models).toHaveLength(1));
    const model = models[0];
    const setSpy = vi.spyOn(model, "set");
    const batch = { seq: 1, nodes: [{ id: "2", lane: "output" }], edges: [{ source: "2", target: "1", cross: true }] };

    rerender(<LinkedGraphWidget view={view} batch={batch} pulse={["1"]} dark loader={loader} />);
    await waitFor(() => expect(model.get("append_batch")).toEqual(batch));
    expect(model.get("pulse_nodes")).toEqual(["1"]);

    setSpy.mockClear();
    rerender(<LinkedGraphWidget view={view} batch={batch} pulse={["1"]} dark={false} loader={loader} />);
    await waitFor(() => expect(setSpy).toHaveBeenCalledWith(expect.objectContaining({ dark_mode: false, theme: expect.any(Object) })));
    const keys = setSpy.mock.calls.flatMap(([key]) => (typeof key === "string" ? [key] : Object.keys(key)));
    expect(keys).not.toContain("nodes");
  });

  it("reports a click on an action lane's glyph", async () => {
    const { loader, models } = featuredLoader(["lanes", "lane_actions"]);
    const onLaneAction = vi.fn();
    render(<LinkedGraphWidget view={view} batch={null} pulse={[]} dark loader={loader} onLaneAction={onLaneAction} />);
    await waitFor(() => expect(models).toHaveLength(1));

    models[0].set("lane_action", { lane: "model", seq: 1 });
    models[0].save_changes();

    expect(onLaneAction).toHaveBeenCalledWith("model");
  });

  it("tells the host what the widget supports and passes the sample's totals", async () => {
    const { loader, models } = featuredLoader(["lanes", "append", "remove", "totals", "action_edges"]);
    const onFeatures = vi.fn();
    const totals = { nodes: { File: 40 }, edges: { CONTAINS: 39 } };
    const { rerender } = render(<LinkedGraphWidget view={view} batch={null} pulse={[]} dark loader={loader} onFeatures={onFeatures} />);
    await waitFor(() => expect(onFeatures).toHaveBeenCalledWith(["lanes", "append", "remove", "totals", "action_edges"]));

    rerender(<LinkedGraphWidget view={view} batch={null} pulse={[]} totals={totals} dark loader={loader} onFeatures={onFeatures} />);

    await waitFor(() => expect(models[0].get("totals")).toEqual(totals));
  });

  it("sends the colours per type, again when they change (a theme switch)", async () => {
    const { loader, models } = featuredLoader(["lanes", "type_colors"]);
    const dark = { nodes: { Method: "#8b87d8" } };
    const light = { nodes: { Method: "#7f79d1" } };
    const { rerender } = render(<LinkedGraphWidget view={view} batch={null} pulse={[]} typeColors={dark} dark loader={loader} />);
    await waitFor(() => expect(models[0]?.get("type_colors")).toEqual(dark));

    rerender(<LinkedGraphWidget view={view} batch={null} pulse={[]} typeColors={light} dark={false} loader={loader} />);

    await waitFor(() => expect(models[0].get("type_colors")).toEqual(light));
  });

  it("reports an older widget without lanes", async () => {
    const { loader } = featuredLoader(null);
    const onUnsupported = vi.fn();
    render(<LinkedGraphWidget view={view} batch={null} pulse={[]} dark loader={loader} onUnsupported={onUnsupported} />);
    await waitFor(() => expect(onUnsupported).toHaveBeenCalled());
  });
});
