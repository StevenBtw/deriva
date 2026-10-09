import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, benchmarks, runs } from "../api/client";
import { followRun } from "../api/events";
import type { BenchmarkRequest, RunEvent } from "../api/types";

export type BenchmarkRunState = {
  runId: string | null;
  status: "idle" | "running" | "finished" | "cancelled" | "error";
  events: RunEvent[];
  error: string | null;
};

/** Start, follow and cancel one benchmark; ``onFinished`` gets the ids of the sessions it wrote. */
export function useBenchmarkRun(onFinished?: (sessions: string[]) => void) {
  const [state, setState] = useState<BenchmarkRunState>({ runId: null, status: "idle", events: [], error: null });
  const stop = useRef<(() => void) | null>(null);
  const finished = useRef(onFinished);

  useEffect(() => {
    finished.current = onFinished;
  }, [onFinished]);

  useEffect(() => () => stop.current?.(), []);

  const start = useCallback(async (request: BenchmarkRequest) => {
    stop.current?.();
    try {
      const { run_id } = await benchmarks.start(request);
      setState({ runId: run_id, status: "running", events: [], error: null });
      stop.current = followRun(
        run_id,
        (event) => {
          setState((s) => ({ ...s, events: [...s.events, event] }));
          if (event.event === "finished" || event.event === "cancelled") finished.current?.(event.data.sessions ?? []);
        },
        (name) => setState((s) => ({ ...s, status: name === "finished" ? "finished" : name === "cancelled" ? "cancelled" : "error" })),
      );
    } catch (reason) {
      const message =
        reason instanceof ApiError && reason.status === 409 ? "A run is in progress; wait for it or cancel it first." : reason instanceof Error ? reason.message : String(reason);
      setState((s) => ({ ...s, error: message }));
    }
  }, []);

  const cancel = useCallback(async () => {
    if (state.runId) await runs.cancel(state.runId);
  }, [state.runId]);

  return { state, start, cancel };
}
