import { describe, expect, it } from "vitest";

import type { InspectorElement, InspectorView } from "../api/types";
import { diagramOf, itemsOf, keep, statusPair, statusRun, statusUnion } from "./inspect";

const RUNS = ["s/1", "s/2", "s/3"];

function el(run: string, name: string, type: string, source: string): InspectorElement {
  const layer = type === "Node" ? "Technology" : "Application";
  return { run, identifier: `${run}:${source}`, name, type, layer, source, by_source: `${type}|${source}`, by_name: `${type}|${name.toLowerCase()}` };
}

const VIEW: InspectorView = {
  repository: "r",
  runs: RUNS,
  elements: [
    el("s/1", "Queue Server", "Node", "tech::r::queue"),
    el("s/3", "Queue Server", "Node", "tech::r::queue"),
    el("s/2", "Queue Server", "Node", "tech::r::bus"),
    el("s/1", "Worker", "ApplicationComponent", "dir::r::worker"),
    el("s/2", "Worker", "ApplicationComponent", "dir::r::worker"),
    el("s/3", "Workers", "ApplicationComponent", "dir::r::worker"),
  ],
  relationships: [
    ...["s/1", "s/3"].map((run) => ({
      run,
      type: "Serving",
      source_by_source: "Node|tech::r::queue",
      target_by_source: "ApplicationComponent|dir::r::worker",
      source_by_name: "Node|queue server",
      target_by_name: "ApplicationComponent|worker",
      derived_from: "metamodel",
    })),
  ],
  causes: { "Node|tech::r::queue": "Node: candidate llm_rejected in s/2" },
};

const byKey = (identity: "source" | "name") => Object.fromEntries(itemsOf(VIEW, identity).map((item) => [item.key, item]));

describe("inspector items", () => {
  it("groups occurrences by source or by name, with the flip cause", () => {
    expect(Object.keys(byKey("source")).sort()).toEqual(["ApplicationComponent|dir::r::worker", "Node|tech::r::bus", "Node|tech::r::queue"]);
    expect(Object.keys(byKey("name")).sort()).toEqual(["ApplicationComponent|worker", "ApplicationComponent|workers", "Node|queue server"]);
    expect(byKey("source")["Node|tech::r::queue"].cause).toBe("Node: candidate llm_rejected in s/2");
    expect(byKey("name")["Node|queue server"].cause).toBe("Node: candidate llm_rejected in s/2");
  });
});

describe("statuses", () => {
  it("over all runs: partial, changed (name or source) and stable", () => {
    const source = byKey("source");
    const name = byKey("name");

    expect(statusUnion(source["Node|tech::r::queue"], RUNS, "source")).toEqual({ cls: "d-partial", text: "in s/1, s/3 (2/3)", diff: true });
    expect(statusUnion(source["ApplicationComponent|dir::r::worker"], RUNS, "source")).toEqual({
      cls: "d-changed",
      text: "name: Worker (s/1) · Worker (s/2) · Workers (s/3)",
      diff: true,
    });
    expect(statusUnion(name["Node|queue server"], RUNS, "name").text).toBe("source: tech::r::queue (s/1) · tech::r::bus (s/2) · tech::r::queue (s/3)");
    expect(statusUnion(name["ApplicationComponent|worker"], ["s/1", "s/2"], "name")).toEqual({ cls: "", text: "2/2", diff: false });
  });

  it("for one run: ghost, missing elsewhere, changed and the same", () => {
    const source = byKey("source");
    const queue = source["Node|tech::r::queue"];

    expect(statusRun(queue, "s/2", RUNS, "source")).toEqual({ cls: "d-ghost", text: "not in s/2 (in s/1, s/3)", diff: true });
    expect(statusRun(queue, "s/1", RUNS, "source")).toEqual({ cls: "d-partial", text: "missing in s/2", diff: true });
    expect(statusRun(source["ApplicationComponent|dir::r::worker"], "s/3", RUNS, "source").text).toBe("name Workers here, Worker in s/1, Worker in s/2");
    expect(statusRun(source["ApplicationComponent|dir::r::worker"], "s/1", ["s/1", "s/2"], "source")).toEqual({ cls: "", text: "same in every run", diff: false });
  });

  it("side by side: only in A, only in B, changed, absent on both", () => {
    const source = byKey("source");
    const queue = source["Node|tech::r::queue"];

    expect(statusPair(queue, "a", "s/1", "s/2", "source")).toEqual({ cls: "d-only-a", text: "only in s/1", diff: true });
    expect(statusPair(queue, "b", "s/1", "s/2", "source")).toEqual({ cls: "d-ghost", text: "only in s/1", diff: true });
    expect(statusPair(source["Node|tech::r::bus"], "b", "s/1", "s/2", "source")?.cls).toBe("d-only-b");
    expect(statusPair(source["ApplicationComponent|dir::r::worker"], "a", "s/2", "s/3", "source")).toEqual({ cls: "d-changed", text: "name Worker (s/3: Workers)", diff: true });
    expect(statusPair(source["Node|tech::r::bus"], "a", "s/1", "s/3", "source")).toBeNull();
  });

  it("filters keep everything, only differences or only stable items", () => {
    const stable = { cls: "", text: "", diff: false };
    const differs = { cls: "d-partial", text: "", diff: true };

    expect([keep(stable, "all"), keep(differs, "all"), keep(null, "all")]).toEqual([true, true, false]);
    expect([keep(stable, "diff"), keep(differs, "diff")]).toEqual([false, true]);
    expect([keep(stable, "stable"), keep(differs, "stable")]).toEqual([true, false]);
  });
});

describe("diagram for the ArchiMate widget", () => {
  it("gives every element its comparison status, a short badge and the cause as documentation", () => {
    const { elements, relationships } = diagramOf(VIEW, "source", { kind: "union" }, "all");
    const byId = Object.fromEntries(elements.map((e) => [e.id, e]));

    expect(byId["Node|tech::r::queue"]).toMatchObject({ name: "Queue Server", type: "Node", layer: "Technology", status: "partial", badge: "2/3" });
    expect(byId["Node|tech::r::queue"].documentation).toContain("llm_rejected");
    expect(byId["ApplicationComponent|dir::r::worker"]).toMatchObject({ status: "changed", badge: "name differs" });
    expect(relationships).toEqual([
      { id: "Serving|Node|tech::r::queue|ApplicationComponent|dir::r::worker", type: "Serving", source: "Node|tech::r::queue", target: "ApplicationComponent|dir::r::worker", name: "", status: "partial" },
    ]);
  });

  it("shows one run with ghosts for what only other runs have, and honours the filter", () => {
    const { elements, relationships } = diagramOf(VIEW, "source", { kind: "run", run: "s/2" }, "all");
    const byId = Object.fromEntries(elements.map((e) => [e.id, e]));

    expect(byId["Node|tech::r::queue"]).toMatchObject({ status: "ghost", badge: "not in this run" });
    expect(byId["Node|tech::r::bus"]).toMatchObject({ status: "partial", badge: "missing in 2 runs" });
    expect(relationships).toEqual([]);
    expect(diagramOf(VIEW, "source", { kind: "union" }, "stable").elements).toEqual([]);
  });
});
