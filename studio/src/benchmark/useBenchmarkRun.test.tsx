import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BenchmarkRequest, RunEvent } from "../api/types";

const handlers: { onEvent?: (e: RunEvent) => void } = {};

vi.mock("../api/events", () => ({
  followRun: vi.fn((_runId: string, onEvent: (e: RunEvent) => void) => {
    handlers.onEvent = onEvent;
    return () => {};
  }),
}));

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, benchmarks: { start: vi.fn() }, runs: { cancel: vi.fn() } };
});

import { benchmarks } from "../api/client";
import { followRun } from "../api/events";
import { useBenchmarkRun } from "./useBenchmarkRun";

const REQUEST: BenchmarkRequest = {
  repositories: ["repo_a"],
  model: "m",
  runs: 1,
  stages: null,
  use_cache: false,
  per_repo: true,
  separate_sessions: false,
  no_cache_extraction: false,
};

describe("useBenchmarkRun", () => {
  it("lists the sessions a failed benchmark wrote", async () => {
    vi.mocked(benchmarks.start).mockResolvedValue({ run_id: "b1" });
    const onFinished = vi.fn();
    const { result } = renderHook(() => useBenchmarkRun(onFinished));

    await act(() => result.current.start(REQUEST));
    act(() => handlers.onEvent?.({ seq: 2, event: "error", data: { message: "LLM provider unavailable", sessions: ["bench_1"] } }));

    expect(onFinished).toHaveBeenCalledWith(["bench_1"]);
  });

  it("follows nothing once unmounted while the start request ran", async () => {
    let resolve: (value: { run_id: string }) => void = () => {};
    vi.mocked(benchmarks.start).mockImplementation(() => new Promise((done) => (resolve = done)));
    const { result, unmount } = renderHook(() => useBenchmarkRun());

    const started = result.current.start(REQUEST);
    unmount();
    resolve({ run_id: "b2" });
    await started;

    expect(followRun).not.toHaveBeenCalled();
  });
});
