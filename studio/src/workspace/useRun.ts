import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, runs } from "../api/client";
import { followRun } from "../api/events";
import type { RunEvent, RunKind, RunSummary } from "../api/types";

export type RunState = {
  runId: string | null;
  status: "idle" | "running" | "finished" | "cancelled" | "error";
  events: RunEvent[];
  error: string | null;
  repository: string | null;
};

const ENDED: RunState["status"][] = ["finished", "cancelled", "error"];

/** A run summary's status as a run state's (a run that is not running has ended). */
function statusOf(run: RunSummary): RunState["status"] {
  if (run.status === "running") return "running";
  return ENDED.find((s) => s === run.status) ?? "finished";
}

/**
 * Start, follow and cancel one run, or attach to one that already exists (a reload, a run picked from the history):
 * its event stream replays from the start. Calls ``onStepComplete`` after every completed step and when the run ends (to refresh views).
 */
export function useRun(onStepComplete?: () => void) {
  const [state, setState] = useState<RunState>({ runId: null, status: "idle", events: [], error: null, repository: null });
  const stop = useRef<(() => void) | null>(null);
  const stepDone = useRef(onStepComplete);

  useEffect(() => {
    stepDone.current = onStepComplete;
  }, [onStepComplete]);

  useEffect(() => () => stop.current?.(), []);

  const follow = useCallback((runId: string) => {
    stop.current = followRun(
      runId,
      (event) => {
        setState((s) => (s.runId === runId ? { ...s, events: [...s.events, event] } : s));
        if (event.event === "progress" && event.data.status === "complete") stepDone.current?.();
      },
      (name, lost) => {
        // A lost stream ends only a run still running (the server lost it); a run that had ended keeps its own status
        setState((s) => {
          if (s.runId !== runId || (lost && s.status !== "running")) return s;
          return { ...s, status: name === "finished" ? "finished" : name === "cancelled" ? "cancelled" : "error" };
        });
        stepDone.current?.();
      },
    );
  }, []);

  const start = useCallback(
    async (kind: RunKind, repository: string | null, noLlm: boolean) => {
      stop.current?.();
      try {
        const { run_id } = await runs.start(kind, repository, noLlm);
        setState({ runId: run_id, status: "running", events: [], error: null, repository });
        follow(run_id);
      } catch (reason) {
        const message =
          reason instanceof ApiError && reason.status === 409 ? "A run is in progress; wait for it or cancel it first." : reason instanceof Error ? reason.message : String(reason);
        setState((s) => ({ ...s, error: message }));
      }
    },
    [follow],
  );

  const attach = useCallback(
    (run: RunSummary) => {
      stop.current?.();
      setState({ runId: run.run_id, status: statusOf(run), events: [], error: null, repository: run.repository });
      follow(run.run_id);
    },
    [follow],
  );

  const cancel = useCallback(async () => {
    if (state.runId) await runs.cancel(state.runId);
  }, [state.runId]);

  return { state, start, attach, cancel };
}
