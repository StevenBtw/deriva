import { useCallback, useEffect, useState } from "react";

import { benchmarks, runs } from "../api/client";
import type { BenchmarkGroup, Flip, InspectorView, StepStability } from "../api/types";
import { useTheme } from "../theme/theme";
import { GraphLanes } from "../workspace/GraphLanes";
import { LiveLog } from "../workspace/LiveLog";
import { BenchmarkPanel } from "./BenchmarkPanel";
import { FlipsList, ResultsTable, StepsHeatmap } from "./BenchmarkTabs";
import type { Item } from "./inspect";
import { ElementTrace } from "./ElementTrace";
import { Inspector } from "./Inspector";
import { useBenchmarkRun } from "./useBenchmarkRun";

type Tab = "results" | "steps" | "flips" | "live";

/** Benchmark mode: configuration and sessions left, graphs or the model inspector in the centre, results, steps, flips and the live log below. */
export function BenchmarkWorkspace() {
  const [, , shownTheme] = useTheme();
  const dark = shownTheme === "dark";
  const [selected, setSelected] = useState<string[]>([]);
  const [groups, setGroups] = useState<BenchmarkGroup[]>([]);
  const [steps, setSteps] = useState<Record<string, StepStability[]>>({});
  // Answers keep the request they belong to: after a change of sessions, repository or model an
  // earlier answer (or a pick from it) is not shown as the new one
  const [flipsAnswer, setFlipsAnswer] = useState<{ key: string; flips?: Flip[]; failed?: string } | null>(null);
  const [inspected, setInspected] = useState<{ key: string; view: InspectorView } | null>(null);
  const [repo, setRepo] = useState("");
  // The inspector reads one model's runs: runs of different models are no repeats of each other
  const [inspectModel, setInspectModel] = useState("");
  const [tab, setTab] = useState<Tab>("results");
  const [modelOpen, setModelOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [reload, setReload] = useState(0);
  const [pick, setPick] = useState<{ key: string; item: Item } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const models = [...new Set(groups.filter((g) => g.repository === repo).map((g) => g.model))];
  const model = models.includes(inspectModel) ? inspectModel : (models[0] ?? "");
  const flipsKey = [selected.join(","), repo].join("|");
  const inspectKey = [flipsKey, model].join("|");
  const flipsNow = flipsAnswer?.key === flipsKey ? flipsAnswer : null;
  const flips = flipsNow?.flips ?? [];
  const view = inspected?.key === inspectKey ? inspected.view : null;
  const picked = pick?.key === inspectKey ? pick.item : null;

  const onFinished = useCallback((written: string[]) => {
    if (written.length) setSelected(written);
    setReload((n) => n + 1);
  }, []);
  const { state, start, attach, cancel } = useBenchmarkRun(onFinished);

  // Back from run mode (or after a reload): a benchmark still running is followed again, so it can be watched and cancelled
  useEffect(() => {
    let gone = false;
    runs
      .current()
      .then((run) => {
        if (run && run.kind === "benchmark" && run.status === "running" && !gone) attach(run);
      })
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [attach]);

  useEffect(() => {
    benchmarks
      .list()
      .then((list) => {
        // The newest session is read first; the panel's list finds the others
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
      .then((found) => live && setFlipsAnswer({ key: flipsKey, flips: found }))
      .catch((reason: Error) => live && setFlipsAnswer({ key: flipsKey, failed: reason.message }));
    if (modelOpen) {
      benchmarks
        .inspector(selected, repo, model || undefined)
        .then((found) => live && setInspected({ key: inspectKey, view: found }))
        .catch((reason: Error) => live && setError(reason.message));
    }
    return () => {
      live = false;
    };
  }, [selected, repo, modelOpen, model, flipsKey, inspectKey]);

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
        selected={selected}
        onToggleSession={toggleSession}
        onRemovedSessions={(gone) => setSelected((current) => current.filter((id) => !gone.includes(id)))}
        reload={reload}
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
              {models.length > 1 && (
                <select aria-label="Model to inspect" value={model} onChange={(e) => setInspectModel(e.target.value)}>
                  {models.map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              )}
            </div>
            {picked && (
              <div className="note pickedel">
                <b>
                  {picked.type} "{picked.name}"
                </b>
                {Object.entries(picked.byRun).map(([run, e]) => ` · ${run}: ${e.name} from ${e.source}`)}
                {picked.cause && <div>{picked.cause}</div>}
                <ElementTrace sessions={selected} repo={repo} item={picked} model={model || undefined} />
              </div>
            )}
            <Inspector view={view} onSelect={(item) => setPick({ key: inspectKey, item })} />
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
          {tab === "flips" &&
            (!selected.length || !repo ? (
              <div className="muted">Select benchmark sessions with a repository to see flips.</div>
            ) : (
              <FlipsList flips={flips} loading={!flipsNow} failed={flipsNow?.failed} repos={repos} repo={repo} onRepo={setRepo} />
            ))}
          {tab === "live" && <LiveLog events={state.events} runId={state.runId} runStatus={state.status} />}
        </div>
      </div>
    </section>
  );
}
