import type { RunEvent } from "../api/types";
import { LiveLog } from "./LiveLog";
import { PromptsList } from "./LlmCalls";
import { TracePanel } from "./TracePanel";

export type Tab = "live" | "trace" | "prompts" | "errors";

type Props = { events: RunEvent[]; status: string; runId?: string | null; tab: Tab; onTab: (tab: Tab) => void; traceElement?: string | null };

/** Live log, trace of the selected element, the run's prompts and its errors. */
export function BottomPanel({ events, status, runId = null, tab, onTab, traceElement = null }: Props) {
  const errors = events.filter((e) => e.event === "error");
  const calls = events.filter((e) => e.event === "llm");
  const tabs: [Tab, string][] = [
    ["live", "Live"],
    ["trace", "Trace"],
    ["prompts", calls.length ? `Prompts (${calls.length})` : "Prompts"],
    ["errors", errors.length ? `Errors (${errors.length})` : "Errors"],
  ];

  return (
    <div className="bottom">
      <div className="tabs" role="tablist">
        {tabs.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => onTab(key)}>
            {label}
          </button>
        ))}
        <span className="right">{status}</span>
      </div>
      <div className="tabpanel" role="tabpanel">
        {tab === "live" && <LiveLog events={events} runId={runId} />}
        {tab === "trace" && <TracePanel elementId={traceElement} runId={runId} />}
        {tab === "prompts" && <PromptsList runId={runId} calls={calls} />}
        {tab === "errors" &&
          (errors.length ? (
            errors.map((e) => (
              <div key={e.seq} className="logline error">
                {e.data.message}
              </div>
            ))
          ) : (
            <div className="muted">No errors in this run.</div>
          ))}
      </div>
    </div>
  );
}
