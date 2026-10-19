import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, runs: { history: vi.fn(), remove: vi.fn(), prune: vi.fn() }, storage: { overview: vi.fn(), clearLlmCache: vi.fn(), deleteExports: vi.fn(), deleteGraph: vi.fn() } };
});

import { ApiError, runs, storage } from "../api/client";
import type { RunSummary } from "../api/types";
import { Storage } from "./Storage";

const run = (run_id: string, kind: RunSummary["kind"], repository: string, status: string, started_at: number): RunSummary => ({
  run_id,
  kind,
  repository,
  status,
  events: 12,
  started_at,
  finished_at: started_at + 60,
});

const PAGE = Array.from({ length: 20 }, (_, i) => run(`r${i}`, i % 2 ? "derivation" : "all", i % 3 ? "deriva" : "TeaStore", i === 4 ? "interrupted" : "finished", 1_792_300_000 - i * 100));

const OVERVIEW = {
  graphs: [
    { key: "deriva", bytes: 11_900_000, kind: "repository" as const, active: true },
    { key: "oldrepo", bytes: 2_500_000, kind: "orphaned" as const, active: false },
    { key: "default", bytes: 300_000, kind: "shared" as const, active: false },
  ],
  llm_cache: { bytes: 2_444_000_000, files: 183 },
  exports: { bytes: 10_100_000, files: 57 },
  benchmark_sessions: { bytes: 9_536_500_000, sessions: 944 },
  runs: { runs: 11, bytes: 2_900_000 },
};

describe("Runs", () => {
  beforeEach(() => {
    vi.mocked(storage.overview).mockResolvedValue(OVERVIEW);
    vi.mocked(runs.history).mockResolvedValue(PAGE);
    vi.mocked(runs.remove).mockResolvedValue({ deleted: "r1" });
    vi.mocked(runs.prune).mockResolvedValue({ deleted: ["r4"] });
  });

  it("lists the runs a page at a time and loads more", async () => {
    render(<Storage />);

    expect(await screen.findByRole("cell", { name: "r0" })).toBeInTheDocument();
    expect(runs.history).toHaveBeenCalledWith(20, { offset: 0, repository: null, kind: null });
    vi.mocked(runs.history).mockResolvedValueOnce([run("r20", "extraction", "deriva", "finished", 1_792_200_000)]);
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));

    expect(await screen.findByRole("cell", { name: "r20" })).toBeInTheDocument();
    expect(runs.history).toHaveBeenLastCalledWith(20, { offset: 20, repository: null, kind: null });
    expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
  });

  it("filters by repository and kind", async () => {
    render(<Storage />);
    await screen.findByRole("cell", { name: "r0" });

    await userEvent.type(screen.getByLabelText("Repository"), "deriva");
    await userEvent.selectOptions(screen.getByLabelText("Kind"), "derivation");

    await waitFor(() => expect(runs.history).toHaveBeenLastCalledWith(20, { offset: 0, repository: "deriva", kind: "derivation" }));
  });

  it("deletes a run after asking", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Storage />);
    const row = (await screen.findByRole("cell", { name: "r1" })).closest("tr")!;

    await userEvent.click(within(row).getByRole("button", { name: "Delete" }));

    expect(runs.remove).toHaveBeenCalledWith("r1");
    await waitFor(() => expect(screen.queryByRole("cell", { name: "r1" })).not.toBeInTheDocument());
  });

  it("deletes the interrupted runs, or every run past the latest N", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Storage />);
    await screen.findByRole("cell", { name: "r0" });

    await userEvent.click(screen.getByRole("button", { name: "Delete interrupted runs" }));
    expect(runs.prune).toHaveBeenCalledWith({ interrupted: true });
    expect(await screen.findByText("Deleted 1 run")).toBeInTheDocument();

    vi.mocked(runs.prune).mockResolvedValueOnce({ deleted: ["r18", "r19"] });
    await userEvent.clear(screen.getByLabelText("Keep the latest"));
    await userEvent.type(screen.getByLabelText("Keep the latest"), "18");
    await userEvent.click(screen.getByRole("button", { name: "Delete older runs" }));
    expect(runs.prune).toHaveBeenLastCalledWith({ keep: 18 });
    expect(await screen.findByText("Deleted 2 runs")).toBeInTheDocument();
  });

  it("says why the run in progress cannot be deleted", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(runs.remove).mockRejectedValue(new ApiError(409, "The run is in progress; cancel it first", {}));
    render(<Storage />);
    const row = (await screen.findByRole("cell", { name: "r1" })).closest("tr")!;

    await userEvent.click(within(row).getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("The run is in progress; cancel it first")).toBeInTheDocument();
  });
});

describe("Storage", () => {
  beforeEach(() => {
    vi.mocked(runs.history).mockResolvedValue([]);
    vi.mocked(storage.overview).mockResolvedValue(OVERVIEW);
    vi.mocked(storage.clearLlmCache).mockResolvedValue({ bytes: 2_444_000_000, files: 183 });
    vi.mocked(storage.deleteExports).mockResolvedValue({ bytes: 10_100_000, files: 57 });
    vi.mocked(storage.deleteGraph).mockResolvedValue({ key: "oldrepo", bytes: 2_500_000 });
  });

  it("shows what each area takes on disk", async () => {
    render(<Storage />);

    const card = (await screen.findByRole("heading", { name: "Storage" })).closest(".card") as HTMLElement;
    expect(within(card).getByText("2.3 GB")).toBeInTheDocument();
    expect(within(card).getByText("183 files")).toBeInTheDocument();
    expect(within(card).getByText("944 sessions")).toBeInTheDocument();
    expect(within(card).getByText("11 runs")).toBeInTheDocument();
    const orphan = within(card).getByRole("cell", { name: "oldrepo" }).closest("tr")!;
    expect(within(orphan).getByText("no repository")).toBeInTheDocument();
    expect(within(orphan).getByRole("button", { name: "Delete" })).toBeEnabled();
    const own = within(card).getByRole("cell", { name: "deriva" }).closest("tr")!;
    expect(within(own).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("warns before clearing the LLM cache and says what was freed", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Storage />);
    await screen.findByText("2.3 GB");

    await userEvent.click(screen.getByRole("button", { name: "Clear LLM cache" }));

    expect(confirm.mock.calls[0][0]).toMatch(/calls the LLM again/);
    expect(storage.clearLlmCache).toHaveBeenCalled();
    expect(await screen.findByText("Freed 2.3 GB")).toBeInTheDocument();
    await waitFor(() => expect(storage.overview).toHaveBeenCalledTimes(2));
  });

  it("deletes the exports and an orphaned graph", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<Storage />);
    await screen.findByText("2.3 GB");

    await userEvent.click(screen.getByRole("button", { name: "Delete exports" }));
    expect(storage.deleteExports).toHaveBeenCalled();
    const orphan = (await screen.findByRole("cell", { name: "oldrepo" })).closest("tr")!;
    await userEvent.click(within(orphan).getByRole("button", { name: "Delete" }));
    expect(storage.deleteGraph).toHaveBeenCalledWith("oldrepo");
  });
});
