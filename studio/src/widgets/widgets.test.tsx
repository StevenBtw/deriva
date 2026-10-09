import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ArchimateWidget } from "./ArchimateWidget";
import { GraphWidget } from "./GraphWidget";
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
  });

  it("updates nodes and edges when the view changes", async () => {
    const { loader, models } = capturingLoader();
    const { rerender } = render(<GraphWidget database="graph" view={{ nodes: [], edges: [] }} dark={false} loader={loader} />);
    await waitFor(() => expect(models).toHaveLength(1));

    rerender(<GraphWidget database="graph" view={{ nodes: [{ id: "a" }], edges: [{ source: "a", target: "a" }] }} dark={false} loader={loader} />);

    await waitFor(() => expect(models[0].get("nodes")).toEqual([{ id: "a" }]));
    expect(models[0].get("edges")).toEqual([{ source: "a", target: "a" }]);
  });

  it("shows a message when the widget cannot be loaded", async () => {
    const loader = vi.fn(async () => {
      throw new Error("Failed to fetch https://esm.sh/graphology");
    });

    render(<GraphWidget database="graph" view={{ nodes: [], edges: [] }} dark={false} loader={loader} />);

    expect(await screen.findByText(/Widget could not be loaded/)).toHaveTextContent("esm.sh");
  });
});

describe("ArchimateWidget", () => {
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
