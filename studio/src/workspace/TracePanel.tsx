import { useEffect, useState } from "react";

import { trace as traceApi } from "../api/client";
import type { Trace } from "../api/types";
import { CallLine } from "./LlmCalls";

function value(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v);
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
      {sources.map((source) => (
        <div key={source.id}>
          <div className="logline">{[source.type ?? "?", source.name ?? "?", source.id].join(" · ")}</div>
          <div className="logline faint">
            {Object.entries(source.properties)
              .filter(([k]) => k !== "id")
              .map(([k, v]) => `${k}: ${value(v)}`)
              .join(" · ")}
          </div>
        </div>
      ))}
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
