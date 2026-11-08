import { useEffect, useState } from "react";

import { trace as traceApi } from "../api/client";
import type { Trace } from "../api/types";
import { CallLine } from "./LlmCalls";

// A property longer than this (README lines, evidence lists) folds away under its name, so the source line stays readable
const SHORT_VALUE = 80;

function value(v: unknown): string {
  // Graph metrics carry every digit of a float; four significant ones say as much here
  if (typeof v === "number" && !Number.isInteger(v)) return String(Number(v.toPrecision(4)));
  return typeof v === "string" ? v : JSON.stringify(v);
}

function sizeOf(v: unknown): string {
  if (Array.isArray(v)) return `${v.length} item${v.length === 1 ? "" : "s"}`;
  if (typeof v === "string") return `${v.length} characters`;
  return `${Object.keys(v ?? {}).length} keys`;
}

/** A long value unfolded: a list one item per line, an object as indented JSON, a text as it is. */
function unfolded(v: unknown): string {
  if (Array.isArray(v)) return v.map(value).join("\n");
  return v !== null && typeof v === "object" ? JSON.stringify(v, null, 2) : value(v);
}

/** The trace of the element selected in the model: its sources, relationships and the run's calls about it. */
export function TracePanel({ elementId, runId }: { elementId: string | null; runId: string | null }) {
  const key = `${elementId}|${runId}`;
  const [result, setResult] = useState<{ key: string; trace?: Trace; error?: string } | null>(null);

  useEffect(() => {
    if (!elementId) return;
    let live = true;
    traceApi
      .element(elementId, runId)
      .then((trace) => live && setResult({ key, trace }))
      .catch((reason: Error) => live && setResult({ key, error: reason.message }));
    return () => {
      live = false;
    };
  }, [elementId, runId, key]);

  if (!elementId) return <div className="muted">Click an element in the model to see its trace.</div>;
  if (!result || result.key !== key) return <div className="muted">Loading trace…</div>;
  if (result.error || !result.trace) return <div className="logline error">{result.error}</div>;
  const { element, sources, relationships, calls } = result.trace;

  return (
    <div>
      <div className="logline phase">
        {element.element_type} · {element.name} <span className="faint mono">{element.identifier}</span>
      </div>
      <div className="logline phase">Sources ({sources.length})</div>
      {!sources.length && <div className="logline muted">No source graph node recorded.</div>}
      {sources.map((source) => {
        const properties = Object.entries(source.properties).filter(([k]) => k !== "id");
        const long = properties.filter(([, v]) => value(v).length > SHORT_VALUE);
        return (
          <div key={source.id}>
            <div className="logline">{[source.type ?? "?", source.name ?? "?", source.id].join(" · ")}</div>
            <div className="logline faint">
              {properties
                .filter(([, v]) => value(v).length <= SHORT_VALUE)
                .map(([k, v]) => `${k}: ${value(v)}`)
                .join(" · ")}
            </div>
            {long.map(([k, v]) => (
              <details key={k} className="faint">
                <summary className="logline">{`${k} (${sizeOf(v)})`}</summary>
                <div className="logline">{unfolded(v)}</div>
              </details>
            ))}
          </div>
        );
      })}
      <div className="logline phase">Relationships ({relationships.length})</div>
      {relationships.map((r) => (
        <div key={r.identifier} className="logline">
          {[`${r.direction === "out" ? "→" : "←"} ${r.type}`, `${r.other.name ?? r.other.identifier} (${r.other.type ?? "?"})`, ...(r.derived_from ? [r.derived_from] : [])].join(" · ")}
        </div>
      ))}
      <div className="logline phase">LLM calls ({calls.length})</div>
      {!runId && <div className="logline muted">Start a run here to link the LLM calls that decided on this element.</div>}
      {runId && !calls.length && <div className="logline muted">No call of this run mentions the element's sources.</div>}
      {calls.map((call) => (
        <CallLine key={call.call_id} runId={runId} data={call} lead={[call.role]} tail={[`LLM #${call.seq}`, `matched ${call.matched}`]} />
      ))}
    </div>
  );
}
