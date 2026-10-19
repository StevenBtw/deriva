import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, benchmarks: { list: vi.fn(), remove: vi.fn(), markFailed: vi.fn() } };
});

import { ApiError, benchmarks } from "../api/client";
import type { BenchmarkSession } from "../api/types";
import { SessionList } from "./SessionList";

const session = (session_id: string, status: string, extra: Partial<BenchmarkSession> = {}): BenchmarkSession => ({
  session_id,
  description: "candidate GlobalRelationships v35",
  status,
  started_at: "2026-10-18T18:23:33",
  completed_at: null,
  repositories: ["deriva", "TeaStore"],
  models: ["mistral-small4"],
  runs: 6,
  stages: ["derivation"],
  bytes: 125_829_120,
  ...extra,
});

const PAGE = Array.from({ length: 20 }, (_, i) => session(`bench_${20 - i}`, i === 1 ? "running" : "completed"));

describe("SessionList", () => {
  beforeEach(() => {
    vi.mocked(benchmarks.list).mockResolvedValue(PAGE);
    vi.mocked(benchmarks.remove).mockResolvedValue({ session_id: "bench_20", runs: 6, bytes: 125_829_120 });
    vi.mocked(benchmarks.markFailed).mockResolvedValue({ session_id: "bench_19", runs_marked: 2 });
  });

  const props = (over: Partial<Parameters<typeof SessionList>[0]> = {}) => ({
    selected: [] as string[],
    onToggle: vi.fn(),
    onRemoved: vi.fn(),
    repositories: ["deriva", "TeaStore"],
    models: ["mistral-small4", "haiku"],
    reload: 0,
    ...over,
  });

  it("shows each session's description, repositories, model, runs and size", async () => {
    render(<SessionList {...props()} />);

    const row = await screen.findByRole("button", { name: /bench_20/ });
    expect(row).toHaveTextContent("candidate GlobalRelationships v35");
    expect(row).toHaveTextContent("2 repositories · mistral-small4 · 6 runs · 120.0 MB");
    expect(row).toHaveTextContent("2026-10-18 18:23");
    expect(benchmarks.list).toHaveBeenCalledWith(20, { offset: 0, search: null, repository: null, model: null, status: null });
  });

  it("finds sessions by text, repository, model and status, and loads more", async () => {
    const user = userEvent.setup();
    render(<SessionList {...props()} />);
    await screen.findByRole("button", { name: /bench_20/ });

    await user.type(screen.getByLabelText("Search sessions"), "v35");
    await user.selectOptions(screen.getByLabelText("Session repository"), "TeaStore");
    await user.selectOptions(screen.getByLabelText("Session model"), "haiku");
    await user.selectOptions(screen.getByLabelText("Session status"), "failed");
    await waitFor(() => expect(benchmarks.list).toHaveBeenLastCalledWith(20, { offset: 0, search: "v35", repository: "TeaStore", model: "haiku", status: "failed" }));

    vi.mocked(benchmarks.list).mockResolvedValueOnce([session("bench_0", "failed")]);
    await user.click(screen.getByRole("button", { name: "Show more" }));
    expect(await screen.findByRole("button", { name: /bench_0/ })).toBeInTheDocument();
    expect(benchmarks.list).toHaveBeenLastCalledWith(20, { offset: 20, search: "v35", repository: "TeaStore", model: "haiku", status: "failed" });
  });

  it("deletes the selected sessions after naming how much goes", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const p = props({ selected: ["bench_20", "bench_18"] });
    render(<SessionList {...p} />);
    await screen.findByRole("button", { name: /bench_20/ });

    await userEvent.click(screen.getByRole("button", { name: "Delete 2 sessions" }));

    expect(confirm.mock.calls[0][0]).toMatch(/2 benchmark sessions \(240\.0 MB\)/);
    expect(benchmarks.remove).toHaveBeenCalledWith("bench_20");
    expect(benchmarks.remove).toHaveBeenCalledWith("bench_18");
    await waitFor(() => expect(p.onRemoved).toHaveBeenCalledWith(["bench_20", "bench_18"]));
  });

  it("marks a selected session that still says running as failed", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<SessionList {...props({ selected: ["bench_19"] })} />);
    await screen.findByRole("button", { name: /bench_19/ });

    await userEvent.click(screen.getByRole("button", { name: "Mark failed" }));

    expect(benchmarks.markFailed).toHaveBeenCalledWith("bench_19");
    expect(screen.queryByRole("button", { name: /Delete/ })).not.toBeInTheDocument();
  });

  it("says why a session could not be deleted", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.mocked(benchmarks.remove).mockRejectedValue(new ApiError(409, "A run is in progress; try again when it has finished", {}));
    render(<SessionList {...props({ selected: ["bench_20"] })} />);
    await screen.findByRole("button", { name: /bench_20/ });

    await userEvent.click(screen.getByRole("button", { name: "Delete 1 session" }));

    expect(await screen.findByText("A run is in progress; try again when it has finished")).toBeInTheDocument();
  });
});
