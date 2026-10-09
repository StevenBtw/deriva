import { describe, expect, it, vi } from "vitest";

import { createModel, mountWidget } from "./host";

describe("createModel", () => {
  it("notifies listeners only when changes are saved", () => {
    const model = createModel({ nodes: [], dark_mode: true });
    const onNodes = vi.fn();
    const onAny = vi.fn();
    model.on("change:nodes", onNodes);
    model.on("change", onAny);

    model.set("nodes", [{ id: "a" }]);
    expect(model.get("nodes")).toEqual([{ id: "a" }]);
    expect(onNodes).not.toHaveBeenCalled();

    model.save_changes();
    expect(onNodes).toHaveBeenCalledTimes(1);
    expect(onAny).toHaveBeenCalledTimes(1);
  });

  it("removes listeners with off", () => {
    const model = createModel({ x: 1 });
    const cb = vi.fn();
    model.on("change:x", cb);
    model.off("change:x", cb);

    model.set("x", 2);
    model.save_changes();

    expect(cb).not.toHaveBeenCalled();
  });

  it("lets the host listen to widget-side saves", () => {
    const model = createModel({ selected_element: null });
    const cb = vi.fn();
    model.on("change:selected_element", cb);

    model.set("selected_element", { id: "n1" });
    model.save_changes();

    expect(cb).toHaveBeenCalledWith(expect.anything(), { id: "n1" });
  });
});

describe("mountWidget", () => {
  it("calls render once with the model and element and cleans up on destroy", async () => {
    const cleanup = vi.fn();
    const render = vi.fn(() => cleanup);
    const el = document.createElement("div");

    const mounted = await mountWidget({ moduleUrl: "/widgets/x/index.js", cssUrl: "/widgets/x/styles.css", el, state: { a: 1 }, loader: async () => ({ default: { render } }) });

    expect(render).toHaveBeenCalledTimes(1);
    const args = (render.mock.calls[0] as unknown as [{ model: { get: (k: string) => unknown }; el: HTMLElement }])[0];
    expect(args.el).toBe(el);
    expect(args.model.get("a")).toBe(1);
    mounted.destroy();
    expect(cleanup).toHaveBeenCalledTimes(1);
  });

  it("supports a default export that is a function and calls initialize", async () => {
    const initialize = vi.fn();
    const render = vi.fn();
    const el = document.createElement("div");

    await mountWidget({ moduleUrl: "/m.js", el, state: {}, loader: async () => ({ default: async () => ({ initialize, render }) }) });

    expect(initialize).toHaveBeenCalledTimes(1);
    expect(render).toHaveBeenCalledTimes(1);
  });

  it("adds the stylesheet once", async () => {
    const loader = async () => ({ default: { render: () => {} } });
    await mountWidget({ moduleUrl: "/m.js", cssUrl: "/widgets/y/styles.css", el: document.createElement("div"), state: {}, loader });
    await mountWidget({ moduleUrl: "/m.js", cssUrl: "/widgets/y/styles.css", el: document.createElement("div"), state: {}, loader });

    expect(document.head.querySelectorAll('link[href="/widgets/y/styles.css"]')).toHaveLength(1);
  });
});
