import { useCallback, useState } from "react";

import { session } from "../api/client";
import { BenchmarkWorkspace } from "../benchmark/BenchmarkWorkspace";
import type { Mode } from "../shell/TopBar";

import { useTheme } from "../theme/theme";
import { BottomPanel, type Tab } from "./BottomPanel";
import { GraphLanes } from "./GraphLanes";
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
  const { state, start, cancel } = useRun(onStepComplete);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("live");
  const [traceElement, setTraceElement] = useState<string | null>(null);
  const onSelect = useCallback((elementId: string | null) => {
    if (!elementId) return;
    setTraceElement(elementId);
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

  return (
    <section className="ws">
      <RunPanel
        run={switchError ? { ...state, error: switchError } : state}
        onStart={start}
        onCancel={cancel}
        collapsed={panelCollapsed || modelOpen}
        onToggle={() => setPanelCollapsed((c) => !c)}
        onRepositoryChange={onRepositoryChange}
      />
      <div className="center">
        {modelOpen ? <ModelPanel dark={dark} refresh={refresh} onSelect={onSelect} /> : <GraphLanes refresh={refresh} dark={dark} />}
      </div>
      <button type="button" className="modelhandle" onClick={() => setModelOpen((o) => !o)}>
        {modelOpen ? "‹ Graphs" : "View model ›"}
      </button>
      <BottomPanel events={state.events} runId={state.runId} tab={tab} onTab={setTab} traceElement={traceElement} status={`run ${STATUS[state.status]}${state.runId ? ` · ${state.runId}` : ""}`} />
    </section>
  );
}
