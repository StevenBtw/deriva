import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RunEvent, Trace } from "../api/types";

const handlers: { onEvent?: (e: RunEvent) => void; onEnd?: (name: string) => void } = {};

vi.mock("../api/events", () => ({
  followRun: vi.fn((_runId: string, onEvent: (e: RunEvent) => void, onEnd: (name: string) => void) => {
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
    graph: { view: vi.fn(), stats: vi.fn() },
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

vi.mock("../widgets/ArchimateWidget", () => ({
  ArchimateWidget: ({ elements, onSelect }: { elements: { id: string; name: string }[]; onSelect?: (e: Record<string, unknown> | null) => void }) => (
    <div data-testid="archimate">
      {elements.length} elements
      {elements.map((e) => (
        <button key={e.id} type="button" onClick={() => onSelect?.(e)}>
          select {e.name}
        </button>
      ))}
    </div>
  ),
}));

vi.mock("../benchmark/BenchmarkWorkspace", () => ({ BenchmarkWorkspace: () => <div data-testid="benchmark-workspace" /> }));

import { ApiError, graph, model, repositories, runs, session, trace } from "../api/client";
import { Workspace } from "./Workspace";

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
    vi.mocked(repositories.list).mockResolvedValue([{ name: "deriva" }, { name: "TeaStore" }]);
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
    vi.mocked(session.useRepository).mockImplementation(async (repository: string) => ({ repository }));
    vi.mocked(model.get).mockResolvedValue({ elements: [{ id: "n1", name: "Application Server", type: "Node", layer: "Technology", documentation: "" }], relationships: [] });
  });

  it("starts a run with the selection and streams its progress into the live log", async () => {
    render(<Workspace />);
    await screen.findByRole("option", { name: "TeaStore" });
    await userEvent.selectOptions(screen.getByLabelText("Repository"), "TeaStore");
    await userEvent.selectOptions(screen.getByLabelText("Scope"), "extraction");
    await userEvent.click(screen.getByLabelText(/without LLM/i));

    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));

    expect(runs.start).toHaveBeenCalledWith("extraction", "TeaStore", true);
    act(() => {
      handlers.onEvent?.(event(1, "started", { kind: "extraction", repository: "TeaStore" }));
      handlers.onEvent?.(event(2, "progress", { phase: "extraction", step: "Repository", status: "complete", message: "1 nodes, 0 edges" }));
    });
    const log = screen.getByRole("tabpanel");
    expect(await within(log).findByText(/Repository · 1 nodes, 0 edges/)).toBeInTheDocument();
    expect(within(log).getByText(/Run started · extraction · TeaStore/)).toBeInTheDocument();
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

  it("opens the model panel and loads the model", async () => {
    render(<Workspace />);

    await userEvent.click(screen.getByRole("button", { name: /View model/ }));

    expect(await screen.findByTestId("archimate")).toHaveTextContent("1 elements");
    expect(model.get).toHaveBeenCalled();
  });

  it("reloads both graphs when a step completes", async () => {
    render(<Workspace />);
    await screen.findByRole("option", { name: "deriva" });
    await waitFor(() => expect(session.useRepository).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: /^Run$/ }));
    await waitFor(() => expect(graph.view).toHaveBeenCalled());
    const before = vi.mocked(graph.view).mock.calls.length;

    act(() => handlers.onEvent?.(event(2, "progress", { step: "Directory", status: "complete" })));

    await waitFor(() => expect(vi.mocked(graph.view).mock.calls.length).toBe(before + 2));
  });

  it("switches the studio to the chosen repository and reloads the graphs", async () => {
    render(<Workspace />);
    await waitFor(() => expect(session.useRepository).toHaveBeenCalledWith("deriva"));
    const before = vi.mocked(graph.view).mock.calls.length;

    await userEvent.selectOptions(screen.getByLabelText("Repository"), "TeaStore");

    await waitFor(() => expect(session.useRepository).toHaveBeenCalledWith("TeaStore"));
    await waitFor(() => expect(vi.mocked(graph.view).mock.calls.length).toBeGreaterThan(before));
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

  it("shows the benchmark workspace in benchmark mode", () => {
    render(<Workspace mode="benchmark" />);

    expect(screen.getByTestId("benchmark-workspace")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Run$/ })).not.toBeInTheDocument();
  });
});
