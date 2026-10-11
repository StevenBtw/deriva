import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, benchmarks, runs } from "../api/client";
import { followRun } from "../api/events";
import type { BenchmarkRequest, RunEvent, RunSummary } from "../api/types";

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

  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      stop.current?.();
    };
  }, []);

  const follow = useCallback((runId: string) => {
    setState({ runId, status: "running", events: [], error: null });
    stop.current = followRun(
      runId,
      (event) => {
        setState((s) => ({ ...s, events: [...s.events, event] }));
        // A failed benchmark can have written sessions too
        if (event.event === "finished" || event.event === "cancelled" || event.event === "error") finished.current?.(event.data.sessions ?? []);
      },
      (name) => setState((s) => ({ ...s, status: name === "finished" ? "finished" : name === "cancelled" ? "cancelled" : "error" })),
    );
  }, []);

  const start = useCallback(
    async (request: BenchmarkRequest) => {
      stop.current?.();
      try {
        const { run_id } = await benchmarks.start(request);
        // Unmounted while the request ran: no stream to open that nothing would close
        if (!mounted.current) return;
        follow(run_id);
      } catch (reason) {
        const message =
          reason instanceof ApiError && reason.status === 409 ? "A run is in progress; wait for it or cancel it first." : reason instanceof Error ? reason.message : String(reason);
        setState((s) => ({ ...s, error: message }));
      }
    },
    [follow],
  );

  /** Follow a benchmark already running (the workspace opened again): its stream replays from the start. */
  const attach = useCallback(
    (run: RunSummary) => {
      stop.current?.();
      follow(run.run_id);
    },
    [follow],
  );

  const cancel = useCallback(async () => {
    if (state.runId) await runs.cancel(state.runId);
  }, [state.runId]);

  return { state, start, attach, cancel };
}
