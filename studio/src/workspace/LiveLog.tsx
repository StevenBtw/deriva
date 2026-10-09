import { useEffect, useRef } from "react";

import type { RunEvent } from "../api/types";
import { LlmLine } from "./LlmCalls";

function time(ts?: number): string {
  if (!ts) return "";
  return new Date(ts * 1000).toTimeString().slice(0, 8);
}

function line(event: RunEvent): string {
  const d = event.data;
  if (event.event === "started") return `Run started · ${d.kind ?? ""}${d.repository ? ` · ${d.repository}` : ""}`;
  if (event.event === "finished") return "Run finished";
  if (event.event === "cancelled") return "Run cancelled";
  if (event.event === "error") return `Error: ${d.message ?? "unknown"}`;
  const position = d.total ? ` (${d.current}/${d.total})` : "";
  return `${d.status === "complete" ? "✓" : "▸"} ${d.step ?? d.phase ?? ""}${position}${d.message ? ` · ${d.message}` : ""}`;
}

/** Each event with the phase header to show before it (when the phase changes). */
function withHeaders(events: RunEvent[]): { event: RunEvent; header: string | null }[] {
  const rows: { event: RunEvent; header: string | null }[] = [];
  let phase: string | undefined;
  for (const event of events) {
    const next = event.event === "progress" ? event.data.phase : undefined;
    const header = next && next !== phase ? next : null;
    if (header) phase = header;
    rows.push({ event, header });
  }
  return rows;
}

/** The run's events as log lines, with a header whenever the phase changes; scrolls along. */
export function LiveLog({ events, runId = null }: { events: RunEvent[]; runId?: string | null }) {
  const end = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [events.length]);

  if (!events.length) return <div className="muted">Start a run to follow its progress here.</div>;
  return (
    <div>
      {withHeaders(events).map(({ event, header }) => {
        return (
          <div key={event.seq}>
            {header && <div className="logline phase">{header[0].toUpperCase() + header.slice(1)}</div>}
            {event.event === "llm" ? (
              <LlmLine runId={runId} event={event} time={time(event.data.ts)} />
            ) : (
              <div className={`logline${event.event === "error" ? " error" : ""}`}>
                <span className="ts">{time(event.data.ts)}</span>
                {line(event)}
              </div>
            )}
          </div>
        );
      })}
      <div ref={end} />
    </div>
  );
}
