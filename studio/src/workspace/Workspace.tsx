import { useCallback, useEffect, useMemo, useState } from "react";

import { runs, session } from "../api/client";
import { BenchmarkWorkspace } from "../benchmark/BenchmarkWorkspace";
import type { Mode } from "../shell/TopBar";

import { useTheme } from "../theme/theme";
import { BottomPanel, type Tab } from "./BottomPanel";
import { GraphLanes } from "./GraphLanes";
import { pulseFrom } from "./linkedView";
import { ModelPanel } from "./ModelPanel";
import { RunPanel } from "./RunPanel";
import { useRun } from "./useRun";

const STATUS: Record<string, string> = { idle: "idle", running: "running", finished: "finished", cancelled: "cancelled", error: "ended with an error" };

/** The workspace of the chosen mode: a single run, or benchmarks and their sessions. */
export function Workspace({ mode = "run" }: { mode?: Mode }) {
  return mode === "benchmark" ? <BenchmarkWorkspace /> : <RunWorkspace />;
}

/** Run configuration left, the two graphs in the centre, the model panel on the right, the log at the bottom. */
function RunWorkspace() {
  const [, , shownTheme] = useTheme();
  const [refresh, setRefresh] = useState(0);
  const [modelOpen, setModelOpen] = useState(false);
  const [panelCollapsed, setPanelCollapsed] = useState(false);
  const onStepComplete = useCallback(() => setRefresh((n) => n + 1), []);
  const { state, start, attach, cancel } = useRun(onStepComplete);
  // A reload shows the run in progress, else the last one (its stream replays from the start)
  useEffect(() => {
    let gone = false;
    runs
      .current()
      .then((current) => current ?? runs.history(1).then((list) => list[0] ?? null))
      .then((run) => {
        if (run && !gone) attach(run);
      })
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [attach]);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("live");
  const [traceElement, setTraceElement] = useState<string | null>(null);
  const onSelect = useCallback((elementId: string | null) => {
    // A cleared selection clears the trace (it would show an element no longer selected)
    setTraceElement(elementId);
    if (!elementId) return;
    setTab("trace");
  }, []);
  const onRepositoryChange = useCallback((repository: string) => {
    session
      .useRepository(repository)
      .then(() => {
        setSwitchError(null);
        setRefresh((n) => n + 1);
      })
      .catch((reason: Error) => setSwitchError(reason.message));
  }, []);
  const dark = shownTheme === "dark";
  const pulse = useMemo(() => pulseFrom(state.events, state.status), [state.events, state.status]);
  const openModel = useCallback(() => setModelOpen(true), []);

  return (
    <section className="ws">
      <RunPanel
        run={switchError ? { ...state, error: switchError } : state}
        onStart={start}
        onCancel={cancel}
        collapsed={panelCollapsed || modelOpen}
        onToggle={() => setPanelCollapsed((c) => !c)}
        onRepositoryChange={onRepositoryChange}
        onSelectRun={attach}
      />
      <div className="center">
        {modelOpen ? <ModelPanel dark={dark} refresh={refresh} onSelect={onSelect} /> : <GraphLanes refresh={refresh} dark={dark} pulse={pulse} onOpenModel={openModel} />}
      </div>
      <button type="button" className="modelhandle" onClick={() => setModelOpen((o) => !o)}>
        {modelOpen ? "‹ Graphs" : "View model ›"}
      </button>
      <BottomPanel events={state.events} runId={state.runId} runStatus={state.status} tab={tab} onTab={setTab} traceElement={traceElement} status={`run ${STATUS[state.status]}${state.runId ? ` · ${state.runId}` : ""}`} />
    </section>
  );
}
