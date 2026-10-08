import { useCallback, useEffect, useState } from "react";

import { benchmarks } from "../api/client";
import type { BenchmarkGroup, BenchmarkSession, Flip, InspectorView, StepStability } from "../api/types";
import { useTheme } from "../theme/theme";
import { GraphLanes } from "../workspace/GraphLanes";
import { LiveLog } from "../workspace/LiveLog";
import { BenchmarkPanel } from "./BenchmarkPanel";
import { FlipsList, ResultsTable, StepsHeatmap } from "./BenchmarkTabs";
import type { Item } from "./inspect";
import { Inspector } from "./Inspector";
import { useBenchmarkRun } from "./useBenchmarkRun";

type Tab = "results" | "steps" | "flips" | "live";

/** Benchmark mode: configuration and sessions left, graphs or the model inspector in the centre, results, steps, flips and the live log below. */
export function BenchmarkWorkspace() {
  const [, , shownTheme] = useTheme();
  const dark = shownTheme === "dark";
  const [sessions, setSessions] = useState<BenchmarkSession[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [groups, setGroups] = useState<BenchmarkGroup[]>([]);
  const [steps, setSteps] = useState<Record<string, StepStability[]>>({});
  const [flips, setFlips] = useState<Flip[]>([]);
  const [view, setView] = useState<InspectorView | null>(null);
  const [repo, setRepo] = useState("");
  const [tab, setTab] = useState<Tab>("results");
  const [modelOpen, setModelOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [reload, setReload] = useState(0);
  const [picked, setPicked] = useState<Item | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onFinished = useCallback((written: string[]) => {
    if (written.length) setSelected(written);
    setReload((n) => n + 1);
  }, []);
  const { state, start, cancel } = useBenchmarkRun(onFinished);

  useEffect(() => {
    benchmarks
      .list()
      .then((list) => {
        setSessions(list);
        setSelected((current) => (current.length ? current : list[0] ? [list[0].session_id] : []));
      })
      .catch((reason: Error) => setError(reason.message));
  }, [reload]);

  useEffect(() => {
    if (!selected.length) return;
    let live = true;
    benchmarks
      .results(selected)
      .then((found) => {
        if (!live) return;
        setGroups(found);
        setRepo((current) => (found.some((g) => g.repository === current) ? current : (found[0]?.repository ?? "")));
        setError(null);
      })
      .catch((reason: Error) => live && setError(reason.message));
    benchmarks
      .steps(selected)
      .then((found) => live && setSteps(found))
      .catch(() => live && setSteps({}));
    return () => {
      live = false;
    };
  }, [selected]);

  useEffect(() => {
    if (!selected.length || !repo) return;
    let live = true;
    benchmarks
      .flips(selected, repo)
      .then((found) => live && setFlips(found))
      .catch(() => live && setFlips([]));
    if (modelOpen) {
      benchmarks
        .inspector(selected, repo)
        .then((found) => live && setView(found))
        .catch((reason: Error) => live && setError(reason.message));
    }
    return () => {
      live = false;
    };
  }, [selected, repo, modelOpen]);

  const toggleSession = (id: string) => setSelected((current) => (current.includes(id) ? (current.length > 1 ? current.filter((x) => x !== id) : current) : [...current, id]));
  const repos = [...new Set(groups.map((g) => g.repository))];
  const tabs: [Tab, string][] = [
    ["results", "Results"],
    ["steps", "Steps"],
    ["flips", flips.length ? `Flips (${flips.length})` : "Flips"],
    ["live", "Live"],
  ];

  return (
    <section className="ws">
      <BenchmarkPanel
        run={state}
        sessions={sessions}
        selected={selected}
        onToggleSession={toggleSession}
        onStart={(request) => {
          setTab("live");
          void start(request);
        }}
        onCancel={cancel}
        collapsed={collapsed || modelOpen}
        onToggle={() => setCollapsed((c) => !c)}
      />
      <div className="center">
        {modelOpen ? (
          <div className="modelpanel">
            <div className="modelpanel-head">
              <b>Runs' models</b>
              {repos.length > 1 ? (
                <select aria-label="Repository to inspect" value={repo} onChange={(e) => setRepo(e.target.value)}>
                  {repos.map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              ) : (
                <span className="muted">{repo}</span>
              )}
            </div>
            {picked && (
              <div className="note pickedel">
                <b>
                  {picked.type} "{picked.name}"
                </b>
                {Object.entries(picked.byRun).map(([run, e]) => ` · ${run}: ${e.name} from ${e.source}`)}
                {picked.cause && <div>{picked.cause}</div>}
              </div>
            )}
            <Inspector view={view} onSelect={setPicked} />
          </div>
        ) : (
          <GraphLanes refresh={reload} dark={dark} />
        )}
      </div>
      <button type="button" className="modelhandle" onClick={() => setModelOpen((o) => !o)}>
        {modelOpen ? "‹ Graphs" : "View model ›"}
      </button>
      <div className="bottom">
        <div className="tabs" role="tablist">
          {tabs.map(([key, label]) => (
            <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>
              {label}
            </button>
          ))}
          <span className="right">
            benchmark {state.status}
            {state.runId ? ` · ${state.runId}` : ""} · {selected.length} session{selected.length === 1 ? "" : "s"}
          </span>
        </div>
        <div className="tabpanel" role="tabpanel">
          {error && <div className="logline error">{error}</div>}
          {tab === "results" && <ResultsTable groups={groups} />}
          {tab === "steps" && <StepsHeatmap steps={steps} />}
          {tab === "flips" && <FlipsList flips={flips} repos={repos} repo={repo} onRepo={setRepo} />}
          {tab === "live" && <LiveLog events={state.events} runId={state.runId} />}
        </div>
      </div>
    </section>
  );
}
