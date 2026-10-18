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
    graph: { view: vi.fn(), linked: vi.fn() },
    runs: { cancel: vi.fn(), call: vi.fn(), current: vi.fn() },
    benchmarks: {
      list: vi.fn(),
      models: vi.fn(),
      start: vi.fn(),
      results: vi.fn(),
      steps: vi.fn(),
      flips: vi.fn(),
      inspector: vi.fn(),
      trace: vi.fn(),
      exportUrl: actual.benchmarks.exportUrl,
      ocelUrl: actual.benchmarks.ocelUrl,
    },
  };
});

vi.mock("../widgets/GraphWidget", () => ({ GraphWidget: () => <div data-testid="graph" /> }));
vi.mock("../widgets/LinkedGraphWidget", () => ({ LinkedGraphWidget: () => <div data-testid="linked-graph" /> }));

vi.mock("../widgets/ArchimateWidget", () => ({
  ArchimateWidget: ({ elements }: { elements: { id: string; name: string; status?: string; badge?: string }[] }) => (
    <ul data-testid="archimate">
      {elements.map((e) => (
        <li key={e.id}>{`${e.name}: ${e.status} ${e.badge}`}</li>
      ))}
    </ul>
  ),
}));

import { benchmarks, graph, repositories, runs } from "../api/client";
import { followRun } from "../api/events";
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
    vi.mocked(graph.linked).mockResolvedValue({ lanes: [], nodes: [], edges: [], missing_links: 0 });
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
    vi.mocked(benchmarks.trace).mockResolvedValue([
      { run: "bench_2/1", present: true, name: "Queue Server", stage: "created", refine: null, cause: null, calls: [{ call_id: "c1", step: "Node", schema: "selection", cache_key: "k1", cache_hit: false, model: "gpt", temperature: 0, prompt: "Candidates: tech::r::queue", response: '{"keep": true}', error: null }] },
      { run: "bench_2/2", present: false, name: null, stage: "llm_rejected", refine: null, cause: "candidate llm_rejected", calls: [{ call_id: "c2", step: "Node", schema: "selection", cache_key: "k1", cache_hit: false, model: "gpt", temperature: 0, prompt: "Candidates: tech::r::queue", response: '{"keep": false}', error: null }] },
    ]);
    vi.mocked(benchmarks.start).mockResolvedValue({ run_id: "b1" });
    vi.mocked(runs.current).mockResolvedValue(null);
  });

  it("follows a benchmark still running when the workspace opens again (back from run mode, or a reload)", async () => {
    vi.mocked(runs.current).mockResolvedValue({ run_id: "b9", kind: "benchmark", repository: null, status: "running", events: 4, started_at: 1, finished_at: null });
    render(<BenchmarkWorkspace />);

    expect(await screen.findByText(/benchmark running · b9/)).toBeInTheDocument();
    expect(followRun).toHaveBeenCalledWith("b9", expect.any(Function), expect.any(Function));
  });

  it("starts on the model Deriva uses, not the first in the list", async () => {
    vi.mocked(benchmarks.models).mockResolvedValue([
      { name: "a-first", provider: "p", model: "x", default: false },
      { name: "b-cheap", provider: "p", model: "y", default: true },
    ]);
    render(<BenchmarkWorkspace />);

    await waitFor(() => expect(screen.getByLabelText("Model")).toHaveValue("b-cheap"));
  });

  it("leaves a single run in progress to the run workspace", async () => {
    vi.mocked(runs.current).mockResolvedValue({ run_id: "r3", kind: "extraction", repository: "repo_a", status: "running", events: 2, started_at: 1, finished_at: null });
    render(<BenchmarkWorkspace />);
    await screen.findByText("repo_a");

    expect(followRun).not.toHaveBeenCalled();
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

  it("does not call one run consistent: consistency needs two runs", async () => {
    vi.mocked(benchmarks.results).mockResolvedValue([
      { ...GROUP, runs: ["bench_2/1"], counts: [GROUP.counts[0]], rows: GROUP.rows.map((r) => ({ ...r, common: r.union, score: 1 })) },
    ]);
    render(<BenchmarkWorkspace />);

    const panel = screen.getByRole("tabpanel");
    const row = (await within(panel).findByText("repo_a")).closest("tr")!;
    expect(row).toHaveTextContent("1 run");
    expect(row).not.toHaveTextContent("100.0");
    expect(row).toHaveTextContent("n/a / n/a");
    expect(within(panel).getByText(/needs at least 2 runs/)).toBeInTheDocument();
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

  it("offers the process mining logs of the picked sessions", async () => {
    render(<BenchmarkWorkspace />);
    expect(await screen.findByRole("link", { name: /Process mining logs/ })).toHaveAttribute("href", "/api/benchmarks/ocel?sessions=bench_2");

    await userEvent.click(screen.getByRole("button", { name: /bench_1/ }));

    // One OCEL 2.0 log and one case log for all picked sessions, so their runs compare side by side
    await waitFor(() => expect(screen.getByRole("link", { name: /Process mining logs/ })).toHaveAttribute("href", "/api/benchmarks/ocel?sessions=bench_2,bench_1"));
  });

  it("starts a benchmark with samples locked at one and follows its progress", async () => {
    render(<BenchmarkWorkspace />);
    await screen.findByRole("option", { name: "m" });
    await userEvent.click(await screen.findByRole("button", { name: "repo_b" }));
    expect(screen.getByLabelText(/Samples per LLM call/)).toBeDisabled();
    // Plain words for users: no references to the project's internal rules
    expect(screen.getByLabelText(/Samples per LLM call/)).toHaveValue("1 (fixed)");
    expect(document.body.textContent).not.toMatch(/rule \d/);

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

  it("keeps the runs per repository within what the API takes (1 to 20)", async () => {
    render(<BenchmarkWorkspace />);
    await screen.findByRole("option", { name: "m" });
    await userEvent.click(await screen.findByRole("button", { name: "repo_b" }));
    const runs = screen.getByLabelText("Runs per repository");

    await userEvent.clear(runs);
    await userEvent.type(runs, "25");
    expect(runs).toHaveValue(20);
    await userEvent.click(screen.getByRole("button", { name: /Start benchmark/ }));

    expect(benchmarks.start).toHaveBeenCalledWith(expect.objectContaining({ runs: 20 }));
  });

  it("shows answer stability per step and the flips with their cause", async () => {
    render(<BenchmarkWorkspace />);
    await screen.findByText("repo_a");

    await userEvent.click(screen.getByRole("tab", { name: "Steps" }));
    // The counts behind the share are on the cell: 1 of 2 and 21 of 22 read very differently
    const cell = await within(screen.getByRole("tabpanel")).findByText("75.0 (3/4)");
    expect(cell).toHaveAttribute("title", "3 of 4 prompts answered identically");
    expect(screen.getByRole("tabpanel")).toHaveTextContent("one changed label in a batched classification makes the whole answer differ");

    await userEvent.click(screen.getByRole("tab", { name: /Flips/ }));
    expect(await within(screen.getByRole("tabpanel")).findByText(/candidate llm_rejected in bench_2\/2 \(same prompt, different answer\)/)).toBeInTheDocument();
    expect(benchmarks.flips).toHaveBeenCalledWith(["bench_2"], "repo_a");
  });

  it("says the flips could not be read instead of calling every element stable", async () => {
    vi.mocked(benchmarks.flips).mockRejectedValue(new Error("flips failed"));
    render(<BenchmarkWorkspace />);
    await screen.findByText("repo_a");

    await userEvent.click(screen.getByRole("tab", { name: /Flips/ }));

    const panel = screen.getByRole("tabpanel");
    expect(await within(panel).findByText(/flips failed/)).toBeInTheDocument();
    expect(within(panel).queryByText("Every element is in every run.")).not.toBeInTheDocument();
  });

  it("drops the picked element and the comparison when the inspected runs change", async () => {
    vi.mocked(benchmarks.results).mockResolvedValue([GROUP, { ...GROUP, model: "m2" }]);
    render(<BenchmarkWorkspace />);
    await screen.findByText("repo_a");
    await userEvent.click(screen.getByRole("button", { name: /View model/ }));
    await screen.findByText(/elements differ by source/);
    await userEvent.click(screen.getByText("Queue Server"));
    await screen.findByTestId("element-trace");

    vi.mocked(benchmarks.inspector).mockImplementation(() => new Promise(() => {}));
    await userEvent.selectOptions(screen.getByLabelText("Model to inspect"), "m2");

    expect(screen.queryByTestId("element-trace")).not.toBeInTheDocument();
    expect(screen.queryByText(/elements differ by source/)).not.toBeInTheDocument();
  });

  it("names the model of each flip when the sessions use several models", async () => {
    const flip = { source: "tech::r::queue", names: { "bench_2/1": "Queue Server" }, present: ["bench_2/1"], missing: {}, also_from: {}, llm: null, cause: "Node: no candidate" };
    vi.mocked(benchmarks.flips).mockResolvedValue([
      { ...flip, type: "Node", model: "luna" },
      { ...flip, type: "Node", model: "small" },
    ]);
    render(<BenchmarkWorkspace />);
    await screen.findByText("repo_a");

    await userEvent.click(screen.getByRole("tab", { name: /Flips/ }));

    const panel = screen.getByRole("tabpanel");
    expect(await within(panel).findByText(/· luna/)).toBeInTheDocument();
    expect(within(panel).getByText(/· small/)).toBeInTheDocument();
  });

  it("inspects one model at a time when the sessions use several", async () => {
    vi.mocked(benchmarks.results).mockResolvedValue([GROUP, { ...GROUP, model: "m2" }]);
    render(<BenchmarkWorkspace />);
    await screen.findByText("repo_a");

    await userEvent.click(screen.getByRole("button", { name: /View model/ }));

    const picker = await screen.findByLabelText("Model to inspect");
    await waitFor(() => expect(benchmarks.inspector).toHaveBeenLastCalledWith(["bench_2"], "repo_a", "m"));
    await userEvent.selectOptions(picker, "m2");
    await waitFor(() => expect(benchmarks.inspector).toHaveBeenLastCalledWith(["bench_2"], "repo_a", "m2"));
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

  it("traces a picked element per run from the session files, with its deciding calls", async () => {
    render(<BenchmarkWorkspace />);
    await screen.findByText("repo_a");
    await userEvent.click(screen.getByRole("button", { name: /View model/ }));
    await screen.findByText(/elements differ by source/);

    await userEvent.click(screen.getByText("Queue Server"));

    // The trace reads the inspected model's runs
    await waitFor(() => expect(benchmarks.trace).toHaveBeenCalledWith(["bench_2"], "repo_a", "Node", "tech::r::queue", "m"));
    const trace = await screen.findByTestId("element-trace");
    expect(trace).toHaveTextContent("bench_2/1: in the model as \"Queue Server\" · candidate created");
    expect(trace).toHaveTextContent("bench_2/2: missing · candidate llm_rejected");
    await userEvent.click(within(trace).getAllByRole("button", { name: /answer/ })[1]);
    expect(within(trace).getByText('{"keep": false}')).toBeInTheDocument();
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
