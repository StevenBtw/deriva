import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BenchmarkGroup, InspectorView, RunEvent } from "../api/types";

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
    graph: { view: vi.fn() },
    runs: { cancel: vi.fn(), call: vi.fn() },
    benchmarks: {
      list: vi.fn(),
      models: vi.fn(),
      start: vi.fn(),
      results: vi.fn(),
      steps: vi.fn(),
      flips: vi.fn(),
      inspector: vi.fn(),
      exportUrl: actual.benchmarks.exportUrl,
    },
  };
});

vi.mock("../widgets/GraphWidget", () => ({ GraphWidget: () => <div data-testid="graph" /> }));

vi.mock("../widgets/ArchimateWidget", () => ({
  ArchimateWidget: ({ elements }: { elements: { id: string; name: string; status?: string; badge?: string }[] }) => (
    <ul data-testid="archimate">
      {elements.map((e) => (
        <li key={e.id}>{`${e.name}: ${e.status} ${e.badge}`}</li>
      ))}
    </ul>
  ),
}));

import { benchmarks, graph, repositories } from "../api/client";
import { BenchmarkWorkspace } from "./BenchmarkWorkspace";

const GROUP: BenchmarkGroup = {
  repository: "repo_a",
  model: "m",
  runs: ["bench_2/1", "bench_2/2"],
  counts: [
    { label: "bench_2/1", elements: 2, relationships: 1 },
    { label: "bench_2/2", elements: 1, relationships: 0 },
  ],
  rows: [
    { key: "graph_concepts", common: 0, union: 0, score: 1 },
    { key: "graph_concept_types", common: 0, union: 0, score: 1 },
    { key: "graph_technologies", common: 1, union: 1, score: 1 },
    { key: "el_name", common: 1, union: 2, score: 0.5 },
    { key: "el_source", common: 1, union: 2, score: 0.5 },
    { key: "rel_name", common: 0, union: 1, score: 0 },
    { key: "rel_source", common: 0, union: 1, score: 0 },
  ],
};

const VIEW: InspectorView = {
  repository: "repo_a",
  runs: ["bench_2/1", "bench_2/2"],
  elements: [
    { run: "bench_2/1", identifier: "n1", name: "Queue Server", type: "Node", layer: "Technology", source: "tech::r::queue", by_source: "Node|tech::r::queue", by_name: "Node|queue server" },
    { run: "bench_2/1", identifier: "a1", name: "Worker", type: "ApplicationComponent", layer: "Application", source: "dir::r::w", by_source: "ApplicationComponent|dir::r::w", by_name: "ApplicationComponent|worker" },
    { run: "bench_2/2", identifier: "a1", name: "Worker", type: "ApplicationComponent", layer: "Application", source: "dir::r::w", by_source: "ApplicationComponent|dir::r::w", by_name: "ApplicationComponent|worker" },
  ],
  relationships: [],
  causes: { "Node|tech::r::queue": "Node: candidate llm_rejected in bench_2/2 (same prompt, different answer)" },
};

describe("BenchmarkWorkspace", () => {
  beforeEach(() => {
    vi.mocked(repositories.list).mockResolvedValue([{ name: "repo_a" }, { name: "repo_b" }]);
    vi.mocked(graph.view).mockResolvedValue({ nodes: [], edges: [] });
    vi.mocked(benchmarks.list).mockResolvedValue([
      { session_id: "bench_2", description: "", status: "completed", started_at: "2026-10-08T01:00:00", completed_at: null },
      { session_id: "bench_1", description: "", status: "completed", started_at: "2026-10-07T01:00:00", completed_at: null },
    ]);
    vi.mocked(benchmarks.models).mockResolvedValue([{ name: "m", provider: "azure", model: "gpt" }]);
    vi.mocked(benchmarks.results).mockResolvedValue([GROUP]);
    vi.mocked(benchmarks.steps).mockResolvedValue({ repo_a: [{ step: "Node", prompts: 4, identical: 3, score: 0.75 }] });
    vi.mocked(benchmarks.flips).mockResolvedValue([
      { type: "Node", source: "tech::r::queue", names: { "bench_2/1": "Queue Server" }, present: ["bench_2/1"], missing: { "bench_2/2": "candidate llm_rejected" }, also_from: {}, llm: "same prompt, different answer", cause: "Node: candidate llm_rejected in bench_2/2 (same prompt, different answer)" },
    ]);
    vi.mocked(benchmarks.inspector).mockResolvedValue(VIEW);
    vi.mocked(benchmarks.start).mockResolvedValue({ run_id: "b1" });
  });

  it("selects the newest session and shows its consistency per repository", async () => {
    render(<BenchmarkWorkspace />);

    const panel = screen.getByRole("tabpanel");
    expect(await within(panel).findByText("repo_a")).toBeInTheDocument();
    expect(benchmarks.results).toHaveBeenCalledWith(["bench_2"]);
    const row = within(panel).getByText("repo_a").closest("tr")!;
    expect(row).toHaveTextContent("50.0 / 50.0");
    expect(row).toHaveTextContent("0.0 / 0.0");
    expect(row).toHaveTextContent("2 runs");
  });

  it("combines the sessions picked in the list", async () => {
    render(<BenchmarkWorkspace />);
    await screen.findByRole("button", { name: /bench_1/ });

    await userEvent.click(screen.getByRole("button", { name: /bench_1/ }));

    await waitFor(() => expect(benchmarks.results).toHaveBeenLastCalledWith(["bench_2", "bench_1"]));
    expect(screen.queryByRole("link", { name: /Export logs/ })).not.toBeInTheDocument();
  });

  it("offers the selected session's log bundle", async () => {
    render(<BenchmarkWorkspace />);

    const link = await screen.findByRole("link", { name: /Export logs/ });

    expect(link).toHaveAttribute("href", "/api/benchmarks/bench_2/export");
  });

  it("starts a benchmark with samples locked at one and follows its progress", async () => {
    render(<BenchmarkWorkspace />);
    await screen.findByRole("option", { name: "m" });
    await userEvent.click(await screen.findByRole("button", { name: "repo_b" }));
    expect(screen.getByLabelText(/Samples per LLM call/)).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: /Start benchmark/ }));

    expect(benchmarks.start).toHaveBeenCalledWith({
      repositories: ["repo_b"],
      model: "m",
      runs: 3,
      stages: null,
      use_cache: false,
      per_repo: true,
      separate_sessions: true,
      no_cache_extraction: true,
    });
    act(() => handlers.onEvent?.({ seq: 1, event: "progress", data: { phase: "benchmark", step: "run 1 · repo_b · m · 1", status: "running", ts: 1791411141 } }));
    expect(screen.getByRole("tab", { name: "Live", selected: true })).toBeInTheDocument();
    expect(screen.getByRole("tabpanel")).toHaveTextContent("run 1 · repo_b · m · 1");
  });

  it("shows answer stability per step and the flips with their cause", async () => {
    render(<BenchmarkWorkspace />);
    await screen.findByText("repo_a");

    await userEvent.click(screen.getByRole("tab", { name: "Steps" }));
    const cell = await within(screen.getByRole("tabpanel")).findByText("75.0");
    expect(cell).toHaveAttribute("title", "3 of 4 prompts answered identically");

    await userEvent.click(screen.getByRole("tab", { name: /Flips/ }));
    expect(await within(screen.getByRole("tabpanel")).findByText(/candidate llm_rejected in bench_2\/2 \(same prompt, different answer\)/)).toBeInTheDocument();
    expect(benchmarks.flips).toHaveBeenCalledWith(["bench_2"], "repo_a");
  });

  it("inspects the runs' models and narrows them to the differences", async () => {
    render(<BenchmarkWorkspace />);
    await screen.findByText("repo_a");

    await userEvent.click(screen.getByRole("button", { name: /View model/ }));

    expect(await screen.findByText(/1 of 2 elements differ by source/)).toBeInTheDocument();
    expect(screen.getByText("Queue Server").closest(".el")).toHaveClass("d-partial");
    await userEvent.click(screen.getByRole("button", { name: "Only differences" }));
    expect(screen.queryByText("Worker")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Side by side" }));
    expect(screen.getByText(/bench_2\/1 vs bench_2\/2 · 1 difference/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "by cause" }));
    expect(screen.getAllByText(/candidate llm_rejected in bench_2\/2/).length).toBeGreaterThan(0);
  });

  it("draws the runs' models as an ArchiMate diagram with each element's comparison status", async () => {
    render(<BenchmarkWorkspace />);
    await screen.findByText("repo_a");
    await userEvent.click(screen.getByRole("button", { name: /View model/ }));
    await screen.findByText(/elements differ by source/);

    await userEvent.click(screen.getByRole("button", { name: "Diagram" }));

    const diagram = screen.getByTestId("archimate");
    expect(diagram).toHaveTextContent("Queue Server: partial 1/2");
    expect(diagram).toHaveTextContent("Worker: stable");
  });
});
