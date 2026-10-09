import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, runs } from "../api/client";
import { followRun } from "../api/events";
import type { RunEvent, RunKind } from "../api/types";

export type RunState = {
  runId: string | null;
  status: "idle" | "running" | "finished" | "cancelled" | "error";
  events: RunEvent[];
  error: string | null;
};

/** Start, follow and cancel one run; calls ``onStepComplete`` after every completed step (to refresh views). */
export function useRun(onStepComplete?: () => void) {
  const [state, setState] = useState<RunState>({ runId: null, status: "idle", events: [], error: null });
  const stop = useRef<(() => void) | null>(null);
  const stepDone = useRef(onStepComplete);

  useEffect(() => {
    stepDone.current = onStepComplete;
  }, [onStepComplete]);

  useEffect(() => () => stop.current?.(), []);

  const start = useCallback(async (kind: RunKind, repository: string | null, noLlm: boolean) => {
    stop.current?.();
    try {
      const { run_id } = await runs.start(kind, repository, noLlm);
      setState({ runId: run_id, status: "running", events: [], error: null });
      stop.current = followRun(
        run_id,
        (event) => {
          setState((s) => ({ ...s, events: [...s.events, event] }));
          if (event.event === "progress" && event.data.status === "complete") stepDone.current?.();
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
