import { useEffect, useState } from "react";

import { benchmarks } from "../api/client";
import type { ElementTrace as Trace, RunTraceCall } from "../api/types";
import type { Item } from "./inspect";

/** What one run says about the element: in the model under a name, or missing with its cause. */
function verdict(t: Trace): string {
  if (t.present) return `in the model as "${t.name}"${t.stage ? ` · candidate ${t.stage}` : ""}`;
  return `missing · ${t.cause ?? "no cause recorded"}`;
}

function Call({ call }: { call: RunTraceCall }) {
  const [open, setOpen] = useState<"prompt" | "answer" | null>(null);
  const toggle = (part: "prompt" | "answer") => setOpen((current) => (current === part ? null : part));
  const facts = [call.step ?? "no step", call.schema, call.model, call.temperature != null ? `temperature ${call.temperature}` : null, call.cache_hit ? "cache hit" : "cache miss"];
  return (
    <div className="logline">
      <span className="k">◆</span>
      {facts.filter(Boolean).join(" · ")}
      <button type="button" className="linkbtn" onClick={() => toggle("prompt")}>
        prompt ▸
      </button>
      <button type="button" className="linkbtn" onClick={() => toggle("answer")}>
        answer ▸
      </button>
      {open && <div className="expand">{open === "prompt" ? call.prompt : (call.response ?? call.error ?? "")}</div>}
    </div>
  );
}

/** Per run of the selected sessions, why the picked element is or is not in the model, with the calls that decided it (from the session files). */
export function ElementTrace({ sessions, repo, item }: { sessions: string[]; repo: string; item: Item }) {
  const source = Object.values(item.byRun)[0]?.source ?? "";
  const request = [sessions.join(","), repo, item.type, source].join("|");
  // The answer keeps the request it belongs to: an answer to an earlier pick is not shown
  const [answer, setAnswer] = useState<{ request: string; trace?: Trace[]; failed?: string } | null>(null);

  useEffect(() => {
    if (!source) return;
    let live = true;
    benchmarks
      .trace(sessions, repo, item.type, source)
      .then((trace) => live && setAnswer({ request, trace }))
      .catch((reason: Error) => live && setAnswer({ request, failed: reason.message }));
    return () => {
      live = false;
    };
  }, [request, sessions, repo, item.type, source]);

  const current = answer?.request === request ? answer : null;
  if (current?.failed) return <div className="logline error">{current.failed}</div>;
  const trace = current?.trace;
  if (!trace) return <div className="faint">Tracing…</div>;
  return (
    <div className="elementtrace" data-testid="element-trace">
      {trace.map((t) => (
        <div key={t.run}>
          <div>
            {t.run}: {verdict(t)}
          </div>
          {t.calls.map((call, i) => (
            <Call key={call.call_id ?? i} call={call} />
          ))}
        </div>
      ))}
    </div>
  );
}
