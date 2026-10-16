import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { LinkedView, RunEvent, Trace } from "../api/types";

const handlers: { onEvent?: (e: RunEvent) => void; onEnd?: (name: string, lost?: boolean) => void } = {};
// What the mocked linked widget says it supports (its _features)
const widget: { features: string[] } = { features: [] };

vi.mock("../api/events", () => ({
  followRun: vi.fn((_runId: string, onEvent: (e: RunEvent) => void, onEnd: (name: string, lost?: boolean) => void) => {
    handlers.onEvent = onEvent;
    handlers.onEnd = onEnd;
    return () => {};
  }),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    repositories: { list: vi.fn() },
    runs: { start: vi.fn(), cancel: vi.fn(), history: vi.fn(), current: vi.fn(), calls: vi.fn(), call: vi.fn() },
    graph: { view: vi.fn(), linked: vi.fn(), stats: vi.fn() },
    model: { get: vi.fn(), exportXml: vi.fn() },
    session: { current: vi.fn(), useRepository: vi.fn() },
    trace: { element: vi.fn() },
  };
});

vi.mock("../widgets/GraphWidget", () => ({
  GraphWidget: ({ database, view }: { database: string; view: { nodes: unknown[] } }) => (
    <div data-testid={`graph-${database}`}>{view.nodes.length} nodes</div>
  ),
}));

vi.mock("../widgets/LinkedGraphWidget", () => ({
  LinkedGraphWidget: ({
    view,
    batch,
    pulse,
    onLaneAction,
    onFeatures,
  }: {
    view: LinkedView;
    batch: { seq: number; nodes: { id: string }[]; remove?: { nodes: string[]; edges: { source: string; target: string }[] } } | null;
    pulse: string[];
    onLaneAction?: (lane: string) => void;
    onFeatures?: (features: string[]) => void;
  }) => {
    onFeatures?.(widget.features);
    return (
      <div data-testid="linked">
        <span data-testid="linked-lanes">{view.lanes.map((lane) => lane.id).join(",")}</span>
        <button type="button" onClick={() => onLaneAction?.("model")}>
          model glyph
        </button>
        <span data-testid="linked-base">{view.nodes.map((n) => n.id).join(",")}</span>
        <span data-testid="linked-batch">{batch ? `${batch.seq}:${batch.nodes.map((n) => n.id).join(",")}` : ""}</span>
        <span data-testid="linked-remove">
          {batch?.remove ? `${batch.remove.nodes.join(",")}|${batch.remove.edges.map((e) => `${e.source}>${e.target}`).join(",")}` : ""}
        </span>
        <span data-testid="linked-pulse">{pulse.join(",")}</span>
      </div>
    );
  },
}));

vi.mock("../widgets/ArchimateWidget", () => ({
  ArchimateWidget: ({ elements, onSelect }: { elements: { id: string; name: string }[]; onSelect?: (e: Record<string, unknown> | null) => void }) => (
    <div data-testid="archimate">
      {elements.length} elements
      {elements.map((e) => (
        <button key={e.id} type="button" onClick={() => onSelect?.(e)}>
          select {e.name}
        </button>
      ))}
      <button type="button" onClick={() => onSelect?.(null)}>
        clear selection
      </button>
    </div>
  ),
}));

vi.mock("../benchmark/BenchmarkWorkspace", () => ({ BenchmarkWorkspace: () => <div data-testid="benchmark-workspace" /> }));

import { ApiError, graph, model, repositories, runs, session, trace } from "../api/client";
import { followRun } from "../api/events";
import { Workspace } from "./Workspace";

const LANES = [
  { id: "intermediate", title: "Intermediate graph" },
  { id: "output", title: "Output graph" },
];
const linkedView = (nodes: { id: string; deriva_id: string; lane: string; enabled?: boolean }[], missing = 0): LinkedView => ({ lanes: LANES, nodes, edges: [], missing_links: missing });
const event = (seq: number, name: RunEvent["event"], data: RunEvent["data"] = {}): RunEvent => ({ seq, event: name, data: { ts: 1791411141, ...data } });
const llm = (seq: number, callId: string, data: RunEvent["data"] = {}): RunEvent =>
  event(seq, "llm", { call_id: callId, seq: Number(callId.slice(1)), step: "DirectoryClassification", cache_hit: false, latency_ms: 812, tokens_in: 1840, tokens_out: 52, error: null, ...data });

async function startRun() {
  render(<Workspace />);
  await screen.findByRole("option", { name: "deriva" });
  await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));
}

describe("Workspace", () => {
  beforeEach(() => {
    vi.mocked(repositories.list).mockResolvedValue([{ name: "deriva" }, { name: "ToolShed" }]);
    vi.mocked(runs.history).mockResolvedValue([]);
    vi.mocked(runs.start).mockResolvedValue({ run_id: "r1" });
    vi.mocked(runs.cancel).mockResolvedValue({ run_id: "r1" });
    vi.mocked(runs.call).mockImplementation(async (_runId: string, callId: string) => ({
      call_id: callId,
      seq: Number(callId.slice(1)),
      step: "DirectoryClassification",
      schema: null,
      cache_hit: false,
      latency_ms: 812,
      tokens_in: 1840,
      tokens_out: 52,
      error: null,
      run_id: "r1",
      prompt: `Classify these directories (${callId})`,
      system_prompt: null,
      response: `{"answer": "${callId}"}`,
    }));
    vi.mocked(graph.view).mockResolvedValue({ nodes: [{ id: "1" }], edges: [] });
    vi.mocked(graph.linked).mockResolvedValue(linkedView([{ id: "10", deriva_id: "file_a", lane: "intermediate" }]));
    vi.mocked(session.useRepository).mockImplementation(async (repository: string) => ({ repository }));
    vi.mocked(session.current).mockResolvedValue({ repository: null });
    vi.mocked(runs.current).mockResolvedValue(null);
    vi.mocked(runs.calls).mockResolvedValue([]);
    widget.features = [];
    vi.mocked(model.get).mockResolvedValue({ elements: [{ id: "n1", name: "Application Server", type: "Node", layer: "Technology", documentation: "" }], relationships: [] });
  });

  it("lists the studio's recent runs with kind, repository and status", async () => {
    const at = new Date(2026, 9, 9, 10, 13).getTime() / 1000;
    vi.mocked(runs.history).mockResolvedValue([
      { run_id: "b2", kind: "derivation", repository: "deriva", status: "finished", events: 30, started_at: at, finished_at: at + 4 },
      { run_id: "a1", kind: "extraction", repository: "ToolShed", status: "cancelled", events: 3, started_at: at - 600, finished_at: at - 590 },
    ]);
    render(<Workspace />);

    expect(await screen.findByText("derivation · deriva")).toBeInTheDocument();
    expect(screen.getByText("extraction · ToolShed · cancelled")).toBeInTheDocument();
    expect(screen.getByText("2026-10-09 10:13")).toBeInTheDocument();
  });

  it("starts a run with the selection and streams its progress into the live log", async () => {
    render(<Workspace />);
    await screen.findByRole("option", { name: "ToolShed" });
    await userEvent.selectOptions(screen.getByLabelText("Repository"), "ToolShed");
    await userEvent.selectOptions(screen.getByLabelText("Scope"), "extraction");
    await userEvent.click(screen.getByLabelText(/without LLM/i));

    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));

    expect(runs.start).toHaveBeenCalledWith("extraction", "ToolShed", true);
    act(() => {
      handlers.onEvent?.(event(1, "started", { kind: "extraction", repository: "ToolShed" }));
      handlers.onEvent?.(event(2, "progress", { phase: "extraction", step: "Repository", status: "complete", message: "1 nodes, 0 edges" }));
    });
    const log = screen.getByRole("tabpanel");
    expect(await within(log).findByText(/Repository · 1 nodes, 0 edges/)).toBeInTheDocument();
    expect(within(log).getByText(/Run started · extraction · ToolShed/)).toBeInTheDocument();
  });

  it("says which metrics a call did not record instead of showing zeros", async () => {
    await startRun();

    act(() => handlers.onEvent?.(llm(2, "c9", { tokens_in: null, latency_ms: null, cache_hit: null })));

    const log = screen.getByRole("log");
    expect(log).toHaveTextContent("tokens not recorded");
    expect(log).toHaveTextContent("latency not recorded");
    expect(log).not.toHaveTextContent("cache miss");
  });

  it("locks the run settings while the start request is under way", async () => {
    let started: (value: { run_id: string }) => void = () => {};
    vi.mocked(runs.start).mockImplementation(() => new Promise((resolve) => (started = resolve)));
    render(<Workspace />);
    await screen.findByRole("option", { name: "deriva" });

    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));

    expect(screen.getByLabelText("Repository")).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Run$/ })).toBeDisabled();
    await act(async () => started({ run_id: "r1" }));
    expect(await screen.findByRole("button", { name: /Cancel/ })).toBeInTheDocument();
  });

  it("cancels the running run", async () => {
    render(<Workspace />);
    await screen.findByRole("option", { name: "deriva" });
    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));

    await userEvent.click(await screen.findByRole("button", { name: /Cancel/ }));

    expect(runs.cancel).toHaveBeenCalledWith("r1");
  });

  it("explains a run that is already in progress", async () => {
    vi.mocked(runs.start).mockRejectedValue(new ApiError(409, "Run abc is in progress", { run_id: "abc" }));
    render(<Workspace />);
    await screen.findByRole("option", { name: "deriva" });

    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));

    expect(await screen.findByText(/A run is in progress/)).toBeInTheDocument();
  });

  it("collects error events in the Errors tab", async () => {
    render(<Workspace />);
    await screen.findByRole("option", { name: "deriva" });
    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));
    act(() => {
      handlers.onEvent?.(event(1, "started"));
      handlers.onEvent?.(event(2, "error", { message: "LLM provider unavailable" }));
      handlers.onEnd?.("error");
    });

    await userEvent.click(screen.getByRole("tab", { name: /Errors/ }));

    expect(screen.getByRole("tabpanel")).toHaveTextContent("LLM provider unavailable");
  });

  it("lists a step that failed mid-run under Errors, and the live log is announced as a log", async () => {
    await startRun();
    act(() => {
      handlers.onEvent?.(event(1, "started"));
      handlers.onEvent?.(event(2, "progress", { phase: "extraction", step: "BusinessConcept", status: "error", message: "LLM call failed" }));
    });
    expect(screen.getByRole("log")).toHaveTextContent("BusinessConcept");

    await userEvent.click(screen.getByRole("tab", { name: /Errors \(1\)/ }));

    expect(screen.getByRole("tabpanel")).toHaveTextContent("BusinessConcept: LLM call failed");
  });

  it("moves between the bottom tabs with the arrow keys, the panel named by its tab", async () => {
    render(<Workspace />);
    const live = screen.getByRole("tab", { name: "Live" });
    expect(live).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Trace" })).toHaveAttribute("tabindex", "-1");

    live.focus();
    await userEvent.keyboard("{ArrowRight}");

    const trace = screen.getByRole("tab", { name: "Trace" });
    expect(trace).toHaveAttribute("aria-selected", "true");
    expect(trace).toHaveFocus();
    expect(screen.getByRole("tabpanel", { name: "Trace" })).toHaveAttribute("id", trace.getAttribute("aria-controls"));
    await userEvent.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(screen.getByRole("tab", { name: /Errors/ })).toHaveAttribute("aria-selected", "true");
  });

  it("opens the model panel and loads the model", async () => {
    render(<Workspace />);

    await userEvent.click(screen.getByRole("button", { name: /View model/ }));

    expect(await screen.findByTestId("archimate")).toHaveTextContent("1 elements");
    expect(model.get).toHaveBeenCalled();
  });

  it("switches the model between the architect and detail level and filters it by viewpoint", async () => {
    const node = { id: "n1", name: "Application Server", type: "Node", layer: "Technology", documentation: "" };
    const core = { id: "ac1", name: "Core", type: "ApplicationComponent", layer: "Application", documentation: "" };
    const artifact = { id: "art1", name: "core", type: "Artifact", layer: "Technology", documentation: "" };
    vi.mocked(model.get).mockImplementation(async (level = "architect") =>
      level === "detail"
        ? {
            elements: [node, core, artifact],
            relationships: [],
            views: [
              { name: "Layered", viewpoint: "Layered", level: "architect", elements: ["n1", "ac1"] },
              { name: "Implementation and Deployment (detail)", viewpoint: "Implementation and Deployment", level: "detail", elements: ["n1", "art1"] },
            ],
          }
        : { elements: [node, core], relationships: [], views: [{ name: "Layered", viewpoint: "Layered", level: "architect", elements: ["n1", "ac1"] }] },
    );
    render(<Workspace />);
    await userEvent.click(screen.getByRole("button", { name: /View model/ }));
    expect(await screen.findByTestId("archimate")).toHaveTextContent("2 elements");

    await userEvent.click(screen.getByRole("radio", { name: "Detail" }));
    await waitFor(() => expect(model.get).toHaveBeenLastCalledWith("detail"));
    expect(await screen.findByTestId("archimate")).toHaveTextContent("3 elements");

    await userEvent.selectOptions(screen.getByLabelText("Viewpoint"), "Implementation and Deployment (detail)");
    expect(screen.getByTestId("archimate")).toHaveTextContent("2 elements");
    expect(screen.getByRole("button", { name: "select core" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "select Core" })).not.toBeInTheDocument();

    // Back to the architect level: a detail view is no longer offered, the whole model shows again
    await userEvent.click(screen.getByRole("radio", { name: "Architect" }));
    await waitFor(() => expect(screen.getByTestId("archimate")).toHaveTextContent("2 elements"));
    expect(screen.getByLabelText("Viewpoint")).toHaveValue("");
  });

  it("reloads both graphs when a step completes", async () => {
    render(<Workspace />);
    await screen.findByRole("option", { name: "deriva" });
    await waitFor(() => expect(session.useRepository).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));
    await waitFor(() => expect(graph.linked).toHaveBeenCalled());
    const before = vi.mocked(graph.linked).mock.calls.length;

    act(() => handlers.onEvent?.(event(2, "progress", { step: "Directory", status: "complete" })));

    await waitFor(() => expect(vi.mocked(graph.linked).mock.calls.length).toBe(before + 1));
  });

  it("shows the linked view by default, says how many links are not shown, and can switch to separate graphs", async () => {
    vi.mocked(graph.linked).mockResolvedValue(linkedView([], 3));
    render(<Workspace />);

    expect(await screen.findByRole("button", { name: "Linked", pressed: true })).toBeInTheDocument();
    expect(await screen.findByText(/3 links not shown/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Separate" }));
    expect(screen.getByText("Intermediate graph")).toBeInTheDocument();
    expect(screen.getByText("Output graph (model)")).toBeInTheDocument();
  });

  it("appends what a completed step added instead of redrawing the linked view", async () => {
    widget.features = ["lanes", "append"];
    render(<Workspace />);
    await screen.findByRole("option", { name: "deriva" });
    await waitFor(() => expect(session.useRepository).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));
    expect(await screen.findByTestId("linked-base")).toHaveTextContent("10");
    vi.mocked(graph.linked).mockResolvedValue(
      linkedView([
        { id: "10", deriva_id: "file_a", lane: "intermediate" },
        { id: "20", deriva_id: "el_a", lane: "output" },
      ]),
    );

    act(() => handlers.onEvent?.(event(2, "progress", { step: "ApplicationComponent", status: "complete" })));

    await waitFor(() => expect(screen.getByTestId("linked-batch")).toHaveTextContent("1:20"));
    expect(screen.getByTestId("linked-base")).toHaveTextContent(/^10$/);
  });

  it("fades out what left and greys a rejected element in place when the widget can remove", async () => {
    widget.features = ["lanes", "append", "remove"];
    const element = { id: "20", deriva_id: "el_a", lane: "output" };
    vi.mocked(graph.linked).mockResolvedValue({
      ...linkedView([{ id: "10", deriva_id: "file_a", lane: "intermediate" }, { ...element, enabled: true }]),
      edges: [{ source: "20", target: "model", label: "IN_MODEL", cross: true }],
    });
    render(<Workspace />);
    await screen.findByRole("option", { name: "deriva" });
    await waitFor(() => expect(session.useRepository).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));
    expect(await screen.findByTestId("linked-base")).toHaveTextContent(/^10,20$/);
    vi.mocked(graph.linked).mockResolvedValue(linkedView([{ id: "10", deriva_id: "file_a", lane: "intermediate" }, { ...element, enabled: false }]));

    act(() => handlers.onEvent?.(event(2, "progress", { step: "Refine", status: "complete" })));

    await waitFor(() => expect(screen.getByTestId("linked-batch")).toHaveTextContent("1:20"));
    expect(screen.getByTestId("linked-remove")).toHaveTextContent(/^\|20>model$/);
    expect(screen.getByTestId("linked-base")).toHaveTextContent(/^10,20$/);
  });

  it("redraws the linked view when nodes leave and the widget cannot remove", async () => {
    vi.mocked(graph.linked).mockResolvedValue(linkedView([{ id: "10", deriva_id: "file_a", lane: "intermediate" }, { id: "11", deriva_id: "file_b", lane: "intermediate" }]));
    render(<Workspace />);
    await screen.findByRole("option", { name: "deriva" });
    await waitFor(() => expect(session.useRepository).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));
    expect(await screen.findByTestId("linked-base")).toHaveTextContent(/^10,11$/);
    vi.mocked(graph.linked).mockResolvedValue(linkedView([{ id: "11", deriva_id: "file_b", lane: "intermediate" }]));

    act(() => handlers.onEvent?.(event(2, "progress", { step: "Method", status: "complete" })));

    await waitFor(() => expect(screen.getByTestId("linked-base")).toHaveTextContent(/^11$/));
    expect(screen.getByTestId("linked-batch")).toBeEmptyDOMElement();
  });

  it("counts a sampled graph against its totals in the separate view", async () => {
    vi.mocked(graph.view).mockResolvedValue({ nodes: [{ id: "1" }], edges: [], totals: { nodes: { File: 40 }, edges: { CONTAINS: 39 } } });
    render(<Workspace />);
    await userEvent.click(await screen.findByRole("button", { name: "Separate" }));

    expect((await screen.findAllByText("1 of 40 nodes · 0 of 39 edges")).length).toBe(2);
  });

  it("pulses the running derivation step's candidates in the linked view", async () => {
    render(<Workspace />);
    await screen.findByRole("option", { name: "deriva" });
    await waitFor(() => expect(session.useRepository).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));
    await screen.findByTestId("linked");

    act(() => handlers.onEvent?.(event(2, "progress", { phase: "derivation", step: "ApplicationComponent", status: "processing", candidates: ["file_a", "file_z"] })));
    await waitFor(() => expect(screen.getByTestId("linked-pulse")).toHaveTextContent(/^10$/));

    act(() => handlers.onEvent?.(event(3, "progress", { phase: "derivation", step: "ApplicationComponent", status: "complete" })));
    await waitFor(() => expect(screen.getByTestId("linked-pulse")).toBeEmptyDOMElement());
  });

  it("keeps the drawn graphs when a refresh during the run fails, and refreshes once more when the run ends", async () => {
    render(<Workspace />);
    await screen.findByRole("option", { name: "deriva" });
    await waitFor(() => expect(session.useRepository).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));
    expect(await screen.findByTestId("linked-base")).toHaveTextContent("10");
    const before = vi.mocked(graph.linked).mock.calls.length;
    vi.mocked(graph.linked).mockRejectedValueOnce(new Error("A pipeline step is running; try again when it finishes"));

    act(() => handlers.onEvent?.(event(2, "progress", { step: "ApplicationComponent", status: "complete" })));
    await waitFor(() => expect(vi.mocked(graph.linked).mock.calls.length).toBe(before + 1));
    await act(async () => {});
    expect(screen.getByTestId("linked-base")).toHaveTextContent("10");

    act(() => handlers.onEnd?.("finished"));
    await waitFor(() => expect(vi.mocked(graph.linked).mock.calls.length).toBe(before + 2));
  });

  it("titles the linked view from repository to model and counts each lane", async () => {
    vi.mocked(graph.linked).mockResolvedValue(
      linkedView([
        { id: "9", deriva_id: "repo::r", lane: "repository" },
        { id: "10", deriva_id: "file_a", lane: "intermediate" },
        { id: "11", deriva_id: "file_b", lane: "intermediate" },
        { id: "20", deriva_id: "el_a", lane: "output" },
      ]),
    );
    render(<Workspace />);

    expect(await screen.findByText("Repository to model")).toBeInTheDocument();
    expect(screen.getByText("1 repository · 2 graph nodes · 1 element")).toBeInTheDocument();
  });

  it("ends the linked view with the model, whose glyph opens the model panel", async () => {
    vi.mocked(graph.linked).mockResolvedValue({ ...linkedView([]), lanes: [{ id: "repository", title: "Repository" }, ...LANES] });
    render(<Workspace />);

    expect(await screen.findByTestId("linked-lanes")).toHaveTextContent("repository,intermediate,output,model");
    await userEvent.click(screen.getByRole("button", { name: "model glyph" }));

    expect(await screen.findByRole("button", { name: "‹ Graphs" })).toBeInTheDocument();
    expect(model.get).toHaveBeenCalled();
  });

  it("starts on a cloned repository when the session reads the shared default graph", async () => {
    // A fresh studio session reads the "default" database, which is no repository: switching to it would fail
    vi.mocked(session.current).mockResolvedValue({ repository: "default" });
    render(<Workspace />);

    await waitFor(() => expect(session.useRepository).toHaveBeenCalledWith("deriva"));
    expect(session.useRepository).not.toHaveBeenCalledWith("default");
    expect(screen.getByLabelText("Repository")).toHaveValue("deriva");
  });

  it("switches the studio to the chosen repository and reloads the graphs", async () => {
    render(<Workspace />);
    await waitFor(() => expect(session.useRepository).toHaveBeenCalledWith("deriva"));
    const before = vi.mocked(graph.linked).mock.calls.length;

    await userEvent.selectOptions(screen.getByLabelText("Repository"), "ToolShed");

    await waitFor(() => expect(session.useRepository).toHaveBeenCalledWith("ToolShed"));
    // One linked request carries both graphs
    await waitFor(() => expect(vi.mocked(graph.linked).mock.calls.length).toBe(before + 1));
  });

  it("keeps the graph that loaded when the other one fails in the separate view", async () => {
    vi.mocked(graph.view).mockImplementation(async (database: string) => {
      if (database === "model") throw new Error("model query failed");
      return { nodes: [{ id: "a" }, { id: "b" }], edges: [] };
    });
    render(<Workspace />);
    await userEvent.click(await screen.findByRole("button", { name: "Separate" }));

    expect(await screen.findByTestId("graph-graph")).toHaveTextContent("2 nodes");
    expect(await screen.findByText("model query failed")).toBeInTheDocument();
  });

  it("clears the trace when the model selection is cleared", async () => {
    vi.mocked(trace.element).mockReturnValue(new Promise(() => {}));
    await startRun();
    await userEvent.click(screen.getByRole("button", { name: /View model/ }));
    await userEvent.click(await screen.findByRole("button", { name: /select Application Server/ }));
    expect(screen.getByRole("tab", { name: "Trace" })).toHaveAttribute("aria-selected", "true");

    await userEvent.click(screen.getByRole("button", { name: "clear selection" }));

    expect(within(screen.getByRole("tabpanel")).getByText(/Click an element in the model/)).toBeInTheDocument();
  });

  it("drops a selected element the refreshed model no longer has", async () => {
    vi.mocked(trace.element).mockReturnValue(new Promise(() => {}));
    await startRun();
    await userEvent.click(screen.getByRole("button", { name: /View model/ }));
    await userEvent.click(await screen.findByRole("button", { name: /select Application Server/ }));
    expect(screen.getByRole("heading", { name: "Application Server" })).toBeInTheDocument();

    vi.mocked(model.get).mockResolvedValue({ elements: [], relationships: [] });
    act(() => handlers.onEvent?.(event(3, "progress", { step: "Refine", status: "complete" })));

    await waitFor(() => expect(screen.queryByRole("heading", { name: "Application Server" })).not.toBeInTheDocument());
  });

  it("shows LLM calls in the live log and opens prompt and answer on demand", async () => {
    await startRun();
    act(() => {
      handlers.onEvent?.(llm(1, "c1"));
      handlers.onEvent?.(llm(2, "c2", { cache_hit: true, latency_ms: 0.4 }));
    });
    const log = screen.getByRole("tabpanel");
    expect(within(log).getByText(/LLM #1 · DirectoryClassification · 1,840 tokens in · 812 ms · cache miss/)).toBeInTheDocument();
    expect(within(log).getByText(/LLM #2 · .* · cache hit/)).toBeInTheDocument();
    expect(runs.call).not.toHaveBeenCalled();

    // The temperature the call ran with, where the log records it
    act(() => handlers.onEvent?.(llm(3, "c3", { temperature: 0 })));
    expect(within(log).getByText(/LLM #3 · .* · cache miss · temperature 0/)).toBeInTheDocument();

    await userEvent.click(within(log).getAllByRole("button", { name: /prompt/ })[0]);

    expect(await within(log).findByText("Classify these directories (c1)")).toBeInTheDocument();
    expect(runs.call).toHaveBeenCalledWith("r1", "c1");
    await userEvent.click(within(log).getAllByRole("button", { name: /answer/ })[0]);
    expect(await within(log).findByText('{"answer": "c1"}')).toBeInTheDocument();
    expect(within(log).queryByText("Classify these directories (c1)")).not.toBeInTheDocument();
  });

  it("marks a failed LLM call in the live log", async () => {
    await startRun();
    act(() => handlers.onEvent?.(llm(1, "c1", { error: "rate limited" })));

    expect(within(screen.getByRole("tabpanel")).getByText(/LLM #1 .* rate limited/)).toHaveClass("error");
  });

  it("lists the run's LLM calls in the Prompts tab", async () => {
    await startRun();
    await userEvent.click(screen.getByRole("tab", { name: /Prompts/ }));
    expect(screen.getByRole("tabpanel")).toHaveTextContent(/No LLM calls/);
    act(() => {
      handlers.onEvent?.(event(1, "started"));
      handlers.onEvent?.(llm(2, "c1"));
      handlers.onEvent?.(llm(3, "c2", { step: "BusinessConcept" }));
    });

    const panel = screen.getByRole("tabpanel");
    expect(screen.getByRole("tab", { name: "Prompts (2)" })).toBeInTheDocument();
    expect(within(panel).getByText(/#2/).closest(".logline")).toHaveTextContent("BusinessConcept");
    await userEvent.click(within(panel).getAllByRole("button", { name: /open/ })[1]);

    expect(await within(panel).findByText(/PROMPT\s+Classify these directories \(c2\)\s+ANSWER\s+\{"answer": "c2"\}/)).toBeInTheDocument();
  });

  it("shows the trace of a clicked model element in the bottom panel", async () => {
    const found: Trace = {
      element: { identifier: "n1", name: "Queue Server", element_type: "Node", properties: { source: "tech::r::queue" } },
      sources: [{ id: "tech::r::queue", type: "Technology", name: "Queue", properties: { id: "tech::r::queue", techCategory: "infrastructure" } }],
      relationships: [{ identifier: "r1", direction: "out", type: "Realization", other: { identifier: "s1", name: "Messaging Service", type: "TechnologyService" }, derived_from: "metamodel" }],
      calls: [
        { call_id: "c2", seq: 2, step: "Node", schema: "role_classification", cache_hit: false, latency_ms: 812, tokens_in: 1840, tokens_out: 52, error: null, role: "decision", matched: "tech::r::queue" },
      ],
    };
    vi.mocked(trace.element).mockResolvedValue(found);
    await startRun();
    await userEvent.click(screen.getByRole("button", { name: /View model/ }));

    await userEvent.click(await screen.findByRole("button", { name: /select Application Server/ }));

    expect(trace.element).toHaveBeenCalledWith("n1", "r1");
    expect(screen.getByRole("tab", { name: "Trace" })).toHaveAttribute("aria-selected", "true");
    const panel = screen.getByRole("tabpanel");
    expect(await within(panel).findByText(/Technology · Queue · tech::r::queue/)).toBeInTheDocument();
    expect(within(panel).getByText(/techCategory: infrastructure/)).toBeInTheDocument();
    expect(within(panel).getByText(/→ Realization · Messaging Service \(TechnologyService\) · metamodel/)).toBeInTheDocument();
    expect(within(panel).getByText(/decision · Node · 1,840 tokens in/)).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: /prompt/ }));
    expect(await within(panel).findByText("Classify these directories (c2)")).toBeInTheDocument();
  });

  it("traces without calls when no run was started here", async () => {
    vi.mocked(trace.element).mockResolvedValue({ element: { identifier: "n1", name: "Queue Server", element_type: "Node", properties: {} }, sources: [], relationships: [], calls: [] });
    render(<Workspace />);
    await userEvent.click(screen.getByRole("button", { name: /View model/ }));

    await userEvent.click(await screen.findByRole("button", { name: /select Application Server/ }));

    expect(trace.element).toHaveBeenCalledWith("n1", null);
    expect(await within(screen.getByRole("tabpanel")).findByText(/Start a run here to link the LLM calls/)).toBeInTheDocument();
  });

  it("follows a run that is already going when the page opens, with its repository in the picker", async () => {
    vi.mocked(runs.current).mockResolvedValue({ run_id: "r9", kind: "all", repository: "ToolShed", status: "running", events: 4, started_at: 1791411141, finished_at: null });
    vi.mocked(repositories.list).mockRejectedValue(new ApiError(503, "The databases are busy", {}));
    vi.mocked(session.useRepository).mockClear();
    render(<Workspace />);

    await waitFor(() => expect(followRun).toHaveBeenLastCalledWith("r9", expect.any(Function), expect.any(Function)));
    expect(await screen.findByRole("option", { name: "ToolShed" })).toBeInTheDocument();
    expect(screen.getByLabelText("Repository")).toHaveValue("ToolShed");
    act(() => handlers.onEvent?.(llm(5, "c1")));
    expect(await screen.findByRole("tab", { name: "Prompts (1)" })).toBeInTheDocument();
    expect(session.useRepository).not.toHaveBeenCalled();
  });

  it("shows the last run after a reload: its prompts from the saved calls, and why its live log is gone", async () => {
    vi.mocked(runs.history).mockResolvedValue([{ run_id: "r8", kind: "all", repository: "deriva", status: "finished", events: 30, started_at: 1791411141, finished_at: 1791411200 }]);
    vi.mocked(runs.calls).mockResolvedValue([llm(1, "c3").data as never]);
    render(<Workspace />);

    expect(await screen.findByText(/live log is not kept/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Prompts/ }));
    expect(await within(screen.getByRole("tabpanel")).findByText(/DirectoryClassification/)).toBeInTheDocument();
    expect(runs.calls).toHaveBeenCalledWith("r8");
  });

  it("keeps the status of an ended run whose stream the restarted studio no longer has", async () => {
    vi.mocked(runs.history).mockResolvedValue([{ run_id: "r8", kind: "all", repository: "deriva", status: "finished", events: 30, started_at: 1791411141, finished_at: 1791411200 }]);
    vi.mocked(runs.calls).mockResolvedValue([]);
    render(<Workspace />);
    expect(await screen.findByText(/run finished · r8/)).toBeInTheDocument();

    act(() => handlers.onEnd?.("error", true));

    expect(screen.getByText(/run finished · r8/)).toBeInTheDocument();
  });

  it("ends a running run whose stream is lost", async () => {
    await startRun();

    act(() => handlers.onEnd?.("error", true));

    expect(await screen.findByText(/run ended with an error/)).toBeInTheDocument();
  });

  it("opens a run from the recent runs", async () => {
    vi.mocked(runs.history).mockResolvedValue([
      { run_id: "r8", kind: "all", repository: "deriva", status: "finished", events: 30, started_at: 1791411141, finished_at: 1791411200 },
      { run_id: "r7", kind: "extraction", repository: "ToolShed", status: "finished", events: 9, started_at: 1791400000, finished_at: 1791400060 },
    ]);
    render(<Workspace />);

    await userEvent.click(await screen.findByRole("button", { name: /extraction · ToolShed/ }));

    await waitFor(() => expect(followRun).toHaveBeenLastCalledWith("r7", expect.any(Function), expect.any(Function)));
    expect(screen.getByRole("button", { name: /extraction · ToolShed/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("starts with the session's repository in the picker", async () => {
    vi.mocked(session.current).mockResolvedValue({ repository: "ToolShed" });
    vi.mocked(session.useRepository).mockClear();
    render(<Workspace />);

    await screen.findByRole("option", { name: "deriva" });
    await waitFor(() => expect(screen.getByLabelText("Repository")).toHaveValue("ToolShed"));
    expect(session.useRepository).not.toHaveBeenCalledWith("deriva");
  });

  it("shows the benchmark workspace in benchmark mode", () => {
    render(<Workspace mode="benchmark" />);

    expect(screen.getByTestId("benchmark-workspace")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Run$/ })).not.toBeInTheDocument();
  });
});
