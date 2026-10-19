import { type KeyboardEvent, useEffect, useId, useState } from "react";

import { runs } from "../api/client";
import type { RunEvent } from "../api/types";
import { downloadText } from "../components/download";
import { LiveLog } from "./LiveLog";
import { PromptsList } from "./LlmCalls";
import { TracePanel } from "./TracePanel";

export type Tab = "live" | "trace" | "prompts" | "errors";

type Props = { events: RunEvent[]; status: string; runId?: string | null; runStatus?: string; tab: Tab; onTab: (tab: Tab) => void; traceElement?: string | null };

// Arrow keys move along the tabs (wrapping), Home and End go to the first and last
const MOVES: Record<string, (index: number, count: number) => number> = {
  ArrowRight: (i, n) => (i + 1) % n,
  ArrowLeft: (i, n) => (i - 1 + n) % n,
  Home: () => 0,
  End: (_, n) => n - 1,
};

/** A run's saved LLM calls, for a run whose events this page has no copy of (it ran before the studio restarted). */
function useSavedCalls(runId: string | null, live: number): RunEvent[] {
  const [saved, setSaved] = useState<{ runId: string; calls: RunEvent[] } | null>(null);

  useEffect(() => {
    if (!runId || live) return;
    let gone = false;
    runs
      .calls(runId)
      .then((list) => {
        if (!gone) setSaved({ runId, calls: list.map((call, i) => ({ seq: i + 1, event: "llm", data: call as RunEvent["data"] })) });
      })
      .catch(() => {});
    return () => {
      gone = true;
    };
  }, [runId, live]);

  return saved && saved.runId === runId ? saved.calls : [];
}

/** A failed run (its terminal error), or a step that failed and let the run go on (a progress update with status error). */
function isError(event: RunEvent): boolean {
  return event.event === "error" || (event.event === "progress" && event.data.status === "error");
}

// A long error list shows its start; the download has all of it
const SAMPLE = 50;

/** The run's error lines: failed steps and a failed run, then the errors that completed steps reported (a file that
 * could not be read, say), which reach the browser only in the run's last update. A failed step's message is in that
 * list too, so it is shown once. */
function errorLines(events: RunEvent[]): string[] {
  const failed = events.filter(isError).map((e) => (e.event === "progress" && e.data.step ? `${e.data.step}: ${e.data.message ?? "failed"}` : (e.data.message ?? "failed")));
  const messages = new Set(events.filter(isError).map((e) => e.data.message));
  const reported = events.flatMap((e) => (e.event === "progress" && !e.data.step && Array.isArray(e.data.stats?.errors) ? (e.data.stats.errors as unknown[]).map(String) : []));
  return [...failed, ...reported.filter((line) => !messages.has(line))];
}

/** Live log, trace of the selected element, the run's prompts and its errors. */
export function BottomPanel({ events, status, runId = null, runStatus = "idle", tab, onTab, traceElement = null }: Props) {
  const id = useId();
  const errors = errorLines(events);
  const live = events.filter((e) => e.event === "llm");
  const saved = useSavedCalls(runId, live.length);
  const calls = live.length ? live : saved;
  const tabs: [Tab, string][] = [
    ["live", "Live"],
    ["trace", "Trace"],
    ["prompts", calls.length ? `Prompts (${calls.length})` : "Prompts"],
    ["errors", errors.length ? `Errors (${errors.length})` : "Errors"],
  ];
  const tabId = (key: Tab) => `${id}-tab-${key}`;
  const panelId = `${id}-panel`;

  // One tab stop for the tab list (the selected tab); the arrow keys choose among them
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const move = MOVES[event.key];
    if (!move) return;
    event.preventDefault();
    const next = tabs[move(index, tabs.length)][0];
    onTab(next);
    document.getElementById(tabId(next))?.focus();
  };

  return (
    <div className="bottom">
      <div className="tabs" role="tablist">
        {tabs.map(([key, label], index) => (
          <button
            key={key}
            id={tabId(key)}
            type="button"
            role="tab"
            aria-selected={tab === key}
            aria-controls={panelId}
            tabIndex={tab === key ? 0 : -1}
            onClick={() => onTab(key)}
            onKeyDown={(event) => onKeyDown(event, index)}
          >
            {label}
          </button>
        ))}
        <span className="right">{status}</span>
      </div>
      <div className="tabpanel" role="tabpanel" id={panelId} aria-labelledby={tabId(tab)}>
        {tab === "live" && <LiveLog events={events} runId={runId} runStatus={runStatus} />}
        {tab === "trace" && <TracePanel elementId={traceElement} runId={runId} />}
        {tab === "prompts" && <PromptsList runId={runId} calls={calls} />}
        {tab === "errors" &&
          (errors.length ? (
            <>
              {errors.length > SAMPLE && (
                <div className="row-actions">
                  <span className="muted">{`${SAMPLE} of ${errors.length} shown`}</span>
                  <button type="button" onClick={() => downloadText(errors, `${runId ?? "run"}-errors.txt`)}>
                    {`Download all ${errors.length}`}
                  </button>
                </div>
              )}
              {errors.slice(0, SAMPLE).map((line, i) => (
                <div key={i} className="logline error">
                  {line}
                </div>
              ))}
            </>
          ) : (
            <div className="muted">No errors in this run.</div>
          ))}
      </div>
    </div>
  );
}
